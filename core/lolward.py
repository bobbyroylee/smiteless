#!/usr/bin/env python3
"""lolward.py - THE WARD CLOCK: the map you can see, against the map they can see.

THE LEAK THIS EXISTS FOR
lolprofile.behavior_read tags a game `low_vision` ("no vision setup") when your vision
score per minute finishes under the bar for your role - 1.2/min for a support, 0.55/min
for a jungler. It is the LAST tag in the behaviour ledger with no in-game surface, and
that is exactly why this module exists: BLEED (lolbleed) owns the first fourteen minutes
of your health bar, RE-ENTRY (lolreentry) the ninety seconds after a death, THE CLOSER
(lolclose) the closeout, THE GOLD CLOCK (lolgold) the first-ten farm pace - and the gold
clock is deliberately SILENT for jungle and support, because camps are not on the lane
schedule and a support's CS was never the story.

So the two roles with nothing to read were the two roles whose whole job this is. This
surface is theirs, and it is silent for everybody else for the same reason the gold clock
is silent for them: lolprofile has never evaluated a laner on vision, and inventing a
number for one here would make the app argue with its own review page.

WHY VISION SCORE, AND WHY A DIFFERENTIAL
:2999 reports `scores.wardScore` for ALL TEN PLAYERS, every tick, unfiltered by fog. That
is a rare thing in this feed - enemy items go stale the moment they leave your vision, but
this number never does. It buys two reads nothing else in the app can make:

  1. THE COUNTERPART. Your vision score against the enemy in YOUR role, live. Same role,
     same game length, same units, both measured - so the comparison is exact rather than
     modelled, and it is the only scoreboard in the game that shows who is winning the
     vision war while you can still do something about it.
  2. DARK. Vision score is MONOTONE: it only ever goes up, and it goes up while wards you
     placed are giving your team vision. So a score that has not moved in a hundred seconds
     is not an opinion - it is a measurement that nothing of yours is on the map. That is
     the fact this whole surface hangs off, and it needs no modelling constant at all.

Both of those are worth more in one specific place than everywhere else combined, which is
the third read:

  3. THE PIT. The ~75 seconds before a neutral objective spawns is the window the tempo
     engine already owns ("team fights 4v5 with no vision" is loltempo's own opening line).
     If your vision has been flat going INTO that window, the fight that is about to happen
     is a coinflip you chose. The bar to speak is lower here than anywhere else on purpose -
     45s of dark instead of 100 - because "ward the pit before the drake" is never bad
     advice, so a false positive costs nothing and a miss costs the objective.

ARMING (why this can never invent a warning)
The whole surface stays asleep until it has SEEN a non-zero vision score from somebody in
the game - proof the field is live in this build/queue. If Riot ever drops the field, or
zeroes it, or a custom lobby doesn't report it, every read here degrades to silence rather
than telling a support who has warded all game that he is dark. One tripwire, checked every
tick, and it is the difference between a guard and a liar.

PIT  - a neutral objective is inside its setup window and nothing of yours is alive. The card.
DARK - your vision score has not moved in 1:40. The card, briefly, then it stands down.
PINK - the control ward in your bag has been in your bag for two minutes. 75g doing nothing.
WARD - the quiet row: you vs your counterpart, your per-minute against your role's bar, stock.
None - outside a lane role that owns vision, dead, too early, or the feed isn't reporting.

It never counts DARK time you spent on the grey screen: you cannot ward from the fountain,
and billing you for a death you are already being billed for by two other guards is how a
coach gets switched off.

House rule (docs/TAGS.md spirit): the card carries its receipt - YOUR OWN W/L split for the
habit, straight out of the behavior ledger, so it is your data talking and not folklore.

100% read-only off :2999. No input, no camera, nothing automated.

  python lolward.py        # print every branch from the fixtures
"""
import math
import time

# ---- what the live feed calls things ----
WARD_KEYS = ("wardScore", "visionScore")   # :2999 calls it wardScore; alias kept defensively
CTRL_WARD = 2055                           # Control Ward (the only ward you buy and carry)
CTRL_GOLD = 75                             # ...and what it costs, so the waste has a price

# ---- the windows ----
OPEN_AT = 180.0        # say nothing before 3:00: nobody's vision score means anything yet
DARK_SECS = 100.0      # vision score flat this long -> nothing of yours is alive. Deliberately
                       # longer than any plausible accrual tick: one ward alive anywhere on the
                       # map moves this number well inside 100s, so a flat span is a fact.
PIT_DARK = 45.0        # ...but inside an objective's setup window the bar is this instead. The
                       # advice there ("ward the pit") is free, so the cost of speaking early is
                       # zero and the cost of staying quiet is the objective.
PIT_TAIL = 60.0        # keep calling for this long after it actually spawns (it's still a fight)
PINK_HOLD = 120.0      # a control ward carried this long without being placed is 75g of nothing
CARD_SECS = 10.0       # how long a DARK/PINK card keeps the directive slot before going quiet
_EV_TTL = 600.0        # re-read the behavior ledger at most this often

# The tempo phases that are a FIGHT DECISION rather than a setup instruction. Once the call is
# "take it" or "give it", vision advice is a second too late and a second card is noise - the
# ward clock keeps its quiet row and lets the tempo engine have the slot. During the SETUP
# phases (MOVE/BASE/PUSH/FARM) it is strictly additive: tempo says where to walk, this says
# what the pit currently looks like to your team, which is a fact tempo does not have.
FIGHT_PHASES = ("TAKE", "GIVE", "EVEN", "FORCE", "FREE")

# The roles lolprofile evaluates for vision, in loltempo._my_role's vocabulary. Exactly the two
# the gold clock stays silent for - between them, every role now has one surface that is its own.
ROLE_POS = {"support": "UTILITY", "jungle": "JUNGLE"}
ROLE_WORD = {"support": "support", "jungle": "jungler"}      # how the row names your opposite
_VPM_FALLBACK = {"UTILITY": 1.2, "JUNGLE": 0.55}     # only used if lolprofile can't be imported

# Which river a pit sits in. Same table loltempo routes rotations with; kept as a local copy
# only because importing loltempo at module scope would be a cycle (it imports lollive, which
# the widget already has loaded) - selftest asserts the two never drift.
OBJ_SIDE = {"Drake": "bot", "Elder": "bot", "Baron": "top", "Herald": "top", "Grubs": "top"}

_EV = {"t": 0.0, "text": None}
_BAR = {"v": None}


def vpm_bar(role):
    """Vision score per minute your role has to clear, DERIVED from lolprofile's own
    `low_vision` bar rather than re-typed - the review page and the live guard must never
    disagree about what 'enough vision' is. Falls back to that tag's documented numbers if
    lolprofile can't be imported (standalone `python lolward.py`)."""
    if _BAR["v"] is None:
        bar = dict(_VPM_FALLBACK)
        try:
            import lolprofile as lp
            if isinstance(getattr(lp, "VPM_BAR", None), dict) and lp.VPM_BAR:
                bar = dict(lp.VPM_BAR)
        except Exception:
            pass
        _BAR["v"] = bar
    return _BAR["v"].get(ROLE_POS.get(role, ""), 0.0)


def _evidence():
    """YOUR measured split for the no-vision habit ('with it: 2W-7L / without: 9W-4L'), or
    None when the ledger doesn't have both sides yet. Cached - it's a disk read and this is
    called from a 1s poll loop."""
    now = time.monotonic()
    if _EV["text"] is not None and (now - _EV["t"]) < _EV_TTL:
        return _EV["text"]
    txt = None
    try:
        import lolprofile as lp
        raw = lp.pattern_evidence("low_vision")
        if raw:                       # "with it: 2W-7L · without: 9W-4L" — name what "it" is
            txt = "your games under the vision bar — " + raw
    except Exception:
        txt = None
    _EV["t"], _EV["text"] = now, txt
    return txt


def ward_score(p):
    """One player's vision score off the live feed, or None when the field isn't there. None
    and 0.0 are NOT the same thing here and never get collapsed: 0.0 is 'has warded nothing',
    None is 'this build isn't telling us', and only one of those is safe to coach on."""
    sc = (p or {}).get("scores") or {}
    for k in WARD_KEYS:
        v = sc.get(k)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):            # a score line caught mid-write
            return None
        return f if math.isfinite(f) else None
    return None


def feed_live(players):
    """True once ANY player in the game has a non-zero vision score - the tripwire that proves
    :2999 is actually reporting the field in this build. Until it trips, this whole surface
    stays silent rather than tell a support who has warded all game that he is dark."""
    for p in players or []:
        v = ward_score(p)
        if v is not None and v > 0:
            return True
    return False


def ctrl_wards(p):
    """Control wards in this player's inventory. Riot reports a stackable as one slot with a
    count, so this sums counts and not slots."""
    n = 0
    items = (p or {}).get("items")
    if not isinstance(items, (list, tuple)):       # a payload caught mid-write, or a shape change
        return 0
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            if int(it.get("itemID") or 0) == CTRL_WARD:
                n += int(it.get("count") or 1)
        except (TypeError, ValueError):
            continue
    return n


def counterpart(me, enemies, role=None):
    """The enemy playing YOUR role - the only fair comparison for a vision score, because it
    is the same job over the same number of minutes. Position first (ranked/normals report
    it); for a jungler, lollive's smite check is the fallback; for a support, the enemy with
    the fewest minions is. Returns None rather than guess wrong - the row simply drops the
    segment, which is the house rule everywhere else too.

    `role` is loltempo._my_role's answer for YOU, which knows things the position field
    doesn't (it falls back to the role you locked at champ select when :2999 reports none).
    Without it this is position-only, and a role this surface never speaks for gets None."""
    enemies = [p for p in (enemies or []) if isinstance(p, dict)]
    pos = (me or {}).get("position") or ""
    role = role or {"JUNGLE": "jungle", "UTILITY": "support"}.get(pos.upper())
    if role not in ROLE_POS:
        return None                     # only the two roles graded on vision have a counterpart
    want = ROLE_POS[role]
    same = [p for p in enemies or [] if (p.get("position") or "").upper() == want]
    if len(same) == 1:
        return same[0]
    if role == "jungle":
        try:
            import lollive as ll
            jgs = [p for p in enemies or [] if ll._is_jungler(p)]
            if len(jgs) == 1:
                return jgs[0]
        except Exception:
            pass
    if role == "support":
        cs = [(float((p.get("scores") or {}).get("creepScore") or 0), p) for p in enemies or []]
        if len(cs) >= 2:
            cs.sort(key=lambda t: t[0])
            if cs[0][0] < cs[1][0]:                # a clear low-CS player = the support
                return cs[0][1]
    return None


def pit_window(objs):
    """The neutral objective whose setup window is OPEN right now, or None. The window itself
    is lollive.objectives()' own `setup`/`urgent` flags (ONE BRAIN - the widget's objective
    chips and this guard can never disagree about when a fight is coming), plus a short tail
    after it actually spawns, because an uncontested drake sitting in an unwarded pit is the
    same problem thirty seconds later."""
    for o in objs or []:
        label = o.get("label")
        if label not in OBJ_SIDE:                  # scuttle isn't a pit; nothing else is either
            continue
        try:
            secs = float(o.get("secs") or 0)
        except (TypeError, ValueError):
            continue
        if o.get("setup") or o.get("urgent"):
            return o
        if o.get("up") and secs > -PIT_TAIL:
            return o
    return None


def _mmss(s):
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


# WHERE to put it. The instruction changes with the game state and it has to, because the two
# answers are opposites: ahead you buy information about their next move, behind you buy the
# few seconds that let you leave. lolprofile's own review line says exactly this ("deep wards
# when ahead, defensive wards when behind") — this is that sentence, at the moment it applies.
def _where(side, ahead):
    if ahead is True:
        return (f"go PAST the pit — their {side} jungle entrance, so you see them walk in "
                f"and the fight starts on your terms")
    if ahead is False:
        return (f"your own {side} tri and the pit mouth — behind, you're buying the seconds "
                f"that let you leave, not a fight")
    return f"the {side} river bush and the pit mouth — a pit you can't see is a coinflip"


_DARK_FIX = {"support": "you have two trinket charges and they cap — a charge you're saving is "
                        "a ward that isn't on the map",
             "jungle": "ward the camp you're walking to, not the one you just did — vision "
                       "in front of your path is what makes a counter-gank free"}


def _verdict(ctx):
    """Pure: context -> the card (or None). Split out from observe() so the fixtures in
    selftest can drive every branch without a live game."""
    role = ctx.get("role")
    if role not in ROLE_POS:
        return None                        # lolprofile never grades a laner on vision
    if not ctx.get("armed"):
        return None                        # the feed hasn't proven itself — say nothing at all
    gt = float(ctx.get("gt") or 0.0)
    if not math.isfinite(gt) or gt < OPEN_AT:
        return None
    vs = ctx.get("vs")
    if vs is None:
        return None                        # no number for US -> no claim about us
    vs = float(vs)
    if not math.isfinite(vs):
        return None
    bar = vpm_bar(role)
    vpm = vs / max(1.0, gt / 60.0)
    them = ctx.get("them")
    them = float(them) if them is not None and math.isfinite(float(them)) else None
    dark = max(0.0, float(ctx.get("dark") or 0.0))
    pinks = int(ctx.get("pinks") or 0)
    pit = ctx.get("pit") or None
    under = vpm < bar

    # The quiet row, as ORDERED SEGMENTS rather than one string: the widget has ~240px for it
    # and joins as many as fit, so a long game state degrades to the important half instead of
    # being clipped mid-number. Most important first — the head-to-head is the whole point.
    lead = f"{vs:.1f}" + (f" v {them:.1f}" if them is not None else "")
    bits = [lead, f"{vpm:.1f}/min" + (f", bar {bar:.2f}".rstrip("0").rstrip(".") if under else "")]
    if pinks:
        bits.append(f"{pinks} pink" + ("s" if pinks > 1 else ""))
    elif dark >= 30:
        bits.append(f"dark {_mmss(dark)}")
    card = {"vs": round(vs, 1), "them": (round(them, 1) if them is not None else None),
            "vpm": round(vpm, 2), "bar": bar, "under": under,
            "gap": (round(vs - them, 1) if them is not None else None),
            "dark": int(round(dark)), "pinks": pinks, "role": role,
            "row": " · ".join(bits), "bits": bits, "clock_txt": None}

    # A fight verdict from the tempo engine outranks everything here: once the call is TAKE or
    # GIVE the decision is made, and a second card about wards is a card you learn to skip.
    if str(ctx.get("tempo_phase") or "") in FIGHT_PHASES:
        card.update(verdict="WARD", tone="plan", quiet=True, line=f"WARD — {card['row']}",
                    sub=f"vision {vpm:.1f}/min against a {bar:g} bar")
        return card

    # ---- 1. an objective is coming and your team is walking into an unlit pit. The single
    #         highest-leverage moment this surface has, and the only one where it speaks on a
    #         SHORTER dark clock — because "ward before the drake" cannot be wrong.
    if pit and dark >= PIT_DARK:
        label = pit.get("label") or "Drake"
        side = OBJ_SIDE.get(label, "bot")
        try:
            secs = float(pit.get("secs") or 0)
        except (TypeError, ValueError):
            secs = 0.0
        when = f"in {int(round(secs))}s" if secs > 0 else "is UP"
        # The clock slot carries the DARK duration, not the objective countdown: the countdown
        # is already in the headline (and on the widget's own objective chip), and the number
        # only this surface knows is how long the map has been unlit.
        card.update(verdict="PIT", tone="hold", quiet=False, obj=label, secs=int(round(secs)),
                    clock_txt=_mmss(dark),
                    line=f"PIT — {label.lower()} {when} and nothing of yours is alive",
                    sub=_where(side, ctx.get("ahead")))
        return card

    # ---- 2. no objective pending, but the map has been dark for a minute and forty. Said
    #         once, held for a few seconds, then it hands the slot straight back.
    if dark >= DARK_SECS and ctx.get("dark_card"):
        gapt = (f" · they're on {them:.0f}" if them is not None and them > vs else "")
        card.update(verdict="DARK", tone="hold", quiet=False, clock_txt=_mmss(dark),
                    line=f"DARK — {_mmss(dark)} with no vision of yours on the map{gapt}",
                    sub=(_DARK_FIX.get(role, "") or "") if not pinks else
                        f"you are carrying {pinks} control ward{'s' if pinks > 1 else ''} — "
                        f"that is {pinks * CTRL_GOLD}g of map you already paid for")
        return card

    # ---- 3. the pink in your bag. Bought, carried, never placed — the most fixable half of
    #         this tag, and the only one that costs you gold as well as the map.
    if pinks and ctx.get("pink_card"):
        held = _mmss(ctx.get("held") or 0)
        card.update(verdict="PINK", tone="plan", quiet=False, clock_txt=held,
                    line=f"PINK — {pinks * CTRL_GOLD}g of control ward, carried {held}",
                    sub="it does nothing in your bag — the pit mouth before the next objective, "
                        "your own tri when you're behind")
        return card

    # ---- 4. the quiet row. One line, all game: this is a scoreboard you want to be able to
    #         GLANCE at, not a coach clearing its throat every thirty seconds.
    card.update(verdict="WARD", tone="hold" if under else "plan", quiet=True,
                line=f"WARD — {card['row']}",
                sub=(f"{vs - them:+.0f} on their {ROLE_WORD.get(role, role)} — this is the vision war"
                     if them is not None else f"vision {vpm:.1f}/min against a {bar:g} bar"))
    return card


class Guard:
    """One instance per widget session. Stateful for three reasons, all of them the same
    reason: a vision score is a running total, and every read worth making here is about how
    long it has been since it MOVED."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._gt = 0.0
        self._vs = None            # last vision score we saw for you
        self._moved = None         # game-time it last went UP  (None until we have a baseline)
        self._armed = False        # the feed has proven it reports the field (see feed_live)
        self._pinks = 0            # control wards in your bag last tick
        self._pink_at = None       # ...and when this stock started sitting there
        self._pink_said = False    # one PINK card per stock, not one per second
        self._card_until = 0.0     # game-time the current DARK/PINK card stops owning the slot
        self._dark_said = 0.0      # game-time of the last DARK card (rate-limits the repeat)
        self._said = None          # the verdict currently owning the slot (edge detection)
        self.calls = 0             # cards opened this game (diagnostics / voice rate)

    # -- state, split out so selftest can drive it without building a whole payload --
    def _track(self, gt, vs, dead, pinks):
        """Advance the vision + stock clocks one tick. Returns seconds of DARK."""
        dt = max(0.0, gt - self._gt)
        if self._vs is None or self._moved is None:        # first sight: start the clock here
            self._vs, self._moved = vs, gt
        elif vs > self._vs + 1e-9:                         # it moved -> you have vision alive
            self._vs, self._moved = vs, gt
        elif vs < self._vs - 1e-9:                         # went backwards -> not the same game
            self._vs, self._moved = vs, gt
        if dead:
            # You cannot ward from the fountain. FREEZE the dark clock rather than reset it:
            # resetting would hand out a free 100 seconds after every death (and this guard
            # would go quiet exactly when a support dies for being blind), while letting it
            # run bills you a second time for a death two other guards already own.
            self._moved = min(gt, (self._moved or gt) + dt)
        if pinks != self._pinks:                           # bought or placed one
            self._pink_at = gt if pinks else None
            self._pink_said = False
            self._pinks = pinks
        elif pinks and self._pink_at is None:
            self._pink_at = gt
        return max(0.0, gt - (self._moved if self._moved is not None else gt))

    def observe(self, dd, data, tempo=None, objs=None, winprob=None):
        """One tick. Returns the WARD row (or a card) while you're playing a role that owns
        vision; None every other moment. `tempo`/`objs`/`winprob` are this same tick's reads
        off the shared payload (ONE BRAIN - the widget already computed them, and re-deriving
        them here is how two surfaces start telling different stories about one game)."""
        if not data:
            return None
        import lollive as ll
        import loltempo as lt
        split = ll.team_split(data)
        if not split:
            return None
        me, _allies, enemies, _team = split
        try:
            gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
        except (TypeError, ValueError):            # a payload caught mid-write: hold, don't crash
            return None
        if not math.isfinite(gt):
            return None
        if gt + 1.0 < self._gt:                    # clock went backwards -> a different game
            self.reset()

        role = lt._my_role(dd, me)
        vs = ward_score(me)
        self._armed = self._armed or feed_live(data.get("allPlayers"))
        dead = bool(me.get("isDead"))
        dark = self._track(gt, vs, dead, ctrl_wards(me)) if vs is not None else 0.0
        self._gt = gt
        if dead:                                   # the death screen owns the grey screen
            return None
        if role not in ROLE_POS or vs is None or not self._armed:
            return None

        # One card at a time, and each of them stands down on its own clock. DARK repeats no
        # more than once per its own window - a warning you get every second is wallpaper.
        # Each card is DUE when its own clock says so, but the rate limit is only SPENT if it
        # actually wins the slot below. PIT outranks both, and a card you were never shown
        # must not be the reason you don't get shown the next one.
        dark_due = dark >= DARK_SECS and (gt - self._dark_said) >= DARK_SECS
        pink_due = (self._pink_at is not None and not self._pink_said
                    and (gt - self._pink_at) >= PINK_HOLD)
        held = (gt - self._pink_at) if self._pink_at is not None else 0.0
        cp = counterpart(me, enemies, role)
        card = _verdict({
            "gt": gt, "role": role, "vs": vs, "them": ward_score(cp) if cp else None,
            "dark": dark, "pinks": self._pinks, "held": held,
            "pit": pit_window(objs), "armed": True,
            "ahead": (winprob or {}).get("ahead") if winprob else None,
            "tempo_phase": (tempo or {}).get("phase"),
            "dark_card": dark_due or (gt < self._card_until and dark >= DARK_SECS),
            "pink_card": pink_due or (gt < self._card_until and self._pink_said and self._pinks),
        })
        if card is None:
            return None
        if card["verdict"] == "DARK" and dark_due:          # shown -> now the clock is spent
            self._dark_said, self._card_until = gt, gt + CARD_SECS
        elif card["verdict"] == "PINK" and pink_due:
            self._pink_said, self._card_until = True, gt + CARD_SECS
        # `calls` counts WINDOWS, not ticks: a card holds the slot for CARD_SECS so you can
        # read it, and something rate-limiting a voice line off this number needs "how many
        # times has it spoken", not "how many frames has it been up".
        vd = card["verdict"] if not card.get("quiet") else None
        if vd and vd != self._said:
            self.calls += 1
        self._said = vd
        card["calls"] = self.calls
        card["evidence"] = _evidence()
        return card


# ---- fixtures for tools/selftest.py: each must land on exactly one verdict ----
def demo(kind):
    """A support at 9:00, on a bar of 1.2/min. Every branch below is reachable live."""
    base = {"gt": 540.0, "role": "support", "vs": 14.0, "them": 15.0, "dark": 10.0,
            "pinks": 0, "held": 0.0, "pit": None, "armed": True, "ahead": None,
            "tempo_phase": "FARM", "dark_card": False, "pink_card": False}
    if kind == "row":                     # comfortably on the bar -> the quiet row
        pass
    elif kind == "under":                 # under the bar, nothing else happening -> still a row
        base.update(vs=4.0)
    elif kind == "pit":                   # a drake is coming and you have nothing on the map
        base.update(vs=4.0, dark=60.0,
                    pit={"label": "Drake", "secs": 40, "setup": True, "urgent": False, "up": False})
    elif kind == "pitup":                 # ...and the same call once it has actually spawned
        base.update(vs=4.0, dark=60.0,
                    pit={"label": "Baron", "secs": -20, "setup": False, "urgent": False, "up": True})
    elif kind == "pitshort":              # a pit is open but you warded 20s ago -> no claim
        base.update(vs=4.0, dark=20.0,
                    pit={"label": "Drake", "secs": 40, "setup": True, "urgent": False, "up": False})
    elif kind == "pitfight":              # tempo already called the fight -> stand down to the row
        base.update(vs=4.0, dark=60.0, tempo_phase="TAKE",
                    pit={"label": "Drake", "secs": 40, "setup": True, "urgent": False, "up": False})
    elif kind == "dark":                  # no objective, but the map has been dark 1:40+
        base.update(vs=4.0, dark=110.0, dark_card=True)
    elif kind == "darkquiet":             # ...the same state after the card has stood down
        base.update(vs=4.0, dark=110.0, dark_card=False)
    elif kind == "pink":                  # 75g of control ward, carried two minutes
        base.update(pinks=1, held=140.0, pink_card=True)
    elif kind == "pinkquiet":             # ...and it is not said twice
        base.update(pinks=1, held=140.0, pink_card=False)
    elif kind == "jungle":                # the other role that owns vision, on its own bar
        base.update(role="jungle", vs=3.0)
    elif kind == "adc":                   # lolprofile never grades a laner on vision -> silent
        base.update(role="adc")
    elif kind == "mid":
        base.update(role="mid")
    elif kind == "notarmed":              # the feed has never reported a vision score -> silent
        base.update(armed=False)
    elif kind == "nofield":               # ...or it has no number for US
        base.update(vs=None)
    elif kind == "early":                 # before anyone's vision score means anything
        base.update(gt=100.0)
    elif kind == "nocounterpart":         # can't identify their support -> drop the segment
        base.update(them=None)
    return base


if __name__ == "__main__":                # python lolward.py — every branch, printed
    print(f"bars: support {vpm_bar('support')}/min · jungle {vpm_bar('jungle')}/min "
          f"(lolprofile.low_vision)\n")
    for k in ("row", "under", "pit", "pitup", "pitshort", "pitfight", "dark", "darkquiet",
              "pink", "pinkquiet", "jungle", "adc", "mid", "notarmed", "nofield", "early",
              "nocounterpart"):
        c = _verdict(demo(k))
        if not c:
            print(f"{k:15} (silent)")
        else:
            q = " [quiet row]" if c.get("quiet") else ""
            print(f"{k:15} {c['verdict']:5}{q} {c['line']}\n                {c['sub']}")
