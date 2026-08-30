/* ONE MORE — world rendering.
   Black ground, white geometry, grey for anything that is not gameplay. The
   backdrop changes with the world you have survived into; the obstacles never
   change their visual language, because the moment a spike stops looking like a
   spike the game has lied to you. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys, PAT = OM.patterns;
  var CEIL = P.CEIL, FLOOR = P.FLOOR;

  function surfaceSegments(holes, side, x0, x1) {
    var segs = [], cur = x0;
    for (var i = 0; i < holes.length; i++) {
      var h = holes[i];
      if (h.side !== side) continue;
      if (h.x + h.w < x0 || h.x > x1) continue;
      if (h.x > cur) segs.push([cur, Math.min(h.x, x1)]);
      cur = Math.max(cur, h.x + h.w);
    }
    if (cur < x1) segs.push([cur, x1]);
    return segs;
  }

  var R = OM.render = {
    /* ---- backdrop ---- */
    backdrop: function (g, W, H, world, t, corrupt, speedFrac) {
      g.fillStyle = '#08090c';
      g.fillRect(0, 0, W, H);

      if (world === 'origin') {
        g.strokeStyle = 'rgba(255,255,255,0.035)';
        g.lineWidth = 1;
        for (var i = 0; i < 5; i++) {
          var y = CEIL + ((FLOOR - CEIL) / 4) * i;
          g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke();
        }
      } else if (world === 'pulse') {
        var sp = (t * 90) % 160;
        g.fillStyle = 'rgba(255,255,255,0.028)';
        for (var b = -160; b < W + 160; b += 160) g.fillRect(b - sp, CEIL, 54, FLOOR - CEIL);
      } else if (world === 'void') {
        g.fillStyle = 'rgba(255,255,255,0.02)';
        for (var k = 0; k < 26; k++) {
          var px = ((k * 977 + t * 30) % (W + 60)) - 30;
          var py = CEIL + ((k * 613) % (FLOOR - CEIL));
          g.fillRect(px, py, 2, 2);
        }
      } else if (world === 'collapse' || world === 'nightmare') {
        g.fillStyle = 'rgba(255,255,255,0.03)';
        for (var s = 0; s < 8; s++) {
          var sy = ((s * 211 + t * 42) % (FLOOR - CEIL)) + CEIL;
          var sw = 60 + ((s * 97) % 220);
          g.fillRect(((s * 383 + t * 130) % (W + sw)) - sw, sy, sw, 1.5);
        }
        if (world === 'nightmare') {
          g.fillStyle = 'rgba(255,255,255,' + (0.02 + Math.sin(t * 7) * 0.012).toFixed(3) + ')';
          g.fillRect(0, CEIL, W, FLOOR - CEIL);
        }
      }

      // corruption: torn bands across the whole frame on very long runs
      if (corrupt > 0.02) {
        for (var c = 0; c < 3; c++) {
          if (Math.random() > corrupt * 0.55) continue;
          var cy = CEIL + Math.random() * (FLOOR - CEIL);
          g.fillStyle = 'rgba(255,255,255,' + (0.03 + Math.random() * 0.07).toFixed(3) + ')';
          g.fillRect(0, cy, W, 1 + Math.random() * 3);
        }
      }
    },

    /* ---- floor and ceiling ---- */
    surfaces: function (g, W, camX, holes, t, speedFrac) {
      var x0 = camX - 40, x1 = camX + W + 40;
      g.save();
      g.lineCap = 'butt';

      ['ceil', 'floor'].forEach(function (side) {
        var y = side === 'floor' ? FLOOR : CEIL;
        var segs = surfaceSegments(holes, side, x0, x1);
        for (var i = 0; i < segs.length; i++) {
          var a = segs[i][0] - camX, b = segs[i][1] - camX;
          g.fillStyle = '#ffffff';
          g.fillRect(a, side === 'floor' ? y : y - 3, b - a, 3);
          // Solid mass behind the surface so a hole reads as an absence. It
          // runs well past the tunnel because on a portrait screen the visible
          // area extends far above and below it.
          g.fillStyle = 'rgba(255,255,255,0.055)';
          g.fillRect(a, side === 'floor' ? y + 3 : y - 3 - 1400, b - a, 1400);
          // speed ticks
          g.fillStyle = 'rgba(255,255,255,0.16)';
          var step = 68;
          var start = Math.ceil(segs[i][0] / step) * step;
          for (var xx = start; xx < segs[i][1]; xx += step) {
            g.fillRect(xx - camX, side === 'floor' ? y + 8 : y - 16, 2, 8);
          }
        }
        // hole edges get a lip so the gap is legible at speed
        for (var h = 0; h < holes.length; h++) {
          var ho = holes[h];
          if (ho.side !== side || ho.x + ho.w < x0 || ho.x > x1) continue;
          g.fillStyle = '#ffffff';
          var ey = side === 'floor' ? y : y - 14;
          g.fillRect(ho.x - camX - 3, ey, 3, 14);
          g.fillRect(ho.x + ho.w - camX, ey, 3, 14);
        }
      });
      g.restore();
    },

    /* ---- obstacles ---- */
    obstacles: function (g, W, camX, list, t, opts) {
      opts = opts || {};
      var fade = opts.fade, strobe = opts.strobe, px = opts.playerX, vision = opts.vision;
      g.save();
      for (var i = 0; i < list.length; i++) {
        var o = list[i];
        var sx = o.x - camX;
        if (sx > W + 80 || sx + (o.w || 0) < -80) continue;

        var alpha = 1;
        if (fade) {                       // PHASE: it arrives late
          alpha = OM.math.clamp(1.25 - (sx - px) / (W * 0.5), 0.06, 1);
        }
        if (vision) {                     // DARK: only what is close
          var d = Math.abs(sx + (o.w || 0) / 2 - px);
          alpha *= OM.math.clamp(1.35 - d / vision, 0.03, 1);
        }
        if (strobe) alpha *= (Math.sin(t * 19 + i) > -0.35 ? 1 : 0.12);
        if (alpha < 0.03) continue;
        g.globalAlpha = alpha;
        drawObstacle(g, o, sx, t);
      }
      g.restore();
    },

    /* Danger telegraph: the nearest thing in front of you, as a thin marker on
       the edge of the screen. Reads as pressure, costs almost no pixels. */
    threatOf: function (list, camX, playerX, W) {
      var best = 0;
      for (var i = 0; i < list.length; i++) {
        var sx = list[i].x - camX;
        if (sx < playerX - 10 || sx > playerX + W * 0.55) continue;
        var f = 1 - (sx - playerX) / (W * 0.55);
        if (f > best) best = f;
      }
      return best;
    }
  };

  /* A solid mass: white frame, dimmed interior, sparse diagonal hatch. Filling
     these solid white makes them shout louder than the player; slicing them into
     stripes made them read as ladders you could climb. A frame reads as "solid,
     do not touch" at a glance and stays quiet in the frame. */
  function mass(g, x, y, w, h) {
    g.fillStyle = 'rgba(255,255,255,0.13)';
    g.fillRect(x, y, w, h);
    g.save();
    g.beginPath(); g.rect(x, y, w, h); g.clip();
    g.strokeStyle = 'rgba(255,255,255,0.22)';
    g.lineWidth = 1.5;
    for (var d = -h; d < w; d += 15) {
      g.beginPath(); g.moveTo(x + d, y + h); g.lineTo(x + d + h, y); g.stroke();
    }
    g.restore();
    g.strokeStyle = '#fff';
    g.lineWidth = 3;
    g.strokeRect(x + 1.5, y + 1.5, w - 3, h - 3);
  }

  function drawObstacle(g, o, sx, t) {
    g.fillStyle = '#ffffff';
    g.strokeStyle = '#ffffff';
    switch (o.t) {
      case 'spike': {
        var teeth = Math.max(2, Math.round(o.w / 34));
        var tw = o.w / teeth;
        g.beginPath();
        for (var i = 0; i < teeth; i++) {
          var x0 = sx + i * tw;
          if (o.side === 'floor') {
            g.moveTo(x0, FLOOR); g.lineTo(x0 + tw / 2, FLOOR - o.h); g.lineTo(x0 + tw, FLOOR);
          } else {
            g.moveTo(x0, CEIL); g.lineTo(x0 + tw / 2, CEIL + o.h); g.lineTo(x0 + tw, CEIL);
          }
        }
        g.closePath(); g.fill();
        break;
      }
      case 'block': {
        var by = o.side === 'floor' ? FLOOR - o.h : CEIL;
        mass(g, sx, by, o.w, o.h);
        // the killing edge, emphasised: the face you actually have to clear
        g.fillStyle = '#fff';
        g.fillRect(sx, o.side === 'floor' ? by : CEIL + o.h - 4, o.w, 4);
        break;
      }
      case 'bar': {
        mass(g, sx, o.y0, o.w, o.y1 - o.y0);
        g.fillStyle = '#fff';
        g.fillRect(sx, o.y0, o.w, 4);
        g.fillRect(sx, o.y1 - 4, o.w, 4);
        break;
      }
      case 'mover': {
        var my = PAT.moverY(o, t) - o.h / 2;
        mass(g, sx, my, o.w, o.h);
        g.fillStyle = '#fff';
        g.fillRect(sx + o.w / 2 - 1, my + 8, 2, o.h - 16);
        // travel guides, so the motion is predictable rather than surprising
        g.globalAlpha *= 0.25;
        g.fillRect(sx + o.w / 2 - 1, o.cy - o.amp - o.h / 2, 2, o.amp * 2 + o.h);
        g.globalAlpha /= 0.25;
        break;
      }
      case 'laser': {
        var ly = o.side === 'ceil' ? CEIL : FLOOR - o.h;
        var ph = PAT.laserPhase(o, t), on = ph < o.duty;
        // emitter
        g.fillRect(sx, o.side === 'ceil' ? CEIL : FLOOR - 8, o.w, 8);
        if (on) {
          g.fillRect(sx + 4, ly, o.w - 8, o.h);
          g.globalAlpha *= 0.35;
          g.fillRect(sx, ly, o.w, o.h);
          g.globalAlpha /= 0.35;
        } else {
          // charge tell: a thin line that thickens as it is about to fire
          var toOn = (1 - ph) / (1 - o.duty);
          g.globalAlpha *= 0.18 + (1 - toOn) * 0.5;
          g.fillRect(sx + o.w / 2 - 1, ly, 2, o.h);
          g.globalAlpha /= (0.18 + (1 - toOn) * 0.5);
        }
        break;
      }
    }
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
