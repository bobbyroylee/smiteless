#!/usr/bin/env python3
"""lolgame.py — resolve the CURRENT game's champs/roles from whatever source is
live, so Win+B works in champ select, on the loading screen, AND in-game.

Priority (richest data first):
  1. LCU champ-select session   -> champ select (incl. post-lock 15s finalization)
  2. Live Client Data API :2999 -> in-game (champ names + teams + ranked roles)
  3. LCU gameflow session       -> loading screen (champ-select endpoint is dead)

Returns champ IDs uniformly: dict(my, pos, allies=[(cid,pos)], enemies=[cid],
phase, source) or (None, error_message). Role is cached per-champ so a
loading-screen press (gameflow exposes no role) can recover the role picked in
champ select / seen in-game.
"""
import os, json, base64, time, string, urllib.error
import lolbuild as lb  # reuse http(), ROLE, LOCKFILES, UA

ROLE = lb.ROLE
ROLECACHE = os.path.expanduser("~/.claude/cache/lolrole.json")


def _lockfile():
    lf = next((p for p in lb.LOCKFILES if os.path.exists(p)), None)
    if not lf:
        for d in string.ascii_uppercase:
            p = f"{d}:\\Riot Games\\League of Legends\\lockfile"
            if os.path.exists(p):
                lf = p
                break
    return lf


def _lcu():
    """(port, headers) for the local LCU, or None if the client isn't running."""
    lf = _lockfile()
    if not lf:
        return None
    try:
        _name, _pid, port, pw, _proto = open(lf).read().split(":")
    except Exception:
        return None
    auth = base64.b64encode(f"riot:{pw}".encode()).decode()
    hdr = {"Authorization": f"Basic {auth}", "Accept": "application/json", "User-Agent": lb.UA}
    return port, hdr


def current_account():
    """(puuid, 'Name#TAG') for the logged-in account via the LCU, or None. Used to auto-
    remember every account the user plays on, so familiarity can pool across them."""
    lc = _lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        d = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
                    headers=hdr, timeout=4, insecure=True)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    gn, tl = (d.get("gameName") or "").strip(), (d.get("tagLine") or "").strip()
    rid = f"{gn}#{tl}" if gn and tl else ""
    if not rid or "#" not in rid:
        return None
    return d.get("puuid"), rid


_MASTERY_CACHE = {"ts": 0.0, "data": {}, "pts": {}}


def my_mastery(ttl=300):
    """{championId: masteryLevel} for the LOCAL player, straight from the LCU — no Riot API
    key, no rate limit, one call. Cached ~5 min (mastery barely moves within a session). {}
    if the client's closed or the call fails. Level (not points) so callers can gate on 'M5+'."""
    now = time.time()
    if _MASTERY_CACHE["data"] and now - _MASTERY_CACHE["ts"] < ttl:
        return _MASTERY_CACHE["data"]
    lc = _lcu()
    if not lc:
        return _MASTERY_CACHE["data"]            # keep last-known through a client blip
    port, hdr = lc
    try:
        rows = lb.http(f"https://127.0.0.1:{port}/lol-champion-mastery/v1/local-player/champion-mastery",
                       headers=hdr, timeout=4, insecure=True)
    except Exception:
        return _MASTERY_CACHE["data"]
    out, pts = {}, {}
    for r in (rows or []):
        cid = r.get("championId")
        if cid:
            out[cid] = r.get("championLevel", 0) or 0
            pts[cid] = r.get("championPoints", 0) or 0
    if out:
        _MASTERY_CACHE["data"] = out
        _MASTERY_CACHE["pts"] = pts
        _MASTERY_CACHE["ts"] = now
    return out


def my_mastery_points(ttl=300):
    """{championId: masteryPoints} for the LOCAL player — same LCU call/cache as my_mastery.
    Points matter for the climb math: a 1M-game study puts sub-12k-point picks at ~44% win
    rate vs 51%+ beyond it, the single largest self-inflicted WR leak."""
    my_mastery(ttl)
    return dict(_MASTERY_CACHE.get("pts") or {})


def champselect_allies():
    """Riot IDs of your TEAMMATES in the current champ select, via the Riot Client's chat
    participants endpoint (the Porofessor method): ['Name#TAG', ...]. [] outside champ
    select / on any failure. Enemies are anonymized by Riot — allies only."""
    try:
        lf = os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\Riot Client\Config\lockfile")
        _n, _p, port, pw, _proto = open(lf).read().split(":")
        out = lb.http(f"https://127.0.0.1:{port}/chat/v5/participants",
                      headers={"Authorization": "Basic " +
                               __import__("base64").b64encode(f"riot:{pw}".encode()).decode()},
                      timeout=4, insecure=True)
        rids = []
        for p in (out.get("participants") or []):
            if "champ-select" in (p.get("cid") or "") and p.get("game_name"):
                rids.append(f"{p['game_name']}#{p.get('game_tag', '')}")
        return rids
    except Exception:
        return []


def save_role(cid, pos):
    if not (cid and pos):
        return
    try:
        os.makedirs(os.path.dirname(ROLECACHE), exist_ok=True)
        json.dump({"champ": cid, "pos": pos, "ts": time.time()}, open(ROLECACHE, "w"))
    except Exception:
        pass


def load_role(cid):
    try:
        d = json.load(open(ROLECACHE))
        if d.get("champ") == cid and time.time() - d.get("ts", 0) < 7200:
            return d.get("pos") or ""
    except Exception:
        pass
    return ""


def _cid(dd, name):
    return dd["name2id"].get(dd["norm"](name or "")) or 0


def _gname(s):
    return (s or "").split("#")[0].strip().lower()


# ---------- source 1: champ select ----------
def _from_champ_select(dd):
    lc = _lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        s = lb.http(f"https://127.0.0.1:{port}/lol-champ-select/v1/session",
                    headers=hdr, timeout=4, insecure=True)
    except Exception:
        return None
    local = s.get("localPlayerCellId")
    mine = next((m for m in s.get("myTeam", []) if m.get("cellId") == local), None)
    if mine is None:
        return None
    my = mine.get("championId", 0) or mine.get("championPickIntent", 0)  # show hovered champ pre-lock
    pos = ROLE.get((mine.get("assignedPosition") or "").lower(), "")
    allies = [(m.get("championId", 0) or m.get("championPickIntent", 0),
               ROLE.get((m.get("assignedPosition") or "").lower(), ""))
              for m in s.get("myTeam", [])]
    enemies = [(e.get("championId", 0), ROLE.get((e.get("assignedPosition") or "").lower(), ""))
               for e in s.get("theirTeam", []) if e.get("championId", 0) > 0]
    # bans (both teams). The session's bans block is authoritative; fall back to completed
    # ban actions (some queues only fill the actions list).
    bans_my, bans_their = [], []
    b = s.get("bans") or {}
    bans_my = [c for c in (b.get("myTeamBans") or []) if c]
    bans_their = [c for c in (b.get("theirTeamBans") or []) if c]
    if not (bans_my or bans_their):
        my_cells = {m.get("cellId") for m in s.get("myTeam", [])}
        for group in (s.get("actions") or []):
            for a in group:
                if a.get("type") == "ban" and a.get("completed") and a.get("championId", 0) > 0:
                    (bans_my if a.get("actorCellId") in my_cells else bans_their).append(a["championId"])
    if not my:
        return dict(my=0, pos=pos, allies=allies, enemies=enemies,
                    bans_my=bans_my, bans_their=bans_their,
                    phase="ChampSelect", source="champ select", err="not_locked")
    save_role(my, pos)
    return dict(my=my, pos=pos, allies=allies, enemies=enemies,
                bans_my=bans_my, bans_their=bans_their,
                locked=bool(mine.get("championId", 0)),   # locked in, not just hovering
                phase="ChampSelect", source="champ select")


# ---------- source 2: live client (in-game) ----------
def _from_live_client(dd):
    try:
        d = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata",
                    timeout=3, insecure=True)
    except Exception:
        return None
    players = d.get("allPlayers") or []
    if not players:
        return None
    ap = d.get("activePlayer") or {}
    me_name = ap.get("riotId") or ""
    if not me_name:
        gn = ap.get("riotIdGameName") or ap.get("summonerName") or ""
        tl = ap.get("riotIdTagLine") or ""
        me_name = f"{gn}#{tl}" if tl else gn
    myg = _gname(me_name)

    def pg(p):
        return _gname(p.get("riotId") or p.get("summonerName") or p.get("riotIdGameName", ""))

    def pos_of(p):
        return ROLE.get((p.get("position") or "").lower(), "")

    me = next((p for p in players if pg(p) == myg), None) if myg else None
    if me is None:
        # SPECTATOR / REPLAY: no active player. Show both teams (ORDER = "your" side) with
        # no designated "me" so the board, scout, ranks + mastery all still populate.
        allies = [(_cid(dd, p.get("championName", "")), pos_of(p))
                  for p in players if p.get("team") == "ORDER"]
        enemies = [(_cid(dd, p.get("championName", "")), pos_of(p))
                   for p in players if p.get("team") == "CHAOS" and _cid(dd, p.get("championName", ""))]
        if not (allies and enemies):
            return None
        return dict(my=0, pos="", allies=allies, enemies=enemies,
                    phase="InProgress", source="replay")
    myteam = me.get("team")

    my = _cid(dd, me.get("championName", ""))
    pos = pos_of(me) or load_role(my)
    allies = [(_cid(dd, p.get("championName", "")), pos_of(p))
              for p in players if p.get("team") == myteam]
    enemies = [(_cid(dd, p.get("championName", "")), pos_of(p))
               for p in players if p.get("team") != myteam and _cid(dd, p.get("championName", ""))]
    save_role(my, pos)
    return dict(my=my, pos=pos, allies=allies, enemies=enemies,
                phase="InProgress", source="live game")


# ---------- source 3: gameflow (loading screen) ----------
def _from_gameflow(dd):
    lc = _lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        s = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/session",
                    headers=hdr, timeout=4, insecure=True)
    except Exception:
        return None
    phase = s.get("phase", "") or ""
    gd = s.get("gameData") or {}
    t1, t2 = gd.get("teamOne") or [], gd.get("teamTwo") or []
    if not (t1 or t2):
        return None
    mypuuid = ""
    try:
        cs = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
                     headers=hdr, timeout=4, insecure=True)
        mypuuid = cs.get("puuid", "")
    except Exception:
        pass
    myteam = other = None
    me = None
    for team, opp in ((t1, t2), (t2, t1)):
        for p in team:
            if mypuuid and p.get("puuid") == mypuuid:
                myteam, other, me = team, opp, p
                break
        if me:
            break
    if me is None:
        return None
    my = me.get("championId", 0)
    pos = load_role(my)  # gameflow exposes no role; recover from cache if we have it
    allies = [(p.get("championId", 0), "") for p in myteam]
    enemies = [(p.get("championId", 0), "") for p in other if p.get("championId", 0) > 0]
    if pos:
        save_role(my, pos)
    return dict(my=my, pos=pos, allies=allies, enemies=enemies,
                phase=phase or "Loading", source="loading screen")


def resolve(dd, allow_unlocked=False):
    """Return (info, None) or (None, error). Tries each source by phase priority.
    allow_unlocked: in champ select, return the board even before you've hovered a champ
    (my=0) instead of erroring — the overlay uses this so the panel appears immediately."""
    info = _from_champ_select(dd)
    if info:
        if info.get("err") == "not_locked" and not allow_unlocked:
            return None, "In champ select but you haven't locked a champ yet."
        return info, None
    for fn in (_from_live_client, _from_gameflow):
        info = fn(dd)
        # accept if we found "you" (my>0) OR a spectator/replay board (both teams, my=0)
        if info and (info.get("my") or (info.get("allies") and info.get("enemies"))):
            return info, None
    return None, ("No live game found — open champ select, be on the loading screen / "
                  "in-game, or watch a replay (all work).")


def coach_snapshot(dd, info=None):
    """Bounded draft/loading shape for the coach; never exposes account identifiers."""
    if info is None:
        info, _err = resolve(dd, allow_unlocked=True)
    if not info:
        return None

    def champion(cid):
        try:
            return (dd.get("id2name") or {}).get(int(cid)) or "unknown"
        except (TypeError, ValueError):
            return "unknown"

    def slots(rows):
        out = []
        ally_n = 0
        for row in (rows or [])[:5]:
            cid, role = (row if isinstance(row, (list, tuple)) else (row, ""))[:2]
            is_self = not any(item.get("slot") == "self" for item in out) and (
                cid == info.get("my") and (not info.get("pos") or role == info.get("pos")))
            if not is_self:
                ally_n += 1
            out.append({"slot": "self" if is_self else f"ally_{ally_n}",
                        "champion": champion(cid), "role": str(role or "")[:12]})
        return out

    def enemies(rows):
        return [{**row, "slot": f"enemy_{index}"}
                for index, row in enumerate(slots(rows), 1)]

    snap = {
        "role": str(info.get("pos") or "")[:12],
        "self_champion": champion(info.get("my")),
        "allies": slots(info.get("allies")),
        "enemies": enemies(info.get("enemies")),
        "source": str(info.get("source") or "")[:32],
    }
    mastery = _MASTERY_CACHE.get("data") or {}
    points = _MASTERY_CACHE.get("pts") or {}
    if info.get("my") in mastery or info.get("my") in points:
        snap["self_mastery"] = {"level": mastery.get(info.get("my"), 0),
                                "points": points.get(info.get("my"), 0)}
    if info.get("phase") == "ChampSelect":
        snap.update({
            "locked": bool(info.get("locked")),
            "ally_bans": [champion(cid) for cid in (info.get("bans_my") or [])[:5]],
            "enemy_bans": [champion(cid) for cid in (info.get("bans_their") or [])[:5]],
        })
    return snap


def coach_lifecycle():
    """Best-effort stable lobby/game identifiers; credentials never leave this function."""
    lc = _lcu()
    if not lc:
        return {}
    port, hdr = lc
    hints = {}
    try:
        session = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/session",
                          headers=hdr, timeout=1, insecure=True) or {}
        game = session.get("gameData") or {}
        if game.get("gameId") not in (None, ""):
            hints["game_id"] = game["gameId"]
    except Exception:
        pass
    if not hints:
        try:
            lobby = lb.http(f"https://127.0.0.1:{port}/lol-lobby/v2/lobby",
                            headers=hdr, timeout=1, insecure=True) or {}
            if lobby.get("partyId"):
                hints["lobby_id"] = lobby["partyId"]
        except Exception:
            pass
    return hints
