#!/usr/bin/env python3
"""Persistent text coach, authenticated IPC owner, and non-activating status card."""

import argparse
import ctypes
import os
import subprocess
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _dir in ("core", "ui", "tools"):
    if os.path.join(_ROOT, _dir) not in sys.path:
        sys.path.insert(0, os.path.join(_ROOT, _dir))

import llmcli
import llmprocess
import lolcoachcontext
import lolcoachipc
import lolcoachprompt
import lolcoachproactive
import lolcoachtools
import phasecheck
import smiteaudio
import smiteconfig as cfg
import smitestt
from lolcoachsession import CoachSession
from smitei18n import lang, t


_NO_WINDOW = llmprocess.NO_WINDOW
_MUTEX_HANDLE = None


def recognition_error_message(code):
    """Map expected recognition outcomes to localized, recoverable UI guidance."""
    error = str(code or "recognition_error")
    source = {
        "low_confidence":
            "I could not hear that clearly. Press the hotkey and try once more.",
        "no_speech": "I did not hear a question. Press the hotkey and try once more.",
        "empty_transcript": "I did not hear a question. Press the hotkey and try once more.",
    }.get(error, smitestt.actionable_error(error))
    return t(source).format(error=error)


def coach_audio_state(answer, result):
    """Keep the textual answer visible while classifying only the audio outcome."""
    if isinstance(result, dict) and result.get("ok"):
        return {"state": "idle", "answer": answer, "error": ""}
    return {"state": "error", "answer": answer,
            "error": smiteaudio.audio_error_message(result, t)}


def _single_instance():
    global _MUTEX_HANDLE
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.CreateMutexW(None, False, "Global\\SmitelessCoach")
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:
        return True


def _server_alive(timeout=0.8, endpoint=None):
    try:
        return bool(lolcoachipc.request({"type": "status"}, timeout=timeout,
                                        endpoint=endpoint).get("ok"))
    except lolcoachipc.IpcError:
        return False


def _launch_server():
    if _server_alive():
        return True
    lolcoachipc.remove_endpoint()
    if getattr(sys, "frozen", False):
        args = [sys.executable, "coach", "serve"]
    else:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else sys.executable
        args = [exe, os.path.join(_ROOT, "smiteless_main.py"), "coach", "serve"]
    try:
        subprocess.Popen(args, creationflags=_NO_WINDOW, cwd=_ROOT)
    except OSError:
        return False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if _server_alive():
            return True
        time.sleep(0.05)
    return False


class Coordinator:
    def __init__(self, root, owner_pid=None):
        self.root = root
        self.session = CoachSession()
        self.lock = threading.RLock()
        self.cancel_handle = None
        # This changes whenever a manual turn is reserved or explicitly cancelled.
        # It lets delayed UI/audio callbacks prove that they still own the card.
        self.manual_turn_token = 0
        self.proactive_handle = None
        self.proactive_turn_token = 0
        self.proactive_muted_lifecycle = None
        self.proactive_spoken = 0
        self.proactive_stop = threading.Event()
        settings = cfg.load()
        self.proactive_detector = lolcoachproactive.ProactiveDetector()
        self.proactive_policy = lolcoachproactive.ProactivePolicy(
            global_cooldown=settings.get("proactive_global_cooldown", 60),
            max_per_lifecycle=settings.get("proactive_max_per_game", 0))
        self._coach_dd = None
        self.state = "idle"
        self.user_text = ""
        self.answer = ""
        self.error = ""
        self.provider = cfg.load().get("llm_provider", cfg.LLM_PROVIDER_DEFAULT)
        self.audio = smiteaudio.AudioScheduler()
        self.stt_runtime = smitestt.WhisperRuntime()
        self.server = lolcoachipc.CoachIpcServer(self.dispatch, owner_pid=owner_pid)
        self.server.publish()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self._build_surface()
        self.proactive_thread = threading.Thread(
            target=self._proactive_observer, daemon=True)
        self.proactive_thread.start()

    def _build_surface(self):
        import tkinter as tk
        import smiteskin as skin
        self.root.title("Smiteless Coach")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)
        self.root.configure(bg=skin.LINE)
        self.root.geometry("440x210+-4000+-4000")
        body = tk.Frame(self.root, bg=skin.SURFACE)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        header = tk.Frame(body, bg=skin.SURFACE)
        header.pack(fill="x", padx=14, pady=(10, 5))
        tk.Label(header, text=f"{skin.BRAND_MARK} SMITELESS  {t('COACH')}",
                 bg=skin.SURFACE, fg=skin.TXT,
                 font=skin.display(skin.SMALL, bold=True)).pack(side="left")
        self.status_label = tk.Label(header, bg=skin.SURFACE, fg=skin.EMBER,
                                     font=skin.body(skin.SMALL, bold=True))
        self.close_button = tk.Button(
            header, text="\u00d7", command=self.hide, takefocus=False, cursor="hand2",
            bg=skin.SURFACE, fg=skin.MUTED, activebackground=skin.SURFACE,
            activeforeground=skin.TXT, relief="flat", bd=0, highlightthickness=0,
            padx=5, font=skin.body(skin.BODY, bold=True),
        )
        self.close_button.pack(side="right")
        self.status_label.pack(side="right", padx=(0, 5))
        tk.Frame(body, bg=skin.LINE_SOFT, height=1).pack(fill="x", padx=14)
        self.phase_label = tk.Label(body, bg=skin.SURFACE, fg=skin.MUTED,
                                    anchor="w", font=skin.body(skin.SMALL))
        self.phase_label.pack(fill="x", padx=14, pady=(7, 3))
        self.user_label = tk.Label(body, bg=skin.SURFACE, fg=skin.TXT, anchor="w",
                                   justify="left", wraplength=410,
                                   font=skin.body(skin.BODY, bold=True))
        self.user_label.pack(fill="x", padx=14, pady=(2, 4))
        self.answer_label = tk.Label(body, bg=skin.SURFACE, fg=skin.MUTED, anchor="nw",
                                     justify="left", wraplength=410,
                                     font=skin.body(skin.SMALL))
        self.answer_label.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.root.bind("<Escape>", lambda _event: self.root.withdraw())
        self._render()
        self.root.withdraw()
        cfg.watch_tray(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)
        self.root.after(700, self._heartbeat)

    def _heartbeat(self):
        if not self.root.winfo_exists():
            return
        try:
            self.stt_runtime.configure(cfg.load())
        except Exception:
            pass
        self.root.after(700, self._heartbeat)

    def show(self):
        def apply():
            self._resize_surface()
            self.root.deiconify()
            try:
                import smiteoverlay as overlay
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                overlay.make_no_activate(hwnd, topmost=True)
                overlay.show_no_activate(hwnd, topmost=True)
            except Exception:
                pass
        self.root.after(0, apply)

    def hide(self):
        self.root.after(0, self.root.withdraw)

    def _render(self):
        snapshot = self.session.snapshot()
        status = {"idle": t("idle"), "listening": t("listening"),
                  "thinking": t("thinking"), "speaking": t("speaking"),
                  "cancelled": t("cancelled"), "error": t("error")}.get(self.state, self.state)
        self.status_label.config(text=status.upper())
        self.phase_label.config(text=f"{snapshot['phase']}  ·  {llmcli.provider_label(self.provider)}")
        self.user_label.config(text=self.user_text or t("Ask Smiteless about the current game."))
        if self.answer and self.error:
            visible = f"{self.answer}\n\n{self.error}"
        else:
            visible = self.error or self.answer or t("Text coach ready.")
        self.answer_label.config(text=visible)
        self._resize_surface()

    def _resize_surface(self):
        """Fit the right-side card above the minimap/HUD region."""
        self.root.update_idletasks()
        width = 440
        height = max(190, self.root.winfo_reqheight())
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = screen_width - width - 28
        # League's minimap occupies roughly the lower-right 25% of the screen.
        # Keep extra clearance so the non-activating coach never hides it, while
        # retaining the familiar right-edge notification placement.
        bottom_clearance = max(300, round(screen_height * 0.30))
        y = max(28, screen_height - height - bottom_clearance)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _set(self, _turn_token=None, _proactive_token=None, **values):
        def apply():
            if _turn_token is not None:
                with self.lock:
                    if getattr(self, "manual_turn_token", 0) != _turn_token:
                        return
            if _proactive_token is not None:
                with self.lock:
                    if getattr(self, "proactive_turn_token", 0) != _proactive_token:
                        return
            for key, value in values.items():
                setattr(self, key, value)
            self._render()
        self.root.after(0, apply)

    def _reserve_manual_turn(self):
        """Reserve the authoritative owner before preempting proactive work."""
        with self.lock:
            if self.cancel_handle is not None:
                return None
            handle = llmprocess.CancellationHandle()
            self.cancel_handle = handle
            self.manual_turn_token = getattr(self, "manual_turn_token", 0) + 1
            # Also invalidate a proactive callback that completed just before this reservation
            # but is still waiting for Tk's event queue.
            self.proactive_turn_token = getattr(self, "proactive_turn_token", 0) + 1
            return handle

    def _manual_token(self, handle):
        with self.lock:
            if self.cancel_handle is handle:
                return getattr(self, "manual_turn_token", 0)
        return None

    def _release_manual_turn(self, handle):
        """Release only the owner that reached its normal terminal callback."""
        with self.lock:
            if self.cancel_handle is not handle:
                return False
            self.cancel_handle = None
            return True

    def _cancel_manual_turn(self):
        """Invalidate the current owner so an old callback cannot repaint a new turn."""
        with self.lock:
            handle = self.cancel_handle
            if handle is not None:
                self.cancel_handle = None
                self.manual_turn_token = getattr(self, "manual_turn_token", 0) + 1
            return handle

    def _set_manual(self, handle, **values):
        token = self._manual_token(handle)
        if token is None:
            return False
        self._set(_turn_token=token, **values)
        return True

    def _complete_manual(self, handle, **values):
        """Publish a terminal state only if this is still the current manual turn."""
        token = self._manual_token(handle)
        if token is None or not self._release_manual_turn(handle):
            return False
        self._set(_turn_token=token, **values)
        return True

    def _current_proactive_token(self, handle):
        with self.lock:
            if self.proactive_handle is handle and self.cancel_handle is None:
                return getattr(self, "proactive_turn_token", 0)
        return None

    def _set_proactive(self, handle, **values):
        token = self._current_proactive_token(handle)
        if token is None:
            return False
        self._set(_proactive_token=token, **values)
        return True

    def dispatch(self, message):
        kind = str(message.get("type") or "")
        if kind == "status":
            with self.lock:
                proactive = self.proactive_policy.snapshot()
                proactive.update(
                    enabled=bool(cfg.load().get("proactive_coach", False)),
                    muted=bool(self.proactive_muted_lifecycle and
                               self.proactive_muted_lifecycle ==
                               self.proactive_detector.lifecycle_id),
                    spoken=self.proactive_spoken,
                )
                return {"ok": True, "state": self.state, "provider": self.provider,
                        "enabled": bool(cfg.load().get("voice_coach", False)),
                        "session": self.session.snapshot(),
                        "stt_worker": self.stt_runtime.status(),
                        "proactive": proactive}
        if kind == "readiness":
            return {**smitestt.readiness(), "worker": self.stt_runtime.status()}
        if kind == "unload_model":
            return self.stt_runtime.unload()
        if kind == "proactive_mute":
            muted = bool(message.get("muted", True))
            with self.lock:
                self.proactive_muted_lifecycle = (
                    (self.proactive_detector.lifecycle_id or "__pending__") if muted else None)
                dropped = self.proactive_policy.drop_queued()
            if muted:
                self._cancel_proactive("game_mute")
            if dropped:
                lolcoachproactive.log_event("suppressed", dropped, "game_mute")
            return {"ok": True, "muted": muted}
        if kind == "show":
            self.show()
            return {"ok": True}
        if kind == "hide":
            self.hide()
            return {"ok": True}
        if kind == "reset":
            with self.lock:
                self.session.reset()
            self._set(state="idle", user_text="", answer="", error="")
            return {"ok": True}
        if kind == "cancel":
            return self.cancel()
        if kind == "toggle":
            with self.lock:
                busy = self.cancel_handle is not None
            if busy:
                return self.cancel()
            return self.start_listening()
        if kind == "listen":
            return self.start_listening()
        if kind == "audio":
            return self.audio_request(message)
        if kind == "shutdown":
            self.root.after(0, self.root.destroy)
            return {"ok": True}
        if kind == "ask":
            return self.ask(str(message.get("text") or ""))
        return {"ok": False, "error": "unknown_request"}

    def cancel(self):
        proactive_cancelled = self._cancel_proactive("manual_cancel")
        handle = self._cancel_manual_turn()
        if handle:
            handle.cancel()
        self.audio.stop_listening()
        self.audio.finish_listening()
        self._set(state="cancelled", error=t("Coach request cancelled."))
        return {"ok": True, "cancelled": bool(handle) or proactive_cancelled}

    def start_listening(self):
        settings = cfg.load()
        if not settings.get("voice_coach", False):
            message = t("Coach is disabled. Enable it in Settings before using the microphone.")
            self._set(state="error", error=message)
            self.show()
            return {"ok": False, "error": message, "disabled": True}
        handle = self._reserve_manual_turn()
        if handle is None:
            return {"ok": False, "error": t("Coach is busy. Press the hotkey again to cancel.")}
        self._cancel_proactive("manual_listening")
        self.audio.stop_listening()
        self._set_manual(handle, state="listening", user_text=t("Listening…"),
                         answer=t("Speak now. Listening stops after silence."), error="")
        self.show()

        def work():
            locale = lang()
            try:
                result = smitestt.recognize(
                    locale, cancel_handle=handle, runtime=self.stt_runtime, settings=settings)
            except Exception:
                result = {"ok": False, "error": "worker_crash"}
            finally:
                self.audio.finish_listening()
            if handle.cancelled:
                return
            if not result.get("ok"):
                error = result.get("error") or "recognition_error"
                message = recognition_error_message(error)
                self._complete_manual(handle, state="error",
                                      user_text=result.get("text") or "", error=message)
                return
            question = result.get("text") or ""
            self._set_manual(handle, state="thinking", user_text=question, answer="", error="")
            self.ask(question, handle=handle)

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "state": "listening"}

    def audio_request(self, message):
        kind = str(message.get("audio_kind") or "deterministic")
        priority = {"manual": smiteaudio.Priority.MANUAL_RESPONSE,
                    "proactive": smiteaudio.Priority.PROACTIVE_RESPONSE,
                    "deterministic": smiteaudio.Priority.DETERMINISTIC_ALERT}.get(kind)
        if priority is None:
            return {"ok": False, "error": "unknown_audio_kind"}
        text = " ".join(str(message.get("text") or "").split())[:6000]
        chime = int(message.get("chime") or 0)
        if not text and chime not in (15, 30, 45):
            return {"ok": False, "error": "empty_audio"}
        job = smiteaudio.AudioJob(priority=priority, name=str(message.get("name") or "cue")[:40],
                                  text=text, locale=str(message.get("locale") or lang()),
                                  volume=max(0, min(100, int(message.get("volume") or 30))),
                                  chime=chime)
        return {"ok": bool(self.audio.submit(job)), "queued": True}

    def ask(self, question, handle=None):
        question = question.strip()
        if not question:
            if handle is not None:
                self._complete_manual(handle, state="error",
                                      error=t("A text question is required."))
            return {"ok": False, "error": t("A text question is required.")}
        settings = cfg.load()
        if not settings.get("voice_coach", False):
            message = t("Coach is disabled. Enable it in Settings before sending game context.")
            if handle is not None:
                self._complete_manual(handle, state="error", error=message, user_text=question)
            else:
                self._set(state="error", error=message, user_text=question)
            self.show()
            return {"ok": False, "error": message, "disabled": True}
        owns_handle = handle is None
        if owns_handle:
            handle = self._reserve_manual_turn()
            if handle is None:
                return {"ok": False, "error": t("Coach is already thinking. Cancel it first.")}
        if self._manual_token(handle) is None:
            return {"ok": False, "error": t("Coach request cancelled.")}
        self._cancel_proactive("manual_question")
        with self.lock:
            self.provider = settings.get("llm_provider", cfg.LLM_PROVIDER_DEFAULT)
        self._set_manual(handle, state="thinking", user_text=question, answer="", error="")
        self.show()
        audio_accepted = False
        terminal = None
        try:
            locale = lang()
            phase = phasecheck.phase_detailed()
            dd = None
            if phase in ("ChampSelect", "Loading", "GameStart", "InProgress", "Reconnect"):
                try:
                    import lolbuild
                    dd = lolbuild.ddragon()
                except Exception:
                    dd = None
            envelope = lolcoachcontext.capture(locale=locale, phase=phase, dd=dd)
            with self.lock:
                self.session.observe(envelope["phase"], envelope["lifecycle_id"])
                history = self.session.history()
            result = lolcoachtools.answer(
                question, envelope, history, locale,
                provider_call=lambda prompt: llmcli.call(
                    prompt, self.provider, timeout=120, cancel_handle=handle),
                dd=dd, cancelled=lambda: handle.cancelled,
            )
            text, error = result.get("text"), result.get("error")
            if handle.cancelled:
                return {"ok": False, "error": t("Coach request cancelled.")}
            if error or not text:
                message = error or t("Coach returned no text.")
                terminal = {"state": "error", "error": message}
                return {"ok": False, "error": message}
            text = " ".join(str(text).split())[:6000]
            with self.lock:
                self.session.add_turn(question, text)
            volume = int(settings.get("dragon_volume", 30))

            def spoken(result):
                self._complete_manual(handle, **coach_audio_state(text, result))
            self._set_manual(handle, state="speaking", answer=text, error="")
            accepted = self.audio.submit(smiteaudio.AudioJob(
                priority=smiteaudio.Priority.MANUAL_RESPONSE, name="answer", text=text,
                locale=locale, volume=volume, callback=spoken))
            if not accepted:
                terminal = coach_audio_state(text, {"ok": False, "error": "speaker_error",
                                                    "stage": "scheduler_submit"})
            else:
                audio_accepted = True
            return {"ok": True, "text": text, "phase": envelope["phase"]}
        except Exception as exc:
            message = t("Coach unavailable: {error}").format(error=str(exc)[:160])
            terminal = {"state": "error", "error": message}
            return {"ok": False, "error": message}
        finally:
            if not audio_accepted:
                self._complete_manual(handle, **(terminal or {
                    "state": "cancelled", "error": t("Coach request cancelled.")}))

    def _cancel_proactive(self, reason):
        if not hasattr(self, "proactive_policy"):
            return False
        with self.lock:
            handle = self.proactive_handle
            self.proactive_handle = None
            if handle is not None:
                self.proactive_turn_token = getattr(self, "proactive_turn_token", 0) + 1
            queued = self.proactive_policy.drop_queued()
        if handle:
            handle.cancel()
        audio_cancelled = bool(self.audio.cancel_proactive())
        if queued:
            lolcoachproactive.log_event("suppressed", queued, reason)
        cancelled = bool(handle or queued or audio_cancelled)
        if cancelled and not self._manual_busy():
            self._set(state="idle", error="")
        return cancelled

    def _manual_busy(self):
        with self.lock:
            return getattr(self, "cancel_handle", None) is not None

    def _proactive_snapshot(self):
        raw_phase = phasecheck.phase_detailed()
        phase = lolcoachcontext.normalize_phase(raw_phase)
        try:
            import lolgame
            hints = lolgame.coach_lifecycle()
        except Exception:
            hints = {}
        lifecycle_id = lolcoachcontext.lifecycle_identity(phase, hints)
        sections = {}
        widget = {}
        stale = False
        uncertain = str(raw_phase or "") not in (
            set(lolcoachcontext.PHASE_SECTIONS) | lolcoachcontext._POSTGAME)
        if phase == "Lobby":
            try:
                import lolqueue
                sections["queue"] = lolqueue.coach_snapshot(phase=phase)
            except Exception:
                stale = True
        elif phase == "ChampSelect":
            try:
                import lolbuild
                import lolgame
                self._coach_dd = self._coach_dd or lolbuild.ddragon()
                sections["draft"] = lolgame.coach_snapshot(self._coach_dd)
                stale = not bool(sections["draft"])
            except Exception:
                stale = True
        elif phase in ("Loading", "GameStart"):
            try:
                import lolload
                sections["loading"] = lolload.coach_snapshot()
                stale = not sections["loading"] or bool(sections["loading"].get("_unavailable"))
            except Exception:
                stale = True
        elif phase in ("InProgress", "Reconnect"):
            widget = lolcoachproactive.read_widget_state()
            stale = bool(widget.get("_unavailable"))
        elif phase == "PostGame":
            try:
                import lolprofile
                sections["postgame"] = lolprofile.coach_snapshot()
                age = int((sections["postgame"] or {}).get("source_age_ms") or 0)
                stale = not sections["postgame"] or age > 10 * 60 * 1000
            except Exception:
                stale = True
        loading_zero = phase == "Loading"
        if phase in ("Loading", "GameStart"):
            live_signal = lolcoachproactive.read_widget_state(max_age=8)
            if not live_signal.get("_unavailable"):
                loading_zero = float(live_signal.get("game_time") or 0.0) <= 1.0
        return {
            "phase": phase, "lifecycle_id": lifecycle_id, "sections": sections,
            "widget": widget, "stale": stale, "uncertain": uncertain,
            "loading_zero": loading_zero, "observed_at": time.monotonic(),
        }

    def _proactive_observer(self):
        """Sparse phase observer; the widget bridge supplies live one-second transitions."""
        while not self.proactive_stop.is_set():
            phase = "None"
            try:
                snapshot = self._proactive_snapshot()
                phase = snapshot["phase"]
                lifecycle_id = snapshot["lifecycle_id"]
                with self.lock:
                    if self.proactive_muted_lifecycle == "__pending__":
                        self.proactive_muted_lifecycle = lifecycle_id
                    if self.proactive_muted_lifecycle and \
                            self.proactive_muted_lifecycle != lifecycle_id:
                        self.proactive_muted_lifecycle = None
                    muted = self.proactive_muted_lifecycle == lifecycle_id
                settings = cfg.load()
                enabled = bool(settings.get("proactive_coach", False))
                if not enabled:
                    self._cancel_proactive("disabled")
                manual_busy = self._manual_busy()
                intents = self.proactive_detector.observe(snapshot, emit=True)
                for intent in intents:
                    reason = self.proactive_policy.offer(
                        intent, lifecycle_id, enabled=enabled, muted=muted,
                        manual_busy=manual_busy, uncertain=snapshot["uncertain"],
                        stale=snapshot["stale"], loading_zero=snapshot["loading_zero"])
                    lolcoachproactive.log_event(
                        "intent", intent, reason,
                        {"enabled": enabled, "muted": muted,
                         "manual_busy": manual_busy})
                if (not enabled or muted or manual_busy) and self.proactive_policy.queued:
                    dropped = self.proactive_policy.drop_queued()
                    lolcoachproactive.log_event(
                        "suppressed", dropped,
                        "disabled" if not enabled else ("muted" if muted else "manual_busy"))
                ready = self.proactive_policy.pop_ready(manual_busy=manual_busy)
                if ready:
                    threading.Thread(target=self._run_proactive,
                                     args=(ready,), daemon=True).start()
            except Exception as exc:
                lolcoachproactive.log_event(
                    "observer_error", reason=type(exc).__name__)
            settings = cfg.load()
            delay = (settings.get("proactive_live_poll_seconds", 2)
                     if phase in ("InProgress", "Reconnect")
                     else settings.get("proactive_poll_seconds", 5))
            self.proactive_stop.wait(max(1.0, float(delay)))

    def _run_proactive(self, intent):
        if self._manual_busy():
            lolcoachproactive.log_event("suppressed", intent, "manual_busy")
            return
        handle = llmprocess.CancellationHandle()
        with self.lock:
            if self.proactive_handle is not None or self.cancel_handle is not None:
                return
            self.proactive_handle = handle
            self.proactive_turn_token = getattr(self, "proactive_turn_token", 0) + 1
        lolcoachproactive.log_event("provider_started", intent)
        try:
            current_phase = lolcoachcontext.normalize_phase(phasecheck.phase_detailed())
            if current_phase != intent.phase or handle.cancelled:
                lolcoachproactive.log_event("suppressed", intent, "phase_changed")
                return
            locale = lang()
            dd = None
            if current_phase in ("ChampSelect", "Loading", "GameStart", "InProgress", "Reconnect"):
                try:
                    import lolbuild
                    dd = self._coach_dd or lolbuild.ddragon()
                    self._coach_dd = dd
                except Exception:
                    dd = None
            envelope = lolcoachcontext.capture(locale=locale, phase=current_phase, dd=dd)
            question = lolcoachproactive.intent_question(intent, locale)
            # Proactive calls deliberately receive no conversational turns and never mutate
            # CoachSession.  The current redacted envelope is the entire context contract.
            prompt = lolcoachprompt.build_prompt(question, envelope, [], locale)
            settings = cfg.load()
            provider = settings.get("llm_provider", cfg.LLM_PROVIDER_DEFAULT)
            text, error = llmcli.call(prompt, provider, timeout=90, cancel_handle=handle)
            if handle.cancelled or self._manual_busy():
                lolcoachproactive.log_event("suppressed", intent, "cancelled")
                return
            if error or not text:
                delay = self.proactive_policy.record_failure()
                lolcoachproactive.log_event(
                    "provider_failed", intent, str(error or "empty")[:80],
                    {"backoff_seconds": delay})
                return
            text = " ".join(str(text).split())[:2000]
            volume = int(settings.get("dragon_volume", 30))
            audio_accepted = False

            def spoken(result):
                token = self._current_proactive_token(handle)
                if token is None:
                    return
                if result.get("ok"):
                    with self.lock:
                        self.proactive_spoken += 1
                    self.proactive_policy.record_success()
                    self._set(_proactive_token=token, state="idle", answer=text, error="")
                    lolcoachproactive.log_event("spoken", intent, extra={"characters": len(text)})
                else:
                    delay = self.proactive_policy.record_failure()
                    self._set(_proactive_token=token, **coach_audio_state(text, result))
                    lolcoachproactive.log_event(
                        "tts_failed", intent, str(result.get("error") or "unavailable")[:80],
                        {"backoff_seconds": delay})
                with self.lock:
                    if self.proactive_handle is handle:
                        self.proactive_handle = None

            if handle.cancelled or self._manual_busy():
                lolcoachproactive.log_event("suppressed", intent, "manual_busy")
                return
            if not self._set_proactive(
                    handle, state="speaking", user_text=t("Proactive tip"), answer=text, error=""):
                lolcoachproactive.log_event("suppressed", intent, "manual_busy")
                return
            self.show()
            accepted = self.audio.submit(smiteaudio.AudioJob(
                priority=smiteaudio.Priority.PROACTIVE_RESPONSE,
                name=f"proactive_{intent.kind}"[:40], text=text,
                locale=locale, volume=volume, callback=spoken))
            if not accepted:
                self._set_proactive(handle, state="idle", answer=text, error="")
                lolcoachproactive.log_event("suppressed", intent, "audio_priority")
            else:
                audio_accepted = True
        except Exception as exc:
            delay = self.proactive_policy.record_failure()
            lolcoachproactive.log_event(
                "provider_failed", intent, type(exc).__name__, {"backoff_seconds": delay})
        finally:
            with self.lock:
                if self.proactive_handle is handle and not locals().get("audio_accepted", False):
                    self.proactive_handle = None

    def close(self):
        self.proactive_stop.set()
        self._cancel_proactive("shutdown")
        with self.lock:
            if self.cancel_handle:
                self.cancel_handle.cancel()
        self.stt_runtime.close()
        self.audio.close()
        self.server.shutdown()
        self.server.server_close()


def serve(owner_pid=None):
    endpoint = lolcoachipc.read_endpoint()
    if _server_alive(endpoint=endpoint):
        if not endpoint:  # Compatibility with an already-live legacy/test coordinator.
            return 0
        same_owner = not owner_pid or not endpoint.get("owner_pid") \
            or int(endpoint.get("owner_pid")) == int(owner_pid)
        if same_owner:
            return 0
        # Reload starts the replacement before the old tray's OnExit shutdown necessarily
        # lands.  Wait for that exact coordinator, not whichever endpoint is current later.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _server_alive(timeout=0.2, endpoint=endpoint):
            time.sleep(0.05)
        if _server_alive(timeout=0.2, endpoint=endpoint):
            return 0
    if endpoint:
        lolcoachipc.remove_endpoint(expected_token=endpoint.get("token"))
    deadline = time.monotonic() + 5.0
    while not _single_instance():
        if time.monotonic() >= deadline:
            return 0
        time.sleep(0.05)
    import tkinter as tk
    root = tk.Tk()
    app = Coordinator(root, owner_pid=owner_pid)
    try:
        root.mainloop()
    finally:
        app.close()
    return 0


def _print_response(response):
    stream = sys.stdout if response.get("ok") else sys.stderr
    text = response.get("text") or response.get("error")
    if text:
        stream.write(str(text) + "\n")
    elif response:
        stream.write(str(response) + "\n")
    return 0 if response.get("ok") else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="coach")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--owner-pid", type=int)
    ask = sub.add_parser("ask")
    ask.add_argument("--text", required=True)
    for name in ("cancel", "toggle", "listen", "show", "hide", "reset", "status",
                 "readiness", "unload-model"):
        sub.add_parser(name)
    shutdown = sub.add_parser("shutdown")
    shutdown.add_argument("--endpoint-token")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args.owner_pid)
    if args.command == "shutdown":
        # Shutdown is idempotent and generation-bound.  In particular, an old tray's delayed
        # OnExit command must neither launch a server nor address a replacement endpoint.
        endpoint = lolcoachipc.read_endpoint()
        if not endpoint or (args.endpoint_token and
                            endpoint.get("token") != args.endpoint_token):
            return 0
        try:
            return _print_response(lolcoachipc.request(
                {"type": "shutdown"}, timeout=5, endpoint=endpoint))
        except lolcoachipc.IpcError:
            lolcoachipc.remove_endpoint(expected_token=endpoint.get("token"))
            return 0
    if not _server_alive() and not _launch_server():
        return _print_response({"ok": False, "error": t("Coach is not running.")})
    payload = {"type": "unload_model" if args.command == "unload-model" else args.command}
    if args.command == "ask":
        payload["text"] = args.text
    try:
        return _print_response(lolcoachipc.request(payload, timeout=130 if args.command == "ask" else 5))
    except lolcoachipc.IpcError as exc:
        return _print_response({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    raise SystemExit(main())
