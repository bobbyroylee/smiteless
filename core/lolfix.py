#!/usr/bin/env python3
"""lolfix.py - THE ONE FIX: your leaks, ranked by what they actually cost you in LP.

The behavior ledger (lolprofile.behavior_read) already writes one row per ranked game:
which habits were *evaluable* that game, which ones *fired*, and whether you won. Five
habits, sixty games, and until now the only thing anyone did with it was print up to three
"PATTERN - ..." bullets about the game you just played.

That is the wrong question. "What went wrong today" is a review. **"Which one of these is
costing me the most ladder, and what would fixing it be worth"** is a plan - and it is
answerable, because the ledger holds both sides of every split: the games where the habit
fired and the games where it didn't.

So this module prices each leak in the only currency that matters:

    RE-ENTRY   ~31 LP / 10 games    with it: 2W-8L  ·  without: 9W-5L   (fires 5 of 10)

and then names exactly ONE of them, because a coach that hands you five things to fix has
handed you nothing. One rep, one habit, until the board says it's closed.

House rules (docs/TAGS.md's spirit - a claim carries its evidence, and never outruns it):

  - **Nothing is priced until the split beats a test.** Same one-sided two-proportion
    z-test the QUEUE CALL uses, read from lolqueue so the two can never disagree about what
    "proven" means. Below the bar the row still renders - as a *lean*, with its numbers -
    but it carries no LP figure and cannot be the headline price.
  - **The price is the conservative end of the split, not the flattering one.** Before a
    gap becomes an LP figure, both sides are pulled a few pseudo-games toward your own
    baseline win rate - so a 3-vs-5 split can't shout, a 40-game one is barely touched, and
    a price that rounds to nothing is reported as no price at all.
  - **The LP is YOUR LP.** Win/loss LP is read from your own rank history; only if that
    can't be measured does it fall back to a stated assumption, and then it says so.
  - **A leak with no proven split can still be picked - on frequency alone**, because "this
    fired in 7 of your last 9 games" is a *count*, not an inference, and it needs no test.
    The wording changes with the claim: priced leaks quote LP, frequent ones quote the count.
  - **No sample, no board.** Under MIN_GAMES the whole surface says how many games it still
    needs and gets out of the way.

Correlation, not proof of causation, and the board says so out loud: these are your own
games, split by a habit, and the direction is yours to act on.

CLI:  python core/lolfix.py            # your real board
      python core/lolfix.py demo       # every render state, from synthetic ledgers
      python core/lolfix.py test       # the guard suite (also wired into selftest)
"""
import json
import os
import sys

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    if os.path.join(_R, _d) not in sys.path:
        sys.path.insert(0, os.path.join(_R, _d))

import lolqueue as lq                  # ONE BRAIN for "is this split proven?" (lq._z_worse)

LEDGER = os.path.expanduser("~/.claude/cache/riot/behavior_ledger.json")
LP_HISTORY = os.path.expanduser("~/.claude/cache/lol_lp_history.json")

# ---- the catalogue ----------------------------------------------------------------
# ONE BRAIN for leak identity: lolprofile derives its _BEHAVIOR_TAGS labels from here, so a
# tag can never be called one thing on the review page and another on the board.
#   label  - what the habit is (the review page's wording)
#   fix    - the IMPERATIVE, in the second person: the thing you commit to for one game
#   guard  - the live in-game surface that already answers it, so the fix has a helper
#   short  - column label, for tight rows
LEAKS = {
    "weak_first_ten": {
        "short": "FIRST TEN",
        "label": "weak first-ten economy",
        "fix": "hit 55 CS by 10:00 — take the wave over the roam",
        "guard": "THE GOLD CLOCK",
    },
    "early_bleeding": {
        "short": "BLEEDING",
        "label": "early bleeding (3+ deaths pre-14)",
        "fix": "two deaths before 14:00 is the cap — back instead of the third",
        "guard": "BLEED",
    },
    "death_cluster": {
        "short": "RE-ENTRY",
        "label": "chained deaths (2+ inside 90s)",
        "fix": "after you respawn, 90 seconds of farm before you look for a fight",
        "guard": "RE-ENTRY",
    },
    "threw_ahead": {
        "short": "CLOSING",
        "label": "coin-flip death while ahead (post-25)",
        "fix": "2k up after 25:00 — take no fight you didn't start with a number advantage",
        "guard": "THE CLOSER",
    },
    "low_vision": {
        "short": "VISION",
        "label": "no vision setup",
        "fix": "a control ward in the bag at all times, and the pit lit before it spawns",
        "guard": "THE WARD CLOCK",
    },
}
ORDER = ["weak_first_ten", "early_bleeding", "death_cluster", "threw_ahead", "low_vision"]

# ---- bars -------------------------------------------------------------------------
MIN_GAMES = 10        # ledger games (with a result) before the board renders anything at all
MIN_EV = 8            # a habit must have been EVALUABLE this often before it can be ranked
MIN_SIDE = 3          # ... and hold this many games on each side before a split may speak
Z_PROVEN = lq.Z_PROVEN   # one-sided ~90% — the same bar the QUEUE CALL promotes a lean at
LP_ASSUMED = 20       # LP per win/loss when your own rank history can't measure it
LP_CLAMP = (8, 45)    # sane per-game LP band; anything outside is an MMR reset, not a game
RECENT_N = 6          # evaluable games drawn in the per-leak form strip
TREND_N = 5           # ... and compared against everything older, for improving/slipping
PRIOR_N = 4           # pseudo-games pulling each side of a split toward your OWN base rate
                      # before it is quoted in LP. Same idea as lolprofile._champ_rating's
                      # perf prior: at 3-vs-5 a 100%/0% split is a coin landing heads, not a
                      # 200-LP habit, and quoting it as one is a lie with numbers. Converges
                      # to the raw split as the sample grows, which is the whole point.


# ---- your LP, from your own rank history -------------------------------------------

def lp_rates(hist=None):
    """(lp_win, lp_loss, measured) — the LP a win and a loss are actually worth to YOU.

    lolprofile snapshots {rv, w, l} every time your profile builds; a snapshot pair whose
    win count went up by exactly one is a won game, and the rank-value delta between them
    IS the LP you gained. Medians, so one promotion series or an MMR correction can't move
    the number. Falls back to LP_ASSUMED (flagged measured=False) with no history."""
    if hist is None:
        try:
            hist = json.load(open(LP_HISTORY, encoding="utf-8"))
        except Exception:
            hist = []
    if not isinstance(hist, list):
        hist = []
    wins, losses = [], []
    for a, b in zip(hist, hist[1:]):
        try:
            dw = int(b.get("w", 0)) - int(a.get("w", 0))
            dl = int(b.get("l", 0)) - int(a.get("l", 0))
            drv = int(b.get("rv", 0)) - int(a.get("rv", 0))
        except Exception:
            continue
        if dw == 1 and dl == 0 and LP_CLAMP[0] <= drv <= LP_CLAMP[1]:
            wins.append(drv)
        elif dl == 1 and dw == 0 and LP_CLAMP[0] <= -drv <= LP_CLAMP[1]:
            losses.append(-drv)

    def med(xs):
        return sorted(xs)[len(xs) // 2] if xs else None
    w, l = med(wins), med(losses)
    if w is None and l is None:
        return LP_ASSUMED, LP_ASSUMED, False
    return (w or l), (l or w), True


# ---- the board ---------------------------------------------------------------------

def _split(rows, tag):
    """Both sides of one habit: the games it fired in, and the games it was evaluable in
    and DIDN'T. Only games that carry a result can be in either — an unfinished row is not
    evidence, it's a hole."""
    ev = [g for g in rows if tag in (g.get("ev") or []) and g.get("win") is not None]
    hit = [g for g in ev if tag in (g.get("hits") or [])]
    miss = [g for g in ev if tag not in (g.get("hits") or [])]
    return ev, hit, miss


def _wr(gs):
    return (sum(1 for g in gs if g.get("win")) / len(gs)) if gs else 0.0


def _trend(ev_rows, tag):
    """'improving' / 'slipping' / None, comparing your last TREND_N evaluable games against
    everything before them. Needs both halves to have a real sample or it says nothing —
    the whole point of the board is that you can watch a leak close, and a trend read off
    two games would make that a lie."""
    if len(ev_rows) < TREND_N + 3:
        return None
    recent, older = ev_rows[-TREND_N:], ev_rows[:-TREND_N]

    def rate(gs):
        return sum(1 for g in gs if tag in (g.get("hits") or [])) / len(gs)
    r, o = rate(recent), rate(older)
    if o - r >= 0.30:
        return "improving"
    if r - o >= 0.30:
        return "slipping"
    return None


def _shrunk(w, n, base):
    """A win rate pulled PRIOR_N pseudo-games toward your own baseline. The z-test still
    runs on the raw counts — significance is a question about the real sample — but the LP
    figure is quoted off this, so a thin split can't turn into a headline number."""
    return (w + PRIOR_N * base) / (n + PRIOR_N) if (n + PRIOR_N) else base


def _row(rows, tag, n_total, lp_swing, base=0.5):
    """One leak, fully priced. state is the strength of the claim the row is allowed to make:
      clean  — evaluable often enough and it never fired. Not a leak of yours.
      priced — the split beat the z-test: quotes LP, and can be the headline.
      lean   — a real gap that hasn't cleared the bar: quotes the split, no LP.
      rate   — one side of the split is too thin to compare, but the COUNT is a fact.
      thin   — not evaluable often enough yet; says how many more games it needs."""
    meta = LEAKS[tag]
    ev, hit, miss = _split(rows, tag)
    out = {"tag": tag, "short": meta["short"], "label": meta["label"], "fix": meta["fix"],
           "guard": meta["guard"], "n_ev": len(ev), "n_hit": len(hit),
           "rate": (len(hit) / len(ev)) if ev else 0.0,
           "lp10": 0.0, "gap": 0.0, "z": 0.0, "evidence": "", "state": "thin",
           "need": max(0, MIN_EV - len(ev)),
           "recent": [tag in (g.get("hits") or []) for g in ev[-RECENT_N:]][::-1],
           "trend": _trend(ev, tag)}
    if len(ev) < MIN_EV:
        return out
    if not hit:
        out["state"] = "clean"
        return out
    w_hit, w_miss = sum(1 for g in hit if g.get("win")), sum(1 for g in miss if g.get("win"))
    if len(hit) < MIN_SIDE or len(miss) < MIN_SIDE:
        # Not comparable — most often because it fires in nearly EVERY game, which is itself
        # the most actionable thing the board can tell you. The count carries the row, and
        # the evidence line says which side is missing instead of printing an empty split.
        out["state"] = "rate"
        out["evidence"] = (f"with it: {w_hit}W-{len(hit) - w_hit}L  ·  "
                           "no games without it to compare"
                           if len(miss) < MIN_SIDE else
                           f"only {len(hit)} game{'s' if len(hit) != 1 else ''} with it — "
                           "too few to compare")
        return out
    out["evidence"] = (f"with it: {w_hit}W-{len(hit) - w_hit}L  ·  "
                       f"without: {w_miss}W-{len(miss) - w_miss}L")
    gap = _wr(miss) - _wr(hit)
    out["gap"] = gap
    out["z"] = lq._z_worse(w_hit, len(hit), w_miss, len(miss))
    if out["z"] >= Z_PROVEN and gap > 0:
        # The gap is quoted SHRUNK, never raw: each side is pulled PRIOR_N pseudo-games
        # toward your own baseline first, so a 3-vs-5 split can't become a headline number
        # and a 40-game one is barely touched. The significance test above still ran on the
        # real counts — this haircut is about how loudly a proven split may speak, not about
        # whether it is one.
        gap_s = max(0.0, _shrunk(w_miss, len(miss), base) - _shrunk(w_hit, len(hit), base))
        out["lp10"] = round(10.0 * (len(hit) / n_total) * gap_s * lp_swing)
        # A price that rounds to nothing IS nothing. Say "lean" rather than draw a -0 LP row.
        out["state"] = "priced" if out["lp10"] >= 1 else "lean"
        if out["state"] == "lean":
            out["lp10"] = 0
    else:
        out["state"] = "lean"
    return out


def board(rows=None, lp=None):
    """The whole board. {rows, pick, n, ready, need, lp_win, lp_loss, lp_measured}.

    `pick` is THE ONE FIX — the priced leak with the biggest LP cost, or, when nothing has
    a proven split yet, the one that simply fires most often (a count needs no test). None
    while the ledger is still filling."""
    rows = _ledger() if rows is None else list(rows)
    played = [g for g in rows if g.get("win") is not None]
    played.sort(key=lambda g: g.get("ts") or 0)
    n = len(played)
    lp_win, lp_loss, measured = lp if lp else lp_rates()
    out = {"rows": [], "pick": None, "n": n, "ready": n >= MIN_GAMES,
           "need": max(0, MIN_GAMES - n), "lp_win": lp_win, "lp_loss": lp_loss,
           "lp_measured": measured}
    if not out["ready"]:
        return out
    swing = lp_win + lp_loss
    base = sum(1 for g in played if g.get("win")) / n     # your own rate, the prior each split shrinks toward
    rs = [_row(played, t, n, swing, base) for t in ORDER]
    # Rank: priced leaks by LP first, then anything that actually fires by how often, then
    # the rest. A clean habit always sorts last — it is the good news, not the headline.
    rank = {"priced": 0, "rate": 1, "lean": 1, "thin": 2, "clean": 3}
    rs.sort(key=lambda r: (rank[r["state"]], -r["lp10"], -r["rate"], -r["n_hit"]))
    out["rows"] = rs
    priced = [r for r in rs if r["state"] == "priced"]
    if priced:
        out["pick"] = max(priced, key=lambda r: r["lp10"])
    else:
        loud = [r for r in rs if r["state"] in ("rate", "lean") and r["n_hit"] >= 2]
        if loud:
            out["pick"] = max(loud, key=lambda r: (r["rate"], r["n_hit"]))
    return out


def _ledger():
    try:
        return json.load(open(LEDGER, encoding="utf-8")).get("games") or []
    except Exception:
        return []


# ---- the sentences the surfaces render ---------------------------------------------

def headline(b):
    """The one line at the top of the board — the claim, sized to what it can prove."""
    if not b.get("ready"):
        return f"reading your games — {b['need']} more and the board opens"
    p = b.get("pick")
    if not p:
        rs = b.get("rows") or []
        if rs and all(r["state"] == "clean" for r in rs):
            return f"your ledger is clean over {b['n']} games — none of the five fired"
        return "nothing in your last games is repeating often enough to be a leak"
    if p["state"] == "priced":
        return f"{p['label']} is costing you about {p['lp10']} LP every 10 games"
    why = ("no games without it to compare against" if p["state"] == "rate"
           else "the split isn't proven yet")
    return f"{p['label']} fired in {p['n_hit']} of your last {p['n_ev']} — {why}"


def receipt(b):
    """The provenance line. Says out loud where the LP number came from, and that the board
    is a correlation from your own games — never dressed up as a causal proof."""
    if not b.get("ready"):
        return f"{b['n']} of {MIN_GAMES} graded games logged"
    lp = (f"your own LP: +{b['lp_win']} / -{b['lp_loss']}" if b["lp_measured"]
          else f"LP assumed at {LP_ASSUMED} (no rank history yet)")
    return f"from your last {b['n']} graded games  ·  {lp}  ·  your split, not a study"


def commitment(b):
    """The lobby line — one imperative for the game you're about to queue, or ''."""
    p = (b or {}).get("pick")
    if not p:
        return ""
    return p["fix"]


def lobby_card(b, verdict="GO"):
    """The QUEUE CALL's THIS GAME strip: {line, sub} or None.

    The profile board is a review; this is the same finding delivered at the only moment
    you can still act on it — cursor over Find Match, one imperative, for one game. It
    stays out of the way when the call is telling you NOT to play: handing somebody a
    thing to work on in the same breath as "log off with the LP" is how a stop rule gets
    ignored."""
    p = (b or {}).get("pick")
    if not p or verdict not in ("GO", "LAST ONE"):
        return None
    if p["state"] == "priced":
        sub = f"{p['label']} — about {p['lp10']} LP every 10 games · {p['guard']} is watching it"
    else:
        sub = (f"{p['label']} — {p['n_hit']} of your last {p['n_ev']} · "
               f"{p['guard']} is watching it")
    return {"line": p["fix"], "sub": sub}


def row_note(r):
    """The right-hand number on a board row, sized to the claim the row may make."""
    if r["state"] == "priced":
        return f"-{r['lp10']} LP / 10"   # ASCII hyphen: this string is drawn through
        #                                    a text-blind PIL font, where U+2212 is tofu
    if r["state"] == "clean":
        return "clean"
    if r["state"] == "thin":
        return f"{r['need']} more"
    return f"{r['n_hit']} of {r['n_ev']}"


# ---- demo ledgers (every render state stays inspectable without waiting weeks) --------

def demo(kind="priced"):
    """A synthetic ledger that provably lands on a given board state. Splits are written
    out as explicit W/L runs rather than modular arithmetic, so each fixture means exactly
    what it says and a tweak to one state can't silently reshape another."""
    gs, ts = [], 1_700_000_000
    every = list(LEAKS)

    def g(hits, win, ev=None):
        gs.append({"mid": f"D{len(gs)}", "ts": (ts + len(gs) * 3600) * 1000,
                   "hits": sorted(hits), "ev": sorted(ev if ev is not None else every),
                   "win": win})

    def run(tag, wins, losses, extra=()):
        for _ in range(wins):
            g([tag] + list(extra) if tag else list(extra), True)
        for _ in range(losses):
            g([tag] + list(extra) if tag else list(extra), False)

    if kind == "thin":                       # 6 games: under MIN_GAMES, no board at all
        run("death_cluster", 2, 1)
        run(None, 2, 1)
        return _shuffle(gs)
    if kind == "clean":                      # 16 games, not one of the five ever fired
        run(None, 9, 7)
        return _shuffle(gs)
    if kind == "rate":                       # fires in EVERY game: nothing to compare against
        run("low_vision", 9, 5)
        return _shuffle(gs)
    if kind == "lean":                       # 43% vs 57% over 7+7: real gap, z well under the bar
        run("death_cluster", 3, 4)
        run(None, 4, 3)
        return _shuffle(gs)
    # 'priced': a believable proven leak (chained deaths, 30% over 10 vs 65% over 14 — the
    # kind of split a real ledger produces), plus a milder unproven one underneath it.
    run("death_cluster", 3, 7)
    run("weak_first_ten", 4, 3)
    run(None, 5, 2)
    return _shuffle(gs)


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def _shuffle(gs):
    """Deterministically interleave a fixture so the games aren't in W-then-L blocks. The
    counts (and therefore every split) are untouched; only the ORDER changes, which is what
    the form strip and the trend read off — a fixture whose leak sits entirely in the past
    would make every demo row say 'improving'."""
    n = len(gs)
    stride = next((s for s in range(3, max(4, n)) if _gcd(s, n) == 1), 1) if n else 1
    out = [gs[(i * stride) % n] for i in range(n)] if n else []
    for i, g in enumerate(out):                  # re-stamp so ts still ascends with position
        g = dict(g)
        g["ts"] = (1_700_000_000 + i * 3600) * 1000
        out[i] = g
    return out


def render(b):
    """The board as text — what the CLI and the guard suite both read."""
    L = [f"  {headline(b)}", f"  {receipt(b)}", ""]
    for r in b.get("rows", []):
        mark = {"priced": "!!", "lean": " ~", "rate": " *", "thin": " ?", "clean": " ."}[r["state"]]
        strip = "".join("X" if h else "-" for h in r["recent"]) or "-"
        L.append(f"  {mark} {r['short']:<10} {row_note(r):>12}   {strip:<8} "
                 f"{r['evidence']}" + (f"   ({r['trend']})" if r["trend"] else ""))
    p = b.get("pick")
    if p:
        L += ["", f"  THE ONE FIX -> {p['fix']}", f"  in game, {p['guard']} is watching it."]
    return "\n".join(L)


# ---- guard suite --------------------------------------------------------------------

def selftest():
    """Every invariant the board is allowed to be trusted for. Raises on the first break."""
    def ck(cond, msg):
        if not cond:
            raise AssertionError(msg)

    # 1. No sample, no board — and it says how far off it is.
    b = board(demo("thin"), lp=(20, 20, True))
    ck(not b["ready"] and b["pick"] is None, "thin ledger must not produce a pick")
    ck(b["need"] == MIN_GAMES - 6, f"need should count the shortfall, got {b['need']}")
    ck("more" in headline(b) and commitment(b) == "", "thin board must ask for games only")

    # 2. A habit that never fires is 'clean' and can never be the pick.
    b = board(demo("clean"), lp=(20, 20, True))
    ck(all(r["state"] == "clean" for r in b["rows"]), "no leak fired: every row must be clean")
    ck(b["pick"] is None, "a clean board must have no ONE FIX")
    ck(b["rows"][-1]["state"] == "clean", "clean rows sort last")

    # 3. The priced board: a proven split, priced conservatively, and picked.
    b = board(demo("priced"), lp=(20, 20, True))
    p = b["pick"]
    ck(p and p["tag"] == "death_cluster", f"expected chained deaths as the pick, got {p}")
    ck(p["state"] == "priced" and p["lp10"] > 0, "the pick must carry a positive LP price")
    ck(b["rows"][0]["tag"] == "death_cluster", "the priced leak must head the board")
    ck(p["z"] >= Z_PROVEN, "a priced row must have beaten the z bar")
    # ... and the price is strictly BELOW the flattering arithmetic on the raw gap.
    raw = 10.0 * (p["n_hit"] / b["n"]) * p["gap"] * 40
    ck(p["lp10"] < raw, f"price {p['lp10']} must be under the raw-gap figure {raw:.1f}")
    ck("costing you" in headline(b) and str(p["lp10"]) in headline(b),
       "the headline must quote the priced LP")
    ck(commitment(b) == LEAKS["death_cluster"]["fix"], "the lobby line is the pick's fix")

    # 4. An unproven gap renders as a lean: numbers, but never an LP price.
    b = board(demo("lean"), lp=(20, 20, True))
    dc = next(r for r in b["rows"] if r["tag"] == "death_cluster")
    ck(dc["state"] == "lean", f"expected a lean, got {dc['state']} (z={dc['z']:.2f})")
    ck(dc["lp10"] == 0 and dc["z"] < Z_PROVEN, "a lean must never carry LP")
    ck("LP" not in headline(b), "an unpriced board must not talk in LP")

    # 5. One-sided sample: the COUNT is still a fact, so it may be picked — on frequency.
    b = board(demo("rate"), lp=(20, 20, True))
    lv = next(r for r in b["rows"] if r["tag"] == "low_vision")
    ck(lv["state"] == "rate" and lv["lp10"] == 0, "a one-sided split may not be priced")
    ck(b["pick"]["tag"] == "low_vision", "the loudest unproven leak is the fallback pick")
    ck("fired in" in headline(b), "a frequency pick must state the count, not a price")

    # 6. Rows with no result are holes, not evidence — they may not enter either side.
    rows = demo("priced")
    poisoned = rows + [{"mid": "X", "ts": 0, "hits": ["death_cluster"], "ev": list(LEAKS),
                        "win": None} for _ in range(30)]
    b2 = board(poisoned, lp=(20, 20, True))
    b1 = board(rows, lp=(20, 20, True))
    ck(b2["n"] == b1["n"], "unfinished games must not count toward the sample")
    ck(b2["pick"]["lp10"] == b1["pick"]["lp10"], "unfinished games must not move the price")

    # 7. The ledger may be garbage. The board may not crash on it.
    for junk in ([], [{}], [{"win": True}], [{"hits": None, "ev": None, "win": False}],
                 [{"hits": ["nope"], "ev": ["nope"], "win": True}] * 20):
        board(junk, lp=(20, 20, True))

    # 8. LP is measured from your own history, and refuses nonsense.
    hist = [{"rv": 1000, "w": 10, "l": 10}, {"rv": 1022, "w": 11, "l": 10},
            {"rv": 1005, "w": 11, "l": 11}, {"rv": 1027, "w": 12, "l": 11},
            {"rv": 1010, "w": 12, "l": 12}]
    w, l, m = lp_rates(hist)
    ck((w, l, m) == (22, 17, True), f"LP should read 22/17 off the history, got {w}/{l}/{m}")
    w, l, m = lp_rates([{"rv": 0, "w": 0, "l": 0}, {"rv": 900, "w": 1, "l": 0}])
    ck(not m and w == LP_ASSUMED, "an MMR-reset jump is not a game — fall back and say so")
    ck(lp_rates([])[2] is False, "no history -> assumed, flagged")
    ck("assumed" in receipt(board(demo("priced"), lp=lp_rates([]))),
       "an assumed LP figure must be declared in the receipt")

    # 9. The price scales with the LP a game is actually worth to you.
    lo = board(demo("priced"), lp=(10, 10, True))["pick"]["lp10"]
    hi = board(demo("priced"), lp=(30, 30, True))["pick"]["lp10"]
    ck(lo < hi, "a bigger LP swing must price the same leak higher")

    # 10. The trend read needs both halves, and moves the right way.
    ev = [{"mid": str(i), "ts": i, "hits": ["death_cluster"], "ev": ["death_cluster"],
           "win": True} for i in range(9)]
    fixed = ev + [{"mid": "n%d" % i, "ts": 100 + i, "hits": [], "ev": ["death_cluster"],
                   "win": True} for i in range(TREND_N)]
    ck(_trend(fixed, "death_cluster") == "improving", "a closed leak must read as improving")
    ck(_trend(ev[:4], "death_cluster") is None, "no trend without both halves")

    # 11. The lobby strip appears only when you're being told to play.
    b = board(demo("priced"), lp=(20, 20, True))
    ck(lobby_card(b, "GO")["line"] == b["pick"]["fix"], "GO must carry the fix into the lobby")
    ck("LP every 10 games" in lobby_card(b, "LAST ONE")["sub"], "a priced fix quotes its LP")
    for v in ("STOP", "WAIT"):
        ck(lobby_card(b, v) is None, f"{v} must never also hand you homework")
    ck(lobby_card(board(demo("thin")), "GO") is None, "no pick, no lobby strip")
    ck("of your last" in lobby_card(board(demo("rate"), lp=(20, 20, True)), "GO")["sub"],
       "an unpriced fix must quote its count, never an LP figure")
    ck("LP" not in lobby_card(board(demo("rate"), lp=(20, 20, True)), "GO")["sub"],
       "an unpriced fix must not talk in LP")

    # 12. A PROVEN leak always outranks a merely frequent one for the headline — otherwise
    #     a habit that fires every game but costs nothing would bury the one losing you LP.
    rows = [{**g, "ev": [t for t in g["ev"] if t != "low_vision"]} for g in demo("priced")]
    rows += [{"mid": f"V{i}", "ts": 1, "hits": ["low_vision"], "ev": ["low_vision"],
              "win": i % 2 == 0} for i in range(20)]
    b = board(rows, lp=(20, 20, True))
    lv = next(r for r in b["rows"] if r["tag"] == "low_vision")
    ck(lv["state"] == "rate" and lv["rate"] == 1.0, "the ever-present habit should read 'rate'")
    ck(b["pick"]["tag"] == "death_cluster",
       f"a priced leak must outrank a 100%-frequency one, got {b['pick']['tag']}")

    # 13. FUZZ: 3000 random ledgers. Whatever the data, the board may not crash, may not
    #     price a claim it hasn't proven, and may not name a fix that isn't on the board.
    import random
    rnd = random.Random(20260730)
    tags = list(LEAKS)
    for _ in range(3000):
        rows = []
        for i in range(rnd.randrange(0, 40)):
            ev = [t for t in tags if rnd.random() < 0.7]
            rows.append({"mid": f"F{i}", "ts": i,
                         "hits": [t for t in ev if rnd.random() < rnd.random()],
                         "ev": ev,
                         "win": rnd.choice([True, False, None])})
        bb = board(rows, lp=(rnd.randrange(8, 45), rnd.randrange(8, 45), True))
        for r in bb["rows"]:
            ck(r["lp10"] >= 0, "an LP price may never be negative")
            ck(r["state"] != "priced" or r["lp10"] >= 1,
               "a priced row must carry a price — a -0 LP row is a broken claim")
            ck((r["lp10"] > 0) <= (r["state"] == "priced"),
               f"{r['tag']} priced at {r['lp10']} in state {r['state']}")
            ck(r["state"] != "priced" or r["z"] >= Z_PROVEN, "priced without clearing the bar")
            ck(r["state"] != "clean" or r["n_hit"] == 0, "a 'clean' row that actually fired")
            ck(0.0 <= r["rate"] <= 1.0 and len(r["recent"]) <= RECENT_N, "row bounds broken")
        if bb["pick"]:
            ck(bb["pick"] in bb["rows"], "the pick must be a row on the board")
            ck(bb["pick"]["state"] in ("priced", "rate", "lean"), "unprovable state picked")
            ck(bb["ready"] and bb["pick"]["n_hit"] >= 2, "a pick needs a real count behind it")
            # the headline and the lobby line always agree about WHICH leak was picked
            ck(bb["pick"]["label"] in headline(bb), "headline names a different leak")
            ck(lobby_card(bb, "GO")["line"] == bb["pick"]["fix"], "lobby line disagrees")
        else:
            ck(commitment(bb) == "", "no pick must mean no commitment")
        render(bb)                                # every state must be printable, always

    # 14. Every leak in the catalogue carries a usable instruction and a live guard.
    for t, m in LEAKS.items():
        ck(m["fix"] and m["guard"] and m["short"], f"{t} is missing its copy")
        ck(len(m["short"]) <= 10, f"{t} short label too long for a row")
    ck(set(ORDER) == set(LEAKS), "ORDER must cover the catalogue exactly")
    return True


if __name__ == "__main__":
    arg = (sys.argv[1].lower() if len(sys.argv) > 1 else "")
    if arg == "test":
        selftest()
        print("lolfix: all guards pass")
    elif arg == "demo":
        for k in ("thin", "clean", "rate", "lean", "priced"):
            print(f"\n===== {k.upper()} " + "=" * 46)
            print(render(board(demo(k), lp=(20, 20, True))))
        print()
    else:
        b = board()
        print("\n  THE ONE FIX" + "\n" + "  " + "-" * 60)
        print(render(b))
        print()
