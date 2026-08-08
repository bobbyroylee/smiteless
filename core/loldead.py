#!/usr/bin/env python3
"""loldead.py - assembles the DEATH BRIEF: the dense read you get on the grey screen.

Being dead is the one zero-cost reading window in League - full attention, nothing to click.
This gathers everything the scattered in-game HUD already knows and packages it for the
fullscreen see-through brief (ui/smitedead.py): your respawn clock + the one tempo verdict,
what to buy on respawn, the win read, the scariest enemy spike, the enemy jungler, the next
objectives, and a kill/objective feed of what you missed while dead.

Everything here is READ-ONLY off the live-client feed (:2999) - no input automation, no camera
control (that needs simulating input into the game and is bannable; not happening). brief()
returns None unless the active player is dead right now, so the overlay only shows on death.
"""
import os
import time

import loltempo as lt
import lollive as ll
import lolitems as li
import lolgame as lg
import loltags as ltag
import lolout as lo

FEED_WINDOW = 40          # seconds of history for "what you missed"
_DEAD_LOG = os.path.expanduser("~/.claude/smiteless_dead.log")


def _dlog(msg):
    """Diagnostic for attribution misses (standing rule: surfaces that can't be triggered
    on demand ship with a log). A killer we couldn't match must leave evidence behind."""
    try:
        with open(_DEAD_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# The live events feed has NO participant ids — ChampionKill carries only KillerName /
# VictimName strings. A non-champion killer arrives as an internal object name
# (Turret_T2_L_03_A, Minion_T1L3S..., SRU_Baron / SRU_Dragon_Fire / SRU_Razorbeak...);
# anything unrecognized falls through to the honest raw-name path, never a wrong claim.
_ENV_MONSTER = (("baron", "Baron"), ("dragon", "the drake"), ("herald", "the Herald"),
                ("razorbeak", "raptors"), ("murkwolf", "wolves"), ("gromp", "Gromp"),
                ("krug", "krugs"), ("red", "red buff"), ("blue", "blue sentinel"),
                ("crab", "the scuttle crab"), ("atakhan", "Atakhan"))


def _env_killer(raw):
    """Friendly name for a non-champion killer in the events feed, or None if `raw`
    doesn't look like an environment object (i.e. it's presumably a player)."""
    r = (raw or "").strip()
    if r.startswith(("Turret", "Obelisk")):
        return "a turret"
    if r.startswith("Minion"):
        return "minions"
    if r.startswith(("SRU_", "SRUAP_", "TT_")):
        low = r.lower()
        for frag, label in _ENV_MONSTER:
            if frag in low:
                return label
        return "a jungle monster"
    return None


def _gname(p):
    return lg._gname(p.get("riotId") or p.get("summonerName") or "")


def _recent_feed(data, ally_names, gt):
    """Compact kill/objective feed for the last FEED_WINDOW seconds, newest first.
    Each row: {text, ally} where ally True = our team did it (tint green vs red)."""
    rows = []
    evs = (data.get("events") or {}).get("Events") or []
    for e in evs:
        t = float(e.get("EventTime") or 0.0)
        if gt - t > FEED_WINDOW or gt - t < 0:
            continue
        nm = e.get("EventName")
        killer = lg._gname(e.get("KillerName") or "")
        ally = killer in ally_names
        ago = max(0, int(gt - t))
        if nm == "ChampionKill":
            vic = e.get("VictimName") or "?"
            vic_ally = lg._gname(vic) in ally_names
            kraw = e.get("KillerName") or "?"
            kshow = _env_killer(kraw) or _short(kraw)   # 'Turret_T2_L_03_A' -> 'a turret'
            # "ally kills enemy" is good for us; "enemy kills ally" is bad
            rows.append({"t": t, "ago": ago, "ally": (not vic_ally),
                         "text": f"{kshow}  killed  {_short(vic)}"})
        elif nm == "DragonKill":
            dt = (e.get("DragonType") or "").replace("Elder", "Elder ").strip().lower()
            rows.append({"t": t, "ago": ago, "ally": ally,
                         "text": f"{'you' if ally else 'they'} took {dt or 'drake'}"})
        elif nm == "BaronKill":
            rows.append({"t": t, "ago": ago, "ally": ally,
                         "text": f"{'you' if ally else 'they'} took BARON"})
        elif nm == "HeraldKill":
            rows.append({"t": t, "ago": ago, "ally": ally,
                         "text": f"{'you' if ally else 'they'} took Herald"})
        elif nm in ("TurretKilled", "FirstBrick"):
            rows.append({"t": t, "ago": ago, "ally": ally, "text": "tower down"})
        elif nm == "InhibKilled":
            rows.append({"t": t, "ago": ago, "ally": ally, "text": "inhibitor down"})
    rows.sort(key=lambda r: r["t"], reverse=True)
    return rows[:6]


def _short(name):
    """Trim a Riot ID ('Name#TAG') to just the name for the feed."""
    return (name or "?").split("#")[0][:14]


_ROLE = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "BOTTOM": "BOT", "UTILITY": "SUP"}


def _scoreboard(dd, data, gt):
    """Full live rundown of all ten: champ, role, level, KDA, CS, est gold, completed items.
    Gold is the fog-proof estimate so a farmed enemy in fog doesn't read as poor."""
    split = ll.team_split(data)
    if not split:
        return None
    me, allies, enemies, _t = split
    myg = _gname(me) if me else ""

    def row(p):
        sc = p.get("scores") or {}
        items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
        try:
            nit, _g = ll._completed_items(dd, items)
        except Exception:
            nit = 0
        cid = dd["name2id"].get(dd["norm"](p.get("championName", "")))
        champ = dd["id2name"].get(cid, p.get("championName", "?"))
        k, dth = int(sc.get("kills", 0)), int(sc.get("deaths", 0))
        return {"champ": champ, "role": _ROLE.get((p.get("position") or "").upper(), ""),
                "lvl": int(p.get("level", 1)), "k": k, "d": dth, "a": int(sc.get("assists", 0)),
                "cs": int(sc.get("creepScore", 0)), "gold": int(ll.est_gold(p, gt)),
                "items": nit, "dead": bool(p.get("isDead")), "me": _gname(p) == myg,
                "cid": cid or 0, "tag": ltag.short(dd, cid) if cid else "",
                "fed": (k - dth >= 5 and nit >= 2)}     # snowballing & itemized -> flag it
    al = [row(p) for p in allies]
    en = [row(p) for p in enemies]
    lead = sum(r["gold"] for r in al) - sum(r["gold"] for r in en)
    return {"allies": al, "enemies": en, "gold_lead": lead}


def _cls(dd, cid):
    tags = dd.get("id2tags", {}).get(cid, []) or []
    return tags[0] if tags else ""


# how to play AGAINST a fed enemy of each class — the counterplay, not just "watch him"
_COUNTER = {
    "Assassin": "buy Zhonya's / GA, never walk alone, group tight — he deletes you solo",
    "Marksman": "he's squishy — hard-engage / CC him first, blow him up before he DPS's",
    "Mage": "don't stand in his poke; flank or dive him, buy MR",
    "Fighter": "don't 1v1 him — kite with your team, buy armor, focus him down together",
    "Tank": "ignore him in fights, buy %HP / armor-pen, kill the carries behind him",
    "Support": "he enables them — CC/kill him first to open the fight",
}


def _death_cause(dd, data, me, enemies, gt):
    """Why you just died + the takeaway, from the kill event where YOU were the victim."""
    myg = _gname(me)
    kill = None
    for e in reversed((data.get("events") or {}).get("Events") or []):
        if e.get("EventName") == "ChampionKill" and lg_gname(e.get("VictimName")) == myg \
                and gt - float(e.get("EventTime") or 0) <= 25:
            kill = e
            break
    if not kill:
        return None
    raw = kill.get("KillerName") or ""
    env = _env_killer(raw)
    assists = len(kill.get("Assisters") or [])
    if env:                                            # executed by turret / minions / a monster
        return {"line": f"Executed by {env}", "sub": "no kill credit given away — reset, buy, "
                                                     "and don't repeat the dive/greed"}
    kg = lg_gname(raw)
    killer = next((p for p in enemies if _gname(p) == kg), None)
    if not killer:
        if raw:
            # a NAMED killer we couldn't match to the enemy roster: say what we know
            # honestly (never claim 'no killer'), and leave evidence for diagnosis
            _dlog(f"unmatched KillerName {raw!r} vs enemies "
                  f"{[p.get('riotId') or p.get('summonerName') for p in enemies]}")
            return {"line": f"Killed by {_short(raw)}", "sub": "caught — reset, respawn clean"}
        return {"line": "You died with no killer credited", "sub": "reset, respawn clean"}
    sc = killer.get("scores") or {}
    kk, kd = int(sc.get("kills", 0)), int(sc.get("deaths", 0))
    champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](killer.get("championName", "")), 0),
                              killer.get("championName", "?"))
    cid = dd["name2id"].get(dd["norm"](killer.get("championName", "")))
    cls = _cls(dd, cid)
    fed = kk - kd >= 3
    # 'Solo' is a claim — it only renders when the kill event credits NO assisters.
    if assists >= 2:
        line = f"Collapsed on by {champ} +{assists}"
        sub = "you were caught out of position — group up, ward flanks, stop face-checking"
    elif assists == 1:
        line = f"Killed by {champ} +1 ({kk}/{kd})"
        sub = _COUNTER.get(cls, "lost a 2v1 trade — track both before committing")
    elif fed and cls == "Assassin":
        line = f"Solo-killed by {champ} ({kk}/{kd})"
        sub = "he one-shots you now — " + _COUNTER["Assassin"]
    else:
        line = f"Solo-killed by {champ} ({kk}/{kd})"
        sub = _COUNTER.get(cls, "lost the trade — don't take even fights into him without summs")
    return {"line": line, "sub": sub}


def _scalers(dd, rows):
    n = 0
    for p in rows:
        cid = dd["name2id"].get(dd["norm"](p.get("championName", "")))
        if _cls(dd, cid) == "Marksman" or dd["id2name"].get(cid) in ("Kassadin", "Vayne", "Jax", "Kayle", "Nasus", "Veigar"):
            n += 1
    return n


def _comeback(dd, me, board):
    """The DOOMED-game line (§12): when the gold says you're clearly behind, the generic
    win-con isn't enough — give ONE concrete stabilizing line, gated to what YOUR champ
    and role can actually execute (a support doesn't get told to split-push). Grounded in
    the standard behind-game macro canon: behind teams win off enemy mistakes and picks,
    not called fights; stall to your item spike; give what you can't win and take waves
    for it; vision on YOUR side of the map, not theirs."""
    cid = dd["name2id"].get(dd["norm"]((me or {}).get("championName", "")))
    cls = _cls(dd, cid)
    pos = ((me or {}).get("position") or "").upper()
    if pos in ("UTILITY", "SUPPORT") or cls == "Support":
        return ("Behind — play for PICKS: sweep + ward YOUR side, catch a face-check. "
                "One pick = your next objective.")
    if pos == "TOP" and cls in ("Fighter", "Tank") or dd.get("id2name", {}).get(cid) in (
            "Jax", "Tryndamere", "Fiora", "Camille", "Yorick", "Trundle"):
        return ("Behind — take a side lane: catch waves, drag their sidelaner, don't "
                "flip mid. Join for soul/Baron only.")
    if cls == "Marksman":
        return ("Behind — stall to your item spike: farm safe, defend at YOUR tower, "
                "don't contest without numbers.")
    if cls == "Assassin":
        return ("Behind — don't group front-to-front: flank from fog; one pick on a "
                "carry makes the next fight 5v4.")
    if cls == "Mage":
        return ("Behind — waveclear and stall at your towers; poke, don't engage. "
                "Fight only off a pick or their mistake.")
    return ("Behind — give what you can't win, take waves for it; engage only on "
            "their mistake. Picks win from behind.")


def _wincon(dd, data, me, allies, enemies, wp, board):
    """How YOU win this specific game — the strategic anchor to hold onto on the grey screen."""
    ahead = bool(wp and wp.get("ahead"))
    my_s, en_s = _scalers(dd, allies), _scalers(dd, enemies)
    myrow = next((r for r in (board.get("allies") or []) if r.get("me")), None)
    lead = int(board.get("gold_lead") or 0)
    if myrow and myrow.get("fed"):
        return "You're the win condition — take objectives with your lead and close before they scale."
    if lead <= -2500:                        # clearly losing on gold -> the champ-gated comeback line
        return _comeback(dd, me, board)
    if ahead and my_s <= en_s:
        return "You're ahead — force tempo NOW: take towers and objectives, end before it evens out."
    if my_s > en_s:
        return "You out-scale — survive the early game, farm, take neutrals; your power is 3 items each."
    if not ahead and en_s >= my_s:
        return "Behind vs a scaling comp — you MUST make plays early: force objectives, don't let it go late."
    return "Even game — win the next neutral objective; group and trade cross-map, don't coinflip."


def _threat(dd, board):
    """The enemy carrying the game + how to deal with them (not just 'watch him')."""
    ens = board.get("enemies") or []
    cand = [r for r in ens if (r["k"] - r["d"]) >= 3 and r["items"] >= 2]
    if not cand:
        return None
    r = max(cand, key=lambda x: (x["k"] - x["d"]) + x["items"])
    cls = _cls(dd, r.get("cid", 0))
    return {"line": f"{r['champ']} {r['k']}/{r['d']}/{r['a']} is carrying",
            "sub": _COUNTER.get(cls, "shut him down — deny him kills, group and focus him")}


def _chain_risk(dd, data, me, gt):
    """PRE-EMPTIVE chained-death read (§13): the reactive 'you died again' is useless —
    this fires while you're STILL DEAD, from conditions that precede a repeat death, so
    the warning lands before you walk back in. One line + one instruction, or None.
    Conditions (all from the live events feed): this death chained off the last one
    (<90s), the same enemy has killed you repeatedly, or the enemy team just took an
    objective (= they're grouped and moving) right before you respawn."""
    myg = _gname(me)
    evs = (data.get("events") or {}).get("Events") or []
    my_deaths = [e for e in evs if e.get("EventName") == "ChampionKill"
                 and lg_gname(e.get("VictimName")) == myg]
    if not my_deaths:
        return None
    risks = []
    if len(my_deaths) >= 2:
        gap = float(my_deaths[-1].get("EventTime") or 0) - float(my_deaths[-2].get("EventTime") or 0)
        if 0 < gap <= 90:
            risks.append((f"CHAINING — this death came {int(gap)}s after the last",
                          "walk to a WAVE, not to the fight. Break the loop this respawn."))
    killers = [lg_gname(e.get("KillerName")) for e in my_deaths[-3:]]
    killers = [k for k in killers if k and not _env_killer(k)]
    if killers and len(killers) >= 2 and killers.count(killers[-1]) >= 2:
        nm = _short(my_deaths[-1].get("KillerName"))
        risks.append((f"{nm} has killed you {killers.count(killers[-1])} of your last {len(killers)}",
                      "path AWAY from them — they're playing to snowball on you"))
    for e in reversed(evs):
        if e.get("EventName") in ("DragonKill", "BaronKill", "HeraldKill") \
                and gt - float(e.get("EventTime") or 0) <= 25:
            ally_names = set()          # killer ally? caller ctx unavailable -> check vs my team below
            k = lg_gname(e.get("KillerName") or "")
            split = ll.team_split(data)
            if split and not any(_gname(p) == k for p in split[1]):   # enemy took it
                obj = {"DragonKill": "the drake", "BaronKill": "BARON",
                       "HeraldKill": "the Herald"}[e["EventName"]]
                risks.append((f"They just took {obj} — they're 5, grouped, and moving",
                              "do NOT walk mid alone; group or cross-map for a wave"))
            break
    if not risks:
        return None
    line, sub = risks[0]
    return {"line": line, "sub": sub}


def lg_gname(name):
    return lg._gname(name or "")


def brief(dd, data):
    """The full death brief, or None unless the active player is dead right now."""
    dead = lt.respawn_plan(dd, data)          # None unless YOU are dead -> the whole trigger
    if not dead:
        return None
    gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
    out = {"secs": dead.get("secs"), "tone": dead.get("tone"),
           "verdict": dead.get("line") or "", "verdict_sub": dead.get("sub") or "",
           "gametime": gt, "buy": None, "winprob": None, "spike": None,
           "jungle": None, "objectives": [], "feed": [], "board": None,
           "why": None, "wincon": None, "threat": None, "chain": None}
    try:
        rc = li.recall_advice(dd, data)
        out["buy"] = rc.get("text") if rc else None
    except Exception:
        pass
    try:
        p = ll.pulse(dd, data)
    except Exception:
        p = None
    if p:
        out["winprob"] = p.get("winprob")
        out["spike"] = p.get("spike")
        out["jungle"] = p.get("jungle")
        out["objectives"] = [o for o in (p.get("objectives") or []) if o.get("secs") is not None][:3]
    split = None
    try:
        split = ll.team_split(data)
    except Exception:
        split = None
    me, allies, enemies = (split[0], split[1], split[2]) if split else (None, [], [])
    try:
        out["feed"] = _recent_feed(data, {_gname(a) for a in allies}, gt)
    except Exception:
        pass
    try:
        out["board"] = _scoreboard(dd, data, gt)
    except Exception:
        out["board"] = None
    # ---- the coaching (the whole point of the overhaul): why you died, how you win, the threat ----
    if me is not None and out.get("board"):
        try:
            out["why"] = _death_cause(dd, data, me, enemies, gt)
        except Exception:
            out["why"] = None
        try:
            out["chain"] = _chain_risk(dd, data, me, gt)
        except Exception:
            out["chain"] = None
        try:
            out["wincon"] = _wincon(dd, data, me, allies, enemies, out.get("winprob"), out["board"])
        except Exception:
            out["wincon"] = None
        try:
            out["threat"] = _threat(dd, out["board"])
        except Exception:
            out["threat"] = None
    # THE OUT: in a game you are LOSING, the strategic sentence above is outranked by the
    # live read — is there still a mechanism in this game, and what is it. This is the one
    # screen where a player is actually deciding whether to keep playing, so it lands here
    # too, with the same words the widget is showing (ONE BRAIN).
    try:
        o = lo.read(dd, data, None, out.get("objectives") or None, while_dead=True)
    except Exception:
        o = None
    if o and o.get("line"):
        out["out"] = o
        out["wincon"] = o["line"]
        out["wincon_sub"] = o.get("sub")
        out["wincon_title"] = t("THE CALL") if o.get("verdict") == "CALL IT" else t("HOW YOU WIN")
    return out
