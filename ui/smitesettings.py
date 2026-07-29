#!/usr/bin/env python3
"""smitesettings.py - Smiteless settings window (Tk). Launched from the tray menu.

A normal (focusable) window - unlike the overlay - so you can tweak it like any dialog.
Everything it saves is read live by the overlay (smitecard.apply_settings each frame).
"""
import sys, os, ctypes, webbrowser
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass
import smiteconfig as cfg
import lolscout as ls

import smiteskin as skin
# Duskfall tokens - see docs/UIDESIGN.md. Nothing below this block may spell out a hex or
# a font-family string; everything routes through skin.* so the whole window re-themes
# from one place.
VOID, SURFACE, RAISED, HOVER = skin.VOID, skin.SURFACE, skin.RAISED, skin.HOVER
SUNKEN, LINE, LINE_SOFT = skin.SUNKEN, skin.LINE, skin.LINE_SOFT
TXT, MUTED, FAINT = skin.TXT, skin.MUTED, skin.FAINT
EMBER, EMBER_DEEP, ARC = skin.EMBER, skin.EMBER_DEEP, skin.ARC
GOOD, BAD, WARN = skin.GOOD, skin.BAD, skin.WARN
BODY, SMALL = skin.BODY, skin.SMALL
HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILES = [os.path.expanduser("~/.riot_api_key"), os.path.expanduser("~/.riot_api_key.txt")]


def _single_instance():
    k = ctypes.windll.kernel32
    k.CreateMutexW(None, False, "Global\\SmitelessSettings")
    return k.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def main():
    if not _single_instance():
        return
    import tkinter as tk
    s = cfg.load()
    root = tk.Tk()
    cfg.watch_tray(root)                        # close with the tray (no orphan settings window)
    root.title("Smiteless Settings")
    root.configure(bg=VOID)
    skin.dark_titlebar(root)
    root.resizable(True, True)
    try:
        root.iconbitmap(os.path.join(HERE, "smiteless.ico"))
    except Exception:
        pass

    shell = tk.Frame(root, bg=VOID)
    shell.pack(fill="both", expand=True)
    vbar = tk.Scrollbar(shell, orient="vertical")
    vbar.pack(side="right", fill="y")
    canvas = tk.Canvas(shell, bg=VOID, highlightthickness=0, yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.config(command=canvas.yview)
    body = tk.Frame(canvas, bg=VOID)
    body_id = canvas.create_window((0, 0), window=body, anchor="nw")

    def _sync_scroll(_=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(body_id, width=canvas.winfo_width())
    body.bind("<Configure>", _sync_scroll)
    canvas.bind("<Configure>", _sync_scroll)
    def _wheel(e):
        # don't hijack the wheel from embedded lists (perma-bans, accounts) — over a
        # Listbox/Text the widget scrolls itself; everywhere else the page scrolls
        w = root.winfo_containing(e.x_root, e.y_root)
        if isinstance(w, (tk.Listbox, tk.Text)):
            return
        canvas.yview_scroll(-1 * (e.delta // 120), "units")
    root.bind_all("<MouseWheel>", _wheel)

    try:
        import smiteupdate as _su
        _ver = _su.local_version()
    except Exception:
        _ver = ""
    _hdr = tk.Frame(body, bg=VOID)
    _hdr.pack(fill="x", padx=skin.PAD_WIN, pady=(16, 1))
    skin.brand_row(_hdr, "settings", bg=VOID).pack(side="left")
    if _ver:
        tk.Label(_hdr, text=f"v{_ver}", bg=RAISED, fg=MUTED, font=skin.body(SMALL)).pack(
            side="left", padx=(10, 0), pady=(4, 4), ipadx=6, ipady=1)
    tk.Label(body, text="Changes apply live - the overlay's gank tags update within a few seconds.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL)).pack(anchor="w", padx=skin.PAD_WIN, pady=(0, 8))

    from tkinter import ttk
    import lolbuild as _lb
    try:
        _dd = _lb.ddragon()
        _champ_names = sorted(_dd["id2name"].values())
        _norm, _name2id, _id2name = _dd["norm"], _dd["name2id"], _dd["id2name"]
    except Exception:
        _champ_names, _name2id, _id2name = [], {}, {}
        _norm = lambda x: "".join(c for c in (x or "").lower() if c.isalnum())

    # dark-ish theming for the ttk combobox (field + its dropdown list)
    try:
        _st = ttk.Style()
        _st.theme_use("clam")
        _st.configure("Fav.TCombobox", fieldbackground=SUNKEN, background=RAISED, foreground=TXT,
                      arrowcolor=TXT, bordercolor=RAISED, lightcolor=RAISED, darkcolor=RAISED)
        root.option_add("*TCombobox*Listbox.background", SUNKEN)
        root.option_add("*TCombobox*Listbox.foreground", TXT)
        root.option_add("*TCombobox*Listbox.selectBackground", HOVER)
        root.option_add("*TCombobox*Listbox.selectForeground", TXT)
    except Exception:
        pass

    # ---- MAX ELO -----------------------------------------------------------------------
    # The one switch. Name your champion and its backup, hit ARM, and every climb feature in
    # cfg.MAX_ELO_ON comes on at once while champ select is held to that pool and locked for
    # you. It sits at the very top because it is the only control most sessions need to touch.
    maxelo_main = tk.StringVar(value=s.get("max_elo_main", ""))
    maxelo_back = tk.StringVar(value=s.get("max_elo_backup", ""))
    maxelo_on = {"v": bool(s.get("max_elo", False))}

    me_card = skin.card(body, rail=EMBER)
    me_card.pack(fill="x", padx=14, pady=(2, 8))
    me_in = tk.Frame(me_card.body, bg=SURFACE)
    me_in.pack(fill="x", padx=12, pady=(9, 10))
    me_head = tk.Frame(me_in, bg=SURFACE)
    me_head.pack(fill="x")
    tk.Label(me_head, text="MAX ELO", bg=SURFACE, fg=EMBER,
             font=skin.display(17, bold=True)).pack(side="left")
    me_state = tk.Label(me_head, text="", bg=SURFACE, font=skin.body(SMALL, bold=True))
    me_state.pack(side="left", padx=(10, 0), pady=(6, 0))
    tk.Label(me_in, text="Everything that shortens the climb, on. Smiteless auto-accepts, bans "
             "the champ that threatens your team, LOCKS your pick for you, imports the runes, "
             "mutes the lobby, and runs every in-game read. Name a Main (and a Backup) to be "
             "held to one champion — or leave them EMPTY and it locks the best pick for each "
             "draft instead. Either way the 30 seconds before a game, where the LP goes, stop "
             "being a decision.",
             bg=SURFACE, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", pady=(4, 6))
    me_row = tk.Frame(me_in, bg=SURFACE)
    me_row.pack(fill="x", pady=(0, 8))
    tk.Label(me_row, text="Main", bg=SURFACE, fg=TXT,
             font=skin.body(SMALL, bold=True)).pack(side="left", padx=(0, 5))
    me_cb1 = ttk.Combobox(me_row, textvariable=maxelo_main, values=_champ_names, width=15,
                          style="Fav.TCombobox", font=skin.body(SMALL))
    me_cb1.pack(side="left")
    tk.Label(me_row, text="Backup", bg=SURFACE, fg=TXT,
             font=skin.body(SMALL, bold=True)).pack(side="left", padx=(12, 5))
    me_cb2 = ttk.Combobox(me_row, textvariable=maxelo_back, values=_champ_names, width=15,
                          style="Fav.TCombobox", font=skin.body(SMALL))
    me_cb2.pack(side="left")

    def _me_filter(cb, var):
        def f(_e=None):
            t = var.get().strip().lower()
            cb["values"] = [n for n in _champ_names if t in n.lower()] if t else _champ_names
        return f
    me_cb1.bind("<KeyRelease>", _me_filter(me_cb1, maxelo_main))
    me_cb2.bind("<KeyRelease>", _me_filter(me_cb2, maxelo_back))

    me_btnrow = tk.Frame(me_in, bg=SURFACE)
    me_btnrow.pack(fill="x")
    me_note = tk.Label(me_in, text="", bg=SURFACE, fg=MUTED, font=skin.body(SMALL),
                       anchor="w", justify="left", wraplength=430)
    me_note.pack(fill="x", pady=(6, 0))

    def _me_paint():
        on = maxelo_on["v"]
        me_state.config(text=("ARMED" if on else "STANDING BY"), fg=(EMBER if on else MUTED))
        me_btn.config(text=("STAND DOWN" if on else "ARM MAX ELO"))
        if on:
            mn = maxelo_main.get().strip()
            bk = maxelo_back.get().strip()
            if mn:
                me_note.config(text=f"Locked to {mn}" + (f", backup {bk}." if bk else ".")
                               + " Champ select is on rails — change your mind here, not in "
                                 "the lobby.", fg=EMBER)
            else:
                me_note.config(text="No champion set — so it locks the BEST PICK for each "
                                    "draft: the same read as GOOD THIS GAME (counters into "
                                    "their locks + comp fit), best first. Name a main above "
                                    "if you'd rather it always be one champion.", fg=EMBER)
        else:
            me_note.config(text="Nothing is being locked. Arming also switches on every feature "
                                "below that shortens the climb.", fg=MUTED)

    def _me_toggle():
        if maxelo_on["v"]:
            cfg.stand_down_max_elo()
            maxelo_on["v"] = False
            status.config(text="MAX ELO stood down - champ select is yours again", fg=MUTED)
            _me_paint()
            return
        # An empty main is a VALID way to arm: no champion named means "lock whatever is best
        # for this draft". Requiring one made the button need setup before it did anything.
        main_nm = _canon(maxelo_main.get()) or ""
        back_nm = _canon(maxelo_back.get()) or ""
        maxelo_main.set(main_nm)
        maxelo_back.set(back_nm)
        cfg.arm_max_elo(main_nm, back_nm)
        maxelo_on["v"] = True
        for _v, _k in _MAXELO_VARS:              # reflect the forced-on toggles in the UI
            _v.set(True)
        _me_paint()
        who = (main_nm + (f" / {back_nm}" if back_nm else "")) if main_nm \
            else "best pick per draft"
        status.config(text=f"MAX ELO armed - {who}, everything climb-focused on", fg=GOOD)

    # THE button: this window's one primary (UIDESIGN §: exactly one EMBER-filled button per
    # window), sized up — it's the only control most sessions touch. Save drops to secondary.
    me_btn = tk.Button(me_btnrow, text="ARM MAX ELO", command=lambda: _me_toggle(),
                       bg=EMBER, fg=VOID, activebackground=EMBER_DEEP, activeforeground=VOID,
                       relief="flat", bd=0, padx=26, pady=8, cursor="hand2",
                       font=skin.display(13, bold=True))
    me_btn.pack(side="left")
    _me_paint()

    def scale_row(title, desc, lo, hi, res, val, fmt):
        outer = skin.card(body, rail=LINE)
        outer.pack(fill="x", padx=14, pady=5)
        fr = outer.body
        top = tk.Frame(fr, bg=SURFACE)
        top.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(top, text=title, bg=SURFACE, fg=TXT, font=skin.body(BODY, bold=True)).pack(side="left")
        valv = tk.StringVar()
        tk.Label(top, textvariable=valv, bg=SURFACE, fg=ARC,
                 font=skin.display(BODY, bold=True)).pack(side="right")
        sc = tk.Scale(fr, from_=lo, to=hi, resolution=res, orient="horizontal", showvalue=0,
                      bg=SURFACE, fg=TXT, troughcolor=SUNKEN, highlightthickness=0, bd=0,
                      activebackground=EMBER, sliderrelief="flat", length=440)
        sc.set(val)
        sc.pack(fill="x", padx=10)
        descv = tk.StringVar()
        tk.Label(fr, textvariable=descv, bg=SURFACE, fg=MUTED, font=skin.body(SMALL),
                 anchor="w", justify="left", wraplength=430).pack(fill="x", padx=12, pady=(0, 8))

        def upd(_=None):
            v = sc.get()
            valv.set(fmt(v))
            descv.set(desc(v) if callable(desc) else desc)
        sc.config(command=upd)
        upd()
        return sc

    # Gank-tuning dials (streak influence / gank threshold / champ-kit) were removed — they
    # confused more than they helped; the gank rating now always uses the tuned defaults.
    scout = scale_row("Scout depth (games / player)",
                      "more games = steadier form read, but a slower first scout",
                      5, 20, 1, s["scout_games"], lambda v: f"{int(v)}")
    pgames = scale_row("Profile: games to load",
                       "how many recent games the home/profile page loads (and per 'Load more')",
                       5, 60, 1, s["profile_games"], lambda v: f"{int(v)}")
    bsize = scale_row("Board size (2nd-monitor scout)",
                      "how big the champ-select / in-game board renders. Lower it if the default "
                      "fills too much of the screen; applies to the next frame.",
                      40, 100, 5, s.get("board_size", 70), lambda v: f"{int(v)}%")
    solocoach = tk.BooleanVar(value=s.get("solo_coaching", True))
    _solo_wrap = tk.Frame(body, bg=VOID)
    _solo_wrap.pack(fill="x", padx=18, pady=(0, 2))
    _chk2 = lambda parent, text, var: tk.Checkbutton(parent, text=text, variable=var, bg=VOID,
        fg=TXT, selectcolor=SUNKEN, activebackground=VOID, activeforeground=TXT,
        font=skin.body(BODY), bd=0, highlightthickness=0)
    _chk2(_solo_wrap, "Coach from Ranked Solo games only (pool, session, climb)", solocoach).pack(side="left")
    dvol = scale_row("Audio volume (chime + voice)",
                     "drake chime and the voice callouts (0 = silent). Applies next game.",
                     0, 100, 5, s.get("dragon_volume", 30), lambda v: f"{int(v)}")

    def _test_audio():
        # hear the chime + a voice line at the CURRENT slider value — no game required
        import threading
        v = int(dvol.get())

        def work():
            try:
                import time as _t
                import smitewidget as sw
                sw._beep(15, v)
                _t.sleep(1.8)                     # let the jingle ring before the voice
                sw._say("test", "Take it. You win this fight.", v)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
    skin.button(body, "♪ Test audio", _test_audio, size=SMALL).pack(anchor="w", padx=18, pady=(0, 4))

    auto = tk.BooleanVar(value=cfg.auto_open_enabled())
    homeonstart = tk.BooleanVar(value=cfg.home_on_start_enabled())
    startwin = tk.BooleanVar(value=cfg.autostart_enabled())

    def _chk(parent, text, var, bg=VOID):
        return tk.Checkbutton(parent, text=text, variable=var, bg=bg, fg=TXT, selectcolor=SUNKEN,
                              activebackground=bg, activeforeground=TXT, font=skin.body(BODY),
                              bd=0, highlightthickness=0)

    tips = tk.BooleanVar(value=s["matchup_tips"])
    widget = tk.BooleanVar(value=s["item_widget"])
    autoq = tk.BooleanVar(value=s.get("auto_accept", False))
    intel = tk.BooleanVar(value=s.get("game_intel", True))
    tempo = tk.BooleanVar(value=s.get("tempo_coach", True))
    freev = tk.BooleanVar(value=s.get("free_alarm", True))
    tempov = tk.BooleanVar(value=s.get("tempo_voice", True))
    dragon = tk.BooleanVar(value=s.get("dragon_audio", True))
    queuecall = tk.BooleanVar(value=s.get("queue_call", True))
    respawnv = tk.BooleanVar(value=s.get("respawn_plan", True))
    reentryv = tk.BooleanVar(value=s.get("re_entry", True))
    bleedv = tk.BooleanVar(value=s.get("bleed_guard", True))
    deadbrief = tk.BooleanVar(value=s.get("death_brief", True))
    loadbrief = tk.BooleanVar(value=s.get("loading_scout", True))
    dodge = tk.BooleanVar(value=s.get("dodge_alerts", True))
    dock = tk.BooleanVar(value=s.get("dock_champ_select", True))
    autoimp = tk.BooleanVar(value=s.get("auto_import", False))
    autoban = tk.BooleanVar(value=s.get("auto_ban", False))
    automute = tk.BooleanVar(value=s.get("auto_mute", True))
    boardtop = tk.BooleanVar(value=s.get("board_topmost", True))
    draftlink = tk.BooleanVar(value=s.get("draft_link", True))
    draftopen = tk.BooleanVar(value=s.get("draft_autoopen", True))
    flash_side = tk.IntVar(value=(0 if s.get("flash_on_d", True) else 1))  # 0=D, 1=F

    # Which checkboxes MAX ELO switches on, so arming it visibly ticks them instead of quietly
    # changing settings behind the panel. Mirrors cfg.MAX_ELO_ON — anything there without a
    # control here just has no checkbox (gank_kit, solo_coaching live elsewhere/nowhere).
    _MAXELO_VARS = [(autoq, "auto_accept"), (autoban, "auto_ban"), (autoimp, "auto_import"),
                    (automute, "auto_mute"), (widget, "item_widget"), (intel, "game_intel"),
                    (tempo, "tempo_coach"), (freev, "free_alarm"), (reentryv, "re_entry"),
                    (bleedv, "bleed_guard"),
                    (respawnv, "respawn_plan"), (deadbrief, "death_brief"),
                    (loadbrief, "loading_scout"), (queuecall, "queue_call"),
                    (dodge, "dodge_alerts"), (tips, "matchup_tips"),
                    (dock, "dock_champ_select"), (draftlink, "draft_link"),
                    (draftopen, "draft_autoopen"), (solocoach, "solo_coaching")]

    # FEATURES, grouped (§15): one card per surface family instead of a flat two-column
    # dump of 19 checkboxes — you find a toggle by asking "where does it live", and each
    # card's rail marks the group.
    skin.section_rule(body, "FEATURES").pack(fill="x", padx=18, pady=(10, 2))

    def _feat_group(title, items):
        card = skin.card(body, rail=LINE)
        card.pack(fill="x", padx=14, pady=4)
        inner = tk.Frame(card.body, bg=SURFACE)
        inner.pack(fill="x", padx=10, pady=(6, 8))
        tk.Label(inner, text=title, bg=SURFACE, fg=EMBER,
                 font=skin.body(SMALL, bold=True)).grid(row=0, column=0, columnspan=2,
                                                        sticky="w", pady=(0, 2))
        inner.columnconfigure(0, weight=1, uniform="feat")
        inner.columnconfigure(1, weight=1, uniform="feat")
        for i, (lbl, var) in enumerate(items):
            _chk(inner, lbl, var, bg=SURFACE).grid(row=1 + i // 2, column=i % 2,
                                                   sticky="w", padx=(0, 8))

    _feat_group("IN-GAME WIDGET", [
        ("Item widget", widget),
        ("Live intel (timers + win read)", intel),
        ("Tempo coach (objective windows)", tempo),
        ("Free-objective alarm", freev),
        ("Voice callouts (base / take)", tempov),
        ("Dragon spawn audio", dragon),
        ("Respawn plan (death card)", respawnv),
        ("Re-entry guard (90s after respawn)", reentryv),
        ("Bleed guard (first 14 minutes)", bleedv),
    ])
    tk.Label(body, text="BLEED GUARD watches your own health bar before 14:00 — the window "
             "where three deaths turn into a 39% game (your last 46: 9W-14L with it, 14W-9L "
             "without). It only speaks when somebody can actually collect: low health AND "
             "their jungler unaccounted for, or a laner two levels up who kills you on his "
             "own. Everything else is silence.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 2))
    _feat_group("OVERLAYS & BOARDS", [
        ("Death brief (while dead)", deadbrief),
        ("Loading-screen scout (splash cards)", loadbrief),
        ("Queue call (pre-queue stop/go)", queuecall),
        ("Matchup lane tips", tips),
        ("Keep live board always on top", boardtop),
        ("Dock champ-select panel by client", dock),
    ])
    _feat_group("CHAMP-SELECT AUTOMATION", [
        ("Auto-accept queue", autoq),
        ("Auto-import runes + summs on lock", autoimp),
        ("Auto-ban (perma-ban list first)", autoban),
        ("The Dodge Call (lobby priced in LP)", dodge),
        ("Live draft link (URL in chat)", draftlink),
        ("Also open the draft board for me", draftopen),
    ])
    _feat_group("IN-GAME QUIET", [
        ("Auto-mute (chat off, pings silent)", automute),
    ])
    tk.Label(body, text="Hides ally chat and all-chat and silences ping audio, by writing "
             "League's OWN settings through the client — nothing is typed into the game, and "
             "Smiteless reads the setting back to confirm it took. Two honest limits: ping "
             "MARKERS still draw on the minimap (the client has no setting for those), and "
             "because it's a client setting it PERSISTS until you turn it off — here, or in "
             "League's own Audio/Interface settings.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 2))

    # Auto-accept ROLE (position) swaps — pick which roles you'll swap INTO.
    _SWAP_LBL = {"top": "Top", "jungle": "Jungle", "mid": "Mid", "adc": "ADC", "support": "Support"}
    _swap_cur = set(s.get("auto_swap_roles") or [])
    swapvars = {r: tk.BooleanVar(value=(r in _swap_cur)) for r in cfg.SWAP_ROLES}
    skin.section_rule(body, "AUTO ROLE SWAP (autofill escape)").pack(fill="x", padx=18, pady=(10, 2))
    tk.Label(body, text="Check the roles you actually play. If you get autofilled off them, Smiteless "
             "automatically REQUESTS a swap from a teammate who has one — and accepts any offer that "
             "lands you on one. It only ever moves you ONTO a checked role, never off one. None "
             "checked = off.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 2))
    swaprow = tk.Frame(body, bg=VOID)
    swaprow.pack(anchor="w", padx=16, pady=(0, 2))
    for r in cfg.SWAP_ROLES:
        _chk(swaprow, _SWAP_LBL[r], swapvars[r]).pack(side="left", padx=(0, 8))

    # Auto PICK-ORDER swap — trade your spot toward a specific pick slot (1st..5th).
    _pk = str(s.get("auto_pick_swap") or "")
    _pk = {"first": "1", "last": "5"}.get(_pk, _pk)     # legacy first/last -> a slot number
    pickswap = tk.StringVar(value=(_pk if _pk in ("any", "1", "2", "3", "4", "5") else "off"))
    skin.section_rule(body, "AUTO PICK-ORDER SWAP").pack(fill="x", padx=18, pady=(10, 2))
    tk.Label(body, text="Auto-handle pick-order swaps toward the slot you pick. 1st = first pick "
             "(lock a contested champ early); 5th = last pick (counter-pick). Pick 4th/5th to sit "
             "near the end without insisting on dead-last. It accepts any offer that moves you "
             "CLOSER to your slot and asks for one otherwise. \"Any\" just accepts every incoming "
             "request. A slot past the lobby size just means last.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 2))
    pkrow = tk.Frame(body, bg=VOID)
    pkrow.pack(anchor="w", padx=16, pady=(0, 2))
    for _lbl, _val in (("Off", "off"), ("Any", "any"), ("1st", "1"), ("2nd", "2"),
                       ("3rd", "3"), ("4th", "4"), ("5th", "5")):
        tk.Radiobutton(pkrow, text=_lbl, variable=pickswap, value=_val, bg=VOID, fg=TXT,
                       selectcolor=SUNKEN, activebackground=VOID, activeforeground=TXT,
                       font=skin.body(BODY), bd=0, highlightthickness=0).pack(side="left", padx=(0, 8))

    def _canon(nm):
        nm = (nm or "").strip()
        if not nm:
            return None
        if not _name2id:                       # ddragon unavailable -> accept the raw name
            return nm
        cid = _name2id.get(_norm(nm))
        return _id2name.get(cid) if cid else None

    skin.section_rule(body, "PERMA-BAN LIST").pack(fill="x", padx=18, pady=(12, 2))
    tk.Label(body, text="With auto-ban on, your ban locks the highest champ on this list that's "
             "still available (skipping anything a teammate is hovering), falling back to the "
             "live recommended bans if the whole list is gone. Order is priority (use ↑/↓).",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 4))
    banfr = skin.card(body, rail=LINE)
    banfr.pack(fill="x", padx=14, pady=(0, 6))
    ban_addrow = tk.Frame(banfr.body, bg=SURFACE)
    ban_addrow.pack(fill="x", padx=8, pady=(8, 4))
    ban_var = tk.StringVar()
    ban_cb = ttk.Combobox(ban_addrow, textvariable=ban_var, values=_champ_names, width=18,
                          style="Fav.TCombobox", font=skin.body(SMALL))
    ban_cb.pack(side="left")
    ban_listfr = tk.Frame(banfr.body, bg=SURFACE)
    ban_listfr.pack(fill="x", padx=8, pady=(0, 8))
    ban_list = tk.Listbox(ban_listfr, height=4, bg=SUNKEN, fg=TXT, selectbackground=HOVER,
                          selectforeground=TXT, relief="flat", highlightthickness=0, bd=0,
                          font=skin.mono(SMALL), activestyle="none")
    ban_list.pack(side="left", fill="x", expand=True)
    for _entry in (s.get("ban_list") or []):
        ban_list.insert("end", _entry)

    def _filter_bans(_e=None):
        t = ban_var.get().strip().lower()
        ban_cb["values"] = [n for n in _champ_names if t in n.lower()] if t else _champ_names

    def _add_ban(_e=None):
        nm = _canon(ban_var.get())
        if not nm:
            return
        if nm.lower() not in [ban_list.get(i).lower() for i in range(ban_list.size())]:
            ban_list.insert("end", nm)
        ban_var.set("")
        ban_cb["values"] = _champ_names

    def _rm_ban():
        sel = ban_list.curselection()
        if sel:
            ban_list.delete(sel[0])

    def _move_ban(delta):
        sel = ban_list.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < ban_list.size():
            v = ban_list.get(i)
            ban_list.delete(i)
            ban_list.insert(j, v)
            ban_list.selection_set(j)

    skin.button(ban_addrow, "+ Add", _add_ban).pack(side="left", padx=(6, 0))
    ban_cb.bind("<KeyRelease>", _filter_bans)
    ban_cb.bind("<Return>", _add_ban)
    banbtns = tk.Frame(ban_listfr, bg=SURFACE)
    banbtns.pack(side="left", fill="y", padx=(6, 0))
    skin.button(banbtns, "Remove", _rm_ban).pack(fill="x", pady=1)
    skin.button(banbtns, "↑", lambda: _move_ban(-1)).pack(fill="x", pady=1)
    skin.button(banbtns, "↓", lambda: _move_ban(1)).pack(fill="x", pady=1)

    skin.section_rule(body, "YOUR ACCOUNTS").pack(fill="x", padx=18, pady=(12, 2))
    tk.Label(body, text="One Riot ID per line (Name#TAG). Accounts you log into are remembered "
             "automatically; add smurfs here too. 'Good this game' pools your champion mastery "
             "across all of them, so it recommends champs you know on ANY account.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 4))
    accfr = skin.card(body, rail=LINE)
    accfr.pack(fill="x", padx=14, pady=(0, 6))
    acc_text = tk.Text(accfr.body, height=4, bg=SUNKEN, fg=TXT, insertbackground=TXT, relief="flat",
                       font=skin.mono(SMALL), wrap="none", highlightthickness=0, bd=0)
    acc_text.pack(fill="x", padx=8, pady=8)
    try:
        acc_text.insert("1.0", "\n".join(a["riot_id"] for a in ls.load_accounts()))
    except Exception:
        pass

    # ---------- one-click Riot login (saved "Stay signed in" sessions, no passwords) ----------
    import threading
    import lolaccounts as la
    skin.section_rule(body, "ONE-CLICK RIOT LOGIN").pack(fill="x", padx=18, pady=(12, 2))
    tk.Label(body, text="Setup, once per account: in the Riot Client log in with \"Stay signed in\" "
             "TICKED, then Save current login. After that, pick a name here (or tray → Riot login) "
             "and it closes the client, swaps the saved session in and relaunches League — no "
             "password typed, nothing stored but Riot's own encrypted session file.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 4))
    lgfr = skin.card(body, rail=LINE)
    lgfr.pack(fill="x", padx=14, pady=(0, 6))
    lg_list_fr = tk.Frame(lgfr.body, bg=SURFACE)
    lg_list_fr.pack(fill="x", padx=8, pady=(8, 4))
    lg_list = tk.Listbox(lg_list_fr, height=4, bg=SUNKEN, fg=TXT, selectbackground=HOVER,
                         selectforeground=TXT, relief="flat", highlightthickness=0, bd=0,
                         font=skin.mono(SMALL), activestyle="none")
    lg_list.pack(side="left", fill="x", expand=True)
    lg_status = tk.StringVar(value="")
    lg_names = []

    def _lg_refresh():
        lg_list.delete(0, "end")
        lg_names.clear()
        for a in la.list_accounts():
            lg_names.append(a["name"])
            rid = f'  {a["riot_id"]}' if a.get("riot_id") else ""
            lg_list.insert("end", f'{"● " if a["active"] else "  "}{a["name"]}{rid}')

    def _lg_busy(msg, fg=MUTED):
        lg_status.set(msg)
        lg_stat_lbl.config(fg=fg)

    def _lg_login():
        sel = lg_list.curselection()
        if not sel:
            _lg_busy("pick an account first", BAD)
            return
        name = lg_names[sel[0]]

        def work():
            try:
                la.switch(name, on_status=lambda s: root.after(0, _lg_busy, f"{name}: {s}"))
                root.after(0, _lg_busy, f"✓ launched as {name}", GOOD)
            except Exception as e:
                root.after(0, _lg_busy, str(e), BAD)
            root.after(0, _lg_refresh)
        _lg_busy(f"{name}: switching…")
        threading.Thread(target=work, daemon=True).start()

    def _lg_save():
        name = lg_name_entry.get().strip()

        def work():
            try:
                rid = la.save_current(name)
                root.after(0, _lg_busy, f'✓ saved "{name}"' + (f" ({rid})" if rid else ""), GOOD)
            except Exception as e:
                root.after(0, _lg_busy, str(e), BAD)
            root.after(0, _lg_refresh)
        _lg_busy("saving current login…")
        threading.Thread(target=work, daemon=True).start()

    def _lg_remove():
        sel = lg_list.curselection()
        if sel:
            la.remove(lg_names[sel[0]])
            _lg_refresh()
            _lg_busy("removed", MUTED)

    lg_btns = tk.Frame(lg_list_fr, bg=SURFACE)
    lg_btns.pack(side="left", fill="y", padx=(6, 0))
    skin.button(lg_btns, "Log in", _lg_login).pack(fill="x", pady=1)
    skin.button(lg_btns, "Remove", _lg_remove).pack(fill="x", pady=1)
    lg_addrow = tk.Frame(lgfr.body, bg=SURFACE)
    lg_addrow.pack(fill="x", padx=8, pady=(0, 4))
    lg_name_entry = tk.Entry(lg_addrow, bg=SUNKEN, fg=TXT, insertbackground=TXT, relief="flat",
                             font=skin.mono(SMALL), width=22)
    lg_name_entry.pack(side="left", ipady=3)
    skin.button(lg_addrow, "Save current login", _lg_save).pack(side="left", padx=(6, 0))
    lg_name_entry.bind("<Return>", lambda e: _lg_save())
    lg_stat_lbl = tk.Label(lgfr.body, textvariable=lg_status, bg=SURFACE, fg=MUTED,
                           font=skin.body(SMALL), anchor="w", justify="left", wraplength=410)
    lg_stat_lbl.pack(fill="x", padx=12, pady=(2, 8))
    _lg_refresh()

    def _lg_prefill():                # suggest the logged-in Riot ID as the name (background:
        try:                          # the LCU call can take seconds / the client may be off)
            import lolgame
            cur = lolgame.current_account()
            if cur and cur[1] and not lg_name_entry.get().strip():
                root.after(0, lambda: (lg_name_entry.insert(0, cur[1])
                                       if not lg_name_entry.get().strip() else None))
        except Exception:
            pass
    threading.Thread(target=_lg_prefill, daemon=True).start()

    fkey = skin.card(body, rail=LINE)
    fkey.pack(fill="x", padx=14, pady=(6, 2))
    tk.Label(fkey.body, text="ESCAPE KEY", bg=SURFACE, fg=TXT,
             font=skin.body(BODY, bold=True)).pack(anchor="w", padx=12, pady=(8, 0))
    tk.Label(fkey.body, text="Which key auto-import puts your movement summoner on. GHOST goes "
             "here too when the build has no Flash — same finger, same panic button, so the "
             "escape never moves between champs.",
             bg=SURFACE, fg=MUTED, font=skin.body(SMALL), justify="left", anchor="w",
             wraplength=430).pack(fill="x", padx=12, pady=(1, 0))
    row = tk.Frame(fkey.body, bg=SURFACE)
    row.pack(fill="x", padx=12, pady=(2, 8))
    tk.Label(row, text="D", bg=SURFACE, fg=EMBER, font=skin.body(SMALL, bold=True)).pack(side="left")
    fscale = tk.Scale(row, from_=0, to=1, resolution=1, orient="horizontal", showvalue=0,
                      variable=flash_side, bg=SURFACE, fg=TXT, troughcolor=SUNKEN, highlightthickness=0,
                      bd=0, activebackground=EMBER, sliderrelief="flat", length=180)
    fscale.pack(side="left", padx=8)
    tk.Label(row, text="F", bg=SURFACE, fg=EMBER, font=skin.body(SMALL, bold=True)).pack(side="left")
    fstat = tk.StringVar()
    tk.Label(row, textvariable=fstat, bg=SURFACE, fg=MUTED, font=skin.body(SMALL)).pack(side="left", padx=(10, 0))

    def _upd_flash(_=None):
        fstat.set("Flash / Ghost on D" if flash_side.get() == 0 else "Flash / Ghost on F")
    fscale.config(command=_upd_flash)
    _upd_flash()

    skin.section_rule(body, "STARTUP").pack(fill="x", padx=18, pady=(10, 2))
    afr = tk.Frame(body, bg=VOID)
    afr.pack(fill="x", padx=16, pady=(0, 0))
    _chk(afr, "Auto-open at champ select", auto).pack(side="left")
    _chk(afr, "Open profile/home on startup", homeonstart).pack(side="left", padx=(18, 0))
    _chk(afr, "Start with Windows", startwin).pack(side="left", padx=(18, 0))

    # ---- Live draft link: the shareable champ-select board (docs/DRAFTLINK.md) ----
    skin.section_rule(body, "LIVE DRAFT LINK").pack(fill="x", padx=18, pady=(12, 2))
    tk.Label(body, text="Posts ONE link into champ-select chat; anyone who clicks it sees the live "
             "draft with pick suggestions + runes per seat. Needs your own free Firebase Realtime "
             "Database URL (5-minute setup, $0 — see docs/DRAFTLINK.md). Empty = off.",
             bg=VOID, fg=MUTED, font=skin.body(SMALL), justify="left",
             anchor="w", wraplength=430).pack(fill="x", padx=18, pady=(0, 2))
    dbfr = skin.card(body, rail=LINE)
    dbfr.pack(fill="x", padx=14, pady=(0, 5))
    dbrow = tk.Frame(dbfr.body, bg=SURFACE)
    dbrow.pack(fill="x", padx=10, pady=(8, 2))
    tk.Label(dbrow, text="Database URL:", bg=SURFACE, fg=MUTED,
             font=skin.body(SMALL)).pack(side="left")
    db_entry = tk.Entry(dbrow, bg=SUNKEN, fg=TXT, insertbackground=TXT, relief="flat",
                        font=skin.mono(SMALL))
    db_entry.pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=3)
    db_entry.insert(0, s.get("draft_db", ""))
    db_status = tk.Label(dbfr.body, text="", bg=SURFACE, fg=MUTED, font=skin.body(SMALL),
                         anchor="w", justify="left")
    db_status.pack(fill="x", padx=12, pady=(2, 8))

    def _test_draft():
        # publish a demo draft to the pasted DB and open the resulting page — proves the
        # whole pipeline (Firebase rules + Pages hosting) without needing a lobby
        db_status.config(text="publishing a test draft…", fg=MUTED)

        def work():
            try:
                import loldraft as ldr
                cfg.save({"draft_db": db_entry.get().strip()})
                dbu = ldr._db_url()
                if not dbu:
                    raise RuntimeError("that doesn't look like a firebaseio.com / "
                                       "firebasedatabase.app URL")
                dd = _lb.ddragon()
                did = ldr._new_id()
                ldr.publish(dbu, did, ldr.build_payload(dd, ldr._demo(dd)))
                url = ldr.link_for(did)
                webbrowser.open(url)
                root.after(0, lambda: db_status.config(text="test draft published ✓ — opened in "
                                                            "your browser", fg=GOOD))
            except Exception as e:
                msg = f"test failed: {str(e)[:70]}"
                root.after(0, lambda: db_status.config(text=msg, fg=BAD))
        import threading
        threading.Thread(target=work, daemon=True).start()

    dbbtns = tk.Frame(dbfr.body, bg=SURFACE)
    dbbtns.pack(fill="x", padx=10, pady=(0, 8))
    skin.button(dbbtns, "Setup guide ↗", lambda: webbrowser.open(
        "https://github.com/bobbyroylee/smiteless/blob/main/docs/DRAFTLINK.md")).pack(
        side="left", padx=(0, 4))
    skin.button(dbbtns, "Save + test", _test_draft, primary=True).pack(side="left", padx=4)

    skin.section_rule(body, "RIOT API KEY").pack(fill="x", padx=18, pady=(12, 2))
    keyfr = skin.card(body, rail=WARN)
    keyfr.pack(fill="x", padx=14, pady=(0, 5))
    top = tk.Frame(keyfr.body, bg=SURFACE)
    top.pack(fill="x", padx=12, pady=(8, 0))
    tk.Label(top, text="Current key:", bg=SURFACE, fg=MUTED, font=skin.body(SMALL)).pack(side="left")
    keylbl = tk.Label(top, text="", bg=SURFACE, fg=MUTED, font=skin.mono(SMALL, bold=True))
    keylbl.pack(side="left", padx=(6, 0))

    row = tk.Frame(keyfr.body, bg=SURFACE)
    row.pack(fill="x", padx=10, pady=(6, 2))
    key_entry = tk.Entry(row, bg=SUNKEN, fg=TXT, insertbackground=TXT, relief="flat",
                         font=skin.mono(SMALL), width=44)
    key_entry.pack(side="left", fill="x", expand=True, ipady=3)

    key_status = tk.Label(keyfr.body, text="", bg=SURFACE, fg=MUTED, font=skin.body(SMALL),
                          anchor="w", justify="left")
    key_status.pack(fill="x", padx=12, pady=(2, 8))
    tk.Label(keyfr.body, text="Saved to ~/.riot_api_key and ~/.riot_api_key.txt", bg=SURFACE,
             fg=MUTED, font=skin.body(SMALL)).pack(anchor="w", padx=12, pady=(0, 8))

    def refresh_key_label():
        k = ls.read_key()
        if k and k.startswith("RGAPI-"):
            keylbl.config(text=f"...{k[-4:]} set", fg=GOOD)
        else:
            keylbl.config(text="not set", fg=BAD)

    def open_dev_site():
        webbrowser.open("https://developer.riotgames.com/")
        key_status.config(text="log in, copy your key, then Paste + Save", fg=MUTED)

    def paste_key():
        try:
            c = root.clipboard_get().strip()
        except Exception:
            key_status.config(text="clipboard is empty", fg=BAD)
            return
        key_entry.delete(0, "end")
        key_entry.insert(0, c)
        key_status.config(text="pasted - review it, then Save", fg=MUTED)

    def save_key():
        k = key_entry.get().strip()
        if not (k.startswith("RGAPI-") and len(k) >= 24):
            key_status.config(text="that doesn't look like an RGAPI-... key", fg=BAD)
            return
        for p in KEY_FILES:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(k)
            except Exception as e:
                key_status.config(text=f"save failed: {e}", fg=BAD)
                return
        key_entry.delete(0, "end")
        refresh_key_label()
        key_status.config(text=f"saved ...{k[-4:]} - applies next game", fg=GOOD)

    bfr = tk.Frame(keyfr.body, bg=SURFACE)
    bfr.pack(fill="x", padx=10, pady=(0, 8))

    skin.button(bfr, "Get key ↗", open_dev_site).pack(side="left", padx=(0, 4))
    skin.button(bfr, "Paste", paste_key).pack(side="left", padx=4)
    skin.button(bfr, "Save key", save_key, primary=True).pack(side="left", padx=4)
    key_entry.bind("<Return>", lambda e: save_key())
    refresh_key_label()

    status = tk.Label(body, text="", bg=VOID, fg=GOOD, font=skin.body(SMALL))
    status.pack(anchor="w", padx=18, pady=(6, 0))

    def save():
        bans = [ban_list.get(i) for i in range(ban_list.size())]
        try:
            ls.save_accounts([ln.strip() for ln in acc_text.get("1.0", "end").splitlines() if ln.strip()])
        except Exception:
            pass
        cfg.save({  # gank dials removed from the UI -> always write the tuned defaults
                  "streak_influence": cfg.DEFAULTS["streak_influence"],
                  "gank_threshold": cfg.DEFAULTS["gank_threshold"],
                  "gank_kit": cfg.BOOLS["gank_kit"],
                  "scout_games": int(scout.get()), "profile_games": int(pgames.get()),
                  "dragon_volume": int(dvol.get()), "board_size": int(bsize.get()),
                  "matchup_tips": tips.get(),
                  "item_widget": widget.get(),
                  "game_intel": intel.get(), "tempo_coach": tempo.get(), "free_alarm": freev.get(),
                  "tempo_voice": tempov.get(),
                  "dragon_audio": dragon.get(), "queue_call": queuecall.get(),
                  "respawn_plan": respawnv.get(), "re_entry": reentryv.get(),
                  "bleed_guard": bleedv.get(),
                  "death_brief": deadbrief.get(),
                  "loading_scout": loadbrief.get(),
                  "dodge_alerts": dodge.get(), "dock_champ_select": dock.get(),
                  "auto_import": autoimp.get(), "auto_ban": autoban.get(),
                  "ban_list": bans, "board_topmost": boardtop.get(),
                  "auto_accept": autoq.get(), "auto_mute": automute.get(),
                  "max_elo": maxelo_on["v"],
                  "max_elo_main": _canon(maxelo_main.get()) or "",
                  "max_elo_backup": _canon(maxelo_back.get()) or "",
                  "flash_on_d": (flash_side.get() == 0),
                  "solo_coaching": solocoach.get(),
                  "draft_link": draftlink.get(), "draft_autoopen": draftopen.get(),
                  "draft_db": db_entry.get().strip(),
                  "auto_swap_roles": [r for r in cfg.SWAP_ROLES if swapvars[r].get()],
                  "auto_pick_swap": ("" if pickswap.get() == "off" else pickswap.get())})
        cfg.set_auto_open(auto.get())
        cfg.set_home_on_start(homeonstart.get())
        cfg.set_autostart(startwin.get())
        status.config(text="saved ✓  (overlay updates live; widget toggle applies next game)", fg=GOOD)

    def reset():
        # EVERY control returns to its default — the old body listed a subset, so "Reset"
        # silently skipped tempo/voice/briefs/auto-import and lied about what it did.
        scout.set(cfg.DEFAULTS["scout_games"])
        pgames.set(cfg.DEFAULTS["profile_games"])
        dvol.set(cfg.DEFAULTS["dragon_volume"])
        bsize.set(cfg.DEFAULTS["board_size"])
        for v in (tips, widget, intel, tempo, freev, tempov, dragon, queuecall,
                  respawnv, reentryv, bleedv, deadbrief, loadbrief, dodge, dock, auto, homeonstart,
                  solocoach, draftlink, draftopen, automute, boardtop):
            v.set(True)
        for v in (autoq, autoimp, autoban):      # off-by-default automations stay off
            v.set(False)
        flash_side.set(0)
        _upd_flash()
        try:
            for var in swapvars.values():
                var.set(False)
            pickswap.set("off")
        except Exception:
            pass
        # startwin (Start with Windows) is deliberately untouched — Reset must never
        # silently re-arm a registry autostart
        status.config(text="reset to defaults - click Save to apply", fg=MUTED)

    btns = tk.Frame(body, bg=VOID)
    btns.pack(fill="x", padx=14, pady=(10, 16))
    skin.button(btns, "Save", save).pack(side="left", padx=4)
    skin.button(btns, "Reset", reset).pack(side="left", padx=4)
    skin.button(btns, "Close", root.destroy).pack(side="right", padx=4)

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w = max(560, root.winfo_reqwidth())
    h = min(max(620, root.winfo_reqheight()), int(sh * 0.90))
    root.minsize(560, 520)
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
