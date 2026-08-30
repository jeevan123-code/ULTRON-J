/* ONE MORE — the game.
   One input. Tap flips gravity. Everything else is consequence. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys, PAT = OM.patterns, MUT = OM.mutations, prog = OM.progress;
  var clamp = OM.math.clamp;

  var STEP = 1 / 240;            // fixed physics step: the arc must not depend on frame rate
  var DEAD_LOCKOUT = 0.22;       // s before a tap can restart, so a death tap is not a restart

  var G = OM.game = {
    canvas: null, ctx: null,
    W: 1280, H: P.H, dpr: 1,
    run: null, state: 'idle',    // idle | playing | dead
    pool: null, trail: null, screen: null,
    hint: 0
  };

  /* ---------- setup ---------- */
  G.attach = function (canvas) {
    G.canvas = canvas;
    G.ctx = canvas.getContext('2d', { alpha: false });
    G.pool = OM.fx.Pool(340);
    G.trail = OM.fx.Trail('line');
    G.screen = OM.fx.Screen();
    G.resize();
    root.addEventListener('resize', G.resize);
    if (root.visualViewport) root.visualViewport.addEventListener('resize', G.resize);
  };

  G.resize = function () {
    var c = G.canvas; if (!c) return;
    var rect = c.getBoundingClientRect();
    var cw = Math.max(1, rect.width), ch = Math.max(1, rect.height);
    G.dpr = Math.min(root.devicePixelRatio || 1, 2.5);
    c.width = Math.round(cw * G.dpr);
    c.height = Math.round(ch * G.dpr);
    var pxW = c.width, pxH = c.height;

    /* The tunnel is a fixed 720 logical units tall on every device, so the
       vertical challenge is identical everywhere. Only the horizontal view
       varies — how far ahead you can read — and it is clamped at both ends so a
       phone is playable and an ultrawide monitor is not an advantage.
       Fit by width, then never let the tunnel crop vertically. On a portrait
       phone that leaves the tunnel as a band in the middle of the screen, which
       is the correct answer: cropping it would put the player off-screen. */
    G.W = clamp(Math.round(P.H * (cw / ch)), 640, 1500);
    G.scale = pxW / G.W;
    if (G.scale * P.H > pxH) G.scale = pxH / P.H;
    G.offX = (pxW - G.W * G.scale) / 2;
    G.offY = (pxH - P.H * G.scale) / 2;
    G.viewTop = -G.offY / G.scale;
    G.viewBottom = (pxH - G.offY) / G.scale;

    /* Lookahead fairness. The player reads the world in the space in front of
       them, which is (1 - x) * W. On a wide screen 0.27 leaves a full second of
       warning at top speed; on a narrow one that same fraction would leave under
       half a second, so the character shifts left to buy the distance back.
       Nobody should be worse at this game for holding their phone upright. */
    G.playerXFrac = G.W < 900 ? 0.18 : P.PLAYER_X_FRAC;
    G.portrait = cw < ch;
  };

  /* ---------- run lifecycle ---------- */
  G.start = function (mode, opts) {
    opts = opts || {};
    var day = mode === 'daily' ? (opts.day == null ? OM.dayIndex() : opts.day) : 0;
    var seed = mode === 'daily' ? OM.hashSeed('onemore-' + OM.dayKey(day))
                                : (Math.random() * 0xffffffff) >>> 0;
    var rng = OM.rng(seed);

    var ghostData = null;
    if (mode === 'endless') ghostData = prog.data.ghost;
    else if (prog.data.dailyGhost && prog.data.dailyGhost.key === OM.dayKey(day)) {
      ghostData = prog.data.dailyGhost.data;
    }

    var target = mode === 'endless' ? prog.data.best : (prog.data.daily[OM.dayKey(day)] || 0);

    G.run = {
      mode: mode, day: day, seed: seed, rng: rng,
      gen: OM.Generator(OM.rng(seed ^ 0x9e3779b9)),
      sched: MUT.schedule(OM.rng(seed ^ 0x85ebca6b)),
      t: 0, px: 0, speed: P.speedAt(0),
      y: P.FLOOR - P.R, vy: 0, grav: 1, grounded: true,
      rot: 0, rotTarget: 0,
      flips: 0, nearMiss: 0, perfect: 0,
      sinceFlip: 99, sinceNear: 99, sinceRecord: 99, deadFor: 0,
      dead: false, cause: null, threat: 0,
      world: P.WORLDS[0], worldFlash: 0, mutFlash: 0, mutLabel: null,
      target: target, beat: false,
      rec: OM.GhostRecorder(),
      ghost: OM.GhostPlayer(ghostData),
      mods: MUT.activeAt([], 0)
    };
    G.trail.clear();
    G.pool.clear();
    G.screen.shake = 0; G.screen.flash = 0; G.screen.slow = 1;
    G.trail.style = prog.data.cosmetics.trail;
    G.state = 'playing';
    G.hint = prog.data.seen.tutorial ? 0 : 3.2;
    OM.audio.unlock();
    OM.bus.emit('run:start', G.run);
  };

  G.flip = function () {
    if (G.state === 'playing') {
      var r = G.run;
      if (r.dead) return;
      r.grav = -r.grav;
      r.grounded = false;
      r.flips++;
      r.sinceFlip = 0;
      r.rotTarget += Math.PI;
      G.screen.kick(3);
      OM.audio.play('flip', r.grav);
      if (prog.data.settings.haptics && root.navigator && root.navigator.vibrate) {
        try { root.navigator.vibrate(8); } catch (e) {}
      }
      if (!prog.data.seen.tutorial) { prog.data.seen.tutorial = true; prog.touch(); G.hint = 0; }
      return true;
    }
    if (G.state === 'dead' && G.run.deadFor > DEAD_LOCKOUT) {
      OM.bus.emit('run:again', G.run.mode);
      return true;
    }
    return false;
  };

  function die(cause) {
    var r = G.run;
    if (r.dead) return;
    r.dead = true; r.cause = cause; r.deadFor = 0;
    G.state = 'dead';
    G.screen.kick(24);
    G.screen.flash = 1;
    G.screen.hitstop = 0.11;
    OM.audio.play('death');
    OM.audio.stopMusic();
    if (prog.data.settings.haptics && root.navigator && root.navigator.vibrate) {
      try { root.navigator.vibrate([12, 40, 26]); } catch (e) {}
    }
    OM.fx.death(G.pool, prog.data.cosmetics.death, G.playerScreenX(), r.y, P.R_VIS);

    var summary = {
      mode: r.mode, day: r.day, time: r.t, cause: cause,
      nearMiss: r.nearMiss, perfect: r.perfect, flips: r.flips,
      world: r.world, ghost: r.rec.finish(), seed: r.seed
    };
    summary.result = prog.commitRun(summary);
    r.summary = summary;
    if (summary.result.record) OM.audio.play('record');
    OM.bus.emit('run:end', summary);
  }

  G.playerScreenX = function () { return G.W * (G.playerXFrac || P.PLAYER_X_FRAC); };

  /* Advances the simulation with no rendering. tools/playtest.js drives an
     automated player through this, so hours of game can be measured in seconds
     and the difficulty curve is a number rather than an opinion. */
  G.stepHeadless = function (dt) { if (G.state === 'playing') simulate(dt); };

  /* ---------- simulation ---------- */
  function simulate(dt) {
    var r = G.run;

    // mutations first: they set speed and density for this instant
    var mods = MUT.activeAt(r.sched, r.t);
    if (mods.list.length !== r.mods.list.length) {
      if (mods.list.length > r.mods.list.length) {
        var fresh = mods.list[mods.list.length - 1];
        r.mutFlash = 1.6; r.mutLabel = fresh.m;
        OM.audio.play('mutation');
        G.screen.kick(9);
      }
    }
    r.mods = mods;

    r.t += dt;
    r.speed = P.speedAt(r.t) * mods.speed;
    var g = P.gravityFor(r.speed, 1);

    var world = P.worldAt(r.t);
    if (world.id !== r.world.id) {
      r.world = world; r.worldFlash = 2.4;
      OM.audio.play('world');
      G.screen.kick(12);
    }

    r.sinceFlip += dt; r.sinceNear += dt; r.sinceRecord += dt;

    // the record-approach moment: strip the music, tell the player nothing but
    // the gap. This is the whole "five seconds. I can beat that." loop.
    if (!r.beat && r.target > 8 && r.t > r.target) {
      r.beat = true; r.sinceRecord = 0;
      OM.audio.play('record');
      G.screen.flash = 0.55;
      OM.bus.emit('run:passed-best', r);
    }

    // integrate in fixed sub-steps
    var remaining = dt;
    while (remaining > 0) {
      var h = Math.min(STEP, remaining);
      remaining -= h;
      r.px += r.speed * h;
      var out = P.stepPlayer(r, h, g, r.px, r.gen.holes);
      if (out === 'void') { die('void'); return; }
      if (r.grounded && r.vy === 0 && r.sinceFlip < 0.05) OM.audio.play('land');
    }

    r.gen.ensure(r.px + G.W + 700, r.t, mods.spacing);
    r.gen.prune(r.px - G.W * 0.6);

    // collision + near miss
    var px = r.px, py = r.y, R = P.R, R2 = R * R;
    var nearD = P.NEAR_MISS_DIST, nearD2 = (R + nearD) * (R + nearD);
    var list = r.gen.obstacles, scratch = [];
    for (var i = 0; i < list.length; i++) {
      var o = list[i];
      if (o.x > px + 90 || o.x + (o.w || 0) < px - 90) continue;
      scratch.length = 0;
      var rects = PAT.rectsOf(o, r.t, scratch);
      for (var j = 0; j < rects.length; j++) {
        var q = rects[j];
        var d2 = P.circleRectDist2(px, py, R, q.x, q.y, q.w, q.h);
        if (d2 <= R2) { die(o.t); return; }
        if (d2 < nearD2 && !o._nm) {
          o._nm = true;
          r.nearMiss++;
          r.sinceNear = 0;
          var perfect = r.sinceFlip < P.PERFECT_WINDOW;
          if (perfect) { r.perfect++; OM.audio.play('perfect'); G.screen.slow = 0.55; }
          else OM.audio.play('near');
          G.screen.kick(perfect ? 7 : 3);
          OM.bus.emit('run:near', { perfect: perfect, clear: Math.sqrt(d2) - R });
        }
      }
    }

    r.threat = OM.render.threatOf(list, r.px - G.playerScreenX(), G.playerScreenX(), G.W);
    r.rec.sample(dt, r.px, r.y, r.grav);

    // rotation eases toward the flip target — instant response, visible follow-through
    r.rot = OM.math.approach(r.rot, r.rotTarget, 17, dt);

    // adaptive music: intensity from survival, silence when a record is in reach
    var closeToBest = r.target > 12 && !r.beat && (r.target - r.t) < 6 && (r.target - r.t) > 0;
    OM.audio.music(clamp(r.t / 170, 0, 1), closeToBest);
  }

  /* ---------- frame ---------- */
  G.tick = function (dt) {
    var r = G.run;
    G.screen.update(dt, prog.data.settings.shake && !prog.data.settings.reduced);
    if (!r) return;

    if (G.state === 'playing') {
      var sdt = dt * G.screen.slow;
      if (G.screen.hitstop > 0) sdt = 0;
      if (sdt > 0) simulate(Math.min(sdt, 0.05));
      // The trail lives in screen space but the world scrolls under it, so old
      // points have to drift left at world speed. Without this the trail is a
      // vertical wire hanging off the character instead of a path behind it.
      G.trail.shift(r.speed * sdt);
      G.trail.push(G.playerScreenX(), r.y, r.t);
    } else if (G.state === 'dead') {
      r.deadFor += dt;
    }
    G.pool.update(dt, G.state === 'dead' ? 0 : r.speed * 0.35);
    if (r.worldFlash > 0) r.worldFlash -= dt;
    if (r.mutFlash > 0) r.mutFlash -= dt;
    if (G.hint > 0) G.hint -= dt;
    G.draw();
  };

  G.draw = function () {
    var g = G.ctx, r = G.run;
    if (!g) return;
    var corrupt = r ? P.corruptionAt(r.t) : 0;
    var mods = r ? r.mods : { mirror: false, drift: 0, vision: 0, fade: false, strobe: false, silence: false };

    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = '#08090c';
    g.fillRect(0, 0, G.canvas.width, G.canvas.height);
    g.setTransform(G.scale, 0, 0, G.scale, G.offX, G.offY);

    if (!r) { drawIdle(g); return; }

    var camX = r.px - G.playerScreenX();

    g.save();
    G.screen.apply(g);
    if (mods.drift) {                          // DRIFT: the frame comes loose
      g.translate(G.W / 2, P.H / 2);
      g.rotate(Math.sin(r.t * 1.1) * mods.drift);
      g.translate(-G.W / 2, -P.H / 2);
    }
    if (mods.mirror) {                         // MIRROR: up is down
      g.translate(0, P.CEIL + P.FLOOR);
      g.scale(1, -1);
    }

    OM.render.backdrop(g, G.W, P.H, r.world.id, r.t, corrupt, clamp(r.t / 200, 0, 1));
    OM.render.surfaces(g, G.W, camX, r.gen.holes, r.t, clamp(r.t / 200, 0, 1));
    OM.render.obstacles(g, G.W, camX, r.gen.obstacles, r.t, {
      fade: mods.fade, strobe: mods.strobe, vision: mods.vision, playerX: G.playerScreenX()
    });

    drawGhost(g, r, camX);

    G.trail.draw(g, prog.data.cosmetics.trail, clamp(r.t / 150, 0, 1), corrupt);
    G.pool.draw(g);

    if (!r.dead) {
      OM.nanogon.draw(g, {
        x: G.playerScreenX(), y: r.y, r: P.R_VIS, rot: r.rot,
        evo: prog.activeCore(),
        mood: OM.nanogon.moodFor({
          dead: false, sinceNear: r.sinceNear, sinceRecord: r.sinceRecord,
          threat: r.threat, speedFrac: clamp((r.speed - P.BASE_SPEED) / 500, 0, 1)
        }),
        t: r.t, glow: clamp(0.2 + r.threat * 0.5 + (r.sinceNear < 0.3 ? 0.8 : 0), 0, 1.4),
        corrupt: corrupt
      });
    }
    g.restore();

    // vignette for DARK, and the corruption bloom
    if (mods.vision) {
      var grd = g.createRadialGradient(G.playerScreenX(), r.y, mods.vision * 0.35,
                                       G.playerScreenX(), r.y, mods.vision * 1.5);
      grd.addColorStop(0, 'rgba(8,9,12,0)');
      grd.addColorStop(1, 'rgba(8,9,12,0.97)');
      g.fillStyle = grd;
      g.fillRect(0, G.viewTop, G.W, G.viewBottom - G.viewTop);
    }
    if (G.screen.flash > 0.01) {
      g.fillStyle = 'rgba(255,255,255,' + (G.screen.flash * 0.5).toFixed(3) + ')';
      g.fillRect(0, G.viewTop, G.W, G.viewBottom - G.viewTop);
    }

    drawHud(g, r, corrupt, mods);
  };

  function drawGhost(g, r, camX) {
    if (!r.ghost) return;
    var s = r.ghost.at(r.t);
    if (s.done) return;
    var gx = s.x - camX;
    if (gx > -60 && gx < G.W + 60) {
      OM.nanogon.drawGhost(g, gx, s.y, P.R_VIS, 0, 0.30);
    } else {
      // off-screen: show the gap as an edge marker, because "0.8s behind" is
      // the entire point of racing yourself
      var right = gx > 0;
      var x = right ? G.W - 16 : 16;
      g.save();
      g.globalAlpha = 0.34;
      g.fillStyle = '#fff';
      g.beginPath();
      g.moveTo(x + (right ? 10 : -10), s.y);
      g.lineTo(x, s.y - 9); g.lineTo(x, s.y + 9);
      g.closePath(); g.fill();
      g.restore();
    }
  }

  function jitterText(str, corrupt) {
    if (corrupt < 0.25 || Math.random() > corrupt * 0.09) return str;
    var i = Math.floor(Math.random() * str.length);
    var glyphs = '0123456789:.#/\\';
    return str.slice(0, i) + glyphs[Math.floor(Math.random() * glyphs.length)] + str.slice(i + 1);
  }

  function drawHud(g, r, corrupt, mods) {
    g.save();
    g.textAlign = 'center';
    g.fillStyle = '#fff';

    if (!mods.silence) {
      var label = jitterText(OM.fmtTime(r.t, 2), corrupt);
      var jy = corrupt > 0.4 && Math.random() < corrupt * 0.1 ? (Math.random() - 0.5) * 6 : 0;
      g.globalAlpha = r.dead ? 0.35 : 0.95;
      g.font = '600 42px ui-monospace, SFMono-Regular, Menlo, monospace';
      g.fillText(label, G.W / 2, 58 + jy);

      // the gap to your record — the number that produces "one more"
      if (r.target > 8 && !r.dead) {
        g.font = '500 15px ui-monospace, Menlo, monospace';
        g.globalAlpha = 0.55;
        if (r.beat) g.fillText('BEST BEATEN  +' + OM.fmtDelta(r.t - r.target), G.W / 2, 80);
        else g.fillText(OM.fmtDelta(r.target - r.t) + ' TO BEAT', G.W / 2, 80);
      }
    }

    if (r.worldFlash > 0) {
      g.globalAlpha = clamp(r.worldFlash, 0, 1) * 0.9;
      g.font = '600 22px ui-sans-serif, system-ui, sans-serif';
      g.fillText(r.world.name, G.W / 2, P.H / 2 - 26);
      g.font = '400 13px ui-sans-serif, system-ui, sans-serif';
      g.globalAlpha *= 0.6;
      g.fillText(r.world.line, G.W / 2, P.H / 2 - 4);
    }

    // Announcements sit below the world flash and never at the height the
    // player actually travels at; the persistent label lives under the floor
    // line, outside the tunnel entirely.
    if (r.mutFlash > 0 && r.mutLabel) {
      g.globalAlpha = clamp(r.mutFlash, 0, 1) * 0.95;
      g.font = '600 26px ui-sans-serif, system-ui, sans-serif';
      g.fillText(r.mutLabel.name, G.W / 2, P.H / 2 + 74);
      g.font = '400 13px ui-sans-serif, system-ui, sans-serif';
      g.globalAlpha *= 0.6;
      g.fillText(r.mutLabel.line, G.W / 2, P.H / 2 + 96);
    }
    if (mods.list.length && !mods.silence) {
      g.globalAlpha = 0.45;
      g.font = '500 12px ui-monospace, Menlo, monospace';
      var names = mods.list.map(function (s) { return s.m.name; }).join('   ');
      g.fillText(names, G.W / 2, P.H - 10);
    }

    if (G.hint > 0 && !r.dead) {
      g.globalAlpha = clamp(G.hint / 3.2, 0, 1) * (0.55 + Math.sin(r.t * 5) * 0.25);
      g.font = '600 20px ui-sans-serif, system-ui, sans-serif';
      g.fillText('TAP TO FLIP GRAVITY', G.W / 2, r.y + (r.grav > 0 ? -60 : 66));
    }
    g.restore();
  }

  function drawIdle(g) {
    OM.render.backdrop(g, G.W, P.H, 'origin', performance.now() / 1000, 0, 0);
  }

  /* Attract mode. Rather than pose the character next to a logo, the menu
     quietly plays the game: an empty tunnel, and a Nanogon flipping between the
     surfaces on a slow rhythm. Anyone watching for two seconds has already been
     taught the entire control scheme. */
  var attract = null;
  G.drawMenuNanogon = function (t) {
    var g = G.ctx;
    if (!g) return;
    if (!attract) {
      attract = { y: P.FLOOR - P.R, vy: 0, grav: 1, grounded: true, rot: 0, rotT: 0,
                  next: 1.2, last: t, x: 0, trail: OM.fx.Trail('line') };
    }
    var dt = Math.min(0.05, Math.max(0, t - attract.last));
    attract.last = t;
    var speed = P.BASE_SPEED * 0.8, gg = P.gravityFor(speed, 1);
    attract.x += speed * dt;
    attract.next -= dt;
    if (attract.next <= 0) {
      attract.grav = -attract.grav;
      attract.grounded = false;
      attract.rotT += Math.PI;
      attract.next = 1.15 + Math.random() * 0.7;
    }
    var left = dt;
    while (left > 0) { var h = Math.min(1 / 240, left); left -= h; P.stepPlayer(attract, h, gg, 0, []); }
    attract.rot = OM.math.approach(attract.rot, attract.rotT, 15, dt);

    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = '#08090c';
    g.fillRect(0, 0, G.canvas.width, G.canvas.height);
    g.setTransform(G.scale, 0, 0, G.scale, G.offX, G.offY);
    OM.render.backdrop(g, G.W, P.H, 'origin', t, 0, 0);
    OM.render.surfaces(g, G.W, attract.x, [], t, 0.2);
    var px = G.W * 0.72;                 // clear of the title
    attract.trail.shift(speed * dt);
    attract.trail.push(px, attract.y, t);
    attract.trail.draw(g, prog.data.cosmetics.trail, 0.25, 0);
    OM.nanogon.draw(g, {
      x: px, y: attract.y, r: P.R_VIS * 1.5, rot: attract.rot,
      evo: prog.activeCore(), mood: 'neutral', t: t, glow: 0.45, corrupt: 0
    });
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
