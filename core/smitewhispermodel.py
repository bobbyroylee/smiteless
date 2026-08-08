#!/usr/bin/env python3
"""Trusted shared-model cache for the local Smiteless Whisper runtime.

This module never imports or loads faster-whisper. It owns only the canonical
LocalAppData path, trusted manifest validation, cross-process download locking,
resumable staging, and atomic promotion of fully verified model files.
"""

import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


MANIFEST_SCHEMA_VERSION = 1
MODEL_NAME = "small"
MODEL_REPOSITORY = "Systran/faster-whisper-small"
MODEL_DIRECTORY = "whisper-small"
MODEL_FORMAT = "CTranslate2"
MODEL_FORMAT_VERSION = 1
MODEL_RUNTIME_VERSION = "4.8.1"
LOCK_STALE_SECONDS = 30 * 60
LOCK_FILE_NAME = ".whisper-small.lock"
STAGING_PREFIX = "whisper-small.partial-"
INVALID_PREFIX = "whisper-small.invalid-"
CHECKPOINT_NAME = ".smiteless-download.json"
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
CHECKPOINT_INTERVAL_BYTES = 8 * DOWNLOAD_CHUNK_BYTES
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_CACHE_DIRECTORY_RE = re.compile(
    r"^whisper-small(?:-[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?)?$")


class ModelManagerError(RuntimeError):
    """Typed model lifecycle failure safe to present without a local path."""

    def __init__(self, code, message=None):
        self.code = str(code)
        super().__init__(message or self.code)


class DownloadCancelled(ModelManagerError):
    def __init__(self):
        super().__init__("cancelled")


@dataclass(frozen=True)
class ModelPaths:
    local_appdata: Path
    app_root: Path
    models_root: Path
    model_root: Path
    lock_path: Path


class DownloadCancellation:
    """Thread-safe cancellation signal shared by Settings and the coordinator."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def raise_if_cancelled(self):
        if self.cancelled:
            raise DownloadCancelled()


def _normal_path(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _same_path(left, right):
    return _normal_path(left) == _normal_path(right)


def _is_within(path, root):
    try:
        return os.path.commonpath((_normal_path(path), _normal_path(root))) == _normal_path(root)
    except (OSError, ValueError):
        return False


def _windows_local_appdata():
    """Resolve LocalAppData through Windows, independent of a redirected environment."""
    if os.name != "nt":
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        # CSIDL_LOCAL_APPDATA. SHGetFolderPath remains available on supported Windows versions.
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, buffer)
        if result == 0 and buffer.value:
            return Path(buffer.value).resolve()
    except Exception:
        pass
    return None


def _validate_cache_directory(value):
    directory = str(value or "")
    if not _CACHE_DIRECTORY_RE.fullmatch(directory):
        raise ModelManagerError("manifest_cache_invalid")
    return directory


def resolve_paths(local_appdata=None, trusted_local_appdata=None,
                  model_directory=MODEL_DIRECTORY):
    """Return the one guarded cache layout used by source and frozen execution.

    Explicit roots exist only for deterministic fixtures. Normal execution compares the
    environment value with Windows' known-folder result so a redirected ``LOCALAPPDATA``
    cannot redirect promotion or later cleanup.
    """
    explicit = local_appdata is not None
    requested = local_appdata if explicit else os.environ.get("LOCALAPPDATA")
    if not requested:
        raise ModelManagerError("local_appdata_unavailable")
    trusted = trusted_local_appdata
    if trusted is None:
        trusted = requested if explicit else (_windows_local_appdata() or requested)
    requested_path = Path(requested).resolve()
    trusted_path = Path(trusted).resolve()
    if not _same_path(requested_path, trusted_path):
        raise ModelManagerError("local_appdata_redirected")
    app_root = (trusted_path / "Smiteless").resolve()
    models_root = (app_root / "models").resolve()
    model_directory = _validate_cache_directory(model_directory)
    model_root = (models_root / model_directory).resolve()
    if not _is_within(app_root, trusted_path) or not _is_within(models_root, app_root) \
            or model_root.parent != models_root or model_root.name != model_directory:
        raise ModelManagerError("unsafe_model_path")
    return ModelPaths(
        local_appdata=trusted_path,
        app_root=app_root,
        models_root=models_root,
        model_root=model_root,
        lock_path=models_root / LOCK_FILE_NAME,
    )


def paths_for_manifest(manifest=None, **kwargs):
    manifest = validate_manifest(manifest or load_manifest())
    return resolve_paths(
        model_directory=manifest["cache"]["directory"], **kwargs)


def model_root(manifest=None, **kwargs):
    return paths_for_manifest(manifest=manifest, **kwargs).model_root


def _validate_paths(paths):
    if not isinstance(paths, ModelPaths):
        raise ModelManagerError("unsafe_model_path")
    local_appdata = paths.local_appdata.resolve()
    app_root = paths.app_root.resolve()
    models_root = paths.models_root.resolve()
    model_path = paths.model_root.resolve()
    lock_path = paths.lock_path.resolve()
    if not _is_within(app_root, local_appdata) \
            or not _same_path(app_root, (local_appdata / "Smiteless").resolve()) \
            or not _is_within(models_root, app_root) \
            or not _same_path(models_root, (app_root / "models").resolve()) \
            or model_path.parent != models_root \
            or not _CACHE_DIRECTORY_RE.fullmatch(model_path.name) \
            or not _same_path(lock_path, models_root / LOCK_FILE_NAME):
        raise ModelManagerError("unsafe_model_path")
    return paths


def default_manifest_path():
    source_root = Path(__file__).resolve().parents[1]
    candidates = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "assets" / "whisper-small-manifest.json")
    candidates.append(source_root / "assets" / "whisper-small-manifest.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ModelManagerError("manifest_missing")


def _safe_relative_path(value):
    text = str(value or "")
    path = Path(text)
    if not text or path.is_absolute() or path.drive or any(part in ("", ".", "..")
                                                            for part in path.parts):
        raise ModelManagerError("manifest_unsafe_path")
    normalized = Path(*path.parts)
    if normalized.as_posix() != text.replace("\\", "/"):
        raise ModelManagerError("manifest_unsafe_path")
    return normalized


def validate_manifest(value):
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ModelManagerError("manifest_schema_invalid")
    model = value.get("model")
    model_format = value.get("format")
    cache = value.get("cache")
    files = value.get("files")
    if not isinstance(model, dict) or model.get("name") != MODEL_NAME \
            or model.get("multilingual") is not True \
            or model.get("repository") != MODEL_REPOSITORY \
            or not _REVISION_RE.fullmatch(str(model.get("revision") or "")):
        raise ModelManagerError("manifest_model_invalid")
    if "small.en" in json.dumps(model, sort_keys=True).lower():
        raise ModelManagerError("manifest_model_invalid")
    if not isinstance(model_format, dict) or model_format.get("name") != MODEL_FORMAT \
            or model_format.get("format_version") != MODEL_FORMAT_VERSION \
            or model_format.get("runtime_version") != MODEL_RUNTIME_VERSION:
        raise ModelManagerError("manifest_format_invalid")
    if not isinstance(cache, dict) \
            or not _CACHE_DIRECTORY_RE.fullmatch(str(cache.get("directory") or "")) \
            or not isinstance(cache.get("compatibility_key"), str) \
            or not cache.get("compatibility_key"):
        raise ModelManagerError("manifest_cache_invalid")
    if not isinstance(files, list) or not files:
        raise ModelManagerError("manifest_files_invalid")
    seen = set()
    normalized_files = []
    for row in files:
        if not isinstance(row, dict):
            raise ModelManagerError("manifest_files_invalid")
        relative = _safe_relative_path(row.get("path"))
        relative_text = relative.as_posix()
        size = row.get("size")
        digest = str(row.get("sha256") or "").lower()
        if relative_text in seen or not isinstance(size, int) or isinstance(size, bool) \
                or size < 0 or not _SHA256_RE.fullmatch(digest):
            raise ModelManagerError("manifest_files_invalid")
        seen.add(relative_text)
        normalized_files.append({"path": relative_text, "size": size, "sha256": digest})
    normalized = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "model": {
            "name": MODEL_NAME,
            "multilingual": True,
            "repository": MODEL_REPOSITORY,
            "revision": str(model["revision"]),
        },
        "format": {
            "name": MODEL_FORMAT,
            "format_version": MODEL_FORMAT_VERSION,
            "runtime_version": MODEL_RUNTIME_VERSION,
        },
        "cache": {
            "directory": str(cache["directory"]),
            "compatibility_key": cache["compatibility_key"],
        },
        "files": normalized_files,
    }
    return normalized


def load_manifest(path=None):
    try:
        with open(path or default_manifest_path(), encoding="utf-8") as handle:
            return validate_manifest(json.load(handle))
    except ModelManagerError:
        raise
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ModelManagerError("manifest_unreadable") from exc


def manifest_digest(manifest):
    normalized = validate_manifest(manifest)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_path(root, entry):
    root = Path(root).resolve()
    target = (root / _safe_relative_path(entry["path"])).resolve()
    if not _is_within(target, root) or target == root:
        raise ModelManagerError("unsafe_model_path")
    return target


def _validate_file(path, entry):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["size"]:
            return False
        return _sha256(path) == entry["sha256"]
    except OSError:
        return False


def inspect_model(directory=None, manifest=None, paths=None):
    manifest = validate_manifest(manifest or load_manifest())
    paths = _validate_paths(paths or paths_for_manifest(manifest))
    root = Path(directory or paths.model_root).resolve()
    if directory is None and not _same_path(root, paths.model_root):
        raise ModelManagerError("unsafe_model_path")
    if not root.exists():
        return {"state": "missing", "ready": False, "files_valid": 0,
                "files_total": len(manifest["files"])}
    if root.is_symlink() or not root.is_dir():
        return {"state": "invalid", "ready": False, "error": "model_root_invalid",
                "files_valid": 0, "files_total": len(manifest["files"])}
    valid = 0
    missing = 0
    invalid = 0
    for entry in manifest["files"]:
        item = _entry_path(root, entry)
        if not item.exists():
            missing += 1
        elif _validate_file(item, entry):
            valid += 1
        else:
            invalid += 1
    if invalid:
        state = "invalid"
        error = "model_hash_mismatch"
    elif missing:
        state = "partial"
        error = "model_incomplete"
    else:
        state = "ready"
        error = None
    result = {
        "state": state,
        "ready": state == "ready",
        "files_valid": valid,
        "files_total": len(manifest["files"]),
        "revision": manifest["model"]["revision"],
        "compatibility_key": manifest["cache"]["compatibility_key"],
    }
    if error:
        result["error"] = error
    return result


def validate_import_candidate(directory, manifest=None, paths=None):
    """Validate only the trusted allowlist for a future manual-import workflow.

    This deliberately performs no copy, promotion, deletion, or arbitrary directory import.
    """
    return inspect_model(
        directory=directory,
        manifest=manifest or load_manifest(),
        paths=paths or paths_for_manifest(manifest or load_manifest()),
    )


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if os.name == "nt":
        try:
            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                error = ctypes.get_last_error()
                return True if error == 5 else False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(process)
            return True if not ok else code.value == 259
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True


def lock_status(paths=None, clock=time.time, pid_probe=pid_alive, stale_seconds=LOCK_STALE_SECONDS):
    paths = _validate_paths(paths or paths_for_manifest(manifest))
    if not paths.lock_path.exists():
        return {"state": "unlocked"}
    value = _read_json(paths.lock_path)
    try:
        age = max(0.0, float(clock()) - float((value or {}).get("created_at")))
        owner_pid = int((value or {}).get("pid"))
        token = str((value or {}).get("token") or "")
    except (TypeError, ValueError):
        return {"state": "locked", "owner_known": False, "recoverable": False}
    active = pid_probe(owner_pid)
    stale = age >= float(stale_seconds)
    return {
        "state": "locked",
        "owner_known": bool(token),
        "owner_pid": owner_pid,
        "age_seconds": round(age, 3),
        "active": bool(active),
        "stale": stale,
        "recoverable": bool(token and stale and not active),
        "operation": str((value or {}).get("operation") or "unknown"),
    }


class ModelLock:
    """Exclusive-create lock that reclaims only an old lock from a proven-dead PID."""

    def __init__(self, paths=None, operation="download", clock=time.time, pid_probe=pid_alive,
                 stale_seconds=LOCK_STALE_SECONDS, owner_pid=None):
        self.paths = paths or resolve_paths()
        _validate_paths(self.paths)
        self.operation = str(operation or "download")[:32]
        self.clock = clock
        self.pid_probe = pid_probe
        self.stale_seconds = stale_seconds
        self.owner_pid = int(owner_pid if owner_pid is not None else os.getpid())
        self.token = secrets.token_hex(16)
        self.owned = False

    def _create(self):
        self.paths.models_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "pid": self.owner_pid,
            "created_at": float(self.clock()),
            "token": self.token,
            "operation": self.operation,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fd = os.open(self.paths.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)
        self.owned = True
        return True

    def acquire(self):
        try:
            return self._create()
        except FileExistsError:
            pass
        before = _read_json(self.paths.lock_path)
        state = lock_status(self.paths, self.clock, self.pid_probe, self.stale_seconds)
        if not state.get("recoverable") or not before:
            return False
        # Re-read immediately before unlinking so a replacement generation is never removed.
        after = _read_json(self.paths.lock_path)
        if after != before or after.get("token") != before.get("token"):
            return False
        try:
            self.paths.lock_path.unlink()
        except OSError:
            return False
        try:
            return self._create()
        except FileExistsError:
            return False

    def release(self):
        if not self.owned:
            return False
        current = _read_json(self.paths.lock_path)
        if not current or current.get("token") != self.token:
            self.owned = False
            return False
        try:
            self.paths.lock_path.unlink()
            released = True
        except OSError:
            released = False
        self.owned = False
        return released

    def __enter__(self):
        if not self.acquire():
            raise ModelManagerError("model_locked")
        return self

    def __exit__(self, *_args):
        self.release()


def status(manifest=None, paths=None):
    manifest = validate_manifest(manifest or load_manifest())
    paths = _validate_paths(paths or paths_for_manifest(manifest))
    result = inspect_model(manifest=manifest, paths=paths)
    lock = lock_status(paths)
    result["lock"] = lock
    staging = _matching_staging(paths, manifest)
    checkpoint = _read_json(staging / CHECKPOINT_NAME) if staging else None
    if checkpoint:
        downloaded = max(0, int(checkpoint.get("bytes_downloaded") or 0))
        total = max(0, int(checkpoint.get("bytes_total") or 0))
        result["download"] = {
            "state": str(checkpoint.get("state") or "unknown")[:24],
            "bytes_downloaded": min(downloaded, total) if total else downloaded,
            "bytes_total": total,
            "percent": round((min(downloaded, total) / total * 100.0) if total else 0.0, 2),
            "resumable": True,
            **({"error": str(checkpoint.get("error"))[:48]}
               if checkpoint.get("error") else {}),
        }
    result["download_started"] = bool(
        lock.get("state") == "locked" and lock.get("active")
        and lock.get("operation") == "download")
    result["model_loaded"] = False
    return result


def _safe_staging(path, paths, prefix=STAGING_PREFIX):
    original = Path(path)
    if original.is_symlink():
        return False
    path = original.resolve()
    return path.parent == paths.models_root and path.name.startswith(prefix)


def _remove_staging(path, paths, prefix=STAGING_PREFIX):
    original = Path(path)
    if not _safe_staging(original, paths, prefix):
        raise ModelManagerError("unsafe_cleanup_target")
    path = original.resolve()
    if path.exists():
        shutil.rmtree(path)


def _checkpoint_value(manifest, state, completed, bytes_downloaded, error=None, now=None):
    value = {
        "schema_version": 1,
        "manifest_sha256": manifest_digest(manifest),
        "compatibility_key": manifest["cache"]["compatibility_key"],
        "revision": manifest["model"]["revision"],
        "state": state,
        "completed": sorted(set(completed)),
        "bytes_downloaded": int(bytes_downloaded),
        "bytes_total": sum(row["size"] for row in manifest["files"]),
        "updated_at": float(time.time() if now is None else now),
    }
    if error:
        value["error"] = str(error)
    return value


def _matching_staging(paths, manifest):
    if not paths.models_root.is_dir():
        return None
    wanted = manifest_digest(manifest)
    candidates = []
    for item in paths.models_root.iterdir():
        if not _safe_staging(item, paths) or not item.is_dir():
            continue
        checkpoint = _read_json(item / CHECKPOINT_NAME)
        if checkpoint and checkpoint.get("manifest_sha256") == wanted:
            try:
                candidates.append((float(checkpoint.get("updated_at") or 0), item))
            except (TypeError, ValueError):
                pass
    return max(candidates, default=(None, None))[1]


def _new_staging(paths, manifest):
    paths.models_root.mkdir(parents=True, exist_ok=True)
    for _attempt in range(10):
        staging = paths.models_root / f"{STAGING_PREFIX}{secrets.token_hex(8)}"
        try:
            staging.mkdir()
            _atomic_json(staging / CHECKPOINT_NAME,
                         _checkpoint_value(manifest, "starting", [], 0))
            return staging
        except FileExistsError:
            continue
    raise ModelManagerError("staging_create_failed")


def _progress_value(manifest, completed_bytes, current_bytes, state="downloading", file_name=None):
    total = sum(row["size"] for row in manifest["files"])
    downloaded = min(total, max(0, int(completed_bytes) + int(current_bytes)))
    value = {
        "state": state,
        "bytes_downloaded": downloaded,
        "bytes_total": total,
        "percent": round((downloaded / total * 100.0) if total else 100.0, 2),
    }
    if file_name:
        value["file"] = file_name
    return value


def _default_fetcher(manifest, entry, partial_path, offset, cancellation, on_chunk):
    repository = urllib.parse.quote(manifest["model"]["repository"], safe="/")
    revision = urllib.parse.quote(manifest["model"]["revision"], safe="")
    relative = "/".join(urllib.parse.quote(part, safe="")
                        for part in Path(entry["path"]).parts)
    url = f"https://huggingface.co/{repository}/resolve/{revision}/{relative}"
    headers = {"User-Agent": "Smiteless model manager"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset == entry["size"]:
            return
        raise ModelManagerError("download_http_error") from exc
    with response:
        append = bool(offset and getattr(response, "status", None) == 206)
        mode = "ab" if append else "wb"
        written = offset if append else 0
        with open(partial_path, mode) as handle:
            while True:
                cancellation.raise_if_cancelled()
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                on_chunk(written)
            handle.flush()
            os.fsync(handle.fileno())


def _promote(staging, paths, manifest):
    if not inspect_model(staging, manifest, paths).get("ready"):
        raise ModelManagerError("staging_validation_failed")
    checkpoint = staging / CHECKPOINT_NAME
    checkpoint.unlink(missing_ok=True)
    target = paths.model_root
    backup = None
    if target.exists():
        current = inspect_model(target, manifest, paths)
        if current.get("ready"):
            return False
        backup = paths.models_root / f"{INVALID_PREFIX}{secrets.token_hex(8)}"
        os.replace(target, backup)
    try:
        os.replace(staging, target)
        if not inspect_model(target, manifest, paths).get("ready"):
            raise ModelManagerError("promotion_validation_failed")
    except Exception:
        if target.exists() and _same_path(target.parent, paths.models_root):
            failed = paths.models_root / f"{INVALID_PREFIX}{secrets.token_hex(8)}"
            try:
                os.replace(target, failed)
            except OSError:
                pass
        if backup and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup and backup.exists():
        _remove_staging(backup, paths, prefix=INVALID_PREFIX)
    return True


def download_model(manifest=None, paths=None, fetcher=None, cancellation=None,
                   progress=None, lock_options=None):
    """Acquire, resume, validate and promote the pinned model without loading it.

    ``fetcher`` is injectable for deterministic fixtures. Its contract is
    ``(manifest, entry, partial_path, offset, cancellation, on_chunk)``.
    """
    manifest = validate_manifest(manifest or load_manifest())
    paths = _validate_paths(paths or paths_for_manifest(manifest))
    cancellation = cancellation or DownloadCancellation()
    fetcher = fetcher or _default_fetcher
    ready = inspect_model(manifest=manifest, paths=paths)
    if ready.get("ready"):
        return {"ok": True, "downloaded": False, "resumed": False, "model": ready}
    lock = ModelLock(paths=paths, **(lock_options or {}))
    if not lock.acquire():
        return {"ok": False, "error": "model_locked", "lock": lock_status(paths)}
    staging = None
    resumed = False
    try:
        ready = inspect_model(manifest=manifest, paths=paths)
        if ready.get("ready"):
            return {"ok": True, "downloaded": False, "resumed": False, "model": ready}
        staging = _matching_staging(paths, manifest)
        resumed = staging is not None
        if staging is None:
            staging = _new_staging(paths, manifest)
        completed = []
        completed_bytes = 0
        for entry in manifest["files"]:
            cancellation.raise_if_cancelled()
            final_path = _entry_path(staging, entry)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if _validate_file(final_path, entry):
                completed.append(entry["path"])
                completed_bytes += entry["size"]
                continue
            if final_path.exists():
                final_path.unlink()
            partial = final_path.with_name(final_path.name + ".partial")
            try:
                offset = partial.stat().st_size if partial.is_file() else 0
            except OSError:
                offset = 0
            if offset > entry["size"] or partial.is_symlink():
                partial.unlink(missing_ok=True)
                offset = 0
            elif offset == entry["size"] and not _validate_file(partial, entry):
                # A complete but invalid partial cannot be resumed. Restart only this file.
                partial.unlink(missing_ok=True)
                offset = 0
            checkpoint_mark = [offset]

            def on_chunk(current, _entry=entry):
                current = max(0, int(current))
                if current >= _entry["size"] \
                        or current - checkpoint_mark[0] >= CHECKPOINT_INTERVAL_BYTES:
                    _atomic_json(staging / CHECKPOINT_NAME, _checkpoint_value(
                        manifest, "downloading", completed, completed_bytes + current))
                    checkpoint_mark[0] = current
                if progress:
                    progress(_progress_value(
                        manifest, completed_bytes, current, file_name=_entry["path"]))

            fetcher(manifest, entry, partial, offset, cancellation, on_chunk)
            cancellation.raise_if_cancelled()
            if not _validate_file(partial, entry):
                raise ModelManagerError("download_file_invalid")
            os.replace(partial, final_path)
            completed.append(entry["path"])
            completed_bytes += entry["size"]
            _atomic_json(staging / CHECKPOINT_NAME, _checkpoint_value(
                manifest, "downloading", completed, completed_bytes))
            if progress:
                progress(_progress_value(
                    manifest, completed_bytes, 0, file_name=entry["path"]))
        if not inspect_model(staging, manifest, paths).get("ready"):
            raise ModelManagerError("staging_validation_failed")
        promoted = _promote(staging, paths, manifest)
        staging = None
        result = inspect_model(manifest=manifest, paths=paths)
        if progress:
            progress(_progress_value(
                manifest, sum(row["size"] for row in manifest["files"]), 0,
                state="ready"))
        return {"ok": True, "downloaded": bool(promoted), "resumed": resumed,
                "model": result}
    except DownloadCancelled:
        if staging and staging.exists():
            checkpoint = _read_json(staging / CHECKPOINT_NAME) or {}
            _atomic_json(staging / CHECKPOINT_NAME, _checkpoint_value(
                manifest, "cancelled", checkpoint.get("completed") or [],
                checkpoint.get("bytes_downloaded") or 0, error="cancelled"))
        return {"ok": False, "error": "cancelled", "resumable": bool(staging)}
    except ModelManagerError as exc:
        if staging and staging.exists():
            checkpoint = _read_json(staging / CHECKPOINT_NAME) or {}
            _atomic_json(staging / CHECKPOINT_NAME, _checkpoint_value(
                manifest, "failed", checkpoint.get("completed") or [],
                checkpoint.get("bytes_downloaded") or 0, error=exc.code))
        return {"ok": False, "error": exc.code, "resumable": bool(staging)}
    except Exception:
        if staging and staging.exists():
            checkpoint = _read_json(staging / CHECKPOINT_NAME) or {}
            _atomic_json(staging / CHECKPOINT_NAME, _checkpoint_value(
                manifest, "failed", checkpoint.get("completed") or [],
                checkpoint.get("bytes_downloaded") or 0, error="download_failed"))
        return {"ok": False, "error": "download_failed", "resumable": bool(staging)}
    finally:
        lock.release()


def cancel_download(cancellation):
    if not isinstance(cancellation, DownloadCancellation):
        raise ModelManagerError("invalid_cancellation_handle")
    cancellation.cancel()
    return {"ok": True, "cancelled": True}
