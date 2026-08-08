#!/usr/bin/env python3
"""smiteprofile.py - the home / profile window (opened out of game, or from the tray/hotkey).

A normal, focusable, landscape, SCROLLABLE window: your rank, recent form, champ win rates,
and your games each scored against the lobby. Click a game to expand its 10-player breakdown
in place (click again to collapse); "Load more" pulls in older games.
"""
import sys, os, threading, ctypes
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass
import lolbuild as lb
import lolprofile as lp
import lolscout as ls
import smitecard as sc
import smiteconfig as cfg
from smitei18n import t

import smiteskin as skin
_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32


def _single_instance():
    _kernel32.CreateMutexW(None, False, "Global\\SmitelessProfile")
    return _kernel32.GetLastError() != 183     # ERROR_ALREADY_EXISTS


def _center(root, w, h):
    """Center on the SECOND monitor if there is one (so it lands beside the game, like the
    overlay), else the primary."""
    try:
        from smiteoverlay import target_monitor
        l, t, r, b = target_monitor()
        x = l + ((r - l) - w) // 2
        y = t + max(0, ((b - t) - h) // 2 - 40)
        root.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        try:
            sw, sh = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
            root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 40)}")
        except Exception:
            root.geometry(f"{w}x{h}")


def _accounts_popup(root):
    """One-click Riot logins: pick a saved account and Smiteless fills the Riot login form
    (no typing by you). Add accounts here too - credentials are DPAPI-encrypted on this PC."""
    import tkinter as tk
    import lolcreds as lc
    if getattr(_accounts_popup, "_win", None) is not None:
        try:
            _accounts_popup._win.deiconify(); _accounts_popup._win.lift(); return
        except Exception:
            pass
    win = tk.Toplevel(root)
    _accounts_popup._win = win
    win.title(t("Riot logins"))
    win.configure(bg=skin.VOID)
    skin.dark_titlebar(win)
    win.resizable(False, False)

    def _close():
        _accounts_popup._win = None
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", _close)

    skin.brand_row(win, "logins", bg=skin.VOID).pack(anchor="w", padx=16, pady=(14, 2))
    tk.Label(win, text="Click an account — Smiteless brings up the Riot login and fills it in. A "
             "fresh login can still hit a Riot captcha / MFA email that nothing can auto-skip.",
             bg=skin.VOID, fg=skin.MUTED, font=skin.body(skin.SMALL), justify="left",
             wraplength=380).pack(anchor="w", padx=16, pady=(0, 8))

    listwrap = tk.Frame(win, bg=skin.VOID)
    listwrap.pack(fill="x", padx=14)
    status = tk.Label(win, text="", bg=skin.VOID, fg=skin.MUTED, font=skin.body(skin.SMALL),
                      anchor="w", justify="left", wraplength=380)

    def _set_status(msg, fg=skin.MUTED):
        status.config(text=msg, fg=fg)

    def _do_login(name):
        _set_status(f"{name}: starting…")

        def work():
            try:
                lc.fill(name, on_status=lambda s: root.after(0, _set_status, f"{name}: {s}"))
                root.after(0, _set_status, f"✓ {name} — check the Riot window", skin.GOOD)
            except Exception as e:
                root.after(0, _set_status, str(e), skin.BAD)
        threading.Thread(target=work, daemon=True).start()

    def _refresh():
        for w in listwrap.winfo_children():
            w.destroy()
        nm = lc.names()
        if not nm:
            tk.Label(listwrap, text=t("No accounts yet — add one below."), bg=skin.VOID,
                     fg=skin.FAINT, font=skin.body(skin.SMALL)).pack(anchor="w", pady=4)
        for name in nm:
            row = skin.card(listwrap, rail=skin.LINE)
            row.pack(fill="x", pady=3)
            tk.Label(row.body, text=name, bg=skin.SURFACE, fg=skin.TXT,
                     font=skin.body(skin.BODY, bold=True)).pack(side="left", padx=12, pady=6)
            skin.button(row.body, "✕", (lambda n=name: (lc.remove(n), _refresh())),
                        size=skin.SMALL).pack(side="right", padx=(0, 8))
            skin.button(row.body, t("Log in"), (lambda n=name: _do_login(n)),
                        primary=True, size=skin.SMALL).pack(side="right", padx=6)

    skin.section_rule(win, "ADD / UPDATE ACCOUNT").pack(fill="x", padx=18, pady=(12, 2))
    form = skin.card(win, rail=skin.LINE)
    form.pack(fill="x", padx=14, pady=(0, 6))
    fb = form.body

    def _field(label, show=None):
        tk.Label(fb, text=label, bg=skin.SURFACE, fg=skin.MUTED,
                 font=skin.body(skin.SMALL)).pack(anchor="w", padx=12, pady=(6, 0))
        e = tk.Entry(fb, bg=skin.SUNKEN, fg=skin.TXT, insertbackground=skin.TXT, relief="flat",
                     font=skin.mono(skin.SMALL), show=(show or ""))
        e.pack(fill="x", padx=12, pady=(1, 2), ipady=3)
        return e
    e_name = _field("Label (e.g. Main, Smurf)")
    e_user = _field("Riot username (not the Riot ID)")
    e_pass = _field("Password", show="•")
    showpw = tk.BooleanVar(value=False)
    tk.Checkbutton(fb, text=t("show password"), variable=showpw, bg=skin.SURFACE, fg=skin.MUTED,
                   selectcolor=skin.SUNKEN, activebackground=skin.SURFACE, activeforeground=skin.MUTED,
                   font=skin.body(skin.SMALL), bd=0, highlightthickness=0,
                   command=lambda: e_pass.config(show="" if showpw.get() else "•")).pack(anchor="w", padx=8)

    def _save():
        try:
            lc.upsert(e_name.get(), e_user.get(), e_pass.get())
            _set_status(f'✓ saved "{e_name.get().strip()}"', skin.GOOD)
            e_name.delete(0, "end"); e_user.delete(0, "end"); e_pass.delete(0, "end")
            _refresh()
        except Exception as e:
            _set_status(str(e), skin.BAD)
    btns = tk.Frame(fb, bg=skin.SURFACE)
    btns.pack(fill="x", padx=8, pady=(4, 8))
    skin.button(btns, t("Save account"), _save, primary=True).pack(side="left", padx=4)
    e_pass.bind("<Return>", lambda e: _save())
    status.pack(anchor="w", padx=16, pady=(6, 12))
    _refresh()

    win.update_idletasks()
    w, h = max(420, win.winfo_reqwidth()), win.winfo_reqheight()
    try:
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        win.geometry(f"{w}x{h}+{rx + 60}+{ry + 60}")
    except Exception:
        pass
    win.bind("<Escape>", lambda e: _close())
    win.transient(root)
    win.update_idletasks()
    skin.dark_titlebar(win)                     # re-apply once realized (DWM needs the live HWND)


def main():
    if not _single_instance():
        return
    import tkinter as tk
    from PIL import Image, ImageTk

    dd = lb.ddragon()
    key = ls.read_key()
    st = {"count": cfg.load().get("profile_games", 30), "busy": False, "photo_top": None, "photo_bottom": None,
          "split_y": 0, "prof": None, "expanded": set(), "details": {}, "nav": [],
          "hit": [], "hit_reviews": [],
          "hit_players": [], "view": None, "own_prof": None,   # view None = my profile; else {puuid, riot_id}
          "scale": 1.0, "ox": 0, "_last_w": 0}                 # display scale + x-offset for window-fit

    root = tk.Tk()
    cfg.watch_tray(root)                        # close with the tray (no orphan profile window)
    root.title(f"Smiteless — {t('Profile')}")
    root.configure(bg=skin.VOID)
    skin.dark_titlebar(root)
    try:
        cand = []
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            cand.extend([
                os.path.join(exe_dir, "assets", "smiteless.ico"),
                os.path.join(exe_dir, "smiteless.ico"),
            ])
        cand.extend([
            os.path.join(_ROOT, "assets", "smiteless.ico"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "smiteless.ico"),
        ])
        ico = next((p for p in cand if os.path.exists(p)), "")
        if ico:
            # Use both APIs so Windows titlebar/taskbar consistently get the same "S" icon.
            root.iconbitmap(ico)
            root._app_icon = ImageTk.PhotoImage(Image.open(ico))
            root.iconphoto(True, root._app_icon)
    except Exception:
        pass
    _center(root, sc.PW + 24, 780)              # default tall enough to show ~10 recent games before scrolling
    root.minsize(sc.PW + 24, 520)

    header = tk.Label(root, bg=skin.VOID, bd=0, highlightthickness=0)
    header.pack(side="top", fill="x")

    body = tk.Frame(root, bg=skin.VOID)
    body.pack(side="top", fill="both", expand=True)
    vbar = tk.Scrollbar(body, orient="vertical", bg=skin.SURFACE, troughcolor=skin.SUNKEN,
                        activebackground=skin.HOVER, relief="flat", bd=0,
                        highlightthickness=0, width=12)
    vbar.pack(side="right", fill="y")
    canvas = tk.Canvas(body, bg=skin.VOID, highlightthickness=0, yscrollcommand=vbar.set, width=sc.PW)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.config(command=canvas.yview)
    canvas.create_text(sc.PW // 2, 60, text=t("loading your match history…"), fill=skin.MUTED, font=skin.body(12))

    # Two-row bottom area so nothing crowds: buttons row on top, status line below it.
    # (One row squeezed the dynamically-shown back button to zero width and mashed Save card.)
    statusbar = tk.Frame(root, bg=skin.SURFACE)
    statusbar.pack(side="bottom", fill="x")
    status = tk.Label(statusbar, text="", bg=skin.SURFACE, fg=skin.MUTED, font=skin.body(skin.SMALL), anchor="w")
    status.pack(fill="x", padx=14, pady=(0, 6))
    bar = tk.Frame(root, bg=skin.SURFACE)
    bar.pack(side="bottom", fill="x")
    backbtn = tk.Button(bar, text=t("← back"), bg=skin.RAISED, fg=skin.EMBER, activebackground=skin.HOVER,
                        activeforeground=skin.EMBER, relief="flat", font=skin.body(skin.SMALL, bold=True),
                        padx=12, pady=4, cursor="hand2")
    search = tk.Entry(bar, bg=skin.SUNKEN, fg=skin.TXT, insertbackground=skin.TXT, relief="flat",
                      font=skin.body(skin.SMALL), width=24)
    search.pack(side="left", padx=(12, 2), pady=7, ipady=3)
    search.insert(0, "Name#TAG")
    search.bind("<FocusIn>", lambda e: (search.delete(0, "end") if search.get() == "Name#TAG" else None))
    gobtn = skin.button(bar, t("Search"), None, size=skin.SMALL)
    gobtn.pack(side="left", padx=(2, 6), pady=7)

    def _open_logins():
        _accounts_popup(root)
    loginbtn = tk.Button(bar, text=t("⚡ Log in"), bg=skin.RAISED, fg=skin.EMBER, activebackground=skin.HOVER,
                         activeforeground=skin.EMBER, relief="flat", font=skin.body(skin.SMALL, bold=True),
                         padx=12, pady=4, cursor="hand2", command=_open_logins)
    loginbtn.pack(side="left", padx=(0, 6), pady=7)
    loginbtn.bind("<Enter>", lambda e: loginbtn.config(bg=skin.HOVER))
    loginbtn.bind("<Leave>", lambda e: loginbtn.config(bg=skin.RAISED))
    loadbtn = skin.button(bar, t("Load more"), None, size=skin.SMALL)
    loadbtn.config(state="disabled")
    loadbtn.pack(side="right", padx=12, pady=7)
    savebtn = skin.button(bar, t("Save card"), None, size=skin.SMALL)
    savebtn.config(state="disabled")
    savebtn.pack(side="right", padx=(0, 4), pady=7)
    refreshbtn = tk.Button(bar, text=t("⟳ Refresh"), bg=skin.RAISED, fg=skin.EMBER, activebackground=skin.HOVER,
                           activeforeground=skin.EMBER, relief="flat", font=skin.body(skin.SMALL, bold=True),
                           padx=12, pady=4, cursor="hand2", state="disabled")
    refreshbtn.pack(side="right", padx=(0, 4), pady=7)
    refreshbtn.bind("<Enter>", lambda e: refreshbtn.config(bg=skin.HOVER))
    refreshbtn.bind("<Leave>", lambda e: refreshbtn.config(bg=skin.RAISED))

    def _save_card():
        prof = st.get("prof")
        if not prof:
            return
        try:
            import time as _t
            pil = sc.render_profile(dd, prof)          # collapsed, shareable snapshot
            name = f"smiteless_{(prof.get('riot_id') or 'profile').split('#')[0]}_{_t.strftime('%Y%m%d')}.png"
            name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
            dest = os.path.join(os.path.expanduser("~"), "Desktop", name)
            pil.save(dest)
            status.config(text=f"saved → {dest}")
        except Exception as e:
            status.config(text=f"save failed: {e}")

    _LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)

    def _blit(force_top=None):
        """Draw the cached profile image, shrink-fitted if the window is somehow narrower
        than the render (never upscaled — the raster is RE-RENDERED at the window's width
        by _render, so maximizing gives more crisp content, not stretched pixels). Hit
        regions stay in image space; clicks divide by st['scale'] and subtract st['ox']."""
        top, bot = st.get("base_top"), st.get("base_bottom")
        if top is None or bot is None:
            return
        cw = canvas.winfo_width()
        if cw <= 1:
            cw = sc.PW                          # not realized yet -> natural width
        k = min(1.0, cw / max(1, bot.width))    # only ever DOWN; up = re-render, not stretch
        st["scale"] = k
        top_s = top.resize((round(top.width * k), round(top.height * k)), _LANCZOS) if k < 0.999 else top
        bot_s = bot.resize((round(bot.width * k), round(bot.height * k)), _LANCZOS) if k < 0.999 else bot
        st["ox"] = ox = max(0, (cw - bot_s.width) // 2)
        ptop, pbot = ImageTk.PhotoImage(top_s), ImageTk.PhotoImage(bot_s)
        st["photo_top"], st["photo_bottom"] = ptop, pbot   # keep refs or Tk GC's them
        top_pos = canvas.yview()[0] if force_top is None else force_top
        header.config(image=ptop)
        canvas.delete("all")
        canvas.create_image(ox, 0, anchor="nw", image=pbot)
        canvas.configure(scrollregion=(0, 0, max(cw, bot_s.width), bot_s.height))
        canvas.yview_moveto(top_pos)

    def _render(keep_scroll=True):
        prof = st["prof"]
        if not prof:
            return
        cw = canvas.winfo_width()
        rw = int(min(2400, max(sc.PW, cw if cw > 1 else sc.PW)))
        st["rw"] = rw                            # render AT the window width — adapt, don't stretch
        pil = sc.render_profile(dd, prof, st["expanded"], st["details"], width=rw)
        split = int(getattr(pil, "profile_split_y", 240))
        split = max(120, min(pil.height - 1, split))
        st["base_top"] = pil.crop((0, 0, pil.width, split))
        st["base_bottom"] = pil.crop((0, split, pil.width, pil.height))
        st["split_y"] = split
        st["hit"] = [(max(0, y0 - split), max(0, y1 - split), idx)
                     for y0, y1, idx in getattr(pil, "hit_games", []) if y1 > split]
        st["hit_reviews"] = [(x0, max(0, y0 - split), x1, max(0, y1 - split), idx)
                             for x0, y0, x1, y1, idx in getattr(pil, "hit_reviews", []) if y1 > split]
        st["hit_players"] = [(x0, max(0, y0 - split), x1, max(0, y1 - split), pu, nm)
                             for x0, y0, x1, y1, pu, nm in getattr(pil, "hit_players", []) if y1 > split]
        _blit(force_top=(None if keep_scroll else 0.0))

    def _apply(prof):
        st["busy"] = False
        if not prof or not prof.get("games"):
            header.config(image="")
            canvas.delete("all")
            if prof and prof.get("error"):
                msg = prof["error"]
            elif prof and prof.get("riot_id"):
                msg = (f"no recent Summoner's Rift games found for {prof['riot_id']} — "
                       "ARAM/Arena don't show here. If that seems wrong, your Riot key may "
                       "have expired (Settings → Riot API Key).")
            else:
                msg = ("couldn't tell who you are yet — open the League client once (Smiteless "
                       "remembers you after that, so the profile works with the client closed) "
                       "and check the Riot key in Settings.")
            canvas.create_text(sc.PW // 2, 70, text=msg, fill=skin.MUTED, font=skin.body(12), width=sc.PW - 100)
            return
        st["prof"] = prof
        _render(keep_scroll=False)
        latest = (prof.get("games") or [{}])[0].get("review") or []
        head = f"{len(prof['games'])} games ({prof.get('queue_label') or 'recent'})"
        if prof.get("stale"):                      # served from disk: say so instead of lying
            status.config(text=f"{head}  ·  {prof.get('stale_note') or 'cached copy'}")
        elif latest:
            status.config(text=f"{head}  ·  latest review: {latest[0]}")
        else:
            status.config(text=f"{head}  ·  click a game for the full breakdown")
        loadbtn.config(state="normal", text="Load more")
        savebtn.config(state="normal", command=_save_card)
        refreshbtn.config(state="normal", text="⟳ Refresh")
        _fill_season(prof)

    def _fill_season(prof):
        """Upgrade TOP CHAMPIONS (and THE POOL) to season-wide numbers in the background."""
        pu = prof.get("puuid")
        if not pu or prof.get("season_champs"):
            return

        def work():
            try:
                champs = lp.season_champs(dd, pu, key)
            except Exception:
                champs = []
            if not champs:
                return

            def apply():
                cur = st.get("prof") or {}
                if cur.get("puuid") != pu:            # user navigated away meanwhile
                    return
                cur["champs"] = champs[:6]
                # THE POOL is re-priced off the FULL season list, not the six drawn on the
                # page: the deeper read is exactly where a champion first crosses MIN_G, and
                # the pool-width claim is about the tail this truncation would have deleted.
                cur["all_champs"] = champs
                cur["pool"] = lp.pool_board(champs)
                cur["season_champs"] = True
                _render()
            root.after(0, apply)
        threading.Thread(target=work, daemon=True).start()

    def _load(more=False, force=False):
        if st["busy"]:
            return
        st["busy"] = True
        if more:
            st["count"] += 10
            loadbtn.config(text="loading…", state="disabled")
        if force:
            refreshbtn.config(text="⟳ …", state="disabled")
        view = st["view"]

        def work():
            try:
                if view:
                    prof = lp.build_profile(dd, count=st["count"], force=force,
                                            riot_id=view.get("riot_id"), puuid=view.get("puuid"))
                else:
                    prof = lp.build_profile(dd, count=st["count"], force=force)
            except Exception:
                prof = None
            root.after(0, lambda: _apply(prof))
        threading.Thread(target=work, daemon=True).start()

    refreshbtn.config(command=lambda: _load(force=True))

    def _open_view(riot_id=None, puuid=None):
        """Switch the window to another player's profile (search / clicked a name).
        Pushes the CURRENT page — profile, expanded games, scroll position — onto a nav
        stack, so back returns EXACTLY where you were (§9: deep-diving accounts is a
        stack walk, not a reset). Match details are match-keyed and immutable, so the
        shared details cache survives every hop and re-expands are instant."""
        if st["busy"]:
            return
        if st["prof"]:
            st["nav"].append({"view": st["view"], "prof": st["prof"],
                              "expanded": set(st["expanded"]), "count": st["count"],
                              "scroll": canvas.yview()[0] if canvas.yview() else 0.0})
            if st["view"] is None:
                st["own_prof"] = st["prof"]               # still kept as a safety net
        st["view"] = {"riot_id": riot_id, "puuid": puuid}
        st["expanded"] = set()
        st["count"] = cfg.load().get("profile_games", 30)
        backbtn.pack(side="left", before=search, padx=(12, 0), pady=7)   # left of search: never crowded out
        status.config(text=f"loading {riot_id or 'player'}…")
        _load(False)

    def _go_back():
        if not st["nav"]:                                 # nothing to pop -> classic reset home
            st["view"] = None
            st["expanded"] = set()
            backbtn.pack_forget()
            if st["own_prof"]:
                _apply(st["own_prof"])
            else:
                _load(False)
            return
        fr = st["nav"].pop()
        st["view"] = fr["view"]
        st["expanded"] = fr["expanded"]
        st["count"] = fr["count"]
        st["prof"] = fr["prof"]
        st["busy"] = False
        if not st["nav"]:
            backbtn.pack_forget()
        _render()
        canvas.yview_moveto(fr.get("scroll") or 0.0)      # land on the exact row you left
        who = (fr["view"] or {}).get("riot_id") or "your profile"
        status.config(text=f"back to {who}")

    def _do_search(_e=None):
        q = search.get().strip()
        if "#" not in q:
            status.config(text="type the full riot id: Name#TAG")
            return
        _open_view(riot_id=q)

    backbtn.config(command=_go_back)
    gobtn.config(command=_do_search)
    search.bind("<Return>", _do_search)

    def _fetch_detail(mid):
        def work():
            try:
                det = lp.match_detail(mid, key)
            except Exception:
                det = None
            det = det or {}
            st["details"][mid] = det
            root.after(0, _render)
            # each player's CURRENT rank (§9): 10 cached league-v4 reads, filled in after
            # the detail is already on screen so the expand never waits on them
            try:
                if det.get("parts"):
                    ranks = {}
                    for pl in det["parts"]:
                        pu = pl.get("puuid")
                        if not pu:
                            continue
                        rk = ls.rank(pu, key)
                        if rk and rk.get("tier"):
                            ranks[pu] = rk
                    if ranks:
                        det["ranks"] = ranks
                        root.after(0, _render)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _show_review(game):
        import tkinter as tk
        tips = list(game.get("review") or [])
        kind = game.get("review_kind", "improve")
        head = t("What you did well") if kind == "positive" else t("3 things to improve")
        win = tk.Toplevel(root)
        win.title(f"Smiteless — {t('Full review')}")
        win.configure(bg=skin.VOID)
        skin.dark_titlebar(win)
        win.minsize(560, 360)
        tk.Label(win, text=f"{game.get('champ', '?')} ({game.get('pos', '?')})", bg=skin.VOID, fg=skin.EMBER,
                 font=skin.display(skin.H2, bold=True)).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(win, text=head, bg=skin.VOID, fg=(skin.TXT if kind == "positive" else skin.MUTED),
                 font=skin.display(skin.BODY)).pack(anchor="w", padx=14, pady=(0, 8))
        wrap = tk.Frame(win, bg=skin.VOID)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        sb = tk.Scrollbar(wrap, orient="vertical")
        sb.pack(side="right", fill="y")
        tx = tk.Text(wrap, bg=skin.SURFACE, fg=skin.TXT, relief="flat", wrap="word", yscrollcommand=sb.set,
                     font=skin.body(skin.BODY), padx=12, pady=10)
        tx.pack(side="left", fill="both", expand=True)
        sb.config(command=tx.yview)
        if not tips:
            tips = [t("No review available yet.")]
        for i, t in enumerate(tips, 1):
            tx.insert("end", f"{i}. {t}\n\n")
        tx.config(state="disabled")

    def _on_click(event):
        k, ox = st.get("scale", 1.0), st.get("ox", 0)
        x = (canvas.canvasx(event.x) - ox) / k     # canvas is in scaled+centered space -> image space
        y = canvas.canvasy(event.y) / k
        for x0, y0, x1, y1, idx in st["hit_reviews"]:
            if x0 <= x <= x1 and y0 <= y <= y1:
                gm = st["prof"]["games"][idx]
                _show_review(gm)
                return
        me = (st["prof"] or {}).get("puuid")
        for x0, y0, x1, y1, pu, nm in st["hit_players"]:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if pu and pu != me:                       # click a player -> their profile
                    _open_view(riot_id=(nm or None), puuid=pu)
                return
        for y0, y1, idx in st["hit"]:
            if y0 <= y <= y1:
                # in-canvas "Load more" region (special hit index)
                if idx == "__load_more__":
                    _load(True)
                    return
                if idx in st["expanded"]:
                    st["expanded"].discard(idx)
                else:
                    st["expanded"].add(idx)
                    mid = st["prof"]["games"][idx].get("mid")
                    if mid and mid not in st["details"]:
                        _fetch_detail(mid)       # loads, then re-renders
                _render()
                return

    def _player_menu(event, riot_id, puuid):
        """Right-click a player -> look them up anywhere / open their Smiteless profile / copy."""
        import webbrowser
        m = tk.Menu(root, tearoff=0, bg=skin.SURFACE, fg=skin.TXT, activebackground=skin.HOVER,
                    activeforeground=skin.TXT, bd=0, font=skin.body(skin.SMALL))
        who = (riot_id or "player").split("#")[0]
        m.add_command(label=f"{who}", state="disabled")
        m.add_separator()
        me = (st["prof"] or {}).get("puuid")
        if puuid and puuid != me:
            m.add_command(label="View on Smiteless",
                          command=lambda: _open_view(riot_id=(riot_id or None), puuid=puuid))
            m.add_separator()
        for label, url in sc.site_urls(riot_id):
            m.add_command(label=label, command=lambda u=url: webbrowser.open(u))
        if riot_id:
            m.add_separator()
            m.add_command(label="Copy name",
                          command=lambda: (root.clipboard_clear(), root.clipboard_append(riot_id),
                                           status.config(text=f"copied {riot_id}")))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _on_right(event):
        k, ox = st.get("scale", 1.0), st.get("ox", 0)
        x, y = (canvas.canvasx(event.x) - ox) / k, canvas.canvasy(event.y) / k
        for x0, y0, x1, y1, pu, nm in st["hit_players"]:
            if x0 <= x <= x1 and y0 <= y <= y1:
                if pu:
                    _player_menu(event, nm, pu)
                return
        # right-clicking the profile owner's own art/header works too
        if st.get("prof") and st["prof"].get("riot_id") and st["prof"]["riot_id"] != "?":
            _player_menu(event, st["prof"]["riot_id"], st["prof"].get("puuid"))

    def _on_canvas_resize(event):
        # window resized (e.g. maximize) -> RE-RENDER the profile at the new width (crisp,
        # more content — never a raster stretch). Debounced so a drag doesn't re-render on
        # every intermediate pixel; skipped until content exists.
        if st.get("base_bottom") is None or event.width == st.get("_last_w"):
            return
        st["_last_w"] = event.width
        if st.get("_resize_after"):
            try:
                root.after_cancel(st["_resize_after"])
            except Exception:
                pass

        def _refit():
            want = int(min(2400, max(sc.PW, event.width)))
            if want != st.get("rw"):
                _render(keep_scroll=True)        # width actually changed -> full re-render
            else:
                _blit(force_top=None)            # same render width -> just re-center
        st["_resize_after"] = root.after(150, _refit)

    loadbtn.config(command=lambda: _load(True))
    canvas.bind("<Configure>", _on_canvas_resize)
    canvas.bind("<Button-1>", _on_click)
    canvas.bind("<Button-3>", _on_right)
    header.bind("<Button-3>", _on_right)                   # right-click the header art too
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
    root.bind("<Escape>", lambda e: root.destroy())

    # Close automatically once you enter champ select (or a game) — the docked champ-select
    # panel / in-game overlay takes over there, so the profile window shouldn't linger.
    def _watch_phase():
        def work():
            try:
                import phasecheck
                ph = phasecheck.phase()
            except Exception:
                ph = ""
            if ph in ("ChampSelect", "GameStart", "InProgress", "Reconnect"):
                try:
                    root.after(0, root.destroy)
                except Exception:
                    pass
            else:
                try:
                    root.after(2500, _watch_phase)
                except Exception:
                    pass
        threading.Thread(target=work, daemon=True).start()
    root.after(2500, _watch_phase)

    root.after(60, lambda: _load(False))
    root.mainloop()


if __name__ == "__main__":
    main()
