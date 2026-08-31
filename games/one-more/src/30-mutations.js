/* ONE MORE — mutations. Every ten to twenty seconds the game changes one rule.
 *
 * HARD CONSTRAINT: a mutation may change how fast the world moves, how much of
 * it you can see, or which way is up. It may NEVER change the shape of the flip
 * arc. Every pattern in the library is proven survivable against one specific
 * arc (tools/validate.js); a mutation that scaled gravity would silently void
 * that proof and start killing people in places the game promised were fair.
 *
 * Pure speed changes are safe for free: gravity is derived from speed as
 * g = G*(v/V)^2, so the horizontal span of a flip is identical at any speed.
 * That is why SURGE and DRAG exist and why HEAVY and FLOAT do not.
 */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});

  /* `cls` is what makes stacking safe. Two mutations may run at once only if
     they belong to different classes — so the game can be fast AND dense, or
     mirrored AND silent, but never dark AND phased AND strobing at the same
     time. The fairness proof says nothing about whether you can SEE an
     obstacle; stacking two visibility mutations would make a proven-fair
     pattern unplayable without any of the tooling noticing. */
  var M = [
    { id: 'surge',   name: 'SURGE',   line: 'Everything accelerates.',   speed: 1.22, weight: 3, cls: 'pace' },
    { id: 'drag',    name: 'DRAG',    line: 'The world thickens.',       speed: 0.84, weight: 2, cls: 'pace' },
    { id: 'rush',    name: 'RUSH',    line: 'No more room to breathe.',  spacing: 0.66, weight: 3, cls: 'density' },
    { id: 'mirror',  name: 'MIRROR',  line: 'Up is down.',               mirror: true, weight: 3, cls: 'frame' },
    { id: 'dark',    name: 'DARK',    line: 'Only what is close.',       vision: 330, weight: 2, cls: 'vision' },
    { id: 'phase',   name: 'PHASE',   line: 'It arrives late.',          fade: true, weight: 2, cls: 'vision' },
    { id: 'drift',   name: 'DRIFT',   line: 'The frame is loose.',       drift: 0.045, weight: 2, cls: 'frame' },
    { id: 'strobe',  name: 'STROBE',  line: 'Intermittent reality.',     strobe: true, weight: 1, cls: 'vision' },
    { id: 'silence', name: 'SILENCE', line: 'No numbers.',               silence: true, weight: 2, cls: 'ui' }
  ];
  var OVERLAY_FROM = 90;   // seconds before a second mutation may run at once

  var BY_ID = {};
  for (var i = 0; i < M.length; i++) BY_ID[M[i].id] = M[i];

  /* The schedule is generated up front from the run's RNG, so a Daily Challenge
     hands every player in the world the same mutations at the same instants.

     Two tracks. The PRIMARY track is the original one-at-a-time sequence and is
     untouched, so the first ninety seconds play exactly as they were tuned. The
     OVERLAY track starts at 90s and can run a second mutation alongside it,
     always from a different class. That puts real compounding pressure into the
     late game, which until now got harder only by going faster. */
  function schedule(rng, count) {
    var primary = primaryTrack(rng, count || 40);
    var merged = primary.concat(overlayTrack(rng, primary));
    merged.sort(function (a, b) { return a.at - b.at; });
    return merged;
  }

  function primaryTrack(rng, count) {
    var out = [], t = 20 + rng.range(0, 6), last = null;
    for (var n = 0; n < count; n++) {
      var pick = weighted(rng, last, null);
      var dur = rng.range(9, 13.5);
      out.push({ at: t, until: t + dur, m: pick, track: 'primary' });
      last = pick.id;
      t += dur + rng.range(7, 15) * Math.max(0.45, 1 - n * 0.045); // they crowd in later
    }
    return out;
  }

  function overlayTrack(rng, primary) {
    var out = [], t = OVERLAY_FROM + rng.range(0, 14);
    for (var n = 0; n < 24; n++) {
      var dur = rng.range(6.5, 10.5);
      // never share a class with whatever the primary track is running here
      var banned = {};
      for (var i = 0; i < primary.length; i++) {
        var p = primary[i];
        if (p.until <= t || p.at >= t + dur) continue;
        banned[p.m.cls] = 1;
      }
      var pick = weighted(rng, null, banned);
      if (pick) out.push({ at: t, until: t + dur, m: pick, track: 'overlay' });
      t += dur + rng.range(16, 30);
    }
    return out;
  }

  function weighted(rng, excludeId, bannedClasses) {
    var pool = [], i, j;
    for (i = 0; i < M.length; i++) {
      if (M[i].id === excludeId) continue;
      if (bannedClasses && bannedClasses[M[i].cls]) continue;
      for (j = 0; j < M[i].weight; j++) pool.push(M[i]);
    }
    if (!pool.length) return null;
    return pool[Math.floor(rng.next() * pool.length)];
  }

  /* Collapse the schedule into the modifier set active at time t. */
  function activeAt(sched, t) {
    var mods = { speed: 1, spacing: 1, mirror: false, vision: 0, fade: false,
                 drift: 0, strobe: false, silence: false, list: [] };
    for (var i = 0; i < sched.length; i++) {
      var s = sched[i];
      if (t < s.at) break;
      if (t >= s.until) continue;
      var m = s.m;
      if (m.speed) mods.speed *= m.speed;
      if (m.spacing) mods.spacing *= m.spacing;
      if (m.mirror) mods.mirror = true;
      if (m.vision) mods.vision = mods.vision ? Math.min(mods.vision, m.vision) : m.vision;
      if (m.fade) mods.fade = true;
      if (m.drift) mods.drift += m.drift;
      if (m.strobe) mods.strobe = true;
      if (m.silence) mods.silence = true;
      mods.list.push(s);
    }
    return mods;
  }

  OM.mutations = { list: M, byId: BY_ID, schedule: schedule, activeAt: activeAt,
                   overlayFrom: OVERLAY_FROM };
})(typeof globalThis !== 'undefined' ? globalThis : this);
