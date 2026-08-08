# Repository Guidelines

## Project Structure & Module Organization

Smiteless is a Windows League companion built with Python, Tk, Pillow, and AutoHotkey v2. `smiteless_main.py` is the application entry point; `smiteless.ahk` starts the desktop experience. Keep game/data logic in `core/` (for example, `lolbuild.py`), Tk surfaces in `ui/`, and checks in `tools/`. Installer and release scripts live in `dist/`; assets are in `assets/`; specifications and DraftBoard content are in `docs/`.

## Build, Test, and Development Commands

- `python -m pip install -r requirements.txt` installs runtime dependencies.
- `python tools\selftest.py` runs the health check, including tag, glyph, and queue-call fixtures. Some live-service checks may be skipped when League, a Riot key, or the Claude CLI is unavailable.
- `python tools\tagcheck.py` validates player tags against `docs/TAGS.md`.
- `python tools\glyphcheck.py` detects unsupported glyph rendering.
- `powershell -ExecutionPolicy Bypass -File dist\build.ps1` creates `build\SmitelessSetup.exe`; it requires PyInstaller, AutoHotkey v2, and Ahk2Exe on Windows.

## Coding Style & Naming Conventions

Use four-space Python indentation and standard-library-first imports. Modules use lowercase `lol*.py` and `smite*.py` names; functions and variables use `snake_case`, classes `PascalCase`, and constants `UPPER_SNAKE_CASE`. Preserve flat imports (`core`, `ui`, and `tools` are added to `sys.path`). Keep network/UI failures recoverable with diagnostics.

## Testing Guidelines

Run `python tools\selftest.py` before handing off Python, data-source, or rendering changes. Add or update deterministic fixtures for tag rules or queue verdict logic. For visuals, inspect a PNG or actual Tk surface; a passing script is insufficient. Keep DraftBoard side-by-side in `docs/draft/index.html`.

## Product and Configuration Invariants

Do not regress these behaviors: grades measure in-game performance only; tags distinguish this-game from account evidence under `docs/TAGS.md`; and DraftBoard links remain short (`/draft/#d=<id>`). Keep `DEFAULT_DB` synchronized with `loldraft._DEFAULT_PAGE_DB`. Never commit Riot keys, credentials, or local configuration.

## Commit & Pull Request Guidelines

Recent commits use concise imperative summaries, such as `Loading board: make the splash art an actual banner`; releases use `Release v0.9.49`. Keep commits narrowly scoped. PRs should state the user-visible outcome, testing performed, and linked issue when applicable; include screenshots for UI or DraftBoard changes. Do not make an app release for docs-only or dev-tray work. Release only coherent, user-visible batches: add the `CHANGELOG.md` entry, run the self-test, then use `dist\make-release.ps1 -Version X.Y.Z -Notes "..."`. Increment versions by `0.0.1` unless directed otherwise.
