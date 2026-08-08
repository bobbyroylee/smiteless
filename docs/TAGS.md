# Player-tag specification

## Display language

English source strings remain the implementation keys. In this Brazilian fork, tags display
in PT-BR (for example, `fora do campeão`, `primeira vez com {champ}?`, `sequência de 9V`);
champion names, stable game abbreviations, and all numeric evidence are kept unchanged. The
evidence rules below apply in either UI language.

The tag system is the credibility core of the scout. Every tag is a **claim** backed by
**named evidence** that meets a **numeric threshold** — if the evidence isn't there, the tag
doesn't render. The tag text itself always cites its evidence (`smurf? · lvl 44 · 8-2`),
so a tag can never assert more than its data supports.

Two kinds of claims, never conflated:

- **THIS-GAME reads** — what to expect from this player *on the champ they locked today*.
  These render first: they're the actionable intel.
- **ACCOUNT reads** — who this account is (streaks, account age, season shape). Context,
  rendered after.

The canonical failure this spec exists to prevent: a Morgana one-trick on a 9-win Morgana
streak queues up on **Brand** and goes 1/8. Account-wide evidence (win streak, few season
games) must never render as a this-game judgment ("SMURF"). In PT-BR, the correct output is
`fora do campeão · 9 das últimas 10 com Morgana` + `9V em sequência · com Morgana` — true,
and it tells you the 1/8 is coming.

Data inputs (all from the player's real match history / Riot API, never rank-peeking or
W/L moralizing — player *quality* judgments only ever come from the perf grade
(`lolprofile._grade_game` lineage)):

| field    | source                                     | meaning                          |
|----------|--------------------------------------------|----------------------------------|
| `n, w`   | match-v5, last ≤10 ranked                  | recent games / wins              |
| `form`   | match-v5                                   | recent W/L bools, newest first   |
| `recent` | match-v5 (same fetches)                    | (champ, win, pos) newest first   |
| `cg, cw` | match-v5                                   | games/wins on TODAY's champ      |
| `pts`    | champion-mastery-v4 on today's champ       | mastery points                   |
| `level`  | LCU summoner (loading) / summoner-v4 (live)| account level                    |
| `perf`   | `_grade_game` avg over recents             | how they actually play, 0–100    |
| `sg,swr` | league-v4 season W+L                       | season volume / winrate          |
| `dpg`    | match-v5 pooled KDA                        | deaths per game                  |

## THIS-GAME tags (first)

| tag | claim | evidence required | notes |
|-----|-------|-------------------|-------|
| `first {champ}? · Xk pts, 0 of last N` | has effectively never played today's champ | scouted AND `pts < 6000` AND `cg == 0` | unchanged from v0.9.x, now cites pts |
| `off-champ · X of last N on {main}` | their recent form was earned on a different champ | `n ≥ 8` AND `cg ≤ 1` AND one champ ≥ 50% of `recent` AND that champ ≠ today's | THE Morgana/Brand fix. Tone: bad-for-them |
| `cold on {champ} · W-L recent` | plays this champ and loses on it | `cg ≥ 4` AND `cw/cg ≤ 0.35` | |
| `comfort · W-L on {champ}` | recent, real reps on today's champ | `cg ≥ 5` | tone by `cw*2 ≥ cg` |
| `{champ} OTP · Xk pts` / `{champ} main · Xk pts` | mastery-proven one-trick / main **on today's champ** | `pts ≥ 250k` / `pts ≥ 100k` | pts is champ-specific so this is a this-game read |

## ACCOUNT tags (after)

| tag | claim | evidence required | notes |
|-----|-------|-------------------|-------|
| `smurf? · lvl L · W-N · P perf` | experienced player, new account | ALL of: `level ≤ 60` AND `n ≥ 8` AND `w/n ≥ 0.70` AND (`perf ≥ 75` OR (`cg ≥ 3` AND `cw/cg ≥ 0.7`)) | Level is the load-bearing evidence (ranked unlocks at 30; a real smurf account is fresh). **No level data → tag cannot fire.** Always rendered with `?` — it is an inference |
| `new account · lvl L` | the account itself is new | `level ≤ 60` (and smurf? didn't fire — smurf implies new) | hard evidence only |
| `fresh ranked · X games` | new to ranked *this season* (account may be old) | `0 < sg ≤ 25`, level unknown or > 60 | weaker claim than new-account, so distinct wording |
| `XW heater · on {champ}` / `XW heater` | live win streak (+ whose champ earned it) | streak ≥ 3 from `form` | if ≥ 70% of streak games on one champ ≠ today's → append `· on {champ}` and tone drops to neutral (their heat isn't on today's pick) |
| `XL skid · tilt risk` | live loss streak | streak ≥ 3 | tilt transfers across champs, no attribution needed |
| `off-role · {POS} main` | not on their normal position | `main_pos` (≥ max(3, half of recents)) ≠ today's role | |
| `bleeds · X deaths/game` / `hard to kill` | death pattern | `n ≥ 5`, dpg ≥ 6.5 / ≤ 2.6 | |
| `carries · P avg perf` / `passenger · P perf` | play quality independent of W/L | `perf ≥ 85` / `≤ 45` | grade lineage — the only sanctioned quality read |
| `grinder · X ranked this season` | volume | `sg ≥ 400` | neutral |
| `climbing · X% season` / `hardstuck · X%` | season trajectory | `sg ≥ 100`, swr ≥ 55 / ≤ 45 | |
| `duo · NAME` | queued together | ≥ 3 shared recent same-team ranked games (`lolload._duo_pass`) | prepended by the duo pass |

## Rules

1. **No evidence, no tag.** A tag whose evidence fields are missing (e.g. no level data)
   is skipped, never guessed.
2. **Every tag cites its numbers inline.** The pill text is the justification.
3. **Inferences carry `?`.** `smurf?` is a hypothesis; `new account · lvl 34` is a fact.
4. **Order = actionability.** duo → this-game → account. The renderers draw first-fit.
5. **Tone is relative to YOU** (enemy on a skid = good for you), except neutral facts.

## Regression fixture

`tools/tagcheck.py` re-runs the classifier over the real cached Morgana/Brand game
(NA1_5604429522: Brand support, 1/8/2, on an account whose other 10 recents are 8W-1L
Morgana) plus synthetic edge rows. It fails if the off-role feeder ever reads as `smurf`
again, and prints the rendered tag set for eyeball checks. Run via
`python tools/tagcheck.py` (also wired into selftest).
