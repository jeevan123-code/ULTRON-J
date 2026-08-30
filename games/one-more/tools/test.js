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
ok('schedule is deterministic per seed', (function () {
  var s1 = JSON.stringify(OM.mutations.schedule(OM.rng(42)).map(function (s) { return [s.at, s.m.id]; }));
  var s2 = JSON.stringify(OM.mutations.schedule(OM.rng(42)).map(function (s) { return [s.at, s.m.id]; }));
  return s1 === s2;
})());
ok('no mutation touches gravity', OM.mutations.list.every(function (m) {
  return m.gravity === undefined && m.gmul === undefined;
}), 'a gravity mutation would void the fairness proof for every pattern');
ok('nothing fires in the first 15 seconds', OM.mutations.schedule(OM.rng(9))[0].at >= 15);
ok('the same mutation never repeats back to back', (function () {
  for (var seed = 0; seed < 40; seed++) {
    var s = OM.mutations.schedule(OM.rng(seed));
    for (var i = 1; i < s.length; i++) if (s[i].m.id === s[i - 1].m.id) return false;
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

console.log('\n  progression');
ok('levels need progressively more xp', (function () {
  for (var l = 1; l < 40; l++) if (OM.progress.needFor(l + 1) <= OM.progress.needFor(l)) return false;
  return true;
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
