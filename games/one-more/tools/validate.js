#!/usr/bin/env node
/* ONE MORE — pattern fairness validator.
 *
 * "Difficult but fair" is a claim, not a feeling. This proves it.
 *
 * For every authored pattern, a beam search over the SHIPPING physics
 * (src/10-physics.js, not a re-implementation) explores the whole space of flip
 * timings — entering from both floor and ceiling, at three speeds, and across a
 * sweep of phase offsets for anything that moves. A pattern passes only if a
 * surviving line exists in EVERY combination.
 *
 * It then measures the human number: take the most forgiving surviving line and
 * slide each individual flip earlier and later until the run dies. The smallest
 * of those slacks is how much timing error the pattern actually allows. Under
 * ~60ms it stops being a skill test and becomes a coin flip.
 *
 *   node tools/validate.js [--verbose]
 */
'use strict';
var path = require('path');
var SRC = path.join(__dirname, '..', 'src');
require(path.join(SRC, '00-core.js'));
require(path.join(SRC, '10-physics.js'));
require(path.join(SRC, '20-patterns.js'));

var P = OM.phys, PAT = OM.patterns;
var VERBOSE = process.argv.indexOf('--verbose') >= 0;

var DX = 8;              // spatial resolution of the search
var BEAM = 1400;         // states kept per column
/* State-merging granularity. This MUST be finer than what one column of motion
   changes, or the search silently merges a state that has been falling for ten
   columns into one that just started, and never explores the trajectory at all. */
var QY = 3, QV = 25;
/* How much timing slack each tier must leave the player, measured at top speed.
   These are the design contract: tier 1 is a wide open door, tier 5 is meant to
   hurt, and nothing anywhere is a coin flip. */
var TIER_FLOOR = { 1: 400, 2: 180, 3: 100, 4: 60, 5: 40 };
/* Lines needing three or more flips can only be lower-bounded, so they are held
   to a weaker floor and flagged for hands-on playtest rather than trusted. */
var LB_FLOOR   = { 1: 200, 2: 100, 3: 50, 4: 30, 5: 20 };
var SLACK_CAP = 700;   // px of shift explored per flip; beyond this the flip is simply free
var COOLDOWN_S = 0.10; // a person cannot reliably tap twice inside 100ms
var MAX_FLIPS = 12;    // and will not execute a twelve-input line under pressure
var R2 = P.R * P.R;

function isDynamic(p) {
  for (var i = 0; i < p.items.length; i++) if (p.items[i].t === 'mover' || p.items[i].t === 'laser') return true;
  return false;
}

function materialize(p, x0) {
  var obs = [], holes = [];
  for (var i = 0; i < p.items.length; i++) {
    var it = p.items[i], o = {};
    for (var k in it) if (Object.prototype.hasOwnProperty.call(it, k)) o[k] = it[k];
    o.x = x0 + it.dx;
    if (o.t === 'hole') holes.push(o); else obs.push(o);
  }
  return { obs: obs, holes: holes };
}

/* Collision goes through the SHIPPING geometry (PAT.rectsOf) so the proof is
   about the code that actually runs. A scratch array keeps it allocation-free
   in the inner loop, which the beam search hits millions of times.
   An earlier version of this file reimplemented the rects for speed and drifted
   out of sync with the game the moment lasers changed shape — never again. */
var SCRATCH = [];
function hits(world, x, y, t) {
  var obs = world.obs;
  for (var i = 0; i < obs.length; i++) {
    var o = obs[i];
    if (o.x > x + P.R || o.x + o.w < x - P.R) continue;
    SCRATCH.length = 0;
    var rects = PAT.rectsOf(o, t, SCRATCH);
    for (var j = 0; j < rects.length; j++) {
      var q = rects[j];
      if (P.circleRectDist2(x, y, P.R, q.x, q.y, q.w, q.h) <= R2) return true;
    }
  }
  return false;
}

function bounds(p) {
  var x0 = 400;
  return { x0: x0, start: x0 - 240, end: x0 + p.len + 120 };
}

/* Beam search. Returns surviving lines (flip x-positions) or null. */
function solve(p, speed, t0, grav) {
  var b = bounds(p), world = materialize(p, b.x0);
  var g = P.gravityFor(speed, 1), dt = DX / speed;
  var cool = COOLDOWN_S * speed;
  var beam = [{ y: grav > 0 ? P.FLOOR - P.R : P.CEIL + P.R, vy: 0, grav: grav, grounded: true, path: [], lf: -1e9 }];

  for (var x = b.start; x < b.end; x += DX) {
    var t = t0 + (x - b.start) / speed;
    var next = [], seen = Object.create(null);
    for (var i = 0; i < beam.length; i++) {
      var s = beam[i];
      /* The search is only allowed to play lines a person could physically
         execute. Without this it "solves" patterns with 80px-apart double taps
         and every honest pattern looks impossibly tight. */
      var canFlip = (x - s.lf >= cool) && s.path.length < MAX_FLIPS;
      for (var f = 0; f < (canFlip ? 2 : 1); f++) {
        var n = { y: s.y, vy: s.vy, grav: f ? -s.grav : s.grav, grounded: f ? false : s.grounded,
                  path: s.path, lf: f ? x : s.lf };
        var out = P.stepPlayer(n, dt, g, x + DX, world.holes);
        if (out === 'void') continue;
        if (n.y > P.FLOOR + P.VOID_DEATH || n.y < P.CEIL - P.VOID_DEATH) continue;
        if (hits(world, x + DX, n.y, t + dt)) continue;
        if (f) n.path = s.path.concat(x);
        var cb = Math.min(15, Math.max(0, Math.ceil((n.lf + cool - x) / DX)));
        var key = ((((Math.round(n.y / QY) * 2 + (n.grav > 0 ? 1 : 0)) * 4096) +
                   (Math.round(n.vy / QV) + 2048)) * 16) + cb;
        var at = seen[key];
        if (at !== undefined) {
          if (n.path.length < next[at].path.length) next[at] = n;
          continue;
        }
        seen[key] = next.length;
        next.push(n);
      }
    }
    if (!next.length) return { ok: false, atX: x - b.x0 };
    if (next.length > BEAM) {
      // Thin by even sampling across the state space, not by "fewest flips" —
      // truncating on flip count throws away exactly the aggressive lines that
      // the hardest patterns require.
      /* Thinning has to preserve BOTH the cheap lines and the spread. Pure
         y-diversity culls the one-flip line a human would actually take; pure
         flip-count keeps a thousand variants of the same idea. Take the cheapest
         40% outright, then sample the rest evenly across the state space. */
      next.sort(function (a, c) { return a.path.length - c.path.length || a.y - c.y; });
      var headN = Math.floor(BEAM * 0.4), q;
      var keep = next.slice(0, headN);
      var rest = next.slice(headN);
      rest.sort(function (a, c) { return a.y - c.y || a.vy - c.vy; });
      var want = BEAM - headN, stride = rest.length / want;
      for (q = 0; q < want; q++) keep.push(rest[Math.floor(q * stride)]);
      next = keep;
    }
    beam = next;
  }
  var lines = [], sig = Object.create(null);
  beam.sort(function (a, c) { return a.path.length - c.path.length; });
  for (var k = 0; k < beam.length && lines.length < 6; k++) {
    var key2 = beam[k].path.join(',');
    if (sig[key2]) continue;
    sig[key2] = 1; lines.push(beam[k].path);
  }
  return { ok: true, lines: lines, minFlips: beam[0].path.length };
}

/* Deterministic replay of one exact flip schedule. */
function replay(p, speed, t0, grav, flips) {
  var b = bounds(p), world = materialize(p, b.x0);
  var g = P.gravityFor(speed, 1), dt = DX / speed;
  var st = { y: grav > 0 ? P.FLOOR - P.R : P.CEIL + P.R, vy: 0, grav: grav, grounded: true };
  var fi = 0;
  for (var x = b.start; x < b.end; x += DX) {
    var t = t0 + (x - b.start) / speed;
    while (fi < flips.length && flips[fi] <= x) { st.grav = -st.grav; st.grounded = false; fi++; }
    var out = P.stepPlayer(st, dt, g, x + DX, world.holes);
    if (out === 'void') return false;
    if (st.y > P.FLOOR + P.VOID_DEATH || st.y < P.CEIL - P.VOID_DEATH) return false;
    if (hits(world, x + DX, st.y, t + dt)) return false;
  }
  // A flip scheduled past the end of the section simply never happened — that
  // is a survivable line, not a death. Counting it as one made every pattern
  // whose last flip sat near the exit look impossibly tight.
  return true;
}

/* The search happily returns lines with 60 flips, because hopping in place on
   the floor is free and costs it nothing. A human does not play that way. Strip
   every flip pair the run survives without, leaving the line an actual person
   would take — that is the only line whose timing slack means anything. */
function minimize(p, speed, t0, grav, flips) {
  var cur = flips.slice(), improved = true, guard = 0, i, cand;
  while (improved && guard++ < 60) {
    improved = false;
    for (i = cur.length - 2; i >= 0; i--) {           // adjacent pairs keep gravity parity
      cand = cur.slice(); cand.splice(i, 2);
      if (replay(p, speed, t0, grav, cand)) { cur = cand; improved = true; }
    }
  }
  if (cur.length <= 14) {                              // then any remaining redundant pair
    improved = true; guard = 0;
    while (improved && guard++ < 30) {
      improved = false;
      outer: for (i = 0; i < cur.length; i++) {
        for (var j = i + 1; j < cur.length; j++) {
          cand = cur.slice(); cand.splice(j, 1); cand.splice(i, 1);
          if (replay(p, speed, t0, grav, cand)) { cur = cand; improved = true; break outer; }
        }
      }
    }
  }
  return cur;
}

/* How much timing error does the most forgiving line tolerate? Slide each flip
   independently until it dies; the tightest flip defines the pattern. */
function humanline(flips, cool) {
  for (var i = 1; i < flips.length; i++) if (flips[i] - flips[i - 1] < cool) return false;
  return true;
}

/* Find how far one flip can slide in each direction with the rest held fixed. */
function slackOf(p, speed, t0, grav, flips, i, cool) {
  var lo = 0, hi = 0, d, cand;
  for (d = DX; d <= SLACK_CAP; d += DX) {
    cand = flips.slice(); cand[i] -= d;
    if (!humanline(cand, cool) || !replay(p, speed, t0, grav, cand)) break;
    lo = d;
  }
  for (d = DX; d <= SLACK_CAP; d += DX) {
    cand = flips.slice(); cand[i] += d;
    if (!humanline(cand, cool) || !replay(p, speed, t0, grav, cand)) break;
    hi = d;
  }
  return { lo: lo, hi: hi, width: lo + hi + DX };
}

/* The solver returns *a* valid line, often with a flip pinned against the edge
   of its window, which reads as zero slack even when the pattern is generous.
   A player converges on the comfortable placement instead — so centre each flip
   inside its own window and measure there. That is the number a human feels. */
function recenter(p, speed, t0, grav, flips, cool) {
  var b = bounds(p), step = DX * 2;
  var cur = flips.slice();
  for (var pass = 0; pass < 4; pass++) {
    var moved = false;
    for (var i = 0; i < cur.length; i++) {
      // Scan this flip across its entire legal range with the others held, then
      // sit in the middle of the WIDEST survivable band — not merely the band we
      // happen to be standing in. Local nudging gets stuck against an edge.
      var runStart = null, bestC = null, bestW = 0;
      for (var v = b.start - 8; v <= b.end; v += step) {
        var cand = cur.slice(); cand[i] = v;
        var ok = humanline(cand, cool) && replay(p, speed, t0, grav, cand);
        if (ok && runStart === null) runStart = v;
        if ((!ok || v + step > b.end) && runStart !== null) {
          var end = ok ? v : v - step, w = end - runStart + step;
          if (w > bestW) { bestW = w; bestC = Math.round((runStart + end) / 2 / DX) * DX; }
          runStart = null;
        }
      }
      if (bestC !== null && bestC !== cur[i]) {
        var c2 = cur.slice(); c2[i] = bestC;
        if (humanline(c2, cool) && replay(p, speed, t0, grav, c2)) { cur = c2; moved = true; }
      }
    }
    if (!moved) {
      /* Coordinate ascent stalls when two flips constrain each other. Slide the
         whole line as a unit and let the per-flip pass run again from there. */
      var jumped = false;
      for (var sh = -6; sh <= 6 && !jumped; sh++) {
        if (!sh) continue;
        var g2 = cur.map(function (v) { return v + sh * DX * 3; });
        if (!humanline(g2, cool) || !replay(p, speed, t0, grav, g2)) continue;
        var before = tightestOf(p, speed, t0, grav, cur, cool);
        if (tightestOf(p, speed, t0, grav, g2, cool) > before) { cur = g2; jumped = true; }
      }
      if (!jumped) break;
    }
  }
  return cur;
}

function tightestOf(p, speed, t0, grav, flips, cool) {
  var m = Infinity;
  for (var i = 0; i < flips.length; i++) m = Math.min(m, slackOf(p, speed, t0, grav, flips, i, cool).width);
  return m;
}

/* For lines of one or two flips — most of the library — the whole solution
   space is small enough to scan outright. The grid is coarse, so it returns the
   best cell as a SEED which the caller then measures exactly; reading slack off
   the grid directly quantises a 50ms window down to one 24px cell and reports
   a fair pattern as a coin flip. */
function exhaustive(p, speed, t0, grav, nFlips, cool) {
  var b = bounds(p), lo = b.start - 8, hi = b.end;
  var step = nFlips === 1 ? DX : DX * 3;
  var xs = [];
  for (var v = lo; v <= hi; v += step) xs.push(v);

  if (nFlips === 1) {
    var run = null, bestC = null, bestW = 0;
    for (var i = 0; i < xs.length; i++) {
      var ok1 = replay(p, speed, t0, grav, [xs[i]]);
      if (ok1 && run === null) run = xs[i];
      if ((!ok1 || i === xs.length - 1) && run !== null) {
        var e = ok1 ? xs[i] : xs[i - 1], w = e - run + step;
        if (w > bestW) { bestW = w; bestC = Math.round((run + e) / 2 / DX) * DX; }
        run = null;
      }
    }
    return bestC === null ? null : [bestC];
  }

  // two flips: survivable grid, then the largest cell whose row and column runs
  // are both wide — that is the placement a player settles into.
  var grid = [], a, c;
  for (a = 0; a < xs.length; a++) {
    grid[a] = [];
    for (c = 0; c < xs.length; c++) {
      grid[a][c] = (xs[c] - xs[a] >= cool) && replay(p, speed, t0, grav, [xs[a], xs[c]]);
    }
  }
  var best2 = 0, seed = null;
  for (a = 0; a < xs.length; a++) for (c = 0; c < xs.length; c++) {
    if (!grid[a][c]) continue;
    var w1 = 1, k;
    for (k = a - 1; k >= 0 && grid[k][c]; k--) w1++;
    for (k = a + 1; k < xs.length && grid[k][c]; k++) w1++;
    var w2 = 1;
    for (k = c - 1; k >= 0 && grid[a][k]; k--) w2++;
    for (k = c + 1; k < xs.length && grid[a][k]; k++) w2++;
    var m = Math.min(w1, w2) * step;
    if (m > best2) { best2 = m; seed = [xs[a], xs[c]]; }
  }
  return seed;
}

function windowMs(p, speed, t0, grav, lines) {
  var best = 0, cool = COOLDOWN_S * speed;
  var minLen = Infinity;
  for (var li = 0; li < lines.length; li++) {
    var flips = lines[li];
    if (!flips.length) return Infinity;
    if (!replay(p, speed, t0, grav, flips)) continue;
    flips = minimize(p, speed, t0, grav, flips);
    if (!flips.length) return Infinity;
    if (flips.length > minLen + 2) continue;           // ignore needlessly busy lines
    minLen = Math.min(minLen, flips.length);
    flips = recenter(p, speed, t0, grav, flips, cool);
    var tightest = Infinity;
    for (var i = 0; i < flips.length; i++) {
      tightest = Math.min(tightest, slackOf(p, speed, t0, grav, flips, i, cool).width / speed * 1000);
    }
    if (tightest > best) best = tightest;
  }
  /* Scan BOTH the one-flip and two-flip solution spaces. A player will gladly
     spend an extra tap for a more forgiving line, so the minimal-flip solution
     is not necessarily the one they take — the needle patterns are twice as
     forgiving with two flips as with one. */
  for (var n = 1; n <= 2; n++) {
    var seed = exhaustive(p, speed, t0, grav, n, cool);
    if (!seed || !replay(p, speed, t0, grav, seed)) continue;
    seed = recenter(p, speed, t0, grav, seed, cool);
    var w = tightestOf(p, speed, t0, grav, seed, cool) / speed * 1000;
    if (w > best) best = w;
  }
  return best;
}

/* --inspect <id> prints the exact line the solver takes through one pattern.
   This is the tool you reach for when a pattern "feels" wrong in playtest. */
var insp = process.argv.indexOf('--inspect');
if (insp >= 0) {
  var want = process.argv[insp + 1];
  var pp = PAT.list.filter(function (q) { return q.id === want; })[0];
  if (!pp) { console.error('no pattern named ' + want); process.exit(2); }
  var sp = P.speedAt(260);
  console.log('\n  ' + pp.id + '  tier ' + pp.tier + '  len ' + pp.len + '  speed ' + Math.round(sp));
  [1, -1].forEach(function (grav) {
    var r = solve(pp, sp, 0, grav);
    if (!r.ok) { console.log('   from ' + (grav > 0 ? 'floor  ' : 'ceiling') + ': UNSURVIVABLE at x=' + r.atX); return; }
    r.lines.slice(0, 3).forEach(function (ln, i) {
      var m = minimize(pp, sp, 0, grav, ln);
      var w = windowMs(pp, sp, 0, grav, [ln]);
      console.log('   from ' + (grav > 0 ? 'floor  ' : 'ceiling') + ' line' + i +
        ': raw ' + ln.length + ' flips -> minimal [' + m.map(function (v) { return v - 400; }).join(', ') +
        ']  slack ' + (isFinite(w) ? Math.round(w) + 'ms' : 'free'));
    });
  });
  console.log('');
  process.exit(0);
}

var speeds = [P.speedAt(0), P.speedAt(70), P.speedAt(260)];
var fails = [], warns = [], rows = [];
var t0Start = Date.now();

PAT.list.forEach(function (p) {
  var dyn = isDynamic(p);
  var phases = dyn ? [0, 0.17, 0.34, 0.51, 0.68, 0.85] : [0];
  var allOk = true, failAt = null, minFlips = 99, worstWindow = Infinity;

  for (var si = 0; si < speeds.length; si++) {
    for (var pi = 0; pi < phases.length; pi++) {
      for (var gi = 0; gi < 2; gi++) {
        var grav = gi ? -1 : 1;
        var r = solve(p, speeds[si], phases[pi] * 3.7, grav);
        if (!r.ok) {
          allOk = false;
          failAt = { speed: Math.round(speeds[si]), phase: phases[pi], grav: grav, x: r.atX };
          si = speeds.length; pi = phases.length; break;
        }
        // Measure slack at the hardest speed only — that is where it is thinnest.
        if (si === speeds.length - 1) {
          var line0 = minimize(p, speeds[si], phases[pi] * 3.7, grav, r.lines[0]);
          minFlips = Math.min(minFlips, line0.length);
          var w = windowMs(p, speeds[si], phases[pi] * 3.7, grav, r.lines);
          if (w < worstWindow) worstWindow = w;
        }
      }
    }
  }

  /* Slack is measured exactly when the line needs one or two flips (the whole
     space is scanned). Beyond that it is a lower bound from hill-climbing, so
     it is reported as >= and held to a floor that reflects the weaker claim. */
  var exact = minFlips <= 2;
  var floor = exact ? TIER_FLOOR[p.tier] : LB_FLOOR[p.tier];
  rows.push({ id: p.id, tier: p.tier, ok: allOk, window: worstWindow, flips: minFlips,
              dyn: dyn, failAt: failAt, exact: exact, floor: floor });
  if (!allOk) fails.push(p.id + ' @x=' + failAt.x + ' (speed ' + failAt.speed + ', from ' + (failAt.grav > 0 ? 'floor' : 'ceiling') + ')');
  else if (worstWindow < floor) warns.push(p.id + ' ' + Math.round(worstWindow) + 'ms<' + floor);
});

function pad(s, n) { s = String(s); while (s.length < n) s += ' '; return s; }
rows.sort(function (a, b) { return a.tier - b.tier || a.id.localeCompare(b.id); });
console.log('\n  ONE MORE — pattern fairness report');
console.log('  ' + '-'.repeat(64));
console.log('  ' + pad('PATTERN', 22) + pad('TIER', 6) + pad('FLIPS', 7) + pad('SLACK', 10) + 'RESULT');
console.log('  ' + '-'.repeat(64));
rows.forEach(function (r) {
  var res = r.ok ? (r.window < r.floor ? 'TIGHT (floor ' + r.floor + 'ms)' : 'pass') : 'FAIL @x=' + r.failAt.x;
  console.log('  ' + pad(r.id + (r.dyn ? ' *' : ''), 22) + pad(String(r.tier), 6) +
    pad(r.flips === 99 ? '-' : String(r.flips), 7) +
    pad(isFinite(r.window) ? (r.exact ? '' : '>=') + Math.round(r.window) + 'ms' : 'free', 10) + res);
});
console.log('  ' + '-'.repeat(64));
console.log('  * = moving geometry, validated across 6 phase offsets');
console.log('  slack = timing error the most forgiving line tolerates, at top speed');
console.log('  >= marks a lower bound (line needs 3+ flips; space not scanned exhaustively)');
console.log('  ' + rows.length + ' patterns / ' + (rows.length - fails.length) +
  ' survivable at every speed, entry side and phase  (' + ((Date.now() - t0Start) / 1000).toFixed(1) + 's)');
if (warns.length) console.log('  BELOW TIER FLOOR: ' + warns.join(', '));
if (fails.length) { console.log('  UNSURVIVABLE:\n    ' + fails.join('\n    ') + '\n'); process.exit(1); }
if (warns.length) { console.log('  ' + warns.length + ' pattern(s) tighter than their tier allows.\n'); process.exit(1); }
console.log('  All patterns fair, every tier within its slack budget.\n');
