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
