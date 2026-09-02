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

  /* ---------- the shell is a solid, not an outline ----------
   *
   * A nonagon outline reads as a flat ring however it is lit. The reference is
   * a faceted sphere: overlapping polygon edges that describe a volume, with
   * the light inside it. So the shell is now a real polyhedron, rotated in
   * three dimensions and projected — which costs a matrix multiply per vertex
   * and buys the one thing brightness could never fake, which is depth.
   *
   * An icosahedron, because twelve vertices and thirty edges is the fewest that
   * still reads as a sphere rather than as a box, and because its silhouette
   * stays a recognisable near-circle from every angle. That matters: the
   * character has to be identifiable at thumbnail size and through five
   * evolutions, and a shape whose outline changes as it turns is not.
   *
   * Edges are drawn in four depth buckets rather than one path per edge, so
   * thirty edges cost four strokes. Far edges are dimmer and thinner. That
   * gradient IS the volume — remove it and the whole thing collapses back into
   * a tangle of lines. */
  var PHI = 1.6180339887;
  var ICO_V = [], ICO_E = [];
  (function buildIco() {
    var raw = [], i, j;
    [[0, 1, PHI], [0, -1, PHI], [0, 1, -PHI], [0, -1, -PHI],
     [1, PHI, 0], [-1, PHI, 0], [1, -PHI, 0], [-1, -PHI, 0],
     [PHI, 0, 1], [-PHI, 0, 1], [PHI, 0, -1], [-PHI, 0, -1]].forEach(function (v) {
      var L = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
      raw.push([v[0] / L, v[1] / L, v[2] / L]);
    });
    ICO_V = raw;
    /* Edges by distance: on a unit icosahedron the short chord is ~1.051 and
       the next one up is ~1.70, so any threshold between them finds exactly the
       thirty real edges without a hand-written table to get wrong. */
    for (i = 0; i < raw.length; i++) {
      for (j = i + 1; j < raw.length; j++) {
        var dx = raw[i][0] - raw[j][0], dy = raw[i][1] - raw[j][1], dz = raw[i][2] - raw[j][2];
        if (Math.sqrt(dx * dx + dy * dy + dz * dz) < 1.3) ICO_E.push([i, j]);
      }
    }
  })();

  var proj = [];
  for (var pi = 0; pi < 12; pi++) proj.push([0, 0, 0]);

  /* Project the shell for this frame. Two rotations, both slow: the character
     is turning, not spinning, and a fast tumble would fight the gameplay
     rotation the player actually caused. */
  function project(r, t, wob) {
    var ay = t * 0.62, ax = t * 0.41 + wob;
    var cy = Math.cos(ay), sy = Math.sin(ay), cx = Math.cos(ax), sx = Math.sin(ax);
    for (var i = 0; i < 12; i++) {
      var v = ICO_V[i];
      var x1 = v[0] * cy + v[2] * sy, z1 = -v[0] * sy + v[2] * cy;
      var y2 = v[1] * cx - z1 * sx, z2 = v[1] * sx + z1 * cx;
      var pp = proj[i];
      pp[0] = x1 * r; pp[1] = y2 * r; pp[2] = z2;
    }
  }

  /* Draw the projected edges in depth buckets. `weight` scales line width and
     `bright` scales alpha, so an evolution can thin the shell out or fade it
     without needing its own copy of this loop. */
  /* At gameplay size the character is 36px across, and thirty edges inside that
     is a tangle rather than a solid. So the far half of the shell is dropped
     below a threshold: the same object, drawn with the detail the size can
     actually carry. The front facets alone still read as a faceted sphere —
     it is the depth gradient that sells the volume, not the edge count — and
     the silhouette, which is what identifies the character, is unchanged. */
  var LOD_R = 24;

  function shell(g, alpha, weight, bright, dash, lod) {
    var BUCKETS = 4, b, e, first = lod ? 2 : 0;
    if (dash) g.setLineDash(dash);
    for (b = first; b < BUCKETS; b++) {
      var lo = -1 + (2 * b) / BUCKETS, hi = -1 + (2 * (b + 1)) / BUCKETS;
      var depth = (b + 0.5) / BUCKETS;              // 0 = far, 1 = near
      g.beginPath();
      var any = false;
      for (e = 0; e < ICO_E.length; e++) {
        var a = proj[ICO_E[e][0]], c = proj[ICO_E[e][1]];
        var mz = (a[2] + c[2]) / 2;
        if (mz < lo || mz >= hi) continue;
        g.moveTo(a[0], a[1]); g.lineTo(c[0], c[1]);
        any = true;
      }
      if (!any) continue;
      g.globalAlpha = alpha * bright * (0.16 + depth * 0.84);
      g.lineWidth = weight * (0.45 + depth * 0.75);
      g.stroke();
    }
    if (dash) g.setLineDash([]);
    g.globalAlpha = alpha;
  }

  /* Vertex points. The reference has bright nodes where facets meet, and they
     are what stops the shell reading as a wire ball and start it reading as a
     structure with joints. Near vertices only — a dot on the far side of a
     sphere is a dot in the middle of the silhouette, which is just noise. */
  function nodes(g, alpha, size, lod) {
    for (var i = 0; i < 12; i++) {
      var p = proj[i];
      if (p[2] < (lod ? 0.4 : 0.1)) continue;
      var d = (p[2] + 1) / 2;
      g.globalAlpha = alpha * (0.25 + d * 0.75);
      g.beginPath();
      g.arc(p[0], p[1], size * (0.55 + d * 0.65), 0, 6.2832);
      g.fill();
    }
    g.globalAlpha = alpha;
  }

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

      /* ---- L0 flash: a hard ring leaving the shell, only in the moment.
         Circular, like everything outside the shell now — the silhouette is a
         sphere, and a nine-sided halo around it reads as a second, wrong
         object rather than as that object's light. */
      if (flash > 0.03) {
        g.globalAlpha = alpha * flash * 0.55;
        g.strokeStyle = '#ffffff';
        g.lineWidth = 1 + flash * 2;
        g.beginPath();
        g.arc(0, 0, r * (1.15 + (1 - flash) * 1.5), 0, 6.2832);
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
        g.beginPath();
        g.arc(0, 0, r * 1.02 * pulse, 0, 6.2832);
        g.stroke();
      }

      g.lineJoin = 'round';
      g.lineCap = 'round';
      g.strokeStyle = '#ffffff';
      g.fillStyle = '#ffffff';

      /* ---- L3 the shell.
         Each evolution changes the STRUCTURE, not the brightness. A brighter
         version of the same object is not a different object, and six of those
         in a row is a progress bar wearing a costume. */
      project(r * pulse, t, evo === 'glitch' ? Math.sin(t * 9) * 0.4 : 0);
      var lod = r < LOD_R;

      if (evo === 'core') {
        shell(g, alpha, 2.0, 1, null, lod);
        nodes(g, alpha, 1.5, lod);

      } else if (evo === 'pulse') {
        // energy circulating: a bright band sweeping around the depth axis
        shell(g, alpha, 1.9, 0.85, null, lod);
        nodes(g, alpha, 1.6, lod);
        var sweep = Math.sin(t * 2.2);
        g.globalAlpha = alpha * 0.5;
        g.lineWidth = 2.6;
        g.beginPath();
        for (var pe = 0; pe < ICO_E.length; pe++) {
          var pa = proj[ICO_E[pe][0]], pc = proj[ICO_E[pe][1]];
          if (Math.abs((pa[2] + pc[2]) / 2 - sweep) > 0.22) continue;
          g.moveTo(pa[0], pa[1]); g.lineTo(pc[0], pc[1]);
        }
        g.stroke();
        g.globalAlpha = alpha;

      } else if (evo === 'phase') {
        // translucency: the shell stops being continuous
        shell(g, alpha, 2.0, 0.55, [r * 0.30, r * 0.22], lod);
        nodes(g, alpha * 0.7, 1.5, lod);

      } else if (evo === 'void') {
        // the interior deepens: near edges only, and the far half goes dark
        shell(g, alpha, 2.3, 0.9, null, lod);
        g.globalAlpha = alpha * 0.55;
        g.fillStyle = '#08090c';
        g.beginPath(); g.arc(0, 0, r * 0.62, 0, 6.2832); g.fill();
        g.fillStyle = '#ffffff';
        g.globalAlpha = alpha;
        nodes(g, alpha, 1.8, lod);
        for (var vi = 0; vi < 5; vi++) {                  // shed fragments in orbit
          var va = t * 1.1 + vi * 1.257, vr = r * (1.5 + Math.sin(t * 2 + vi) * 0.16);
          g.globalAlpha = alpha * 0.55;
          g.fillRect(Math.cos(va) * vr - 1.5, Math.sin(va) * vr - 1.5, 3, 3);
        }
        g.globalAlpha = alpha;

      } else if (evo === 'glitch') {
        // desynchronisation: the shell is drawn twice, out of step with itself
        shell(g, alpha, 1.8, 0.75, null, lod);
        project(r * pulse * 1.04, t + 0.06, Math.sin(t * 9) * 0.4);
        g.globalAlpha = alpha * 0.4;
        shell(g, alpha * 0.4, 1.2, 1, null);
        g.globalAlpha = alpha;
        nodes(g, alpha, 1.4, lod);
        for (var sI = 0; sI < 3; sI++) {                  // torn horizontal slices
          var off = (Math.random() - 0.5) * r * 0.9;
          var yy = -r + Math.random() * r * 2;
          g.globalAlpha = alpha * 0.5;
          g.fillRect(off - r * 0.5, yy, r, 1.6);
        }
        g.globalAlpha = alpha;

      } else if (evo === 'singularity') {
        // space bends towards it: the shell pulls the field in around itself
        for (var k = 0; k < 12; k++) {
          var sp = proj[k];
          if (sp[2] < 0) continue;
          g.globalAlpha = alpha * 0.32;
          g.lineWidth = 1;
          g.beginPath();
          g.moveTo(sp[0], sp[1]);
          g.lineTo(sp[0] * (1.55 + Math.sin(t * 4 + k) * 0.3),
                   sp[1] * (1.55 + Math.sin(t * 4 + k) * 0.3));
          g.stroke();
        }
        g.globalAlpha = alpha;
        shell(g, alpha, 2.4, 1, null, lod);
        nodes(g, alpha, 2.0, lod);
        coreScale = Math.max(coreScale, T.coreScale * 1.55);
      }

      /* ---- L4 rim: a bright arc on the leading edge, earned by speed. Drawn
         after the shell so it sits on top of whatever the evolution did to it. */
      if (q.rim && speed > 0.05) {
        g.globalAlpha = alpha * T.rimAlpha * Math.min(1, speed * 1.4);
        g.lineWidth = T.bodyWeightLead * 0.75;
        g.lineCap = 'round';
        g.beginPath();
        /* Inside the circumradius, not on it. An icosahedron only touches its
           circumscribed circle at twelve points; an arc drawn out there floats
           off the object instead of lighting its edge. */
        g.arc(0, 0, r * pulse * 0.88, down - 0.8, down + 0.8);
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
