#!/usr/bin/env python3
"""lolrunes.py - ADAPTIVE RUNES: pick the rune page that fits THIS lobby, not the average one.

Auto-import has always taken op.gg's most-played page and stopped thinking. But a champion's
best keystone depends on what it's fighting. Talon is the canonical example, and it's right
there in op.gg's own numbers this patch:

    Talon mid   Electrocute  46.4% over 521 games   <- most played, always imported
                Conqueror    51.8% over 257 games   <- exists, never chosen

Into five squishies you want the burst. Into a wall of tanks, front-loaded damage does nothing
and you want the sustained page. Same champion, different game.

WHAT'S EVIDENCE AND WHAT'S A MODEL, stated plainly:
  - The PAGES are op.gg's: real pages real players run on that champion this patch, with their
    real sample and win rate. We never invent a page, and we never pick one nobody plays.
  - The TAGS are Riot's own (Data Dragon `id2tags`) - Tank / Fighter / Mage / Marksman /
    Assassin / Support.
  - The MAPPING from "enemy comp" to "keystone class" is a MODELLING ASSUMPTION (below). It is
    deliberately coarse and only fires on an unambiguous comp; anything in between keeps the
    most-played page, because a coin-flip read is worse than the default.
"""

from smitei18n import tf

# Keystones whose damage scales with how long a fight lasts, or with the target's HP — the ones
# that keep working into tanks and bruisers.
SUSTAINED = {"Conqueror", "Press the Attack", "Grasp of the Undying", "Lethal Tempo"}
# Keystones that are front-loaded: they delete a squishy and bounce off a tank.
BURST = {"Electrocute", "Dark Harvest", "First Strike", "Hail of Blades"}
# Everything else (Aery, Comet, Phase Rush, Fleet Footwork, Aftershock, Guardian, Glacial
# Augment, Unsealed Spellbook...) is deliberately unclassified. They're picked for poke, safety
# or utility rather than for what they're hitting, so this module has no opinion on them.

MIN_PLAY = 120         # a page needs this many games before we'll switch TO it
MIN_TANKS = 2          # this many Tank-tagged enemies = a tanky comp
MIN_FRONTLINE = 3      # ...or this many Tank+Fighter between them
MAX_TANKS_SQUISH = 0   # a squishy comp has no tanks at all
MIN_SQUISH = 4         # ...and at least this many squishy bodies


def comp_read(dd, enemy_ids):
    """(verdict, why) for the enemy team: 'tank', 'squish' or (None, None) when it's mixed.
    Needs at least three locked enemies — calling a comp off two picks is guessing."""
    ids = [c for c in (enemy_ids or []) if c]
    if len(ids) < 3:
        return None, None
    tags = (dd or {}).get("id2tags") or {}
    names = (dd or {}).get("id2name") or {}
    tanks, fighters, squishy = [], [], []
    for c in ids:
        t = tags.get(c) or []
        if "Tank" in t:
            tanks.append(names.get(c, c))
        elif "Fighter" in t:
            fighters.append(names.get(c, c))
        else:
            squishy.append(names.get(c, c))
    if len(tanks) >= MIN_TANKS or (len(tanks) + len(fighters)) >= MIN_FRONTLINE:
        front = tanks + fighters
        return "tank", tf("{count} frontline locked ({names})",
                          count=len(front), names=", ".join(front[:3]))
    if len(tanks) <= MAX_TANKS_SQUISH and len(squishy) >= MIN_SQUISH:
        return "squish", tf("no frontline — {count} squishy ({names})",
                            count=len(squishy), names=", ".join(squishy[:3]))
    return None, None


def choose(dd, options, enemy_ids):
    """(index, reason) - which of `options` (op.gg pages, index 0 = most played) to run.
    Returns (0, None) whenever there's no clear reason to deviate, which is most of the time."""
    opts = list(options or [])
    if len(opts) < 2:
        return 0, None
    verdict, why = comp_read(dd, enemy_ids)
    if not verdict:
        return 0, None
    want = SUSTAINED if verdict == "tank" else BURST
    if (opts[0].get("keystone") or "") in want:
        return 0, None                       # the default already suits the comp — leave it
    best = None
    for i, o in enumerate(opts):
        if (o.get("keystone") or "") not in want:
            continue
        if (o.get("rune_play") or 0) < MIN_PLAY:
            continue                         # real pages only; never import a meme
        if best is None or (o.get("rune_play") or 0) > (opts[best].get("rune_play") or 0):
            best = i
    if best is None:
        return 0, None
    o, d0 = opts[best], opts[0]
    reason = tf("{reason} — {chosen} over {default} "
                "({chosen_wr:.0f}% on {chosen_games} games "
                "vs {default_wr:.0f}% on {default_games})",
                reason=why, chosen=o.get("keystone"), default=d0.get("keystone"),
                chosen_wr=o.get("rune_wr", 0), chosen_games=o.get("rune_play", 0),
                default_wr=d0.get("rune_wr", 0), default_games=d0.get("rune_play", 0))
    return best, reason


# ---- fixtures for tools/selftest.py -------------------------------------------------------
def demo(kind):
    """(dd, options, enemy_ids) for each branch. Mirrors the real Talon mid page set."""
    dd = {"id2name": {1: "Ornn", 2: "Sejuani", 3: "Malphite", 4: "Ahri", 5: "Jinx",
                      6: "Zed", 7: "Lux", 8: "Ezreal", 9: "Garen"},
          "id2tags": {1: ["Tank"], 2: ["Tank"], 3: ["Tank", "Mage"], 4: ["Mage", "Assassin"],
                      5: ["Marksman"], 6: ["Assassin"], 7: ["Mage", "Support"],
                      8: ["Marksman", "Mage"], 9: ["Fighter", "Tank"]}}
    opts = [{"keystone": "Electrocute", "rune_play": 521, "rune_wr": 46.4},
            {"keystone": "Conqueror", "rune_play": 257, "rune_wr": 51.8},
            {"keystone": "Electrocute", "rune_play": 210, "rune_wr": 46.7}]
    if kind == "tank":
        return dd, opts, [1, 2, 3, 4, 5]                  # 3 tanks -> want Conqueror
    if kind == "squish":
        return dd, opts, [4, 5, 6, 7, 8]                  # all squishy -> Electrocute is fine
    if kind == "mixed":
        return dd, opts, [1, 4, 5, 6, 7]                  # one tank -> no call
    if kind == "early":
        return dd, opts, [1, 2]                           # too few locked -> no call
    if kind == "thin":                                     # the fitting page is a meme sample
        thin = [opts[0], {"keystone": "Conqueror", "rune_play": 9, "rune_wr": 66.0}]
        return dd, thin, [1, 2, 3, 4, 5]
    return dd, opts, []


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for k in ("tank", "squish", "mixed", "early", "thin"):
        dd, opts, en = demo(k)
        i, why = choose(dd, opts, en)
        print(f"{k:7} -> page {i} ({opts[i]['keystone']:12}) {why or '(most played, no call)'}")
