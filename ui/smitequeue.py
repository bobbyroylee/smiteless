#!/usr/bin/env python3
"""smitequeue.py - the QUEUE CALL card: should you play this one?

Opens in the League LOBBY - the one moment the answer can still change anything - and
closes itself the instant you leave it (you queued, or you took the advice). It carries
one verdict and the evidence for it, all of it from your own ranked games (core/lolqueue).

Never steals focus (WS_EX_NOACTIVATE) and never covers the client: it docks off the
client's right edge, falling back to the bottom-right of the primary display.

    python ui/smitequeue.py              # live (lobby only)
    python ui/smitequeue.py test         # render now, whatever the phase, and stay up
    python ui/smitequeue.py test stop    # ... on a fixture that forces stop|wait|last
"""
import os
import sys
import time
import threading
import ctypes

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_R, _d))
for _s in ("stdout", "stderr"):                 # pythonw / bundled exe: no console
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass

import smiteskin as skin
import smiteconfig as cfg
import lolqueue as lq
import lolfix as lf                              # THE ONE FIX — the leak worth this game
import smiteoverlay as ov                        # win32 window helpers (the canonical copy)
import phasecheck
from smitei18n import coach, t, tf

VOID, SURFACE, LINE, LINE_SOFT = skin.VOID, skin.SURFACE, skin.LINE, skin.LINE_SOFT
TXT, MUTED, FAINT, EMBER = skin.TXT, skin.MUTED, skin.FAINT, skin.EMBER
GOOD, BAD, WARN, INFO = skin.GOOD, skin.BAD, skin.WARN, skin.INFO

W = 400                                          # card width, px (before Tk DPI scaling)
GRACE = 6.0                                      # seconds before a non-lobby phase may close us
MAX_LIFE = 8 * 60                                # never linger longer than this
TONE = {"bad": BAD, "soft": WARN, "good": GOOD}
VERDICT_COLOR = {"STOP": BAD, "WAIT": WARN, "LAST ONE": WARN, "GO": GOOD}
_k32 = ctypes.windll.kernel32


def _single_instance():
    _k32.CreateMutexW(None, False, "Global\\SmitelessQueue")
    return _k32.GetLastError() != 183            # ERROR_ALREADY_EXISTS


def _place(root):
    """Dock off the RIGHT edge of the League client (vertically centred), else bottom-right
    of the primary display. Never overlaps the client - the Find Match button stays clear."""
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    _hwnd, rect = ov.client_rect()
    if rect:
        l, t, r, b = rect
        mon = ov.monitor_of((l + r) // 2, (t + b) // 2)
        x, y = r + 8, t + max(0, (b - t - h) // 2)
        if x + w > mon[2]:                       # no room to the right -> left of the client
            x = max(mon[0], l - w - 8)
    else:
        mon = ov.monitors()[0]
        x, y = mon[2] - w - 24, mon[3] - h - 64
    root.geometry(f"+{int(x)}+{int(y)}")


def _row(parent, text, font, fg, pad=(0, 0), wrap=None):
    import tkinter as tk
    lb = tk.Label(parent, text=text, bg=SURFACE, fg=fg, font=font, justify="left", anchor="w")
    if wrap:
        lb.config(wraplength=wrap)
    lb.pack(fill="x", padx=14, pady=pad)
    return lb


def main():
    args = [a.lower() for a in sys.argv[1:]]
    test = "test" in args
    demo_kind = next((a for a in args if a in ("stop", "wait", "last")), None)
    if not test:
        if not cfg.load().get("queue_call", True):
            lq.log("queue call disabled in settings")
            return
        if not _single_instance():
            lq.log("a queue call is already up")
            return
    import tkinter as tk

    lq.log("queue call opening")
    root = tk.Tk()
    cfg.watch_tray(root)                         # dies with the tray, like every other surface
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.97)
    root.configure(bg=LINE)                      # 1px hairline via padding
    root.geometry("1x1+-4000+-4000")             # park off-screen until the first paint

    rail = tk.Frame(root, bg=FAINT, width=skin.RAIL)
    rail.pack(side="left", fill="y", padx=(1, 0), pady=1)
    body = tk.Frame(root, bg=SURFACE)
    body.pack(side="left", fill="both", expand=True, padx=(0, 1), pady=1)

    hdr = tk.Frame(body, bg=SURFACE)
    hdr.pack(fill="x", padx=12, pady=(8, 2))
    tk.Label(hdr, text=skin.BRAND_MARK, bg=SURFACE, fg=EMBER,
             font=skin.display(skin.SMALL, bold=True)).pack(side="left")
    tk.Label(hdr, text=" SMITELESS", bg=SURFACE, fg=TXT,
             font=skin.display(skin.SMALL, bold=True)).pack(side="left")
    tk.Label(hdr, text=" " + t("QUEUE CALL"), bg=SURFACE, fg=MUTED,
             font=skin.display(skin.SMALL)).pack(side="left")
    close = tk.Label(hdr, text="✕", bg=SURFACE, fg=FAINT, cursor="hand2",
                     font=skin.body(9, bold=True))
    close.pack(side="right")
    close.bind("<Enter>", lambda e: close.config(fg=TXT))
    close.bind("<Leave>", lambda e: close.config(fg=FAINT))

    tk.Frame(body, bg=LINE_SOFT, height=1).pack(fill="x", padx=12, pady=(4, 6))
    content = tk.Frame(body, bg=SURFACE)
    content.pack(fill="both", expand=True, pady=(0, 10))
    _row(content, t("reading your ranked games…"),
         skin.body(skin.BODY), MUTED, pad=(2, 8))

    st = {"alive": True, "born": time.time(), "misses": 0}

    def bye(*_a):
        if st["alive"]:
            st["alive"] = False
            lq.log("queue call closed")
            try:
                root.destroy()
            except Exception:
                pass
    close.bind("<Button-1>", bye)
    root.bind("<Escape>", bye)
    root.bind("<Button-1>", bye)                 # click anywhere to dismiss

    def render(r):
        for ch in content.winfo_children():
            ch.destroy()
        col = VERDICT_COLOR.get(r["verdict"], MUTED)
        rail.config(bg=col)
        _row(content, t(r["verdict"]), skin.display(21, bold=True), col, pad=(0, 0))
        _row(content, r["headline"], skin.display(13), TXT, pad=(0, 3))
        if r["sub"]:
            _row(content, coach(r["sub"]), skin.body(skin.SMALL), MUTED, pad=(0, 6), wrap=W - 40)
        tk.Frame(content, bg=LINE_SOFT, height=1).pack(fill="x", padx=14, pady=(2, 6))
        _row(content, lq.session_line(r["session"]), skin.body(skin.SMALL, bold=True),
             TXT, pad=(0, 2))
        for ln in r["lines"]:
            _row(content, "· " + ln["text"], skin.body(skin.SMALL),
                 TONE.get(ln["tone"], MUTED), pad=(0, 1), wrap=W - 44)
        # THIS GAME — one habit to hold yourself to, from THE ONE FIX. Only ever under a
        # verdict that's telling you to play; lolfix.lobby_card enforces that, not this.
        fx = lf.lobby_card(r.get("fix"), r["verdict"])
        if fx:
            tk.Frame(content, bg=LINE_SOFT, height=1).pack(fill="x", padx=14, pady=(7, 6))
            _row(content, t("THIS GAME"), skin.display(skin.SMALL, bold=True), EMBER, pad=(0, 2))
            _row(content, fx["line"], skin.body(skin.BODY), TXT, pad=(0, 2), wrap=W - 40)
            _row(content, fx["sub"], skin.body(8), FAINT, pad=(0, 2), wrap=W - 40)
        if r["n"]:
            _row(content, tf("from your last {games} ranked games", games=r["n"]),
                 skin.body(8), FAINT,
                 pad=(4, 0))
        root.update_idletasks()                  # labels must settle before they can be measured
        root.geometry(f"{W}x{body.winfo_reqheight() + 2}")
        _place(root)
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        ov.make_no_activate(hwnd, topmost=True)
        ov.show_no_activate(hwnd, topmost=True)
        lq.log(f"verdict {r['verdict']} ({r['headline']}) from {r['n']} games")

    def work():
        try:
            r = lq.call(lq.demo(demo_kind) if demo_kind else lq.history())
        except Exception as e:
            lq.log(f"call failed: {type(e).__name__}: {e}")
            r = {"verdict": "GO", "headline": t("QUEUE IT"), "n": 0, "lines": [],
                 "sub": t("couldn't read your match history — no call this time."),
                 "session": {}, "base": 0}
        try:                                     # the leak board is a bonus on this card —
            r["fix"] = lf.board(lf.demo("priced") if test else None)
        except Exception as e:                   # ... never a reason the verdict doesn't show
            lq.log(f"leak board failed: {type(e).__name__}: {e}")
            r["fix"] = None
        if st["alive"]:
            root.after(0, lambda: render(r))
    threading.Thread(target=work, daemon=True).start()

    def watch():
        """Close as soon as the lobby is behind you. Two straight non-lobby reads (and never
        inside the first few seconds) - the phase file the tray watcher acts on is a tick
        stale, so a single miss right after spawn means nothing."""
        while st["alive"]:
            time.sleep(3)
            if time.time() - st["born"] > MAX_LIFE:
                lq.log("queue call timed out")
                break
            try:
                ph = phasecheck.phase()
            except Exception:
                continue
            if ph == "Lobby":
                st["misses"] = 0
                continue
            if time.time() - st["born"] < GRACE:
                continue
            st["misses"] += 1
            if st["misses"] >= 2:
                lq.log(f"phase left the lobby ({ph or 'client gone'})")
                break
        try:
            root.after(0, bye)
        except Exception:
            pass
    if not test:
        threading.Thread(target=watch, daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()
