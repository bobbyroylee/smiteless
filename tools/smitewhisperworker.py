#!/usr/bin/env python3
"""Persistent local faster-whisper worker using a versioned JSON-lines protocol."""

import gc
import importlib.metadata
import json
import platform
import struct
import sys
import time
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
for _folder in ("core", "tools"):
    _path = str(_ROOT / _folder)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import smitemicworker
import smitewhispermodel


for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 16384
MAX_TRANSCRIPT_CHARACTERS = 8192
LOCALE_LANGUAGES = {"en": "en", "pt_BR": "pt"}
ALLOWED_COMPUTE = {"cpu": {"int8"}, "cuda": {"float16", "int8_float16"}}


class WorkerError(RuntimeError):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


def _runtime_error(exc):
    detail = f"{type(exc).__name__}: {exc}".lower()
    if "cublas64_12.dll" in detail or ("cudnn" in detail and "64_9.dll" in detail):
        return "cuda_runtime_missing"
    if "out of memory" in detail:
        return "model_memory_error"
    return "incompatible_runtime"


def _package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _runtime_readiness():
    """Import the native runtime without loading a model or initializing CUDA inference."""
    try:
        import ctranslate2
        return {
            "ok": True,
            "architecture": platform.machine() or "unknown",
            "pointer_bits": struct.calcsize("P") * 8,
            "cpu_compute_types": sorted(ctranslate2.get_supported_compute_types("cpu")),
            "cuda_device_count": int(ctranslate2.get_cuda_device_count()),
        }
    except (ImportError, OSError) as exc:
        return {"ok": False, "error": "whisper_runtime_missing",
                "detail": type(exc).__name__}
    except Exception as exc:
        return {"ok": False, "error": "incompatible_runtime",
                "detail": type(exc).__name__}


class WhisperWorker:
    def __init__(self, paths=None, manifest=None, model_factory=None, audio_root=None):
        self.manifest = manifest or smitewhispermodel.load_manifest()
        self.paths = paths or smitewhispermodel.paths_for_manifest(self.manifest)
        self.model_factory = model_factory
        self.allowed_audio_root = Path(audio_root or smitemicworker.audio_root(self.paths)).resolve()
        self.model = None
        self.device = None
        self.compute_type = None
        self.loaded_at = None
        self.shutdown_requested = False

    def _base(self):
        return {"version": PROTOCOL_VERSION}

    def _validate_model_path(self, value):
        if not value:
            raise WorkerError("invalid_model_path")
        path = Path(value).resolve()
        if path != self.paths.model_root.resolve():
            raise WorkerError("invalid_model_path")
        state = smitewhispermodel.inspect_model(manifest=self.manifest, paths=self.paths)
        if not state.get("ready"):
            raise WorkerError(state.get("error") or "model_missing")
        return path

    @staticmethod
    def _validate_runtime(device, compute_type):
        device = str(device or "")
        compute_type = str(compute_type or "")
        if device not in ALLOWED_COMPUTE or compute_type not in ALLOWED_COMPUTE[device]:
            raise WorkerError("unsupported_compute_type")
        return device, compute_type

    def readiness(self):
        state = smitewhispermodel.inspect_model(manifest=self.manifest, paths=self.paths)
        runtime = _runtime_readiness()
        return {**self._base(), "ok": runtime["ok"], "command": "readiness", "model": state,
                "packages": {"faster-whisper": _package_version("faster-whisper"),
                             "ctranslate2": _package_version("ctranslate2")},
                "runtime": runtime,
                "model_loaded": self.model is not None, "download_started": False}

    def status(self):
        return {**self._base(), "ok": True, "command": "status",
                "model_loaded": self.model is not None, "device": self.device,
                "compute_type": self.compute_type}

    def load(self, request):
        model_path = self._validate_model_path(request.get("model_path"))
        device, compute_type = self._validate_runtime(
            request.get("device"), request.get("compute_type"))
        if self.model is not None:
            if (device, compute_type) != (self.device, self.compute_type):
                raise WorkerError("worker_configuration_mismatch")
            return {**self.status(), "command": "load", "reused": True}
        factory = self.model_factory
        if factory is None:
            try:
                from faster_whisper import WhisperModel
            except (ImportError, OSError) as exc:
                raise WorkerError("whisper_runtime_missing") from exc
            factory = WhisperModel
        try:
            self.model = factory(str(model_path), device=device, compute_type=compute_type,
                                 local_files_only=True)
        except Exception as exc:
            raise WorkerError(_runtime_error(exc)) from exc
        self.device, self.compute_type = device, compute_type
        self.loaded_at = time.monotonic()
        return {**self._base(), "ok": True, "command": "load", "model_loaded": True,
                "device": device, "compute_type": compute_type, "reused": False,
                "cpu_fallback": False}

    def transcribe(self, request):
        if self.model is None:
            raise WorkerError("model_not_loaded")
        locale = str(request.get("locale") or "")
        if locale not in LOCALE_LANGUAGES:
            raise WorkerError("unsupported_locale")
        try:
            audio_path = smitemicworker.validate_audio_path(
                request.get("audio_path"), root=self.allowed_audio_root, require_exists=True)
            audio = smitemicworker.validate_wav(audio_path, root=self.allowed_audio_root)
        except smitemicworker.CaptureError as exc:
            raise WorkerError(exc.code) from exc
        started = time.monotonic()
        try:
            segments, info = self.model.transcribe(
                str(audio_path), language=LOCALE_LANGUAGES[locale], beam_size=5,
                condition_on_previous_text=False)
            rows = list(segments)
        except Exception as exc:
            raise WorkerError(_runtime_error(exc)) from exc
        text = " ".join(str(getattr(row, "text", "")).strip() for row in rows).strip()
        text = " ".join(text.split())[:MAX_TRANSCRIPT_CHARACTERS]
        if not text:
            raise WorkerError("empty_transcript")
        language_probability = float(getattr(info, "language_probability", 0.0) or 0.0)
        no_speech = [float(getattr(row, "no_speech_prob", 0.0) or 0.0) for row in rows]
        if language_probability and language_probability < 0.20 \
                or no_speech and min(no_speech) >= 0.80:
            raise WorkerError("low_confidence")
        return {**self._base(), "ok": True, "command": "transcribe", "text": text,
                "locale": locale, "language": str(getattr(info, "language", "") or ""),
                "language_probability": round(language_probability, 6),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "audio_duration_ms": audio["duration_ms"], "cpu_fallback": False}

    def unload(self):
        was_loaded = self.model is not None
        self.model = None
        self.device = None
        self.compute_type = None
        self.loaded_at = None
        gc.collect()
        return {**self._base(), "ok": True, "command": "unload",
                "model_loaded": False, "unloaded": was_loaded}

    def handle(self, request):
        if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
            return {**self._base(), "ok": False, "error": "protocol_mismatch"}
        command = request.get("command")
        try:
            if command == "readiness":
                response = self.readiness()
            elif command == "status":
                response = self.status()
            elif command == "load":
                response = self.load(request)
            elif command == "transcribe":
                response = self.transcribe(request)
            elif command == "unload":
                response = self.unload()
            elif command == "shutdown":
                self.unload()
                self.shutdown_requested = True
                response = {**self._base(), "ok": True, "command": "shutdown",
                            "model_loaded": False}
            else:
                response = {**self._base(), "ok": False, "error": "unknown_command"}
        except WorkerError as exc:
            response = {**self._base(), "ok": False, "error": exc.code,
                        "command": command}
        except Exception as exc:
            print(f"worker_error:{type(exc).__name__}", file=sys.stderr)
            response = {**self._base(), "ok": False, "error": "worker_failed",
                        "command": command}
        if "id" in request:
            response["id"] = request["id"]
        return response


def decode_request(raw):
    if len(raw) > MAX_REQUEST_BYTES:
        raise WorkerError("request_too_large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WorkerError("malformed_json") from exc
    if not isinstance(value, dict):
        raise WorkerError("malformed_json")
    return value


def main():
    try:
        worker = WhisperWorker()
    except (smitewhispermodel.ModelManagerError, smitemicworker.CaptureError) as exc:
        print(json.dumps({"version": PROTOCOL_VERSION, "ok": False,
                          "error": getattr(exc, "code", "worker_start_failed")},
                         separators=(",", ":")), flush=True)
        return 2
    for raw in sys.stdin.buffer:
        try:
            request = decode_request(raw)
            response = worker.handle(request)
        except WorkerError as exc:
            response = {"version": PROTOCOL_VERSION, "ok": False, "error": exc.code}
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
        if worker.shutdown_requested:
            break
    worker.unload()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
