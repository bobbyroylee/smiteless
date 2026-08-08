#!/usr/bin/env python3
"""Local Whisper STT orchestration with isolated capture and model workers."""

import importlib.metadata
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import llmprocess
import smiteconfig
import smitewhispermodel


LOCALE_CULTURES = {"en": "en-US", "pt_BR": "pt-BR"}
BACKEND_LOCAL = "faster_whisper"
BACKEND_MODERN = BACKEND_LOCAL  # Compatibility name until Settings is rewritten in Phase 3E.
CAPTURE_MODE = "windows_default"
PROTOCOL_VERSION = 1
DEFAULT_CONFIDENCE = 0.45
DEFAULT_INITIAL_SILENCE_MS = 5000
DEFAULT_END_SILENCE_MS = 900
DEFAULT_BABBLE_MS = 3000
DEFAULT_TOTAL_MS = 15000
MAX_PROTOCOL_OUTPUT_BYTES = 65536
_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = _ROOT / "tools"
CUDA_COMPUTE_PREFERENCE = ("float16", "int8_float16")


class SttError(RuntimeError):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


ACTIONABLE_ERRORS = {
    "model_missing": "Whisper small is not installed. Download it once to use voice coaching.",
    "model_incomplete": "The Whisper model download is incomplete. Retry to resume it.",
    "model_hash_mismatch": "The Whisper model failed validation. Retry the trusted download.",
    "model_root_invalid": "The Whisper model folder is invalid. Retry the trusted download.",
    "whisper_runtime_missing": "The local Whisper runtime is unavailable. Reinstall Smiteless and retry.",
    "worker_unavailable": "The local Whisper worker could not start. Restart Smiteless and retry.",
    "worker_crash": "The local Whisper worker stopped unexpectedly. Retry the question.",
    "worker_shutdown_failed": "The Whisper worker did not close cleanly. Restart Smiteless.",
    "cuda_unavailable": "GPU NVIDIA was selected, but CUDA is unavailable. Install the supported CUDA runtime or select CPU.",
    "unsupported_compute_type": "This GPU does not support the required Whisper compute type. Select CPU.",
    "cuda_runtime_missing": "GPU NVIDIA needs the CUDA 12 cuBLAS and cuDNN 9 runtime. Install them or explicitly select CPU.",
    "incompatible_runtime": "The selected Whisper runtime is incompatible. Reinstall Smiteless or select CPU.",
    "model_memory_error": "There is not enough memory to load Whisper. Unload it, close other apps, or select CPU.",
    "microphone_unavailable": "No available Windows default microphone was found.",
    "permission_denied": "Microphone access is blocked in Windows privacy settings.",
    "default_microphone_no_signal": "The Windows default microphone produced no signal. Check Windows Sound settings and retry.",
    "no_speech": "No speech was detected. Check the Windows default microphone and retry.",
    "empty_transcript": "I did not hear a question. Press the hotkey and try once more.",
    "low_confidence": "I could not hear that clearly. Check the Windows default microphone and try again.",
    "timeout": "The voice operation timed out. Retry when the microphone is available.",
    "malformed_json": "The local Whisper worker returned an invalid response. Restart Smiteless.",
    "response_too_large": "The local Whisper worker returned too much data. Restart Smiteless.",
    "stale_worker_response": "An old Whisper worker replied after replacement. Retry the question.",
}


def actionable_error(code):
    return ACTIONABLE_ERRORS.get(
        str(code or ""), "Local speech recognition is unavailable: {error}")


def locale_to_culture(locale):
    key = str(locale or "").strip().replace("-", "_")
    if key.lower() == "pt_br":
        key = "pt_BR"
    elif key.lower() == "en":
        key = "en"
    if key not in LOCALE_CULTURES:
        raise ValueError("unsupported_locale")
    return LOCALE_CULTURES[key]


def _locale_key(locale):
    culture = locale_to_culture(locale)
    return "pt_BR" if culture == "pt-BR" else "en"


def _worker_command(module_name):
    """Return the isolated source or frozen command for one private JSON worker."""
    if getattr(sys, "frozen", False):
        commands = {
            "smitemicworker": "__stt-mic-worker",
            "smitewhisperworker": "__stt-whisper-worker",
        }
        command = commands.get(module_name)
        executable = Path(sys.executable).resolve()
        if not command or not executable.is_file():
            raise SttError("worker_unavailable")
        return [str(executable), command]
    path = (_TOOLS / f"{module_name}.py").resolve()
    if path.parent != _TOOLS.resolve() or not path.is_file():
        raise SttError("worker_unavailable")
    return [sys.executable, str(path)]


def runtime_configuration(settings=None, compute_probe=None):
    """Resolve one explicit STT configuration without loading a model or falling back."""
    values = settings or smiteconfig.load()
    device = smiteconfig.normalize_coach_stt_device(values.get("coach_stt_device"))
    policy = smiteconfig.normalize_coach_stt_load_policy(
        values.get("coach_stt_load_policy"))
    model = smiteconfig.normalize_coach_stt_model(values.get("coach_stt_model"))
    if device == "cpu":
        compute_type = "int8"
    else:
        if compute_probe is None:
            try:
                import ctranslate2
                if int(ctranslate2.get_cuda_device_count()) < 1:
                    raise SttError("cuda_unavailable")
                supported = set(ctranslate2.get_supported_compute_types("cuda"))
            except SttError:
                raise
            except (ImportError, OSError) as exc:
                raise SttError("whisper_runtime_missing") from exc
            except Exception as exc:
                raise SttError("cuda_unavailable") from exc
        else:
            try:
                supported = set(compute_probe())
            except SttError:
                raise
            except Exception as exc:
                raise SttError("cuda_unavailable") from exc
        compute_type = next(
            (candidate for candidate in CUDA_COMPUTE_PREFERENCE if candidate in supported), None)
        if compute_type is None:
            raise SttError("unsupported_compute_type")
    return {"device": device, "compute_type": compute_type,
            "load_policy": policy, "model": model}


def _run_protocol(command, requests, timeout, cancel_handle=None, popen_factory=None):
    """Run a JSON-lines worker and return validated response objects."""
    factory = popen_factory or subprocess.Popen
    process = None
    started = time.monotonic()
    encoded = "".join(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
                      for request in requests)
    try:
        process = factory(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=llmprocess.NO_WINDOW,
        )
        if cancel_handle is not None and not cancel_handle.attach(process):
            return [], "cancelled"
        try:
            stdout, stderr = process.communicate(input=encoded, timeout=max(0.1, float(timeout)))
        except subprocess.TimeoutExpired:
            llmprocess.terminate_tree(process)
            return [], "timeout"
        if cancel_handle is not None and cancel_handle.cancelled:
            return [], "cancelled"
        raw = str(stdout or "")
        if len(raw.encode("utf-8", errors="replace")) > MAX_PROTOCOL_OUTPUT_BYTES:
            return [], "response_too_large"
        responses = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                return [], "malformed_json"
            if not isinstance(value, dict) or value.get("version") != PROTOCOL_VERSION \
                    or not isinstance(value.get("ok"), bool):
                return [], "malformed_json"
            responses.append(value)
        if not responses:
            error = "worker_crash" if process.returncode else "no_output"
            return [], error
        if process.returncode not in (0, 2):
            return [], "worker_crash"
        return responses, None
    except OSError:
        return [], "worker_unavailable"
    finally:
        if cancel_handle is not None and process is not None:
            cancel_handle.detach(process)
        _ = started


def _package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _capture_readiness(popen_factory=None):
    try:
        command = _worker_command("smitemicworker")
    except SttError as exc:
        return {"ok": False, "error": exc.code, "capture_mode": CAPTURE_MODE,
                "available": False, "capture_started": False}
    responses, error = _run_protocol(
        command, [{"version": PROTOCOL_VERSION, "command": "readiness"}],
        timeout=8.0, popen_factory=popen_factory)
    if error:
        return {"ok": False, "error": error, "capture_mode": CAPTURE_MODE,
                "available": False, "capture_started": False}
    return responses[-1]


def readiness(popen_factory=None, capture_popen_factory=None, **_compatibility):
    """Report local runtime/model/default-microphone state without capture, load or download."""
    try:
        manifest = smitewhispermodel.load_manifest()
        paths = smitewhispermodel.paths_for_manifest(manifest)
        model = smitewhispermodel.status(manifest=manifest, paths=paths)
    except smitewhispermodel.ModelManagerError as exc:
        model = {"state": "unavailable", "ready": False, "error": exc.code,
                 "files_valid": 0, "files_total": 0}
    capture = _capture_readiness(capture_popen_factory or popen_factory)
    runtime = {
        "faster-whisper": _package_version("faster-whisper"),
        "ctranslate2": _package_version("ctranslate2"),
        "sounddevice": _package_version("sounddevice"),
    }
    runtime_ready = all(runtime.values())
    microphone = bool(capture.get("ok") and capture.get("available"))
    recognizer = bool(model.get("ready") and runtime_ready and microphone)
    if not runtime_ready:
        error = "whisper_runtime_missing"
    elif not model.get("ready"):
        error = model.get("error") or ("model_missing" if model.get("state") == "missing"
                                       else "model_invalid")
    elif not microphone:
        error = capture.get("error") or "microphone_unavailable"
    else:
        error = ""
    locales = {
        locale: {
            "culture": culture, "backend": BACKEND_LOCAL, "recognizer": recognizer,
            # Compatibility for the pre-3E Settings summary. TTS readiness remains owned by
            # smiteaudio and its localized test; this field no longer probes speech recognition.
            "voice": True, "local": True, "online_required": False, "error": error,
        }
        for locale, culture in LOCALE_CULTURES.items()
    }
    return {
        "ok": bool(runtime_ready or capture.get("ok")),
        "backend": BACKEND_LOCAL,
        "capture_mode": CAPTURE_MODE,
        "microphone": microphone,
        "default_microphone": {"active": microphone},
        "locales": locales,
        "model": model,
        "runtime": runtime,
        "capture": capture,
        "model_loaded": False,
        "download_started": False,
    }


def _new_audio_file(paths=None):
    import smitemicworker

    paths = paths or smitewhispermodel.resolve_paths()
    root = smitemicworker.audio_root(paths)
    root.mkdir(parents=True, exist_ok=True)
    smitemicworker.cleanup_stale_audio(root=root)
    descriptor, value = tempfile.mkstemp(
        prefix=smitemicworker.TEMP_PREFIX, suffix=smitemicworker.TEMP_SUFFIX, dir=root)
    os.close(descriptor)
    path = smitemicworker.validate_audio_path(value, root=root, require_exists=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path, root


def _capture(path, total_ms, initial_silence_ms, end_silence_ms,
             cancel_handle=None, popen_factory=None):
    try:
        command = _worker_command("smitemicworker")
    except SttError as exc:
        return {"ok": False, "error": exc.code}
    request = {
        "version": PROTOCOL_VERSION,
        "command": "capture",
        "audio_path": str(path),
        "initial_silence_ms": max(250, int(initial_silence_ms)),
        "end_silence_ms": max(150, int(end_silence_ms)),
        "total_ms": max(1000, min(20000, int(total_ms))),
    }
    responses, error = _run_protocol(
        command, [request], timeout=request["total_ms"] / 1000.0 + 8.0,
        cancel_handle=cancel_handle, popen_factory=popen_factory)
    if error:
        return {"ok": False, "error": error}
    return responses[-1]


def _transcribe(path, locale, model_path, cancel_handle=None, popen_factory=None,
                device="cpu", compute_type="int8", timeout=45.0):
    try:
        command = _worker_command("smitewhisperworker")
    except SttError as exc:
        return {"ok": False, "error": exc.code}
    requests = [
        {"version": PROTOCOL_VERSION, "id": "load", "command": "load",
         "model_path": str(model_path), "device": device, "compute_type": compute_type},
        {"version": PROTOCOL_VERSION, "id": "transcribe", "command": "transcribe",
         "audio_path": str(path), "locale": locale},
        {"version": PROTOCOL_VERSION, "id": "shutdown", "command": "shutdown"},
    ]
    responses, error = _run_protocol(
        command, requests, timeout=timeout, cancel_handle=cancel_handle,
        popen_factory=popen_factory)
    if error:
        return {"ok": False, "error": error}
    by_id = {row.get("id"): row for row in responses}
    load = by_id.get("load")
    transcription = by_id.get("transcribe")
    shutdown = by_id.get("shutdown")
    if not load or not load.get("ok"):
        return load or {"ok": False, "error": "no_output"}
    if not transcription:
        return {"ok": False, "error": "no_output"}
    if not shutdown or not shutdown.get("ok"):
        return {"ok": False, "error": "worker_shutdown_failed"}
    return transcription


class WhisperRuntime:
    """Coordinator-owned, generation-safe lifecycle for one local Whisper worker."""

    def __init__(self, popen_factory=None, command_factory=None, compute_probe=None,
                 clock=time.monotonic):
        self._popen_factory = popen_factory or subprocess.Popen
        self._command_factory = command_factory or (lambda: _worker_command("smitewhisperworker"))
        self._compute_probe = compute_probe
        self._clock = clock
        self._lock = threading.RLock()
        self._process = None
        self._responses = None
        self._generation = 0
        self._request_id = 0
        self._configuration = None
        self._model_loaded = False
        self._last_error = ""

    @staticmethod
    def _reader(stream, output):
        try:
            for line in stream:
                output.put(line)
        except Exception:
            pass
        finally:
            output.put(None)

    @staticmethod
    def _drain(stream):
        try:
            for _line in stream:
                pass
        except Exception:
            pass

    def _clear_locked(self, process, generation, error=""):
        if self._process is process and self._generation == generation:
            self._process = None
            self._responses = None
            self._model_loaded = False
            if error:
                self._last_error = error

    def _terminate_locked(self, process, generation, error=""):
        llmprocess.terminate_tree(process)
        self._clear_locked(process, generation, error)

    def _start_locked(self):
        if self._process is not None and self._process.poll() is None:
            return self._process, self._generation
        if self._process is not None:
            self._clear_locked(self._process, self._generation, "worker_crash")
        try:
            command = self._command_factory()
            process = self._popen_factory(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=llmprocess.NO_WINDOW)
        except (OSError, SttError):
            self._last_error = "worker_unavailable"
            return None, self._generation
        self._generation += 1
        self._process = process
        self._responses = queue.Queue()
        self._model_loaded = False
        threading.Thread(
            target=self._reader, args=(process.stdout, self._responses), daemon=True).start()
        threading.Thread(target=self._drain, args=(process.stderr,), daemon=True).start()
        return process, self._generation

    def _request_locked(self, request, timeout, cancel_handle=None):
        process = self._process
        generation = self._generation
        responses = self._responses
        if process is None or responses is None or process.poll() is not None:
            if process is not None:
                self._clear_locked(process, generation, "worker_crash")
            return {"ok": False, "error": "worker_crash"}
        self._request_id += 1
        request = dict(request)
        request.setdefault("version", PROTOCOL_VERSION)
        request.setdefault("id", f"g{generation}-{self._request_id}")
        attached = False
        try:
            if cancel_handle is not None:
                attached = cancel_handle.attach(process)
                if not attached:
                    self._terminate_locked(process, generation, "cancelled")
                    return {"ok": False, "error": "cancelled"}
            process.stdin.write(json.dumps(
                request, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
            deadline = self._clock() + max(0.1, float(timeout))
            while True:
                if cancel_handle is not None and cancel_handle.cancelled:
                    self._terminate_locked(process, generation, "cancelled")
                    return {"ok": False, "error": "cancelled"}
                remaining = deadline - self._clock()
                if remaining <= 0:
                    self._terminate_locked(process, generation, "timeout")
                    return {"ok": False, "error": "timeout"}
                try:
                    raw = responses.get(timeout=min(0.05, remaining))
                except queue.Empty:
                    if process.poll() is not None:
                        self._clear_locked(process, generation, "worker_crash")
                        return {"ok": False, "error": "worker_crash"}
                    continue
                if raw is None:
                    self._clear_locked(process, generation, "worker_crash")
                    return {"ok": False, "error": "worker_crash"}
                if len(str(raw).encode("utf-8", errors="replace")) > MAX_PROTOCOL_OUTPUT_BYTES:
                    self._terminate_locked(process, generation, "response_too_large")
                    return {"ok": False, "error": "response_too_large"}
                try:
                    value = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    self._terminate_locked(process, generation, "malformed_json")
                    return {"ok": False, "error": "malformed_json"}
                if not isinstance(value, dict) or value.get("version") != PROTOCOL_VERSION \
                        or not isinstance(value.get("ok"), bool):
                    self._terminate_locked(process, generation, "malformed_json")
                    return {"ok": False, "error": "malformed_json"}
                if value.get("id") != request["id"]:
                    self._terminate_locked(process, generation, "stale_worker_response")
                    return {"ok": False, "error": "stale_worker_response"}
                if self._process is not process or self._generation != generation:
                    return {"ok": False, "error": "stale_worker_response"}
                return value
        except (BrokenPipeError, OSError, ValueError):
            self._terminate_locked(process, generation, "worker_crash")
            return {"ok": False, "error": "worker_crash"}
        finally:
            if cancel_handle is not None and attached:
                cancel_handle.detach(process)

    def _stop_locked(self, graceful=True):
        process = self._process
        generation = self._generation
        if process is None:
            self._model_loaded = False
            return True
        clean = False
        if graceful and process.poll() is None:
            response = self._request_locked(
                {"command": "shutdown"}, timeout=5.0)
            clean = bool(response.get("ok"))
        if clean and process.poll() is None:
            try:
                process.wait(timeout=5)
            except Exception:
                clean = False
        if process.poll() is None:
            llmprocess.terminate_tree(process)
        else:
            try:
                process.wait(timeout=1)
            except Exception:
                pass
        self._clear_locked(process, generation, "" if clean else "worker_shutdown_failed")
        return clean

    def configure(self, settings=None):
        try:
            selected = runtime_configuration(settings, compute_probe=self._compute_probe)
        except SttError as exc:
            with self._lock:
                self._stop_locked()
                self._configuration = None
                self._last_error = exc.code
            return {"ok": False, "error": exc.code}
        signature = tuple(selected[key] for key in (
            "device", "compute_type", "load_policy", "model"))
        with self._lock:
            old_signature = None if self._configuration is None else tuple(
                self._configuration[key] for key in (
                    "device", "compute_type", "load_policy", "model"))
            if old_signature is not None and signature != old_signature:
                self._stop_locked()
            self._configuration = selected
            self._last_error = ""
        return {"ok": True, **selected}

    def transcribe(self, path, locale, model_path, settings=None, cancel_handle=None,
                   timeout=45.0):
        selected = self.configure(settings)
        if not selected.get("ok"):
            return selected
        if selected["load_policy"] == "per_question":
            with self._lock:
                self._stop_locked()
            return _transcribe(
                path, locale, model_path, cancel_handle=cancel_handle,
                popen_factory=self._popen_factory, device=selected["device"],
                compute_type=selected["compute_type"], timeout=timeout)
        with self._lock:
            process, _generation = self._start_locked()
            if process is None:
                return {"ok": False, "error": self._last_error or "worker_unavailable"}
            if not self._model_loaded:
                loaded = self._request_locked({
                    "command": "load", "model_path": str(model_path),
                    "device": selected["device"],
                    "compute_type": selected["compute_type"],
                }, timeout=timeout, cancel_handle=cancel_handle)
                if not loaded.get("ok"):
                    self._stop_locked(graceful=False)
                    return loaded
                self._model_loaded = True
            result = self._request_locked({
                "command": "transcribe", "audio_path": str(path), "locale": locale,
            }, timeout=timeout, cancel_handle=cancel_handle)
            if not result.get("ok") and result.get("error") in {
                    "worker_crash", "timeout", "cancelled", "malformed_json",
                    "response_too_large", "stale_worker_response",
                    "cuda_runtime_missing", "incompatible_runtime", "model_memory_error"}:
                self._stop_locked(graceful=False)
            return result

    def unload(self):
        with self._lock:
            had_worker = self._process is not None
            clean = self._stop_locked()
            return {"ok": clean, "unloaded": had_worker, "model_loaded": False,
                    "generation": self._generation,
                    **({} if clean else {"error": "worker_shutdown_failed"})}

    def status(self):
        with self._lock:
            alive = self._process is not None and self._process.poll() is None
            return {"ok": True, "worker_alive": alive,
                    "model_loaded": bool(alive and self._model_loaded),
                    "generation": self._generation,
                    "configuration": dict(self._configuration or {}),
                    "last_error": self._last_error}

    def close(self):
        with self._lock:
            self._stop_locked()


def recognize(locale, confidence_threshold=DEFAULT_CONFIDENCE,
              initial_silence_ms=DEFAULT_INITIAL_SILENCE_MS,
              end_silence_ms=DEFAULT_END_SILENCE_MS, babble_ms=DEFAULT_BABBLE_MS,
              total_ms=DEFAULT_TOTAL_MS, cancel_handle=None, popen_factory=None,
              helper_popen_factory=None, readiness_result=None, helper=None,
              capture_popen_factory=None, worker_popen_factory=None,
              runtime=None, settings=None):
    """Capture one local utterance, transcribe it offline, and delete its WAV on every path."""
    del confidence_threshold, babble_ms, readiness_result, helper
    locale_key = _locale_key(locale)
    try:
        manifest = smitewhispermodel.load_manifest()
        paths = smitewhispermodel.paths_for_manifest(manifest)
        model = smitewhispermodel.inspect_model(manifest=manifest, paths=paths)
    except smitewhispermodel.ModelManagerError as exc:
        return {"ok": False, "error": exc.code, "backend": BACKEND_LOCAL,
                "capture_mode": CAPTURE_MODE}
    if not model.get("ready"):
        error = model.get("error") or ("model_missing" if model.get("state") == "missing"
                                       else "model_invalid")
        return {"ok": False, "error": error, "backend": BACKEND_LOCAL,
                "capture_mode": CAPTURE_MODE, "model_loaded": False}
    if cancel_handle is not None and cancel_handle.cancelled:
        return {"ok": False, "error": "cancelled", "backend": BACKEND_LOCAL,
                "capture_mode": CAPTURE_MODE}
    try:
        selected = runtime_configuration(settings)
    except SttError as exc:
        return {"ok": False, "error": exc.code, "backend": BACKEND_LOCAL,
                "capture_mode": CAPTURE_MODE, "model_loaded": False}

    path = None
    audio_root = None
    try:
        path, audio_root = _new_audio_file(paths)
        capture = _capture(
            path, total_ms, initial_silence_ms, end_silence_ms,
            cancel_handle=cancel_handle,
            popen_factory=capture_popen_factory or popen_factory)
        if not capture.get("ok"):
            return {**capture, "backend": BACKEND_LOCAL, "capture_mode": CAPTURE_MODE,
                    "model_loaded": False}
        import smitemicworker
        try:
            audio = smitemicworker.validate_wav(path, root=audio_root, max_total_ms=total_ms)
        except smitemicworker.CaptureError as exc:
            return {"ok": False, "error": exc.code, "backend": BACKEND_LOCAL,
                    "capture_mode": CAPTURE_MODE, "model_loaded": False}
        if cancel_handle is not None and cancel_handle.cancelled:
            return {"ok": False, "error": "cancelled", "backend": BACKEND_LOCAL,
                    "capture_mode": CAPTURE_MODE, "model_loaded": False}
        if runtime is not None:
            result = runtime.transcribe(
                path, locale_key, paths.model_root, settings={
                    "coach_stt_device": selected["device"],
                    "coach_stt_load_policy": selected["load_policy"],
                    "coach_stt_model": selected["model"],
                },
                cancel_handle=cancel_handle)
        else:
            result = _transcribe(
                path, locale_key, paths.model_root, cancel_handle=cancel_handle,
                popen_factory=worker_popen_factory or helper_popen_factory,
                device=selected["device"], compute_type=selected["compute_type"])
        result.setdefault("backend", BACKEND_LOCAL)
        result.setdefault("capture_mode", CAPTURE_MODE)
        result.setdefault("culture", locale_to_culture(locale_key))
        result.setdefault("device", selected["device"])
        result.setdefault("compute_type", selected["compute_type"])
        result.setdefault("load_policy", selected["load_policy"])
        result["capture"] = {key: capture.get(key) for key in (
            "duration_ms", "sample_rate", "channels", "peak_int16", "rms_int16",
            "stopped_by_silence", "start_beep", "end_beep") if key in capture}
        result["audio"] = audio
        return result
    finally:
        if path is not None:
            try:
                import smitemicworker
                safe = smitemicworker.validate_audio_path(path, root=audio_root)
                safe.unlink(missing_ok=True)
            except (OSError, smitemicworker.CaptureError):
                pass
