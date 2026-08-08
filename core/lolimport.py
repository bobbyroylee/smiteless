#!/usr/bin/env python3
"""lolimport.py - write the op.gg runes + summoners into the League client (LCU).

Shared by the champ-select panel's Import button and the AUTO-IMPORT path (imports the
moment you lock a champion, when the toggle is on). POSTs a fresh "Smiteless ..." rune
page (recycling an old Smiteless page / the current editable one when the page limit is
hit) and PATCHes the summoner picks, honoring the Flash-on-D/F preference.
"""
import json
import os
import ssl
import time
import urllib.request

import lolgame as lg
import smiteconfig as cfg
from smitei18n import tf


def _lcu_json(method, path, payload=None, timeout=5):
    lc = lg._lcu()
    if not lc:
        raise RuntimeError("League client not found")
    port, hdr = lc
    headers = dict(hdr)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", headers=headers,
                                 data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
        raw = r.read()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def hover_champ(cid):
    """HOVER (select, not lock) a champion in champ select via the LCU: PATCH your in-progress
    pick action with the championId and no 'completed' flag. The client then shows it as your
    intent, and the overlay re-renders to that champ. Returns "hovered"; raises RuntimeError
    with a friendly message on anything expected. Never locks — that's a separate action."""
    if not cid:
        raise RuntimeError("no champion")
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        raise RuntimeError("not in champ select")
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        raise RuntimeError("not in champ select")
    cell = sess.get("localPlayerCellId")
    action_id = None
    for group in (sess.get("actions") or []):
        for a in group:
            if (a.get("actorCellId") == cell and a.get("type") == "pick"
                    and not a.get("completed")):
                action_id = a.get("id")               # your current (un-locked) pick slot
    if action_id is None:
        raise RuntimeError("can't hover yet — wait for your turn (or you've already locked)")
    _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
              {"championId": int(cid)})
    return "hovered"


BAN_WAIT_MS = 12000        # hold the auto-ban until this little is left on the phase clock
_BAN_LOG = os.path.expanduser("~/.claude/smiteless_ban.log")
_BAN_LOG_STATE = {"last": ""}      # collapse repeated identical lines (the 1s watcher polls a lot)


def _banlog(msg, dedupe=False):
    """One diagnostic line per ban-attempt event — a missed ban must never be silent
    (work-order §2). dedupe=True collapses repeats of the same waiting-state line."""
    if dedupe and msg == _BAN_LOG_STATE["last"]:
        return
    _BAN_LOG_STATE["last"] = msg
    try:
        with open(_BAN_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def auto_ban(dd, targets, extra_avoid=()):
    """If it's YOUR ban turn right now, LOCK the first champ in `targets` that's safe to ban:
    not already banned/picked and not a teammate's hovered pick (never ban an ally's champ).
    DELIBERATELY WAITS until the last ~12s of the ban phase before locking — every extra
    second lets more teammates hover, and the team-wide ban math gets sharper with each
    hover (the caller recomputes `targets` every poll). Fires immediately if the timer
    isn't readable (never risk missing the ban). Returns the banned championId or None.
    Never raises — auto-ban must never disrupt champ select.

    Reliability (the 'ban sometimes didn't happen' fix): the LOCK is verified by re-reading
    the session; if the one-shot PATCH {championId, completed} didn't take (some client
    builds want the two-step), we fall back to PATCH-then-POST /complete. Every attempt
    writes a line to ~/.claude/smiteless_ban.log so a failure is never silent."""
    if not targets:
        return None
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        return None
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        return None
    cell = sess.get("localPlayerCellId")
    action_id = None
    for group in (sess.get("actions") or []):
        for a in group:
            if (a.get("actorCellId") == cell and a.get("type") == "ban"
                    and a.get("isInProgress") and not a.get("completed")):
                action_id = a.get("id")
    if action_id is None:
        return None                              # not your ban turn
    tmr = sess.get("timer") or {}
    left = tmr.get("adjustedTimeLeftInPhase")
    if (not tmr.get("isInfinite")) and isinstance(left, (int, float)) and left > BAN_WAIT_MS:
        _banlog(f"ban turn open, holding for hovers ({int(left) // 1000}s left)", dedupe=True)
        return None                              # clock still fat -> wait for more hovers
    avoid = set(int(c) for c in extra_avoid if c)
    b = sess.get("bans") or {}
    for c in (b.get("myTeamBans") or []) + (b.get("theirTeamBans") or []):
        if c:
            avoid.add(int(c))
    for m in (sess.get("myTeam") or []):         # don't ban a teammate's hovered / locked champ
        pi = m.get("championPickIntent") or m.get("championId") or 0
        if pi:
            avoid.add(int(pi))
    for group in (sess.get("actions") or []):    # or anything already locked
        for a in group:
            if a.get("completed") and a.get("championId"):
                avoid.add(int(a["championId"]))
    nm = (dd.get("id2name") or {}) if isinstance(dd, dict) else {}
    pick = next((int(c) for c in targets if c and int(c) not in avoid), None)
    if not pick:
        _banlog(f"no safe target: all of {[nm.get(int(c), c) for c in targets[:5]]} "
                f"already banned/picked/hovered")
        return None
    label = nm.get(pick, str(pick))
    try:
        _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
                  {"championId": pick, "completed": True})
    except Exception as e:
        _banlog(f"PATCH lock {label} raised {type(e).__name__} — trying two-step")
    if _ban_completed(action_id):
        _banlog(f"BANNED {label} (action {action_id}, one-shot)")
        return pick
    # two-step fallback: set intent, then complete — older client builds want this shape
    try:
        _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
                  {"championId": pick})
        _lcu_json("POST", f"/lol-champ-select/v1/session/actions/{action_id}/complete",
                  {"championId": pick})
    except Exception as e:
        _banlog(f"two-step lock {label} raised {type(e).__name__}")
    if _ban_completed(action_id):
        _banlog(f"BANNED {label} (action {action_id}, two-step)")
        return pick
    _banlog(f"FAILED to lock {label} — action {action_id} still open after both attempts")
    return None


def _ban_completed(action_id):
    """Re-read the session and report whether OUR ban action actually completed — the
    only proof a ban happened (a 2xx on the PATCH is not it)."""
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
        for group in (sess.get("actions") or []):
            for a in group:
                if a.get("id") == action_id:
                    return bool(a.get("completed"))
    except Exception:
        pass
    return False


# ---- dedicated ban watcher: the champ-select render loop polls every ~3s BUT an iteration
# can stall for many seconds on network work (op.gg fetch, team scout) — long enough to
# swallow the 12s firing window entirely. That was the root of 'auto-ban sometimes no-ops'.
# This thread polls ONLY the local champ-select session (cheap, ~ms) every second, reading
# its targets from a shared ref the render loop keeps fresh.
_BAN_WATCH = {"thread": None, "targets": [], "avoid": (), "dd": None, "on": False}


def ban_watch_update(dd, targets, avoid, enabled):
    """Called by the champ-select loop each poll: refresh what the watcher should ban
    (priority ban list + live EV ideas) and whether auto-ban is on. Starts the watcher
    on first use; it idles at 2s out of champ select, 1s in it."""
    _BAN_WATCH.update(dd=dd, targets=list(targets or []), avoid=tuple(avoid or ()),
                      on=bool(enabled))
    th = _BAN_WATCH.get("thread")
    if th and th.is_alive():
        return
    import threading

    def _loop():
        while True:
            try:
                if _BAN_WATCH["on"] and _BAN_WATCH["targets"]:
                    banned = auto_ban(_BAN_WATCH["dd"], _BAN_WATCH["targets"],
                                      extra_avoid=_BAN_WATCH["avoid"])
                    if banned:
                        time.sleep(5)            # our turn is done; ease off
                time.sleep(1 if _BAN_WATCH["on"] else 2)
            except Exception:
                time.sleep(2)                    # never die: a watcher that quits = silent no-ban

    th = threading.Thread(target=_loop, daemon=True, name="smiteless-ban-watch")
    _BAN_WATCH["thread"] = th
    th.start()


# ---- MAX ELO: auto-LOCK your one champion --------------------------------------------------
# The pool-discipline half of the MAX ELO switch. You name a main and a backup; when your pick
# turn comes this hovers the first one that's still available and LOCKS it. No deliberating, no
# last-second "I'll try something", no autofilled off-champ — the single highest-confidence
# climbing lever there is, enforced instead of intended.
# Hover, let the client register it (that's what feeds auto-import its champ), then LOCK.
# Deliberately NOT "wait for the end of the timer like the auto-ban does": the ban gets sharper
# the longer you wait for teammates to hover, a pick doesn't. Sitting hovered just invites
# someone to argue for your lane. MAX ELO's whole promise is that the pick is not a discussion.
PICK_SETTLE_S = 2.5
_PICK_LOG = os.path.expanduser("~/.claude/smiteless_pick.log")
_PICK_LOG_STATE = {"last": ""}
_PICK_HOVER = {"action": None, "cid": 0, "ts": 0.0}   # when we first hovered this pick action


def _picklog(msg, dedupe=False):
    """One line per auto-lock event. Same rule as the ban log: a pick that didn't happen must
    never be silent, because you only find out when you're staring at a random champion."""
    if dedupe and msg == _PICK_LOG_STATE["last"]:
        return
    _PICK_LOG_STATE["last"] = msg
    try:
        with open(_PICK_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# Riot summoner-spell ids. The mobility spells, in priority order: whichever of these a build
# carries goes on your preferred key (Settings -> Flash key). spell1Id is D, spell2Id is F.
FLASH_ID, GHOST_ID = 4, 6
MOBILITY_SPELLS = (FLASH_ID, GHOST_ID)

_PICKABLE = {"ids": None, "ts": 0.0}
_PICK_FAIL = {}            # (action_id, cid) -> consecutive failed lock attempts


def pickable_ids(ttl=5.0):
    """Champion ids you can ACTUALLY pick right now, or None if the client won't say.

    This is the thing that was missing and it cost a whole draft: since the recommender stopped
    gating on mastery it ranks champions on merit alone, which includes champions you don't own.
    The client refuses to complete a pick action for one of those, so auto-lock sat there
    failing every second while the timer ran out. `pickable-champion-ids` is the honest answer
    during champ select (it accounts for free rotation and bans too); owned-champions-minimal
    is the fallback outside it."""
    now = time.monotonic()
    if _PICKABLE["ids"] is not None and (now - _PICKABLE["ts"]) < ttl:
        return _PICKABLE["ids"]
    ids = None
    for path in ("/lol-champ-select/v1/pickable-champion-ids",
                 "/lol-champions/v1/owned-champions-minimal"):
        try:
            r = _lcu_json("GET", path)
        except Exception:
            continue
        if isinstance(r, list) and r:
            got = {c if isinstance(c, int) else c.get("id") for c in r}
            got = {int(c) for c in got if c}
            if got:
                ids = got
                break
    _PICKABLE.update(ids=ids, ts=now)
    return ids


def auto_pick(dd, cids):
    """If it's YOUR pick turn, hover-then-LOCK the first champion in `cids` that's still
    available (not banned, not taken by either team). Returns the locked championId or None.
    Never raises — like auto_ban, this must never be able to disrupt champ select."""
    cids = [int(c) for c in (cids or []) if c]
    if not cids:
        return None
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        return None
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        return None
    cell = sess.get("localPlayerCellId")
    action_id, hovered = None, 0
    for group in (sess.get("actions") or []):
        for a in group:
            if (a.get("actorCellId") == cell and a.get("type") == "pick"
                    and a.get("isInProgress") and not a.get("completed")):
                action_id = a.get("id")
                hovered = int(a.get("championId") or 0)   # what's on YOUR pick slot right now
    if action_id is None:
        return None                              # not your pick turn (or already locked)
    gone = set()
    b = sess.get("bans") or {}
    for c in (b.get("myTeamBans") or []) + (b.get("theirTeamBans") or []):
        if c:
            gone.add(int(c))
    for group in (sess.get("actions") or []):    # anything already LOCKED by anyone
        for a in group:
            if a.get("completed") and a.get("championId"):
                gone.add(int(a["championId"]))
    nm = (dd.get("id2name") or {}) if isinstance(dd, dict) else {}
    own = pickable_ids()
    # `is not None`, NOT truthiness: None means "the client wouldn't tell us" (don't filter),
    # an empty set means "you can pick nothing" (filter everything). Collapsing those two made
    # the guard silently do nothing in the one case it most needed to bite.
    if own is not None:                          # never try to lock a champion you don't have
        unowned = [c for c in cids if c not in own]
        if unowned:
            _picklog(f"skipping (you don't own / can't pick): "
                     f"{[nm.get(c, c) for c in unowned]}", dedupe=True)
        cids = [c for c in cids if c in own]
    # a champ the client has already refused 3x is not going to start working — drop it and
    # move down the list rather than burning the whole timer on it
    cids = [c for c in cids if _PICK_FAIL.get((action_id, c), 0) < 3]

    def _ok(c):
        return (c and c not in gone and (own is None or c in own)
                and _PICK_FAIL.get((action_id, c), 0) < 3)

    # ONCE A CHAMPION IS ON THE SLOT, THAT IS THE ONE WE LOCK.
    # We hover, then we lock what we hovered — we do not re-ask the recommender first. Read
    # from the live session rather than our own memory, so a momentarily empty pool (a network
    # blip in suggest_champs) can't wipe the commitment and restart the 2.5s timer.
    # This is what was broken: the target changed every tick, and a changed target restarts the
    # timer, so the lock was never reached. It hovered forever.
    prev = _PICK_HOVER["cid"] if _PICK_HOVER["action"] == action_id else 0
    if _ok(hovered):
        want = hovered                           # already on the slot (ours, or you moved it)
    else:
        want = prev if _ok(prev) else next((c for c in cids if c not in gone), None)
    if want is None:
        _picklog("nothing left to lock — everything on the list is banned, taken, unowned or "
                 "refused. Pick it yourself.", dedupe=True)
        return None
    label = nm.get(want, str(want))
    # Hover ONCE (not a PATCH every poll), then lock a beat later. The hover is what makes the
    # client - and our own auto-import - agree on which champion this is before it's final.
    if _PICK_HOVER["action"] != action_id or _PICK_HOVER["cid"] != want:
        _PICK_HOVER.update(action=action_id, cid=want, ts=time.monotonic())
        try:
            _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
                      {"championId": want})
        except Exception:
            pass
        _picklog(f"hovering {label} — locking in {PICK_SETTLE_S:.1f}s")
        return None
    if (time.monotonic() - _PICK_HOVER["ts"]) < PICK_SETTLE_S:
        return None
    try:
        _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
                  {"championId": want, "completed": True})
    except Exception as e:
        _picklog(f"PATCH lock {label} raised {type(e).__name__} — trying two-step")
    if _pick_completed(action_id):
        _PICK_FAIL.clear()
        _picklog(f"LOCKED {label} (action {action_id}, one-shot)")
        return want
    try:                                         # two-step: some client builds want it
        _lcu_json("PATCH", f"/lol-champ-select/v1/session/actions/{action_id}",
                  {"championId": want})
        _lcu_json("POST", f"/lol-champ-select/v1/session/actions/{action_id}/complete",
                  {"championId": want})
    except Exception as e:
        _picklog(f"two-step lock {label} raised {type(e).__name__}")
    if _pick_completed(action_id):
        _PICK_FAIL.clear()
        _picklog(f"LOCKED {label} (action {action_id}, two-step)")
        return want
    # Count the refusal and FALL THROUGH TO THE NEXT CHAMPION. v0.9.59 re-tried the same
    # champion once a second until the timer ran out (11 identical "FAILED to lock Nasus" lines,
    # then a random pick) — a client that has refused a champion three times is telling you
    # something, so believe it and move down the list.
    k = (action_id, want)
    _PICK_FAIL[k] = _PICK_FAIL.get(k, 0) + 1
    _PICK_HOVER.update(action=None, cid=0, ts=0.0)     # re-hover whatever comes next
    if _PICK_FAIL[k] >= 3:
        nxt = [nm.get(c, c) for c in cids if c != want and c not in gone]
        _picklog(f"GIVING UP on {label} after 3 refusals (you may not own it) — "
                 f"next: {nxt[:3] or 'nothing left'}")
    else:
        _picklog(f"lock {label} refused ({_PICK_FAIL[k]}/3) — retrying, then moving on")
    return None


def _pick_completed(action_id):
    """Re-read the session: did OUR pick action actually complete? A 2xx on the PATCH is not
    proof (that's the lesson the ban path already paid for)."""
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
        for group in (sess.get("actions") or []):
            for a in group:
                if a.get("id") == action_id:
                    return bool(a.get("completed"))
    except Exception:
        pass
    return False


_PICK_WATCH = {"thread": None, "cids": [], "dd": None, "on": False}


def pick_watch_update(dd, cids, enabled):
    """Same contract as ban_watch_update: the champ-select render loop refreshes this every
    poll, and a dedicated 1s thread does the actual locking. The render loop can stall for
    seconds on network work — far too slow to hit an 8s firing window."""
    # Only a DISABLED watcher resets the commitment. An empty pool must not: suggest_champs
    # does network work and can transiently return nothing, and wiping the hover state there
    # restarted the lock timer mid-draft.
    if not enabled:
        _PICK_HOVER.update(action=None, cid=0, ts=0.0)
        _PICK_FAIL.clear()
    _PICK_WATCH.update(dd=dd, cids=list(cids or []), on=bool(enabled))
    th = _PICK_WATCH.get("thread")
    if th and th.is_alive():
        return
    import threading

    def _loop():
        while True:
            try:
                if _PICK_WATCH["on"] and _PICK_WATCH["cids"]:
                    if auto_pick(_PICK_WATCH["dd"], _PICK_WATCH["cids"]):
                        time.sleep(5)            # locked; our turn is over
                time.sleep(1 if _PICK_WATCH["on"] else 2)
            except Exception:
                time.sleep(2)                    # never die: a dead watcher = a silent no-pick

    th = threading.Thread(target=_loop, daemon=True, name="smiteless-pick-watch")
    _PICK_WATCH["thread"] = th
    th.start()


_POS_SWAP_LAST = {"sid": None, "ts": 0.0}     # anti-spam for our outgoing ROLE-swap requests


def _post_pos_swap(sid, cellid, action):
    """POST a position-swap action. request/accept can key off the swap id or the holder's
    cellId depending on client version — try both; the wrong one 404s harmlessly."""
    for seg in (sid, cellid):
        if seg is None:
            continue
        try:
            _lcu_json("POST", f"/lol-champ-select/v1/session/position-swaps/{int(seg)}/{action}")
            return True
        except Exception:
            continue
    return False


def auto_accept_swap(want_roles):
    """Work the ROLE (assigned-position) swaps toward a lane you want — the autofill escape.
    `want_roles` = the app roles you'll play ('top','jungle','mid','adc','support'); empty ->
    no-op. If you're already on a wanted role, does nothing. Otherwise it ACCEPTS any incoming
    offer that lands you on a wanted role, and otherwise proactively REQUESTS a swap from a
    teammate who's ON one of your wanted roles (one live ask, 10s anti-spam). It only ever
    moves you ONTO a wanted role, never off one. Returns a short status ('jungle' /
    'ask jungle') or None. Never raises — must not disrupt champ select. (LCU: positionSwaps.)"""
    want = [r for r in (want_roles or []) if r]
    if not want:
        return None
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        return None
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        return None
    swaps = sess.get("positionSwaps") or []
    if not swaps:
        return None
    local = sess.get("localPlayerCellId")
    pos_of, my_pos = {}, ""
    for m in (sess.get("myTeam") or []):
        role = lg.ROLE.get((m.get("assignedPosition") or "").lower(), "")
        pos_of[m.get("cellId")] = role
        if m.get("cellId") == local:
            my_pos = role
    if not my_pos or my_pos in want:
        return None                              # no assigned role (blind/ARAM), or already happy

    # 1) ACCEPT an incoming offer that lands you on a wanted role.
    for s in swaps:
        if s.get("state") != "RECEIVED":
            continue
        their = pos_of.get(s.get("cellId"), "")
        if their and their in want:
            return their if _post_pos_swap(s.get("id"), s.get("cellId"), "accept") else None

    # 2) Otherwise REQUEST a swap from a teammate who's ON a wanted role (want-order preference).
    for role in want:
        cell = next((c for c, r in pos_of.items() if r == role and c != local), None)
        if cell is None:
            continue
        s = next((x for x in swaps if x.get("cellId") == cell), None)
        if not s or s.get("state") not in (None, "AVAILABLE"):
            continue                             # already SENT/BUSY/DECLINED -> leave it
        sid = s.get("id")
        now = time.time()
        if _POS_SWAP_LAST["sid"] == sid and now - _POS_SWAP_LAST["ts"] < 10:
            return None                          # don't hammer the same teammate
        _POS_SWAP_LAST.update(sid=sid, ts=now)
        return f"ask {role}" if _post_pos_swap(sid, cell, "request") else None
    return None


_PICK_SWAP_LAST = {"sid": None, "ts": 0.0}    # anti-spam for our outgoing pick-order requests


def _post_pick_swap(sid, action):
    """POST a pick-order-swap action. The LCU has shipped TWO spellings for this path across
    patches (/session/swaps/ and /session/pick-order-swaps/), so try both — the wrong one just
    404s harmlessly. Returns True on success."""
    for base in ("swaps", "pick-order-swaps"):
        try:
            _lcu_json("POST", f"/lol-champ-select/v1/session/{base}/{int(sid)}/{action}")
            return True
        except Exception:
            continue
    return False


def auto_pick_order_swap(target):
    """Handle champ-select PICK ORDER swaps. `target`:
      'any'         -> just ACCEPT every incoming pick-order request (no direction, no asking).
      'first'/'last'-> pick as early / late as possible (last = counter-pick).
      '1'..'5'      -> seek that exact pick slot (clamped to the lobby size); '4'/'5' let you
                       pick near the end without insisting on dead-last.
      '' / anything else = off.
    Accepts an incoming offer that moves you closer to the target, otherwise requests a swap
    toward it. Returns a short status string or None. Never raises — must not disrupt champ
    select. (LCU: pickOrderSwaps in the session.)"""
    target = str(target).strip().lower()
    if target not in ("any", "first", "last") and not (target.isdigit() and target != "0"):
        return None
    try:
        sess = _lcu_json("GET", "/lol-champ-select/v1/session")
    except Exception:
        return None
    if not isinstance(sess, dict) or sess.get("localPlayerCellId") is None:
        return None
    local = sess.get("localPlayerCellId")
    team_cells = {m.get("cellId") for m in (sess.get("myTeam") or [])}
    # Pick slots 1..N for our team, from the ORDER of pick actions in the session.
    order, done = [], False
    for grp in (sess.get("actions") or []):
        for a in grp:
            if a.get("type") == "pick" and a.get("actorCellId") in team_cells:
                c = a.get("actorCellId")
                if c not in order:
                    order.append(c)
                if c == local and a.get("completed"):
                    done = True                  # you've already locked -> swapping is moot
    pos = {c: i + 1 for i, c in enumerate(order)}
    my_pos = pos.get(local)
    if done:
        return None
    swaps = sess.get("pickOrderSwaps") or []

    if target == "any":                          # simplest mode: accept EVERY incoming request
        for s in swaps:
            if s.get("state") == "RECEIVED":
                return (f"pick {pos.get(s.get('cellId'), '?')}"
                        if _post_pick_swap(s.get("id"), "accept") else None)
        return None

    if not my_pos or len(order) < 2:
        return None
    # Resolve the desired slot number, clamped to the actual lobby size.
    if target == "first":
        want = 1
    elif target == "last":
        want = len(order)
    else:
        want = max(1, min(len(order), int(target)))
    if my_pos == want:
        return None                              # already where you want to be
    # A slot is "better" if it's strictly closer to the target than where you are now.
    dist = lambda p: abs(p - want)
    better = lambda p: p and dist(p) < dist(my_pos)

    # 1) Accept the incoming offer that lands you CLOSEST to the target (among those that help).
    incoming = [(pos.get(s.get("cellId")), s) for s in swaps if s.get("state") == "RECEIVED"]
    incoming = [(tp, s) for tp, s in incoming if better(tp)]
    if incoming:
        tp, s = min(incoming, key=lambda t: dist(t[0]))
        return f"pick {tp}" if _post_pick_swap(s.get("id"), "accept") else None

    # 2) Otherwise request a swap toward the available slot CLOSEST to the target.
    cands = sorted(((pos.get(s.get("cellId")), s) for s in swaps if s.get("state") == "AVAILABLE"),
                   key=lambda t: (dist(t[0]) if t[0] else 99))
    cands = [(tp, s) for tp, s in cands if better(tp)]
    if cands:
        tp, s = cands[0]
        sid, now = s.get("id"), time.time()
        if _PICK_SWAP_LAST["sid"] == sid and now - _PICK_SWAP_LAST["ts"] < 12:
            return None                          # don't hammer the same holder
        _PICK_SWAP_LAST.update(sid=sid, ts=now)
        return f"asked pick {tp}" if _post_pick_swap(sid, "request") else None
    return None


def import_build(dd, cid, role, build):
    """Push `build`'s runes + summoners for cid/role into the client. Returns a status
    string; raises RuntimeError with a friendly message on anything expected."""
    if not cid:
        raise RuntimeError("lock a champion first")
    if not build:
        raise RuntimeError("no op.gg build for this champ/role yet")
    perks = (build.get("primary_ids") or []) + (build.get("secondary_ids") or []) + (build.get("stat_mod_ids") or [])
    if len(perks) < 9:
        raise RuntimeError("rune data incomplete")
    page = {
        "name": f"Smiteless {dd['id2name'].get(cid, 'Champ')} {str(role or '').title()}",
        "primaryStyleId": int(build.get("primary_page_id") or 0),
        "subStyleId": int(build.get("secondary_page_id") or 0),
        "selectedPerkIds": [int(x) for x in perks[:9]],
        "current": True,
    }
    try:
        _lcu_json("POST", "/lol-perks/v1/pages", page)
    except Exception:
        pages = _lcu_json("GET", "/lol-perks/v1/pages") or []
        editable = [p for p in pages if p.get("isEditable", True)]
        target = None
        for p in editable:
            if (p.get("name") or "").startswith("Smiteless "):
                target = p
                break
        if target is None:
            target = next((p for p in editable if p.get("current")), None)
        if target is None and editable:
            target = editable[0]
        if not target or not target.get("id"):
            raise RuntimeError("rune page limit reached and no editable page is available")
        up = dict(page)
        up["id"] = int(target["id"])
        _lcu_json("PUT", f"/lol-perks/v1/pages/{int(target['id'])}", up)
    sums = build.get("summoner_ids") or []
    if len(sums) >= 2:
        s1, s2 = int(sums[0]), int(sums[1])
        flash_on_d = cfg.load().get("flash_on_d", True)
        # Your ESCAPE key never moves. Flash owns the preferred slot; on a build that has no
        # Flash, GHOST inherits it — same finger, same panic button. Ghost-only builds used to
        # land wherever op.gg happened to order them, which is the one spell you cannot afford
        # to hunt for. If a build somehow runs both, Flash wins and Ghost takes the other slot.
        key_spell = next((sp for sp in MOBILITY_SPELLS if sp in (s1, s2)), None)
        if key_spell is not None and (s1 == key_spell) != bool(flash_on_d):
            s1, s2 = s2, s1
        _lcu_json("PATCH", "/lol-champ-select/v1/session/my-selection",
                  {"spell1Id": s1, "spell2Id": s2})
    return tf("imported for {champ} ({role})",
              champ=dd["id2name"].get(cid, "?"), role=role)
