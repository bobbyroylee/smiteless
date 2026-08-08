#!/usr/bin/env python3
"""lolout.py - THE OUT: the losing game, answered while it can still be won or ended.

WHY THIS EXISTS
Everything in this app is judged on one thing: LP per hour. Every surface built so far
attacks the numerator - win the game you're in. Nothing has ever touched the DENOMINATOR,
and half of it is spent inside games that were decided ten minutes ago. A 38-minute loss
and a 24-minute loss cost the same LP; the difference is fourteen minutes you will never
queue with. Over a climb that is not a rounding error, it is games.

And the mirror of it costs even more: a game your team throws away at the 15:00 vote that
was never actually lost. THE CLOSER (lolclose) owns the game you are winning and says
nothing at all when you are behind - deliberately. This is the other half of that map, and
it answers exactly one question at the only moment anybody asks it:

    you are behind. is there still a path, and what is it?

WHAT IT DOES
From 15:00 - the first surrender window; there is no such thing as a "decided" game before
one exists - and ONLY while you are behind by the same 2k the CLOSER calls "ahead" on, it
looks for an OUT. An out is a fact with a clock on it, never a mood:

  BARON      - the objective that erases a deficit, live and contestable right now.
  ELDER/SOUL - the drake that decides it, when the next one is yours to take.
  ACE MATH   - past ~28:00 their deaths cost 50s+. One won fight IS the map, and this is
               the number: their own death timer at their own level, on the live clock.
  SCALING    - you out-scale them (same power-curve table the champ-select game plan
               grades comps with - ONE BRAIN) and the game has not reached you yet.
  STRUCTURE  - nothing of yours is open. They are up gold and have to actually come get
               it, which is a fight on your terms next to your turrets.

If one of those holds, the game is live and the card says so - because the most expensive
thing that happens in a losing game is a team that stops playing one it could still win.

CALL IT - and it is deliberately hard to reach. Three facts have to be true at once, all
measured, none modelled: 20:00+, 8k+ down, and they are INSIDE YOUR BASE (an inhibitor of
yours open, or a nexus turret gone) with a 5v5 you lose by a mile - and no live out. That
is not "you are losing", that is a game with no remaining mechanism. Then it says the true
thing: the LP is already spent, the clock is the only thing left to save, and the next
game starts when this one ends.

THE NUMBER NOBODY SHOWS YOU: what you have CLAWED BACK. The CLOSER tracks a lead's peak
because a lead being given back is a game being thrown in slow motion. The mirror is the
trough - `-4.2k, won back 3.7k of 7.9k` - and it is the single most useful thing you can
put in front of a team deciding whether to keep playing, because it is the comeback
happening, in the same measured gold, before anyone can feel it.

House rules kept: it stands down to a quiet row the moment the tempo engine has a live
objective verdict, it never speaks aloud, and every number on it is measured off :2999
except the scaling curve, which says out loud that it is modelled.

100% read-only. No input, no camera, nothing automated - it cannot vote for you and it
never will.

  python lolout.py        # print every branch from the fixtures
"""
import lolclose as lcl
from smitei18n import t, tf

OUT_FROM = 15 * 60.0       # 15:00 — the first surrender window. Before one exists, a
                           # "decided game" is a feeling, not a state.
CALL_FROM = 20 * 60.0      # ...and a write-off needs more than the first window
BEHIND_MIN = lcl.LEAD_MIN  # 2000 — ONE BRAIN: the exact bar the CLOSER calls "ahead" on,
                           # mirrored, so the two guards can never both be silent (or both
                           # talk) about the same game state.
CALL_GOLD = 8000.0         # the write-off deficit
CALL_E = -3000.0           # ...and a 5v5 you lose by this much
E_CONTEST = -1000.0        # you can plausibly contest an objective at this edge
OBJ_LEAD = 60.0            # an objective this close is a live window, not a plan
SOUL_LEAD = 90.0           # ...soul gets a longer fuse: it is worth setting up for
LATE_ACE = 28 * 60.0       # from here, their death timers alone are an out
ACE_SECS = 45.0            # ...once one death costs them this many seconds
VOTE_WIN = 45.0            # seconds a surrender-vote moment stays "now"
WON_MIN = 1500.0           # gold clawed back off the trough before it is worth saying
NEXUS_TURRETS = 4          # mid turret count at which a NEXUS turret is down (3 lane + 1)

# What to do while you wait for the out, by role. Deliberately not lolclose._LATE (that set
# is written from ahead — "make them come to you" is nonsense when they already are) and not
# lolreentry._SAFE (lane phase). Playing from behind is its own sport: the only losing move
# is the fight you did not have to take.
_HOLD = {"top": "hold your side wave under tower — a wave lost here is a free turret for them",
         "mid": "hold mid short and keep your side clear — nothing past the river is worth it",
         "jungle": "farm your own half and ward your own entrances — no invades from behind",
         "adc": "farm what is safe and never walk up alone — you ARE the comeback",
         "support": "ward your own jungle and peel — no roams into fog"}


def _k(v):
    return f"{v / 1000:+.1f}k"


def _mmss(s):
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------------- the outs ----
def _immediate(ctx):
    """The outs with a CLOCK on them — an objective you can be standing on inside a minute.
    These are the only ones that can block a CALL IT, because they are the only ones that
    change the game before the enemy team can end it. Returns (line, sub, tag) or None —
    `tag` is the three-word version for the quiet row, which gets one line and no wrap."""
    e = float(ctx.get("e") or 0.0)
    bodies = float(ctx.get("bodies") or 0.0)
    dead_n = int(ctx.get("dead_enemies") or 0)
    # "contestable" is not optimism: two of them dead, or an edge the tempo engine itself
    # would not call a loss. A 5v5 you lose by 4k at the pit is not an out, it is the loss.
    contest = dead_n >= 2 or bodies >= 1.0 or e >= E_CONTEST
    baron = ctx.get("baron_secs")
    if baron is not None and baron <= OBJ_LEAD and contest:
        when = t("is up") if baron <= 0 else tf("in {time}", time=_mmss(baron))
        why = (tf("{count} of them dead", count=dead_n) if dead_n >= 2 else
               t("you win the fight for it") if bodies >= 1.0 else t("the fight for it is close"))
        return (tf("OUT — baron {when}, and {reason}", when=when, reason=why),
                t("baron is the only thing on this map that erases a deficit — group as five and take the fight at the pit, not on the way to it"),
                tf("baron {when}", when=t("up") if baron <= 0 else _mmss(baron)))
    drake = ctx.get("drake_secs")
    if drake is not None and drake <= OBJ_LEAD and ctx.get("elder") and contest:
        when = t("is up") if drake <= 0 else tf("in {time}", time=_mmss(drake))
        return (tf("OUT — elder {when} and it is contestable", when=when),
                t("elder execute wins a fight you should lose — stack up and take it as five"),
                tf("elder {when}", when=t("up") if drake <= 0 else _mmss(drake)))
    if (drake is not None and drake <= SOUL_LEAD and int(ctx.get("my_drakes") or 0) == 3
            and not ctx.get("elder")):
        when = t("is up") if drake <= 0 else tf("in {time}", time=_mmss(drake))
        return (tf("OUT — soul point: the drake {when} is yours to take", when=when),
                t("soul changes every fight after it — set up early and make this the fight"),
                t("soul point"))
    return None


def _standing(ctx):
    """The outs without a clock — true for the next several minutes rather than the next
    sixty seconds. They are what you PLAY toward; they never block a write-off, because a
    plan is not a mechanism when they are already in your base. Returns (line, sub, tag)."""
    gt = float(ctx.get("gt") or 0.0)
    their_death = float(ctx.get("their_death_cost") or 0.0)
    if gt >= LATE_ACE and their_death >= ACE_SECS:
        secs = int(round(their_death))
        return (tf("OUT — one won fight is the map: their deaths cost {seconds}s", seconds=secs),
                t("stop trading small — group as five, take the fight you choose next to an objective, and end it on the timers"),
                tf("their deaths {seconds}s", seconds=secs))
    gap = ctx.get("scale_gap")
    items = ctx.get("my_items")
    if gap is not None and float(gap) >= _scale_gap() and gt < LATE_ACE:
        tail = (tf(" — you are {items} items in", items=int(items)) if items is not None else "")
        return (tf("OUT — you out-scale them, so time is on your side{tail}", tail=tail),
                t("modelled off both comps' power curves: farm every safe wave, take every neutral, and refuse the fight until you have your third item"),
                t("you out-scale"))
    # "nothing of yours is open" only counts as an out while it is still a statement about
    # the map: once they have all three turrets in a lane the inhibitor behind it is exposed
    # and the sentence is a technicality, so the read drops to SURVIVE rather than reassure.
    deep = int(ctx.get("their_deepest") or 0)
    if (not (ctx.get("our_open_inhibs") or []) and not ctx.get("nexus_turret")
            and deep < lcl.LANE_TURRETS):
        tail = (tf(" — {count} of your turrets down in their best lane", count=deep) if deep else "")
        return (tf("OUT — nothing of yours is open{tail}", tail=tail),
                t("they are up gold and still have to come get it — defend on your side of the river, next to your turrets, and make them force through you"),
                t("base intact"))
    return None


def _scale_gap():
    """The comp power-curve gap that counts as out-scaling. Read through lollive so this
    guard and the champ-select game plan can never disagree about the same two comps."""
    try:
        import lollive as ll
        return float(ll.SCALE_GAP)
    except Exception:
        return 0.25


# ----------------------------------------------------------------- the verdict ----
def _verdict(ctx):
    """Pure: context -> the card (or None). Split out from observe() so the fixtures in
    tools/selftest.py can drive every branch without a live game."""
    gt = float(ctx.get("gt") or 0.0)
    if gt < OUT_FROM:
        return None                     # no surrender window yet: nothing to have a view on
    lead = float(ctx.get("lead") or 0.0)
    if lead > -BEHIND_MIN:
        return None                     # not behind — THE CLOSER owns this half of the map
    trough = min(float(ctx.get("trough", lead)), lead)
    won = max(0.0, lead - trough)
    won_txt = (tf("won back {won:.1f}k of {trough:.1f}k", won=won / 1000,
                  trough=abs(trough) / 1000)
               if won >= WON_MIN else None)
    card = {"lead": lead, "won": won, "clock_txt": _k(lead), "won_txt": won_txt,
            # the receipt line under the card: the comeback in measured gold, before the
            # scoreboard or anybody's mood can show it.
            "evidence": (tf("{won} off your worst — that is the comeback, measured", won=won_txt)
                         if won_txt else None)}
    imm = _immediate(ctx)
    ours = ctx.get("our_open_inhibs") or []
    e = float(ctx.get("e") or 0.0)

    # ---- 1. the write-off. Three measured facts at once and no live out. Everything about
    #         this branch is built to be hard to reach: it is the one call in the whole app
    #         that cannot be taken back, so it fires on a game with no mechanism left, not
    #         on a game that is going badly.
    in_base = bool(ours) or bool(ctx.get("nexus_turret"))
    decided = (gt >= CALL_FROM and lead <= -CALL_GOLD and in_base
               and (len(ours) >= 2 or e <= CALL_E))
    if decided and not imm:
        where = (tf("{lane} inhib open {time}", lane=t(lcl.LANE_N.get(ours[0][0], "?")),
                    time=_mmss(ours[0][1])) if ours else t("a nexus turret down"))
        bits = [f"{_k(lead)}", where]
        if e <= CALL_E:
            bits.append(tf("you lose a 5v5 by {gap:.1f}k", gap=abs(e) / 1000))
        card.update(verdict="CALL IT", tone="hold", quiet=False, tag="decided",
                    line=t("CALL IT — this one is decided"),
                    sub=tf("{facts} — the LP is already spent, the minutes are not: vote to end and put them into the next game",
                           facts=" · ".join(bits)))
        return card

    # ---- 2. a live out with a clock on it. This is the card the app exists to show at the
    #         15:00 vote: a team about to end a game that has a mechanism left in it.
    if imm:
        line, sub, tag = imm
        card.update(verdict="OUT", tone="go", quiet=bool(ctx.get("tempo_urgent")),
                    line=line, sub=sub, tag=tag)
        return card

    # ---- 3. a standing out. It takes the card only at a vote moment — the seconds when
    #         somebody actually types it — and rides a quiet row every other second, because
    #         "you out-scale, keep farming" is a state, not an instruction.
    st = _standing(ctx)
    if st:
        line, sub, tag = st
        vote = bool(ctx.get("vote_now")) and not ctx.get("tempo_urgent")
        card.update(verdict="OUT", tone="plan", quiet=not vote, line=line, sub=sub, tag=tag)
        return card

    # ---- 4. behind, no named path, and not decided either. The honest answer is the one
    #         thing that is always true from behind: do not hand them the next one.
    role = ctx.get("role") or "mid"
    card.update(verdict="SURVIVE", tone="plan", tag=t("no free path"),
                quiet=not (ctx.get("vote_now") and not ctx.get("tempo_urgent")),
                line=t("SURVIVE — behind, and there is no free path yet"),
                sub=tf("{hold} · the only losing move from here is a fight you did not have to take",
                       hold=t(_HOLD.get(role, _HOLD["mid"]))))
    return card


def row_bits(card):
    """The quiet row, as ORDERED segments (the widget keeps as many as fit rather than
    clipping the last number in half): the deficit, what you have clawed back off the
    trough, and the out in three words."""
    if not card:
        return []
    bits = [card.get("clock_txt") or ""]
    tag = card.get("tag")
    if tag:
        bits.append(tf("out: {tag}", tag=tag) if card.get("verdict") == "OUT" else tag)
    if card.get("won_txt"):
        bits.append(card["won_txt"])
    return [b for b in bits if b]


class Guard:
    """One instance per widget session. Stateful for two reasons: the clawed-back number
    needs the TROUGH of the deficit (visible only over time), and the vote moments need to
    know when one of your own inhibitors fell."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._gt = 0.0
        self.trough = 0.0          # worst est-gold deficit seen this game (<= 0)
        self.calls = 0             # CALL IT windows opened (diagnostics)
        self._firing = False

    def _vote_now(self, gt, our_inhib_times):
        """True inside the seconds when a surrender vote actually happens: the 15:00 window
        opening, the 20:00 one, and the moments right after they break into your base."""
        for mark in (OUT_FROM, CALL_FROM):
            if mark <= gt < mark + VOTE_WIN:
                return True
        for t in our_inhib_times or ():
            if t <= gt < t + VOTE_WIN:
                return True
        return False

    def observe(self, dd, data, tempo=None, objs=None, while_dead=False):
        """One tick. Returns the card while you're behind after 15:00, else None. `tempo`
        and `objs` are this same tick's reads (ONE BRAIN — the widget already computed
        them): the card stands down to a quiet row rather than talk over a live objective
        verdict, and the objective clocks are not recomputed."""
        if not data:
            return None
        import lollive as ll
        import loltempo as lt
        split = ll.team_split(data)
        if not split:
            return None
        me, allies, enemies, team = split
        try:
            gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
        except (TypeError, ValueError):            # a payload mid-write: hold, don't crash
            return None
        if gt + 1.0 < self._gt:                    # clock went backwards -> a different game
            self.reset()
        self._gt = gt

        # The deficit, on the SAME fog-proof score-based gold the CLOSER measures a lead
        # with. Anything that prefers VISIBLE item gold reads a farming enemy in fog as
        # poorer than they are, which from behind is the one direction you cannot afford.
        lead = ll.team_lead(allies, enemies, gt)
        self.trough = min(self.trough, lead)
        if gt < OUT_FROM or lead > -BEHIND_MIN:
            self._firing = False
            return None
        if me.get("isDead") and not while_dead:    # the death screen owns the grey screen
            self._firing = False                   # ...unless the DEATH BRIEF is the caller:
            return None                            # that screen is where this gets decided

        act = data.get("activePlayer") or {}
        ms = (act.get("championStats") or {}).get("moveSpeed")
        e = bodies = 0.0
        try:                                       # ONE BRAIN: the tempo engine's own edge
            fe = lt.fight_edge(dd, data, 0.0, lt._travel(ms, gt), gt)
            if fe:
                e, bodies = float(fe[0]), float(fe[1])
        except Exception:
            pass

        st = lcl.structures(ll._events(data), team)
        ours = lcl.open_inhibs(st["us"], gt)
        # HOW DEEP THEY ARE INTO YOU, so it reads OUR fallen turrets — the CLOSER's mirror
        # reads "them" for the same question pointed the other way. Getting this backwards
        # tells a team whose base is already open that nothing of theirs is.
        us_turrets = (st["us"].get("turrets") or {})
        objs = objs if objs is not None else ll.objectives(data)
        baron = drake = None
        elder = False
        for o in objs or []:
            if o.get("label") == "Baron" and baron is None:
                baron = float(o.get("secs") or 0.0)
            elif o.get("label") in ("Drake", "Elder") and drake is None:
                drake, elder = float(o.get("secs") or 0.0), o.get("label") == "Elder"
        my_dr, _en_dr = ll.drake_counts(data, allies)

        # what a death costs THEM right now, at their own average level on the live clock
        lv = [int(p.get("level") or 1) for p in enemies] or [1]
        their_cost = lt.death_timer(int(round(sum(lv) / float(len(lv)))), gt)
        try:
            my_items = ll._completed_items(
                dd, [it.get("itemID") for it in (me.get("items") or []) if it.get("itemID")])[0]
        except Exception:
            my_items = None
        try:
            gap = ll.comp_scale(dd, allies) - ll.comp_scale(dd, enemies)
        except Exception:
            gap = None

        inhib_times = [rec.get("killed") for rec in (st["us"].get("inhibs") or {}).values()
                       if rec.get("killed") is not None]
        card = _verdict({
            "gt": gt, "lead": lead, "trough": self.trough, "e": e, "bodies": bodies,
            "our_open_inhibs": ours,
            "nexus_turret": int(us_turrets.get("C", 0)) >= NEXUS_TURRETS,
            "their_deepest": (max(us_turrets.values()) if us_turrets else 0),
            "baron_secs": baron, "drake_secs": drake, "elder": elder, "my_drakes": my_dr,
            "their_death_cost": their_cost, "scale_gap": gap, "my_items": my_items,
            "dead_enemies": sum(1 for p in enemies if p.get("isDead")),
            "role": lt._my_role(dd, me),
            "tempo_urgent": bool((tempo or {}).get("urgent")),
            "vote_now": self._vote_now(gt, inhib_times),
        })
        if card is None:
            self._firing = False
            return None
        if card["verdict"] == "CALL IT" and not self._firing:
            self._firing = True
            self.calls += 1
        elif card["verdict"] != "CALL IT":
            self._firing = False
        card["calls"] = self.calls
        card["bits"] = row_bits(card)
        return card


_ONE = Guard()


def read(dd, data, tempo=None, objs=None, while_dead=False):
    """One-shot read for consumers outside the widget's poll loop (the death brief). Keeps
    its own trough across ticks in whatever process calls it, and resets itself when the
    game clock goes backwards, exactly like the widget's instance."""
    return _ONE.observe(dd, data, tempo, objs, while_dead=while_dead)


# ---- fixtures for tools/selftest.py: each must land on exactly one verdict ----
def demo(kind):
    base = {"gt": 1500.0, "lead": -4200.0, "trough": -4200.0, "e": -1800.0, "bodies": 0.0,
            "our_open_inhibs": [], "nexus_turret": False, "their_deepest": 1,
            "baron_secs": None, "drake_secs": None, "elder": False, "my_drakes": 1,
            "their_death_cost": 32.0, "scale_gap": 0.0, "my_items": 2,
            "dead_enemies": 0, "role": "mid", "tempo_urgent": False, "vote_now": False}
    if kind == "baron":                   # the equalizer, live and contestable
        base.update(gt=1400.0, baron_secs=35.0, dead_enemies=2)
    elif kind == "baron_lost":            # ...same window, but the fight for it is gone
        base.update(gt=1400.0, baron_secs=35.0, e=-4000.0, their_deepest=3,
                    our_open_inhibs=[("C", 200.0)])
    elif kind == "elder":                 # elder is contestable -> the fight to have
        base.update(gt=2200.0, drake_secs=20.0, elder=True, bodies=1.0)
    elif kind == "soul":                  # soul point on YOUR side
        base.update(drake_secs=70.0, my_drakes=3, e=-500.0)
    elif kind == "ace":                   # past 28:00 their death timers alone are an out
        base.update(gt=1800.0, their_death_cost=52.0, their_deepest=3,
                    our_open_inhibs=[("C", 200.0)])
    elif kind == "scale":                 # you out-scale and the game hasn't reached you
        base.update(scale_gap=0.4, their_deepest=3, our_open_inhibs=[("C", 200.0)])
    elif kind == "structure":             # nothing of yours is open: they have to come get it
        pass
    elif kind == "survive":               # behind, nothing named, base intact-ish
        base.update(their_deepest=3, our_open_inhibs=[("C", 200.0)], gt=1300.0,
                    their_death_cost=30.0)
    elif kind == "survive_vote":          # ...and somebody is typing it right now
        base.update(their_deepest=3, our_open_inhibs=[("C", 200.0)], gt=1300.0,
                    their_death_cost=30.0, vote_now=True)
    elif kind == "call":                  # 20:00+, 8k down, in your base, 5v5 is gone
        base.update(gt=1500.0, lead=-9200.0, trough=-9200.0, e=-5200.0,
                    our_open_inhibs=[("C", 180.0)], their_deepest=3)
    elif kind == "call_nexus":            # ...same, via a nexus turret rather than an inhib
        base.update(gt=1600.0, lead=-11000.0, trough=-11000.0, e=-6000.0,
                    nexus_turret=True, their_deepest=3)
    elif kind == "call_blocked":          # ...but baron is up and contestable: still a game
        base.update(gt=1500.0, lead=-9200.0, trough=-9200.0, e=-5200.0,
                    our_open_inhibs=[("C", 180.0)], their_deepest=3,
                    baron_secs=0.0, dead_enemies=3)
    elif kind == "call_early":            # 8k down at 17:00 is not a decided game
        base.update(gt=1020.0, lead=-9200.0, trough=-9200.0, e=-5200.0,
                    our_open_inhibs=[("C", 180.0)], their_deepest=3)
    elif kind == "call_thin":             # ...nor is 5k down with an inhib open
        base.update(gt=1500.0, lead=-5000.0, trough=-5000.0, e=-5200.0,
                    our_open_inhibs=[("C", 180.0)], their_deepest=3)
    elif kind == "clawback":              # the comeback, measured, before anyone feels it
        base.update(lead=-4200.0, trough=-7900.0)
    elif kind == "ahead":                 # NEVER speaks when you're not behind
        base.update(lead=3000.0)
    elif kind == "even":                  # ...or inside the CLOSER's own bar
        base.update(lead=-1200.0)
    elif kind == "early":                 # ...or before a surrender window exists
        base.update(gt=800.0)
    elif kind == "tempo":                 # a live objective verdict outranks a standing out
        base.update(scale_gap=0.4, their_deepest=3, our_open_inhibs=[("C", 200.0)],
                    vote_now=True, tempo_urgent=True)
    return base


DEMOS = ("baron", "baron_lost", "elder", "soul", "ace", "scale", "structure", "survive",
         "survive_vote", "call", "call_nexus", "call_blocked", "call_early", "call_thin",
         "clawback", "ahead", "even", "early", "tempo")


if __name__ == "__main__":                # python lolout.py — print every branch
    for k in DEMOS:
        c = _verdict(demo(k))
        if not c:
            print(f"{k:14} (silent)")
        else:
            q = " [quiet row]" if c.get("quiet") else ""
            print(f"{k:14} {c['verdict']:8}{q} {c['line']}\n               {c['sub']}"
                  f"\n               row: {' · '.join(row_bits(c))}")
