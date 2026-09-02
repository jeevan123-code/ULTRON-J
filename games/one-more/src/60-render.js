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
    /* ---- backdrop ----
       Five worlds, one ink, and a rule: the environment may never compete with
       the geometry that can kill you. Everything here is drawn under 0.06 alpha
       except where a world is deliberately about visibility, and nothing here
       ever occupies the band an obstacle can spawn in without being obviously
       softer than one.

       The worlds are a sentence: clean, then alive, then dark, then coming
       apart, then hostile. Each one adds a layer rather than swapping a trick,
       so arriving somewhere feels like accumulation and not redecoration.

       `vis` is the conductor's sample, so depth, drift and instability all move
       on the same clock as the character and the UI. */
    backdrop: function (g, W, H, world, t, corrupt, speedFrac, vis) {
      g.fillStyle = '#08090c';
      g.fillRect(0, 0, W, H);
      var q = (vis && vis.q) || OM.visual.q();
      var atmos = vis ? vis.atmos : 0;
      var band = FLOOR - CEIL;

      /* Depth. Three parallax planes of long horizontal rules, furthest first,
         each moving at a fraction of the world's speed. This is the layer that
         turns a black rectangle into somewhere with distance in it, and it is
         also the cheapest: nine strokes. */
      function depth(planes, alphaMul) {
        for (var pI = 0; pI < planes; pI++) {
          var rate = 0.06 + pI * 0.10;
          var a = (0.020 + pI * 0.009) * alphaMul;
          g.strokeStyle = 'rgba(255,255,255,' + a.toFixed(3) + ')';
          g.lineWidth = 1;
          for (var i = 0; i < 3; i++) {
            var seed = pI * 37 + i * 91;
            var yy = CEIL + ((seed * 137) % band);
            var len = 180 + (seed % 260);
            var span = W + len;
            var x = span - (((t * 60 * rate + seed * 13) % span));
            g.beginPath();
            g.moveTo(x - len, yy);
            g.lineTo(x, yy);
            g.stroke();
          }
        }
      }

      if (world === 'origin') {
        /* Pure minimalism. Four guide rules and nothing else — the player has
           one job here, which is to learn that the tunnel has two sides. */
        g.strokeStyle = 'rgba(255,255,255,0.035)';
        g.lineWidth = 1;
        for (var i = 0; i < 5; i++) {
          var y = CEIL + (band / 4) * i;
          g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke();
        }

      } else if (world === 'pulse') {
        /* Alive. The bands breathe rather than slide, and depth arrives. */
        var breath = 0.55 + Math.sin(t * 0.9) * 0.45;
        var sp = (t * 90) % 160;
        g.fillStyle = 'rgba(255,255,255,' + (0.018 + breath * 0.016).toFixed(3) + ')';
        for (var b = -160; b < W + 160; b += 160) g.fillRect(b - sp, CEIL, 54, band);
        depth(2, 0.8);

      } else if (world === 'void') {
        /* Dark. Most of it stops being visible, so what remains has to be
           worth looking at: slow motes that drift rather than scroll, and a
           soft gradient that eats the middle of the frame without touching the
           surfaces the player reads. */
        depth(1, 0.5);
        var cache = g.__omGrad || (g.__omGrad = {});
        if (!cache.voidfog) {
          var vg = g.createLinearGradient(0, CEIL, 0, FLOOR);
          vg.addColorStop(0, 'rgba(8,9,12,0)');
          vg.addColorStop(0.5, 'rgba(8,9,12,0.85)');
          vg.addColorStop(1, 'rgba(8,9,12,0)');
          cache.voidfog = vg;
        }
        for (var k = 0; k < 26; k++) {
          var px = ((k * 977 + t * 30) % (W + 60)) - 30;
          var py = CEIL + ((k * 613) % band) + Math.sin(t * 0.6 + k) * 14;
          var pa = 0.02 + (Math.sin(t * 1.3 + k * 2.1) * 0.5 + 0.5) * 0.03;
          g.fillStyle = 'rgba(255,255,255,' + pa.toFixed(3) + ')';
          g.fillRect(px, py, 2, 2);
        }
        g.fillStyle = cache.voidfog;
        g.fillRect(0, CEIL, W, band);

      } else if (world === 'collapse' || world === 'nightmare') {
        /* Coming apart. Fragments tumble instead of sliding, and they are the
           only thing in the backdrop with rotation in it — the eye reads a
           turning object as debris and a sliding one as scenery. */
        depth(3, 1);
        for (var s = 0; s < 10; s++) {
          var sy = ((s * 211 + t * 42) % band) + CEIL;
          var sw = 60 + ((s * 97) % 220);
          var sx = ((s * 383 + t * 130) % (W + sw)) - sw;
          g.save();
          g.translate(sx + sw / 2, sy);
          g.rotate(Math.sin(t * 0.5 + s) * 0.25);
          g.fillStyle = 'rgba(255,255,255,' + (0.022 + (s % 3) * 0.008).toFixed(3) + ')';
          g.fillRect(-sw / 2, -0.75, sw, 1.5);
          g.restore();
        }

        if (world === 'nightmare') {
          /* Hostile. The frame itself is lit unevenly and never settles. */
          g.fillStyle = 'rgba(255,255,255,' + (0.02 + Math.sin(t * 7) * 0.012).toFixed(3) + ')';
          g.fillRect(0, CEIL, W, band);
          if (q.distortion) {
            for (var n = 0; n < 2; n++) {
              if (Math.random() > 0.35) continue;
              var ny = CEIL + Math.random() * band;
              g.fillStyle = 'rgba(255,255,255,' + (0.04 + Math.random() * 0.05).toFixed(3) + ')';
              g.fillRect(0, ny, W, 1 + Math.random() * 2);
            }
          }
        }
      }

      // corruption: torn bands across the whole frame on very long runs
      if (corrupt > 0.02) {
        for (var c = 0; c < 3; c++) {
          if (Math.random() > corrupt * 0.55) continue;
          var cy = CEIL + Math.random() * band;
          g.fillStyle = 'rgba(255,255,255,' + (0.03 + Math.random() * 0.07).toFixed(3) + ')';
          g.fillRect(0, cy, W, 1 + Math.random() * 3);
        }
      }
      return atmos;
    },

    /* ---- haze ----
       Atmospheric perspective, and the thing that stops the architecture from
       looking like it is stuck to the same pane of glass as the tunnel. It sits
       between the two, densest in the middle band where the structures are, and
       clears at the surfaces so the geometry the player reads never goes
       through it. */
    haze: function (g, W, vis) {
      var amount = vis ? (0.35 + vis.atmos * 0.65) : 0.5;
      var q = (vis && vis.q) || OM.visual.q();
      if (!q.aura) return;
      var cache = g.__omGrad || (g.__omGrad = {});
      if (!cache.haze) {
        var hg = g.createLinearGradient(0, CEIL, 0, FLOOR);
        hg.addColorStop(0, 'rgba(8,9,12,0)');
        /* A veil, not a curtain. The first pass ran this at 0.55 and it erased
           the architecture it exists to sit in front of — separation is the
           job, not concealment. */
        hg.addColorStop(0.42, 'rgba(8,9,12,0.30)');
        hg.addColorStop(0.58, 'rgba(8,9,12,0.30)');
        hg.addColorStop(1, 'rgba(8,9,12,0)');
        cache.haze = hg;
      }
      g.save();
      g.globalAlpha = amount;
      g.fillStyle = cache.haze;
      g.fillRect(0, CEIL, W, FLOOR - CEIL);
      g.restore();
    },

    /* ---- contact light ----
       The character is the only light source in the game, so the surfaces it
       passes should know about it. This brightens a short span of whichever
       surface it is closest to, falling off with distance, plus a sharper
       kick on a perfect switch.

       It is a horizontal gradient drawn in a translated frame, which means the
       gradient is always centred on the origin and can be cached like every
       other one. Two fills a frame, and only when the character is close
       enough to a surface for the eye to expect a response. */
    contactLight: function (g, px, py, flash, q) {
      if (q && !q.aura) return;                  // an expensive nicety, first to go
      var toFloor = FLOOR - py, toCeil = py - CEIL;
      var near = Math.min(toFloor, toCeil);
      var reach = 190;
      if (near > reach && flash < 0.05) return;
      var side = toFloor < toCeil ? 1 : -1;
      var y = side > 0 ? FLOOR : CEIL;
      var prox = Math.max(0, 1 - near / reach);
      var a = prox * prox * 0.5 + flash * 0.35;
      if (a < 0.012) return;

      var cache = g.__omGrad || (g.__omGrad = {});
      var grd = cache.contact;
      if (!grd) {
        grd = g.createLinearGradient(-260, 0, 260, 0);
        grd.addColorStop(0, 'rgba(255,255,255,0)');
        grd.addColorStop(0.5, 'rgba(255,255,255,1)');
        grd.addColorStop(1, 'rgba(255,255,255,0)');
        cache.contact = grd;
      }
      g.save();
      g.translate(px, y);
      g.globalAlpha = Math.min(0.55, a);
      g.globalCompositeOperation = 'lighter';
      g.fillStyle = grd;
      g.fillRect(-260, side > 0 ? -2 : -1, 520, 3);
      g.globalAlpha = Math.min(0.3, a * 0.5);
      g.fillRect(-260, side > 0 ? 1 : -14, 520, 13);
      g.restore();
    },

    /* Speed streaks. An earlier version scattered these across the whole tunnel
       at fixed heights, which read as scratches on the screen rather than as
       motion — the eye reads a static y as dirt. These re-seed their height on
       every wrap, stay near the player's altitude where the eye already is, and
       only appear once the world is genuinely moving fast. */
    speedLines: function (g, W, camX, playerY, frac) {
      if (frac < 0.34) return;
      var f = (frac - 0.34) / 0.66;
      var n = 4 + Math.round(f * 9);
      g.save();
      g.fillStyle = '#fff';
      for (var i = 0; i < n; i++) {
        var seed = i * 2654435761 % 100000;
        var rate = 1.5 + (seed % 5) * 0.22;
        var span = 70 + f * 210 + (seed % 60);
        var cycle = W + span * 2;
        var travel = camX * rate + seed;
        var lap = Math.floor(travel / cycle);
        var x = W + span - (travel - lap * cycle);
        // fresh height each lap, biased toward wherever the player is looking
        var hs = ((lap * 2654435761 + seed) >>> 0) % 1000 / 1000;
        var y = playerY + (hs - 0.5) * 320;
        if (y < P.CEIL + 10 || y > P.FLOOR - 10) continue;
        g.globalAlpha = (0.05 + f * 0.13) * (1 - Math.abs(hs - 0.5) * 1.2);
        g.fillRect(x, y, span, 1);
      }
      g.restore();
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
        // the thing you just grazed lights up: near misses should be legible
        // after the fact, not only felt
        if (o._flash > 0.01) {
          g.globalAlpha = alpha * o._flash * 0.8;
          g.strokeStyle = '#fff';
          g.lineWidth = 2 + o._flash * 5;
          var rects = PAT.rectsOf(o, t, []);
          for (var q = 0; q < rects.length; q++) {
            g.strokeRect(rects[q].x - 4, rects[q].y - 4, rects[q].w + 8, rects[q].h + 8);
          }
        }
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
      case 'piston': {
        var pe = PAT.pistonExt(o, t);
        var base = o.side === 'floor' ? FLOOR : CEIL;
        // housing: always visible, so the threat has a fixed address
        g.fillStyle = '#fff';
        g.fillRect(o.side === 'floor' ? sx - 4 : sx - 4, o.side === 'floor' ? base - 10 : base, o.w + 8, 10);
        if (pe > 1) {
          var py = o.side === 'floor' ? base - pe : base;
          mass(g, sx, py, o.w, pe);
          g.fillStyle = '#fff';                     // the head, the part that kills
          g.fillRect(sx - 3, o.side === 'floor' ? py : py + pe - 7, o.w + 6, 7);
        } else {
          // primed: a short stub that grows just before it fires
          var pp = (o.phase + t * o.rate) % 1;
          var soon = Math.max(0, 1 - (1 - pp) / (1 - o.duty) * 3);
          g.globalAlpha *= 0.25 + soon * 0.6;
          g.fillRect(sx + o.w / 2 - 2, o.side === 'floor' ? base - 22 : base, 4, 22);
          g.globalAlpha /= (0.25 + soon * 0.6);
        }
        break;
      }
      case 'rotor': {
        var ra = PAT.rotorAngle(o, t);
        var pvx = sx + o.w / 2, pvy = o.side === 'floor' ? FLOOR : CEIL;
        var dir = o.side === 'floor' ? -1 : 1;
        // the sweep, drawn faint: the arm's whole reachable arc, always visible
        g.globalAlpha *= 0.16;
        g.lineWidth = 1.4;
        g.beginPath();
        g.arc(pvx, pvy, o.len, dir > 0 ? -Math.PI / 2 - o.swing : Math.PI / 2 - o.swing,
              dir > 0 ? -Math.PI / 2 + o.swing : Math.PI / 2 + o.swing);
        g.stroke();
        g.globalAlpha /= 0.16;
        g.save();
        g.translate(pvx, pvy);
        g.rotate(dir > 0 ? ra : -ra);
        // the arm itself, drawn a shade wider than the cells that kill
        mass(g, -o.thick * 0.62, dir > 0 ? -o.len : 0, o.thick * 1.24, o.len);
        g.fillStyle = '#fff';
        g.fillRect(-o.thick * 0.62, dir > 0 ? -o.len : o.len - 5, o.thick * 1.24, 5);
        g.restore();
        g.fillStyle = '#fff';                       // housing: a fixed address
        g.fillRect(pvx - o.thick, o.side === 'floor' ? FLOOR - 9 : CEIL, o.thick * 2, 9);
        break;
      }
      case 'orbit': {
        var op = PAT.orbitPos(o, t, [0, 0]);
        var ocx = sx + o.w / 2, ocy = o.cy;
        g.globalAlpha *= 0.18;                      // the path, so it is a rule
        g.lineWidth = 1.3;
        g.beginPath(); g.arc(ocx, ocy, o.rad, 0, 6.2832); g.stroke();
        g.globalAlpha /= 0.18;
        var oX = ocx + (op[0] - (o.x + o.w / 2)), oY = op[1];
        mass(g, oX - o.size / 2, oY - o.size / 2, o.size, o.size);
        g.fillStyle = '#fff';
        g.fillRect(oX - o.size / 2, oY - o.size / 2, o.size, 4);
        g.fillRect(oX - o.size / 2, oY + o.size / 2 - 4, o.size, 4);
        break;
      }
      case 'gate': {
        var gc = PAT.gateCenter(o, t);
        mass(g, sx, CEIL, o.w, (gc - o.half) - CEIL);
        mass(g, sx, gc + o.half, o.w, FLOOR - (gc + o.half));
        g.fillStyle = '#fff';                        // the two edges of the opening
        g.fillRect(sx - 3, gc - o.half - 5, o.w + 6, 5);
        g.fillRect(sx - 3, gc + o.half, o.w + 6, 5);
        g.globalAlpha *= 0.22;                       // where the opening will travel
        g.fillRect(sx + o.w / 2 - 1, o.cy - o.amp - o.half, 2, (o.amp + o.half) * 2);
        g.globalAlpha /= 0.22;
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
