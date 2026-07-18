# Smiteless — Patch Notes

## v0.9.25
- **Player tags are now readable at a glance.** The in-game board's profile tags (OTP, tilt risk, smurf read, off-role, comfort, etc.) now render as stronger, cleaner chips: **green for good**, **red for bad**, with clearer neutral/info variants and a larger display face so they read fast on a second monitor.
- **Overlay sizing is now truly adaptive (and no more cut-off on resize).** Non-docked boards now scale to a bounded share of the monitor instead of taking over most of the screen, and resize events re-render the board to the new size so shrinking the window no longer clips content. Docked champ-select panels keep fit-clamped behavior.

## v0.9.24
- **The live board now fills its monitor.** It rendered at a fixed design size and could only ever shrink — small on the very screen it owns. It now **draws itself scaled to the monitor it opens on** (~1740px wide on 1080p, larger on 1440p+): every font, art slab, tag pill, grade chip and gank badge grows in step, crisp at any size because it re-renders instead of stretching pixels. Small windows and low resolutions still shrink-to-fit exactly as before.

## v0.9.23
- **The second-monitor board got the profile treatment — it's the tool that's always on, so now it looks like it.** The live in-game board is a full redesign in the profile/loading-screen language: a **splash hero header** (your champ, role chip, build line, win rate), a **winners/losers-queue verdict strip** with both teams' average grades, and five **lane-matchup rows** where every player is a mini profile card — **champion art slab, Riot ID, rank + LP in tier colors, last-10 form bars, KDA, mastery**, their **S–F performance grade**, and the same **profile-read tags** as the loading screen (`duo`, `SMURF READ`, `OTP · 612k pts`, `4L streak · tilt risk`, `passenger · low impact`, `grinder`) — with the ★ gank verdict between each pair. Wider (it owns a whole monitor), taller rows, and the win-condition card in the house style. Champ select's docked panel is unchanged; clicking a player still opens their u.gg.
- **One-click login is fast now.** It used to take forever to notice the Riot login form was sitting there waiting — root cause found: it was crawling the Riot window's UI tree element-by-element from Python (thousands of COM calls, seconds per look), re-creating the automation object every poll, and only accepting the form when a password *flag* it often never got showed up — so most logins silently rode out a 35-second timeout before typing. Now it asks Windows UI Automation for all edit fields in **one native query (~20ms)**, polls ~3× a second with one shared object, accepts the form the moment two fields exist, and — if the client window is already open — **waits for the form instead of relaunching the client**. The fill should start within a beat of the form appearing.
- **The widget can no longer eat your clicks — ever.** The in-game TEMPO widget is now **fully click-through during a live game**: every click lands in the game, even when your cursor drifts over it mid-fight. Hold **Ctrl+Alt** to actually touch it (drag it, mute, volume, close) — hovering it in-game shows a small "ctrl+alt to touch" reminder. Outside a game it behaves like a normal window, exactly as before.
- **The loading screen is now a real account scoreboard — nothing else in Smiteless looks like it.** Ten full-width splash-art rows, one per player, each loaded with their **actual account**: Riot ID, **rank + LP + full season record** (412W 380L · 52%), **last-10 form bars**, average KDA with the per-game k/d/a split, **mastery points on the champ they locked**, their record *on that champ*, and a **performance grade** (S+–D, same grading as your profile — how they play, not just whether they won). And the headline feature: **detailed profile-read tags** mined from each account's real history — `duo · parallel b` (players sharing recent games), `SMURF READ · new acct, stomping`, `Zed OTP · 612k pts`, `4L streak · tilt risk`, `first-time Miss Fortune?`, `off-role · BOT main`, `bleeds · 6.8 deaths/game`, `carries games · 96 avg perf`, `grinder · 792 ranked this season`, `hardstuck · 44% season wr`. Champion knowledge pills show instantly; accounts fill in as the scout resolves.
- **The Death Brief now respects the game's own death HUD.** It used to sit on top of the death recap / gold / shop button in the top-left and park its kill feed in the bottom-left — right where the chat and your TEMPO widget live. The layout is now built around a keep-out map of the real death screen: the **team boards sit top-center** (where TAB lives), the respawn clock / why-you-died / on-respawn read hangs **under the death recap** on the left, the win-read column hangs **under the stats bar** on the right and stops above the respawn-portrait strip, and nothing ever covers the minimap, the BACK IN plate, the chat, or the widget's corner. Cards that can't fit their lane on a given resolution skip cleanly instead of overlapping.
- **Loading screen: smaller, cleaner, and a lot more informative.** Shrunk it down to a compact centered card instead of a full-screen sprawl, and packed real scouting into each row: champion **mastery** (M7·210k), their recent record **on that exact champ** (6-2), **overall winrate**, and **recent KDA** — alongside the rank badge and hot/tilt/OTP/off-role pills. Reads like a clean scouting table now, with the game plan underneath.

## v0.9.19
- **The loading screen got a real design.** The flat text is gone — every player is now a card with their **champion portrait**, name, role, damage type, a **rank badge in its tier colour** (Diamond blue, Emerald green, Gold amber…), tag pills for streaks/one-tricks, and the champ read, split into two team panels with a game-plan footer. It looks like the profile page now, not a spreadsheet. Portraits load in the background and pop in; after the first game they're instant.
- **Fix: it no longer vanishes while you're still loading.** It was closing itself the moment the live-game API started responding — but that happens *while you're still on the loading screen*. It now waits for the actual game clock to start before closing, and a momentary hiccup can't make it disappear anymore.

## v0.9.18
- **The loading brief actually appears now — root cause found in the logs, not guessed.** It was detecting the loading screen correctly, then trying to scout all ten players through the rate-limited Riot API *on the same thread that draws the window* — which blocked the whole thing, so the loading screen came and went with nothing shown. Now the overlay pops up **instantly** with champions, matchup tags, and the game plan (no network needed, ~0.1s), and the per-player rank/one-trick scout fills in a moment later in the background. It can't be blocked anymore.

## v0.9.17
- **HOTFIX: dying no longer shows a white fullscreen.** v0.9.16's fancy transparency method broke in the real app — the death overlay painted as a solid white sheet over the game. That method is gone; the overlay is back on the same proven rendering the widget has always used, with the whole window at ~88% opacity for the see-through look. Sorry about that one — it was shipped without being exercised in a live game, which is on us.
- **The loading-screen brief should FINALLY appear** — found the real reason it never did: it was launched at the moment the game went "in progress," which is usually *after* the loading screen is already over, so it started, saw a live game, and closed itself instantly. It now launches at **champ select** and waits, armed, for the loading screen to begin. It also writes a diagnostic log (`~/.claude/smiteless_load.log`) so if it still misbehaves, the log says exactly why instead of anyone guessing.
- Intended looks for both overlays are in `docs/preview_loading_ui.png` and `docs/preview_death_ui.png`.

## v0.9.16
- **The Death Brief is glass now, not solid blocks.** The panels were fully opaque and walled off whatever they sat over. They're now **semi-transparent** (~80%) with true per-pixel alpha — the game tints through them while the text stays fully crisp and opaque on top. Painted via `UpdateLayeredWindow` instead of a binary chroma key, so it's a real glassy HUD, still click-through and still keeping the middle of the screen clear.

## v0.9.15
- **The Death Brief is sized right now.** It was drawn against a 1080p reference, so on a 1080p screen it rendered at full size and each column ate ~22% of the width — it felt oversized. It's now drawn against a taller reference so it sits as a compact ~17%-per-column strip on **any** resolution (still fully resolution-adaptive — proportional on 1080p, 1440p, 4K, ultrawide), leaving much more of the screen clear.

## v0.9.14
- **The Death Brief is now a coach, not a dashboard.** Death is when you need guidance most, so instead of just showing numbers it now reads the state and *tells you what to do*, leading with three synthesized calls:
  - **WHY YOU DIED** — from the actual kill that got you: *"Solo-killed by Zed (9/1) — he one-shots you now: buy Zhonya's/GA, never walk alone, group tight."* Knows solo-kill vs collapsed-on, and the killer's class + how fed they are.
  - **HOW YOU WIN** — your win condition for *this* game, from the comps and who's ahead: *"You out-scale — survive the early game, farm, take neutrals; your power is 3 items each,"* or *"Behind vs a scaling comp — you MUST make plays early."*
  - **THE THREAT** — the enemy carrying the game and the actual counterplay for their class (dive the fed ADC, buy Zhonya's vs the assassin, %HP the tank), not just "watch him."
- Still fronted by your respawn clock and the on-respawn buy + macro move, with the tagged team boards on the edges and the middle of the screen kept clear to watch the fight. Everything is grounded in the live game — it stays quiet when it can't prove a read.

## v0.9.13
- **Fix: the loading-screen overlay never actually showed.** It was gated on the gameflow phase being exactly `GameStart` — but that's a sub-second flash, and the phase reads `InProgress` for almost the entire loading screen, so the overlay launched and instantly closed itself every game. It now detects the loading window the right way: the game process is up (`GameStart`/`InProgress`) **but the live game (:2999) isn't serving yet** — which is precisely the loading screen. It shows the whole time you're loading and closes the moment the game world starts. (No change to what it shows — the lobby scout, champ tags, and game plan from v0.9.12.)

## v0.9.12
- **The loading screen now SCOUTS the whole lobby.** The loading screen is the first time everyone's IGN is exposed — so it's the first time the lobby can be read — and Smiteless now does it: each player's summonerId resolves to their Riot ID, which resolves to a real puuid, which pulls their full scout. Every one of the ten now shows their **rank**, a **hot/tilted streak** read (`4W hot`, `4L skid`, `25% struggling`), whether they're a **one-trick** on this champ, and whether they're on an **off-champ** (sub-12k-mastery, ~44% win). Tags are colored *relative to you* — your ally struggling is red, an enemy on a skid is green. (Champ select just cached all of it, so it's near-instant.)
- Kept from before: each champ's good/bad tags + AD/AP damage split, and the plain **GAME PLAN** for the comp. Correcting the v0.9.11 note — live player scouting on the loading screen IS possible after all; thanks to the IGNs being visible there.

## v0.9.11
- **NEW — the LOADING-SCREEN matchup overlay.** While the game loads (dead time you're staring at anyway), the whole screen fills with the read that decides the early game: every champion's **good/bad tags**, the **damage split** to itemize against (AD/AP per player), and a plain-English **GAME PLAN** for the comp — *"Enemy is AP-heavy → build MR early"*, *"2 assassins → respect level 6, group, buy Zhonya's/GA"*, *"you out-scale → survive early, win late."* Your team gets light tags on the left; the enemy gets the detailed "what they do" on the right (Zed: *ults to delete a carry · dodge-able ult — ping it*; Darius: *wins extended trades — don't stay · no dash, kite the pull*). Gone the instant the game starts. Toggle: **Settings → Loading brief**.
- Note: the loading screen only shows **champion** knowledge, not live rank/form — Riot exposes only placeholder player IDs during loading, so player scouting stays in champ select where it belongs.

## v0.9.10
- **The Death Brief keeps the middle of your screen clear again.** v0.9.9 packed the 10-player board dead-center, which covered the fight — the whole point of the see-through design is that you can still watch the game while dead. The board now splits to the **left and right edges** (your team left, enemy right), and the center is fully transparent and click-through, as it should be.
- **Every player carries a good/bad tag now** — the deeper read the dead screen is for. Each row shows a one-word threat/scaling tag (`burst`, `scales`, `engage`, `hook`, `bully`, `wombo`, `skirmish`…), and anyone snowballing lights up **FED** in red. Tags come from champion class + a curated sharpener for the highest-signal champs (Zed, Malphite, Yasuo, Vayne, Kassadin, Draven…). Rows stay compact: role · champ · KDA · gold · tag, with the team gold lead up top.

## v0.9.9
- **The Death Brief now shows on your MAIN monitor** — where the game actually is. It was landing on the secondary screen (it borrowed the champ-select board's "use the other monitor" rule, which is wrong for a fullscreen in-game HUD). It now finds the League game window and draws on that monitor, falling back to your primary — so it's actually in front of you when you die.
- **Packed with the whole game state.** The empty center is now a full live rundown of all ten players: role, champ, level, KDA, CS, fog-proof gold estimate, completed items, and who's dead — your row highlighted, the team gold lead up top. Alongside the respawn clock, the tempo verdict, your buy, the win read, the enemy to watch, next objectives, and the feed, the grey screen now hands you everything at once.

## v0.9.8
- **THE DEATH BRIEF — a fullscreen read of the whole game, the moment you die.** Being dead is the one time in League you can process information at zero cost, so Smiteless now fills it: the instant you die, a **see-through overlay** fades in over the whole screen with a giant **respawn clock**, the **one tempo verdict** for what your death just did (*"Baron up now — you're too dead to contest, GIVE it, meet mid for grubs"*), **what to buy on respawn** for your current gold, the **win read**, the **scariest fed enemy** to watch, the **next objectives**, and a **feed of what you missed** while grey. It vanishes the instant you respawn. Toggle: **Settings → Death brief**.
- **The center stays clear** — a chroma-key hole makes the middle of the screen fully transparent *and* click-through, so you keep watching the fight through the brief and keep full camera control while dead. It's the calm, high-information version of "follow the action."
- **100% read-only, no automation.** It reads the live-client feed and shows you what's true — it never moves your camera or sends a single input to the game (that would be the automation Riot bans for; not happening). Runs in-game alongside the item widget, on your game monitor, never stealing focus.

## v0.9.7
- **Pick-order swap now targets an exact slot — 1st through 5th, not just first/last.** Settings → AUTO PICK-ORDER SWAP is now a row of slots: pick **4th** or **5th** to sit near the end of the pick order (great for counter-picking) without insisting on dead-last, or **1st** to lock a contested champ early. It accepts any incoming swap that moves you *closer* to your chosen slot and asks for one otherwise; a slot past your lobby size just means last. Old "first"/"last" settings carry over automatically.
- **The Profile page resizes properly now — maximize actually uses the space.** It was rendered at a fixed width and stranded top-left when you enlarged the window (header and body even drifted out of alignment). It now scales to fill the current window width, centered, so maximizing enlarges the whole page cleanly instead of leaving a broken-looking gutter. Clicks (expand a game, open a player) stay pixel-accurate at any size.

## v0.9.6
- **One-click login now has a password path too — pick an account, it fills the Riot login for you.** Profile page → **⚡ Log in** opens a popout: add each account's username + password once (stored **DPAPI-encrypted** on this PC, never in plaintext, never on the clipboard), then click one and Smiteless brings up the Riot login window and drops your credentials straight into the fields. It finds the username/password boxes by reading the login page's accessibility tree (UI Automation) and injects the text as keystrokes, so it works even though Riot's page won't let anything paste into a password box.
- **Why this exists alongside the no-password switcher:** the session switcher (v0.9.5) breaks the instant you click *Sign out* in the client — Riot revokes that session server-side, so the saved cookie is dead and you land back on the login screen. If you're someone who logs out and back in, the password autofill fits how you actually play. Honest limits, spelled out in the popout: a fresh login can still trip a Riot **captcha or MFA email**, and nothing can auto-skip those — that's Riot's risk engine, not Smiteless.
- Safety: it refuses to fill while you're already logged into a game, and it confirms an actual login form is on screen (not the client home) before it types a single character.

## v0.9.5
- **ONE-CLICK RIOT LOGIN — all your accounts, one tray menu.** Tray → **Riot login** → pick a name, and Smiteless closes the Riot/League clients, swaps in that account's saved session, and relaunches League already logged in. **No passwords, ever**: it snapshots the "Stay signed in" session the Riot Client itself keeps on disk (the same proven mechanism as the big account switchers — password login via the local API has been dead since Riot added captcha). Snapshots are DPAPI-encrypted, so only your Windows user can read them.
- **Setup is once per account:** log in with *Stay signed in* ticked → Settings → **ONE-CLICK RIOT LOGIN** → *Save current login* (the name box pre-fills with the account's Riot ID when the client's open). Saved accounts also join your mastery pool automatically, so "good this game" already knows your smurfs' champs.
- It refuses to switch while you're in an actual game, and it re-snapshots the account you're *leaving* on every switch — Riot rotates session cookies each login, so your saved sessions stay fresh instead of quietly expiring.

## v0.9.4
- **The Profile is a whole new page.** Not a re-skin this time — a new board, drawn from scratch: a full-bleed splash of your main behind your name in real display type, your rank / record / KDA as chips, the average-score ring wearing its letter grade, your last ten games as form bars, and the LP trend as a live spark. The old cramped header card is gone entirely.
- **PATTERNS — Smiteless now tells you WHEN you win.** A new out-of-game brain mines your own match timestamps for the habits behind your winrate: whether the queue after 11pm is robbing you, whether you tilt-queue straight after a loss, whether marathon sittings turn on you after game 2, whether you win the long games or the fast ones. It only speaks with a real sample (5+ games on the split) and a real gap (12+ points off your overall winrate), and every claim carries its receipt (`wr% · games`) right on the row. Nothing is guessed; if your history doesn't prove it, the panel stays quiet.
- **PERSONAL BESTS.** Your records from the loaded games, each with the game as proof: best game (score + grade), best KDA (a deathless game reads PERFECT), most kills, longest win streak, fastest win.
- **Stat tiles with a pulse.** Winrate, KDA, kill participation, CS/min and damage share each get a tile with a big Bahnschrift numeral and a per-game sparkline underneath — you can see a stat trending before you could ever feel it.
- **Your champion pool is splash art now.** Six portrait cards with face-centered art, winrate in large type, games and average score on the card, a winrate bar along the base.
- **Match rows show your item build.** Every recent game now carries its full six-slot build as icons on the row, op.gg-style, next to grade, role, verdict and pace stats. Rows got taller and calmer; wins and losses tint their own cards.
- Match data now remembers when each game was played (needed for PATTERNS) — the first profile open after this update refetches your recent games once, so give it a few extra seconds.

## v0.9.3
- **DUSKFALL — the whole UI, redesigned from scratch.** v0.9.1 unified the palette but kept its colors, so every window still looked like it always had. This time the things your eye actually keys on changed: the ground is now **violet ink** instead of blue-grey, the accent is a **hot ember amber** instead of muted gold, and a new **arcane cyan** owns everything live — timers, win%, sparklines — so identity and telemetry never fight over one color again. Full spec: `docs/UIDESIGN.md`.
- **Numbers finally look like instruments.** Every header, champ name, score, timer, win rate and KDA is now set in Bahnschrift (the DIN-style face that ships with Windows 10/11) — the HUD reads like a cockpit, not a spreadsheet. Body text also grew from 8–9pt to 10pt.
- **Railed cards everywhere.** Flat rectangles are gone: every surface is a rounded card carrying a 3px state rail — cyan for your team, red for the enemy, ember for *you*, green/red for results, amber-warning on the Riot-key bar. Grade badges (S–F), AUTO chips and rune tabs are pills; import is the one ember button in champ select.
- **One design system, enforced.** `core/smiteskin.py` is now a real token module (colors, type scale, spacing, shared widgets) and not a single window declares its own hex or font anymore — including the update dialog, and including a second frozen copy of the old palette we found hiding inside the widget's renderer. Drift is structurally dead.
- Built by a four-seat council — the Illuminator (boards + champ select + profile card), the Machinist (tempo widget), the Archivist (settings + patch notes), the Chronicler (profile chrome + key bar) — on a shared spec, one surface each.

## v0.9.2
- **Your profile now opens without the League client running.** The client was only ever needed for one thing: asking the LCU who you are. Smiteless now remembers that answer whenever the client is open, so from then on the Profile window works entirely off the Riot Web API — rank, match history, grades, session read, everything — game closed. Just open Profile from the tray whenever you feel like looking. (One-time note: it learns who you are the next time the client is open; after that, never again. If you ever log into a different account, it re-learns on the next client sighting.)

## v0.9.1
- **One skin, every window (council pick: the Naturalist, 27/70 Borda points from 14 ballots).** Smiteless's five windows had five hand-copied palettes that quietly drifted apart — Profile's background was a different black, Settings had its own red, the widget's header its own panel tone. All colors now live in one module (`core/smiteskin.py`) and every window draws from it, so the app finally reads as one product — and can never drift again.
- **The white title bars are gone.** Profile, Settings, and Patch Notes keep their real Windows title bars (drag/snap/minimize all intact) but Windows 11 now paints them Smiteless-black with a matching border — the single biggest "why does this look off" fix, done natively with zero custom chrome.
- **The widget header stops dressing like a title bar** (judge's amendment, from the Skeptic/Systems-Thinker consensus): the strip stays — it's the drag handle and holds the live controls — but only the gold ◆ keeps its color at rest; the wordmark, mute note, and ✕ sit muted and brighten under your cursor, and the volume slider appears only while you're hovering the widget. Mid-game the HUD is pure data.
- **The Riot-key bar only shows up when it has a job.** With a valid key the overlay board floats clean; the bar (and its paste/save controls) returns on the next launch after the 24-hour dev key expires or goes missing.

## v0.9.0
- **The UI now fits your screen — every screen.** All the live surfaces (the scoreboard, the champ-select panel, the in-game widget and its legend) are now resolution-adaptive: they're drawn for a 1080p-tall screen and shrink proportionally on anything shorter — swap the game to a lower display resolution mid-session and the overlay shrinks in step, on the monitor it's actually sitting on. Nothing ever upscales, so text stays crisp on big displays.
- **The champ-select panel balances itself beside the client.** The tall panel used to top-align to the League client — and once it grew taller than the client, its bottom ran off the desktop. It now centers itself vertically against the client's span and hard-clamps fully on-screen (scaling itself down first if it's taller than the monitor), and it re-balances whenever its height changes as picks come in. Drag it anywhere and it respects your placement for the rest of that champ select. Click targets (import, hover-pick, rune tabs) track the new scaling exactly.

## v0.8.0
- **LEGEND — the widget now explains itself.** A tiny `?` now sits in the widget's header. Click it and a reference card opens beside the widget decoding everything the HUD can say: every tempo phase **in its real color** (so "teal = FREE, red = GIVE" is learned from the exact swatch you'll see live), the intel glyphs (`⌖` jungler tracker, `◎` gank window, `⚠` power spike, `⌂` recall read, `★` GHOST), the WIN% and objective chips, the item-line tags, and the RESPAWN card. It opens itself exactly once — on your very first launch, while the widget says "waiting for a live game…" — then never again uninvited; after that it's there whenever you forget what a row means. The live HUD itself is untouched: no per-row clutter, no new hover traps, nothing that can eat a click mid-fight. (Council pick: the Player's design won over hover tooltips — you never mouse over a HUD mid-game, so the vocabulary is taught once in downtime instead.)

## v0.7.0
- **FREE — the free-objective alarm. The enemy jungler dies, and the game tells you what it just handed you.** When a drake/grubs/herald/baron is coming and the enemy jungler is dead too long to contest it, the tempo card turns teal and fires early and loud: `FREE drake 0:18 — their Kha'Zix dead 40s · yours 39s — path bot river NOW, ward, take it`. It's the one enemy-position read the live client can actually PROVE — a respawn timer isn't a guess — fused with the objective schedule and the same fight math the coach uses. It only fires when you can reach the pit AND you'd still win the fight with their jungler removed, so it can never walk you into a losing 4v5. This is the highest-EV repeated decision in the jungle (an uncontested drake is ~+8% win rate, soul ~85-90%), and it recurs multiple times a game — the alarm makes sure you never leave one on the table again. Toggle: **Settings → Free-objective alarm**. (A live-but-unseen jungler is deliberately never called "free" — cross-map traverse is faster than securing an objective, so that stays the "respect the gank" read's job.)

## v0.6.0
- **ONE BRAIN — the win% and the coach now share the same eyes.** The live win read used to count only finished items it could SEE, while the TAKE/GIVE tempo verdict used the fog-proof economy estimate — so the widget could say "WIN 88%" directly above "GIVE drake (−8k)". The win% now runs on the exact same per-player power model as the fight math (score-estimated gold + XP, immune to fog-of-war item staleness) plus drake/baron swings, recalibrated so a one-item team lead reads ~68% instead of a flat 50%. Same chip, same card — they just can't disagree anymore. (The GHOST gold trace reads from the same model too.) Verified against the old engine: the fight math itself is unchanged to the decimal.

## v0.5.1
- **Refinement pass (council audit).** Fixed a real bug: a live-data hiccup could silently kill the GHOST race for the rest of the game (a variable-name collision in the widget's poll loop). Polish: the RESPAWN countdown is now neutral white so it never wears the same gold as a 50/50 directive; muted text on the widget matches the board's brighter grey (it was near-invisible at ghost opacity); routine "farm window" reminders are a quiet plain line again instead of a bordered decision card; the objective named by a TAKE/GIVE/EVEN verdict no longer repeats as a timer chip below it; Settings labels caught up with reality ("Matchup lane tips (written guides)" — they haven't been AI since v0.2.94 — and the volume slider now says it controls chime + voice + fanfare).

## v0.5.0
- **RESPAWN — the death screen is now a plan.** The moment you die, the widget collapses to a single card: a ticking respawn countdown, ONE directive for when you're back — `DRAKE 0:38 — you make it, and you win it. Buy fast, path bot river` (teal = go, red = don't, gold = neutral) — and the next item to buy, since you're literally standing in the shop. It reuses the tempo engine's fight math, and here the travel model is at its most honest: everywhere else "time from base" is an estimate, but on the death screen you really are at the fountain. When nothing major is coming, you get your role's productive default (reset camps / shove the wave) instead of dead air. The instant you respawn, the normal HUD snaps back. Toggle: **Settings → Respawn plan**.

## v0.4.0
- **GHOST — race your own best game, live.** Smiteless now learns a "ghost" from your single best-graded game on each champ+role (grade A or better): its minute-by-minute CS and gold pace, and its death count. Next time you're on that champ, one quiet line in the in-game widget races you against it like a speedrun timer — `GHOST · CS +8 · deaths 1/2 · +340g` — glowing gold while you're ahead, dimming silently when you're not. Crossing 10:00 flashes your CS split vs the record; 15:00 flashes deaths. Finish ahead and you get the item-get jingle, a spoken "New record." — and the ghost gets faster. Your only opponent is who you were last week: ghosts are built purely from your own in-game performance, never rank or win/loss. First game on a champ sets the baseline. Toggle: **Settings → Ghost race**.

## v0.3.1
- **Matchup tips are quality-filtered now.** The written-guide scraper was showing raw user submissions — including salt stories, rants, and even slurs. Tips are now hard-gated: anything with slurs/abuse, toxicity/report/"1v1 after the game" rant markers, non-English text, or that reads as a personal game-recap instead of advice is dropped entirely. What's left is ranked by how much actual matchup guidance it contains. Sorry you saw that one.

## v0.3.0
- **Auto role-swap now fights to GET your role, not just accept one — the autofill escape.** If you get autofilled off a role you actually play, Smiteless immediately REQUESTS a position swap from whoever has one of your roles (and still accepts any offer that lands you on one). It only ever moves you ONTO a checked role, never off it, and won't spam the same teammate. Set your roles in **Settings → Auto role swap**. Getting your main role every game is one of the biggest quiet win-rate edges there is.

## v0.2.99
- **The champ-select ally scout is now always visible.** Clean lobby or not, the panel shows a compact team line — `team: Bob G2·B  Ann S1·C·2L` (name, rank, grade, loss streak) — so you can see the scout working every lobby, not only when a DODGE READ flag fires. (For the record: ally names in champ select come through the Riot Client's chat service — the same bypass Porofessor uses — since Riot only anonymized the client UI, not the chat backend. Enemies remain genuinely hidden until loading; no tool has those.)

## v0.2.98
- **Ally scout while you can still dodge.** Champ select now identifies your four teammates (via the Riot Client, the same method Porofessor uses) and scouts them immediately — if someone's on a 3+ loss tilt streak or grading F, a **DODGE READ** line appears on the panel *before* you're locked in. Enemies stay hidden until loading (Riot anonymizes them).
- Refreshed the project README.

## v0.2.97
- **The take/give math no longer trusts fog of war.** Enemy items only update when they've been SEEN — so an enemy farming in fog looked poorer than they were, biasing calls toward "take." Each player's power now uses their **estimated earned gold from scores** (CS, kills, assists — which update for everyone regardless of vision), with visible items as a floor. A fed-but-unseen enemy team now correctly reads as a GIVE.
- **Contest calls fire earlier.** The TAKE / GIVE / 50-50 verdict now lands **45 seconds before spawn** (was 30) — while you can still rotate on it, not as the fight starts. Decision thresholds retuned for the new power scale.
- **Bans: your lane comes first.** Your own champ's counters now weigh ~2× a teammate's in the ban ranking — but a champ that dumpsters TWO teammates still outranks a champ that's merely annoying for you, and pick-rate weighting stays (no more banning 4%-pick niche counters).

## v0.2.96
- **The in-game widget is now a real HUD, not a wall of text.** The body is fully redrawn (same rendering style as the main board): the tempo directive is a **color-coded card** (red = give, green = take, gold = decide), objective timers are **chips** (gold when something's UP), intel rows are aligned with proper glyphs, and the item advice sits visually quieter below a divider. Numbers got one format — "GIVE baron (−23k · 2 down)" instead of three different spellings of the same fact — and a fed enemy is announced once, not twice. Same information, drawn like it matters.

## v0.2.95
- **"Good this game" now enforces the 12k-mastery climb line — across ALL your accounts.** Champ suggestions are gated on 12,000+ mastery **points** (was mastery level 5+), pooled across your main and every registered smurf (max per champ), with 30k+ comfort picks ranked first. Sub-12k champs are never suggested — if nothing qualifies for your role it says so rather than pushing an off-mastery pick. The champ-select hover warning and the profile's CLIMB LEAK check use the same all-accounts pool, so a champ you have 100k on your main never warns on the smurf.

## v0.2.94
- **Matchup tips are now REAL written guides, not AI.** Lane tips are scraped from counterstats.net — actual prose counter-advice written by MOBAFire guide authors for the exact enemy champion, preferring tips written by players of YOUR champion (the true matchup POV), with vote-ranked general tips as backup. Loads in ~1 second (the old AI generator took 60-120s and sometimes failed), cached per patch, deterministic. The AI path survives only as an offline fallback. **Junglers get matchup tips now too** (they were excluded entirely).
- **THE CLIMB SYSTEM — research-backed fast-climb discipline, built in.** Deep-dive into what actually makes people climb fast (sources: iTero's 1M-game mastery study, Deng et al. ACM CHI PLAY 2024 on 597k matches, loltheory's 100k-game break analysis):
  - **The 12k-mastery rule.** Picks under ~12,000 mastery points win ~44%; past ~20 games they cross 50%+ (and the effect is BIGGEST in jungle). Champ select now warns you live when you hover a sub-12k pick, and your profile flags sub-12k champs you've been spamming.
  - **The 2-loss stop rule.** Players who break ~30 minutes after 2 straight losses win ~3% more; tilted sessions bleed 10-15%. After 2 consecutive losses your profile now leads with STOP RULE instead of a pleasantry, and the tilt flag trips at 2 losses (was 3).
  - **Pool concentration.** A +5% champ-mastery win rate literally halves games-per-rank (160→80). If your recent games are spread across 6+ champs, the profile tells you to commit to 2-3 — with the EV-ranked coach picks right next to it.

## v0.2.93
- **Fixed a wrong Elder call.** The timers said "Elder" once 4 drakes had died *in total* — but Elder only comes after **one team's** fourth (soul). A 3–2 drake split now correctly shows the next **Drake** (your soul point!), not a phantom Elder.
- **First baron is no longer an alarm.** Nobody rushes baron on spawn — the tempo engine now treats the first spawn as a posture objective: no recall countdowns, no urgency, just "posture, don't force / punish them for starting it." It also prefers a drake/elder within the next ~4 minutes over first baron (your soul-point drake beats a baron nobody's taking). Once a baron has actually died, respawns get the full scheduling again — that's when it decides games.
- **Widget slimmed to game-winning info.** The tempo "why" line now only appears when there's a decision to justify (take/give/50-50/force/too-far) — routine farm/base/rotate lines stand alone; item advice trims to the 2 most important lines during a game (full list outside games); and the bottom threat/source footer is hidden in-game. Roughly a third fewer lines on screen, nothing decision-relevant removed.
- Fixed players already-arrived at a live objective being told they're "too far" (reachability now allows the real ~25s contest window once something is up).

## v0.2.92
- **Volume slider on the in-game widget.** A small slider in the widget's header now controls the voice callouts + drake chime live: drag it and the new level applies instantly, plays a short preview so you can set it by ear, and saves back to Settings. 0 = silent; the ♪ button still mutes everything for the game.

## v0.2.91
- **New voice: Salli.** The tempo callouts are now spoken by the much nicer Salli voice (AWS Polly, via ttsmp3.com's free service) instead of the robotic Windows one. Each phrase is fetched once and cached as a local MP3, played through Windows' built-in decoder — no extra installs. If you're offline it falls back to the old local voice, so callouts never go silent.
- **The in-game widget got a glow-down.** Same information, less in your face:
  - **Adaptive transparency** — it ghosts to ~84% opacity while nothing needs you, solidifies on its own when a call-to-action is up (take/give/force, gank window, spike alert), and goes fully opaque under your cursor.
  - **Macro first** — the tempo directive and objective timers now sit at the top; item advice moved below the line as smaller reference text (it no longer out-shouts the "rotate now" call).
  - Tighter paddings and type all around — same content, meaningfully smaller footprint.

## v0.2.90
- **Auto-ban now waits until the last ~12 seconds of the ban phase** before locking. Every extra second lets more teammates hover their picks, and the team-wide ban math recomputes on every poll — so the ban that finally locks is based on the most complete picture of your draft. (Fires immediately if the phase clock can't be read — it will never miss the ban.)
- **The Tempo engine now knows what lane you're in.** It detects your role live and reshapes the whole schedule around your position on the map:
  - **Rotate deadlines use YOUR lane's distance to the pit** — a bot laner is ~12s from drake, a top laner ~35s; the old one-size-fits-all fountain math is gone (recall deadlines still use the fountain path, because that's where backing puts you).
  - **Laners get wave discipline built in:** "CRASH your wave → rotate" — it will never tell you to walk away from a slow push, and the farm window reminds you to crash before leaving.
  - **"Too far" honesty + TP awareness:** if you physically can't reach the fight in time (top laner, drake spawning now), it stops pretending — **"SHOVE for the cross-trade"** (take plates/camps while they posture), or **"SHOVE — then TP to drake"** if you're holding Teleport. New spoken callout to match.
  - Junglers keep the original pathing-flavored schedule, now with a more accurate on-map rotate deadline.
- **GAME PLAN is now WIN CONDITION** — and it opens with the read that actually decides games: the **scaling verdict**. It compares both comps' power curves and headlines *when* you win: "YOU OUTSCALE — don't coinflip early, hit 3 items" vs "THEY OUTSCALE — your win is EARLY: snowball and end." Only claims it when the gap is real; the damage-split / frontline / engage reads follow behind.

## v0.2.89
- **Mastery now has its own color scale (it used to lie).** The mastery text was inheriting the color of the player's *recent win rate* — so a 209k-point main could show "worse" (brown) than someone's 23k dabble (green) purely because of their last 10 games. Mastery is now colored by champ comfort itself: **gold = their MAIN (100k+ pts), green = comfortable (30k+), plain = knows it (8k+), dim = barely played**, and **red "off-champ" = first-timing it**. The recent W/L keeps its old green/tan/red coloring, and the legend spells out the scale.

## v0.2.88
- **THE disappearing-widget bug, actually found.** Right-click anywhere on the widget was bound to *close it* — in a game where right-click is the move command. Any move-click that drifted onto the widget silently killed it, which is why it "randomly" vanished for months no matter how the game-over detection was tuned. Right-click (and Escape) no longer close the widget — only the ✕ button does.
- **Three more layers so it can never come back:** (1) while the actual game process (League of Legends.exe) is running the widget is **immortal** — it ignores client-API blips entirely; (2) it re-asserts its always-on-top status every few seconds so the game window can't bury it; (3) every close now writes its reason to a log (`~/.claude/cache/smiteless_widget.log`) — if it ever disappears again, we'll know exactly why instead of guessing.
- **Bans are now ranked by expected value, ending the "always ban Zac" loop.** A ban's worth = how hard the champ counters your team **×** how likely you are to actually face them (their live pick rate in that role). A brutal-but-niche 4%-pick counter now ranks below a popular counter you'll meet every third game. Multi-lane threats still stack, and everything else (fallbacks, auto-ban) rides the same list.

## v0.2.87
- **Fixed the in-game widget randomly disappearing mid-game.** The "is the game over?" check counted poll ticks but was tuned as if ticks were 5s when they're ~1s — so a **4-second** client hiccup (a teamfight lagging the client and the live-data port at once) could close the widget mid-game. It's now wall-clock based: ~25s of confirmed non-game (or 3 min of unreachable client) before it even considers closing, and it always asks the live game directly first — if the game answers, the widget stays.
- **Fixed the voice callouts being completely silent in the installed app.** The speech renderer worked in development but died instantly in the shipped (windowed) build due to a Windows process-handle quirk — so no WAVs were ever created. Now fixed and verified under the same condition.
- **"Tempo online."** — the widget now says a short hello when it first picks up your game, so you know immediately that audio is working instead of discovering silence at first drake.

## v0.2.86
- **The Tempo engine now talks.** Short spoken callouts fire exactly when a window opens: **"Base now."**, **"Rotate to dragon."** (per-objective), **"Take it — you win this fight."**, **"Give it — trade elsewhere."**, **"Fifty fifty — only with vision."**, **"Force now — numbers advantage."** Voiced by Windows' built-in speech engine — free, offline, rendered once to WAV and cached, played at your existing widget volume. It only speaks on a *phase change* (never repeats, 6s global cooldown, anti-flap guard), the in-game ♪ mute button silences it along with the drake chime, and there's a separate "Tempo voice callouts" toggle in Settings.

## v0.2.85
- **Ban suggestions now consider the whole team's hovers, not just yours.** GOOD BANS aggregates the counters of every champ your team is hovering or has locked (including you) and ranks enemy champs by total threat to the draft — a champ that beats two of your lanes now outranks one that only edges yours, so the ban adapts as teammates hover instead of always showing your champ's #1 counter. The shown % is the most-countered teammate's win rate into that champ. Falls back to your champ's counters, then to the meta ban list, if there's nothing to aggregate. (Auto-ban uses the same improved list.)

## v0.2.84
- **THE TEMPO ENGINE.** The in-game widget now runs a live objective-setup director — the single highest-leverage macro system in the game, built on real research (8M-game Diamond+ study: 1 drake at even gold = +8% win rate, 2 = +16.9%, full grubs = +11%, and the dragon-soul team wins ~85–90% of games). Games are decided in the ~90 seconds *before* each objective, and now that window is scheduled for you:
  - **FARM window** — how long you can safely farm, with your exact recall-by and arrive-by deadlines counted down, walked back from the next spawn using your **live movement speed**, recall time and homeguard.
  - **BASE window** — the last moment to recall so you arrive 30s early with items.
  - **ROTATE** — when to start walking, and what setup to do (pit ward + river control).
  - **TAKE / GIVE / 50-50 verdict at the spawn** — computed from **death timers** (the real per-level respawn formula, including whether a dead enemy respawns *and walks back* in time to fight), **item gold** and **XP-as-gold** for all ten players. If you win the fight, it says take; if you don't, it names the trade to make instead. It never lets you coinflip blind.
  - **FORCE windows** — the moment an enemy dies with a long respawn, it tells you the numbers (5v4 for 23s) and to cash the advantage.
  - **SOUL POINT escalation** — at 3 drakes either side, the next drake is flagged as the ~85–90% game-decider it is.
  - **Elder tracking** — the objective timers now roll over to Elder after the 4th elemental (6:00 spawn/respawn), which they previously just dropped.
  - Toggle in Settings ("Tempo coach"). Every game constant verified against the wiki this week: baron 20:00, grubs 8:00 one-spawn, herald 15:00–19:45, drake 5:00/5:00, elder 6:00, the full death-timer table, recall 8.5s, homeguard 80%→150%.

## v0.2.83
- **"Play more / ease off" champ advice now uses real statistics.** It no longer crowns a 3-0 champ your best pick. Champs are ranked by a **Wilson score** — a confidence-adjusted win rate that discounts small samples so a wide 3-0 can't beat a tight 40-25 — blended with **how well you actually play the champ** (your average game score on it), and a champ needs a real sample (5+ games) before it can drive advice. So a proven main beats a lucky streak; "ease off" only fires when it's statistically confident a non-main is a loser (never off a 4-game fluke); and a champ you *main* on a rough patch is still flagged as a slump, not a pick problem. Each suggestion now shows the games it rests on (e.g. "play more Graves 61% (40g)"). The season-wide version also factors in your performance now, not just W/L.

## v0.2.82
- **Pick-order swap now has a simple "Accept any" mode.** In **Settings → Auto pick-order swap**, pick **Accept any** to just auto-accept every incoming pick-order swap request — no direction, no asking. (First pick / Last pick are still there if you want Smiteless to actively work toward an end of the order.)

## v0.2.81
- **Auto pick-order swap (counter-pick automation).** New in **Settings → Auto pick-order swap**: choose **Last pick** and Smiteless works your spot in the pick order as late as possible so you can counter-pick — it accepts a teammate's swap offer that moves you later, and requests one otherwise. **First pick** does the opposite (swap early to lock a contested champ). Off by default. (This is the pick-order swap; the v0.2.80 role swap is a separate setting.)

## v0.2.80
- **Auto-accept role swaps.** New in **Settings → Auto-accept role swap**: check the role(s) you're happy to play. When a teammate offers a role (position) swap in champ select that would put you on one of them, Smiteless accepts it for you. It **only ever moves you ONTO a checked role, never off one** — so a jungle main who got autofilled support auto-takes the jungle swap, but never gets swapped off jungle. None checked = off. (This is the assigned-lane swap, not a champion trade.)

## v0.2.79
- **The player grade now reads how you actually PLAY, not your win/loss.** It scores each of your recent games against your role's benchmarks — CS/min, kill participation, damage share, deaths, vision (the same engine as your post-game review) — and averages them. Win rate is only a light tie-breaker now.
- **Why this matters:** if you're a strong player grinding on a low/off-role account, or just lost a few playing off-champs, your fundamentals still show through — you'll grade a solid **B**, not a bogus **F**, even mid-losing-streak. It figures out your skill from your gameplay, not from your account. Meanwhile someone who's genuinely inting (bad CS, no participation, feeding) still grades low even if they got carried to a win.
- (No account-peeking — the grade is read purely from the games in front of it. Detailed per-game stats build up as your recent matches get scanned; until then it falls back to the old win-rate + KDA read.)

## v0.2.78
- **Ban ideas (before you pick) are now live op.gg data**, not a hardcoded list — the highest win-rate champs in YOUR role this patch. No more banning off-meta champs.
- **Player grade is now a real-stats skill read.** It's driven by win rate (your season ranked W/L when available — a big sample), with KDA and current form as supporting factors. Rank tier is ignored, so a Silver on a 65% climb grades higher than a Diamond who's feeding.
- **New GOOD PLAYER tag** on any player graded S or A — spot the carries (and carry threats) at a glance.
- **Gank ratings are now purely champ-vs-champ matchup** (plus your kit and live game state). Player form/skill no longer muddies the lane read — that's what the grade + GOOD PLAYER tag are for now.

## v0.2.77
- **Auto-ban.** New **AUTO** toggle next to GOOD BANS in champ select (also in Settings). When on, it locks the top recommended ban on your ban turn — and never bans an already-banned champ or one a teammate is hovering.
- **Ban ideas now show during the ban phase.** Since you ban before you pick, GOOD BANS now shows high-priority solo-queue bans when you don't have a champ yet (instead of "hover your champ for ban ideas"); once you hover, it switches to your champ's hardest counters.
- **QoL:** the current version number now shows in the Settings header.

## v0.2.76
- **"Good this game" now populates the moment champ select opens** — you no longer have to hover a champ (or wait for enemies to lock) to see it. It shows your mastery-5+ champs for your assigned role right away, and refines as enemies lock in.

## v0.2.75
- **The scout now loads everyone at once.** All 10 players are scouted in parallel instead of one at a time, so the board fills in roughly as fast as a single player used to take (~10× quicker) instead of trickling in. (Allies are also prioritized first.)

## v0.2.74
- **Rune sets now switch instantly.** Clicking one of the 3 rune-set tabs in champ select used to lag up to ~2 seconds before it updated — now it's immediate.
- **Each rune set carries its own summoners.** Picking a set now also shows (and imports) the summoner spells that go with it, not just the runes.

## v0.2.73
- **Removed the gank-tuning dials.** The "streak influence", "gank decisiveness (threshold)", and "champ kit in gank rating" settings are gone — they caused more confusion than help. The gank ratings now always use the tuned defaults, and any custom values you'd set are reset back to default.

## v0.2.72
- **Favourite picks now use a dropdown.** In Settings, pick a champ from a searchable dropdown (type to filter), choose a role (or "any"), and hit **+ Add** — no more typing names by hand. Your list shows below with **Remove** and **↑/↓** to set priority order.

## v0.2.71
- **Game plan now shows in champ select too.** As soon as the enemy team locks in (draft), the docked champ-select panel shows the same GAME PLAN box — read their comp and plan your win condition before the game even starts.
- **Player grades in the queue read.** The in-game winners/losers-queue chip now also shows each team's average letter grade (e.g. "WINNERS QUEUE 80% vs 30% · grades S vs F") — a KDA/form-based second opinion next to the win-rate read.

## v0.2.70
- **Post-game review on your latest game.** Your most recent game now gets a short, data-driven review pulled from Riot's match timeline: where you fell behind vs your laner (gold@10/@14), your CS at 10:00 vs benchmark, and your worst death window. It's rule-based — no AI, no tokens, no waiting — and shows up with that game's tips in your profile.

## v0.2.69
- **Auto game-plan card.** The in-game board now shows a "GAME PLAN" box: 2-3 blunt win conditions read from both comps — the enemy's damage split (rush armor/MR), whether they lack a frontline (dive their carries), and how much engage each side has (respect all-ins vs play for picks).
- **First scuttle timer.** The in-game widget's objective timers now include the first Rift Scuttler (2:55) — the early jungle tempo anchor, with the usual soon/urgent cues.

## v0.2.68
- **Recall / power-spike coach.** The in-game widget now reads your live gold + items and tells you when to back for your next spike: **"BACK now → finish Trinity (spike)"** when you can afford it, **"wait ~200g → …"** when you're close, or how far off you are otherwise. It subtracts components you already hold, so it's the real cost to *finish* the item — no more backing for a longsword when 8 seconds of farm gets you a whole item.

## v0.2.67
- **"Good this game" now only suggests champs you're mastery 5+ on** (mastery 7+ first). It won't recommend a champ you've barely touched — if none of the role-appropriate picks are ones you're M5+ on, it just says so instead of guessing. Pooled across all your accounts, same as before. (If the client can't report your mastery, it falls back to the old meta suggestions rather than showing nothing.)

## v0.2.66
- **Mute the drake chime mid-game.** The in-game widget now has a **♪** button in its header — click it to silence the 45/30/15s drake cues for the rest of the game (e.g. when your jungler is never going to contest it). It shows a struck-through red note while muted; click again to turn it back on. Resets each game, and Settings still has the permanent on/off.

## v0.2.65
- **Fixed the lane tip showing a raw "401 authentication" error.** A transient auth blip from the AI tip generator was being treated as the tip text and cached, so it showed every game. Those errors are now detected and never shown or cached, poisoned cached tips self-heal, and a bad tip just quietly regenerates next game.

## v0.2.64
- **Player rating is now about how you're *playing*, not your rank.** The S–F grade is driven by your recent win rate, KDA (are you carrying or inting), and hot/cold streak — rank is ignored entirely. A Silver stomping 20/0 game after game shows up as a gold **S** God-Mode player; a Diamond who's been feeding is a black-hole **F**.

## v0.2.63
- **Player rating is clearer.** The S–F grade now sits right next to each player's name (so it's obvious it's rating the player), the bottom legend spells out what it means, and it no longer collides with the duo/premade dot.

## v0.2.62
- **Player ratings on the in-game board.** Every player now gets a grade (S–F) from their rank, recent form, and comfort on their champ. A smurf/sicko lights up with a **gold glowing banner and an S**; someone tanking or way out of their depth goes **dark red with an F** — spot the carry and the griefer at a glance, on both teams.
- **Fixed the Flash key reverting to D.** Settings are now saved by merging onto the existing file, so changing one setting can never quietly reset another (Flash-on-F now sticks).

## v0.2.61
- **The champ-select panel now appears as soon as champ select opens** — it used to stay hidden until you hovered a champion. Right away it shows your assigned role, your team's roles, bans, and suggested picks; runes/build fill in once you hover.

## v0.2.60
- **"Good this game" now pools familiarity across all your accounts.** It remembers each account you log into and combines your champion mastery across your main and smurfs, so a champ you main on one account counts as familiar on the others. Manage the list in **Settings → Your accounts** (add smurfs you haven't logged into recently by Riot ID).

## v0.2.59
- **"Good this game" now factors in champs you actually play.** It reads your champion mastery from the client and surfaces picks you're familiar with first, so it won't tell you to first-time some champ you've never touched. If you have too few known picks for the role, it still fills in with strong meta options.

## v0.2.58
- **Click a "Good this game" face to hover it** in champ select. It selects (hovers) the champ for you — it never locks — and the panel updates to that champ's runes and build. Handy for trying suggestions quickly.

## v0.2.57
- **This page.** Added a **Patch notes** window (right-click the tray → Patch notes) so you can see what changed each update. It shows the notes for your installed version and pulls the very latest from GitHub when you're online.

## v0.2.56
- Fixed the **Deeplol** right-click link. It was using the wrong region code, so Deeplol said the account didn't exist. Now it opens the profile correctly, like the other sites.

## v0.2.55
- **Rune-set picker in champ select.** op.gg often lists more than one good rune page — the panel now shows small tabs (e.g. `1 · 54%  2 · 49%`). Click one to switch which runes are shown, and Import / auto-import writes that set.
- **Favourite picks.** Set an ordered list of your go-to champs in Settings → Favourite Picks (add a role like `Kha'Zix, jungle` to limit it to that role). In champ select the panel shows your top still-open picks in priority order. Recommend-only — it never hovers or locks for you.
- **Fixed the ⬜ square symbols** on the overlay (the `★ gank` chip, the dodge banner, the coach lines, and the ✓ marks) — they render properly now.
- **Better duo detection.** If the first player scan misses someone (a rate-limit hiccup), it now re-checks a little later and fills in any duo/premade markers it missed.
- **Profile window closes on its own** when you enter champ select, so the champ-select panel and in-game overlay take over cleanly.

## v0.2.54
- **Refresh button on your profile** — force a fresh pull when a just-finished game hasn't shown up yet.
- **Right-click any player's face** for a menu: open them on u.gg, op.gg, League of Graphs, Deeplol, or Porofessor (their live game), or copy their name. Left-click still opens their Smiteless profile.

## v0.2.53
- **Auto-import toggle** sits right next to the runes/summoners, so you can flip it in champ select.
- **Live gank sides.** Someone's always tagged the strong side and someone the weak side, and it shifts as the game goes on (deaths, level leads).

## v0.2.52
- No more blank "claude" terminal flashing on the loading screen.
- Champ banners now auto-focus the champion's face instead of a random slice of the splash art.
- More reliable jungle tracker.

## v0.2.51
- Rebuilt the jungle tracker so it reports a state every tick instead of going blank between events.
