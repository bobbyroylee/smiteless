#!/usr/bin/env python3
"""lolbuild.py — fast per-game LoL build card (op.gg data, decoded via ddragon).

Speed: ddragon static data is cached locally per-patch, so after the first run a
build card prints in ~1-2s.

Usage:
  python lolbuild.py                         # AUTO: read champ select from the running League client (LCU)
  python lolbuild.py Qiyana                  # manual champ, default role jungle
  python lolbuild.py Qiyana jungle           # manual champ + role
  python lolbuild.py Qiyana jungle Rengar    # + enemy jungler -> matchup note
  python lolbuild.py "Kha'Zix" jungle --tier gold
Roles: top jungle mid adc support
"""
import sys, os, json, time, ssl, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CACHE = os.path.expanduser("~/.claude/cache/ddragon")
LOCKFILES = [
    r"F:\Riot Games\League of Legends\lockfile",
    r"C:\Riot Games\League of Legends\lockfile",
    r"C:\Program Files\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    os.path.expanduser(r"~/Riot Games/League of Legends/lockfile"),
]
ROLE = {"top":"top","jungle":"jungle","jg":"jungle","mid":"mid","middle":"mid",
        "adc":"adc","bot":"adc","bottom":"adc","sup":"support","support":"support","utility":"support"}

def http(url, headers=None, timeout=8, insecure=False, data=None):
    ctx = ssl._create_unverified_context() if insecure else None
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA}, data=data)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.load(r)


def _atomic_json(fp, data):
    """Write JSON atomically so an interrupted run can't leave a corrupt cache file."""
    tmp = f"{fp}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, fp)


def _ddragon_version():
    """Latest patch, cached ~6h so we skip the network call on every run, and fall
    back to the newest locally cached patch if we're offline."""
    vf = os.path.join(CACHE, "_version.json")
    try:
        c = json.load(open(vf, encoding="utf-8"))
        if time.time() - c.get("ts", 0) < 21600 and c.get("ver"):
            return c["ver"]
    except Exception:
        pass
    try:
        ver = http("https://ddragon.leagueoflegends.com/api/versions.json")[0]
        try:
            _atomic_json(vf, {"ver": ver, "ts": time.time()})
        except Exception:
            pass
        return ver
    except Exception:
        # offline: reuse the newest patch we've already cached
        cached = sorted(f[:-len("_champion.json")] for f in os.listdir(CACHE)
                        if f.endswith("_champion.json")) if os.path.isdir(CACHE) else []
        if cached:
            return cached[-1]
        raise

# ---------- ddragon (cached per patch) ----------
_DD_MEMO = {}              # parse the static data once per process (it's the same all session)


def ddragon():
    """Load Data Dragon in the active UI locale, with a locale-scoped cache."""
    try:
        from smitei18n import lang
        locale = "pt_BR" if lang() == "pt_BR" else "en_US"
    except Exception:
        locale = "pt_BR"
    ver = _ddragon_version()
    memo_key = (ver, locale)
    if _DD_MEMO.get("key") == memo_key and _DD_MEMO.get("dd") is not None:
        return _DD_MEMO["dd"]
    os.makedirs(CACHE, exist_ok=True)
    def load(name):
        fp = os.path.join(CACHE, f"{ver}_{locale}_{name}.json")
        if os.path.exists(fp):
            try:
                return json.load(open(fp, encoding="utf-8"))
            except Exception:
                pass  # corrupt cache file -> re-fetch below
        d = http(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/{locale}/{name}.json")
        try:
            _atomic_json(fp, d)
        except Exception:
            pass
        return d
    _items = load("item")["data"]
    items = {int(k): v["name"] for k, v in _items.items()}
    item_data = {int(k): v for k, v in _items.items()}   # full stats/tags for threat analysis
    rr = load("runesReforged"); runes = {}; trees = {}
    for s in rr:
        trees[s["id"]] = s["name"]
        for slot in s["slots"]:
            for r in slot["runes"]: runes[r["id"]] = r["name"]
    spells = {int(v["key"]): v["name"] for v in load("summoner")["data"].values()}
    champ = load("champion")["data"]
    def norm(x): return "".join(c for c in x.lower() if c.isalnum())
    name2id = {}; id2name = {}; id2key = {}; id2tags = {}; id2info = {}
    for c in champ.values():
        cid = int(c["key"]); id2name[cid] = c["name"]; id2key[cid] = c["id"]
        id2tags[cid] = c.get("tags", [])
        id2info[cid] = c.get("info", {})        # attack/defense/magic/difficulty 0-10 (for good/bad tags)
        name2id[norm(c["name"])] = cid; name2id[norm(c["id"])] = cid
    dd = dict(ver=ver, locale=locale, items=items, item_data=item_data, runes=runes, trees=trees, spells=spells,
              name2id=name2id, id2name=id2name, id2key=id2key, id2tags=id2tags, id2info=id2info, norm=norm)
    _DD_MEMO["key"], _DD_MEMO["dd"] = memo_key, dd
    return dd

# ---------- op.gg ----------
OPGG_CACHE = os.path.expanduser("~/.claude/cache/opgg")
OPGG_TTL = 6 * 3600        # op.gg champ data only shifts patch-to-patch; 6h keeps champ select snappy
def opgg(cid, role, tier=None):
    """op.gg champ data, disk-cached per (champ, role, tier) for OPGG_TTL. On a network
    hiccup it serves stale cache rather than failing the build/scout. Empty results aren't
    cached, so a transient blank re-fetches next time."""
    role = ROLE.get((role or "").lower(), (role or "").lower())
    fp = os.path.join(OPGG_CACHE, f"{cid}_{role}_{tier or 'def'}.json")
    try:
        c = json.load(open(fp, encoding="utf-8"))
        if time.time() - c.get("ts", 0) < OPGG_TTL:
            return c.get("data", {})
    except Exception:
        pass
    url = f"https://lol-api-champion.op.gg/api/na/champions/ranked/{cid}/{role}"
    if tier: url += f"?tier={tier}"
    try:
        data = http(url, headers={"User-Agent": UA, "Accept": "application/json"}).get("data", {})
    except Exception:
        try:                                   # serve stale on failure if we have any
            return json.load(open(fp, encoding="utf-8")).get("data", {})
        except Exception:
            raise
    if data:
        try:
            os.makedirs(OPGG_CACHE, exist_ok=True)
            _atomic_json(fp, {"data": data, "ts": time.time()})
        except Exception:
            pass
    return data


def opgg_all_ranked():
    """op.gg's whole champion pool with per-position stats (win_rate / play / pick_rate), for
    'strongest champs in role X' reads (e.g. ban ideas). One list, disk-cached ~6h. [] on any
    failure (serves stale if present). Each entry: {id, average_stats{...}, positions:[{name,
    stats{win_rate,play,...}}]}."""
    fp = os.path.join(OPGG_CACHE, "_ranked_all.json")
    try:
        c = json.load(open(fp, encoding="utf-8"))
        if time.time() - c.get("ts", 0) < OPGG_TTL:
            return c.get("data", [])
    except Exception:
        pass
    try:
        raw = http("https://lol-api-champion.op.gg/api/na/champions/ranked",
                   headers={"User-Agent": UA, "Accept": "application/json"}, timeout=10)
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
    except Exception:
        try:
            return json.load(open(fp, encoding="utf-8")).get("data", [])
        except Exception:
            return []
    if isinstance(data, list) and data:
        try:
            os.makedirs(OPGG_CACHE, exist_ok=True)
            _atomic_json(fp, {"data": data, "ts": time.time()})
        except Exception:
            pass
        return data
    return []


# ---------- op.gg matchup win rates ----------
def gather_matchups(dd, my_cid, role, enemy_ids):
    """op.gg same-role matchup win rates for the enemy champs in the table.
    Returns ([(enemy_name, wr%, games), ...], your_overall_wr)."""
    try:
        d = opgg(my_cid, role)
    except Exception:
        return [], None
    if not d or "summary" not in d:
        return [], None
    cmap = {c["champion_id"]: c for c in d.get("counters", []) if c.get("play", 0) >= 20}
    out = []
    for e in enemy_ids:
        c = cmap.get(e)
        if c:
            out.append((dd["id2name"].get(e, e), c["win"] / c["play"] * 100, c["play"]))
    tier = d["summary"]["average_stats"].get("win_rate")
    return out, tier


def gather_lane_matchups(dd, allies, enemies):
    """Pair each lane STRICTLY BY ROLE using the real champion in that slot - no
    guessing. ally[role] is matched against enemy[role] (the actual enemy who plays
    that role, read from the live game), and the WR is op.gg's number for THAT exact
    pair, or None if op.gg has no sample for it. We never substitute a different
    enemy. Both `allies` and `enemies` are lists of (champ_id, role); a lane is only
    returned when BOTH roles are known (i.e. in-game; in champ select enemy roles are
    hidden, so no pairings are produced).
    Returns [(ally_name, role, enemy_name, wr_or_None, games_or_None), ...]."""
    enemy_by_role = {}
    for cid, role in enemies:
        if cid and role and role not in enemy_by_role:
            enemy_by_role[role] = cid
    out = []
    for cid, role in allies:
        if not cid or not role:
            continue
        opp = enemy_by_role.get(role)
        if not opp:
            continue  # enemy role for this lane unknown -> do NOT fabricate a pairing
        wr = games = None
        try:
            d = opgg(cid, role)
        except Exception:
            d = None
        if isinstance(d, dict):
            for c in d.get("counters", []):
                if c.get("champion_id") == opp and c.get("play", 0) >= 20:
                    wr, games = c["win"] / c["play"] * 100, c["play"]
                    break
        out.append((dd["id2name"].get(cid, cid), role,
                    dd["id2name"].get(opp, opp), wr, games))
        time.sleep(0.1)  # rapid op.gg calls get throttled; space them out
    return out


# ---------- format ----------
def card(dd, cid, role, tier, enemy_cid=None):
    role = ROLE.get(role.lower(), role.lower())
    d = opgg(cid, role, tier)
    if not d or "summary" not in d:
        return f"No op.gg data for {dd['id2name'].get(cid, cid)} {role}."
    av = d["summary"]["average_stats"]
    name = dd["id2name"].get(cid, str(cid))
    tiername = {1:"S",2:"A",3:"B",4:"C",5:"D"}.get(av.get("tier"), av.get("tier"))
    out = []
    out.append(f"{name.upper()} - {role.upper()}   (op.gg {tier or 'Emerald+'}, patch {dd['ver']}"
               f" | WR {av['win_rate']*100:.1f}% | pick {av['pick_rate']*100:.1f}% | {tiername}-tier | {av['play']}g)")
    rp = max(d["runes"], key=lambda r: r["play"])
    pr, sr = rp["primary_rune_ids"], rp["secondary_rune_ids"]
    out.append(f"RUNES  {dd['trees'].get(rp['primary_page_id'])}: "
               + " / ".join(dd['runes'].get(x, x) for x in pr))
    shard = {5008:"Adaptive",5005:"AtkSpd",5007:"Haste",5011:"Health",5001:"HP-scale",5010:"MoveSpd",5013:"Tenacity"}
    out.append(f"       {dd['trees'].get(rp['secondary_page_id'])}: " + " / ".join(dd['runes'].get(x, x) for x in sr)
               + "   |  Shards: " + " / ".join(shard.get(x, str(x)) for x in rp["stat_mod_ids"]))
    ss = max(d["summoner_spells"], key=lambda x: x["play"])
    stt = max(d["starter_items"], key=lambda x: x["play"])
    out.append(f"SUMS   {' + '.join(dd['spells'].get(i) for i in ss['ids'])}"
               f"     START  {', '.join(dd['items'].get(i, str(i)) for i in stt['ids'])}")
    sk = max(d["skills"], key=lambda x: x["play"])
    sm = max(d["skill_masteries"], key=lambda x: x["play"])
    out.append(f"SKILL  max {' > '.join(sm['ids'])}   (lvl: {','.join(sk['order'][:6])})")
    core = max(d["core_items"], key=lambda x: x["play"])
    boots = max(d["boots"], key=lambda x: x["play"])
    out.append(f"CORE   {' > '.join(dd['items'].get(i, str(i)) for i in core['ids'])}   ({core['win']/core['play']*100:.0f}%)")
    out.append(f"BOOTS  {dd['items'].get(boots['ids'][0], boots['ids'][0])}")
    situ = sorted((x for x in d["last_items"] if x["play"] >= 150), key=lambda x: -x["win"]/x["play"])[:4]
    out.append("SITU   " + " / ".join(f"{dd['items'].get(s['ids'][0], s['ids'][0])} ({s['win']/s['play']*100:.0f}%)" for s in situ))
    if enemy_cid:
        cm = next((c for c in d.get("counters", []) if c["champion_id"] == enemy_cid), None)
        en = dd["id2name"].get(enemy_cid, enemy_cid)
        if cm and cm["play"] >= 20:
            wr = cm["win"]/cm["play"]*100
            tag = "FAVORED" if wr >= 51 else ("EVEN" if wr >= 49 else "UNFAVORED")
            out.append(f"VS {en.upper()}: {wr:.1f}% ({cm['play']}g) — {tag}")
        else:
            out.append(f"VS {en.upper()}: not enough matchup data on op.gg (play it standard).")
    return "\n".join(out)

def main():
    t0 = time.time()
    args = [a for a in sys.argv[1:]]
    tier = None
    if "--tier" in args:
        i = args.index("--tier"); tier = args[i+1]; del args[i:i+2]
    dd = ddragon()
    enemy_cid = None
    if not args:  # AUTO: champ select / loading screen / in-game
        import lolgame as lg
        info, err = lg.resolve(dd)
        if err:
            print(err); return
        cid, role = info["my"], info["pos"]
        src = info.get("source", "auto")
        enemies = ", ".join(dd["id2name"].get(c, c) for c, _ in info["enemies"]) or "none yet"
        if not role:  # loading screen with no cached role
            print(f"[{src}] you: {dd['id2name'].get(cid)} - role not cached "
                  f"(press Win+B during champ select to cache it; it's auto-detected in-game).\n"
                  f"enemies: {enemies}\nBuild card needs a role; the coach analysis below infers it.")
            return
        print(f"[{src}] you: {dd['id2name'].get(cid)} ({role}); enemies: {enemies}\n")
        print(card(dd, cid, role, tier))
    else:
        cid = dd["name2id"].get(dd["norm"](args[0]))
        if not cid:
            print(f"Unknown champ '{args[0]}'."); return
        role = args[1] if len(args) > 1 else "jungle"
        if len(args) > 2:
            enemy_cid = dd["name2id"].get(dd["norm"](args[2]))
        print(card(dd, cid, role, tier, enemy_cid))
    print(f"\n(pulled in {time.time()-t0:.1f}s)")

if __name__ == "__main__":
    main()
