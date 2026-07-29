# Smiteless ⚔️

WARNING:  I frequently update Smiteless and sometimes the updates just aren't good.  I usually revert them if its not good as I'm trying completely new ideas, UIs, techniques and more.  So sometimes there'll be an update and it'll be something you just wont like and likely I dont either and I'll either change it or revert it but it can take usually up to 24 hours before I change it back or fine tune it.  The point of Smiteless is extreme researched back evidence on techniques on climbing the absolute fastest.  It may not look like much but under the hood there is extremely extensive research-backed calculations going on behind the scenes including a 1M accounts case study done on what worked and what didn't work to climb.  TLDR 1 version might be shit but just give it two days max and it'll be dialed back in.

**A League of Legends companion built for one thing: climbing as fast as it is possible to climb.** It watches champ select and your live game and tells you the one thing that matters right now — what to ban, when to back, whether that drake fight is winnable, and when to stop queuing — because the fastest climb is a string of decisions made correctly, and almost none of them are made with the information in front of you.

![The in-game scoreboard](docs/board.png)

## What it lives for: SPEED

**Smiteless exists to get you up the ladder as fast as the ladder can physically be climbed.**
Not to help you enjoy the game more, not to cover the game comprehensively, not to give you
something to read after a loss. Speed of rank gain, and nothing else, is the metric every
feature in here is judged against.

That is a much harsher filter than it sounds, and it is applied constantly:

- **Every feature has to shorten time-to-rank, or it gets cut.** "Interesting to know" is not a
  reason to build something. If a surface doesn't change a decision you are about to make, in
  the seconds before you make it, it isn't earning its place on your screen — and features have
  been deleted from this app for exactly that.
- **It goes after the biggest levers first, in order.** Champion-pool discipline, the 2-loss
  stop rule, and the handful of in-game habits that measurably decide games — because a fast
  climb comes from fixing the few things that cost the most LP, not from marginally improving
  everything. Which lever is biggest isn't a guess: it comes out of research including a 1M-game
  study, and out of your own match history.
- **Six things done right beat twelve done halfway.** Quality over coverage. A read you can't
  trust is worse than no read, because acting on a wrong call costs you the game the app was
  supposed to win.

And three rules that keep it fast in practice:

- **It speaks once, or not at all.** Every surface is allowed to say nothing, and most of them
  say nothing most of the game. A coach that talks through a losing game, or nags every ninety
  seconds, is a coach you turn off — and an app you've turned off climbs nothing.
- **Every claim carries its receipt.** No line tells you a habit is costing you games without
  showing the split *from your own match history* — *"with it: 3W-9L · without: 11W-5L"*. Where
  a number is modelled rather than measured, the source says so out loud.
- **It reads, it doesn't play.** The live surfaces are 100% read-only off Riot's own local
  endpoint. Nothing touches your camera, your inputs, or your mouse mid-fight.

## Your leaks, answered while you can still fix them

Between games, your profile reads each match and tags the habits that actually cost you the
game. **The direction of this project is simple: every one of those tags gets a live in-game
surface that fires while the mistake is still preventable** — the review is worth far less
than the intervention.

This is where the speed actually comes from. A leak isn't one lost game, it's the same lost
game on repeat — so closing one changes every game you play after it, and that compounding is
the difference between grinding a rank and arriving at it.

| Your profile tags it | In game, this answers it | When |
|---|---|---|
| `weak first-ten economy` | **THE GOLD CLOCK** | 2:30 → 14:00 |
| `early bleeding` (3+ deaths pre-14) | **BLEED** | 0:00 → 14:00 |
| `chained deaths` (2+ inside 90s) | **RE-ENTRY** | the 90s after you respawn |
| `coin-flip death while ahead` | **THE CLOSER** | 20:00+, only while winning |
| `no vision setup` | **THE WARD CLOCK** | 3:00 → end (jg / sup) |

That's the whole ledger — **every tag your profile can give you now has a surface that fires while the mistake is still preventable.** Plus the **Tempo engine**, which owns the ~90 seconds before every objective. Here is the whole
in-game HUD, one panel per guard:

![The in-game widget](docs/widget.png)

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
summoners, mutes the lobby, and switches on all 24 climb-focused reads at once. Champion-pool
discipline is the highest-confidence lever in ranked and this enforces it rather than suggesting
it. **STAND DOWN** releases the lock and leaves the reads on.

### 🧠 In champ select
- **Scouts everyone live** — rank, form, player grades (S–F from how they actually *play*), duo detection, and a **dodge read** that flags tilted or struggling teammates *while you can still dodge*
- **Smart bans** — ranked by who threatens your whole team's hovers, weighted by pick rate, with optional **auto-ban** that waits until the last seconds for maximum hover intel
- **Real matchup tips** — written by actual guide authors for your exact matchup, not AI
- **The live draft link** — posts one URL into lobby chat; teammates who click it get a live web board of the draft with pick suggestions + runes for their seat, no install needed ([setup](docs/DRAFTLINK.md), $0 to run)
- **One-click (or automatic) runes + summoners import**, multiple rune sets
- **Climb guards** — warns when you hover a champ you barely play (sub-12k-mastery picks win ~44%, per a 1M-game study), pooled across all your accounts so a smurf pick your main knows is fine

### ⚡ In game
- **The Tempo engine** — a live director for the ~90 seconds before every objective: your farm window, exact recall deadline, when to rotate, and a **TAKE / GIVE / 50-50 verdict** from death timers, levels and gold (fog-of-war aware). With spoken callouts: *"Base now"*, *"Rotate to dragon"*, *"Give it, trade elsewhere"*
- **BLEED, the first fourteen minutes** — the only thing in the app watching your own health bar, and it exists because low HP on its own is not a warning (you'd get one every wave) — low HP *while somebody can actually collect* is. It fires only when the live game can prove the threat: your health, plus the enemy jungler unaccounted for, or a lane opponent two levels up who kills you on his own. The bar **tightens as the game shape gets worse** — two deaths already banked before 14:00 and it calls at a health total it would have let pass at zero, because the third death is the one that flips the tag. Otherwise: silence
- **RE-ENTRY, the 90-second guard** — the moment you respawn, a clock starts on the window that actually loses games: dying *again* inside 90 seconds. While it runs the widget answers one thing off live data — can they punish you right now? **HOLD** (the champion who killed you is up and ahead, or you lose any fight this second) takes over the directive card with the productive thing to do instead; **CLEAR** names the enemies who are dead and how long you own the map. It carries its receipt: your own W/L split for the habit, straight out of your match history
- **THE CLOSER — the game you're already winning.** From 20:00, and only while your team is 2k+ up (the same bar your profile uses to tag a thrown game), it answers the question the minimap answers and you never look at: *what is the shortest path to their nexus from here?* It keeps a live structure map from the turret and inhibitor events — **END IT** when an inhibitor is open, with the seconds left on its five-minute clock; **CLOSE** when one turret is all that stands in front of one. It also tracks what you've **given back** of your peak lead (*+4.5k · gave back 2.1k of 6.6k*) — the one number that shows a game being thrown in slow motion — and **HOLD**s you off a fight you'd lose, priced in the seconds your death actually costs against the live baron timer. Behind or even, it says nothing at all
- **THE GOLD CLOCK — your lane, counted against the minions that actually spawned.** Every CS overlay ever built shows you CS/min against a flat benchmark; a flat benchmark doesn't know that at 4:32 only nine waves have left the fountain. Minions are a *schedule* — one wave at 1:05 and one every 30s, 3 melee + 3 casters, every third carrying a cannon — so the denominator here isn't a benchmark, it's the minions that have walked into your lane: *`41 of 74 · 55% · on track for 63, bar 55`*. It back-times your own profile's bar (55 CS by 10:00, the `weak first-ten economy` tag) into the only sentence that helps — ***"you need 25 of the next 32 minions"*** — and says so plainly when the answer is no, switching to plates and objectives instead. The **cannon minion** (60g, the biggest object in lane phase) gets its own seconds-out warning, but only while you're behind. Kills count as the CS they were worth, so a roaming game reads `30+44 of 82 · 90%` and stays green. A wave lost while you were dead is never billed to you. One quiet row for ten minutes; it takes the card only at the moment a wave went by, and never outranks BLEED. Top / mid / ADC — silent for jungle and support rather than invent a number
- **THE WARD CLOCK — the vision war, live, and the other half of the map.** The gold clock is deliberately silent for jungle and support; this is theirs, and it is the two roles your profile actually grades on vision. It hangs off one fact nothing else in the app can use: `:2999` reports a **vision score for all ten players**, unfiltered by fog, and that number *only ever goes up while a ward of yours is alive*. So a score that hasn't moved in 1:40 isn't an opinion — it's a measurement that **nothing of yours is on the map**, and it needs no model at all. That buys three things nobody has shown you before: a live **head-to-head against the enemy in your own role** — same job, same minutes, same units — sitting in one quiet row all game (*`14.2 v 21.6 · 0.9/min, bar 1.2 · 1 pink`*); **PIT**, which fires in the seconds before a drake or baron *you are about to fight blind*, on a deliberately shorter fuse than anywhere else because "ward the pit" is never bad advice — and it tells you **where**, deep past the pit when you're ahead, your own tri when you're behind; and **PINK**, because a control ward you bought and never placed is 75 gold of map you already paid for. It is asleep until the live feed has *proven* it reports a vision score at all, so it can never tell a support who has warded all game that he is dark. Dark time you spent on the grey screen is never billed to you, and it stands down to its row the moment the tempo engine calls a fight
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

`python tools\selftest.py` runs the health check and every engine guard — the verdict engines
(tempo, gold clock, bleed, re-entry, closer, queue call) are pure functions with fixtures, so
they're testable without a live game. Each also prints its own branches: `python core\lolgold.py`.

`dist\build.ps1` builds the frozen app and `dist\make-release.ps1 -Version X.Y.Z` cuts a release
locally (PyInstaller + AHK-compiled tray/installer, Python 3.11+). Releases are normally cut in
the cloud instead — the **Release** workflow in the Actions tab builds the installer on a Windows
runner and publishes it, no local toolchain needed.
