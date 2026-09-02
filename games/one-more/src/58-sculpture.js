/* ONE MORE — the run sculpture.
 *
 * Every run already records its own shape. The ghost is world-x, y and gravity
 * at 24Hz for the whole run — the thing that makes racing your record possible
 * — and nothing has ever looked at it as a shape rather than as a replay.
 *
 * So: wind the run into an object. Progress becomes angle, so a longer run is
 * more turns. Height rises with time. Radius is where you were in the tunnel,
 * which means the silhouette is a portrait of how you played: someone who hugs
 * one surface makes a narrow cone, someone who crosses constantly makes a wide
 * flared coil, and a run that started cautious and ended frantic opens out as
 * it rises. Flips are marked where they happened.
 *
 * It is built from the real path, not from summary statistics. A sculpture
 * derived from "47 flips, 12 near misses" would be a bar chart in fancy dress
 * and every run with the same totals would look identical. This one cannot
 * lie about a run because it IS the run.
 */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys;

  var MAX_PTS = 200;        // enough to describe a seven-minute run, cheap to draw
  var TURNS = 3.2;

  OM.sculpture = {
    /* ghost: { r, x0, dx[], y[], g[] } — the format the recorder already
       writes, so this costs nothing extra to store. */
    build: function (ghost) {
      if (!ghost || !ghost.y || ghost.y.length < 8) return null;
      var n = ghost.y.length;
      var step = Math.max(1, Math.floor(n / MAX_PTS));
      var pts = [], flips = [], last = ghost.g[0];
      var band = P.FLOOR - P.CEIL;
      for (var i = 0; i < n; i += step) {
        var u = i / (n - 1);
        var yn = (ghost.y[i] - P.CEIL) / band;          // 0 ceiling, 1 floor
        var ang = u * TURNS * 6.2832;
        var rad = 0.34 + (yn - 0.5) * 0.62;
        pts.push([Math.cos(ang) * rad, (u - 0.5) * 1.55, Math.sin(ang) * rad]);
        if (ghost.g[i] !== last) { flips.push(pts.length - 1); last = ghost.g[i]; }
      }
      return { pts: pts, flips: flips, n: n, secs: n / (ghost.r || 24) };
    },

    /* Orthographic, tilted, and rotating slowly — the same language as the
       character, because they are the same kind of object: a wire figure whose
       depth is carried by how bright its far side is. */
    draw: function (g, W, H, s, t) {
      if (!s) return;
      var cx = W / 2, cy = H / 2, scale = Math.min(W, H) * 0.44;
      var ay = t * 0.35, tilt = 0.42;
      var cyy = Math.cos(ay), syy = Math.sin(ay);
      var cxx = Math.cos(tilt), sxx = Math.sin(tilt);
      var pr = [], i, p;
      for (i = 0; i < s.pts.length; i++) {
        p = s.pts[i];
        var x1 = p[0] * cyy + p[2] * syy, z1 = -p[0] * syy + p[2] * cyy;
        var y2 = p[1] * cxx - z1 * sxx, z2 = p[1] * sxx + z1 * cxx;
        pr.push([cx + x1 * scale, cy + y2 * scale, z2]);
      }
      g.save();
      g.lineCap = 'round';
      g.lineJoin = 'round';
      g.strokeStyle = '#ffffff';
      g.fillStyle = '#ffffff';
      /* Depth buckets again: one path per bucket rather than per segment, so a
         two-hundred point figure costs four strokes. */
      for (var b = 0; b < 4; b++) {
        var lo = -1.2 + (2.4 * b) / 4, hi = -1.2 + (2.4 * (b + 1)) / 4;
        var depth = (b + 0.5) / 4;
        g.beginPath();
        var open = false;
        for (i = 1; i < pr.length; i++) {
          var mz = (pr[i - 1][2] + pr[i][2]) / 2;
          if (mz < lo || mz >= hi) { open = false; continue; }
          if (!open) { g.moveTo(pr[i - 1][0], pr[i - 1][1]); open = true; }
          g.lineTo(pr[i][0], pr[i][1]);
        }
        g.globalAlpha = 0.14 + depth * 0.66;
        g.lineWidth = 0.7 + depth * 1.5;
        g.stroke();
      }
      for (i = 0; i < s.flips.length; i++) {
        p = pr[s.flips[i]];
        if (!p || p[2] < -0.1) continue;
        g.globalAlpha = 0.35 + ((p[2] + 1.2) / 2.4) * 0.55;
        g.beginPath(); g.arc(p[0], p[1], 1.7, 0, 6.2832); g.fill();
      }
      g.restore();
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
