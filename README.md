# Smiteless ⚔️

WARNING:  I frequently update Smiteless and sometimes the updates just aren't good.  I usually revert them if its not good as I'm trying completely new ideas, UIs, techniques and more.  So sometimes there'll be an update and it'll be something you just wont like and likely I dont either and I'll either change it or revert it but it can take usually up to 24 hours before I change it back or fine tune it.  The point of Smiteless is extreme researched back evidence on techniques on climbing the absolute fastest.  It may not look like much but under the hood there is extremely extensive research-backed calculations going on behind the scenes including a 1M accounts case study done on what worked and what didn't work to climb.  TLDR 1 version might be shit but just give it two days max and it'll be dialed back in.

**A League of Legends companion that plays the map with you.** It watches champ select and your live game, then tells you the one thing that matters right now — what to ban, when to back, whether that drake fight is winnable, and when to stop queuing.

![The in-game scoreboard](docs/board.png)

| Champ select (docks by the client) | Your profile |
|:---:|:---:|
| ![Champ select panel](docs/champselect.png) | ![Profile](docs/profile.png) |

**The loading-screen scout** — every account in the lobby read from its real match history, with profile tags (duo · smurf read · OTP · tilt risk · first-timer · off-role):

![Loading-screen scout](docs/preview_loading_ui.png)

**The Death Brief** — laid out around the game's own death HUD, center kept clear to watch the fight:

![Death brief](docs/preview_death_ui.png)

**The Live Draft Link** — one URL posted into champ-select chat; teammates click it and get the live draft with pick + rune suggestions for their seat, no install needed ([setup](docs/DRAFTLINK.md)):

![Live draft board](docs/draft_board.png)

> ⚠️ **Small personal project — Windows + NA only, no warranty.** Not affiliated with or endorsed by Riot Games; respect the [Riot API terms](https://developer.riotgames.com/policies/general). The player scout needs your own free Riot API key.

## ⬇️ Install

**[Download SmitelessSetup.exe](https://github.com/bobbyroylee/smiteless/releases/latest)** → double-click → Install. No Python, no setup — everything's bundled. Windows 10/11, League in **Borderless** mode. Full walkthrough (including the free Riot-key setup): **[INSTALL.md](INSTALL.md)**.

It lives in your tray (gold **S**), opens itself at champ select and in-game, and keeps itself updated. Hotkeys: **Ctrl+Alt+X** overlay · **Ctrl+Alt+B** widget.

## What it does

### 🔥 MAX ELO — the one button
Hit **ARM** and the app goes on rails for the climb. Name a champion and a backup to be held
to one pick, or **leave them empty and it locks the best champion for that draft** — counters
into the enemies who've locked plus comp fit, falling through the list if the top one is gone.
Then it bans the champ that most threatens your team, auto-accepts, imports your runes and
summoners, mutes the lobby, and switches on all 21 climb-focused reads at once. Champion-pool
discipline is the highest-confidence lever in ranked and this enforces it rather than suggesting
it. **STAND DOWN** releases the lock and leaves the reads on.

### 🧠 In champ select
- **Scouts everyone live** — rank, form, player grades (S–F from how they actually *play*), duo detection, and the flags that feed the Dodge Call *while you can still dodge*
- **The Dodge Call** — the lobby priced in LP, not in vibes. A quiet line under your champ says what this game is worth (*"LOBBY 52% · +2.9 LP · PLAY"*), and turns into a red card only when walking away actually pays: *"⚠ DODGE — worth +2.8 LP vs playing it · 5/5 lanes behind · worst Yasuo vs Malzahar (-11%)"*. It uses **your** LP per win and per loss, **your** median game length, and Riot's real penalties — which is how it can tell you the second dodge of the day (10 LP, 30 minutes) is almost never worth taking. Tilted teammates only count for the amount they beat the rate the enemy team carries them at, measured from every lobby it has scouted
- **Smart bans** — ranked by who threatens your whole team's hovers, weighted by pick rate, with optional **auto-ban** that waits until the last seconds for maximum hover intel
- **Real matchup tips** — written by actual guide authors for your exact matchup, not AI
- **The live draft link** — posts one URL into lobby chat; teammates who click it get a live web board of the draft with pick suggestions + runes for their seat, no install needed ([setup](docs/DRAFTLINK.md), $0 to run)
- **One-click (or automatic) runes + summoners import**, multiple rune sets
- **Climb guards** — warns when you hover a champ you barely play (sub-12k-mastery picks win ~44%, per a 1M-game study), pooled across all your accounts so a smurf pick your main knows is fine

### ⚡ In game
- **The Tempo engine** — a live director for the ~90 seconds before every objective: your farm window, exact recall deadline, when to rotate, and a **TAKE / GIVE / 50-50 verdict** from death timers, levels and gold (fog-of-war aware). With spoken callouts: *"Base now"*, *"Rotate to dragon"*, *"Give it, trade elsewhere"*
- **RE-ENTRY, the 90-second guard** — the moment you respawn, a clock starts on the window that actually loses games: dying *again* inside 90 seconds. While it runs the widget answers one thing off live data — can they punish you right now? **HOLD** (the champion who killed you is up and ahead, or you lose any fight this second) takes over the directive card with the productive thing to do instead; **CLEAR** names the enemies who are dead and how long you own the map. It carries its receipt: your own W/L split for the habit, straight out of your match history
- **Enemy jungle tracker** — where they were seen, when they're dead, when to respect the gank
- **Win probability, objective timers with audio, power-spike alerts, item coaching** — one compact draggable HUD that fades when nothing needs you, and is fully click-through during a live game so it can never eat a click (hold **Ctrl+Alt** to touch it)
- **The Death Brief** — the moment you die, a see-through fullscreen overlay gives you the whole game at a glance: respawn clock, why you died, what to buy on respawn, the win read, the enemy to watch, next objectives, and the team boards. Laid out around the game's own death HUD (team boards top-center where TAB lives, nothing over the recap / chat / minimap), center stays clear + click-through so you keep watching the fight. Read-only — never touches your camera or inputs
- **Auto-mute** — a few seconds into the game Smiteless types Riot's own `/fullmute all` for you: chat *and* ping markers from every player, gone for that game. Your own pings still work, and it waits for the game window to be focused so the command is never typed anywhere else. Underneath that it also sets League's own options (ally chat off, all-chat off, ping audio off) and verifies them by reading them back — those persist until you turn them off. On by default; **Settings → In-game quiet**
- **The Loading-Screen Scout** — while the game loads, ten tall portrait cards (Riot's own loading art, laid out like the real loading screen) read every ACCOUNT in the lobby: rank + LP + season record, last-10 form bars, KDA, mastery, record on the locked champ, a performance grade, and profile tags mined from their real history — `duo`, `SMURF READ`, `OTP · 612k pts`, `4L streak · tilt risk`, `first-time?`, `off-role`, `carries games`, `hardstuck`. Gone the instant the game starts

### 🚦 Before you queue
- **The Queue Call** — the lobby answers the only question left before Find Match: *is this one worth playing?* One verdict — **GO / LAST ONE / WAIT / STOP** — computed from your own ranked history (riding 2+ losses, deep into a sitting, straight back in under 10 minutes, the hour you're playing). It only calls a stop when that split beats a two-proportion significance test against the rest of your games, so it isn't superstition: every line carries its receipt — *"game 4+ of a sitting · 33% over 36 (vs 63% otherwise)"*. Docks beside the client, never takes focus, and closes itself the moment you queue

### 📈 Between games
- **Your profile** — per-game performance scores graded against your role's benchmarks (never the lobby), timeline review of your latest game, LP trend, session tracking
- **The climb system** — research-backed discipline: the 2-loss stop rule, champion-pool focus, and sample-aware "play more / ease off" coaching
- **Click any player** to scout their full profile; right-click for u.gg / op.gg / Porofessor
- **One-click Riot login, two ways** — *(a)* save each account's "Stay signed in" session and switch from the tray with no password stored, or *(b)* Profile → **⚡ Log in** to save a username+password (DPAPI-encrypted) and have Smiteless autofill the Riot login form for you. Both relaunch you straight into League; the password path survives logging out, the session path can't be captcha'd

Patch notes: tray → **Patch notes**, or [CHANGELOG.md](CHANGELOG.md).

## 🛠️ Building from source

```
git clone https://github.com/bobbyroylee/smiteless
pip install pillow pystray
python smiteless_main.py overlay      # or: widget / settings / profile
```

`dist\build.ps1` builds the frozen app; `dist\make-release.ps1 -Version X.Y.Z` cuts a release (PyInstaller + AHK-compiled tray/installer, Python 3.11+).
