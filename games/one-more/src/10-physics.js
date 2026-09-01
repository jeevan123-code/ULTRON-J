/* ONE MORE — physics + difficulty director.
   Pure functions and constants only: no canvas, no DOM. This file is loaded by
   the browser AND by tools/validate.js + tools/test.js under node, so the
   fairness validator proves things about the exact code that ships. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var clamp = OM.math.clamp;

  var P = OM.phys = {
    /* Logical space. The canvas letterboxes to this; H is fixed, W varies with
       the device aspect so phones and desktops see the same vertical challenge. */
    H: 720,
    CEIL: 96,          // inner surface of the ceiling
    FLOOR: 672,        // inner surface of the floor
    R: 16,             // collision radius (visual radius is slightly larger — forgiving)
    R_VIS: 18,

    BASE_SPEED: 430,   // px/s at t=0
    BASE_G: 3300,      // px/s^2 at BASE_SPEED

    PLAYER_X_FRAC: 0.27,
    VOID_DEATH: 260,   // px past a surface line before a fall through a hole kills

    NEAR_MISS_DIST: 15,   // px of clearance that counts as a near miss
    PERFECT_WINDOW: 0.34  // s after a flip during which a near miss reads as PERFECT
  };

  P.TUNNEL = P.FLOOR - P.CEIL;                 // 576
  /* Horizontal distance covered by one full surface-to-surface flip. Because
     g scales with speed^2 this is constant at every speed — the single most
     important decision in the whole game: every hand-authored pattern stays
     exactly as fair at 900px/s as it was at 430px/s. */
  P.TRANSIT_H = P.TUNNEL - 2 * P.R;            // 544
  P.TRANSIT_T = Math.sqrt(2 * P.TRANSIT_H / P.BASE_G);
  P.TRANSIT_X = P.TRANSIT_T * P.BASE_SPEED;    // ~247px

  /* Speed curve: fast early ramp so the first 20s already feels alive, then a
     slow linear creep that never stops. Reaches ~1000px/s around 5 minutes. */
  P.speedAt = function (t) {
    var ramp = 320 * (1 - Math.exp(-t / 42));
    return P.BASE_SPEED + ramp + Math.min(t, 400) * 0.62;
  };

  /* Practice runs at one fixed speed with no ramp. It is a lower speed than the
     game ever starts at, but not a lower difficulty setting for the game: it is
     a separate mode with its own records and no XP, and its deaths are kept out
     of the read entirely, so nothing you learn here is priced into what the
     game tells you about how you play.
     335 rather than a round fraction because that is the speed the difference
     between slow and full was actually measured at. */
  P.PRACTICE_SPEED = 335;

  P.gravityFor = function (speed, mult) {
    var s = speed / P.BASE_SPEED;
    return P.BASE_G * s * s * (mult == null ? 1 : mult);
  };

  /* ---------- difficulty director ----------
     Returns the shape of the world at time t: which pattern tiers may spawn,
     how much breathing room between them, and how far ahead obstacles read. */
  var TIERS = [
    // [untilSeconds, weights per tier 1..5, spacing multiplier]
    [14, [1, 0, 0, 0, 0], 1.75],
    [34, [3, 1, 0, 0, 0], 1.35],
    [62, [3, 4, 1, 0, 0], 1.15],
    [96, [1, 4, 3, 1, 0], 1.02],
    [140, [0, 3, 4, 2, 1], 0.94],
    [200, [0, 1, 4, 4, 2], 0.88],
    [Infinity, [0, 0, 3, 4, 4], 0.82]
  ];

  P.directorAt = function (t) {
    for (var i = 0; i < TIERS.length; i++) {
      if (t < TIERS[i][0]) return { weights: TIERS[i][1], spacing: TIERS[i][2], band: i };
    }
    var last = TIERS[TIERS.length - 1];
    return { weights: last[1], spacing: last[2], band: TIERS.length - 1 };
  };

  /* ---------- worlds ----------
     Not menu choices — you arrive by surviving. */
  P.WORLDS = [
    { at: 0, id: 'origin', name: 'ORIGIN', line: 'Clean geometry. Learn the rule.' },
    { at: 48, id: 'pulse', name: 'PULSE', line: 'The world starts breathing.' },
    { at: 108, id: 'void', name: 'VOID', line: 'Most of it stops being visible.' },
    { at: 168, id: 'collapse', name: 'COLLAPSE', line: 'Reality is no longer stable.' },
    { at: 240, id: 'nightmare', name: 'NIGHTMARE', line: 'No warnings from here.' }
  ];
  P.worldAt = function (t) {
    var w = P.WORLDS[0];
    for (var i = 0; i < P.WORLDS.length; i++) if (t >= P.WORLDS[i].at) w = P.WORLDS[i];
    return w;
  };

  /* Corruption 0..1 — drives UI instability, visual noise and audio bed.
     Starts at 90s so a normal run never sees it; long runs feel dangerous. */
  P.corruptionAt = function (t) {
    return clamp((t - 90) / 150, 0, 1);
  };

  /* ---------- surface queries ----------
     `holes` is a sorted array of {x, w, side}. A surface simply stops existing
     across a hole, so the player falls out of the world instead of being killed
     by an invisible wall. */
  function hasSurface(holes, x, side) {
    for (var i = 0; i < holes.length; i++) {
      var h = holes[i];
      if (h.side === side && x > h.x && x < h.x + h.w) return false;
    }
    return true;
  }
  P.hasSurface = hasSurface;

  /* ---------- integration ----------
     Fixed sub-stepping keeps the arc identical regardless of frame rate, which
     matters both for ghost replays and for the validator's guarantees.
     st: {y, vy, grav(+1 down/-1 up), grounded}
     Returns 'void' if the player has fallen out of the world. */
  P.stepPlayer = function (st, dt, g, x, holes) {
    st.vy += st.grav * g * dt;
    st.y += st.vy * dt;
    st.grounded = false;
    if (st.grav > 0) {
      var f = P.FLOOR - P.R;
      if (st.y >= f) {
        if (hasSurface(holes, x, 'floor')) { st.y = f; st.vy = 0; st.grounded = true; }
        else if (st.y > P.FLOOR + P.VOID_DEATH) return 'void';
      }
    } else {
      var c = P.CEIL + P.R;
      if (st.y <= c) {
        if (hasSurface(holes, x, 'ceil')) { st.y = c; st.vy = 0; st.grounded = true; }
        else if (st.y < P.CEIL - P.VOID_DEATH) return 'void';
      }
    }
    return null;
  };

  /* Squared distance from the player circle to an axis-aligned rect.
     0 means overlap. Used for both collision and near-miss scoring. */
  P.circleRectDist2 = function (cx, cy, r, rx, ry, rw, rh) {
    var dx = cx < rx ? rx - cx : (cx > rx + rw ? cx - (rx + rw) : 0);
    var dy = cy < ry ? ry - cy : (cy > ry + rh ? cy - (ry + rh) : 0);
    return dx * dx + dy * dy;
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
