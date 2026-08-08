#!/usr/bin/env python3
"""loltags.py - quick "what does this champ do good/bad" tags for the pre-game / dead reads.

Rule-based off Data Dragon (champion class tags + the info attack/magic/difficulty ratings),
so it covers all 173 champs without hand-curating each. A short one-word tag for scoreboard
rows, plus a couple of fuller good/bad phrases for the loading-screen detail. A small curated
override sharpens the highest-signal champs where the generic class read is too vague.
"""

from smitei18n import coach

# One-keyword read per primary class — for tight scoreboard rows.
_SHORT = {"Assassin": "burst", "Marksman": "scales", "Mage": "poke",
          "Tank": "engage", "Fighter": "duelist", "Support": "peel"}

# Fuller good/bad phrases per primary class — for the loading screen where there's room.
_PHRASES = {
    "Assassin": ["one-shots squishies", "snowbally — deadly if fed", "weak if behind"],
    "Marksman": ["scales to a hypercarry", "squishy — needs peel", "weak early"],
    "Mage": ["long-range poke/burst", "immobile — punish flanks", "mana-hungry early"],
    "Tank": ["frontline engage + CC", "low damage — ignore in fights", "peels for carries"],
    "Fighter": ["sticky bruiser duelist", "strong 1v1 / skirmish", "kited by range"],
    "Support": ["utility / peel / vision", "low solo threat", "roams for picks"],
}

# Curated sharpeners: champ id (ddragon) -> (short, [phrases]). Only the high-signal ones.
_OVERRIDE = {
    "Yasuo": ("skirmish", ["windwall blocks your ranged", "snowbally duelist", "int-prone if behind"]),
    "Yone": ("skirmish", ["dashes back after diving", "strong mid-game teamfights"]),
    "Zed": ("assassin", ["ults to delete a carry", "dodge-able ult — ping it", "weak to CC/armor"]),
    "Malphite": ("wombo", ["R engages whole teamfights", "hard-counters AD carries", "flash-R threat"]),
    "Blitzcrank": ("hook", ["one hook = one death — stay behind minions", "no hook, no threat"]),
    "Thresh": ("hook", ["hook + lantern playmaker", "flay peels your dives"]),
    "Kassadin": ("scaling", ["dumpster early, unkillable late — END FAST", "R roam threat post-6"]),
    "Master Yi": ("scaling", ["gets un-kiteable if fed — CC him", "dive-punishable early"]),
    "Vayne": ("scaling", ["shreds tanks late — END FAST", "very weak early / short range"]),
    "Jax": ("scaling", ["splitpush duelist — don't 1v1 late", "E dodges your autos"]),
    "Kai'Sa": ("scaling", ["late-game hypercarry", "R dive threat once fed"]),
    "Katarina": ("burst", ["resets snowball out of control", "shut down early / grievous"]),
    "Darius": ("bully", ["wins extended trades — don't stay", "no dash, kite the pull"]),
    "Draven": ("bully", ["huge early lead if unchecked", "falls off — deny axes"]),
    "Teemo": ("annoy", ["blind + shrooms zone objectives", "control ward the pit"]),
}


def _cid(dd, ref):
    if isinstance(ref, int):
        return ref
    return dd.get("name2id", {}).get(dd.get("norm", lambda x: x)(str(ref)))


def _name(dd, cid):
    return dd.get("id2name", {}).get(cid, "")


def short(dd, ref):
    """One keyword for a scoreboard row (e.g. 'burst', 'scales', 'engage')."""
    cid = _cid(dd, ref)
    name = _name(dd, cid)
    if name in _OVERRIDE:
        return coach(_OVERRIDE[name][0])
    tags = dd.get("id2tags", {}).get(cid, []) or []
    return coach(_SHORT.get(tags[0], "")) if tags else ""


def phrases(dd, ref):
    """Two or three good/bad phrases for the loading-screen detail row."""
    cid = _cid(dd, ref)
    name = _name(dd, cid)
    if name in _OVERRIDE:
        return [coach(text) for text in _OVERRIDE[name][1]]
    tags = dd.get("id2tags", {}).get(cid, []) or []
    out = list(_PHRASES.get(tags[0], [])) if tags else []
    info = dd.get("id2info", {}).get(cid, {}) or {}
    if int(info.get("difficulty", 0)) >= 8 and "high skill" not in " ".join(out):
        out.append("high skill — can misplay it")
    return [coach(text) for text in out[:3]]


def dmg_type(dd, ref):
    """'AD' / 'AP' / 'mixed' from the info attack vs magic ratings, for itemizing armor/MR."""
    info = dd.get("id2info", {}).get(_cid(dd, ref), {}) or {}
    atk, mag = int(info.get("attack", 0)), int(info.get("magic", 0))
    if mag >= atk + 3:
        return "AP"
    if atk >= mag + 3:
        return "AD"
    return "mixed"
