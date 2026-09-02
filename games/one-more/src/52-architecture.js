/* ONE MORE — the procedural architecture engine.
 *
 * The void needed something to be void OF. Depth planes of horizontal rules
 * gave the frame distance but nothing to measure that distance against, and a
 * player cannot feel small next to a line.
 *
 * So the background builds structures: rings, monoliths, arches, bridges,
 * wireframe spheres, stairways, fragments. None of them touch gameplay. They
 * exist to say how big the tunnel is by being much bigger than it, and to make
 * one stretch of black distinguishable from the next.
 *
 * Placement is stateless and derived, not stored. Each plane has slots at a
 * fixed spacing, and what stands in a slot is a hash of (seed, plane, slot) —
 * so there is nothing to allocate, nothing to prune, no memory that grows with
 * a long run, and the same seed builds the same skyline every time. That last
 * property is not decoration: a Daily has to be identical for everyone and a
 * retry has to be identical to the run it repeats, and an architecture that
 * drifted would quietly break both.
 *
 * Everything is drawn at a fraction of the alpha gameplay geometry uses. The
 * rule from the art direction holds hardest here, where it is easiest to break:
 * the environment may never compete with the thing that can kill you.
 */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys;
  var CEIL = P.CEIL, FLOOR = P.FLOOR;

  /* Integer hash. Three mixed inputs, because a structure has to be a function
     of its slot AND its plane AND the run — not of a counter that resets. */
  function hash(a, b, c) {
    var h = (a | 0) * 374761393 + (b | 0) * 668265263 + (c | 0) * 2147483647;
    h = (h ^ (h >>> 13)) * 1274126177;
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }

  /* ---- the vocabulary ----
     Each shape is drawn in its own translated frame, centred on the origin,
     sized in `s` pixels. They are outlines: a filled silhouette at this alpha
     turns into a grey smear, and an outline keeps its structure. */
  var SHAPES = {
    /* The signature. A ring seen near edge-on, which is the one shape in the
       set that reads as enormous and man-made at any size. */
    ring: function (g, s, r) {
      var squash = 0.25 + r * 0.5;
      g.beginPath(); g.ellipse(0, 0, s, s * squash, 0, 0, 6.2832); g.stroke();
      if (r > 0.5) {
        g.beginPath(); g.ellipse(0, 0, s * 0.72, s * squash * 0.72, 0, 0, 6.2832); g.stroke();
      }
    },
    monolith: function (g, s, r) {
      var w = s * (0.18 + r * 0.18);
      g.strokeRect(-w, -s, w * 2, s * 2);
      g.beginPath(); g.moveTo(-w, -s * (0.2 + r * 0.4)); g.lineTo(w, -s * (0.2 + r * 0.4)); g.stroke();
    },
    pillar: function (g, s, r) {
      var w = s * 0.09;
      g.strokeRect(-w, -s, w * 2, s * 2);
      g.strokeRect(-w * 2.2, -s - w * 1.4, w * 4.4, w * 1.4);
      g.strokeRect(-w * 2.2, s, w * 4.4, w * 1.4);
    },
    arch: function (g, s, r) {
      var w = s * (0.5 + r * 0.3), h = s;
      g.beginPath();
      g.moveTo(-w, h); g.lineTo(-w, 0);
      g.arc(0, 0, w, Math.PI, 0);
      g.lineTo(w, h);
      g.stroke();
    },
    bridge: function (g, s, r) {
      var w = s * 1.6;
      g.beginPath(); g.moveTo(-w, 0); g.lineTo(w, 0); g.stroke();
      var n = 4 + Math.round(r * 4);
      for (var i = 0; i <= n; i++) {
        var x = -w + (2 * w * i) / n;
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x, s * (0.3 + r * 0.5)); g.stroke();
      }
    },
    /* A wireframe sphere, latitudes only. It rhymes with the Nanogon without
       competing with it — same family of object, vastly different scale. */
    sphere: function (g, s, r) {
      g.beginPath(); g.arc(0, 0, s, 0, 6.2832); g.stroke();
      for (var i = 1; i <= 3; i++) {
        var yy = -s + (2 * s * i) / 4;
        var rr = Math.sqrt(Math.max(0, s * s - yy * yy));
        g.beginPath(); g.ellipse(0, yy, rr, rr * 0.22, 0, 0, 6.2832); g.stroke();
      }
    },
    stair: function (g, s, r) {
      var n = 5 + Math.round(r * 4), step = (s * 2) / n;
      g.beginPath();
      for (var i = 0; i < n; i++) {
        var x = -s + i * step, y = s - i * step;
        g.moveTo(x, y); g.lineTo(x + step, y);
        g.lineTo(x + step, y - step);
      }
      g.stroke();
    },
    frame: function (g, s, r) {
      for (var i = 0; i < 3; i++) {
        var k = 1 - i * 0.28;
        g.strokeRect(-s * k, -s * k, s * 2 * k, s * 2 * k);
      }
    },
    fragment: function (g, s, r) {
      var n = 3 + Math.round(r * 3);
      for (var i = 0; i < n; i++) {
        var a = hash(i, 7, 3) * 6.2832, L = s * (0.3 + hash(i, 9, 5) * 0.7);
        var ox = (hash(i, 11, 2) - 0.5) * s, oy = (hash(i, 13, 4) - 0.5) * s;
        g.beginPath();
        g.moveTo(ox, oy);
        g.lineTo(ox + Math.cos(a) * L, oy + Math.sin(a) * L);
        g.stroke();
      }
    }
  };

  /* Which shapes a world is built from. Origin is deliberately almost empty —
     the player has one thing to learn there and a skyline would be noise. The
     later worlds are not just fuller, they are built of different things:
     Collapse loses its intact forms, Nightmare keeps only the shapes that read
     as wrong. */
  var PALETTE = {
    origin:    { shapes: ['pillar'], density: 0.18, alpha: 0.5 },
    pulse:     { shapes: ['monolith', 'pillar', 'arch', 'ring'], density: 0.55, alpha: 0.85 },
    void:      { shapes: ['ring', 'sphere', 'monolith'], density: 0.32, alpha: 0.7 },
    collapse:  { shapes: ['fragment', 'bridge', 'frame', 'monolith', 'stair'], density: 0.7, alpha: 1 },
    nightmare: { shapes: ['fragment', 'stair', 'frame', 'ring', 'sphere'], density: 0.85, alpha: 1.1 }
  };

  /* Three planes. Rate is how fast a plane tracks the camera, so the far one
     barely moves and the near one nearly keeps up — which is the entire
     illusion. Spacing widens with distance so the far plane does not read as a
     picket fence. */
  var PLANES = [
    { rate: 0.05, spacing: 1500, scale: 1.00, alpha: 0.045, weight: 1.0 },
    { rate: 0.13, spacing: 1050, scale: 0.66, alpha: 0.062, weight: 1.0 },
    { rate: 0.26, spacing: 820,  scale: 0.42, alpha: 0.082, weight: 1.2 }
  ];

  OM.architecture = {
    shapes: SHAPES,
    planes: PLANES,
    palette: PALETTE,

    /* Draw everything visible. `seed` makes the skyline a property of the run,
       so a retry and a Daily rebuild it exactly. */
    draw: function (g, W, worldId, camX, t, seed, vis) {
      var pal = PALETTE[worldId];
      if (!pal) return;
      var q = (vis && vis.q) || OM.visual.q();
      if (!q.aura) return;                    // first thing to go on a weak device
      var atmos = vis ? vis.atmos : 0.5;
      var mid = (CEIL + FLOOR) / 2, band = FLOOR - CEIL;

      g.save();
      g.lineJoin = 'round';
      for (var p = 0; p < PLANES.length; p++) {
        var pl = PLANES[p];
        var shift = camX * pl.rate;
        var first = Math.floor((shift - pl.spacing) / pl.spacing);
        var last = Math.ceil((shift + W + pl.spacing) / pl.spacing);
        for (var slot = first; slot <= last; slot++) {
          var pick = hash(seed, p, slot);
          if (pick > pal.density) continue;
          var kinds = pal.shapes;
          var kind = kinds[Math.floor(hash(seed, p + 31, slot) * kinds.length) % kinds.length];
          var jitter = hash(seed, p + 61, slot);
          var x = slot * pl.spacing - shift + (jitter - 0.5) * pl.spacing * 0.6;
          if (x < -900 || x > W + 900) continue;

          /* Vertically centred on the tunnel and much taller than it, so the
             structures read as passing behind the world rather than sitting
             inside it. */
          var s = band * pl.scale * (0.5 + hash(seed, p + 97, slot) * 1.4);
          var y = mid + (hash(seed, p + 131, slot) - 0.5) * band * 0.55;
          var a = pl.alpha * pal.alpha * (0.45 + atmos * 0.55);

          g.save();
          g.translate(x, y);
          if (worldId === 'collapse' || worldId === 'nightmare') {
            g.rotate((hash(seed, p + 167, slot) - 0.5) * (worldId === 'nightmare' ? 0.9 : 0.35));
          }
          g.globalAlpha = a;
          g.lineWidth = pl.weight;
          g.strokeStyle = '#ffffff';
          SHAPES[kind](g, s, hash(seed, p + 199, slot));
          g.restore();
        }
      }
      g.restore();
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
