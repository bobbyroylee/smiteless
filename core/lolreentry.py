#!/usr/bin/env python3
"""lolreentry.py - RE-ENTRY: the 90-second guard that starts the moment you respawn.

THE LEAK THIS EXISTS FOR
lolprofile.behavior_read already tags a game `death_cluster` when two of YOUR deaths land
within 90 seconds of each other. In this account's ledger that tag is not a curiosity, it's
the biggest single split in the file: 23 of 41 graded games carry it, and they were won at
35% against 65% in the games without it. Dying is normal. Dying TWICE inside a minute and a
half is what actually loses the game - you walk back into a lane where you are a level and
a wave down, against the player who just proved he beats you there.

That leak is invisible in the moment and obvious afterwards, which is the exact shape of
problem an overlay can fix. The death screen already gets a plan (loltempo.respawn_plan);
the 90 seconds AFTER you press respawn were empty. This fills them.

WHAT IT DOES
From the instant you come back alive it runs a 90-second clock - the same 90 seconds that
define the tag - and, while it runs, answers one question off live data only: can they
punish you right now? The answer comes from facts the Live Client API can prove and you
can't check quickly mid-game:
  - is the champion who just killed you alive, and is he stronger than you right now?
  - how many enemies are dead, and for how long?
  - what is the 5v5 fight edge if a fight starts this second (ONE BRAIN: loltempo.fight_edge)?

HOLD  - you lose any fight you take right now. The widget's directive card becomes this.
CLEAR - they're a body down and the map is yours. Quiet row; the tempo engine keeps the card.
RESET - even. Quiet row: farm the window out, don't go looking for a trade.

House rule (docs/TAGS.md spirit): the card carries its receipt - YOUR OWN W/L split for the
habit, straight out of the behavior ledger, so it's your data talking and not folklore.

100% read-only off :2999. No input, no camera, nothing automated.
"""
import time

import lollive as ll
import loltempo as lt
from smitei18n import t, tf

WINDOW = 90.0          # seconds - the death_cluster definition in lolprofile.behavior_read
E_HOLD = -700.0        # gold-equivalent fight edge at/below which re-entering is a losing trade
E_CLEAR = 0.0          # ... and the bar a body-up read must also clear to read CLEAR
KILLER_EDGE = 1.12     # your killer counts as a live threat when he's this much stronger than you
_EV_TTL = 600.0        # re-read the behavior ledger at most this often

_EV = {"t": 0.0, "text": None}


def _evidence():
    """YOUR measured split for the death-cluster habit ('with it: 8W-15L / without: 11W-6L'),
    or None when the ledger doesn't have both sides yet. Cached - it's a disk read and this
    is called from a 1s poll loop."""
    now = time.monotonic()
    if _EV["text"] is not None and (now - _EV["t"]) < _EV_TTL:
        return _EV["text"]
    txt = None
    try:
        import lolprofile as lp
        raw = lp.pattern_evidence("death_cluster")
        if raw:                       # "with it: 8W-15L · without: 11W-6L" — name what "it" is
            txt = tf("your games where two deaths landed inside 90s — {evidence}", evidence=raw)
    except Exception:
        txt = None
    _EV["t"], _EV["text"] = now, txt
    return txt


def _gname(p):
    import lolgame as lg
    return lg._gname(p.get("riotId") or p.get("summonerName") or "")


def _last_killer(data, me):
    """Game name of whoever killed you most recently, or None. The events feed carries only
    KillerName / VictimName strings, so a non-champion killer (turret, monster) simply won't
    match a player below - which is the honest answer, nobody is coming to re-kill you."""
    import lolgame as lg
    myname = _gname(me)
    best = None
    for ev in ll._events(data):
        # names in the feed are raw Riot IDs; every player lookup in this app is on the
        # normalized game name, so BOTH sides go through _gname or the match silently never
        # happens (and the killer line silently never fires).
        if ev.get("EventName") == "ChampionKill" and lg._gname(ev.get("VictimName") or "") == myname:
            best = lg._gname(ev.get("KillerName") or "") or None
    return best


def _short(secs):
    s = max(0, int(secs))
    return f"{s}s" if s < 60 else f"{s // 60}:{s % 60:02d}"


def _verdict(ctx):
    """Pure: context -> the card. Split out from observe() so the fixtures in selftest can
    drive every branch without a live game."""
    e = float(ctx.get("e") or 0.0)
    bodies = float(ctx.get("bodies") or 0.0)
    killer = ctx.get("killer")                    # champ name of who killed you, or None
    killer_up = bool(ctx.get("killer_up"))
    killer_ahead = bool(ctx.get("killer_ahead"))
    dead = list(ctx.get("dead_enemies") or [])    # [(champ, secs_left)], soonest first
    role = ctx.get("role") or "jungle"

    if bodies >= 1.0 and e >= E_CLEAR:
        if dead:
            who = " · ".join(f"{c} {_short(s)}" for c, s in dead[:2])
            sub = tf("{who} — the map is yours until they're back", who=who)
        else:
            sub = t("they're a body down — play for the objective, not the kill")
        return {"verdict": "CLEAR", "tone": "go",
                "line": t("CLEAR — this is your window"), "sub": sub}

    if e <= E_HOLD or bodies <= -1.0 or (killer_up and killer_ahead):
        if killer_up and killer_ahead and killer:
            line = tf("HOLD — {killer} is up and ahead", killer=killer)
        elif bodies <= -1.0:
            line = tf("HOLD — you're {bodies:.0f} body down", bodies=abs(bodies))
        else:
            line = t("HOLD — you lose any fight now")
        return {"verdict": "HOLD", "tone": "hold", "line": line, "sub": t(_SAFE[role])}

    return {"verdict": "RESET", "tone": "plan",
            "line": t("RESET — even fight, no free trade here"),
            "sub": t(_SAFE[role])}


# The productive thing to do instead, by role. Deliberately the same shape of instruction
# loltempo.respawn_plan gives on the grey screen - one action, no theory.
_SAFE = {"top": "shove your wave in, take the plate/camp, don't walk at him",
         "mid": "shove your wave in, cross to a camp, don't walk at him",
         "jungle": "reset your own camps, safe side first — no counter-jungle",
         "adc": "catch the wave under tower, farm it out",
         "support": "ward your own side and reset the wave — no deep pathing"}


class Guard:
    """The 90-second state machine. One instance per widget session; it re-arms every death
    and resets itself when a new game starts (game clock going backwards)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.armed_until = None    # game-time the window closes (None = not armed)
        self.was_dead = False
        self.killer = None         # game name of the champion who killed you
        self.clean = 0             # windows survived this game
        self.clustered = 0         # windows that ended in a second death (a real cluster)
        self._gt = 0.0

    def observe(self, dd, data):
        """One tick. Returns the card dict while the window is live and you're alive, else
        None (the death screen and the tempo engine own those moments)."""
        if not data:
            return None
        split = ll.team_split(data)
        if not split:
            return None
        me, allies, enemies, _team = split
        gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
        if gt + 1.0 < self._gt:                    # clock went backwards -> a different game
            self.reset()
        self._gt = gt

        if me.get("isDead"):
            if not self.was_dead:                  # the moment of death
                if self.armed_until is not None and gt < self.armed_until:
                    self.clustered += 1            # died again inside the window: a cluster
                self.armed_until = None
                self.killer = _last_killer(data, me)
            self.was_dead = True
            return None

        if self.was_dead:                          # the moment you come back
            self.was_dead = False
            self.armed_until = gt + WINDOW
        if self.armed_until is None:
            return None
        left = self.armed_until - gt
        if left <= 0:
            self.armed_until = None
            self.clean += 1
            return None

        card = _verdict(self._context(dd, data, me, allies, enemies, gt))
        card["left"] = int(round(left))
        card["clean"], card["clustered"] = self.clean, self.clustered
        card["evidence"] = _evidence()
        return card

    def _context(self, dd, data, me, allies, enemies, gt):
        act = data.get("activePlayer") or {}
        ms = (act.get("championStats") or {}).get("moveSpeed")
        travel = lt._travel(ms, gt)
        e = bodies = 0.0
        try:                                       # ONE BRAIN: the same edge the tempo card uses
            fe = lt.fight_edge(dd, data, 0.0, travel, gt)
            if fe:
                e, bodies = float(fe[0]), float(fe[1])
        except Exception:
            pass
        killer_name = self.killer
        killer, killer_up, killer_ahead = None, False, False
        if killer_name:
            kp = next((p for p in enemies if _gname(p) == killer_name), None)
            if kp is not None:
                killer = kp.get("championName") or None
                killer_up = not kp.get("isDead")
                try:
                    killer_ahead = (ll.player_power(dd, kp, gt)
                                    >= ll.player_power(dd, me, gt) * KILLER_EDGE)
                except Exception:
                    killer_ahead = False
        dead_enemies = sorted(
            ((p.get("championName") or "?", float(p.get("respawnTimer") or 0.0))
             for p in enemies if p.get("isDead")), key=lambda t: t[1])
        return {"e": e, "bodies": bodies, "killer": killer, "killer_up": killer_up,
                "killer_ahead": killer_ahead, "dead_enemies": dead_enemies,
                "role": lt._my_role(dd, me)}


# ---- fixtures for tools/selftest.py: each must land on exactly one verdict ----
def demo(kind):
    base = {"e": 0.0, "bodies": 0.0, "killer": "Kha'Zix", "killer_up": False,
            "killer_ahead": False, "dead_enemies": [], "role": "jungle"}
    if kind == "hold":                    # the man who killed you is up and stronger
        base.update(killer_up=True, killer_ahead=True)
    elif kind == "clear":                 # two of them are dead and you don't lose the fight
        base.update(bodies=2.0, e=1200.0, dead_enemies=[("Viego", 21.0), ("Ahri", 34.0)])
    elif kind == "reset":                 # even: nothing free, nothing fatal
        base.update(e=-200.0)
    return base


if __name__ == "__main__":                # python lolreentry.py — print every branch
    for k in ("hold", "clear", "reset"):
        c = _verdict(demo(k))
        print(f"{c['verdict']:6} {c['line']}\n       {c['sub']}")
