"""Shared subprocess safety helpers for local LLM CLIs."""

import subprocess
import threading


NO_WINDOW = 0x08000000


class CancellationHandle:
    """Thread-safe ownership of one provider process and its child tree."""

    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._cancelled = False

    @property
    def cancelled(self):
        with self._lock:
            return self._cancelled

    def attach(self, process):
        with self._lock:
            self._process = process
            cancelled = self._cancelled
        if cancelled:
            terminate_tree(process)
        return not cancelled

    def detach(self, process):
        with self._lock:
            if self._process is process:
                self._process = None

    def cancel(self):
        with self._lock:
            self._cancelled = True
            process = self._process
        if process is not None:
            terminate_tree(process)


def terminate_tree(process):
    """Best-effort termination of a CLI and every process it spawned."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True, creationflags=NO_WINDOW, timeout=10,
        )
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.communicate(timeout=5)
    except Exception:
        pass
