# ONE MORE

One input. Tap to flip gravity. Survive one more time.

A complete, playable one-tap survival game — the character, the world, every
effect and the entire soundtrack are generated at runtime, so the whole thing is
a single 152 KB HTML file with no dependencies, no assets and no build step
required to play it.

```
open dist/one-more.html          # that's it — desktop or phone
```

## Play

| Input | Action |
|---|---|
| tap / click / `space` | flip gravity |
| `Esc` / `P` | pause |
| tap anywhere on the results screen | go again |

You move forward automatically. The only thing you control is which way is down.

## What is in it

**Core** — gravity-flip survival, 60 hand-authored obstacle patterns across five
difficulty tiers built from eight obstacle types, plus 41 proven compositions
of them, a procedural generator, a difficulty director, five worlds you arrive
at by surviving rather than by choosing, nine mutations that rewrite one rule at
a time, near-miss and perfect-switch detection, instant restart.

**The read** — the game watches how you die and tells you. Not with a fabricated
percentile: with your own numbers, held against your own baseline, and only once
there are enough of them to mean anything. When one kind of death dominates it
names it, explains the fix, and offers a **Trial** — a run weighted towards the
patterns you actually fail. Then it comes back and tells you whether the
drilling worked: *since your first TIMING trial, deaths to static geometry have
fallen from 60% to 20% (12 of 20 → 4 of 20)*. The records screen shows the same
history as a shape, so "you used to die to static geometry; now it is moving
geometry" is a thing the game can say. When your deaths are evenly spread it
says so instead of inventing a weakness.

Under twelve runs the statistics say nothing at all — but the panel is not an
empty countdown either. It describes the death that just happened against the
one constant the physics guarantees: *a mover caught you crossing to the floor.
That flip was 0.23s old. A crossing takes 0.57s at this speed — it had not
finished.* No generalisation, no invented percentile, and it works on death
one.

**Death replay** — every death captures the last two seconds and replays them on
the results screen in slow motion, framed on the geometry that killed you. It is
the honest answer to "what just happened", and it is the clip people post.

**Modes** — Endless, a Daily Challenge seeded from the UTC date so every player
in the world runs the identical layout, Trials aimed at your weakness, Practice
at a fixed 335 px/s with its own record and no XP, and Nightmare, which unlocks
at two minutes and starts where the endless run ends: top speed, last world, no
warm-up.

**Retention** — ghost replays of your own record runs that occupy real positions
in the world so you can watch your past self pull ahead, XP and levels, six
Nanogon evolutions, five trails, six death effects, twenty achievements, a daily
streak, a run-history sparkline, and per-device records including exactly what
kills you. Any run can be replayed exactly — the world is a pure function of one
32-bit seed — and that seed rides in a URL hash, so a link is a world: **retry
this exact run**, or hand it to somebody else.

**Feel** — fixed-timestep physics, landing impacts that scale with drop height
(compression, dust, a scar on the floor, a matched thump), squash and stretch,
flip bursts, hit-stop, slow-motion on near misses, near-miss highlighting on the
obstacle you grazed, speed streaks that re-seed their height every pass, screen
shake, procedural WebAudio with a music bed that layers up as you survive and
strips back to a heartbeat when your record is within reach, haptics, and a UI
that starts corrupting itself past ninety seconds.

## The one invariant everything rests on

Gravity is derived from speed as `g = G·(v/V)²`. The consequence is that the
horizontal distance covered by a full surface-to-surface flip is **identical at
every speed** — 247 px at 430 px/s and 247 px at 936 px/s.

```
t=0s    speed=430   flip=0.574s   span=246.9px
t=60s   speed=711   flip=0.347s   span=246.9px
t=300s  speed=936   flip=0.264s   span=246.9px
```

Every authored pattern is designed against that one arc, so a pattern that is
fair in the first ten seconds is still geometrically fair five minutes later.
The game gets harder because your reaction time has to shrink, never because the
geometry quietly stopped fitting. This is also why no mutation is allowed to
scale gravity — see `DESIGN.md`.

## Tooling

The interesting part of this project is that "difficult but fair" is checked
rather than asserted.

```bash
npm run validate    # prove every pattern is survivable and fair
npm test            # 130 unit tests over the pure logic
npm run e2e         # 94 end-to-end checks driven by real taps
npm run playtest    # play the real game in a real browser with a bot
npm run build       # bundle to dist/
```

### `tools/validate.js` — the fairness proof

For every pattern, a beam search over the *shipping* physics explores the whole
space of flip timings — from both entry surfaces, at every speed the pattern can
spawn at, across six phase offsets for anything that moves. A pattern passes
only if a surviving line exists in every combination.

**Every speed** means the whole envelope, which is wider than the speed curve.
Practice pins 335 px/s; the curve runs 430 → 998; DRAG multiplies by 0.84 and
SURGE by 1.22, so the game actually runs anywhere from 361 to 1218 px/s. Those
multipliers are read off the shipping mutation table rather than copied here, so
a new pace mutation widens the proof automatically.

Static patterns need one survivability check, at the top of that range: their
geometry is fixed in space and so is the flip arc, so the only thing speed
changes is the flip cooldown — a fixed number of *seconds*, so it covers more
pixels the faster you go. A line executable at 1218 has every flip far enough
apart to be executable at any slower speed, threading identical geometry. Moving
patterns get no such implication in either direction and are sampled across the
envelope.

Slack budgets are held against the base curve, where a player lives. SURGE and
DRAG are announced, temporary and deliberate — a burst 22 % tighter is the point
of a burst — so anything that drops under its floor only inside a mutation is
printed as an advisory rather than failed, because "legitimately tighter" and
"accidentally brutal" look identical from inside the code.

It then measures the number that actually matters: take the most forgiving line
and slide each flip until the run dies. That is how much timing error the
pattern allows a human. Each tier has a slack budget it must meet.

```
PATTERN               TIER  FLIPS  SLACK     RESULT
t1_floor              1     0      1081ms    pass
t2_pinch              2     1      228ms     pass
t3_gate *             3     1      105ms     pass
t4_needle_tight       4     2      62ms      pass
t5_gate_pair *        5     2      53ms      pass

101 patterns / 101 survivable at every speed, entry side and phase
All patterns fair, every tier within its slack budget.
```

`--only t3_gate,t5_gate_pair` validates a subset at full rigour, so tuning one
pattern costs thirty seconds instead of six minutes.

The search is constrained to lines a person could physically execute — no flips
closer together than 100 ms. Without that constraint it "solves" patterns with
80 ms double-taps and every honest pattern looks like a coin flip.

This tool keeps earning its keep. Three findings that changed the game:

- **A full-height blinking laser is not a skill test at all**, because the
  player cannot control when they arrive at it. Lasers were redesigned to cover
  half the tunnel, which turns them into a decision — "the bottom is lit, be on
  top" — instead of a dice roll.
- **Needle gates are limited by their width, not their gap height.** The player
  crosses the middle of the tunnel at maximum vertical speed, so how long they
  must hold a narrow band costs far more slack than how tall the band is. Every
  gate got narrower and every gap got taller.
- **Sliding gates inherit the same problem, twice over.** Four of them shipped
  their first draft at 9–35 ms of slack. They are now narrow, with slow-moving
  openings and approach rails drawn back from each jaw so a thin obstacle still
  telegraphs from a distance.
- **The validator was proving the wrong top speed.** It sampled up to
  `speedAt(260)` = 910 px/s while the curve reaches 998 and SURGE reaches 1218,
  so three of the speeds the game actually runs at had never been checked.
  Widening the envelope put four patterns under their tier floor at a speed
  players reach: `t3_gate` 96 ms, `t4_gate_fast` 56 ms, `t4_bar_needle` 48 ms,
  `t5_full_house` 32 ms. And the fix was not the obvious one — narrowing those
  gates moved their slack by exactly 0 ms. Once a gate is narrow enough, the
  binding constraint is the *height* of the opening, because the slow ends of
  the flip arc are what land in the jaws. Opening each of them by 6–16 px put
  all four back in budget.

### `tools/compose.js` — more world, without more hand-authoring

Sixty authored patterns is a lot of hand work and not a lot of world. The cheap
way to more is to author another hundred; the honest way is to join the ones
that exist and prove every join.

`node tools/validate.js --compose` runs each candidate join through the same
proof the authored library goes through, and writes the survivors to
`src/22-compositions.js` — the only way a composition can ship.

```
342 candidate joins at 90px, from 19 static fragments
342 attempted · 342 fair · 164 PROVEN-DISTINCT COMBINATIONS
real joins by tier: {"2":34,"3":78,"4":52}
rejected as unfair: 0 · rejected as no harder than one half: 178
  no join  t1_bar_high+t1_block 0 flips vs 0, 633ms vs 1072ms
shipping 41 of them: {"2":13,"3":14,"4":14}
```

Two fragments joined at 90 px are one problem, not two: that is the tight end of
what the generator already puts between patterns once the late-game spacing and
RUSH are both applied, and it is the one case sixty individually-proven patterns
never said anything about. A line that clears A and a line that clears B say
nothing about whether a line clears both.

**Fairness turned out not to be the binding constraint.** All 342 joins passed
the fairness proof, and the first version of this shipped 41 of them — of which
seventeen could be survived without touching the screen. A bar high up joined to
a block on the floor is perfectly fair and is also two things you could have
ignored separately.

So a join clears a second gate: it must need at least one flip, and it must be
strictly harder than *either* half by one of the two measures there are — more
flips than either half needs, or less slack than either half leaves. That gate
rejects 178 of 342. It is the one that does the work.

What limits growth after that is variety, not fairness: compositions never
outnumber the hand-authored patterns at their tier, because past that the world
stops being the thing sixty patterns were authored to be and becomes a shuffle
of two of them. 164 are provably real joins; 41 ship.

### `tools/playtest.js` — the difficulty curve, measured

Loads the built game in Chromium and plays it with a bot that looks ahead
through the live obstacle list. Give the bot a reaction delay and it stops being
a solver and starts standing in for a person.

```
PROFILE   REACTION   RUNS  MEDIAN    BEST      WORLD REACHED
PERFECT   0ms        11    03:01.83  04:49.79  COLLAPSE
GOOD      110ms      11    01:14.13  02:29.84  PULSE
HUMAN     190ms      11    00:42.57  00:52.56  ORIGIN
SLOPPY    300ms      11    00:18.35  00:24.80  ORIGIN
```

Eleven runs a profile, not five. A PERFECT run lasts minutes and its length has
a long tail, so five samples put its median anywhere: three consecutive runs of
an unchanged build gave 4:04, 1:10 and 2:53, and the middle one reported that a
slower reaction survived longer. That was the sample size talking, not the game
— but a curve that says something different every time you measure it is not a
measurement, so the default went up.

A competent human lands around a minute — long enough to feel like progress,
short enough that restarting costs nothing. Sharpening your reaction from 190 ms
to 110 ms lengthens the run substantially, and perfect play tops out near five
minutes, so there is a real mastery ceiling to chase.

### `tools/e2e.js` — the buttons, not just the game

Ninety-four checks driven by real taps on a touch viewport: menu to play, pause
without losing the run, death to results to one-more, the daily seed's
stability, cosmetic locks, persistence across a reload, and every new system —
that the replay captures the geometry which killed you, that the read stays
silent without evidence and refuses to invent a weakness from an even spread,
that a Trial only ever draws from proven patterns, that Nightmare is locked
until you have earned it. Plus a draw-call cost guard, which is where an
accidental O(n²) over the obstacle list would surface.

It has already caught a shipped-quality bug: a player who died to exactly one
kind of obstacle was told they had *no* single weakness, because the diagnosis
compared against an even split of the families that had *occurred* rather than
of the families that *could*. One-of-one scored as perfectly even.

## Layout

```
src/00-core.js        RNG, storage, formatting, event bus
src/10-physics.js     constants, integration, difficulty director   [pure]
src/20-patterns.js    60 authored patterns + collision geometry     [pure]
src/22-compositions.js 41 proven joins of them (generated)          [pure]
src/25-generator.js   seeded procedural composition                 [pure]
src/30-mutations.js   the nine rule changes                         [pure]
src/32-analysis.js    the read: death history, diagnosis, trials    [pure]
src/35-progress.js    save data, XP, unlocks, records
src/40-ghost.js       delta-encoded ghost record and replay
src/45-audio.js       procedural WebAudio, adaptive music bed
src/50-nanogon.js     the character: nine sides, six evolutions
src/55-fx.js          trails, particles, death effects, screen response
src/60-render.js      world, surfaces, obstacles, speed streaks
src/70-game.js        loop, collision, run lifecycle, HUD
src/72-replay.js      death capture and slow-motion playback
src/80-ui.js          screens
src/99-boot.js        canvas, input, frame loop
```

The `[pure]` modules touch no DOM, which is what lets the validator and the test
suite run the real game logic under node.

## Not built yet

Deliberately. There is no server, so **there is no global leaderboard**, and the
UI says so rather than inventing one — the profile screen is explicit that
everything is measured from your own runs and compared to nobody. There are no
fabricated rival names, no invented world records and no "97 % of players died
before you" computed from nothing. The only opponent is your own past run, and
the read only speaks when your own history supports it.

The next real milestone is a backend: accounts, server-validated scores, shared
ghosts, the rival system and daily leaderboards. The ghost format is already
delta-encoded and cheap to ship over a wire, and the daily seed is already
derived from the UTC date, so both were designed for that day.
