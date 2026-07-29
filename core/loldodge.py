#!/usr/bin/env python3
"""loldodge.py - THE DODGE CALL: is walking away from this lobby actually worth 3 LP?

THE HOLE THIS FILLS
Dodging is the only lever in the whole app that lets you refuse a game you were going to
lose, and up to now Smiteless answered it with vibes. Two unrelated surfaces both said
"consider dodging" and neither one priced the decision:

  - the draft read (smitecard.dodge_read) fired on four hard-coded thresholds - average lane
    delta under -3, three losing lanes, one hard counter - which are somebody's taste, not a
    number you can argue with;
  - the ally scout flagged a teammate on a 3-loss streak and shouted about it, having never
    once considered that the ENEMY team, which you cannot see in champ select, has tilted
    players in it at exactly the same rate. A flag on your side is only evidence to the
    extent that it BEATS that base rate, and about half the time it doesn't.

Neither one knew what a dodge costs, what a game is worth to you, or how long either takes.
So a dodge that saved 1 LP and a dodge that saved 12 read identically, and a lobby that was
merely unlucky-looking got treated like a lost one.

WHAT THIS DOES INSTEAD
One question, in LP, over the same horizon: **you have the next hour either way - which
branch ends with more LP in it?**

    play this lobby:   ev_play   then carry on at your baseline rate
    dodge it:          -cost, sit out the penalty, then play a FRESH lobby at baseline

    dodge - play  =  -cost - ev_play + ev_next * (game_minutes - dodge_minutes) / game_minutes

Every term is yours and measured, not assumed:
  - ev_play / ev_next  from YOUR LP per win and per loss, read off your own rank snapshots
    (lolprofile's LP history), not the folklore 20/20;
  - game_minutes       the median length of YOUR ranked games (lolqueue's client history),
    plus the champ-select + loading + post-game time you spend either way;
  - cost / dodge_minutes  Riot's own published solo-queue penalties - and because the SECOND
    dodge of a day is -10 LP and a 30-minute lockout, this math says out loud what no
    threshold ever could: the second dodge is almost never worth it. It takes a lobby under
    ~17% for the numbers to justify it, and no draft read is that confident.

WHAT'S EVIDENCE AND WHAT'S A MODEL, stated plainly (house rule, docs/TAGS.md):
  - LANE WIN RATES are op.gg's, on real samples, gated at MIN_LANE_GAMES games per lane and
    MIN_LANES lanes before the draft term may speak at all. Each one is already a GAME win
    rate for that pairing, so the lanes COMPOSE in log-odds rather than average (see DRAFT_K),
    and DRAFT_K halves the result so a noisy read can't carry a dodge on its own.
  - THE FLAG BASE RATE is measured, by us, from the lobbies we have already scouted (every
    champ select scouts four teammates; the running count lives in CACHE). Under MIN_SCOUTED
    players seen it makes no claim and the lobby term is zero.
  - THE PER-FLAG EFFECT (FLAG_PP) is this module's ONE modelling assumption. It is small on
    purpose and capped at LOBBY_CAP, so the lobby term can never call a dodge by itself - it
    can only sharpen a draft that is already losing.

100% read-only. It never dodges for you and never touches the client; it puts a number on
the button you were already deciding whether to press.

  python core/loldodge.py        # print every branch from the fixtures
"""
import json
import math
import os
import time

CACHE = os.path.expanduser("~/.claude/cache/lol_dodge.json")   # running flag base rate
_LOG = os.path.expanduser("~/.claude/smiteless_dodge.log")

# ---- Riot's published ranked-solo dodge penalties (one edit if they ever change) ----------
DODGE_LP = (3, 10)             # LP lost on your 1st / 2nd+ dodge of the day
DODGE_MIN = (6, 30)            # ...and the queue lockout, in minutes

REQUEUE_MIN = 2.0              # finding the next lobby after the lockout clears
OVERHEAD_MIN = 6.0             # champ select + loading + post-game, paid on every game
DEFAULT_GAME_MIN = 30.0        # a ranked game, when your own history hasn't said otherwise
MIN_EDGE_LP = 1.0              # dodging must beat playing by this much before we say so
CHIP_WHY_UNDER = 0.46          # below this the quiet chip explains why it still says PLAY

# ---- the win-probability model ------------------------------------------------------------
# Lane win rates COMPOSE, they don't average. op.gg's "Yasuo vs Malzahar 45%" is the win rate
# of the whole GAME for that mid pairing, measured with the other four lanes randomised - so it
# is already a 5-point shift against a neutral background, and a draft that loses every lane by
# 5 points is far worse than a draft that loses one. Averaging the five (what the old read did)
# threw that away and made a lost draft look like a mildly bad one. Adding them in LOG-ODDS is
# the composition that's correct for independent shifts to the same outcome.
DRAFT_K = 0.5                  # ...halved, because the lanes are NOT independent: one strong
                               # side wins several lanes for the same reason, op.gg's per-lane
                               # samples are noisy, and soloqueue is mostly the players. This
                               # can only ever make the app dodge LESS.
LANE_CLAMP = 0.30              # no single lane may read further from even than this (fraction)
MIN_LANES = 4                  # lanes with a real sample before the draft term may speak
MIN_LANE_GAMES = 20            # ...and games behind each of those lane win rates
FLAG_PP = 2.0                  # points of win probability per NET flagged player (the model)
LOBBY_CAP = 5.0                # ...hard-capped, so the lobby term can never dodge on its own
MIN_SCOUTED = 40               # players scouted before the flag base rate is allowed to speak
TEAM = 5                       # players per team, for the base-rate comparison
P_FLOOR, P_CEIL = 0.15, 0.85   # no draft read is more certain than this

# ---- your own numbers ---------------------------------------------------------------------
P0_PRIOR = 30                  # pseudo-games pulling a thin baseline toward 50%
MIN_STAKE_N = 6                # LP deltas of each kind before we trust your own +/- per game
ASSUMED_WIN, ASSUMED_LOSS = 20.0, 20.0     # the fallback, and it is labelled as one
MIN_TILT_STREAK = 3            # losses in a row that make a player a flag (matches the scout)


def log(msg):
    """One line per call. This surface only appears in champ select, so when it doesn't
    appear there has to be somewhere to look (same rule as lolqueue.log)."""
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def _logit(p):
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def _shift(pp):
    """Log-odds shift of a `pp`-point move away from an even game."""
    f = max(-LANE_CLAMP, min(LANE_CLAMP, (pp or 0.0) / 100.0))
    return _logit(0.5 + f)


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# ---------- what a game is worth to you ----------------------------------------------------

def stakes(hist):
    """(win_lp, loss_lp, n, measured) - YOUR LP per win and per loss.

    lolprofile writes a rank snapshot every time your profile builds; consecutive snapshots
    that differ by exactly one win (or one loss) price that single game. Median, not mean, so
    one promotion series or a demotion floor can't drag the number. Falls back to a labelled
    assumption until there are MIN_STAKE_N of each."""
    wins, losses = [], []
    for a, b in zip(hist or [], (hist or [])[1:]):
        if a.get("rv") is None or b.get("rv") is None:
            continue
        dw = int(b.get("w", 0) or 0) - int(a.get("w", 0) or 0)
        dl = int(b.get("l", 0) or 0) - int(a.get("l", 0) or 0)
        d = b["rv"] - a["rv"]
        if dw == 1 and dl == 0 and 0 < d <= 60:
            wins.append(d)
        elif dl == 1 and dw == 0 and 0 < -d <= 60:
            losses.append(-d)
    if len(wins) >= MIN_STAKE_N and len(losses) >= MIN_STAKE_N:
        return float(_median(wins)), float(_median(losses)), min(len(wins), len(losses)), True
    return ASSUMED_WIN, ASSUMED_LOSS, min(len(wins), len(losses)), False


def baseline(games):
    """Your win probability in a FRESH lobby, from your own ranked results, regressed toward
    50% by P0_PRIOR pseudo-games so a hot week doesn't read as a permanent edge."""
    gs = games or []
    n = len(gs)
    w = sum(1 for g in gs if g.get("win"))
    return (w + P0_PRIOR * 0.5) / (n + P0_PRIOR)


def game_minutes(games):
    """Median length of your ranked games + the overhead you pay around every one of them."""
    ds = [(g["end"] - g["start"]) / 60.0 for g in (games or [])
          if g.get("end") and g.get("start") and 300 <= (g["end"] - g["start"]) <= 3 * 3600]
    med = _median(ds)
    return (med if med else DEFAULT_GAME_MIN) + OVERHEAD_MIN


def my_streak(games):
    """Losses you are riding right now (0 if your last game was a win). games is newest-first,
    the shape lolqueue.history returns."""
    n = 0
    for g in games or []:
        if g.get("win"):
            break
        n += 1
    return n


# ---------- the draft term -----------------------------------------------------------------

def draft_edge(rows):
    """{pp, shift, lanes, losing, worst} from op.gg lane matchups, or None when the draft
    can't yet be judged. rows are lolbuild.gather_lane_matchups' (ally, role, enemy, wr, games).

    `pp` is the mean lane delta and exists only to be printed. `shift` is the number the model
    uses: the SUM of the lanes' log-odds shifts (see DRAFT_K above)."""
    deltas = [(role, ally, enemy, wr - 50.0) for ally, role, enemy, wr, g in (rows or [])
              if wr is not None and g and g >= MIN_LANE_GAMES]
    if len(deltas) < MIN_LANES:
        return None
    ds = [x[3] for x in deltas]
    worst = min(deltas, key=lambda x: x[3])
    return {"pp": sum(ds) / len(ds), "shift": sum(_shift(v) for v in ds),
            "lanes": len(deltas), "losing": sum(1 for v in ds if v <= -3),
            "worst": (worst[1], worst[2], worst[3])}


def gather(dd, allies, enemies):
    """draft_edge() over live op.gg data. None (never an exception) if op.gg is unreachable."""
    try:
        import lolbuild as lb
        return draft_edge(lb.gather_lane_matchups(dd, allies, enemies))
    except Exception as e:
        log(f"lane matchups unavailable: {type(e).__name__}: {e}")
        return None


# ---------- the lobby term -----------------------------------------------------------------

def _cache():
    try:
        c = json.load(open(CACHE, encoding="utf-8"))
        return {"seen": int(c.get("seen", 0)), "flagged": int(c.get("flagged", 0)),
                "dodges": [int(t) for t in (c.get("dodges") or [])]}
    except Exception:
        return {"seen": 0, "flagged": 0, "dodges": []}


DODGE_WINDOW = 24 * 3600       # Riot escalates the penalty within a rolling day


def _write(c):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump({**c, "ts": int(time.time())}, open(CACHE, "w"))
    except Exception:
        pass


def observe(seen, flagged):
    """Bank one champ select's worth of scouted players into the running base rate. Called
    once per lobby by the champ-select scout; this is how the enemy-side expectation gets
    measured instead of assumed."""
    c = _cache()
    c["seen"] += max(0, int(seen))
    c["flagged"] += max(0, int(flagged))
    _write(c)
    return c


def note_dodge(ts=None):
    """Record that YOU dodged. The second dodge inside a day costs 10 LP and 30 minutes
    instead of 3 and 6, which changes the answer completely - so the call has to know."""
    c = _cache()
    now = int(ts if ts is not None else time.time())
    c["dodges"] = [t for t in c.get("dodges", []) if now - t < DODGE_WINDOW][-8:] + [now]
    _write(c)
    log(f"dodge recorded — {len(c['dodges'])} in the last 24h")
    return len(c["dodges"])


def dodges_today(now=None, cache=None):
    """How many dodges you've taken in the last rolling day (0 if we've never seen one)."""
    c = cache if cache is not None else _cache()
    now = int(now if now is not None else time.time())
    return sum(1 for t in c.get("dodges", []) if now - t < DODGE_WINDOW)


def probe_penalty():
    """True if the League client is currently holding a DODGE penalty against you.

    Champ select ending without a game start means SOMEBODY dodged, and only the client knows
    whether it was you — so we ask it rather than assume. Every branch is logged, including
    the shapes we didn't expect, because this can only be exercised by actually dodging: if
    the field names ever move, the log is where that shows up. Returns None when we can't
    tell, which prices the next call as a first dodge (3 LP) — the common case."""
    try:
        import lolgame as lg, lolbuild as lb
        lc = lg._lcu()
        if not lc:
            return None
        port, hdr = lc
        for ep in ("/lol-lobby/v2/lobby/matchmaking/search-state",
                   "/lol-matchmaking/v1/search"):
            d = lb.http(f"https://127.0.0.1:{port}{ep}", headers=hdr, timeout=4, insecure=True)
            if not isinstance(d, dict):
                continue
            low = d.get("lowPriorityData") or {}
            pen = low.get("penaltyTimeRemaining") or low.get("penaltyTime") or 0
            err_pen = 0.0
            for e in (d.get("errors") or []):
                try:                                  # the client has shipped strings here
                    err_pen = max(err_pen, float((e or {}).get("penaltyTimeRemaining") or 0))
                except Exception:
                    continue
            log(f"penalty probe {ep}: penalty={pen} errors={err_pen} keys={sorted(d)[:8]}")
            if float(pen or 0) > 0 or err_pen > 0:
                return True
        return False
    except Exception as e:
        log(f"penalty probe failed: {type(e).__name__}: {e}")
        return None


def flag_rate(cache=None):
    """(rate, seen) - how often a scouted player carries a flag, across every lobby we've
    read. (None, seen) under MIN_SCOUTED: no sample, no claim, and the lobby term is dropped
    rather than guessed."""
    c = cache if cache is not None else _cache()
    seen = int(c.get("seen", 0))
    if seen < MIN_SCOUTED:
        return None, seen
    return c["flagged"] / float(seen), seen


def lobby_edge(flags, known, rate):
    """{pp, text} for a lobby holding `flags` flagged players among `known` you could read.

    The whole point: you can't see the enemy team in champ select, so a flag on your side is
    only worth the amount by which it BEATS what the other team is carrying. Expected enemy
    flags over the same denominator is known * rate; only the surplus moves the number, and it
    moves it by at most LOBBY_CAP."""
    if rate is None or not known:
        return None
    net = len(flags or []) - known * rate
    pp = max(-LOBBY_CAP, min(LOBBY_CAP, -FLAG_PP * net))
    exp = known * rate
    if flags:
        txt = (f"{', '.join(flags[:3])} — {len(flags)} flagged of {known} read, "
               f"vs {exp:.1f} expected on any team")
    else:
        txt = f"clean lobby — 0 flagged of {known} read, vs {exp:.1f} expected on any team"
    return {"pp": pp, "text": txt, "net": net, "expected": exp, "flags": list(flags or [])}


# ---------- the call -----------------------------------------------------------------------

def win_prob(p0, draft_shift=0.0, lobby_pp=0.0):
    """This lobby's win probability: your baseline in log-odds, moved by the composed draft
    shift and by the part of the lobby read that beats the base rate. Clamped - no draft read
    is more certain than P_FLOOR/P_CEIL, whatever the arithmetic says."""
    x = _logit(p0) + DRAFT_K * (draft_shift or 0.0) + _shift(lobby_pp or 0.0)
    return max(P_FLOOR, min(P_CEIL, _sigmoid(x)))


def context(games=None, hist=None):
    """The half of the sum that is about YOU, not about this lobby: baseline, LP per win and
    per loss, and how long a game takes. Reads the client history + your rank snapshots; every
    piece degrades to a labelled fallback rather than failing."""
    if games is None:
        try:
            import lolqueue as lq
            games = lq.history(80)
        except Exception as e:
            log(f"history unavailable: {type(e).__name__}: {e}")
            games = []
    if hist is None:
        try:
            import lolprofile as lp
            hist = json.load(open(lp.LP_HISTORY, encoding="utf-8"))
        except Exception:
            hist = []
    win_lp, loss_lp, sn, measured = stakes(hist)
    return {"p0": baseline(games), "win_lp": win_lp, "loss_lp": loss_lp,
            "stakes_n": sn, "stakes_measured": measured, "game_min": game_minutes(games),
            "games": len(games or []), "streak": my_streak(games)}


def call(ctx, draft=None, lobby=None, dodges_today=0):
    """The verdict. {verdict: DODGE|PLAY, p, edge, ev_play, chip, headline, reason, lines}
    verdict is None when nothing can be judged yet (no draft sample -> no opinion)."""
    i = 1 if dodges_today >= 1 else 0
    cost, pen = DODGE_LP[i], DODGE_MIN[i]
    out = {"verdict": None, "p": ctx["p0"], "p0": ctx["p0"], "cost": cost, "penalty_min": pen,
           "edge": 0.0, "ev_play": 0.0, "ev_next": 0.0, "lines": [], "reason": "",
           "headline": "", "chip": "", "losing": 0, "dodges_today": dodges_today}
    if not draft:
        out["chip"] = "LOBBY  —  reading the draft…"
        return out

    d_pp = draft["pp"]
    l_pp = (lobby or {}).get("pp") or 0.0
    p = win_prob(ctx["p0"], draft.get("shift", 0.0), l_pp)
    lw, ll = ctx["win_lp"], ctx["loss_lp"]
    ev_play = p * lw - (1 - p) * ll
    ev_next = ctx["p0"] * lw - (1 - ctx["p0"]) * ll
    tg, td = ctx["game_min"], pen + REQUEUE_MIN
    # dodge minus play, over the same hour: the lockout is paid in games you don't get to play,
    # which is why it's priced at your baseline rate rather than as a flat scold.
    edge = -cost - ev_play + ev_next * (tg - td) / tg

    out.update({"p": p, "ev_play": ev_play, "ev_next": ev_next, "edge": edge,
                "losing": draft["losing"]})
    out["verdict"] = "DODGE" if edge >= MIN_EDGE_LP else "PLAY"

    w = draft["worst"]
    out["lines"].append({"tone": "bad" if d_pp <= -1 else "good",
                         "text": f"draft {d_pp:+.1f}pp over {draft['lanes']} sampled lanes · "
                                 f"{draft['losing']} behind · worst {w[0]} vs {w[1]} ({w[2]:+.0f}%)"})
    if lobby:
        out["lines"].append({"tone": "bad" if l_pp < 0 else "good", "text": lobby["text"]})
    stake_txt = (f"your LP: +{lw:.0f} / -{ll:.0f} over {ctx['stakes_n']} priced games"
                 if ctx["stakes_measured"] else
                 f"your LP: +{lw:.0f} / -{ll:.0f} (assumed — not enough rank snapshots yet)")
    out["lines"].append({"tone": "soft", "text":
                         f"{stake_txt} · {ctx['game_min']:.0f} min a game · "
                         f"dodge #{dodges_today + 1} costs {cost} LP + {pen} min"})

    if out["verdict"] == "DODGE":
        out["headline"] = f"DODGE — worth {edge:+.1f} LP vs playing it"
        out["reason"] = (f"{draft['losing']}/{draft['lanes']} lanes behind · "
                         f"worst {w[0]} vs {w[1]} ({w[2]:+.0f}%)")
        if lobby and l_pp < 0 and lobby.get("flags"):
            out["reason"] += " · " + ", ".join(lobby["flags"][:2])
    else:
        out["headline"] = f"PLAY — dodging costs you {-edge:.1f} LP"
        out["reason"] = f"{draft['lanes']} lanes sampled, {draft['losing']} behind"
    out["chip"] = f"LOBBY {p * 100:.0f}%  ·  {ev_play:+.1f} LP  ·  {out['verdict']}"
    if out["verdict"] == "PLAY" and p < CHIP_WHY_UNDER:
        # A red 36% next to the word PLAY looks like a contradiction unless it says why -
        # and "why" is the whole point: the lobby IS bad, the dodge is just worse.
        out["chip"] += f" — dodging costs {-edge:.1f} LP more"
    return out


def read(dd, allies, enemies, flags=None, known=0, dodges_today=0, ctx=None):
    """The one entry point champ select uses: gather the draft, price it, return the call.
    Never raises - a dead op.gg or a missing history degrades the call, it doesn't break the
    panel."""
    try:
        draft = gather(dd, allies, enemies)
        ctx = ctx or context()
        flags = list(flags or [])
        if known and ctx.get("streak", 0) >= MIN_TILT_STREAK:
            # you are the fifth player on your team, and the Queue Call already knows how many
            # losses you're riding. Counting yourself keeps the comparison honest - the enemy
            # expectation covers five seats, so ours has to as well.
            flags.append(f"you {ctx['streak']}L")
            known += 1
        rate, seen = flag_rate()
        lob = lobby_edge(flags, known, rate) if known else None
        r = call(ctx, draft, lob, dodges_today)
        log(f"{r['verdict']} p={r['p']:.3f} edge={r['edge']:+.2f} "
            f"draft={(draft or {}).get('pp')} lobby={(lob or {}).get('pp')} "
            f"flags={len(flags)}/{known} base={rate} seen={seen}")
        return r
    except Exception as e:
        log(f"call failed: {type(e).__name__}: {e}")
        return None


# ---- fixtures for tools/selftest.py -------------------------------------------------------
def demo(kind):
    """(ctx, draft, lobby, dodges_today) per branch, from numbers a real account produces."""
    ctx = {"p0": 0.52, "win_lp": 22.0, "loss_lp": 18.0, "stakes_n": 24,
           "stakes_measured": True, "game_min": 34.0, "games": 80, "streak": 0}

    def rows(wrs):
        lanes = [("Yasuo", "mid", "Malzahar"), ("Aatrox", "top", "Ornn"),
                 ("Kayn", "jungle", "Sejuani"), ("Ashe", "adc", "Caitlyn"),
                 ("Nami", "support", "Thresh")]
        return [(a, r, e, wr, 140) for (a, r, e), wr in zip(lanes, wrs)]

    lost = draft_edge(rows([39.0, 45.0, 46.0, 47.0, 46.0]))    # every lane behind
    even = draft_edge(rows([47.0, 51.0, 50.0, 49.0, 51.0]))    # a normal, slightly-down draft
    good = draft_edge(rows([56.0, 53.0, 52.0, 54.0, 51.0]))    # the draft is yours
    tilted = lobby_edge(["Kayn 4L", "Ashe F-grade"], 5, 0.12)      # 2 flags vs 0.6 expected
    clean = lobby_edge([], 5, 0.12)
    if kind == "dodge":
        return ctx, lost, tilted, 0
    if kind == "play":
        return ctx, good, clean, 0
    if kind == "even":                       # a mildly bad draft is NOT worth 3 LP
        return ctx, even, clean, 0
    if kind == "second":                     # same lost draft, but it's your second dodge
        return ctx, lost, tilted, 1
    if kind == "flags-only":                 # tilted lobby, fine draft -> the cap holds
        return ctx, even, lobby_edge(["A 4L", "B 4L", "C F-grade"], 5, 0.12), 0
    if kind == "nobase":                     # base rate not earned yet -> lobby term dropped
        return ctx, lost, None, 0
    return ctx, None, None, 0                # draft not sampled yet -> no opinion


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    for k in ("dodge", "play", "even", "second", "flags-only", "nobase", "thin"):
        ctx, draft, lob, dt = demo(k)
        r = call(ctx, draft, lob, dt)
        print(f"\n{k:11} -> {r['verdict'] or '(no call)':6}  {r['chip']}")
        if r["headline"]:
            print(f"{'':14}{r['headline']}")
        for l in r["lines"]:
            print(f"{'':14}[{l['tone']:4}] {l['text']}")
    print()
