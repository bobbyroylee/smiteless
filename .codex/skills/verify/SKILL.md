---
name: verify
description: Execute and visually validate Smiteless changes on Windows. Use after modifying Python application code, Tk/Pillow overlays, AutoHotkey scripts, builds, or user-visible UI; use before committing or releasing when verification evidence is needed.
---

# Verify Smiteless

Run the smallest relevant checks first, then perform the full health check before handoff for Python, data-source, or rendering changes.

## Baseline checks

- Run `python tools\selftest.py`. It includes the tag and glyph guards; some live-service checks can skip if League, a Riot key, or the Claude CLI is unavailable.
- Run a focused entry point when the change is surface-specific:

  ```powershell
  python ui\smitesettings.py
  python ui\smiteprofile.py
  python smiteless_main.py <overlay|widget|settings|profile|phase|login|accounts> ...
  ```

- Validate player tags with `python tools\tagcheck.py` and glyph rendering with `python tools\glyphcheck.py` when the change affects their rules or rendered text.

## UI and overlay evidence

- Render UI changes with real data and inspect the resulting PNG or the actual Tk surface. Do not treat a successful script alone as visual verification.
- Find Tk windows by title. To inspect an occluded window, use `PrintWindow(PW_RENDERFULLCONTENT)` with `GetDIBits`.
- Do not use `SetForegroundWindow` or `SetCursorPos`: the user may be playing fullscreen. For a required Tk interaction, send synthetic `WM_LBUTTONDOWN` and `WM_LBUTTONUP` with `PostMessage` at client coordinates.
- Keep the DraftBoard scoreboard horizontal: teams are side by side in `.scoutcols` and collapse to one column only on phones.

## AutoHotkey and frozen builds

Validate an AHK v2 script from PowerShell so the validator's exit code is preserved:

```powershell
$ahk = "$env:LOCALAPPDATA\Programs\AutoHotkey\v2\AutoHotkey64.exe"
Start-Process $ahk -ArgumentList '/ErrorStdOut','/Validate','<script>.ahk' -Wait -PassThru -NoNewWindow
```

Build a frozen artifact with `powershell -ExecutionPolicy Bypass -File dist\build.ps1`, then run `build\pyi\SmitelessApp\SmitelessApp.exe <command>` to verify what ships.

## Safety

Do not drive destructive live paths: anything that kills Riot/League clients (`lolaccounts.switch`) or sends LCU POST requests during queue. Test engine functions and refusal paths instead.

Before an app release, update `CHANGELOG.md`, run the self-test, and use `dist\make-release.ps1`. Do not create an app release for web-only DraftBoard or dev-tray changes.
