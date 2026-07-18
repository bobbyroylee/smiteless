#!/usr/bin/env python3
"""smiteoverlay.py - the live Smiteless overlay, all in Python.

A borderless, always-on-top window that polls the League client/API directly and
updates IN PLACE as champ-select picks come in and the game progresses - no PNG
round-trip, no AutoHotkey picture-reload. It reuses smitecard's renderer (the same
Pillow scoreboard) but displays each frame straight into a Tk window via PhotoImage.

Key behaviors:
  - Never steals focus from the game (WS_EX_NOACTIVATE) - stays on top, click/Esc closes.
  - Opens on the second monitor if you have one.
  - Auto-closes ~1.5 min after the match ends so the next game's auto-open is fresh.
  - Single-instance (a second launch no-ops while one is already up).

  python smiteoverlay.py            # manual: show status now, then the board
  python smiteoverlay.py --wait     # auto-open: stay hidden until champs are present
  python smiteoverlay.py --count 10
"""
import sys, os, threading, ctypes, webbrowser, json, ssl, urllib.request
from ctypes import wintypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass
import smitecard as sc
import smiteconfig as cfg

import smiteskin as skin
BG = skin.VOID   # matches smitecard's background so there's no border seam
MIN_UI_SCALE = 0.12

# ---- win32 constants ----
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def acquire_single_instance():
    """True if we're the only overlay; False if one is already running."""
    _kernel32.CreateMutexW(None, False, "Global\\SmitelessOverlay")
    return _kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def monitors():
    """List of (left, top, right, bottom) for each display."""
    rects = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), ctypes.c_double)

    def cb(_h, _dc, prc, _d):
        r = prc.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return 1
    try:
        _user32.EnumDisplayMonitors(0, 0, proc(cb), 0)
    except Exception:
        pass
    if not rects:  # fallback: primary only
        rects = [(0, 0, _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1))]
    return rects


def target_monitor():
    """The non-primary monitor if there is one, else the primary. (left,top,right,bottom)"""
    mons = monitors()
    for m in mons:
        if (m[0], m[1]) != (0, 0):      # primary's origin is (0,0)
            return m
    return mons[0]


def make_no_activate(hwnd):
    try:
        ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                               ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    except Exception:
        pass


def show_no_activate(hwnd):
    try:
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
    except Exception:
        pass


def toplevel_hwnd(child):
    """Tk's winfo_id() can return a CHILD window; the WS_EX_NOACTIVATE style has to be on
    the actual TOP-LEVEL window (that's what gets activated). GA_ROOT walks up to it."""
    try:
        top = _user32.GetAncestor(child, 2)      # GA_ROOT
        return top or child
    except Exception:
        return child


def restore_foreground(target):
    """Hand focus back to `target` if our window grabbed it. Windows ignores a plain
    SetForegroundWindow from a background process, so briefly attach to the target's input
    thread. This is the hard guarantee that the overlay NEVER keeps focus from the game."""
    try:
        cur = _kernel32.GetCurrentThreadId()
        tgt = _user32.GetWindowThreadProcessId(target, None)
        _user32.AttachThreadInput(cur, tgt, True)
        _user32.SetForegroundWindow(target)
        _user32.AttachThreadInput(cur, tgt, False)
    except Exception:
        pass


def client_rect():
    """(hwnd, (l, t, r, b)) of the League client window, or (None, None)."""
    try:
        hwnd = _user32.FindWindowW("RCLIENT", None)
        if not hwnd or not _user32.IsWindowVisible(hwnd):
            return None, None
        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        return hwnd, (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None, None


def monitor_of(x, y):
    """The monitor rect containing point (x, y), else the primary."""
    mons = monitors()
    for m in mons:
        if m[0] <= x < m[2] and m[1] <= y < m[3]:
            return m
    return mons[0]


def move_window(hwnd, x, y):
    try:
        _user32.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0,
                             SWP_NOSIZE | 0x0004 | SWP_NOACTIVATE)   # SWP_NOZORDER
        return True
    except Exception:
        return False


def ui_scale(size, mon, extra_h=0, docked=False):
    """Resolution-adaptive display scale for a rendered frame.

    Non-docked boards (loading / in-game) intentionally occupy a bounded slice of the
    monitor so they don't dominate the whole screen, then hard-clamp to fit. Docked
    champ-select panels skip the occupancy cap and only fit-clamp. Never upscales."""
    w, h = size
    mw, mh = max(1, mon[2] - mon[0]), max(1, mon[3] - mon[1])
    fit = min((mh - 16 - extra_h) / max(1, h), (mw - 16) / max(1, w))
    if docked:
        s = min(1.0, fit)
    else:
        occ = min((mw * 0.78) / max(1, w), (mh * 0.84 - extra_h) / max(1, h))
        s = min(1.0, fit, occ)
    return max(MIN_UI_SCALE, s)


def _open_profile():
    """Open the Profile window as its own process (works frozen or as dev scripts)."""
    import subprocess
    try:
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable, "profile"], close_fds=True)   # SmitelessApp.exe profile
        else:
            prof = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smiteprofile.py")
            subprocess.Popen([sys.executable, prof], close_fds=True)         # pythonw smiteprofile.py
    except Exception:
        pass


def _lcu_json(method, path, payload=None, timeout=5):
    import lolgame as lg
    lc = lg._lcu()
    if not lc:
        raise RuntimeError("League client not found")
    port, hdr = lc
    headers = dict(hdr)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", headers=headers, data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
        raw = r.read()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def main():
    argv = sys.argv[1:]
    wait = "--wait" in argv
    if wait:
        argv.remove("--wait")
    # A manual open OUTSIDE a game -> the home/profile window (a separate process) instead of
    # the in-game board.
    if not wait:
        try:
            import phasecheck
            if phasecheck.phase() not in sc.ACTIVE_PHASES:
                _open_profile()
                return
        except Exception:
            pass
    if not acquire_single_instance():
        return  # another overlay is already up
    count = None                                 # None -> smitecard.run uses the saved scout-depth setting
    if "--count" in argv:
        i = argv.index("--count")
        try:
            count = int(argv[i + 1])
        except Exception:
            pass

    import tkinter as tk
    from PIL import Image, ImageTk

    root = tk.Tk()
    root.overrideredirect(True)                 # borderless, no taskbar button
    root.attributes("-topmost", True)
    root.configure(bg=BG)
    root.geometry("1x1+-4000+-4000")            # park off-screen until the first frame
    label = tk.Label(root, bd=0, bg=BG)
    label.pack(side="top")

    # --- Riot API key bar: refresh the dev key (expires every 24h) without leaving the game ---
    KEY_FILES = [os.path.expanduser("~/.riot_api_key"), os.path.expanduser("~/.riot_api_key.txt")]

    def read_current_key():
        for p in KEY_FILES:
            try:
                if os.path.exists(p):
                    k = open(p, encoding="utf-8").read().strip()
                    if k:
                        return k
            except Exception:
                pass
        return None

    bar = tk.Frame(root, bg=skin.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(bar, bg=skin.WARN, width=skin.RAIL).pack(side="left", fill="y")
    tk.Label(bar, text="RIOT KEY", bg=skin.SURFACE, fg=skin.EMBER,
             font=skin.display(10, bold=True)).pack(side="left", padx=(10, 4), pady=6)
    keylbl = tk.Label(bar, text="", bg=skin.SURFACE, fg=skin.MUTED, font=skin.body(skin.SMALL, bold=True))
    keylbl.pack(side="left", padx=(0, 6))

    def refresh_key_label():
        k = read_current_key()
        if k and k.startswith("RGAPI-"):
            keylbl.config(text=f"...{k[-4:]} set", fg=skin.GOOD)
        else:
            keylbl.config(text="not set", fg=skin.BAD)

    def open_dev_site():
        webbrowser.open("https://developer.riotgames.com/")
        status.config(text="log in, copy your key, then Paste + Save", fg=skin.MUTED)

    def paste_key():
        try:
            c = root.clipboard_get().strip()
        except Exception:
            status.config(text="clipboard is empty", fg=skin.BAD)
            return
        entry.delete(0, "end")
        entry.insert(0, c)
        status.config(text="pasted - review it, then Save", fg=skin.MUTED)

    def save_key():
        k = entry.get().strip()
        if not (k.startswith("RGAPI-") and len(k) >= 24):
            status.config(text="that doesn't look like an RGAPI-... key", fg=skin.BAD)
            return
        for p in KEY_FILES:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(k)
            except Exception as e:
                status.config(text=f"save failed: {e}", fg=skin.BAD)
                return
        entry.delete(0, "end")
        refresh_key_label()
        status.config(text=f"saved ...{k[-4:]} - applies next game", fg=skin.GOOD)

    def import_build():
        status.config(text="importing runes + summoners...", fg=skin.MUTED)

        def work():
            try:
                import lolbuild as lb
                import lolgame as lg
                import lolimport as limp
                dd = lb.ddragon()
                info, err = lg.resolve(dd)
                if err:
                    raise RuntimeError("not in champ select")
                if info.get("source") != "champ select":
                    raise RuntimeError("import works in champ select only")
                cid = info.get("my") or 0
                role = info.get("pos") or "jungle"
                build = sc.pick_rune(sc.build_data(dd, cid, role))   # honor the selected rune set
                msg = limp.import_build(dd, cid, role, build)
                root.after(0, lambda: status.config(text=msg, fg=skin.GOOD))
            except Exception as e:
                root.after(0, lambda: status.config(text=f"import failed: {e}", fg=skin.BAD))

        threading.Thread(target=work, daemon=True).start()

    def hover_pick(cid):
        """Click a 'good this game' face -> HOVER that champ in champ select (never locks).
        The panel then re-renders to the hovered champ (its runes/build) on its own."""
        def work():
            try:
                import lolbuild as lb
                import lolimport as limp
                dd = lb.ddragon()
                limp.hover_champ(cid)
                nm = dd["id2name"].get(cid, "champ")
                root.after(0, lambda: status.config(text=f"hovered {nm}", fg=skin.GOOD))
            except Exception as e:
                root.after(0, lambda: status.config(text=f"hover failed: {e}", fg=skin.BAD))
        threading.Thread(target=work, daemon=True).start()

    skin.button(bar, "Get key ↗", open_dev_site, size=skin.SMALL).pack(side="left", padx=2, pady=4)
    entry = tk.Entry(bar, bg=skin.SUNKEN, fg=skin.TXT, insertbackground=skin.TXT, relief="flat",
                     font=skin.mono(9), width=30)
    entry.pack(side="left", padx=(8, 2), pady=4, ipady=2)
    entry.bind("<Button-1>", lambda e: entry.focus_set())   # attempt keyboard focus for Ctrl+V
    entry.bind("<Return>", lambda e: save_key())
    skin.button(bar, "Paste", paste_key, size=skin.SMALL).pack(side="left", padx=2, pady=4)
    skin.button(bar, "Save", save_key, size=skin.SMALL).pack(side="left", padx=2, pady=4)
    status = tk.Label(bar, text="", bg=skin.SURFACE, fg=skin.MUTED, font=skin.body(skin.SMALL))
    status.pack(side="left", padx=8)
    refresh_key_label()

    # The key bar earns its row only when there's work to do: with a valid key the board
    # floats clean, and the bar (with its refresh controls) returns on the next launch
    # after the 24h dev key lapses or goes missing.
    key_ok = (read_current_key() or "").startswith("RGAPI-")
    root.update_idletasks()
    bar_h = 0 if key_ok else bar.winfo_reqheight()   # the key bar's height, added below the board
    if key_ok:
        bar.pack_forget()
    hwnd = toplevel_hwnd(root.winfo_id())        # the REAL top-level (winfo_id can be a child)
    make_no_activate(hwnd)

    st = {"img": None, "dirty": False, "ref": None, "size": None, "hitmap": [],
          "pos": None, "shown": False, "closing": False, "done": False,
          "docked": False, "client_moved": None, "barh": bar_h,
          "user_scale": 1.0, "user_scaled": False, "auto_scale": 1.0,
          "raw_size": None, "win_size": None, "_placing": False}
    lock = threading.Lock()

    def emit(pil_img):                           # called from the worker thread (no Tk here!)
        with lock:
            st["img"] = pil_img
            st["dirty"] = True

    def _restore_client():
        cm = st.get("client_moved")
        if cm:
            move_window(cm[0], cm[1], cm[2])
            st["client_moved"] = None

    def _dock(pil):
        """Park the panel LEFT of the League client, vertically BALANCED against it —
        centered on the client's span, then clamped fully on-screen. (Top-aligning to the
        client used to push the panel's bottom below the desktop once it grew taller than
        the client.) Nudges the client right when there's no room, remembering where it
        was so we can put it back."""
        hwnd_c, rect = client_rect()
        if not rect:
            return                               # client not found -> normal centering
        need = pil.width + 12
        mon = monitor_of((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        x = rect[0] - need
        if x < mon[0] + 4:                       # no room -> shift the client right, park at edge
            shift = (mon[0] + 4) - x
            new_cx = min(rect[0] + shift, mon[2] - (rect[2] - rect[0]) - 4)
            if new_cx > rect[0] and move_window(hwnd_c, new_cx, rect[1]):
                if st["client_moved"] is None:
                    st["client_moved"] = (hwnd_c, rect[0], rect[1])
            x = mon[0] + 4
        y = (rect[1] + rect[3] - pil.height) // 2              # balance on the client...
        y = max(mon[1] + 4, min(y, mon[3] - pil.height - 4))   # ...clamped fully on-screen
        st["pos"] = (x, y)
        st["docked"] = True
        st["barh"] = 0                           # key bar is noise in the docked panel
        try:
            bar.pack_forget()
        except Exception:
            pass

    def _undock():
        _restore_client()
        st["docked"] = False
        st["dragged"] = False                    # a fresh dock gets to balance itself again
        st["pos"] = None                         # recenter on the next frame
        st["barh"] = bar_h
        if bar_h:                                # bar only exists on screen when the key needs work
            try:
                bar.pack(side="bottom", fill="x")
            except Exception:
                pass

    def close(*_):
        st["closing"] = True
        _restore_client()
        try:
            root.destroy()
        except Exception:
            pass

    # left-click a champ icon -> open that player's op.gg; left-DRAG moves the window;
    # Esc / right-click closes. A click is a press+release that didn't move (>5px = drag).
    def on_press(e):
        st["press"] = (e.x_root, e.y_root, e.x, e.y)
        st["last"] = (e.x_root, e.y_root)
        st["moved"] = False

    def on_drag(e):
        if not st.get("press") or not st["pos"] or not st["size"]:
            return
        if not st["moved"] and abs(e.x_root - st["press"][0]) + abs(e.y_root - st["press"][1]) < 5:
            return                               # within click tolerance - not a drag yet
        st["moved"] = True
        st["dragged"] = True                     # user placed it -> stop auto re-balancing
        dx, dy = e.x_root - st["last"][0], e.y_root - st["last"][1]
        st["pos"] = (st["pos"][0] + dx, st["pos"][1] + dy)
        st["last"] = (e.x_root, e.y_root)
        w, h = st["size"]
        root.geometry(f"{w}x{h + st['barh']}+{st['pos'][0]}+{st['pos'][1]}")

    def on_release(e):
        if st.get("press") and not st["moved"]:  # a click, not a drag
            cx, cy = st["press"][2], st["press"][3]
            for x0, y0, x1, y1, url in st["hitmap"]:
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    if isinstance(url, str) and url.startswith("action:"):
                        if url == "action:import_build":
                            import_build()
                        elif url.startswith("action:pick:"):
                            hover_pick(int(url.rsplit(":", 1)[1]))
                        elif url.startswith("action:rune:"):
                            try:
                                sc.set_rune_idx(int(url.rsplit(":", 1)[1]))
                                status.config(text="rune set switched — re-importing / re-rendering…", fg=skin.MUTED)
                            except Exception:
                                pass
                        elif url == "action:toggle_auto_import":
                            s = cfg.load()
                            s["auto_import"] = not s.get("auto_import", False)
                            cfg.save(s)
                            status.config(text=f"auto-import {'ON — runes+summs apply on lock' if s['auto_import'] else 'off'}",
                                          fg=skin.GOOD if s["auto_import"] else skin.MUTED)
                        elif url == "action:toggle_auto_ban":
                            s = cfg.load()
                            s["auto_ban"] = not s.get("auto_ban", False)
                            cfg.save(s)
                            status.config(text=f"auto-ban {'ON — locks the top ban on your turn' if s['auto_ban'] else 'off'}",
                                          fg=skin.GOOD if s["auto_ban"] else skin.MUTED)
                    else:
                        webbrowser.open(url)
                    break
        st["press"] = None
        st["moved"] = False

    def on_motion(e):                            # hand cursor over a clickable icon
        over = any(x0 <= e.x <= x1 and y0 <= e.y <= y1 for x0, y0, x1, y1, _ in st["hitmap"])
        label.config(cursor="hand2" if over else "")

    label.bind("<Button-1>", on_press)
    label.bind("<B1-Motion>", on_drag)
    label.bind("<ButtonRelease-1>", on_release)
    label.bind("<Motion>", on_motion)

    # User-resizing a borderless window can leave the image clipped if we don't recompute
    # scale immediately. Treat size changes that diverge from the auto-fit size as a user
    # override (shrink-only), and redraw at that scale.
    def on_configure(e):
        if e.widget is not root or st["closing"]:
            return
        wh = (max(1, int(e.width)), max(1, int(e.height)))
        if wh == st.get("win_size"):
            return
        st["win_size"] = wh
        if st.get("_placing") or st["docked"]:
            return
        raw = st.get("raw_size")
        if not raw:
            return
        avail_h = max(1, wh[1] - st["barh"])
        ns = min(wh[0] / max(1, raw[0]), avail_h / max(1, raw[1]))
        ns = max(MIN_UI_SCALE, min(1.0, ns))
        auto = max(MIN_UI_SCALE, min(1.0, st.get("auto_scale", 1.0)))
        if ns >= auto - 0.02:
            if st.get("user_scaled"):
                st["user_scaled"] = False
                st["user_scale"] = 1.0
                with lock:
                    if st["img"] is not None:
                        st["dirty"] = True
            return
        if (not st.get("user_scaled")) or abs(ns - st.get("user_scale", 1.0)) > 0.01:
            st["user_scaled"] = True
            st["user_scale"] = ns
            with lock:
                if st["img"] is not None:
                    st["dirty"] = True

    root.bind("<Configure>", on_configure)
    root.bind("<Escape>", close)
    label.bind("<Button-3>", close)              # right-click the board to close (not the key bar)

    def worker():
        try:
            l_, t_, r_, b_ = target_monitor()    # size the live board to the monitor it owns
            sc.BOARD_TARGET = (r_ - l_, b_ - t_)
            sc.run(emit, count=count, wait=wait, stop=lambda: st["closing"], monitor=True)
            st["done"] = True                    # normal return = match over -> overlay may close
        except Exception as e:
            # Unexpected crash: show it and KEEP the window up (don't auto-close) so it's visible.
            emit(sc.info_image(f"overlay error: {type(e).__name__}: {e}  -  Esc to close"))

    threading.Thread(target=worker, daemon=True).start()

    def place(size):
        w, h = size
        wh = h + st["barh"]                      # window = board image + the key bar (when shown)
        if st["pos"] is None:                    # center on the target monitor, once
            l, t, r, b = target_monitor()
            st["pos"] = (l + ((r - l) - w) // 2, t + ((b - t) - wh) // 2)
        x, y = st["pos"]
        def _done_placing():
            st["_placing"] = False
        st["_placing"] = True
        st["win_size"] = (w, wh)
        root.geometry(f"{w}x{wh}+{x}+{y}")
        root.after_idle(_done_placing)

    def pump():
        if st["closing"]:
            return
        with lock:
            dirty, pil = st["dirty"], st["img"]
            st["dirty"] = False
        if dirty and pil is not None:
            prev_fg = _user32.GetForegroundWindow()     # whatever had focus (the game/client)
            want_dock = bool(getattr(pil, "dock_left", False))
            st["raw_size"] = pil.size
            # Resolution-adaptive display: find the monitor this frame will live on and
            # scale the rendered board to it. A lower in-game display resolution shrinks
            # the whole UI in step, and the tall champ-select panel can never spill off
            # the bottom of the screen again.
            if want_dock:
                _c, crect = client_rect()
                mon = (monitor_of((crect[0] + crect[2]) // 2, (crect[1] + crect[3]) // 2)
                       if crect else target_monitor())
            elif st["pos"]:
                mon = monitor_of(st["pos"][0], st["pos"][1])
            else:
                mon = target_monitor()
            base_s = ui_scale(pil.size, mon, extra_h=0 if want_dock else bar_h, docked=want_dock)
            st["auto_scale"] = base_s
            if want_dock:
                s = base_s
            else:
                s = min(base_s, st["user_scale"]) if st.get("user_scaled") else base_s
                s = max(MIN_UI_SCALE, s)
            disp = pil if s >= 0.999 else pil.resize(
                (max(1, round(pil.width * s)), max(1, round(pil.height * s))), Image.LANCZOS)
            ref = ImageTk.PhotoImage(disp)       # build on the Tk (main) thread
            label.configure(image=ref)
            st["ref"] = ref                      # keep a reference or it gets GC'd (blank image)
            st["hitmap"] = [(x0 * s, y0 * s, x1 * s, y1 * s, u)   # click rects follow the scale
                            for x0, y0, x1, y1, u in getattr(pil, "hitmap", [])]
            if want_dock and not st.get("dragged") and (not st["docked"] or st["size"] != disp.size):
                _dock(disp)                      # champ-select panel -> balanced left of the client
                st["size"] = None                # force re-place at the docked position
            elif not want_dock and st["docked"]:
                _undock()                        # board/loading frame -> back to normal centering
                st["size"] = None
            if st["size"] != disp.size:
                st["size"] = disp.size
                place(disp.size)
            make_no_activate(hwnd)               # keep the no-activate style (Tk can clear it)
            if not st["shown"]:
                show_no_activate(hwnd)           # reveal without taking focus
                st["shown"] = True
            # HARD GUARANTEE: never hold focus. If updating grabbed it, hand it right back.
            if prev_fg and prev_fg != hwnd and _user32.GetForegroundWindow() == hwnd:
                restore_foreground(prev_fg)
        if st["done"] and not dirty:             # worker finished (match over) -> close out
            close()
            return
        root.after(120, pump)

    root.after(50, pump)
    root.mainloop()
    # Force-release the process (and thus the single-instance mutex) immediately, even if a
    # background tip-generation thread is mid-flight - otherwise a lingering thread could keep
    # the mutex held and block the next launch.
    os._exit(0)


if __name__ == "__main__":
    main()
