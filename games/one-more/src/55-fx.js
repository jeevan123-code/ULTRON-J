/* ONE MORE — trails, particles, death effects and screen response.
   All of it is pooled and all of it is monochrome. The rule from the art
   direction holds here: if removing 30% of an effect makes the frame read
   better, it was decoration, not feedback. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var clamp = OM.math.clamp;

  /* ---------- particle pool ---------- */
  function Pool(n) {
    var P = new Array(n), i;
    for (i = 0; i < n; i++) P[i] = { life: 0 };
    var head = 0;
    return {
      all: P,
      spawn: function (x, y, vx, vy, life, size, kind, spin) {
        var p = P[head]; head = (head + 1) % n;
        p.x = x; p.y = y; p.vx = vx; p.vy = vy;
        p.life = life; p.max = life; p.size = size; p.kind = kind || 0;
        p.rot = Math.random() * 6.28; p.spin = spin || 0;
        return p;
      },
      update: function (dt, drift) {
        for (var i = 0; i < n; i++) {
          var p = P[i];
          if (p.life <= 0) continue;
          p.life -= dt;
          p.x += (p.vx - (drift || 0)) * dt;
          p.y += p.vy * dt;
          p.vy += (p.kind === 2 ? 900 : 0) * dt;
          p.vx *= 0.995; p.rot += p.spin * dt;
        }
      },
      draw: function (g) {
        g.save();
        g.fillStyle = '#fff'; g.strokeStyle = '#fff';
        for (var i = 0; i < n; i++) {
          var p = P[i];
          if (p.life <= 0) continue;
          var a = clamp(p.life / p.max, 0, 1);
          g.globalAlpha = a * a;
          if (p.kind === 1) {                 // shard
            g.save(); g.translate(p.x, p.y); g.rotate(p.rot);
            g.fillRect(-p.size, -p.size * 0.34, p.size * 2, p.size * 0.68);
            g.restore();
          } else if (p.kind === 3) {          // ring
            g.globalAlpha = a * 0.5; g.lineWidth = 1.4;
            g.beginPath(); g.arc(p.x, p.y, p.size * (1 + (1 - a) * 6), 0, 6.2832); g.stroke();
          } else {
            g.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
          }
        }
        g.restore();
      },
      clear: function () { for (var i = 0; i < n; i++) P[i].life = 0; }
    };
  }

  /* ---------- trails ----------
     The trail is not decoration: its length reads speed and its break-up reads
     danger, which is how the player senses the difficulty curve without a HUD. */
  function Trail(style) {
    var pts = [], MAXP = 46;
    return {
      style: style,
      push: function (x, y, t) {
        pts.push({ x: x, y: y, t: t });
        if (pts.length > MAXP) pts.shift();
      },
      shift: function (dx) { for (var i = 0; i < pts.length; i++) pts[i].x -= dx; },
      clear: function () { pts.length = 0; },
      draw: function (g, style, intensity, corrupt) {
        if (pts.length < 3) return;
        var i, a, p;
        g.save();
        g.strokeStyle = '#fff'; g.fillStyle = '#fff'; g.lineCap = 'round';
        if (style === 'particle') {
          for (i = 0; i < pts.length; i += 2) {
            a = i / pts.length; p = pts[i];
            g.globalAlpha = a * a * 0.7;
            var s = 1 + a * 2.4;
            g.fillRect(p.x - s / 2, p.y - s / 2, s, s);
          }
        } else if (style === 'wave') {
          g.lineWidth = 1.6;
          for (var k = -1; k <= 1; k += 2) {
            g.beginPath();
            for (i = 0; i < pts.length; i++) {
              p = pts[i]; a = i / pts.length;
              var off = Math.sin(i * 0.55 + p.t * 7) * (1 - a) * 9 * k;
              if (i === 0) g.moveTo(p.x, p.y + off); else g.lineTo(p.x, p.y + off);
            }
            g.globalAlpha = 0.42;
            g.stroke();
          }
        } else if (style === 'shatter') {
          for (i = 1; i < pts.length; i += 2) {
            a = i / pts.length; p = pts[i];
            g.globalAlpha = a * 0.55;
            var w = (1 - a) * 12 + 3;
            g.fillRect(p.x - w / 2, p.y - 1, w, 2);
          }
        } else if (style === 'void') {
          g.lineWidth = 2.2;
          g.beginPath();
          for (i = 0; i < pts.length; i++) { p = pts[i]; if (i === 0) g.moveTo(p.x, p.y); else g.lineTo(p.x, p.y); }
          g.globalAlpha = 0.22; g.stroke();
          for (i = 0; i < pts.length; i += 3) {
            a = i / pts.length; p = pts[i];
            g.globalAlpha = a * 0.8;
            g.beginPath(); g.arc(p.x, p.y, (1 - a) * 5 + 1, 0, 6.2832); g.stroke();
          }
        } else {                                     // line
          g.lineWidth = 2.6;
          g.beginPath();
          for (i = 0; i < pts.length; i++) { p = pts[i]; if (i === 0) g.moveTo(p.x, p.y); else g.lineTo(p.x, p.y); }
          var grad = 0.26 + intensity * 0.5;
          g.globalAlpha = grad;
          g.stroke();
          g.lineWidth = 1.2; g.globalAlpha = grad * 1.6;
          g.stroke();
        }
        if (corrupt > 0.3) {
          for (i = 0; i < pts.length; i += 5) {
            if (Math.random() > corrupt * 0.4) continue;
            p = pts[i];
            g.globalAlpha = 0.6;
            g.fillRect(p.x + (Math.random() - 0.5) * 24, p.y, 6, 1.4);
          }
        }
        g.restore();
      }
    };
  }

  /* ---------- death effects ---------- */
  function death(pool, style, x, y, r) {
    var i, a, sp;
    if (style === 'explode') {
      for (i = 0; i < 46; i++) {
        a = Math.random() * 6.2832; sp = 130 + Math.random() * 560;
        pool.spawn(x, y, Math.cos(a) * sp, Math.sin(a) * sp, 0.5 + Math.random() * 0.5,
                   1.5 + Math.random() * 3, 0);
      }
      pool.spawn(x, y, 0, 0, 0.5, r, 3);
    } else if (style === 'implode') {
      for (i = 0; i < 40; i++) {
        a = Math.random() * 6.2832; var d = 90 + Math.random() * 200;
        var p = pool.spawn(x + Math.cos(a) * d, y + Math.sin(a) * d,
                           -Math.cos(a) * d * 2.4, -Math.sin(a) * d * 2.4, 0.42, 2.4, 0);
        p.vy += 0;
      }
    } else if (style === 'pixel') {
      for (i = 0; i < 64; i++) {
        pool.spawn(x + (Math.random() - 0.5) * r * 2.4, y + (Math.random() - 0.5) * r * 2.4,
                   (Math.random() - 0.5) * 90, (Math.random() - 0.5) * 90,
                   0.55 + Math.random() * 0.7, 2 + Math.random() * 2, 0);
      }
    } else if (style === 'collapse') {
      for (i = 0; i < 54; i++) {
        a = Math.random() * 6.2832; var dd = 30 + Math.random() * 220;
        var q = pool.spawn(x + Math.cos(a) * dd, y + Math.sin(a) * dd, -Math.sin(a) * 340, Math.cos(a) * 340,
                           0.8 + Math.random() * 0.5, 1.6, 0);
        q.vx += -Math.cos(a) * 150; q.vy += -Math.sin(a) * 150;
      }
      pool.spawn(x, y, 0, 0, 0.9, r * 0.4, 3);
    } else if (style === 'wipe') {
      for (i = 0; i < 40; i++) {
        pool.spawn(x, y + (Math.random() - 0.5) * r * 2, 260 + Math.random() * 900,
                   (Math.random() - 0.5) * 60, 0.5 + Math.random() * 0.4, 2 + Math.random() * 4, 1, 0);
      }
    } else {                                    // glass shatter (default)
      for (i = 0; i < 26; i++) {
        a = Math.random() * 6.2832; sp = 110 + Math.random() * 380;
        pool.spawn(x, y, Math.cos(a) * sp, Math.sin(a) * sp - 80, 0.75 + Math.random() * 0.6,
                   3 + Math.random() * 5, 1, (Math.random() - 0.5) * 14);
      }
      pool.spawn(x, y, 0, 0, 0.45, r * 0.7, 3);
    }
  }

  /* ---------- screen response ---------- */
  function Screen() {
    var s = { shake: 0, flash: 0, hitstop: 0, slow: 1, rot: 0 };
    s.kick = function (mag) { if (mag > s.shake) s.shake = mag; };
    s.update = function (dt, enabled) {
      s.shake = Math.max(0, s.shake - dt * (s.shake * 6 + 1.5));
      s.flash = Math.max(0, s.flash - dt * 4.5);
      s.hitstop = Math.max(0, s.hitstop - dt);
      s.slow = OM.math.approach(s.slow, 1, 3.5, dt);
      if (!enabled) s.shake = 0;
    };
    s.apply = function (g) {
      if (s.shake > 0.01) {
        g.translate((Math.random() - 0.5) * s.shake, (Math.random() - 0.5) * s.shake);
      }
    };
    return s;
  }

  OM.fx = { Pool: Pool, Trail: Trail, death: death, Screen: Screen };
})(typeof globalThis !== 'undefined' ? globalThis : this);
