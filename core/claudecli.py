#!/usr/bin/env python3
"""claudecli.py - thin wrapper around the logged-in `claude` CLI (no API key needed).

Shared by lolmatchup.py (per-matchup lane tips, web search) and lolcoach.py (the
standalone text coach). Runs the CLI from a neutral temp cwd so it does NOT load the
heavy C:\\ project memory (that was adding 30-60s), and hard-kills the whole process
tree on timeout.
"""
import os, shutil, subprocess, tempfile
import llmprocess

MODEL = "sonnet"      # quality model for the guide/tips
TIMEOUT = 120         # generous default; callers can override (e.g. web-search tips use 170)
# Never flash a console: from the windowed (frozen) app, spawning a console subprocess pops
# a blank "claude" terminal on the loading screen. CREATE_NO_WINDOW keeps it invisible.
_NO_WINDOW = llmprocess.NO_WINDOW
_AUTH_SIGNS = (
    "invalid authentication", "authentication_error", "failed to authenticate",
    "api error: 401", "api error: 403", "could not authenticate",
    "invalid x-api-key", "credit balance is too low", "overloaded_error",
)
_LIMIT_SIGNS = ("session limit", "usage limit", "rate limit", "rate_limit")


def find_claude():
    """Prefer the real claude.exe (lets us exec without a shell so the timeout can kill
    the process directly). Fall back to whatever `claude` resolves to on PATH."""
    exe = os.path.expanduser(
        r"~/AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe")
    if os.path.exists(exe):
        return exe
    return shutil.which("claude")


def call_claude(prompt, allow_tools=None, timeout=None, model=None, cancel_handle=None):
    """Return (text, error). Uses the logged-in claude CLI; no API key needed.
    Pass allow_tools="WebSearch,WebFetch" to let it pull up-to-date info."""
    claude = find_claude()
    if not claude:
        return None, "claude CLI not found"
    args = [claude, "-p", "--model", model or MODEL, "--strict-mcp-config"]
    if allow_tools:
        args += ["--allowedTools", allow_tools]
    try:
        p = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", cwd=tempfile.gettempdir(),
            creationflags=_NO_WINDOW,
        )
    except (FileNotFoundError, OSError) as e:
        return None, f"couldn't launch claude ({e})"
    if cancel_handle and not cancel_handle.attach(p):
        return None, "cancelled"
    try:
        out, err = p.communicate(input=prompt, timeout=(timeout or TIMEOUT))
    except subprocess.TimeoutExpired:
        llmprocess.terminate_tree(p)
        return None, "timed out"
    finally:
        if cancel_handle:
            cancel_handle.detach(p)
    if cancel_handle and cancel_handle.cancelled:
        return None, "cancelled"
    out = (out or "").strip()
    err = (err or "").strip()
    blob = (out + "\n" + err).lower()
    if any(sign in blob for sign in _LIMIT_SIGNS):
        return None, "Claude usage/session limit reached"
    # The CLI sometimes prints auth / credit / rate errors to STDOUT with a zero-ish exit code,
    # which would otherwise be returned as the "answer" (and then cached + shown as a tip). Catch
    # those explicitly so an error string never masquerades as output.
    for sign in _AUTH_SIGNS:
        if sign in blob:
            return None, "claude auth/API error"
    if p.returncode != 0:
        detail = err or out
        return None, (detail[:200] or f"claude exited {p.returncode}")
    if not out:
        return None, "claude returned no text"
    return out, None
