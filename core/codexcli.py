#!/usr/bin/env python3
"""Thin wrapper around the logged-in Codex CLI."""

import os
import shutil
import subprocess
import tempfile

import llmprocess


TIMEOUT = 120
_NO_WINDOW = llmprocess.NO_WINDOW
_AUTH_SIGNS = (
    "not logged in", "login required", "authentication_error",
    "failed to authenticate", "unauthorized", "api error: 401",
    "api error: 403", "invalid api key", "invalid_api_key",
)
_LIMIT_SIGNS = (
    "usage limit", "session limit", "rate limit", "rate_limit",
    "quota exceeded", "insufficient_quota",
)


def find_codex():
    """Find a native Codex executable without invoking a shell."""
    found = shutil.which("codex")
    if found:
        return found
    candidates = (
        r"~/AppData/Roaming/npm/codex.exe",
        r"~/AppData/Local/Programs/codex/codex.exe",
    )
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return None


def _error_from(blob):
    lowered = blob.lower()
    if any(sign in lowered for sign in _LIMIT_SIGNS):
        return "Codex usage/rate limit reached"
    if any(sign in lowered for sign in _AUTH_SIGNS):
        return "codex auth/API error"
    return None


def call_codex(prompt, timeout=None, model=None, allow_web=False, cancel_handle=None):
    """Return ``(text, error)`` from an ephemeral, read-only Codex invocation."""
    codex = find_codex()
    if not codex:
        return None, "codex CLI not found"

    with tempfile.TemporaryDirectory(prefix="smiteless-codex-") as workdir:
        output_path = os.path.join(workdir, "last-message.txt")
        args = [
            codex, "exec",
            "--ephemeral",
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--color", "never",
            "--cd", workdir,
            "--output-last-message", output_path,
        ]
        if allow_web:
            args += ["--config", 'web_search="live"']
        if model:
            args += ["--model", model]
        args.append("-")
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=workdir,
                creationflags=_NO_WINDOW,
            )
        except (FileNotFoundError, OSError) as exc:
            return None, f"couldn't launch codex ({exc})"

        if cancel_handle and not cancel_handle.attach(process):
            return None, "cancelled"

        try:
            stdout, stderr = process.communicate(
                input=prompt, timeout=(timeout or TIMEOUT),
            )
        except subprocess.TimeoutExpired:
            llmprocess.terminate_tree(process)
            return None, "timed out"
        finally:
            if cancel_handle:
                cancel_handle.detach(process)

        if cancel_handle and cancel_handle.cancelled:
            return None, "cancelled"

        stdout = (stdout or "").strip()
        stderr = (stderr or "").strip()
        known_error = _error_from(stdout + "\n" + stderr)
        if known_error:
            return None, known_error

        try:
            with open(output_path, encoding="utf-8", errors="replace") as handle:
                text = handle.read().strip()
        except OSError:
            text = ""

        known_error = _error_from(text)
        if known_error:
            return None, known_error
        if process.returncode != 0:
            detail = stderr or stdout
            return None, (detail[:200] or f"codex exited {process.returncode}")
        if not text:
            return None, "codex returned no text"
        return text, None
