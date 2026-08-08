#!/usr/bin/env python3
"""lolpool.py - THE POOL: your champion pool, priced in your own LP.

v0.9.70 gave every *habit* in your ledger a price in LP and named the one worth fixing. This
module does the same job for the other half of the climb - and, by the app's own north star,
the bigger half: **which champions you queue.** Champion-pool discipline is the highest-
confidence lever in ranked; MAX ELO has enforced a pool since the day it shipped without the
app ever telling you what the pool should BE. The profile's answer was three raw win-rate
bullets ("play more Sett 58%"), computed by their own separate math, which meant the profile
and the champ-select recommender could disagree about the same champion. That is now one read.

Two decisions get priced here, in two different units, and both are labelled everywhere they
are drawn because mixing them up would be a lie:

    per 10 games ON THAT CHAMPION      "should I queue this champion?"
    per 10 of YOUR games               "is my pool too wide?"   (THE ONE FIX's unit)

    THE POOL - 9 champions over your last 31 games
      Sett        +38 LP / 10 on it     14W-6L over 20   70% on it vs 45% otherwise
      Ornn          +11pp lean           6W-3L over 9
      Darius      -44 LP / 10 on it      2W-8L over 10   20% on it vs 58% otherwise
      SPREAD      -29 LP / 10 games      top 3: 20W-15L  ·  the other 6: 3W-13L

HOUSE RULES (docs/TAGS.md - a claim carries its evidence, and never outruns it):

  - **It corrects for looking at every champion at once.** This is the failure mode of every
    "your best champion" stat ever shown to a League player, and it is not a small one - the
    guard suite measures it: on random pools where every champion is a TRUE coin flip, testing
    each one at the app's ordinary bar declares a "proven" best or worst champion in **49% of
    them**. So the bar is divided among the champions eligible to clear it, in both directions
    (Sidak on the alpha lolqueue's Z_PROVEN encodes, over 2k comparisons) - one eligible
    champion needs z>=1.63, three need z>=2.11, eight need z>=2.48. That takes the same
    measured false-positive rate to **7%**. The pool-WIDTH test below is a single
    pre-specified hypothesis and correctly takes no such correction.
  - **The price is the conservative end, never the flattering one.** Every champion's win rate
    is pulled PRIOR_N pseudo-games toward YOUR OWN baseline before it is quoted, so a 6-0 run
    can't shout and a 40-game main is barely touched. The significance test still runs on the
    real counts - the haircut governs how loudly a proven gap may speak, not whether it is one.
  - **Against your own baseline, not 50%.** A 47% champion is not a leak for a player who wins
    44% of everything else; it is their second-best champion. Every comparison here is
    champion-vs-your-other-games, the same bucket-vs-complement shape lolqueue uses.
  - **Your most-played champion is never benched.** A main on a bad run is variance, and the
    row says so - the one idea worth keeping from the old pool coach.
  - **No sample, no board.** Under MIN_TOTAL games the surface says how many more it needs and
    gets out of the way. Under MIN_G games a champion carries no claim at all.

Correlation, not proof of causation, and the board says so out loud: these are your own games,
split by champion, and the direction is yours to act on.

CLI:  python core/lolpool.py            # your real pool board
      python core/lolpool.py demo       # every render state, from synthetic pools
      python core/lolpool.py test       # the guard suite (also wired into selftest)
"""
import os
import sys
from statistics import NormalDist

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    if os.path.join(_R, _d) not in sys.path:
        sys.path.insert(0, os.path.join(_R, _d))

import lolqueue as lq                  # ONE BRAIN for "is this split proven?" (lq._z_worse)
import lolfix as lx                    # ONE READER for "what is a win worth to YOU" (lp_rates)
from smitei18n import t, tf

# ---- bars -------------------------------------------------------------------------
MIN_TOTAL = 15        # your games on record before the board renders anything at all
MIN_G = 6             # games on ONE champion before it may carry any claim
CORE_N = 3            # the pool you're being asked to commit to (the climb research's number)
MIN_SIDE = 4          # games on each side of the core/tail split before WIDTH may speak
PRIOR_N = 6           # pseudo-games pulling a champion's rate toward YOUR baseline before it
                      # is quoted in LP. Champions carry thinner samples than lolfix's habit
                      # splits, so this prior is heavier than that module's - a 6-0 champion is
                      # a real signal but it is not a 100-LP headline, and quoting it as one is
                      # a lie with numbers. Converges to the raw rate as the sample grows.
LEAN_GAP = 0.08       # a gap under this isn't even a lean - it's your average game
MAIN_SHARE = 0.30     # this share of your games makes a champion a MAIN: slump, never bench
FOCUS_SHARE = 0.80    # your top CORE_N holding this much of your games IS pool discipline
WIDE_POOL = 6         # ... and this many champions with the top 3 under FOCUS_SHARE is wide

ALPHA = 1.0 - NormalDist().cdf(lq.Z_PROVEN)   # the one-sided risk Z_PROVEN encodes (~0.10),
                                              # read off lolqueue so the two can never disagree
Z_CEIL = 3.5          # no correction may make a claim unreachable on a real person's history


def z_bar(k):
    """The z a champion must beat when k champions are eligible to be tested.

    ALPHA is the risk the app already accepts for a single pre-specified claim. Searching k
    champions spends that risk k times over, so it gets divided (Sidak, via the exact normal
    quantile) - and divided by **2k**, not k, because each champion may be claimed in EITHER
    direction. lolqueue only ever asks "is this bucket worse", a one-sided question fixed in
    advance; "is this champion different from my average" is two-sided, and charging it as
    one-sided is the second-most-common way a stat like this lies. Floored at the app's own
    Z_PROVEN so this can never be a laxer bar than anything else in the app."""
    m = 2 * max(1, int(k or 1))
    return max(lq.Z_PROVEN,
               min(Z_CEIL, NormalDist().inv_cdf(1.0 - (1.0 - (1.0 - ALPHA) ** (1.0 / m)))))


# ---- reading a pool ---------------------------------------------------------------

def _norm(name):
    return "".join(c for c in (name or "").lower() if c.isalnum())


def normalize(champs):
    """[{champ,g,w,avg}] from anything the app already holds: lolprofile's champs list, or
    lolfit's {normname: {g,w,avg}} record. Rows without a name or without games are dropped -
    a champion you have no games on is not in your pool."""
    out = []
    if isinstance(champs, dict):
        champs = [dict(v or {}, champ=k) for k, v in champs.items()]
    for c in champs or []:
        try:
            g, w = int((c or {}).get("g") or 0), int((c or {}).get("w") or 0)
        except (TypeError, ValueError):
            continue
        name = (c or {}).get("champ")
        if not name or g <= 0:
            continue
        w = max(0, min(g, w))                    # a pool row claiming more wins than games is
        avg = (c or {}).get("avg")               # corrupt, not evidence
        try:
            avg = None if avg is None else round(float(avg))
        except (TypeError, ValueError):
            avg = None
        out.append({"champ": str(name), "g": g, "w": w,
                    "wr": round(w / g * 100), "avg": avg})
    # Sorted by GAMES, then by name. Never by win rate: the top CORE_N of this list becomes the
    # "core" the width test measures the rest against, and picking that core by win rate would
    # be choosing the winners and then discovering they win. Ties break alphabetically, which
    # is meaningless on purpose - _width refuses to price a boundary that lands inside a tie.
    out.sort(key=lambda c: (-c["g"], c["champ"]))
    return out


def _shrunk(w, g, base):
    """A win rate pulled PRIOR_N pseudo-games toward your own baseline."""
    return (w + PRIOR_N * base) / (g + PRIOR_N) if (g + PRIOR_N) else base


def _row(c, n, wins_all, base, swing, bar, is_main):
    """One champion, fully priced. state is the strength of claim the row may make:
      earner - proven above your own baseline for you, and priced
      bench  - proven below it, and priced
      slump  - would have been benched, but it's your MAIN: variance, not the pick
      lean   - a real gap (>=LEAN_GAP) that hasn't cleared the corrected bar
      flat   - enough games, no real gap: this champion plays like your average game
      thin   - under MIN_G games; carries its count and nothing else."""
    g, w = c["g"], c["w"]
    g_out, w_out = n - g, wins_all - w
    out = dict(c, lp10=0, z=0.0, gap=0.0, share=(g / n) if n else 0.0,
               state="thin", need=max(0, MIN_G - g), main=bool(is_main),
               evidence=tf("{wins}W-{losses}L over {games}", wins=w, losses=g - w, games=g), rest="")
    if g < MIN_G or g_out <= 0:
        # g_out == 0 is the one-trick: nothing of yours to compare against, so no claim. That
        # is not a gap in the module, it IS the answer - a single-champion pool has no spread.
        return out
    rate_out = w_out / g_out
    out["rest"] = tf("{on_it}% on it vs {otherwise}% otherwise",
                     on_it=out["wr"], otherwise=round(rate_out * 100))
    gap = (w / g) - rate_out
    out["gap"] = gap
    if gap >= 0:
        out["z"] = lq._z_worse(w_out, g_out, w, g)      # "the rest is worse than this champion"
    else:
        out["z"] = lq._z_worse(w, g, w_out, g_out)      # "this champion is worse than the rest"
    # The price is quoted off the SHRUNK rate against your own baseline, never the raw gap.
    gap_s = _shrunk(w, g, base) - base
    lp10 = round(10.0 * gap_s * swing)
    if out["z"] >= bar and abs(gap) >= LEAN_GAP and abs(lp10) >= 1:
        if gap > 0:
            out["state"], out["lp10"] = "earner", lp10
        elif is_main:
            # Your most-played champion on a bad run is variance, not a champion to drop. It
            # keeps its evidence and loses its price - a coach that tells you to abandon your
            # main is a coach you close.
            out["state"] = "slump"
        else:
            out["state"], out["lp10"] = "bench", lp10
    elif abs(gap) >= LEAN_GAP:
        out["state"] = "lean"
    else:
        out["state"] = "flat"
    return out


def _width(rows, n, wins_all, base, swing):
    """The pool-WIDTH read: your top CORE_N champions against everything else you queued,
    priced in LP per 10 of YOUR games (THE ONE FIX's unit, because that is the unit of "how
    much is my whole pool costing me").

    One pre-specified hypothesis - "a wider pool wins less" - so it takes NO multiple-
    comparisons correction. It is also the only claim here that survives a pool where no
    single champion has a sample: six champions at four games each can say nothing about any
    one of them and still say something true about the shape."""
    core, tail = rows[:CORE_N], rows[CORE_N:]
    g_c, w_c = sum(r["g"] for r in core), sum(r["w"] for r in core)
    g_t, w_t = sum(r["g"] for r in tail), sum(r["w"] for r in tail)
    out = {"state": "thin", "lp10": 0, "z": 0.0, "gap": 0.0, "n_core": g_c, "n_tail": g_t,
           "core": [r["champ"] for r in core], "tail_n": len(tail),
           "share": round((g_c / n) * 100) if n else 0,
           "evidence": "", "wr_core": round(w_c / g_c * 100) if g_c else 0,
           "wr_tail": round(w_t / g_t * 100) if g_t else 0}
    if not tail:
        out["state"] = "focused"                       # nothing outside the core to price
        return out
    out["evidence"] = tf("top {core_count}: {core_wins}W-{core_losses}L  ·  the other {tail_count}: {tail_wins}W-{tail_losses}L",
                         core_count=len(core), core_wins=w_c, core_losses=g_c - w_c,
                         tail_count=len(tail), tail_wins=w_t, tail_losses=g_t - w_t)
    if g_c < MIN_SIDE or g_t < MIN_SIDE:
        return out
    if core[-1]["g"] <= tail[0]["g"]:
        # The CORE_N boundary landed inside a tie on games played, so which champions count as
        # "your core" is an alphabetical accident. Eight champions at six games each have no
        # core, and pricing the split would be measuring the coin that came up heads. Say
        # nothing - the pool WIDTH is still reported as a count, which is a fact.
        out["state"] = "even"
        return out
    out["gap"] = (w_c / g_c) - (w_t / g_t)
    out["z"] = lq._z_worse(w_t, g_t, w_c, g_c)
    gap_s = max(0.0, _shrunk(w_c, g_c, base) - _shrunk(w_t, g_t, base))
    lp10 = round(10.0 * (g_t / n) * gap_s * swing)
    if out["z"] >= lq.Z_PROVEN and out["gap"] > 0 and lp10 >= 1:
        out["state"], out["lp10"] = "priced", -lp10    # a cost, so it renders negative
    elif out["gap"] >= LEAN_GAP:
        out["state"] = "lean"
    else:
        out["state"] = "flat"
    return out


_RANK = {"earner": 0, "lean": 1, "flat": 2, "slump": 3, "bench": 4, "thin": 5}


def board(champs, lp=None):
    """The whole board.

    {rows, width, queue, bench, slump, n, pool_n, ready, need, bar, k_eligible, verdict,
     lp_win, lp_loss, lp_measured}

    `queue` is the one champion your own history says to press Find Match on; `bench` the one
    it says to stop pressing it on. Either can be None, and usually one of them is - the board
    is allowed to say nothing, which is the whole reason it can be trusted when it does."""
    rows_in = normalize(champs)
    n = sum(c["g"] for c in rows_in)
    wins_all = sum(c["w"] for c in rows_in)
    lp_win, lp_loss, measured = lp if lp else lx.lp_rates()
    swing = lp_win + lp_loss
    out = {"rows": [], "width": None, "queue": None, "bench": None, "slump": None,
           "n": n, "pool_n": len(rows_in), "ready": n >= MIN_TOTAL,
           "need": max(0, MIN_TOTAL - n), "bar": lq.Z_PROVEN, "k_eligible": 0,
           "verdict": "thin", "base": (wins_all / n) if n else 0.0,
           "lp_win": lp_win, "lp_loss": lp_loss, "lp_measured": measured}
    if not out["ready"]:
        out["rows"] = [dict(c, state="thin", lp10=0, z=0.0, gap=0.0, main=False,
                            share=(c["g"] / n) if n else 0.0, need=max(0, MIN_G - c["g"]),
                            evidence=tf("{wins}W-{losses}L over {games}",
                                        wins=c["w"], losses=c["g"] - c["w"], games=c["g"]), rest="")
                       for c in rows_in]
        return out
    base = out["base"]
    # The correction is sized by how many champions are ELIGIBLE to be tested, not by how many
    # you have played: a pool of twelve champions where only three carry MIN_G games has been
    # searched three ways, and charging it for twelve would silence the board entirely.
    k = sum(1 for c in rows_in if c["g"] >= MIN_G and (n - c["g"]) > 0)
    out["k_eligible"], out["bar"] = k, z_bar(k)
    main = rows_in[0]["champ"] if (rows_in and rows_in[0]["g"] >= MAIN_SHARE * n) else None
    rows = [_row(c, n, wins_all, base, swing, out["bar"], c["champ"] == main) for c in rows_in]
    out["width"] = _width(rows_in, n, wins_all, base, swing)
    out["rows"] = sorted(rows, key=lambda r: (_RANK[r["state"]], -abs(r["lp10"]), -r["g"]))
    earners = [r for r in rows if r["state"] == "earner"]
    benched = [r for r in rows if r["state"] == "bench"]
    if earners:
        out["queue"] = max(earners, key=lambda r: (r["lp10"], r["g"]))
    if benched:
        out["bench"] = min(benched, key=lambda r: (r["lp10"], -r["g"]))
    slumps = [r for r in rows if r["state"] == "slump"]
    if slumps:
        out["slump"] = min(slumps, key=lambda r: r["gap"])
    w = out["width"]
    if w["state"] == "priced":
        out["verdict"] = "spread"
    elif w["state"] == "focused" or w["share"] >= FOCUS_SHARE * 100:
        out["verdict"] = "focused"
    elif out["pool_n"] >= WIDE_POOL:
        out["verdict"] = "wide"
    else:
        out["verdict"] = "ok"
    return out


_LIVE = {"ts": 0.0, "board": None}
LIVE_TTL = 120        # seconds. champ select re-renders on a timer and calls live_board() every
                      # pass; your champion history cannot change during a draft, so rebuilding
                      # it per frame would be pure disk traffic on the machine playing the game.


def live_board(lp=None, force=False):
    """The board off whatever this machine already knows, no network. lolfit's merged record is
    the deepest champion history on disk (profile + season read, pooled), so it is the source
    of truth here; the cached profile is the fallback when the fit cache hasn't been built.

    Memoized for LIVE_TTL — safe to call from a render loop."""
    import time as _t
    if not force and _LIVE["board"] is not None and (_t.time() - _LIVE["ts"]) < LIVE_TTL:
        return _LIVE["board"]
    champs = None
    try:
        import lolfit as _fit
        champs = (_fit.build() or {}).get("champs") or None
    except Exception:
        champs = None
    if not champs:
        try:
            import lolprofile as _lp
            rid = _lp.current_riot_id()
            prof = _lp._load_profile(rid) if rid else None
            champs = (prof or {}).get("champs") or []
        except Exception:
            champs = []
    b = board(champs, lp=lp)
    _LIVE["ts"], _LIVE["board"] = _t.time(), b
    return b


# ---- the sentences the surfaces render ---------------------------------------------

def row_note(r):
    """The short right-hand figure for one champion row, in the unit it is measured in."""
    st = r["state"]
    if st == "earner":
        return tf("+{lp} LP / 10 on it", lp=r["lp10"])
    if st == "bench":
        return tf("{lp} LP / 10 on it", lp=r["lp10"])
    if st == "slump":
        return t("rough patch")
    if st == "lean":
        return tf("{gap:+d}pp lean", gap=round(r["gap"] * 100))
    if st == "flat":
        return t("your average game")
    return tf("{games} more", games=r["need"]) if r["need"] else t("no comparison")


def width_note(w):
    """The short right-hand figure for the WIDTH row."""
    if not w:
        return ""
    if w["state"] == "priced":
        return tf("{lp} LP / 10 games", lp=w["lp10"])
    if w["state"] == "focused":
        return t("focused")
    if w["state"] == "lean":
        return tf("{gap:+d}pp lean", gap=round(w["gap"] * 100))
    if w["state"] == "flat":
        return t("no cost found")
    if w["state"] == "even":
        return t("no core to measure")
    return t("thin")


def _champs_n(b):
    n = b.get("pool_n") or 0
    return tf("{count} champion", count=n) if n == 1 else tf("{count} champions", count=n)


def headline(b):
    """The one line the profile page leads with - the strongest claim the board can defend."""
    if not b.get("ready"):
        return tf("THE POOL: reading your games - {games} more and your champions get priced in LP",
                  games=b["need"])
    q, bn, w = b.get("queue"), b.get("bench"), b.get("width") or {}
    if w.get("state") == "priced":
        return tf("THE POOL: {champions} over your last {games} - your top {core_count} win {core_wr}%, the other {tail_count} win {tail_wr}%. That spread is {lp} LP / 10 games. Commit to {core}.",
                  champions=_champs_n(b), games=b["n"], core_count=len(w["core"]),
                  core_wr=w["wr_core"], tail_count=w["tail_n"], tail_wr=w["wr_tail"],
                  lp=abs(w["lp10"]), core=", ".join(w["core"][:CORE_N]))
    if bn:
        return tf("THE POOL: {champion} costs you {lp} LP / 10 games on it ({evidence}). Bench it - queue {replacement} instead.",
                  champion=bn["champ"], lp=abs(bn["lp10"]), evidence=bn["evidence"],
                  replacement=(q or {}).get("champ") or (w.get("core") or [t("your mains")])[0])
    if q:
        return tf("THE POOL: {champion} is your earner - +{lp} LP / 10 games on it ({evidence}). Queue it.",
                  champion=q["champ"], lp=q["lp10"], evidence=q["evidence"])
    if b.get("slump"):
        s = b["slump"]
        return tf("THE POOL: rough patch on {champion} ({evidence}) - it's your main and the sample says variance, not the pick. Keep queueing it.",
                  champion=s["champ"], evidence=s["evidence"])
    if b["verdict"] == "focused":
        share = (tf(", top {core} holding {share}%", core=CORE_N, share=w.get("share"))
                 if b["pool_n"] > CORE_N else "")
        return tf("THE POOL: {champions} over your last {games}{share} - that IS the discipline. Nothing to cut.",
                  champions=_champs_n(b), games=b["n"], share=share)
    ending = (t("nothing of yours to compare a single-champion pool against.")
              if b["pool_n"] < 2 else t("none of them separates from your own average yet."))
    return tf("THE POOL: {champions} over your last {games} - {ending}",
              champions=_champs_n(b), games=b["n"], ending=ending)


def receipt(b):
    """The honesty line under the board. Never omitted - it is what makes the rest usable."""
    if not b.get("ready"):
        return tf("needs {minimum} games on record  ·  {games} so far",
                  minimum=MIN_TOTAL, games=b["n"])
    lp = (tf("your LP: +{win} / -{loss}", win=b["lp_win"], loss=b["lp_loss"])
          if b.get("lp_measured") else
          tf("assuming {lp} LP a game (no rank history yet)", lp=b["lp_win"]))
    if b["k_eligible"]:
        bar = tf("bar z>={bar:.2f} across {count} champions",
                 bar=b["bar"], count=b["k_eligible"])
    elif b["pool_n"] < 2:
        bar = t("one champion, so nothing of yours to compare it against")
    else:
        bar = tf("no champion has {games} games yet", games=MIN_G)
    return tf("{games} games  ·  {lp}  ·  {bar}  ·  correlation from your own games",
              games=b["n"], lp=lp, bar=bar)


def notes(b):
    """Up to three [(kind, text)] for the compact strips (profile session band, champ select).
    Ordered by what you can act on soonest. kind is the tone the renderer colors from."""
    out = []
    if not b.get("ready"):
        return [("quiet", tf("POOL - {games} more games and your champions get priced",
                              games=b["need"]))]
    q, bn, w = b.get("queue"), b.get("bench"), b.get("width") or {}
    if q:
        out.append(("queue", tf("QUEUE {champion}  +{lp} LP/10 on it",
                                 champion=q["champ"], lp=q["lp10"])))
    if bn:
        out.append(("bench", tf("BENCH {champion}  {lp} LP/10 on it",
                                 champion=bn["champ"], lp=bn["lp10"])))
    if w.get("state") == "priced" and len(out) < 2:
        out.append(("spread", tf("POOL {count} champs  {lp} LP/10 games",
                                  count=b["pool_n"], lp=w["lp10"])))
    if b.get("slump") and len(out) < 2:
        out.append(("slump", tf("{champion} rough patch - variance, not the pick",
                                 champion=b["slump"]["champ"])))
    if not out:
        verdict = t("focused") if b["verdict"] == "focused" else t("nothing separates yet")
        out.append(("quiet", tf("POOL {count} champs  ·  {verdict}",
                                 count=b["pool_n"], verdict=verdict)))
    return out[:3]


def champ_note(b, name):
    """(state, text) for ONE champion, or (None, None) when your history can't speak about it.

    This is the shared read: the champ-select climb guard quotes it instead of a study, and
    lolfit's recommender veto IS this function's 'bench' - so the page that tells you to bench
    a champion and the recommender that refuses to suggest it can never disagree again."""
    if not b or not b.get("ready"):
        return None, None
    k = _norm(name)
    for r in b.get("rows") or []:
        if _norm(r["champ"]) != k:
            continue
        if r["state"] in ("earner", "bench"):
            return r["state"], f"{row_note(r)}  ·  {r['evidence']}  ·  {r['rest']}"
        if r["state"] == "slump":
            return "slump", tf("rough patch - {evidence}, and it's your main", evidence=r["evidence"])
        if r["state"] == "lean":
            return "lean", f"{row_note(r)}  ·  {r['evidence']}"
        if r["state"] == "flat":
            return "flat", tf("plays like your average game  ·  {evidence}", evidence=r["evidence"])
        return None, None
    return None, None


DRAFT_MAX = 46        # champ select draws its note on one unwrapped line beside the import
                      # button. A note that overflows that is a rendering bug wearing a receipt.


def short_note(b, name):
    """(state, compact text) for ONE champion, sized for champ select, or (None, None).

    Only the three states worth interrupting a draft for. A 'lean' is deliberately silent
    here: the profile page is where you read a lean, and a maybe is not worth the two seconds
    you have to decide what to hover."""
    st, _why = champ_note(b, name)
    if st not in ("earner", "bench", "slump"):
        return None, None
    r = next((x for x in b["rows"] if _norm(x["champ"]) == _norm(name)), None)
    if not r:
        return None, None
    wl = f"({r['w']}W-{r['g'] - r['w']}L)"
    if st == "slump":
        txt = tf("rough patch {record} - variance, not the pick", record=wl)
    else:
        txt = f"{row_note(r)} {wl}"
    return st, txt[:DRAFT_MAX]


def render(b):
    """The board as text - what the CLI and the guard suite both read."""
    L = [f"  {headline(b)}", f"  {receipt(b)}", ""]
    mark = {"earner": "++", "lean": " ~", "flat": " .", "slump": " *", "bench": "!!", "thin": " ?"}
    for r in b.get("rows", []):
        L.append(f"  {mark[r['state']]} {r['champ'][:14]:<14} {row_note(r):>20}   "
                 f"{r['evidence']:<18} {r['rest']}")
    w = b.get("width")
    if w and b.get("ready"):
        L.append(f"  == {'POOL WIDTH':<14} {width_note(w):>20}   {w['evidence']}")
    return "\n".join(L)


# ---- synthetic pools, one per render state ------------------------------------------

def demo(kind="spread"):
    """A champion list that lands the board in one known state. Every one of these is a shape
    a real account actually produces, which is the only reason they are worth testing."""
    if kind == "thin":
        return [{"champ": "Sett", "g": 5, "w": 3, "avg": 78},
                {"champ": "Ornn", "g": 4, "w": 2, "avg": 70}]
    if kind == "onetrick":
        return [{"champ": "Sett", "g": 34, "w": 20, "avg": 84}]
    if kind == "focused":
        return [{"champ": "Sett", "g": 20, "w": 11, "avg": 82},
                {"champ": "Ornn", "g": 12, "w": 7, "avg": 79},
                {"champ": "Mordekaiser", "g": 9, "w": 5, "avg": 76},
                {"champ": "Garen", "g": 3, "w": 2, "avg": 71}]
    if kind == "earner":
        return [{"champ": "Sett", "g": 22, "w": 16, "avg": 88},
                {"champ": "Ornn", "g": 14, "w": 6, "avg": 72},
                {"champ": "Mordekaiser", "g": 12, "w": 5, "avg": 70},
                {"champ": "Garen", "g": 10, "w": 4, "avg": 68}]
    if kind == "bench":
        return [{"champ": "Sett", "g": 24, "w": 14, "avg": 84},
                {"champ": "Ornn", "g": 16, "w": 9, "avg": 80},
                {"champ": "Darius", "g": 14, "w": 2, "avg": 58},
                {"champ": "Garen", "g": 9, "w": 5, "avg": 74}]
    if kind == "slump":
        # A main having a genuinely awful stretch, and nothing else with a sample. This is the
        # shape where the old pool coach said "ease off Sett" - the single worst advice the app
        # was capable of giving, and the reason the slump read is kept.
        return [{"champ": "Sett", "g": 26, "w": 6, "avg": 62},
                {"champ": "Ornn", "g": 5, "w": 4, "avg": 84},
                {"champ": "Mordekaiser", "g": 5, "w": 3, "avg": 82},
                {"champ": "Garen", "g": 4, "w": 2, "avg": 74}]
    if kind == "flat":
        return [{"champ": "Sett", "g": 14, "w": 7, "avg": 76},
                {"champ": "Ornn", "g": 12, "w": 6, "avg": 75},
                {"champ": "Mordekaiser", "g": 10, "w": 5, "avg": 74}]
    if kind == "noisy":
        # Eight champions, six games each, every one a coin flip. The whole point of the
        # correction: an uncorrected bar finds a "proven" winner in here.
        return [{"champ": f"Champ{i}", "g": 6, "w": w, "avg": 74}
                for i, w in enumerate((5, 1, 4, 2, 3, 3, 4, 2))]
    # "spread": a disciplined core and a long tail of ranked tourism
    return [{"champ": "Sett", "g": 16, "w": 10, "avg": 84},
            {"champ": "Ornn", "g": 11, "w": 7, "avg": 81},
            {"champ": "Mordekaiser", "g": 8, "w": 5, "avg": 79},
            {"champ": "Darius", "g": 5, "w": 1, "avg": 62},
            {"champ": "Garen", "g": 4, "w": 0, "avg": 58},
            {"champ": "Aatrox", "g": 4, "w": 1, "avg": 60},
            {"champ": "Camille", "g": 3, "w": 0, "avg": 55},
            {"champ": "Gwen", "g": 3, "w": 1, "avg": 61},
            {"champ": "Jax", "g": 3, "w": 1, "avg": 63}]


DEMOS = ("thin", "onetrick", "focused", "earner", "bench", "slump", "flat", "noisy", "spread")


# ---- guard suite --------------------------------------------------------------------

def selftest():
    # Phrase assertions below predate localization; bilingual contract parity lives in the
    # repository i18n guard, while this suite remains about the statistical engine.
    from smitei18n import set_lang
    set_lang("en")
    """Every invariant the board is allowed to be trusted for. Raises on the first break."""
    def ck(cond, msg):
        if not cond:
            raise AssertionError(msg)

    LP = (22, 18, True)
    swing = LP[0] + LP[1]

    # 1. No sample, no board - and it says how far off it is, without pricing anything.
    b = board(demo("thin"), lp=LP)
    ck(not b["ready"] and b["queue"] is None and b["bench"] is None,
       "a thin pool must price nothing")
    ck(b["need"] == MIN_TOTAL - 9, f"need must count the shortfall, got {b['need']}")
    ck(all(r["state"] == "thin" for r in b["rows"]), "every row on a thin board is thin")
    ck("more" in headline(b) and notes(b)[0][0] == "quiet", "thin board asks for games only")
    ck(render(b), "a thin board must still render")

    # 2. The one-trick: nothing to compare against, so no claim - and no crash.
    b = board(demo("onetrick"), lp=LP)
    ck(b["ready"] and b["pool_n"] == 1, "the one-trick board should be ready")
    ck(b["queue"] is None and b["bench"] is None, "a one-champion pool can prove nothing")
    ck(b["rows"][0]["state"] == "thin" and b["rows"][0]["z"] == 0.0,
       "a one-trick row has no complement and must carry no z")
    ck(b["width"]["state"] == "focused" and b["width"]["lp10"] == 0,
       "one champion is not a spread")
    ck(b["verdict"] == "focused", f"one-trick verdict should be focused, got {b['verdict']}")

    # 3. THE CORRECTION - the invariant this module exists for. Eight coin-flip champions
    #    must produce NO priced claim, and the same pool at the uncorrected bar must produce
    #    one (otherwise the test proves nothing about the correction).
    noisy = demo("noisy")
    b = board(noisy, lp=LP)
    ck(b["k_eligible"] == 8, f"all eight should be eligible, got {b['k_eligible']}")
    ck(b["bar"] > lq.Z_PROVEN, "eight eligible champions must raise the bar")
    ck(b["queue"] is None and b["bench"] is None,
       f"pure noise must not price a champion (got {b['queue']}, {b['bench']})")
    rows_in = normalize(noisy)
    n_all = sum(c["g"] for c in rows_in)
    w_all = sum(c["w"] for c in rows_in)
    naive = [_row(c, n_all, w_all, w_all / n_all, swing, lq.Z_PROVEN, False) for c in rows_in]
    ck(any(r["state"] in ("earner", "bench") for r in naive),
       "the uncorrected bar should have been fooled here - fixture no longer tests anything")
    # ... and the bar has to move monotonically with the search, and stay reachable.
    ck(z_bar(1) > lq.Z_PROVEN, "even one champion is a two-sided question and costs something")
    ck(z_bar(3) > z_bar(2) > z_bar(1), "the bar must rise with the number of champions tested")
    ck(z_bar(0) == z_bar(1) == z_bar(None), "no eligible champions must not crash the bar")
    ck(z_bar(400) <= Z_CEIL, "the correction must never become unreachable")
    ck(min(z_bar(k) for k in range(1, 60)) >= lq.Z_PROVEN,
       "this module must never price a claim at a laxer bar than the rest of the app")

    # 4. A proven earner: priced, picked, and priced CONSERVATIVELY.
    b = board(demo("earner"), lp=LP)
    q = b["queue"]
    ck(q and q["champ"] == "Sett", f"expected Sett as the earner, got {q}")
    ck(q["state"] == "earner" and q["lp10"] > 0, "the earner must carry a positive price")
    ck(q["z"] >= b["bar"], "a priced row must have beaten the corrected bar")
    raw = 10.0 * q["gap"] * swing
    ck(q["lp10"] < raw, f"price {q['lp10']} must sit under the raw-gap figure {raw:.1f}")
    ck(b["rows"][0]["champ"] == "Sett", "the earner heads the board")
    ck(str(q["lp10"]) in headline(b) and "Queue it" in headline(b),
       f"the headline must quote the earner's price: {headline(b)}")
    ck(notes(b)[0][0] == "queue" and "Sett" in notes(b)[0][1], "the strip leads with the earner")
    ck(champ_note(b, "sett")[0] == "earner" and champ_note(b, "SETT")[0] == "earner",
       "champ_note must be name-normalized")
    ck(champ_note(b, "Nobody") == (None, None), "an unknown champion gets no claim")

    # 5. A proven loser gets benched, priced negative, and the headline names the swap.
    b = board(demo("bench"), lp=LP)
    bn = b["bench"]
    ck(bn and bn["champ"] == "Darius", f"expected Darius benched, got {bn}")
    ck(bn["lp10"] < 0 and "Bench it" in headline(b), "a bench row must be priced as a cost")
    ck(bn["main"] is False, "Darius is not this account's main")
    ck(champ_note(b, "Darius")[0] == "bench", "the shared read must agree with the board")
    ck(b["rows"][-1]["state"] in ("bench", "thin"), "a benched champion sorts to the bottom")

    # 6. Your MAIN is never benched - it slumps, and it loses the price, not the evidence.
    b = board(demo("slump"), lp=LP)
    s = b["slump"]
    ck(s and s["champ"] == "Sett", f"expected Sett slumping, got {s}")
    ck(b["bench"] is None, "the main must never be handed to you as a bench")
    ck(s["lp10"] == 0 and s["evidence"], "a slump carries evidence but no price")
    ck("variance" in headline(b), f"the slump headline must say variance: {headline(b)}")
    ck(champ_note(b, "Sett")[0] == "slump", "the shared read must call it a slump too")
    # A slumping main and a proven earner can coexist - with two champions it is arithmetically
    # unavoidable. The headline then leads with the champion to QUEUE (that's the action), but
    # the slump must not vanish, or the app has quietly told you to drop your main by omission.
    mixed = board([{"champ": "Sett", "g": 30, "w": 7, "avg": 62},
                   {"champ": "Ornn", "g": 14, "w": 9, "avg": 84}], lp=LP)
    ck(mixed["slump"] and mixed["slump"]["champ"] == "Sett", "the main must still read as a slump")
    ck(mixed["bench"] is None, "a main is never benched, earner present or not")
    ck(mixed["queue"] and mixed["queue"]["champ"] == "Ornn", "the earner should still be picked")
    ck([k for k, _t in notes(mixed)] == ["queue", "slump"],
       f"the strip must carry both the earner and the slump: {notes(mixed)}")

    # 7. A flat pool says so rather than inventing a difference.
    b = board(demo("flat"), lp=LP)
    ck(b["queue"] is None and b["bench"] is None and b["slump"] is None,
       "three champions at your own rate must produce no pick")
    ck(all(r["state"] in ("flat", "thin") for r in b["rows"]), "flat pool, flat rows")
    ck(b["width"]["state"] in ("flat", "thin", "focused"),
       f"a flat pool has no width cost, got {b['width']['state']}")

    # 8. Pool WIDTH: priced, in THE ONE FIX's unit, and it takes no correction.
    b = board(demo("spread"), lp=LP)
    w = b["width"]
    ck(w["state"] == "priced" and w["lp10"] < 0, f"the spread fixture must price: {w}")
    ck(w["z"] >= lq.Z_PROVEN, "the width claim must have beaten the uncorrected bar")
    ck(len(w["core"]) == CORE_N and w["tail_n"] == 6, f"core/tail split wrong: {w}")
    ck(w["wr_core"] > w["wr_tail"], "the fixture's core must out-win its tail")
    ck(b["verdict"] == "spread" and "Commit to" in headline(b),
       f"a priced spread must reach the headline: {headline(b)}")
    ck(all(c in headline(b) for c in w["core"]), "the headline must name the core to commit to")
    ck("LP / 10 games" in width_note(w) and "on it" not in width_note(w),
       "the width row must be quoted per 10 of YOUR games, never per 10 on a champion")
    for r in b["rows"]:
        if r["state"] in ("earner", "bench"):
            ck("on it" in row_note(r),
               "a champion row must be quoted per 10 games ON IT, never per 10 of your games")

    # 9. Every state renders, every headline is a sentence, and nothing raises.
    for k in DEMOS:
        bb = board(demo(k), lp=LP)
        ck(render(bb) and headline(bb) and receipt(bb) and notes(bb),
           f"demo '{k}' failed to render")
        ck("correlation" in receipt(bb) or "needs" in receipt(bb),
           f"demo '{k}' dropped the honesty line")
        for r in bb["rows"]:
            ck(row_note(r), f"demo '{k}' produced a row with no note: {r}")
            ck(r["state"] != "earner" or r["lp10"] >= 1, "an earner with no price is broken")
            ck(r["state"] != "bench" or r["lp10"] <= -1, "a bench row with no price is broken")
            ck(r["state"] not in ("earner", "bench", "slump") or r["z"] >= bb["bar"],
               f"demo '{k}': a claim below the bar escaped as {r['state']}")
        ck(bb["queue"] is None or bb["queue"]["state"] == "earner", "queue must be an earner")
        ck(bb["bench"] is None or bb["bench"]["state"] == "bench", "bench must be a bench row")
        ck(bb["queue"] is None or bb["bench"] is None
           or bb["queue"]["champ"] != bb["bench"]["champ"],
           "the same champion can never be both the queue and the bench")

    # 10. The LP reader: an unmeasured history says so, and the price scales with YOUR LP.
    b1 = board(demo("earner"), lp=(11, 9, True))
    b2 = board(demo("earner"), lp=(22, 18, True))
    ck(b2["queue"]["lp10"] > b1["queue"]["lp10"],
       "a bigger LP swing must produce a bigger price")
    ck(abs(b2["queue"]["lp10"] - 2 * b1["queue"]["lp10"]) <= 1,
       "the price must be linear in your LP swing")
    ck("assuming" in receipt(board(demo("earner"), lp=(20, 20, False))),
       "an unmeasured LP rate must be declared on the card")
    ck("+22 / -18" in receipt(b2), "a measured LP rate must be quoted")

    # 11. Garbage in the pool can never crash the board or fake a sample.
    junk = [None, {}, {"champ": "Sett"}, {"champ": "", "g": 9, "w": 4},
            {"champ": "Ornn", "g": "x", "w": 2}, {"champ": "Jax", "g": 3, "w": 99},
            {"champ": "Gwen", "g": 20, "w": 10, "avg": "n/a"},
            {"champ": "Sett", "g": 14, "w": 9, "avg": 80.4}]
    rows = normalize(junk)
    ck([r["champ"] for r in rows] == ["Gwen", "Sett", "Jax"], f"normalize let junk through: {rows}")
    ck(rows[2]["w"] == 3, "a row claiming more wins than games must be clamped")
    ck(rows[0]["avg"] is None and rows[1]["avg"] == 80, "avg must be a rounded int or None")
    b = board(junk, lp=LP)
    ck(b["n"] == 37 and render(b), "the board must survive a junk pool")
    ck(board([], lp=LP)["ready"] is False, "an empty pool is not a board")
    ck(board(None)["pool_n"] == 0, "None must read as an empty pool")

    # 12. The WIDTH test is bias-proof too. Eight champions at six games each have no core -
    #     which three you call "the top 3" is an alphabetical accident, and pricing that split
    #     is how you discover that the coins which came up heads came up heads.
    b = board(demo("noisy"), lp=LP)
    ck(b["width"]["state"] == "even" and b["width"]["lp10"] == 0,
       f"an equal-volume pool has no core to price: {b['width']}")
    ck(b["verdict"] == "wide" and "separates" in headline(b),
       f"pure noise must produce no claim at all: {headline(b)}")
    ck(b["width"]["share"] and b["width"]["evidence"],
       "refusing to PRICE the width must not stop it reporting the counts")
    # ... and the boundary rule has to bite on the boundary itself, not just on a flat pool.
    even = board([{"champ": "A", "g": 10, "w": 8}, {"champ": "B", "g": 10, "w": 7},
                  {"champ": "C", "g": 8, "w": 6}, {"champ": "D", "g": 8, "w": 1},
                  {"champ": "E", "g": 6, "w": 1}], lp=LP)
    ck(even["width"]["state"] == "even",
       f"the 3rd and 4th champions are tied on games - no core: {even['width']}")

    # 13. It accepts lolfit's record shape too - that is how the recommender shares this brain.
    rec = {"sett": {"g": 22, "w": 16, "avg": 88}, "ornn": {"g": 14, "w": 6, "avg": 72},
           "mordekaiser": {"g": 12, "w": 5}, "garen": {"g": 10, "w": 4, "avg": 68}}
    b = board(rec, lp=LP)
    ck(b["queue"] and b["queue"]["champ"] == "sett", f"dict-shaped record failed: {b['queue']}")
    ck(champ_note(b, "Sett")[0] == "earner", "the dict shape must answer to real champion names")

    # 14. The champ-select note: short enough for the one unwrapped line it is drawn on, and
    #     silent on anything weaker than a claim worth interrupting a draft for.
    b = board(demo("bench"), lp=LP)
    st, txt = short_note(b, "Darius")
    ck(st == "bench" and len(txt) <= DRAFT_MAX and "LP" in txt, f"bench draft note: {txt!r}")
    ck(short_note(b, "Sett") == (None, None), "a lean must not interrupt a draft")
    ck(short_note(b, "Nobody") == (None, None), "an unknown champion gets no draft note")
    ck(short_note(board(demo("thin"), lp=LP), "Sett") == (None, None),
       "an unready board must never reach champ select")
    for k in DEMOS:
        bb = board(demo(k), lp=LP)
        for r in bb["rows"]:
            st2, t2 = short_note(bb, r["champ"])
            ck(st2 is None or (t2 and len(t2) <= DRAFT_MAX),
               f"demo '{k}' draft note too long for the line it's drawn on: {t2!r}")
            ck(st2 in (None, "earner", "bench", "slump"), f"unexpected draft state {st2}")

    # 15. THE FUZZ. Random pools where every champion is a TRUE coin flip and the player's own
    #     baseline is 50% - so ANY priced claim the board makes is, by construction, a lie. Two
    #     things are asserted: the structural invariants hold on every shape of history that
    #     can exist, and the false-positive RATE is actually held down by the correction (the
    #     same pools are re-scored at the uncorrected bar, which must be measurably worse - or
    #     this test is proving nothing about the thing it exists to prove).
    import random
    rnd = random.Random(0xC0FFEE)
    trials, fp_champ, fp_naive, fp_width = 1200, 0, 0, 0
    for _t in range(trials):
        pool = []
        for i in range(rnd.randint(1, 9)):
            g = rnd.randint(1, 30)
            pool.append({"champ": f"C{i}", "g": g,
                         "w": sum(1 for _ in range(g) if rnd.random() < 0.5),
                         "avg": rnd.choice([None, rnd.randint(50, 110)])})
        bb = board(pool, lp=LP)
        ck(render(bb) and headline(bb) and receipt(bb) and notes(bb), f"fuzz render broke: {pool}")
        rs = bb["rows"]
        ck(len(rs) == len(normalize(pool)), "the board must keep every champion in the pool")
        ck(sum(r["g"] for r in rs) == bb["n"], "the board's game count must equal the pool's")
        for r in rs:
            ck(row_note(r), f"fuzz produced a row with no note: {r}")
            ck(r["state"] != "earner" or (r["lp10"] >= 1 and r["gap"] > 0),
               f"an earner must be priced and positive: {r}")
            ck(r["state"] != "bench" or (r["lp10"] <= -1 and r["gap"] < 0),
               f"a bench row must be priced and negative: {r}")
            ck(r["state"] not in ("earner", "bench", "slump")
               or (r["z"] >= bb["bar"] and r["g"] >= MIN_G),
               f"a claim escaped below the bar or the sample: {r}")
            ck(not (r["state"] == "bench" and r["main"]), f"a main was benched: {r}")
            ck(r["state"] == "thin" or r["rest"], "a row that compares must show what it beat")
        q, bn = bb["queue"], bb["bench"]
        ck(q is None or bn is None or q["champ"] != bn["champ"], "queue and bench collided")
        w = bb["width"]
        if w and w["state"] == "priced":
            core, tail = normalize(pool)[:CORE_N], normalize(pool)[CORE_N:]
            ck(core[-1]["g"] > tail[0]["g"], f"a tied boundary was priced: {w}")
            ck(w["z"] >= lq.Z_PROVEN and w["lp10"] < 0, f"width priced below its bar: {w}")
            fp_width += 1
        if q or bn:
            fp_champ += 1
        rows_in = normalize(pool)
        nn, ww = sum(c["g"] for c in rows_in), sum(c["w"] for c in rows_in)
        if nn >= MIN_TOTAL and any(
                _row(c, nn, ww, ww / nn, swing, lq.Z_PROVEN, False)["state"]
                in ("earner", "bench") for c in rows_in):
            fp_naive += 1
    r_c, r_n, r_w = fp_champ / trials, fp_naive / trials, fp_width / trials
    ck(r_n > 2 * r_c, f"the correction must measurably cut false positives ({r_n:.3f} -> {r_c:.3f})")
    ck(r_c <= 0.10, f"corrected false-positive rate {r_c:.3f} is too high for a priced claim")
    ck(r_w <= 0.10, f"width false-positive rate {r_w:.3f} is too high for a priced claim")
    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "test":
        selftest()
        print("lolpool: all guards pass")
    elif arg == "demo":
        for k in DEMOS:
            print(f"\n===== {k.upper()} " + "=" * (60 - len(k)))
            print(render(board(demo(k), lp=(22, 18, True))))
    else:
        print(render(live_board()))
