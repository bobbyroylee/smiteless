#!/usr/bin/env python3
"""Locale-aware speech, chimes, cache isolation, and one-process audio arbitration."""

import base64
import hashlib
import json
import math
import os
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass, field
from enum import IntEnum

import llmprocess


RENDERER_VERSION = "v2"
CHIME_VERSION = "v8"
LOCALE_VOICES = {"en": ("en-US", "Salli"), "pt_BR": ("pt-BR", "Camila")}
TTS_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://ttsmp3.com/"}
CACHE_DIR = os.path.join(tempfile.gettempdir(), "smiteless_audio")
MAX_RESPONSE_FILES = 64
MAX_RESPONSE_AGE = 7 * 24 * 60 * 60
AUDIO_ERRORS = frozenset({
    "silent", "online_unavailable", "missing_voice", "sapi_error", "timeout",
    "playback_error", "speaker_error",
})
AUDIO_ERROR_MESSAGES = {
    "silent": "The answer is ready, but Coach volume is zero. Raise it in Settings to hear audio.",
    "online_unavailable": "Online speech is unavailable. Check the connection or use an installed matching-language voice.",
    "missing_voice": "The answer is ready, but no matching Windows voice is installed. Install one or restore the internet connection.",
    "sapi_error": "The answer is ready, but speech synthesis is unavailable. Retry the audio test in Settings.",
    "timeout": "The answer is ready, but the audio operation timed out. Retry the audio test in Settings.",
    "playback_error": "The answer is ready, but Windows could not play it. Check the default output device and retry the audio test in Settings.",
    "speaker_error": "The answer is ready, but an unexpected audio error occurred. Retry the audio test in Settings.",
}


class Priority(IntEnum):
    PROACTIVE_RESPONSE = 10
    DETERMINISTIC_ALERT = 20
    MANUAL_RESPONSE = 30
    LISTENING = 40


def normalize_locale(locale):
    value = str(locale or "").strip().replace("-", "_")
    if value.lower() == "pt_br":
        return "pt_BR"
    return "en" if value.lower() == "en" else "en"


def voice_for_locale(locale):
    return LOCALE_VOICES[normalize_locale(locale)][1]


def culture_for_locale(locale):
    return LOCALE_VOICES[normalize_locale(locale)][0]


def audio_error_message(result, translate=None):
    """Format one stable terminal audio cause for Coach and Settings."""
    value = result if isinstance(result, dict) else {"error": result}
    code = str(value.get("error") or "speaker_error")
    source = AUDIO_ERROR_MESSAGES.get(code, AUDIO_ERROR_MESSAGES["speaker_error"])
    return (translate or (lambda message: message))(source)


def cache_identity(text, locale="en", voice=None, volume=30, renderer=RENDERER_VERSION):
    locale = normalize_locale(locale)
    voice = voice or voice_for_locale(locale)
    digest = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
    return f"{renderer}_{locale}_{voice}_{max(0, min(100, int(volume)))}_{digest}"


def cache_path(kind, name, text, locale="en", voice=None, volume=30, extension="mp3"):
    safe_kind = "".join(c for c in str(kind) if c.isalnum() or c in "_-")[:24] or "speech"
    safe_name = "".join(c for c in str(name) if c.isalnum() or c in "_-")[:32] or "line"
    ident = cache_identity(text, locale, voice, volume)
    return os.path.join(CACHE_DIR, f"{safe_kind}_{safe_name}_{ident}.{extension}")


def _atomic_bytes(path, blob):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(blob)
    os.replace(tmp, path)


def cleanup_cache(now=None):
    """Expire arbitrary response files while leaving the small deterministic cue set alone."""
    now = time.time() if now is None else float(now)
    try:
        rows = []
        for name in os.listdir(CACHE_DIR):
            if not name.startswith(("manual_", "proactive_", "test_")):
                continue
            path = os.path.join(CACHE_DIR, name)
            try:
                rows.append((os.path.getmtime(path), path))
            except OSError:
                pass
        rows.sort(reverse=True)
        for index, (mtime, path) in enumerate(rows):
            if index >= MAX_RESPONSE_FILES or now - mtime > MAX_RESPONSE_AGE:
                try:
                    os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def render_online(name, text, locale="en", volume=30, kind="cue", urlopen=None):
    """Render with ttsMP3's locale-specific Polly voice and atomically cache the MP3."""
    locale = normalize_locale(locale)
    voice = voice_for_locale(locale)
    path = cache_path(kind, name, text, locale, voice, volume, "mp3")
    try:
        if os.path.getsize(path) > 800:
            return path
    except OSError:
        pass
    opener = urlopen or urllib.request.urlopen
    data = urllib.parse.urlencode({"msg": str(text), "lang": voice, "source": "ttsmp3"}).encode()
    try:
        request = urllib.request.Request("https://ttsmp3.com/makemp3_new.php", data=data,
                                         headers=TTS_HEADERS)
        with opener(request, timeout=15) as response:
            value = json.load(response)
        url = value.get("URL") if isinstance(value, dict) and not value.get("Error") else None
        if not url:
            return None
        with opener(urllib.request.Request(url, headers=TTS_HEADERS), timeout=15) as response:
            blob = response.read()
        if len(blob) <= 800:
            return None
        _atomic_bytes(path, blob)
        return path
    except Exception:
        return None


_SAPI_PS = r'''
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$cfg = $env:SMITELESS_SPEECH_CONFIG | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$s = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
  $voice = $s.GetInstalledVoices() | Where-Object {
    $_.Enabled -and $_.VoiceInfo.Culture.Name -eq [string]$cfg.culture
  } | Select-Object -First 1
  if ($null -eq $voice) { [Console]::Out.Write('{"ok":false,"error":"missing_voice"}'); exit 0 }
  $s.SelectVoice($voice.VoiceInfo.Name)
  $s.Volume = [int]$cfg.volume
  $s.Rate = 2
  $s.SetOutputToWaveFile([string]$cfg.path)
  $s.Speak([string]$cfg.text)
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  [Console]::Out.Write(([ordered]@{ok=$true; renderer="sapi"; voice=$voice.VoiceInfo.Name;
    culture=$voice.VoiceInfo.Culture.Name} | ConvertTo-Json -Compress))
} catch {
  [Console]::Out.Write(([ordered]@{ok=$false; error="sapi_error"; message=[string]$_.Exception.Message} |
    ConvertTo-Json -Compress))
} finally { $s.Dispose() }
'''


def render_sapi(name, text, locale="en", volume=30, kind="cue", popen_factory=None):
    """Render with an installed SAPI voice of the exact culture; never cross languages."""
    locale = normalize_locale(locale)
    culture = culture_for_locale(locale)
    path = cache_path(kind, name, text, locale, f"SAPI-{culture}", volume, "wav")
    try:
        if os.path.getsize(path) > 1000:
            return {"ok": True, "path": path, "renderer": "sapi", "culture": culture}
    except OSError:
        pass
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp.wav"
    config = {"culture": culture, "volume": max(0, min(100, int(volume))),
              "text": str(text), "path": tmp}
    env = os.environ.copy()
    env["SMITELESS_SPEECH_CONFIG"] = json.dumps(config, ensure_ascii=False,
                                                   separators=(",", ":"))
    encoded = base64.b64encode(_SAPI_PS.encode("utf-16-le")).decode("ascii")
    factory = popen_factory or subprocess.Popen
    process = None
    try:
        process = factory(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                           "-EncodedCommand", encoded], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace", creationflags=llmprocess.NO_WINDOW,
                          env=env)
        stdout, _stderr = process.communicate(timeout=25)
        value = json.loads(str(stdout or "").strip())
        if process.returncode or not value.get("ok"):
            return value if isinstance(value, dict) else {"ok": False, "error": "sapi_error"}
        if not os.path.exists(tmp) or os.path.getsize(tmp) <= 1000:
            return {"ok": False, "error": "sapi_error"}
        os.replace(tmp, path)
        value["path"] = path
        return value
    except subprocess.TimeoutExpired:
        if process is not None:
            llmprocess.terminate_tree(process)
        return {"ok": False, "error": "timeout"}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": "sapi_error", "message": str(exc)[:200]}
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


_mci_lock = threading.RLock()
_active_aliases = set()


def _mci(command):
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(255)
        return ctypes.windll.winmm.mciSendStringW(command, buf, 254, 0)
    except Exception:
        return -1


def stop_playback():
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
    with _mci_lock:
        aliases = list(_active_aliases)
    for alias in aliases:
        _mci(f"stop {alias}")
        _mci(f"close {alias}")
        with _mci_lock:
            _active_aliases.discard(alias)


def _mci_play_result(path, volume, media_type, stage_prefix, mci_call=None):
    call = mci_call or _mci
    alias = (f"smiteaudio{os.getpid()}x{threading.get_ident()}x"
             f"{time.monotonic_ns()}")
    with _mci_lock:
        _active_aliases.add(alias)
    try:
        opened = call(f'open "{path}" type {media_type} alias {alias}')
        if opened != 0:
            return {"ok": False, "error": "playback_error",
                    "stage": f"{stage_prefix}_open", "backend": "mci"}
        call(f"setaudio {alias} volume to {max(0, min(1000, int(volume) * 10))}")
        played = call(f"play {alias} wait")
        return {"ok": played == 0, "error": "" if played == 0 else "playback_error",
                "stage": f"{stage_prefix}_play", "backend": "mci"}
    except Exception:
        return {"ok": False, "error": "playback_error",
                "stage": f"{stage_prefix}_play", "backend": "mci"}
    finally:
        try:
            call(f"close {alias}")
        except Exception:
            pass
        finally:
            with _mci_lock:
                _active_aliases.discard(alias)


def _valid_wav(path):
    try:
        with wave.open(str(path), "rb") as source:
            return source.getnchannels() in (1, 2) \
                and source.getsampwidth() in (1, 2, 3, 4) \
                and source.getframerate() > 0 and source.getnframes() > 0
    except (OSError, EOFError, wave.Error):
        return False


def _winsound_play(path, winsound_module=None):
    if winsound_module is None:
        import winsound as winsound_module
    # PlaySound is synchronous unless SND_ASYNC is requested. Python 3.13 does not expose
    # SND_SYNC on every Windows build, so relying on that zero-valued compatibility name
    # prevents playback before the default output device is even opened.
    winsound_module.PlaySound(
        path, winsound_module.SND_FILENAME | winsound_module.SND_NODEFAULT)


def _play_file_result(path, volume=30):
    if not path or volume <= 0:
        return {"ok": False, "error": "silent", "stage": "playback_preflight",
                "backend": "", "attempts": []}
    if str(path).lower().endswith(".mp3"):
        result = _mci_play_result(path, volume, "mpegvideo", "mp3")
        result["attempts"] = [dict(result)]
        result["attempts"][0].pop("attempts", None)
        return result
    attempts = []
    if not _valid_wav(path):
        invalid = {"ok": False, "error": "playback_error", "stage": "wav_validate",
                   "backend": "wave"}
        invalid["attempts"] = [dict(invalid)]
        invalid["attempts"][0].pop("attempts", None)
        return invalid
    attempts.append({"ok": True, "error": "", "stage": "wav_validate",
                     "backend": "wave"})
    try:
        _winsound_play(path)
        played = {"ok": True, "error": "", "stage": "wav_winsound",
                  "backend": "winsound"}
        played["attempts"] = attempts + [dict(played)]
        played["attempts"][-1].pop("attempts", None)
        return played
    except Exception:
        attempts.append({"ok": False, "error": "playback_error",
                         "stage": "wav_winsound", "backend": "winsound"})
    mci = _mci_play_result(path, volume, "waveaudio", "wav_mci")
    mci["attempts"] = attempts + [dict(mci)]
    mci["attempts"][-1].pop("attempts", None)
    return mci


def play_file(path, volume=30):
    """Compatibility API returning whether one file was played successfully."""
    return bool(_play_file_result(path, volume).get("ok"))


def _stage_result(stage, ok, renderer, culture, error="", **private):
    """Build one internal audio-stage result without spoken or configuration content."""
    result = {"ok": bool(ok), "stage": str(stage), "renderer": str(renderer or ""),
              "culture": str(culture or ""), "error": str(error or "")}
    result.update(private)
    return result


def _online_result(name, text, locale, volume, kind):
    culture = culture_for_locale(locale)
    try:
        path = render_online(name, text, locale, volume, kind)
    except Exception:
        path = None
    if path:
        return _stage_result("online_render", True, "ttsmp3", culture, path=path)
    return _stage_result(
        "online_render", False, "ttsmp3", culture, "online_unavailable")


def _sapi_result(name, text, locale, volume, kind):
    culture = culture_for_locale(locale)
    try:
        value = render_sapi(name, text, locale, volume, kind)
    except Exception:
        value = {"ok": False, "error": "sapi_error"}
    if isinstance(value, dict) and value.get("ok") and value.get("path"):
        return _stage_result(
            "sapi_render", True, "sapi", culture, path=value["path"],
            voice=str(value.get("voice") or ""))
    error = str(value.get("error") or "sapi_error") if isinstance(value, dict) else "sapi_error"
    if error not in {"missing_voice", "sapi_error", "timeout"}:
        error = "sapi_error"
    return _stage_result("sapi_render", False, "sapi", culture, error)


def _playback_result(path, renderer, culture, volume):
    try:
        value = _play_file_result(path, volume)
    except Exception:
        value = {"ok": False, "error": "playback_error", "stage": "playback_error",
                 "attempts": []}
    attempts = [
        _stage_result(row.get("stage") or "playback", row.get("ok"), renderer, culture,
                      row.get("error") or "")
        for row in value.get("attempts", [])
    ]
    if not attempts:
        attempts.append(_stage_result(
            value.get("stage") or "playback", value.get("ok"), renderer, culture,
            value.get("error") or ""))
    result = attempts[-1]
    result["attempts"] = attempts
    return result


def _public_audio_result(attempts, ok=False, renderer="", culture="", error=""):
    """Return safe diagnostics: no text, temporary URL, local path, or backend detail."""
    safe_attempts = [
        {key: attempt.get(key) for key in ("stage", "ok", "renderer", "culture", "error")}
        for attempt in attempts
    ]
    return {"ok": bool(ok), "renderer": str(renderer or ""),
            "culture": str(culture or ""), "error": str(error or ""),
            "stage": safe_attempts[-1]["stage"] if safe_attempts else "preflight",
            "attempts": safe_attempts}


def speak(name, text, volume=30, locale="en", kind="cue"):
    """Render and synchronously play one line, reporting the renderer actually used."""
    culture = culture_for_locale(locale)
    if not str(text or "").strip() or volume <= 0:
        return _public_audio_result([], culture=culture, error="silent")
    cleanup_cache()
    attempts = []
    online = _online_result(name, text, locale, volume, kind)
    attempts.append(online)
    if online["ok"]:
        playback = _playback_result(online["path"], "ttsmp3", culture, volume)
        attempts.extend(playback["attempts"])
        if playback["ok"]:
            result = _public_audio_result(
                attempts, ok=True, renderer="ttsmp3", culture=culture)
            result["voice"] = voice_for_locale(locale)
            return result
    sapi = _sapi_result(name, text, locale, volume, kind)
    attempts.append(sapi)
    if not sapi["ok"]:
        return _public_audio_result(
            attempts, renderer="sapi", culture=culture, error=sapi["error"])
    playback = _playback_result(sapi["path"], "sapi", culture, volume)
    attempts.extend(playback["attempts"])
    if playback["ok"]:
        result = _public_audio_result(attempts, ok=True, renderer="sapi", culture=culture)
        if sapi.get("voice"):
            result["voice"] = sapi["voice"]
        return result
    return _public_audio_result(
        attempts, renderer="sapi", culture=culture, error="playback_error")


_SR = 44100
_MAX_AMP = 0.55
_HZ = {"G4": 392.00, "B4": 493.88, "D5": 587.33, "E5": 659.25,
       "G5": 783.99, "A5": 880.00, "B5": 987.77}
_CUES = {45: (0.22, [("D5", 0.18), ("G5", 0.44)]),
         30: (0.17, [("G4", 0.15), ("B4", 0.15), ("D5", 0.17), ("G5", 0.50)]),
         15: (0.12, [("D5", 0.12), ("E5", 0.12), ("G5", 0.12), ("A5", 0.12),
                      ("B5", 0.55)])}


def _tone(freq, at, duration, last=False):
    env = math.exp(-at * (2.8 / duration))
    attack = min(1.0, at / 0.028)
    sample = math.sin(2 * math.pi * freq * at)
    sample += 0.16 * math.sin(2 * math.pi * 2 * freq * at) * math.exp(-at * 4)
    if last:
        sample += 0.16 * math.sin(2 * math.pi * (freq / 2) * at) * math.exp(-at * 2.5)
    return sample * env * attack


def _render_chime(cue, volume):
    step, sequence = cue
    total = (len(sequence) - 1) * step + sequence[-1][1] + 0.17
    samples = [0.0] * int(_SR * total)
    for index, (note, ring) in enumerate(sequence):
        start = int(_SR * index * step)
        for offset in range(int(_SR * ring)):
            samples[start + offset] += _tone(_HZ[note], offset / _SR, ring,
                                               index == len(sequence) - 1)
    peak = max(1e-6, max(abs(value) for value in samples))
    amp = (max(0, min(100, int(volume))) / 100.0 * _MAX_AMP) / peak
    return b"".join(struct.pack("<h", int(max(-1, min(1, value * amp)) * 32767))
                    for value in samples)


def chime_path(threshold, volume=30):
    threshold = int(threshold)
    volume = max(0, min(100, int(volume)))
    path = os.path.join(CACHE_DIR, f"chime_{CHIME_VERSION}_{threshold}_{volume}.wav")
    try:
        if os.path.getsize(path) > 1000:
            return path
    except OSError:
        pass
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with wave.open(tmp, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(_SR)
            handle.writeframes(_render_chime(_CUES[threshold], volume))
        os.replace(tmp, path)
        return path
    except Exception:
        return None


def play_chime(threshold, volume=30):
    path = chime_path(threshold, volume)
    return {"ok": bool(path and play_file(path, volume)), "renderer": "chime"}


@dataclass
class AudioJob:
    priority: Priority
    name: str = "line"
    text: str = ""
    locale: str = "en"
    volume: int = 30
    chime: int = 0
    created_at: float = field(default_factory=time.monotonic)
    callback: object = None


class AudioScheduler:
    """One-worker scheduler implementing listening/manual/deterministic/proactive priority."""

    def __init__(self, speaker=speak, chime_player=play_chime, stopper=stop_playback):
        self.speaker = speaker
        self.chime_player = chime_player
        self.stopper = stopper
        self.condition = threading.Condition()
        self.pending = []
        self.current = None
        self.listening = False
        self.generation = 0
        self.closed = False
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def submit(self, job):
        if not isinstance(job.priority, Priority):
            job.priority = Priority(int(job.priority))
        with self.condition:
            if self.closed:
                return False
            if job.priority == Priority.LISTENING:
                self.pending.clear()
                self.listening = True
                self.generation += 1
                self.stopper()
                self.condition.notify_all()
                return True
            if self.listening and job.priority == Priority.PROACTIVE_RESPONSE:
                return False
            if job.priority == Priority.MANUAL_RESPONSE:
                self.pending = [item for item in self.pending
                                if item.priority != Priority.PROACTIVE_RESPONSE]
                if self.current and self.current.priority == Priority.PROACTIVE_RESPONSE:
                    self.generation += 1
                    self.stopper()
            elif job.priority == Priority.DETERMINISTIC_ALERT:
                self.pending = [item for item in self.pending
                                if item.priority != Priority.PROACTIVE_RESPONSE]
                if self.current and self.current.priority == Priority.PROACTIVE_RESPONSE:
                    self.generation += 1
                    self.stopper()
            else:
                self.pending = [item for item in self.pending
                                if item.priority != Priority.PROACTIVE_RESPONSE]
            self.pending.append(job)
            self.pending.sort(key=lambda item: (-int(item.priority), item.created_at))
            self.condition.notify()
            return True

    def _worker(self):
        while True:
            with self.condition:
                while (not self.pending or self.listening) and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                job = self.pending.pop(0)
                self.current = job
                generation = self.generation
            try:
                result = (self.chime_player(job.chime, job.volume) if job.chime else
                          self.speaker(job.name, job.text, job.volume, job.locale,
                                       "manual" if job.priority == Priority.MANUAL_RESPONSE else
                                       ("proactive" if job.priority == Priority.PROACTIVE_RESPONSE
                                        else "cue")))
            except Exception:
                culture = "" if job.chime else culture_for_locale(job.locale)
                renderer = "chime" if job.chime else ""
                result = _public_audio_result(
                    [_stage_result("speaker", False, renderer, culture, "speaker_error")],
                    renderer=renderer, culture=culture, error="speaker_error")
            with self.condition:
                if self.current is job:
                    self.current = None
            if generation == self.generation and callable(job.callback):
                try:
                    job.callback(result)
                except Exception:
                    pass

    def stop_listening(self):
        return self.submit(AudioJob(Priority.LISTENING))

    def finish_listening(self):
        """Release queued higher-priority audio after microphone capture has ended."""
        with self.condition:
            if self.closed:
                return False
            self.listening = False
            self.condition.notify_all()
            return True

    def cancel_proactive(self):
        """Drop queued proactive speech and stop it when it is currently playing."""
        with self.condition:
            pending_before = len(self.pending)
            self.pending = [item for item in self.pending
                            if item.priority != Priority.PROACTIVE_RESPONSE]
            current = bool(self.current and
                           self.current.priority == Priority.PROACTIVE_RESPONSE)
            if current:
                self.generation += 1
                self.stopper()
            if pending_before != len(self.pending):
                self.condition.notify_all()
            return current or pending_before != len(self.pending)

    def close(self):
        with self.condition:
            self.closed = True
            self.listening = False
            self.pending.clear()
            self.stopper()
            self.condition.notify_all()
        self.thread.join(timeout=2)


def coordinator_request(payload, timeout=0.45):
    try:
        import lolcoachipc
        return lolcoachipc.request({"type": "audio", **payload}, timeout=timeout)
    except Exception:
        return None


def deterministic_speech(name, text, volume=30, locale="en"):
    response = coordinator_request({"audio_kind": "deterministic", "name": name,
                                    "text": text, "volume": int(volume), "locale": locale})
    if response and response.get("ok"):
        return response
    return speak(name, text, volume, locale, "cue")


def deterministic_chime(threshold, volume=30):
    response = coordinator_request({"audio_kind": "deterministic", "chime": int(threshold),
                                    "volume": int(volume)})
    if response and response.get("ok"):
        return response
    return play_chime(threshold, volume)
