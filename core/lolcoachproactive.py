#!/usr/bin/env python3
"""Pure proactive-coach detection/policy plus a tiny typed widget bridge.

The in-game widget remains the only one-second Live Client poller.  It publishes only
allowlisted transition facts here; the coach never reads raw widget/UI or allgamedata state.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import time


WIDGET_STATE_FILE = os.path.expanduser("~/.claude/cache/smiteless_proactive_widget.json")
INTENT_LOG_FILE = os.path.expanduser("~/.claude/cache/smiteless_proactive_intents.jsonl")
WIDGET_MAX_AGE = 5.0
MAJOR_EVENT_KINDS = {
    "DragonKill", "BaronKill", "RiftHeraldKill", "HordeKill",
    "TurretKilled", "InhibKilled",
}
ACTIONABLE_TEMPO = {"FREE", "BASE", "MOVE", "TAKE", "GIVE", "EVEN", "FORCE", "PUSH"}


@dataclass(frozen=True)
class ProactiveIntent:
    kind: str
    phase: str
    priority: int
    created_at: float
    ttl: float
    dedupe_key: str
    context_ref: str

    @property
    def expires_at(self):
        return self.created_at + self.ttl


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _fingerprint(kind, value):
    digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:20]
    return f"{kind}:{digest}"


def _intent(kind, phase, priority, ttl, value, context_ref, now):
    return ProactiveIntent(
        kind=kind, phase=phase, priority=int(priority), created_at=float(now),
        ttl=float(ttl), dedupe_key=_fingerprint(kind, value),
        context_ref=str(context_ref)[:160],
    )


class ProactiveDetector:
    """Stateful edge detector.  Detection state advances even when emission is suppressed."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lifecycle_id = None
        self.signals = {}
        self.started = False

    def reset(self, lifecycle_id=None):
        self.lifecycle_id = lifecycle_id
        self.signals = {}

    def _changed(self, key, value):
        marker = _canonical(value)
        old = self.signals.get(key)
        self.signals[key] = marker
        return old != marker

    def observe(self, snapshot, emit=True):
        """Return exact high-value edges from one already-bounded snapshot.

        ``emit=False`` still consumes every edge, which is how mute/late registration avoids
        replay.  The first observation only establishes a baseline.
        """
        snapshot = snapshot or {}
        now = float(snapshot.get("observed_at", self.clock()))
        lifecycle_id = str(snapshot.get("lifecycle_id") or "")
        if lifecycle_id != self.lifecycle_id:
            self.reset(lifecycle_id)
        first = not self.started
        self.started = True
        phase = str(snapshot.get("phase") or "None")
        sections = snapshot.get("sections") or {}
        out = []

        if phase == "Lobby":
            queue = sections.get("queue") or {}
            verdict = str(queue.get("verdict") or "").upper()
            value = (verdict, queue.get("summary"), tuple(queue.get("evidence") or ()))
            changed = self._changed("lobby_queue", value)
            if changed and verdict in ("STOP", "WAIT"):
                out.append(_intent("queue_warning", phase, 3, 120, value,
                                   f"queue:{verdict.lower()}", now))

        elif phase == "ChampSelect":
            draft = sections.get("draft") or {}
            role = str(draft.get("role") or "").upper()
            champion = str(draft.get("self_champion") or "")
            locked = bool(draft.get("locked"))
            if self._changed("draft_assignment", role) and role:
                out.append(_intent("draft_assignment", phase, 2, 75, role,
                                   f"draft:self:{role.lower()}", now))
            lock_value = (locked, champion)
            if self._changed("draft_lock", lock_value) and locked \
                    and champion not in ("", "unknown"):
                out.append(_intent("draft_lock", phase, 2, 75, lock_value,
                                   "draft:self_lock", now))
            lane = next((row for row in (draft.get("enemies") or [])
                         if role and str(row.get("role") or "").upper() == role
                         and row.get("champion") not in (None, "", "unknown")), None)
            lane_value = (role, (lane or {}).get("champion"))
            if self._changed("draft_enemy_lane", lane_value) and lane:
                out.append(_intent("enemy_lane_reveal", phase, 2, 75, lane_value,
                                   f"draft:enemy_lane:{role.lower()}", now))
            enemies = tuple(sorted(str(row.get("champion") or "")
                                   for row in (draft.get("enemies") or [])
                                   if row.get("champion") not in (None, "", "unknown")))
            final = (locked, enemies)
            if self._changed("draft_final", final) and locked and len(enemies) >= 5:
                out.append(_intent("draft_final_plan", phase, 3, 90, final,
                                   "draft:final_plan", now))

        elif phase in ("Loading", "GameStart"):
            loading = sections.get("loading") or {}
            ready = bool(loading.get("scouted"))
            value = (ready, loading.get("plan"), loading.get("win_conditions"))
            if self._changed("loading_ready", value) and ready:
                out.append(_intent("loading_plan", phase, 3, 180, value,
                                   "loading:consolidated_plan", now))

        elif phase in ("InProgress", "Reconnect"):
            widget = snapshot.get("widget") or {}
            tempo = widget.get("tempo") or {}
            tempo_value = (tempo.get("phase"), tempo.get("objective"))
            if self._changed("live_tempo", tempo_value) \
                    and tempo_value[0] in ACTIONABLE_TEMPO:
                out.append(_intent("live_tempo", phase, 2, 35, tempo_value,
                                   f"live:tempo:{str(tempo_value[0]).lower()}", now))
            for name, row in sorted((widget.get("guards") or {}).items()):
                value = (int((row or {}).get("calls") or 0),
                         str((row or {}).get("verdict") or ""),
                         bool((row or {}).get("quiet")))
                if self._changed(f"guard:{name}", value) and value[0] > 0 and not value[2]:
                    out.append(_intent(f"guard_{name}", phase, 2, 40, value,
                                       f"live:guard:{name}", now))
            for event in widget.get("events") or []:
                kind = str(event.get("kind") or "")
                if kind not in MAJOR_EVENT_KINDS:
                    continue
                value = (kind, round(float(event.get("time") or 0.0), 1))
                if self._changed(f"event:{_canonical(value)}", value):
                    out.append(_intent("major_event", phase, 3, 30, value,
                                       f"live:event:{kind.lower()}", now))

        elif phase == "PostGame":
            profile = sections.get("postgame") or {}
            latest = ((profile.get("recent_games") or [None])[0])
            if self._changed("postgame_review", latest) and latest:
                out.append(_intent("postgame_review", phase, 3, 300, latest,
                                   "postgame:latest_review", now))

        if first or not emit:
            return []
        return out


class ProactivePolicy:
    """Pure one-item scheduler with cooldown, dedupe, optional limits and failure backoff."""

    def __init__(self, clock=time.monotonic, global_cooldown=60.0,
                 per_kind_cooldown=120.0, max_per_lifecycle=0,
                 max_per_phase=0, backoff_base=30.0, backoff_cap=900.0):
        self.clock = clock
        self.global_cooldown = float(global_cooldown)
        self.per_kind_cooldown = float(per_kind_cooldown)
        self.max_per_lifecycle = int(max_per_lifecycle)
        self.max_per_phase = int(max_per_phase)
        self.backoff_base = float(backoff_base)
        self.backoff_cap = float(backoff_cap)
        self.lifecycle_id = None
        self.queued = None
        self.seen = {}
        self.last_call = -1e30
        self.last_kind = {}
        self.calls = 0
        self.phase_calls = {}
        self.failures = 0
        self.backoff_until = -1e30

    def reset(self, lifecycle_id=None):
        self.lifecycle_id = lifecycle_id
        self.queued = None
        self.seen = {}
        self.calls = 0
        self.phase_calls = {}
        self.failures = 0
        self.backoff_until = -1e30

    def _prune(self, now):
        self.seen = {key: expiry for key, expiry in self.seen.items() if expiry > now}
        if self.queued and self.queued.expires_at <= now:
            self.queued = None

    def offer(self, intent, lifecycle_id, enabled=True, muted=False,
              manual_busy=False, uncertain=False, stale=False, loading_zero=False):
        now = float(self.clock())
        lifecycle_id = str(lifecycle_id or "")
        if lifecycle_id != self.lifecycle_id:
            self.reset(lifecycle_id)
        self._prune(now)
        if intent.expires_at <= now:
            return "expired"
        if intent.dedupe_key in self.seen:
            return "duplicate"
        self.seen[intent.dedupe_key] = intent.expires_at
        reason = next((name for name, blocked in (
            ("disabled", not enabled), ("muted", muted), ("manual_busy", manual_busy),
            ("uncertain", uncertain), ("stale", stale), ("loading_zero", loading_zero),
        ) if blocked), None)
        if reason:
            return reason
        # A zero cap means unlimited; positive injected caps remain useful for fixtures.
        if self.max_per_lifecycle > 0 and self.calls >= self.max_per_lifecycle:
            return "max_lifecycle"
        if self.max_per_phase > 0 and self.phase_calls.get(intent.phase, 0) >= self.max_per_phase:
            return "max_phase"
        if self.queued is None or (intent.priority, intent.created_at) >= \
                (self.queued.priority, self.queued.created_at):
            result = "queued" if self.queued is None else "replaced"
            self.queued = intent
            return result
        return "lower_priority"

    def pop_ready(self, manual_busy=False):
        now = float(self.clock())
        self._prune(now)
        if manual_busy or self.queued is None:
            return None
        intent = self.queued
        ready_at = max(self.backoff_until, self.last_call + self.global_cooldown,
                       self.last_kind.get(intent.kind, -1e30) + self.per_kind_cooldown)
        if now < ready_at:
            return None
        self.queued = None
        self.last_call = now
        self.last_kind[intent.kind] = now
        self.calls += 1
        self.phase_calls[intent.phase] = self.phase_calls.get(intent.phase, 0) + 1
        return intent

    def drop_queued(self):
        intent, self.queued = self.queued, None
        return intent

    def record_success(self):
        self.failures = 0
        self.backoff_until = -1e30

    def record_failure(self):
        now = float(self.clock())
        self.failures += 1
        delay = min(self.backoff_cap, self.backoff_base * (2 ** (self.failures - 1)))
        self.backoff_until = now + delay
        return delay

    def snapshot(self):
        return {
            "queued": asdict(self.queued) if self.queued else None,
            "calls": self.calls, "phase_calls": dict(self.phase_calls),
            "failures": self.failures, "backoff_until": self.backoff_until,
        }


def publish_widget_state(game_time, tempo=None, guards=None, events=None, now=None):
    """Atomically publish only typed transition facts from the one-second widget poll."""
    now = time.time() if now is None else float(now)
    tempo = tempo or {}
    clean_guards = {}
    for name, row in sorted((guards or {}).items()):
        if not isinstance(row, dict):
            continue
        clean_guards[str(name)[:24]] = {
            "calls": max(0, int(row.get("calls") or 0)),
            "verdict": str(row.get("verdict") or "")[:24],
            "quiet": bool(row.get("quiet")),
        }
    clean_events = []
    for event in (events or [])[-20:]:
        kind = str(event.get("EventName") or event.get("kind") or "")
        if kind in MAJOR_EVENT_KINDS:
            clean_events.append({"kind": kind,
                                 "time": round(float(event.get("EventTime") or
                                                     event.get("time") or 0.0), 1)})
    payload = {
        "schema_version": 1, "published_at": now,
        "game_time": round(float(game_time or 0.0), 1),
        "tempo": {"phase": str(tempo.get("phase") or "")[:16],
                  "objective": str(tempo.get("obj") or tempo.get("objective") or "")[:24]},
        "guards": clean_guards, "events": clean_events,
    }
    try:
        os.makedirs(os.path.dirname(WIDGET_STATE_FILE), exist_ok=True)
        tmp = f"{WIDGET_STATE_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, WIDGET_STATE_FILE)
        return True
    except Exception:
        return False


def read_widget_state(now=None, max_age=WIDGET_MAX_AGE):
    now = time.time() if now is None else float(now)
    try:
        with open(WIDGET_STATE_FILE, encoding="utf-8") as handle:
            payload = json.load(handle)
        age = max(0.0, now - float(payload.get("published_at") or 0.0))
        if payload.get("schema_version") != 1 or age > float(max_age):
            return {"_unavailable": "stale", "source_age_ms": int(age * 1000)}
        return payload
    except Exception:
        return {"_unavailable": "missing"}


def intent_question(intent, locale="en"):
    label = intent.context_ref.replace("_", " ").replace(":", " / ")
    if locale == "pt_BR":
        return ("DÃª uma dica proativa curta e acionÃ¡vel sobre esta transiÃ§Ã£o: " + label +
                ". Use apenas o contexto atual e nÃ£o mencione que recebeu uma intent.")
    return ("Give one short, actionable proactive tip for this transition: " + label +
            ". Use only current context and do not mention that you received an intent.")


def log_event(event, intent=None, reason="", extra=None, now=None):
    row = {"ts": round(time.time() if now is None else float(now), 3),
           "event": str(event)[:40], "reason": str(reason)[:80]}
    if intent:
        row.update(kind=intent.kind, phase=intent.phase, priority=intent.priority,
                   dedupe_key=intent.dedupe_key, context_ref=intent.context_ref)
    if extra:
        row["extra"] = {str(k)[:40]: v for k, v in dict(extra).items()}
    try:
        os.makedirs(os.path.dirname(INTENT_LOG_FILE), exist_ok=True)
        if os.path.exists(INTENT_LOG_FILE) and os.path.getsize(INTENT_LOG_FILE) > 512 * 1024:
            os.replace(INTENT_LOG_FILE, INTENT_LOG_FILE + ".old")
        with open(INTENT_LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass
