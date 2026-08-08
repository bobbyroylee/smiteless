#!/usr/bin/env python3
"""Bounded Windows-default microphone capture worker with a JSON-only contract."""

import json
import math
import os
import sys
import time
import wave
from collections import deque
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
for _folder in ("core", "tools"):
    _path = str(_ROOT / _folder)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import smitewhispermodel


for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


PROTOCOL_VERSION = 1
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
BLOCK_MS = 50
DEFAULT_INITIAL_SILENCE_MS = 5000
DEFAULT_END_SILENCE_MS = 900
DEFAULT_TOTAL_MS = 15000
MIN_PEAK = 256
MIN_RMS = 32.0
MAX_REQUEST_BYTES = 8192
MAX_AUDIO_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * 20
TEMP_DIRECTORY = "coach-audio"
TEMP_PREFIX = "coach-"
TEMP_SUFFIX = ".wav"
STALE_AUDIO_SECONDS = 60 * 60
START_BEEP_HZ = 880
START_BEEP_MS = 250
END_BEEP_HZ = 440
END_BEEP_MS = 180
POST_BEEP_DELAY_SECONDS = 0.20


class CaptureError(RuntimeError):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


def audio_root(paths=None):
    paths = paths or smitewhispermodel.resolve_paths()
    root = (paths.app_root / "tmp" / TEMP_DIRECTORY).resolve()
    expected = (paths.app_root / "tmp" / TEMP_DIRECTORY).resolve()
    if root != expected or root.parent.parent != paths.app_root.resolve():
        raise CaptureError("unsafe_audio_path")
    return root


def validate_audio_path(value, root=None, require_exists=False):
    root = Path(root or audio_root()).resolve()
    original = Path(value)
    if original.is_symlink():
        raise CaptureError("invalid_audio_path")
    path = original.resolve()
    if path.parent != root or not path.name.startswith(TEMP_PREFIX) \
            or not path.name.endswith(TEMP_SUFFIX):
        raise CaptureError("invalid_audio_path")
    if require_exists and (not path.is_file() or path.is_symlink()):
        raise CaptureError("invalid_audio_path")
    return path


def cleanup_stale_audio(root=None, clock=time.time, max_age=STALE_AUDIO_SECONDS):
    root = Path(root or audio_root()).resolve()
    if not root.is_dir():
        return 0
    removed = 0
    for item in root.iterdir():
        try:
            path = validate_audio_path(item, root=root, require_exists=True)
            age = max(0.0, float(clock()) - path.stat().st_mtime)
            if age >= float(max_age):
                path.unlink()
                removed += 1
        except (CaptureError, OSError, ValueError):
            continue
    return removed


def _stats(block):
    if len(block) % SAMPLE_WIDTH:
        raise CaptureError("invalid_pcm")
    samples = memoryview(block).cast("h")
    if not samples:
        return 0, 0.0
    peak = 0
    squares = 0
    for sample in samples:
        value = abs(int(sample))
        peak = max(peak, value)
        squares += value * value
    return peak, math.sqrt(squares / len(samples))


def capture_blocks(blocks, initial_silence_ms=DEFAULT_INITIAL_SILENCE_MS,
                   end_silence_ms=DEFAULT_END_SILENCE_MS,
                   total_ms=DEFAULT_TOTAL_MS, block_ms=BLOCK_MS):
    """Select one utterance from PCM blocks without touching audio hardware."""
    initial_silence_ms = max(250, int(initial_silence_ms))
    end_silence_ms = max(150, int(end_silence_ms))
    total_ms = max(1000, min(20000, int(total_ms)))
    block_ms = max(10, min(200, int(block_ms)))
    preroll = deque(maxlen=max(1, 200 // block_ms))
    kept = []
    speech = False
    silence_ms = 0
    elapsed_ms = 0
    peak_seen = 0
    square_weight = 0.0
    sample_count = 0

    for raw in blocks:
        if elapsed_ms >= total_ms:
            break
        block = bytes(raw)
        if len(block) > MAX_AUDIO_BYTES:
            raise CaptureError("audio_too_large")
        peak, rms = _stats(block)
        count = len(block) // SAMPLE_WIDTH
        peak_seen = max(peak_seen, peak)
        square_weight += rms * rms * count
        sample_count += count
        voiced = peak >= MIN_PEAK and rms >= MIN_RMS
        elapsed_ms += block_ms
        if not speech:
            preroll.append(block)
            if voiced:
                speech = True
                kept.extend(preroll)
                preroll.clear()
                silence_ms = 0
            elif elapsed_ms >= initial_silence_ms:
                break
            continue
        kept.append(block)
        silence_ms = 0 if voiced else silence_ms + block_ms
        if silence_ms >= end_silence_ms:
            break
        if sum(len(part) for part in kept) > MAX_AUDIO_BYTES:
            raise CaptureError("audio_too_large")

    if not speech:
        raise CaptureError("no_speech")
    pcm = b"".join(kept)
    if not pcm:
        raise CaptureError("no_speech")
    rms_seen = math.sqrt(square_weight / sample_count) if sample_count else 0.0
    return {
        "pcm": pcm,
        "duration_ms": round(len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH) * 1000),
        "peak_int16": peak_seen,
        "rms_int16": round(rms_seen, 3),
        "stopped_by_silence": silence_ms >= end_silence_ms,
    }


def _default_input_info(sounddevice):
    try:
        info = sounddevice.query_devices(None, "input")
        channels = int(info.get("max_input_channels", 0))
        if channels < 1:
            raise CaptureError("microphone_unavailable")
        return {"available": True, "max_input_channels": channels}
    except CaptureError:
        raise
    except Exception as exc:
        raise CaptureError("microphone_unavailable", str(exc)) from exc


def microphone_readiness(sounddevice=None):
    try:
        if sounddevice is None:
            import sounddevice
        info = _default_input_info(sounddevice)
        return {"ok": True, "capture_mode": "windows_default", **info,
                "capture_started": False}
    except CaptureError as exc:
        return {"ok": False, "error": exc.code, "capture_mode": "windows_default",
                "available": False, "capture_started": False}
    except (ImportError, OSError) as exc:
        return {"ok": False, "error": "capture_runtime_missing",
                "capture_mode": "windows_default", "available": False,
                "capture_started": False, "detail": type(exc).__name__}


def capture_beep(frequency, duration_ms):
    """Play a blocking local cue without opening or selecting an audio input."""
    try:
        import winsound
        winsound.Beep(int(frequency), int(duration_ms))
        return True
    except (ImportError, OSError, RuntimeError):
        return False


def capture_default(path, initial_silence_ms=DEFAULT_INITIAL_SILENCE_MS,
                    end_silence_ms=DEFAULT_END_SILENCE_MS,
                    total_ms=DEFAULT_TOTAL_MS, sounddevice=None, root=None, beeper=None,
                    post_beep_delay=POST_BEEP_DELAY_SECONDS):
    path = validate_audio_path(path, root=root, require_exists=True)
    if path.stat().st_size:
        raise CaptureError("invalid_audio_path")
    if sounddevice is None:
        try:
            import sounddevice
        except (ImportError, OSError) as exc:
            raise CaptureError("capture_runtime_missing", type(exc).__name__) from exc
    _default_input_info(sounddevice)
    block_frames = SAMPLE_RATE * BLOCK_MS // 1000
    total_blocks = math.ceil(max(1000, min(20000, int(total_ms))) / BLOCK_MS)
    beep = beeper or capture_beep
    start_beep = bool(beep(START_BEEP_HZ, START_BEEP_MS))
    time.sleep(max(0.0, min(0.5, float(post_beep_delay))))

    def blocks():
        try:
            with sounddevice.RawInputStream(
                    samplerate=SAMPLE_RATE, blocksize=block_frames, channels=CHANNELS,
                    dtype="int16", device=None) as stream:
                for _index in range(total_blocks):
                    data, _overflowed = stream.read(block_frames)
                    yield bytes(data)
        except CaptureError:
            raise
        except Exception as exc:
            message = str(exc).lower()
            code = "permission_denied" if "permission" in message else "microphone_unavailable"
            raise CaptureError(code, str(exc)) from exc

    try:
        result = capture_blocks(blocks(), initial_silence_ms, end_silence_ms, total_ms)
    finally:
        end_beep = bool(beep(END_BEEP_HZ, END_BEEP_MS))
    with wave.open(str(path), "wb") as target:
        target.setnchannels(CHANNELS)
        target.setsampwidth(SAMPLE_WIDTH)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(result.pop("pcm"))
    result.update(ok=True, sample_rate=SAMPLE_RATE, channels=CHANNELS,
                  capture_mode="windows_default", start_beep=start_beep,
                  end_beep=end_beep)
    return result


def validate_wav(path, root=None, max_total_ms=DEFAULT_TOTAL_MS):
    path = validate_audio_path(path, root=root, require_exists=True)
    if path.stat().st_size > MAX_AUDIO_BYTES + 128:
        raise CaptureError("audio_too_large")
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.getnframes()
    except (OSError, EOFError, wave.Error) as exc:
        raise CaptureError("invalid_audio") from exc
    duration_ms = round(frames / float(rate) * 1000) if rate else 0
    if channels != CHANNELS or width != SAMPLE_WIDTH or rate != SAMPLE_RATE or frames <= 0 \
            or duration_ms > max(1000, min(20000, int(max_total_ms))) + BLOCK_MS:
        raise CaptureError("invalid_audio")
    return {"duration_ms": duration_ms, "sample_rate": rate, "channels": channels,
            "sample_width": width, "frames": frames}


def handle(request):
    if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
        return {"ok": False, "error": "protocol_mismatch", "version": PROTOCOL_VERSION}
    command = request.get("command")
    if command == "readiness":
        return {"version": PROTOCOL_VERSION, **microphone_readiness()}
    if command != "capture":
        return {"ok": False, "error": "unknown_command", "version": PROTOCOL_VERSION}
    try:
        result = capture_default(
            request.get("audio_path"),
            initial_silence_ms=request.get("initial_silence_ms", DEFAULT_INITIAL_SILENCE_MS),
            end_silence_ms=request.get("end_silence_ms", DEFAULT_END_SILENCE_MS),
            total_ms=request.get("total_ms", DEFAULT_TOTAL_MS),
        )
        return {"version": PROTOCOL_VERSION, **result}
    except CaptureError as exc:
        return {"ok": False, "error": exc.code, "version": PROTOCOL_VERSION}
    except Exception as exc:
        print(f"capture_error:{type(exc).__name__}", file=sys.stderr)
        return {"ok": False, "error": "capture_failed", "version": PROTOCOL_VERSION}


def decode_request(raw):
    if len(raw) > MAX_REQUEST_BYTES:
        raise CaptureError("request_too_large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureError("malformed_json") from exc
    if not isinstance(value, dict):
        raise CaptureError("malformed_json")
    return value


def main():
    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    try:
        request = decode_request(raw)
        response = handle(request)
    except CaptureError as exc:
        response = {"ok": False, "error": exc.code, "version": PROTOCOL_VERSION}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0 if response.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
