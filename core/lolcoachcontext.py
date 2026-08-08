#!/usr/bin/env python3
"""Canonical, phase-aware and redacted context boundary for the local coach.

Only the dictionaries returned by domain ``coach_snapshot`` adapters may cross this
boundary. Raw LCU/Live Client payloads and rendered UI strings are never serialized.
"""
import concurrent.futures
import hashlib
import json
import re
import threading
import time
import uuid


SCHEMA_VERSION = 1
COLLECTOR_TIMEOUT = 0.75
SECTION_BUDGETS = {
    "profile": 5000, "queue": 3000, "draft": 5000,
    "loading": 7000, "live": 9000, "postgame": 5000,
}
PHASE_SECTIONS = {
    "None": ("profile",),
    "Lobby": ("profile", "queue"),
    "Matchmaking": ("queue",),
    "ReadyCheck": ("queue",),
    "ChampSelect": ("draft",),
    "Loading": ("draft", "loading"),
    "GameStart": ("draft", "loading"),
    "InProgress": ("live",),
    "Reconnect": ("live",),
    "PostGame": ("postgame",),
}
_POSTGAME = {"WaitingForStats", "PreEndOfGame", "EndOfGame"}
_SECRET_KEYS = re.compile(
    r"(?:authorization|password|passwd|token|secret|api[_-]?key|lockfile|puuid|"
    r"summoner[_-]?id|riot[_-]?id|game[_-]?name|tag[_-]?line|filesystem|path)$", re.I)
_TEXT_SECRETS = (
    (re.compile(r"RGAPI-[A-Za-z0-9_-]+", re.I), "riot_api_key"),
    (re.compile(r"\bBasic\s+[A-Za-z0-9+/=]+", re.I), "basic_auth"),
    (re.compile(r"\b(?:LeagueClient|riotclient-services):\d+:\d+:[^:\s]+:(?:https|http)\b",
                re.I), "lockfile_credentials"),
    (re.compile(r"(?<!\w)[A-Za-z]:\\(?:[^\s\"']+\\)*[^\s\"']*", re.I), "local_path"),
    (re.compile(r"(?:^|\s)[^#\s]{2,32}#[A-Za-z0-9]{2,8}(?=$|\s|[,.])"), "riot_id"),
    (re.compile(r"\b[a-zA-Z0-9_-]{70,}\b"), "opaque_identifier"),
)
_LIFECYCLE_LOCK = threading.Lock()
_FALLBACK = {"id": None, "phase": None, "active": False}


def normalize_phase(value):
    """Map gameflow variants to the stable coach phase vocabulary."""
    raw = str(value or "").strip()
    if raw in _POSTGAME:
        return "PostGame"
    if raw in PHASE_SECTIONS:
        return raw
    return "None"


def lifecycle_identity(phase, hints=None):
    """Stable opaque identity from game/lobby IDs, with a transition-safe fallback."""
    phase = normalize_phase(phase)
    hints = hints or {}
    for key in ("game_id", "lobby_id", "session_id", "roster_signature"):
        value = hints.get(key)
        if value not in (None, ""):
            digest = hashlib.sha256(f"{key}:{value}".encode("utf-8")).hexdigest()[:20]
            return f"league-{digest}"

    active = phase not in ("None", "PostGame")
    with _LIFECYCLE_LOCK:
        old_phase = _FALLBACK["phase"]
        backwards = old_phase in ("Loading", "GameStart", "InProgress", "Reconnect", "PostGame") \
            and phase in ("Lobby", "Matchmaking", "ReadyCheck", "ChampSelect")
        if not _FALLBACK["id"] or (active and not _FALLBACK["active"]) or backwards:
            seed = f"{time.time_ns()}:{uuid.uuid4().hex}"
            _FALLBACK["id"] = "local-" + hashlib.sha256(seed.encode()).hexdigest()[:20]
        _FALLBACK.update(phase=phase, active=active)
        return _FALLBACK["id"]


def _redact_text(value, path, redactions):
    text = value
    for pattern, reason in _TEXT_SECRETS:
        text, count = pattern.subn("[redacted]", text)
        if count:
            redactions.append({"path": path, "reason": reason})
    return text


def sanitize(value, redactions=None, path="$"):
    """Recursively remove secret/identity keys and redact dangerous string patterns."""
    redactions = redactions if redactions is not None else []
    if isinstance(value, dict):
        out = {}
        for key in sorted(value, key=lambda item: str(item)):
            name = str(key)
            child = f"{path}.{name}"
            if _SECRET_KEYS.search(name):
                redactions.append({"path": child, "reason": "forbidden_field"})
                continue
            out[name] = sanitize(value[key], redactions, child)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize(item, redactions, f"{path}[{index}]")
                for index, item in enumerate(value)]
    if isinstance(value, str):
        return _redact_text(value, path, redactions)[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value), path, redactions)[:1000]


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8"))


def _fit_budget(value, budget):
    """Deterministically trim list tails and optional dictionary fields to a byte budget."""
    if _json_size(value) <= budget:
        return value, False
    value = json.loads(json.dumps(value, ensure_ascii=False))
    changed = False
    while _json_size(value) > budget:
        lists = []

        def visit(node, path=()):
            if isinstance(node, list) and node:
                lists.append((len(node), path, node))
            elif isinstance(node, dict):
                for key in sorted(node):
                    visit(node[key], path + (key,))
            elif isinstance(node, list):
                for index, item in enumerate(node):
                    visit(item, path + (index,))

        visit(value)
        if lists:
            max(lists, key=lambda item: (item[0], str(item[1])))[2].pop()
            changed = True
            continue
        if isinstance(value, dict) and value:
            value.pop(sorted(value)[-1])
            changed = True
            continue
        break
    return value, changed


def _evidence(section, value):
    rows = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("in_game_performance_grade") is not None:
                rows.append({"section": section, "path": path,
                             "kind": "in_game_performance_grade",
                             "evidence_scope": "this_game"})
            if node.get("evidence_scope") in ("this_game", "account_history"):
                rows.append({"section": section, "path": path, "kind": "tag",
                             "evidence_scope": node["evidence_scope"]})
            for key in sorted(node):
                walk(node[key], f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(value, f"$.sections.{section}")
    return rows


def _default_collectors(dd=None, phase=None):
    import lolgame
    import lolload
    import lollive
    import lolprofile
    import lolqueue

    return {
        "profile": lolprofile.coach_snapshot,
        "queue": lambda: lolqueue.coach_snapshot(phase=phase),
        "draft": (lambda: lolgame.coach_snapshot(dd)) if dd else (lambda: None),
        "loading": lolload.coach_snapshot,
        "live": (lambda: lollive.coach_snapshot(dd)) if dd else (lambda: None),
        "postgame": lolprofile.coach_snapshot,
    }


def capture(locale="en", phase=None, lifecycle_hints=None, collectors=None, dd=None,
            now=None, timeout=COLLECTOR_TIMEOUT):
    """Capture one fresh phase-exclusive envelope. Collectors may be values or callables."""
    if phase is None:
        import phasecheck
        phase = phasecheck.phase_detailed()
    phase = normalize_phase(phase)
    if lifecycle_hints is None:
        try:
            import lolgame
            lifecycle_hints = lolgame.coach_lifecycle()
        except Exception:
            lifecycle_hints = {}
    now = time.time() if now is None else float(now)
    allowed = PHASE_SECTIONS[phase]
    available = _default_collectors(dd=dd, phase=phase)
    if collectors:
        available.update(collectors)

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": int(now),
        "locale": "pt_BR" if locale == "pt_BR" else "en",
        "phase": phase,
        "lifecycle_id": lifecycle_identity(phase, lifecycle_hints),
        "source_age_ms": 0,
        "sections": {}, "unavailable": [], "evidence": [], "redactions": [],
    }
    for name in sorted(set(SECTION_BUDGETS) - set(allowed)):
        envelope["unavailable"].append({"section": name,
                                         "reason": "not_allowed_in_phase"})
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(allowed)))
    futures = {}
    for name in allowed:
        source = available.get(name)
        if source is None:
            envelope["unavailable"].append({"section": name, "reason": "missing"})
            continue
        futures[name] = executor.submit(source if callable(source) else lambda value=source: value)
    deadline = time.monotonic() + max(0.01, float(timeout))
    for name in allowed:
        future = futures.get(name)
        if future is None:
            continue
        try:
            data = future.result(timeout=max(0.0, deadline - time.monotonic()))
        except concurrent.futures.TimeoutError:
            envelope["unavailable"].append({"section": name, "reason": "timeout"})
            future.cancel()
            continue
        except Exception:
            envelope["unavailable"].append({"section": name, "reason": "missing"})
            continue
        if not data:
            envelope["unavailable"].append({"section": name, "reason": "missing"})
            continue
        if isinstance(data, dict) and data.get("_unavailable"):
            envelope["unavailable"].append({"section": name,
                                             "reason": data.get("_unavailable")})
            continue
        clean = sanitize(data, envelope["redactions"], f"$.sections.{name}")
        clean, trimmed = _fit_budget(clean, SECTION_BUDGETS[name])
        if trimmed:
            envelope["redactions"].append({"path": f"$.sections.{name}",
                                             "reason": "size_budget"})
        envelope["sections"][name] = clean
        age = clean.get("source_age_ms", 0) if isinstance(clean, dict) else 0
        envelope["source_age_ms"] = max(envelope["source_age_ms"], int(age or 0))
        envelope["evidence"].extend(_evidence(name, clean))
    executor.shutdown(wait=False, cancel_futures=True)
    envelope["unavailable"].sort(key=lambda row: (row["section"], row["reason"]))
    envelope["redactions"].sort(key=lambda row: (row["path"], row["reason"]))
    envelope["evidence"].sort(key=lambda row: (row["section"], row["path"], row["kind"]))
    return envelope


def serialize_json(envelope):
    """Stable provider/fixture JSON."""
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def serialize_text(envelope):
    """Stable human-readable diagnostic form containing exactly the redacted envelope."""
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2)
