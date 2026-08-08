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

That's the whole ledger — **every tag your profile can give you now has a surface that fires
while the mistake is still preventable.** Plus the **Tempo engine**, which owns the ~90 seconds
before every objective — and **THE CLOSER** / **THE OUT**, the two halves of the same read:
the game you're winning, and the game you're losing.

And because five things to fix is the same as no things to fix, **THE ONE FIX** prices each of
those habits in *your own LP* — off both sides of the split in your own history — and names the
single one worth working on, then hands it to you in the lobby as one line right before you press
Find Match. Here is the whole in-game HUD, one panel per guard:

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

It lives in your tray (gold **S**), opens itself at champ select and in-game, and keeps itself updated. Hotkeys: **Ctrl+Alt+X** overlay · **Ctrl+Alt+B** widget · **Ctrl+Alt+C** voice coach (press again to cancel).

### Voice coach, privacy, and local Whisper

The optional coach follows you from before queue through post-game. Ask in English or Brazilian
Portuguese and it answers in the selected UI language, on screen and through the matching voice
(`Salli` for English, `Camila` for PT-BR). Claude or Codex must already be installed and signed in;
Settings selects exactly one provider and Smiteless never silently fails over to the other.

- **Consent first.** Manual voice and proactive coaching are separate opt-ins and both default to
  off. Text history stays in memory. Raw microphone audio is a bounded temporary WAV deleted after
  every success, failure, timeout or cancellation; it is never uploaded to a speech API.
- **Only current, minimized context leaves the app.** Smiteless sends phase-legal, redacted facts to
  the selected local CLI. It strips credentials, PUUIDs, Riot IDs and local paths, anonymizes other
  players, and labels account-history evidence separately from this-game performance. A bounded
  read-only discovery harness may retrieve one allowlisted Smiteless source; it has no shell,
  filesystem, browser, LCU-write or general MCP capability.
- **Whisper is local after one download.** The multilingual `small` model is downloaded only after
  confirmation, hash-validated, and shared at `%LOCALAPPDATA%\Smiteless\models\whisper-small`.
  Model weights are not bundled in the installer. Complete uninstall removes this shared cache, so
  source or a later reinstall must download it again.
- **CPU is the safe default:** `int8`. NVIDIA GPU is explicit and requires compatible CUDA 12
  cuBLAS plus cuDNN 9; failure never falls back silently to CPU. **Keep loaded** gives faster warm
  turns; **per question** releases RAM/VRAM after each answer. Settings shows model, device, compute
  type and worker state and provides **Unload model now**.
- **Proactive remains sparse and optional.** It reacts only to high-value draft, loading, live and
  post-game transitions, stays silent during Loading clock zero, and yields to manual conversation
  and deterministic alerts. **Mute for this game** does not disable the manual coach; reset clears
  only the in-memory conversation.

Troubleshooting: confirm the chosen Claude/Codex CLI is logged in; check the Settings readiness
summary; keep a Windows default microphone selected; retry or validate a missing/corrupt model;
select CPU when NVIDIA/CUDA is unavailable; use **Unload model now** after changing device/policy;
and restart the tray if coordinator status is unavailable. Offline TTS uses a matching installed
Windows voice when the online renderer is unreachable; if no matching culture exists, the text
answer remains available without speaking through the wrong language.

## What it does

### 🔥 MAX ELO — the one button
Hit **ARM** and the app goes on rails for the climb. Name a champion and a backup to hold
yourself to one pick, or leave them empty and it calls the best champion for that draft —
counters into the enemies who've locked plus comp fit, falling through the list if the top
one is gone. It brings up the ban that most threatens your team, has your runes and summoners
ready to import, quiets the lobby, and switches on all 25 climb-focused reads at once.
Champion-pool discipline is the highest-confidence lever in ranked, and ARM is how you hold
the line on it — and **THE POOL** (below) is what tells you *which* champions to hold yourself
to, priced in your own LP. **STAND DOWN** releases the hold and leaves the reads on.

### 🧠 In champ select
- **Scouts everyone live** — rank, form, player grades (S–F from how they actually *play*), duo detection, and a **dodge read** that flags tilted or struggling teammates *while you can still dodge*
- **Smart bans** — ranked by who threatens your whole team's hovers, weighted by pick rate, held until the last seconds so the call uses every hover on the board
- **Real matchup tips** — written by actual guide authors for your exact matchup, not AI
- **The live draft link** — posts one URL into lobby chat; teammates who click it get a live web board of the draft with pick suggestions + runes for their seat, no install needed ([setup](docs/DRAFTLINK.md), $0 to run)
- **One-click runes + summoners import**, multiple rune sets
- **Climb guards** — hover a champion **THE POOL** has priced out of your own games and it says so while you can still change your mind (*⚠ Darius: −93 LP / 10 on it (2W-12L)*). When your history can't speak about the pick yet — which is exactly the case it describes — it falls back to the mastery warning (sub-12k-mastery picks win ~44%, per a 1M-game study), pooled across all your accounts so a smurf pick your main knows is fine

### ⚡ In game
- **The Tempo engine** — a live director for the ~90 seconds before every objective: your farm window, exact recall deadline, when to rotate, and a **TAKE / GIVE / 50-50 verdict** from death timers, levels and gold (fog-of-war aware). With spoken callouts: *"Base now"*, *"Rotate to dragon"*, *"Give it, trade elsewhere"*
- **BLEED, the first fourteen minutes** — the only thing in the app watching your own health bar, and it exists because low HP on its own is not a warning (you'd get one every wave) — low HP *while somebody can actually collect* is. It fires only when the live game can prove the threat: your health, plus the enemy jungler unaccounted for, or a lane opponent two levels up who kills you on his own. The bar **tightens as the game shape gets worse** — two deaths already banked before 14:00 and it calls at a health total it would have let pass at zero, because the third death is the one that flips the tag. Otherwise: silence
- **RE-ENTRY, the 90-second guard** — the moment you respawn, a clock starts on the window that actually loses games: dying *again* inside 90 seconds. While it runs the widget answers one thing off live data — can they punish you right now? **HOLD** (the champion who killed you is up and ahead, or you lose any fight this second) takes over the directive card with the productive thing to do instead; **CLEAR** names the enemies who are dead and how long you own the map. It carries its receipt: your own W/L split for the habit, straight out of your match history
- **THE CLOSER — the game you're already winning.** From 20:00, and only while your team is 2k+ up (the same bar your profile uses to tag a thrown game), it answers the question the minimap answers and you never look at: *what is the shortest path to their nexus from here?* It keeps a live structure map from the turret and inhibitor events — **END IT** when an inhibitor is open, with the seconds left on its five-minute clock; **CLOSE** when one turret is all that stands in front of one. It also tracks what you've **given back** of your peak lead (*+4.5k · gave back 2.1k of 6.6k*) — the one number that shows a game being thrown in slow motion — and **HOLD**s you off a fight you'd lose, priced in the seconds your death actually costs against the live baron timer. Behind or even, it says nothing at all
- **THE GOLD CLOCK — your lane, counted against the minions that actually spawned.** Every CS overlay ever built shows you CS/min against a flat benchmark; a flat benchmark doesn't know that at 4:32 only nine waves have left the fountain. Minions are a *schedule* — one wave at 1:05 and one every 30s, 3 melee + 3 casters, every third carrying a cannon — so the denominator here isn't a benchmark, it's the minions that have walked into your lane: *`41 of 74 · 55% · on track for 63, bar 55`*. It back-times your own profile's bar (55 CS by 10:00, the `weak first-ten economy` tag) into the only sentence that helps — ***"you need 25 of the next 32 minions"*** — and says so plainly when the answer is no, switching to plates and objectives instead. The **cannon minion** (60g, the biggest object in lane phase) gets its own seconds-out warning, but only while you're behind. Kills count as the CS they were worth, so a roaming game reads `30+44 of 82 · 90%` and stays green. A wave lost while you were dead is never billed to you. One quiet row for ten minutes; it takes the card only at the moment a wave went by, and never outranks BLEED. Top / mid / ADC — silent for jungle and support rather than invent a number
- **THE WARD CLOCK — the vision war, live, and the other half of the map.** The gold clock is deliberately silent for jungle and support; this is theirs, and it is the two roles your profile actually grades on vision. It hangs off one fact nothing else in the app can use: `:2999` reports a **vision score for all ten players**, unfiltered by fog, and that number *only ever goes up while a ward of yours is alive*. So a score that hasn't moved in 1:40 isn't an opinion — it's a measurement that **nothing of yours is on the map**, and it needs no model at all. That buys four things nobody has shown you before: a live **head-to-head against the enemy in your own role** — same job, same minutes, same units — sitting in one quiet row all game (*`14.2 v 21.6 · 0.9/min, bar 1.2 · 1 pink`*); **PIT**, which fires in the seconds before a drake or baron *you are about to fight blind*, on a deliberately shorter fuse than anywhere else because "ward the pit" is never bad advice — naming **the deadline it has to be in by**, **where** (deep past the pit when you're ahead, your own tri when you're behind) and **how, with the trinket actually in your hand** (a sweeper takes theirs first; a farsight can't sweep at all); **PINK**, because a control ward you bought and never placed is 75 gold of map you already paid for — and in a recall window, where buying one is an actual action, the row leads with it; and the number nothing else has ever put in front of a player: **the share of the game you had a control ward on you at all**, off the fact that a count falling out of your bag *is* the placement event. It is asleep until the live feed has *proven* it reports a vision score at all, so it can never tell a support who has warded all game that he is dark. Dark time you spent on the grey screen is never billed to you, it stands down to its row the moment the tempo engine calls a fight, and it says *"Ward it."* out loud at most three times a game — this is the one guard whose whole subject is somewhere your eyes are not
- **Enemy jungle tracker** — where they were seen, when they're dead, when to respect the gank
- **THE OUT — the game you're LOSING, and the fourteen minutes nobody counts.** THE CLOSER owns the game you're winning and says nothing at all when you're behind. This is the other half of that map, and it exists because a climb is **LP per hour** and half the hour is spent inside games that were decided ten minutes ago — a 38-minute loss and a 24-minute loss cost the same LP. From 15:00 (the first surrender window; there is no such thing as a decided game before one exists) and only while you're 2k+ down — the exact bar the CLOSER calls *ahead*, mirrored — it looks for an **OUT**, and an out is always a fact with a clock on it: **baron** in range and actually contestable, **elder or soul point**, **death timers** long enough that one won fight is the map (*their deaths cost 52s*), a comp that **out-scales** theirs (the same power-curve table champ select graded the draft with), or a **base they still haven't opened**. Because the most expensive thing in a losing game is a team that stops playing one it could still win. It also carries the number nobody has ever shown a losing team: **what you've won back off your worst** — *`-4.2k · won back 3.7k of 7.9k`* — the comeback in measured gold, before anyone can feel it. And when a game genuinely has nothing left — 20:00+, 8k down, an inhibitor of yours open and the 5v5 gone, with no live objective out — it says **CALL IT**: the LP is already spent, the minutes are not. It's deliberately the hardest verdict in the app to reach; in 600 simulated games, **0%** of the games it wrote off ever came back to even. It never speaks aloud and it never votes for you
- **Objective timers with audio, power-spike alerts, item coaching, and the measured team gold gap** — one compact draggable HUD that fades when nothing needs you, and is fully click-through during a live game so it can never eat a click (hold **Ctrl+Alt** to touch it)
- **The Death Brief** — the moment you die, a see-through fullscreen overlay gives you the whole game at a glance: respawn clock, why you died, what to buy on respawn, the win read, the enemy to watch, next objectives, and the team boards. Laid out around the game's own death HUD (team boards top-center where TAB lives, nothing over the recap / chat / minimap), center stays clear + click-through so you keep watching the fight. Read-only — never touches your camera or inputs
- **In-game quiet** — sets League's own options for you (ally chat off, all-chat off, ping audio off) and verifies them by reading them back, so the noise that tilts you is gone before the game starts and stays gone until you turn it back on. Your own pings still work. On by default; **Settings → In-game quiet**
- **The Loading-Screen Scout** — while the game loads, ten tall portrait cards (Riot's own loading art, laid out like the real loading screen) read every ACCOUNT in the lobby: rank + LP + season record, last-10 form bars, KDA, mastery, record on the locked champ, a performance grade, and profile tags mined from their real history — `duo`, `SMURF READ`, `OTP · 612k pts`, `4L streak · tilt risk`, `first-time?`, `off-role`, `carries games`, `hardstuck`. Gone the instant the game starts

### 🚦 Before you queue
- **The Queue Call** — the lobby answers the only question left before Find Match: *is this one worth playing?* One verdict — **GO / LAST ONE / WAIT / STOP** — computed from your own ranked history (riding 2+ losses, deep into a sitting, straight back in under 10 minutes, the hour you're playing). It only calls a stop when that split beats a two-proportion significance test against the rest of your games, so it isn't superstition: every line carries its receipt — *"game 4+ of a sitting · 33% over 36 (vs 63% otherwise)"*. When the call is **GO** or **LAST ONE**, it also carries **THIS GAME** — the one habit from THE ONE FIX to hold yourself to, in the seconds before you press the button (never under a STOP: homework and a stop rule in the same breath is how the stop rule gets ignored). Docks beside the client, never takes focus, and closes itself the moment you queue

### 📈 Between games
- **THE ONE FIX** — the five habits your profile grades every game, **priced in LP**, ranked, and narrowed to one. The ledger holds both sides of every split — the games a habit fired in and the games it didn't — so each leak gets the number nobody has ever shown you: *`RE-ENTRY · −41 LP / 10 games · with it: 3W-7L · without: 9W-5L`*. The LP is **yours**, read from your own rank snapshots (`+22 / -17`, not "about 20"). It names **one** habit, as something you can hold yourself to for a single game, and says which in-game guard is watching it. Every row carries a form strip of the last six games it could have happened in, so you can watch a leak close — and it flags `improving` once it's real. Nothing is priced until its split beats the same significance test the QUEUE CALL uses, and even then the split is quoted shrunk toward your own baseline so a 3-vs-5 fluke can't become a headline; below that bar the row shows its numbers as a *lean*, never a price. Under ten graded games it doesn't guess — it says how many more it needs
- **THE POOL** — the other half of the climb, in the same currency: **your champions, priced in your own LP.** Not a win rate — *`Sett +38 LP / 10 on it · 14W-6L over 20 · 70% on it vs 45% otherwise`* — measured against **your own baseline**, because a 47% champion is not a leak for a player who wins 44% of everything else. It names one champion to **QUEUE** and one to **BENCH**, prices your whole **POOL WIDTH** (your top 3 against everything else you queued, per ten of your games — the real cost of ranked tourism), and it **never benches your main**: a main on an awful run is variance, and the card says so. Then the number that makes the rest trustworthy: it **corrects for looking at every champion at once**, which is the failure mode of every "your best champion" stat ever shown to a League player. The guard suite measures it — at the ordinary bar, pools made of pure coin flips produce a "proven" best or worst champion **49%** of the time; corrected, **7%**. Below the bar a row still shows its numbers, labelled as a *lean*, never a price. And it's **one brain**: the champ-select recommender's veto IS this board's bench, so the two can never disagree about a champion again
- **Your profile** — per-game performance scores graded against your role's benchmarks (never the lobby), timeline review of your latest game, LP trend, session tracking
- **The climb system** — research-backed discipline: the 2-loss stop rule and champion-pool focus, with every claim sized to the sample behind it
- **Click any player** to scout their full profile; right-click for u.gg / op.gg / Porofessor
- **Fast account switching** — save each account's "Stay signed in" session and switch between them from the tray, no passwords stored anywhere. Relaunches you straight into League

Patch notes: tray → **Patch notes**, or [CHANGELOG.md](CHANGELOG.md).

## 🛠️ Building from source

```
git clone https://github.com/bobbyroylee/smiteless
pip install pillow pystray
python smiteless_main.py overlay      # or: widget / settings / profile
```

`python tools\selftest.py` runs the health check and every engine guard — the verdict engines
(tempo, gold clock, ward clock, bleed, re-entry, closer, the out, queue call, the one fix,
the pool) are pure
functions with fixtures, so they're testable without a live game. Each also prints its own branches:
`python core\lolward.py`, `python core\lolout.py`, `python core\lolfix.py demo`,
`python core\lolpool.py demo`.

`dist\build.ps1` builds the frozen app and `dist\make-release.ps1 -Version X.Y.Z` cuts a release
locally (PyInstaller + AHK-compiled tray/installer, Python 3.11+). Releases are normally cut in
the cloud instead — the **Release** workflow in the Actions tab builds the installer on a Windows
runner and publishes it, no local toolchain needed.
