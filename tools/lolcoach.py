#!/usr/bin/env python3
"""lolcoach.py — basic lane-matchup + mid-game macro guide for the current game.

Reads champ select from the running League client (LCU), pulls op.gg matchup
win rates, then asks `claude -p` (fast model, no tools) for a short, role-aware
coaching read. Designed to run right after lolbuild.py from the Win+B AHK macro.

Role-aware output:
  - JUNGLE  -> enemy-jungler matchup + STRONG SIDE / WEAK SIDE + objective plan
  - MID     -> lane matchup + mid-game macro
  - other   -> generic lane matchup + mid-game macro

Usage:
  python lolcoach.py                          # AUTO from champ select (LCU)
  python lolcoach.py Ahri mid Zed Leona       # manual: champ role [enemy champs...]
"""
import sys, os

# reuse the verified ddragon/op.gg plumbing from lolbuild.py + multi-source resolver,
# the op.gg matchup helpers (lb.gather_*), and the shared LLM provider facade.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import lolgame as lg
import llmcli
import smiteconfig as cfg
from smitei18n import lang, t, tf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def deterministic_analysis(lane_mu, role):
    """Strong/weak side computed PURELY from the verified lane winrates - no LLM,
    nothing invented. Returns '' if we have no per-lane data."""
    rated = [x for x in lane_mu if x[3] is not None]
    nodata = [x for x in lane_mu if x[3] is None]
    if not rated and not nodata:
        return ""
    fmt = lambda x: tf("{role} {ally} vs {enemy} {winrate:.0f}% ({games}g)",
                       role=x[1], ally=x[0], enemy=x[2], winrate=x[3], games=x[4])
    ranked = sorted(rated, key=lambda x: x[3], reverse=True)
    strong = [x for x in ranked if x[3] >= 52]
    weak = [x for x in ranked if x[3] < 48]
    even = [x for x in ranked if 48 <= x[3] < 52]
    out = []
    if strong:
        tail = t(" -> path/gank these lanes") if role == "jungle" else t(" -> play for these")
        out.append(t("STRONG (data): ") + "; ".join(fmt(x) for x in strong) + tail)
    if weak:
        tail = (t(" -> play safe; the enemy jungler likely camps here")
                if role == "jungle" else t(" -> respect, play safe"))
        out.append(t("WEAK (data): ") + "; ".join(fmt(x) for x in weak) + tail)
    if even:
        out.append(t("EVEN (data): ") + "; ".join(fmt(x) for x in even))
    if nodata:
        out.append(t("NO OP.GG SAMPLE (pairing known, WR not): ")
                   + "; ".join(tf("{role} {ally} vs {enemy}",
                                  role=x[1], ally=x[0], enemy=x[2]) for x in nodata))
    return "\n".join(out)


def matchup_text(lane_mu, my_matchups, myname, role, ver):
    """One verified-data string for the prompt + quick read. Prefers full per-lane
    data; falls back to the user's own matchups; else says so plainly."""
    if lane_mu:
        parts = []
        for a, r, e, wr, g in lane_mu:
            parts.append(tf("{role} {ally} vs {enemy} (no op.gg sample)",
                            role=r, ally=a, enemy=e) if wr is None
                         else tf("{role} {ally} vs {enemy} {winrate:.1f}% ({games}g)",
                                 role=r, ally=a, enemy=e, winrate=wr, games=g))
        return tf("VERIFIED LANE WINRATES (op.gg Emerald+, patch {patch}) - your team vs "
                  "the enemy in that lane (paired by role): ", patch=ver) + "; ".join(parts)
    if my_matchups:
        return (tf("VERIFIED op.gg winrates for {champ} {role}: ", champ=myname, role=role)
                + "; ".join(tf("vs {enemy} {winrate:.1f}% ({games}g)",
                               enemy=n, winrate=wr, games=g) for n, wr, g in my_matchups))
    return t("No op.gg matchup data for this game (roles not yet known, or no sample). "
             "Do NOT invent win rates.")


MACRO_PRINCIPLES = (
    "Macro principles to ground your advice: prio is the right to leave lane; "
    "crash the wave (esp. cannon) BEFORE you roam/recall/rotate; don't roam on a "
    "wave pushing to you; set up objectives ~60-90s early by shoving for prio + "
    "deep vision; identify the win condition by archetype (control mage = prio+"
    "scale+zone, assassin = tempo+picks, skirmisher = side-lane 1v1 + flanks, "
    "scaling = farm safe then take over); group when you win 5v5, split when you "
    "don't but have a strong 1v1; bias to self-sufficient, forgiving lines (Gold/Plat)."
)


def build_prompt(dd, myname, role, allies, enemy_names, mu_text, ver):
    role_known = bool(role)
    rlabel = role if role_known else "UNKNOWN — infer it from my champion + team"
    lines = [
        f"PATCH {ver}, op.gg Emerald+ (NA), ranked solo queue.",
        f"ME: {myname} ({rlabel}).",
    ]
    if allies:
        team = ", ".join(f"{r or '?'}:{dd['id2name'].get(c, c)}" for c, r in allies if c)
        lines.append(f"MY TEAM: {team}")
    lines.append("ENEMY CHAMPS (roles hidden in solo queue): "
                 + (", ".join(enemy_names) or "none locked yet"))
    lines.append(mu_text)
    data = "\n".join(lines)

    common = (
        "You are a sharp, concise League of Legends coach. Output PLAIN TEXT, skimmable, "
        "lines under 88 chars. No preamble; no markdown except the SECTION LABELS I "
        "specify (CAPS, own line). Keep the WHOLE response under 12 lines, terse.\n"
        "HARD RULES (do not break):\n"
        "1. Only name champions that appear in MY TEAM or ENEMY CHAMPS. NEVER mention any "
        "other champion.\n"
        "2. The ONLY win rates you may state are the VERIFIED ones in the data. NEVER "
        "invent, estimate, or guess a number.\n"
        "3. Base STRONG SIDE / WEAK SIDE on the verified lane winrates: your highest-WR "
        "lane is the strong side, your lowest-WR lane is the weak side. If a lane has no "
        "verified number, say 'no data' for it - do NOT guess who wins it.\n"
        "4. Tactical advice (what a champ does) may use your own knowledge, but any "
        "matchup VERDICT must trace to a verified number above.\n"
    )
    if lang() == "pt_BR":
        common += ("5. Reply in Brazilian Portuguese. Keep champion names, role abbreviations, "
                   "item names and every verified number unchanged.\n")
    else:
        common += "5. Reply in English.\n"

    if not role_known:
        ask = (
            "\nFIRST output one line `ROLE: <your inferred role>` (infer it from my "
            "champion and team). THEN:\n"
            "- If you're the JUNGLER, write JUNGLE MATCHUP (early read vs the likely enemy "
            "jungler), STRONG SIDE / WEAK SIDE (which side to path toward & gank vs which to "
            "play safe, given both teams), and OBJECTIVE & MACRO.\n"
            "- If you're a LANER, write LANE MATCHUP (likely opponent + key tips) and "
            "MID-GAME MACRO (win condition, group vs pick/split vs this comp).\n"
            "Cite an op.gg WR only if present. Keep under 16 lines.\n"
        )
    elif role == "jungle":
        ask = (
            "\nWrite these three sections:\n"
            "JUNGLE MATCHUP — identify the likely enemy jungler from the enemy champs; "
            "give the early read: scuttle/level-2-3 duel, invade/counter-invade, and their "
            "gank threat vs yours. Cite the op.gg WR if present. 2 lines.\n"
            "STRONG SIDE / WEAK SIDE — using MY TEAM's laners vs the enemy champs, say which "
            "side (TOP or BOT) is your STRONG side to path toward and gank (winning matchup, "
            "kill pressure, follow-up CC) and which is your WEAK side to play around / expect "
            "the enemy jungler to camp. Add a level-1 start + first-clear direction. 2-3 lines.\n"
            "OBJECTIVE & MACRO — first objective to prioritize (void grubs / dragon / herald) "
            "given both comps, plus your mid-game win condition. 2 lines.\n"
        )
    elif role == "mid":
        ask = (
            "\nWrite these two sections:\n"
            "LANE MATCHUP — identify your likely lane opponent from the enemy champs; give the "
            "trading pattern, wave plan (push for prio vs freeze), all-in / level-6 threats, and "
            "how to get prio. Cite the op.gg WR if present. 3 lines.\n"
            "MID-GAME MACRO — your win condition by archetype, roam vs side-lane plan, and whether "
            "to GROUP or PICK/SPLIT vs THIS enemy comp. 3 lines.\n"
        )
    else:
        ask = (
            "\nWrite these two sections:\n"
            "LANE MATCHUP — identify your likely lane opponent; trading/wave/all-in tips and what "
            "to respect. Cite the op.gg WR if present. 3-5 lines.\n"
            "MID-GAME MACRO — your win condition, grouping vs splitting vs THIS enemy comp, and "
            "objective/teamfight role. 3-5 lines.\n"
        )
    return common + ask + "\nDATA:\n" + data


FALLBACK_MACRO = {
    "jungle": ("Path toward your winning/kill-pressure lanes (strong side); play safe "
               "around your losing lanes. Crash camps on tempo, contest scuttle with prio, "
               "and set up the first objective (grubs/herald top-side, dragon bot-side) "
               "~30-60s early with vision. Gank where there's CC follow-up + a low/immobile "
               "target; avoid forcing into the enemy jungler's strong-side."),
    "mid": ("Crash the wave (esp. cannon) BEFORE you roam or recall; never roam on a wave "
            "pushing to you. Use prio to help scuttle/objectives and to roam with a target. "
            "Win condition by archetype: control mage = prio + scale + zone, assassin = tempo "
            "+ picks, skirmisher = side-lane 1v1 + flanks. Group only if you win 5v5; else "
            "pick/split."),
}
FALLBACK_MACRO_DEFAULT = ("Manage your wave for prio, set up objectives early with vision, "
                          "and pick group-vs-split by whether you win a straight 5v5.")


def fallback(mu_text, role):
    return (mu_text + tf("\n\nMACRO ({role}): ", role=(role or "?").upper())
            + t(FALLBACK_MACRO.get(role, FALLBACK_MACRO_DEFAULT)))


def _write(path, text):
    """Atomic write so the AHK poller never reads a half-written file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)
    os.replace(tmp, path)


def _touch(path):
    if path:
        try:
            open(path, "w").close()
        except Exception:
            pass


def _takeflag(argv, name):
    if name in argv:
        i = argv.index(name)
        val = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
        return val
    return None


def _call_ai(prompt):
    """Dispatch through the persisted provider without changing verified coach data."""
    provider = cfg.load().get("llm_provider", cfg.LLM_PROVIDER_DEFAULT)
    return llmcli.call(prompt, provider)


def main():
    # File mode (from Win+B): write a QUICK read immediately, then upgrade to the
    # full AI guide in place. Stdout mode (manual/console): just print the result.
    argv = sys.argv[1:]
    outp = _takeflag(argv, "--out")
    qm = _takeflag(argv, "--qm")
    fm = _takeflag(argv, "--fm")
    args = argv

    dd = lb.ddragon()
    ver = dd["ver"]

    if args:  # manual mode (testing / no client)
        my_cid = dd["name2id"].get(dd["norm"](args[0]))
        if not my_cid:
            print(tf("Unknown champ '{champ}'.", champ=args[0]))
            return
        role = lb.ROLE.get((args[1].lower() if len(args) > 1 else "jungle"), "jungle")
        allies = []
        enemies = [(cid, "") for cid in (dd["name2id"].get(dd["norm"](a)) for a in args[2:]) if cid]
        source = "manual"
    else:  # AUTO: champ select / loading screen / in-game
        info, errmsg = lg.resolve(dd)
        if errmsg:
            if outp:
                _write(outp, errmsg); _touch(qm); _touch(fm)
            else:
                print(errmsg)
            return
        my_cid, role = info["my"], info["pos"]   # role may be "" on the loading screen
        allies = info["allies"]
        enemies = info["enemies"]                 # [(champ_id, role)] — roles known in-game
        source = info.get("source", "auto")

    myname = dd["id2name"].get(my_cid, str(my_cid))
    enemy_names = [dd["id2name"].get(c, str(c)) for c, _ in enemies]
    enemy_cids = [c for c, _ in enemies]
    # Per-lane winrates need BOTH teams' roles (in-game). gather_lane_matchups pairs
    # strictly by role and returns only the lanes it could pair; else fall back.
    lane_mu = lb.gather_lane_matchups(dd, allies, enemies) if (allies and enemies) else []
    my_mu = lb.gather_matchups(dd, my_cid, role, enemy_cids)[0] if (role and not lane_mu) else []
    mu_text = matchup_text(lane_mu, my_mu, myname, role, ver)
    analysis = deterministic_analysis(lane_mu, role)

    # VERIFIED block = everything that is real op.gg data + computed-from-data calls +
    # evergreen macro principles. Nothing here is invented. This is ALWAYS the output.
    verified = mu_text
    if analysis:
        verified += "\n\n" + analysis
    verified += (tf("\n\nMACRO ({role}, general principles): ",
                    role=(role or "?").upper())
                 + t(FALLBACK_MACRO.get(role, FALLBACK_MACRO_DEFAULT)))

    header = tf("[{source}] {champ} ({role}) vs ", source=source, champ=myname,
                role=role or t("role?")) + (", ".join(enemy_names) or t("unknown"))
    base = header + t("\n\n=== VERIFIED (op.gg data) ===\n") + verified
    prompt = build_prompt(dd, myname, role, allies, enemy_names, mu_text, ver)

    def with_ai(text, err):
        if text:
            return base + t("\n\n=== AI TACTICAL NOTES (commentary, not a data source) ===\n") + text
        return base + t("\n\n(AI tactical notes skipped — the verified data above is complete.)")

    if outp:
        _write(outp, base + t("\n\n(AI tactical notes loading… the verified data above is already complete.)"))
        _touch(qm)
        text, err = _call_ai(prompt)
        _write(outp, with_ai(text, err))
        _touch(fm)
    else:
        text, err = _call_ai(prompt)
        print(with_ai(text, err))


if __name__ == "__main__":
    main()
