#!/usr/bin/env python3
"""Authenticated, bounded loopback IPC for the persistent local coach."""

import hmac
import json
import os
import secrets
import socket
import socketserver


PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
ENDPOINT_FILE = os.path.expanduser("~/.claude/cache/smiteless_coach_endpoint.json")


class IpcError(RuntimeError):
    pass


def _atomic_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, separators=(",", ":"))
    os.replace(tmp, path)


def read_endpoint(path=ENDPOINT_FILE):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not data.get("port") or not data.get("token"):
            return None
        return data
    except Exception:
        return None


def remove_endpoint(path=ENDPOINT_FILE, expected_token=None):
    """Remove only our endpoint record; never inspect or terminate the advertised PID."""
    try:
        current = read_endpoint(path)
        if expected_token is not None and current and not hmac.compare_digest(
                str(current.get("token", "")), str(expected_token)):
            return False
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def request(message, timeout=5.0, endpoint_path=ENDPOINT_FILE, endpoint=None):
    endpoint = endpoint or read_endpoint(endpoint_path)
    if not endpoint:
        raise IpcError("coach is not running")
    body = dict(message or {})
    body["version"] = PROTOCOL_VERSION
    body["token"] = endpoint["token"]
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(encoded) > MAX_REQUEST_BYTES:
        raise IpcError("request is too large")
    try:
        with socket.create_connection(("127.0.0.1", int(endpoint["port"])), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(encoded)
            data = bytearray()
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_REQUEST_BYTES:
                    raise IpcError("response is too large")
        if not data:
            raise IpcError("coach did not respond")
        return json.loads(bytes(data).split(b"\n", 1)[0].decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise IpcError(f"coach IPC unavailable ({exc})") from exc


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
            return self._reply({"ok": False, "error": "request_too_large"})
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._reply({"ok": False, "error": "invalid_json"})
        if message.get("version") != PROTOCOL_VERSION:
            return self._reply({"ok": False, "error": "version_mismatch"})
        if not hmac.compare_digest(str(message.get("token", "")), self.server.token):
            return self._reply({"ok": False, "error": "unauthorized"})
        try:
            response = self.server.dispatch(message)
        except Exception:
            response = {"ok": False, "error": "internal_error"}
        self._reply(response)

    def _reply(self, value):
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.wfile.write(data[:MAX_REQUEST_BYTES - 1] + b"\n")


class CoachIpcServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, dispatch, endpoint_path=ENDPOINT_FILE, owner_pid=None):
        self.dispatch = dispatch
        self.token = secrets.token_urlsafe(32)
        self.endpoint_path = endpoint_path
        self.owner_pid = int(owner_pid) if owner_pid else None
        super().__init__(("127.0.0.1", 0), _Handler)

    def publish(self):
        value = {"pid": os.getpid(), "port": self.server_address[1],
                  "token": self.token, "version": PROTOCOL_VERSION}
        if self.owner_pid:
            value["owner_pid"] = self.owner_pid
        _atomic_json(self.endpoint_path, value)
        return value

    def server_close(self):
        remove_endpoint(self.endpoint_path, self.token)
        super().server_close()
