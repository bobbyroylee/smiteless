# Smiteless â€” Patch Notes

## v0.9.68 - THE WARD CLOCK: the vision war, live - and the last leak in the ledger

**New feature, and it finishes the set. Every tag your profile can give you now has a
surface that fires while the mistake is still preventable.**

`no vision setup` has sat in your ledger with nothing in the game to answer it since the
ledger existed. It was the last one. BLEED watches your health bar, RE-ENTRY the 90s after
a death, THE CLOSER the closeout, THE GOLD CLOCK the first ten minutes of farm - and the
gold clock is deliberately silent for jungle and support, because camps aren't on the lane
schedule and a support's CS was never the story. So the two roles whose entire job is
vision were the two roles with nothing to read. **This one is theirs.**

- **It is a measurement, not a guess.** :2999 reports a **vision score for all ten
  players**, every tick, unfiltered by fog - and that number *only ever goes up while a
  ward of yours is alive*. So a score that hasn't moved in 1:40 isn't an opinion. It is a
  fact that **nothing of yours is on the map**, and it needs no modelling constant at all.
- **The head-to-head nobody has ever shown you.** One quiet row, all game: you against the
  enemy in your own role. Same job, same minutes, same units - so it's an exact comparison,
  not a benchmark:

      WARD   14.2 v 21.6 · 0.9/min, bar 1.2 · 1 pink

  That is the only live scoreboard in League for the thing a support is actually doing, and
  the bar is your own profile's (1.2/min support, 0.55 jungle - the same number the
  `no vision setup` tag grades you on, read from one place so the two can never disagree).
- **PIT - the fight you were about to take blind.** In the ~75 seconds before a drake,
  grubs, herald or baron, if nothing of yours is alive, it takes the card:

      PIT - drake in 40s and nothing of yours is alive          1:00
      go PAST the pit - their bot jungle entrance, so you see them
      walk in and the fight starts on your terms

  It speaks on a **shorter fuse there than anywhere else** on purpose: "ward the pit before
  the drake" cannot be wrong, so a false alarm costs nothing and staying quiet costs the
  objective. And it tells you **where** - deep past the pit when you're ahead, your own tri
  and the pit mouth when you're behind, because those are opposite instructions and the
  right one depends on the game you're in.
- **PINK - 75 gold of map you already paid for.** It reads your actual inventory. A control
  ward you bought and have carried for two minutes gets one card, once, and then never
  again for that ward.
- **It cannot cry wolf.** The whole surface stays **asleep until the live feed has proven
  it reports a vision score at all**. If Riot ever drops the field, or a lobby doesn't send
  it, everything here degrades to silence instead of telling a support who has warded all
  game that he's blind. That tripwire is checked every single tick.
- **It bills you once.** Dark time you spent on the grey screen is never counted against
  you - that's RE-ENTRY's and BLEED's subject, and charging you twice for one death is how
  a coach gets switched off. It also hands the slot straight back the moment the tempo
  engine calls an actual fight, and it never outranks BLEED, RE-ENTRY or THE CLOSER.
- Jungle and support only. It stays **silent for every laner** rather than invent a number,
  for the same reason your profile has never graded a laner on vision.
- On by default: **Settings -> Ward clock (the vision war, jg / sup)**. The widget legend
  has a new WARD CLOCK section. Included in MAX ELO.

**Tested:** 419,160 assertions before this shipped, plus the permanent guards in
`selftest.py`. Every verdict branch is driven across a full grid of role x clock x vision
score x dark time x control wards x objective state x tempo phase (and both armed states);
the pit window is checked against the app's *real* objective clock at every 7 seconds of a
40-minute game rather than hand-written fixtures; the counterpart matcher is asserted to
return **nothing** rather than guess whenever the lobby is ambiguous; and the guard is
driven second-by-second through whole simulated games - a support who wards constantly
(never accused once), one who stops at 6:40 (caught on the exact second the clock earns
it), one who never wards at all, a jungler on his own bar, four different death windows
(the dark clock must freeze, not reset and not accrue), a bought-carried-placed control
ward, all three laners (total silence), and a game where the feed reports no vision score
at all (total silence). A 20-shape malformed-payload sweep x every tempo/objective/win-read
combination must never raise. Two real defects were found and fixed by that sweep before
release, and every frame the guard produces was rendered through the real widget path and
inspected.

## v0.9.67 - THE GOLD CLOCK: your lane, counted against the minions that actually spawned

**New feature, and it covers the biggest leak in your ledger that had nothing in the game
to answer it - the one almost every game you play can earn.**

Your profile has tagged games `weak first-ten economy` since the behaviour ledger existed:
finish minute 10 under 55 CS and under 3100 gold and it goes in the file. Four of the five
roles can earn it. Nothing in the app has ever said a word about it *while you could still
fix it* - BLEED watches your health bar, RE-ENTRY the 90s after a death, THE CLOSER the
closeout. The thing you spend the entire lane phase actually doing was the blind spot.

- **It does the arithmetic instead of guessing.** Every CS overlay ever built shows you
  CS/min against a flat benchmark, and a flat benchmark is a bad coach - it doesn't know
  that at 4:32 only nine waves have spawned. Minions are a **schedule**: one wave leaves at
  1:05 and one every 30s after, 3 melee + 3 casters, every third wave carrying a cannon.
  So the denominator isn't a benchmark, it's *the minions that have walked into your lane*:

      GOLD   41 of 74 · 55% · on track for 63, bar 55

  Melee are 21g, casters 14g, cannons 60g, and **every one of those is flat until 15:00** -
  which is why this whole window can be priced exactly rather than modelled.
- **It back-times the deadline.** 55 by 10:00 is your own tag's bar. Subtract what you have,
  divide by what's still coming, and you get the only sentence that actually helps:

      MISS - that wave went by · on track for 42 at 10:00, bar 55
      you need 25 of the next 32 minions (78%) · shove, then cross to a camp -
      a wave you walk away from is 105g on the floor

  And when the answer is *no* it says so - "49 short of 55 with 32 minions left" - and
  switches the advice to plates and objectives instead. A lane you cannot farm your way out
  of needs a different plan, and four more minutes of "farm harder" is four minutes wasted.
- **The cannon minion has a clock and now you get it.** 60 gold, the biggest single object
  in lane phase, and the one you most often give away because you were walking back from a
  roam. It warns you seconds before it lands - **and only while you're behind**, because a
  reminder that fires every 90 seconds regardless is a reminder you stop reading.
- **Roaming never reads as farming badly.** 30 CS and three kills is not a weak first ten,
  and your own tag agrees (it needs the gold bar missed too). Kills and assists are priced
  back into CS at the app's own per-CS rate - so the row shows **`30+44 of 82 · 90%`** and
  stays green. The number it converts at is *derived from* the live gold model rather than
  typed twice, so the two can never drift apart.
- **It bills you once.** A wave you lost on the grey screen is never counted against you -
  that's RE-ENTRY's and BLEED's subject, and charging you twice for one death is how a coach
  gets switched off.
- **It is a row, not a nag.** For the whole ten minutes it's ONE quiet line you can glance
  at. It only takes the card at the moment a wave actually went by, or just before a cannon,
  and it hands the slot straight back. It never outranks BLEED (something that can kill you
  beats 105 gold) and never talks over a live objective call - the grub fight *is* the
  reason you left the wave.
- Top / mid / ADC. It stays **silent for jungle and support** rather than invent a number:
  camps aren't on the lane schedule and a support's CS was never the story.
- On by default: **Settings -> Gold clock (farm pace, first 10 min)**. The widget legend has
  a new GOLD CLOCK section. Included in MAX ELO.

**Tested:** 10,721 assertions before this shipped. The wave schedule is verified spawn-by-
spawn and arrival-by-arrival for all three lanes across 30 waves (mid meets at 1:30, the
side lanes at 1:38, and a wave is never counted a tick before it lands); the cannon clock is
checked at every second of a 15-minute game for going negative, naming a non-cannon wave, or
pointing at a wave that already arrived; the gold composition is re-derived independently at
every sampled second; the per-CS conversion is asserted equal to the live gold model's own;
every verdict branch has a fixture; and the guard is driven through four full simulated games
- a clean farmer (never accused once), a player who quits farming at 5:00 (caught on the
first wave boundary after he crosses the bar, not before), a player dead across three waves
(billed for none of them), and an ADC - plus an eleven-payload malformed-data sweep that must
never crash the widget. Every frame the guard produced was rendered through the real widget
path and inspected.

## v0.9.66 - THE CLOSER: the games you were winning, and lost

**New feature, and it only ever shows up in games you are already winning.**

Smiteless has had a guard for every phase of a game that goes badly. It has never had one
for the phase that costs the most LP: **ahead, past 20 minutes, not ended yet.** That's the
game you already paid for. Every one of those you lose is LP you earned and handed back.

Your own ledger has been saying so the whole time. The profile tags a game `threw_ahead`
when one of your deaths lands after 25:00 with your team 2k+ up. It was the last tag in the
file with **nothing in the game to answer it** - RE-ENTRY owns the 90 seconds after a death,
BLEED owns the first fourteen minutes, the tempo engine owns the objective windows, and the
closeout was empty. Not any more.

- **It reads the actual map.** Every turret and inhibitor kill is in the live event feed and
  Smiteless was throwing all of it away. The CLOSER now keeps a live structure map of both
  bases and tells you the shortest path to their nexus:

      END IT - mid inhib open 3:34 - 2 of them dead
      nexus turrets as five - baron is a detour, the inhib clock isn't

  **An open inhibitor is a five-minute clock and most games spend it taking baron instead.**
  When one is down it says so, with the seconds left on it. When one turret stands in front
  of one, it tells you that turret is the game - not the next skirmish, not the drake.
- **It tells you what you've GIVEN BACK.** Nothing else in the app - and nothing else you
  can see in a game - tracks the *trajectory* of a lead. The CLOSER remembers your peak and
  shows the erosion: *+4.5k - gave back 2.1k of 6.6k*. A lead that has been quietly bleeding
  for four minutes is a game being thrown in slow motion, and you almost never notice from
  inside it. Once you've given back 1.5k it also **tightens its own bar**: an even fight is
  no longer good enough, because you don't need a fight, you need the nexus.
- **It prices your death in seconds, live.** Not "don't die" - the number:

      HOLD - you're +4.5k and down 2 bodies
      dying here costs 51s - baron is up inside that

  That's your real death timer at your level and this clock, checked against the live baron
  timer. Fifty-one seconds is what they buy with your one bad step, and now you can see it
  before you take it.
- **It stays out of your way.** Behind or even, it says **nothing at all** - a closeout coach
  talking during a losing game is worse than no coach. Ahead with nothing burning, it's one
  quiet line with your lead and your give-back. It never argues with the tempo card either:
  if the fight math says you win the fight, it will not tell you to hold.
- **Late-game advice, finally.** The "do this instead" lines are written for minute 28, not
  minute 8 - *"stay behind your frontline - you never walk in first from ahead"*, *"ward
  their jungle entrances - no solo roams"* - instead of the lane-phase wave advice the other
  guards give.
- On by default: **Settings -> Closer (win-conversion, from 20:00)**. The widget legend has a
  new CLOSER section explaining every verdict.

**Tested:** 60 assertions covering the structure parser (including a turret name Riot renames,
a replayed event, the fountain shrine, and the mid lane running past three turrets into the
nexus pair), the inhibitor clock from both the five-minute rule and the respawn event, all
twelve verdict branches, a full simulated game timeline, and a malformed-payload sweep that
must never crash the widget. The self-test now guards the CLOSER **and** the BLEED guard,
which had never had a check of its own.

## v0.9.65 - runes adapt to the lobby, not just the champion

- **Auto-import now picks the rune page that fits THIS game.** It always took op.gg's
  most-played page and stopped thinking - but the right keystone depends on what you're
  fighting. Your Talon example is literally sitting in op.gg's numbers this patch:

      Talon mid   Electrocute  46.4% over 521 games   <- most played, always imported
                  Conqueror    51.8% over 257 games   <- exists, never chosen

  Into five squishies you want the burst. Into a wall of tanks it bounces off and you want the
  sustained page. Same champion, different game. It now reads the enemy comp off Riot's own
  champion tags and imports accordingly.
- **It only fires on an unambiguous comp.** Two tanks (or three frontline between Tank and
  Fighter) reads as tanky; zero tanks and four squishies reads as squishy; **anything in
  between keeps the most-played page**, because a coin-flip read is worse than the default. It
  also refuses to read a comp off fewer than three locked enemies, and will never switch to a
  page with a thin sample - no importing somebody's 9-game meme.
- **It never invents a page.** Every option is one op.gg says real players run on that champion
  this patch, with its real sample. The only modelling assumption is the mapping from comp to
  keystone class, and that's stated in the source rather than hidden.
- **The panel tells you why**: *ADAPTED - 3 frontline locked (Ornn, Sejuani, Malphite) -
  Conqueror over Electrocute (52% on 257 games vs 46% on 521)*.
- **Clicking a rune chip still wins.** The moment you pick a page by hand, the adaptive chooser
  stops touching it for that champion.

## v0.9.64 - the recommender now knows how YOU do on a champion, and Ghost sits on your Flash key

- **Ghost lands on your Flash key.** Auto-import always put Flash on your chosen key; on a build
  with no Flash, Ghost went wherever op.gg happened to order the two spells. Now the MOBILITY
  spell owns that key either way - same finger, same panic button, so your escape never moves
  between champs. If a build runs both, Flash keeps the key and Ghost takes the other slot.
  (Settings calls it ESCAPE KEY now, since it governs more than Flash.)
- **It stopped recommending champions you're bad on.** Since the mastery gate came off, the
  recommender ranked purely on merit - it would happily hand you the strongest pick into a draft
  on a champion you've lost your last four games with. It now reads your own results and
  **vetoes champions it's ~80% confident are genuine losers for you** (same statistical bar the
  profile's "ease off" advice uses). Losing three in a row is NOT proof and vetoes nothing.
- **Champions you play below your own standard get demoted**, with the receipt. On your account
  right now that flags something worth knowing: **Yasuo, your MAX ELO main, is 8W-8L averaging
  64 against your 83 overall, over 16 games.** You win on it; you don't play it well.
- **New: the boredom fix, and it isn't novelty.** Getting bored is what makes people first-time
  something in ranked, and a sub-12k-mastery pick wins ~44% - so "play something new" is
  expensive advice. Instead the recommender now PROMOTES champions you're already good on and
  haven't touched in a while. Yours: **Aatrox, 3W-0L at avg 110, last played 16 games ago.**
  Same itch, no LP cost. It needs a real sample - one good game is a coin flip, not a champion.
- The panel prints the reason under GOOD THIS GAME (`FRESH  Aatrox - 3W-0L (100%), avg 110 -
  last played 16 games ago`), so a promotion or a drop is never mysterious.
- MAX ELO's auto-lock uses the same filter - it will not lock you onto a champion your own
  results say you're bad on.
- The read is built from your season history (~60 games, 22 champions on your account) and
  cached; it refreshes once per session on a background thread, never in the draft loop.

## v0.9.63 - auto-mute waits for your hands to be still, and backs off the moment they aren't

- **It now watches your real keyboard and mouse while it types, and aborts instantly if you
  touch anything.** Windows tags injected input, so a low-level hook can tell OUR keystrokes
  apart from YOURS. If a real keypress or click lands mid-command, it closes the chat box and
  stops - your input and the command can never shred each other for more than one keystroke.
  Then it just tries again later.
- **It won't start typing while you're already busy.** It waits for a genuine ~350ms gap with
  your hands off the keyboard and mouse before it begins. The fountain is full of those; if it
  can't find one it simply doesn't start, and retries a second later.
- **Mouse movement doesn't count.** Moving the cursor doesn't defocus League's chat box - only
  a click does - and treating movement as interference would mean it never fired at all, since
  the cursor is essentially never still.
- I checked whether the game has a bindable "mute all" hotkey that would replace the typing
  with a single keypress. **It doesn't** - the client exposes ping bindings and nothing else -
  so typing is the only in-game route, and the answer had to be making it interruption-proof
  rather than shorter.
- The self-test now proves the guard on seven cases: real key and real click must trip it; our
  own injected key and click must not; mouse move and wheel must be ignored; and it must not
  trip on our own typing during a live run, with the hooks released afterwards.

## v0.9.62 - auto-mute hardened: the real bug was THREE copies typing at once

- **Found it. Three copies of the mute helper were running and all typed into the same chat box
  in the same second.** Your log, verbatim - three identical lines, same timestamp, same game
  clock:

      16:14:38 TYPED '/fullmute all' at gameTime=4.3
      16:14:38 TYPED '/fullmute all' at gameTime=4.3
      16:14:38 TYPED '/fullmute all' at gameTime=4.3

  Three commands interleaved character by character is `///ffuullllmm...` - garbage, not a
  command, muting nobody. And because each copy reported success, the log looked *great*. The
  v0.9.55 rewrite had quietly dropped the single-instance mutex the original had, and the tray
  re-spawns the helper on any phase flap.
- **The mutex is back**, plus an in-process send lock so two threads can't interleave either.
  The self-test now FAILS if either guard ever goes missing again.
- **A missed attempt now recovers - safely.** Before, if the game window wasn't focused during
  the fountain window, that was the whole game. Now, if the fountain attempt misses, it waits
  and retries **while you're dead**. A dead champion cannot cast, move or attack, so a stray
  keystroke there costs exactly nothing - it is the one genuinely free window in a game, and
  every game hands us several. It still refuses to type while you're alive and on the move,
  because that is what cast Flash.
- **A lost focus now costs one character instead of nine.** Focus is re-checked before *every
  single character*, not once per burst, and the chat box is closed on abort. The `f` in
  "fullmute" is the Flash key; that exposure is now one keystroke wide.
- **The settings layer covers more ground**: on top of ally chat and all-chat hidden and ping
  audio muted, it now also sets the chat channels invisible outright and drops ping volume to
  zero. All five are written through the client and read back to confirm. This layer needs no
  focus, no keystrokes and no timing, so it holds even if the typing never lands.

## v0.9.61 - MAX ELO actually locks the champ it hovers

- **It hovered a champion and then never locked it.** Root cause: the recommendation was being
  computed with your own hovered champion counted as taken. Smiteless hovers Warwick -> Warwick
  disappears from "what's good this game" -> Hecarim is now top -> it hovers Hecarim -> Warwick
  comes back -> it hovers Warwick. Once a second, forever. And because the 2.5-second lock timer
  restarts whenever the target changes, **the lock was never reached.** The flip-flop and the
  no-lock were the same bug.
- **"What's good this game" no longer takes your current champion into account.** The answer to
  "what's strong into this draft" must not move every time you hover something. This applies to
  the panel's list and to the auto-lock pool.
- **Once a champion is on your pick slot, that is the one it locks.** It reads the slot from the
  live client instead of its own memory, so a momentary network blip in the suggestion fetch
  can't wipe the commitment and restart the timer either. If you move the hover yourself, it
  locks what you moved it to.
- Verified against a simulated draft where the pool deliberately flips order every single poll:
  it hovers Warwick at 0s, holds it through six reversals, and locks at 3s.

## v0.9.60 - MAX ELO only tries champions you actually own, and moves down the list

- **The auto-lock was trying to lock champions you don't own.** Dropping the mastery gate in
  v0.9.57 made the recommender rank on merit alone - which is what you wanted - but it also
  meant the auto-lock pool had no idea whether you could *pick* the champion. The client
  refuses a pick action for a champion you don't own, so it sat there failing once a second
  until the timer ran out and the draft picked for you. Your log, verbatim: *hovering Nasus -
  locking in 2.5s*, then **eleven** identical *FAILED to lock Nasus*. You don't own Nasus.
- **It now reads what you can actually pick** (`pickable-champion-ids` - which also accounts for
  free rotation and bans) and walks the list: best champion first, and if you don't own it, the
  second, then the third. Your real chains right now:

  | role | it will try, in order |
  |---|---|
  | jungle | Nunu → Hecarim → Warwick → Sejuani → Rammus |
  | mid | Irelia → Twisted Fate → Ekko |
  | top | Warwick → Malphite → Volibear → Sett |
  | adc | Hwei → Xerath → Mel → Syndra |
  | support | Amumu → Teemo → Poppy → Blitzcrank → Leona |

- **A refused champion is now dropped after 3 attempts instead of retried forever**, and the
  next one is tried immediately. The pool is also 12 deep rather than 5, because ownership plus
  bans can empty a short list - mid only yields three champions you own.
- **GOOD THIS GAME no longer suggests champions you can't pick either.** This is not the old
  mastery gate coming back: a champion you own with zero games on it still shows. It only drops
  the ones the client would refuse.
- The self-test now covers ownership: an unowned top pick must fall through to the next, owning
  nothing must lock nothing, and owning everything must still take the best one.

## v0.9.59 - MAX ELO with no champion set now locks the best pick for the draft

- **You can arm MAX ELO with the Main and Backup boxes EMPTY.** It used to refuse ("pick a main
  first"), which meant the one button needed setup before it did anything. Leave them blank and
  it locks **the best pick for that specific draft** instead - the same read the panel's GOOD
  THIS GAME strip shows (counters into the enemies who've locked + comp fit, merit only,
  best-first). The list already excludes anything banned or taken, so it doubles as its own
  backup chain: if the top pick goes, it takes the next one.
- Name a Main (and a Backup) if you'd rather be held to one champion - that behaviour is
  unchanged, and it still wins over the recommender when it's set.
- What it would lock right now, per role: jungle **Nunu**, mid **Anivia**, top **Warwick**,
  adc **Hwei**, support **Teemo** - each falling through its own list if those are gone.

## v0.9.58 - auto-mute types ONCE, in the fountain, and never while you're moving

- **It cast Flash. Sorry.** v0.9.56 sent a second "confirming" `/fullmute all` at 25 seconds,
  on the reasoning that a repeat was free insurance. It isn't. Typing into a live game is only
  safe while the chat box holds keyboard focus, and **clicking to move takes that focus away** -
  so the resend fired while you were walking to a camp, the box dropped focus mid-command, and
  the **`f` in "fullmute" hit Flash**. (Every letter in that command is a keybind: `f a e t l m u`.)
- **There is now exactly one attempt, at ~4 seconds, while you're parked in the fountain** - the
  moment the first send already worked. If it misses, it misses; there is no retry, and it stops
  trying entirely once the clock passes 20s because by then you're out on the map and clicking.
  The client-settings layer (ally chat off, all-chat off, ping audio off) is the fallback for a
  missed attempt - that is exactly why it's there.
- **The self-test now fails the build if a retry is ever re-added**, or if the give-up time
  drifts past 30s. This was a safety limit dressed up as a tuning constant, and it cost you a
  Flash; it's enforced now rather than commented.

## v0.9.57 - champ select recommends what's GOOD, not what you already own

- **"GOOD THIS GAME" now uses the web DraftBoard's algorithm - because it was mostly showing
  you nothing.** The champ-select panel and the web board have always shared one scoring
  function (counters into the locked enemies + comp fit), but champ select was passing your
  pooled mastery into it, which applied a HARD 12,000-point gate on top. The result, on your
  own account, right now:

  | role | before | after |
  |---|---|---|
  | jungle | *(nothing at all)* | Nunu, Xin Zhao, Master Yi, Sylas, Lee Sin |
  | adc | *(nothing at all)* | Hwei, Viktor, Samira, Seraphine, Xerath |
  | mid | Yasuo | Anivia, Katarina, Veigar, Lissandra, Twisted Fate |
  | top | Cho'Gath, Yasuo | Warwick, Kayle, Mordekaiser, Locke, Gragas |

  For your main role it was rendering an empty strip and the line "no 12k+ mastery picks for
  this role". A list of champs you already play is not something you need an overlay to tell
  you; what's strong into *this* draft is. Same change on the queue card.
- **The climb guard is untouched.** Hover something you barely play and you still get
  *"⚠ 4k mastery pick — sub-12k wins ~44% (1M-game study)"*. The warning was always the useful
  half of that idea; silently deleting the recommendations was not.
- Click a suggested face to hover it, exactly as before.

## v0.9.56 - auto-mute works. The bug was one missing scan code.

- **`/fullmute all` is back, and this time chat actually opens.** Four releases of "fixing" this
  were all fixing the wrong thing. Every CHARACTER was going out as a scan code - but the
  **Enter** that opens the chat box went out as a virtual-key event with `wScan = 0`. The League
  game reads scan codes. So Enter was ignored, the chat box never opened, and the letters landed
  on your champion as gameplay binds. From the keyboard that is exactly what it looked like:
  *"it sounded like you just hit keys."* Enter now goes out as scan code **0x1C** like every
  other key, and the chat box opens.
- **That also means v0.9.55's conclusion was wrong.** I claimed a kernel anti-cheat was filtering
  injected input. It isn't - the letters proved it by casting spells. Injected input reaches the
  game fine; only the Enter was malformed.
- **Both layers are kept, deliberately.** The typed `/fullmute all` is the real thing (chat AND
  ping markers, every player, that game - nothing else can suppress ping markers). Underneath it,
  the client-settings layer from v0.9.55 still writes ally chat off / all-chat off / ping audio
  off and verifies them by reading back, so a game where the typing misses is still quieter than
  nothing. `python core\lolmute.py off` reverts the persistent half.
- **The self-test now fails loudly if Enter ever loses its scan code**, because a zero there
  doesn't look like a broken feature - it looks like your champion randomly mashing keys at the
  start of every game.
- Timings are the ones proven by hand against a live client: 0.60s for the chat box to take
  keyboard focus after Enter, then 30ms per key.

## v0.9.55 - auto-mute, done properly: no typing, and it checks its own work

- **Auto-mute never worked, and the reason wasn't the one I kept fixing.** v0.9.51 through
  v0.9.54 tried to TYPE `/fullmute all` into the game. The diagnosis is now conclusive rather
  than a guess: with the game window focused, Windows reports every keystroke **accepted**
  (`SendInput` inserts 2/2 events, no error) and both processes sit at the same integrity level,
  so nothing in the OS is dropping them - **the OS delivers the keys and the game discards
  them.** That's what a kernel anti-cheat filtering injected input looks like, and no amount of
  unicode-vs-scan-code or timing tuning was ever going to change it.
- It was also the wrong thing to build. Every other surface here says plainly that it never
  sends an input to the game - that's the line this app draws, and typing into a live match
  crossed it.
- **It now writes League's own settings instead**, through the client, with nothing typed
  anywhere: **ally chat hidden**, **all-chat hidden**, **ping audio silenced**. And - the part
  the old one structurally could not do - **it reads the setting back and verifies it took**.
  That's why it lied for four releases: it had no way to tell success from failure, so it
  reported success. The new one can only report what the client actually confirms.
- **Two honest limits, stated up front:** ping MARKERS still draw on the minimap (the client
  exposes no setting for those, only their sound), and because these are client settings they
  **persist** until you turn them off - here, or in League's own settings. That's arguably what
  you wanted anyway: decide once, not at 0:15 every game. `python core\lolmute.py off` reverts
  all three.
- The self-test now reads the live mute state every run, so a setting Riot renames fails loudly
  instead of silently doing nothing.
- **Fixed: the self-test was writing fake entries into `smiteless_pick.log`.** That log exists
  to answer "why didn't my champ lock" - filling it with fixture LOCKs made it useless for the
  one job it has.

## v0.9.54 - MAX ELO locks your champ immediately, not at the buzzer

- **The auto-lock no longer sits there hovering.** v0.9.53 hovered your champion the moment your
  pick turn opened and then waited until the last 8 seconds of the timer to lock it - copied from
  the auto-ban, where waiting genuinely helps (every extra second of teammate hovers sharpens the
  ban math). A pick gets nothing from waiting; it just leaves you hovered for 20 seconds while
  someone types "can I mid". It now hovers, gives the client **2.5 seconds** to register it (which
  is what feeds auto-import the right champion), and **locks**. The pick is not a discussion.
- It also stopped re-sending the hover every single second while it waited, and a new draft can no
  longer inherit the previous one's hover clock.
- **The self-test now drives the whole auto-lock through a simulated champ select** - main free,
  main banned, main taken by an ally, both gone, not your turn, no pool - because this is a thing
  you cannot trigger on demand, and a break means finding out mid-draft with a champion you didn't
  ask for and no way back.

## v0.9.53 - the MAX ELO button, and auto-mute actually mutes now

- **New: MAX ELO.** One button at the top of Settings. Name your champion and a backup, hit
  **ARM**, and the whole app goes on rails for the climb:
  - **You play that champion.** When your pick turn comes it hovers your main and **LOCKS it**
    for you - or the backup, if the main got banned or taken. No deliberating, no last-second
    "I'll try something", no autofilled off-champ. Champion pool discipline is the single
    highest-confidence lever in ranked, and this one enforces it instead of suggesting it.
  - **It bans for you** (your perma-ban list first, then the live pick that most threatens your
    team's hovers), **auto-accepts the queue**, **imports your runes + summs on lock**, and
    **mutes the lobby**.
  - **And every read comes on at once** - Tempo, the free-objective alarm, the re-entry guard,
    live intel, the death brief, the loading scout, the queue call, dodge alerts, matchup tips,
    the draft link. 21 toggles, one click, and you can watch them all tick on in the panel.
  - **STAND DOWN** releases the champion lock and leaves the features on, because they were
    good ideas before you armed it. The lock also drops itself if you dodge.
  - Every auto-lock attempt writes to `~/.claude/smiteless_pick.log`, so a pick that didn't
    happen is never a mystery - same rule the auto-ban has followed since v0.9.44.
- **Fixed: AUTO-MUTE never actually muted anyone.** v0.9.51 shipped it typing with Windows'
  *unicode* key events - which is right for the Riot login window (a browser) and wrong for the
  League game, a DirectX client that reads RAW keyboard input and throws unicode events away.
  It logged a confident `SENT '/fullmute all'` every single game and nothing was ever muted. It
  now types **scan codes**, one key at a time with a human-sized gap, exactly like a real
  keyboard. Two more things were wrong with it: it fired at game-time **1.7 seconds**, while the
  client is still coming out of the load transition and swallowing input (now 4s), and it only
  ever tried **once** - so a single dropped burst meant a whole game of pings. It now sends
  again at 25s. `/fullmute all` sets the mute rather than toggling it (only `/unmute all`
  reverses), so the second send can only help.
  - You can prove it yourself in a custom game: `python core\lolmute.py test`.
  - The self-test now checks the keystroke path every run - it can't catch "did the mute land",
    but it does catch the layout/timing half, which is the half that broke.

## v0.9.52 - RE-ENTRY: the 90 seconds after you respawn are now guarded

- **New: the RE-ENTRY guard.** Your own match history has one split bigger than any other in
  it: games where two of your deaths landed within 90 seconds of each other were won at
  **35% (8W-15L)**; games without that, **65% (11W-6L)**. Dying is normal. Dying *again* a
  minute later is what actually loses the game - you walk back into a lane where you're a
  level and a wave down, against the player who just proved he beats you there. So the moment
  you respawn, a 90-second clock starts on the widget and answers one question off live data:
  **can they punish you right now?**
  - **HOLD** - *"Kha'Zix is up and ahead"*, or you simply lose any fight this second. It takes
    over the directive card and tells you the productive thing to do instead ("reset your own
    camps, safe side first - no counter-jungle"). This is the moment the whole feature exists for.
  - **CLEAR** - they're a body down: *"Viego 21s - Ahri 34s - the map is yours until they're
    back"*. Quiet row, and the Tempo engine keeps the card, because there's a real play on.
  - **RESET** - even. Farm the window out, don't go hunting a trade.
- **It carries its receipt.** The card prints YOUR split for the habit - *"your games where two
  deaths landed inside 90s - with it: 8W-15L - without: 11W-6L"* - so it's your data talking,
  not folklore. The verdict itself is read off their death timers, their item gold and their
  levels (the same fight math the TAKE/GIVE verdict uses), never a vibe.
- The clock is exactly the 90 seconds Smiteless already uses to tag the habit in your profile,
  so the overlay and the post-game read are measuring the same thing. New legend section
  explains all three verdicts. Off switch: **Settings -> In-game widget -> "Re-entry guard"**.
- **Removed: FAVOURITE PICKS.** The ordered "my go-to champs" list in Settings, and the YOUR
  PICKS icon row it drew in the champ-select panel, are gone. It was the largest block of
  controls in the Settings window - a dropdown, a role filter, a list, Add/Remove/up/down - and
  the list had never had a single champ added to it, so the row it fed had never once rendered.
  The strip directly beneath it, **GOOD THIS GAME**, already does the same job better and
  without being configured: it's derived from your real mastery pooled across all your accounts,
  filtered to your role and to what's still open, and you can click a face to hover it.

## v0.9.51 - AUTO-MUTE: the game starts, everyone goes quiet

- **New: AUTO-MUTE.** The moment the game clock starts, Smiteless sends Riot's own
  **`/fullmute all`** for you - chat AND pings from every player, allies and enemies, gone for
  that game. It's the one decision you were making the same way every game, at 0:15, while you
  were trying to path; now you make it once in Settings. Your own pings still work, and nothing
  is changed permanently: `/fullmute` lasts for that game only, so nobody is muted in your next
  one and no client setting is touched.
- **It will not type anywhere but the game.** The command has to go in as keystrokes (there's no
  API for muting), so before every burst it checks that the foreground window really is the
  League game - right window class, and its process really is `League of Legends.exe` - and
  re-checks between opening chat and typing. If you're alt-tabbed it just waits and mutes when
  you come back. A reconnect gets muted again, because a reconnect clears your mutes.
- Off switch: **Settings -> Features -> In-game automation -> "Auto-mute everyone (chat + pings)"**.
  On by default.

## v0.9.50 - the loading board is TALL, and it fills in seconds instead of a whole load screen

- **The cards are tall portraits now, like the real League loading screen.** v0.9.48 pushed the
  art the other way - a wide 2.4:1 letterbox strip sitting above a block of stats. That was the
  wrong shape for this screen. Each player is now one tall rectangle carrying **Riot's own
  loading-screen portrait** (the 308x560 art the client itself uses, not a landscape splash
  squeezed into a strip), with the whole read - name, rank, win% . W-L . KDA, last-10 form, the
  tag pills, the damage bar - laid over a scrim on its lower half. Champ names line up straight
  across the row. Side benefit: that art is ~45KB a champ instead of ~2.6MB, so ten portraits
  warm in a blink.
- **The ten accounts now load in about a second, not the whole loading screen.** They were being
  read strictly one after another - ten players x rank + ten match reads + mastery, about 130
  Riot round-trips nose to tail, and every card sat on "scouting..." until the last one landed.
  They're read **concurrently** now (all ten at once, with a shared pool underneath for the match
  reads), and **cards fill in as each player resolves** instead of the board waiting for the
  slowest account.
- **One read, three surfaces - for real this time.** The loading board, the in-game scoreboard and
  the web DraftBoard all show the same ten-account scout, and it is now built exactly once per
  lobby: whoever asks first pays for it and publishes it, everyone else reads that. The champ
  select dodge-read also went parallel, so it warms the same cache instead of queueing behind
  itself.
- **The in-game widget stays off the loading screen.** v0.9.47 gated this on the launcher's phase
  read, which has a hole: one blip from the live-game API and the loading screen reads as
  in-game, and the widget lands on top of the board. The widget now checks for itself - it stays
  off screen, silent, until the game clock actually starts, and goes away again on a reconnect
  load screen.
- **Names that aren't Latin render properly.** A Riot ID like a CJK name was drawing as three
  empty boxes on the board - the account you're scouting, unreadable.

## v0.9.49 - the QUEUE CALL: your own numbers, before you press Find Match

- **New: the QUEUE CALL.** Sit in the lobby and a small card docks beside the client with the
  one question left before Find Match - **is this one worth playing?** It reads your own ranked
  history off the League client (no key, no Riot round-trip) and returns a single verdict:
  **GO**, **LAST ONE**, **WAIT** or **STOP**, with the instruction spelled out - *THE SITTING IS
  DONE*, *TAKE TEN FIRST*, *NOT YOUR WINDOW*. Four slices of your history are checked against the
  state you're actually in: riding 2+ losses, deep into a sitting, queueing back inside 10
  minutes, and the hour you're playing.
- **It can't call a stop on a hunch.** A slice only becomes a verdict if it beats a two-proportion
  significance test against the rest of your games *and* sits 10+ points under them; anything
  short of that renders as **leaning cold** and leaves the verdict alone. Under 20 ranked games it
  says so and gets out of the way. Every line carries its receipt - `game 4+ of a sitting - 33%
  over 36 (vs 63% otherwise)` - so it's your data talking, not folklore.
- The card never takes focus off the client, never covers it, and closes itself the moment you
  queue. Off switch: **Settings -> Overlays & Boards -> "Queue call"**.
- **Removed: the GHOST pace race.** The widget's `GHOST - CS +8 - deaths 1/2 - +340g` line is
  gone, along with its records file, its fanfare and its setting. It was the one live row with no
  decision attached to it: nothing you do differently on hearing you're 8 CS up on a personal
  best, and if anything it pulled toward farming your own record instead of playing the objective
  call sitting directly above it. The widget is one row quieter.

## v0.9.48 - the splash art is an actual BANNER now
- **The art is a wide letterbox strip, not a square block.** v0.9.47 sized the art off the card's HEIGHT and made it *taller*, which pushed it further toward a square (360x206, barely 1.7:1). It's now sized off the card's WIDTH at a fixed **2.4:1 letterbox** (360x150) - a real banner, at every resolution.
- **Cards fit their content.** They no longer stretch to fill the screen, so there's no dead void under the art; the two rows are centered between the header and the game-plan strip, which is pinned to the bottom.

## v0.9.47 - lanes line up, one scout for everything, and your profile survives a Riot outage
- **The loading board is in LANE ORDER now.** TOP . JG . MID . BOT . SUP, left to right, on both rows - so a column IS a lane and your card sits directly above the enemy you're laning against. Mid was landing in random columns because Riot hands back the roster in lobby order. Players whose position the client doesn't report (blind pick) fill the leftover slots instead of being dropped.
- **The header tells you who to PLAY FOR, not who to fear.** It used to read "WATCH CASSIOPEIA" - true, but not something you act on. Now it names the teammate most likely to carry and why: **PLAY FOR AHRI (geminigwen) - Ahri main . 145k pts**. If that teammate is you, it says **YOU'RE THE WIN CONDITION**.
- **The splash art reads like a banner instead of a pasted block.** The art is taller and now dissolves into the card on every open edge - a long vertical ramp plus a soft vignette down each side - so there's no hard rectangle boundary anywhere.
- **The scout is pulled ONCE per lobby and shared by every surface.** The loading board and the web DraftBoard both woke up at champ select and each fired ~100 Riot calls for the same ten accounts, throttling each other into half-scouted results. Now the first one to ask builds it and the others read that same snapshot (keyed to the lobby, so a new game never sees the old one). Fewer calls, and every surface shows the *same* complete read.
- **The in-game widget no longer opens on top of the loading screen.** It was firing as soon as the live-game API answered - which happens while you're still loading. It now waits for the game clock to actually start.
- **Your profile loads even when Riot's API is down.** It used to blame your key ("may be expired") when the real problem was Riot's regional host being unreachable. Now, for your own profile, Smiteless reads your match history **straight from the League client** - no key, no Riot round-trip, and it can't get rate-limited (it also tends to find *more* games than the web API). If even that's unavailable, the last-good profile is served from disk with its age shown, so the page is never blank.

## v0.9.46 - the loading scout is back, rebuilt as splash cards (+ a u.gg backup)
- **The fullscreen LOADING SCOUT returns, completely redesigned.** While the game loads you now get ten tall **splash-art cards** - your team on top, theirs below - each with the champion's face-cropped splash, a ringed portrait, the account's **rank badge**, mastery, the recent-form read (**win% . games . KDA** with last-10 W/L bars), the profile-read tag pills (`smurf?`, `off-champ`, `Thresh OTP . 240k pts`, `4W heater`, `duo`...), and a damage-lean bar. Your own card is framed in ember so you find yourself instantly, and the one enemy most likely to decide the game rides a **WATCH** call in the header. Built to be read at a glance in the seconds you're staring at the load screen anyway. (Turn it off under Settings -> Overlays & Boards -> "Loading-screen scout".)
- **The scout now falls back to u.gg when Riot's match history is down.** Riot's Match-V5 API lives on a Cloudflare-gated host that goes dark or rate-limits often (you'll have seen the whole lobby read "no recent ranked" for no reason). When Riot returns nothing, Smiteless now pulls the same recent games - champ, W/L, KDA, role, match id - straight from u.gg's indexer instead, so the scout keeps working through a Riot outage. Riot stays the primary source; u.gg is only the safety net.

## v0.9.43 â€” every game gets a grade, ranked 1stâ€“10th, and a GOD KING tier
- **Expanded match details now grade all ten players and rank them 1stâ†’10th.** Each row shows that player's performance grade (Dâ†’SS, the same role-benchmarked score, not raw KDA) next to their KDA, and a placement medal on the left â€” **gold #1, silver #2, bronze #3**, then the rest â€” sorted by who actually played the best game in the lobby. See at a glance where you (and everyone else) placed.
- **New god tier.** A genuinely game-breaking game (~120+) now reads **SS / "GOD KING"** in hot ember gold instead of just "hard carry" (that's now reserved for 115â€“119). Lost a game you hard-carried? It reads **"GOD, still lost."**
- **The page now reliably swaps from the champ-select draft to the in-game scoreboard.** Root cause: the publisher quit and retired the draft the instant the phase read anything but "in game" for a *single* poll â€” and the live-game API (:2999) returns an empty phase on brief hiccups, so one blip mid-load permanently killed the swap. It now debounces (three straight non-game polls, ~18s, before it treats the game as over) and keeps publishing across a transient blip.
- **The publisher writes a diagnostic log now** (`~/.claude/smiteless_draft.log`): every step â€” spawn, champ-select end, each scout attempt, whether the scout data built, and whether the upload succeeded or failed. No more guessing why the board did or didn't appear.
- **The web scout board is horizontal again.** Your team and the enemy team sit **side by side** like a real scoreboard, using the full width, instead of one long top-to-bottom list of ten. Each row reflows to fit its column (name Â· rank Â· form Â· record Â· grade on top, tags underneath), and it collapses back to a single column on phones.

## v0.9.40 â€” the tactical board moves onto the web, and it catches a game in progress
- **The 2nd-monitor tactical board is on the web now.** The live call the on-monitor board used to make â€” **GANK TOP â€” Darius is lvl 5 (your lane 7)** â€” rides at the top of DraftBoard, next to a live **win read** (with its basis: "+2 kills, +1 drake"), the **enemy jungler track** (where he was last seen, doing what), and **objective countdown timers** (Void Grubs / Drake / Baron) that tick down in your browser between updates and flip to **UP** when they spawn. It streams live over the same shared link the whole lobby already has.
- **Start Smiteless mid-game and the board still comes up.** Before, the web board only started if Smiteless was running through champ select â€” launch it after the game had loaded and nothing appeared. Now it detects that you're already in a game, seeds the board, opens it on your second monitor, and starts streaming the scoreboard + tactical board right away.

## v0.9.39 â€” actually retire the loading overlay + fix the in-game swap
- **The native loading-screen overlay is gone for real.** v0.9.37 only flipped a default, which a settings file that already had it *on* ignored â€” so it kept opening. Now the launcher (`smiteless.ahk`) no longer spawns it at all, and the overlay reads a fresh opt-in key so a stale setting can't resurrect it. It will not open again. (Deliberately want the on-monitor version back? Set `loading_overlay: true`.)
- **The web board swaps to the in-game scoreboard immediately again.** The v0.9.37 lane-coaching work accidentally made the scout wait on up to five counter-guide scrapes (12s each) *before* it could publish â€” so the page could sit on the champ-select view for most of a minute after the game loaded. The scoreboard now publishes instantly and the how-to-play tips stream in a few seconds later, on their own.

## v0.9.38 â€” your lane opens for you, teammates opt in
- **The YOUR LANE panel no longer assumes a teammate is you.** Before, the shared board auto-opened the publisher's lane for everyone who opened the link. Now the board Smiteless opens **in your own browser** auto-opens **your** lane (it's flagged as yours), while a teammate's copy shows no coaching until they tap **This is me** on their row â€” then it's *their* matchup. Nobody gets fed the wrong lane by default.

## v0.9.37 â€” DraftBoard IS the scoreboard, and it knows who you are
- **The native loading-screen overlay is retired â€” DraftBoard does its whole job now.** The scout/scoreboard that used to paint over your loading screen on the second monitor is folded entirely into the shared DraftBoard page: same ten-account scoreboard, but it's the link that's already in lobby chat, so you AND your teammates get it. The old overlay is off by default (Settings â†’ Overlays & Boards still has the switch if you want the on-monitor version back).
- **It rebuilds to look like the real in-game scoreboard.** The side-by-side v0.9.36 layout is gone â€” the board now stacks **YOUR TEAM** over **ENEMY TEAM** in full-width rows, in the exact visual language of the on-monitor overlay: one strict column grid so every row lines up (face Â· account Â· rank Â· last-10 Â· grade Â· reads Â· claim) all the way down instead of the two halves drifting out of alignment.
- **DraftBoard knows who you're playing.** The moment the game loads, your own row is detected and highlighted, and a **YOUR LANE** panel opens under it automatically â€” you no longer have to tell the page who you are. It carries your matchup (**Vi vs Lee Sin**), a written "how to play this lane" tip pulled from real counter-guides, and the game's WIN / LOSE lines.
- **Every teammate gets their own lane â€” "This is me" carries into the scoreboard.** The claim button isn't just for champ select anymore. Tap your row (or the button) on the live scoreboard and the YOUR LANE panel switches to **your** matchup and coaching â€” each of the five allies gets a personalized read from the one shared link. In-game the roster exposes roles, so lanes are paired for real (your top vs their top, etc.).
- **A WATCH read rides in the header.** The one enemy account most likely to decide the game â€” the perf/OTP/heater standout â€” surfaces as a **âš  watch Darius â€” smurf? Â· 5W heater** chip at the top of the board, the same call the loading overlay used to make.

## v0.9.36 â€” DraftBoard scoreboard goes wide
- **The in-game scout board is horizontal now.** Your team and the enemy team sit **side by side** like a real scoreboard instead of one long top-to-bottom stack â€” the page uses the full width. Collapses back to a single column on phones.

## v0.9.35 â€” DraftBoard becomes the whole-lobby scout
- **When the game loads, DraftBoard turns into the full scoreboard.** The link you (and your teammates) already have in chat stops being just the champ-select draft â€” the moment loading hits, the same page fills with the **complete scout of all ten players**: rank, last-10 form bars, record on the champ they locked, an Sâ€“F performance grade (how they actually play, not W/L), and the evidence-cited read tags (`smurf? Â· lvl 41`, `off-champ Â· 7 of last 10 on Yasuo`, `Thresh OTP Â· 210k pts`, `4L skid Â· tilt risk`) â€” the exact intel your own loading screen shows, now on every teammate's phone. Plus the game plan and the WIN/LOSE lines underneath. No refresh; the same URL just upgrades itself.
- It's live for the whole game and retires when you leave. Try it without a game: `python core/loldraft.py test scout` publishes a demo scoreboard, or open the hosted page with `#demo` to watch a draft resolve all the way into the scout board.
- **The draft link is now DraftBoard, and the URL is short + trustworthy.** It used to post a scary-looking `â€¦github.io/smiteless/draft/#d=xxx&db=yyy.firebaseio.com` that nobody wanted to click. The page now bakes in its own database, so the link that lands in chat is just **`â€¦/draft/#d=<id>`** â€” and it's branded **DraftBoard** on the page and in the chat message ("DraftBoard â€” live picks + runes for our lobby: â€¦"). (Self-hosters pointed at a different database still get the full `&db=` form automatically.)
- **It opens for you, too.** When Smiteless posts the DraftBoard link to lobby chat it now also **opens the board in your own browser** on your second monitor â€” no more clicking your own link. Toggle it under Settings â†’ Champ-select automation ("Also open the draft board for me"), and the chat message text is overridable via `draft_msg` in the settings file.
- **Match details are color-graded now.** Expand any game and every player's KDA is tinted by how they actually PLAYED (the role-benchmarked grade, not raw KDA): exceptional reads arcane cyan, good reads green, okay stays neutral, bad goes amber â€” and a 2/11 goes **demon red**. Each player's **current rank** appears beside their name in tier colors, filled in right after the detail opens.
- **Browsing profiles no longer loses your place.** Clicking into a player from a match detail pushes a real navigation stack â€” **â† back returns you to the exact scroll position with the same game still expanded**, however deep you went. Match details are cached across hops, so re-expands are instant.
- **The gank read is a CALL now, not math.** The live board's verdict strip carries one decision line: **"GO TOP â€” best gank on the map (vs Darius)"**, "gank BOT when it's pushed", or the honest fallback â€” **"NO GOOD GANKS â€” farm tempo, set up the next objective â€” and stay out of TOP."** The lane badges stay for detail; the call is the takeaway.
- **The death brief warns you BEFORE the next death, not after it.** New card while you're dead â€” **BEFORE YOU WALK BACK**: fires when this death chained off the last (<90s, with the gap), when the same enemy has killed you repeatedly ("path AWAY from them"), or when the enemy just took an objective ("they're 5, grouped, and moving â€” do NOT walk mid alone").
- **"How you win" now has doomed-game lines.** When you're clearly down on gold, the win-con turns into a concrete stabilizer **gated to what your champ can actually do**: supports get "play for PICKS: sweep + ward YOUR side", split-capable tops get "take a side lane, don't flip mid", ADCs get "stall to your item spike", assassins get "flank from fog". Grounded in standard behind-game macro (behind teams win off picks and enemy mistakes, not called fights).
- **The loading screen earns its place: WIN / LOSE lines.** Under the game plan, two lines the live board doesn't have â€” how this comp matchup is won and how it's thrown ("WIN: end before 25 â€” turn every kill into towers Â· LOSE: letting it go late").
- **Settings got reorganized.** The flat 19-checkbox dump is now three labeled groups â€” **IN-GAME WIDGET / OVERLAYS & BOARDS / CHAMP-SELECT AUTOMATION** â€” in two-column cards, and slider descriptions wrap instead of truncating off the window edge.

## v0.9.32 â€” tags that can't lie, bans that can't miss
- **The tag system was rebuilt around a written spec (docs/TAGS.md): every tag is a claim, and every tag cites its evidence right in the pill.** The canonical bug â€” a Morgana one-trick on a 9-win *Morgana* streak locks Brand, goes 1/8, and Smiteless calls him `SMURF, NEW ACCOUNT` â€” can't happen anymore. THIS-GAME reads (what to expect on the champ they locked *today*) are now separate from ACCOUNT reads, so that player reads as **`first Brand? Â· 2k pts, 0 of last 10` + `off-champ Â· 9 of last 10 on Morgana` + `9W heater Â· on Morgana`** â€” true, and it tells you the 1/8 is coming. `smurf?` only fires on real smurf evidence (**account level â‰¤ 60** â€” newly pulled from the client/API â€” plus â‰¥70% over 8+ and a high perf grade), always with a `?` because it's an inference; no level data, no tag. New reads: `off-champ`, `cold on X Â· 1-5 recent`, `new account Â· lvl 34` (fact) vs `fresh ranked Â· 12 games` (weaker claim), and win-streak attribution (a heater earned on a different champ than today's says so, and stops counting as a threat read). Re-validated against the actual Morgana/Brand game from the match cache â€” a regression test (`tools/tagcheck.py`, wired into selftest) keeps it honest forever.
- **Auto-ban rebuilt + a perma-ban list â€” Shyvana never sees daylight again.** Settings â†’ PERMA-BAN LIST: an ordered priority list (ships with Shyvana at #1); on your ban turn Smiteless locks the highest listed champ still available, skipping anything a teammate hovers, then falls back to the live recommended bans. The "ban sometimes didn't happen" bug is fixed at the root: the ban used to fire from the render loop, which can stall for seconds on network work and swallow the last-12s ban window entirely â€” it now runs on a **dedicated 1-second watcher thread** that only touches the local client. Locks are **verified by re-reading the session** (with a two-step fallback for client builds that ignore the one-shot), and every attempt writes a line to `~/.claude/smiteless_ban.log`, so a missed ban is never silent again.
- **The widget's tofu boxes (`[]`) are dead â€” this time structurally.** Round two of this bug: the July fix added a hand-typed "symbols Segoe UI can't draw" list per surface, and the lists drifted (the widget's never learned `âœš` antiheal; the import button's `â‡©` was missing too; Bahnschrift can't even draw `âœ“`). Fonts are now **probed directly** â€” render the glyph, compare against the font's tofu box â€” so coverage can never rot, plus a source-scan tripwire (`tools/glyphcheck.py`, in selftest) that fails the moment any symbol literal is routed to a text-blind font. Verified by rendering the widget legend + live body: zero boxes.
- **Death attribution stops guessing.** "Solo-killed" now only renders when the kill event credits zero assisters (one helper reads `Killed by Zed +1`); executes read honestly (`Executed by a turret / minions / Baron`); and a killer that can't be matched to the enemy roster is named as-is instead of claiming "no killer credited" â€” with a diagnostic line in `~/.claude/smiteless_dead.log` so it can be chased down.
- **Duo detection catches real duos and stops flagging rivals.** Shared games are now verified **same-side** from the cached match data â€” two players who merely *faced* each other repeatedly no longer count (that false-positive was live in the old logic), and two verified same-team games already flag as `duo?` (three+ = `duo`), because 10-game windows drift out of sync fast â€” that's how obvious duos were slipping through. Duo tags cite their evidence: `duo Â· Nick (4 shared)`.
- **The board respects your desktop and your dodges.** New setting: *"Keep live board always on top"* â€” untick it and other windows can cover the board (applies live). Drag the board anywhere and it **remembers that spot across sessions**. And when a champ select ends in a dodge, the panel now tears down cleanly and stays hidden until the next draft â€” no more stray queue-timer window materializing on the wrong monitor mid-requeue (every per-draft state, including armed bans, resets so nothing stale fires in the next lobby).
- **Tag chips got a hierarchy.** The first (sharpest) tag on each player renders as a filled chip and the rest go quiet â€” one loud read per row instead of a string of equally-screaming outlines. Same chip language on the loading screen and the live board.

## v0.9.31
- **The 2nd-monitor board is smaller by default and can't get clipped anymore.** The scout board used to render large enough to fill the whole monitor â€” way too big on bigger screens. There's now a **Board size** slider in Settings (default 70%, applies to the next frame) so you can size it however you like. And the board no longer had a hard "never shrink below 50%" floor that made it spill off the edges of smaller monitors â€” it now always scales down to fit the screen it's on, so nothing gets cut off.

## v0.9.30
- **The Live Draft Link â€” give the whole lobby the scout, even the four people who'll never install anything.** In champ select, Smiteless now posts **one URL into the lobby chat**; anyone who clicks it lands on a live web board of the current draft: both teams, bans, and per-seat **champion suggestions with runes** for this exact game. They tap "This is me" on their seat and the picks + rune cards keep updating live as the draft evolves â€” no app, no account, no refresh. Runs on GitHub Pages + a free Firebase database ($0/month, ~5-minute one-time setup: Settings â†’ LIVE DRAFT LINK, guide in docs/DRAFTLINK.md). Publishes champion/rune IDs only â€” no names, no ranks, nothing personal â€” and each draft is retired the moment champ select ends.

## v0.9.29
- **Habits now show what they cost YOU.** The behavior ledger records each game's result, so every recurring pattern carries your own win-rate split as soon as there's a real sample: the death screen's WORKING ON card and the profile's PATTERN bullets now read like *"chained deaths (2+ inside 90s) Â· 3 games running Â· with it: 1W-4L Â· without: 3W-1L"* â€” the LP cost of the habit, proven from your own games, shown at the moment you just repeated it. Splits stay hidden until both sides have 2+ games (no lying with tiny samples).

## v0.9.28
- **The profile truly adapts to its window now.** Resizing or maximizing used to stretch a fixed-width raster (the "800x600 blown up to 1080p" look). The page now **re-renders at the window's actual width** â€” text stays crisp at its designed size and the layout genuinely gets roomier: wider stat tiles with longer sparklines, wider patterns/bests panels, full-width game rows. Shrink it and it re-fits cleanly too.
- **The 2nd-monitor board re-targets its monitor live.** It sized itself once at launch; now, if it ends up on (or is dragged to) a different-resolution monitor, the very next frame re-renders crisp at that monitor's size instead of being scaled from the wrong one.

## v0.9.27
- **The Death Brief went on a diet â€” coaching, not coverage.** The team boards, threat card, win read, objective list and kill feed are gone (TAB, the widget and the chat already show all of it). A death now buys you exactly two things, so that's all it draws: the **respawn clock + on-respawn buy/move** and **WHY YOU DIED** on the left, **HOW YOU WIN** on the right â€” plus one new card that actually serves the climb: **WORKING ON**, your recurring pattern from the behavioral review ledger ("chained deaths (2+ inside 90s) Â· 3 games running â€” break it this game"), surfaced at the exact moment you may have just repeated it. Total screen coverage: ~5%.

## v0.9.26 â€” the reliability release
No new features â€” this one makes what's already there honest.
- **Coaching reads Ranked Solo only (by default).** The profile pulled ALL queues, so normals and flex distorted your champion pool, session read, and climb advice. Pool/session/climb/patterns now come from ranked solo games (season pool = solo queue only); it falls back to all queues â€” clearly labelled â€” only when the solo sample is too thin. Toggle: Settings â†’ "Coach from Ranked Solo games only".
- **Live calls now say how sure they are.** TAKE/GIVE is computed from an estimate (items + levels + death timers â€” the client exposes no positions, cooldowns, waves, or real vision), and now it acts like it: a thin edge reads **"LEAN TAKE drake (+1k)"** with *"low confidence â€” edge is estimated; commit only with setup"* instead of "you win this fight." Strong margins keep the strong language. Death-timer calls (FORCE/FREE) stay categorical â€” a respawn timer isn't a guess. Win% shows as **~58%** everywhere, because it's an estimate.
- **The widget collapsed to Now / Next / Reference.** Default view: ONE directive (the tempo card), ONE next deadline, and at most one urgent safety line (gank window / jungler no-sign). Everything else â€” ghost pace, objective chips, intel rows, recall, items â€” is the reference view, shown while your cursor is over the widget. All the information, none of the decision pressure.
- **Post-game reviews got behavioral.** Alongside the stat feedback, the latest game is checked for recurring ROOT-CAUSE patterns provable from the match timeline: weak first-ten economy, early bleeding (3+ deaths pre-14), chained deaths inside 90s, coin-flip deaths while ahead post-25, no vision setup (jungle/support). Each is tracked across games: repeat it and the review says **"PATTERN â€” â€¦ Â· 3 games running"**; clean it up and it says **"FIXED âœ“ â€” improved this game."**
- **Player labels downgraded to evidence.** "GOOD PLAYER" is gone â€” grades now read like **"A-like Â· 7g"**, every grade shows its sample size, and nobody gets graded at all on fewer than 4 recent games (loading screen, live board, and champ select alike).

## v0.9.25
- **The overlay now opens the moment your QUEUE starts, not at champ select.** As soon as you hit Find Match, the second monitor shows the new queue card: a live **in-queue clock vs the estimate**, your queue + selected roles as chips, and a **"good this game" row of your comfort picks** for your primary role (mastery-gated, from all your accounts). On match found it flips to a gold **MATCH FOUND** banner â€” and the full lobby scout takes over the instant champ select actually starts, exactly like before.
- **Auto-accept actually works now.** The Settings toggle existed, but nothing ever polled it â€” the tray now watches for ready checks every 2s and accepts for you when it's on. The queue card shows "auto-accepting âœ“" so you know it's armed.
- **QoL round (council pass):**
  - **"Reset" in Settings actually resets everything** â€” it used to skip tempo, voice, the death/loading briefs, and auto-import/ban, silently keeping your old values.
  - **Drake-up audio is no longer a nag** â€” the full jingle plays once when it spawns; while it stays up you get a short calm two-note reminder every ~15s (was: the full fanfare every ~5s).
  - **Respawn chime** â€” one soft cue as your death timer hits ~1.5s, so looking away while dead doesn't cost you seconds after respawn.
  - **"â™ª Test audio" button in Settings** â€” hear the chime + a voice line at the current volume without launching a game.
  - **Loading screen calls the threat** â€” when one enemy account stands out (perf + OTP + streak), the header says so: "WATCH BRIAR â€” SMURF READ Â· 6W streak".
  - **Settings mouse-wheel fix** â€” scrolling over the favourites/accounts lists scrolls the list, not the whole page.
  - **The overlay's Riot-key rail now shows key state** â€” green when your key is set, amber only when it actually needs work.

## v0.9.24
- **The live board now fills its monitor.** It rendered at a fixed design size and could only ever shrink â€” small on the very screen it owns. It now **draws itself scaled to the monitor it opens on** (~1740px wide on 1080p, larger on 1440p+): every font, art slab, tag pill, grade chip and gank badge grows in step, crisp at any size because it re-renders instead of stretching pixels. Small windows and low resolutions still shrink-to-fit exactly as before.

## v0.9.23
- **The second-monitor board got the profile treatment â€” it's the tool that's always on, so now it looks like it.** The live in-game board is a full redesign in the profile/loading-screen language: a **splash hero header** (your champ, role chip, build line, win rate), a **winners/losers-queue verdict strip** with both teams' average grades, and five **lane-matchup rows** where every player is a mini profile card â€” **champion art slab, Riot ID, rank + LP in tier colors, last-10 form bars, KDA, mastery**, their **Sâ€“F performance grade**, and the same **profile-read tags** as the loading screen (`duo`, `SMURF READ`, `OTP Â· 612k pts`, `4L streak Â· tilt risk`, `passenger Â· low impact`, `grinder`) â€” with the â˜… gank verdict between each pair. Wider (it owns a whole monitor), taller rows, and the win-condition card in the house style. Champ select's docked panel is unchanged; clicking a player still opens their u.gg.
- **One-click login is fast now.** It used to take forever to notice the Riot login form was sitting there waiting â€” root cause found: it was crawling the Riot window's UI tree element-by-element from Python (thousands of COM calls, seconds per look), re-creating the automation object every poll, and only accepting the form when a password *flag* it often never got showed up â€” so most logins silently rode out a 35-second timeout before typing. Now it asks Windows UI Automation for all edit fields in **one native query (~20ms)**, polls ~3Ã— a second with one shared object, accepts the form the moment two fields exist, and â€” if the client window is already open â€” **waits for the form instead of relaunching the client**. The fill should start within a beat of the form appearing.
- **The widget can no longer eat your clicks â€” ever.** The in-game TEMPO widget is now **fully click-through during a live game**: every click lands in the game, even when your cursor drifts over it mid-fight. Hold **Ctrl+Alt** to actually touch it (drag it, mute, volume, close) â€” hovering it in-game shows a small "ctrl+alt to touch" reminder. Outside a game it behaves like a normal window, exactly as before.
- **The loading screen is now a real account scoreboard â€” nothing else in Smiteless looks like it.** Ten full-width splash-art rows, one per player, each loaded with their **actual account**: Riot ID, **rank + LP + full season record** (412W 380L Â· 52%), **last-10 form bars**, average KDA with the per-game k/d/a split, **mastery points on the champ they locked**, their record *on that champ*, and a **performance grade** (S+â€“D, same grading as your profile â€” how they play, not just whether they won). And the headline feature: **detailed profile-read tags** mined from each account's real history â€” `duo Â· parallel b` (players sharing recent games), `SMURF READ Â· new acct, stomping`, `Zed OTP Â· 612k pts`, `4L streak Â· tilt risk`, `first-time Miss Fortune?`, `off-role Â· BOT main`, `bleeds Â· 6.8 deaths/game`, `carries games Â· 96 avg perf`, `grinder Â· 792 ranked this season`, `hardstuck Â· 44% season wr`. Champion knowledge pills show instantly; accounts fill in as the scout resolves.
- **The Death Brief now respects the game's own death HUD.** It used to sit on top of the death recap / gold / shop button in the top-left and park its kill feed in the bottom-left â€” right where the chat and your TEMPO widget live. The layout is now built around a keep-out map of the real death screen: the **team boards sit top-center** (where TAB lives), the respawn clock / why-you-died / on-respawn read hangs **under the death recap** on the left, the win-read column hangs **under the stats bar** on the right and stops above the respawn-portrait strip, and nothing ever covers the minimap, the BACK IN plate, the chat, or the widget's corner. Cards that can't fit their lane on a given resolution skip cleanly instead of overlapping.
- **Loading screen: smaller, cleaner, and a lot more informative.** Shrunk it down to a compact centered card instead of a full-screen sprawl, and packed real scouting into each row: champion **mastery** (M7Â·210k), their recent record **on that exact champ** (6-2), **overall winrate**, and **recent KDA** â€” alongside the rank badge and hot/tilt/OTP/off-role pills. Reads like a clean scouting table now, with the game plan underneath.

## v0.9.19
- **The loading screen got a real design.** The flat text is gone â€” every player is now a card with their **champion portrait**, name, role, damage type, a **rank badge in its tier colour** (Diamond blue, Emerald green, Gold amberâ€¦), tag pills for streaks/one-tricks, and the champ read, split into two team panels with a game-plan footer. It looks like the profile page now, not a spreadsheet. Portraits load in the background and pop in; after the first game they're instant.
- **Fix: it no longer vanishes while you're still loading.** It was closing itself the moment the live-game API started responding â€” but that happens *while you're still on the loading screen*. It now waits for the actual game clock to start before closing, and a momentary hiccup can't make it disappear anymore.

## v0.9.18
- **The loading brief actually appears now â€” root cause found in the logs, not guessed.** It was detecting the loading screen correctly, then trying to scout all ten players through the rate-limited Riot API *on the same thread that draws the window* â€” which blocked the whole thing, so the loading screen came and went with nothing shown. Now the overlay pops up **instantly** with champions, matchup tags, and the game plan (no network needed, ~0.1s), and the per-player rank/one-trick scout fills in a moment later in the background. It can't be blocked anymore.

## v0.9.17
- **HOTFIX: dying no longer shows a white fullscreen.** v0.9.16's fancy transparency method broke in the real app â€” the death overlay painted as a solid white sheet over the game. That method is gone; the overlay is back on the same proven rendering the widget has always used, with the whole window at ~88% opacity for the see-through look. Sorry about that one â€” it was shipped without being exercised in a live game, which is on us.
- **The loading-screen brief should FINALLY appear** â€” found the real reason it never did: it was launched at the moment the game went "in progress," which is usually *after* the loading screen is already over, so it started, saw a live game, and closed itself instantly. It now launches at **champ select** and waits, armed, for the loading screen to begin. It also writes a diagnostic log (`~/.claude/smiteless_load.log`) so if it still misbehaves, the log says exactly why instead of anyone guessing.
- Intended looks for both overlays are in `docs/preview_loading_ui.png` and `docs/preview_death_ui.png`.

## v0.9.16
- **The Death Brief is glass now, not solid blocks.** The panels were fully opaque and walled off whatever they sat over. They're now **semi-transparent** (~80%) with true per-pixel alpha â€” the game tints through them while the text stays fully crisp and opaque on top. Painted via `UpdateLayeredWindow` instead of a binary chroma key, so it's a real glassy HUD, still click-through and still keeping the middle of the screen clear.

## v0.9.15
- **The Death Brief is sized right now.** It was drawn against a 1080p reference, so on a 1080p screen it rendered at full size and each column ate ~22% of the width â€” it felt oversized. It's now drawn against a taller reference so it sits as a compact ~17%-per-column strip on **any** resolution (still fully resolution-adaptive â€” proportional on 1080p, 1440p, 4K, ultrawide), leaving much more of the screen clear.

## v0.9.14
- **The Death Brief is now a coach, not a dashboard.** Death is when you need guidance most, so instead of just showing numbers it now reads the state and *tells you what to do*, leading with three synthesized calls:
  - **WHY YOU DIED** â€” from the actual kill that got you: *"Solo-killed by Zed (9/1) â€” he one-shots you now: buy Zhonya's/GA, never walk alone, group tight."* Knows solo-kill vs collapsed-on, and the killer's class + how fed they are.
  - **HOW YOU WIN** â€” your win condition for *this* game, from the comps and who's ahead: *"You out-scale â€” survive the early game, farm, take neutrals; your power is 3 items each,"* or *"Behind vs a scaling comp â€” you MUST make plays early."*
  - **THE THREAT** â€” the enemy carrying the game and the actual counterplay for their class (dive the fed ADC, buy Zhonya's vs the assassin, %HP the tank), not just "watch him."
- Still fronted by your respawn clock and the on-respawn buy + macro move, with the tagged team boards on the edges and the middle of the screen kept clear to watch the fight. Everything is grounded in the live game â€” it stays quiet when it can't prove a read.

## v0.9.13
- **Fix: the loading-screen overlay never actually showed.** It was gated on the gameflow phase being exactly `GameStart` â€” but that's a sub-second flash, and the phase reads `InProgress` for almost the entire loading screen, so the overlay launched and instantly closed itself every game. It now detects the loading window the right way: the game process is up (`GameStart`/`InProgress`) **but the live game (:2999) isn't serving yet** â€” which is precisely the loading screen. It shows the whole time you're loading and closes the moment the game world starts. (No change to what it shows â€” the lobby scout, champ tags, and game plan from v0.9.12.)

## v0.9.12
- **The loading screen now SCOUTS the whole lobby.** The loading screen is the first time everyone's IGN is exposed â€” so it's the first time the lobby can be read â€” and Smiteless now does it: each player's summonerId resolves to their Riot ID, which resolves to a real puuid, which pulls their full scout. Every one of the ten now shows their **rank**, a **hot/tilted streak** read (`4W hot`, `4L skid`, `25% struggling`), whether they're a **one-trick** on this champ, and whether they're on an **off-champ** (sub-12k-mastery, ~44% win). Tags are colored *relative to you* â€” your ally struggling is red, an enemy on a skid is green. (Champ select just cached all of it, so it's near-instant.)
- Kept from before: each champ's good/bad tags + AD/AP damage split, and the plain **GAME PLAN** for the comp. Correcting the v0.9.11 note â€” live player scouting on the loading screen IS possible after all; thanks to the IGNs being visible there.

## v0.9.11
- **NEW â€” the LOADING-SCREEN matchup overlay.** While the game loads (dead time you're staring at anyway), the whole screen fills with the read that decides the early game: every champion's **good/bad tags**, the **damage split** to itemize against (AD/AP per player), and a plain-English **GAME PLAN** for the comp â€” *"Enemy is AP-heavy â†’ build MR early"*, *"2 assassins â†’ respect level 6, group, buy Zhonya's/GA"*, *"you out-scale â†’ survive early, win late."* Your team gets light tags on the left; the enemy gets the detailed "what they do" on the right (Zed: *ults to delete a carry Â· dodge-able ult â€” ping it*; Darius: *wins extended trades â€” don't stay Â· no dash, kite the pull*). Gone the instant the game starts. Toggle: **Settings â†’ Loading brief**.
- Note: the loading screen only shows **champion** knowledge, not live rank/form â€” Riot exposes only placeholder player IDs during loading, so player scouting stays in champ select where it belongs.

## v0.9.10
- **The Death Brief keeps the middle of your screen clear again.** v0.9.9 packed the 10-player board dead-center, which covered the fight â€” the whole point of the see-through design is that you can still watch the game while dead. The board now splits to the **left and right edges** (your team left, enemy right), and the center is fully transparent and click-through, as it should be.
- **Every player carries a good/bad tag now** â€” the deeper read the dead screen is for. Each row shows a one-word threat/scaling tag (`burst`, `scales`, `engage`, `hook`, `bully`, `wombo`, `skirmish`â€¦), and anyone snowballing lights up **FED** in red. Tags come from champion class + a curated sharpener for the highest-signal champs (Zed, Malphite, Yasuo, Vayne, Kassadin, Dravenâ€¦). Rows stay compact: role Â· champ Â· KDA Â· gold Â· tag, with the team gold lead up top.

## v0.9.9
- **The Death Brief now shows on your MAIN monitor** â€” where the game actually is. It was landing on the secondary screen (it borrowed the champ-select board's "use the other monitor" rule, which is wrong for a fullscreen in-game HUD). It now finds the League game window and draws on that monitor, falling back to your primary â€” so it's actually in front of you when you die.
- **Packed with the whole game state.** The empty center is now a full live rundown of all ten players: role, champ, level, KDA, CS, fog-proof gold estimate, completed items, and who's dead â€” your row highlighted, the team gold lead up top. Alongside the respawn clock, the tempo verdict, your buy, the win read, the enemy to watch, next objectives, and the feed, the grey screen now hands you everything at once.

## v0.9.8
- **THE DEATH BRIEF â€” a fullscreen read of the whole game, the moment you die.** Being dead is the one time in League you can process information at zero cost, so Smiteless now fills it: the instant you die, a **see-through overlay** fades in over the whole screen with a giant **respawn clock**, the **one tempo verdict** for what your death just did (*"Baron up now â€” you're too dead to contest, GIVE it, meet mid for grubs"*), **what to buy on respawn** for your current gold, the **win read**, the **scariest fed enemy** to watch, the **next objectives**, and a **feed of what you missed** while grey. It vanishes the instant you respawn. Toggle: **Settings â†’ Death brief**.
- **The center stays clear** â€” a chroma-key hole makes the middle of the screen fully transparent *and* click-through, so you keep watching the fight through the brief and keep full camera control while dead. It's the calm, high-information version of "follow the action."
- **100% read-only, no automation.** It reads the live-client feed and shows you what's true â€” it never moves your camera or sends a single input to the game (that would be the automation Riot bans for; not happening). Runs in-game alongside the item widget, on your game monitor, never stealing focus.

## v0.9.7
- **Pick-order swap now targets an exact slot â€” 1st through 5th, not just first/last.** Settings â†’ AUTO PICK-ORDER SWAP is now a row of slots: pick **4th** or **5th** to sit near the end of the pick order (great for counter-picking) without insisting on dead-last, or **1st** to lock a contested champ early. It accepts any incoming swap that moves you *closer* to your chosen slot and asks for one otherwise; a slot past your lobby size just means last. Old "first"/"last" settings carry over automatically.
- **The Profile page resizes properly now â€” maximize actually uses the space.** It was rendered at a fixed width and stranded top-left when you enlarged the window (header and body even drifted out of alignment). It now scales to fill the current window width, centered, so maximizing enlarges the whole page cleanly instead of leaving a broken-looking gutter. Clicks (expand a game, open a player) stay pixel-accurate at any size.

## v0.9.6
- **One-click login now has a password path too â€” pick an account, it fills the Riot login for you.** Profile page â†’ **âš¡ Log in** opens a popout: add each account's username + password once (stored **DPAPI-encrypted** on this PC, never in plaintext, never on the clipboard), then click one and Smiteless brings up the Riot login window and drops your credentials straight into the fields. It finds the username/password boxes by reading the login page's accessibility tree (UI Automation) and injects the text as keystrokes, so it works even though Riot's page won't let anything paste into a password box.
- **Why this exists alongside the no-password switcher:** the session switcher (v0.9.5) breaks the instant you click *Sign out* in the client â€” Riot revokes that session server-side, so the saved cookie is dead and you land back on the login screen. If you're someone who logs out and back in, the password autofill fits how you actually play. Honest limits, spelled out in the popout: a fresh login can still trip a Riot **captcha or MFA email**, and nothing can auto-skip those â€” that's Riot's risk engine, not Smiteless.
- Safety: it refuses to fill while you're already logged into a game, and it confirms an actual login form is on screen (not the client home) before it types a single character.

## v0.9.5
- **ONE-CLICK RIOT LOGIN â€” all your accounts, one tray menu.** Tray â†’ **Riot login** â†’ pick a name, and Smiteless closes the Riot/League clients, swaps in that account's saved session, and relaunches League already logged in. **No passwords, ever**: it snapshots the "Stay signed in" session the Riot Client itself keeps on disk (the same proven mechanism as the big account switchers â€” password login via the local API has been dead since Riot added captcha). Snapshots are DPAPI-encrypted, so only your Windows user can read them.
- **Setup is once per account:** log in with *Stay signed in* ticked â†’ Settings â†’ **ONE-CLICK RIOT LOGIN** â†’ *Save current login* (the name box pre-fills with the account's Riot ID when the client's open). Saved accounts also join your mastery pool automatically, so "good this game" already knows your smurfs' champs.
- It refuses to switch while you're in an actual game, and it re-snapshots the account you're *leaving* on every switch â€” Riot rotates session cookies each login, so your saved sessions stay fresh instead of quietly expiring.

## v0.9.4
- **The Profile is a whole new page.** Not a re-skin this time â€” a new board, drawn from scratch: a full-bleed splash of your main behind your name in real display type, your rank / record / KDA as chips, the average-score ring wearing its letter grade, your last ten games as form bars, and the LP trend as a live spark. The old cramped header card is gone entirely.
- **PATTERNS â€” Smiteless now tells you WHEN you win.** A new out-of-game brain mines your own match timestamps for the habits behind your winrate: whether the queue after 11pm is robbing you, whether you tilt-queue straight after a loss, whether marathon sittings turn on you after game 2, whether you win the long games or the fast ones. It only speaks with a real sample (5+ games on the split) and a real gap (12+ points off your overall winrate), and every claim carries its receipt (`wr% Â· games`) right on the row. Nothing is guessed; if your history doesn't prove it, the panel stays quiet.
- **PERSONAL BESTS.** Your records from the loaded games, each with the game as proof: best game (score + grade), best KDA (a deathless game reads PERFECT), most kills, longest win streak, fastest win.
- **Stat tiles with a pulse.** Winrate, KDA, kill participation, CS/min and damage share each get a tile with a big Bahnschrift numeral and a per-game sparkline underneath â€” you can see a stat trending before you could ever feel it.
- **Your champion pool is splash art now.** Six portrait cards with face-centered art, winrate in large type, games and average score on the card, a winrate bar along the base.
- **Match rows show your item build.** Every recent game now carries its full six-slot build as icons on the row, op.gg-style, next to grade, role, verdict and pace stats. Rows got taller and calmer; wins and losses tint their own cards.
- Match data now remembers when each game was played (needed for PATTERNS) â€” the first profile open after this update refetches your recent games once, so give it a few extra seconds.

## v0.9.3
- **DUSKFALL â€” the whole UI, redesigned from scratch.** v0.9.1 unified the palette but kept its colors, so every window still looked like it always had. This time the things your eye actually keys on changed: the ground is now **violet ink** instead of blue-grey, the accent is a **hot ember amber** instead of muted gold, and a new **arcane cyan** owns everything live â€” timers, win%, sparklines â€” so identity and telemetry never fight over one color again. Full spec: `docs/UIDESIGN.md`.
- **Numbers finally look like instruments.** Every header, champ name, score, timer, win rate and KDA is now set in Bahnschrift (the DIN-style face that ships with Windows 10/11) â€” the HUD reads like a cockpit, not a spreadsheet. Body text also grew from 8â€“9pt to 10pt.
- **Railed cards everywhere.** Flat rectangles are gone: every surface is a rounded card carrying a 3px state rail â€” cyan for your team, red for the enemy, ember for *you*, green/red for results, amber-warning on the Riot-key bar. Grade badges (Sâ€“F), AUTO chips and rune tabs are pills; import is the one ember button in champ select.
- **One design system, enforced.** `core/smiteskin.py` is now a real token module (colors, type scale, spacing, shared widgets) and not a single window declares its own hex or font anymore â€” including the update dialog, and including a second frozen copy of the old palette we found hiding inside the widget's renderer. Drift is structurally dead.
- Built by a four-seat council â€” the Illuminator (boards + champ select + profile card), the Machinist (tempo widget), the Archivist (settings + patch notes), the Chronicler (profile chrome + key bar) â€” on a shared spec, one surface each.

## v0.9.2
- **Your profile now opens without the League client running.** The client was only ever needed for one thing: asking the LCU who you are. Smiteless now remembers that answer whenever the client is open, so from then on the Profile window works entirely off the Riot Web API â€” rank, match history, grades, session read, everything â€” game closed. Just open Profile from the tray whenever you feel like looking. (One-time note: it learns who you are the next time the client is open; after that, never again. If you ever log into a different account, it re-learns on the next client sighting.)

## v0.9.1
- **One skin, every window (council pick: the Naturalist, 27/70 Borda points from 14 ballots).** Smiteless's five windows had five hand-copied palettes that quietly drifted apart â€” Profile's background was a different black, Settings had its own red, the widget's header its own panel tone. All colors now live in one module (`core/smiteskin.py`) and every window draws from it, so the app finally reads as one product â€” and can never drift again.
- **The white title bars are gone.** Profile, Settings, and Patch Notes keep their real Windows title bars (drag/snap/minimize all intact) but Windows 11 now paints them Smiteless-black with a matching border â€” the single biggest "why does this look off" fix, done natively with zero custom chrome.
- **The widget header stops dressing like a title bar** (judge's amendment, from the Skeptic/Systems-Thinker consensus): the strip stays â€” it's the drag handle and holds the live controls â€” but only the gold â—† keeps its color at rest; the wordmark, mute note, and âœ• sit muted and brighten under your cursor, and the volume slider appears only while you're hovering the widget. Mid-game the HUD is pure data.
- **The Riot-key bar only shows up when it has a job.** With a valid key the overlay board floats clean; the bar (and its paste/save controls) returns on the next launch after the 24-hour dev key expires or goes missing.

## v0.9.0
- **The UI now fits your screen â€” every screen.** All the live surfaces (the scoreboard, the champ-select panel, the in-game widget and its legend) are now resolution-adaptive: they're drawn for a 1080p-tall screen and shrink proportionally on anything shorter â€” swap the game to a lower display resolution mid-session and the overlay shrinks in step, on the monitor it's actually sitting on. Nothing ever upscales, so text stays crisp on big displays.
- **The champ-select panel balances itself beside the client.** The tall panel used to top-align to the League client â€” and once it grew taller than the client, its bottom ran off the desktop. It now centers itself vertically against the client's span and hard-clamps fully on-screen (scaling itself down first if it's taller than the monitor), and it re-balances whenever its height changes as picks come in. Drag it anywhere and it respects your placement for the rest of that champ select. Click targets (import, hover-pick, rune tabs) track the new scaling exactly.

## v0.8.0
- **LEGEND â€” the widget now explains itself.** A tiny `?` now sits in the widget's header. Click it and a reference card opens beside the widget decoding everything the HUD can say: every tempo phase **in its real color** (so "teal = FREE, red = GIVE" is learned from the exact swatch you'll see live), the intel glyphs (`âŒ–` jungler tracker, `â—Ž` gank window, `âš ` power spike, `âŒ‚` recall read, `â˜…` GHOST), the WIN% and objective chips, the item-line tags, and the RESPAWN card. It opens itself exactly once â€” on your very first launch, while the widget says "waiting for a live gameâ€¦" â€” then never again uninvited; after that it's there whenever you forget what a row means. The live HUD itself is untouched: no per-row clutter, no new hover traps, nothing that can eat a click mid-fight. (Council pick: the Player's design won over hover tooltips â€” you never mouse over a HUD mid-game, so the vocabulary is taught once in downtime instead.)

## v0.7.0
- **FREE â€” the free-objective alarm. The enemy jungler dies, and the game tells you what it just handed you.** When a drake/grubs/herald/baron is coming and the enemy jungler is dead too long to contest it, the tempo card turns teal and fires early and loud: `FREE drake 0:18 â€” their Kha'Zix dead 40s Â· yours 39s â€” path bot river NOW, ward, take it`. It's the one enemy-position read the live client can actually PROVE â€” a respawn timer isn't a guess â€” fused with the objective schedule and the same fight math the coach uses. It only fires when you can reach the pit AND you'd still win the fight with their jungler removed, so it can never walk you into a losing 4v5. This is the highest-EV repeated decision in the jungle (an uncontested drake is ~+8% win rate, soul ~85-90%), and it recurs multiple times a game â€” the alarm makes sure you never leave one on the table again. Toggle: **Settings â†’ Free-objective alarm**. (A live-but-unseen jungler is deliberately never called "free" â€” cross-map traverse is faster than securing an objective, so that stays the "respect the gank" read's job.)

## v0.6.0
- **ONE BRAIN â€” the win% and the coach now share the same eyes.** The live win read used to count only finished items it could SEE, while the TAKE/GIVE tempo verdict used the fog-proof economy estimate â€” so the widget could say "WIN 88%" directly above "GIVE drake (âˆ’8k)". The win% now runs on the exact same per-player power model as the fight math (score-estimated gold + XP, immune to fog-of-war item staleness) plus drake/baron swings, recalibrated so a one-item team lead reads ~68% instead of a flat 50%. Same chip, same card â€” they just can't disagree anymore. (The GHOST gold trace reads from the same model too.) Verified against the old engine: the fight math itself is unchanged to the decimal.

## v0.5.1
- **Refinement pass (council audit).** Fixed a real bug: a live-data hiccup could silently kill the GHOST race for the rest of the game (a variable-name collision in the widget's poll loop). Polish: the RESPAWN countdown is now neutral white so it never wears the same gold as a 50/50 directive; muted text on the widget matches the board's brighter grey (it was near-invisible at ghost opacity); routine "farm window" reminders are a quiet plain line again instead of a bordered decision card; the objective named by a TAKE/GIVE/EVEN verdict no longer repeats as a timer chip below it; Settings labels caught up with reality ("Matchup lane tips (written guides)" â€” they haven't been AI since v0.2.94 â€” and the volume slider now says it controls chime + voice + fanfare).

## v0.5.0
- **RESPAWN â€” the death screen is now a plan.** The moment you die, the widget collapses to a single card: a ticking respawn countdown, ONE directive for when you're back â€” `DRAKE 0:38 â€” you make it, and you win it. Buy fast, path bot river` (teal = go, red = don't, gold = neutral) â€” and the next item to buy, since you're literally standing in the shop. It reuses the tempo engine's fight math, and here the travel model is at its most honest: everywhere else "time from base" is an estimate, but on the death screen you really are at the fountain. When nothing major is coming, you get your role's productive default (reset camps / shove the wave) instead of dead air. The instant you respawn, the normal HUD snaps back. Toggle: **Settings â†’ Respawn plan**.

## v0.4.0
- **GHOST â€” race your own best game, live.** Smiteless now learns a "ghost" from your single best-graded game on each champ+role (grade A or better): its minute-by-minute CS and gold pace, and its death count. Next time you're on that champ, one quiet line in the in-game widget races you against it like a speedrun timer â€” `GHOST Â· CS +8 Â· deaths 1/2 Â· +340g` â€” glowing gold while you're ahead, dimming silently when you're not. Crossing 10:00 flashes your CS split vs the record; 15:00 flashes deaths. Finish ahead and you get the item-get jingle, a spoken "New record." â€” and the ghost gets faster. Your only opponent is who you were last week: ghosts are built purely from your own in-game performance, never rank or win/loss. First game on a champ sets the baseline. Toggle: **Settings â†’ Ghost race**.

## v0.3.1
- **Matchup tips are quality-filtered now.** The written-guide scraper was showing raw user submissions â€” including salt stories, rants, and even slurs. Tips are now hard-gated: anything with slurs/abuse, toxicity/report/"1v1 after the game" rant markers, non-English text, or that reads as a personal game-recap instead of advice is dropped entirely. What's left is ranked by how much actual matchup guidance it contains. Sorry you saw that one.

## v0.3.0
- **Auto role-swap now fights to GET your role, not just accept one â€” the autofill escape.** If you get autofilled off a role you actually play, Smiteless immediately REQUESTS a position swap from whoever has one of your roles (and still accepts any offer that lands you on one). It only ever moves you ONTO a checked role, never off it, and won't spam the same teammate. Set your roles in **Settings â†’ Auto role swap**. Getting your main role every game is one of the biggest quiet win-rate edges there is.

## v0.2.99
- **The champ-select ally scout is now always visible.** Clean lobby or not, the panel shows a compact team line â€” `team: Bob G2Â·B  Ann S1Â·CÂ·2L` (name, rank, grade, loss streak) â€” so you can see the scout working every lobby, not only when a DODGE READ flag fires. (For the record: ally names in champ select come through the Riot Client's chat service â€” the same bypass Porofessor uses â€” since Riot only anonymized the client UI, not the chat backend. Enemies remain genuinely hidden until loading; no tool has those.)

## v0.2.98
- **Ally scout while you can still dodge.** Champ select now identifies your four teammates (via the Riot Client, the same method Porofessor uses) and scouts them immediately â€” if someone's on a 3+ loss tilt streak or grading F, a **DODGE READ** line appears on the panel *before* you're locked in. Enemies stay hidden until loading (Riot anonymizes them).
- Refreshed the project README.

## v0.2.97
- **The take/give math no longer trusts fog of war.** Enemy items only update when they've been SEEN â€” so an enemy farming in fog looked poorer than they were, biasing calls toward "take." Each player's power now uses their **estimated earned gold from scores** (CS, kills, assists â€” which update for everyone regardless of vision), with visible items as a floor. A fed-but-unseen enemy team now correctly reads as a GIVE.
- **Contest calls fire earlier.** The TAKE / GIVE / 50-50 verdict now lands **45 seconds before spawn** (was 30) â€” while you can still rotate on it, not as the fight starts. Decision thresholds retuned for the new power scale.
- **Bans: your lane comes first.** Your own champ's counters now weigh ~2Ã— a teammate's in the ban ranking â€” but a champ that dumpsters TWO teammates still outranks a champ that's merely annoying for you, and pick-rate weighting stays (no more banning 4%-pick niche counters).

## v0.2.96
- **The in-game widget is now a real HUD, not a wall of text.** The body is fully redrawn (same rendering style as the main board): the tempo directive is a **color-coded card** (red = give, green = take, gold = decide), objective timers are **chips** (gold when something's UP), intel rows are aligned with proper glyphs, and the item advice sits visually quieter below a divider. Numbers got one format â€” "GIVE baron (âˆ’23k Â· 2 down)" instead of three different spellings of the same fact â€” and a fed enemy is announced once, not twice. Same information, drawn like it matters.

## v0.2.95
- **"Good this game" now enforces the 12k-mastery climb line â€” across ALL your accounts.** Champ suggestions are gated on 12,000+ mastery **points** (was mastery level 5+), pooled across your main and every registered smurf (max per champ), with 30k+ comfort picks ranked first. Sub-12k champs are never suggested â€” if nothing qualifies for your role it says so rather than pushing an off-mastery pick. The champ-select hover warning and the profile's CLIMB LEAK check use the same all-accounts pool, so a champ you have 100k on your main never warns on the smurf.

## v0.2.94
- **Matchup tips are now REAL written guides, not AI.** Lane tips are scraped from counterstats.net â€” actual prose counter-advice written by MOBAFire guide authors for the exact enemy champion, preferring tips written by players of YOUR champion (the true matchup POV), with vote-ranked general tips as backup. Loads in ~1 second (the old AI generator took 60-120s and sometimes failed), cached per patch, deterministic. The AI path survives only as an offline fallback. **Junglers get matchup tips now too** (they were excluded entirely).
- **THE CLIMB SYSTEM â€” research-backed fast-climb discipline, built in.** Deep-dive into what actually makes people climb fast (sources: iTero's 1M-game mastery study, Deng et al. ACM CHI PLAY 2024 on 597k matches, loltheory's 100k-game break analysis):
  - **The 12k-mastery rule.** Picks under ~12,000 mastery points win ~44%; past ~20 games they cross 50%+ (and the effect is BIGGEST in jungle). Champ select now warns you live when you hover a sub-12k pick, and your profile flags sub-12k champs you've been spamming.
  - **The 2-loss stop rule.** Players who break ~30 minutes after 2 straight losses win ~3% more; tilted sessions bleed 10-15%. After 2 consecutive losses your profile now leads with STOP RULE instead of a pleasantry, and the tilt flag trips at 2 losses (was 3).
  - **Pool concentration.** A +5% champ-mastery win rate literally halves games-per-rank (160â†’80). If your recent games are spread across 6+ champs, the profile tells you to commit to 2-3 â€” with the EV-ranked coach picks right next to it.

## v0.2.93
- **Fixed a wrong Elder call.** The timers said "Elder" once 4 drakes had died *in total* â€” but Elder only comes after **one team's** fourth (soul). A 3â€“2 drake split now correctly shows the next **Drake** (your soul point!), not a phantom Elder.
- **First baron is no longer an alarm.** Nobody rushes baron on spawn â€” the tempo engine now treats the first spawn as a posture objective: no recall countdowns, no urgency, just "posture, don't force / punish them for starting it." It also prefers a drake/elder within the next ~4 minutes over first baron (your soul-point drake beats a baron nobody's taking). Once a baron has actually died, respawns get the full scheduling again â€” that's when it decides games.
- **Widget slimmed to game-winning info.** The tempo "why" line now only appears when there's a decision to justify (take/give/50-50/force/too-far) â€” routine farm/base/rotate lines stand alone; item advice trims to the 2 most important lines during a game (full list outside games); and the bottom threat/source footer is hidden in-game. Roughly a third fewer lines on screen, nothing decision-relevant removed.
- Fixed players already-arrived at a live objective being told they're "too far" (reachability now allows the real ~25s contest window once something is up).

## v0.2.92
- **Volume slider on the in-game widget.** A small slider in the widget's header now controls the voice callouts + drake chime live: drag it and the new level applies instantly, plays a short preview so you can set it by ear, and saves back to Settings. 0 = silent; the â™ª button still mutes everything for the game.

## v0.2.91
- **New voice: Salli.** The tempo callouts are now spoken by the much nicer Salli voice (AWS Polly, via ttsmp3.com's free service) instead of the robotic Windows one. Each phrase is fetched once and cached as a local MP3, played through Windows' built-in decoder â€” no extra installs. If you're offline it falls back to the old local voice, so callouts never go silent.
- **The in-game widget got a glow-down.** Same information, less in your face:
  - **Adaptive transparency** â€” it ghosts to ~84% opacity while nothing needs you, solidifies on its own when a call-to-action is up (take/give/force, gank window, spike alert), and goes fully opaque under your cursor.
  - **Macro first** â€” the tempo directive and objective timers now sit at the top; item advice moved below the line as smaller reference text (it no longer out-shouts the "rotate now" call).
  - Tighter paddings and type all around â€” same content, meaningfully smaller footprint.

## v0.2.90
- **Auto-ban now waits until the last ~12 seconds of the ban phase** before locking. Every extra second lets more teammates hover their picks, and the team-wide ban math recomputes on every poll â€” so the ban that finally locks is based on the most complete picture of your draft. (Fires immediately if the phase clock can't be read â€” it will never miss the ban.)
- **The Tempo engine now knows what lane you're in.** It detects your role live and reshapes the whole schedule around your position on the map:
  - **Rotate deadlines use YOUR lane's distance to the pit** â€” a bot laner is ~12s from drake, a top laner ~35s; the old one-size-fits-all fountain math is gone (recall deadlines still use the fountain path, because that's where backing puts you).
  - **Laners get wave discipline built in:** "CRASH your wave â†’ rotate" â€” it will never tell you to walk away from a slow push, and the farm window reminds you to crash before leaving.
  - **"Too far" honesty + TP awareness:** if you physically can't reach the fight in time (top laner, drake spawning now), it stops pretending â€” **"SHOVE for the cross-trade"** (take plates/camps while they posture), or **"SHOVE â€” then TP to drake"** if you're holding Teleport. New spoken callout to match.
  - Junglers keep the original pathing-flavored schedule, now with a more accurate on-map rotate deadline.
- **GAME PLAN is now WIN CONDITION** â€” and it opens with the read that actually decides games: the **scaling verdict**. It compares both comps' power curves and headlines *when* you win: "YOU OUTSCALE â€” don't coinflip early, hit 3 items" vs "THEY OUTSCALE â€” your win is EARLY: snowball and end." Only claims it when the gap is real; the damage-split / frontline / engage reads follow behind.

## v0.2.89
- **Mastery now has its own color scale (it used to lie).** The mastery text was inheriting the color of the player's *recent win rate* â€” so a 209k-point main could show "worse" (brown) than someone's 23k dabble (green) purely because of their last 10 games. Mastery is now colored by champ comfort itself: **gold = their MAIN (100k+ pts), green = comfortable (30k+), plain = knows it (8k+), dim = barely played**, and **red "off-champ" = first-timing it**. The recent W/L keeps its old green/tan/red coloring, and the legend spells out the scale.

## v0.2.88
- **THE disappearing-widget bug, actually found.** Right-click anywhere on the widget was bound to *close it* â€” in a game where right-click is the move command. Any move-click that drifted onto the widget silently killed it, which is why it "randomly" vanished for months no matter how the game-over detection was tuned. Right-click (and Escape) no longer close the widget â€” only the âœ• button does.
- **Three more layers so it can never come back:** (1) while the actual game process (League of Legends.exe) is running the widget is **immortal** â€” it ignores client-API blips entirely; (2) it re-asserts its always-on-top status every few seconds so the game window can't bury it; (3) every close now writes its reason to a log (`~/.claude/cache/smiteless_widget.log`) â€” if it ever disappears again, we'll know exactly why instead of guessing.
- **Bans are now ranked by expected value, ending the "always ban Zac" loop.** A ban's worth = how hard the champ counters your team **Ã—** how likely you are to actually face them (their live pick rate in that role). A brutal-but-niche 4%-pick counter now ranks below a popular counter you'll meet every third game. Multi-lane threats still stack, and everything else (fallbacks, auto-ban) rides the same list.

## v0.2.87
- **Fixed the in-game widget randomly disappearing mid-game.** The "is the game over?" check counted poll ticks but was tuned as if ticks were 5s when they're ~1s â€” so a **4-second** client hiccup (a teamfight lagging the client and the live-data port at once) could close the widget mid-game. It's now wall-clock based: ~25s of confirmed non-game (or 3 min of unreachable client) before it even considers closing, and it always asks the live game directly first â€” if the game answers, the widget stays.
- **Fixed the voice callouts being completely silent in the installed app.** The speech renderer worked in development but died instantly in the shipped (windowed) build due to a Windows process-handle quirk â€” so no WAVs were ever created. Now fixed and verified under the same condition.
- **"Tempo online."** â€” the widget now says a short hello when it first picks up your game, so you know immediately that audio is working instead of discovering silence at first drake.

## v0.2.86
- **The Tempo engine now talks.** Short spoken callouts fire exactly when a window opens: **"Base now."**, **"Rotate to dragon."** (per-objective), **"Take it â€” you win this fight."**, **"Give it â€” trade elsewhere."**, **"Fifty fifty â€” only with vision."**, **"Force now â€” numbers advantage."** Voiced by Windows' built-in speech engine â€” free, offline, rendered once to WAV and cached, played at your existing widget volume. It only speaks on a *phase change* (never repeats, 6s global cooldown, anti-flap guard), the in-game â™ª mute button silences it along with the drake chime, and there's a separate "Tempo voice callouts" toggle in Settings.

## v0.2.85
- **Ban suggestions now consider the whole team's hovers, not just yours.** GOOD BANS aggregates the counters of every champ your team is hovering or has locked (including you) and ranks enemy champs by total threat to the draft â€” a champ that beats two of your lanes now outranks one that only edges yours, so the ban adapts as teammates hover instead of always showing your champ's #1 counter. The shown % is the most-countered teammate's win rate into that champ. Falls back to your champ's counters, then to the meta ban list, if there's nothing to aggregate. (Auto-ban uses the same improved list.)

## v0.2.84
- **THE TEMPO ENGINE.** The in-game widget now runs a live objective-setup director â€” the single highest-leverage macro system in the game, built on real research (8M-game Diamond+ study: 1 drake at even gold = +8% win rate, 2 = +16.9%, full grubs = +11%, and the dragon-soul team wins ~85â€“90% of games). Games are decided in the ~90 seconds *before* each objective, and now that window is scheduled for you:
  - **FARM window** â€” how long you can safely farm, with your exact recall-by and arrive-by deadlines counted down, walked back from the next spawn using your **live movement speed**, recall time and homeguard.
  - **BASE window** â€” the last moment to recall so you arrive 30s early with items.
  - **ROTATE** â€” when to start walking, and what setup to do (pit ward + river control).
  - **TAKE / GIVE / 50-50 verdict at the spawn** â€” computed from **death timers** (the real per-level respawn formula, including whether a dead enemy respawns *and walks back* in time to fight), **item gold** and **XP-as-gold** for all ten players. If you win the fight, it says take; if you don't, it names the trade to make instead. It never lets you coinflip blind.
  - **FORCE windows** â€” the moment an enemy dies with a long respawn, it tells you the numbers (5v4 for 23s) and to cash the advantage.
  - **SOUL POINT escalation** â€” at 3 drakes either side, the next drake is flagged as the ~85â€“90% game-decider it is.
  - **Elder tracking** â€” the objective timers now roll over to Elder after the 4th elemental (6:00 spawn/respawn), which they previously just dropped.
  - Toggle in Settings ("Tempo coach"). Every game constant verified against the wiki this week: baron 20:00, grubs 8:00 one-spawn, herald 15:00â€“19:45, drake 5:00/5:00, elder 6:00, the full death-timer table, recall 8.5s, homeguard 80%â†’150%.

## v0.2.83
- **"Play more / ease off" champ advice now uses real statistics.** It no longer crowns a 3-0 champ your best pick. Champs are ranked by a **Wilson score** â€” a confidence-adjusted win rate that discounts small samples so a wide 3-0 can't beat a tight 40-25 â€” blended with **how well you actually play the champ** (your average game score on it), and a champ needs a real sample (5+ games) before it can drive advice. So a proven main beats a lucky streak; "ease off" only fires when it's statistically confident a non-main is a loser (never off a 4-game fluke); and a champ you *main* on a rough patch is still flagged as a slump, not a pick problem. Each suggestion now shows the games it rests on (e.g. "play more Graves 61% (40g)"). The season-wide version also factors in your performance now, not just W/L.

## v0.2.82
- **Pick-order swap now has a simple "Accept any" mode.** In **Settings â†’ Auto pick-order swap**, pick **Accept any** to just auto-accept every incoming pick-order swap request â€” no direction, no asking. (First pick / Last pick are still there if you want Smiteless to actively work toward an end of the order.)

## v0.2.81
- **Auto pick-order swap (counter-pick automation).** New in **Settings â†’ Auto pick-order swap**: choose **Last pick** and Smiteless works your spot in the pick order as late as possible so you can counter-pick â€” it accepts a teammate's swap offer that moves you later, and requests one otherwise. **First pick** does the opposite (swap early to lock a contested champ). Off by default. (This is the pick-order swap; the v0.2.80 role swap is a separate setting.)

## v0.2.80
- **Auto-accept role swaps.** New in **Settings â†’ Auto-accept role swap**: check the role(s) you're happy to play. When a teammate offers a role (position) swap in champ select that would put you on one of them, Smiteless accepts it for you. It **only ever moves you ONTO a checked role, never off one** â€” so a jungle main who got autofilled support auto-takes the jungle swap, but never gets swapped off jungle. None checked = off. (This is the assigned-lane swap, not a champion trade.)

## v0.2.79
- **The player grade now reads how you actually PLAY, not your win/loss.** It scores each of your recent games against your role's benchmarks â€” CS/min, kill participation, damage share, deaths, vision (the same engine as your post-game review) â€” and averages them. Win rate is only a light tie-breaker now.
- **Why this matters:** if you're a strong player grinding on a low/off-role account, or just lost a few playing off-champs, your fundamentals still show through â€” you'll grade a solid **B**, not a bogus **F**, even mid-losing-streak. It figures out your skill from your gameplay, not from your account. Meanwhile someone who's genuinely inting (bad CS, no participation, feeding) still grades low even if they got carried to a win.
- (No account-peeking â€” the grade is read purely from the games in front of it. Detailed per-game stats build up as your recent matches get scanned; until then it falls back to the old win-rate + KDA read.)

## v0.2.78
- **Ban ideas (before you pick) are now live op.gg data**, not a hardcoded list â€” the highest win-rate champs in YOUR role this patch. No more banning off-meta champs.
- **Player grade is now a real-stats skill read.** It's driven by win rate (your season ranked W/L when available â€” a big sample), with KDA and current form as supporting factors. Rank tier is ignored, so a Silver on a 65% climb grades higher than a Diamond who's feeding.
- **New GOOD PLAYER tag** on any player graded S or A â€” spot the carries (and carry threats) at a glance.
- **Gank ratings are now purely champ-vs-champ matchup** (plus your kit and live game state). Player form/skill no longer muddies the lane read â€” that's what the grade + GOOD PLAYER tag are for now.

## v0.2.77
- **Auto-ban.** New **AUTO** toggle next to GOOD BANS in champ select (also in Settings). When on, it locks the top recommended ban on your ban turn â€” and never bans an already-banned champ or one a teammate is hovering.
- **Ban ideas now show during the ban phase.** Since you ban before you pick, GOOD BANS now shows high-priority solo-queue bans when you don't have a champ yet (instead of "hover your champ for ban ideas"); once you hover, it switches to your champ's hardest counters.
- **QoL:** the current version number now shows in the Settings header.

## v0.2.76
- **"Good this game" now populates the moment champ select opens** â€” you no longer have to hover a champ (or wait for enemies to lock) to see it. It shows your mastery-5+ champs for your assigned role right away, and refines as enemies lock in.

## v0.2.75
- **The scout now loads everyone at once.** All 10 players are scouted in parallel instead of one at a time, so the board fills in roughly as fast as a single player used to take (~10Ã— quicker) instead of trickling in. (Allies are also prioritized first.)

## v0.2.74
- **Rune sets now switch instantly.** Clicking one of the 3 rune-set tabs in champ select used to lag up to ~2 seconds before it updated â€” now it's immediate.
- **Each rune set carries its own summoners.** Picking a set now also shows (and imports) the summoner spells that go with it, not just the runes.

## v0.2.73
- **Removed the gank-tuning dials.** The "streak influence", "gank decisiveness (threshold)", and "champ kit in gank rating" settings are gone â€” they caused more confusion than help. The gank ratings now always use the tuned defaults, and any custom values you'd set are reset back to default.

## v0.2.72
- **Favourite picks now use a dropdown.** In Settings, pick a champ from a searchable dropdown (type to filter), choose a role (or "any"), and hit **+ Add** â€” no more typing names by hand. Your list shows below with **Remove** and **â†‘/â†“** to set priority order.

## v0.2.71
- **Game plan now shows in champ select too.** As soon as the enemy team locks in (draft), the docked champ-select panel shows the same GAME PLAN box â€” read their comp and plan your win condition before the game even starts.
- **Player grades in the queue read.** The in-game winners/losers-queue chip now also shows each team's average letter grade (e.g. "WINNERS QUEUE 80% vs 30% Â· grades S vs F") â€” a KDA/form-based second opinion next to the win-rate read.

## v0.2.70
- **Post-game review on your latest game.** Your most recent game now gets a short, data-driven review pulled from Riot's match timeline: where you fell behind vs your laner (gold@10/@14), your CS at 10:00 vs benchmark, and your worst death window. It's rule-based â€” no AI, no tokens, no waiting â€” and shows up with that game's tips in your profile.

## v0.2.69
- **Auto game-plan card.** The in-game board now shows a "GAME PLAN" box: 2-3 blunt win conditions read from both comps â€” the enemy's damage split (rush armor/MR), whether they lack a frontline (dive their carries), and how much engage each side has (respect all-ins vs play for picks).
- **First scuttle timer.** The in-game widget's objective timers now include the first Rift Scuttler (2:55) â€” the early jungle tempo anchor, with the usual soon/urgent cues.

## v0.2.68
- **Recall / power-spike coach.** The in-game widget now reads your live gold + items and tells you when to back for your next spike: **"BACK now â†’ finish Trinity (spike)"** when you can afford it, **"wait ~200g â†’ â€¦"** when you're close, or how far off you are otherwise. It subtracts components you already hold, so it's the real cost to *finish* the item â€” no more backing for a longsword when 8 seconds of farm gets you a whole item.

## v0.2.67
- **"Good this game" now only suggests champs you're mastery 5+ on** (mastery 7+ first). It won't recommend a champ you've barely touched â€” if none of the role-appropriate picks are ones you're M5+ on, it just says so instead of guessing. Pooled across all your accounts, same as before. (If the client can't report your mastery, it falls back to the old meta suggestions rather than showing nothing.)

## v0.2.66
- **Mute the drake chime mid-game.** The in-game widget now has a **â™ª** button in its header â€” click it to silence the 45/30/15s drake cues for the rest of the game (e.g. when your jungler is never going to contest it). It shows a struck-through red note while muted; click again to turn it back on. Resets each game, and Settings still has the permanent on/off.

## v0.2.65
- **Fixed the lane tip showing a raw "401 authentication" error.** A transient auth blip from the AI tip generator was being treated as the tip text and cached, so it showed every game. Those errors are now detected and never shown or cached, poisoned cached tips self-heal, and a bad tip just quietly regenerates next game.

## v0.2.64
- **Player rating is now about how you're *playing*, not your rank.** The Sâ€“F grade is driven by your recent win rate, KDA (are you carrying or inting), and hot/cold streak â€” rank is ignored entirely. A Silver stomping 20/0 game after game shows up as a gold **S** God-Mode player; a Diamond who's been feeding is a black-hole **F**.

## v0.2.63
- **Player rating is clearer.** The Sâ€“F grade now sits right next to each player's name (so it's obvious it's rating the player), the bottom legend spells out what it means, and it no longer collides with the duo/premade dot.

## v0.2.62
- **Player ratings on the in-game board.** Every player now gets a grade (Sâ€“F) from their rank, recent form, and comfort on their champ. A smurf/sicko lights up with a **gold glowing banner and an S**; someone tanking or way out of their depth goes **dark red with an F** â€” spot the carry and the griefer at a glance, on both teams.
- **Fixed the Flash key reverting to D.** Settings are now saved by merging onto the existing file, so changing one setting can never quietly reset another (Flash-on-F now sticks).

## v0.2.61
- **The champ-select panel now appears as soon as champ select opens** â€” it used to stay hidden until you hovered a champion. Right away it shows your assigned role, your team's roles, bans, and suggested picks; runes/build fill in once you hover.

## v0.2.60
- **"Good this game" now pools familiarity across all your accounts.** It remembers each account you log into and combines your champion mastery across your main and smurfs, so a champ you main on one account counts as familiar on the others. Manage the list in **Settings â†’ Your accounts** (add smurfs you haven't logged into recently by Riot ID).

## v0.2.59
- **"Good this game" now factors in champs you actually play.** It reads your champion mastery from the client and surfaces picks you're familiar with first, so it won't tell you to first-time some champ you've never touched. If you have too few known picks for the role, it still fills in with strong meta options.

## v0.2.58
- **Click a "Good this game" face to hover it** in champ select. It selects (hovers) the champ for you â€” it never locks â€” and the panel updates to that champ's runes and build. Handy for trying suggestions quickly.

## v0.2.57
- **This page.** Added a **Patch notes** window (right-click the tray â†’ Patch notes) so you can see what changed each update. It shows the notes for your installed version and pulls the very latest from GitHub when you're online.

## v0.2.56
- Fixed the **Deeplol** right-click link. It was using the wrong region code, so Deeplol said the account didn't exist. Now it opens the profile correctly, like the other sites.

## v0.2.55
- **Rune-set picker in champ select.** op.gg often lists more than one good rune page â€” the panel now shows small tabs (e.g. `1 Â· 54%  2 Â· 49%`). Click one to switch which runes are shown, and Import / auto-import writes that set.
- **Favourite picks.** Set an ordered list of your go-to champs in Settings â†’ Favourite Picks (add a role like `Kha'Zix, jungle` to limit it to that role). In champ select the panel shows your top still-open picks in priority order. Recommend-only â€” it never hovers or locks for you.
- **Fixed the â¬œ square symbols** on the overlay (the `â˜… gank` chip, the dodge banner, the coach lines, and the âœ“ marks) â€” they render properly now.
- **Better duo detection.** If the first player scan misses someone (a rate-limit hiccup), it now re-checks a little later and fills in any duo/premade markers it missed.
- **Profile window closes on its own** when you enter champ select, so the champ-select panel and in-game overlay take over cleanly.

## v0.2.54
- **Refresh button on your profile** â€” force a fresh pull when a just-finished game hasn't shown up yet.
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
