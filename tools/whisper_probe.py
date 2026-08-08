#!/usr/bin/env python3
"""Isolated faster-whisper hardware and model probe for active Phase 3A.

Readiness is deliberately non-loading and non-downloading. Model acquisition is an
explicit command, pinned to one upstream revision, and live microphone capture uses
only the Windows default input device.
"""

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path


MODEL_NAME = "small"
MODEL_ID = "Systran/faster-whisper-small"
MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
MODEL_FORMAT = "CTranslate2"
REQUIRED_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
PACKAGE_NAMES = (
    "faster-whisper",
    "ctranslate2",
    "sounddevice",
    "huggingface-hub",
    "tokenizers",
    "onnxruntime",
    "av",
    "numpy",
)
LOCALE_LANGUAGES = {"en": "en", "pt_BR": "pt"}


class ProbeError(RuntimeError):
    """An actionable probe failure."""


def actionable_runtime_error(exc):
    detail = f"{type(exc).__name__}: {exc}"
    lowered = detail.lower()
    if "cublas64_12.dll" in lowered:
        return ("cuda_runtime_missing: cublas64_12.dll is unavailable; install the CUDA 12 "
                "cuBLAS runtime and cuDNN 9, then retry the explicit GPU selection")
    if "cudnn" in lowered and "64_9.dll" in lowered:
        return ("cuda_runtime_missing: cuDNN 9 DLLs are unavailable; install cuDNN 9 for "
                "CUDA 12, then retry the explicit GPU selection")
    return detail


def _json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _local_appdata():
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise ProbeError("LOCALAPPDATA is unavailable; the shared model root cannot be resolved")
    return Path(value).resolve()


def model_root():
    """Return the one source/frozen shared cache path locked by the plan."""
    return _local_appdata() / "Smiteless" / "models" / "whisper-small"


def validate_model_name(value):
    normalized = str(value or "").strip().lower()
    if normalized != MODEL_NAME:
        raise ProbeError("only the multilingual 'small' model is permitted")
    return MODEL_NAME


def _package_versions():
    values = {}
    for name in PACKAGE_NAMES:
        try:
            values[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            values[name] = None
    return values


def _model_status(path=None):
    path = Path(path or model_root()).resolve()
    present = [name for name in REQUIRED_FILES if (path / name).is_file()]
    if not path.exists():
        state = "missing"
    elif len(present) != len(REQUIRED_FILES):
        state = "partial"
    else:
        state = "present_unverified"
    return {
        "state": state,
        "path": str(path),
        "required_files": list(REQUIRED_FILES),
        "present_files": present,
    }


def _default_microphone():
    try:
        import sounddevice as sd

        index = int(sd.default.device[0])
        if index < 0:
            return {"available": False, "error": "no_default_input"}
        info = sd.query_devices(index, "input")
        return {
            "available": bool(info.get("max_input_channels", 0)),
            "name": str(info.get("name") or "Windows default input"),
            "max_input_channels": int(info.get("max_input_channels", 0)),
            "default_samplerate": float(info.get("default_samplerate", 0)),
        }
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def readiness(model_path=None):
    """Inspect runtime/hardware without downloading or loading model weights."""
    packages = _package_versions()
    result = {
        "ok": False,
        "command": "readiness",
        "python": sys.version.split()[0],
        "architecture": platform.machine(),
        "platform": platform.platform(),
        "packages": packages,
        "model": {
            "name": MODEL_NAME,
            "multilingual": True,
            "repository": MODEL_ID,
            "revision": MODEL_REVISION,
            "format": MODEL_FORMAT,
            **_model_status(model_path),
        },
        "microphone": _default_microphone(),
        "cpu": {"available": False, "compute_types": [], "selected": "int8"},
        "cuda": {"device_count": 0, "compute_types": [], "usable": False},
        "model_loaded": False,
        "download_started": False,
    }
    if not packages.get("ctranslate2"):
        result["error"] = "ctranslate2_not_installed"
        return result
    try:
        import ctranslate2

        cpu_types = sorted(ctranslate2.get_supported_compute_types("cpu"))
        result["cpu"] = {
            "available": "int8" in cpu_types,
            "compute_types": cpu_types,
            "selected": "int8",
        }
        count = int(ctranslate2.get_cuda_device_count())
        cuda_types = []
        cuda_error = None
        if count:
            try:
                cuda_types = sorted(ctranslate2.get_supported_compute_types("cuda", 0))
            except Exception as exc:
                cuda_error = f"{type(exc).__name__}: {exc}"
        candidates = [kind for kind in ("float16", "int8_float16") if kind in cuda_types]
        result["cuda"] = {
            "device_count": count,
            "compute_types": cuda_types,
            "candidate_compute_types": candidates,
            "reported_compatible": bool(count and candidates and not cuda_error),
            "runtime_verified": None,
            "usable": None,
            "error": cuda_error,
        }
        result["ok"] = result["cpu"]["available"]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_manifest(path=None):
    root = Path(path or model_root()).resolve()
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ProbeError("model is incomplete; missing: " + ", ".join(missing))
    files = []
    for name in REQUIRED_FILES:
        item = root / name
        files.append({"path": name, "size": item.stat().st_size, "sha256": _sha256(item)})
    return {
        "model": MODEL_NAME,
        "multilingual": True,
        "repository": MODEL_ID,
        "revision": MODEL_REVISION,
        "format": MODEL_FORMAT,
        "root": str(root),
        "files": files,
    }


def download_model():
    """Download the pinned snapshot into the shared cache through a sibling staging dir."""
    from huggingface_hub import snapshot_download

    target = model_root()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        manifest = model_manifest(target)
        return {"ok": True, "downloaded": False, "manifest": manifest}
    staging = target.parent / f"whisper-small.probe-{os.getpid()}"
    if staging.exists():
        raise ProbeError(f"probe staging path already exists: {staging}")
    try:
        snapshot_download(
            MODEL_ID,
            revision=MODEL_REVISION,
            local_dir=str(staging),
            allow_patterns=list(REQUIRED_FILES),
        )
        manifest = model_manifest(staging)
        os.replace(staging, target)
        manifest["root"] = str(target)
        return {"ok": True, "downloaded": True, "manifest": manifest}
    except Exception:
        if staging.exists() and staging.parent == target.parent \
                and staging.name.startswith("whisper-small.probe-"):
            shutil.rmtree(staging)
        raise


def _process_working_set_mb():
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb):
        return None
    return counters.WorkingSetSize / (1024 * 1024)


def _gpu_memory_mb():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None


def capture_beep(frequency, duration_ms):
    """Play a blocking local cue; recording starts only after the start cue ends."""
    try:
        import winsound

        winsound.Beep(int(frequency), int(duration_ms))
        return True
    except Exception:
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_OK)
            return True
        except Exception:
            return False
    try:
        child = subprocess.run(
            [executable, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        values = [float(line.strip()) for line in child.stdout.splitlines() if line.strip()]
        return sum(values) if values else None
    except Exception:
        return None


class ResourceSampler:
    def __init__(self, interval=0.1):
        self.interval = interval
        self.stop_event = threading.Event()
        self.ram = []
        self.gpu = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop_event.is_set():
            ram = _process_working_set_mb()
            gpu = _gpu_memory_mb()
            if ram is not None:
                self.ram.append(ram)
            if gpu is not None:
                self.gpu.append(gpu)
            self.stop_event.wait(self.interval)

    def __enter__(self):
        self._run_once()
        self.thread.start()
        return self

    def _run_once(self):
        ram = _process_working_set_mb()
        gpu = _gpu_memory_mb()
        if ram is not None:
            self.ram.append(ram)
        if gpu is not None:
            self.gpu.append(gpu)

    def __exit__(self, *_args):
        self.stop_event.set()
        self.thread.join(timeout=2)
        self._run_once()

    def summary(self):
        return {
            "ram_baseline_mb": self.ram[0] if self.ram else None,
            "ram_peak_mb": max(self.ram) if self.ram else None,
            "ram_final_mb": self.ram[-1] if self.ram else None,
            "gpu_global_baseline_mb": self.gpu[0] if self.gpu else None,
            "gpu_global_peak_mb": max(self.gpu) if self.gpu else None,
            "gpu_global_final_mb": self.gpu[-1] if self.gpu else None,
        }


def _audio_duration(path):
    try:
        with wave.open(str(path), "rb") as source:
            return source.getnframes() / float(source.getframerate())
    except (wave.Error, EOFError):
        import av

        with av.open(str(path)) as source:
            stream = source.streams.audio[0]
            return float(stream.duration * stream.time_base) if stream.duration else None


def transcribe_files(paths, locale, device, compute_type, repeat=1):
    validate_model_name(MODEL_NAME)
    if locale not in LOCALE_LANGUAGES:
        raise ProbeError(f"unsupported locale: {locale}")
    if device not in ("cpu", "cuda"):
        raise ProbeError(f"unsupported device: {device}")
    if device == "cpu" and compute_type != "int8":
        raise ProbeError("CPU probing is locked to int8")
    if device == "cuda" and compute_type not in ("float16", "int8_float16"):
        raise ProbeError("CUDA probing permits only float16 or int8_float16")
    manifest = model_manifest()
    audio_paths = [Path(path).resolve() for path in paths]
    missing = [str(path) for path in audio_paths if not path.is_file()]
    if missing:
        raise ProbeError("audio file is missing: " + ", ".join(missing))

    from faster_whisper import WhisperModel

    sampler = ResourceSampler()
    started = time.perf_counter()
    with sampler:
        try:
            model = WhisperModel(
                str(model_root()), device=device, compute_type=compute_type,
                local_files_only=True,
            )
        except Exception as exc:
            raise ProbeError(
                f"{device}/{compute_type} model load failed without CPU fallback: "
                f"{actionable_runtime_error(exc)}"
            ) from exc
        load_seconds = time.perf_counter() - started
        runs = []
        for path in audio_paths:
            duration = _audio_duration(path)
            for iteration in range(max(1, int(repeat))):
                began = time.perf_counter()
                try:
                    segments, info = model.transcribe(
                        str(path), language=LOCALE_LANGUAGES[locale], beam_size=5,
                        condition_on_previous_text=False,
                    )
                    text = " ".join(segment.text.strip() for segment in segments).strip()
                except Exception as exc:
                    raise ProbeError(
                        f"{device}/{compute_type} transcription failed without CPU fallback: "
                        f"{actionable_runtime_error(exc)}"
                    ) from exc
                elapsed = time.perf_counter() - began
                runs.append({
                    "audio": path.name,
                    "iteration": iteration + 1,
                    "duration_seconds": duration,
                    "latency_seconds": elapsed,
                    "real_time_factor": (elapsed / duration if duration else None),
                    "language": info.language,
                    "language_probability": info.language_probability,
                    "text": text,
                })
        del model
        gc.collect()
        time.sleep(0.25)
    return {
        "ok": True,
        "device": device,
        "compute_type": compute_type,
        "locale": locale,
        "load_seconds": load_seconds,
        "resources": sampler.summary(),
        "runs": runs,
        "model": {key: manifest[key] for key in ("model", "revision", "format", "root")},
        "cpu_fallback": False,
    }


def capture_once(locale, device, compute_type, seconds):
    """Capture one utterance from the OS default input and delete its WAV afterward."""
    import numpy as np
    import sounddevice as sd

    temp_root = _local_appdata() / "Smiteless" / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix="whisper-probe-", suffix=".wav", dir=temp_root)
    os.close(fd)
    path = Path(raw_path)
    try:
        start_beep = capture_beep(880, 250)
        frames = sd.rec(
            int(float(seconds) * 16000), samplerate=16000, channels=1,
            dtype="int16", device=None,
        )
        sd.wait()
        end_beep = capture_beep(440, 180)
        samples = np.asarray(frames, dtype=np.int16)
        absolute = np.abs(samples.astype(np.int32))
        peak = int(absolute.max()) if absolute.size else 0
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) \
            if samples.size else 0.0
        with wave.open(str(path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(samples.tobytes())
        capture = {
            "seconds": float(seconds),
            "sample_rate": 16000,
            "peak_int16": peak,
            "rms_int16": rms,
            "audible_signal": peak >= 256 and rms >= 32,
            "start_beep": start_beep,
            "end_beep": end_beep,
        }
        if not capture["audible_signal"]:
            return {
                "ok": False,
                "error": "default_microphone_no_signal",
                "capture": capture,
                "model_loaded": False,
                "temporary_audio_deleted": True,
                "cpu_fallback": False,
            }
        result = transcribe_files([path], locale, device, compute_type)
        result["capture"] = capture
        result["temporary_audio_deleted"] = True
        return result
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("readiness", help="inspect dependencies/hardware without model load")
    ready.add_argument("--model", default=MODEL_NAME)
    sub.add_parser("download", help="download the pinned model snapshot explicitly")
    sub.add_parser("manifest", help="hash the complete local model")
    bench = sub.add_parser("benchmark", help="transcribe existing audio files")
    bench.add_argument("audio", nargs="+")
    bench.add_argument("--locale", choices=tuple(LOCALE_LANGUAGES), required=True)
    bench.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    bench.add_argument("--compute-type", default="int8")
    bench.add_argument("--repeat", type=int, default=1)
    capture = sub.add_parser("capture", help="capture one default-microphone utterance")
    capture.add_argument("--locale", choices=tuple(LOCALE_LANGUAGES), required=True)
    capture.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    capture.add_argument("--compute-type", default="int8")
    capture.add_argument("--seconds", type=float, default=6.0)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "readiness":
            validate_model_name(args.model)
            value = readiness()
        elif args.command == "download":
            value = download_model()
        elif args.command == "manifest":
            value = model_manifest()
        elif args.command == "benchmark":
            value = transcribe_files(
                args.audio, args.locale, args.device, args.compute_type, args.repeat)
        else:
            value = capture_once(
                args.locale, args.device, args.compute_type, args.seconds)
        _json(value)
        return 0 if value.get("ok", True) else 2
    except ProbeError as exc:
        _json({"ok": False, "error": str(exc), "cpu_fallback": False})
        return 2
    except Exception as exc:
        _json({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "cpu_fallback": False,
        })
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
