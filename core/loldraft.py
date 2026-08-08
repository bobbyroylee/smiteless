#!/usr/bin/env python3
"""loldraft.py — the shareable LIVE DRAFT LINK.

Publishes the current champ select (both teams, bans, and per-seat pick suggestions
with runes/summs/core items) to a Firebase Realtime Database over plain REST, and
drops ONE link into the champ-select chat. Anyone in the lobby who clicks it lands on
the static GitHub Pages board (docs/draft/), which streams this data live over SSE —
no server, no account, updates as the draft evolves.

Costs nothing to run: the page is static hosting, the data channel is Firebase's free
Spark tier, and everything heavy (art, names) comes from Riot's public ddragon CDN in
the viewer's browser. This module only ships a few KB of champion/rune IDs.

Setup (one-time, see docs/DRAFTLINK.md): create a free Firebase RTDB, paste its URL
into Settings -> "Draft link database". No URL = the whole feature stays dormant.

CLI (manual seeding / testing, no lobby needed):
  python loldraft.py test        # publish a fake draft, print the link to open
"""
import json
import os, re, sys, threading, time, secrets
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import lolgame as lg
import phasecheck
import smiteconfig as cfg

# One publisher per process; champ select ending resets it for the next lobby.
_ST = {"thread": None, "draft_id": "", "posted": False, "opened": False, "last_pub": "",
       "sugg": {}, "sugg_key": {}, "stop": False}
_LOCK = threading.Lock()

_LOG = os.path.expanduser("~/.claude/smiteless_draft.log")


def _dlog(msg):
    """The publisher had NO logging, so every 'it didn't swap' was a guess. Now every
    lifecycle step (spawn, publish, champ-select end, scout-phase iteration, PATCH result,
    retire) leaves a line in ~/.claude/smiteless_draft.log — the swap can't fail silently."""
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%m-%d %H:%M:%S')} [{_ST.get('draft_id','')[:6]}] {msg}\n")
    except Exception:
        pass

SUGG_PER_SEAT = 3          # suggestion cards per seat (each carries runes -> keep payload lean)
PUBLISH_POLL = 2.0         # seconds between champ-select reads
_ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # unambiguous, URL-safe

# The DB host baked into the hosted page (docs/draft/index.html DEFAULT_DB). When the
# user's DB IS this one, the shared link can omit "&db=host.firebaseio.com" entirely and
# be just "…/draft/#d=ID" — short and not phishing-shaped. Keep the two in sync.
_DEFAULT_PAGE_DB = "smiteless-draft-default-rtdb.firebaseio.com"
BRAND = "DraftBoard"       # the shareable feature's identity (chat message + page)


def _new_id(n=12):
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(n))


def _db_url(settings=None):
    """The user's Firebase RTDB base URL from settings, normalized ('' = feature off).
    Accepts 'https://x-default-rtdb.firebaseio.com' or the bare host, with/without '/'."""
    s = settings or cfg.load()
    raw = (s.get("draft_db") or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = "https://" + raw
    host = raw.split("://", 1)[1].split("/", 1)[0]
    # only real Firebase RTDB hosts — anything else in the setting is a paste mistake
    if not (host.endswith(".firebaseio.com") or host.endswith(".firebasedatabase.app")):
        return ""
    return "https://" + host


def _page_url(settings=None):
    s = settings or cfg.load()
    return (s.get("draft_page") or "").strip().rstrip("/") or cfg.STRINGS["draft_page"].rstrip("/")


def link_for(draft_id, settings=None):
    """The URL that goes into chat. When the user's DB is the one the hosted page already
    bakes in (_DEFAULT_PAGE_DB — the normal case), the link is just '…/draft/#d=ID' — short
    and trustworthy. A self-hoster pointed at a different DB still gets the '&db=host' form
    so their page knows where to stream from."""
    db = _db_url(settings)
    host = db.split("://", 1)[1] if db else ""
    base = f"{_page_url(settings)}/#d={draft_id}"
    return base if host == _DEFAULT_PAGE_DB else f"{base}&db={host}"


# ---------- Firebase REST (stdlib only; the DB is public per its rules, auth-free) ----------
def _fb(method, db, path, obj=None, timeout=6):
    req = urllib.request.Request(f"{db}/{path}.json", method=method,
                                 data=(json.dumps(obj, separators=(",", ":")).encode()
                                       if obj is not None else None),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": lb.UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def publish(db, draft_id, payload):
    _fb("PUT", db, f"drafts/{draft_id}", payload)


def retire(db, draft_id):
    """Mark a draft ended (page shows 'draft over') and let it be tiny; full delete of
    stale drafts happens on the NEXT lobby so a refresh mid-game still shows something."""
    try:
        _fb("PATCH", db, f"drafts/{draft_id}", {"end": int(time.time())})
        _dlog(f"RETIRED {draft_id[:6]}")
    except Exception:
        pass


def _delete(db, draft_id):
    try:
        _fb("DELETE", db, f"drafts/{draft_id}")
    except Exception:
        pass


# ---------- champ-select chat ----------
def post_chat_link(url):
    """Drop the link into the CHAMP SELECT chat via the LCU (lol-chat). True on success."""
    lc = lg._lcu()
    if not lc:
        return False
    port, hdr = lc
    try:
        convs = lb.http(f"https://127.0.0.1:{port}/lol-chat/v1/conversations",
                        headers=hdr, timeout=4, insecure=True)
        conv = next((c for c in (convs or []) if c.get("type") == "championSelect"), None)
        if not conv:
            return False
        msg = (cfg.load().get("draft_msg") or "").strip() or \
            f"{BRAND} — live picks + runes for our lobby:"
        body = json.dumps({"body": f"{msg} {url}", "type": "chat"}).encode()
        req = urllib.request.Request(
            f"https://127.0.0.1:{port}/lol-chat/v1/conversations/{conv['id']}/messages",
            data=body, headers={**hdr, "Content-Type": "application/json"}, method="POST")
        import ssl
        with urllib.request.urlopen(req, timeout=4,
                                    context=ssl._create_unverified_context()) as r:
            r.read()
        return True
    except Exception:
        return False


# ---------- payload ----------
def _rune_block(d):
    """Terse rune/summs/items block from an opgg() champ dict: ids only, the viewer's
    browser resolves names + icons from ddragon. None if the data is too thin."""
    pages = sorted((r for r in (d.get("runes") or []) if r.get("primary_rune_ids")),
                   key=lambda r: r.get("play", 0), reverse=True)
    if not pages:
        return None
    rp = pages[0]
    out = {"pp": rp.get("primary_page_id"), "pr": list(rp.get("primary_rune_ids") or []),
           "sp": rp.get("secondary_page_id"), "sr": list(rp.get("secondary_rune_ids") or [])}
    if rp.get("stat_mod_ids"):
        out["st"] = list(rp["stat_mod_ids"])
    sspells = sorted((x for x in (d.get("summoner_spells") or []) if x.get("ids")),
                     key=lambda x: x.get("play", 0), reverse=True)
    if sspells:
        out["sm"] = list(sspells[0]["ids"])
    cores = d.get("core_items") or []
    if cores:
        out["it"] = list(max(cores, key=lambda x: x.get("play", 0)).get("ids") or [])
    return out


def _suggestion(dd, cid, role, enemy_ids):
    """One suggestion card: champ + overall WR/tier + runes + the matchup WRs vs the
    locked enemies op.gg has a same-role sample for."""
    try:
        d = lb.opgg(cid, role)
    except Exception:
        return None
    if not d or "summary" not in d:
        return None
    av = d["summary"].get("average_stats") or {}
    card = {"c": cid, "wr": round((av.get("win_rate") or 0) * 100, 1),
            "t": {1: "S", 2: "A", 3: "B", 4: "C", 5: "D"}.get(av.get("tier"), "")}
    r = _rune_block(d)
    if r:
        card["r"] = r
    vs = []
    cmap = {c.get("champion_id"): c for c in (d.get("counters") or []) if c.get("play", 0) >= 20}
    for eid in enemy_ids:
        c = cmap.get(eid)
        if c:
            vs.append({"c": eid, "wr": round(c["win"] / c["play"] * 100, 1)})
    if vs:
        card["vs"] = vs
    return card


def _seat_suggestions(dd, role, ally_ids, enemy_ids, taken):
    """Suggestion cards for one seat. Reuses the overlay's pick brain (counters + comp
    fit, meta fallback) with no mastery gate — these are for TEAMMATES whose champion
    pools we don't know, so it's 'good for THIS game', not 'good for you'."""
    import smitecard as sc                     # lazy: smitecard imports us back
    cids = sc.suggest_champs(dd, role, ally_ids, enemy_ids, topn=SUGG_PER_SEAT + 2, fam=None)
    out = []
    for cid in cids:
        if cid in taken:
            continue
        card = _suggestion(dd, cid, role, enemy_ids)
        if card:
            out.append(card)
        if len(out) >= SUGG_PER_SEAT:
            break
        time.sleep(0.1)                        # space op.gg fetches (cache absorbs repeats)
    return out


def build_payload(dd, info, with_suggestions=True):
    """The full draft document: tiny (IDs only), the page hydrates it from ddragon."""
    allies = info.get("allies") or []
    enemies = info.get("enemies") or []
    bans_my = [c for c in (info.get("bans_my") or []) if c]
    bans_their = [c for c in (info.get("bans_their") or []) if c]
    ally_ids = [c for c, _ in allies if c]
    enemy_ids = [c for c, _ in enemies if c]
    taken = set(bans_my) | set(bans_their) | set(ally_ids) | set(enemy_ids)
    seats = []
    for cid, role in allies:
        seat = {"role": role or "", "c": cid or 0}
        if cid and role:
            own = _suggestion(dd, cid, role, enemy_ids)   # runes/summs/items for the LOCKED pick
            if own:
                seat["own"] = own
        if with_suggestions and role:
            key = (role, tuple(sorted(taken)))
            with _LOCK:
                cached = _ST["sugg_key"].get(role) == key and _ST["sugg"].get(role)
            if cached:
                seat["sugg"] = _ST["sugg"][role]
            else:
                sugg = _seat_suggestions(dd, role, ally_ids, enemy_ids, taken)
                with _LOCK:
                    _ST["sugg"][role] = sugg
                    _ST["sugg_key"][role] = key
                if sugg:
                    seat["sugg"] = sugg
        seats.append(seat)
    from smitei18n import lang
    return {"v": 1, "ts": int(time.time()), "patch": dd.get("ver", ""), "lang": lang(),
            "seats": seats, "enemy": enemy_ids,
            "bans": {"a": bans_my, "e": bans_their}}


# ---------- scout mirror: turn the page into the loading/in-game scoreboard ----------
def _scout_row(r):
    """One player from lolload.brief -> the compact web-scout shape (IDs + short strings;
    the page hydrates art/names from ddragon just like the draft view)."""
    rk = r.get("rank_full") or {}
    row = {"c": r.get("cid") or 0, "role": r.get("role") or "", "me": bool(r.get("me"))}
    if r.get("player"):
        row["n"] = r["player"].split("#")[0][:16]
    if rk.get("tier"):
        row["rk"] = {"t": rk.get("tier"), "d": rk.get("div", ""), "lp": rk.get("lp", 0)}
    form = r.get("form") or []
    if form:
        row["f"] = [1 if x else 0 for x in form[:10]]
    row["g"], row["w"] = int(r.get("n", 0)), int(r.get("w", 0))
    if r.get("cg"):
        row["cg"], row["cw"] = int(r["cg"]), int(r.get("cw", 0))
    if r.get("kdar") is not None:
        row["kda"] = r["kdar"]
    if r.get("perf") is not None:
        row["p"] = r["perf"]
    if r.get("pts"):
        row["pts"] = int(r["pts"])
    tags = r.get("tags") or []
    if tags:
        row["t"] = [[str(t), tone] for t, tone in tags[:4]]
    return row


def _lane_pairs(allies, enemies):
    """ally index -> the enemy row sharing its role (the lane opponent). In-game the roster
    exposes everyone's role, so we CAN pair lanes here (champ select can't — roles are hidden)."""
    by_role = {}
    for e in enemies:
        rl = (e.get("role") or "").lower()
        if rl and rl not in by_role:
            by_role[rl] = e
    return {i: by_role[(a.get("role") or "").lower()]
            for i, a in enumerate(allies) if (a.get("role") or "").lower() in by_role}


def _tip_key(my_cid, opp_cid, role):
    return (my_cid, opp_cid, (role or "").lower())


def _ensure_tips(dd, wants):
    """Fetch any missing matchup tips on a BACKGROUND thread and stash them in _ST['tips'].
    written_tip() scrapes counterstats with a 12s timeout per enemy — doing that inline would
    stall the scout PATCH that swaps the page (the v0.9.37 regression). So the scoreboard ships
    immediately with whatever tips are already cached, and a later 6s tick PATCHes the rest in."""
    with _LOCK:
        cache = _ST.setdefault("tips", {})
        todo = [k for k in wants if k not in cache]
        if not todo or _ST.get("tips_busy"):
            return
        _ST["tips_busy"] = True
    def work():
        try:
            import lolmatchup as lm
            patch = lm.patch_of(dd.get("ver", ""))
            for (my_cid, opp_cid, role) in todo:
                tip = ""
                try:
                    tip = lm.written_tip(dd, my_cid, opp_cid, role, patch) or ""
                except Exception:
                    tip = ""
                with _LOCK:
                    _ST["tips"][(my_cid, opp_cid, role)] = tip
        finally:
            with _LOCK:
                _ST["tips_busy"] = False
    threading.Thread(target=work, daemon=True).start()


def _threat(enemies):
    """The one enemy account most likely to decide the game (perf, sharpened by OTP mastery,
    a live streak, champ comfort) — mirrors the loading overlay's WATCH line. None if the lobby
    is quiet. Feeds the viewer's 'WATCH <champ>' header chip."""
    best, bs = None, -1.0
    for r in enemies or []:
        if not r.get("scouted"):
            continue
        s = float(r.get("perf") or 50)
        if r.get("pts", 0) >= 100_000:
            s += 12
        f = r.get("form") or []
        if len(f) >= 3 and all(f[:3]):
            s += 8
        if r.get("cg", 0) >= 5 and r.get("cw", 0) * 2 > r["cg"]:
            s += 6
        if s > bs:
            bs, best = s, r
    if best and bs >= 78:
        return {"c": best.get("cid", 0),
                "txt": " · ".join(t for t, _ in (best.get("tags") or [])[:2])}
    return None


def _scout_payload(dd, brief):
    allies = brief.get("allies") or []
    enemies = brief.get("enemies") or []
    pairs = _lane_pairs(allies, enemies)
    cache = _ST.get("tips", {})
    wants, arows, me = [], [], -1
    for i, r in enumerate(allies):
        row = _scout_row(r)
        if row.get("me"):
            me = i
        opp = pairs.get(i)
        if opp and opp.get("cid"):
            row["lane"] = opp["cid"]                       # lane opponent's champ id
            k = _tip_key(r.get("cid"), opp.get("cid"), r.get("role"))
            wants.append(k)
            tip = cache.get(k)                             # attach ONLY if already fetched —
            if tip:                                        #   never block the swap on a scrape
                row["tip"] = tip[:420]
        arows.append(row)
    _ensure_tips(dd, wants)                                # fill missing tips off-thread
    from smitei18n import lang
    pay = {"lang": lang(), "allies": arows, "enemies": [_scout_row(r) for r in enemies],
           "plan": (brief.get("plan") or [])[:4],
           "wincons": brief.get("wincons") or {}, "me": me}
    th = _threat(enemies)
    if th:
        pay["threat"] = th
    return pay


_GAME_PHASES = ("GameStart", "InProgress", "Reconnect")


def _scout_phase(dd, db, cap_s=25 * 60):
    """After champ select ends, keep the SAME draft node alive and PATCH a full scout onto
    it — both teams' rank, last-10 form, this-champ record, performance grade, and the
    profile-read tags — so the shared page becomes the live scoreboard the moment the game
    loads. Ends when the client leaves the game (or a 25-min safety cap)."""
    import lolload
    last, last_live, t0, seen = "", "", time.time(), False
    gone = 0                       # consecutive non-game polls AFTER we've seen the game
    _dlog(f"scout phase START (phase={phasecheck.phase()})")
    while not _ST["stop"] and time.time() - t0 < cap_s:
        if not cfg.load().get("draft_link", True):
            _dlog("scout phase EXIT: draft_link turned off")
            return
        ph = phasecheck.phase()
        in_game = ph in _GAME_PHASES
        if in_game:
            seen, gone = True, 0
        elif seen:
            # DEBOUNCE: a single :2999 / lockfile hiccup returns "" mid-game — DON'T retire on
            # one blip (that permanently killed the swap). Only quit after 3 straight non-game
            # polls (~18s), which means the game genuinely ended.
            gone += 1
            _dlog(f"non-game poll {gone}/3 (phase={ph!r}) after seeing game")
            if gone >= 3:
                _dlog("scout phase EXIT: game ended")
                return
        elif time.time() - t0 > 180:
            _dlog(f"scout phase EXIT: never loaded in 180s (phase={ph!r}) — dodge?")
            return
        brief, live = None, None
        if in_game or (seen and gone < 3):             # keep publishing across a transient blip
            try:
                # SHARED: the loading overlay wants this same read at this same moment — one
                # of us builds it, the other reuses it (see lolload.brief_shared).
                brief = lolload.brief_shared(dd)       # both teams' rank/form/grade/tags (slow)
            except Exception as e:
                _dlog(f"brief() raised {type(e).__name__}: {e}")
                brief = None
            try:
                import lollive                          # the TACTICAL layer: gank call, objective
                live = lollive.pulse(dd)                #   timers, win read, enemy-jungler track
            except Exception:
                live = None
        patch = {}
        if brief and (brief.get("allies") or brief.get("enemies")):
            payload = _scout_payload(dd, brief)
            blob = json.dumps(payload, sort_keys=True)
            if blob != last:
                patch["scout"] = payload
                last = blob
        elif in_game and brief is not None:
            _dlog("brief returned but roster empty (no allies/enemies)")
        if live is not None:
            lblob = json.dumps(live, sort_keys=True)
            if lblob != last_live:                      # timers tick every poll -> usually changes
                patch["live"] = live
                last_live = lblob
        if patch:
            patch["sts"] = int(time.time())             # capture time -> web counts timers down
            try:
                _fb("PATCH", db, f"drafts/{_ST['draft_id']}", patch)
                _dlog(f"PATCH ok: {sorted(patch.keys())}"
                      + (f" scout={len(patch['scout']['allies'])}+{len(patch['scout']['enemies'])}"
                         if 'scout' in patch else ""))
            except Exception as e:
                _dlog(f"PATCH FAILED {type(e).__name__}: {e}")
        time.sleep(6)


# ---------- the per-lobby publisher thread ----------
def _worker(dd):
    db = ""
    try:
        while not _ST["stop"]:
            settings = cfg.load()
            db = _db_url(settings)
            if not db or not settings.get("draft_link", True):
                return
            if phasecheck.phase() != "ChampSelect":
                _dlog(f"champ select ended (phase={phasecheck.phase()!r}) "
                      f"-> scout phase; posted_link={_ST['posted']}")
                break                                  # champ select over -> scout phase below
            info = lg._from_champ_select(dd)
            if not info:
                time.sleep(PUBLISH_POLL)
                continue
            payload = build_payload(dd, info)
            blob = json.dumps(payload, sort_keys=True)
            # ts changes every call — compare everything BUT the timestamp
            sig = re.sub(r'"ts": \d+', "", blob)
            if sig != _ST["last_pub"]:
                try:
                    publish(db, _ST["draft_id"], payload)
                    _ST["last_pub"] = sig
                except Exception:
                    time.sleep(PUBLISH_POLL)           # network blip -> retry next round
                    continue
                if not _ST["posted"]:                  # first successful publish
                    link = link_for(_ST["draft_id"], settings)
                    _ST["posted"] = post_chat_link(link)     # ONE chat link
                    if settings.get("draft_autoopen", True) and not _ST["opened"]:
                        _ST["opened"] = True                 # open it for YOU, once per lobby
                        try:
                            import webbrowser
                            # &me flags THIS copy as the publisher's — the scout auto-opens your
                            # lane. The chat link teammates get omits it, so they see the coach
                            # panel only after tapping their own row.
                            webbrowser.open(link + "&me")
                        except Exception:
                            pass
            time.sleep(PUBLISH_POLL)
        # champ select ended (not a dodge/stop) -> mirror the loading + in-game scoreboard
        if db and _ST["draft_id"] and not _ST["stop"]:
            # Started mid-game (Smiteless launched after champ select — nothing was published,
            # so there's no base doc and no chat link). Seed a minimal doc so the page recognizes
            # the draft, and open the board for the user directly since there's no chat to post to.
            if not _ST["last_pub"] and phasecheck.phase() in _GAME_PHASES:
                try:
                    publish(db, _ST["draft_id"], {"v": 1, "ts": int(time.time()),
                            "patch": dd.get("ver", ""), "seats": [], "enemy": [],
                            "bans": {"a": [], "e": []}})
                except Exception:
                    pass
                settings = cfg.load()
                if settings.get("draft_autoopen", True) and not _ST["opened"]:
                    _ST["opened"] = True
                    try:
                        import webbrowser
                        webbrowser.open(link_for(_ST["draft_id"], settings) + "&me")
                    except Exception:
                        pass
            _scout_phase(dd, db)
    finally:
        if db and _ST["draft_id"]:
            retire(db, _ST["draft_id"])
        with _LOCK:
            _ST["thread"] = None                       # next champ select spawns fresh


def tick(dd):
    """Called from the overlay's champ-select loop. Spawns the publisher for this lobby
    (once) and returns immediately; a no-op when the feature isn't configured/enabled."""
    settings = cfg.load()
    if not settings.get("draft_link", True) or not _db_url(settings):
        return
    with _LOCK:
        if _ST["thread"] is not None:
            return
        prev, _ST["draft_id"] = _ST["draft_id"], _new_id()
        _ST.update(posted=False, opened=False, last_pub="", sugg={}, sugg_key={}, stop=False)
        t = threading.Thread(target=_worker, args=(dd,), daemon=True)
        _ST["thread"] = t
    _dlog(f"tick -> spawned worker (phase={phasecheck.phase()!r})")
    if prev:                                           # tidy the previous lobby's node
        threading.Thread(target=_delete, args=(_db_url(settings), prev), daemon=True).start()
    t.start()


def current_link():
    """The live link for this lobby ('' if the publisher isn't running) — lets the
    overlay render it as a clickable line too."""
    with _LOCK:
        if _ST["thread"] is None or not _ST["draft_id"]:
            return ""
        return link_for(_ST["draft_id"])


# ---------- CLI: publish a fake draft so the Firebase + page setup can be tested ----------
def _demo(dd):
    def cid(nm):
        return dd["name2id"].get(dd["norm"](nm)) or 0
    allies = [(cid("Malphite"), "top"), (cid("Vi"), "jungle"), (cid("Ahri"), "mid"),
              (0, "adc"), (cid("Thresh"), "support")]
    enemies = [(cid("Darius"), ""), (cid("LeeSin"), ""), (cid("Yasuo"), "")]
    bans = dict(bans_my=[cid("Zed"), cid("Blitzcrank")], bans_their=[cid("Kayn"), cid("Shaco")])
    return dict(my=0, pos="", allies=allies, enemies=enemies, **bans)


def _demo_scout(dd):
    """A believable scout payload for verifying the page's scoreboard view without a game."""
    from smitei18n import t, tf

    def cid(nm):
        return dd["name2id"].get(dd["norm"](nm)) or 0

    def row(nm, champ, role, tier, div, lp, form, w, g, cg, cw, kda, perf, pts, tags, me=False):
        r = {"c": cid(champ), "role": role, "n": nm, "me": me,
             "rk": {"t": tier, "d": div, "lp": lp}, "f": form, "w": w, "g": g,
             "kda": kda, "p": perf, "pts": pts, "t": tags}
        if cg:
            r["cg"], r["cw"] = cg, cw
        return r
    allies = [
        row(t("You"), "Kha'Zix", "JG", "GOLD", "II", 66, [1, 1, 0, 1, 1], 7, 10, 6, 4, 3.1, 82,
            140000, [[tf("{champ} main · {points}k pts", champ="Kha'Zix", points=140), "good"],
                     [tf("{wins}W in last {games}", wins=7, games=10), "good"]], me=True),
        row("Sett Enjoyer", "Sett", "TOP", "SILVER", "I", 88, [1, 0, 0, 1, 0], 4, 10, 8, 4, 2.0, 61,
            42000, [[tf("comfort · {wins}-{losses} on {champ}",
                        wins=4, losses=4, champ="Sett"), "neutral"]]),
        row("faker fan99", "Ahri", "MID", "PLATINUM", "IV", 12, [1, 1, 1, 1, 0], 8, 10, 2, 1, 4.2, 88,
            9000, [[tf("off-champ · {count} of last {games} on {champ}",
                       count=7, games=10, champ="Yasuo"), "bad"],
                   [tf("{count}W heater · on {champ}", count=4, champ="Yasuo"), "neutral"]]),
        row("adcdiff", "Jinx", "BOT", "GOLD", "III", 40, [0, 0, 1, 0, 0], 2, 10, 6, 2, 1.6, 44,
            88000, [[tf("cold on {champ} · {wins}-{losses} recent",
                        champ="Jinx", wins=2, losses=6), "bad"],
                    [tf("bleeds · {deaths} deaths/game", deaths=6.8), "bad"]]),
        row("wardbot", "Thresh", "SUP", "GOLD", "II", 55, [1, 1, 0, 1, 1], 6, 10, 9, 6, 2.9, 74,
            210000, [[tf("{champ} OTP · {points}k pts", champ="Thresh", points=210), "good"]]),
    ]
    enemies = [
        row("smurfander", "Darius", "TOP", "GOLD", "IV", 38, [1, 1, 1, 1, 1], 9, 10, 3, 3, 5.1, 88,
            18000, [[tf("smurf? · {evidence}", evidence=(
                tf("lvl {level} · {wins}-{losses}", level=41, wins=9, losses=1)
                + tf(" · {performance} perf", performance=88))), "bad"],
                    [tf("{count}W heater", count=5), "bad"]]),
        row("jgandiff", "Graves", "JG", "GOLD", "IV", 30, [1, 0, 1, 0, 1], 5, 10, 0, 0, 2.0, 55,
            60000, [[tf("off-champ · {count} of last {games} on {champ}",
                        count=8, games=10, champ="Viego"), "bad"]]),
        row("midbeast", "Zed", "MID", "GOLD", "III", 44, [0, 1, 0, 1, 1], 6, 10, 7, 5, 3.4, 79,
            120000, [[tf("{champ} main · {points}k pts", champ="Zed", points=120), "bad"],
                     [tf("comfort · {wins}-{losses} on {champ}",
                         wins=5, losses=2, champ="Zed"), "bad"]]),
        row("botlaner", "Caitlyn", "BOT", "SILVER", "II", 61, [0, 0, 0, 1, 0], 3, 10, 4, 1, 1.5, 45,
            30000, [[tf("cold on {champ} · {wins}-{losses} recent",
                        champ="Caitlyn", wins=1, losses=3), "good"],
                    [tf("{count}L skid · tilt risk", count=4), "good"]]),
        row("supdiff", "Lux", "SUP", "GOLD", "IV", 20, [1, 0, 0, 0, 0], 2, 10, 2, 1, 2.1, 52,
            15000, [[tf("off-role · {role} main", role="MID"), "good"]]),
    ]
    allies[0]["lane"] = cid("Darius")           # you (JG) — pair to the enemy top for the demo
    allies[0]["tip"] = t(
        "Respect Darius level 1-2 — his Q outtrades everything early. Gank him before he "
        "snowballs; he has no escape, so a hard collapse post-6 is free."
    )
    return {
        "allies": allies,
        "enemies": enemies,
        "me": 0,
        "threat": {
            "c": cid("Darius"),
            "txt": tf("smurf? · {evidence}", evidence=tf("{count}W heater", count=5)),
        },
        "plan": [
            t("Enemy is AD-heavy — rush armor / Seeker's, Randuin's on tanks."),
            t("They out-scale — force early tempo and objectives, end before 3 items."),
        ],
        "wincons": {
            "win": t("end before 25 — turn every kill into towers and objectives"),
            "lose": t("letting it go late — their comp outgrows yours"),
        },
    }


def main():
    if "test" not in sys.argv:
        print(__doc__)
        return
    settings = cfg.load()
    db = _db_url(settings)
    if not db:
        print("no draft_db configured — Settings -> Draft link, or add \"draft_db\" to "
              f"{cfg.PATH}")
        return
    dd = lb.ddragon()
    _ST["draft_id"] = _new_id()
    payload = build_payload(dd, _demo(dd))
    if "scout" in sys.argv:                    # `test scout` -> also attach the scoreboard view
        payload["scout"] = _demo_scout(dd)
        payload["sts"] = int(time.time())
    publish(db, _ST["draft_id"], payload)
    print("published test draft ->", link_for(_ST["draft_id"], settings))


if __name__ == "__main__":
    main()
