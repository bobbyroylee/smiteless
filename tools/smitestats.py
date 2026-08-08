#!/usr/bin/env python3
"""smitestats.py - how many people actually run Smiteless.

There's no server and no telemetry: every INSTALLED copy auto-downloads each release from
GitHub (the updater), so a release's SmitelessSetup.exe download count is a head-count of
the installs that were alive when it shipped. This window pulls the public GitHub API and
shows downloads per release - read "recent releases' downloads" as ~active users, and the
all-time total as cumulative installs+updates. Anonymous by design: GitHub only exposes
counts, never who.

  python tools/smitestats.py     (or SmitelessApp.exe stats / tray -> Usage stats)
"""
import sys, os, json, ssl, threading, urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
from smitei18n import t
for _s in ("stdout", "stderr"):
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass

API = "https://api.github.com/repos/bobbyroylee/smiteless/releases?per_page=30"
BG = "#11131a"; PANEL = "#171a24"; GOLD = "#c8aa6e"; TXT = "#d8d6cf"; MUTED = "#8b897f"
GREEN = "#5fc47a"


def fetch():
    """[(tag, downloads, published)] newest first, or None on network failure."""
    try:
        req = urllib.request.Request(API, headers={"User-Agent": "Smiteless-Stats",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as r:
            rels = json.load(r)
    except Exception:
        return None
    out = []
    for rel in rels:
        n = sum(a.get("download_count", 0) for a in rel.get("assets", [])
                if a.get("name", "").lower().startswith("smitelesssetup"))
        out.append((rel.get("tag_name", "?"), n, (rel.get("published_at") or "")[:10]))
    return out


def main():
    import tkinter as tk
    root = tk.Tk()
    root.title(f"Smiteless — {t('Usage stats')}")
    root.configure(bg=BG)
    root.minsize(430, 380)
    tk.Label(root, text=t("USAGE"), bg=BG, fg=GOLD, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
    tk.Label(root, text=t("Every install auto-downloads each release, so a recent release's\ndownload count ≈ how many active installs existed when it shipped."),
             bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="left").pack(anchor="w", padx=16, pady=(2, 8))
    head = tk.Label(root, text=t("loading from GitHub…"), bg=BG, fg=TXT, font=("Segoe UI", 11, "bold"))
    head.pack(anchor="w", padx=16)
    box = tk.Frame(root, bg=PANEL)
    box.pack(fill="both", expand=True, padx=14, pady=(8, 14))

    def show(rows):
        for w in box.winfo_children():
            w.destroy()
        if rows is None:
            head.config(text=t("couldn't reach GitHub — try again later"))
            return
        total = sum(n for _t, n, _p in rows)
        recent = [n for _t, n, _p in rows[1:5] if n > 0]        # latest may still be rolling out
        est = max(recent) if recent else (rows[0][1] if rows else 0)
        head.config(text=f"≈ {est} active installs   ·   {total} downloads all-time")
        hdr = tk.Frame(box, bg=PANEL)
        hdr.pack(fill="x", padx=12, pady=(10, 2))
        for txt, w_, anch in (("RELEASE", 12, "w"), ("DATE", 12, "w"), ("DOWNLOADS", 10, "e")):
            tk.Label(hdr, text=t(txt), width=w_, anchor=anch, bg=PANEL, fg=GOLD,
                     font=("Segoe UI", 8, "bold")).pack(side="left")
        for tag, n, pub in rows[:14]:
            row = tk.Frame(box, bg=PANEL)
            row.pack(fill="x", padx=12)
            tk.Label(row, text=tag, width=12, anchor="w", bg=PANEL, fg=TXT,
                     font=("Consolas", 9)).pack(side="left")
            tk.Label(row, text=pub, width=12, anchor="w", bg=PANEL, fg=MUTED,
                     font=("Consolas", 9)).pack(side="left")
            tk.Label(row, text=str(n), width=10, anchor="e", bg=PANEL,
                     fg=GREEN if n else MUTED, font=("Consolas", 9, "bold")).pack(side="left")

    def work():
        rows = fetch()
        try:
            root.after(0, lambda: show(rows))
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
