#!/usr/bin/env python3
"""lollive.py - live in-game intel from the Live Client Data API (:2999), no AI, no key.

Three reads off a single /liveclientdata/allgamedata fetch:
  - objectives(): next dragon / void-grub / baron spawn timers, event-driven (respawns come
    straight from the kill events, so they're correct regardless of patch tuning).
  - power_spike():the scariest enemy who has spiked (completed items) AND is ahead.
  - win_prob():   a transparent live win read from net item gold + levels + drakes (no model,
    just a logistic on the gold/level/objective lead - rough on purpose, tune with the consts).

All timings are Season-16 (2026) defaults and live at the top so they're trivial to dial in.
"""
import os
import lolbuild as lb
import lolgame as lg

# ---- objective spawn model (seconds of game time). Respawns are event-driven (kill + delta);
#      first-spawn constants are the only patch-sensitive values, kept here for easy tuning. ----
DRAGON_FIRST, DRAGON_RESPAWN = 300, 300            # 5:00, then 5:00 after each kill
ELDER_RESPAWN = 360                                # elder: 6:00 after the 4th elemental / each elder
GRUBS_FIRST, GRUBS_DESPAWN = 480, 885              # patch 25.09: 8:00, ONE spawn, gone ~14:45
HERALD_SPAWN, HERALD_GONE = 900, 1185              # 15:00 (where grubs were), leaves ~19:45
BARON_FIRST, BARON_RESPAWN, BARON_OPEN = 1200, 360, 1140    # 20:00, +6:00; only show from 19:00
SCUTTLE_FIRST, SCUTTLE_SHOW_UNTIL = 175, 210        # 2:55 first scuttle (wiki: cut from 3:30), respawn 2:30
ALERT_LEAD = 45                                    # within this many seconds = "soon" (urgent)
SETUP_LEAD = 75                                    # inside this = start SETTING UP (shove + ward)

# ---- ONE BRAIN: the live game-economy model. win_prob (here), the tempo engine's
#      fight_edge (loltempo) and the live win read all read from the
#      same per-player power estimate below, so the win% chip and the TAKE/GIVE coach
#      can never tell opposite stories about the same game state. ----
XP_CUM = {1: 0, 2: 280, 3: 660, 4: 1140, 5: 1720, 6: 2400, 7: 3180, 8: 4060, 9: 5040,
          10: 6120, 11: 7300, 12: 8580, 13: 9960, 14: 11440, 15: 13020, 16: 14700,
          17: 16480, 18: 18360}   # wiki "Experience": cumulative XP to reach each level
XP_GOLD = 0.25            # modeling assumption: gold value per XP point
DRAKE_GOLD = 230          # standing value of a drake (buff + soul progress), per drake taken
BARON_GOLD = 1700         # an active baron is worth roughly this in pushing/teamfight power
GOLD_SCALE = 3400.0       # gold-equivalent lead at which the read is ~68% - bigger = flatter
                          # curve (retuned for the full est-gold power scale; was 7000 on the
                          # old finished-items-only scale)


# ---- comp power curves (modeling): who gets scarier the longer a game runs. ONE BRAIN —
#      the champ-select game plan (smitecard.game_plan, "YOU OUTSCALE") and the live
#      comeback read (lolout, "time is on your side") grade the same two comps off the same
#      table, so the lobby and the game can never tell you opposite stories about them.
SCALE_W = {"Marksman": 3.0, "Mage": 2.4, "Fighter": 2.0, "Assassin": 1.7, "Tank": 1.6,
           "Support": 1.4}
SCALE_DEF = 1.8           # a champ whose class isn't in the table
SCALE_GAP = 0.25          # average-curve gap that counts as "one comp out-scales the other"


def comp_scale_ids(dd, ids):
    """Average power-curve weight of a comp, from champion IDS (champ select). None when
    there aren't any."""
    rows = [set((dd.get("id2tags") or {}).get(i) or []) for i in ids if i]
    if not rows:
        return None
    return sum(max((SCALE_W.get(t, SCALE_DEF) for t in s), default=SCALE_DEF)
               for s in rows) / float(len(rows))


def comp_scale(dd, players):
    """Same curve, from LIVE players (`championName` off :2999) rather than champ-select
    ids. None when no champion in the list resolves — never a fake 0.0, which would read
    as 'they out-scale you' on a data miss."""
    ids = []
    norm = dd.get("norm")
    for p in players or []:
        cid = (dd.get("name2id") or {}).get(norm(p.get("championName") or "")) if norm else None
        if cid:
            ids.append(cid)
    return comp_scale_ids(dd, ids)


def _read():
    try:
        return lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata", timeout=3, insecure=True)
    except Exception:
        return None


def _events(data):
    return ((data.get("events") or {}).get("Events")) or []


def _last_time(events, name):
    """Game-time of the most recent event with this EventName, or None."""
    ts = [e.get("EventTime") for e in events if e.get("EventName") == name and e.get("EventTime") is not None]
    return max(ts) if ts else None


def _count(events, name):
    return sum(1 for e in events if e.get("EventName") == name)


def objectives(data):
    """Upcoming neutral objectives as [{label, secs, up, urgent}], soonest first.
    secs is time-to-spawn (<=0 means it's up now). Event-driven respawns stay correct
    even when Riot tweaks the numbers; only the first-spawn constants are patch-guessed."""
    gd = data.get("gameData") or {}
    gt = float(gd.get("gameTime") or 0.0)
    if gt <= 0:
        return []
    ev = _events(data)
    out = []

    def add(label, nxt):
        secs = int(round(nxt - gt))
        out.append({"label": label, "secs": secs, "up": secs <= 0,
                    "urgent": 0 < secs <= ALERT_LEAD,
                    "setup": ALERT_LEAD < secs <= SETUP_LEAD})

    # First river scuttle — the early jungle tempo anchor (first clears end into it). Clock-based
    # only: the Live Client feed has no crab-kill event, so we can't track respawns; shown as a
    # countdown to 2:55 then briefly "up" through the contest window.
    if gt < SCUTTLE_SHOW_UNTIL:
        add("Scuttle", SCUTTLE_FIRST)

    # Dragon: first at 5:00, then 5:00 after each kill. Elder spawns 6:00 after ONE TEAM's
    # 4th elemental kill (soul) — NOT after 4 total across both teams (3-2 is just another
    # drake: soul point). Each slain elder respawns in 6:00 (wiki "Dragon", verified 2026-07).
    drags = [e for e in ev if e.get("EventName") == "DragonKill"]
    elder_kills = [e.get("EventTime") for e in drags
                   if str(e.get("DragonType") or "").lower() == "elder"
                   and e.get("EventTime") is not None]
    elem = [e for e in drags
            if str(e.get("DragonType") or "").lower() != "elder" and e.get("EventTime") is not None]
    ally_names = {lg._gname(p.get("riotId") or p.get("summonerName") or "")
                  for p in (data.get("allPlayers") or [])
                  if p.get("team") == "ORDER"}             # either side works: we need A-vs-B, not us-vs-them
    a_kills = sum(1 for e in elem if lg._gname(e.get("KillerName") or "") in ally_names)
    soul_taken = max(a_kills, len(elem) - a_kills) >= 4    # one SIDE at 4 = soul -> elder next
    if elder_kills:
        add("Elder", max(elder_kills) + ELDER_RESPAWN)
    elif soul_taken:
        add("Elder", max(e.get("EventTime") for e in elem) + ELDER_RESPAWN)
    else:
        add("Drake", (max(e.get("EventTime") for e in elem) + DRAGON_RESPAWN) if elem else DRAGON_FIRST)

    # Void grubs: ONE spawn at 8:00 (patch 25.09 removed the respawn), gone by ~14:45.
    if gt < GRUBS_DESPAWN and _last_time(ev, "HordeKill") is None:
        add("Grubs", GRUBS_FIRST)

    # Rift Herald: 15:00 where the grubs were, one only, leaves before Baron.
    if GRUBS_DESPAWN <= gt < HERALD_GONE and _last_time(ev, "RiftHeraldKill") is None:
        add("Herald", HERALD_SPAWN)

    # Baron: only surfaces from ~19:00 on (irrelevant earlier). First 20:00, then 6:00.
    if gt >= BARON_OPEN:
        last_b = _last_time(ev, "BaronKill")
        add("Baron", (last_b + BARON_RESPAWN) if last_b is not None else BARON_FIRST)

    out.sort(key=lambda o: o["secs"])
    return out


def _completed_items(dd, items):
    """Count of pricey, finished items (a proxy for legendary spikes) + their summed gold."""
    n, gold = 0, 0
    idata = dd.get("item_data", {})
    for iid in items:
        info = idata.get(iid) or {}
        g = ((info.get("gold") or {}).get("total")) or 0
        gold += g
        tags = info.get("tags", [])
        if g >= 2000 and "Boots" not in tags and "Consumable" not in tags:
            n += 1
    return n, gold


def team_split(data):
    """(me, allies, enemies, my_team) from an allgamedata payload, or None. THE shared
    identity read - every live consumer (tempo, win read) goes through this."""
    players = data.get("allPlayers") or []
    act = data.get("activePlayer") or {}
    myg = lg._gname(act.get("riotId") or act.get("summonerName") or "")
    me = next((p for p in players if lg._gname(p.get("riotId") or p.get("summonerName") or "") == myg), None)
    if me is None or not players:
        return None
    myteam = me.get("team")
    allies = [p for p in players if p.get("team") == myteam]
    enemies = [p for p in players if p.get("team") != myteam]
    return me, allies, enemies, myteam


_team_split = team_split                   # legacy alias: existing callers keep working


def est_gold(p, gt):
    """ESTIMATED total earned gold from scores the Live Client reports for everyone
    regardless of vision (CS, kills, assists, game time). Critical because enemy ITEM
    data only updates when they've been seen — an enemy farming in fog looks poorer than
    they are. Modeling constants: 500 start, ~20.4g/10s passive from 1:50, ~20.5g/CS,
    300g/kill, ~155g/assist (bounty averages). (Moved from loltempo — ONE BRAIN.)"""
    sc = p.get("scores") or {}
    g = 500.0
    if gt > 110:
        g += (gt - 110) * 2.04
    g += float(sc.get("creepScore") or 0) * 20.5
    g += float(sc.get("kills") or 0) * 300.0 + float(sc.get("assists") or 0) * 155.0
    return g


def team_lead(allies, enemies, gt):
    """THE lead/deficit number: the team gold gap on the fog-proof score-based estimate.
    ONE BRAIN — the CLOSER's lead, THE OUT's deficit and the widget's chip are all this one
    function, so nothing on screen can quote a different gap than the guard beside it.
    Deliberately NOT player_power: that one prefers VISIBLE item gold when it is higher,
    which your own team always has and an enemy farming in fog does not."""
    return (sum(est_gold(p, gt) for p in allies or ())
            - sum(est_gold(p, gt) for p in enemies or ()))


def player_power(dd, p, gt):
    """One player's gold-equivalent fight power: XP value + the BEST-KNOWN read of their
    gold — visible item gold, or the score-based estimate (x0.82 spent-fraction) when
    that's higher (i.e. their items are stale because they haven't been seen).
    (Moved from loltempo — ONE BRAIN.)"""
    items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
    _n, gold = _completed_items(dd, items)
    gold = max(gold, est_gold(p, gt) * 0.82)
    return gold + XP_CUM.get(max(1, min(18, int(p.get("level", 1)))), 0) * XP_GOLD


def drake_counts(data, allies):
    """(ally_drakes, enemy_drakes) from DragonKill events, credited via killer name.
    (Moved from loltempo — ONE BRAIN; win_prob's own copy of this logic is gone.)"""
    names = {lg._gname(p.get("riotId") or p.get("summonerName") or "") for p in allies}
    a = e = 0
    for ev in _events(data):
        if ev.get("EventName") == "DragonKill":
            if lg._gname(ev.get("KillerName") or "") in names:
                a += 1
            else:
                e += 1
    return a, e


def power_spike(dd, data):
    """The scariest enemy who has SPIKED (>=2 completed items) AND is ahead - the moment to
    play safe / itemize. None if no enemy is both spiked and fed."""
    split = _team_split(data)
    if not split:
        return None
    _me, _allies, enemies, _t = split
    best = None
    for p in enemies:
        items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
        n, _g = _completed_items(dd, items)
        sc = p.get("scores") or {}
        k, d = int(sc.get("kills", 0)), int(sc.get("deaths", 0))
        lead = k - d
        if n >= 2 and lead >= 3:
            name = dd["id2name"].get(dd["name2id"].get(dd["norm"](p.get("championName", "")), 0),
                                     p.get("championName", "?"))
            score = n * 2 + lead
            if not best or score > best["score"]:
                best = {"name": name, "items": n, "k": k, "d": d, "score": score}
    return best


def win_prob(dd, data):
    """Transparent live win read on the SAME economy the tempo engine fights with (ONE
    BRAIN): per-player fog-proof power (est gold + XP via player_power) + drake/baron
    swings, through a logistic. The old read counted finished items only, so a farmed
    enemy in fog inflated our win% while fight_edge (correctly) said we lose — the two
    could contradict each other on the same widget frame. Returns {pct, ahead, basis}."""
    split = team_split(data)
    if not split:
        return None
    _me, allies, enemies, _t = split
    if not (allies and enemies):
        return None
    gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)

    my_dr, en_dr = drake_counts(data, allies)
    # baron: count recent (<180s) barons per side as an "active" power swing
    ally_names = {lg._gname(p.get("riotId") or p.get("summonerName") or "") for p in allies}
    my_bar = en_bar = 0
    for e in _events(data):
        if e.get("EventName") == "BaronKill" and gt - float(e.get("EventTime") or 0) < 180:
            if lg._gname(e.get("KillerName") or "") in ally_names:
                my_bar += 1
            else:
                en_bar += 1

    my_g = sum(player_power(dd, p, gt) for p in allies) + my_dr * DRAKE_GOLD + my_bar * BARON_GOLD
    en_g = sum(player_power(dd, p, gt) for p in enemies) + en_dr * DRAKE_GOLD + en_bar * BARON_GOLD
    diff = my_g - en_g
    import math
    pct = 1.0 / (1.0 + math.exp(-diff / GOLD_SCALE))
    pct = max(0.05, min(0.95, pct))
    kdiff = f"{diff/1000:+.1f}k gold"
    drk = f", {my_dr - en_dr:+d} drake" if (my_dr or en_dr) else ""
    return {"pct": int(round(pct * 100)), "ahead": diff >= 0, "basis": kdiff + drk}


_JG_SIDE = {"TOP": "topside", "MIDDLE": "mid", "MID": "mid", "BOTTOM": "botside", "UTILITY": "botside"}
JG_STALE = 300             # keep showing a sighting (dimmed) up to this old - old info beats none
JG_FRESH = 75              # under this it's an actionable read; over it the widget dims it


def _is_jungler(p):
    if (p.get("position") or "").upper() == "JUNGLE":
        return True
    ss = p.get("summonerSpells") or {}
    for k in ("summonerSpellOne", "summonerSpellTwo"):
        if "smite" in ((ss.get(k) or {}).get("displayName") or "").lower():
            return True
    return False


_TURRET_LANE = {"L": "topside", "C": "mid", "R": "botside"}


def _jg_events(data, jg_g):
    """Newest event the jungler took part in -> (event_gt, side, what) or None. Sources:
    drake = botside; grubs/herald/baron = topside; tower kills = the tower's own lane
    (parsed from the turret name); champion kills = the victim's lane; their own death."""
    pos_of = {}
    for p in (data.get("allPlayers") or []):
        pos_of[lg._gname(p.get("riotId") or p.get("summonerName") or "")] = (p.get("position") or "").upper()
    best = None
    for e in _events(data):
        t, n = e.get("EventTime"), e.get("EventName")
        if t is None:
            continue
        involved = [e.get("KillerName", ""), e.get("VictimName", "")] + list(e.get("Assisters") or [])
        if jg_g not in (lg._gname(x) for x in involved if x):
            continue
        if n == "DragonKill":
            side, what = "botside", "drake"
        elif n == "HordeKill":
            side, what = "topside", "grubs"
        elif n == "RiftHeraldKill":
            side, what = "topside", "herald"
        elif n == "BaronKill":
            side, what = "topside", "baron"
        elif n == "TurretKilled":
            tn = e.get("TurretKilled") or ""
            lane = next((_TURRET_LANE[c] for c in ("L", "C", "R") if f"_{c}_" in tn), None)
            if not lane:
                continue
            side, what = lane, "tower"
        elif n == "ChampionKill":
            victim = lg._gname(e.get("VictimName") or "")
            if victim == jg_g:                    # the jungler DIED - that's a timer, not a sighting
                side, what = "dead", "died"
            else:
                side = _JG_SIDE.get(pos_of.get(victim, ""), "a fight")
                what = "kill"
        else:
            continue
        if best is None or t > best[0]:
            best = (t, side, what)
    return best


def jungle_read(dd, data):
    """Where the enemy jungler was LAST SEEN, from the events they took part in.
    Returns {champ, side, what, ago} or None. (The stateful tracker below supersedes this
    in the widget; kept as the simple one-shot read.)"""
    split = _team_split(data)
    if not split:
        return None
    _me, _allies, enemies, _t = split
    jg = next((p for p in enemies if _is_jungler(p)), None)
    if jg is None:
        return None
    jg_name = lg._gname(jg.get("riotId") or jg.get("summonerName") or "")
    if not jg_name:
        return None
    gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
    best = _jg_events(data, jg_name)
    champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](jg.get("championName", "")), 0),
                              jg.get("championName", "?"))
    if best is None:
        return {"champ": champ, "side": None, "what": "no sightings yet", "ago": None,
                "stale": True, "enemy_team": jg.get("team", "")}
    ago = int(gt - best[0])
    if ago > JG_STALE:
        return {"champ": champ, "side": None, "what": f"no read for {ago // 60}m+", "ago": None,
                "stale": True, "enemy_team": jg.get("team", "")}
    return {"champ": champ, "side": best[1], "what": best[2], "ago": ago,
            "stale": ago > JG_FRESH, "enemy_team": jg.get("team", "")}


class JgTracker:
    """Stateful enemy-jungler tracker: gives a definite state EVERY tick, not just when an
    event happens. Knowledge sources, all fog-safe to claim:
      - events (kills/objectives/towers)     -> SEEN <side>
      - their death + respawnTimer           -> DEAD, back in Xs
      - creepScore ticking up                -> farm registered (if the API vision-gates enemy
        CS, a tick also implies they were just seen - either way: benign)
      - CS frozen while alive, no events     -> NO SIGN for Xs (in fog / on the move) - the
        actionable 'respect the gank' state, valid whether or not CS leaks through fog.
    Identity is sticky for the whole game; a gameTime reset (new game) clears it."""
    SEEN_FRESH = 25        # an event this recent is a live sighting
    SIGN_WINDOW = 35       # a cs tick within this = 'farm registered'
    WARN_AFTER = 45        # alive + nothing for this long -> warning state

    def __init__(self):
        self.reset()

    def reset(self):
        self.gname = None
        self.champ = "?"
        self.last_gt = 0.0
        self.cs = None
        self.cs_gt = None          # game-time of the last observed cs increase
        self.seen = None           # newest (event_gt, side, what)
        self.dead = False
        self.respawn = 0
        self.was_dead = False

    def update(self, dd, data):
        gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
        if gt + 30 < self.last_gt:                # gameTime went backwards -> a NEW game
            self.reset()
        self.last_gt = max(self.last_gt, gt)
        split = _team_split(data)
        if not split:
            return self._status(gt)               # partial payload -> hold current knowledge
        _me, _allies, enemies, _t = split
        jg = None
        if self.gname:                            # sticky identity: same jungler all game
            jg = next((p for p in enemies
                       if lg._gname(p.get("riotId") or p.get("summonerName") or "") == self.gname), None)
        if jg is None:
            jg = next((p for p in enemies if _is_jungler(p)), None)
            if jg is not None:
                self.gname = lg._gname(jg.get("riotId") or jg.get("summonerName") or "")
                self.champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](jg.get("championName", "")), 0),
                                               jg.get("championName", "?"))
        if jg is None:
            return self._status(gt)
        cs = int((jg.get("scores") or {}).get("creepScore", 0) or 0)
        if self.cs is None or cs > self.cs:
            if self.cs is not None:
                _jg_callog(gt, cs)                # calibration: does enemy CS move in fog?
            self.cs, self.cs_gt = cs, gt
        self.dead = bool(jg.get("isDead"))
        self.respawn = int(float(jg.get("respawnTimer") or 0))
        if self.was_dead and not self.dead:       # just respawned: they're AT BASE, a known spot
            self.seen = (gt, "their base", "respawned")   # restarts the no-sign clock too
        self.was_dead = self.dead
        s = _jg_events(data, self.gname)
        if s and (self.seen is None or s[0] > self.seen[0]):
            self.seen = s
        return self._status(gt)

    def _status(self, gt):
        if not self.gname:
            return None
        last_side = self.seen[1] if (self.seen and self.seen[1] != "dead") else None
        last_ago = int(gt - self.seen[0]) if self.seen else None
        out = {"champ": self.champ, "state": "unknown", "side": None, "what": None,
               "ago": None, "idle": None, "respawn": 0,
               "last_side": last_side, "last_ago": last_ago,
               # legacy fields so older render paths keep working
               "stale": True, "enemy_team": ""}
        if self.dead:
            out.update(state="dead", respawn=self.respawn)
            return out
        if self.seen and gt - self.seen[0] <= self.SEEN_FRESH and self.seen[1] != "dead":
            out.update(state="seen", side=self.seen[1], what=self.seen[2],
                       ago=int(gt - self.seen[0]), stale=False)
            return out
        acts = [x for x in (self.cs_gt, self.seen[0] if self.seen else None) if x is not None]
        if not acts:
            return out
        idle = int(gt - max(acts))
        out["idle"] = idle
        if self.cs_gt is not None and gt - self.cs_gt <= self.SIGN_WINDOW:
            out["state"] = "farming"
        elif idle >= self.WARN_AFTER:
            out["state"] = "nosign"
        else:
            out["state"] = "moving"
        return out


_CALLOG = os.path.expanduser("~/.claude/cache/smiteless_jgcal.jsonl")


def _jg_callog(gt, cs):
    """Log enemy-jungler cs ticks so we can find out empirically whether the live API
    vision-gates enemy CS (smooth camp-sized ticks = it leaks; big bursts after gaps = it
    syncs on sight). Tiny, capped, local-only."""
    try:
        if os.path.exists(_CALLOG) and os.path.getsize(_CALLOG) > 256 * 1024:
            os.remove(_CALLOG)
        with open(_CALLOG, "a", encoding="utf-8") as f:
            f.write('{"gt": %.1f, "cs": %d}\n' % (gt, cs))
    except Exception:
        pass


_TRACKER = JgTracker()


def lane_live_adj(dd, data, ally_role, enemy_role):
    """{role: score_adjustment} for the gank ratings from the CURRENT game state, so the
    strong/weak side shifts as the game evolves: an enemy lane that's dying, levels behind
    its counterpart, or literally dead right now becomes the gank side; a fed one stops
    being one. Champs are matched by name->cid, so it works even when the live client
    reports no positions."""
    players = data.get("allPlayers") or []
    by_cid = {}
    for p in players:
        cid = dd["name2id"].get(dd["norm"](p.get("championName", ""))) or 0
        if cid and cid not in by_cid:
            by_cid[cid] = p
    out = {}
    for role, e_cid in (enemy_role or {}).items():
        ep = by_cid.get(e_cid)
        if not ep:
            continue
        adj = 0.0
        sc_ = ep.get("scores") or {}
        adj += (int(sc_.get("deaths", 0) or 0) - int(sc_.get("kills", 0) or 0)) * 1.2
        ap = by_cid.get((ally_role or {}).get(role))
        if ap:
            adj += (int(ap.get("level", 1) or 1) - int(ep.get("level", 1) or 1)) * 1.8
        if ep.get("isDead"):
            adj += 5.0                             # dead RIGHT NOW: free lane pressure
        out[role] = round(adj, 1)
    return out


GANK_LVL_GAP = 2           # enemy this many levels behind their lane = a gank window


def gank_window(dd, data):
    """The most gankable enemy LANE right now: alive and >=2 levels behind their direct
    counterpart (a level lead is the cleanest 'you win the 2v1' signal :2999 exposes).
    Returns {lane, champ, lvl, vs_lvl} or None. Positions come from the live client, so
    this only fires in ranked/normals where positions are reported."""
    split = _team_split(data)
    if not split:
        return None
    _me, allies, enemies, _t = split
    ally_lvl = {}
    for p in allies:
        pos = (p.get("position") or "").upper()
        if pos:
            ally_lvl[pos] = int(p.get("level", 1) or 1)
    best = None
    for p in enemies:
        pos = (p.get("position") or "").upper()
        if pos in ("", "JUNGLE") or pos not in ally_lvl:
            continue
        if p.get("isDead"):
            continue
        gap = ally_lvl[pos] - int(p.get("level", 1) or 1)
        if gap >= GANK_LVL_GAP and (best is None or gap > best[0]):
            champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](p.get("championName", "")), 0),
                                      p.get("championName", "?"))
            best = (gap, {"lane": _JG_SIDE.get(pos, pos.lower()), "champ": champ,
                          "lvl": int(p.get("level", 1) or 1), "vs_lvl": ally_lvl[pos]})
    return best[1] if best else None


_UNSET = object()


def pulse(dd, data=_UNSET):
    """One-shot live intel for the widget: {objectives, spike, winprob} or None if not in game.
    Pass `data` (an already-fetched allgamedata payload) to share one :2999 fetch; passing an
    explicit None means 'no data this tick' and returns None without re-fetching."""
    if data is _UNSET:
        data = _read()
    if not data or not (data.get("allPlayers")):
        return None
    try:
        objs = objectives(data)
    except Exception:
        objs = []
    try:
        spike = power_spike(dd, data)
    except Exception:
        spike = None
    try:
        wp = win_prob(dd, data)
    except Exception:
        wp = None
    try:
        jg = _TRACKER.update(dd, data)   # stateful: a definite jungler state EVERY tick
    except Exception:
        jg = None
    try:
        gank = gank_window(dd, data)
    except Exception:
        gank = None
    lead = None
    try:                                 # the measured team gold gap the widget's chip shows
        sp = team_split(data)
        if sp:
            lead = team_lead(sp[1], sp[2], float((data.get("gameData") or {}).get("gameTime") or 0.0))
    except Exception:
        lead = None
    if not (objs or spike or wp or jg or gank or lead is not None):
        return None
    return {"objectives": objs, "spike": spike, "winprob": wp, "jungle": jg, "gank": gank,
            "lead": lead}


def coach_snapshot(dd, data=_UNSET):
    """Allowlisted live state; intentionally omits the raw allgamedata document."""
    if data is _UNSET:
        data = _read()
    if not data:
        return None
    split = team_split(data)
    if not split:
        return None
    me, allies, enemies, _team = split
    game_time = float((data.get("gameData") or {}).get("gameTime") or 0.0)

    def player(row):
        scores = row.get("scores") or {}
        return {
            "champion": row.get("championName"), "role": row.get("position"),
            "level": row.get("level"),
            "kda": [scores.get("kills", 0), scores.get("deaths", 0), scores.get("assists", 0)],
            "cs": scores.get("creepScore", 0),
            "items": [it.get("displayName") or it.get("itemID")
                      for it in (row.get("items") or [])[:7]],
            "dead": bool(row.get("isDead")), "respawn_seconds": row.get("respawnTimer", 0),
        }

    derived = pulse(dd, data) or {}
    try:
        import loltempo
        derived["tempo"] = loltempo.tempo_read(dd, data)
        derived["respawn"] = loltempo.respawn_plan(dd, data)
    except Exception:
        derived.setdefault("tempo", None)
        derived.setdefault("respawn", None)
    events = [{"kind": event.get("EventName"), "time": event.get("EventTime")}
              for event in _events(data)[-12:]]
    ally_rows = [player(p) for p in allies if p is not me][:4]
    enemy_rows = [player(p) for p in enemies][:5]
    for index, row in enumerate(ally_rows, 1):
        row["slot"] = f"ally_{index}"
    for index, row in enumerate(enemy_rows, 1):
        row["slot"] = f"enemy_{index}"
    self_row = player(me)
    self_row["slot"] = "self"
    return {"game_time": round(game_time, 1), "self": self_row,
            "allies": ally_rows, "enemies": enemy_rows, "events": events,
            "reads": derived, "source_age_ms": 0}


def _fmt(secs):
    if secs <= 0:
        return "UP"
    return f"{secs // 60}:{secs % 60:02d}"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    dd = lb.ddragon()
    p = pulse(dd)
    if not p:
        print("not in a live game")
    else:
        print("objectives:", [(o["label"], _fmt(o["secs"]), "!" if o["urgent"] else "") for o in p["objectives"]])
        print("spike:", p["spike"])
        print("winprob:", p["winprob"])
