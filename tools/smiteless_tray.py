#!/usr/bin/env python3
"""smiteless_tray.py - the persistent Smiteless tray app, pure Python (replaces the AHK).

A system-tray icon + right-click menu (Open overlay / Settings / Auto-open / Start with
Windows / Quit), a global Ctrl+Alt+X hotkey (native Win32 RegisterHotKey), and the
champ-select auto-open watcher. The overlay and settings windows are launched as separate
single-instance Python processes.

Run with pythonw.exe so there's no console window. Needs: pip install pystray pillow.
"""
import sys, os, threading, subprocess, ctypes
from ctypes import wintypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import smiteconfig as cfg
import phasecheck
import lolcoachipc
from smitei18n import t

HERE = os.path.dirname(os.path.abspath(__file__))
_pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
PYW = _pyw if os.path.exists(_pyw) else sys.executable        # windowless launcher
OVERLAY = os.path.join(_ROOT, "ui", "smiteoverlay.py")
SETTINGS = os.path.join(_ROOT, "ui", "smitesettings.py")
MAIN = os.path.join(_ROOT, "smiteless_main.py")
ICON = os.path.join(_ROOT, "assets", "smiteless.ico")
CREATE_NO_WINDOW = 0x08000000

_k32 = ctypes.windll.kernel32
_u32 = ctypes.windll.user32
_stop = threading.Event()


def _single_instance():
    # use_last_error so GetLastError is read reliably (a plain ctypes call can clobber it,
    # which let duplicate instances start)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW(None, False, "Global\\SmitelessTray")
    return ctypes.get_last_error() != 183        # ERROR_ALREADY_EXISTS


def _launch(script, *args):
    try:
        subprocess.Popen([PYW, script, *args], creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def open_overlay(auto=False):
    _launch(OVERLAY, *(["--wait"] if auto else []))


def open_settings():
    _launch(SETTINGS)


def open_coach():
    _launch(MAIN, "coach", "show")


def hide_coach():
    _launch(MAIN, "coach", "hide")


def ask_coach():
    _launch(MAIN, "coach", "toggle")


def _shutdown_coach():
    endpoint = lolcoachipc.read_endpoint()
    if endpoint and endpoint.get("token"):
        _launch(MAIN, "coach", "shutdown", f"--endpoint-token={endpoint['token']}")


def _wait_for_process(pid, timeout_ms=7000):
    """Wait for the replaced tray to release its mutex without killing an unknown PID."""
    try:
        open_process = _k32.OpenProcess
        open_process.restype = wintypes.HANDLE
        handle = open_process(0x00100000, False, int(pid))  # SYNCHRONIZE
        if handle:
            _k32.WaitForSingleObject(handle, int(timeout_ms))
            _k32.CloseHandle(handle)
    except Exception:
        pass


def quit_tray(icon):
    _stop.set()
    _shutdown_coach()
    icon.stop()


def reload_tray(icon):
    _stop.set()
    _shutdown_coach()
    _launch(os.path.abspath(__file__), "--reload-wait", str(os.getpid()))
    icon.stop()


# ---------- auto-open watcher (polls the phase in-process every 2s) ----------
def _watcher():
    opened = False
    while not _stop.is_set():
        ph = phasecheck.phase()
        if cfg.auto_open_enabled():
            # the overlay now opens the moment the QUEUE starts (it shows the queue
            # card and warms up), not just at champ select
            active = ph in ("Matchmaking", "ReadyCheck", "ChampSelect",
                            "GameStart", "InProgress", "Reconnect")
            if active and not opened:
                opened = True
                open_overlay(auto=True)
            elif not active:
                opened = False                   # any non-active phase re-arms for next game
        else:
            opened = False
        if ph == "ReadyCheck":
            # the auto-accept SETTING existed but nothing ever polled it — the tray is
            # the always-running process, so it owns the accept now
            try:
                import lolautoaccept
                lolautoaccept.try_accept()
            except Exception:
                pass
        _stop.wait(2)


# ---------- global hotkey: Ctrl+Alt+X (native, like AHK uses) ----------
def _hotkey():
    MOD_ALT, MOD_CONTROL, VK_X, VK_C, WM_HOTKEY = 0x0001, 0x0002, 0x58, 0x43, 0x0312
    if not _u32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL, VK_X):
        return                                   # another app owns it (e.g. an old AHK tray)
    coach_registered = bool(_u32.RegisterHotKey(None, 2, MOD_ALT | MOD_CONTROL, VK_C))
    try:
        msg = wintypes.MSG()
        while not _stop.is_set():
            r = _u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                if msg.wParam == 2:
                    ask_coach()
                else:
                    open_overlay(False)
    finally:
        _u32.UnregisterHotKey(None, 1)
        if coach_registered:
            _u32.UnregisterHotKey(None, 2)


def main(replace_pid=None):
    if replace_pid:
        _wait_for_process(replace_pid)
    if not _single_instance():
        return
    import pystray
    from PIL import Image

    threading.Thread(target=_watcher, daemon=True).start()
    threading.Thread(target=_hotkey, daemon=True).start()
    _launch(MAIN, "coach", "serve", "--owner-pid", str(os.getpid()))

    try:
        img = Image.open(ICON)
    except Exception:
        img = Image.new("RGB", (64, 64), (20, 23, 32))

    def toggle_autoopen(icon, item):
        cfg.set_auto_open(not cfg.auto_open_enabled())
        icon.update_menu()

    def toggle_autostart(icon, item):
        cfg.set_autostart(not cfg.autostart_enabled())
        icon.update_menu()

    def _login_items():
        # rebuilt each time the menu opens; one item per saved Riot session
        try:
            import lolaccounts as la
            names = [a["name"] for a in la.list_accounts()]
        except Exception:
            names = []
        if not names:
            return [pystray.MenuItem(t("Set up in Settings…"), lambda icon, item: open_settings())]
        main_py = os.path.join(_ROOT, "smiteless_main.py")
        return [pystray.MenuItem(n, (lambda nm: lambda icon, item: _launch(main_py, "login", nm))(n))
                for n in names]

    menu = pystray.Menu(
        pystray.MenuItem(t("Open overlay"), lambda icon, item: open_overlay(False), default=True),
        pystray.MenuItem(t("Coach"), lambda icon, item: open_coach()),
        pystray.MenuItem(t("Ask coach"), lambda icon, item: ask_coach()),
        pystray.MenuItem(t("Hide coach"), lambda icon, item: hide_coach()),
        pystray.MenuItem(t("Riot login"), pystray.Menu(_login_items)),
        pystray.MenuItem(t("Settings…"), lambda icon, item: open_settings()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("Auto-open (queue → game)"), toggle_autoopen,
                         checked=lambda item: cfg.auto_open_enabled()),
        pystray.MenuItem(t("Start with Windows"), toggle_autostart,
                         checked=lambda item: cfg.autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("Reload"), lambda icon, item: reload_tray(icon)),
        pystray.MenuItem(t("Quit"), lambda icon, item: quit_tray(icon)),
    )
    icon = pystray.Icon("smiteless", img, "Smiteless", menu)
    icon.run()
    _stop.set()


if __name__ == "__main__":
    old_pid = None
    if len(sys.argv) == 3 and sys.argv[1] == "--reload-wait":
        try:
            old_pid = int(sys.argv[2])
        except ValueError:
            old_pid = None
    main(replace_pid=old_pid)
