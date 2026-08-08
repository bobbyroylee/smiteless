#!/usr/bin/env python3
"""smiteupdate.py - notify + one-click updater.

On launch the tray runs `SmitelessApp.exe update`. This checks the GitHub Releases API for
a newer version than the local VERSION file; if there is one, it shows a small window with
an Update button. Clicking Update downloads that release's SmitelessSetup.exe and runs it
(the installer closes the running app, lays the new files down, and relaunches). If we're
up to date or offline, it exits silently.
"""
import os
import sys
import json
import ssl
import tempfile
import subprocess
import urllib.request

REPO = "bobbyroylee/smiteless"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
UA = "Smiteless-Updater"

# Duskfall skin, guarded: the updater must never die over cosmetics. Frozen builds bundle
# smiteskin; dev runs get core/ inserted here; if anything fails, a frozen fallback of the
# same tokens keeps the dialogs correct.
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
    import smiteskin as skin
    from smitei18n import t
except Exception:
    t = lambda msgid: msgid
    class skin:
        VOID = "#0c0a13"; TXT = "#e8e3f4"; MUTED = "#9a92b4"
        EMBER = "#ffb454"; EMBER_DEEP = "#c77f2e"; RAISED = "#1e1930"; HOVER = "#2a2342"

        @staticmethod
        def display(size, bold=False):
            return ("Bahnschrift", size, "bold") if bold else ("Bahnschrift", size)

        @staticmethod
        def body(size=10, bold=False):
            return ("Segoe UI", size, "bold") if bold else ("Segoe UI", size)

        @staticmethod
        def dark_titlebar(root):
            pass


def install_root():
    """The folder that holds VERSION + Smiteless.exe. Frozen layout: <root>/app/SmitelessApp.exe."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ -> repo root


def local_version():
    try:
        with open(os.path.join(install_root(), "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"


def _vtuple(s):
    s = (s or "").lstrip("vV").strip()
    out = []
    for part in s.split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out or [0])


def latest_release():
    """(tag, setup_download_url) for the newest release, or None."""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(API, headers={"User-Agent": UA,
                                                    "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
            d = json.load(r)
    except Exception:
        return None
    tag = d.get("tag_name")
    url = None
    for a in d.get("assets", []):
        if a.get("name", "").lower() == "smitelesssetup.exe":
            url = a.get("browser_download_url")
            break
    return (tag, url) if tag and url else None


def _download(url, dest, on_progress=None):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r, open(dest, "wb") as f:
        total = 0
        try:
            total = int(r.headers.get("Content-Length", "0") or "0")
        except Exception:
            total = 0
        done = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)


def _run_setup(cur, tag, url, with_progress=False):
    prog = None
    update_text = None
    update_bar = None

    if with_progress:
        try:
            import tkinter as tk
            from tkinter import ttk
            prog = tk.Tk()
            prog.title(t("Smiteless update"))
            prog.configure(bg=skin.VOID)
            skin.dark_titlebar(prog)
            prog.resizable(False, False)
            try:
                prog.attributes("-topmost", True)
            except Exception:
                pass
            frm = tk.Frame(prog, bg=skin.VOID)
            frm.pack(padx=18, pady=14)
            tk.Label(frm, text=t("Updating to {tag}").format(tag=tag), fg=skin.EMBER, bg=skin.VOID,
                     font=skin.display(11, bold=True)).pack(anchor="w")
            update_text = tk.StringVar(value="Preparing update...")
            tk.Label(frm, textvariable=update_text, fg=skin.TXT, bg=skin.VOID,
                     font=skin.body(9)).pack(anchor="w", pady=(4, 8))
            update_bar = ttk.Progressbar(frm, orient="horizontal", mode="determinate", length=320, maximum=100)
            update_bar.pack(fill="x")
            prog.update_idletasks()
            prog.eval("tk::PlaceWindow . center")
            prog.update()
        except Exception:
            prog = None
            update_text = None
            update_bar = None

    def _set_status(msg, pct=None):
        if not prog:
            return
        try:
            if update_text is not None:
                update_text.set(msg)
            if update_bar is not None:
                if pct is None:
                    update_bar.config(mode="indeterminate")
                    update_bar.start(20)
                else:
                    update_bar.stop()
                    update_bar.config(mode="determinate")
                    update_bar["value"] = max(0, min(100, pct))
            prog.update_idletasks()
            prog.update()
        except Exception:
            pass

    setup = os.path.join(tempfile.gettempdir(), "SmitelessSetup.exe")
    try:
        _set_status("Downloading installer...", 0)
        _download(url, setup, on_progress=lambda done, total: _set_status(
            f"Downloading installer... {int(done * 100 / total)}%" if total > 0 else "Downloading installer...",
            (done * 100 / total) if total > 0 else None))
    except Exception:
        if prog:
            try:
                prog.destroy()
            except Exception:
                pass
        return False
    # /upgrade tells the installer to close the running app, overwrite, and relaunch silently
    _set_status("Starting installer...", None)
    subprocess.Popen([setup, "/upgrade"], close_fds=True)
    if prog:
        _set_status("Installer started. Smiteless will relaunch when done.", 100)
        try:
            prog.after(1200, prog.destroy)
            prog.mainloop()
        except Exception:
            pass
    return True


def _dialog(cur, tag, url):
    import tkinter as tk
    root = tk.Tk()
    root.title(t("Smiteless update"))
    root.configure(bg=skin.VOID)
    skin.dark_titlebar(root)
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    wrap = tk.Frame(root, bg=skin.VOID)
    wrap.pack(padx=18, pady=16)
    tk.Label(wrap, text=t("A new version of Smiteless is available"),
             font=skin.display(12, bold=True), fg=skin.EMBER, bg=skin.VOID).pack(anchor="w")
    tk.Label(wrap, text=t("You have {current}.  Latest is {latest}.").format(current=cur, latest=tag),
             font=skin.body(9), fg=skin.TXT, bg=skin.VOID).pack(anchor="w", pady=(4, 12))
    btns = tk.Frame(wrap, bg=skin.VOID)
    btns.pack(anchor="e")

    def do_update():
        later_btn.configure(state="disabled")
        update_btn.configure(state="disabled")
        ok = _run_setup(cur, tag, url, with_progress=True)
        root.destroy()
        if not ok:
            try:
                import tkinter.messagebox as mb
                mb.showerror("Smiteless", "Couldn't download the update. Try again later.")
            except Exception:
                pass
        else:
            _info("Update started. Smiteless will restart automatically when installation finishes.")

    later_btn = tk.Button(btns, text=t("Later"), width=10, command=root.destroy,
                          bg=skin.RAISED, fg=skin.TXT, activebackground=skin.HOVER,
                          relief="flat", font=skin.body(9))
    later_btn.pack(side="right", padx=(8, 0))
    update_btn = tk.Button(btns, text=t("Update now"), width=12, command=do_update,
                           bg=skin.EMBER, fg=skin.VOID, activebackground=skin.EMBER_DEEP,
                           relief="flat", font=skin.body(9, bold=True))
    update_btn.pack(side="right")
    root.update_idletasks()
    root.eval("tk::PlaceWindow . center")
    root.mainloop()


def _info(msg):
    try:
        import tkinter as tk
        import tkinter.messagebox as mb
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        mb.showinfo("Smiteless", msg)
        r.destroy()
    except Exception:
        pass


def main(args=None):
    args = args or []
    # --check <file>: write the newer version (or empty) to <file>, no GUI. The tray polls
    # this in the background and pops a balloon notification when something is available.
    if "--check" in args:
        i = args.index("--check")
        out = (args[i + 1] if i + 1 < len(args)
               else os.path.join(tempfile.gettempdir(), "smiteless_update.txt"))
        rel = latest_release()
        ver = rel[0] if (rel and _vtuple(rel[0]) > _vtuple(local_version())) else ""
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(ver)
        except Exception:
            pass
        return
    force = "--force" in args                     # manual "Check for updates" -> always give feedback
    cur = local_version()
    rel = latest_release()
    if not rel:
        if force:
            _info("Couldn't reach the update server. Check your internet and try again.")
        return                                    # offline / no release -> silent otherwise
    tag, url = rel
    if _vtuple(tag) <= _vtuple(cur):
        if force:
            _info(f"You're on the latest version ({cur}).")
        return                                     # up to date
    if "--apply" in args:                          # headless apply (no prompt)
        _run_setup(cur, tag, url, with_progress=False)
    else:
        _dialog(cur, tag, url)


if __name__ == "__main__":
    main(sys.argv[1:])
