/* ONE MORE — obstacle pattern library.
   Hand-authored, tiered 1..5. Nothing here is random: randomness picks WHICH
   pattern and how much space follows it, never what a pattern contains. That is
   the whole difference between "hard" and "unfair".
   Every pattern in this file is proven survivable by tools/validate.js. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys;
  var CEIL = P.CEIL, FLOOR = P.FLOOR;

  /* item constructors ------------------------------------------------------ */
  function spike(side, dx, w, h) { return { t: 'spike', side: side, dx: dx, w: w, h: h }; }
  function block(side, dx, w, h) { return { t: 'block', side: side, dx: dx, w: w, h: h }; }
  function bar(dx, w, y0, y1) { return { t: 'bar', dx: dx, w: w, y0: y0, y1: y1 }; }
  function hole(side, dx, w) { return { t: 'hole', side: side, dx: dx, w: w }; }
  function mover(dx, w, h, cy, amp, rate, phase) {
    return { t: 'mover', dx: dx, w: w, h: h, cy: cy, amp: amp, rate: rate, phase: phase || 0 };
  }
  /* A laser covers ONE half of the tunnel and blinks on a slow, readable cycle.
     It deliberately does not span the full height: the player cannot choose when
     they arrive, so a full-height blocker would be a coin flip rather than a
     decision. Half height turns it into "the bottom is lit — be on top". */
  var LASER_H = Math.round((FLOOR - CEIL) * 0.56);
  function laser(side, dx, w, rate, duty, phase) {
    return { t: 'laser', side: side, dx: dx, w: w, rate: rate, duty: duty, phase: phase || 0, h: LASER_H };
  }
  function pat(id, tier, len, items) { return { id: id, tier: tier, len: len, items: items }; }

  /* A "needle" is the signature moment: floor and ceiling both close in at the
     same x, leaving only a window in the middle. The only way through is to be
     mid-flip exactly there. Every PERFECT SWITCH callout comes from one of these.
     Gates are deliberately NARROW: the player crosses the middle of the tunnel at
     maximum vertical speed, so the width of the gate — how long they must hold
     that band — costs far more timing slack than the height of the gap does. */
  function needle(dx, w, halfGap) {
    var mid = (CEIL + FLOOR) / 2;
    return [
      block('ceil', dx, w, (mid - halfGap) - CEIL),
      block('floor', dx, w, FLOOR - (mid + halfGap))
    ];
  }

  var L = [];

  /* ---- TIER 1 — teaches the rule ---- */
  L.push(pat('t1_floor', 1, 600, [spike('floor', 130, 190, 118)]));
  L.push(pat('t1_ceil', 1, 600, [spike('ceil', 130, 190, 118)]));
  L.push(pat('t1_pair', 1, 1020, [spike('floor', 110, 170, 112), spike('ceil', 620, 170, 112)]));
  L.push(pat('t1_hole', 1, 640, [hole('floor', 150, 210)]));
  L.push(pat('t1_block', 1, 620, [block('floor', 140, 230, 150)]));
  L.push(pat('t1_hole_ceil', 1, 640, [hole('ceil', 150, 210)]));

  /* ---- TIER 2 — rhythm ---- */
  L.push(pat('t2_zig', 2, 1180, [
    spike('floor', 100, 165, 115), spike('ceil', 440, 165, 115), spike('floor', 780, 165, 115)
  ]));
  L.push(pat('t2_bar', 2, 700, [bar(180, 190, CEIL + 150, FLOOR - 150)]));
  L.push(pat('t2_holes', 2, 1080, [hole('floor', 120, 220), hole('ceil', 560, 220)]));
  L.push(pat('t2_wide', 2, 780, [spike('floor', 120, 350, 125)]));
  L.push(pat('t2_pinch', 2, 900, [spike('floor', 110, 200, 120), spike('ceil', 420, 200, 120)]));
  L.push(pat('t2_step', 2, 900, [block('ceil', 110, 180, 150), block('floor', 430, 180, 200)]));
  L.push(pat('t2_mover', 2, 820, [mover(200, 120, 150, (CEIL + FLOOR) / 2, 130, 0.55, 0)]));
  L.push(pat('t2_bar_low', 2, 760, [bar(180, 170, CEIL + 250, FLOOR - 90)]));

  /* ---- TIER 3 — combination ---- */
  L.push(pat('t3_gauntlet', 3, 1500, [
    spike('floor', 90, 145, 115), spike('ceil', 460, 145, 115),
    spike('floor', 830, 145, 115), spike('ceil', 1200, 145, 115)
  ]));
  L.push(pat('t3_bar_zig', 3, 1120, [
    spike('floor', 90, 170, 118), bar(430, 170, CEIL + 160, FLOOR - 160), spike('ceil', 800, 170, 118)
  ]));
  L.push(pat('t3_hole_spike', 3, 1080, [hole('floor', 120, 400), spike('ceil', 560, 190, 120)]));
  L.push(pat('t3_laser', 3, 980, [laser('floor', 300, 90, 0.42, 0.5, 0)]));
  L.push(pat('t3_double_bar', 3, 1120, [
    bar(140, 170, CEIL + 140, FLOOR - 210), bar(520, 170, CEIL + 210, FLOOR - 140)
  ]));
  L.push(pat('t3_comb', 3, 1500, [
    spike('floor', 80, 115, 110), spike('ceil', 430, 115, 110),
    spike('floor', 780, 115, 110), spike('ceil', 1130, 115, 110)
  ]));
  L.push(pat('t3_mover_pair', 3, 1180, [
    mover(180, 110, 160, CEIL + 200, 110, 0.62, 0),
    mover(660, 110, 160, FLOOR - 200, 110, 0.62, Math.PI)
  ]));
  L.push(pat('t3_stagger_soft', 3, 1060, [spike('floor', 110, 200, 115), spike('ceil', 480, 200, 115)]));
  L.push(pat('t3_hole_bar', 3, 1120, [hole('floor', 110, 300), bar(600, 170, CEIL + 170, FLOOR - 170)]));

  /* ---- TIER 4 — precision ---- */
  L.push(pat('t4_needle_wide', 4, 1040, needle(400, 40, 215)));
  L.push(pat('t4_needle_tight', 4, 1060, needle(400, 40, 200)));
  L.push(pat('t4_storm', 4, 1840, [
    spike('floor', 80, 130, 118), spike('ceil', 420, 130, 118), spike('floor', 760, 130, 118),
    spike('ceil', 1100, 130, 118), spike('floor', 1440, 130, 118)
  ]));
  L.push(pat('t4_stagger', 4, 1040, [spike('floor', 110, 220, 118), spike('ceil', 355, 220, 118)]));
  L.push(pat('t4_laser_zig', 4, 1380, [
    spike('floor', 100, 160, 118), laser('ceil', 520, 90, 0.42, 0.5, 0.5), spike('ceil', 980, 160, 118)
  ]));
  L.push(pat('t4_mover_gate', 4, 1120, [
    mover(240, 130, 210, (CEIL + FLOOR) / 2, 150, 0.72, 0), spike('floor', 760, 180, 120)
  ]));
  L.push(pat('t4_hole_run', 4, 1300, [
    hole('floor', 100, 520), spike('ceil', 300, 150, 105), hole('ceil', 780, 240)
  ]));
  L.push(pat('t4_needle_after', 4, 2000, [spike('floor', 90, 170, 115)].concat(needle(1240, 40, 210))));
  L.push(pat('t4_bar_comb', 4, 1360, [
    bar(120, 160, CEIL + 130, FLOOR - 230), spike('floor', 480, 150, 118),
    bar(800, 160, CEIL + 230, FLOOR - 130)
  ]));

  /* ---- TIER 5 — the part people post clips of ---- */
  L.push(pat('t5_needle_pair', 5, 2440, needle(380, 44, 185).concat(needle(1780, 44, 185))));
  L.push(pat('t5_chaos', 5, 2600, [
    spike('floor', 70, 100, 110), spike('ceil', 430, 100, 110), spike('floor', 790, 100, 110),
    spike('ceil', 1150, 100, 110), spike('floor', 1510, 100, 110), spike('ceil', 1870, 100, 110)
  ]));
  L.push(pat('t5_laser_needle', 5, 1680, [laser('floor', 240, 90, 0.42, 0.5, 0)].concat(needle(1040, 44, 185))));
  L.push(pat('t5_mover_storm', 5, 1620, [
    mover(180, 110, 190, CEIL + 190, 130, 0.8, 0),
    mover(640, 110, 190, FLOOR - 190, 130, 0.8, Math.PI * 0.5),
    mover(1100, 110, 190, (CEIL + FLOOR) / 2, 170, 0.8, Math.PI)
  ]));
  /* Ride the ceiling over the first gap, drop onto the island to duck the
     ceiling spike, then get back up before the floor runs out again. */
  /* The floor is simply gone, and the ceiling you were riding has a tooth in it.
     Duck under it and climb back out before the drop takes you. */
  L.push(pat('t5_void_dip', 5, 1500, [
    hole('floor', 90, 520), spike('ceil', 300, 90, 70)
  ]));
  L.push(pat('t5_gauntlet_bars', 5, 1720, [
    bar(100, 150, CEIL + 120, FLOOR - 240), spike('floor', 420, 150, 118),
    bar(720, 150, CEIL + 240, FLOOR - 120), spike('ceil', 1040, 150, 118),
    bar(1340, 150, CEIL + 180, FLOOR - 180)
  ]));

  /* ---- collision geometry -------------------------------------------------
     Everything reduces to axis-aligned rects. Spikes get a generous inset so a
     death always looks like a death — nothing is ever killed by a pixel of a
     tooth it visibly cleared. */
  var SPIKE_IN_X = 6, SPIKE_IN_Y = 10;

  function rectsOf(o, t, out) {
    out = out || [];
    switch (o.t) {
      case 'spike':
        if (o.side === 'floor') out.push({ x: o.x + SPIKE_IN_X, y: FLOOR - o.h + SPIKE_IN_Y, w: o.w - SPIKE_IN_X * 2, h: o.h - SPIKE_IN_Y, o: o });
        else out.push({ x: o.x + SPIKE_IN_X, y: CEIL, w: o.w - SPIKE_IN_X * 2, h: o.h - SPIKE_IN_Y, o: o });
        break;
      case 'block':
        if (o.side === 'floor') out.push({ x: o.x, y: FLOOR - o.h, w: o.w, h: o.h, o: o });
        else out.push({ x: o.x, y: CEIL, w: o.w, h: o.h, o: o });
        break;
      case 'bar':
        out.push({ x: o.x, y: o.y0, w: o.w, h: o.y1 - o.y0, o: o });
        break;
      case 'mover':
        out.push({ x: o.x, y: moverY(o, t) - o.h / 2, w: o.w, h: o.h, o: o });
        break;
      case 'laser':
        if (laserOn(o, t)) {
          out.push({ x: o.x, y: o.side === 'ceil' ? CEIL : FLOOR - o.h, w: o.w, h: o.h, o: o });
        }
        break;
      // 'hole' has no solid geometry — it removes a surface instead.
    }
    return out;
  }

  function moverY(o, t) {
    var y = o.cy + Math.sin(o.phase + t * o.rate * Math.PI * 2) * o.amp;
    var half = o.h / 2;
    return Math.max(CEIL + half, Math.min(FLOOR - half, y));
  }
  function laserPhase(o, t) { return (o.phase + t * o.rate) % 1; }
  function laserOn(o, t) { var p = laserPhase(o, t); return p >= 0 && p < o.duty; }

  OM.patterns = {
    list: L,
    byTier: (function () {
      var m = { 1: [], 2: [], 3: [], 4: [], 5: [] };
      for (var i = 0; i < L.length; i++) m[L[i].tier].push(L[i]);
      return m;
    })(),
    rectsOf: rectsOf,
    moverY: moverY,
    laserOn: laserOn,
    laserPhase: laserPhase,
    needle: needle
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
