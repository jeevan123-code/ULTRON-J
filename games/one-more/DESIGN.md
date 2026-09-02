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
the proof for every pattern at once — the game would start killing people where it
had promised were fair. A mutation may change how fast the world moves, how much
of it you can see, or which way is up. It may never change the shape of the arc.
There is a unit test asserting no mutation carries a gravity term.

## 3. Difficult, and provably fair

Randomness picks *which* proven pattern comes next and how much room follows
it. It never invents geometry. That is the whole difference between hard and
unfair.

Patterns come from two places and neither of them is chance. Sixty are authored
by hand. Forty-one are joins of two authored fragments at 90 px — one problem
rather than two, since that gap is the tight end of what the generator already
leaves between patterns — and each of those joins goes through the identical
proof before it can spawn. A line that clears A and a line that clears B say
nothing about whether a line clears both, so the join is a new pattern and is
treated as one.

Fairness is not what limits that. All 342 candidate joins passed the fairness
proof; 178 of them were thrown out anyway, for not being joins. A bar high up
followed by a block on the floor is perfectly survivable and needs no input at
all — two things you could have ignored separately. So a join also has to be
strictly harder than either half, in flips or in slack, and to need at least one
flip. The proof says a pattern is fair. It cannot say a pattern is worth
spawning, and pretending otherwise is how a library gets bigger without the game
getting better.

Each tier owes the player a slack budget, measured at the top of the speed
curve — 998 px/s, not the 910 the validator used to stop at. The gap between
those two numbers hid four patterns that were out of budget at a speed players
reach. Under SURGE the game runs tighter still; that is reported but not
enforced, because an announced, temporary burst is allowed to be harder than the
budget the base curve owes you. It is not allowed to be impossible, which is why
survivability is proven across the whole 361–1218 px/s envelope.

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

Three findings from building that tool that changed the game:

- **A full-height blinking laser is not a skill test.** The player cannot
  control when they arrive at it, so whether it is lit is luck. Lasers now cover
  half the tunnel: the decision is which side to be on, and the answer is
  visible a second in advance.
- **Needle gates are limited by width, not gap height.** The player crosses the
  middle of the tunnel at maximum vertical speed, so how *long* they must hold a
  narrow band costs far more slack than how tall the band is. Every gate got
  narrower and every gap got taller.
- **Sliding gates compound both problems.** All four shipped their first draft
  between 9 and 35 ms. Fair versions are narrow with slowly-moving openings —
  which made them hard to *see*, so they gained approach rails: faint lines
  running back from each jaw that show where the opening is and which way it is
  travelling, long before you reach it. Fairness and legibility are the same
  problem viewed from two ends.

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
better, it was decoration and not feedback. Applied literally, twice:

- Solid obstacle masses were originally striped, which made them read as ladders
  you could climb. They are now a white frame over a dimmed hatch, which reads
  as "solid, do not touch" at a glance and stays quiet in the frame.
- Speed streaks were first scattered across the whole tunnel at fixed heights,
  which the eye read as scratches on the screen rather than as motion — a static
  y reads as dirt. They now re-seed their height on every wrap, cluster near the
  player's altitude, and only appear once the world is genuinely moving.

The same rule cuts the other way for landing. A flip that ended in a soundless,
motionless stop read as the character being *teleported* onto the surface. The
compression, the dust, the brief scar on the floor and a thump pitched to the
impact speed are not decoration: they are what gives the character mass.

## 6. Arriving, not choosing

Worlds are not a menu. You reach ORIGIN, PULSE, VOID, COLLAPSE and NIGHTMARE by
surviving to 0, 48, 108, 168 and 240 seconds. Past ninety seconds a corruption
value ramps up and starts tearing at the backdrop, the character's shell and
eventually the interface itself — the timer jitters, a glyph swaps. Long runs
should feel like territory you are not supposed to be in.

## 7. The read

The differentiator is not that the game is hard. It is that it pays attention.

Every death records what killed you and what you were doing when it did: which
authored pattern you were inside, whether you were airborne, how long since your
last flip, which mutations were running. Deaths are then grouped into four
families a person can actually practise — timing, prediction, commitment, nerve
— because "you die on moving geometry" is actionable and "you die on
t4_mover_gate" is trivia.

The discipline is in what it refuses to say:

- Under twelve deaths it says nothing, and tells you how many runs are left
  before it will.
- If your deaths are evenly spread it says so. It does not manufacture a
  weakness to have something to report.
- Every claim carries its own evidence: "100 % of your last 21 deaths", not
  "you seem to struggle with".
- The trend line is your own median, first fifteen runs against last fifteen. It
  can and does tell you that you are getting worse.

When there is a diagnosis, there is a **Trial**: a run weighted towards the
patterns you actually fail — the family chooses which proven patterns may
appear, and your own record chooses how often each one comes up. It starts past
the tutorial band. It never changes the rules, the physics or the geometry —
because those are the things the fairness proof covers, and a mode that quietly
escaped that proof would be the least fair part of the game.

And then it closes the loop. Taking the moment of your first Trial in a family
and comparing that family's share of your normal deaths before it against after
gives the game a way to say whether its own advice worked — with Trial deaths
excluded from both sides, since a Trial is one family by construction, and with
a rise reported exactly as readily as a fall.

Before there are twelve deaths there is nothing statistical to say, but there is
still something true: what hit you, which surface you were on, how old your last
flip was, and what a crossing costs at that speed. One death cannot show whether
the gap you needed was even there, so it stops there.

**Practice** is the one mode that runs at a different speed, and it draws only
from the 41 static patterns. That is not caution, it is the same invariant: a
pattern fixed in space, crossed by an arc fixed in space, poses the identical
problem at any speed — and the flip cooldown, being a fixed number of seconds,
covers fewer pixels the slower you go, so the line only gets easier to execute.
Time-driven patterns have no such guarantee: their phase advances further over
the same stretch of tunnel, so they are a different problem and they stay out.
Practice keeps its own record, pays no XP, and its deaths never enter the read —
otherwise every number the game quotes you would carry a hidden asterisk.

## 8. The last two seconds

Every death captures the player's path and a copy of the geometry around them,
and replays it in slow motion on the results screen with the tunnel framed in
full. Not framed tight on the character, which looks dramatic and answers
nothing — you need to see the surface you failed to reach.

It does two jobs at once: it is the honest answer to "what just happened", and
it is the thing worth posting. A game that generates its own clips does not need
a marketing budget as badly as one that does not.

## 9. Honest opponents

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

## 10. Audio does the tension

The music is a step sequencer whose layers arrive with survival time: drone,
then kick, then hats, then a bass figure, then a detuned pad. When your personal
best comes within six seconds it strips to a bare heartbeat. Going quiet is the
loudest thing the soundtrack can do at that moment, and it costs nothing to
build.

## 11. What is deliberately missing

Real-time multiplayer, chat, clans, battle passes, multiple currencies,
inventories, crafting, pets, a story, and any monetisation that touches the
restart loop. Rewarded video after a death would earn money and destroy the
game.

The first milestone was never "ship every idea". It was: a player who dies at
forty seconds reaches for the screen before they have decided to.
