#!/usr/bin/env python3
"""smiteless_main.py - single entry point for the bundled app.

One frozen exe (SmitelessApp.exe) covers every window/tool; the first CLI arg picks which:

    SmitelessApp.exe overlay        the scoreboard overlay (default)
    SmitelessApp.exe widget         the floating item widget
    SmitelessApp.exe dead           the fullscreen see-through DEATH BRIEF (while you're dead)
    SmitelessApp.exe load           the LOADING-SCREEN matchup overlay (champ tags + game plan)
    SmitelessApp.exe queue          the QUEUE CALL card (lobby only: should you play this one?)
    SmitelessApp.exe mute           AUTO-MUTE: /fullmute all when the game clock starts
    SmitelessApp.exe settings       the settings window
    SmitelessApp.exe phase <file>   write the LCU gameflow phase to <file> (for the tray watcher)
    SmitelessApp.exe autoaccept     auto-accept queue ready checks (when enabled)
    SmitelessApp.exe login <name>   one-click Riot login: swap to a saved account SESSION (no pw)
    SmitelessApp.exe accounts ...   saved-session admin (list / save <name> / remove <name>)
    SmitelessApp.exe fill <name>    one-click Riot login: autofill a saved username+PASSWORD
    SmitelessApp.exe logins ...     saved-login (password) admin (list / remove <name>)
    SmitelessApp.exe update [--apply]  check GitHub for a newer release (notify / one-click)
    SmitelessApp.exe selftest       dependency health check (dev)

The two ``__stt-*`` commands are private JSON workers. The frozen executable uses a
console-capable bootloader whose console is hidden before startup, allowing those workers to
retain pipe-based stdin/stdout without showing a window.

Kept tiny on purpose so PyInstaller has a clean root to analyse.
"""
import os
import sys

# Dev (not frozen): make the flat imports resolve from the source folders. When frozen,
# every module is bundled into the exe, so these inserts are harmless no-ops.
if not getattr(sys, "frozen", False):
    _R = os.path.dirname(os.path.abspath(__file__))
    for _d in ("core", "ui", "tools"):
        sys.path.insert(0, os.path.join(_R, _d))


for _s in ("stdout", "stderr"):                # pythonw / bundled exe: no console -> stdio is None
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass


def main():
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "overlay").lower()
    rest = sys.argv[2:]
    sys.argv = [sys.argv[0]] + rest                  # downstream sees only its own flags

    if cmd == "__stt-mic-worker":
        import smitemicworker
        raise SystemExit(smitemicworker.main())
    elif cmd == "__stt-whisper-worker":
        import smitewhisperworker
        raise SystemExit(smitewhisperworker.main())
    elif cmd == "overlay":
        import smiteoverlay
        smiteoverlay.main()
    elif cmd == "widget":
        import smitewidget
        smitewidget.main()
    elif cmd == "dead":
        import smitedead
        smitedead.main()
    elif cmd == "load":
        import smiteload
        smiteload.main()
    elif cmd == "settings":
        import smitesettings
        smitesettings.main()
    elif cmd == "profile":
        import smiteprofile
        smiteprofile.main()
    elif cmd == "notes":
        import smitenotes
        smitenotes.main()
    elif cmd == "queue":
        import smitequeue
        smitequeue.main()
    elif cmd == "mute":
        import lolmute
        lolmute.main()
    elif cmd == "coach":
        import smitecoach
        raise SystemExit(smitecoach.main(rest))
    elif cmd == "phase":
        import tempfile
        import phasecheck
        out = rest[0] if rest else os.path.join(tempfile.gettempdir(), "smiteless_phase.txt")
        try:
            # DETAILED: the loading screen reports as 'Loading', so the AHK watcher can open
            # the loading scout there while holding the in-game widget back until the match
            # actually starts (see phasecheck.phase_detailed).
            with open(out, "w", encoding="utf-8") as f:
                f.write(phasecheck.phase_detailed() or "")
        except Exception:
            pass
    elif cmd == "autoaccept":
        import lolautoaccept
        lolautoaccept.main()
    elif cmd == "login":
        import lolaccounts
        lolaccounts.main(["login", *rest])
    elif cmd == "accounts":
        import lolaccounts
        lolaccounts.main(rest)
    elif cmd == "fill":
        import lolcreds
        lolcreds.main(["fill", *rest])
    elif cmd == "logins":
        import lolcreds
        lolcreds.main(rest)
    elif cmd == "stats":
        import smitestats
        smitestats.main()
    elif cmd == "keycheck":
        import smitekeycheck
        smitekeycheck.main()
    elif cmd == "update":
        import smiteupdate
        smiteupdate.main(rest)
    elif cmd == "selftest":
        import selftest
        selftest.main()
    else:
        sys.stderr.write("usage: SmitelessApp.exe [overlay|widget|dead|load|queue|mute|coach|settings|"
                         "phase|autoaccept|login <name>|accounts|fill <name>|logins|update|"
                         "selftest]\n")


if __name__ == "__main__":
    main()
