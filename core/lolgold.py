#!/usr/bin/env python3
"""lolgold.py - THE GOLD CLOCK: the first ten minutes, counted against the minions that
actually spawned.

THE LEAK THIS EXISTS FOR
lolprofile.behavior_read tags a game `weak_first_ten` when you finish minute 10 under
55 CS AND under 3100 gold. It is the only tag in the ledger that applies to FOUR of the
five roles and it is the one with no in-game surface: BLEED (lolbleed) owns the first
fourteen minutes of your HEALTH BAR, RE-ENTRY (lolreentry) the ninety seconds after a
death, the CLOSER (lolclose) the closeout, and the tempo engine the objective windows.
Nobody in this app has ever had a word to say about the thing you spend the whole lane
phase doing, and the thing that decides whether your item spike lands on time.

WHY A NEW NUMBER, AND NOT "CS/MIN"
Every overlay ever built shows you CS/min against a flat benchmark, and a flat benchmark
is a bad coach: it does not know that at 4:32 only nine waves have spawned, or that the
wave landing in twelve seconds is a cannon worth three casters. So this does the exact
arithmetic instead.

  Minions are a SCHEDULE, not a rate. The first wave leaves the fountain at 1:05 and one
  leaves every 30s after. Every wave is 3 melee + 3 casters; every third wave carries a
  siege minion. Melee are 21g, casters 14g, siege 60g - and every one of those values is
  FLAT until 15:00, which is why this module can price the whole window exactly instead
  of modelling it. (Wave 26 - the last one that arrives before this guard closes at 14:00 -
  spawns at 13:35, so the every-third-wave cannon rule holds for the entire window and
  the 15:00 gold-growth curve never enters the math.)

So the denominator is not a benchmark. It is *the minions that have walked into your lane*,
to the minion:

    41 of 74 arrived   (55%)   17 behind pace   ~660g on the floor

WHAT IT DOES
From 2:30 to 14:00, for TOP / MID / ADC, it answers one question off live data only:
are you actually collecting your lane, and if not, can you still fix it before 10:00?

  - THE EXACT DENOMINATOR. waves_by()/offered() - the schedule above, walked forward to
    the current clock, including the lane's own travel time (mid meets at 1:30, the side
    lanes at 1:38, so a side laner is NOT behind for the first eight seconds of the game).
  - CS-EQUIVALENT, not CS. A mid laner on 40 CS and three kills is not bleeding, and the
    tag agrees - it needs the gold bar missed too. Kills and assists are converted into
    CS at lollive.est_gold's OWN per-CS constant (ONE BRAIN: the number is derived from
    that function at import, never re-typed here), so roaming reads as what it is.
  - THE DEADLINE, back-timed. 55 CS by 10:00 is the tag's own bar. Subtract what you have,
    divide by the minions still to come, and you get the only sentence that helps:
    "you need 22 of the next 34". When that is over 100% it says so - a lane you cannot
    farm your way out of needs a different plan, and pretending otherwise wastes the
    remaining minutes.
  - THE CANNON. The single biggest object in lane phase, 60 gold, on a fixed clock, and
    the one you most often give up because you were walking back from a roam. It tells you
    it is coming - but only while you are behind, because a reminder you get every ninety
    seconds regardless is a reminder you stop reading.

MISS   - you just gave up most of a wave and you are under the bar. The card. It fires on
         the wave BOUNDARY, at the moment it happened, and gets out of the way again.
CANNON - under the bar, and a siege minion lands in the next few seconds.
PACE   - the quiet row: what you have, of what arrived, and your standing vs the bar.
None   - outside the window, dead, or a role where lane CS is not the story (jungle camps
         are not on this schedule; a support's CS is noise, and lolprofile has always
         exempted both from farm advice - so this stays silent for them rather than
         invent a number).

It never counts a wave you missed while DEAD against you: dying is RE-ENTRY's and BLEED's
subject, and billing you twice for one mistake is how a coach gets turned off.

House rule (docs/TAGS.md spirit): the card carries its receipt - YOUR OWN W/L split for
the habit, straight out of the behavior ledger, so it is your data talking and not folklore.

100% read-only off :2999. No input, no camera, nothing automated.

  python lolgold.py        # print every branch from the fixtures, and the wave schedule
"""
import math
import time

from smitei18n import t, tf

# ---- the minion schedule (wiki "Minion (League of Legends)", checked 2026-07-29) ----
WAVE_FIRST = 65.0          # first wave leaves the fountain at 1:05
WAVE_EVERY = 30.0          # ...and one every 30s after
MELEE_N, CASTER_N = 3, 3   # every wave
CANNON_EVERY = 3           # every 3rd wave carries a siege minion (the pre-15:00 rule; see
                           # the module docstring - our window closes before it changes)
G_MELEE, G_CASTER, G_CANNON = 21, 14, 60      # base gold; all three are FLAT until 15:00

# Travel: minions meet in mid at ~1:30 and in the side lanes at ~1:38, i.e. 25s / 33s after
# the 1:05 spawn. Counting a wave as "offered" only once it has arrived is what keeps a top
# laner from reading as behind at 1:31.
LANE_ARRIVE = {"top": 33.0, "mid": 25.0, "adc": 33.0}      # jungle/support: not on this schedule

# ---- the bars, both lifted from code that already exists ----
FIRST_TEN = 600.0          # lolprofile.behavior_read evaluates weak_first_ten at minute 10
BAR_CS10 = 55              # ...and its CS half of that bar
GOOD_CS10 = 70             # lolprofile's own "aim ~70+" line in the timeline review
OPEN_AT = 150.0            # say nothing before ~3 waves have landed: a 2-wave sample is noise
WINDOW = 14 * 60.0         # ...and stop where the early game does (lolbleed.WINDOW)

LEAK_FRAC = 0.55           # took less than this share of the wave that just went by -> MISS
CANNON_LEAD = 14.0         # warn this many seconds before a siege minion arrives
CARD_SECS = 11.0           # how long a MISS keeps the directive slot before going quiet again
_EV_TTL = 600.0            # re-read the behavior ledger at most this often

_EV = {"t": 0.0, "raw": None}
_CSG = {"v": None}


def cs_gold():
    """Gold per CS, DERIVED from lollive.est_gold rather than re-typed - the two must never
    drift. Falls back to that function's documented constant if lollive can't be imported
    (standalone `python lolgold.py`)."""
    if _CSG["v"] is None:
        v = 20.5
        try:
            import lollive as ll
            probe = ll.est_gold({"scores": {"creepScore": 1}}, 0.0) - ll.est_gold({"scores": {}}, 0.0)
            if probe > 0:
                v = probe
        except Exception:
            pass
        _CSG["v"] = v
    return _CSG["v"]


def _evidence():
    """YOUR measured split for the weak-first-ten habit ('with it: 3W-9L / without: 11W-5L'),
    or None when the ledger doesn't have both sides yet. Cached - it's a disk read and this
    is called from a 1s poll loop."""
    now = time.monotonic()
    if _EV["raw"] is not None and (now - _EV["t"]) < _EV_TTL:
        return tf("your games under {cs} CS at 10:00 — {evidence}",
                  cs=BAR_CS10, evidence=_EV["raw"])
    raw = None
    try:
        import lolprofile as lp
        raw = lp.pattern_evidence("weak_first_ten")
    except Exception:
        raw = None
    _EV["t"], _EV["raw"] = now, raw
    return (tf("your games under {cs} CS at 10:00 — {evidence}",
               cs=BAR_CS10, evidence=raw) if raw else None)


# ------------------------------------------------------------------ the wave schedule ----
def waves_by(gt, role):
    """How many minion waves have ARRIVED in your lane by game-time `gt` (seconds). 0 for a
    role that isn't on the lane schedule at all."""
    trav = LANE_ARRIVE.get(role)
    if trav is None:
        return 0
    try:
        t = float(gt) - WAVE_FIRST - trav
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(t) or t < 0:              # a NaN clock is a payload caught mid-write
        return 0
    return int(t // WAVE_EVERY) + 1


def cannons_in(n):
    """Siege minions among the first `n` waves (every 3rd; see the docstring on why that
    rule is safe for this whole window)."""
    return max(0, int(n)) // CANNON_EVERY


def offered(gt, role):
    """(minions, gold) that have arrived in your lane by `gt` - the exact denominator. Gold
    is exact too, not modelled: every minion value is flat until 15:00."""
    n = waves_by(gt, role)
    if n <= 0:
        return 0, 0.0
    c = cannons_in(n)
    minions = n * (MELEE_N + CASTER_N) + c
    gold = n * (MELEE_N * G_MELEE + CASTER_N * G_CASTER) + c * G_CANNON
    return minions, float(gold)


def next_cannon(gt, role):
    """(seconds_until_it_arrives, wave_number) for the next siege minion in your lane, or
    None for a role that isn't on the schedule. Never negative: the instant one lands, this
    rolls to the following one."""
    trav = LANE_ARRIVE.get(role)
    if trav is None:
        return None
    n = waves_by(gt, role)
    k = (n // CANNON_EVERY + 1) * CANNON_EVERY          # next wave index carrying a cannon
    return (WAVE_FIRST + (k - 1) * WAVE_EVERY + trav) - float(gt), k


def cs_equiv(scores):
    """Your CS plus the kill/assist gold you've taken instead, priced back into CS at
    lollive's own rate. This is the number the tag really cares about: 40 CS and three kills
    is not a weak first ten, and calling it one would be the fastest way to teach somebody
    to stop roaming."""
    sc = scores or {}
    try:
        cs = float(sc.get("creepScore") or 0)
        k = float(sc.get("kills") or 0)
        a = float(sc.get("assists") or 0)
    except (TypeError, ValueError):                # a score line caught mid-write
        return 0.0
    v = cs + (k * 300.0 + a * 155.0) / cs_gold()
    return v if math.isfinite(v) else 0.0


def bar_rate(role):
    """The capture FRACTION the tag's own bar implies: 55 CS out of everything that had
    actually arrived in YOUR lane by 10:00. Role-aware on purpose - a side lane is offered
    one wave fewer by then, so the same 55 CS is a slightly higher share of it, and the
    live read should say so instead of pretending every lane is mid."""
    m10 = offered(FIRST_TEN, role)[0]
    return (BAR_CS10 / float(m10)) if m10 else 0.0


def good_rate(role):
    m10 = offered(FIRST_TEN, role)[0]
    return (GOOD_CS10 / float(m10)) if m10 else 0.0


def _mmss(s):
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


# The productive thing to do instead. Deliberately not lolreentry._SAFE (that set is about
# not dying) and not lolclose._LATE (that set is about minute 28): this is lane phase, and
# the instruction is always the same shape - the wave is gold, go and be near it.
_FIX = {"top": "shove it in and take the plate — you don't have to win a trade to win the lane",
        "mid": "shove, then cross to a camp — a wave you walk away from is 105g on the floor",
        "adc": "catch it under tower and farm it out — every wave you drop is a Doran's"}
# ...and what to do instead when the waves alone can no longer get you there.
_LOST = {"top": "the lane won't repay it now — play for plates and the grub window instead",
         "mid": "the lane won't repay it now — take every camp you cross and prio the objective",
         "adc": "the lane won't repay it now — hold the wave and play for the drake fight"}


def _verdict(ctx):
    """Pure: context -> the card (or None). Split out from observe() so the fixtures in
    selftest can drive every branch without a live game."""
    role = ctx.get("role")
    if role not in LANE_ARRIVE:
        return None                       # jungle camps aren't on this schedule; support CS is noise
    gt = float(ctx.get("gt") or 0.0)
    if not math.isfinite(gt) or gt < OPEN_AT or gt > WINDOW:
        return None
    offer, offer_g = float(ctx.get("offer") or 0.0), float(ctx.get("offer_gold") or 0.0)
    if not (math.isfinite(offer) and math.isfinite(offer_g)) or offer <= 0:
        return None
    cs = int(ctx.get("cs") or 0)
    eq = float(ctx.get("eq") if ctx.get("eq") is not None else cs)
    br, gr = bar_rate(role), good_rate(role)
    rate = eq / offer
    pace = br * offer                     # what the bar would have you on RIGHT NOW
    behind = pace - eq
    missed = max(0.0, offer - eq)
    per = offer_g / offer                 # this lane's real gold-per-minion so far (exact)
    lost_g = missed * per
    waves_lost = lost_g / (MELEE_N * G_MELEE + CASTER_N * G_CASTER)     # a plain wave = 105g

    # The deadline we're back-timing to: 10:00 while it's ahead of us, else the window's end.
    # PROJECTION is the number everything hangs off, because it is the tag's own currency -
    # "you are on track to finish minute 10 under 55" is the leak, stated before it happens.
    dl = FIRST_TEN if gt < FIRST_TEN else WINDOW
    off_dl = float(offered(dl, role)[0])
    target = BAR_CS10 if dl == FIRST_TEN else br * off_dl
    proj = rate * off_dl                  # where this capture rate lands you at the deadline
    need = target - eq
    left = max(0.0, off_dl - offer)
    if need <= 0:
        plan = tf("on the {target} by {deadline} — hold this rate",
                  target=int(round(target)), deadline=_mmss(dl))
        recoverable = True
    elif left <= 0 or need > left:
        plan = tf("{need} short of {target} with {left} minions left",
                  need=int(round(need)), target=int(round(target)), left=int(left))
        recoverable = False
    else:
        plan = tf("you need {need} of the next {left} minions ({rate:.0%})",
                  need=int(round(need)), left=int(left), rate=need / left)
        recoverable = True

    under = rate < br
    # The quiet row, as ORDERED SEGMENTS rather than one string: the widget has ~240px for
    # it and joins as many as fit, so a long game state degrades to the important half
    # instead of being ellipsis-clipped mid-number (v0.9.67: "on track for 1…" told you
    # nothing). Most important first.
    #   `30+44 of 82` = 30 CS plus the 44 CS-worth of gold your kills were - the count the
    #   verdict is actually computed on, never hidden behind a percentage.
    lead = (tf("{cs} of {offer}", cs=cs, offer=int(offer)) if eq - cs < 1 else
            tf("{cs}+{equiv} of {offer}", cs=cs, equiv=int(round(eq - cs)),
               offer=int(offer)))
    projection = (tf("on track for {proj}, bar {target}",
                     proj=int(round(proj)), target=int(round(target))) if under else
                  tf("on track for {proj}", proj=int(round(proj))))
    bits = [lead, f"{rate:.0%}", projection]
    row = " · ".join(bits)
    card = {"cs": cs, "eq": round(eq, 1), "offer": int(offer), "pct": round(rate, 3),
            "proj": int(round(proj)), "behind": round(behind, 1), "missed": int(round(missed)),
            "lost_gold": int(round(lost_g)), "waves_lost": round(waves_lost, 1),
            "target": int(round(target)), "need": int(round(max(0.0, need))),
            "left": int(max(0, round(dl - gt))), "deadline": dl,
            "recoverable": recoverable, "ahead": rate >= gr, "under": under,
            "row": row, "bits": bits,
            "clock_txt": None}
    fix = t((_FIX if recoverable else _LOST).get(role, _FIX["mid"]))
    # A live objective verdict outranks a dropped wave, every time: the grub fight IS the
    # reason you left the wave. When the tempo engine has the card, this keeps its row and
    # says nothing louder — but the row still reads `under`, because you still are.
    speak = under and not ctx.get("tempo_urgent")

    # ---- 1. you just gave up a wave, and you are under the bar. The card, at the moment it
    #         happened - not a running scold. It stands down again a few seconds later.
    #         The headline is the PROJECTION, never the raw 'minions missed': a good half of
    #         those were always going to be your opponent's, and a number you can argue with
    #         is a number you stop believing.
    if speak and ctx.get("leaked"):
        card.update(verdict="MISS", tone="hold", quiet=False,
                    line=tf("MISS — that wave went by · on track for {proj} at "
                            "{deadline}, bar {target}",
                            proj=int(round(proj)), deadline=_mmss(dl),
                            target=int(round(target))),
                    sub=tf("{plan} · {instruction}", plan=plan, instruction=fix))
        return card

    # ---- 2. the biggest single object in lane phase is about to land and you're behind it.
    nc = ctx.get("cannon_in")
    if speak and nc is not None and 0 <= float(nc) <= CANNON_LEAD:
        card.update(verdict="CANNON", tone="plan", quiet=False,
                    line=tf("CANNON — siege minion lands in {seconds}s ({gold}g)",
                            seconds=int(round(float(nc))), gold=G_CANNON),
                    sub=tf("be on the wave, not walking to it · {plan}", plan=plan))
        return card

    # ---- 3. the quiet row. One line, all game, never a card: this is a number you want to
    #         be able to glance at, not a coach clearing its throat every thirty seconds.
    card.update(verdict="PACE", tone="hold" if under else "plan", quiet=True,
                line=tf("PACE — {row}", row=row), sub=plan)
    return card


class Guard:
    """One instance per widget session. Stateful for one reason: 'you just gave up a wave'
    can only be seen by remembering where your CS was when the last one arrived."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._gt = 0.0
        self._wave = 0             # index of the last wave we marked
        self._mark = 0.0           # CS-equivalent at that moment
        self._died = False         # ...and whether you were dead at any point since
        self._miss_until = 0.0     # game-time the current MISS card stops owning the slot
        self.calls = 0             # MISS windows opened this game (diagnostics / voice rate)

    def _boundary(self, gt, role, eq, dead):
        """Advance the wave marker. Returns True when the wave that just went by was mostly
        given away - and never when you spent any of it on the grey screen."""
        n = waves_by(gt, role)
        if n <= self._wave:
            self._died = self._died or dead
            return False
        offer_now = offered(gt, role)[0]
        offer_then = offered(WAVE_FIRST + (self._wave - 1) * WAVE_EVERY + LANE_ARRIVE[role],
                             role)[0] if self._wave > 0 else 0
        gap = offer_now - offer_then
        took = eq - self._mark
        leaked = bool(self._wave and not self._died and gap > 0
                      and (took / gap) < LEAK_FRAC)
        self._wave, self._mark, self._died = n, eq, dead
        return leaked

    def observe(self, dd, data, tempo=None):
        """One tick. Returns the PACE row (or a card) while you're in a lane inside the
        first fourteen minutes; None every other moment. `tempo` is this same tick's tempo
        read (ONE BRAIN - the widget already computed it): a MISS stands down to the quiet
        row rather than talk over a live objective verdict."""
        if not data:
            return None
        import lollive as ll
        import loltempo as lt
        split = ll.team_split(data)
        if not split:
            return None
        me, _allies, _enemies, _team = split
        try:
            gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
        except (TypeError, ValueError):            # a payload mid-write: hold, don't crash
            return None
        if not math.isfinite(gt):                  # ...and a NaN clock is a payload mid-write too
            return None
        if gt + 1.0 < self._gt:                    # clock went backwards -> a different game
            self.reset()
        self._gt = gt
        if gt > WINDOW:
            return None

        role = lt._my_role(dd, me)
        if role not in LANE_ARRIVE:
            return None
        eq = cs_equiv(me.get("scores"))
        dead = bool(me.get("isDead"))
        leaked = self._boundary(gt, role, eq, dead)
        if leaked:
            self._miss_until = gt + CARD_SECS
            self.calls += 1
        if dead:                                   # the death screen owns the grey screen
            return None

        offer, offer_g = offered(gt, role)
        nc = next_cannon(gt, role)
        card = _verdict({
            "gt": gt, "role": role, "cs": int((me.get("scores") or {}).get("creepScore") or 0),
            "eq": eq, "offer": offer, "offer_gold": offer_g,
            "leaked": gt < self._miss_until,
            "cannon_in": nc[0] if nc else None,
            "tempo_urgent": bool((tempo or {}).get("urgent")),
        })
        if card is None:
            return None
        card["calls"] = self.calls
        card["evidence"] = _evidence()
        return card


# ---- fixtures for tools/selftest.py: each must land on exactly one verdict ----
def demo(kind):
    """A mid laner at 7:30. offered() at that clock is the real schedule, not a guess."""
    gt, role = 450.0, "mid"
    offer, gold = offered(gt, role)
    base = {"gt": gt, "role": role, "cs": 62, "eq": 62.0, "offer": offer, "offer_gold": gold,
            "leaked": False, "cannon_in": 40.0}
    if kind == "pace":                    # comfortably on the bar -> the quiet row
        pass
    elif kind == "behind":                # under the bar, but nothing just happened
        base.update(cs=30, eq=30.0)
    elif kind == "miss":                  # ...and you just gave up most of a wave
        base.update(cs=30, eq=30.0, leaked=True)
    elif kind == "cannon":                # under the bar with a siege minion inbound
        base.update(cs=30, eq=30.0, cannon_in=9.0)
    elif kind == "roaming":               # 30 CS but three kills: NOT a weak first ten
        base.update(cs=30, eq=30.0 + (3 * 300.0) / cs_gold(), leaked=True, cannon_in=9.0)
    elif kind == "unrecoverable":         # so far under that the waves can't get you there
        base.update(cs=6, eq=6.0, leaked=True)
    elif kind == "onpace_miss":           # a dropped wave while ABOVE the bar stays quiet
        base.update(leaked=True, cannon_in=9.0)
    elif kind == "jungle":                # camps aren't on this schedule -> never speaks
        base.update(role="jungle")
    elif kind == "support":               # a support's CS is noise -> never speaks
        base.update(role="support")
    elif kind == "early":                 # before the sample is worth anything
        base.update(gt=90.0, cs=0, eq=0.0, offer=offered(90.0, "mid")[0],
                    offer_gold=offered(90.0, "mid")[1])
    elif kind == "late":                  # the early game is over; BLEED/tempo own it now
        base.update(gt=900.0)
    return base


if __name__ == "__main__":                # python lolgold.py — the schedule + every branch
    print("wave schedule (mid lane, arrival-counted)")
    for t in (65, 90, 150, 300, 450, 600, 840):
        m, g = offered(float(t), "mid")
        nc = next_cannon(float(t), "mid")
        print(f"  {_mmss(t):>5}  {waves_by(float(t), 'mid'):2d} waves  {m:3d} minions  "
              f"{int(g):5d}g   next cannon in {int(nc[0]):3d}s (wave {nc[1]})")
    print(f"\nbar: {BAR_CS10} CS by 10:00 = {bar_rate('mid'):.1%} of the mid lane "
          f"({offered(FIRST_TEN, 'mid')[0]} minions) / {bar_rate('adc'):.1%} of a side lane "
          f"({offered(FIRST_TEN, 'adc')[0]} minions)\n")
    for k in ("pace", "behind", "miss", "cannon", "roaming", "unrecoverable", "onpace_miss",
              "jungle", "support", "early", "late"):
        c = _verdict(demo(k))
        if not c:
            print(f"{k:14} (silent)")
        else:
            q = " [quiet row]" if c.get("quiet") else ""
            print(f"{k:14} {c['verdict']:6}{q} {c['line']}\n               {c['sub']}")
