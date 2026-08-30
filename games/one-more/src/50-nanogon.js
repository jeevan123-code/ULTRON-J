/* ONE MORE — the Nanogon.
   Drawn entirely from geometry: no sprites, no atlas, no resolution to be wrong
   at. Nine sides, one bright core, and six evolutions that arrive with your
   level. Everything is white on black; the only expressive channels are size,
   brightness, break-up and motion, which is exactly the constraint that makes
   it readable at thumbnail size. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var SIDES = 9;

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

  var N = OM.nanogon = {
    /* st: {x,y,r,rot,grav,vy,speed,evo,mood,t,glow,corrupt,alpha,scale} */
    draw: function (g, st) {
      var r = st.r * (st.scale == null ? 1 : st.scale);
      var evo = st.evo || 'core';
      var mood = st.mood || 'neutral';
      var t = st.t || 0;
      var alpha = st.alpha == null ? 1 : st.alpha;
      var corrupt = st.corrupt || 0;

      // mood drives core brightness, size and how much the shell trembles
      var coreScale = 0.30, glow = st.glow || 0, tremble = 0;
      if (mood === 'focused') { coreScale = 0.25; }
      else if (mood === 'alert') { coreScale = 0.30 + Math.sin(t * 22) * 0.03; tremble = 0.5; }
      else if (mood === 'near') { coreScale = 0.40; glow = Math.max(glow, 0.9); tremble = 1.6; }
      else if (mood === 'success') { coreScale = 0.42; glow = Math.max(glow, 1); }
      else if (mood === 'hurt') { coreScale = 0.22; tremble = 3; }
      var pulse = 1 + Math.sin(t * 3.4) * 0.035;

      g.save();
      g.globalAlpha = alpha;
      g.translate(st.x + (tremble ? (Math.random() - 0.5) * tremble : 0),
                  st.y + (tremble ? (Math.random() - 0.5) * tremble : 0));
      g.rotate(st.rot || 0);

      // outer glow — a couple of cheap wide strokes rather than a shadow blur,
      // which is the single most expensive thing you can ask a 2D canvas for
      if (glow > 0.01) {
        g.strokeStyle = 'rgba(255,255,255,' + (0.10 * glow).toFixed(3) + ')';
        g.lineWidth = 9 + glow * 8;
        poly(g, 0, 0, r * 1.06 * pulse, 0);
        g.stroke();
      }

      g.lineJoin = 'round';
      g.strokeStyle = '#ffffff';
      g.fillStyle = '#ffffff';

      if (evo === 'core') {
        g.lineWidth = 2.4;
        poly(g, 0, 0, r * pulse, 0); g.stroke();

      } else if (evo === 'pulse') {
        g.lineWidth = 2.4;
        poly(g, 0, 0, r * pulse, 0); g.stroke();
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
        coreScale = Math.max(coreScale, 0.55);
      }

      // corruption tears at the shell on very long runs
      if (corrupt > 0.02 && Math.random() < corrupt * 0.5) {
        g.globalAlpha = alpha * 0.8;
        g.fillRect((Math.random() - 0.5) * r * 2, (Math.random() - 0.5) * r * 2,
                   r * (0.3 + Math.random() * 0.5), 1.4);
        g.globalAlpha = alpha;
      }

      // the core
      g.beginPath();
      g.arc(0, 0, r * coreScale * pulse, 0, Math.PI * 2);
      g.fill();
      if (glow > 0.2) {
        g.globalAlpha = alpha * 0.25 * glow;
        g.beginPath();
        g.arc(0, 0, r * coreScale * 2.1, 0, Math.PI * 2);
        g.fill();
      }
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
      if (run.speedFrac > 0.5) return 'focused';
      return 'neutral';
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
