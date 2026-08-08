#!/usr/bin/env python3
"""lolload.py - the LOADING-SCREEN brief: know the players AND the matchup before the game.

The loading screen is the first time everyone's IGN is exposed, so it's the first time you can
actually scout the lobby. Riot hands out placeholder puuids in the gameflow session, but each
player carries a real summonerId -> the LCU resolves that to a real Name#TAG -> the Riot API
resolves THAT to a real puuid -> full scout (rank, recent form, one-trick, mastery). Champ
select just cached all of it, so it's near-instant here.

So the brief carries both: per-player SCOUT tags (rank, hot/tilted streak, OTP, off-champ) and
per-champ good/bad tags + a plain game-plan for the comp. All read-only off the local client
and the user's own Riot key.
"""
import os, json, time, hashlib, threading
import concurrent.futures as _futures

import lolgame as lg
import lolbuild as lb
import loltags as ltag
import lolscout as ls
from smitei18n import t, tf

_ROLE = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "MID": "MID", "BOTTOM": "BOT",
         "BOT": "BOT", "UTILITY": "SUP", "SUPPORT": "SUP"}
_TIER = {"IRON": "Iron", "BRONZE": "Bronze", "SILVER": "Silver", "GOLD": "Gold",
         "PLATINUM": "Plat", "EMERALD": "Emerald", "DIAMOND": "Diamond", "MASTER": "Master",
         "GRANDMASTER": "GM", "CHALLENGER": "Chall"}


def _ign_for(port, hdr, sid):
    """(riot_id, summoner_level) for a summonerId. The LCU summoner blob already carries
    summonerLevel, so the new-account / smurf evidence is free on the loading path."""
    if not sid:
        return "", None
    try:
        r = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/summoners/{sid}",
                    headers=hdr, timeout=4, insecure=True)
        gn, tl = r.get("gameName", ""), r.get("tagLine", "")
        lvl = int(r.get("summonerLevel") or 0) or None
        return (f"{gn}#{tl}" if gn and tl else ""), lvl
    except Exception:
        return "", None


def _timed_lcu(label, url, hdr, timeout, on_timing=None):
    started = time.monotonic()
    outcome = "ok"
    try:
        return lb.http(url, headers=hdr, timeout=timeout, insecure=True)
    except Exception as exc:
        outcome = type(exc).__name__
        raise
    finally:
        if on_timing:
            try:
                on_timing(label, time.monotonic() - started, outcome)
            except Exception:
                pass


def current_summoner_id(request_timeout=2.0, on_timing=None):
    """Read the local summoner id early so Loading only waits for the roster session."""
    lc = lg._lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        current = _timed_lcu(
            "current-summoner",
            f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
            hdr, request_timeout, on_timing,
        )
        return current.get("summonerId")
    except Exception:
        return None


def _roster(mysid=None, request_timeout=4.0, on_timing=None):
    """(my_rows, enemy_rows, (port, hdr)) or None. Each row: {sid, champ_id, role, me}."""
    lc = lg._lcu()
    if not lc:
        return None
    port, hdr = lc
    session_url = f"https://127.0.0.1:{port}/lol-gameflow/v1/session"
    current_url = f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner"
    if mysid is None:
        # Both reads are independent.  Running them together caps the cold path at one timeout
        # instead of the eight-second sequence that outlived fast Loading screens.
        with _futures.ThreadPoolExecutor(max_workers=2) as ex:
            session_future = ex.submit(
                _timed_lcu, "gameflow-session", session_url, hdr,
                request_timeout, on_timing,
            )
            current_future = ex.submit(
                _timed_lcu, "current-summoner", current_url, hdr,
                request_timeout, on_timing,
            )
            try:
                s = session_future.result()
            except Exception:
                s = None
            try:
                current = current_future.result()
                mysid = current.get("summonerId")
            except Exception:
                pass
    else:
        try:
            s = _timed_lcu("gameflow-session", session_url, hdr,
                           request_timeout, on_timing)
        except Exception:
            s = None
    if not s:
        return None
    gd = (s or {}).get("gameData") or {}
    t1, t2 = gd.get("teamOne") or [], gd.get("teamTwo") or []
    if not (t1 and t2):
        return None
    mine = t1 if any(p.get("summonerId") == mysid for p in t1) else \
        (t2 if any(p.get("summonerId") == mysid for p in t2) else t1)
    other = t2 if mine is t1 else t1

    def rows(team):
        out = []
        for p in team:
            if p.get("championId"):
                out.append({"sid": p.get("summonerId"), "champ_id": int(p["championId"]),
                            "role": _ROLE.get((p.get("selectedPosition") or "").upper(), ""),
                            "me": p.get("summonerId") == mysid})
        return out
    return rows(mine), rows(other), (port, hdr)


def _player_scout(dd, puuid, cid, key, riot_id=None):
    """Full per-ACCOUNT read for the loading scoreboard: solo rank (+LP, season W/L),
    last-10 form, recent + this-champ record, pooled KDA, deaths/game, avg performance
    score (how they actually play), mastery on this champ, their MAIN role over the last
    10 games, and the recent match ids. `riot_id` lets the
    scout fall back to u.gg when Riot's match history is down (see lolscout.scout)."""
    out = {"rank_full": None, "pts": 0, "mlevel": 0, "n": 0, "w": 0, "cg": 0, "cw": 0,
           "form": [], "kdar": None, "kavg": "", "dpg": None, "perf": None,
           "main_pos": "", "mids": [], "recent": []}
    # rank / match history / mastery hit three different Riot endpoints and don't need each
    # other — firing them together turns this player's read into ONE round-trip's latency
    # instead of three stacked ones.
    with _futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_rank = ex.submit(ls.rank, puuid, key)
        f_scout = ex.submit(ls.scout, dd, puuid, cid, key, 10, riot_id=riot_id)
        f_mast = ex.submit(ls.mastery, puuid, cid, key)
        try:
            out["rank_full"] = f_rank.result()
        except Exception:
            pass
        try:
            n, w, cg, cw, form, mids, kda, perf, recent = f_scout.result()
            out.update(n=n, w=w, cg=cg, cw=cw, form=form, mids=mids or [], perf=perf,
                       recent=recent or [])
            g = (kda or {}).get("g", 0)
            if g:
                out["kdar"] = round((kda["k"] + kda["a"]) / max(1, kda["d"]), 1)
                out["kavg"] = f"{kda['k'] / g:.1f} / {kda['d'] / g:.1f} / {kda['a'] / g:.1f}"
                out["dpg"] = round(kda["d"] / g, 1)
        except Exception:
            pass
        try:
            m = f_mast.result() or {}
            out["pts"], out["mlevel"] = int(m.get("points", 0)), int(m.get("level", 0))
        except Exception:
            pass
    out["main_pos"] = _main_pos(out["recent"])
    return out


def _main_pos(recent):
    """Their real position over the recent games (from the same match reads) — a main is a
    position holding at least max(3, half) of the sample, anything less is noise."""
    posc = {}
    for _c, _w, pos in recent or []:
        if pos:
            posc[pos] = posc.get(pos, 0) + 1
    if not posc:
        return ""
    best = max(posc, key=posc.get)
    if posc[best] >= max(3, (sum(posc.values()) + 1) // 2):
        return _ROLE.get(best.upper(), "")
    return ""


def _profile_tags(row, ally):
    """The profile-read tags, per docs/TAGS.md: every tag is a CLAIM whose EVIDENCE is cited
    in the pill text itself — no evidence, no tag. THIS-GAME reads (what to expect on the
    champ they locked TODAY) render before ACCOUNT reads (who the account is), because a
    Morgana one-trick can be a Brand feeder in the same lobby and the tag must say which.
    Tone is relative to YOU: an enemy on a loss streak is 'good' (for you).
    Inferences (smurf?) always carry a '?'; facts (new account · lvl 34) don't."""
    this_game, account = [], []

    def tone(good_for_them):
        return ("good" if good_for_them else "bad") if ally else ("bad" if good_for_them else "good")

    rk = row.get("rank_full") or {}
    sg = int(rk.get("w", 0) or 0) + int(rk.get("l", 0) or 0)
    swr = round(rk["w"] / sg * 100) if sg else None
    form, n, w = row.get("form") or [], row.get("n", 0), row.get("w", 0)
    pts, cg, cw = row.get("pts", 0), row.get("cg", 0), row.get("cw", 0)
    perf, dpg, champ = row.get("perf"), row.get("dpg"), row.get("champ", "?")
    level, recent = row.get("level"), row.get("recent") or []

    # their dominant RECENT champ (evidence for off-champ + heater attribution)
    champc = {}
    for cname, _win, _pos in recent:
        champc[cname] = champc.get(cname, 0) + 1
    top_champ, top_n = ("", 0)
    if champc:
        top_champ = max(champc, key=champc.get)
        top_n = champc[top_champ]

    # ---- THIS-GAME reads: the champ they locked today ----
    if row.get("scouted") and pts < 6000 and cg == 0:
        text = (tf("first {champ}? · {points}k pts, 0 of last {games}",
                   champ=champ, points=pts // 1000, games=n) if n
                else tf("first {champ}? · {points}k pts",
                        champ=champ, points=pts // 1000))
        this_game.append((text, tone(False)))
    if (n >= 8 and cg <= 1 and top_champ and top_n * 2 >= n
            and top_champ != champ):
        this_game.append((tf("off-champ · {count} of last {games} on {champ}",
                             count=top_n, games=n, champ=top_champ), tone(False)))
    if cg >= 4 and cw / cg <= 0.35:
        this_game.append((tf("cold on {champ} · {wins}-{losses} recent",
                             champ=champ, wins=cw, losses=cg - cw), tone(False)))
    elif cg >= 5:
        this_game.append((tf("comfort · {wins}-{losses} on {champ}",
                             wins=cw, losses=cg - cw, champ=champ), tone(cw * 2 >= cg)))
    if pts >= 250_000:
        this_game.append((tf("{champ} OTP · {points}k pts",
                             champ=champ, points=pts // 1000), tone(True)))
    elif pts >= 100_000:
        this_game.append((tf("{champ} main · {points}k pts",
                             champ=champ, points=pts // 1000), tone(True)))

    # ---- ACCOUNT reads: who this account is ----
    # smurf?: experienced player on a NEW account. Level is the load-bearing evidence
    # (ranked unlocks at 30; real smurfs sit in the fresh 30-60 band). No level -> no tag.
    smurfish = (level is not None and level <= 60 and n >= 8 and w / n >= 0.70
                and ((perf is not None and perf >= 75) or (cg >= 3 and cw / cg >= 0.7)))
    if smurfish:
        ev = tf("lvl {level} · {wins}-{losses}", level=level, wins=w, losses=n - w)
        if perf is not None and perf >= 75:
            ev += tf(" · {performance} perf", performance=int(perf))
        account.append((tf("smurf? · {evidence}", evidence=ev), tone(True)))
    elif level is not None and level <= 60:
        account.append((tf("new account · lvl {level}", level=level), "neutral"))
    elif 0 < sg <= 25:
        account.append((tf("fresh ranked · {games} games this season", games=sg), "neutral"))
    # live streak, with champ attribution: a heater earned on a different champ than
    # today's is context, not a threat read on this pick
    if form:
        lead = 1
        while lead < len(form) and form[lead] == form[0]:
            lead += 1
        if lead >= 3:
            if form[0]:
                streak_champs = [c for c, _w2, _p in recent[:lead]]
                on_one = (streak_champs and streak_champs.count(max(
                    set(streak_champs), key=streak_champs.count)) * 10 >= 7 * len(streak_champs))
                hot = max(set(streak_champs), key=streak_champs.count) if on_one else ""
                if hot and hot != champ:
                    account.append((tf("{count}W heater · on {champ}",
                                       count=lead, champ=hot), "neutral"))
                else:
                    account.append((tf("{count}W heater", count=lead), tone(True)))
            else:
                account.append((tf("{count}L skid · tilt risk", count=lead), tone(False)))
    # autofill / off-role
    mp = row.get("main_pos")
    if mp and row.get("role") and mp != row["role"]:
        account.append((tf("off-role · {role} main", role=mp), tone(False)))
    # how they die (or don't)
    if dpg is not None and n >= 5:
        if dpg >= 6.5:
            account.append((tf("bleeds · {deaths} deaths/game", deaths=dpg), tone(False)))
        elif dpg <= 2.6:
            account.append((tf("hard to kill · {deaths} deaths/game", deaths=dpg), tone(True)))
    # how they actually play, independent of W/L (the sanctioned quality read)
    if perf is not None and not smurfish:
        if perf >= 85:
            account.append((tf("carries · {performance} avg perf",
                               performance=int(perf)), tone(True)))
        elif perf <= 45:
            account.append((tf("passenger · {performance} perf",
                               performance=int(perf)), tone(False)))
    # season shape
    if sg >= 400:
        account.append((tf("grinder · {games} ranked this season", games=sg), "neutral"))
    if swr is not None and sg >= 100:
        if swr >= 55:
            account.append((tf("climbing · {winrate}% season", winrate=swr), tone(True)))
        elif swr <= 45:
            account.append((tf("hardstuck · {winrate}% season", winrate=swr), tone(False)))
    return this_game + account


def _comp_read(dd, rows):
    ad = ap = divers = tanks = scalers = 0
    for r in rows:
        cid = r["champ_id"]
        dt = ltag.dmg_type(dd, cid)
        ad += dt in ("AD", "mixed")
        ap += dt in ("AP", "mixed")
        tags = dd.get("id2tags", {}).get(cid, []) or []
        divers += "Assassin" in tags
        tanks += "Tank" in tags
        if "Marksman" in tags or dd.get("id2name", {}).get(cid) in ("Kassadin", "Vayne", "Jax", "Kayle"):
            scalers += 1
    return {"ad": ad, "ap": ap, "divers": divers, "tanks": tanks, "scalers": scalers}


def _plan(dd, my, en):
    ec, mc = _comp_read(dd, en), _comp_read(dd, my)
    out = []
    if ec["ad"] >= 3 and ec["ap"] <= 1:
        out.append(t("Enemy is AD-heavy — rush armor / Seeker's, Randuin's on tanks."))
    elif ec["ap"] >= 3 and ec["ad"] <= 1:
        out.append(t("Enemy is AP-heavy — build MR / Maw / Hexdrinker early."))
    if ec["divers"] >= 2:
        out.append(tf("{count} assassins — respect level 6, group, buy Zhonya's/GA, ward flanks.",
                      count=ec["divers"]))
    if mc["scalers"] >= 2 and ec["divers"] + ec["tanks"] <= mc["scalers"]:
        out.append(t("You out-scale — survive the early game, don't coinflip, win the late."))
    elif ec["scalers"] >= 2:
        out.append(t("They out-scale — force early tempo and objectives, end before 3 items."))
    if ec["tanks"] >= 2:
        out.append(t("Two+ tanks — buy % HP / armor-pen; don't waste burst on the frontline."))
    return out[:4] or [t("Even comps — play your matchup, track the enemy jungler, trade objectives.")]


def _wincons(dd, my, en):
    """The pre-game WIN/LOSE condition pair (§5): the one thing the loading screen can say
    that the live board doesn't — how this specific comp matchup is won and thrown."""
    mc, ec = _comp_read(dd, my), _comp_read(dd, en)
    if mc["scalers"] > ec["scalers"]:
        return {"win": t("drag it late — farm, stall, don't coinflip; you out-scale at 3 items"),
                "lose": t("bleeding early kills before your spikes come online")}
    if ec["scalers"] > mc["scalers"]:
        return {"win": t("end before 25 — turn every kill into towers and objectives"),
                "lose": t("letting it go late — their comp outgrows yours")}
    if mc["divers"] > ec["divers"]:
        return {"win": t("force fights and picks — your comp hits harder in chaos"),
                "lose": t("letting them poke and siege on their own terms")}
    return {"win": t("take the next neutral objective off a pick — trade cross-map"),
            "lose": t("coin-flipping 5v5s without vision or a numbers edge")}


def _brief_shape(dd, my, en, scouted=False, key_prefix=""):
    base = {"plan": _plan(dd, my, en), "wincons": _wincons(dd, my, en),
            "scouted": bool(scouted),
            "_lobby_key": key_prefix + _key_for_rows(my, en)}

    def blank(row):
        cid = row["champ_id"]
        return {"champ": dd.get("id2name", {}).get(cid, "?"), "cid": cid,
                "role": row["role"], "dmg": ltag.dmg_type(dd, cid),
                "phrases": ltag.phrases(dd, cid), "me": row["me"],
                "player": "", "scouted": False, "tags": [], "rank_full": None,
                "form": [], "n": 0, "w": 0, "cg": 0, "cw": 0, "kdar": None,
                "kavg": "", "dpg": None, "perf": None, "pts": 0, "mlevel": 0,
                "main_pos": "", "mids": [], "recent": [], "level": None,
                "puuid": None}

    return dict(base, allies=[blank(row) for row in my],
                enemies=[blank(row) for row in en])


def brief_from_live(dd, request_timeout=0.3, on_timing=None):
    """Anonymous minimal roster fallback once Live Client appears at clock zero."""
    try:
        data = _timed_lcu(
            "live-allgamedata", "https://127.0.0.1:2999/liveclientdata/allgamedata",
            {}, request_timeout, on_timing,
        )
    except Exception:
        return None
    players = data.get("allPlayers") or []
    if not players:
        return None
    active = data.get("activePlayer") or {}
    active_name = (active.get("riotId") or active.get("summonerName") or
                   active.get("riotIdGameName") or "")
    mine_name = lg._gname(active_name)

    def player_name(player):
        return lg._gname(player.get("riotId") or player.get("summonerName") or
                         player.get("riotIdGameName") or "")

    me = next((player for player in players
               if mine_name and player_name(player) == mine_name), None)
    my_team = me.get("team") if me else "ORDER"

    def rows(team):
        out = []
        for player in players:
            if player.get("team") != team:
                continue
            cid = dd.get("name2id", {}).get(dd["norm"](player.get("championName", ""))) or 0
            if cid:
                out.append({"sid": None, "champ_id": int(cid),
                            "role": _ROLE.get((player.get("position") or "").upper(), ""),
                            "me": player is me})
        return out

    my, en = rows(my_team), rows("CHAOS" if my_team == "ORDER" else "ORDER")
    if not (my and en):
        return None
    return _brief_shape(dd, my, en, scouted=False, key_prefix="live-")


def brief(dd, key=None, scout=True, on_progress=None, mysid=None,
          roster_timeout=4.0, on_timing=None):
    """The loading brief. scout=False returns FAST (champs + tags + damage + plan, no Riot API)
    so the overlay can appear instantly; scout=True additionally pulls each player's rank/form/
    OTP tags. None if no roster is readable.

    The ten accounts are read CONCURRENTLY. Serially this was ~130 stacked round-trips and it
    owned the entire loading screen — every card sat on "scouting…" until the last player
    landed. `on_progress(brief)` (optional) is called with a fresh, fully-shaped brief each
    time a player resolves, so a surface can paint cards as they fill in instead of waiting
    for the slowest account."""
    r = _roster(mysid=mysid, request_timeout=roster_timeout, on_timing=on_timing)
    if not r:
        return None
    my, en, (port, hdr) = r
    key = (key or ls.read_key()) if scout else None
    shaped = _brief_shape(dd, my, en, scouted=bool(key))
    allies, enemies = shaped["allies"], shaped["enemies"]

    def fill(rec, row, ally):
        try:
            ign, lvl = _ign_for(port, hdr, row["sid"])
            puuid = ls.resolve_puuid(ign, key) if ign else None
            if puuid and len(puuid) > 70:
                rec["player"] = ign
                rec["level"] = lvl
                rec["puuid"] = puuid
                rec.update(_player_scout(dd, puuid, row["champ_id"], key, riot_id=ign))
                rec["scouted"] = True        # _profile_tags reads this (the first-timer tag)
                rec["tags"] = _profile_tags(rec, ally)
        except Exception:
            pass

    if key:
        lock = threading.Lock()
        jobs = ([(rec, row, True) for rec, row in zip(allies, my)]
                + [(rec, row, False) for rec, row in zip(enemies, en)])
        with _futures.ThreadPoolExecutor(max_workers=max(1, len(jobs))) as ex:
            futs = [ex.submit(fill, *j) for j in jobs]
            for _f in _futures.as_completed(futs):
                if not on_progress:
                    continue
                with lock:                       # one player landed -> hand out a paintable copy
                    snap = dict(shaped, allies=[dict(a) for a in allies],
                                enemies=[dict(e) for e in enemies])
                try:
                    on_progress(snap)
                except Exception:
                    pass
    return dict(shaped, allies=allies, enemies=enemies)


# ---------- ONE scout per lobby, shared by every surface ----------
# The loading overlay, the web DraftBoard publisher and the in-game board all want the same
# ten-account read, and they all wake up at the same moment — so they used to fire three
# independent storms of ~100 Riot calls each into one rate limiter, throttle each other, and
# every surface came back half-scouted. Now the FIRST caller builds it and everyone else reads
# that build: a disk snapshot keyed by the lobby (so a new game never sees the old one) plus an
# exclusive build lock, because these are separate PROCESSES — an in-memory cache can't help.
SNAP_FILE = os.path.expanduser("~/.claude/cache/scout_snapshot.json")
SNAP_LOCK = SNAP_FILE + ".lock"
SNAP_TTL = 45 * 60          # a lobby's accounts don't change mid-game
LOCK_STALE = 120            # a builder holding the lock longer than this is presumed dead
_LOCAL = {"key": None, "brief": None}      # in-process memo, so repeat calls are free


def _key_for_rows(my, en):
    sig = sorted(f"{x.get('sid')}:{x.get('champ_id')}" for x in (my + en))
    return hashlib.sha1("|".join(sig).encode()).hexdigest()[:16]


def _lobby_key(mysid=None, request_timeout=4.0, on_timing=None):
    """Stable id for THIS lobby: the ten (summonerId, championId) pairs. Changes the moment a
    new game forms, which is what expires the snapshot — no time-based guessing."""
    r = _roster(mysid=mysid, request_timeout=request_timeout, on_timing=on_timing)
    if not r:
        return None
    my, en, _ = r
    return _key_for_rows(my, en)


def _snap_read(want_key, require_scouted=False):
    try:
        c = json.load(open(SNAP_FILE, encoding="utf-8"))
    except Exception:
        return None
    if c.get("key") != want_key or time.time() - c.get("ts", 0) > SNAP_TTL:
        return None
    brief_data = c.get("brief") or None
    if require_scouted and not (brief_data or {}).get("scouted"):
        return None
    return brief_data


def coach_snapshot(brief_data=None, lifecycle_key=None, max_age=SNAP_TTL):
    """Read and bound the shared loading scout without triggering any player refetch."""
    age = 0
    if brief_data is None:
        try:
            cached = json.load(open(SNAP_FILE, encoding="utf-8"))
        except Exception:
            return None
        age = max(0, int(time.time() - float(cached.get("ts") or 0)))
        if age > max_age or (lifecycle_key and cached.get("key") != lifecycle_key):
            return {"_unavailable": "stale", "source_age_ms": age * 1000}
        brief_data = cached.get("brief")
    if not brief_data:
        return None

    def team(rows, enemy=False):
        out = []
        next_ally = 1
        for index, row in enumerate((rows or [])[:5], 1):
            tags = []
            for tag in (row.get("tags") or [])[:4]:
                text = (tag.get("text") if isinstance(tag, dict) else
                        (tag[0] if isinstance(tag, (list, tuple)) and tag else tag))
                low = str(text or "").lower()
                this_game = ("first ", "primeira ", "off-champ", "fora do campeão",
                             "cold on ", "frio de ", "comfort", "conforto",
                             " otp", " main")
                scope = (tag.get("evidence_scope") if isinstance(tag, dict) else None)
                scope = scope if scope in ("this_game", "account_history") else (
                    "this_game" if any(mark in low for mark in this_game)
                    else "account_history")
                tags.append({"text": str(text or "")[:120],
                             "evidence_scope": scope})
            out.append({
                "slot": (f"enemy_{index}" if enemy else
                         ("self" if row.get("me") else f"ally_{next_ally}")),
                "champion": row.get("champ"), "role": row.get("role"),
                "rank": row.get("rank_full"), "recent_games": row.get("n", 0),
                "recent_wins": row.get("w", 0), "performance": row.get("perf"),
                "tags": tags, "scouted": bool(row.get("scouted")),
            })
            if not enemy and not row.get("me"):
                next_ally += 1
        return out

    return {"plan": brief_data.get("plan"), "win_conditions": brief_data.get("wincons"),
            "scouted": bool(brief_data.get("scouted")),
            "allies": team(brief_data.get("allies")),
            "enemies": team(brief_data.get("enemies"), enemy=True),
            "source_age_ms": age * 1000}


def _snap_write(lkey, brief, preserve_scouted=False):
    try:
        if preserve_scouted:
            current = _snap_read(lkey)
            if current and current.get("scouted"):
                return
            # The Live Client fallback has no summoner IDs, so its key intentionally differs
            # from the full gameflow key.  Still avoid downgrading a fresh full scout when the
            # two team/champion shapes prove it is already this match.
            try:
                with open(SNAP_FILE, encoding="utf-8") as handle:
                    cached = json.load(handle)
                cached_brief = cached.get("brief") or {}

                def champ_shape(value):
                    return tuple(tuple(sorted(int(row.get("cid") or 0) for row in
                                              value.get(team) or []))
                                 for team in ("allies", "enemies"))

                if time.time() - float(cached.get("ts") or 0) <= SNAP_TTL \
                        and cached_brief.get("scouted") \
                        and champ_shape(cached_brief) == champ_shape(brief):
                    return
            except Exception:
                pass
        os.makedirs(os.path.dirname(SNAP_FILE), exist_ok=True)
        tmp = f"{SNAP_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"key": lkey, "ts": time.time(), "brief": brief}, f)
        os.replace(tmp, SNAP_FILE)
    except Exception:
        pass


def publish_minimal_snapshot(dd, brief_data=None):
    """Publish the anonymous roster/comp brief before the full account scout finishes.

    Fast loading screens can end the overlay process before the daemon scout completes.  This
    snapshot gives cross-process coach consumers fresh champions, roles and composition reads
    immediately, while ``brief_shared`` still owns the only full account-history fetch.
    """
    brief_data = brief_data or brief(dd, scout=False)
    if not brief_data:
        return None
    lkey = brief_data.get("_lobby_key") or _lobby_key()
    if not lkey:
        return None
    _snap_write(lkey, brief_data, preserve_scouted=True)
    return brief_data


def prepare_minimal_snapshot(dd, mysid=None, attempts=4, request_timeout=1.25,
                             live_timeout=0.3, retry_delay=0.1,
                             should_continue=None, on_timing=None):
    """Retry the bounded anonymous roster read and persist it before any full scouting."""
    should_continue = should_continue or (lambda: True)
    for attempt in range(1, max(1, attempts) + 1):
        if not should_continue():
            return None
        started = time.monotonic()
        fast = (brief_from_live(dd, request_timeout=live_timeout, on_timing=on_timing)
                if live_timeout is not None else None)
        if not fast:
            fast = brief(dd, scout=False, mysid=mysid, roster_timeout=request_timeout,
                         on_timing=on_timing)
        if on_timing:
            try:
                on_timing(f"minimal-attempt-{attempt}", time.monotonic() - started,
                          "ready" if fast else "missing")
            except Exception:
                pass
        if fast:
            publish_minimal_snapshot(dd, fast)
            return fast
        if attempt < attempts and should_continue():
            time.sleep(max(0, retry_delay))
    return None


def _lock_acquire():
    """True if we own the build. Exclusive-create is atomic across processes; a lock left
    behind by a crashed builder goes stale and is reclaimed."""
    try:
        if os.path.exists(SNAP_LOCK) and time.time() - os.path.getmtime(SNAP_LOCK) > LOCK_STALE:
            os.remove(SNAP_LOCK)
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(SNAP_LOCK), exist_ok=True)
        fd = os.open(SNAP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except Exception:
        return False


def _lock_release():
    try:
        os.remove(SNAP_LOCK)
    except Exception:
        pass


def brief_shared(dd, key=None, wait=40, on_progress=None, mysid=None,
                 on_timing=None):
    """The full scouted brief for this lobby, built ONCE and shared by every surface.

    Returns the snapshot if someone already built it; otherwise builds it (holding a lock) and
    publishes it. If another process is mid-build we wait for its result rather than duplicating
    ~100 Riot calls — that duplication is what was rate-limiting the scout into partial data.
    Falls back to building locally if the wait times out, so a surface is never left with
    nothing. None only when there's no readable roster at all.

    `on_progress` is forwarded to brief() when WE are the builder, so the surface that pays for
    the read gets to paint it as it fills. A caller that lands on an existing snapshot gets the
    finished thing in one shot and never needs progress."""
    lkey = _lobby_key(mysid=mysid, on_timing=on_timing)
    if not lkey:
        return None
    if _LOCAL["key"] == lkey and _LOCAL["brief"]:
        return _LOCAL["brief"]
    # A minimal snapshot is useful to the coach, but must never satisfy the full-scout path.
    snap = _snap_read(lkey, require_scouted=True)
    if snap:
        _LOCAL.update(key=lkey, brief=snap)
        return snap
    if _lock_acquire():
        try:
            b = brief(dd, key=key, scout=True, on_progress=on_progress,
                      mysid=mysid, on_timing=on_timing)
            if b and b.get("scouted"):
                _snap_write(lkey, b)
                _LOCAL.update(key=lkey, brief=b)
            return b
        finally:
            _lock_release()
    deadline = time.time() + wait                  # someone else is building -> use THEIR result
    while time.time() < deadline:
        time.sleep(1.0)
        snap = _snap_read(lkey, require_scouted=True)
        if snap:
            _LOCAL.update(key=lkey, brief=snap)
            return snap
        if not os.path.exists(SNAP_LOCK):          # builder finished (or died) -> stop waiting
            break
    b = brief(dd, key=key, scout=True, on_progress=on_progress,
              mysid=mysid, on_timing=on_timing)   # last resort: build it ourselves
    if b and b.get("scouted"):
        _snap_write(lkey, b)
        _LOCAL.update(key=lkey, brief=b)
    return b
