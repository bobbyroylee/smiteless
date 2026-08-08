#!/usr/bin/env python3
"""tagcheck.py - regression guard for the player-tag spec (docs/TAGS.md).

The canonical failure this guards against (v0.9.29 and earlier): a Morgana one-trick on a
Morgana win streak locked BRAND in the user's game, went 1/8, and the scout tagged him
`SMURF READ · new acct, stomping` — account-wide evidence rendered as a this-game judgment.

Runs two layers:
  1. STATIC fixtures (always) — the Morgana/Brand shape plus smurf/heater/no-level edges,
     asserting exact spec behavior. This is the guard that keeps the bug from returning.
  2. LIVE fixture (when the real match cache holds it) — reconstructs the actual
     NA1_5604429522 lobby row from cached match data and re-runs the classifier on it.

  python tools/tagcheck.py        # prints every fixture's tags; exit 1 on any violation
"""
import sys, os, json, glob

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import lolload as llo
import smitei18n

# These historical fixtures assert the exact PT-BR copy recorded in docs/TAGS.md. Keep
# them independent from whichever UI locale happens to be saved on the build machine.
smitei18n.set_lang("pt_BR")

FAILS = []


def _run(name, row, ally, must=(), must_not=()):
    tags = llo._profile_tags(row, ally)
    texts = [t for t, _tone in tags]
    joined = " | ".join(texts) or "(no tags)"
    print(f"\n{name}\n  -> {joined}")
    for frag in must:
        if not any(frag.lower() in t.lower() for t in texts):
            FAILS.append(f"{name}: missing expected tag fragment '{frag}'")
    for frag in must_not:
        if any(frag.lower() in t.lower() for t in texts):
            FAILS.append(f"{name}: forbidden tag fragment '{frag}' rendered")
    return texts


def _old_smurf_fired(row):
    """v0.9.29's trigger, kept here as the before/after comparison line."""
    rk = row.get("rank_full") or {}
    sg = int(rk.get("w", 0) or 0) + int(rk.get("l", 0) or 0)
    n, w = row.get("n", 0), row.get("w", 0)
    return n >= 8 and w / n >= 0.65 and 0 < sg < 80


def static_fixtures():
    # 1) THE Morgana/Brand case: 9W-1L recents almost all on Morgana, locked Brand today.
    morg_brand = {
        "champ": "Brand", "role": "SUP", "main_pos": "SUP", "scouted": True,
        "n": 10, "w": 9, "form": [True] * 9 + [False],
        "recent": [("Morgana", True, "UTILITY")] * 9 + [("Lux", False, "UTILITY")],
        "cg": 0, "cw": 0, "pts": 2400, "level": None,
        "rank_full": {"tier": "GOLD", "div": "IV", "lp": 40, "w": 22, "l": 18},
        "dpg": 4.1, "perf": 61, "kdar": 2.8,
    }
    if _old_smurf_fired(morg_brand):
        print("v0.9.29 would have said: SMURF READ · new acct, stomping   <- the lie")
    _run("STATIC Morgana OTP locks Brand (enemy)", morg_brand, ally=False,
         must=("fora do campeão", "com Morgana", "primeira vez com Brand"),
         must_not=("smurf",))

    # 2) A genuinely smurf-shaped account: fresh level, stomping, high perf.
    smurf = {
        "champ": "Zed", "role": "MID", "main_pos": "MID", "scouted": True,
        "n": 10, "w": 9, "form": [True] * 9 + [False],
        "recent": [("Zed", True, "MIDDLE")] * 6 + [("Talon", True, "MIDDLE")] * 3
                  + [("Zed", False, "MIDDLE")],
        "cg": 7, "cw": 7, "pts": 18000, "level": 38,
        "rank_full": {"tier": "GOLD", "div": "II", "lp": 75, "w": 14, "l": 4},
        "dpg": 2.2, "perf": 88, "kdar": 5.1,
    }
    _run("STATIC real smurf shape (enemy)", smurf, ally=False,
         must=("smurf? ·", "nível 38"))

    # 3) Same stomping account but NO level data -> smurf may not fire (no evidence, no tag).
    no_level = dict(smurf, level=None)
    _run("STATIC same shape, level unknown (enemy)", no_level, ally=False,
         must_not=("smurf",))

    # 4) Old account (lvl 400) on a streak -> heater, never smurf/new-account.
    vet = dict(smurf, level=412, pts=310_000)
    _run("STATIC veteran on a heater (enemy)", vet, ally=False,
         must=("em sequência", "OTP"), must_not=("smurf", "conta nova"))

    # 5) Loss skid -> tilt read, tone good-for-you on an enemy.
    tilted = {
        "champ": "Jinx", "role": "BOT", "main_pos": "BOT", "scouted": True,
        "n": 10, "w": 2, "form": [False] * 4 + [True, False, True, False, False, False],
        "recent": [("Jinx", False, "BOTTOM")] * 4 + [("Jinx", True, "BOTTOM")] * 6,
        "cg": 10, "cw": 2, "pts": 90000, "level": 250,
        "rank_full": {"tier": "GOLD", "div": "III", "lp": 10, "w": 60, "l": 75},
        "dpg": 7.2, "perf": 44, "kdar": 1.6,
    }
    _run("STATIC 4L skid (enemy)", tilted, ally=False,
         must=("4D seguidas", "frio com Jinx", "morre muito"))


def live_fixture():
    """Reconstruct the real NA1_5604429522 Brand row from the cached matches, if present."""
    d = os.path.expanduser("~/.claude/cache/riot/match")
    target = os.path.join(d, "NA1_5604429522.json")
    if not os.path.exists(target):
        print("\nLIVE fixture: NA1_5604429522 not in the match cache here - skipped.")
        return
    m = json.load(open(target))
    puuid = next((p for p, rec in m.items() if isinstance(rec, list) and len(rec) >= 5
                  and rec[1] == "Brand" and rec[3] >= 7), None)
    if not puuid:
        print("\nLIVE fixture: Brand row not found in NA1_5604429522 - skipped.")
        return
    hist = []      # his OTHER cached games = the recents the scout saw before that lobby
    for fp in glob.glob(os.path.join(d, "*.json")):
        if os.path.basename(fp) == "NA1_5604429522.json":
            continue
        try:
            mm = json.load(open(fp))
        except Exception:
            continue
        rec = mm.get(puuid)
        if isinstance(rec, list) and len(rec) >= 11:
            hist.append((os.path.basename(fp)[:-5], rec))
    hist.sort(key=lambda x: x[0], reverse=True)     # match-id order ~= recency
    hist = hist[:10]
    recent = [(r[1], bool(r[0]), r[10]) for _mid, r in hist]
    n = len(recent)
    w = sum(1 for _c, win, _p in recent if win)
    row = {
        "champ": "Brand", "role": "SUP", "main_pos": llo._main_pos(recent),
        "scouted": True, "n": n, "w": w, "form": [win for _c, win, _p in recent],
        "recent": recent, "cg": sum(1 for c, _w2, _p in recent if c == "Brand"),
        "cw": sum(1 for c, w2, _p in recent if c == "Brand" and w2),
        "pts": 2400,      # sub-6k per the lobby that night; mastery cache TTL'd out since
        "level": None, "rank_full": None, "dpg": None, "perf": None,
    }
    print(f"\nLIVE reconstruction: {n} cached recents, {w}W, dist="
          f"{ {c: [x[0] for x in recent].count(c) for c in set(x[0] for x in recent)} }")
    _run("LIVE NA1_5604429522 Brand row (enemy)", row, ally=False,
         must=("fora do campeão",), must_not=("smurf",))


def main():
    print("TAG SPEC CHECK (docs/TAGS.md)")
    print("=" * 60)
    static_fixtures()
    live_fixture()
    print("\n" + "=" * 60)
    if FAILS:
        for f in FAILS:
            print("FAIL:", f)
        sys.exit(1)
    print("all tag fixtures conform to the spec")
    sys.exit(0)


if __name__ == "__main__":
    main()
