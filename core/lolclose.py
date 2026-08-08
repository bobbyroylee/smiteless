#!/usr/bin/env python3
"""lolclose.py - THE CLOSER: the last uncovered leak, the game you were winning.

THE LEAK THIS EXISTS FOR
lolprofile.behavior_read tags a game `threw_ahead` when one of YOUR deaths lands after
25:00 while your team is 2000+ gold ahead. It is the only tag left in the ledger with no
in-game surface. The other four are covered: RE-ENTRY (lolreentry) owns the 90 seconds
after a death, BLEED (lolbleed) owns the first fourteen minutes, and the tempo engine owns
the objective windows. Nothing in this app has ever had anything to say about the state
that actually decides ranked games - AHEAD, AFTER 20:00, NOT ENDED YET.

That is the most expensive minute in League. You already paid for the lead; every game you
lose from here is LP you earned and gave back. And the two ways it happens are both
fixable with information you cannot get at a glance:

  1. YOU DON'T KNOW HOW CLOSE YOU ARE. "Should we end or take baron?" is a structural
     question and the game shows you the answer on a minimap you are not looking at.
  2. YOU FIGHT WHEN YOU DON'T NEED TO. A team that is up does not need a fight. It needs
     the nexus. One coin-flip death at 28:00 is a fifty-second hole and a free baron.

WHAT IT DOES
From 20:00, and ONLY while you are genuinely ahead, it answers one question off live data:
what is the shortest path to their nexus from here, and what could still take it away?

  - THE STRUCTURE MAP, from the event feed. Turrets fall in a fixed order (a turret is
    invulnerable until the one in front of it is gone), so COUNTING their dead turrets in
    a lane tells you exactly how deep that lane is - no fragile guessing at Riot's turret
    index names, and nothing to re-check on a patch. Three down = their inhibitor is
    exposed. `InhibKilled` gives the inhibitor and its five-minute clock.
  - THE LEAD, and what you have GIVEN BACK of it. Peak-to-now on the same fog-proof
    score-based team gold the `threw_ahead` tag itself is defined on (lollive.est_gold).
    Nothing else in the app tracks a lead's TRAJECTORY, and the trajectory is the tell:
    +5.6k that has been +7.7k is a game being thrown in slow motion.
  - CAN YOU WIN A FIGHT RIGHT NOW (ONE BRAIN: loltempo.fight_edge, death-timer aware).
  - WHAT A DEATH COSTS YOU RIGHT NOW (loltempo.death_timer at your level and clock) -
    priced against the baron timer, because that is what they buy with it.

END   - their inhibitor is open and you win the fight. Go nexus. The card.
SIEGE - the inhibitor is open but you do NOT win a 5v5. Take it with the wave, don't dive.
CLOSE - one turret from an inhibitor. That turret is the game, not the next skirmish.
HOLD  - you are ahead and would lose a fight this second. This is the throw, mid-throw.
BANK  - ahead, nothing open, nothing burning. A quiet row with the lead and the give-back.

It NEVER speaks while you are behind or even: a coach for closing out games has nothing
to say about a game you are not winning. That is the tempo engine's job and it keeps it.

House rule (docs/TAGS.md spirit): the card carries its receipt - YOUR OWN W/L split for
the habit, straight out of the behavior ledger, so it is your data talking and not folklore.

100% read-only off :2999. No input, no camera, nothing automated.

  python lolclose.py        # print every branch from the fixtures
"""
import time

from smitei18n import t, tf

CLOSE_FROM = 20 * 60.0     # game-time the closer opens (the tag itself fires from 25:00 —
                           # a warning that arrives with the mistake is not a warning)
LEAD_MIN = 2000.0          # est-gold team lead that counts as ahead: the threw_ahead bar
E_END = 400.0              # fight edge at/above which an open inhibitor means GO
BODY_RISK = -1.0           # a full body down (death-timer aware) = don't take this fight
E_RISK = -2500.0           # ...or an edge this bad even at equal bodies
GIVEBACK_MIN = 1500.0      # gold given back off the peak before the bar tightens
GIVE_BODY, GIVE_E = -0.5, -1000.0     # ...the tightened bars once it has
INHIB_RESPAWN = 300.0      # seconds an inhibitor stays down (wiki "Inhibitor")
SIEGE_STEP = 1             # turrets left in front of an inhibitor to call CLOSE
LANE_N = {"L": "top", "C": "mid", "R": "bot"}
_EV_TTL = 600.0            # re-read the behavior ledger at most this often

_EV = {"t": 0.0, "raw": None}


def _evidence():
    """YOUR measured split for the throwing-a-won-game habit ('with it: 2W-5L / without:
    9W-4L'), or None when the ledger doesn't have both sides yet. Cached — it's a disk read
    and this is called from a 1s poll loop."""
    now = time.monotonic()
    if _EV["raw"] is not None and (now - _EV["t"]) < _EV_TTL:
        return tf("your games where you died ahead after 25:00 — {evidence}",
                  evidence=_EV["raw"])
    raw = None
    try:
        import lolprofile as lp
        raw = lp.pattern_evidence("threw_ahead")
    except Exception:
        raw = None
    _EV["t"], _EV["raw"] = now, raw
    return (tf("your games where you died ahead after 25:00 — {evidence}", evidence=raw)
            if raw else None)


# ---------------------------------------------------------------- the structure map ----
# Turret names look like Turret_T1_C_05_A and inhibitors like Barracks_T2_L1. T1 is ORDER,
# T2 is CHAOS (Riot's own team ids, 100/200). We take ONLY the side and the lane letter out
# of the name — never the index — because the index encoding is the fragile part and we
# don't need it: turrets in a lane can only die front-to-back, so the COUNT is the depth.
# Mid can run past three (the two nexus turrets are also "C"), hence the clamp below.
_SIDE = {"T1": "ORDER", "T2": "CHAOS"}
LANE_TURRETS = 3           # outer + inner + inhibitor turret, per lane


def _lane_of(name, kind):
    """(side, lane) out of a structure name, or None when it isn't one we model (the
    fountain shrine turrets, or a naming shape we've never seen)."""
    parts = (name or "").split("_")
    if kind == "turret":
        if len(parts) < 4 or parts[1] not in _SIDE or parts[2] not in LANE_N:
            return None
        return _SIDE[parts[1]], parts[2]
    if len(parts) < 3 or parts[1] not in _SIDE or (parts[2][:1] not in LANE_N):
        return None
    return _SIDE[parts[1]], parts[2][:1]


def structures(events, my_team):
    """The live map state from the event feed, from THEIR side and ours:

        {"them": {"turrets": {"L": 2, "C": 3, "R": 0},
                  "inhibs":  {"C": {"killed": 1723.4, "back": None}}},
         "us":   {...}}

    Turret counts are of DISTINCT structures (an event replayed in the feed can't inflate
    them). Inhibitors keep the kill time and the respawn time, if the feed reported one."""
    out = {"them": {"turrets": {}, "inhibs": {}, "_t": set()},
           "us": {"turrets": {}, "inhibs": {}, "_t": set()}}
    mine = "ORDER" if my_team == "ORDER" else "CHAOS"
    for ev in events or []:
        n = ev.get("EventName")
        t = float(ev.get("EventTime") or 0.0)
        if n == "TurretKilled":
            name = ev.get("TurretKilled") or ""
            got = _lane_of(name, "turret")
            if not got:
                continue
            side, lane = got
            box = out["us"] if side == mine else out["them"]
            if name in box["_t"]:
                continue
            box["_t"].add(name)
            box["turrets"][lane] = box["turrets"].get(lane, 0) + 1
        elif n in ("InhibKilled", "InhibRespawned"):
            name = ev.get("InhibKilled") or ev.get("InhibRespawned") or ""
            got = _lane_of(name, "inhib")
            if not got:
                continue
            side, lane = got
            box = out["us"] if side == mine else out["them"]
            rec = box["inhibs"].setdefault(lane, {"killed": None, "back": None})
            if n == "InhibKilled":
                rec["killed"] = t if rec["killed"] is None else max(rec["killed"], t)
            else:
                rec["back"] = t if rec["back"] is None else max(rec["back"], t)
    for box in (out["them"], out["us"]):
        box.pop("_t")
    return out


def open_inhibs(box, gt):
    """[(lane, seconds_left)] for that side's inhibitors that are DOWN right now, soonest
    to come back first. An `InhibRespawned` newer than the kill closes it; failing that the
    five-minute clock does. Never reports a negative window."""
    out = []
    for lane, rec in (box.get("inhibs") or {}).items():
        k = rec.get("killed")
        if k is None:
            continue
        back = rec.get("back")
        if back is not None and back >= k:
            continue
        left = (k + INHIB_RESPAWN) - gt
        if left > 0:
            out.append((lane, left))
    out.sort(key=lambda t: t[1])
    return out


def steps_to_inhib(box):
    """{lane: turrets still standing in front of that inhibitor}. 0 means the inhibitor
    itself is the next thing you hit."""
    tur = box.get("turrets") or {}
    return {ln: max(0, LANE_TURRETS - min(LANE_TURRETS, int(tur.get(ln, 0)))) for ln in LANE_N}


def _k(v):
    return f"{v / 1000:+.1f}k"


# The productive thing to do instead, at 25 minutes. Deliberately NOT lolreentry._SAFE:
# that set is written for lane phase ("shove your wave in, take the plate") and reads as
# nonsense in a 5v5 game state. Closing out is a different sport.
_LATE = {"top": "hold the side wave, cross the river with your team or not at all",
         "mid": "clear mid from your side and group — nothing across the river is worth it",
         "jungle": "farm your own half and ward their entrances — no solo pathing",
         "adc": "stay behind your frontline — you never walk in first from ahead",
         "support": "ward their jungle entrances and the pit — no solo roams"}


def _death_line(cost, baron):
    """What a death costs you RIGHT NOW, priced against what they buy with it. Both halves
    are computed (loltempo.death_timer at your level + clock; the live baron timer), so
    this is never the generic 'don't die' — it's the number."""
    c = int(round(cost))
    if baron is not None and baron <= max(0.0, cost):
        return tf("dying here costs {seconds}s — baron is up inside that", seconds=c)
    return tf("dying here costs {seconds}s at this level", seconds=c)


def _verdict(ctx):
    """Pure: context -> the card (or None). Split out from observe() so the fixtures in
    selftest can drive every branch without a live game."""
    if float(ctx.get("gt") or 0.0) < CLOSE_FROM:
        return None
    lead = float(ctx.get("lead") or 0.0)
    if lead < LEAD_MIN:
        return None                    # not ahead: the closer has nothing to say. Ever.
    e = float(ctx.get("e") or 0.0)
    bodies = float(ctx.get("bodies") or 0.0)
    give = max(0.0, float(ctx.get("peak") or lead) - lead)
    role = ctx.get("role") or "mid"
    inhib = ctx.get("open_inhib")      # (lane, secs_left) of THEIRS, or None
    steps = ctx.get("steps") or {}
    cost = float(ctx.get("death_cost") or 0.0)
    baron = ctx.get("baron_secs")
    card = {"lead": lead, "give": give, "clock_txt": _k(lead),
            "give_txt": (tf("gave back {given:.1f}k of {peak:.1f}k",
                            given=give / 1000, peak=(lead + give) / 1000)
                         if give >= GIVEBACK_MIN else None)}

    # ---- 1. throw risk. It outranks the structural calls: walking into a lost fight ON
    #         THE WAY to the inhibitor is the exact shape of the tag. Never contradicts a
    #         positive tempo read — if fight_edge says you win it, you win it.
    tight = give >= GIVEBACK_MIN
    b_bar, e_bar = (GIVE_BODY, GIVE_E) if tight else (BODY_RISK, E_RISK)
    import loltempo as lt
    if e <= e_bar or (bodies <= b_bar and e < lt.E_TAKE):
        why = (tf("down {count:.0f} bodies", count=abs(bodies))
               if bodies <= -2.0 else
               t("down 1 body") if bodies <= -1.0 else
               t("you lose a fight right now"))
        sub = _death_line(cost, baron) + " · " + t(_LATE.get(role, _LATE["mid"]))
        if tight:
            sub = tf("you've given back {given:.1f}k already · {instruction}",
                     given=give / 1000, instruction=sub)
        card.update(verdict="HOLD", tone="hold", quiet=False,
                    line=tf("HOLD — you're {lead} and {reason}",
                            lead=_k(lead), reason=why), sub=sub)
        return card

    # ---- 2. their inhibitor is open. This is a CLOCK, and it is the highest-value fact
    #         on the map: nothing else you can do in those five minutes is worth as much.
    if inhib:
        lane, left = inhib[0], float(inhib[1])
        mm = f"{int(left) // 60}:{int(left) % 60:02d}"
        if e >= E_END or bodies >= 1.0:
            dead = ctx.get("dead_enemies") or []
            extra = (tf(" · {count} of them dead", count=len(dead))
                     if len(dead) >= 2 else "")
            card.update(verdict="END", tone="go", quiet=False,
                        line=tf("END IT — {lane} inhib open {time}{extra}",
                                lane=t(LANE_N[lane]), time=mm, extra=extra),
                        sub=t("nexus turrets as five — baron is a detour, the inhib clock isn't"))
            return card
        card.update(verdict="SIEGE", tone="plan", quiet=False,
                    line=tf("SIEGE — {lane} inhib open {time}, but you lose a 5v5",
                            lane=t(LANE_N[lane]), time=mm),
                    sub=t("push the wave in and take it from range — do not dive the nexus turrets"))
        return card

    # ---- 3. one turret from an inhibitor. That turret is the game; it is not a skirmish,
    #         and at this point in a won game everything else on the map is a distraction.
    ready = sorted((v, k) for k, v in steps.items())
    if ready and ready[0][0] <= SIEGE_STEP and e >= 0:
        n, lane = ready[0]
        # n is the number of turrets still STANDING in front of that inhibitor: at 0 the
        # inhibitor itself is the next thing you hit, at 1 the inhib turret still is.
        head = (tf("CLOSE — {lane} inhibitor is next, nothing in front of it",
                   lane=t(LANE_N[lane])) if n == 0 else
                tf("CLOSE — {lane} is one turret from their inhib", lane=t(LANE_N[lane])))
        if ctx.get("tempo_urgent"):
            card.update(verdict="CLOSE", tone="plan", quiet=True, line=head,
                        sub=t("take it as five off the next wave, then reset — don't chase"))
            return card
        card.update(verdict="CLOSE", tone="plan", quiet=False, line=head,
                    sub=tf("{lead} up: take it as five off the next wave, then reset — don't chase",
                           lead=_k(lead)))
        return card

    # ---- 4. ahead, nothing open, nothing burning: a quiet row, never a card. A coach that
    #         talks when there is nothing to say is a coach you turn off.
    card.update(verdict="BANK", tone="plan", quiet=True,
                line=tf("BANK — {lead} up, nothing free here", lead=_k(lead)),
                sub=t("take towers and vision, make them come to you"))
    return card


class Guard:
    """One instance per widget session. Stateful for exactly one reason: the give-back
    number needs the PEAK of the lead, and a peak can only be seen over time."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._gt = 0.0
        self.peak = 0.0            # best est-gold team lead seen this game
        self.calls = 0             # HOLD windows opened this game (diagnostics / voice rate)
        self._firing = False

    def observe(self, dd, data, tempo=None):
        """One tick. Returns the card while you're ahead after 20:00, else None. `tempo` is
        this same tick's tempo read (ONE BRAIN — the widget already computed it): a CLOSE
        stands down to a quiet row rather than talk over a live objective verdict."""
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

        # The lead, on the SAME fog-proof score-based gold the threw_ahead tag is defined
        # on. Deliberately not player_power: that one prefers VISIBLE item gold when it's
        # higher, which your own team always has and a farming enemy in fog does not — an
        # asymmetry worth nothing here and worth a false "you're ahead" every game.
        lead = ll.team_lead(allies, enemies, gt)
        self.peak = max(self.peak, lead)
        if gt < CLOSE_FROM or lead < LEAD_MIN:
            self._firing = False
            return None
        if me.get("isDead"):                       # the death screen owns the grey screen
            self._firing = False
            return None

        act = data.get("activePlayer") or {}
        ms = (act.get("championStats") or {}).get("moveSpeed")
        e = bodies = 0.0
        try:                                       # ONE BRAIN: the same edge the tempo card uses
            fe = lt.fight_edge(dd, data, 0.0, lt._travel(ms, gt), gt)
            if fe:
                e, bodies = float(fe[0]), float(fe[1])
        except Exception:
            pass
        st = structures(ll._events(data), team)
        baron = None
        try:
            b = next((o for o in ll.objectives(data) if o.get("label") == "Baron"), None)
            baron = float(b["secs"]) if b else None
        except Exception:
            baron = None
        dead_enemies = [p for p in enemies if p.get("isDead")]
        oi = open_inhibs(st["them"], gt)
        card = _verdict({
            "gt": gt, "lead": lead, "peak": self.peak, "e": e, "bodies": bodies,
            "open_inhib": oi[0] if oi else None,
            "steps": steps_to_inhib(st["them"]),
            "death_cost": lt.death_timer(me.get("level", 1), gt),
            "baron_secs": baron,
            "dead_enemies": dead_enemies,
            "role": lt._my_role(dd, me),
            "tempo_urgent": bool((tempo or {}).get("urgent")),
        })
        if card is None:
            self._firing = False
            return None
        if card["verdict"] == "HOLD" and not self._firing:
            self._firing = True
            self.calls += 1
        elif card["verdict"] != "HOLD":
            self._firing = False
        card["calls"] = self.calls
        card["our_inhib"] = bool(open_inhibs(st["us"], gt))
        card["evidence"] = _evidence()
        return card


# ---- fixtures for tools/selftest.py: each must land on exactly one verdict ----
def demo(kind):
    base = {"gt": 1700.0, "lead": 4200.0, "peak": 4200.0, "e": 2600.0, "bodies": 0.0,
            "open_inhib": None, "steps": {"L": 3, "C": 2, "R": 3},
            "death_cost": 51.0, "baron_secs": 120.0, "dead_enemies": [], "role": "mid",
            "tempo_urgent": False}
    if kind == "end":                     # inhib open, you win the fight -> go nexus
        base.update(open_inhib=("C", 214.0), steps={"L": 3, "C": 0, "R": 3},
                    dead_enemies=[1, 2])
    elif kind == "siege":                 # inhib open, but a 5v5 loses -> take it safely
        base.update(open_inhib=("C", 112.0), steps={"L": 3, "C": 0, "R": 3},
                    e=200.0, bodies=0.0)
    elif kind == "close":                 # one turret from their inhib
        base.update(steps={"L": 3, "C": 1, "R": 3})
    elif kind == "closeinhib":            # ...and now nothing in front of it at all
        base.update(steps={"L": 3, "C": 0, "R": 3})
    elif kind == "quietclose":            # ...but the tempo engine has a live verdict
        base.update(steps={"L": 3, "C": 1, "R": 3}, tempo_urgent=True)
    elif kind == "hold":                  # ahead and a body down: the throw, mid-throw
        base.update(bodies=-1.0, e=-9000.0, baron_secs=0.0)
    elif kind == "giveback":              # even-ish fight, but 2k of the lead is gone
        base.update(peak=6300.0, bodies=-0.5, e=-1400.0)
    elif kind == "bank":                  # ahead, nothing open, nothing burning
        pass
    elif kind == "behind":                # NEVER speaks when you're not ahead
        base.update(lead=-3000.0)
    elif kind == "early":                 # ...or before the window opens
        base.update(gt=900.0)
    elif kind == "thin":                  # a lead under the tag's own bar isn't a lead
        base.update(lead=1200.0)
    elif kind == "winning_fight":         # a body down but fight_edge says you WIN it:
        base.update(bodies=-1.0, e=3400.0)     # never contradict a positive tempo read
    return base


if __name__ == "__main__":                # python lolclose.py — print every branch
    for k in ("end", "siege", "close", "closeinhib", "quietclose", "hold", "giveback",
              "bank", "behind", "early", "thin", "winning_fight"):
        c = _verdict(demo(k))
        if not c:
            print(f"{k:14} (silent)")
        else:
            q = " [quiet row]" if c.get("quiet") else ""
            print(f"{k:14} {c['verdict']:6}{q} {c['line']}\n               {c['sub']}")
