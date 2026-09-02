/* ONE MORE — death replay.
   Every death captures the last two seconds: the player's path, and the actual
   obstacles around them. It replays on the results screen in slow motion,
   framed close on the moment it went wrong.
   It answers "what killed me" honestly — and it is the clip people post. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys, PAT = OM.patterns;

  var WINDOW = 2.1;      // seconds kept
  var RATE = 60;         // samples per second
  /* The window always shows the FULL tunnel height with margin above and below
     for the caption strip. An earlier version framed tight on the player, which
     looked dramatic and answered nothing: you could not see the surface you
     failed to reach. Context is the whole point.
     Horizontal extent is derived from the canvas rather than fixed, so the
     visible width and the width used for culling can never disagree — they did,
     and the right third of the panel rendered empty. */
  var ZOOM_H = 700, PLAYER_AT = 0.42;

  /* A ring buffer on the run; costs about 130 tiny objects. */
  OM.ReplayBuffer = function () {
    var f = [], acc = 0;
    return {
      frames: f,
      sample: function (dt, r) {
        acc += dt;
        if (acc < 1 / RATE) return;
        acc = 0;
        f.push({ t: r.t, x: r.px, y: r.y, grav: r.grav, rot: r.rot });
        while (f.length && f[0].t < r.t - WINDOW) f.shift();
      }
    };
  };

  /* Freeze what mattered: the path, plus a deep copy of the geometry near the
     death so the replay cannot be invalidated by the generator moving on. */
  OM.captureDeath = function (r, cause) {
    var lo = r.px - 1500, hi = r.px + 700;
    function near(list) {
      var out = [];
      for (var i = 0; i < list.length; i++) {
        var o = list[i];
        if (o.x + (o.w || 0) < lo || o.x > hi) continue;
        var c = {};
        for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k) && k.charAt(0) !== '_') c[k] = o[k];
        out.push(c);
      }
      return out;
    }
    return {
      frames: r.replay.frames.slice(),
      obstacles: near(r.gen.obstacles),
      holes: near(r.gen.holes),
      deathT: r.t, deathX: r.px, deathY: r.y, grav: r.grav, rot: r.rot,
      cause: cause, world: r.world.id, evo: OM.progress.activeCore()
    };
  };

  var CAUSE_LABEL = {
    spike: 'SPIKES', block: 'A BLOCK', bar: 'A BAR', mover: 'A MOVER',
    laser: 'A LASER', piston: 'A PISTON', gate: 'A GATE', void: 'THE VOID'
  };
  OM.causeLabel = function (c) { return CAUSE_LABEL[c] || 'SOMETHING'; };

  /* Playback. Owns its own frame loop so it can run while the game loop is
     idle on the results screen, and stops itself the moment it is hidden. */
  OM.ReplayPlayer = function (canvas) {
    var g = canvas.getContext('2d', { alpha: false });
    var data = null, raf = 0, t0 = 0, running = false;
    var SPEED = 0.34, HOLD = 1.0;

    function size() {
      var rect = canvas.getBoundingClientRect();
      var dpr = Math.min(root.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      return canvas.height / ZOOM_H;
    }

    function frameAt(t) {
      var f = data.frames;
      if (!f.length) return null;
      if (t <= f[0].t) return f[0];
      for (var i = 1; i < f.length; i++) {
        if (f[i].t >= t) {
          var a = f[i - 1], b = f[i], m = (t - a.t) / Math.max(1e-4, b.t - a.t);
          return { t: t, x: a.x + (b.x - a.x) * m, y: a.y + (b.y - a.y) * m,
                   grav: b.grav, rot: a.rot + (b.rot - a.rot) * m };
        }
      }
      return f[f.length - 1];
    }

    function draw(now) {
      if (!running || !data) return;
      var scale = size();
      var span = Math.max(0.2, data.deathT - data.frames[0].t);
      var elapsed = (now - t0) / 1000;
      var loop = span / SPEED + HOLD;
      if (elapsed > loop) { t0 = now; elapsed = 0; }
      var dead = elapsed * SPEED >= span;
      var t = data.frames[0].t + Math.min(span, elapsed * SPEED);
      var f = frameAt(t) || { x: data.deathX, y: data.deathY, rot: 0 };

      /* One camera. Logical x is measured from the left edge of the visible
         window, which is derived from the canvas so culling and rendering can
         never disagree; logical y stays in tunnel coordinates so the shared
         renderers work unchanged. */
      var visW = canvas.width / scale;
      var camX = f.x - visW * PLAYER_AT;
      var mid = (P.CEIL + P.FLOOR) / 2;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = '#08090c';
      g.fillRect(0, 0, canvas.width, canvas.height);
      g.setTransform(scale, 0, 0, scale, 0, canvas.height / 2 - mid * scale);

      OM.render.surfaces(g, visW, camX, data.holes, t, 0.4);
      OM.render.obstacles(g, visW, camX, data.obstacles, t, { playerX: visW * PLAYER_AT });

      // the path taken, drawn up to the current moment
      g.save();
      g.strokeStyle = '#fff'; g.lineWidth = 2.2; g.globalAlpha = 0.4;
      g.beginPath();
      var started = false;
      for (var i = 0; i < data.frames.length; i++) {
        var p = data.frames[i];
        if (p.t > t) break;
        if (!started) { g.moveTo(p.x - camX, p.y); started = true; }
        else g.lineTo(p.x - camX, p.y);
      }
      g.stroke();
      g.restore();

      if (!dead) {
        OM.nanogon.draw(g, {
          x: f.x - camX, y: f.y, r: P.R_VIS, rot: f.rot,
          grav: f.grav, speed: 0.8,
          evo: data.evo, mood: 'alert', t: t, glow: 0.85, corrupt: 0
        });
      } else {
        var since = elapsed - span / SPEED;
        var burst = OM.math.clamp(1 - since / 0.6, 0, 1);
        var dx = data.deathX - camX;
        g.save();
        g.globalAlpha = burst;
        g.strokeStyle = '#fff'; g.lineWidth = 2;
        g.beginPath();
        g.arc(dx, data.deathY, 10 + (1 - burst) * 110, 0, 6.2832);
        g.stroke();
        g.fillStyle = '#fff';
        for (var k = 0; k < 12; k++) {
          var ang = k * 0.5236, d = 14 + (1 - burst) * 80;
          g.fillRect(dx + Math.cos(ang) * d - 2, data.deathY + Math.sin(ang) * d - 2, 4, 4);
        }
        g.restore();
      }

      // caption, on its own strip so it never fights the geometry behind it
      g.setTransform(1, 0, 0, 1, 0, 0);
      var fs = Math.max(9, Math.round(10 * (canvas.width / 620)));
      var strip = fs * 2.6;
      g.fillStyle = 'rgba(8,9,12,0.78)';
      g.fillRect(0, canvas.height - strip, canvas.width, strip);
      g.fillStyle = 'rgba(232,234,240,0.6)';
      g.font = '600 ' + fs + 'px ui-monospace, Menlo, monospace';
      g.textAlign = 'left';
      var baseline = canvas.height - strip / 2 + fs * 0.36;
      g.fillText('LAST MOMENTS · ' + Math.round(SPEED * 100) + '% SPEED', 12, baseline);
      g.textAlign = 'right';
      g.fillText('KILLED BY ' + OM.causeLabel(data.cause), canvas.width - 12, baseline);

      raf = root.requestAnimationFrame(draw);
    }

    return {
      load: function (d) { data = d; },
      start: function () {
        if (!data || !data.frames.length) return false;
        running = true; t0 = performance.now();
        root.cancelAnimationFrame(raf);
        raf = root.requestAnimationFrame(draw);
        return true;
      },
      stop: function () { running = false; root.cancelAnimationFrame(raf); },
      restart: function () { t0 = performance.now(); }
    };
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
