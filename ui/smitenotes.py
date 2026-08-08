#!/usr/bin/env python3
"""smitenotes.py - the Patch Notes / What's New window.

Renders the localized changelog in a scrollable, read-only window. It reads the copy bundled
with the install (staged next to VERSION, so it matches the version you're running). English
sessions also pull the latest upstream CHANGELOG.md in the background; PT-BR sessions keep
the bundled translation and use English only when that translation is unavailable. Opened
from the tray ("Patch notes") or:

    SmitelessApp.exe notes      (frozen)   /   python ui/smitenotes.py   (dev)
"""
import sys
import os
import ssl
import threading
import urllib.request
import ctypes

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_R, _d))
for _s in ("stdout", "stderr"):                 # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass

import smiteskin as skin
from smitei18n import lang, t
# Duskfall tokens - see docs/UIDESIGN.md. No hex or font-family string may appear below;
# everything routes through skin.* so this window re-themes from one place.
VOID, SURFACE, LINE = skin.VOID, skin.SURFACE, skin.LINE
TXT, MUTED, INFO, EMBER = skin.TXT, skin.MUTED, skin.INFO, skin.EMBER
BODY = skin.BODY
RAW_URL = "https://raw.githubusercontent.com/bobbyroylee/smiteless/main/CHANGELOG.md"
_k32 = ctypes.windll.kernel32
_MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â†", "âˆ", "â‰", "âœ", "â˜", "â—",
                     "âŒ", "â™", "âš", "â‡", "â€¢")


def _single_instance():
    _k32.CreateMutexW(None, False, "Global\\SmitelessNotes")
    return _k32.GetLastError() != 183           # ERROR_ALREADY_EXISTS


def _install_root():
    try:
        import smiteupdate
        return smiteupdate.install_root()
    except Exception:
        return _R


def _repair_mojibake(text):
    """Undo one accidental UTF-8-as-Windows-1252 decode without touching valid Unicode."""
    repaired = []
    for line in text.splitlines(keepends=True):
        if not any(marker in line for marker in _MOJIBAKE_MARKERS):
            repaired.append(line)
            continue
        try:
            raw = bytearray()
            for char in line:
                codepoint = ord(char)
                # Some old changelog lines were decoded as a CP1252/Latin-1 mixture,
                # leaving undefined C1 bytes as U+0080..U+009F control characters.
                raw.extend(bytes((codepoint,)) if codepoint <= 0xFF
                           else char.encode("cp1252"))
            candidate = raw.decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            repaired.append(line)
            continue
        old_score = sum(line.count(marker) for marker in _MOJIBAKE_MARKERS)
        new_score = sum(candidate.count(marker) for marker in _MOJIBAKE_MARKERS)
        repaired.append(candidate if new_score < old_score else line)
    return "".join(repaired)


def _read_changelog(path, source_lang):
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read().strip()
        if text:
            return (_repair_mojibake(text) if source_lang == "en" else text), source_lang
    except (OSError, UnicodeError):
        pass
    return None


def _local_changelog(active_lang=None, roots=None):
    active_lang = active_lang or lang()
    roots = tuple(roots or (_install_root(), _R))
    candidates = ([("CHANGELOG.pt_BR.md", "pt_BR"), ("CHANGELOG.md", "en")]
                  if active_lang == "pt_BR" else [("CHANGELOG.md", "en")])
    for name, source_lang in candidates:
        for root in roots:
            result = _read_changelog(os.path.join(root, name), source_lang)
            if result:
                return result
    heading = "Notas da atualização" if active_lang == "pt_BR" else "Patch Notes"
    missing = ("nenhuma nota de atualização encontrada" if active_lang == "pt_BR"
               else "no patch notes found")
    return f"# Smiteless — {heading}\n\n({missing})", None


def _fetch_remote():
    try:
        req = urllib.request.Request(RAW_URL, headers={"User-Agent": "Smiteless-Notes"})
        with urllib.request.urlopen(req, timeout=6, context=ssl.create_default_context()) as r:
            return _repair_mojibake(r.read().decode("utf-8-sig"))
    except (OSError, UnicodeError):
        return None


def main():
    if not _single_instance():
        return
    import tkinter as tk

    root = tk.Tk()
    root.title(f"Smiteless — {t('Patch Notes')}")
    root.configure(bg=VOID)
    skin.dark_titlebar(root)
    root.geometry("560x680")
    try:
        for ico in (os.path.join(_R, "assets", "smiteless.ico"),
                    os.path.join(_install_root(), "assets", "smiteless.ico")):
            if os.path.exists(ico):
                root.iconbitmap(ico)
                break
    except Exception:
        pass

    _hdr = tk.Frame(root, bg=VOID)
    _hdr.pack(anchor="w", padx=16, pady=(14, 6))
    skin.brand_row(_hdr, t("Patch notes"), bg=VOID).pack(side="left")

    card = skin.card(root, rail=LINE)
    card.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    frame = card.body
    vbar = tk.Scrollbar(frame)
    vbar.pack(side="right", fill="y")
    txt = tk.Text(frame, bg=SURFACE, fg=TXT, relief="flat", bd=0, wrap="word", padx=14, pady=10,
                  yscrollcommand=vbar.set, font=skin.body(BODY), highlightthickness=0,
                  spacing1=1, spacing3=3, cursor="arrow")
    txt.pack(side="left", fill="both", expand=True)
    vbar.config(command=txt.yview)
    txt.tag_config("h1", foreground=EMBER, font=skin.display(15), spacing3=8)
    txt.tag_config("ver", foreground=EMBER, font=skin.display(13), spacing1=14, spacing3=4)
    txt.tag_config("bul", lmargin1=14, lmargin2=28, spacing3=5)
    txt.tag_config("b", font=skin.body(BODY, bold=True), foreground=TXT)
    txt.tag_config("dot", foreground=INFO, font=skin.body(BODY, bold=True))

    def _inline(s, base):
        """Insert a line, honoring **bold** segments; `base` is an extra tag on every run."""
        for i, seg in enumerate(s.split("**")):
            if not seg:
                continue
            tags = ([base] if base else [])
            if i % 2 == 1:                          # odd segments are between ** ** -> bold
                tags.append("b")
            txt.insert("end", seg, tuple(tags))

    def render(md):
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for line in md.splitlines():
            s = line.rstrip()
            if s.startswith("## "):
                txt.insert("end", s[3:] + "\n", "ver")
            elif s.startswith("# "):
                txt.insert("end", s[2:] + "\n", "h1")
            elif s.startswith("- "):
                txt.insert("end", "•  ", ("dot", "bul"))
                _inline(s[2:], "bul")
                txt.insert("end", "\n")
            elif not s:
                txt.insert("end", "\n")
            else:
                _inline(s, None)
                txt.insert("end", "\n")
        txt.config(state="disabled")

    active_lang = lang()
    local_md, source_lang = _local_changelog(active_lang)
    render(local_md)

    def _remote():
        md = _fetch_remote()
        if md and md.strip():
            root.after(0, lambda: render(md))       # GitHub copy may be newer than the bundled one
    # A translated PT-BR file is authoritative. Upstream English is only the fallback when
    # the translation is unavailable; English sessions still refresh to the latest notes.
    if active_lang == "en" or source_lang != "pt_BR":
        threading.Thread(target=_remote, daemon=True).start()

    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    main()
