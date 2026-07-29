#!/usr/bin/env python3
"""smitecard.py - renders the Smiteless overlay as a scoreboard-style PNG.

One image: build/runes header, both teams aligned by role (matchups paired by the
REAL champ in each slot), a data-only gank rating per enemy lane, and a last-10 W/L
form bar per player. Renders progressively (build + lanes first, scout fills in).

Usage:
  python smitecard.py --out card.png [--fm done.flag] [--count 10]
"""
import sys, os, time, threading, urllib.request, urllib.parse, io, json
from PIL import Image, ImageDraw, ImageFont, ImageOps

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import lolgame as lg
import lolscout as ls
import lolmatchup as lm
import lollive as ll
import lolprofile as lp
import phasecheck
import smiteconfig as cfg
import smiteskin as skin

# Phases where the overlay's session is still alive. Anything else (Lobby, None, EndOfGame…)
# means the champ select was dodged/left or the game is over -> the overlay should close so a
# fresh one opens for the next game (avoids showing a stale board from the prior session).
ACTIVE_PHASES = ("ChampSelect", "GameStart", "InProgress", "Reconnect")

# ---- theme ("Duskfall" — every color here is DERIVED from smiteskin.py, never a local hex.
# See docs/UIDESIGN.md §2. Old names are kept (BG, GOLD, TAN, ...) so the huge body of draw
# calls below doesn't need touching, but each now points at its Duskfall token. ----
BG = skin.rgb(skin.VOID)              # board/window ground (violet ink)
SURFACE = skin.rgb(skin.SURFACE)      # cards, strips, panels
RAISED = skin.rgb(skin.RAISED)        # chips/rows a step up off the ground
SUNKEN = skin.rgb(skin.SUNKEN)        # bar troughs, wells
LINE = skin.rgb(skin.LINE)            # card outlines / strong hairlines
LINE_SOFT = skin.rgb(skin.LINE_SOFT)  # soft in-card seams
TEXT = skin.rgb(skin.TXT)             # body ink
MUTED = skin.rgb(skin.MUTED)          # secondary ink
FAINT = skin.rgb(skin.FAINT)          # tertiary/disabled ink
GOLD = skin.rgb(skin.EMBER)           # THE accent: brand, "me", identity/action (was muted gold)
EMBER_DEEP = skin.rgb(skin.EMBER_DEEP)  # ember's dimmed shade: large fills, quiet rails
ARC = skin.rgb(skin.ARC)              # live telemetry: timers, win-prob, sparklines
GREEN = skin.rgb(skin.GOOD)           # wins / TAKE / saved-ok
RED = skin.rgb(skin.BAD)              # losses / danger / GIVE / dodge flags
WARN = skin.rgb(skin.WARN)            # caution / 50-50 / expiring
INFO = skin.rgb(skin.INFO)            # links, neutral highlights, bullet dots
MYSTIC = skin.rgb(skin.MYSTIC)        # antiheal/utility tags
# legacy aliases: the file used BLUE/RED for the ally/enemy rail accent and REDWR/TAN as a
# second win-rate ramp — re-anchored onto the new tokens instead of re-typed everywhere.
BLUE = ARC                            # ally identity used to be a flat blue; now ARC (live cyan)
REDWR = RED
TAN = MUTED
PEDGE = LINE                          # card edge color, used all over as a var named PEDGE
PCARD = SURFACE
PCARD2 = RAISED
ALLY_BG = SURFACE                     # rail color now carries ally/enemy identity, not the fill
ENEMY_BG = SURFACE
WSQ = GREEN; LSQ = RED


def _dim(c, f):
    return tuple(max(0, min(255, int(x * f))) for x in c)


# Win/gank badge (BEST/GANK/EVEN/TOUGH/AVOID): (bg, fg) pairs re-anchored on GOOD/WARN/BAD so the
# ramp reads as a single status system instead of five unrelated hand-picked hues.
GANK = {"BEST": (_dim(GREEN, 0.28), GREEN),
        "GANK": (_dim(GREEN, 0.22), _dim(GREEN, 0.94)),
        "EVEN": (_dim(WARN, 0.24), WARN),
        "TOUGH": (_dim(RED, 0.24), _dim(RED, 0.94)),
        "AVOID": (_dim(RED, 0.30), RED)}
ROLES = [("top", "top"), ("jungle", "jg"), ("mid", "mid"), ("adc", "adc"), ("support", "sup")]
LANE_MACRO = {
    "top": "Lane: freeze when ahead, shove + TP/roam with prio.   After: splitpush a side lane, draw pressure, TP to fights.",
    "mid": "Lane: crash then roam/recall on prio; don't roam on a wave pushing to you.   After: roam for picks, set up objectives.",
    "adc": "Lane: farm safe, trade on cooldowns, ward for ganks.   After: take objectives, position back-line, scale to carry.",
    "support": "Lane: enable your ADC, ward river, track the enemy jungler.   After: roam for vision + picks, peel or engage by your kit.",
}

# Champion archetype from Riot's tags, with a small override where tags mislead
# (e.g. Yasuo is tagged Fighter/Assassin but plays as a skirmisher).
ARCH_OVERRIDE = {
    "Yasuo": "skirmisher", "Yone": "skirmisher", "Sylas": "skirmisher", "Akshan": "skirmisher",
    "Katarina": "assassin", "Akali": "assassin", "Fizz": "assassin", "Diana": "assassin",
    "Ekko": "assassin", "Qiyana": "assassin", "Pyke": "assassin",
    "Kassadin": "scaling", "Vladimir": "scaling", "Kayle": "scaling", "Veigar": "scaling",
    "Cassiopeia": "scaling", "AurelionSol": "scaling", "Azir": "scaling", "Ryze": "scaling",
    "Smolder": "scaling", "Nasus": "scaling",
}
ARCHETYPE_MACRO = {
    "mage": "Lane: shove for prio + poke, respect all-ins (you're squishy).   After: group, zone with range from the back, win the 5v5.",
    "assassin": "Lane: shove and roam for picks, get a lead before they scale.   After: hunt isolated carries/supports - don't 5v5 front-to-back.",
    "skirmisher": "Lane: shove for tempo, look for side-lane 1v1s.   After: take a side lane, flank fights, fight around a knockup/engage.",
    "scaling": "Lane: farm safe, survive your weak early.   After: hit your spikes then take over - group, zone, force objectives.",
    "marksman": "Lane: farm safe, trade on cooldowns, respect ganks.   After: stay back-line, take objectives, scale to carry the 5v5.",
    "bruiser": "Lane: trade with your sustain/durability, manage the wave.   After: front-line or splitpush a side lane, draw pressure.",
    "tank": "Lane: soak XP, set up your jungler's ganks, scale.   After: front-line, start fights with your CC, peel the carry.",
}
VS_NOTE = {
    "assassin": "vs an assassin: respect the lvl-6 all-in, ward your flanks.",
    "mage": "vs a mage: dodge poke, trade when their key spell is down.",
    "skirmisher": "vs a skirmisher: avoid extended 1v1s, play for picks/collapse.",
    "scaling": "vs a scaling pick: punish early - shove, roam, deny farm.",
    "marksman": "vs a marksman: all-in early before they get items online.",
    "bruiser": "vs a bruiser: kite, don't extended-trade into their sustain.",
    "tank": "vs a tank: they out-sustain - play for objectives/roams, not the 1v1.",
    "enchanter": "vs an enchanter: dive the carry they peel, or burst through them.",
}


def archetype(dd, cid):
    if not cid:
        return ""
    if dd.get("id2key", {}).get(cid, "") in ARCH_OVERRIDE:
        return ARCH_OVERRIDE[dd["id2key"][cid]]
    tags = dd.get("id2tags", {}).get(cid, [])
    for t, a in (("Assassin", "assassin"), ("Marksman", "marksman"), ("Mage", "mage"),
                 ("Support", "enchanter"), ("Tank", "tank"), ("Fighter", "bruiser")):
        if t in tags:
            return a
    return ""
W = 920; ROWH = 66; TOP = 96
PW = 1150               # the profile window renders WIDER than the board (landscape home page)
ICONCACHE = os.path.expanduser("~/.claude/cache/icons")
_FONTS = {}
_ICONS = {}   # (cid, size) -> resized RGBA Image; avoids re-reading/resizing every repaint
_SPLASH = {}      # (cid, (w,h)) -> cropped RGB splash art
_SPLASH_RAW = {}  # cid -> base RGB splash art (full-size, in-memory only)
LOADCACHE = os.path.join(ICONCACHE, "loading")   # Riot's 308x560 loading-screen portraits
_LOADART = {}     # (cid, (w,h)) -> cropped RGB portrait
_LOADART_RAW = {} # cid -> base 308x560 RGB portrait


# Glyphs Segoe UI regular/bold don't carry -> they render as tofu boxes. Segoe UI Symbol
# has all of them AND the same Latin, so a mixed string ("★ gank") drawn wholly in it looks
# right (it just loses bold weight on those few short labels, which is fine).
# Coverage is PROBED from the font itself (skin.needs_symbol) — the old hand-typed
# allowlist here and the widget's copy drifted apart, which is how tofu kept regressing.


def font(size, bold=False, text=None):
    """Segoe UI (bold optional). If `text` carries a glyph Segoe UI lacks (★ ▸ ⚠ ✓ …),
    fall back to Segoe UI Symbol for the whole string so it doesn't render as a tofu box."""
    if text and skin.needs_symbol(text):
        key = ("sym", size)
        if key not in _FONTS:
            try:
                _FONTS[key] = ImageFont.truetype(skin.FONT_SYMBOL_TTF, size)
            except Exception:
                _FONTS[key] = font(size, bold)      # no symbol font -> at least don't crash
        return _FONTS[key]
    key = (size, bold)
    if key not in _FONTS:
        fp = r"C:\Windows\Fonts\seguisb.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"
        try:
            _FONTS[key] = ImageFont.truetype(fp, size)
        except Exception:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


_DISPLAY_TTF_FALLBACK = r"C:\Windows\Fonts\seguisb.ttf"    # Segoe UI Semibold (UIDESIGN §3 fallback)


def display_font(size, bold=False):
    """Bahnschrift (skin.FONT_DISPLAY_TTF) for headers, the brand wordmark, champ names,
    verdict text, and every numeral (KDA, win rates, scores, timers, gold, LP) — the Duskfall
    display face (UIDESIGN §3). Bahnschrift is a variable font; PIL's plain truetype loader
    just takes its default (Regular) weight, which is fine here — `bold` only widens where we
    fall back to Segoe UI Semibold. Falls back to Segoe UI Semibold when Bahnschrift is
    missing (any non-Windows dev box, or old Win10 LTSB), same as smiteskin.display()."""
    key = ("display", size, bold)
    if key not in _FONTS:
        try:
            _FONTS[key] = ImageFont.truetype(skin.FONT_DISPLAY_TTF, size)
        except Exception:
            try:
                _FONTS[key] = ImageFont.truetype(_DISPLAY_TTF_FALLBACK, size)
            except Exception:
                _FONTS[key] = font(size, bold)      # last resort -> never crash a render
    return _FONTS[key]


def name_font(size, text):
    """Bold Segoe UI for Latin names; a CJK-capable font for names with CJK chars (so a
    Chinese/Japanese/Korean summoner name renders instead of tofu boxes)."""
    if all(ord(ch) < 0x2E00 for ch in text):
        return font(size, True)
    key = ("cjk", size)
    if key not in _FONTS:
        for fp in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
                   r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\YuGothB.ttc"):
            try:
                _FONTS[key] = ImageFont.truetype(fp, size)
                break
            except Exception:
                continue
        else:
            _FONTS[key] = font(size, True)
    return _FONTS[key]


_ICON_PRUNED = False


def _prune_icon_cache(keep_ver):
    """Drop icon dirs for OLD patches (they accumulate ~2MB every two weeks, forever)."""
    global _ICON_PRUNED
    _ICON_PRUNED = True
    try:
        for name in os.listdir(ICONCACHE):
            p = os.path.join(ICONCACHE, name)
            if name != keep_ver and os.path.isdir(p):
                import shutil
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def get_icon(dd, cid, size):
    ck = (cid, size)
    if ck in _ICONS:
        return _ICONS[ck]
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    if not _ICON_PRUNED:
        _prune_icon_cache(dd["ver"])
    d = os.path.join(ICONCACHE, dd["ver"])
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, key + ".png")
    if not os.path.exists(fp):
        url = f"https://ddragon.leagueoflegends.com/cdn/{dd['ver']}/img/champion/{key}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": lb.UA})
            data = urllib.request.urlopen(req, timeout=8).read()
            tmp = f"{fp}.{os.getpid()}.tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, fp)                       # atomic: never a half-written icon
        except Exception:
            return None
    try:
        im = Image.open(fp).convert("RGBA").resize((size, size))
        _ICONS[ck] = im
        return im
    except Exception:
        try:
            os.remove(fp)                             # corrupt cached icon -> re-download next time
        except Exception:
            pass
        return None


_ITEM_ICONS = {}


def get_item_icon(dd, iid, size):
    """Item icon from ddragon, disk-cached per patch like champ icons."""
    ck = (iid, size)
    if ck in _ITEM_ICONS:
        return _ITEM_ICONS[ck]
    if not iid:
        return None
    d = os.path.join(ICONCACHE, dd["ver"], "items")
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, f"{iid}.png")
    if not os.path.exists(fp):
        url = f"https://ddragon.leagueoflegends.com/cdn/{dd['ver']}/img/item/{iid}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": lb.UA})
            data = urllib.request.urlopen(req, timeout=8).read()
            tmp = f"{fp}.{os.getpid()}.tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, fp)
        except Exception:
            return None
    try:
        im = Image.open(fp).convert("RGBA").resize((size, size))
        if len(_ITEM_ICONS) > 200:
            _ITEM_ICONS.clear()
        _ITEM_ICONS[ck] = im
        return im
    except Exception:
        try:
            os.remove(fp)
        except Exception:
            pass
        return None


_FACES = {}             # cid -> (fx, fy) normalized face center in the splash (or None)
_FACES_LOADED = False


def _faces_path():
    return os.path.join(ICONCACHE, "faces.json")


def _face_center(dd, cid, splash):
    """Face center for banner cropping: template-match the champ's icon (Riot's own face
    crop) inside the splash once, then disk-cache forever. None -> caller's fixed bias."""
    global _FACES_LOADED
    if not _FACES_LOADED:
        _FACES_LOADED = True
        try:
            _FACES.update({int(k): (tuple(v) if v else None)
                           for k, v in json.load(open(_faces_path(), encoding="utf-8")).items()})
        except Exception:
            pass
    if cid in _FACES:
        return _FACES[cid]
    try:
        import lolvision as lv
        icon = get_icon(dd, cid, 96)
        face = lv.find_face(splash, icon) if icon else None
    except Exception:
        face = None
    _FACES[cid] = face
    try:
        os.makedirs(ICONCACHE, exist_ok=True)
        json.dump({str(k): (list(v) if v else None) for k, v in _FACES.items()},
                  open(_faces_path(), "w", encoding="utf-8"))
    except Exception:
        pass
    return face


def get_splash(dd, cid, size):
    ck = (cid, size)
    if ck in _SPLASH:
        return _SPLASH[ck]
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    if cid not in _SPLASH_RAW:
        urls = [
            f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key}_0.jpg",
            f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{key}_0.jpg",
        ]
        base = None
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": lb.UA})
                data = urllib.request.urlopen(req, timeout=8).read()
                base = Image.open(io.BytesIO(data)).convert("RGB")
                break
            except Exception:
                continue
        if base is None:
            return None
        if len(_SPLASH_RAW) >= 10:      # full splashes are ~2.6MB each; the profile hero +
            _SPLASH_RAW.clear()         # six pool cards live here, so keep a real working set
        if len(_SPLASH) >= 28:          # cropped variants too (a few hundred KB each)
            _SPLASH.clear()
        _SPLASH_RAW[cid] = base
    try:
        tw, th = size
        base = _SPLASH_RAW[cid]
        face = _face_center(dd, cid, base)         # (fx, fy) or None
        im = base.copy()
        sw, sh = im.size
        scale = max(float(tw) / max(1, sw), float(th) / max(1, sh))
        rw, rh = max(1, int(sw * scale)), max(1, int(sh * scale))
        im = im.resize((rw, rh), Image.LANCZOS)
        if face:
            # center the crop on the FACE (slightly above center vertically - portraits
            # read better with headroom), clamped to the art bounds
            x0 = int(max(0, min(rw - tw, face[0] * rw - tw * 0.5)))
            y0 = int(max(0, min(rh - th, face[1] * rh - th * 0.42)))
        else:
            x0 = (rw - tw) // 2
            y0 = int(max(0, min(rh - th, (rh - th) * 0.22)))   # old fixed upper-bias fallback
        im = im.crop((x0, y0, x0 + tw, y0 + th))
        _SPLASH[ck] = im
        return im
    except Exception:
        return None


def get_loadart(dd, cid, size):
    """Riot's own LOADING-SCREEN portrait (308x560) cropped to `size` — the TALL card the real
    League loading screen shows, already composed for that shape (the champ centered, headroom
    above, nothing important at the edges). Use this wherever the art is taller than it is wide;
    get_splash's landscape 1215x717 art only survives a portrait crop as a narrow slice.

    Disk-cached: ~45KB each against a splash's ~2.6MB, so ten of them warm in a blink instead
    of costing 26MB of downloads on the loading screen. Falls back to the splash crop for a
    champ whose loading art won't load."""
    ck = (cid, size)
    if ck in _LOADART:
        return _LOADART[ck]
    key = dd.get("id2key", {}).get(cid)
    if not key:
        return None
    if cid not in _LOADART_RAW:
        fp = os.path.join(LOADCACHE, dd.get("ver", "x"), key + ".jpg")
        base = None
        try:
            base = Image.open(fp).convert("RGB")
        except Exception:
            base = None
        if base is None:
            url = f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{key}_0.jpg"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": lb.UA})
                data = urllib.request.urlopen(req, timeout=8).read()
                base = Image.open(io.BytesIO(data)).convert("RGB")
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "wb") as f:
                    f.write(data)
            except Exception:
                base = None
        if base is None:
            return get_splash(dd, cid, size)          # no portrait art -> landscape crop
        if len(_LOADART_RAW) >= 24:                   # ~0.5MB each in memory; a lobby is 10
            _LOADART_RAW.clear()
        if len(_LOADART) >= 32:
            _LOADART.clear()
        _LOADART_RAW[cid] = base
    try:
        tw, th = size
        base = _LOADART_RAW[cid]
        sw, sh = base.size
        scale = max(float(tw) / max(1, sw), float(th) / max(1, sh))
        rw, rh = max(1, int(sw * scale)), max(1, int(sh * scale))
        im = base.resize((rw, rh), Image.LANCZOS)
        # the art is already framed on the champ — center horizontally, bias UP so the face
        # stays clear of whatever the caller lays over the bottom of the card
        x0 = (rw - tw) // 2
        y0 = int(max(0, min(rh - th, (rh - th) * 0.18)))
        im = im.crop((x0, y0, x0 + tw, y0 + th))
        _LOADART[ck] = im
        return im
    except Exception:
        return None


_SHARD = {5008: "Adaptive", 5005: "AtkSpd", 5007: "Haste", 5011: "Health",
          5001: "HP-scale", 5010: "MoveSpd", 5013: "Tenacity"}


def _rune_page(dd, rp):
    """Decode ONE op.gg rune page into the fields render + import both use."""
    pr = rp.get("primary_rune_ids", [])
    sr = rp.get("secondary_rune_ids", [])
    pl, wn = rp.get("play", 0) or 0, rp.get("win", 0) or 0
    return dict(keystone=dd["runes"].get(pr[0], "") if pr else "",
                primary=[dd["runes"].get(i, "") for i in pr],
                secondary=[dd["runes"].get(i, "") for i in sr],
                primary_tree=dd["trees"].get(rp.get("primary_page_id"), ""),
                secondary_tree=dd["trees"].get(rp.get("secondary_page_id"), ""),
                primary_ids=pr,
                secondary_ids=sr,
                primary_page_id=rp.get("primary_page_id"),
                secondary_page_id=rp.get("secondary_page_id"),
                stat_mod_ids=rp.get("stat_mod_ids", []),
                shards=[_SHARD.get(i, "") for i in rp.get("stat_mod_ids", [])],
                rune_play=pl,
                rune_wr=(wn / pl * 100) if pl else 0.0)


# Which of the op.gg rune pages is currently selected in the champ-select panel (a click
# on a rune-set chip changes this). Process-wide, since the overlay's click handler and its
# render loop share this module; reset to 0 (most-played) whenever the champ changes.
# `manual` marks a selection the USER made by clicking a rune chip. The adaptive chooser
# (core/lolrunes) may set the index freely while it's False, but must never overrule a human.
_RUNE_SEL = {"idx": 0, "manual": False}
_RUNE_EVENT = threading.Event()          # set on a rune-chip click -> wakes the champ-select loop now


def set_rune_idx(n, manual=True):
    _RUNE_SEL["idx"] = max(0, int(n))
    _RUNE_SEL["manual"] = bool(manual)
    _RUNE_EVENT.set()                    # re-render immediately instead of waiting out the 2s poll


def get_rune_idx():
    return _RUNE_SEL["idx"]


def pick_rune(build, idx=None):
    """`build` with its rune fields set to the selected rune page (default = the current
    selection). Non-destructive; used for BOTH the panel display and the import so the two
    never disagree."""
    opts = (build or {}).get("rune_options") or []
    if not opts:
        return build
    i = _RUNE_SEL["idx"] if idx is None else int(idx)
    i = max(0, min(i, len(opts) - 1))
    b = dict(build)
    b.update(opts[i])
    return b


def build_data(dd, cid, role):
    """op.gg build/runes for a champ+role, or None on any missing/odd data (never crashes).
    Carries the top rune pages in `rune_options` (index 0 = most-played, the default);
    top-level rune fields mirror option 0 so old callers keep working unchanged."""
    try:
        d = lb.opgg(cid, role or "jungle")
        if not d or "summary" not in d or not d.get("runes"):
            return None
        av = d["summary"]["average_stats"]
        pages = sorted((r for r in d["runes"] if r.get("primary_rune_ids")),
                       key=lambda r: r.get("play", 0), reverse=True)
        opts = [_rune_page(dd, rp) for rp in pages[:3]]
        if not opts:
            return None
        # each rune set carries its own summoners: op.gg doesn't link them, so pair the Nth-most
        # rune page with the Nth-most summoner combo (capped). Selecting a set shows+imports these.
        sspells = sorted((x for x in d.get("summoner_spells", []) if x.get("ids")),
                         key=lambda x: x.get("play", 0), reverse=True)
        for i, opt in enumerate(opts):
            combo = list(sspells[min(i, len(sspells) - 1)]["ids"]) if sspells else []
            opt["summoner_ids"] = combo
            opt["summs"] = [dd["spells"].get(s, "") for s in combo]
        core = max(d["core_items"], key=lambda x: x["play"])
        sm = max(d["skill_masteries"], key=lambda x: x["play"]) if d.get("skill_masteries") else None
        base = dict(opts[0])                       # default = most-played rune page (runes + summoners)
        base.update(rune_options=opts,
                    core=[dd["items"].get(i, "") for i in core["ids"]],
                    core_ids=list(core["ids"]),
                    skills=(sm["ids"] if sm else []),
                    wr=av.get("win_rate", 0) * 100,
                    tier={1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}.get(av.get("tier"), ""))
        return base
    except Exception:
        return None


_ROLE_ALIAS = {"jg": "jungle", "jung": "jungle", "jungle": "jungle", "mid": "mid",
               "middle": "mid", "top": "top", "adc": "adc", "bot": "adc", "bottom": "adc",
               "marksman": "adc", "carry": "adc", "sup": "support", "supp": "support",
               "support": "support", "utility": "support"}


def _norm_role(r):
    return _ROLE_ALIAS.get((r or "").strip().lower(), (r or "").strip().lower())


# Gank score = transparent weighted math (no AI). The champ-vs-champ matchup is the
# BASE (dominant); the enemy laner's recent form is ~a 30% modifier that COMPOUNDS
# with the length of their win/loss streak; and an extreme (near-0%/100% winrate or
# a long streak) OVERRIDES the matchup entirely - amazing/avoid no matter what.
GANK_W_LANE = 1.0       # champ-vs-champ matchup edge vs 50% (the base; e.g. 55% -> +5)
GANK_W_FORM = 0.15      # enemy recent-form weight before streak compounding (~30% influence)
GANK_W_CHAMP = 0.10     # enemy's winrate ON the champ they're playing vs 50%
GANK_OFFCHAMP = 4.0     # enemy is off their champ (no recent games on it)
GANK_STREAK_COMP = 0.18 # each game in a streak BEYOND 2 amplifies the form term (compounding)
GANK_EXTREME = 16.0     # near-total streak/winrate decides regardless of matchup
GANK_T = 6.0            # |score| threshold for GANK / TOUGH; between = EVEN

# YOUR champ's gank/roam potential (added to every lane's score): hard reliable CC + engage
# makes any lane gankable; no CC means you need the enemy to be already losing. Keyed by
# Data Dragon champ key. Curated by kit (jungle + common mid roamers); default = neutral.
GANK_KIT = {
    # +6 elite lockdown / unmissable CC engage
    "Maokai": 6, "Nautilus": 6, "Sejuani": 6, "Amumu": 6, "Zac": 6, "Rammus": 6,
    "Skarner": 6, "Warwick": 6, "Volibear": 6, "Nunu": 6, "Leona": 6, "Galio": 6,
    "Lissandra": 6, "Annie": 6, "Malphite": 6, "Ornn": 6,
    # +4 strong engage / reliable CC
    "JarvanIV": 5, "Vi": 5, "Nocturne": 5, "RekSai": 5, "Elise": 5, "Trundle": 5,
    "Poppy": 5, "Evelynn": 5, "Pantheon": 5, "Sett": 5, "Hecarim": 4, "XinZhao": 4,
    "MonkeyKing": 4, "Gragas": 4, "Camille": 4, "Diana": 4, "Jax": 4, "Viego": 4,
    "Lillia": 4, "Fiddlesticks": 4, "Rengar": 4, "TwistedFate": 4, "Neeko": 4,
    "Veigar": 4, "Morgana": 4, "LeeSin": 4, "Udyr": 4, "Shaco": 4,
    # +2 gap-close / skillshot or single-target CC
    "Graves": 2, "KhaZix": 3, "Kayn": 3, "Ekko": 3, "Belveth": 2, "Taliyah": 3,
    "Kindred": 2, "Zed": 3, "Talon": 3, "Qiyana": 4, "Briar": 4, "Naafiri": 3,
    "Ahri": 3, "Sylas": 3, "Vex": 4, "Zoe": 3, "Akali": 2, "Fizz": 3, "Lux": 3,
    "Yone": 2, "Katarina": 2, "Gwen": 2,
    # 0/-1 little reliable CC -> weak ganks
    "Nidalee": -1, "Karthus": -1, "MasterYi": 0, "Shyvana": 0, "Teemo": 0,
    "Cassiopeia": 1, "Yasuo": 1,
}
GANK_KIT_DEFAULT = 1    # neutral (some CC / standard)


def gank_kit(dd, my_cid):
    """Your champ's flat gank/roam bonus (CC + engage). 0 if unknown champ."""
    if not my_cid:
        return 0.0
    return float(GANK_KIT.get(dd.get("id2key", {}).get(my_cid, ""), GANK_KIT_DEFAULT))


def apply_settings():
    """Pull the user's tuning (smitesettings.py) into the gank weights. The single
    'streak influence' dial scales the form weight, streak compounding, and the extreme
    override together (50 = the defaults above). Called each render so changes apply live."""
    global GANK_W_FORM, GANK_STREAK_COMP, GANK_EXTREME, GANK_W_CHAMP, GANK_OFFCHAMP, GANK_T
    global GANK_KIT_ON
    s = cfg.load()
    m = s["streak_influence"] / 50.0          # 0..2, default 1.0; scales all "enemy state" terms
    GANK_W_FORM = 0.15 * m
    GANK_STREAK_COMP = 0.18 * m
    GANK_W_CHAMP = 0.10 * m
    GANK_OFFCHAMP = 4.0 * m
    GANK_EXTREME = min(32.0, 16.0 * m)        # at m=0 -> 0: pure champ matchup, ignore how they're doing
    GANK_T = float(s["gank_threshold"])
    GANK_KIT_ON = s.get("gank_kit", True)     # feature toggle
    return s


GANK_KIT_ON = True


def _streak(form):
    """Signed consecutive results from the MOST RECENT game: +k win streak, -k loss streak."""
    if not form:
        return 0
    first, k = form[0], 0
    for w in form:
        if w == first:
            k += 1
        else:
            break
    return k if first else -k


def gank_score(ally_wr, e_n=0, e_w=0, e_cg=0, e_cw=0, e_form=None, self_kit=0.0):
    """PURE champ-vs-champ gank read: the lane matchup edge (op.gg WR vs 50) plus YOUR champ's
    gank/roam kit. Player form / streak / smurf reads are deliberately NOT mixed in here — that
    lives on the per-player grade + GOOD PLAYER tag instead, so 'gank' stays about the champs.
    (Extra args kept for signature compatibility; unused.)"""
    s = float(self_kit)                                   # YOUR champ's CC/engage (gank/roam kit)
    if ally_wr is not None:
        s += GANK_W_LANE * (ally_wr - 50.0)               # champ vs champ matchup edge
    return s


def gank_label(score):
    return "GANK" if score >= GANK_T else ("TOUGH" if score <= -GANK_T else "EVEN")


def rank_gank_labels(scores):
    """{role: label} with RELATIVE forcing: with 2+ scored lanes, SOMEONE is always the
    strong side (BEST) and someone the weak side (AVOID) - ganking is a comparison, not an
    absolute. Lanes in between keep their absolute GANK/EVEN/TOUGH labels."""
    out = {r: gank_label(s) for r, s in scores.items()}
    if len(scores) >= 2:
        best = max(scores, key=scores.get)
        worst = min(scores, key=scores.get)
        if best != worst:
            out[best] = "BEST"
            out[worst] = "AVOID"
    return out


def gank_directive(dd, gscores, glabels, enemy_role):
    """The gank read as ONE CALL, not a table of numbers (§6): where to go right now, or
    the honest fallback when nothing clears the bar. (text, color) or None. The scores
    already carry the live shift (deaths + level leads), so 'GO TOP' means top *now*."""
    if not gscores:
        return None
    best = max(gscores, key=gscores.get)
    s = gscores[best]
    champ = dd["id2name"].get(enemy_role.get(best, 0), "")
    vs = f" (vs {champ})" if champ else ""
    if s >= GANK_T:
        if glabels.get(best) == "BEST":
            return f"GO {best.upper()} — best gank on the map{vs}", GREEN
        return f"gank {best.upper()} when it's pushed{vs}", ARC
    worst = min(gscores, key=gscores.get)
    tail = f" — and stay out of {worst.upper()}" if gscores[worst] <= -GANK_T else ""
    return f"NO GOOD GANKS — farm tempo, set up the next objective{tail}", TAN


def queue_prediction(my_cid, scout_map):
    """Winners/losers queue read from recent team WR vs enemy WR. You are excluded from
    the ally average - your own recent form is the thing this read is being compared to."""
    me = (my_cid, True) if my_cid else None
    ally_wrs, enemy_wrs = [], []
    for k, sc in scout_map.items():
        n = int(sc.get("n") or 0)
        if n <= 0:
            continue
        wr = (float(sc.get("w") or 0) / n) * 100.0
        cid, is_ally = k
        if is_ally:
            if me and k == me:
                continue
            ally_wrs.append(wr)
        else:
            enemy_wrs.append(wr)
    if not ally_wrs or not enemy_wrs:
        return {"text": "QUEUE READ: scouting...", "fill": MUTED, "bg": _dim(MUTED, 0.2)}
    aavg = sum(ally_wrs) / len(ally_wrs)
    eavg = sum(enemy_wrs) / len(enemy_wrs)
    diff = aavg - eavg
    if diff >= 2.5:
        lab, col = "WINNERS QUEUE", GREEN
    elif diff <= -2.5:
        lab, col = "LOSERS QUEUE", REDWR
    else:
        lab, col = "EVEN QUEUE", TAN
    txt = f"{lab}  {aavg:.0f}% vs {eavg:.0f}%  (excl. you)"
    return {"text": txt, "fill": col, "bg": _dim(col, 0.24)}


_DODGE_CACHE = {}
# your baseline / LP-per-game / game length: one LCU round-trip, warmed OFF-THREAD and
# reused for the whole session (it only moves when you finish a game, not during a draft).
_DODGE_CTX = {"v": None, "busy": False, "tries": 0}


def dodge_read(dd, allies, enemies, flags=None, known=0):
    """THE DODGE CALL (core/loldodge): what this lobby is worth in LP against dodging it.

    Returns loldodge's dict — {verdict: DODGE|PLAY, p, edge, chip, headline, reason, lines} —
    or None if the engine couldn't answer. The old version of this function was four
    hard-coded thresholds with no idea what a dodge costs; the engine prices the decision
    instead. Cached per draft signature because every hover permutation lands here."""
    sig = (tuple(sorted((c, r) for c, r in allies if c and r)),
           tuple(sorted((c, r) for c, r in enemies if c and r)),
           tuple(sorted(flags or [])), known)
    if sig in _DODGE_CACHE:
        return _DODGE_CACHE[sig]
    if len(_DODGE_CACHE) > 64:
        _DODGE_CACHE.clear()
    try:
        import loldodge as ldg
        if _DODGE_CTX["v"] is None:
            # Your baseline / LP-per-game / game length come off the client's match history —
            # one LCU round-trip, and it must NEVER sit in the champ-select render loop (same
            # rule as the personal-fit warm). Kick it off once; until it lands the panel shows
            # "reading the draft…", and the next 2s frame picks it up.
            if not _DODGE_CTX["busy"] and _DODGE_CTX["tries"] < 3:
                _DODGE_CTX["busy"] = True
                _DODGE_CTX["tries"] += 1

                def _warm():
                    try:
                        _DODGE_CTX["v"] = ldg.context()
                    except Exception:
                        pass                       # three strikes and the call stays quiet
                    finally:
                        _DODGE_CTX["busy"] = False
                threading.Thread(target=_warm, daemon=True).start()
            return None                            # not cached: the very next frame retries
        result = ldg.read(dd, allies, enemies, flags=flags, known=known,
                          dodges_today=ldg.dodges_today(), ctx=_DODGE_CTX["v"])
    except Exception:
        result = None
    _DODGE_CACHE[sig] = result
    return result


def _wr_color(wr):
    """UIDESIGN §2's re-anchored win-rate ramp: <46 BAD, 46-52 MUTED, 52-56 GOOD, >56 ARC
    (exceptional). Same math as smiteskin.wr_color, kept local so callers here don't need to
    thread a percent through the Tk-oriented helper."""
    if wr is None:
        return MUTED
    if wr < 46:
        return RED
    if wr < 52:
        return MUTED
    if wr <= 56:
        return GREEN
    return ARC


TIER_ABBR = {"IRON": "I", "BRONZE": "B", "SILVER": "S", "GOLD": "G", "PLATINUM": "P",
             "EMERALD": "E", "DIAMOND": "D", "MASTER": "M", "GRANDMASTER": "GM", "CHALLENGER": "C"}
_DIVNUM = {"I": "1", "II": "2", "III": "3", "IV": "4"}
# Rank-tier ladder: every stop is a Duskfall token (some reused/dimmed for a low tier that
# doesn't get its own token), climbing FAINT -> MUTED -> EMBER_DEEP -> GOLD -> ARC -> GOOD ->
# INFO -> MYSTIC -> BAD -> WARN so low ranks read quiet and high ranks read hot/rare.
TIER_COLOR = {"IRON": FAINT, "BRONZE": EMBER_DEEP, "SILVER": MUTED,
              "GOLD": GOLD, "PLATINUM": ARC, "EMERALD": GREEN,
              "DIAMOND": INFO, "MASTER": MYSTIC, "GRANDMASTER": RED,
              "CHALLENGER": WARN}


def rank_str(r):
    """('D2 45LP', tier-color) for a rank dict; ('Unranked', muted) if none."""
    if not r or not r.get("tier"):
        return "Unranked", MUTED
    t = r["tier"].upper()
    col = TIER_COLOR.get(t, TAN)
    ab = TIER_ABBR.get(t, t[:1])
    if t in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return f"{ab} {r.get('lp', 0)}LP", col
    return f"{ab}{_DIVNUM.get(r.get('div', ''), '')} {r.get('lp', 0)}LP", col


# Grade ramp, per UIDESIGN §5.1: S/A read as exceptional -> ARC (the "live/standout" telemetry
# color); B is a plain good result -> GOOD; C is average -> MUTED; D/F are bad -> BAD.
GRADE_COLOR = {"SS": GOLD, "S+": ARC, "S": ARC, "A": ARC, "B": GREEN, "C": MUTED, "D": RED}
LABEL_COL = {
    # the god tier — a game-breaking performance, the hottest color there is
    "GOD KING": GOLD,
    "GOD, still lost": _dim(GOLD, 0.85),
    # wins - graduated off GOOD/GOLD, brightest for the best outcome
    "hard carry": GOLD,
    "carried": _dim(GOLD, 0.86),
    "great game": GREEN,
    "solid win": _dim(GREEN, 0.9),
    "decent game": _dim(GREEN, 0.74),
    "scrappy win": MUTED,
    # losses - INFO family for "played well anyway", BAD family for the rough ones
    "carried, lost": INFO,
    "great game, lost": _dim(INFO, 0.92),
    "kept fighting": MUTED,
    "tough loss": _dim(WARN, 0.78),
    "rough game": RED,
}
_POS_ABBR = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "MID": "MID", "BOTTOM": "ADC", "UTILITY": "SUP"}


def _rrect(d, box, r, fill=None, outline=None, width=1):
    try:
        d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)
    except Exception:
        d.rectangle(box, fill=fill, outline=outline)


def _railed_card(d, box, rail_col, fill=None, outline=None, width=1, r=None, rail=None):
    """Duskfall's signature shape (UIDESIGN §4): a rounded card with a 3px state-colored rail
    inset just inside its left edge. Draws the card body first, then the rail on top."""
    x0, y0, x1, y1 = box
    r = skin.R_CARD if r is None else r
    rail = skin.RAIL if rail is None else rail
    _rrect(d, box, r, fill=fill, outline=outline, width=width)
    if rail_col:
        rx = x0 + max(2, r // 3)
        d.rectangle([rx, y0 + r * 0.6, rx + rail, y1 - r * 0.6], fill=rail_col)


def _brand_row(d, x, y, size=8, anchor="la", suffix="", suffix_col=None):
    """The '✦ SMITELESS <suffix>' identity mark every board opens with (UIDESIGN §4): the
    spark in EMBER, the wordmark in Bahnschrift, an optional MUTED suffix. `anchor` is 'la'
    (draw rightward from x) or 'ra' (right-align the whole mark against x), matching how the
    rest of this module already anchors text. Returns the total pixel width drawn."""
    star_f = font(size, True, "✦")
    word_f = display_font(size, True)
    suf_f = font(size, True)
    star_w = d.textlength("✦ ", font=star_f)
    word_w = d.textlength("SMITELESS", font=word_f)
    suf_w = d.textlength(" " + suffix, font=suf_f) if suffix else 0
    total = star_w + word_w + suf_w
    x0 = x - total if anchor == "ra" else x
    d.text((x0, y), "✦ ", font=star_f, fill=GOLD, anchor="la")
    d.text((x0 + star_w, y), "SMITELESS", font=word_f, fill=TEXT, anchor="la")
    if suffix:
        d.text((x0 + star_w + word_w, y), " " + suffix, font=suf_f, fill=(suffix_col or MUTED), anchor="la")
    return total


def _sparkline(d, x0, y0, w, h, vals):
    """A tiny LP-over-time line; green if net-up, red if net-down. Endpoint dotted."""
    if not vals or len(vals) < 2:
        return
    lo, hi = min(vals), max(vals)
    rng = max(1, hi - lo)
    n = len(vals)
    pts = [(x0 + int(i / (n - 1) * w), y0 + h - int((v - lo) / rng * h)) for i, v in enumerate(vals)]
    col = GREEN if vals[-1] >= vals[0] else REDWR
    try:
        d.line(pts, fill=col, width=2, joint="curve")
    except Exception:
        d.line(pts, fill=col, width=2)
    ex, ey = pts[-1]
    d.ellipse((ex - 2, ey - 2, ex + 2, ey + 2), fill=col)


def _draw_session_coach(d, p, y, W=None):
    """Session band: W-L + LP swing + streak/tilt on the left, pool-coach advice on the right.
    For ANOTHER player's profile the session half is meaningless (it's local history) - show
    only their pool read."""
    W = int(W or PW)                              # profile surfaces render at the window's width
    f = font(11, 1)                                # body bits (sentences, riot id)
    nf = display_font(11, True)                    # header/numeral bits (SESSION, W-L, LP, streak)
    sess = p.get("session") or {}
    bits = []
    if p.get("other"):
        bits = [("VIEWING", GOLD, True), (p.get("riot_id", "?"), TAN, False),
                ("· their last games, scored the same way", MUTED, False)]
    else:
        if sess.get("games"):
            bits.append(("SESSION", GOLD, True))
            bits.append((f"{sess['wins']}W-{sess['losses']}L", TAN, True))
            if sess.get("lp_delta") is not None:
                dv = sess["lp_delta"]
                bits.append((f"{dv:+d} LP", GREEN if dv >= 0 else REDWR, True))
        stv = sess.get("streak", 0)
        if abs(stv) >= 2:
            bits.append((f"{'W' if stv > 0 else 'L'}{abs(stv)} streak", GREEN if stv > 0 else REDWR, True))
        if not bits:
            bits = [("SESSION", GOLD, True), ("play a ranked game to start tracking", MUTED, False)]
    x = 20
    for txt, col, is_num in bits:
        bf = nf if is_num else f
        d.text((x, y), txt, font=bf, fill=col)
        x += d.textlength(txt, font=bf) + 12
    if sess.get("tilt"):
        d.text((x, y), "· take a breather, tilt risk", font=f, fill=REDWR)
    coach = p.get("coach")
    if coach:
        cx = W - 22
        order = [k for k in ("more", "less", "slump") if coach.get(k)]
        for k in order:                                   # right-anchored, first = rightmost
            c = coach[k]
            if k == "more":
                txt, col = f"▸ play more {c['champ']} {c['wr']}% ({c.get('g','?')}g)", GREEN
            elif k == "less":
                txt, col = f"▸ ease off {c['champ']} {c['wr']}% ({c.get('g','?')}g)", REDWR
            else:                                         # a slumping MAIN: variance, not the pick
                txt, col = f"▸ rough patch on {c['champ']} — variance, not the pick", TAN
            cf = font(11, 1, txt)                          # ▸ needs Segoe UI Symbol
            d.text((cx, y), txt, font=cf, fill=col, anchor="ra")
            cx -= d.textlength(txt, font=cf) + 16


def _profile_headline(p):
    """One line about how you've been doing — CLIMB discipline first (the research-backed
    fast-climb rules outrank pleasantries): the 2-loss stop rule, sub-12k-mastery leaks,
    then pool concentration; the friendly form line only when none of those fire."""
    s = p.get("session") or {}
    if (s.get("streak") or 0) <= -2:
        return ("STOP RULE: 2 straight losses — break 30 min. Players who break win ~3% more "
                "next game; tilted sessions bleed 10-15% (597k-game study). The climb resumes after.")
    cl = p.get("climb") or {}
    if cl.get("sub12k"):
        return (f"CLIMB LEAK: {', '.join(cl['sub12k'][:2])} under 12k mastery — sub-12k picks win "
                f"~44% vs 51%+ past ~20 games (1M-game study). Feed your mains instead.")
    if cl and cl.get("pool_n", 0) >= 6 and cl.get("top_share", 100) < 40 and p.get("n", 0) >= 15:
        return (f"CLIMB: your last {p['n']} span {cl['pool_n']} champs — concentration is the fastest "
                f"climb (+5% wr from champ mastery halves games-per-rank). Commit to 2-3.")
    best = p["champs"][0] if p["champs"] else None
    if p["n"] < 3:
        return "Play a few ranked games and your form, scores and best champs show up here."
    if p["wr"] >= 60:
        tail = f"  {best['champ']} is your best at {best['wr']}%." if best and best["g"] >= 2 else ""
        return f"You're on a {p['wr']}% run over your last {p['n']} — keep riding it.{tail}"
    if p["wr"] <= 40:
        tail = f"  Lean on {best['champ']} ({best['wr']}%)." if best and best["wr"] >= 55 else ""
        return f"Rough stretch ({p['wr']}% of {p['n']}). Tighten up — avg game score {p['avg_score']}/100.{tail}"
    if p["avg_score"] >= 62:
        return f"You've been playing well (avg score {p['avg_score']}/100) — the wins will follow."
    return f"{p['wr']}% over your last {p['n']}. Avg game score {p['avg_score']}/100; each game is graded against your role's benchmarks."


def _champ_id_from_name(dd, name):
    nm = (name or "").strip()
    if not nm:
        return 0
    cid = dd["name2id"].get(dd["norm"](nm))
    if cid:
        return cid
    nn = dd["norm"](nm)
    for i, n in dd.get("id2name", {}).items():
        if dd["norm"](n).startswith(nn) or nn.startswith(dd["norm"](n)):
            return i
    return 0


DETAIL_H = 258          # height of an expanded game's 10-player breakdown + quick review


DEMON = (222, 40, 52)     # the "demise of us all" step below BAD — reserved for catastrophic games


def _perf_color(score):
    """Performance color ramp for the match-detail stat lines (§16): grade-driven (the
    _grade_game score — role-benchmarked play, not raw KDA), five steps
    great/good/okay/bad/catastrophic. None (ungradeable) stays neutral."""
    if score is None:
        return TAN
    if score >= 92:
        return ARC
    if score >= 78:
        return GREEN
    if score >= 58:
        return TAN
    if score >= 42:
        return WARN
    if score >= 30:
        return RED
    return DEMON


def _draw_match_detail(d, img, dd, parts, my_puuid, x0, y0, w, review=None, review_kind="improve",
                       dur=0, ranks=None):
    """The 10-player breakdown for an expanded game: name (clickable -> their profile),
    current rank, perf-colored KDA, full item build as icons, damage/cs/gold/vision -
    both teams, plus the review panel. KDA color comes from each player's
    _grade_game score for THIS game (role-benchmarked), so a 2/11 top laner reads demon
    red at a glance while a quiet 6/7 stays neutral.
    Returns {'review': box, 'players': [(x0,y0,x1,y1,puuid,name)]}."""
    ranks = ranks or {}
    _rrect(d, (x0, y0, x0 + w, y0 + DETAIL_H), 9, fill=SURFACE, outline=PEDGE, width=1)
    me = next((pl for pl in parts if pl["puuid"] == my_puuid), None)
    myteam = me["team"] if me else 100
    maxd = max((pl["dmg"] for pl in parts), default=1) or 1
    scores, letters = {}, {}
    try:
        import lolprofile as lp
        for pl in parts:
            try:
                s, lt, _lb = lp._grade_game(parts, pl, dur)
                scores[pl["puuid"]] = s
                letters[pl["puuid"]] = lt
            except Exception:
                pass
    except Exception:
        pass
    # placement 1..10 across the WHOLE lobby by grade score (1 = best game in the match)
    order = sorted((pl for pl in parts if pl["puuid"] in scores),
                   key=lambda p: scores[p["puuid"]], reverse=True)
    place = {pl["puuid"]: i + 1 for i, pl in enumerate(order)}
    pad, rw = 16, 232
    colw = (w - (pad * 2) - rw - 24) // 2
    teams = [[pl for pl in parts if pl["team"] == myteam],
             [pl for pl in parts if pl["team"] != myteam]]
    player_hits = []
    for ci, team in enumerate(teams):
        cx = x0 + pad + ci * (colw + 16)
        d.text((cx, y0 + 9), "YOUR TEAM" if ci == 0 else "ENEMY", font=display_font(10, True),
               fill=ARC if ci == 0 else RED)
        ry = y0 + 28
        for pl in team[:5]:
            pu = pl["puuid"]
            # placement medal (1..10 across the lobby by grade): gold/silver/bronze, then faint
            pn = place.get(pu)
            if pn:
                pcol = (GOLD if pn == 1 else (215, 215, 225) if pn == 2 else
                        EMBER_DEEP if pn == 3 else FAINT)
                _rrect(d, (cx, ry, cx + 15, ry + 15), 4, fill=_dim(pcol, 0.20),
                       outline=_dim(pcol, 0.5), width=1)
                d.text((cx + 7, ry + 7), str(pn), font=display_font(9, True), fill=pcol, anchor="mm")
            icx = cx + 20                                 # icon shifts right to clear the medal
            cid = dd["name2id"].get(dd["norm"](pl["champ"]))
            ic = get_icon(dd, cid, 26)
            if ic:
                img.paste(ic, (icx, ry + 1), ic)
            mine = pu == my_puuid
            name = (pl.get("name") or pl.get("champ") or "?").split("#")[0][:12]
            nf = font(10, 1 if mine else 0)
            d.text((icx + 32, ry), name, font=nf, fill=GOLD if mine else TEXT)
            nx = icx + 36 + d.textlength(name, font=nf)
            rk = ranks.get(pu)
            if rk:                                        # current rank beside the name (§9)
                rtxt, rcol = rank_str(rk)
                d.text((nx, ry + 1), rtxt.split(" ")[0], font=font(9, 1), fill=rcol)
                nx += d.textlength(rtxt.split(" ")[0], font=font(9, 1)) + 8
            # right side of line 1: GRADE letter chip + KDA (both grade-colored)
            kda = f"{pl['k']}/{pl['d']}/{pl['a']}"
            kw = d.textlength(kda, font=display_font(10, True))
            d.text((cx + colw - 2, ry), kda, font=display_font(10, True),
                   fill=_perf_color(scores.get(pu)), anchor="ra")
            lt = letters.get(pu)
            if lt:
                gcol = GRADE_COLOR.get(lt, MUTED)
                gx = cx + colw - 2 - kw - 8
                _rrect(d, (gx - d.textlength(lt, font=display_font(10, True)) - 8, ry - 1,
                           gx, ry + 15), 5, fill=_dim(gcol, 0.20), outline=_dim(gcol, 0.5), width=1)
                d.text((gx - 4, ry + 7), lt, font=display_font(10, True), fill=gcol, anchor="rm")
            # damage bar under the name, then items + economy line
            bx, bw_ = icx + 32, 92
            _rrect(d, (bx, ry + 14, bx + bw_, ry + 18), 2, fill=SUNKEN)
            _rrect(d, (bx, ry + 14, bx + max(2, int(bw_ * pl["dmg"] / maxd)), ry + 18), 2,
                   fill=EMBER_DEEP)
            ix = bx + bw_ + 8
            for iid in (pl.get("items") or [])[:6]:
                iic = get_item_icon(dd, iid, 15)
                if iic:
                    img.paste(iic, (ix, ry + 12), iic)
                ix += 17
            d.text((cx + colw - 2, ry + 22), f"{pl['dmg'] // 1000}k dmg · {pl['cs']}cs · "
                   f"{pl['gold'] // 1000}k g · {pl.get('vision', 0)}v",
                   font=display_font(9, True), fill=MUTED, anchor="ra")
            player_hits.append((cx, ry, cx + colw, ry + 34, pl.get("puuid", ""),
                                pl.get("name") or ""))
            ry += 42
    rx = x0 + w - rw - 12
    _rrect(d, (rx, y0 + 8, rx + rw, y0 + DETAIL_H - 8), 8, fill=RAISED, outline=PEDGE, width=1)
    good = (review_kind == "positive")
    d.text((rx + 12, y0 + 18), "POST-GAME REVIEW", font=display_font(10, True), fill=GOLD)
    d.text((rx + 12, y0 + 34), ("What you did well" if good else "3 things to improve"),
           font=font(10), fill=(GREEN if good else MUTED))
    tips = list(review or [])
    if not tips:
        tips = ["Loading role-specific review..."]
    yy = y0 + 54
    line_h = 14
    tip_gap = 6
    max_w = rw - 30
    for t in tips[:3]:
        wrapped = _wrap(t, font(10), max_w)
        if not wrapped:
            continue
        wrapped = wrapped[:2]  # keep each tip compact so all 3 fit
        d.text((rx + 12, yy), "• " + wrapped[0], font=font(10), fill=(TAN if good else TEXT))
        yy += line_h
        for ln in wrapped[1:]:
            d.text((rx + 24, yy), ln, font=font(10), fill=(TAN if good else TEXT))
            yy += line_h
        yy += tip_gap
        if yy > y0 + DETAIL_H - 18:
            break
    return {"review": (rx, y0 + 8, rx + rw, y0 + DETAIL_H - 8), "players": player_hits}


def _mix(c1, c2, f):
    """Blend c1 toward c2 by f (0..1)."""
    return tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))


def _vshade(img, box, color, a0, a1):
    """Vertical alpha ramp of a solid color over box: a0 opacity at the top edge -> a1 at
    the bottom (0-255). The cheap PIL way to art-direct splash art into a background."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    ramp = Image.new("L", (1, h))
    ramp.putdata([int(a0 + (a1 - a0) * (i / max(1, h - 1))) for i in range(h)])
    img.paste(color, (x0, y0, x1, y1), ramp.resize((w, h)))


def _hshade(img, box, color, a0, a1):
    """Horizontal twin of _vshade: a0 opacity at the left edge -> a1 at the right."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    ramp = Image.new("L", (w, 1))
    ramp.putdata([int(a0 + (a1 - a0) * (i / max(1, w - 1))) for i in range(w)])
    img.paste(color, (x0, y0, x1, y1), ramp.resize((w, h)))


def _area_spark(d, x0, y0, w, h, vals, col):
    """Filled area sparkline (line + soft fill + endpoint dot) - the stat tiles' pulse."""
    if not vals or len(vals) < 2:
        return
    lo, hi = min(vals), max(vals)
    rng = max(1e-6, float(hi - lo))
    n = len(vals)
    pts = [(x0 + i / (n - 1) * w, y0 + h - 1 - (v - lo) / rng * (h - 4)) for i, v in enumerate(vals)]
    d.polygon([(x0, y0 + h)] + pts + [(x0 + w, y0 + h)], fill=_dim(col, 0.24))
    try:
        d.line(pts, fill=_dim(col, 0.9), width=2, joint="curve")
    except Exception:
        d.line(pts, fill=_dim(col, 0.9), width=2)
    ex, ey = pts[-1]
    d.ellipse((ex - 2.5, ey - 2.5, ex + 2.5, ey + 2.5), fill=col)


def _ring(d, cx, cy, r, frac, col, width=8):
    """Progress ring: full track in SUNKEN, then the arc from 12 o'clock."""
    box = (cx - r, cy - r, cx + r, cy + r)
    try:
        d.arc(box, 0, 360, fill=_mix(SUNKEN, MUTED, 0.18), width=width)
        if frac > 0:
            d.arc(box, -90, -90 + 360 * min(1.0, frac), fill=col, width=width)
    except Exception:
        pass


def _grade_of(avg):
    """(letter, color) for an average game score, same bands as per-game letters."""
    for lo, letter in ((120, "SS"), (115, "S+"), (100, "S"), (85, "A"), (70, "B"), (55, "C")):
        if avg >= lo:
            return letter, GRADE_COLOR[letter]
    return "D", GRADE_COLOR["D"]


def render_profile(dd, p, expanded=None, details=None, width=None):
    """The home page, Duskfall hero edition: a full-bleed splash hero (name, rank, score
    ring, form bars), five sparkline stat tiles, the PATTERNS + PERSONAL BESTS panels, a
    splash-art champion pool, and the graded match list with item builds. Games in
    `expanded` (indices) show the 10-player breakdown from `details` (mid -> parts).
    Sets img.hit_games = [(y0, y1, index)] for click-to-expand."""
    # ADAPTIVE width: the window's real width (clamped) — wider window = wider tiles,
    # longer sparklines, roomier rows. A true re-render, never a raster stretch.
    W = int(min(2400, max(PW, width or PW)))
    expanded = expanded or set()
    details = details or {}
    games = p.get("games", [])

    # ---- vertical plan (top to bottom) ----
    HERO = 292
    sess_y = HERO + 12                            # session/coach strip
    tiles_y = sess_y + 30                         # five stat tiles
    tile_h = 100
    panels_y = tiles_y + tile_h + 16              # PATTERNS + PERSONAL BESTS
    panel_h = 186
    pool_y = panels_y + panel_h + 18              # champion pool rule
    pool_h = 168
    games_rule = pool_y + 26 + pool_h + 20        # RECENT GAMES rule
    games_top = games_rule + 26
    H = games_top + 16
    for i in range(len(games)):
        H += 56 + (DETAIL_H + 8 if i in expanded else 0)
    H += 52                                        # in-image Load more
    H = max(H, games_top + 60)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ============================ HERO ============================
    best = (p.get("champs") or [{}])[0].get("champ") or (games or [{}])[0].get("champ")
    best_cid = _champ_id_from_name(dd, best)
    splash = get_splash(dd, best_cid, (W, HERO)) if best_cid else None
    if splash:
        img.paste(splash, (0, 0))
        img.paste(BG, (0, 0, W, HERO), Image.new("L", (W, HERO), 66))   # global veil
        _vshade(img, (0, 0, W, 90), BG, 150, 0)                          # settle the top edge
        _vshade(img, (0, HERO - 190, W, HERO), BG, 0, 244)               # readable base
        _hshade(img, (0, 0, 560, HERO), BG, 165, 0)                      # name block ground
    else:
        _vshade(img, (0, 0, W, HERO), RAISED, 255, 0)
    d.line([(0, HERO - 1), (W, HERO - 1)], fill=_dim(GOLD, 0.55), width=1)

    name, _, tag = (p.get("riot_id") or "?").partition("#")
    nf = name_font(40, name)
    if d.textlength(name, font=nf) > 470:
        nf = name_font(28, name)
    d.text((36, 178), name, font=nf, fill=TEXT, anchor="ls")
    if tag:
        d.text((40 + d.textlength(name, font=nf), 178), f"#{tag}",
               font=display_font(15, True), fill=MUTED, anchor="ls")
    if best:
        d.text((37, 108), f"✦ {best} MAIN" if (p.get("champs") or [{}])[0].get("g", 0) >= 3 else "✦ SMITELESS",
               font=font(10, 1, "✦"), fill=_dim(GOLD, 0.95))
    # chip row: rank / record / KDA
    cy_, cx_ = 196, 36
    rs, rc = rank_str(p.get("rank"))
    chips = [(rs, rc, _dim(rc, 0.20), _dim(rc, 0.6))]
    chips.append((f"{p['wins']}W {p['losses']}L · {p['wr']}%",
                  GREEN if p["wr"] >= 50 else REDWR, RAISED, PEDGE))
    av = p.get("avgs") or {}
    if av.get("kda") is not None:
        chips.append((f"{av['kda']} KDA", TAN, RAISED, PEDGE))
    roles = p.get("roles") or {}
    if roles:
        pos, cnt = max(roles.items(), key=lambda kv: kv[1])
        chips.append((f"{_POS_ABBR.get(pos, pos[:3])} {round(cnt / max(1, sum(roles.values())) * 100)}%",
                      MUTED, RAISED, PEDGE))
    cf = display_font(13, True)
    for txt, fg, bgc, oc in chips:
        cw_ = d.textlength(txt, font=cf)
        _rrect(d, (cx_, cy_, cx_ + cw_ + 20, cy_ + 26), 13, fill=bgc, outline=oc, width=1)
        d.text((cx_ + 10, cy_ + 4), txt, font=cf, fill=fg)
        cx_ += cw_ + 30
    # headline (coach's one-liner) on the hero's readable base
    for ln in _wrap(_profile_headline(p), font(12), W - 640)[:2]:
        d.text((36, cy_ + 42), ln, font=font(12), fill=TAN)
        cy_ += 17

    # right cluster: score ring + form bars + LP spark
    avg = int(p.get("avg_score", 0) or 0)
    letter, sc_col = _grade_of(avg)
    rcx, rcy, rr = W - 110, 128, 54
    _ring(d, rcx, rcy, rr, avg / 120.0, sc_col, width=9)
    d.text((rcx, rcy - 9), str(avg), font=display_font(30, True), fill=sc_col, anchor="mm")
    d.text((rcx, rcy + 18), letter, font=display_font(13, True), fill=_dim(sc_col, 0.85), anchor="mm")
    d.text((rcx, rcy + rr + 16), "AVG GAME SCORE", font=display_font(9, True), fill=MUTED, anchor="mm")
    form = games[:10][::-1]                        # oldest -> newest, last ten
    if form:
        fx, fw, fgap, fbase = W - 350, 12, 5, 208
        d.text((fx, fbase - 62), "FORM", font=display_font(9, True), fill=MUTED)
        for g in form:
            fh = 10 + int(36 * min(1.0, (g.get("score") or 0) / 110.0))
            col = GREEN if g["win"] else RED
            _rrect(d, (fx, fbase - fh, fx + fw, fbase), 3, fill=_dim(col, 0.9))
            fx += fw + fgap
    trend = p.get("lp_trend") or []
    if len(trend) >= 2:
        net = trend[-1] - trend[0]
        d.text((W - 350, 232), "LP", font=display_font(9, True), fill=MUTED)
        d.text((W - 36, 232), f"{net:+d}", font=display_font(11, True),
               fill=GREEN if net >= 0 else REDWR, anchor="ra")
        _area_spark(d, W - 350, 246, 314, 26, trend, ARC)

    # ============================ SESSION STRIP ============================
    _draw_session_coach(d, p, sess_y, W)

    # ============================ STAT TILES ============================
    seq = games[:20][::-1]                         # oldest -> newest for every tile spark
    roll = []
    for j in range(len(seq)):                      # rolling 5-game winrate
        win5 = seq[max(0, j - 4):j + 1]
        roll.append(sum(1 for g in win5 if g["win"]) / len(win5) * 100)
    tiles = [
        ("WINRATE", f"{p['wr']}%", (GREEN if p["wr"] >= 50 else REDWR), roll),
        ("KDA", f"{av.get('kda', '—')}", TEXT,
         [min(12.0, (g["k"] + g["a"]) / max(1, g["d"])) for g in seq]),
        ("KILL PART.", f"{av.get('kp', '—')}%", TEXT, [g.get("kp") or 0 for g in seq]),
        ("CS / MIN", f"{av.get('csm', '—')}", TEXT, [g.get("csm") or 0 for g in seq]),
        ("DMG SHARE", f"{av.get('dmg_share', '—')}%", TEXT, [g.get("dmg_share") or 0 for g in seq]),
    ]
    tw = (W - 28 - 4 * 10) // 5
    tx = 14
    for lab, val, vcol, series in tiles:
        _rrect(d, (tx, tiles_y, tx + tw, tiles_y + tile_h), 10, fill=PCARD, outline=PEDGE, width=1)
        d.text((tx + 14, tiles_y + 11), lab, font=display_font(9, True), fill=MUTED)
        d.text((tx + 14, tiles_y + 26), str(val), font=display_font(24, True), fill=vcol)
        if len(series) >= 2:
            _area_spark(d, tx + 14, tiles_y + tile_h - 32, tw - 28, 22, series, ARC)
        tx += tw + 10

    # ============================ PATTERNS + PERSONAL BESTS ============================
    lx0, lx1 = 14, 714
    _rrect(d, (lx0, panels_y, lx1, panels_y + panel_h), 10, fill=PCARD, outline=PEDGE, width=1)
    d.text((lx0 + 16, panels_y + 12), "PATTERNS", font=display_font(11, True), fill=GOLD)
    d.text((lx0 + 16 + d.textlength("PATTERNS", font=display_font(11, True)) + 10, panels_y + 14),
           "when you win, from your own history", font=font(9), fill=FAINT)
    ins = p.get("insights") or []
    if ins:
        iy = panels_y + 40
        for it in ins[:4]:
            dot = GREEN if it.get("good") else RED
            d.ellipse((lx0 + 18, iy + 5, lx0 + 26, iy + 13), fill=dot)
            txt = _wrap(it["text"], font(11), lx1 - lx0 - 150)
            d.text((lx0 + 36, iy), (txt[0] if txt else it["text"]), font=font(11), fill=TEXT)
            d.text((lx1 - 16, iy), f"{it['wr']}% · {it['g']}g", font=display_font(11, True),
                   fill=dot, anchor="ra")
            iy += 35
    else:
        d.text((lx0 + 16, panels_y + 46),
               "Patterns unlock as your timestamped history loads (about 10 games in).",
               font=font(11), fill=MUTED)
        d.text((lx0 + 16, panels_y + 66),
               "They'll find things like: your late-night winrate, whether you tilt-queue, "
               "and if you", font=font(10), fill=FAINT)
        d.text((lx0 + 16, panels_y + 82),
               "win the long games — measured, never guessed.", font=font(10), fill=FAINT)
    rx0 = lx1 + 14
    _rrect(d, (rx0, panels_y, W - 14, panels_y + panel_h), 10, fill=PCARD, outline=PEDGE, width=1)
    d.text((rx0 + 16, panels_y + 12), "PERSONAL BESTS", font=display_font(11, True), fill=GOLD)
    ry = panels_y + 38
    for rec in (p.get("records") or [])[:5]:
        rcid = dd["name2id"].get(dd["norm"](rec.get("champ") or ""))
        ric = get_icon(dd, rcid, 22)
        if ric:
            img.paste(ric, (rx0 + 16, ry + 3), ric)
        d.text((rx0 + 48, ry), rec["label"], font=display_font(10, True), fill=MUTED)
        d.text((rx0 + 48, ry + 14), rec.get("sub", ""), font=font(9), fill=FAINT)
        d.text((W - 30, ry + 4), rec["value"], font=display_font(14, True), fill=GOLD, anchor="ra")
        ry += 29

    # ============================ CHAMPION POOL ============================
    ch_label = "CHAMPION POOL · THIS SEASON" if p.get("season_champs") else "CHAMPION POOL · RECENT"
    chf = display_font(13, True)
    d.text((20, pool_y), ch_label, font=chf, fill=GOLD)
    d.line([34 + int(d.textlength(ch_label, font=chf)), pool_y + 8, W - 20, pool_y + 8],
           fill=LINE_SOFT, width=1)
    cards_y = pool_y + 26
    pool = p.get("champs", [])[:6]
    if pool:
        cw = (W - 28 - (len(pool) - 1) * 10) // len(pool)
        cw = min(cw, 220)
        x = 14
        for c in pool:
            cid = dd["name2id"].get(dd["norm"](c["champ"]))
            card_box = (x, cards_y, x + cw, cards_y + pool_h)
            art = get_splash(dd, cid, (cw, pool_h)) if cid else None
            if art:
                mask = Image.new("L", (cw, pool_h), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw, pool_h), radius=12, fill=255)
                img.paste(art, (x, cards_y), mask)
                grad = Image.new("L", (1, pool_h))
                grad.putdata([int(max(0, (i - pool_h * 0.30) / (pool_h * 0.70)) * 235) for i in range(pool_h)])
                img.paste(BG, (x, cards_y, x + cw, cards_y + pool_h),
                          Image.composite(grad.resize((cw, pool_h)), Image.new("L", (cw, pool_h), 0), mask))
            else:
                _rrect(d, card_box, 12, fill=PCARD2)
            _rrect(d, card_box, 12, fill=None, outline=PEDGE, width=1)
            nm = dd["id2name"].get(cid, c["champ"])
            d.text((x + 13, cards_y + pool_h - 58), nm[:13], font=display_font(13, True), fill=TEXT)
            wcol = GREEN if c["wr"] >= 55 else (REDWR if c["wr"] < 45 else TAN)
            d.text((x + 13, cards_y + pool_h - 40), f"{c['wr']}%", font=display_font(19, True), fill=wcol)
            d.text((x + cw - 12, cards_y + pool_h - 36), f"{c['g']}g", font=display_font(11, True),
                   fill=MUTED, anchor="ra")
            if c.get("avg") is not None:
                gcol = GRADE_COLOR["A"] if c["avg"] >= 85 else (GRADE_COLOR["B"] if c["avg"] >= 70 else MUTED)
                d.text((x + cw - 12, cards_y + pool_h - 52), f"{c['avg']} avg",
                       font=display_font(10, True), fill=gcol, anchor="ra")
            bw_ = cw - 26
            _rrect(d, (x + 13, cards_y + pool_h - 13, x + 13 + bw_, cards_y + pool_h - 10), 1, fill=SUNKEN)
            _rrect(d, (x + 13, cards_y + pool_h - 13,
                       x + 13 + int(bw_ * min(1.0, c["wr"] / 100.0)), cards_y + pool_h - 10), 1,
                   fill=_dim(wcol, 0.95))
            x += cw + 10
    else:
        d.text((20, cards_y + 20), "play a few games and your pool shows up here",
               font=font(11), fill=MUTED)

    # ============================ RECENT GAMES ============================
    rg_f = display_font(13, True)
    d.text((20, games_rule), "RECENT GAMES", font=rg_f, fill=GOLD)
    d.line([34 + int(d.textlength("RECENT GAMES", font=rg_f)), games_rule + 8, W - 350, games_rule + 8],
           fill=LINE_SOFT, width=1)
    d.text((W - 20, games_rule + 1), "click a game to expand  ·  score = vs your role's goals",
           font=font(10), fill=FAINT, anchor="ra")
    hit_games, hit_reviews, hit_players, yy = [], [], [], games_top
    for i, g in enumerate(games):
        acc = GREEN if g["win"] else RED
        # railed card with a whisper of the result color in the fill itself
        _railed_card(d, (14, yy, W - 14, yy + 48), acc, fill=_mix(SURFACE, acc, 0.05),
                     outline=PEDGE, width=1, r=10)
        cid = dd["name2id"].get(dd["norm"](g["champ"]))
        ic = get_icon(dd, cid, 36)
        if ic:
            img.paste(ic, (28, yy + 6), ic)
        d.text((76, yy + 7), dd["id2name"].get(cid, g["champ"])[:14], font=display_font(13, True), fill=TEXT)
        d.text((76, yy + 27), f"{g['k']}/{g['d']}/{g['a']}", font=display_font(11, True), fill=MUTED)
        kx = 80 + d.textlength(f"{g['k']}/{g['d']}/{g['a']}", font=display_font(11, True))
        d.text((kx + 4, yy + 28), _POS_ABBR.get((g.get("pos") or "").upper(), ""), font=font(9, 1), fill=FAINT)
        gc = GRADE_COLOR.get(g["letter"], TAN)
        _rrect(d, (250, yy + 11, 318, yy + 37), 13, fill=_dim(gc, 0.20), outline=_dim(gc, 0.5), width=1)
        d.text((262, yy + 16), g["letter"], font=display_font(14, True), fill=gc)
        d.text((291, yy + 18), str(g["score"]), font=display_font(12, True), fill=gc)
        d.text((338, yy + 17), g["label"], font=font(12, 1), fill=LABEL_COL.get(g["label"], MUTED))
        # the item build, right there on the row (op.gg-grade glanceability)
        ix = 560
        for iid in (g.get("items") or [])[:6]:
            iic = get_item_icon(dd, iid, 24)
            if iic:
                _rrect(d, (ix - 1, yy + 11, ix + 24, yy + 36), 4, fill=SUNKEN)
                img.paste(iic, (ix, yy + 12), iic)
            ix += 27
        extra = []
        if (g.get("pos") or "").upper() == "UTILITY":     # a support's cs/min is noise: show vision
            if g.get("vision") and g.get("dur"):
                extra.append(f"{g['vision'] / max(1.0, g['dur'] / 60.0):.1f} vis/m")
        elif g.get("csm"):
            extra.append(f"{g['csm']} cs/m")
        if g.get("kp") is not None:
            extra.append(f"{g['kp']}% kp")
        if g.get("dur"):
            extra.append(f"{int(g['dur'] // 60)}m")
        if extra:
            d.text((W - 46, yy + 18), "  ·  ".join(extra), font=display_font(10, True), fill=FAINT, anchor="ra")
        d.text((W - 26, yy + 17), "▾" if i in expanded else "▸", font=font(13, text="▾"), fill=MUTED, anchor="ra")
        hit_games.append((yy, yy + 48, i))
        yy += 56
        if i in expanded:
            det = details.get(g.get("mid")) or {}
            parts = det.get("parts")
            if parts:
                rb = _draw_match_detail(d, img, dd, parts, p.get("puuid"), 14, yy, W - 28,
                                        g.get("review"), g.get("review_kind", "improve"),
                                        dur=det.get("dur", 0), ranks=det.get("ranks"))
                if rb:
                    r = rb["review"]
                    hit_reviews.append((r[0], r[1], r[2], r[3], i))
                    hit_players.extend(rb["players"])
            else:
                _rrect(d, (14, yy, W - 14, yy + DETAIL_H), 9, fill=SURFACE, outline=PEDGE, width=1)
                d.text((W // 2, yy + DETAIL_H // 2), "loading game detail…", font=font(11),
                       fill=MUTED, anchor="mm")
            yy += DETAIL_H + 8
    # append an in-image "Load more" button (clickable area) so users can load older games
    btn_h = 36
    btn_y = yy + 8
    try:
        _rrect(d, (14, btn_y, W - 14, btn_y + btn_h), 9, fill=PCARD2, outline=PEDGE, width=1)
        d.text((W // 2, btn_y + btn_h // 2), "Load more", font=font(12, 1), fill=GOLD, anchor="mm")
        hit_games.append((btn_y, btn_y + btn_h, "__load_more__"))
    except Exception:
        # drawing shouldn't crash rendering; if it does, silently skip the button
        pass

    img.hit_games = hit_games
    img.hit_reviews = hit_reviews
    img.hit_players = hit_players
    img.hitmap = []
    img.profile_split_y = HERO                    # the hero stays fixed; everything else scrolls
    return img


def _abbr_pts(p):
    if p >= 1_000_000:
        return f"{p / 1e6:.1f}M"
    if p >= 1000:
        return f"{p // 1000}k"
    return str(p)


def draw_form(d, x, y, form):
    sq, gap = 7, 2
    for i, win in enumerate(form[:10]):
        cx = x + i * (sq + gap)
        d.rectangle([cx, y, cx + sq, y + sq], fill=WSQ if win else LSQ)


# How good has this player been IN THEIR GAMES — regardless of rank. A Silver stomping 20/0
# every game is God Mode (S, gold glow); a feeder is a black hole (F, avoid). Driven by recent
# win rate + KDA (are they carrying or inting) + hot/cold streak. Rank is deliberately ignored.
# Same S/A-ARC, B-GOOD, C-MUTED, D/F-BAD ramp as GRADE_COLOR (UIDESIGN §5.1) — one grade
# language across the scout rows and the profile's post-game grades.
_RATE_COLOR = {"S": ARC, "A": ARC, "B": GREEN, "C": MUTED, "D": RED, "F": RED}


def player_rating(sc):
    """(grade, color) for a player's SKILL, read from HOW THEY ACTUALLY PLAY — their per-game
    performance vs their role's benchmarks (CS, kill participation, damage share, deaths, vision),
    averaged over recent games (sc['perf'], from the same engine as the post-game review). This
    is real in-game skill, NOT win/loss and NOT rank — so a strong player grinding off-champs on
    a low account still grades well even mid-losing-streak. Win rate is only a light tie-breaker.
    Falls back to a win-rate + KDA read until detailed games have been cached."""
    if not sc:
        return None, None
    perf = sc.get("perf")
    n, w = int(sc.get("n") or 0), int(sc.get("w") or 0)
    kda = sc.get("kda") or {}
    kg = int(kda.get("g") or 0)
    if n < 4:                                         # too thin to label a human — no grade
        return None, None

    if perf is not None:
        # perf ~85 = met role targets (A-caliber game); 100+ = carrying; <55 = off — averaged.
        score = float(perf)
        if n >= 4:                                    # a tiny win-rate tie-breaker, never the driver
            score += max(-6.0, min(6.0, (w / n * 100.0 - 50.0) * 0.12))
        g = ("S" if score >= 98 else "A" if score >= 86 else "B" if score >= 74
             else "C" if score >= 62 else "D" if score >= 50 else "F")
        return g, _RATE_COLOR[g]

    # --- fallback (no detailed games cached yet): win rate + KDA on a 0-100 scale ---
    r = sc.get("rank") or {}
    sw, sl = int(r.get("w") or 0), int(r.get("l") or 0)   # this season's ranked W/L
    sg = sw + sl
    if sg < 15 and n < 3:
        return None, None                             # nothing real to judge yet
    score = 50.0
    if sg >= 15:
        score += (sw / sg * 100.0 - 50.0) * 2.0
        if n >= 5:
            score += (w / n * 100.0 - 50.0) * 0.35
    elif n >= 3:
        score += (w / n * 100.0 - 50.0) * 2.0
    if kg >= 3:
        avg = (kda.get("k", 0) + kda.get("a", 0)) / max(1, kda.get("d", 0))
        score += max(-16.0, min(20.0, (avg - 2.6) * 6.0))
    stv = _streak(sc.get("form") or [])
    if abs(stv) >= 3:
        score += 5 if stv > 0 else -5
    score = max(0.0, min(100.0, score))
    g = ("S" if score >= 80 else "A" if score >= 68 else "B" if score >= 56
         else "C" if score >= 44 else "D" if score >= 32 else "F")
    return g, _RATE_COLOR[g]


_GRADE_NUM = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
_NUM_GRADE = {6: "S", 5: "A", 4: "B", 3: "C", 2: "D", 1: "F"}


def team_avg_grades(scout_map):
    """(ally_grade, enemy_grade) — each team's AVERAGE player grade (S..F) from the live scout,
    or (None, None) if not enough scouted. A KDA/form-based second opinion on the WR queue read."""
    def avg(team):
        gs = [_GRADE_NUM[player_rating(sc)[0]] for k, sc in scout_map.items()
              if k[1] is team and player_rating(sc)[0]]
        return _NUM_GRADE[max(1, min(6, round(sum(gs) / len(gs))))] if gs else None
    return avg(True), avg(False)


def _grade_chip(d, cx, cy, grade, col, k=1.0):
    """A bold grade letter in a filled pill (UIDESIGN §5.1), centered on (cx, cy).
    k scales it in step with a scaled board (the live board renders monitor-sized)."""
    w, h = int(22 * k), int(20 * k)
    fill = tuple(int(c * 0.28) for c in col)
    _rrect(d, (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2), h // 2, fill=fill, outline=col, width=1)
    d.text((cx, cy), grade, font=display_font(int(13 * k), True), fill=col, anchor="mm")


def draw_player(d, img, dd, x, y, cid, sc, is_me, side, accent, accent_bg, live=True):
    if not cid:
        return
    grade, gcol = player_rating(sc)
    box_fill, box_edge, box_w = accent_bg, PEDGE, 1
    if grade == "S":
        box_edge, box_w = gcol, 2                     # banner glows gold
    elif grade == "F":
        box_fill, box_edge, box_w = SUNKEN, gcol, 2   # black-hole: dark fill, red ring
    name = dd["id2name"].get(cid, "?")
    icon = get_icon(dd, cid, 38)
    cw = 372
    if side == "L":
        if box_w == 2:                                # S/F: soft outer glow ring
            _rrect(d, (x - 2, y + 7, x + cw + 2, y + ROWH - 3), 11,
                   outline=tuple(int(c * 0.5) for c in box_edge), width=1)
        _rrect(d, (x, y + 9, x + cw, y + ROWH - 5), 9, fill=box_fill, outline=box_edge, width=box_w)
        d.rectangle([x, y + 16, x + 3, y + ROWH - 12], fill=accent)
        ix = x + 12
        if icon:
            img.paste(icon, (ix, y + 13), icon)
        tx = ix + 46
        nm, nf = name + ("  YOU" if is_me else ""), font(14, 1)
        d.text((tx, y + 13), nm, font=nf, fill=GOLD if is_me else TEXT)
        if grade:                                     # right after the name -> clearly the player's grade
            gx = tx + d.textlength(nm, font=nf) + 18
            _grade_chip(d, gx, y + 21, grade, gcol)
            # evidence, not a verdict: the grade always shows its sample size
            d.text((gx + 15, y + 15), f"{grade}-like · {int(sc.get('n') or 0)}g",
                   font=font(8, 1), fill=_dim(gcol, 0.85))
        _wr_line(d, tx, y + 35, sc, "la", live)
        if sc and sc.get("form"):
            draw_form(d, x + cw - 88, y + 38, sc["form"])
    else:
        if box_w == 2:
            _rrect(d, (x - cw - 2, y + 7, x + 2, y + ROWH - 3), 11,
                   outline=tuple(int(c * 0.5) for c in box_edge), width=1)
        _rrect(d, (x - cw, y + 9, x, y + ROWH - 5), 9, fill=box_fill, outline=box_edge, width=box_w)
        d.rectangle([x - 3, y + 16, x, y + ROWH - 12], fill=accent)
        ix = x - 12 - 38
        if icon:
            img.paste(icon, (ix, y + 13), icon)
        tx = ix - 8
        nf = font(14, 1)
        d.text((tx, y + 13), name, font=nf, fill=TEXT, anchor="ra")
        if grade:                                     # left of the (right-anchored) name
            gx = tx - d.textlength(name, font=nf) - 18
            _grade_chip(d, gx, y + 21, grade, gcol)
            d.text((gx - 15, y + 15), f"{grade}-like · {int(sc.get('n') or 0)}g",
                   font=font(8, 1), fill=_dim(gcol, 0.85), anchor="ra")
        _wr_line(d, tx, y + 35, sc, "ra", live)
        if sc and sc.get("form"):
            draw_form(d, x - cw + 6, y + 38, sc["form"])


def _mastery_color(pts):
    """Champ-COMFORT color, by mastery points (levels inflate forever; points tell the truth):
    gold = their MAIN (respect it), green = comfortable, plain = knows it, dim = barely played."""
    if pts >= 100_000:
        return GOLD
    if pts >= 30_000:
        return GREEN
    if pts >= 8_000:
        return TEXT
    return MUTED


def _wr_line(d, x, y, sc, anchor, live=True):
    if sc is None:
        if live:
            d.text((x, y), "scouting...", font=font(11), fill=MUTED, anchor=anchor)
        return
    rtext, rcol = rank_str(sc.get("rank"))
    n, w, cg, cw = sc["n"], sc["w"], sc["cg"], sc["cw"]
    if n:
        wr = w / n * 100
        t = f"L10 {w}-{n - w} {wr:.0f}%"
        col = _wr_color(wr)
    else:
        t, col = "no recent", MUTED
    # champ comfort gets its OWN color (it used to inherit the win-rate color, which made
    # a 209k-point main look "worse" than a 23k dabble whenever their recent W/L differed)
    m = sc.get("mastery")
    if m and m.get("points"):
        t2, col2 = f"·  M{m['level']} {_abbr_pts(m['points'])}", _mastery_color(m["points"])
    elif cg == 0:
        t2, col2 = "·  off-champ", REDWR          # no mastery + none recent = first-timing it
    else:
        t2, col2 = f"·  {cw}/{cg} on", TEXT
    # rank / form / comfort are all numerals (LP, W-L, %, mastery points) -> the display face
    rf, ff = display_font(11, True), display_font(11)
    if anchor == "ra":                           # right rows: comfort ... form ... rank, mirrored
        d.text((x, y), t2, font=ff, fill=col2, anchor="ra")
        x2 = x - d.textlength(t2, font=ff) - 8
        d.text((x2, y), t, font=ff, fill=col, anchor="ra")
        d.text((x2 - d.textlength(t, font=ff) - 10, y), rtext, font=rf, fill=rcol, anchor="ra")
    else:
        d.text((x, y), rtext, font=rf, fill=rcol, anchor="la")
        x2 = x + d.textlength(rtext, font=rf) + 10
        d.text((x2, y), t, font=ff, fill=col, anchor="la")
        d.text((x2 + d.textlength(t, font=ff) + 8, y), t2, font=ff, fill=col2, anchor="la")


def draw_badge(d, cx, y, rating, k=1.0):
    bg, fg = GANK[rating]
    label = {"BEST": "★ gank", "GANK": "gank", "EVEN": "even",
             "TOUGH": "tough", "AVOID": "avoid"}[rating]
    f = font(int(11 * k), 1, label)
    half = d.textlength(label, font=f) / 2 + 8 * k
    d.rounded_rectangle([cx - half, y, cx + half, y + int(17 * k)], radius=int(8 * k), fill=bg)
    d.text((cx, y + int(8.5 * k)), label, font=f, fill=fg, anchor="mm")


def _wrap(text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if fnt.getlength(t) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_lane_panel(d, img, dd, x, y, w, my_cid, my_role, opp_cid, my_wr, opp_sc, tip_lines, ph):
    _rrect(d, (x, y, x + w, y + ph), 10, fill=SURFACE, outline=PEDGE, width=1)
    d.rectangle([x, y + 8, x + 3, y + ph - 8], fill=GOLD)
    myn = dd["id2name"].get(my_cid, "?")
    arch = archetype(dd, my_cid)
    label = "YOUR LANE" + (f"   ·   {arch}" if arch else "") + ("   ·   live tip" if tip_lines else "")
    d.text((x + 14, y + 8), label, font=display_font(13, True), fill=GOLD)
    if opp_cid:
        oppn = dd["id2name"].get(opp_cid, "?")
        head = f"{myn} vs {oppn}"                          # champ names -> display face
        head_f = display_font(15, True)
        d.text((x + 14, y + 25), head, font=head_f, fill=TEXT)
        hx = x + 14 + d.textlength(head, font=head_f) + 12
        if my_wr is not None:
            d.text((hx, y + 27), f"{my_wr:.0f}%", font=display_font(14, True), fill=_wr_color(my_wr))
        else:
            d.text((hx, y + 28), "no op.gg sample", font=font(12), fill=MUTED)
        if opp_sc and opp_sc["n"]:
            ofw = opp_sc["w"] / opp_sc["n"] * 100
            ct = (f"{opp_sc['cw']}/{opp_sc['cg']} on {oppn}" if opp_sc["cg"] else "off-champ")
            orank = rank_str(opp_sc.get("rank"))[0]
            d.text((x + 14, y + 46),
                   f"{oppn} {orank}   ·   last 10: {opp_sc['w']}-{opp_sc['n'] - opp_sc['w']} ({ofw:.0f}%)   ·   {ct}",
                   font=font(11), fill=MUTED)
    else:
        d.text((x + 14, y + 26), f"{myn} — lane opponent fills in once the match starts", font=font(12), fill=MUTED)
    if tip_lines:
        ty = y + 65
        for ln in tip_lines:
            d.text((x + 14, ty), ln, font=font(12), fill=_dim(GOLD, 0.85))
            ty += 18
    else:
        macro = (LANE_MACRO["support"] if my_role == "support"
                 else (ARCHETYPE_MACRO.get(arch) or LANE_MACRO.get(my_role)))
        if macro:
            d.text((x + 14, y + 64), macro, font=font(11), fill=INFO)
        vs = VS_NOTE.get(archetype(dd, opp_cid)) if opp_cid else None
        if vs:
            d.text((x + 14, y + 82), vs, font=font(11), fill=_dim(WARN, 0.85))


def draw_build_block(d, img, dd, x, y, build, hits=None):
    """The champ-select runes/build card: keystone + rune words, the core build as real
    ITEM ICONS, summoners, skill order, and the import button - in one framed card."""
    cw, chh = 396, 236
    _rrect(d, (x - 16, y - 10, x - 16 + cw, y - 10 + chh), 12, fill=SURFACE, outline=PEDGE, width=1)
    d.text((x, y), "RUNES", font=display_font(10, True), fill=GOLD)
    d.text((x, y + 16), build.get("keystone", ""), font=font(15, 1), fill=TEXT)
    minor = "  ·  ".join(r for r in build.get("primary", [])[1:] if r)
    if minor:
        d.text((x, y + 40), minor, font=font(11), fill=MUTED)
    sec = [r for r in build.get("secondary", []) if r]
    if sec:
        d.text((x, y + 58), f"{build.get('secondary_tree', '')}:  " + "  ·  ".join(sec),
               font=font(11), fill=INFO)
    shards = [s for s in build.get("shards", []) if s]
    if shards:
        d.text((x, y + 76), "Shards:  " + "  /  ".join(shards), font=font(11), fill=MUTED)
    d.line([x, y + 98, x - 32 + cw, y + 98], fill=PEDGE, width=1)
    d.text((x, y + 106), "CORE BUILD", font=display_font(10, True), fill=GOLD)
    ids = build.get("core_ids") or []
    ix = x
    if ids:
        for j, iid in enumerate(ids[:4]):
            ic = get_item_icon(dd, iid, 34)
            if ic:
                _rrect(d, (ix - 1, y + 121, ix + 35, y + 157), 6, outline=PEDGE, width=1)
                img.paste(ic, (ix, y + 122), ic)
            if j < min(len(ids), 4) - 1:
                d.text((ix + 40, y + 132), "›", font=font(14, 1), fill=MUTED)
            ix += 52
    else:
        d.text((x, y + 124), " > ".join(c for c in build.get("core", []) if c), font=font(12), fill=TEXT)
    d.text((x, y + 164), "Summoners:  " + " / ".join(build.get("summs", [])), font=font(11), fill=MUTED)
    skills = [s for s in build.get("skills", []) if s]
    if skills:
        d.text((x + 190, y + 164), "Skill max:  " + " > ".join(skills), font=font(11), fill=MUTED)
    # Keep import action visually grouped with the runes/summoners block. THE primary action
    # on this panel (UIDESIGN §4/§5.1): ember pill fill, VOID ink.
    bx, by, bw, bh = x, y + 186, 188, 28
    _rrect(d, (bx, by, bx + bw, by + bh), bh // 2, fill=GOLD)
    d.text((bx + (bw // 2), by + (bh // 2) + 1), "⇩ Import runes + summs", font=font(10, 1, "⇩"), fill=BG, anchor="mm")
    if hits is not None:
        hits.append((bx, by, bx + bw, by + bh, "action:import_build"))
    _auto_chip(d, bx + bw + 8, by + 3, cfg_load_auto(), hits)


def cfg_load_auto():
    try:
        import smiteconfig as _cfg
        return bool(_cfg.load().get("auto_import", False))
    except Exception:
        return False


_SITE_REGION = {"na1": "na", "euw1": "euw", "eun1": "eune", "kr": "kr", "br1": "br",
                "jp1": "jp", "oc1": "oce", "la1": "lan", "la2": "las", "tr1": "tr", "ru": "ru"}


def _profile_url(riot_id):
    """u.gg profile URL for a 'Name#TAG' riot id, or None. (u.gg plays nicer than op.gg
    behind Cloudflare WARP.) u.gg uses the platform code directly, e.g. na1."""
    if not riot_id or "#" not in riot_id:
        return None
    region = getattr(ls, "PLATFORM", "na1")
    name, tag = riot_id.rsplit("#", 1)
    return f"https://u.gg/lol/profile/{region}/{urllib.parse.quote(name)}-{urllib.parse.quote(tag)}/overview"


def site_urls(riot_id):
    """[(label, url)] to look a player up across the sites, for the right-click menu.
    Porofessor links to their LIVE game if they're in one (best 'info gathering')."""
    if not riot_id or "#" not in riot_id:
        return []
    plat = getattr(ls, "PLATFORM", "na1")
    reg = _SITE_REGION.get(plat, "na")
    name, tag = riot_id.rsplit("#", 1)
    q = urllib.parse.quote(name)
    slug = f"{q}-{urllib.parse.quote(tag)}"
    return [
        ("u.gg", f"https://u.gg/lol/profile/{plat}/{slug}/overview"),
        ("op.gg", f"https://op.gg/summoners/{reg}/{slug}"),
        ("League of Graphs", f"https://www.leagueofgraphs.com/summoner/{reg}/{slug}"),
        ("Deeplol", f"https://www.deeplol.gg/summoner/{reg}/{slug}"),
        ("Porofessor (live game)", f"https://porofessor.gg/live/{reg}/{slug}"),
    ]


_PICK_CACHE = {}
# A broad per-role champ pool (strongest / most-common first). Doubles as (a) the meta
# fallback when we can't read your mastery, and (b) the "which champs play this role" filter
# that lets 'GOOD THIS GAME' surface YOUR 12k+ mastery champs for the role BEFORE any enemy has
# locked (so it's populated the moment champ select opens, not only once you hover). Unknown
# names resolve to nothing and are skipped, so it's safe to be generous.
_ROLE_FALLBACK = {
    "top": ("Darius", "Garen", "Sett", "Aatrox", "Renekton", "Mordekaiser", "Camille", "Fiora",
            "Jax", "Malphite", "Ornn", "Shen", "Gwen", "KSante", "Riven", "Irelia", "Nasus",
            "Sion", "Volibear", "Warwick", "Yorick", "Illaoi", "Teemo", "Gnar", "Kled", "Urgot",
            "Tryndamere", "Jayce", "Kayle", "Quinn", "Gangplank", "Rumble", "Vladimir", "Wukong",
            "Yone", "Sylas", "Cho'Gath", "Poppy", "Singed", "Olaf", "Trundle", "Pantheon"),
    "jungle": ("Khazix", "Graves", "Viego", "LeeSin", "Vi", "JarvanIV", "Kayn", "Hecarim",
               "Nocturne", "Warwick", "Sejuani", "Kindred", "Elise", "Diana", "Ekko", "Evelynn",
               "Amumu", "MasterYi", "Nunu", "Rammus", "RekSai", "Rengar", "Shaco", "Skarner",
               "Belveth", "Lillia", "Fiddlesticks", "Gragas", "Ivern", "Karthus", "Nidalee",
               "Trundle", "Udyr", "XinZhao", "Zac", "Maokai", "Talon", "Shyvana", "Brand",
               "Poppy", "Volibear", "Wukong"),
    "mid": ("Ahri", "Yasuo", "Yone", "Zed", "Katarina", "Akali", "Sylas", "Orianna", "Syndra",
            "Viktor", "Vex", "LeBlanc", "Fizz", "Kassadin", "Veigar", "Lux", "Malzahar", "Anivia",
            "Azir", "Cassiopeia", "Galio", "Lissandra", "Naafiri", "Qiyana", "Ryze", "TwistedFate",
            "Xerath", "Zoe", "Talon", "Ekko", "Diana", "Swain", "Taliyah", "Neeko", "AurelionSol",
            "Annie", "Akshan", "Corki", "Vladimir"),
    "adc": ("Jinx", "Caitlyn", "KaiSa", "Ashe", "Ezreal", "Jhin", "Lucian", "MissFortune", "Xayah",
            "Aphelios", "Zeri", "Vayne", "Samira", "Draven", "Sivir", "Tristana", "Varus", "Twitch",
            "Kalista", "KogMaw", "Nilah", "Senna", "Smolder", "Ziggs"),
    "support": ("Leona", "Nautilus", "Thresh", "Lulu", "Rell", "Blitzcrank", "Pyke", "Nami",
                "Karma", "Morgana", "Milio", "Renata", "Senna", "Soraka", "Janna", "Alistar",
                "Braum", "Bard", "Rakan", "Seraphine", "Sona", "Taric", "Yuumi", "Zilean", "Zyra",
                "Brand", "Xerath", "Vel'Koz", "Maokai", "TahmKench", "Swain", "Neeko", "Poppy",
                "Shen", "Lux"),
}


def _ally_comp_bonus(dd, cid, ally_ids):
    """Small draft-fit bonus based on what your team currently lacks."""
    tags_by_id = dd.get("id2tags", {})
    ally_tags = [set(tags_by_id.get(i, [])) for i in ally_ids if i]
    have_tank = any("Tank" in t for t in ally_tags)
    have_ap = any("Mage" in t for t in ally_tags)
    have_ad = any(("Marksman" in t) or ("Assassin" in t) or ("Fighter" in t) for t in ally_tags)
    have_engage = any(("Tank" in t) or ("Fighter" in t) for t in ally_tags)
    ctags = set(tags_by_id.get(cid, []))
    b = 0.0
    if not have_tank and ("Tank" in ctags):
        b += 7.0
    if not have_ap and ("Mage" in ctags):
        b += 4.0
    if not have_ad and (("Marksman" in ctags) or ("Assassin" in ctags) or ("Fighter" in ctags)):
        b += 4.0
    if not have_engage and (("Tank" in ctags) or ("Fighter" in ctags)):
        b += 3.0
    return b


# power-curve weight by champ class (modeling): who gets scarier as the game goes long.
_SCALE_W = {"Marksman": 3.0, "Mage": 2.4, "Fighter": 2.0, "Assassin": 1.7, "Tank": 1.6, "Support": 1.4}


def game_plan(dd, ally_ids, enemy_ids):
    """WIN CONDITION bullets, adjusted to THIS game's two comps. The HEADLINE is the scaling
    verdict — who gets stronger the longer it goes, i.e. WHEN you have to win — computed from
    each comp's power-curve profile (champ classes). Behind it, the situational reads: damage
    split, frontline, engage. Returns [] when there isn't enough to say."""
    tags = dd.get("id2tags", {})

    def prof(ids):
        rows = [set(tags.get(i, [])) for i in ids if i]
        return {
            "n": len(rows),
            "ad": sum(1 for s in rows if ("Marksman" in s or "Fighter" in s or "Assassin" in s) and "Mage" not in s),
            "ap": sum(1 for s in rows if "Mage" in s),
            "front": sum(1 for s in rows if "Tank" in s),
            "engage": sum(1 for s in rows if ("Tank" in s) or ("Fighter" in s)),
            "scale": (sum(max((_SCALE_W.get(t, 1.8) for t in s), default=1.8) for s in rows)
                      / max(1, len(rows))),
        }
    them, me = prof(enemy_ids), prof(ally_ids)
    out = []
    # headline: the scaling verdict = WHEN you win. Meaningful gap only (0.25+ on the avg curve).
    if me["n"] >= 4 and them["n"] >= 4:
        d = me["scale"] - them["scale"]
        if d >= 0.25:
            out.append("YOU OUTSCALE — don't coinflip early: play clean, hit 3 items, win the late game.")
        elif d <= -0.25:
            out.append("THEY OUTSCALE — your win is EARLY: snowball, force objectives, end before 3 items.")
    if them["n"] >= 3:
        if them["ad"] >= 3 and them["ad"] >= them["ap"] * 2:
            out.append("Enemy damage is mostly AD — an early armor item swings fights.")
        elif them["ap"] >= 3 and them["ap"] >= them["ad"] * 2:
            out.append("Enemy damage is mostly AP — an early MR item swings fights.")
    if them["n"] >= 4 and them["front"] == 0:
        out.append("They have no real frontline — dive their carries, win the chaos.")
    if them["engage"] >= 3:
        out.append("Heavy engage comp — respect all-ins; hold summs/peel for their dive.")
    elif them["n"] >= 4 and them["engage"] <= 1:
        out.append("Low enemy engage — you pick the fights; poke, then all-in when they group.")
    if me["n"] >= 4 and me["front"] == 0:
        out.append("No frontline on your team — play for picks, avoid messy 5v5s.")
    return out[:3]


MIN_MASTERY = 12000     # only suggest champs with at least this many mastery POINTS — the
                        # climb line: sub-12k picks win ~44% vs 51%+ past it (1M-game study)
PREF_MASTERY = 30000    # ...preferring 30k+ ("real comfort") first


_FIT_WARM = {"done": False}      # the deep personal-fit read runs once per overlay session


def _mates(ally_ids, my_cid):
    """Your team's champs WITHOUT your own hover. suggest_champs treats every ally champ as
    unavailable and as comp already covered — and your own hovered champ is an ally champ, so
    leaving it in makes the whole recommendation move every time you hover something. The
    answer to "what's good this game" must not depend on what you're currently holding."""
    return [c for c in (ally_ids or []) if c and c != my_cid]


def suggest_champs(dd, role, ally_ids, enemy_ids, topn=4, fam=None):
    """A few role-appropriate champ suggestions for champ select, scored by enemy counters
    (op.gg) + ally comp fit. When `fam` (a {championId: masteryPOINTS} map, pooled across all
    your accounts) is given, it ONLY suggests champs with MIN_MASTERY+ points (the 12k climb
    line — sub-12k picks win ~44%), preferring 30k+ comfort first. If mastery is unavailable
    (client closed / API down) it falls back to the meta ranking so the section isn't empty."""
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    if role not in _ROLE_FALLBACK:
        return []
    ally_ids = tuple(sorted(i for i in ally_ids if i))
    enemy_ids = tuple(sorted(i for i in enemy_ids if i))
    have_fam = bool(fam)
    elig = {c: pts for c, pts in (fam or {}).items() if (pts or 0) >= MIN_MASTERY}   # 12k+ points only
    ck = (role, ally_ids, enemy_ids, have_fam, frozenset(elig.items()))
    if ck in _PICK_CACHE:
        return _PICK_CACHE[ck]
    banned = set(ally_ids) | set(enemy_ids)
    scores = {}
    # Enemy-adaptive score: champs that op.gg lists as strong into the locked enemy picks.
    for eid in enemy_ids:
        try:
            d = lb.opgg(eid, role)
        except Exception:
            continue
        for c in d.get("counters", []):
            cid = c.get("champion_id")
            play = c.get("play", 0) or 0
            if not cid or cid in banned or play < 40:
                continue
            enemy_wr = (c.get("win", 0) / play) * 100.0
            ctr_wr = max(0.0, min(100.0, 100.0 - enemy_wr))
            sc = scores.setdefault(cid, {"sum": 0.0, "n": 0, "play": 0, "comp": 0.0})
            sc["sum"] += ctr_wr
            sc["n"] += 1
            sc["play"] += play
    # Ally-adaptive score: prefer candidates that patch missing comp pieces.
    for cid, sc in list(scores.items()):
        sc["comp"] = _ally_comp_bonus(dd, cid, ally_ids)
    for nm in _ROLE_FALLBACK[role]:
        cid = dd["name2id"].get(dd["norm"](nm))
        if not cid or cid in banned:
            continue
        sc = scores.setdefault(cid, {"sum": 50.0, "n": 1, "play": 0, "comp": 0.0})
        sc["comp"] = max(sc.get("comp", 0.0), _ally_comp_bonus(dd, cid, ally_ids))

    def _key(kv):
        cid, s = kv
        base = (s["sum"] / max(1, s["n"])) + s.get("comp", 0.0)
        pts = elig.get(cid, 0)                 # 30k+ comfort first, then points, then meta
        return (pts >= PREF_MASTERY, pts, base, s["play"])
    ranked = sorted(scores.items(), key=_key, reverse=True)
    if have_fam:
        # HARD mastery gate: only champs with 12k+ points. No meta fallback — better to show fewer
        # than to suggest a champ you don't play.
        picked = [cid for cid, _ in ranked if cid in elig and cid not in banned][:topn]
    else:
        picked = [cid for cid, _ in ranked if cid not in banned][:topn]
        if len(picked) < topn:                 # mastery unknown -> old meta fill so it's not empty
            for nm in _ROLE_FALLBACK[role]:
                cid = dd["name2id"].get(dd["norm"](nm))
                if cid and cid not in banned and cid not in picked:
                    picked.append(cid)
                if len(picked) >= topn:
                    break
    _PICK_CACHE[ck] = picked
    return picked


_BAN_CACHE = {}


def suggest_bans(dd, my_cid, role, taken=(), topn=3):
    """Good bans for YOUR champ: op.gg counters you statistically lose to (your WR into
    them, min sample), boosted when the counter is itself strong this patch (their own
    overall WR in your role - the 'extremely OP' factor). Skips already banned/picked."""
    if not my_cid:
        return []
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    if not role:                                   # blind pick / no assigned position -> the
        try:                                       # champ's most-played role (else no data at all,
            import lolitems as _li                 # which showed as 'lock or hover' despite a lock)
            role = _li.primary_role(dd, my_cid)
        except Exception:
            role = "mid"
    ck = (my_cid, role)
    if ck in _BAN_CACHE:
        cands = _BAN_CACHE[ck]
    else:
        try:
            d = lb.opgg(my_cid, role)
        except Exception:
            return []
        raw = []
        for c in d.get("counters", []):
            play = c.get("play", 0) or 0
            if not c.get("champion_id") or play < 60:
                continue
            my_wr = (c.get("win", 0) / play) * 100.0
            if my_wr < 49.0:                       # you actually lose this matchup
                raw.append((c["champion_id"], my_wr, play))
        raw.sort(key=lambda x: x[1])               # hardest counters first
        cands = []
        for cid, my_wr, play in raw[:6]:            # OP-boost only the finalists (cached calls)
            op = 0.0
            try:
                av = (lb.opgg(cid, role).get("summary") or {}).get("average_stats") or {}
                op = max(0.0, (float(av.get("win_rate") or 0.5) * 100.0) - 50.0)
            except Exception:
                pass
            cands.append((cid, (49.0 - my_wr) * 2.0 + op * 1.5, my_wr))
        cands.sort(key=lambda x: -x[1])
        if len(_BAN_CACHE) > 32:
            _BAN_CACHE.clear()
        _BAN_CACHE[ck] = cands
    out = [(cid, my_wr) for cid, _s, my_wr in cands if cid not in set(taken)]
    return out[:topn]


_TEAM_BAN_CACHE = {}


def _champ_threats(dd, cid, role):
    """[(enemy_cid, our_wr, play)] — the matchups this champ statistically LOSES (op.gg,
    min sample), i.e. the champs that threaten whoever hovers it. Cached per (champ, role)."""
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    if not role:
        try:
            import lolitems as _li
            role = _li.primary_role(dd, cid)
        except Exception:
            role = "mid"
    key = ("thr", cid, role)
    if key in _TEAM_BAN_CACHE:
        return _TEAM_BAN_CACHE[key]
    out = []
    try:
        d = lb.opgg(cid, role)
        for c in d.get("counters", []):
            play = c.get("play", 0) or 0
            if not c.get("champion_id") or play < 60:
                continue
            wr = (c.get("win", 0) / play) * 100.0
            if wr < 49.0:                          # a matchup we actually lose
                out.append((c["champion_id"], wr, play))
    except Exception:
        out = []
    if len(_TEAM_BAN_CACHE) > 64:
        _TEAM_BAN_CACHE.clear()
    _TEAM_BAN_CACHE[key] = out
    return out


def _role_presence(dd):
    """{(cid, 'TOP'|'JUNGLE'|...): (pick_rate 0..1, win_rate 0..1)} from op.gg's all-champ
    ranking (one cached fetch). How LIKELY each champ is to actually show up in a role —
    the missing half of a good ban."""
    out = {}
    try:
        for ent in lb.opgg_all_ranked():
            cid = ent.get("id")
            if not cid:
                continue
            for p in (ent.get("positions") or []):
                stx = p.get("stats") or {}
                pr = float(stx.get("pick_rate") or 0.0)
                wr = float(stx.get("win_rate") or 0.5)
                if pr > 1.5:                        # tolerate percent-scaled feeds
                    pr /= 100.0
                if wr > 1.5:
                    wr /= 100.0
                out[(int(cid), (p.get("name") or "").upper())] = (pr, wr)
    except Exception:
        return {}
    return out


SELF_BAN_W = 1.8           # your own lane's counters weigh ~2x a teammate's in the ban EV


def team_bans(dd, hovers, taken=(), topn=3, self_cid=0):
    """Good bans for the WHOLE TEAM's draft, ranked by EXPECTED VALUE:
      threat = (how hard they counter each hover) x (their PICK RATE in that role),
    summed over the team — with YOUR champ's counters weighted SELF_BAN_W (~2x): the ban
    protects your own game first, but a champ that's merely annoying for you while it
    absolutely dumpsters two teammates still climbs the list, and a niche 4%-pick
    hard-counter still loses to a popular counter you'll actually face. Finalists get a
    small 'strong this patch' boost. hovers = [(cid, role), ...]; self_cid marks which
    hover is YOU. Returns [(cid, worst_ally_wr), ...]."""
    hovs = [(c, r) for c, r in (hovers or []) if c]
    if not hovs:
        return []
    pres = _role_presence(dd)
    threat, worst = {}, {}
    for cid, role in hovs:
        rkey = _OPGG_POS.get(lb.ROLE.get((role or "").lower(), ""), "")
        w_self = SELF_BAN_W if (self_cid and cid == self_cid) else 1.0
        for e_cid, wr, _play in _champ_threats(dd, cid, role):
            pr = pres.get((e_cid, rkey), (None, None))[0] if rkey else None
            presence = pr if pr is not None else 0.10   # no data -> assume average presence
            threat[e_cid] = threat.get(e_cid, 0.0) + (49.0 - wr) * max(0.01, presence) * 10.0 * w_self
            if wr < worst.get(e_cid, 100.0):
                worst[e_cid] = wr                  # the most-countered ally's WR (display)
    if not threat:
        return []
    taken = set(taken)
    role0 = _OPGG_POS.get(lb.ROLE.get((hovs[0][1] or "").lower(), ""), "")
    scored = []
    for e_cid, s in threat.items():
        if e_cid in taken:
            continue
        wr_meta = pres.get((e_cid, role0), (0.0, 0.5))[1]
        s += max(0.0, wr_meta * 100.0 - 50.0) * 0.3     # OP-this-patch nudge, never the driver
        scored.append((e_cid, s))
    scored.sort(key=lambda x: -x[1])
    return [(e, worst.get(e, 0.0)) for e, _s in scored[:topn]]


def _ban_icon(img, dd, cid, x, y, size, slash=True):
    """A grayed champ icon with a red slash - the universal 'banned' visual."""
    ic = get_icon(dd, cid, size)
    if not ic:
        return
    try:
        gray = ImageOps.grayscale(ic).convert("RGBA")
        gray.putalpha(ic.getchannel("A"))
        img.paste(gray, (x, y), gray)
        if slash:
            dr = ImageDraw.Draw(img)
            dr.line([x + 3, y + size - 3, x + size - 3, y + 3], fill=RED, width=2)
    except Exception:
        img.paste(ic, (x, y), ic)


def _draw_draft_band(d, img, dd, x0, y0, w, bans, enemy_picks, ban_ideas):
    """Champ-select intel band: GOOD BANS (your hardest counters) · the lobby's bans · any
    visible enemy picks. Its own card, BAD rail (UIDESIGN §5.1 - it's a ban/draft surface)."""
    _railed_card(d, (x0, y0, x0 + w, y0 + 52), RED, fill=SURFACE, outline=PEDGE, width=1, r=9)
    x = x0 + 14
    # --- good bans ---
    d.text((x, y0 + 6), "GOOD BANS", font=display_font(9, True), fill=GOLD)
    if ban_ideas:
        for cid, my_wr in ban_ideas[:3]:
            ic = get_icon(dd, cid, 28)
            if ic:
                img.paste(ic, (x, y0 + 19), ic)
            d.text((x + 32, y0 + 25), f"{my_wr:.0f}%", font=display_font(9, True), fill=RED)
            x += 62
    elif ban_ideas is not None:                    # champ known, but nothing statistically scary
        d.text((x, y0 + 26), "no hard counters — ban comfort/meta", font=font(10), fill=MUTED)
        x += 150
    else:                                          # truly no champ hovered yet
        d.text((x, y0 + 26), "hover your champ for ban ideas", font=font(10), fill=MUTED)
        x += 150
    x = max(x, x0 + 210) + 18
    d.line([x - 12, y0 + 8, x - 12, y0 + 44], fill=PEDGE, width=1)
    # --- lobby bans ---
    bm, bt = (bans or ({}, {}))[0] or [], (bans or ((), ()))[1] or []
    d.text((x, y0 + 6), "BANS", font=display_font(9, True), fill=INFO)
    bx = x
    for cid in bm[:5]:
        _ban_icon(img, dd, cid, bx, y0 + 19, 26)
        bx += 30
    if bm and bt:
        d.text((bx + 3, y0 + 24), "·", font=font(12, 1), fill=MUTED)
        bx += 14
    for cid in bt[:5]:
        _ban_icon(img, dd, cid, bx, y0 + 19, 26)
        bx += 30
    if not (bm or bt):
        d.text((x, y0 + 26), "none yet", font=font(10), fill=MUTED)
        bx = x + 70
    # --- enemy picks (visible in some queues / after reveal) ---
    x = max(bx + 26, x0 + 560)
    d.line([x - 12, y0 + 8, x - 12, y0 + 44], fill=PEDGE, width=1)
    d.text((x, y0 + 6), "ENEMY PICKS", font=display_font(9, True), fill=RED)
    if enemy_picks:
        for cid in enemy_picks[:5]:
            ic = get_icon(dd, cid, 26)
            if ic:
                img.paste(ic, (x, y0 + 19), ic)
            x += 30
    else:
        d.text((x, y0 + 26), "hidden in ranked", font=font(10), fill=MUTED)


VW = 384                 # width of the vertical (docked) champ-select panel


# High-priority solo-queue bans — the "ban to not suffer" champs, used when you don't have a
# pick yet (bans happen before you hover in draft) so auto-ban / GOOD BANS still have a target.
# Popularity-ordered, evergreen-ish; unknown names resolve to nothing and are skipped.
_BAN_PRIORITY = ("Yasuo", "Yone", "Zed", "Katarina", "Fizz", "MasterYi", "Akali", "LeBlanc",
                 "Vayne", "Draven", "Kassadin", "Darius", "Teemo", "Tryndamere", "Nasus",
                 "Singed", "Shaco", "Evelynn", "Kayn", "Briar", "Ambessa", "Naafiri", "Aatrox",
                 "Riven", "Irelia", "Kled", "Fiora", "Camille", "Nilah", "Smolder")


_OPGG_POS = {"top": "TOP", "jungle": "JUNGLE", "mid": "MID", "adc": "ADC", "support": "SUPPORT"}
BAN_MIN_PLAY = 3000     # min games for a champ's role stats to count as a "real" ban target


def general_bans(dd, role, taken=(), topn=3):
    """Ban ideas for the ban phase (before you've picked a champ): the highest WIN-RATE champs
    in YOUR role right now, straight from op.gg — so it tracks the live patch instead of a stale
    list. [(cid, wr%), ...]; falls back to a tiny hardcoded backstop only if op.gg is down."""
    role = lb.ROLE.get((role or "").lower(), (role or "").lower())
    pos = _OPGG_POS.get(role)
    taken = set(taken or [])
    rows = []
    if pos:
        try:
            champs = lb.opgg_all_ranked()
        except Exception:
            champs = []
        for ch in (champs or []):
            cid = ch.get("id")
            if not cid or cid in taken:
                continue
            p = next((pp for pp in (ch.get("positions") or []) if pp.get("name") == pos), None)
            if not p:
                continue                         # this champ isn't played in your role
            st = p.get("stats") or {}
            wr, play = st.get("win_rate"), st.get("play", 0) or 0
            if wr is None:                       # per-position stat missing -> overall
                avg = ch.get("average_stats") or {}
                wr, play = avg.get("win_rate"), avg.get("play", 0) or 0
            if wr:
                rows.append((cid, wr, play))
        # meaningful-sample champs first (so a niche 55% one-trick doesn't outrank the meta),
        # then by win rate.
        rows.sort(key=lambda x: (x[2] >= BAN_MIN_PLAY, x[1]), reverse=True)
    out = [(cid, wr * 100.0) for cid, wr, _ in rows[:topn]]
    if not out:                                  # op.gg unavailable -> minimal safe backstop
        for nm in _BAN_PRIORITY:
            cid = dd["name2id"].get(dd["norm"](nm))
            if cid and cid not in taken:
                out.append((cid, None))
            if len(out) >= topn:
                break
    return out


def _auto_chip(d, x, y, on, hits, action="action:toggle_auto_import", label="AUTO"):
    """AUTO toggle PILL (UIDESIGN §5.1): on = GOOD outline + dot, off = FAINT outline."""
    f = font(9, 1)
    h = 22
    dot = 12 if on else 0
    w = int(d.textlength(label, font=f)) + 16 + dot
    _rrect(d, (x, y, x + w, y + h), h // 2, fill=(_dim(GREEN, 0.16) if on else RAISED),
           outline=(GREEN if on else FAINT), width=1)
    tx = x + 9
    if on:
        d.ellipse((tx, y + h // 2 - 3, tx + 6, y + h // 2 + 3), fill=GREEN)
        tx += dot
    d.text((tx, y + 5), label, font=f, fill=GREEN if on else MUTED)
    if hits is not None:
        hits.append((x, y, x + w, y + h, action))
    return w


def _rune_chip(d, x, y, idx, wr, sel, hits):
    """A little clickable rune-set PILL: '1 · 52%'. Selected one gets the GOOD dot treatment
    (same on/off language as the AUTO chip - it's a toggle too)."""
    label = f"{idx + 1} · {wr:.0f}%"
    f = font(9, 1)
    h = 20
    dot = 11 if sel else 0
    w = int(d.textlength(label, font=f)) + 14 + dot
    _rrect(d, (x, y, x + w, y + h), h // 2, fill=(_dim(GREEN, 0.16) if sel else RAISED),
           outline=(GREEN if sel else FAINT), width=1)
    tx = x + 8
    if sel:
        d.ellipse((tx, y + h // 2 - 3, tx + 6, y + h // 2 + 3), fill=GREEN)
        tx += dot
    d.text((tx, y + 3), label, font=f, fill=GREEN if sel else MUTED)
    if hits is not None:
        hits.append((x, y, x + w, y + h, f"action:rune:{idx}"))
    return w


def render_cs_vertical(dd, my_cid, my_role, allies, build, suggestions=None, bans=None,
                       enemy_picks=None, ban_ideas=None, dodge=None, auto_import=False,
                       note=None, auto_ban=False, fit_notes=None, rune_note=None):
    """The champ-select helper as a TALL panel meant to dock LEFT of the League client:
    your champ + runes + core icons + import, suggested picks, good bans, lobby bans, and
    your team - stacked vertically. Returns a PIL image with .hitmap for the import button."""
    H = 1130
    img = Image.new("RGB", (VW, H), BG)
    d = ImageDraw.Draw(img)
    hits = []
    if build:
        build = pick_rune(build)                   # show/import the selected rune set (#3)
    # header: splash strip + champ + role — "your champ" card, ember rail (UIDESIGN §5.1)
    if my_cid:
        strip = get_splash(dd, my_cid, (VW, 84))
        if strip:
            img.paste(strip, (0, 0))
            shade = Image.new("L", (VW, 84), 0)
            sd = ImageDraw.Draw(shade)
            for yy in range(84):
                sd.line([(0, yy), (VW, yy)], fill=min(255, 140 + int(yy * 1.5)))
            img.paste(Image.new("RGB", (VW, 84), BG), (0, 0), shade)
    d.rectangle([0, 10, skin.RAIL, 74], fill=GOLD)              # ember identity rail
    ic = get_icon(dd, my_cid, 52)
    if ic:
        img.paste(ic, (14, 14), ic)
    nm_f = display_font(20, True)
    champ_nm = dd["id2name"].get(my_cid, "pick a champ")
    d.text((78, 12), champ_nm, font=nm_f, fill=GOLD)
    if my_role:                                      # role chip pill next to the champ name
        rl_txt = my_role.upper()
        rl_f = font(9, True)
        rl_w = d.textlength(rl_txt, font=rl_f)
        rx0 = 78 + d.textlength(champ_nm, font=nm_f) + 10
        _rrect(d, (rx0, 18, rx0 + rl_w + 14, 34), 8, fill=_dim(ARC, 0.18), outline=ARC, width=1)
        d.text((rx0 + 7, 21), rl_txt, font=rl_f, fill=ARC)
    if build:
        d.text((78, 44), f"{build['wr']:.1f}%  {build['tier']}", font=display_font(11, True), fill=TEXT)
    _brand_row(d, VW - 12, 6, size=8, anchor="ra")
    y = 92
    if dodge and dodge.get("verdict") == "DODGE":
        # THE DODGE CALL (core/loldodge) as a railed card, never inline text (UIDESIGN §5.1):
        # BAD rail + fill, the LP verdict on top and the receipt for it underneath.
        _railed_card(d, (10, y, VW - 10, y + 44), RED, fill=_dim(RED, 0.14), outline=RED, width=1, r=8)
        head = "⚠ " + (dodge.get("headline") or "DODGE")
        d.text((VW // 2, y + 15), head, font=font(11, 1, head), fill=RED, anchor="mm")
        d.text((VW // 2, y + 32), (dodge.get("reason") or "")[:74],
               font=font(9), fill=_dim(RED, 0.86), anchor="mm")
        y += 52
    elif dodge and dodge.get("chip"):
        # ...and when it says PLAY it says so QUIETLY, in the same spot every draft, so the
        # red card is never the first you hear of the read.
        d.text((VW // 2, y + 8), dodge["chip"], font=font(9),
               fill=_wr_color(dodge.get("p", 0.5) * 100), anchor="mm")
        y += 22
    # runes + build card — quiet rail; the import button is THE primary action (ember pill)
    if build:
        card_h = 214 + (20 if rune_note else 0)
        _railed_card(d, (10, y, VW - 10, y + card_h), LINE, fill=SURFACE, outline=PEDGE, width=1)
        x = 24
        d.text((x, y + 10), "RUNES", font=display_font(9, True), fill=GOLD)
        opts = build.get("rune_options") or []
        if len(opts) > 1:                                  # rune-set picker (#3): click to switch
            cxr = 78
            for oi, opt in enumerate(opts):
                cxr += _rune_chip(d, cxr, y + 6, oi, opt.get("rune_wr", 0.0),
                                  oi == get_rune_idx(), hits) + 6
        d.text((x, y + 24), build.get("keystone", ""), font=font(14, 1), fill=TEXT)
        minor = "  ·  ".join(r for r in build.get("primary", [])[1:] if r)
        for i, ln in enumerate(_wrap(minor, font(10), VW - 48)[:2]):
            d.text((x, y + 46 + i * 14), ln, font=font(10), fill=MUTED)
        sec = "  ·  ".join(r for r in build.get("secondary", []) if r)
        d.text((x, y + 76), f"{build.get('secondary_tree', '')}: {sec}"[:60], font=font(10), fill=INFO)
        shards = " / ".join(s for s in build.get("shards", []) if s)
        d.text((x, y + 92), f"Shards: {shards}", font=font(10), fill=MUTED)
        # ADAPTIVE RUNES: say WHY this page and not the most-played one, in op.gg's numbers.
        # Everything below the divider shifts down by RN when the note is showing.
        rn = 0
        if rune_note:
            rn = 20
            d.text((x, y + 105), "ADAPTED", font=display_font(8, True), fill=ARC)
            for i, ln in enumerate(_wrap(rune_note, font(9), VW - 108)[:2]):
                d.text((x + 54, y + 104 + i * 11), ln, font=font(9), fill=MUTED)
        d.line([x, y + 110 + rn, VW - 24, y + 110 + rn], fill=PEDGE, width=1)
        d.text((x, y + 116 + rn), "CORE BUILD", font=display_font(9, True), fill=GOLD)
        ix = x
        for j, iid in enumerate((build.get("core_ids") or [])[:4]):
            iic = get_item_icon(dd, iid, 32)
            if iic:
                _rrect(d, (ix - 1, y + 131 + rn, ix + 33, y + 165 + rn), 6, outline=PEDGE, width=1)
                img.paste(iic, (ix, y + 132 + rn), iic)
            if j < min(len(build.get("core_ids") or []), 4) - 1:
                d.text((ix + 37, y + 141 + rn), "›", font=font(12, 1), fill=MUTED)
            ix += 48
        d.text((x, y + 172 + rn), "Summs: " + " / ".join(build.get("summs", [])),
               font=font(10), fill=MUTED)
        sk = [s for s in build.get("skills", []) if s]
        if sk:
            d.text((x + 170, y + 172 + rn), "Max: " + " > ".join(sk), font=font(10), fill=MUTED)
        bx, by, bw, bh = x, y + 186 + rn, 160, 22
        _rrect(d, (bx, by, bx + bw, by + bh), bh // 2, fill=GOLD)
        d.text((bx + bw // 2, by + bh // 2), "⇩ Import runes + summs", font=font(9, 1, "⇩"), fill=BG, anchor="mm")
        hits.append((bx, by, bx + bw, by + bh, "action:import_build"))
        aw = _auto_chip(d, bx + bw + 8, by, auto_import, hits)
        if note:
            d.text((bx + bw + 8 + aw + 8, by + 5), note, font=font(9, text=note), fill=GREEN)
        y += card_h + 10
    else:
        d.text((20, y + 6), "lock or hover a champ for runes + build", font=font(11), fill=MUTED)
        y += 30
    # GAME PLAN — comp win-conditions, shown the moment the enemy team locks in (draft).
    plan = game_plan(dd, [c for c, _ in (allies or []) if c], enemy_picks or [])
    if plan:
        wrapped = []
        for b in plan:
            wrapped += _wrap("▸ " + b, font(10), VW - 42)[:2]
        ph_ = 22 + len(wrapped) * 14 + 4
        _railed_card(d, (10, y, VW - 10, y + ph_ - 4), LINE, fill=SURFACE, outline=PEDGE, width=1, r=9)
        d.text((22, y + 6), "WIN CONDITION", font=display_font(9, True), fill=GOLD)
        for i, ln in enumerate(wrapped):
            d.text((22, y + 22 + i * 14), ln, font=font(10, text="▸"), fill=TEXT)
        y += ph_ + 6
    # suggested picks (horizontal icons) — click a face to HOVER it in champ select (not lock)
    d.text((20, y), "GOOD THIS GAME", font=display_font(9, True), fill=GOLD)
    if suggestions:
        d.text((VW - 12, y + 1), "click to hover", font=font(8), fill=FAINT, anchor="ra")
    xx = 20
    for cid in (suggestions or [])[:6]:
        sic = get_icon(dd, cid, 40)
        if sic:
            img.paste(sic, (xx, y + 16), sic)
        hits.append((xx, y + 16, xx + 40, y + 56, f"action:pick:{cid}"))
        xx += 50
    if not suggestions:
        d.text((20, y + 20), "suggestions load in a moment…", font=font(10), fill=MUTED)
    y += 62
    # PERSONAL FIT note (core/lolfit): why the top pick is the top pick, in YOUR numbers. A
    # promotion or a veto that can't be seen is just the app being mysterious at you.
    top = (suggestions or [None])[0]
    note = (fit_notes or {}).get(top) if top else None
    if note:
        kind, why = note
        tag = {"fresh": ("FRESH", ARC), "cold": ("COLD", RED)}.get(kind, ("", MUTED))
        nm = dd["id2name"].get(top, "?")
        d.text((20, y), tag[0], font=display_font(8, True), fill=tag[1])
        for i, ln in enumerate(_wrap(f"{nm} — {why}", font(9), VW - 76)[:2]):
            d.text((56, y + i * 11), ln, font=font(9), fill=MUTED)
        y += 24
    y += 4
    # bans/draft band — one railed card wrapping GOOD BANS + lobby BANS + ENEMY PICKS,
    # BAD rail (UIDESIGN §5.1). Numbers move to Bahnschrift; slash icons are unchanged.
    band_content_h = 74 + 52 + (52 if enemy_picks else 0)
    band_h = band_content_h + 10                  # 6px top pad + 4px bottom pad, snug not tight
    _railed_card(d, (10, y, VW - 10, y + band_h), RED, fill=SURFACE, outline=PEDGE, width=1)
    y += 6
    # good bans
    d.text((20, y), "GOOD BANS", font=display_font(9, True), fill=GOLD)
    _auto_chip(d, VW - 78, y - 3, auto_ban, hits, action="action:toggle_auto_ban", label="AUTO")
    if ban_ideas:
        xx = 20
        for cid, my_wr in ban_ideas[:3]:
            bic = get_icon(dd, cid, 34)
            if bic:
                img.paste(bic, (xx, y + 16), bic)
            lbl = f"{my_wr:.0f}%" if my_wr is not None else "ban"     # None = general priority ban
            d.text((xx + 17, y + 54), lbl, font=display_font(9, True), fill=RED, anchor="ma")
            xx += 58
    else:
        d.text((20, y + 20), "ban ideas load in a moment…", font=font(10), fill=MUTED)
    y += 68
    # lobby bans
    bm, bt = (bans or ((), ()))[0] or [], (bans or ((), ()))[1] or []
    d.text((20, y), "BANS", font=display_font(9, True), fill=INFO)
    xx = 20
    for cid in bm[:5]:
        _ban_icon(img, dd, cid, xx, y + 15, 26)
        xx += 30
    if bm and bt:
        d.text((xx + 4, y + 20), "·", font=font(12, 1), fill=MUTED)
        xx += 16
    for cid in bt[:5]:
        _ban_icon(img, dd, cid, xx, y + 15, 26)
        xx += 30
    if not (bm or bt):
        d.text((60, y), "none yet", font=font(9), fill=MUTED)
    y += 52
    # enemy picks when a queue reveals them
    if enemy_picks:
        d.text((20, y), "ENEMY PICKS", font=display_font(9, True), fill=RED)
        xx = 20
        for cid in enemy_picks[:5]:
            eic = get_icon(dd, cid, 26)
            if eic:
                img.paste(eic, (xx, y + 15), eic)
            xx += 30
        y += 52
    y += 4
    # your team — railed rows (UIDESIGN §5.2): ARC for allies, GOLD for the "me" row
    d.text((20, y), "YOUR TEAM", font=display_font(9, True), fill=ARC)
    y += 16
    for cid, role in (allies or [])[:5]:
        me = (cid == my_cid)
        _railed_card(d, (12, y, VW - 12, y + 40), GOLD if me else ARC, fill=SURFACE, outline=PEDGE, width=1, r=8)
        if cid:
            aic = get_icon(dd, cid, 30)
            if aic:
                img.paste(aic, (20, y + 5), aic)
            d.text((58, y + 11), dd["id2name"].get(cid, "?") + ("  YOU" if me else ""),
                   font=font(12, 1), fill=GOLD if me else TEXT)
        else:
            d.text((58, y + 11), "picking…", font=font(11), fill=MUTED)
        rl = lb.ROLE.get((role or "").lower(), role or "")
        if rl:
            cf = font(8, 1)
            cw_ = d.textlength(rl.upper(), font=cf)
            _rrect(d, (VW - 26 - cw_ - 12, y + 11, VW - 26, y + 27), 8, fill=RAISED, outline=PEDGE, width=1)
            d.text((VW - 32 - cw_ / 2 - 3, y + 14), rl.upper(), font=cf, fill=MUTED, anchor="ma")
        y += 46
    d.text((20, y + 6), "enemies hidden in ranked · board opens at loading screen",
           font=font(9), fill=FAINT)
    out = img.crop((0, 0, VW, min(H, y + 26)))    # trim the unused tail; panel ends after the team
    out.hitmap = hits
    out.dock_left = True                          # smiteoverlay: park this next to the client
    return out


LW = 1480                 # the LIVE board's DESIGN width; it renders scaled to its monitor
BOARD_TARGET = (1920, 1080)   # (w, h) of the monitor the board will live on — the overlay
                              # sets this at launch; the renderer sizes itself to fill it
_TAG_TONE = {"good": GREEN, "bad": RED, "neutral": MUTED, "info": INFO}


def _board_scale():
    """How much to grow the live board beyond its 1480px design width so it FILLS the
    monitor it's headed to (crisp redraw at scale, never a blurry raster upscale). Height
    is budgeted against the tallest variant (laner panel + tips); smiteoverlay's ui_scale
    still shrink-fits anything that would overflow a small window. Never below 1.0."""
    try:
        mw, mh = BOARD_TARGET
    except Exception:
        mw, mh = 1920, 1080
    return max(1.0, min((mw - 60) / 1480.0, (mh - 45) / 880.0, 1.8))


def _live_tags(dd, cid, sc, ally):
    """The loading screen's profile-read tags (smurf/OTP/tilt/first-time/…), driven by
    the live scout's data. One tag language across every Smiteless surface."""
    try:
        import lolload as llo
        kda = sc.get("kda") or {}
        g = int(kda.get("g") or 0)
        recent = sc.get("recent") or []
        # live-client role vocab (lb.ROLE) -> the scout's _ROLE vocab, so off-role can fire here
        rl = {"top": "TOP", "jungle": "JG", "mid": "MID", "adc": "BOT",
              "support": "SUP"}.get((sc.get("role") or "").lower(), "")
        row = {"champ": dd["id2name"].get(cid, "?"), "role": rl,
               "main_pos": llo._main_pos(recent), "recent": recent,
               "level": sc.get("level"),
               "rank_full": sc.get("rank"), "form": sc.get("form") or [],
               "n": int(sc.get("n") or 0), "w": int(sc.get("w") or 0),
               "cg": int(sc.get("cg") or 0), "cw": int(sc.get("cw") or 0),
               "pts": int((sc.get("mastery") or {}).get("points", 0) or 0),
               "dpg": round(kda["d"] / g, 1) if g else None,
               "perf": sc.get("perf"), "scouted": True}
        return llo._profile_tags(row, ally)
    except Exception:
        return []


def render_live_board(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map,
                      source, note="", live=True, lane_tip=None, live_gank=None):
    """The IN-GAME board, profile-grade: it sits on the second monitor for the whole game,
    so it gets the full treatment — a splash hero header, the winners-queue verdict strip,
    and five lane-matchup rows where each player is a mini profile card (art slab, riot id,
    rank + LP, last-10 form, KDA, mastery, S–F grade pill, and the same profile-read tags
    as the loading screen), with the gank verdict between them. Same inputs and hitmap
    contract as render_image's live path."""
    k = _board_scale()
    def S(v): return int(round(v * k))
    BW = S(1480)
    HERO = S(100)
    panel = bool(my_role and my_role != "jungle" and my_role in dict(ROLES))
    tip_lines = _wrap(lane_tip, font(12), BW - 60) if (panel and lane_tip) else []
    panel_h = (77 + len(tip_lines) * 18) if tip_lines else (108 if panel else 0)
    plan = game_plan(dd, list(ally_role.values()), list(enemy_role.values()))
    plan_h = (S(26) + len(plan) * S(16) + S(8)) if plan else 0
    ROW, GAP = S(92), S(8)
    rows_y = HERO + S(8) + S(58) + S(8)      # strip carries the queue read + the gank CALL
    H = rows_y + 5 * (ROW + GAP) + (panel_h + S(10) if panel_h else 0) + plan_h + S(42)
    img = Image.new("RGB", (BW, H), BG)
    d = ImageDraw.Draw(img)
    hits = []

    # ============================ HERO ============================
    if my_cid:
        splash = get_splash(dd, my_cid, (BW, HERO))
        if splash:
            img.paste(splash, (0, 0))
            img.paste(BG, (0, 0, BW, HERO), Image.new("L", (BW, HERO), 96))
            _vshade(img, (0, HERO - S(60), BW, HERO), BG, 0, 235)
            _hshade(img, (0, 0, S(520), HERO), BG, 170, 0)
        ic = get_icon(dd, my_cid, S(56))
        if ic:
            img.paste(ic, (S(22), S(22)), ic)
            msc = scout_map.get((my_cid, True))
            murl = _profile_url(msc.get("riot_id")) if msc else None
            if murl:
                hits.append((S(22), S(22), S(78), S(78), murl))
        nm = dd["id2name"].get(my_cid, "?")
        d.text((S(92), S(24)), nm, font=display_font(S(26), True), fill=TEXT)
        rf = display_font(S(12), True)
        rx = S(96) + d.textlength(nm, font=display_font(S(26), True))
        _rrect(d, (rx, S(30), rx + d.textlength((my_role or "?").upper(), font=rf) + S(16), S(50)),
               S(10), fill=_dim(GOLD, 0.20), outline=_dim(GOLD, 0.6), width=1)
        d.text((rx + S(8), S(34)), (my_role or "?").upper(), font=rf, fill=GOLD)
        if build:
            bl = f"{build['keystone']}   ·   " + " > ".join(x for x in build['core'] if x) \
                 + "   ·   " + " / ".join(build['summs'])
            d.text((S(92), S(62)), bl[:120], font=font(S(12)), fill=MUTED)
            d.text((BW - S(20), S(24)), f"{build['wr']:.1f}%  {build['tier']}",
                   font=display_font(S(16), True), fill=TEXT, anchor="ra")
    else:
        d.text((S(22), S(24)), "SPECTATING", font=display_font(S(26), True), fill=GOLD)
        d.text((S(22), S(62)), "both teams scouted — no personal build (replay/spectator mode)",
               font=font(S(12)), fill=MUTED)
    _brand_row(d, BW - S(20), HERO - S(28), size=S(10), anchor="ra", suffix="· " + source,
               suffix_col=FAINT)
    d.line([(0, HERO - 1), (BW, HERO - 1)], fill=_dim(GOLD, 0.55), width=1)

    # gank scores first: the labels are RELATIVE (see rank_gank_labels) and the verdict
    # strip's CALL line needs them before it draws
    my_kit = gank_kit(dd, my_cid) if GANK_KIT_ON else 0.0
    gscores = {}
    for role, _lbl in ROLES:
        e_cid = enemy_role.get(role)
        if not e_cid or role == my_role:
            continue
        es = scout_map.get((e_cid, False))
        a = (es["n"], es["w"], es["cg"], es["cw"], es.get("form")) if es else (0, 0, 0, 0, None)
        s = gank_score(lanes.get(role), *a, self_kit=my_kit)
        if live_gank:
            s += float(live_gank.get(role, 0.0))
        gscores[role] = s
    glabels = rank_gank_labels(gscores)

    # ============================ VERDICT STRIP ============================
    qr = queue_prediction(my_cid, scout_map)
    ga, ge = team_avg_grades(scout_map)
    sy = HERO + S(8)
    _railed_card(d, (S(14), sy, BW - S(14), sy + S(58)), qr.get("fill") or ARC, fill=SURFACE,
                 outline=PEDGE, width=1)
    d.text((S(32), sy + S(8)), qr["text"], font=display_font(S(13), True), fill=qr["fill"])
    d.text((BW / 2, sy + S(16)), "YOUR TEAM", font=display_font(S(11), True), fill=GREEN, anchor="rm")
    d.text((BW / 2 + S(4), sy + S(16)), "  vs  ENEMY", font=display_font(S(11), True), fill=RED, anchor="lm")
    if ga and ge:
        d.text((BW - S(30), sy + S(8)), f"team grades  {ga}  vs  {ge}",
               font=display_font(S(12), True), fill=TEXT, anchor="ra")
    call = gank_directive(dd, gscores, glabels, enemy_role)
    if call:                                     # §6: the decision, not the math
        ctxt, ccol = call
        d.text((S(32), sy + S(32)), "CALL", font=display_font(S(11), True), fill=FAINT)
        d.text((S(78), sy + S(31)), ctxt, font=display_font(S(13), True), fill=ccol)

    # ============================ LANE ROWS ============================
    cxc = BW // 2
    CTR = S(128)                                  # center matchup column width
    half = (BW - S(28) - CTR) // 2                # each team's half-row width
    AW = S(104)                                   # art slab width

    def _pill(x, y, txt, col, maxx, anchor="la", primary=False):
        """Tag chip, same visual language as the loading screen: first/sharpest tag is a
        filled chip, the rest are quiet outlines — one loud thing per player."""
        f = font(S(10), 1)
        w = d.textlength(txt, font=f) + S(14)
        if anchor == "ra":
            x0 = x - w
            if x0 < maxx:
                return None
        else:
            x0 = x
            if x0 + w > maxx:
                return None
        if primary:
            _rrect(d, (x0, y, x0 + w, y + S(18)), S(9), fill=_dim(col, 0.24))
            d.text((x0 + S(7), y + S(3)), txt, font=f, fill=col)
        else:
            _rrect(d, (x0, y, x0 + w, y + S(18)), S(9), fill=SUNKEN, outline=_dim(col, 0.35), width=1)
            d.text((x0 + S(7), y + S(3)), txt, font=f, fill=_dim(col, 0.82))
        return (x0 - S(6)) if anchor == "ra" else (x0 + w + S(6))

    def _half(x0, y, cid, sc, ally, is_me, mirror):
        """One player as a mini profile card half. mirror=True -> enemy side (art far right,
        text right-anchored toward the center column)."""
        if not cid:
            return
        grade, gcol = player_rating(sc)
        rail = GOLD if is_me else (GREEN if ally else RED)
        _rrect(d, (x0, y, x0 + half, y + ROW), S(10), fill=SURFACE, outline=PEDGE, width=1)
        ax = x0 + half - AW if mirror else x0
        art = get_splash(dd, cid, (AW, ROW))
        if art:
            mask = Image.new("L", (AW, ROW), 0)
            mm = ImageDraw.Draw(mask)
            mm.rounded_rectangle((0, 0, AW, ROW), radius=S(10), fill=255)
            mm.rectangle((0, 0, AW // 2, ROW) if mirror else (AW // 2, 0, AW, ROW), fill=255)
            img.paste(art, (ax, y), mask)
            grad = Image.new("L", (AW, 1))
            ramp = [int(max(0, (i - AW * 0.40) / (AW * 0.60)) * 255) for i in range(AW)]
            grad.putdata(ramp[::-1] if mirror else ramp)
            img.paste(Image.new("RGB", (AW, ROW), SURFACE), (ax, y), grad.resize((AW, ROW)))
        else:
            ic = get_icon(dd, cid, S(44))
            if ic:
                img.paste(ic, (ax + (AW - S(44)) // 2, y + (ROW - S(44)) // 2), ic)
        rx = (x0 + half - S(4), y + S(8), x0 + half, y + ROW - S(8)) if mirror \
            else (x0, y + S(8), x0 + S(4), y + ROW - S(8))
        d.rounded_rectangle(rx, 2, fill=rail)

        tx = x0 + half - int(AW * 0.70) if mirror else x0 + int(AW * 0.70)
        anc = "ra" if mirror else "la"
        sgn = -1 if mirror else 1
        name = dd["id2name"].get(cid, "?")
        nf = display_font(S(16), True)
        d.text((tx, y + S(8)), name, font=nf, fill=(GOLD if is_me else TEXT), anchor=anc)
        gx = tx + sgn * (d.textlength(name, font=nf) + S(22))
        if is_me:
            d.text((gx - sgn * S(6), y + S(11)), "YOU", font=font(S(9), 1), fill=GOLD, anchor=anc)
            gx += sgn * S(38)
        if grade:
            _grade_chip(d, gx, y + S(18), grade, gcol, k=k)
            d.text((gx + sgn * S(16), y + S(13)), f"{int((sc or {}).get('n') or 0)}g",
                   font=font(S(8), 1), fill=_dim(gcol, 0.7), anchor=anc)
        # line 2: riot id + rank
        who = ((sc or {}).get("riot_id") or "").split("#")[0]
        rtext, rcol = rank_str((sc or {}).get("rank"))
        pf = font(S(11), 1)
        if who:
            d.text((tx, y + S(34)), who[:18], font=pf, fill=MUTED, anchor=anc)
            rx2 = tx + sgn * (d.textlength(who[:18], font=pf) + S(10))
        else:
            rx2 = tx
        if rtext:
            d.text((rx2, y + S(34)), rtext, font=display_font(S(12), True), fill=rcol, anchor=anc)
        # line 3: L10 record · KDA · mastery
        if sc:
            n, w = int(sc.get("n") or 0), int(sc.get("w") or 0)
            bits = []
            if n:
                wr = w / n * 100
                bits.append((f"L10 {w}-{n - w} {wr:.0f}%", _wr_color(wr)))
            kda = sc.get("kda") or {}
            if kda.get("g"):
                bits.append((f"{(kda['k'] + kda['a']) / max(1, kda['d']):.1f} KDA", TEXT))
            m = sc.get("mastery") or {}
            if m.get("points"):
                bits.append((f"M{m.get('level', 0)} {_abbr_pts(m['points'])}",
                             _mastery_color(m["points"])))
            elif int(sc.get("cg") or 0) == 0 and n:
                bits.append(("off-champ", REDWR))
            if mirror:
                bits.reverse()                    # right-anchored chain draws right-to-left
            bx = tx
            bf = display_font(S(11), True)
            for i, (t, col) in enumerate(bits):
                # separator goes BETWEEN items: trailing for a left-to-right chain, and
                # trailing too for the right-to-left chain (it lands against the previous
                # item's left edge because the string is right-aligned)
                sep = (i < len(bits) - 1) if not mirror else (i > 0)
                t2 = t + ("   ·   " if sep else "")
                d.text((bx, y + S(56)), t2, font=bf, fill=col, anchor=anc)
                bx += sgn * d.textlength(t2, font=bf)
            # tags: the sharpest profile reads that fit between the stats and the center
            tags = _live_tags(dd, cid, sc, ally)
            inner = x0 + half - S(12) if not mirror else x0 + S(12)
            ty = y + S(8)
            shown = 0
            for ti_, (txt_, tone) in enumerate(tags):
                if shown >= 3 or ty > y + ROW - S(24):
                    break
                res = _pill(inner, ty, txt_, _TAG_TONE.get(tone, MUTED),
                            (bx + S(16)) if not mirror else (bx - S(16)),
                            anchor=("ra" if not mirror else "la"), primary=(ti_ == 0))
                if res is not None:
                    shown += 1
                ty += S(22)
            # last-10 form bars under the tags column
            form = sc.get("form") or []
            if form:
                fw = 10 * S(11) - S(3)
                fx = (x0 + half - S(12) - fw) if not mirror else (x0 + S(12))
                fy = y + ROW - S(18)
                for i, win in enumerate(form[:10][::-1]):
                    d.rounded_rectangle([fx + i * S(11), fy, fx + i * S(11) + S(8), fy + S(9)], 2,
                                        fill=WSQ if win else LSQ)
        elif live:
            d.text((tx, y + S(56)), "scouting…", font=font(S(11)), fill=FAINT, anchor=anc)
        # click zone: art + name block -> their profile
        url = _profile_url((sc or {}).get("riot_id")) if sc else None
        if url:
            zone = (x0 + half - AW - S(240), y, x0 + half, y + ROW) if mirror \
                else (x0, y, x0 + AW + S(240), y + ROW)
            hits.append((zone[0], zone[1], zone[2], zone[3], url))

    y = rows_y
    for role, lbl in ROLES:
        a_cid, e_cid = ally_role.get(role), enemy_role.get(role)
        _half(S(14), y, a_cid, scout_map.get((a_cid, True)), True, a_cid == my_cid, False)
        _half(S(14) + half + CTR, y, e_cid, scout_map.get((e_cid, False)), False, False, True)
        d.text((cxc, y + S(18)), lbl.upper(), font=display_font(S(10), True), fill=FAINT, anchor="ma")
        if role in glabels:
            draw_badge(d, cxc, y + S(36), glabels[role], k=k)
        else:
            d.text((cxc, y + S(40)), "vs", font=font(S(10)), fill=FAINT, anchor="ma")
        y += ROW + GAP

    # ============================ LANE PANEL + WIN CONDITION ============================
    if panel_h:
        opp = enemy_role.get(my_role)
        draw_lane_panel(d, img, dd, S(14), y, BW - S(28), my_cid, my_role, opp,
                        lanes.get(my_role), scout_map.get((opp, False)) if opp else None,
                        tip_lines, panel_h)
        y += panel_h + S(10)
    if plan:
        _railed_card(d, (S(14), y, BW - S(14), y + plan_h - S(4)), GOLD, fill=SURFACE,
                     outline=PEDGE, width=1)
        d.text((S(32), y + S(8)), "WIN CONDITION", font=display_font(S(11), True), fill=GOLD)
        for i, b in enumerate(plan):
            d.text((S(32), y + S(26) + i * S(16)), "▸ " + b, font=font(S(11), text="▸"), fill=TEXT)
        y += plan_h
    _legend = ("S-F grade = how they PLAY (role benchmarks, not W/L; shown only with 4+ recent games) · "
               "tags from each account's history · form = last 10, oldest → newest · "
               "★ gank = matchup edge · click a player → u.gg")
    d.text((S(16), y + S(6)), _legend, font=font(S(11), text=_legend), fill=FAINT)
    if note:
        d.text((S(16), y + S(24)), note, font=font(S(11)), fill=EMBER_DEEP)
    img.hitmap = hits
    return img


def render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, source, note="", roles_known=True, live=True, lane_tip=None, champ_select=False, suggestions=None, dodge=None, bans=None, enemy_picks=None, ban_ideas=None, live_gank=None):
    if roles_known and not champ_select and enemy_role:
        # the LIVE game board gets the profile-grade renderer; champ select and the
        # pre-game states keep the compact layout below
        return render_live_board(dd, my_cid, my_role, ally_role, enemy_role, build, lanes,
                                 scout_map, source, note, live, lane_tip, live_gank)
    panel = bool(roles_known and not champ_select and my_role and my_role != "jungle" and my_role in dict(ROLES))
    tip_lines = _wrap(lane_tip, font(12), (W - 32) - 28) if (panel and lane_tip) else []
    panel_h = (77 + len(tip_lines) * 18) if tip_lines else (108 if panel else 0)
    band_h = 60 if champ_select else 0           # draft-intel band: good bans · bans · enemy picks
    # game plan: comp-level win conditions (in-game / loading, once both teams are known)
    plan = game_plan(dd, list(ally_role.values()), list(enemy_role.values())) if (roles_known and not champ_select and enemy_role) else []
    plan_h = (20 + len(plan) * 15 + 6) if plan else 0
    H = ((TOP + 5 * ROWH + 12 + panel_h + 48) if panel else (TOP + 5 * ROWH + 46 + band_h)) + plan_h
    rail_w = 96 if (champ_select and suggestions) else 0
    W2 = W + rail_w
    xoff = rail_w
    img = Image.new("RGB", (W2, H), BG)
    d = ImageDraw.Draw(img)
    hits = []                                    # clickable icon rects -> op.gg URL
    if my_cid:                                   # splash strip behind the header (all boards)
        strip = get_splash(dd, my_cid, (W2, 66))
        if strip:
            img.paste(strip, (0, 0))
            shade = Image.new("L", (W2, 66), 0)
            sd = ImageDraw.Draw(shade)
            for yy_ in range(66):                # darken evenly + fade to BG at the bottom edge
                sd.line([(0, yy_), (W2, yy_)], fill=min(255, 150 + int(yy_ * 1.6)))
            img.paste(Image.new("RGB", (W2, 66), BG), (0, 0), shade)
    # header
    ic = get_icon(dd, my_cid, 48)
    if ic:
        img.paste(ic, (16 + xoff, 9), ic)
        msc = scout_map.get((my_cid, True))
        murl = _profile_url(msc.get("riot_id")) if msc else None
        if murl:
            hits.append((16 + xoff, 9, 64 + xoff, 57, murl))
    if my_cid:
        d.text((74 + xoff, 12), f"{dd['id2name'].get(my_cid, '?')}   {(my_role or '?').upper()}",
               font=display_font(18, True), fill=GOLD)
    else:                                        # spectator / replay: no "you"
        d.text((16 + xoff, 12), "SPECTATING", font=display_font(18, True), fill=GOLD)
        d.text((16 + xoff, 42), "both teams scouted — no personal build (replay/spectator mode)", font=font(11), fill=MUTED)
    if build:
        bl = f"{build['keystone']}   ·   " + " > ".join(x for x in build['core'] if x) + "   ·   " + " / ".join(build['summs'])
        d.text((74 + xoff, 40), bl[:104], font=font(12), fill=MUTED)
        d.text((W2 - 16, 13), f"{build['wr']:.1f}%  {build['tier']}", font=display_font(15, True), fill=TEXT, anchor="ra")
    _brand_row(d, W2 - 16, 40, size=9, anchor="ra", suffix="· " + source, suffix_col=FAINT)
    d.line([16 + xoff, 66, W2 - 16, 66], fill=LINE_SOFT, width=1)
    d.text((26 + xoff, 73), "YOUR TEAM", font=display_font(13, True), fill=ARC)
    if champ_select:
        d.text((W2 - 26, 73), "YOUR RUNES + BUILD", font=display_font(13, True), fill=GOLD, anchor="ra")
    else:
        d.text((W2 - 26, 73), "ENEMY", font=display_font(13, True), fill=RED, anchor="ra")
    cxc = W2 // 2
    my_kit = gank_kit(dd, my_cid) if GANK_KIT_ON else 0.0           # toggleable
    if roles_known and not champ_select:
        # the closest thing this board has to UIDESIGN's win-prob "verdict strip" — same
        # GOOD/BAD/MUTED status colors, numerals in the display face, true pill radius.
        qr = queue_prediction(my_cid, scout_map)
        ga, ge = team_avg_grades(scout_map)          # grade-based read alongside the WR read
        text = qr["text"] + (f"   ·   grades {ga} vs {ge}" if (ga and ge) else "")
        qf = display_font(10, True)
        tw = d.textlength(text, font=qf)
        qx0, qx1 = cxc - (tw / 2) - 10, cxc + (tw / 2) + 10
        _rrect(d, (qx0, 69, qx1, 87), 9, fill=qr["bg"], outline=PEDGE, width=1)
        d.text((cxc, 78), text, font=qf, fill=qr["fill"], anchor="mm")
    if champ_select and dodge and dodge.get("verdict") == "DODGE":
        txt = "⚠ " + (dodge.get("headline") or "DODGE") + " — " + (dodge.get("reason") or "")
        bf = font(12, 1, txt)
        tw = d.textlength(txt, font=bf)
        bx0, bx1 = cxc - tw / 2 - 12, cxc + tw / 2 + 12
        _rrect(d, (bx0, 68, bx1, 92), 12, fill=_dim(RED, 0.14), outline=RED, width=1)
        d.text((cxc, 80), txt, font=bf, fill=RED, anchor="mm")
    elif champ_select and dodge and dodge.get("chip"):
        d.text((cxc, 80), dodge["chip"], font=font(10),
               fill=_wr_color(dodge.get("p", 0.5) * 100), anchor="mm")
    if champ_select and build:
        draw_build_block(d, img, dd, cxc + 50, TOP + 16, build, hits=hits)
    # gank scores for every enemy lane FIRST, so labels can be RELATIVE (someone is always
    # the strong side, someone the weak side) and shifted by the live game state.
    glabels = {}
    if roles_known and not champ_select:
        gscores = {}
        for role, _lbl in ROLES:
            e_cid = enemy_role.get(role)
            if not e_cid or role == my_role:
                continue
            es = scout_map.get((e_cid, False))
            a = (es["n"], es["w"], es["cg"], es["cw"], es.get("form")) if es else (0, 0, 0, 0, None)
            s = gank_score(lanes.get(role), *a, self_kit=my_kit)
            if live_gank:
                s += float(live_gank.get(role, 0.0))
            gscores[role] = s
        glabels = rank_gank_labels(gscores)
    for i, (role, lbl) in enumerate(ROLES):
        y = TOP + i * ROWH
        a_cid, e_cid = ally_role.get(role), enemy_role.get(role)
        draw_player(d, img, dd, 16 + xoff, y, a_cid, scout_map.get((a_cid, True)), a_cid == my_cid, "L", BLUE, ALLY_BG, live)
        draw_player(d, img, dd, W2 - 16, y, e_cid, scout_map.get((e_cid, False)), False, "R", RED, ENEMY_BG, live)
        asc, esc = scout_map.get((a_cid, True)), scout_map.get((e_cid, False))
        aurl = _profile_url(asc.get("riot_id")) if (a_cid and asc) else None
        eurl = _profile_url(esc.get("riot_id")) if (e_cid and esc) else None
        if aurl:
            hits.append((27 + xoff, y + 13, 65 + xoff, y + 51, aurl))     # ally icon (left)
        if eurl:
            hits.append((W2 - 65, y + 13, W2 - 27, y + 51, eurl))   # enemy icon (right)
        if roles_known and not champ_select:
            d.text((cxc, y + 11), lbl, font=font(10), fill=FAINT, anchor="ma")
            if role in glabels:
                draw_badge(d, cxc, y + 25, glabels[role])
            else:
                d.text((cxc, y + 28), "vs", font=font(10), fill=FAINT, anchor="ma")
        elif champ_select:
            cf = font(9, 1)
            cw_ = d.textlength(lbl.upper(), font=cf)
            _rrect(d, (384, y + 20, 384 + cw_ + 14, y + 36), 8, fill=RAISED, outline=PEDGE, width=1)
            d.text((391, y + 24), lbl.upper(), font=cf, fill=MUTED)
    if champ_select and suggestions:
        # Draw this AFTER the team rows so it can't be covered by row backgrounds. Header and
        # icons are flush top-left of the rail; tight vertical step fits 5 suggestions.
        sx, sy = 6, TOP + 2
        _rrect(d, (sx, sy, sx + 78, sy + 322), 10, fill=SURFACE, outline=PEDGE, width=1)
        d.text((sx + 9, sy + 9), "GOOD THIS", font=display_font(9, True), fill=GOLD, anchor="la")
        d.text((sx + 9, sy + 21), "GAME", font=display_font(9, True), fill=GOLD, anchor="la")
        yy = sy + 40
        for cid in suggestions[:5]:
            ic = get_icon(dd, cid, 36)
            if ic:
                img.paste(ic, (sx + 9, yy), ic)
            yy += 56
    ly = TOP + 5 * ROWH + 12
    if champ_select and band_h:
        _draw_draft_band(d, img, dd, 16 + xoff, ly, W2 - xoff - 32, bans, enemy_picks, ban_ideas)
        ly += band_h
    if panel:
        opp = enemy_role.get(my_role)
        draw_lane_panel(d, img, dd, 16 + xoff, ly, W2 - xoff - 32, my_cid, my_role, opp,
                        lanes.get(my_role), scout_map.get((opp, False)) if opp else None,
                        tip_lines, panel_h)
        ly += panel_h + 14
    if plan:
        _railed_card(d, (12 + xoff, ly, W2 - 12, ly + plan_h - 4), LINE, fill=SURFACE, outline=PEDGE, width=1, r=8)
        d.text((22 + xoff, ly + 6), "WIN CONDITION", font=display_font(9, True), fill=GOLD)
        for i, b in enumerate(plan):
            d.text((22 + xoff, ly + 22 + i * 15), "▸ " + b, font=font(10, text="▸"), fill=TEXT)
        ly += plan_h
    _legend = "rank · L10 W/L · mastery (gold=main 100k+, green=comfort 30k+, red=first-timing) · S-F / GOOD PLAYER = skill (how they PLAY)   |   ★ gank = champ matchup edge   |   click → u.gg"
    d.text((16 + xoff, ly), _legend, font=font(11, text=_legend), fill=FAINT)
    if note:
        d.text((16 + xoff, ly + 18), note, font=font(11), fill=EMBER_DEEP)
    img.hitmap = hits
    return img


def render(path, dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map, source,
           note="", roles_known=True, live=True, lane_tip=None, champ_select=False):
    """Render the board to a PIL Image and write it to a PNG (CLI / debug / fallback)."""
    img = render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map,
                       source, note, roles_known, live, lane_tip, champ_select)
    _save_png(img, path)
    return img


def _save_png(img, path):
    tmp = path + ".tmp"
    img.save(tmp, format="PNG")
    os.replace(tmp, path)
    try:                                   # sidecar so the AHK overlay can resize to match
        open(path + ".dim", "w").write(str(img.height))
    except Exception:
        pass


def info_image(msg):
    """A small status/error card (no live game yet, key stale, etc.)."""
    img = Image.new("RGB", (W, 140), BG)
    d = ImageDraw.Draw(img)
    _brand_row(d, 20, 20, size=18)
    d.text((20, 58), msg, font=font(13), fill=TEXT)
    return img


# ---------- the QUEUE card: the overlay opens WITH the queue, not after it ----------
QUEUE_PHASES = ("Matchmaking", "ReadyCheck")
_OVLOG = os.path.expanduser("~/.claude/smiteless_overlay.log")


def _ovlog(msg):
    """Phase-transition diagnostics for the overlay loop — dodge teardowns can't be
    triggered on demand, so they must leave a trail (standing live-verify rule)."""
    try:
        with open(_OVLOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass
_QUEUE_NAMES = {420: "Ranked Solo/Duo", 440: "Ranked Flex", 400: "Normal Draft",
                430: "Normal Blind", 450: "ARAM", 480: "Swiftplay", 490: "Quickplay",
                700: "Clash", 1700: "Arena", 1900: "URF"}
_POS_NICE = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID", "BOTTOM": "ADC",
             "UTILITY": "SUPPORT"}
_NO_ROLE_QUEUES = ("ARAM", "Arena", "URF", "Normal Blind")


def _lcu_get(port, hdr, path, timeout=3):
    try:
        return lb.http(f"https://127.0.0.1:{port}{path}", headers=hdr, timeout=timeout, insecure=True)
    except Exception:
        return None


def queue_state():
    """What the LCU knows while you're queueing: queue name, your role prefs, time in
    queue vs the estimate, the ready-check countdown, and whether auto-accept is armed.
    All cheap local reads — safe to poll every couple of seconds."""
    out = {"phase": phasecheck.phase(), "queue": "", "roles": [], "tq": None, "est": None,
           "rc": None, "auto": bool(cfg.load().get("auto_accept", False))}
    lc = lg._lcu()
    if not lc:
        return out
    port, hdr = lc
    lob = _lcu_get(port, hdr, "/lol-lobby/v2/lobby") or {}
    gc = lob.get("gameConfig") or {} if isinstance(lob, dict) else {}
    out["queue"] = _QUEUE_NAMES.get(gc.get("queueId"), "")
    me = lob.get("localMember") or {} if isinstance(lob, dict) else {}
    for r in (me.get("firstPositionPreference"), me.get("secondPositionPreference")):
        if r and r != "UNSELECTED":
            out["roles"].append(_POS_NICE.get(r, r))
    srch = _lcu_get(port, hdr, "/lol-matchmaking/v1/search")
    if isinstance(srch, dict):
        out["tq"] = srch.get("timeInQueue")
        out["est"] = srch.get("estimatedQueueTime")
    if out["phase"] == "ReadyCheck":
        rc = _lcu_get(port, hdr, "/lol-matchmaking/v1/ready-check")
        if isinstance(rc, dict):
            out["rc"] = rc.get("timer")
    return out


def _q_mmss(v):
    v = max(0, int(v or 0))
    return f"{v // 60}:{v % 60:02d}"


def render_queue_card(dd, q, sugg=None):
    """The IN-QUEUE / MATCH-FOUND card — up the moment you start searching, so the board
    is already on the second monitor warming up before champ select exists. Calm and
    compact: the queue clock, your roles, and your comfort picks for the role, then the
    full scout takes over the instant champ select starts."""
    warm = [c for c in (sugg or []) if c][:6]
    H = 150 + (108 if warm else 0)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    ready = q.get("phase") == "ReadyCheck"
    _brand_row(d, 20, 18, size=12, suffix=("· match found" if ready else "· in queue"),
               suffix_col=(GOLD if ready else FAINT))

    if ready:
        _railed_card(d, (16, 46, W - 16, 106), GOLD, fill=_dim(GOLD, 0.13), outline=_dim(GOLD, 0.6), width=1)
        d.text((36, 62), "MATCH FOUND", font=display_font(24, True), fill=GOLD)
        if q.get("auto"):
            # Bahnschrift has no ✓ glyph -> route through the symbol-aware body face
            d.text((W - 36, 62), "auto-accepting ✓", font=font(14, True, "✓"), fill=GREEN, anchor="ra")
        else:
            left = q.get("rc")
            t = f"ACCEPT NOW{f'  ·  {int(max(0, 12 - left))}s' if isinstance(left, (int, float)) else ''}"
            d.text((W - 36, 62), t, font=display_font(14, True), fill=WARN, anchor="ra")
    else:
        _railed_card(d, (16, 46, W - 16, 106), ARC, fill=SURFACE, outline=PEDGE, width=1)
        tq = q.get("tq")
        clock = _q_mmss(tq) if tq is not None else "…"
        d.text((36, 56), "IN QUEUE", font=display_font(12, True), fill=MUTED)
        d.text((36, 70), clock, font=display_font(24, True), fill=ARC)
        est = q.get("est")
        if est:
            d.text((44 + d.textlength(clock, font=display_font(24, True)), 79),
                   f"est {_q_mmss(est)}", font=display_font(12, True), fill=FAINT)
        # queue + roles, right-aligned as chips
        cx = W - 36
        rf = display_font(12, True)
        for lab, col in [(r, GOLD) for r in reversed(q.get("roles") or [])] + \
                        ([(q["queue"], MUTED)] if q.get("queue") else []):
            wdt = d.textlength(lab, font=rf)
            _rrect(d, (cx - wdt - 16, 66, cx, 90), 12, fill=RAISED, outline=PEDGE, width=1)
            d.text((cx - wdt - 8, 71), lab, font=rf, fill=col)
            cx -= wdt + 26
    yy = 118
    if warm:
        chf = display_font(12, True)
        lbl = "GOOD THIS GAME · YOUR COMFORT PICKS"
        d.text((20, yy), lbl, font=chf, fill=GOLD)
        d.line([34 + int(d.textlength(lbl, font=chf)), yy + 8, W - 20, yy + 8], fill=LINE_SOFT, width=1)
        x = 20
        for cid2 in warm:
            ic = get_icon(dd, cid2, 56)
            if ic:
                _rrect(d, (x - 2, yy + 22, x + 58, yy + 82), 8, fill=SUNKEN)
                img.paste(ic, (x, yy + 24), ic)
            nm = dd["id2name"].get(cid2, "")[:10]
            d.text((x + 28, yy + 86), nm, font=font(9), fill=MUTED, anchor="ma")
            x += 74
        yy += 108
    d.text((20, H - 24), "the full lobby scout takes over the moment champ select starts",
           font=font(10), fill=FAINT)
    return img


def _info_card(path, msg):
    _save_png(info_image(msg), path)


def _takeflag(argv, name, default=None):
    if name in argv:
        i = argv.index(name); v = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]; return v
    return default


def run(emit, count=None, wait=False, stop=None, monitor=False):
    """Core loop: resolve the live game, render each frame, and hand the finished PIL
    Image to emit(img). Shared by the PNG CLI (main) and the live Tk overlay.

      emit(img) - called with every rendered frame (a PIL Image).
      count     - scout games per player; None -> use the user's setting (live).
      wait      - auto-open mode: stay blank until champs are actually present.
      stop()    - return True to break out early (overlay was closed).
      monitor   - in-game, after the board is complete, keep watching for the match to
                  end (the overlay stays open through the game) instead of returning.

    Returns when the game/session ends, the deadline passes, or stop() is True."""
    stop = stop or (lambda: False)
    dd = lb.ddragon()
    deadline = time.time() + 420          # cap the pre-game wait (champ select + loading)
    build = None
    build_cid = 0
    auto_done = 0                         # champ we already auto-imported for (once per lock)
    auto_note = None                      # "auto-imported ✓" note shown on the panel
    last_cs_sig = None                    # champ-select frame signature (skip identical re-renders)
    # per-champ-select ally scout: the roster line plus the FLAGS that feed the dodge call
    team_read = {"state": "idle", "text": "", "flags": [], "known": 0}
    shown = False                         # have we rendered a real session (champ select / game)?
    inactive = 0                          # consecutive reads with the client out of an active phase
    acct_captured = False                 # auto-remember the logged-in account once per session
    profile_img, profile_tried = None, False   # the home/profile page (manual open, out of game)
    last_ph = None                        # previous gameflow phase (drives the dodge teardown)
    dodged = False                        # champ select just aborted -> stay hidden until the next draft
    while not stop() and time.time() < deadline:
        settings = apply_settings()       # live tuning: gank weights + scout depth
        n_scout = count if count is not None else settings["scout_games"]
        # The PHASE is authoritative for "are we in a session". lg.resolve keeps returning a
        # STALE board after a game ends, so we gate on phasecheck, not resolve - otherwise
        # opening the overlay out of game shows the PREVIOUS game instead of the home page.
        ph = phasecheck.phase()
        # DODGE TEARDOWN (§10): champ select ending in anything but a game start is a dodge/
        # abort. Reset every per-draft state so the NEXT champ select re-inits clean, park the
        # window, and don't morph into a queue card for the auto-requeue — that was the stray
        # "queue timer window on the wrong monitor" bug.
        if last_ph == "ChampSelect" and ph not in ("ChampSelect", "GameStart", "InProgress", ""):
            _ovlog(f"champ select aborted -> {ph!r}: state reset, window parked until next draft")
            build, build_cid, auto_done, auto_note, last_cs_sig = None, 0, 0, None, None
            team_read = {"state": "idle", "text": "", "flags": [], "known": 0}
            dodged = True
            _DODGE_CACHE.clear()
            _DODGE_CTX.update(v=None, tries=0)       # your history moved; re-read it
            try:
                # If the client is holding a dodge penalty, YOU dodged — and the next dodge
                # costs 10 LP and 30 minutes instead of 3 and 6, which is most of the answer.
                import loldodge as _ldg
                if _ldg.probe_penalty():
                    _ldg.note_dodge()
            except Exception:
                pass
            try:
                import lolimport as limp
                limp.ban_watch_update(dd, [], [], False)   # stale targets must not fire next draft
                limp.pick_watch_update(dd, [], False)      # ... and never auto-lock into a dodge
            except Exception:
                pass
            emit("hide")
        if ph == "ChampSelect" and dodged:
            dodged = False                # a fresh draft: state was reset above, re-init normally
        if last_ph != ph:
            _ovlog(f"phase {last_ph!r} -> {ph!r}")
        last_ph = ph
        if dodged and ph in QUEUE_PHASES:
            time.sleep(2)                 # requeueing after a dodge: stay parked, no queue card
            continue
        if ph in QUEUE_PHASES:
            # IN QUEUE: the board opens WITH the queue and warms up (queue clock, your
            # roles, comfort picks); champ select then fills in over it the moment it
            # starts. The pre-game deadline is pushed while queueing so a long queue
            # can't expire the overlay.
            deadline = max(deadline, time.time() + 420)
            q = queue_state()
            sugg = None
            if q.get("roles") and q.get("queue") not in _NO_ROLE_QUEUES:
                try:
                    # queue card: same rule as champ select — what's strong, not what you own
                    sugg = suggest_champs(dd, q["roles"][0], [], [], topn=6, fam=None)
                except Exception:
                    sugg = None
            emit(render_queue_card(dd, q, sugg))
            shown = True                   # leaving the queue (decline/dodge) closes us
            inactive = 0
            time.sleep(2)
            continue
        if ph not in ACTIVE_PHASES:
            if ph == "":                   # client unreachable (closed, or a mid-game lag blip) -> wait
                time.sleep(3)
                continue
            if monitor and shown:          # we were in champ select / a game and it's over -> close
                inactive += 1
                if inactive >= 2:
                    return
            elif not wait:                 # opened out of a game -> the Profile WINDOW handles this
                return
            time.sleep(3)
            continue
        inactive = 0
        # allow_unlocked: show the champ-select panel the moment champ select opens, before
        # you've hovered anything (resolve otherwise treats "no champ hovered yet" as an error).
        info, err = lg.resolve(dd, allow_unlocked=True)
        if err:                            # in an active phase but nothing resolvable yet (loading)
            time.sleep(3)
            continue
        shown = True                       # resolve succeeded -> we're in a session
        if not acct_captured:              # remember this account (main/smurf) for pooled familiarity
            acct_captured = True

            def _cap():
                try:
                    ca = lg.current_account()
                    if ca:
                        ls.remember_account(ca[1], source="auto")
                except Exception:
                    pass
            threading.Thread(target=_cap, daemon=True).start()
        my_cid, my_role = info["my"], info["pos"]
        allies, enemies = info["allies"], info["enemies"]
        ally_role = {r: c for c, r in allies if r and c}
        enemy_role = {r: c for c, r in enemies if r and c}
        if my_cid and my_cid != build_cid:        # (re)fetch on champ change (champ-select hover/lock)
            build = build_data(dd, my_cid, my_role)
            build_cid = my_cid
            set_rune_idx(0, manual=False)          # new champ -> back to auto (adaptive) selection
        src = info.get("source", "")
        if not enemy_role:                 # champ select / loading: enemies + scout not live yet
            if src == "champ select":
                # CHAMP SELECT: show your team forming + your runes/build the moment champ
                # select opens (even before anyone's hovered) — the panel is useful right away
                # (your role, suggested picks, good bans). We still only RE-render when a pick
                # actually changes, via the signature below, so it doesn't flicker/grab focus.
                bans_my = info.get("bans_my") or []
                bans_their = info.get("bans_their") or []
                # LIVE DRAFT LINK: publish this champ select to the user's Firebase and
                # drop the shareable board URL in chat (own thread; dormant unless the
                # user configured a database — see loldraft.py / docs/DRAFTLINK.md).
                try:
                    import loldraft
                    loldraft.tick(dd)
                except Exception:
                    pass
                # AUTO-IMPORT: the moment the champ is LOCKED (not hovered), push runes+summs
                # once. A different lock (re-pick) imports again; failures show on the panel.
                if (settings.get("auto_import", False) and info.get("locked")
                        and my_cid and build and auto_done != my_cid):
                    auto_done = my_cid
                    try:
                        import lolimport as limp
                        limp.import_build(dd, my_cid, my_role, pick_rune(build))   # selected rune set
                        auto_note = "auto-imported ✓"
                    except Exception as e:
                        auto_note = f"auto-import failed: {str(e)[:38]}"
                    last_cs_sig = None            # re-render with the note
                ally_ids = [c for c, _ in allies if c]
                enemy_ids = [c for c, _ in enemies if c]
                taken = set(bans_my) | set(bans_their) | set(ally_ids) | set(enemy_ids)
                # Ban ideas: the champ that threatens the TEAM'S hovers most (every ally's
                # pick intent + yours, counters aggregated), falling back to your champ's
                # counters, then to high-priority solo-q bans (bans happen before picks, so
                # there's always a target to show/auto-ban).
                ideas = team_bans(dd, allies, taken=taken, self_cid=my_cid) \
                    or (suggest_bans(dd, my_cid, my_role, taken=taken) if my_cid else []) \
                    or general_bans(dd, my_role, taken)
                # PRIORITY BAN LIST first (settings, e.g. perma-ban Shyvana), then the live
                # EV ideas as fallback. The actual lock runs on lolimport's 1s watcher
                # thread — this render loop can stall for seconds on network work, which
                # used to swallow the last-12s firing window (the 'ban didn't happen' bug).
                try:
                    import lolimport as limp
                    listed = [dd["name2id"].get(dd["norm"](nm2))
                              for nm2 in settings.get("ban_list") or []]
                    targets = [c for c in listed if c] + [c for c, _ in ideas]
                    limp.ban_watch_update(dd, targets, ally_ids,
                                          settings.get("auto_ban", False))
                    # MAX ELO: hold the pool and lock it. Same dedicated-watcher shape as the
                    # ban, for the same reason — this render loop is too slow to be trusted
                    # with a firing window.
                    pool = [dd["name2id"].get(dd["norm"](nm2))
                            for nm2 in (settings.get("max_elo_main"),
                                        settings.get("max_elo_backup")) if nm2]
                    pool = [c for c in pool if c]
                    if settings.get("max_elo") and not pool and my_role:
                        # NO CHAMPION SET -> lock the best pick for THIS draft instead of
                        # standing down. Same recommender the panel's GOOD THIS GAME strip
                        # shows (counters into the locked enemies + comp fit, merit only),
                        # best-first, and it already excludes anything banned or taken — so
                        # the list doubles as its own backup chain.
                        # topn=12, not 5: auto_pick filters this to champions you can actually
                        # pick, and a five-deep list can be emptied by ownership + bans alone.
                        try:
                            pool = suggest_champs(dd, my_role, _mates(ally_ids, my_cid),
                                                  enemy_ids, topn=12, fam=None)
                            # ...and never AUTO-LOCK you onto a champion your own results say
                            # you're bad on (core/lolfit), which matters far more here than in
                            # a list you can ignore.
                            import lolfit as _fit
                            pool, _fn = _fit.apply(_fit.build(), dd, pool)
                        except Exception:
                            pool = []
                    limp.pick_watch_update(dd, pool, settings.get("max_elo", False))
                except Exception:
                    pass
                if settings.get("auto_swap_roles"):      # teammate offered a role you want? -> accept
                    try:
                        import lolimport as limp
                        limp.auto_accept_swap(settings.get("auto_swap_roles"))
                    except Exception:
                        pass
                if settings.get("auto_pick_swap"):        # work pick order toward first/last pick
                    try:
                        import lolimport as limp
                        limp.auto_pick_order_swap(settings.get("auto_pick_swap"))
                    except Exception:
                        pass
                # ALLY SCOUT while you can still dodge: teammate Riot IDs come from the
                # Riot Client chat participants (allies only — enemies are anonymized).
                # One background pass per champ select; flags tilted / F-grade teammates.
                if team_read["state"] == "idle":
                    team_read["state"] = "busy"
                    def _team_scout():
                        flags, roster = [], []
                        try:
                            me_rid = (lg.current_account() or "")
                            key = ls.read_key()

                            def _one(rid):
                                """One ally's dodge read. Also WARMS the shared match/rank cache
                                that the loading board reads minutes later — champ select is dead
                                time, so paying here is free; paying again at load is not."""
                                try:
                                    pu = ls.resolve_puuid(rid, key)
                                    if not pu:
                                        return None
                                    n, w, cg, cw, form, _m, kda, perf, _r = ls.scout(dd, pu, 0, key, 10)
                                    sc = {"n": n, "w": w, "cg": cg, "cw": cw, "form": form,
                                          "kda": kda, "perf": perf, "rank": ls.rank(pu, key)}
                                    g, _c = player_rating(sc)
                                    streak = 0
                                    for won in form:
                                        if won:
                                            break
                                        streak += 1
                                    nm = rid.split("#")[0][:10]
                                    rk = (sc["rank"] or {})
                                    ab = TIER_ABBR.get((rk.get("tier") or "").upper(), "")
                                    ab += _DIVNUM.get(rk.get("div", ""), "") if ab else ""
                                    return (nm, g, streak, ab)
                                except Exception:
                                    return None

                            # RANKED HIDES NAMES — your own team's as well as the enemy's — so
                            # this list is routinely EMPTY in the mode that matters, and the
                            # dodge call then runs on the draft alone (by design, see
                            # core/loldodge's header). Log what actually resolved so the answer
                            # lives in the log instead of in an assumption.
                            _rids = lg.champselect_allies()
                            mates = [rid for rid in _rids[:5]
                                     if key and rid.lower() != (me_rid or "").lower()]
                            try:
                                import loldodge as _ldg
                                _ldg.log(f"ally scout: chat roster returned {len(_rids)} "
                                         f"name(s), {len(mates)} scoutable"
                                         + ("" if key else " (no Riot API key -> none)"))
                            except Exception:
                                pass
                            reads = []
                            if mates:               # the four teammates read in parallel, not in a queue
                                import concurrent.futures as _fx
                                with _fx.ThreadPoolExecutor(max_workers=len(mates)) as _ex:
                                    reads = list(_ex.map(_one, mates))
                            known = 0
                            for got in reads:
                                if not got:
                                    continue
                                known += 1
                                nm, g, streak, ab = got
                                roster.append(f"{nm} {ab or '?'}·{g or '?'}"
                                              + (f"·{streak}L" if streak >= 2 else ""))
                                if streak >= 3:
                                    flags.append(f"{nm} {streak}L")
                                elif g == "F":
                                    flags.append(f"{nm} F-grade")
                            # The scout no longer shouts "DODGE READ" on its own. A flag is
                            # only evidence to the extent it beats what the ENEMY team (which
                            # you can't see in champ select) is carrying, so the flags go to
                            # loldodge and the running base rate learns from this lobby too.
                            team_read["flags"], team_read["known"] = flags, known
                            if known:
                                try:
                                    import loldodge as _ldg
                                    _ldg.observe(known, len(flags))
                                except Exception:
                                    pass
                            team_read["text"] = ("team: " + "  ".join(roster[:4])) if roster else ""
                        except Exception:
                            team_read["text"] = ""
                        team_read["state"] = "done"
                    threading.Thread(target=_team_scout, daemon=True).start()
                # CLIMB check on the hovered pick: sub-12k mastery points is the single
                # biggest self-inflicted WR leak (~44% vs 51%+, 1M-game study) — warn early,
                # while there's still time to hover something you actually play.
                climb_note = ""
                if my_cid and not auto_note:
                    try:
                        # pooled across ALL your accounts — 100k on the main means the
                        # smurf pick is fine; only warn when NO account knows the champ
                        _pool = ls.familiarity(lg.my_mastery_points())
                        _pts = _pool.get(my_cid) if _pool else None
                        if _pts is not None and _pts < 12000:
                            climb_note = (f"⚠ {_pts // 1000}k mastery pick — sub-12k wins ~44% "
                                          f"(1M-game study); your mains climb faster")
                    except Exception:
                        climb_note = ""
                sig = (my_cid, my_role, tuple(sorted(ally_role.items())),
                       tuple(sorted((c, r) for c, r in enemies if c)), bool(build),
                       tuple(bans_my), tuple(bans_their),
                       bool(settings.get("auto_import", False)), bool(settings.get("auto_ban", False)),
                       auto_note, climb_note, team_read["text"],
                       tuple(team_read.get("flags") or ()), get_rune_idx())
                if sig != last_cs_sig:
                    # WHAT'S GOOD THIS GAME — the same call the web DraftBoard makes (fam=None):
                    # counters into the locked enemies + comp fit, ranked on merit alone.
                    # It used to pass your pooled mastery, which applied a HARD 12k+ gate and
                    # turned this into "champs you already play" — a list you don't need an
                    # overlay to tell you. The climb warning above still fires if you hover
                    # something you don't know, so the guard isn't lost, just moved off the
                    # recommendation.
                    sugg = suggest_champs(dd, my_role, _mates(ally_ids, my_cid), enemy_ids,
                                          topn=12, fam=None)
                    # PERSONAL FIT (core/lolfit): merit says what beats this draft; your own
                    # results say whether YOU should be the one playing it. Drops champions
                    # you're statistically proven bad on, and promotes ones you're good on but
                    # haven't touched in a while — the boredom answer that costs no LP.
                    # ADAPTIVE RUNES (core/lolrunes): the enemy comp decides which of op.gg's
                    # pages to run. Recomputed as they lock, and only while the selection is
                    # still automatic — one click on a rune chip and this stops touching it.
                    rune_note = None
                    if build and not _RUNE_SEL["manual"]:
                        try:
                            import lolrunes as _lr
                            _ri, rune_note = _lr.choose(dd, build.get("rune_options"), enemy_ids)
                            set_rune_idx(_ri, manual=False)
                        except Exception:
                            rune_note = None
                    fit_notes = {}
                    try:
                        import lolfit as _fit
                        sugg, fit_notes = _fit.apply(_fit.build(), dd, sugg)
                    except Exception:
                        fit_notes = {}
                    if not _FIT_WARM["done"]:
                        # Refresh the deep season read ONCE per session, off-thread — it's ~60
                        # match fetches and must never sit in the champ-select render loop.
                        _FIT_WARM["done"] = True

                        def _warm():
                            try:
                                import lolfit as _f
                                _f.build(dd, ls.read_key())
                            except Exception:
                                pass
                        threading.Thread(target=_warm, daemon=True).start()
                    # ...but only show what you can actually pick. This is NOT the old mastery
                    # gate (a champ you own with 0 games still qualifies) — it just drops the
                    # ones the client would refuse. Unavailable list -> show them all rather
                    # than an empty strip.
                    try:
                        import lolimport as _limp
                        _own = _limp.pickable_ids()
                        if _own:
                            sugg = [c for c in sugg if c in _own]
                    except Exception:
                        pass
                    sugg = sugg[:5]
                    # THE DODGE CALL (core/loldodge): the draft priced in LP against what a
                    # dodge costs you, sharpened by the flags the ally scout found.
                    dodge = (dodge_read(dd, allies, enemies, flags=team_read.get("flags"),
                                        known=team_read.get("known", 0))
                             if settings.get("dodge_alerts", True) else None)
                    if settings.get("dock_champ_select", True):
                        # tall panel that docks LEFT of the client (the overlay parks it there
                        # and nudges the client right if there's no room)
                        emit(render_cs_vertical(dd, my_cid, my_role, allies, build,
                             suggestions=sugg, bans=(bans_my, bans_their),
                             enemy_picks=enemy_ids, ban_ideas=ideas, dodge=dodge,
                             auto_import=bool(settings.get("auto_import", False)),
                             note=(auto_note or team_read["text"] or climb_note),
                             auto_ban=bool(settings.get("auto_ban", False)),
                             fit_notes=fit_notes, rune_note=rune_note))
                    else:
                        emit(render_image(dd, my_cid, my_role, ally_role, {}, build, {}, {}, src,
                             "enemies are hidden in champ select - matchups + player scout load at the loading screen",
                             roles_known=True, live=False, champ_select=True, suggestions=sugg, dodge=dodge,
                             bans=(bans_my, bans_their), enemy_picks=enemy_ids, ban_ideas=ideas))
                    last_cs_sig = sig
                _RUNE_EVENT.wait(2)          # 2s poll, but a rune-chip click wakes it instantly
                _RUNE_EVENT.clear()
                continue
            # LOADING screen: positional preview (no roles yet)
            champs_ready = bool(allies) and bool(enemies)
            if wait and not champs_ready:
                time.sleep(3)
                continue
            ar = {ROLES[i][0]: c for i, (c, _r) in enumerate(allies[:5]) if c}
            er = {ROLES[i][0]: c for i, (c, _r) in enumerate(enemies[:5]) if c}
            emit(render_image(dd, my_cid, my_role, ar, er, build, {}, {}, src,
                 "roles + live player scout load once the match starts...",
                 roles_known=False, live=False))
            time.sleep(3)
            continue
        # in-game: full board + matchup tip + progressive player scout
        # LIVE DRAFT LINK: also start the publisher here, so launching Smiteless MID-GAME (after
        # champ select) still brings the web scoreboard + tactical board up. tick() spawns once;
        # its worker sees we're past champ select and goes straight to the scout/live phase.
        try:
            import loldraft
            loldraft.tick(dd)
        except Exception:
            pass
        lanes = {r: wr for a, r, e, wr, g in lb.gather_lane_matchups(dd, allies, enemies)}
        scout_map = {}
        patch = lm.patch_of(dd["ver"])
        # jungle included now: the tips are real written guide advice (counterstats), and
        # jungler-vs-jungler write-ups are some of the best content on there.
        opp_cid = enemy_role.get(my_role)
        tips_on = settings.get("matchup_tips", True)
        tip_box = {"tip": (lm.get_tip(dd["id2key"].get(my_cid, ""), dd["id2key"].get(opp_cid, ""),
                                      my_role, patch) if (tips_on and opp_cid) else None)}
        live_box = {"adj": None}                      # live gank adjustments (evolves in-game)

        def paint(note=""):
            emit(render_image(dd, my_cid, my_role, ally_role, enemy_role, build, lanes, scout_map,
                 src, note, lane_tip=tip_box["tip"], live_gank=live_box["adj"]))

        paint()
        # Generate the matchup tip in the BACKGROUND (web search, ~60-120s) so it never
        # blocks the scout - the board fills in while the tip is being written, and each
        # repaint picks it up once it's ready.
        tip_thread = None
        if tips_on and opp_cid and not tip_box["tip"]:
            def _gen_tip():
                t, _e = lm.generate_tip(dd["id2name"].get(my_cid, ""), dd["id2key"].get(my_cid, ""),
                                        dd["id2name"].get(opp_cid, ""), dd["id2key"].get(opp_cid, ""),
                                        my_role, patch)
                if t:
                    tip_box["tip"] = t
            tip_thread = threading.Thread(target=_gen_tip, daemon=True)
            tip_thread.start()
        for r in ls.iter_scout_struct(dd, n_scout):
            if stop():
                return
            if "error" in r:
                paint(r["error"])
                break
            scout_map[(r["cid"], r["is_ally"])] = r
            paint()
        if tip_thread:                                # board's done; wait out the tip, repaint
            tip_thread.join(timeout=185)              # > the 170s tip-gen cap, so a slow tip
            paint()                                   # still lands (and gets cached) before we exit
        if not monitor:
            return
        # SCOUT GAP RE-CHECK (#4): if the initial scout left gaps (a player's match list
        # came back empty — rate-limit / transient failure), that player's card is missing the
        # rank/form/grade the whole board exists for. Once, a little later (so the rate-limit
        # window clears), re-scout and fill those gaps, then ask the loop to repaint.
        rescan = {"repaint": False}
        gaps = [k for k, e in scout_map.items() if not e.get("mids")]
        if gaps:
            def _refill():
                time.sleep(20)
                try:
                    fresh = {}
                    for r in ls.iter_scout_struct(dd, n_scout):
                        if "error" in r:
                            return
                        fresh[(r["cid"], r["is_ally"])] = r
                    for k in gaps:
                        fr = fresh.get(k)
                        if fr and fr.get("mids"):
                            scout_map[k] = fr          # atomic item set; loop repaints below
                            rescan["repaint"] = True
                except Exception:
                    pass
            threading.Thread(target=_refill, daemon=True).start()
        # Overlay: board is complete -> keep it on screen and watch THIS game's phase.
        #   new champ select   -> refresh this same window to the new draft (don't go stale)
        #   game over (lobby)  -> close, so the next champ select opens fresh
        # Phase-driven, because lg.resolve can keep returning stale data after a session ends.
        miss, blip, restart = 0, 0, False
        while not stop():
            time.sleep(5)
            if rescan["repaint"]:                     # gap-fill found new scout data -> redraw
                rescan["repaint"] = False
                paint()
            ph = phasecheck.phase()
            if ph in ("InProgress", "GameStart", "Reconnect"):
                miss = blip = 0                       # still in this game
                # LIVE gank shift: strong/weak side follows the game state (deaths, level
                # deficits, deaths-in-progress). Repaint only when the read actually moves.
                try:
                    raw = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata",
                                  timeout=2, insecure=True)
                    adj = ll.lane_live_adj(dd, raw, ally_role, enemy_role)
                    if adj and adj != live_box["adj"]:
                        live_box["adj"] = adj
                        paint()
                except Exception:
                    pass
                continue
            if ph == "ChampSelect":                   # a NEW champ select -> refresh, don't close
                restart = True
                break
            if ph == "":                              # client unreachable (lag spike / closing) -> tolerate
                blip += 1
                if blip >= 6:                         # ~30s truly gone -> close out
                    return
                continue
            miss += 1                                 # a DEFINITE end phase (WaitingForStats/EndOfGame/Lobby/None)
            if miss >= 2:                             # ~10s after the game ends -> close so the profile takes over
                return
        if not restart:
            return                                    # stop() requested -> close
        build_cid, last_cs_sig = 0, None              # re-render fresh for the new champ select
        auto_done, auto_note = 0, None
        continue


def main():
    argv = sys.argv[1:]
    wait = "--wait" in argv          # auto-open: don't draw anything until champs are present
    if wait:
        argv.remove("--wait")
    outp = _takeflag(argv, "--out") or os.path.expanduser("~/.claude/cache/smitecard.png")
    fm = _takeflag(argv, "--fm")
    try:
        count = int(_takeflag(argv, "--count"))      # None -> use the saved scout-depth setting
    except Exception:
        count = None
    try:
        run(lambda img: _save_png(img, outp), count=count, wait=wait, monitor=False)
    finally:
        if fm:
            try:
                open(fm, "w").close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
