#!/usr/bin/env python3
"""lolbleed.py - BLEED GUARD: the first 14 minutes, watched on your own health bar.

THE LEAK THIS EXISTS FOR
lolprofile.behavior_read tags a game `early_bleeding` when three or more of YOUR deaths
land before 14:00. In this account's ledger it is the second-biggest split in the file and
the biggest one with NO in-game surface: 23 of 46 graded games carry it, won at 39% against
61% in the games without it. Half his games. The RE-ENTRY guard (lolreentry) already owns
the 90 seconds AFTER a death; the minutes BEFORE the first one were empty.

WHY A HEALTH BAR
Nothing else in Smiteless reads `activePlayer.championStats` - your own current health is
in every single :2999 poll and was going straight in the bin. That number is the one fact
that decides whether the next thirty seconds is a death, and it is the one thing you stop
looking at when you are last-hitting. Low HP alone is not a warning (you'd get one every
wave); low HP while somebody can actually collect is.

WHAT IT DOES
While the clock is under 14:00 and you are alive, it answers one question off live data
only: can they kill you right this second?
  - your health, as a percentage of your own maximum   (activePlayer.championStats)
  - is the enemy jungler accounted for?                (ONE BRAIN: lollive.JgTracker)
  - is your lane opponent alive, and how far up on you (levels) is he?
  - how many deaths have you already taken before 14:00?

BLEED - back off now. The widget's directive card becomes this.
None  - silence. This surface is a warning or it is nothing; it never chatters.

The bar TIGHTENS as the game shape gets worse: two deaths already banked before 14:00 and
it starts calling at a health total it would have let pass at zero. That is deliberate -
the third death is the one that flips the tag, and the tag is the thing that costs the LP.

House rule (docs/TAGS.md spirit): the card carries its receipt - YOUR OWN W/L split for
the habit, straight out of the behavior ledger, so it is your data talking and not folklore.

100% read-only off :2999. No input, no camera, nothing automated.

  python lolbleed.py        # print every branch from the fixtures
"""
import time

from smitei18n import t, tf

WINDOW = 14 * 60.0     # seconds - the early_bleeding definition in lolprofile.behavior_read
HP_BAR = 0.42          # health fraction at/below which a collapse is a real death
HP_BAR_BLED = 0.58     # ... once you've already banked 2+ deaths inside the window
HP_BAR_LVL = 0.08      # ... plus this much per level your lane opponent is up on you
HP_BAR_MAX = 0.70      # never call it above this: at 3/4 health you are not dying to a gank
DIVE_LVL = 2           # a lane opponent this many levels up solo-kills you on his own
_EV_TTL = 600.0        # re-read the behavior ledger at most this often

_EV = {"t": 0.0, "raw": None}

# The productive thing to do instead, by role. Same shape of instruction lolreentry gives
# in its own window - one action, no theory - and imported from there so there is exactly
# one copy of "what safe looks like in your lane" in the app.
try:
    from lolreentry import _SAFE
except Exception:                                 # standalone / import-order edge
    _SAFE = {"top": "shove your wave in, take the plate/camp, don't walk at him",
             "mid": "shove your wave in, cross to a camp, don't walk at him",
             "jungle": "reset your own camps, safe side first — no counter-jungle",
             "adc": "catch the wave under tower, farm it out",
             "support": "ward your own side and reset the wave — no deep pathing"}


def _evidence():
    """YOUR measured split for the early-bleeding habit ('with it: 9W-14L / without:
    14W-9L'), or None when the ledger doesn't have both sides yet. Cached - it's a disk
    read and this is called from a 1s poll loop."""
    now = time.monotonic()
    if _EV["raw"] is not None and (now - _EV["t"]) < _EV_TTL:
        return tf("your games with 3+ deaths before 14:00 — {evidence}",
                  evidence=_EV["raw"])
    raw = None
    try:
        import lolprofile as lp
        raw = lp.pattern_evidence("early_bleeding")
    except Exception:
        raw = None
    _EV["t"], _EV["raw"] = now, raw
    return (tf("your games with 3+ deaths before 14:00 — {evidence}", evidence=raw)
            if raw else None)


def _threat(ctx):
    """(is_someone_able_to_collect, why) from facts the live client can prove. No claim
    without evidence: an unknown jungler is not a threat, it's an unknown."""
    jg = ctx.get("jg") or {}
    state, champ = jg.get("state"), jg.get("champ") or t("their jungler")
    lvl_up = int(ctx.get("opp_lvl_up") or 0)
    opp = ctx.get("opp_champ")
    if opp and lvl_up >= DIVE_LVL:
        return True, tf("{champ} is {levels} levels up", champ=opp, levels=lvl_up)
    if not ctx.get("opp_alive"):
        return False, None            # nobody in lane to hold you there -> no collapse
    if state == "seen" and (jg.get("side") or "") == ctx.get("my_side"):
        return True, tf("{champ} was just {side}", champ=champ,
                        side=t(str(jg.get("side") or "").upper()))
    if state == "nosign":
        return True, tf("{champ} unaccounted {seconds}s", champ=champ,
                        seconds=int(jg.get("idle") or 0))
    if state == "moving":
        return True, tf("{champ} off camps {seconds}s", champ=champ,
                        seconds=int(jg.get("idle") or 0))
    return False, None                # dead / farming / seen elsewhere / no read at all


def _verdict(ctx):
    """Pure: context -> the card (or None). Split out from observe() so the fixtures in
    selftest can drive every branch without a live game."""
    hp = float(ctx.get("hp") if ctx.get("hp") is not None else 1.0)
    deaths = int(ctx.get("deaths") or 0)
    bar = HP_BAR_BLED if deaths >= 2 else HP_BAR
    bar = min(HP_BAR_MAX, bar + HP_BAR_LVL * max(0, int(ctx.get("opp_lvl_up") or 0)))
    if hp > bar:
        return None
    ok, why = _threat(ctx)
    if not ok:
        return None
    sub = t(_SAFE.get(ctx.get("role") or "jungle", _SAFE["jungle"]))
    if deaths >= 3:
        sub += tf(" · {deaths} deaths before 14:00 — this is the 39% shape",
                  deaths=deaths)
    elif deaths == 2:
        sub += t(" · 2 deaths before 14:00 — one more is the pattern")
    return {"verdict": "BLEED", "tone": "hold", "deaths": deaths,
            "hp": int(round(hp * 100)),
            "line": tf("BACK OFF — {hp}% and {reason}",
                       hp=int(round(hp * 100)), reason=why),
            "sub": sub}


# Live-client positions -> our role names and the map side a gank comes from, so "seen BOT"
# next to an ADC reads as "he is on top of you" and next to a TOP does not.
_LC_ROLE = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid", "BOTTOM": "adc",
            "UTILITY": "support"}
_ROLE_SIDE = {"top": "top", "mid": "mid", "adc": "bot", "support": "bot", "jungle": None}


class Guard:
    """One instance per widget session. Stateless per tick apart from the new-game reset -
    the whole read is live, so there is nothing to arm and nothing to expire."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._gt = 0.0
        self.calls = 0             # BLEED windows opened this game (diagnostics / voice rate)
        self._firing = False

    def observe(self, dd, data, jg=None):
        """One tick. Returns the card while you're alive, under 14:00 and in real danger;
        None every other moment. `jg` is lollive's jungler status dict for this same tick
        (ONE BRAIN - the tracker is stateful and must only be advanced once per poll)."""
        if not data:
            return None
        import lollive as ll
        import loltempo as lt
        split = ll.team_split(data)
        if not split:
            return None
        me, _allies, enemies, _team = split
        gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
        if gt + 1.0 < self._gt:                    # clock went backwards -> a different game
            self.reset()
        self._gt = gt
        if gt > WINDOW or me.get("isDead"):
            self._firing = False
            return None

        stats = (data.get("activePlayer") or {}).get("championStats") or {}
        try:
            cur, mx = float(stats.get("currentHealth")), float(stats.get("maxHealth"))
        except (TypeError, ValueError):
            return None
        if mx <= 0:
            return None

        role = lt._my_role(dd, me)
        pos = (me.get("position") or "").upper()
        opp = None
        if pos:
            opp = next((p for p in enemies if (p.get("position") or "").upper() == pos), None)
        my_lvl = int(me.get("level", 1) or 1)
        card = _verdict({
            "hp": cur / mx,
            "deaths": int((me.get("scores") or {}).get("deaths") or 0),
            "role": role,
            "my_side": _ROLE_SIDE.get(role),
            "jg": jg,
            "opp_champ": (opp or {}).get("championName"),
            "opp_alive": bool(opp) and not opp.get("isDead"),
            "opp_lvl_up": (int(opp.get("level", 1) or 1) - my_lvl) if opp else 0,
        })
        if card is None:
            self._firing = False
            return None
        if not self._firing:
            self._firing = True
            self.calls += 1
        card["left"] = int(max(0, WINDOW - gt))
        card["calls"] = self.calls
        card["evidence"] = _evidence()
        return card


# ---- fixtures for tools/selftest.py: each must land on exactly one outcome ----
def demo(kind):
    base = {"hp": 0.30, "deaths": 0, "role": "mid", "my_side": "mid",
            "jg": {"state": "nosign", "champ": "Kha'Zix", "idle": 58},
            "opp_champ": "Ahri", "opp_alive": True, "opp_lvl_up": 0}
    if kind == "bleed":                   # low, and nobody knows where their jungler is
        pass
    elif kind == "dive":                  # healthy-ish, but the laner alone can kill you
        base.update(hp=0.50, opp_lvl_up=2, jg={"state": "dead", "champ": "Kha'Zix"})
    elif kind == "banked":                # 55% would be fine at 0 deaths; at 2 it is not
        base.update(hp=0.55, deaths=2)
    elif kind == "healthy":               # full health -> never a warning
        base.update(hp=0.95)
    elif kind == "accounted":             # low, but their jungler is dead and the laner is up
        base.update(jg={"state": "dead", "champ": "Kha'Zix"})
    elif kind == "alone":                 # low, jungler unknown, but the laner is dead
        base.update(opp_alive=False, jg={"state": "moving", "champ": "Kha'Zix", "idle": 20})
    elif kind == "noread":                # low, and we simply have no jungler read: say nothing
        base.update(jg=None)
    return base


if __name__ == "__main__":                # python lolbleed.py — print every branch
    for k in ("bleed", "dive", "banked", "healthy", "accounted", "alone", "noread"):
        c = _verdict(demo(k))
        if c:
            print(f"{k:10} {c['line']}\n           {c['sub']}")
        else:
            print(f"{k:10} (silent)")
