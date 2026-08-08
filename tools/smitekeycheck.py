#!/usr/bin/env python3
"""smitekeycheck.py - on-launch Riot key freshness check.

Free dev keys die every 24h. The tray runs `SmitelessApp.exe keycheck` shortly after
startup: if a key file EXISTS but Riot now rejects it (401/403 on the status host - a
definitive verdict, not a network blip), a small prompt opens to paste a fresh one.
No key file at all = the user never set the scout up -> stay silent (it's optional).
Valid key / can't-tell (offline) -> exit silently.
"""
import sys, os, webbrowser

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
import lolscout as ls

BG = "#11131a"; PANEL = "#171a24"; GOLD = "#c8aa6e"; TXT = "#d8d6cf"; MUTED = "#8b897f"
GREEN = "#5fc47a"; RED = "#d46d78"; ENTRY = "#0d0f16"; BTN = "#262b3b"; BTN_A = "#333a52"
KEY_FILES = [os.path.expanduser("~/.riot_api_key"), os.path.expanduser("~/.riot_api_key.txt")]


def prompt(old_key):
    import tkinter as tk
    root = tk.Tk()
    root.title(f"Smiteless — {t('Riot key expired')}")
    root.configure(bg=BG)
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    wrap = tk.Frame(root, bg=BG)
    wrap.pack(padx=20, pady=16)
    tk.Label(wrap, text=t("Your Riot API key expired"), font=("Segoe UI", 12, "bold"),
             fg=GOLD, bg=BG).pack(anchor="w")
    tk.Label(wrap, text=t("Free dev keys stop working after 24 hours. Grab a fresh one\n(same login, one click) and paste it here — everything else keeps working\nwithout it, but ranks, match history and the scout need it."),
             font=("Segoe UI", 9), fg=MUTED, bg=BG, justify="left").pack(anchor="w", pady=(4, 10))
    row = tk.Frame(wrap, bg=BG)
    row.pack(fill="x")
    entry = tk.Entry(row, bg=ENTRY, fg=TXT, insertbackground=TXT, relief="flat",
                     font=("Consolas", 9), width=42)
    entry.pack(side="left", ipady=4)
    status = tk.Label(wrap, text=f"current key ...{old_key[-4:]} was rejected by Riot",
                      font=("Segoe UI", 8), fg=RED, bg=BG)
    status.pack(anchor="w", pady=(6, 8))

    def paste():
        try:
            entry.delete(0, "end")
            entry.insert(0, root.clipboard_get().strip())
        except Exception:
            status.config(text=t("clipboard is empty"), fg=RED)

    def save(_e=None):
        k = entry.get().strip()
        if not (k.startswith("RGAPI-") and len(k) >= 24):
            status.config(text=t("that doesn't look like an RGAPI-... key"), fg=RED)
            return
        for p in KEY_FILES:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(k)
            except Exception as e:
                status.config(text=f"save failed: {e}", fg=RED)
                return
        status.config(text=f"saved ...{k[-4:]} — you're set", fg=GREEN)
        root.after(900, root.destroy)

    btns = tk.Frame(wrap, bg=BG)
    btns.pack(anchor="e", fill="x")

    def mk(text, cmd, accent=False):
        return tk.Button(btns, text=text, command=cmd, bg=(GOLD if accent else BTN),
                         fg=(BG if accent else TXT), activebackground=(GOLD if accent else BTN_A),
                         activeforeground=(BG if accent else TXT), relief="flat", bd=0,
                         padx=12, pady=4, font=("Segoe UI", 9, "bold"), cursor="hand2")

    mk(t("Get key ↗"), lambda: webbrowser.open("https://developer.riotgames.com/")).pack(side="left")
    mk(t("Later"), root.destroy).pack(side="right", padx=(6, 0))
    mk(t("Save"), save, accent=True).pack(side="right", padx=(6, 0))
    mk(t("Paste"), paste).pack(side="right")
    entry.bind("<Return>", save)
    root.update_idletasks()
    root.eval("tk::PlaceWindow . center")
    root.mainloop()


def main():
    key = ls.read_key()
    if not key:
        return                                   # scout never set up -> not our business
    if ls.key_ok(key) is False:                  # DEFINITIVE rejection only (never on outages)
        prompt(key)


if __name__ == "__main__":
    main()
