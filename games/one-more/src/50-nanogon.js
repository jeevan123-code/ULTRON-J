/* ONE MORE — the Nanogon.
   Drawn entirely from geometry: no sprites, no atlas, no resolution to be wrong
   at. Nine sides, one bright core, and six evolutions that arrive with your
   level. Everything is white on black; the only expressive channels are size,
   brightness, break-up and motion, which is exactly the constraint that makes
   it readable at thumbnail size.

   It is built in layers, drawn back to front:

     aura        a soft field, only when there is something to feel
     glow ring   the shell bleeding light outwards
     body        the nonagon, weighted towards the direction of travel
     rim         a bright arc on the leading edge, earned by speed
     evolution   whatever this level has done to the shell
     motes       energy shed into orbit
     core        a gradient, not a disc
     corruption  the shell tearing on very long runs

   The layering is the point. One outline and one flat circle reads as a
   wireframe; the same silhouette with falloff, direction and a hot centre
   reads as an object with light inside it, at the same cost to within a few
   tenths of a millisecond.

   Nothing here may grow the BODY beyond the radius it is handed. Collision
   uses R=16 against art at R_VIS=18, and that gap is the promise that a death
   always looks like a death. Aura, glow and motes are free to exceed it —
   they are light, not matter — but the shell is not. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var SIDES = 9;
  var VIS = OM.visual, T = VIS.tok;
  var ink = VIS.ink;

  /* Gradients are expensive to build and free to reuse, and every one of them
     is centred on the origin because the character is always drawn translated.
     That makes them cacheable on the context that owns them — there is more
     than one canvas in this game, and a gradient belongs to exactly one. */
  function radial(g, r, stops) {
    var cache = g.__omGrad || (g.__omGrad = {});
    var key = stops.key + '|' + Math.round(r);
    var hit = cache[key];
    if (hit) return hit;
    var grd = g.createRadialGradient(0, 0, 0, 0, 0, Math.max(0.01, r));
    for (var i = 0; i < stops.list.length; i++) grd.addColorStop(stops.list[i][0], stops.list[i][1]);
    cache[key] = grd;
    return grd;
  }
  /* Tight. A first pass ran the falloff out to twice the core radius and the
     character turned into a lamp: every mood read as "bright ball" because the
     bloom swallowed the shell and the size differences with it. The core is a
     precise hot point with a short skirt; the aura is what carries reach. */
  var CORE_STOPS = { key: 'core', list: [
    [0, 'rgba(255,255,255,1)'], [0.30, 'rgba(255,255,255,0.92)'],
    [0.58, 'rgba(255,255,255,0.34)'], [1, 'rgba(255,255,255,0)'] ] };
  var AURA_STOPS = { key: 'aura', list: [
    [0, 'rgba(255,255,255,0.55)'], [0.35, 'rgba(255,255,255,0.18)'],
    [0.7, 'rgba(255,255,255,0.05)'], [1, 'rgba(255,255,255,0)'] ] };

  function poly(g, cx, cy, r, rot, jitter, rng) {
    g.beginPath();
    for (var i = 0; i <= SIDES; i++) {
      var a = rot + (i / SIDES) * Math.PI * 2;
      var rr = r + (jitter ? (Math.sin(i * 12.9898 + rng) * 43758.5453 % 1) * jitter : 0);
      var x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
      if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
    }
    g.closePath();
  }

  /* ---- L3 the body.
     One stroke weight all the way round reads as a wireframe. Weighting the
     edges that face the direction of travel reads as an object with a front,
     and costs one extra partial stroke rather than a second full one. */
  function body(g, r, downAngle) {
    g.lineWidth = T.bodyWeight;
    poly(g, 0, 0, r, 0);
    g.stroke();
    var i0 = Math.round((downAngle / (Math.PI * 2)) * SIDES) - 2;
    g.lineWidth = T.bodyWeightLead;
    polyRun(g, r, i0, 4);
    g.stroke();
  }

  /* A run of consecutive edges, for weighting one side of the silhouette
     without drawing the whole shape twice at full weight. */
  function polyRun(g, r, fromIdx, count) {
    g.beginPath();
    for (var i = 0; i <= count; i++) {
      var a = ((fromIdx + i) / SIDES) * Math.PI * 2;
      var x = Math.cos(a) * r, y = Math.sin(a) * r;
      if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
    }
  }

  /* Draws one arc-segment ring with gaps — the shared language of the later
     evolutions, where the shell progressively stops being a solid object. */
  function brokenRing(g, cx, cy, r, rot, segs, gapFrac) {
    var span = (Math.PI * 2) / segs;
    for (var i = 0; i < segs; i++) {
      var a0 = rot + i * span, a1 = a0 + span * (1 - gapFrac);
      g.beginPath();
      g.arc(cx, cy, r, a0, a1);
      g.stroke();
    }
  }

  /* ---------- moods ----------
     A table, not a chain of ifs. Every state answers the same questions, so a
     new one cannot accidentally forget to say what its core does, and two of
     them cannot quietly disagree about what "alert" means.

       core     core radius, as a multiple of the token
       glowMin  a floor under the glow this state insists on
       tremble  positional noise, px
       pulse    how fast the whole shell breathes
       aura     aura multiplier */
  var MOODS = {
    neutral:  { core: 1.00, coreAlpha: 0.80, glowMin: 0,   tremble: 0,   pulse: 3.4, aura: 1.0 },
    focused:  { core: 0.66, coreAlpha: 1.00, glowMin: 0,   tremble: 0,   pulse: 4.6, aura: 0.8 },
    excited:  { core: 1.08, coreAlpha: 1.00, glowMin: 0.5, tremble: 0,   pulse: 9.0, aura: 1.2 },
    alert:    { core: 0.92, coreAlpha: 0.95, glowMin: 0.3, tremble: 0.5, pulse: 22,  aura: 1.1 },
    near:     { core: 1.45, coreAlpha: 1.00, glowMin: 0.9, tremble: 1.6, pulse: 3.4, aura: 1.7 },
    success:  { core: 1.30, coreAlpha: 1.00, glowMin: 1.0, tremble: 0,   pulse: 3.0, aura: 2.0 },
    hurt:     { core: 0.55, coreAlpha: 0.55, glowMin: 0,   tremble: 3.0, pulse: 3.4, aura: 0.5 }
  };

  var N = OM.nanogon = {
    /* st: {x,y,r,rot,grav,evo,mood,t,glow,corrupt,alpha,scale,sx,sy,speed} */
    draw: function (g, st) {
      var r = st.r * (st.scale == null ? 1 : st.scale);
      var evo = st.evo || 'core';
      var m = MOODS[st.mood] || MOODS.neutral;
      var t = st.t || 0;
      var alpha = st.alpha == null ? 1 : st.alpha;
      var corrupt = st.corrupt || 0;
      var q = st.q || VIS.q();
      var speed = st.speed == null ? 0 : st.speed;

      /* A flash is not a mood. It is a single event the shell cannot produce on
         its own — a perfect switch, a graze — and it decays in under a third of
         a second, so it rides on top of whatever state the character is in
         rather than replacing it. */
      var flash = st.flash || 0;
      var glow = Math.max(st.glow || 0, m.glowMin);
      var coreScale = T.coreScale * (m.core + flash * 0.55);
      var tremble = m.tremble;
      var pulse = 1 + Math.sin(t * m.pulse) * 0.035;

      g.save();
      g.globalAlpha = alpha;
      g.translate(st.x + (tremble ? (Math.random() - 0.5) * tremble : 0),
                  st.y + (tremble ? (Math.random() - 0.5) * tremble : 0));
      /* Squash and stretch in world axes, before the spin. Rotating inside a
         non-uniform scale shears the shape slightly, which is exactly what a
         compressed object mid-tumble should look like. */
      if (st.sx || st.sy) g.scale(st.sx || 1, st.sy || 1);
      g.rotate(st.rot || 0);

      /* Which way is "down" for this character, in its own rotated frame. The
         silhouette is weighted towards it and the rim light sits on it, which
         is what stops a spinning nonagon reading as a spinning nonagon and
         starts it reading as an object being pulled somewhere. */
      var down = (st.grav > 0 ? Math.PI / 2 : -Math.PI / 2) - (st.rot || 0);

      // ---- L0 flash: a hard ring leaving the shell, only in the moment
      if (flash > 0.03) {
        g.globalAlpha = alpha * flash * 0.55;
        g.strokeStyle = '#ffffff';
        g.lineWidth = 1 + flash * 2;
        poly(g, 0, 0, r * (1.15 + (1 - flash) * 1.5), 0);
        g.stroke();
        g.globalAlpha = alpha;
      }

      // ---- L1 aura: a field, not an outline. Only when there is something to feel.
      if (q.aura && glow > 0.02) {
        var aR = r * T.auraScale;
        g.globalAlpha = alpha * T.auraAlpha * Math.min(1, glow) * m.aura * q.aura;
        g.fillStyle = radial(g, aR, AURA_STOPS);
        g.beginPath(); g.arc(0, 0, aR, 0, 6.2832); g.fill();
        g.globalAlpha = alpha;
      }

      // ---- L2 glow ring: the shell bleeding outwards. A wide soft stroke rather
      // than a shadow blur, which is the single most expensive thing a 2D canvas does.
      if (glow > 0.01) {
        g.strokeStyle = ink(T.glowRingAlpha * glow);
        g.lineWidth = 9 + glow * 8;
        poly(g, 0, 0, r * 1.06 * pulse, 0);
        g.stroke();
      }

      g.lineJoin = 'round';
      g.lineCap = 'round';
      g.strokeStyle = '#ffffff';
      g.fillStyle = '#ffffff';

      if (evo === 'core') {
        body(g, r * pulse, down);

      } else if (evo === 'pulse') {
        body(g, r * pulse, down);
        var pr = r * (1.25 + (Math.sin(t * 3.1) * 0.5 + 0.5) * 0.5);
        g.globalAlpha = alpha * (0.5 - (pr / r - 1.25) * 0.7);
        g.lineWidth = 1.4;
        poly(g, 0, 0, pr, 0); g.stroke();
        g.globalAlpha = alpha;

      } else if (evo === 'phase') {
        g.lineWidth = 2.4;
        g.setLineDash([r * 0.5, r * 0.34]);
        g.lineDashOffset = -t * 26;
        poly(g, 0, 0, r * pulse, 0); g.stroke();
        g.setLineDash([]);

      } else if (evo === 'void') {
        g.lineWidth = 2.6;
        brokenRing(g, 0, 0, r * pulse, t * 0.5, 5, 0.42);
        for (var i = 0; i < 5; i++) {                     // shed fragments in orbit
          var a = t * 1.1 + i * 1.257, rr = r * (1.5 + Math.sin(t * 2 + i) * 0.16);
          g.globalAlpha = alpha * 0.55;
          g.fillRect(Math.cos(a) * rr - 1.5, Math.sin(a) * rr - 1.5, 3, 3);
        }
        g.globalAlpha = alpha;

      } else if (evo === 'glitch') {
        g.lineWidth = 2.2;
        poly(g, 0, 0, r * pulse, 0, r * 0.16, t * 40); g.stroke();
        for (var s = 0; s < 3; s++) {                     // torn horizontal slices
          var off = (Math.random() - 0.5) * r * 0.9;
          var yy = -r + Math.random() * r * 2;
          g.globalAlpha = alpha * 0.5;
          g.fillRect(off - r * 0.5, yy, r, 1.6);
        }
        g.globalAlpha = alpha;

      } else if (evo === 'singularity') {
        for (var k = 0; k < SIDES; k++) {                 // it stopped being a shape
          var ang = t * 0.8 + (k / SIDES) * Math.PI * 2;
          var len = r * (1.5 + Math.sin(t * 4 + k) * 0.35);
          g.globalAlpha = alpha * 0.5;
          g.lineWidth = 1.2;
          g.beginPath();
          g.moveTo(Math.cos(ang) * r * 0.85, Math.sin(ang) * r * 0.85);
          g.lineTo(Math.cos(ang) * len, Math.sin(ang) * len);
          g.stroke();
        }
        g.globalAlpha = alpha;
        g.lineWidth = 2.6;
        poly(g, 0, 0, r * 0.92 * pulse, 0); g.stroke();
        coreScale = Math.max(coreScale, T.coreScale * 1.55);
      }

      // corruption tears at the shell on very long runs
      if (corrupt > 0.02 && Math.random() < corrupt * 0.5) {
        g.globalAlpha = alpha * 0.8;
        g.fillRect((Math.random() - 0.5) * r * 2, (Math.random() - 0.5) * r * 2,
                   r * (0.3 + Math.random() * 0.5), 1.4);
        g.globalAlpha = alpha;
      }

      /* ---- L4 rim: a bright arc on the leading edge, earned by speed. Drawn
         after the shell so it sits on top of whatever the evolution did to it. */
      if (q.rim && speed > 0.05) {
        var i0 = Math.round((down / (Math.PI * 2)) * SIDES) - 2;
        g.globalAlpha = alpha * T.rimAlpha * Math.min(1, speed * 1.4);
        g.lineWidth = T.bodyWeightLead * 0.8;
        polyRun(g, r * pulse, i0, 4);
        g.stroke();
        g.globalAlpha = alpha;
      }

      /* ---- L6 motes: energy shed into orbit. They live outside the shell, which
         is allowed — they are light, not matter, and nothing collides with them. */
      if (q.motes && glow > 0.25) {
        g.globalAlpha = alpha * 0.5 * Math.min(1, glow);
        for (var mi = 0; mi < T.moteCount; mi++) {
          var ma = t * 1.7 + (mi / T.moteCount) * 6.2832;
          var mr = r * (1.34 + Math.sin(t * 2.3 + mi * 2) * 0.10);
          var ms = 1.1 + Math.sin(t * 5 + mi) * 0.35;
          g.beginPath(); g.arc(Math.cos(ma) * mr, Math.sin(ma) * mr, ms, 0, 6.2832); g.fill();
        }
        g.globalAlpha = alpha;
      }

      /* ---- L7 core: a gradient with a solid hotspot, not a flat disc. The
         falloff is what makes it read as light coming from inside the shell
         rather than a white circle sitting in front of it. */
      var cR = r * coreScale * pulse, cSkirt = cR * 1.45;
      g.globalAlpha = alpha * m.coreAlpha;
      g.fillStyle = radial(g, cSkirt, CORE_STOPS);
      g.beginPath(); g.arc(0, 0, cSkirt, 0, 6.2832); g.fill();
      g.fillStyle = '#ffffff';
      g.beginPath(); g.arc(0, 0, cR * T.coreHot, 0, 6.2832); g.fill();
      g.restore();
    },

    /* Outline-only rendering for ghosts: same silhouette, no presence. */
    drawGhost: function (g, x, y, r, rot, alpha) {
      g.save();
      g.globalAlpha = alpha;
      g.translate(x, y); g.rotate(rot || 0);
      g.strokeStyle = '#ffffff'; g.lineWidth = 1.3;
      g.setLineDash([4, 5]);
      poly(g, 0, 0, r, 0); g.stroke();
      g.setLineDash([]);
      g.beginPath(); g.arc(0, 0, r * 0.2, 0, Math.PI * 2); g.fill();
      g.restore();
    },

    /* Mood from the current run state — used by the HUD-less feedback language.
       The character IS the feedback: there is no health bar to look at. */
    moodFor: function (run) {
      if (run.dead) return 'hurt';
      if (run.sinceNear < 0.35) return 'near';
      if (run.sinceRecord < 1.2) return 'success';
      if (run.threat > 0.6) return 'alert';
      /* Deep into a fast run with nothing immediately in the way: not focused
         and not alarmed, just running hot. It is the state a long clean stretch
         deserves and the one the character never had. */
      if (run.speedFrac > 0.72 && run.intensity > 0.55) return 'excited';
      if (run.speedFrac > 0.5) return 'focused';
      return 'neutral';
    },

    moods: MOODS
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
