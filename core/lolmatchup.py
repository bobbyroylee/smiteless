#!/usr/bin/env python3
"""lolmatchup.py - specific lane matchup tips from REAL WRITTEN GUIDES, cached per patch.

PRIMARY source: counterstats.net (MOBAFire) — actual prose counter-tips written by guide
authors for the exact enemy champion, filtered to your lane and (when available) authored
by players of YOUR champion. Fast (~1s scrape, cached per enemy+patch), deterministic, no
AI in the loop. FALLBACK when the site has nothing for the matchup: the old LLM+web-search
generator. Cache key includes the patch, so tips refresh when the game changes.

CLI (manual seeding / testing):
  python lolmatchup.py Yasuo Syndra mid
"""
import json
import os, re, sys
import time
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import llmcli
import smiteconfig as cfg
from smitei18n import tf

CACHE = os.path.expanduser("~/.claude/cache/matchups")
CS_CACHE = os.path.expanduser("~/.claude/cache/counterstats")
CS_HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# our role names -> the site's data-lane tokens
CS_LANE = {"top": "top", "jungle": "jungle", "jg": "jungle", "mid": "mid", "middle": "mid",
           "adc": "adc", "bot": "adc", "bottom": "adc", "support": "support", "sup": "support"}


def _safe(s):
    return re.sub(r"[^A-Za-z0-9]", "", s or "")


def patch_of(ver):
    p = (ver or "").split(".")
    return ".".join(p[:2]) if len(p) >= 2 else (ver or "x")


def _file(my_key, opp_key, role, patch):
    os.makedirs(CACHE, exist_ok=True)
    try:
        from smitei18n import lang
        locale = lang()
    except Exception:
        locale = "pt_BR"
    return os.path.join(CACHE, f"{_safe(my_key)}_vs_{_safe(opp_key)}_{_safe(role)}_{_safe(patch)}_{locale}.txt")


# Signatures that mean the "tip" is actually an error the CLI printed (auth/limit/etc). None of
# these appear in a real lane tip, so we can safely reject + never cache/show them.
_BAD_SIGNS = ("api error", "invalid authentication", "authentication credentials",
              "failed to authenticate", "authentication_error", "usage limit", "session limit",
              "rate limit", "rate_limit", "invalid x-api-key", "invalid api key",
              "credit balance", "quota exceeded", "not logged in", "login required",
              "claude auth", "codex auth")


def _looks_bad(text):
    tl = (text or "").lower()
    return any(s in tl for s in _BAD_SIGNS)


def get_tip(my_key, opp_key, role, patch):
    """Cached tip text for this patch, or None if not generated yet. Self-heals: a cache file
    that's actually an error message (from before this fix, or a transient auth blip) is dropped
    so the tip regenerates instead of showing the error forever."""
    fp = _file(my_key, opp_key, role, patch)
    if os.path.exists(fp):
        try:
            t = open(fp, encoding="utf-8").read().strip()
        except Exception:
            return None
        if t and not _looks_bad(t):
            return t
        try:
            os.remove(fp)                      # poisoned/empty -> drop it, regenerate next time
        except Exception:
            pass
    return None


def coach_snapshot(dd, my_name, opp_name, role, locale="en"):
    """Read one exact cached matchup without generating, searching, writing or self-healing."""
    try:
        my_cid = dd["name2id"].get(dd["norm"](my_name))
        opp_cid = dd["name2id"].get(dd["norm"](opp_name))
        if not my_cid or not opp_cid:
            return None
        my_key = dd["id2key"][my_cid]
        opp_key = dd["id2key"][opp_cid]
        patch = patch_of(dd.get("ver"))
        filename = (f"{_safe(my_key)}_vs_{_safe(opp_key)}_{_safe(role)}_"
                    f"{_safe(patch)}_{'pt_BR' if locale == 'pt_BR' else 'en'}.txt")
        path = os.path.join(CACHE, filename)
        text = open(path, encoding="utf-8").read().strip()
        if not text or _looks_bad(text):
            return None
        return {"self_champion": dd["id2name"].get(my_cid, my_name),
                "opponent": dd["id2name"].get(opp_cid, opp_name),
                "role": str(role or "")[:12], "patch": patch,
                "cached_guidance": text[:2400], "source_age_ms": 0}
    except (KeyError, OSError, TypeError, ValueError):
        return None


def _cs_slug(name):
    """ddragon display name -> counterstats URL slug: 'Kha'Zix'->'khazix',
    'Lee Sin'->'lee-sin', 'Dr. Mundo'->'dr-mundo', 'Nunu & Willump'->'nunu-willump'."""
    s = (name or "").lower().replace("&", " ").replace("'", "").replace(".", "")
    return "-".join(s.split())


def _cs_clean(t):
    t = re.sub(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", r"\1", t)    # [[paranoia]] -> paranoia
    t = (t.replace("&#039;", "'").replace("&quot;", '"').replace("&amp;", "&")
          .replace("“", "").replace("”", "").replace("�", ""))
    return " ".join(t.split()).strip(' "')


_CS_BOX = re.compile(
    r"tip-box__tip'><span class='author'>[^<]*</span>\s*(.+?)</span>.*?"
    r"champion/square/([a-z0-9]+)\.png.*?class=\"score\">(-?\d+)</span>", re.S)


# These are USER-SUBMITTED prose. A lot of it is salt stories, rants, or worse — gate hard.
# Any hit here = the tip is dropped entirely, never shown or cached.
_TIP_BLOCK = re.compile(
    r"nigg|n[i1]gg|nig\*|\bfag|f[a4]gg|retard|\bkys\b|kill your ?self|autist|\bcunt\b", re.I)
# Story / rant markers — not advice, drop them (the 'I once made a 420 player 0/10' genre).
_TIP_JUNK = re.compile(
    r"\breport(ed|s)?\b|\bhonor\b|trash ?talk|\btoxic\b|1v1|after the game|\briot\b|"
    r"banned me|\bflam(ed|e)\b|\binted?\b|\bgrief(ed|ing)?\b|\btroll(ed|ing)?\b|\bxd\b", re.I)
# Advice markers — real matchup guidance uses these; used to score + require substance.
_TIP_ADVICE = re.compile(
    r"\byou\b|\byour\b|dodge|bait|poke|avoid|\bwait\b|\bsave\b|ward|respect|all-?in|freeze|"
    r"trade|shove|roam|track|punish|engage|disengag|level ?6|spike|cooldown|position|kite|"
    r"\bpeel\b|sidestep|\bzone\b|early game|\bgank|\bcc\b|ult\b|hook|stun", re.I)


def _tip_ok(text):
    """True if a scraped tip reads as actual ADVICE, not a story/rant/abuse."""
    tl = text.lower()
    if _TIP_BLOCK.search(tl) or _TIP_JUNK.search(tl):
        return False
    if sum(ord(c) > 127 for c in text) > 5:
        return False                              # non-English (counterstats has PT/ES/etc tips)
    if not _TIP_ADVICE.search(tl):
        return False                              # no advice vocabulary at all -> skip
    # story detector: heavy first-person narration with little advice = someone's game recap
    narration = len(re.findall(r"\bi\b|\bhe\b|\bme\b|\bhim\b", tl))
    if narration >= 4 and len(_TIP_ADVICE.findall(tl)) < 3:
        return False
    return True


def _tip_score(text):
    return len(set(m.lower() for m in _TIP_ADVICE.findall(text)))   # distinct advice cues


def fetch_cs_tips(enemy_name, patch):
    """Every USABLE written counter-tip for playing AGAINST `enemy_name`, scraped from
    counterstats.net and quality-filtered: [{lane, champ, votes, text}]. champ = the author's
    champion (the matchup POV). Cached per enemy+patch; [] on any failure — caller falls back."""
    fp = os.path.join(CS_CACHE, f"{_safe(enemy_name)}_{_safe(patch)}_v2.json")   # v2 = filtered
    try:
        return json.load(open(fp, encoding="utf-8"))
    except Exception:
        pass
    try:
        req = urllib.request.Request(
            f"https://www.counterstats.net/league-of-legends/{_cs_slug(enemy_name)}",
            headers=CS_HDRS)
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return []
    tips = []
    # lane sections: <div class="champ-box__tips__wrap LANE" data-lane="LANE"> ... boxes ...
    secs = list(re.finditer(r'champ-box__tips__wrap\s+([a-z]+)"', html))
    for i, m in enumerate(secs):
        lane = m.group(1)
        chunk = html[m.end(): secs[i + 1].start() if i + 1 < len(secs) else len(html)]
        for b in _CS_BOX.finditer(chunk):
            text = _cs_clean(b.group(1))[:360]         # check + store the SAME string
            if len(text) < 60 or not _tip_ok(text):    # too short, not advice, or non-English
                continue
            tips.append({"lane": lane, "champ": b.group(2), "votes": int(b.group(3)),
                         "text": text})
    if tips:
        try:
            os.makedirs(CS_CACHE, exist_ok=True)
            json.dump(tips, open(fp, "w", encoding="utf-8"))
        except Exception:
            pass
    return tips


def written_tip(dd, my_cid, opp_cid, role, patch):
    """The best HUMAN-WRITTEN tip for my champ vs the enemy in this lane, or None.
    Preference order: a tip written by a player of MY champion about this enemy (the true
    matchup POV, best votes first), else the best general 'how to beat them' tips for the
    lane. Returns display-ready text."""
    opp_name = dd["id2name"].get(opp_cid, "")
    if not opp_name:
        return None
    tips = fetch_cs_tips(opp_name, patch)
    if not tips:
        return None
    lane = CS_LANE.get((role or "").lower(), "")
    norm = dd["norm"]
    mine_norm = norm(dd["id2name"].get(my_cid, ""))
    pool = [t for t in tips if t["lane"] == lane] or tips
    def rank(t):                                  # most advice cues, then votes, then length
        return (_tip_score(t["text"]), t["votes"], min(len(t["text"]), 320))
    mine = sorted((t for t in pool if norm(t["champ"]) == mine_norm), key=rank, reverse=True)
    if mine:
        return tf("{tip}  — a {champ} main (MOBAFire)",
                  tip=mine[0]["text"], champ=dd["id2name"].get(my_cid, ""))
    best = sorted(pool, key=rank, reverse=True)[:2]
    if not best:
        return None
    out = "  ·  ".join(t["text"] for t in best[:1] if t["text"])
    return tf("{tip}  — guide authors (MOBAFire)", tip=out) if out else None


def generate_tip(my_name, my_key, opp_name, opp_key, role, patch):
    """Real written-guide tip first (counterstats.net scrape, cached); the LLM+web-search
    generator only as fallback when no written tip exists. Returns (text, error)."""
    try:
        dd = lb.ddragon()
        my_cid = dd["name2id"].get(dd["norm"](my_name), 0)
        opp_cid = dd["name2id"].get(dd["norm"](opp_name), 0)
        if my_cid and opp_cid:
            t = written_tip(dd, my_cid, opp_cid, role, patch)
            if t:
                try:
                    open(_file(my_key, opp_key, role, patch), "w", encoding="utf-8").write(t)
                except Exception:
                    pass
                return t, None
    except Exception:
        pass
    return _generate_tip_llm(my_name, my_key, opp_name, opp_key, role, patch)


def _generate_tip_llm(my_name, my_key, opp_name, opp_key, role, patch):
    """Fallback: generate with the logged-in CLI (web search) + cache. Returns (text, error)."""
    provider = cfg.load().get("llm_provider", cfg.LLM_PROVIDER_DEFAULT)
    try:
        from smitei18n import lang
        language = "Brazilian Portuguese" if lang() == "pt_BR" else "English"
    except Exception:
        language = "Brazilian Portuguese"
    prompt = (
        f"Patch {patch}. Search the web for the CURRENT {my_name} vs {opp_name} {role} matchup "
        f"(Mobafire, u.gg, Mobalytics, Reddit). In 2-3 sentences, give a SPECIFIC, up-to-date tip on "
        f"HOW TO PLAY THE LANE: which enemy ability/abilities to dodge or bait and how, the trade and "
        f"wave pattern, and when you win vs when you lose (you may reference generic timings like "
        f"'level 6' or 'your first item spike'). "
        f"CRITICAL: do NOT recommend or name ANY runes, keystones, summoner spells, or items - the "
        f"live op.gg build is shown to the player separately and the LLM gets builds wrong. Keep it "
        f"purely to lane mechanics and decisions. If you can't find current info, use your own best "
        f"knowledge. Reply in {language}. Plain text only - no preamble, no markdown, no bullet points, no headers."
    )
    text, err = llmcli.call(prompt, provider, allow_web=True, timeout=170)
    if not text or _looks_bad(text):          # never cache/return an error string as a tip
        return None, (err or "tip unavailable")
    text = " ".join(text.split())          # collapse to one block
    try:
        open(_file(my_key, opp_key, role, patch), "w", encoding="utf-8").write(text)
    except Exception:
        pass
    return text, None


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("usage: python lolmatchup.py <myChamp> <oppChamp> [role]")
        return
    dd = lb.ddragon()
    patch = patch_of(dd["ver"])
    my = dd["name2id"].get(dd["norm"](args[0]))
    opp = dd["name2id"].get(dd["norm"](args[1]))
    role = (args[2].lower() if len(args) > 2 else "mid")
    if not my or not opp:
        print("unknown champ name")
        return
    mk, ok = dd["id2key"][my], dd["id2key"][opp]
    cached = get_tip(mk, ok, role, patch)
    if cached:
        print("[cached]", cached)
        return
    print("(generating with web search, ~60-120s...)")
    t, err = generate_tip(dd["id2name"][my], mk, dd["id2name"][opp], ok, role, patch)
    print(t if t else f"[failed: {err}]")


if __name__ == "__main__":
    main()
