# ONE MORE

One input. Tap to flip gravity. Survive one more time.

A complete, playable one-tap survival game — the character, the world, every
effect and the entire soundtrack are generated at runtime, so the whole thing is
a single 112 KB HTML file with no dependencies, no assets and no build step
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

**Core** — gravity-flip survival, 38 hand-authored obstacle patterns across five
difficulty tiers, a procedural generator that composes them, a difficulty
director, five worlds you arrive at by surviving rather than by choosing, nine
mutations that rewrite one rule at a time, near-miss and perfect-switch
detection, instant restart.

**Retention** — a Daily Challenge seeded from the UTC date so every player in
the world runs the identical layout, ghost replays of your own record runs that
occupy real positions in the world so you can watch your past self pull ahead,
XP and levels, six Nanogon evolutions, five trails, six death effects, sixteen
achievements, a daily streak, per-device records and statistics including what
actually kills you.

**Feel** — fixed-timestep physics, hit-stop, slow-motion on near misses, screen
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
npm run validate    # prove every pattern is survivable
npm test            # 47 unit tests over the pure logic
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
t3_gauntlet           3     3      >=272ms   pass
t4_needle_tight       4     2      62ms      pass
t5_needle_pair        5     2      53ms      pass

38 patterns / 38 survivable at every speed, entry side and phase
All patterns fair, every tier within its slack budget.
```

The search is constrained to lines a person could physically execute — no flips
closer together than 100 ms. Without that constraint it "solves" patterns with
80 ms double-taps and every honest pattern looks like a coin flip.

This tool earned its keep immediately: it proved that a full-height blinking
laser is **not a skill test at all**, because the player cannot control when they
arrive at it. Lasers were redesigned to cover half the tunnel, which turns them
into a decision — "the bottom is lit, be on top" — instead of a dice roll.

### `tools/playtest.js` — the difficulty curve, measured

Loads the built game in Chromium and plays it with a bot that looks ahead
through the live obstacle list. Give the bot a reaction delay and it stops being
a solver and starts standing in for a person.

```
PROFILE   REACTION   RUNS  MEDIAN    BEST      WORLD REACHED
PERFECT   0ms        4     02:55.83  04:06.47  COLLAPSE
GOOD      110ms      4     01:26.28  01:34.23  PULSE
HUMAN     190ms      4     00:40.47  00:48.39  ORIGIN
SLOPPY    300ms      4     00:10.34  00:20.86  ORIGIN
```

A competent human lands around forty seconds — long enough to feel like
progress, short enough that restarting costs nothing. Sharpening your reaction
from 190 ms to 110 ms doubles your run, and perfect play tops out near four
minutes, so there is a real mastery ceiling to chase.

## Layout

```
src/00-core.js        RNG, storage, formatting, event bus
src/10-physics.js     constants, integration, difficulty director   [pure]
src/20-patterns.js    38 authored patterns + collision geometry     [pure]
src/25-generator.js   seeded procedural composition                 [pure]
src/30-mutations.js   the nine rule changes                         [pure]
src/35-progress.js    save data, XP, unlocks, records
src/40-ghost.js       delta-encoded ghost record and replay
src/45-audio.js       procedural WebAudio, adaptive music bed
src/50-nanogon.js     the character: nine sides, six evolutions
src/55-fx.js          trails, particles, death effects, screen response
src/60-render.js      world, surfaces, obstacles
src/70-game.js        loop, collision, run lifecycle, HUD
src/80-ui.js          screens
src/99-boot.js        canvas, input, frame loop
```

The `[pure]` modules touch no DOM, which is what lets the validator and the test
suite run the real game logic under node.

## Not built yet

Deliberately. There is no server, so **there is no global leaderboard**, and the
UI says so rather than inventing one — the records screen is explicit that
scores live on your device. There are no fabricated rival names or fake global
bests anywhere in the game; the only opponent is your own past run.

The next real milestone is a backend: accounts, server-validated scores, shared
ghosts, the rival system and daily leaderboards. The ghost format is already
delta-encoded and cheap to ship over a wire, and the daily seed is already
derived from the UTC date, so both were designed for that day.
