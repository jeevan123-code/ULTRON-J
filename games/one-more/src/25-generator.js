/* ONE MORE — procedural world generator.
   Randomness chooses which authored pattern comes next and how much room
   follows it. It never invents geometry. Seeded by the daily key for the Daily
   Challenge, so every player in the world runs the identical layout. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys, PAT = OM.patterns;

  OM.Generator = function (rng, opts) {
    opts = opts || {};
    var self = {
      obstacles: [],   // absolute-x, sorted by x
      holes: [],       // absolute-x, sorted by x
      cursor: opts.startX == null ? 900 : opts.startX,  // calm opening runway
      recent: [],
      spawned: 0
    };

    function place(p, x0) {
      for (var i = 0; i < p.items.length; i++) {
        var it = p.items[i];
        var o = {};
        for (var k in it) if (Object.prototype.hasOwnProperty.call(it, k)) o[k] = it[k];
        o.x = x0 + it.dx;
        o.pat = p.id;
        if (o.t === 'hole') self.holes.push(o); else self.obstacles.push(o);
      }
      self.spawned++;
    }

    function pickTier(weights) {
      var total = 0, i;
      for (i = 0; i < 5; i++) total += weights[i];
      if (total <= 0) return 1;
      var r = rng.next() * total, acc = 0;
      for (i = 0; i < 5; i++) { acc += weights[i]; if (r < acc) return i + 1; }
      return 1;
    }

    function pickPattern(tier) {
      var pool = PAT.byTier[tier];
      if (!pool || !pool.length) pool = PAT.byTier[1];
      // Up to 6 tries to avoid something we just showed — repetition is what
      // makes a procedural runner feel cheap.
      for (var a = 0; a < 6; a++) {
        var p = pool[Math.floor(rng.next() * pool.length)];
        if (self.recent.indexOf(p.id) < 0) return p;
      }
      return pool[Math.floor(rng.next() * pool.length)];
    }

    /* Fill the world out to `untilX`. `t` is the run time used by the director,
       `spacingMul` lets mutations (RUSH) squeeze the breathing room. */
    self.ensure = function (untilX, t, spacingMul) {
      var guard = 0;
      while (self.cursor < untilX && guard++ < 64) {
        var dir = P.directorAt(t);
        var tier = pickTier(dir.weights);
        var p = pickPattern(tier);
        place(p, self.cursor);
        self.recent.push(p.id);
        if (self.recent.length > 3) self.recent.shift();

        // Rest proportional to what just happened: harder patterns get a beat
        // of silence after them so the run breathes instead of grinding.
        var rest = (P.TRANSIT_X * 0.62 + p.tier * 34) * dir.spacing * (spacingMul || 1);
        rest *= rng.range(0.9, 1.22);
        self.cursor += p.len + rest;
      }
    };

    /* Drop everything behind the camera. Called every frame; keeps a long run
       at a flat memory profile. */
    self.prune = function (x) {
      var i = 0;
      while (i < self.obstacles.length && self.obstacles[i].x + (self.obstacles[i].w || 0) < x) i++;
      if (i) self.obstacles.splice(0, i);
      i = 0;
      while (i < self.holes.length && self.holes[i].x + self.holes[i].w < x) i++;
      if (i) self.holes.splice(0, i);
    };

    return self;
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
