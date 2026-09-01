#!/usr/bin/env node
/* ONE MORE — unit tests for the pure logic: physics, determinism, generation,
   ghosts and progression. The pattern library has its own proof in
   tools/validate.js; this covers everything around it. */
'use strict';
var path = require('path');
var SRC = path.join(__dirname, '..', 'src');

// minimal localStorage so the progression module loads under node
var mem = {};
globalThis.localStorage = {
  getItem: function (k) { return k in mem ? mem[k] : null; },
  setItem: function (k, v) { mem[k] = String(v); },
  removeItem: function (k) { delete mem[k]; }
};

require(path.join(SRC, '00-core.js'));
require(path.join(SRC, '10-physics.js'));
require(path.join(SRC, '20-patterns.js'));
require(path.join(SRC, '25-generator.js'));
require(path.join(SRC, '30-mutations.js'));
require(path.join(SRC, '32-analysis.js'));
require(path.join(SRC, '35-progress.js'));
require(path.join(SRC, '40-ghost.js'));

var P = OM.phys, PAT = OM.patterns;
var pass = 0, fail = 0;
function ok(name, cond, detail) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (detail ? '  -> ' + detail : '')); }
}
function near(a, b, eps) { return Math.abs(a - b) <= (eps || 1e-6); }

console.log('\n  core');
ok('fmtTime formats mm:ss.cc', OM.fmtTime(107.283, 2) === '01:47.28', OM.fmtTime(107.283, 2));
ok('fmtTime pads seconds', OM.fmtTime(65.5, 2) === '01:05.50', OM.fmtTime(65.5, 2));
ok('fmtTime clamps negatives', OM.fmtTime(-3, 2) === '00:00.00');
ok('dayKey round-trips', OM.dayKey(OM.dayIndex(new Date(Date.UTC(2026, 7, 30)))) === '2026-08-30');
ok('hashSeed is stable', OM.hashSeed('2026-08-30') === OM.hashSeed('2026-08-30'));
ok('hashSeed separates days', OM.hashSeed('2026-08-30') !== OM.hashSeed('2026-08-31'));

console.log('\n  rng');
var a = OM.rng(1234), b = OM.rng(1234), same = true;
for (var i = 0; i < 500; i++) if (a.next() !== b.next()) same = false;
ok('same seed gives identical stream', same);
var c = OM.rng(1235), diff = false, r1 = OM.rng(1234);
for (i = 0; i < 50; i++) if (r1.next() !== c.next()) diff = true;
ok('different seed diverges', diff);
var rr = OM.rng(7), inRange = true;
for (i = 0; i < 3000; i++) { var v = rr.next(); if (v < 0 || v >= 1) inRange = false; }
ok('output stays in [0,1)', inRange);

console.log('\n  physics');
ok('flip arc is speed invariant', (function () {
  var spans = [0, 40, 120, 300].map(function (t) {
    var s = P.speedAt(t), g = P.gravityFor(s, 1);
    return Math.sqrt(2 * P.TRANSIT_H / g) * s;
  });
  return spans.every(function (s) { return near(s, spans[0], 0.01); });
})(), 'this invariant is what makes every authored pattern valid at every speed');
ok('the practice speed keeps the same flip arc as the game', (function () {
  function span(sp) { return Math.sqrt(2 * P.TRANSIT_H / P.gravityFor(sp, 1)) * sp; }
  return near(span(P.PRACTICE_SPEED), span(P.BASE_SPEED), 1e-9) &&
         P.PRACTICE_SPEED < P.BASE_SPEED;
})(), 'practice is a slower run of the same game, not an easier one');
ok('a flip line stays executable at the practice speed', (function () {
  /* The cooldown is a fixed number of SECONDS, so at a lower speed it covers
     fewer pixels. Any sequence of flip positions a human could hit at full
     speed is therefore still executable slower — which is half of why the
     static patterns need no revalidation for practice. The other half is the
     arc invariant above. */
  var COOLDOWN_S = 0.10;
  return COOLDOWN_S * P.PRACTICE_SPEED < COOLDOWN_S * P.speedAt(260);
})());
ok('speed increases monotonically', (function () {
  for (var t = 0; t < 400; t += 5) if (P.speedAt(t + 5) <= P.speedAt(t)) return false;
  return true;
})());
ok('player lands on the floor', (function () {
  var st = { y: P.CEIL + P.R, vy: 0, grav: 1, grounded: false };
  for (var i = 0; i < 4000; i++) P.stepPlayer(st, 1 / 240, P.BASE_G, 0, []);
  return near(st.y, P.FLOOR - P.R, 0.001) && st.grounded;
})());
ok('player falls through a hole into the void', (function () {
  var st = { y: P.FLOOR - P.R - 4, vy: 0, grav: 1, grounded: false };
  var holes = [{ x: -1e6, w: 2e6, side: 'floor' }];
  for (var i = 0; i < 4000; i++) if (P.stepPlayer(st, 1 / 240, P.BASE_G, 0, holes) === 'void') return true;
  return false;
})());
ok('a surface stops the fall even at huge dt', (function () {
  var st = { y: P.CEIL + P.R, vy: 0, grav: 1, grounded: false };
  P.stepPlayer(st, 0.5, P.BASE_G, 0, []);
  return st.y <= P.FLOOR - P.R + 0.001;
})());
ok('circleRectDist2 is zero inside', P.circleRectDist2(10, 10, 5, 0, 0, 20, 20) === 0);
ok('circleRectDist2 measures the gap', near(P.circleRectDist2(30, 10, 5, 0, 0, 20, 20), 100));
ok('worldAt advances with time', P.worldAt(0).id === 'origin' && P.worldAt(250).id === 'nightmare');
ok('corruption is clamped', P.corruptionAt(0) === 0 && P.corruptionAt(1e5) === 1);

console.log('\n  patterns');
ok('library is non-empty and tiered 1..5', (function () {
  if (PAT.list.length < 20) return false;
  for (var t = 1; t <= 5; t++) if (!PAT.byTier[t] || !PAT.byTier[t].length) return false;
  return true;
})());
ok('every item sits inside its declared length', (function () {
  return PAT.list.every(function (p) {
    return p.items.every(function (it) { return it.dx >= 0 && it.dx + (it.w || 0) <= p.len + 1; });
  });
})());
ok('no pattern seals the tunnel', (function () {
  // a solid wall across the full height at one x would be unsurvivable by
  // construction, whatever the beam search says
  return PAT.list.every(function (p) {
    var x0 = 0;
    for (var x = 0; x < p.len; x += 8) {
      var covered = 0, marks = [];
      p.items.forEach(function (it) {
        if (it.t === 'hole' || it.dx > x || it.dx + it.w < x) return;
        if (it.t === 'spike' || it.t === 'block') {
          marks.push(it.side === 'floor' ? [P.FLOOR - it.h, P.FLOOR] : [P.CEIL, P.CEIL + it.h]);
        } else if (it.t === 'bar') marks.push([it.y0, it.y1]);
        else if (it.t === 'laser') {
          marks.push(it.side === 'ceil' ? [P.CEIL, P.CEIL + it.h] : [P.FLOOR - it.h, P.FLOOR]);
        } else if (it.t === 'mover') marks.push([it.cy - it.amp - it.h / 2, it.cy + it.amp + it.h / 2]);
      });
      marks.sort(function (m, n) { return m[0] - n[0]; });
      var reach = P.CEIL;
      for (var i = 0; i < marks.length; i++) {
        if (marks[i][0] > reach + 2 * P.R) break;
        reach = Math.max(reach, marks[i][1]);
      }
      if (reach >= P.FLOOR) return false;
    }
    return true;
  });
})());
ok('unique ids', new Set(PAT.list.map(function (p) { return p.id; })).size === PAT.list.length);
ok('piston extends and retracts', (function () {
  var o = { t: 'piston', side: 'floor', x: 0, w: 80, h: 300, rate: 1, duty: 0.5, phase: 0 };
  var mid = PAT.pistonExt(o, 0.25), out = PAT.pistonExt(o, 0.6);
  return near(mid, 300, 1) && out === 0 && PAT.pistonExt(o, 0.01) < 300;
})());
ok('gate always leaves an opening', (function () {
  var o = { t: 'gate', x: 0, w: 80, half: 110, cy: (P.CEIL + P.FLOOR) / 2, amp: 400, rate: 1, phase: 0 };
  for (var t = 0; t < 3; t += 0.01) {
    var r = PAT.rectsOf(o, t);
    if (r.length !== 2) return false;
    var gap = r[1].y - (r[0].y + r[0].h);
    if (gap < 2 * P.R + 10) return false;            // must stay passable
    if (r[0].h < 10 || r[1].h < 10) return false;    // and both jaws must be real
  }
  return true;
})());
ok('laser rects follow the duty cycle', (function () {
  var o = { t: 'laser', side: 'floor', x: 0, w: 40, h: 300, rate: 1, duty: 0.5, phase: 0 };
  return PAT.rectsOf(o, 0.1).length === 1 && PAT.rectsOf(o, 0.7).length === 0;
})());
ok('mover stays inside the tunnel', (function () {
  var o = { t: 'mover', x: 0, w: 40, h: 100, cy: (P.CEIL + P.FLOOR) / 2, amp: 900, rate: 1, phase: 0 };
  for (var t = 0; t < 4; t += 0.02) {
    var y = PAT.moverY(o, t);
    if (y - o.h / 2 < P.CEIL - 0.001 || y + o.h / 2 > P.FLOOR + 0.001) return false;
  }
  return true;
})());

console.log('\n  generator');
ok('same seed builds the identical world', (function () {
  function build(seed) {
    var g = OM.Generator(OM.rng(seed));
    g.ensure(30000, 60, 1);
    return JSON.stringify(g.obstacles.map(function (o) { return [o.t, o.x, o.w || 0]; }));
  }
  return build(99) === build(99);
})(), 'the Daily Challenge depends on this exactly');
ok('different seeds build different worlds', (function () {
  function build(seed) {
    var g = OM.Generator(OM.rng(seed));
    g.ensure(30000, 60, 1);
    return JSON.stringify(g.obstacles.map(function (o) { return [o.t, o.x]; }));
  }
  return build(1) !== build(2);
})());
ok('obstacles are generated in ascending x', (function () {
  var g = OM.Generator(OM.rng(5));
  g.ensure(40000, 120, 1);
  for (var i = 1; i < g.obstacles.length; i++) if (g.obstacles[i].x < g.obstacles[i - 1].x - 2200) return false;
  return g.obstacles.length > 40;
})());
ok('opening runway is clear', (function () {
  var g = OM.Generator(OM.rng(3));
  g.ensure(5000, 0, 1);
  return g.obstacles.every(function (o) { return o.x >= 800; });
})(), 'the first seconds must never kill a first-time player');
ok('pruning keeps memory flat', (function () {
  var g = OM.Generator(OM.rng(11));
  for (var x = 0; x < 400000; x += 2000) { g.ensure(x + 4000, x / 700, 1); g.prune(x); }
  return g.obstacles.length < 80;
})(), 'obstacles=' + (function () {
  var g = OM.Generator(OM.rng(11));
  for (var x = 0; x < 400000; x += 2000) { g.ensure(x + 4000, x / 700, 1); g.prune(x); }
  return g.obstacles.length;
})());
ok('difficulty escalates with time', (function () {
  function avgTier(t) {
    var g = OM.Generator(OM.rng(21));
    g.ensure(60000, t, 1);
    var seen = {}, sum = 0, n = 0;
    g.obstacles.forEach(function (o) { if (!seen[o.pat + o.x]) { seen[o.pat + o.x] = 1; } });
    var ids = {};
    g.obstacles.forEach(function (o) { ids[o.pat] = 1; });
    Object.keys(ids).forEach(function (id) {
      var p = PAT.list.filter(function (q) { return q.id === id; })[0];
      if (p) { sum += p.tier; n++; }
    });
    return sum / n;
  }
  return avgTier(5) < avgTier(150);
})());
ok('director never emits an empty tier set', (function () {
  for (var t = 0; t < 600; t += 3) {
    var d = P.directorAt(t);
    if (d.weights.reduce(function (a, b) { return a + b; }, 0) <= 0) return false;
  }
  return true;
})());

console.log('\n  mutations');
ok('at most two run at once', (function () {
  for (var seed = 0; seed < 300; seed++) {
    var sc = OM.mutations.schedule(OM.rng(seed));
    for (var t = 0; t < 300; t += 0.5) if (OM.mutations.activeAt(sc, t).list.length > 2) return false;
  }
  return true;
})());
ok('two mutations never share a class', (function () {
  for (var seed = 0; seed < 300; seed++) {
    var sc = OM.mutations.schedule(OM.rng(seed));
    for (var t = 0; t < 300; t += 0.5) {
      var a = OM.mutations.activeAt(sc, t).list, seen = {};
      for (var i = 0; i < a.length; i++) {
        if (seen[a[i].m.cls]) return false;
        seen[a[i].m.cls] = 1;
      }
    }
  }
  return true;
})(), 'two visibility mutations at once would make a proven-fair pattern unreadable');
ok('nothing stacks before the overlay window', (function () {
  for (var seed = 0; seed < 300; seed++) {
    var sc = OM.mutations.schedule(OM.rng(seed));
    for (var t = 0; t < OM.mutations.overlayFrom; t += 0.5) {
      if (OM.mutations.activeAt(sc, t).list.length > 1) return false;
    }
  }
  return true;
})(), 'the first 90s must play exactly as they were tuned');
ok('stacking does actually happen later', (function () {
  var hits = 0;
  for (var seed = 0; seed < 300; seed++) {
    var sc = OM.mutations.schedule(OM.rng(seed));
    for (var t = OM.mutations.overlayFrom; t < 300; t += 0.5) {
      if (OM.mutations.activeAt(sc, t).list.length > 1) { hits++; break; }
    }
  }
  return hits > 250;
})(), 'machinery that pretends to stack but never does is the thing being fixed');
ok('every mutation declares a class', OM.mutations.list.every(function (m) { return !!m.cls; }));
ok('the dead `ending` field is gone', (function () {
  var sc = OM.mutations.schedule(OM.rng(1));
  return !('ending' in OM.mutations.activeAt(sc, 0));
})());
ok('schedule is deterministic per seed', (function () {
  var s1 = JSON.stringify(OM.mutations.schedule(OM.rng(42)).map(function (s) { return [s.at, s.m.id]; }));
  var s2 = JSON.stringify(OM.mutations.schedule(OM.rng(42)).map(function (s) { return [s.at, s.m.id]; }));
  return s1 === s2;
})());
ok('no mutation touches gravity', OM.mutations.list.every(function (m) {
  return m.gravity === undefined && m.gmul === undefined;
}), 'a gravity mutation would void the fairness proof for every pattern');
ok('nothing fires in the first 15 seconds', OM.mutations.schedule(OM.rng(9))[0].at >= 15);
ok('the same mutation never repeats back to back within a track', (function () {
  // the schedule now merges two tracks, so adjacency in the array is not
  // adjacency in time; the guarantee belongs per-track
  for (var seed = 0; seed < 60; seed++) {
    var sc = OM.mutations.schedule(OM.rng(seed));
    var pri = sc.filter(function (e) { return e.track === 'primary'; });
    for (var i = 1; i < pri.length; i++) if (pri[i].m.id === pri[i - 1].m.id) return false;
  }
  return true;
})());
ok('the same mutation is never active twice at once', (function () {
  for (var seed = 0; seed < 300; seed++) {
    var sc = OM.mutations.schedule(OM.rng(seed));
    for (var t = 0; t < 300; t += 0.5) {
      var a = OM.mutations.activeAt(sc, t).list, seen = {};
      for (var i = 0; i < a.length; i++) { if (seen[a[i].m.id]) return false; seen[a[i].m.id] = 1; }
    }
  }
  return true;
})());
ok('activeAt returns neutral mods before the first', (function () {
  var s = OM.mutations.schedule(OM.rng(3));
  var m = OM.mutations.activeAt(s, 1);
  return m.speed === 1 && m.spacing === 1 && !m.mirror && m.list.length === 0;
})());
ok('activeAt applies a running mutation', (function () {
  var s = OM.mutations.schedule(OM.rng(3));
  var m = OM.mutations.activeAt(s, s[0].at + 1);
  return m.list.length === 1;
})());

console.log('\n  ghosts');
ok('records and replays a path', (function () {
  var rec = OM.GhostRecorder(), x = 0;
  for (var i = 0; i < 600; i++) { x += 8; rec.sample(1 / 60, x, 300 + i, i < 300 ? 1 : -1); }
  var data = rec.finish();
  var gp = OM.GhostPlayer(data);
  if (!gp) return false;
  var s = gp.at(1.0);
  return s.y > 300 && s.y < 900 && s.x > 0 && gp.duration > 4;
})());
ok('short runs record no ghost', (function () {
  var rec = OM.GhostRecorder();
  for (var i = 0; i < 10; i++) rec.sample(1 / 60, i * 8, 300, 1);
  return rec.finish() === null;
})());
ok('playback clamps past the end', (function () {
  var rec = OM.GhostRecorder();
  for (var i = 0; i < 300; i++) rec.sample(1 / 60, i * 8, 300, 1);
  var gp = OM.GhostPlayer(rec.finish());
  return gp.at(9999).done === true;
})());
ok('x deltas stay small (cheap to store)', (function () {
  var rec = OM.GhostRecorder(), x = 0;
  for (var i = 0; i < 2400; i++) { x += 15; rec.sample(1 / 60, x, 400, 1); }
  var d = rec.finish();
  return d.dx.every(function (v) { return Math.abs(v) < 200; });
})());

console.log('\n  the read');
ok('the death log reads the corrected context key', (function () {
  OM.analysis.clear();
  OM.analysis.record({ time: 10, cause: 'spike', context: { pat: 't1_floor' } });
  return OM.analysis.history()[0].pat === 't1_floor';
})(), 'the producer called it context.tier while storing a pattern id');
ok('the unused tierOf helper is gone', OM.analysis.tierOf === undefined);
ok('byPat survives — a trial needs it', (function () {
  OM.analysis.clear();
  OM.analysis.record({ time: 10, cause: 'spike', context: { pat: 't1_floor' } });
  OM.analysis.record({ time: 10, cause: 'spike', context: { pat: 't1_floor' } });
  return OM.analysis.tally().byPat.t1_floor === 2;
})());
var A = OM.analysis;
function feed(cause, n, extra) {
  for (var i = 0; i < n; i++) A.record({ time: 20 + i, cause: cause, context: extra || {} });
}
ok('says nothing until it has evidence', (function () {
  A.clear(); feed('mover', 8);
  var r = A.read();
  return r.kind === 'none' && r.need === 4;
})(), 'an early diagnosis from four runs would be noise dressed up as insight');
ok('diagnoses a single dominant cause', (function () {
  A.clear(); feed('void', 20);
  var r = A.read();
  return r.kind === 'weakness' && r.family === 'nerve' && r.share === 1;
})(), 'this is the case that regressed once: 1-of-1 families read as an even split');
ok('diagnoses a dominant family across causes', (function () {
  A.clear(); feed('mover', 9); feed('laser', 8); feed('spike', 3);
  var r = A.read();
  return r.kind === 'weakness' && r.family === 'prediction';
})());
ok('refuses to invent a weakness from an even spread', (function () {
  A.clear(); feed('spike', 10); feed('mover', 10); feed('bar', 10); feed('void', 10);
  return A.read().kind === 'balanced';
})());
ok('cites counts that match the history', (function () {
  A.clear(); feed('mover', 15); feed('spike', 5);
  var r = A.read();
  return r.n === 20 && r.count === 15 && Math.abs(r.share - 0.75) < 1e-9;
})());
ok('history is capped so storage stays flat', (function () {
  A.clear(); feed('spike', 400);
  return A.history().length <= 260;
})());
ok('trend needs enough runs before it claims anything', (function () {
  A.clear(); feed('spike', 20);
  return A.trend() === null;
})());
ok('trend detects improvement', (function () {
  A.clear();
  for (var i = 0; i < 15; i++) A.record({ time: 10, cause: 'spike', context: {} });
  for (i = 0; i < 15; i++) A.record({ time: 40, cause: 'spike', context: {} });
  var t = A.trend();
  return t && t.delta > 25 && t.recent > t.early;
})());
ok('trend detects decline', (function () {
  A.clear();
  for (var i = 0; i < 15; i++) A.record({ time: 50, cause: 'spike', context: {} });
  for (i = 0; i < 15; i++) A.record({ time: 12, cause: 'spike', context: {} });
  var t = A.trend();
  return t && t.delta < -25;
})());
ok('a habit stays silent below the evidence gate', (function () {
  A.clear();
  for (var i = 0; i < 8; i++) {
    A.record({ time: 30, cause: 'spike', context: { sinceFlip: 2.0, flipRate: 1 } });
  }
  return A.habit() === null;
})());
ok('a habit stays silent when nothing clears its floor', (function () {
  A.clear();
  // deaths spread evenly across timings: nothing over-represented
  for (var i = 0; i < 40; i++) {
    A.record({ time: 30, cause: 'spike', context: { sinceFlip: i % 2 ? 0.15 : 2.0, flipRate: 1 } });
  }
  var h = A.habit();
  return h === null || h.mult >= 1.25;
})());
ok('a habit names a real over-representation', (function () {
  A.clear();
  for (var i = 0; i < 30; i++) {
    A.record({ time: 30, cause: 'spike', context: { sinceFlip: 2.0, flipRate: 1 } });
  }
  var h = A.habit();
  return h && h.key === 'late' && h.share > 0.9 && h.mult > 1.5;
})());
ok('the same share is judged against YOUR flip rate, not a constant', (function () {
  // identical behaviour, two players: one flips often, one rarely.
  // 70% late deaths is damning for the first and unremarkable for the second,
  // because long gaps are what rarely flipping produces.
  function run(fr) {
    A.clear();
    for (var i = 0; i < 30; i++) {
      A.record({ time: 30, cause: 'spike',
                 context: { sinceFlip: i < 21 ? 2.0 : 0.2, flipRate: fr } });
    }
    return A.habit();
  }
  var busy = run(1.0), idle = run(0.2);
  return busy && busy.key === 'late' && (!idle || idle.key !== 'late');
})(), 'this is the difference between an observation and a horoscope');
ok('a habit reports the baseline it was judged against', (function () {
  A.clear();
  for (var i = 0; i < 30; i++) {
    A.record({ time: 30, cause: 'spike', context: { sinceFlip: 2.0, flipRate: 1 } });
  }
  var h = A.habit();
  return h && h.expected > 0 && h.expected < 1 &&
         Math.abs(h.mult - h.share / h.expected) < 1e-9 &&
         h.count <= h.n;
})(), 'every number it prints must be checkable against the log');
ok('void deaths do not inflate the mid-flip habit', (function () {
  A.clear();
  // falling through a hole is airborne by definition; counting it would make
  // every hole-heavy player look like they die crossing
  for (var i = 0; i < 30; i++) {
    A.record({ time: 30, cause: 'void', context: { airborne: true, sinceFlip: 0.5, flipRate: 1 } });
  }
  return A.tally().transit === 0 && A.tally().nonVoid === 0;
})());
ok('the share stays silent below the evidence gate', (function () {
  A.clear(); feed('mover', 8);
  return A.shareClaim() === null;
})(), 'a share button is not a reason to invent a read');
ok('the share quotes the habit, and every number in it is checkable', (function () {
  A.clear();
  for (var i = 0; i < 30; i++) {
    A.record({ time: 30, cause: 'spike', context: { sinceFlip: 2.0, flipRate: 1 } });
  }
  var h = A.habit(), c = A.shareClaim();
  if (!h || !c) return false;
  return c.indexOf(h.me) === 0 &&
         c.indexOf(Math.round(h.share * 100) + '% of my deaths') > 0 &&
         c.indexOf(h.mult.toFixed(1) + '\u00d7') > 0;
})());
ok('with no habit the share falls back to the family read', (function () {
  A.clear(); feed('mover', 12); feed('laser', 6); feed('spike', 2);
  var r = A.read(), c = A.shareClaim();
  if (r.kind !== 'weakness' || A.habit() !== null || !c) return false;
  return c.indexOf(r.me) === 0 &&
         c.indexOf('my last ' + r.n + ' deaths') > 0 &&
         c.indexOf(r.mult.toFixed(1) + '\u00d7') > 0;
})());
ok('an even spread shares nothing rather than something', (function () {
  A.clear(); feed('spike', 10); feed('mover', 10); feed('bar', 10); feed('void', 10);
  return A.read().kind === 'balanced' && A.shareClaim() === null;
})(), 'silence is the correct fallback, not a manufactured line');
/* ---- the read as a history ---- */
ok('a history needs two halves worth of deaths', (function () {
  A.clear();
  for (var i = 0; i < 20; i++) A.record({ time: 20, cause: 'spike', mode: 'endless', context: {} });
  return A.shift() === null && A.weaknessBands() === null;
})());
ok('a shift is only named when the thing beating you changed', (function () {
  A.clear();
  for (var i = 0; i < 20; i++) A.record({ time: 20, cause: 'spike', mode: 'endless', context: {} });
  for (i = 0; i < 20; i++) A.record({ time: 20, cause: 'mover', mode: 'endless', context: {} });
  var sh = A.shift();
  return sh && sh.from.family === 'timing' && sh.to.family === 'prediction' &&
         sh.from.n === 20 && sh.to.n === 20;
})());
ok('the same weakness throughout is not a story', (function () {
  A.clear();
  for (var i = 0; i < 40; i++) A.record({ time: 20, cause: 'spike', mode: 'endless', context: {} });
  return A.shift() === null;
})());
ok('two halves of nothing in particular is not a story either', (function () {
  A.clear();
  var causes = ['spike', 'mover', 'bar', 'void'];
  for (var i = 0; i < 48; i++) {
    A.record({ time: 20, cause: causes[i % 4], mode: 'endless', context: {} });
  }
  return A.shift() === null;
})(), 'a 51/49 wobble between two families is not a change of weakness');
ok('drilling cannot fake a shift towards the thing you drilled', (function () {
  A.clear();
  for (var i = 0; i < 20; i++) A.record({ time: 20, cause: 'mover', mode: 'endless', context: {} });
  // 40 trial deaths, all timing, from deliberately practising timing
  for (i = 0; i < 40; i++) {
    A.record({ time: 20, cause: 'spike', mode: 'trial', family: 'timing', context: {} });
  }
  for (i = 0; i < 20; i++) A.record({ time: 20, cause: 'mover', mode: 'endless', context: {} });
  return A.shift() === null;
})(), 'a trial is one family by construction; counting it would invent the shift');
ok('the bands cover every death they claim to', (function () {
  A.clear();
  for (var i = 0; i < 48; i++) {
    A.record({ time: 20, cause: i < 24 ? 'spike' : 'mover', mode: 'endless', context: {} });
  }
  var wb = A.weaknessBands(8), total = 0;
  for (i = 0; i < wb.buckets.length; i++) {
    var b = wb.buckets[i], sum = 0;
    for (var k in b.counts) sum += b.counts[k];
    if (sum !== b.n) return false;
    total += b.n;
  }
  return total === wb.n && wb.n === 48;
})());
ok('the bands are in recorded order, oldest first', (function () {
  A.clear();
  for (var i = 0; i < 48; i++) {
    A.record({ time: 20, cause: i < 24 ? 'spike' : 'mover', mode: 'endless', context: {} });
  }
  var wb = A.weaknessBands(8), b = wb.buckets;
  return (b[0].counts.timing || 0) > 0 && !(b[0].counts.prediction > 0) &&
         (b[b.length - 1].counts.prediction || 0) > 0 &&
         !(b[b.length - 1].counts.timing > 0);
})());
ok('every family has a band weight, so none is invisible', (function () {
  var fams = Object.keys(A.families);
  A.clear();
  for (var i = 0; i < 48; i++) {
    A.record({ time: 20, cause: 'spike', mode: 'endless', context: {} });
  }
  var wb = A.weaknessBands();
  if (wb.order.length !== fams.length) return false;
  for (i = 0; i < fams.length; i++) if (wb.order.indexOf(fams[i]) < 0) return false;
  return true;
})());

/* ---- the read before there is a read ---- */
function death(cause, ctx) {
  return { cause: cause, context: ctx || {} };
}
ok('nothing to say about nothing', A.moment(null) === null && A.moment({}) === null);
ok('the crossing time it quotes is the crossing time at that speed', (function () {
  var m = A.moment(death('spike', { speed: 860, sinceFlip: 3, airborne: false, grav: 1 }));
  return m && Math.abs(m.cross - P.TRANSIT_X / 860) < 1e-12 &&
         m.when.indexOf((P.TRANSIT_X / 860).toFixed(2) + 's') > 0;
})(), 'the one constant a player can act on: a crossing is the same distance at every speed');
ok('a flip that it had not finished is named as one', (function () {
  var speed = P.BASE_SPEED, cross = P.TRANSIT_X / speed;
  var m = A.moment(death('mover', { speed: speed, sinceFlip: cross * 0.4, airborne: true, grav: 1 }));
  return m && m.when.indexOf('it had not finished') > 0 &&
         m.where.indexOf('crossing to the floor') > 0;
})());
ok('a flip that had time is not accused of anything', (function () {
  var speed = P.BASE_SPEED, cross = P.TRANSIT_X / speed;
  var m = A.moment(death('spike', { speed: speed, sinceFlip: cross * 3, airborne: false, grav: -1 }));
  return m && m.when.indexOf('it had not finished') < 0 &&
         m.where.indexOf('on the ceiling') > 0;
})(), 'one death cannot show whether the gap you needed was even there');
ok('never having flipped is stated, not measured', (function () {
  var m = A.moment(death('spike', { speed: 430, sinceFlip: 99, airborne: false, grav: 1 }));
  return m && m.when.indexOf('had not flipped yet') > 0;
})());
ok('the void gets its own sentence', (function () {
  var m = A.moment(death('void', { speed: 430, sinceFlip: 0.4, airborne: true, grav: 1 }));
  return m && m.where.indexOf('floor ran out') > 0;
})());
ok('a missing speed falls back to the base speed rather than dividing by zero', (function () {
  var m = A.moment(death('spike', {}));
  return m && isFinite(m.cross) && m.cross > 0 &&
         Math.abs(m.cross - P.TRANSIT_T) < 1e-12;
})());

/* ---- did the drilling work? ---- */
/* Deliberately no clock stubbing: the before/after split is by position in the
   log, so these run at real speed and every one of them would fail if it ever
   went back to comparing timestamps — entries written in the same millisecond
   would all land on one side. */
function deaths(n, cause, mode, family) {
  for (var i = 0; i < n; i++) {
    A.record({ time: 20, cause: cause, mode: mode, family: family, context: {} });
  }
}
ok('no trial, no verdict', (function () {
  A.clear();
  deaths(30, 'spike', 'endless');
  return A.trialEffect('timing') === null;
})());
ok('a verdict needs deaths on both sides of the trial', (function () {
  A.clear();
  deaths(30, 'spike', 'endless');
  deaths(4, 'spike', 'trial', 'timing');
  deaths(3, 'spike', 'endless');   // only three normal deaths after
  return A.trialEffect('timing') === null;
})(), 'a two-run "after" window would be noise dressed as a result');
ok('a verdict measures the drop it can actually see', (function () {
  A.clear();
  deaths(12, 'spike', 'endless');  // 12 of 20 timing before = 60%
  deaths(8, 'mover', 'endless');
  deaths(6, 'spike', 'trial', 'timing');
  deaths(4, 'spike', 'endless');   // 4 of 20 timing after = 20%
  deaths(16, 'mover', 'endless');
  var e = A.trialEffect('timing');
  return e && e.direction === 'down' && e.trials === 6 &&
         Math.abs(e.before.share - 0.6) < 1e-9 && Math.abs(e.after.share - 0.2) < 1e-9 &&
         e.before.count === 12 && e.after.count === 4;
})());
ok('a verdict reports a rise as readily as a fall', (function () {
  A.clear();
  deaths(4, 'spike', 'endless');
  deaths(16, 'mover', 'endless');
  deaths(6, 'spike', 'trial', 'timing');
  deaths(14, 'spike', 'endless');
  deaths(6, 'mover', 'endless');
  var e = A.trialEffect('timing');
  return e && e.direction === 'up' && e.after.share > e.before.share;
})(), 'a drill that made things worse is the more useful thing to be told');
ok('trial deaths are excluded from both sides of their own verdict', (function () {
  // 40 trial deaths, all timing, sitting after the marker. If they counted,
  // the after-share would be near 100% and successful practice would read as
  // catastrophe.
  A.clear();
  deaths(10, 'spike', 'endless');
  deaths(10, 'mover', 'endless');
  deaths(40, 'spike', 'trial', 'timing');
  deaths(2, 'spike', 'endless');
  deaths(18, 'mover', 'endless');
  var e = A.trialEffect('timing');
  return e && e.after.n === 20 && e.after.count === 2 && e.direction === 'down';
})(), 'a trial is made of one family; counting it would invert every verdict');
ok('nightmare and legacy deaths stay out of the comparison', (function () {
  A.clear();
  deaths(20, 'spike', 'endless');
  deaths(6, 'spike', 'trial', 'timing');
  deaths(20, 'mover', 'endless');
  deaths(40, 'spike', 'nightmare');
  deaths(40, 'spike', null);       // recorded before md existed
  var e = A.trialEffect('timing');
  return e && e.before.n === 20 && e.after.n === 20 && e.after.count === 0;
})(), 'a mode a player took up after the trial must not be read as its effect');
ok('a small change is called unchanged, not a result', (function () {
  A.clear();
  deaths(10, 'spike', 'endless');
  deaths(10, 'mover', 'endless');
  deaths(6, 'spike', 'trial', 'timing');
  deaths(9, 'spike', 'endless');
  deaths(11, 'mover', 'endless');
  var e = A.trialEffect('timing');
  return e && e.direction === 'flat';
})());
ok('every number in a verdict is checkable against the log', (function () {
  A.clear();
  deaths(12, 'spike', 'endless');
  deaths(8, 'mover', 'endless');
  deaths(3, 'spike', 'trial', 'timing');
  deaths(5, 'spike', 'endless');
  deaths(15, 'mover', 'endless');
  var e = A.trialEffect('timing'), h = A.history();
  function normal(d) { return d.md === 'endless' || d.md === 'daily'; }
  var before = h.slice(0, e.from).filter(normal);
  var after = h.slice(e.from).filter(normal);
  return e.before.n === before.length && e.after.n === after.length &&
         Math.abs(e.before.share - e.before.count / e.before.n) < 1e-9 &&
         Math.abs(e.delta - (e.after.share - e.before.share)) < 1e-9;
})());
ok('a clock that jumps backwards cannot rewrite the verdict', (function () {
  A.clear();
  var real = Date.now, now = 5e12;
  Date.now = function () { return now; };
  try {
    deaths(20, 'spike', 'endless');
    now = 1;                          // the device's clock moved, the history did not
    deaths(3, 'spike', 'trial', 'timing');
    deaths(20, 'mover', 'endless');
  } finally { Date.now = real; }
  var e = A.trialEffect('timing');
  return e && e.before.n === 20 && e.after.n === 20 && e.after.count === 0;
})(), 'the order deaths were recorded in cannot move; the wall clock can');
ok('trial verdicts are ranked by how much moved, in either direction', (function () {
  A.clear();
  // timing barely moves; nerve collapses
  deaths(10, 'spike', 'endless');
  deaths(10, 'void', 'endless');
  deaths(3, 'spike', 'trial', 'timing');
  deaths(3, 'void', 'trial', 'nerve');
  deaths(9, 'spike', 'endless');
  deaths(1, 'void', 'endless');
  deaths(10, 'mover', 'endless');
  var es = A.trialEffects();
  return es.length === 2 && es[0].family === 'nerve' &&
         Math.abs(es[0].delta) > Math.abs(es[1].delta);
})());
/* ---- weighting a trial by the patterns you actually fail ---- */
function poolCount(pool, id) {
  var n = 0;
  for (var i = 0; i < pool.length; i++) if (pool[i].id === id) n++;
  return n;
}
function timingIds(n) {
  var pool = A.trialPatterns('timing'), ids = [], i;
  for (i = 0; i < pool.length && ids.length < n; i++) {
    if (ids.indexOf(pool[i].id) < 0) ids.push(pool[i].id);
  }
  return ids;
}
ok('with no history the pool has no opinion', (function () {
  A.clear();
  var pool = A.trialPatterns('timing'), seen = {};
  for (var i = 0; i < pool.length; i++) {
    if (seen[pool[i].id]) return false;
    seen[pool[i].id] = 1;
  }
  return pool.length > 0;
})(), 'a trial cannot weight what it has never seen you fail');
ok('a pattern you keep failing comes up more often', (function () {
  var ids = timingIds(2);
  A.clear();
  for (var i = 0; i < 30; i++) {
    A.record({ time: 20, cause: 'spike', mode: 'endless', context: { pat: ids[0] } });
  }
  var pool = A.trialPatterns('timing');
  return poolCount(pool, ids[0]) > poolCount(pool, ids[1]);
})());
ok('a pattern you have never failed is still in the pool', (function () {
  var ids = timingIds(2);
  A.clear();
  for (var i = 0; i < 30; i++) {
    A.record({ time: 20, cause: 'spike', mode: 'endless', context: { pat: ids[0] } });
  }
  var pool = A.trialPatterns('timing');
  return poolCount(pool, ids[1]) === 1;
})(), 'drilling only what you have already failed is how you get good at a list');
ok('no single pattern can take over a trial', (function () {
  var ids = timingIds(1);
  A.clear();
  for (var i = 0; i < 200; i++) {
    A.record({ time: 20, cause: 'spike', mode: 'endless', context: { pat: ids[0] } });
  }
  var pool = A.trialPatterns('timing');
  return poolCount(pool, ids[0]) === 4 &&
         poolCount(pool, ids[0]) / pool.length < 0.35;
})());
ok('weighting never smuggles in a pattern from another family', (function () {
  A.clear();
  // fail hard on a NERVE pattern, then ask for a TIMING trial
  var nerve = A.trialPatterns('nerve')[0].id;
  for (var i = 0; i < 40; i++) {
    A.record({ time: 20, cause: 'void', mode: 'endless', context: { pat: nerve } });
  }
  var pool = A.trialPatterns('timing');
  return poolCount(pool, nerve) === 0 && pool.length > 0;
})());
/* ---- practice mode ---- */
ok('every pattern is either static or time-driven, and nothing is both', (function () {
  var stat = PAT.staticList, i;
  for (i = 0; i < stat.length; i++) if (PAT.isDynamic(stat[i])) return false;
  var dyn = PAT.list.filter(function (p) { return PAT.isDynamic(p); });
  return stat.length + dyn.length === PAT.list.length && stat.length > 0 && dyn.length > 0;
})());
ok('the practice pool holds no moving geometry', (function () {
  for (var i = 0; i < PAT.staticList.length; i++) {
    var p = PAT.staticList[i];
    for (var j = 0; j < p.items.length; j++) {
      if (['mover', 'laser', 'piston', 'gate'].indexOf(p.items[j].t) >= 0) return false;
    }
  }
  return PAT.staticList.length >= 30;
})(), 'a time-driven pattern is a different problem at a different speed, and unproven there');
ok('the practice pool can still fill every tier', (function () {
  var byTier = {};
  for (var i = 0; i < PAT.staticList.length; i++) {
    byTier[PAT.staticList[i].tier] = (byTier[PAT.staticList[i].tier] || 0) + 1;
  }
  for (var t = 1; t <= 5; t++) if (!byTier[t]) return false;
  return true;
})());
ok('a practice death never enters the read', (function () {
  A.clear();
  for (var i = 0; i < 30; i++) {
    A.record({ time: 40, cause: 'spike', mode: 'practice', context: {} });
  }
  return A.history().length === 0 && A.read().kind === 'none' && A.tally().n === 0;
})(), 'a slower speed is a different problem; counting it would put an asterisk on the read');
ok('a trial pool is built only from proven patterns', (function () {
  var fams = ['timing', 'prediction', 'commitment', 'nerve'];
  for (var f = 0; f < fams.length; f++) {
    var pool = A.trialPatterns(fams[f]);
    if (pool.length < 4) return false;
    for (var i = 0; i < pool.length; i++) if (PAT.list.indexOf(pool[i]) < 0) return false;
  }
  return true;
})(), 'a Trial must never invent geometry — it is a different selection, not different rules');
ok('a trial pool actually matches its weakness', (function () {
  var pool = A.trialPatterns('nerve');
  var withHole = pool.filter(function (p) {
    return p.items.some(function (it) { return it.t === 'hole'; });
  });
  return withHole.length / pool.length >= 0.5;
})());
ok('every family maps to copy the UI can render', (function () {
  var seen = {};
  ['spike', 'block', 'bar', 'mover', 'gate', 'piston', 'laser', 'void'].forEach(function (c) {
    seen[A.familyOf(c)] = 1;
  });
  return Object.keys(seen).every(function (f) {
    var c = A.families[f];
    return c && c.name && c.line && c.fix;
  });
})());
A.clear();

console.log('\n  progression');
ok('levels need progressively more xp', (function () {
  for (var l = 1; l < 40; l++) if (OM.progress.needFor(l + 1) <= OM.progress.needFor(l)) return false;
  return true;
})());
ok('the curve ends where the rewards end', (function () {
  var last = 0;
  [OM.progress.cores, OM.progress.trails, OM.progress.deaths].forEach(function (g) {
    g.forEach(function (it) { last = Math.max(last, it.at); });
  });
  return last === OM.progress.maxLevel;
})(), 'levels past the last unlock buy nothing');
ok('xp bar fraction cannot exceed 1', (function () {
  // the old curve kept accumulating remainder past the cap, so the fill grew
  // without bound — 43x the bar width at twice the cap
  var huge = 50000000;
  var li = OM.progress.levelInfo();
  OM.progress.data.xp = huge;
  var at = OM.progress.levelInfo();
  OM.progress.data.xp = 0;
  return at.frac <= 1 && at.level === OM.progress.maxLevel && at.capped === true;
})());
ok('the cap is reachable in a plausible number of runs', (function () {
  var c = 0;
  for (var l = 1; l < OM.progress.maxLevel; l++) c += OM.progress.needFor(l);
  return c / 115 < 900;            // ~115 xp is a typical run
})());
ok('a run banks xp and a record', (function () {
  var before = OM.progress.data.xp;
  var res = OM.progress.commitRun({
    mode: 'endless', time: 42.5, cause: 'spike', nearMiss: 3, perfect: 1, flips: 20,
    world: P.WORLDS[0], ghost: null
  });
  return OM.progress.data.xp > before && res.record === true && OM.progress.data.best === 42.5;
})());
ok('practice banks its own record and nothing else', (function () {
  var d = OM.progress.data;
  var xp = d.xp, best = d.best, runs = d.runs, total = d.totalTime;
  var res = OM.progress.commitRun({
    mode: 'practice', time: 300, cause: 'spike', nearMiss: 9, perfect: 4, flips: 90,
    world: P.WORLDS[0], ghost: null
  });
  return res.xp === 0 && res.record === true && d.practice === 300 &&
         d.xp === xp && d.best === best && d.runs === runs && d.totalTime === total;
})(), 'xp is paid by the second, so a slower speed must not be the fastest way to level');
ok('a worse run does not overwrite the record', (function () {
  OM.progress.commitRun({
    mode: 'endless', time: 10, cause: 'spike', nearMiss: 0, perfect: 0, flips: 3,
    world: P.WORLDS[0], ghost: null
  });
  return OM.progress.data.best === 42.5;
})());
ok('achievements unlock exactly once', (function () {
  var n1 = OM.progress.data.achievements.length;
  OM.progress.commitRun({
    mode: 'endless', time: 31, cause: 'spike', nearMiss: 0, perfect: 0, flips: 1,
    world: P.WORLDS[0], ghost: null
  });
  var n2 = OM.progress.data.achievements.length;
  OM.progress.commitRun({
    mode: 'endless', time: 31, cause: 'spike', nearMiss: 0, perfect: 0, flips: 1,
    world: P.WORLDS[0], ghost: null
  });
  return n2 >= n1 && OM.progress.data.achievements.length === n2;
})());
ok('the core evolves with level', OM.progress.coreFor(1) === 'core' && OM.progress.coreFor(50) === 'singularity');
ok('storage failures never throw', (function () {
  var real = globalThis.localStorage;
  globalThis.localStorage = { getItem: function () { throw new Error('blocked'); },
                              setItem: function () { throw new Error('blocked'); },
                              removeItem: function () { throw new Error('blocked'); } };
  var okv = OM.store.get('x', 'fallback') === 'fallback' && OM.store.set('x', 1) === false;
  globalThis.localStorage = real;
  return okv;
})(), 'private browsing and blocked cookies must not break the game');

console.log('\n  ' + pass + ' passed, ' + fail + ' failed\n');
process.exit(fail ? 1 : 0);
