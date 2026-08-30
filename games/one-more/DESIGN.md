# ONE MORE — design notes

The rules this game is built on, and the reasoning behind the ones that cost
something to keep.

## 1. The product is the loop, not the content

Die → results → tap → playing. Nothing may sit in that path: no ad, no menu, no
loading, no transition longer than the 620 ms it takes for the death effect to
finish. The results screen is one tap tall and a tap *anywhere* restarts.

Every feature was asked one question: does this make the player want to go one
more time? Cosmetics passed. Chat, clans, currencies, crafting, real-time
multiplayer and a story campaign did not, and are not here.

## 2. The invariant

`g = G·(v/V)²`, so the horizontal span of a flip is constant at every speed.

This is the single load-bearing decision. It means:

- every authored pattern stays exactly as fair at 936 px/s as at 430 px/s;
- difficulty comes from shrinking reaction time, never from geometry that
  quietly stopped fitting;
- the fairness proof in `tools/validate.js` is valid for the whole game rather
  than for one speed.

**Nothing may break it.** That is why the mutation list has SURGE and DRAG (pure
speed changes, safe for free under the invariant) and does not have HEAVY or
FLOAT. A gravity multiplier changes the arc by `1/√mult` and would silently void
the proof for all 38 patterns — the game would start killing people in places it
had promised were fair. A mutation may change how fast the world moves, how much
of it you can see, or which way is up. It may never change the shape of the arc.
There is a unit test asserting no mutation carries a gravity term.

## 3. Difficult, and provably fair

Randomness picks *which* authored pattern comes next and how much room follows
it. It never invents geometry. That is the whole difference between hard and
unfair.

Each tier owes the player a slack budget, measured at top speed:

| tier | slack floor | reads as |
|---|---|---|
| 1 | 400 ms | a wide open door |
| 2 | 180 ms | rhythm |
| 3 | 100 ms | combination |
| 4 | 60 ms | precision |
| 5 | 40 ms | the part people post clips of |

Slack is the timing error the most forgiving line tolerates. It is measured
exactly where the solution space is small enough to scan outright (one- and
two-flip lines) and reported as a lower bound otherwise.

Two findings from building that tool that changed the game:

- **A full-height blinking laser is not a skill test.** The player cannot
  control when they arrive at it, so whether it is lit is luck. Lasers now cover
  half the tunnel: the decision is which side to be on, and the answer is
  visible a second in advance.
- **Needle gates are limited by width, not gap height.** The player crosses the
  middle of the tunnel at maximum vertical speed, so how *long* they must hold a
  narrow band costs far more slack than how tall the band is. Every gate got
  narrower and every gap got taller.

## 4. The character is the HUD

There is no health bar, no combo meter, no minimap. Feedback lives in the
Nanogon and its trail: the core brightens under threat, the shell trembles on a
near miss, the trail lengthens with speed and breaks up with corruption. The
only persistent number on screen is the timer, and the gap to your record under
it — because that gap is the entire psychological engine.

Six evolutions arrive with your level: CORE, PULSE, PHASE, VOID, GLITCH,
SINGULARITY. They are purely visual. Two players at level 3 and level 50 are
playing exactly the same game, and the garage says so.

## 5. Black and white, and nothing else

Background `#08090c`, geometry `#e8eaf0`, grey for anything that is not
gameplay. No accent colour anywhere. The constraint is what makes the game
readable at thumbnail size and instantly recognisable in a still frame, which
matters more for how it spreads than any amount of visual richness would.

The art-direction rule: if removing 30 % of an effect makes the frame read
better, it was decoration and not feedback. Applied literally — solid obstacle
masses were originally striped, which made them read as ladders you could climb;
they are now a white frame over a dimmed hatch, which reads as "solid, do not
touch" at a glance and stays quiet in the frame.

## 6. Arriving, not choosing

Worlds are not a menu. You reach ORIGIN, PULSE, VOID, COLLAPSE and NIGHTMARE by
surviving to 0, 48, 108, 168 and 240 seconds. Past ninety seconds a corruption
value ramps up and starts tearing at the backdrop, the character's shell and
eventually the interface itself — the timer jitters, a glyph swaps. Long runs
should feel like territory you are not supposed to be in.

## 7. Honest opponents

There is no server, so there is no global leaderboard — and the game does not
pretend otherwise. No fabricated rival names, no invented world records, no
"97 % of players died before you" computed from nothing. The records screen
states plainly that scores are stored on the device.

What it has instead is real: ghosts of your own record runs, recorded as
delta-encoded position samples and replayed at their true world position, so you
watch your past self pull ahead or fall behind. The Daily Challenge is seeded
from the UTC date, so it is genuinely the same layout for everyone, verifiable
without a server.

Both were built in the shape a backend would want. The ghost format is a few
bytes per frame; the daily seed is a pure function of the date.

## 8. Audio does the tension

The music is a step sequencer whose layers arrive with survival time: drone,
then kick, then hats, then a bass figure, then a detuned pad. When your personal
best comes within six seconds it strips to a bare heartbeat. Going quiet is the
loudest thing the soundtrack can do at that moment, and it costs nothing to
build.

## 9. What is deliberately missing

Real-time multiplayer, chat, clans, battle passes, multiple currencies,
inventories, crafting, pets, a story, and any monetisation that touches the
restart loop. Rewarded video after a death would earn money and destroy the
game.

The first milestone was never "ship every idea". It was: a player who dies at
forty seconds reaches for the screen before they have decided to.
