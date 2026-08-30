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
difficulty tiers built from eight obstacle types, a procedural generator that
composes them, a difficulty director, five worlds you arrive at by surviving
rather than by choosing, nine mutations that rewrite one rule at a time,
near-miss and perfect-switch detection, instant restart.

**The read** — the game watches how you die and tells you. Not with a fabricated
percentile: with your own numbers, held against your own baseline, and only once
there are enough of them to mean anything. When one kind of death dominates it
names it, explains the fix, and offers a **Trial** — a run built mostly from the
patterns you actually fail. When your deaths are evenly spread it says so
instead of inventing a weakness. Under twelve runs it says nothing at all.

**Death replay** — every death captures the last two seconds and replays them on
the results screen in slow motion, framed on the geometry that killed you. It is
the honest answer to "what just happened", and it is the clip people post.

**Modes** — Endless, a Daily Challenge seeded from the UTC date so every player
in the world runs the identical layout, Trials aimed at your weakness, and
Nightmare, which unlocks at two minutes and starts where the endless run ends:
top speed, last world, no warm-up.

**Retention** — ghost replays of your own record runs that occupy real positions
in the world so you can watch your past self pull ahead, XP and levels, six
Nanogon evolutions, five trails, six death effects, twenty achievements, a daily
streak, a run-history sparkline, and per-device records including exactly what
kills you.

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
npm test            # 61 unit tests over the pure logic
npm run e2e         # 53 end-to-end checks driven by real taps
npm run playtest    # play the real game in a real browser with a bot
npm run build       # bundle to dist/
```

### `tools/validate.js` — the fairness proof

For every pattern, a beam search over the *shipping* physics explores the whole
space of flip timings — from both entry surfaces, at three speeds, across six
phase offsets for anything that moves. A pattern passes only if a surviving line
exists in every combination.

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

60 patterns / 60 survivable at every speed, entry side and phase
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

### `tools/playtest.js` — the difficulty curve, measured

Loads the built game in Chromium and plays it with a bot that looks ahead
through the live obstacle list. Give the bot a reaction delay and it stops being
a solver and starts standing in for a person.

```
PROFILE   REACTION   RUNS  MEDIAN    BEST      WORLD REACHED
PERFECT   0ms        5     02:54.63  05:31.17  COLLAPSE
GOOD      110ms      5     01:10.13  02:09.28  PULSE
HUMAN     190ms      5     00:54.19  01:26.44  PULSE
SLOPPY    300ms      5     00:23.11  00:43.47  ORIGIN
```

A competent human lands around a minute — long enough to feel like progress,
short enough that restarting costs nothing. Sharpening your reaction from 190 ms
to 110 ms lengthens the run substantially, and perfect play tops out near five
minutes, so there is a real mastery ceiling to chase.

### `tools/e2e.js` — the buttons, not just the game

Fifty-three checks driven by real taps on a touch viewport: menu to play, pause
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
