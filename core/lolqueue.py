#!/usr/bin/env python3
"""lolqueue.py - QUEUE CALL: the stop/go verdict, delivered before you press Find Match.

The single cheapest source of LP per hour in solo queue is not playing the games you were
going to lose. Everyone knows the folklore ("don't queue on tilt"); almost nobody knows
their OWN numbers, and the numbers are the only thing that makes the call obeyable.

Smiteless already computes these splits - lolprofile._patterns() slices your history by
after-a-loss, deep-sitting and time-of-day - but it renders them on the profile page,
which you open *after* the session that cost you the LP. This module answers the same
question at the one moment it can change a decision: you're sitting in the lobby with the
cursor over Find Match.

House rules (same spirit as docs/TAGS.md - a claim must carry its evidence):
  - Every line cites YOUR games: "after 2+ losses · 24% over 17 (vs 47% otherwise)".
  - A verdict needs a bucket that beats a two-proportion z-test against the games OUTSIDE
    it (see _z_worse) AND a >=GAP_STOP point gap. A cold patch that hasn't cleared that bar
    renders as "leaning cold" and does NOT change the verdict.
  - No sample, no claim. Under MIN_BASE games it says so and gets out of the way.

Sources, in order: the League client's own match history (keyless, never rate-limited),
then lolprofile's behavior ledger on disk (so the call still works with the client shut).
"""
import os, json, time, datetime
from smitei18n import t, tf

SESSION_GAP = 3 * 3600        # a >3h break starts a new sitting (matches lolprofile)
REQUEUE_GAP = 10 * 60         # "straight back in" = queued inside 10 min of the last game
MIN_BASE = 20                 # total ranked games before ANY claim is allowed
MIN_SPLIT = 6                 # games inside a bucket before the bucket may speak
GAP_STOP = 10                 # ... and sit >=10pp under the games outside it to be a verdict
GAP_GOOD = 8                  # ... or >=8pp over them to be worth a green note
DEEP_FROM = 3                 # "game N+ of a sitting" only becomes a question at game 3
RANKED_SOLO = 420

# (verdict, headline) per bucket kind - the call names the action, not the mood.
_INSTRUCTION = {"streak": ("STOP", "LOG OFF WITH THE LP"),
                "deep": ("STOP", "THE SITTING IS DONE"),
                "clock": ("STOP", "NOT YOUR WINDOW"),
                "requeue": ("WAIT", "TAKE TEN FIRST")}

_LOG = os.path.expanduser("~/.claude/smiteless_queue.log")
_LEDGER = os.path.expanduser("~/.claude/cache/riot/behavior_ledger.json")
_QUEUE_NAMES = {420: "Ranked Solo/Duo", 440: "Ranked Flex", 400: "Normal Draft",
                430: "Normal Blind", 450: "ARAM", 480: "Swiftplay", 490: "Quickplay",
                700: "Clash", 1700: "Arena", 1900: "URF"}
_POSITIONS = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID", "BOTTOM": "ADC",
              "UTILITY": "SUPPORT"}


def log(msg):
    """One diagnostic line per queue-call step - this surface only ever appears in the
    lobby, so when it doesn't appear there has to be somewhere to look."""
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


# ---------- history ----------

def _from_client(limit):
    """Your recent ranked-solo results straight off the League client - ONE request, no key,
    no Riot round-trip (see lollocal for why the LCU beats Match-V5 for your own history).
    The list endpoint already carries your own participant row, so no per-game fetch."""
    import lolgame as lg, lolbuild as lb
    lc = lg._lcu()
    if not lc:
        return []
    port, hdr = lc
    want = min(190, max(limit * 2, limit + 20))  # headroom: ARAM/remakes get filtered out
    d = lb.http(f"https://127.0.0.1:{port}/lol-match-history/v1/products/lol/"
                f"current-summoner/matches?begIndex=0&endIndex={want}",
                headers=hdr, timeout=10, insecure=True)
    games = ((d or {}).get("games") or {}).get("games") or []
    out = []
    for g in games:
        if g.get("queueId") != RANKED_SOLO or g.get("gameMode") not in ("CLASSIC", None):
            continue
        dur = int(g.get("gameDuration") or 0)
        if dur < 300:                            # sub-5-minute = remake, not a game you played
            continue
        parts = g.get("participants") or []
        st = (parts[0].get("stats") or {}) if parts else {}
        if "win" not in st:
            continue
        ts = int(g.get("gameCreation") or 0) // 1000
        if not ts:
            continue
        out.append({"start": ts, "end": ts + dur, "win": bool(st["win"])})
    out.sort(key=lambda g: -g["start"])
    return out[:limit]


def _from_ledger(limit):
    """Fallback: lolprofile's behavior ledger (written every time your profile builds).
    It carries {ts, win} per game, which is all the call needs."""
    try:
        led = json.load(open(_LEDGER, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for g in (led.get("games") or []):
        if g.get("win") is None or not g.get("ts"):
            continue
        ts = int(g["ts"]) // 1000
        out.append({"start": ts, "end": ts + 1800, "win": bool(g["win"])})   # dur unknown
    out.sort(key=lambda g: -g["start"])
    return out[:limit]


def history(limit=80):
    """[{start, end, win}] most-recent-first, from the best source that answers."""
    try:
        gs = _from_client(limit)
    except Exception as e:
        gs = []
        log(f"client history failed: {type(e).__name__}: {e}")
    if gs:
        log(f"history: {len(gs)} ranked games from the client")
        return gs
    gs = _from_ledger(limit)
    log(f"history: {len(gs)} ranked games from the behavior ledger (client had none)")
    return gs


# ---------- the call ----------

Z_PROVEN = 1.28               # one-sided ~90%: the bar a bucket clears to become a VERDICT


def _z_worse(w_in, n_in, w_out, n_out):
    """Two-proportion z for 'this bucket is worse than every OTHER game you played'.

    The comparison has to be bucket-vs-COMPLEMENT, not bucket-vs-overall: the bucket is
    part of the overall rate, so measuring against it dilutes exactly the effect you're
    testing for. z >= Z_PROVEN (one-sided ~90%) promotes a lean to a verdict - a lower bar
    than a research finding would use, on purpose: a false STOP costs you a coffee break,
    a false GO costs the game."""
    if n_in <= 0 or n_out <= 0:
        return 0.0
    p1, p2 = w_in / n_in, w_out / n_out
    pool = (w_in + w_out) / (n_in + n_out)
    se = (pool * (1 - pool) * (1.0 / n_in + 1.0 / n_out)) ** 0.5
    return 0.0 if se <= 0 else (p2 - p1) / se


def _hour_bucket(ts):
    h = datetime.datetime.fromtimestamp(ts).hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 23:
        return "evening"
    return "late night"


def _annotate(gs):
    """Walk oldest->newest and stamp each game with the state you were in when you queued
    it: session index, how many losses you were riding, and the break before it."""
    out = []
    idx, run_loss, prev = 0, 0, None
    for g in sorted(gs, key=lambda x: x["start"]):
        gap = (g["start"] - prev["end"]) if prev else None
        if prev is None or gap is None or gap > SESSION_GAP:
            idx, run_loss, gap = 1, 0, None      # new sitting: no "before" state carries over
        else:
            idx += 1
        out.append({**g, "idx": idx, "prev_losses": run_loss, "gap": gap,
                    "clock": _hour_bucket(g["start"])})
        run_loss = 0 if g["win"] else run_loss + 1
        prev = g
    return out


def _state(ann, now):
    """The state you're in RIGHT NOW - i.e. what the next game's stamp would be."""
    if not ann:
        return {"games": 0, "w": 0, "l": 0, "streak": 0, "since": None,
                "idx": 1, "prev_losses": 0, "clock": _hour_bucket(now)}
    last = ann[-1]
    since = max(0, int(now - last["end"]))
    if since > SESSION_GAP:                      # the sitting is over; you're starting fresh
        return {"games": 0, "w": 0, "l": 0, "streak": 0, "since": since,
                "idx": 1, "prev_losses": 0, "clock": _hour_bucket(now)}
    sess = []
    for g in reversed(ann):
        if sess and (sess[-1]["start"] - g["end"]) > SESSION_GAP:
            break
        sess.append(g)
    w = sum(1 for g in sess if g["win"])
    # sess is newest-first. Scope the streak to THIS sitting so it matches how _annotate
    # stamped every historical game - a break resets the "before" state on both sides.
    streak = 0
    for g in sess:
        if g["win"] != last["win"]:
            break
        streak += 1
    run_loss = 0 if last["win"] else streak      # losses you'd be riding into the next game
    return {"games": len(sess), "w": w, "l": len(sess) - w,
            "streak": streak if ann[-1]["win"] else -streak, "since": since,
            "idx": len(sess) + 1, "prev_losses": run_loss,
            "clock": _hour_bucket(now)}


def _bucket(ann, pred, label):
    """One slice of your history plus the games outside it, so the two can be compared."""
    sub = [g for g in ann if pred(g)]
    rest = [g for g in ann if not pred(g)]
    if len(sub) < MIN_SPLIT or len(rest) < MIN_SPLIT:
        return None
    w, wo = sum(1 for g in sub if g["win"]), sum(1 for g in rest if g["win"])
    return {"label": label, "n": len(sub), "w": w, "wr": round(w / len(sub) * 100),
            "rest_n": len(rest), "rest_wr": round(wo / len(rest) * 100),
            "z": _z_worse(w, len(sub), wo, len(rest))}


def call(games, now=None):
    """The verdict for the game you're about to queue.

    {verdict: GO|LAST ONE|WAIT|STOP, headline, sub, lines: [{text, tone}], session, n, base}
    tone is 'bad' | 'good' | 'soft' (an honest lean that hasn't earned a verdict)."""
    now = int(now if now is not None else time.time())
    ann = _annotate(games or [])
    st = _state(ann, now)
    n = len(ann)
    base_w = sum(1 for g in ann if g["win"])
    base = round(base_w / n * 100) if n else 0
    out = {"verdict": "GO", "headline": t("QUEUE IT"), "sub": "", "lines": [],
           "session": st, "n": n, "base": base}

    if n < MIN_BASE:
        out["sub"] = tf(
            "no read yet — {count} of {minimum} ranked games logged. "
            "Smiteless only calls it off your own history.",
            count=n, minimum=MIN_BASE)
        return out

    # The buckets the NEXT game falls into. Each is a slice of your own history taken with
    # the same state you're sitting in now.
    cands = []
    if st["prev_losses"] >= 2:
        # always sampled (and labelled) at 2+, not at today's exact streak: a "5+ losses"
        # slice of your own history is a handful of games and can't prove anything.
        cands.append((_bucket(ann, lambda g: g["prev_losses"] >= 2,
                              t("after 2+ losses")), "streak"))
    if st["idx"] >= DEEP_FROM:
        cands.append((_bucket(ann, lambda g, k=st["idx"]: g["idx"] >= k,
                              tf("game {index}+ of a sitting", index=st["idx"])), "deep"))
    if st["since"] is not None and st["games"] and st["since"] < REQUEUE_GAP:
        cands.append((_bucket(ann, lambda g: g["gap"] is not None and g["gap"] < REQUEUE_GAP,
                              t("straight back in (<10 min)")), "requeue"))
    cands.append((_bucket(ann, lambda g, c=st["clock"]: g["clock"] == c,
                          t(st["clock"])), "clock"))
    cands = [(b, k) for b, k in cands if b]

    def _proven_bad(b):
        return bool(b) and b["z"] >= Z_PROVEN and (b["rest_wr"] - b["wr"]) >= GAP_STOP

    stop = [(b, k) for b, k in cands if _proven_bad(b)]

    # One game away: a loss now would put you in a proven-bad cold-streak bucket, or the
    # game AFTER this one crosses into a proven-bad deep-sitting bucket.
    edge = []
    if st["prev_losses"] == 1:
        b = _bucket(ann, lambda g: g["prev_losses"] >= 2, t("after 2+ losses"))
        if _proven_bad(b):
            edge.append((b, t("a loss here puts you in it")))
    nxt = st["idx"] + 1
    if nxt >= DEEP_FROM:
        b = _bucket(ann, lambda g, k=nxt: g["idx"] >= k,
                    tf("game {index}+ of a sitting", index=nxt))
        if _proven_bad(b) and not any(k == "deep" for _b, k in stop):
            edge.append((b, t("the game after this one is in it")))

    for b, _k in sorted(cands, key=lambda x: -(x[0]["rest_wr"] - x[0]["wr"])):
        gap = b["rest_wr"] - b["wr"]
        if _proven_bad(b):
            tone = "bad"
        elif gap >= GAP_STOP:
            tone = "soft"
        elif -gap >= GAP_GOOD:
            tone = "good"
        else:
            continue
        lead = t("leaning cold: ") if tone == "soft" else ""
        out["lines"].append({
            "text": tf("{lead}{label} · {winrate}% over {games} "
                       "(vs {other_winrate}% otherwise)",
                       lead=lead, label=b["label"], winrate=b["wr"], games=b["n"],
                       other_winrate=b["rest_wr"]),
            "tone": tone})
    out["lines"] = out["lines"][:3]

    if stop:
        # A 'stop' isn't always the same instruction: a bad hour means come back later, a
        # 90-second requeue just means take ten. Rank so the strongest action wins, and let
        # the headline BE the instruction rather than a generic scold.
        worst, kind = max(stop, key=lambda x: (x[1] != "requeue",
                                               x[0]["rest_wr"] - x[0]["wr"]))
        out["verdict"], out["headline"] = _INSTRUCTION[kind]
        out["headline"] = t(out["headline"])
        out["sub"] = tf(
            "{label}, you win {winrate}% — {gap}pp under the rest of your games, "
            "over {games} of them.",
            label=worst["label"], winrate=worst["wr"],
            gap=worst["rest_wr"] - worst["wr"], games=worst["n"])
    elif edge:
        b, why = edge[0]
        out["verdict"] = "LAST ONE"
        out["headline"] = t("ONE MORE, THEN OUT")
        out["sub"] = tf("{label} you're {winrate}% over {games} — {why}.",
                        label=b["label"], winrate=b["wr"], games=b["n"], why=why)
    else:
        out["headline"] = t("QUEUE IT")
        soft = next((l for l in out["lines"] if l["tone"] == "soft"), None)
        good = next((l for l in out["lines"] if l["tone"] == "good"), None)
        if soft:
            out["sub"] = t("nothing your history can prove against this one — but watch it.")
        elif good:
            out["sub"] = t("this is one of your good windows.")
        else:
            out["sub"] = tf("nothing in your last {games} games argues against this one.",
                            games=n)
    return out


def session_line(st):
    """'SESSION - 4 games - 1W-3L - 2h10m in', or '' before the first game of a sitting."""
    if not st or not st.get("games"):
        return t("first game of the sitting")
    bits = [tf("{games} game", games=st["games"]) if st["games"] == 1
            else tf("{games} games", games=st["games"]),
            tf("{wins}W-{losses}L", wins=st["w"], losses=st["l"])]
    s = st.get("streak") or 0
    if abs(s) >= 2:
        bits.append(tf("{count}{result} streak", count=abs(s),
                       result=t("W" if s > 0 else "L")))
    if st.get("since") is not None:
        m = st["since"] // 60
        bits.append(tf("last game {minutes}m ago", minutes=m) if m < 90
                    else tf("last game {hours}h ago", hours=m // 60))
    return "  ·  ".join(bits)


def _coach_queue_state(phase=None):
    """Cheap local queue state, kept here so the coach does not import smitecard UI locals."""
    import lolbuild as lb
    import lolgame as lg
    if phase is None:
        try:
            import phasecheck
            phase = phasecheck.phase()
        except Exception:
            phase = ""
    out = {"phase": phase, "queue": "", "roles": [], "elapsed_seconds": None,
           "estimated_seconds": None, "ready_check_seconds": None}
    lc = lg._lcu()
    if not lc:
        return out
    port, hdr = lc

    def get(path):
        try:
            return lb.http(f"https://127.0.0.1:{port}{path}", headers=hdr,
                           timeout=1, insecure=True)
        except Exception:
            return None

    lobby = get("/lol-lobby/v2/lobby") or {}
    config = lobby.get("gameConfig") or {} if isinstance(lobby, dict) else {}
    out["queue"] = _QUEUE_NAMES.get(config.get("queueId"), "")
    member = lobby.get("localMember") or {} if isinstance(lobby, dict) else {}
    for role in (member.get("firstPositionPreference"), member.get("secondPositionPreference")):
        if role and role != "UNSELECTED":
            out["roles"].append(_POSITIONS.get(role, role))
    search = get("/lol-matchmaking/v1/search")
    if isinstance(search, dict):
        out["elapsed_seconds"] = search.get("timeInQueue")
        out["estimated_seconds"] = search.get("estimatedQueueTime")
    if phase == "ReadyCheck":
        ready = get("/lol-matchmaking/v1/ready-check")
        if isinstance(ready, dict):
            out["ready_check_seconds"] = ready.get("timer")
    return out


def coach_snapshot(games=None, now=None, state=None, phase=None):
    """Cached-first Queue Call facts for the coach, without a synchronous history refresh."""
    games = _from_ledger(80) if games is None else list(games)
    verdict = call(games, now=now)
    return {
        "state": _coach_queue_state(phase=phase) if state is None else state,
        "verdict": verdict.get("verdict"),
        "headline": verdict.get("headline"),
        "summary": verdict.get("sub"),
        "evidence": [row.get("text") for row in (verdict.get("lines") or [])[:3]],
        "sample_games": verdict.get("n", 0),
        "session": verdict.get("session") or {},
    }


def demo(kind="stop", now=None):
    """Synthetic history that provably lands on a given verdict — the STOP state can be
    weeks away in real life, so every rendering path stays inspectable on demand."""
    now = int(now if now is not None else time.time())
    fresh, stale = (True, True, False), (True, False, False)   # ~67% vs ~33%, a plausible split
    h = []
    if kind == "wait":                           # only the instant-requeue bucket is bad
        for s in range(20):
            st = now - 86400 * 30 + s * 86400
            h.append({"start": st, "end": st + 1800, "win": fresh[s % 3]})
            h.append({"start": st + 1980, "end": st + 3780, "win": stale[s % 3]})
        h.append({"start": now - 2000, "end": now - 200, "win": True})
        return h
    for s in range(18):                          # sittings of 4: the back half runs cold
        st = now - 86400 * 40 + s * 86400
        for j in range(4):
            w = (fresh if j < 2 else stale)[(s + j) % 3]
            h.append({"start": st + j * 2400, "end": st + j * 2400 + 1800, "win": w})
    if kind == "last":
        h.append({"start": now - 2400, "end": now - 600, "win": True})
    else:
        h.append({"start": now - 4600, "end": now - 2800, "win": False})
        h.append({"start": now - 2400, "end": now - 600, "win": False})
    return h


if __name__ == "__main__":                       # python core/lolqueue.py [test]
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    gs = history()
    r = call(gs)
    print(f"\n  {r['verdict']}  -  {r['headline']}")
    print(f"  {r['sub']}")
    print(f"  {session_line(r['session'])}")
    for l in r["lines"]:
        print(f"    [{l['tone']:4}] {l['text']}")
    print(tf("  basis: {games} ranked games, baseline {baseline}%\n",
             games=r["n"], baseline=r["base"]))
