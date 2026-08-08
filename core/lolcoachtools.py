#!/usr/bin/env python3
"""Bounded, phase-aware context discovery for the conversational coach.

This is an application-owned read-only harness, not a provider tool runtime.  A
provider may request one registered context source, once.  Smiteless validates
the request, performs the collection itself, sanitizes the result, and makes a
second and final provider call.
"""

import concurrent.futures
import json
import os
import threading
import time
from dataclasses import dataclass

import lolcoachcontext


TRACE_FILE = os.path.expanduser("~/.claude/cache/smiteless_coach_tools.jsonl")
MAX_TRACE_BYTES = 256 * 1024
_TRACE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    description: str
    phases: tuple
    timeout_seconds: float
    freshness_seconds: int
    output_bytes: int

    def public(self):
        return {
            "id": self.tool_id,
            "description": self.description,
            "arguments": {"type": "object", "properties": {},
                          "additionalProperties": False},
            "timeout_ms": int(self.timeout_seconds * 1000),
            "freshness_seconds": self.freshness_seconds,
            "max_output_bytes": self.output_bytes,
        }


_SPECS = (
    ToolSpec("profile.recent", "Recent cached self profile and match summaries.",
             ("None", "Lobby"), 0.75, 24 * 3600, 5000),
    ToolSpec("queue.current", "Current queue state and Queue Call evidence.",
             ("Lobby", "Matchmaking", "ReadyCheck"), 0.75, 30, 3000),
    ToolSpec("draft.current", "Current anonymous picks, bans, role and mastery.",
             ("ChampSelect", "Loading", "GameStart"), 0.75, 15, 5000),
    ToolSpec("loading.scout", "Current anonymous cached loading scout and plan.",
             ("Loading", "GameStart"), 0.75, 10 * 60, 7000),
    ToolSpec("live.current", "Current anonymous bounded live state and derived reads.",
             ("InProgress", "Reconnect"), 0.75, 5, 9000),
    ToolSpec("matchup.current", "Cached current lane-matchup guidance; never searches the web.",
             ("ChampSelect", "Loading", "GameStart", "InProgress", "Reconnect"),
             0.75, 30 * 24 * 3600, 3000),
    ToolSpec("postgame.latest", "Latest cached self match summary and review.",
             ("PostGame",), 0.75, 10 * 60, 5000),
)
SPECS = {spec.tool_id: spec for spec in _SPECS}


def manifest_for_phase(phase):
    """Return only the public tool descriptions legal in ``phase``."""
    phase = lolcoachcontext.normalize_phase(phase)
    return [spec.public() for spec in _SPECS if phase in spec.phases]


def parse_request(text):
    """Classify provider output as a plain answer, one strict request, or invalid."""
    value = str(text or "").strip()
    if not value:
        return {"kind": "invalid", "reason": "empty"}
    looks_structured = value.startswith("{") or "needs_context" in value
    if not looks_structured:
        return {"kind": "answer", "text": value}
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    try:
        payload = json.loads(value, object_pairs_hook=unique_object)
    except (TypeError, ValueError):
        return {"kind": "invalid", "reason": "malformed"}
    if not isinstance(payload, dict) or set(payload) != {"needs_context"}:
        return {"kind": "invalid", "reason": "schema"}
    request = payload.get("needs_context")
    if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
        return {"kind": "invalid", "reason": "schema"}
    tool_id = request.get("tool")
    arguments = request.get("arguments")
    if not isinstance(tool_id, str) or not isinstance(arguments, dict):
        return {"kind": "invalid", "reason": "schema"}
    return {"kind": "request", "tool": tool_id, "arguments": arguments}


def context_unavailable(locale):
    if locale == "pt_BR":
        return ("Não consegui obter com segurança o contexto adicional do Smiteless, "
                "então não posso responder isso com confiança.")
    return ("I could not safely retrieve the additional Smiteless context, "
            "so I cannot answer that reliably.")


def _matchup_snapshot(dd, locale):
    if not dd:
        return None
    import lolgame
    import lolmatchup

    draft = lolgame.coach_snapshot(dd)
    if not draft or not draft.get("self_champion"):
        return None
    role = str(draft.get("role") or "").lower()
    enemies = draft.get("enemies") or []
    opponent = next((row for row in enemies
                     if str(row.get("role") or "").lower() == role), None)
    opponent = opponent or (enemies[0] if enemies else None)
    if not opponent or not opponent.get("champion"):
        return None
    return lolmatchup.coach_snapshot(
        dd, draft["self_champion"], opponent["champion"], role,
        locale=locale,
    )


def _default_collectors(phase, locale, dd=None):
    import lolgame
    import lolload
    import lollive
    import lolprofile
    import lolqueue

    def latest_postgame():
        snapshot = lolprofile.coach_snapshot()
        if snapshot and snapshot.get("recent_games"):
            snapshot = dict(snapshot)
            snapshot["recent_games"] = snapshot["recent_games"][:1]
        return snapshot

    return {
        "profile.recent": lolprofile.coach_snapshot,
        "queue.current": lambda: lolqueue.coach_snapshot(phase=phase),
        "draft.current": (lambda: lolgame.coach_snapshot(dd)) if dd else (lambda: None),
        "loading.scout": lolload.coach_snapshot,
        "live.current": (lambda: lollive.coach_snapshot(dd)) if dd else (lambda: None),
        "matchup.current": lambda: _matchup_snapshot(dd, locale),
        "postgame.latest": latest_postgame,
    }


def _write_trace(tool_id, elapsed_ms, byte_count, outcome, path=None):
    """Persist metadata only; arguments and player-context results are never logged."""
    path = path or TRACE_FILE
    row = {
        "ts": int(time.time()), "tool": str(tool_id)[:80],
        "timing_ms": max(0, int(elapsed_ms)), "byte_count": max(0, int(byte_count)),
        "outcome": str(outcome)[:40],
    }
    try:
        with _TRACE_LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > MAX_TRACE_BYTES:
                old = path + ".old"
                try:
                    os.replace(path, old)
                except OSError:
                    pass
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
    except OSError:
        pass


def execute(tool_id, arguments, phase, locale="en", dd=None, collectors=None,
            trace_path=None):
    """Validate and execute one registered read-only collector."""
    started = time.monotonic()
    phase = lolcoachcontext.normalize_phase(phase)
    spec = SPECS.get(str(tool_id or ""))
    if spec is None:
        return {"ok": False, "outcome": "unknown_tool", "executed": False}
    if phase not in spec.phases:
        return {"ok": False, "outcome": "forbidden_phase", "executed": False}
    if arguments != {}:
        return {"ok": False, "outcome": "invalid_arguments", "executed": False}
    available = _default_collectors(phase, locale, dd=dd)
    if collectors:
        available.update(collectors)
    collector = available.get(spec.tool_id)
    if not callable(collector):
        return {"ok": False, "outcome": "missing", "executed": False}

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(collector)
    outcome = "ok"
    data = None
    try:
        data = future.result(timeout=spec.timeout_seconds)
    except concurrent.futures.TimeoutError:
        outcome = "timeout"
        future.cancel()
    except Exception:
        outcome = "missing"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    redactions = []
    byte_count = 0
    if outcome == "ok":
        if not data or (isinstance(data, dict) and data.get("_unavailable")):
            outcome = ((data or {}).get("_unavailable", "missing")
                       if isinstance(data, dict) else "missing")
        else:
            age = int(data.get("source_age_ms") or 0) if isinstance(data, dict) else 0
            if age > spec.freshness_seconds * 1000:
                outcome = "stale"
            else:
                redactions = []
                data = lolcoachcontext.sanitize(
                    data, redactions, path=f"$.retrieved.{spec.tool_id}")
                redactions.sort(key=lambda row: (row["path"], row["reason"]))
                byte_count = len(json.dumps(
                    data, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")).encode("utf-8"))
                if byte_count > spec.output_bytes:
                    outcome = "oversized"
                    data = None
    elapsed_ms = (time.monotonic() - started) * 1000
    _write_trace(spec.tool_id, elapsed_ms, byte_count, outcome, path=trace_path)
    if outcome != "ok":
        return {"ok": False, "outcome": outcome, "executed": True}
    return {
        "ok": True, "outcome": "ok", "executed": True,
        "tool": spec.tool_id, "data": data, "redactions": redactions,
        "byte_count": byte_count, "timing_ms": int(elapsed_ms),
    }


def answer(question, envelope, history, locale, provider_call, dd=None,
           collectors=None, trace_path=None, cancelled=None):
    """Run the direct path or one bounded retrieval round (at most two provider calls)."""
    import lolcoachprompt

    manifest = manifest_for_phase(envelope.get("phase"))
    first_prompt = lolcoachprompt.build_prompt(
        question, envelope, history, locale, tools=manifest)
    first_text, error = provider_call(first_prompt)
    if error or not first_text:
        return {"text": None, "error": error or "no text", "provider_calls": 1,
                "tool_calls": 0}
    parsed = parse_request(first_text)
    if parsed["kind"] == "answer":
        return {"text": parsed["text"], "error": None, "provider_calls": 1,
                "tool_calls": 0}
    if parsed["kind"] != "request":
        return {"text": context_unavailable(locale), "error": None,
                "provider_calls": 1, "tool_calls": 0}
    if cancelled and cancelled():
        return {"text": None, "error": "cancelled", "provider_calls": 1,
                "tool_calls": 0}

    result = execute(parsed["tool"], parsed["arguments"], envelope.get("phase"),
                     locale=locale, dd=dd, collectors=collectors,
                     trace_path=trace_path)
    if not result.get("ok"):
        return {"text": context_unavailable(locale), "error": None,
                "provider_calls": 1, "tool_calls": int(result.get("executed", False)),
                "tool_outcome": result.get("outcome")}
    if cancelled and cancelled():
        return {"text": None, "error": "cancelled", "provider_calls": 1,
                "tool_calls": 1, "tool_outcome": "ok"}
    retrieved = {
        "tool": result["tool"], "data": result["data"],
        "redactions": result["redactions"],
    }
    final_prompt = lolcoachprompt.build_prompt(
        question, envelope, history, locale, retrieved=retrieved, final_round=True)
    final_text, error = provider_call(final_prompt)
    if error or not final_text:
        return {"text": None, "error": error or "no text", "provider_calls": 2,
                "tool_calls": 1, "tool_outcome": "ok"}
    final = parse_request(final_text)
    if final["kind"] != "answer":
        final_text = context_unavailable(locale)
    else:
        final_text = final["text"]
    return {"text": final_text, "error": None, "provider_calls": 2,
            "tool_calls": 1, "tool_outcome": "ok"}
