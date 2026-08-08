#!/usr/bin/env python3
"""lolfit.py - PERSONAL FIT: what the champion recommender should know about YOU.

Two problems, one answer.

1. "Don't recommend champions I consistently do badly on." Since the mastery gate came off in
   v0.9.57 the recommender ranks on merit alone — it will happily hand you the strongest pick
   into the draft on a champion you have lost your last four games on. It has never once looked
   at your results.

2. "I get bored of my champs." This is not a small problem dressed up as one: boredom is what
   makes you first-time something in ranked, and a sub-12k-mastery pick wins about 44%. The
   usual advice ("just one-trick") loses to human nature. The useful move is not novelty, it's
   ROTATION: surface the champion you are already good at and haven't touched in fifteen games.
   That scratches the same itch and costs no LP.

So this module answers, per champion: is this a proven LOSER for me, a proven WINNER, and how
long since I played it. The recommender then vetoes the first, promotes the last.

HOUSE RULE (docs/TAGS.md): a claim carries its evidence, and thin samples make no claim. Losing
three in a row is not proof and will not veto anything.

ONE BRAIN (v0.9.71): the veto is no longer this module's own arithmetic. It IS core/lolpool's
`bench` state — the same read the profile page draws and prices in LP — so the page that tells
you to bench a champion and the recommender that refuses to suggest it can never disagree again.
That also upgrades the veto in two ways worth knowing about: it is measured against YOUR OWN
baseline rather than a flat 48% (a 46% champion is not a leak for a player who wins 43% of
everything else, it is their second-best pick), and it is corrected for the fact that every
champion in your pool is being tested at once. Your most-played champion can no longer be
vetoed at all — lolpool reads a main on a bad run as variance, which is what it usually is.
"""
import json
import os
import time

import lolprofile as lp
from smitei18n import t, tf

CACHE = os.path.expanduser("~/.claude/cache/lol_fit.json")
TTL = 6 * 3600             # rebuild the season read at most this often (it's ~60 match fetches)

PERF_MIN = 3               # games before your average PERFORMANCE on a champ may speak
PERF_GAP = 12              # ...and it must sit this far under your own overall average
FRESH_AFTER = 10           # not played in this many recent games = "fresh"
FRESH_RATING = 0.30        # ...and it still has to be a champion you're actually decent on
FRESH_MIN = 3              # ...on a real sample. One good game is a coin flip, not a champion
                           # you're good at, and promoting it would break this module's own rule


def _norm(name):
    return "".join(c for c in (name or "").lower() if c.isalnum())


def _read_cache():
    try:
        c = json.load(open(CACHE, encoding="utf-8"))
        return c if isinstance(c, dict) else None
    except Exception:
        return None


def _write_cache(rec):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = f"{CACHE}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, CACHE)
    except Exception:
        pass


def _merge(into, champs):
    """Fold a [{champ,g,w,avg}] list into {normname: {g,w,avg_sum,avg_n}}. Sources overlap
    (the season read contains the recent games too), so the DEEPER count wins rather than
    being added — double-counting your own games would fake up a sample that doesn't exist."""
    for c in champs or []:
        k = _norm(c.get("champ"))
        if not k:
            continue
        g, w = int(c.get("g") or 0), int(c.get("w") or 0)
        cur = into.setdefault(k, {"g": 0, "w": 0, "avg": None})
        if g > cur["g"]:
            cur["g"], cur["w"] = g, w
        if c.get("avg") is not None:
            cur["avg"] = c["avg"] if cur["avg"] is None else max(cur["avg"], c["avg"])
    return into


def build(dd=None, key=None, force=False):
    """{"baseline": avg_score, "champs": {norm: {g,w,avg}}, "recent": [norm, ...newest first]}.
    Cheap by default: the cached profile on disk needs no network at all. The deeper season read
    only runs when a key is available and the cache is stale."""
    cached = _read_cache()
    if cached and not force and (time.time() - cached.get("ts", 0)) < TTL:
        return cached
    # Start from what we already knew. A rebuild WITHOUT a key can only see the ~20 games in
    # the cached profile; discarding the deeper season read every time the TTL lapses would
    # quietly shrink your record from 22 champions to 6 and take the vetoes with it. _merge
    # keeps the deeper count per champion, so this can only ever grow.
    out = {"ts": int(time.time()), "baseline": None,
           "champs": dict((cached or {}).get("champs") or {}), "recent": []}
    prof = None
    try:
        rid = lp.current_riot_id()
        prof = lp._load_profile(rid) if rid else None
    except Exception:
        prof = None
    if prof:
        out["baseline"] = prof.get("avg_score")
        _merge(out["champs"], prof.get("champs"))
        # newest-first list of the champions in your recent games — this is the boredom clock
        out["recent"] = [_norm(g.get("champ")) for g in (prof.get("games") or [])
                         if g.get("champ")]
    if key and prof and prof.get("puuid"):
        try:
            _merge(out["champs"], lp.season_champs(dd, prof["puuid"], key))
        except Exception:
            pass
    if out["champs"]:
        _write_cache(out)
    return out


def _stats(rec, name):
    c = (rec.get("champs") or {}).get(_norm(name))
    if not c or not c.get("g"):
        return None
    return c


def games_since(rec, name):
    """How many of your recent games ago you last played this champion, or None if it isn't in
    the recent window at all (which counts as maximally fresh)."""
    k = _norm(name)
    for i, c in enumerate(rec.get("recent") or []):
        if c == k:
            return i
    return None


def pool_board(rec):
    """THE POOL board for this record (core/lolpool), memoized on the record itself. This is the
    shared read behind the veto — one brain, so the profile page and the recommender agree."""
    if rec.get("_pool") is None:
        try:
            import lolpool as _lpl
            rec["_pool"] = _lpl.board(rec.get("champs") or {})
        except Exception:
            rec["_pool"] = False
    return rec["_pool"] or None


def verdict(rec, name):
    """(kind, reason) for one champion, or (None, None) when your history has nothing to say.

      'veto'  - proven loser for you (core/lolpool's 'bench'); the recommender drops it
      'cold'  - you play it measurably below your own standard; demoted, not dropped
      'fresh' - you're good on it and haven't touched it in a while; promoted (the boredom fix)
    """
    c = _stats(rec, name)
    if not c:
        return None, None
    g, w, avg = c["g"], c["w"], c.get("avg")
    wr = round(w / g * 100)
    try:
        import lolpool as _lpl
        st, why = _lpl.champ_note(pool_board(rec), name)
        if st == "bench":
            return "veto", why
    except Exception:
        pass
    base = rec.get("baseline")
    if avg is not None and base and g >= PERF_MIN and avg <= base - PERF_GAP:
        return "cold", tf("you average {average} on it vs {baseline} overall, over {games} games",
                          average=avg, baseline=base, games=g)
    since = games_since(rec, name)
    rating = lp._champ_rating(g, w, avg)
    if g >= FRESH_MIN and rating >= FRESH_RATING and (since is None or since >= FRESH_AFTER):
        ago = (t("not in your recent games") if since is None else
               tf("{games} games ago", games=since))
        average = "" if avg is None else tf(", avg {average}", average=avg)
        return "fresh", tf("{wins}W-{losses}L ({winrate}%){average} — last played {ago}",
                           wins=w, losses=g - w, winrate=wr, average=average, ago=ago)
    return None, None


# Rank adjustments applied to the recommender's merit score. Small on purpose: this nudges the
# order, it does not replace "what actually beats this draft".
ADJUST = {"fresh": 6.0, "cold": -8.0}


def apply(rec, dd, cids):
    """Filter + reorder a recommendation list by your own results. Returns
    (ordered_cids, {cid: (kind, reason)}) — the notes are what the UI shows so a promotion or a
    drop is never mysterious."""
    id2name = (dd or {}).get("id2name") or {}
    notes, scored = {}, []
    for i, cid in enumerate(cids or []):
        kind, why = verdict(rec, id2name.get(cid, ""))
        if kind:
            notes[cid] = (kind, why)
        if kind == "veto":
            continue
        scored.append((i - ADJUST.get(kind, 0.0), cid))   # lower = better (i is merit order)
    scored.sort()
    return [cid for _s, cid in scored], notes


if __name__ == "__main__":                # python lolfit.py — what it thinks of your champs
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = build(force="--force" in sys.argv)
    print(f"baseline avg score: {r.get('baseline')}   ({len(r.get('champs') or {})} champs known)")
    for k, c in sorted((r.get("champs") or {}).items(), key=lambda kv: -kv[1]["g"]):
        kind, why = verdict(r, k)
        print(f"  {k:14} {c['w']}W-{c['g'] - c['w']}L avg={str(c.get('avg')):>4}  "
              f"{(kind or '-'):6} {why or ''}")
