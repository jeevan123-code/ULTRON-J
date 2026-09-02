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
    hint: 0, praise: 0
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
    /* Every mode except daily has thrown its seed away until now, which meant a
       run you had just learned something from could never be played again. A
       retry passes the old seed back in and gets the identical world: the
       generator and the mutation schedule are pure functions of it, so nothing
       about the layout has to be stored or trusted — if a retry ever diverged,
       determinism would already be broken and worth finding out. */
    var seed = mode === 'daily' ? OM.hashSeed('onemore-' + OM.dayKey(day))
             : opts.seed != null ? (opts.seed >>> 0)
             : (Math.random() * 0xffffffff) >>> 0;
    var rng = OM.rng(seed);

    /* A Trial is a run built mostly from the patterns you actually fail, and it
       starts past the tutorial band because you are not here to be taught. */
    var pool = opts.pool || null, tBias = 0, family = opts.family || null;
    /* Practice: one fixed speed, no ramp, no mutations. The mutations are out
       because SURGE and DRAG are speed multipliers, and a mode whose whole point
       is a single known speed cannot have two of them wandering off it. */
    var fixed = mode === 'practice' ? P.PRACTICE_SPEED : 0;
    if (mode === 'practice') {
      /* Static geometry only, and this is the whole safety argument for the
         mode. A static pattern is fixed in space and so is the flip arc, so the
         line that survives it is the same line at any speed — and the flip
         cooldown, being a fixed number of seconds, covers fewer pixels the
         slower you go, so the line only gets easier to execute. Every one of
         these 41 is therefore already proven at 335 by the run that proved it
         at 911.
         The 19 time-driven ones have no such guarantee: their phase advances
         further over the same stretch of tunnel at a lower speed, so they are a
         different problem that has not been proven, and they stay out. */
      if (!pool) pool = PAT.staticList.slice();
      /* Same as a Trial: start past the tutorial band. Practice is unlocked
         after five runs, so nobody arrives here needing to be taught what a
         spike is — and at this speed the opening tiers are close to empty. */
      tBias = 30;
    } else if (mode === 'trial') {
      /* A retry carries the pool rather than recomputing it. The pool is derived
         from the death log, and the run being retried has already added to that
         log — recomputing would quietly hand back a different world. */
      if (!pool) pool = OM.analysis.trialPatterns(family);
      tBias = 30;
    } else if (mode === 'nightmare') {
      /* Starts where the endless run ends. No runway, no tier-one warm-up, top
         speed from the first second — the mode that exists so a good player has
         somewhere left to go. */
      tBias = 245;
    }

    /* A retry races the attempt it repeats, not your all-time best. On the same
       world that is the only comparison that teaches anything: here is where you
       were last time, and here is where it went wrong. */
    var ghostData = null;
    if (opts.ghost) ghostData = opts.ghost;
    else if (mode === 'endless') ghostData = prog.data.ghost;
    else if (mode === 'trial' || mode === 'practice') ghostData = null;
    else if (prog.data.dailyGhost && prog.data.dailyGhost.key === OM.dayKey(day)) {
      ghostData = prog.data.dailyGhost.data;
    }

    var target = mode === 'endless' ? prog.data.best
               : mode === 'trial' ? (prog.data.trial[family] || 0)
               : mode === 'nightmare' ? prog.data.nightmare
               : mode === 'practice' ? prog.data.practice
               : (prog.data.daily[OM.dayKey(day)] || 0);

    G.run = {
      mode: mode, day: day, seed: seed, rng: rng, pool: pool,
      gen: OM.Generator(OM.rng(seed ^ 0x9e3779b9), { pool: pool, startX: mode === 'nightmare' ? 620 : undefined }),
      tBias: tBias, family: family,
      sched: fixed ? [] : MUT.schedule(OM.rng(seed ^ 0x85ebca6b)),
      /* Its own stream, so whether the sky does something never shifts the
         mutation schedule or the world layout by a single call. */
      dream: OM.dream.Director(OM.rng(seed ^ 0xc2b2ae35)),
      fixed: fixed,
      t: 0, px: 0, speed: fixed || P.speedAt(tBias > 100 ? 200 : 0),
      y: P.FLOOR - P.R, vy: 0, grav: 1, grounded: true,
      rot: 0, rotTarget: 0, rotKick: 0, coreFlash: 0,
      squash: 0, wasGrounded: true, lastVy: 0, marks: [],
      flips: 0, nearMiss: 0, perfect: 0,
      sinceFlip: 99, sinceNear: 99, sinceRecord: 99, deadFor: 0,
      dead: false, cause: null, threat: 0,
      world: P.worldAt(tBias > 100 ? tBias : 0), worldFlash: 0, mutFlash: 0, mutLabel: null,
      target: target, beat: false,
      rec: OM.GhostRecorder(),
      replay: OM.ReplayBuffer(),
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
      /* Overshoot, not anticipation. A wind-up before the turn would be the one
         thing this game cannot afford — the tap has to move the character on
         the same frame it arrives. So the snap is on the far side: the rotation
         runs past its target and settles back, which reads as weight without
         costing a millisecond of response. */
      r.rotKick = 0.30;
      G.screen.kick(3.5);
      r.squash = -0.45;                        // stretch along the new direction
      var fx = G.playerScreenX();
      G.pool.spawn(fx, r.y, 0, 0, 0.22, P.R_VIS * 0.9, 3);
      for (var b = 0; b < 5; b++) {
        G.pool.spawn(fx, r.y, (Math.random() - 0.5) * 90 - r.speed * 0.1,
                     -r.grav * (110 + Math.random() * 130), 0.2 + Math.random() * 0.2, 1.6, 0);
      }
      OM.audio.play('flip', r.grav);
      if (prog.data.settings.haptics && root.navigator && root.navigator.vibrate) {
        try { root.navigator.vibrate(8); } catch (e) {}
      }
      if (!prog.data.seen.tutorial) {
        prog.data.seen.tutorial = true; prog.touch();
        G.hint = 0; G.praise = 1.1;          // acknowledge the first input, once
      }
      return true;
    }
    if (G.state === 'dead' && G.run.deadFor > DEAD_LOCKOUT) {
      OM.bus.emit('run:again', G.run.mode);
      return true;
    }
    return false;
  };

  /* One collision and near-miss pass at a single instant. Returns the cause of
     death, or null.
     Near misses fire once per obstacle through the _nm flag, so running this at
     240Hz does not inflate the count — it only makes the moment of detection
     accurate, and that moment is what PERFECT is judged against. */
  var SCAN = [];
  function scanObstacles(r, near, t) {
    var px = r.px, py = r.y, R = P.R, R2 = R * R;
    var nearD2 = (R + P.NEAR_MISS_DIST) * (R + P.NEAR_MISS_DIST);
    for (var i = 0; i < near.length; i++) {
      var o = near[i];
      SCAN.length = 0;
      var rects = PAT.rectsOf(o, t, SCAN);
      for (var j = 0; j < rects.length; j++) {
        var q = rects[j];
        var d2 = P.circleRectDist2(px, py, R, q.x, q.y, q.w, q.h);
        if (d2 <= R2) return o.t;
        if (d2 < nearD2 && !o._nm) {
          o._nm = true;
          o._flash = 1;
          r.nearMiss++;
          r.sinceNear = 0;
          var perfect = r.sinceFlip < P.PERFECT_WINDOW;
          if (perfect) {
            r.perfect++; OM.audio.play('perfect'); G.screen.slow = 0.55;
            /* The moment the game is proudest of, so it gets its own shape: a
               ring that leaves the character rather than debris that falls off
               it, and a core flash the shell cannot produce on its own. */
            G.pool.spawn(G.playerScreenX(), r.y, 0, 0, 0.42, P.R_VIS * 1.3, 3);
            r.coreFlash = 1;
          } else {
            OM.audio.play('near');
            r.coreFlash = Math.max(r.coreFlash, 0.55);
          }
          G.screen.kick(perfect ? 7 : 3);
          OM.bus.emit('run:near', { perfect: perfect, clear: Math.sqrt(d2) - R });
        }
      }
    }
    return null;
  }

  /* Arrival matters as much as departure. A flip that ends in a soundless,
     motionless stop reads as the character being teleported onto the surface;
     the compression, the dust and the mark on the floor are what make it read
     as landing. Strength scales with impact speed so a short hop and a full
     ceiling-to-floor drop do not feel the same. */
  function land(r, v) {
    var f = clamp(v / 1900, 0.15, 1);
    r.squash = f;
    var sx = G.playerScreenX();
    var surfY = r.grav > 0 ? P.FLOOR : P.CEIL;
    var dir = r.grav > 0 ? -1 : 1;
    for (var i = 0; i < 4 + Math.round(f * 9); i++) {
      var a = (Math.random() - 0.5) * 2.2;
      G.pool.spawn(sx + (Math.random() - 0.5) * 16, surfY + dir * 3,
                   Math.sin(a) * 190 * f - r.speed * 0.12, dir * Math.abs(Math.cos(a)) * 150 * f,
                   0.22 + Math.random() * 0.34, 1 + Math.random() * 2.4, 0);
    }
    G.pool.spawn(sx, surfY + dir * 4, 0, 0, 0.26, 6 + f * 10, 3);
    r.marks.push({ x: r.px, side: r.grav > 0 ? 'floor' : 'ceil', life: 0.5, f: f });
    if (r.marks.length > 10) r.marks.shift();
    G.screen.kick(2 + f * 7);
    OM.audio.play('land', f);
  }

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
      mode: r.mode, day: r.day, family: r.family, time: r.t, cause: cause,
      nearMiss: r.nearMiss, perfect: r.perfect, flips: r.flips,
      world: r.world, ghost: r.rec.finish(), seed: r.seed, pool: r.pool,
      /* The record this run was chasing, chosen once when the run started.
         The results screen used to re-derive it from the mode and got it wrong
         for every mode that is not endless or daily. */
      target: r.target,
      replay: OM.captureDeath(r, cause),
      /* Context for the death analysis: what killed you is far less useful than
         what you were doing when it did. */
      context: {
        pat: patternIdAt(r),
        speed: r.speed,
        airborne: !r.grounded,
        grav: r.grav,
        sinceFlip: r.sinceFlip,
        mutations: r.mods.list.map(function (m) { return m.m.id; }),
        worldId: r.world.id,
        flipRate: r.flips / Math.max(1, r.t)
      }
    };
    summary.result = prog.commitRun(summary);
    r.summary = summary;
    if (summary.result.record) OM.audio.play('record');
    OM.bus.emit('run:end', summary);
  }

  G.playerScreenX = function () { return G.W * (G.playerXFrac || P.PLAYER_X_FRAC); };

  /* Which authored pattern was the player inside when it ended? This is the
     single most useful fact for telling somebody what they are bad at.
     It returns a pattern ID. It was called patternTierAt and its result was
     stored as context.tier, which is what the next person would have believed. */
  function patternIdAt(r) {
    var best = null, bestD = 1e9;
    for (var i = 0; i < r.gen.obstacles.length; i++) {
      var o = r.gen.obstacles[i];
      var d = Math.abs(o.x + (o.w || 0) / 2 - r.px);
      if (d < bestD) { bestD = d; best = o; }
    }
    return best && bestD < 600 ? best.pat : null;
  }

  /* Advances the simulation with no rendering. tools/playtest.js drives an
     automated player through this, so hours of game can be measured in seconds
     and the difficulty curve is a number rather than an opinion. */
  G.stepHeadless = function (dt) { if (G.state === 'playing') simulate(dt); };

  /* ---------- simulation ---------- */
  function simulate(dt) {
    var r = G.run;

    // mutations first: they set speed and density for this instant
    /* Mutations can now overlap, so "the newest one is last in the list" is no
       longer true — the list is ordered by start time, not by recency. Announce
       whichever entry was not active last frame. */
    var mods = MUT.activeAt(r.sched, r.t);
    for (var mi = 0; mi < mods.list.length; mi++) {
      if (r.mods.list.indexOf(mods.list[mi]) < 0) {
        r.mutFlash = 1.6; r.mutLabel = mods.list[mi].m;
        OM.audio.play('mutation');
        G.screen.kick(9);
      }
    }
    r.mods = mods;

    r.t += dt;
    r.speed = r.fixed || P.speedAt(r.t + (r.tBias > 100 ? r.tBias : 0)) * mods.speed;
    var g = P.gravityFor(r.speed, 1);

    var world = P.worldAt(r.t + (r.tBias > 100 ? r.tBias : 0));
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

    /* Obstacles are tested INSIDE the substep loop, at 240Hz, alongside the
       surfaces. Testing them once per frame against the post-frame position let
       a fast player cross a floating obstacle entirely between samples, and let
       anyone clip a corner unnoticed — which also made the outcome depend on
       frame rate. Measured before this change: a 196px bar at 1218px/s with a
       50ms frame was passed through 72 times out of 72.

       The candidate list is filtered once per frame rather than per substep: the
       player advances at most speed*dt in x, so widening the window by that much
       covers every substep without rescanning the whole world twelve times. */
    r.gen.ensure(r.px + G.W + 700, r.t + r.tBias, mods.spacing);
    r.gen.prune(r.px - G.W * 0.6);
    var list = r.gen.obstacles;
    var reach = r.speed * dt + 90;
    var near = [];
    for (var ni = 0; ni < list.length; ni++) {
      var no = list[ni];
      if (no.x > r.px + reach || no.x + (no.w || 0) < r.px - reach) continue;
      near.push(no);
    }

    // integrate in fixed sub-steps
    var remaining = dt, landedAt = 0;
    var tSub = r.t - dt;                  // r.t advanced above; walk it back
    while (remaining > 0) {
      var h = Math.min(STEP, remaining);
      remaining -= h;
      r.px += r.speed * h;
      tSub += h;                          // moving geometry sampled where it IS
      var vBefore = r.vy;
      var out = P.stepPlayer(r, h, g, r.px, r.gen.holes);
      /* Report the substep the run actually ended on, not the end of the frame
         that contained it. r.t is advanced once per frame, so without this a
         player at 30fps banks up to 33ms of survival they did not earn, and the
         same death scores differently on different hardware. */
      if (out === 'void') { r.t = tSub; die('void'); return; }
      if (r.grounded && !r.wasGrounded) landedAt = Math.abs(vBefore);
      r.wasGrounded = r.grounded;
      var cause = scanObstacles(r, near, tSub);
      if (cause) { r.t = tSub; die(cause); return; }
    }
    if (landedAt > 240) land(r, landedAt);

    // audible tell for pistons about to fire near you
    for (var pi = 0; pi < list.length; pi++) {
      var po = list[pi];
      if (po.t !== 'piston') continue;
      var d = po.x - r.px;
      if (d < -120 || d > G.W * 0.55) { po._fired = false; continue; }
      var ext = PAT.pistonExt(po, r.t);
      if (ext > 8 && !po._fired) {
        po._fired = true;
        OM.audio.play('piston', clamp(1 - d / (G.W * 0.55), 0, 1));
      } else if (ext <= 0.5) po._fired = false;
    }

    /* Every announcement timer decays on GAME time, inside the simulation.
       Decaying them on frame time in tick() meant a paused or fast-forwarded
       game left world cards and mutation banners frozen on screen. */
    if (G.hint > 0) G.hint -= dt;
    if (G.praise > 0) G.praise -= dt;
    if (r.worldFlash > 0) r.worldFlash -= dt;
    if (r.mutFlash > 0) r.mutFlash -= dt;
    r.squash = OM.math.approach(r.squash, 0, 11, dt);
    for (var m = r.marks.length - 1; m >= 0; m--) {
      r.marks[m].life -= dt;
      if (r.marks[m].life <= 0) r.marks.splice(m, 1);
    }
    for (var fl = 0; fl < list.length; fl++) {
      if (list[fl]._flash > 0) list[fl]._flash = Math.max(0, list[fl]._flash - dt * 2.6);
    }
    r.threat = OM.render.threatOf(list, r.px - G.playerScreenX(), G.playerScreenX(), G.W);
    r.rec.sample(dt, r.px, r.y, r.grav);
    r.replay.sample(dt, r);

    // rotation eases toward the flip target — instant response, visible follow-through
    r.dream.update(dt, r, OM.visual.sample(r, P));
    r.rotKick = OM.math.approach(r.rotKick, 0, 9, dt);
    r.coreFlash = Math.max(0, r.coreFlash - dt * 3.6);
    r.rot = OM.math.approach(r.rot, r.rotTarget + r.rotKick, 17, dt);

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
    G.pool.update(dt, G.state === 'dead' ? 0 : r.speed);
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

    /* One read of the run for every visual system in the frame, so the
       backdrop, the streaks, the trail and the character cannot disagree about
       how far into the escalation this moment is. */
    var vis = OM.visual.sample(r, P);
    var speedFrac = vis.speed;
    OM.render.backdrop(g, G.W, P.H, r.world.id, r.t, corrupt, speedFrac, vis);
    /* Background structures, then the haze that sits between them and the
       tunnel. Seeded from the run so a retry and a Daily rebuild the same
       skyline — a background that drifted would make "the identical world" a
       lie in the one place the player would actually notice it. */
    OM.architecture.draw(g, G.W, r.world.id, camX, r.t, r.seed, vis);
    r.dream.draw(g, G.W, P.H);
    OM.render.haze(g, G.W, vis);
    OM.render.speedLines(g, G.W, camX, r.y, speedFrac);
    OM.render.surfaces(g, G.W, camX, r.gen.holes, r.t, speedFrac);
    OM.render.contactLight(g, G.playerScreenX(), r.y, r.coreFlash, vis.q);
    drawMarks(g, r, camX);
    OM.render.obstacles(g, G.W, camX, r.gen.obstacles, r.t, {
      fade: mods.fade, strobe: mods.strobe, vision: mods.vision, playerX: G.playerScreenX()
    });

    drawGhost(g, r, camX);

    /* The trail's job is to make speed legible without a speedometer, so it is
       driven by how fast the world is actually moving and only topped up by how
       long you have been in it. */
    G.trail.draw(g, prog.data.cosmetics.trail,
                 clamp(vis.speed * 0.75 + vis.intensity * 0.25, 0, 1), corrupt);
    G.pool.draw(g);

    if (!r.dead) {
      var sq = r.squash;
      OM.nanogon.draw(g, {
        x: G.playerScreenX(), y: r.y, r: P.R_VIS, rot: r.rot,
        sx: 1 - sq * 0.30, sy: 1 + sq * 0.34,
        grav: r.grav, speed: vis.speed, q: vis.q,
        evo: prog.activeCore(),
        mood: OM.nanogon.moodFor({
          dead: false, sinceNear: r.sinceNear, sinceRecord: r.sinceRecord,
          threat: r.threat, speedFrac: vis.speed, intensity: vis.intensity
        }),
        flash: r.coreFlash,
        t: r.t, glow: clamp(0.2 + r.threat * 0.5 + r.coreFlash * 0.9, 0, 1.6),
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

  /* A brief bright scar on the surface where you touched down. It is gone in
     half a second, but it is the difference between a floor you land on and a
     floor you merely stop at. */
  function drawMarks(g, r, camX) {
    if (!r.marks.length) return;
    g.save();
    for (var i = 0; i < r.marks.length; i++) {
      var m = r.marks[i], a = clamp(m.life / 0.5, 0, 1);
      var w = 20 + m.f * 60 * (1.4 - a);
      g.globalAlpha = a * a * 0.85;
      g.fillStyle = '#fff';
      g.fillRect(m.x - camX - w / 2, m.side === 'floor' ? P.FLOOR - 3 : P.CEIL, w, 3);
    }
    g.restore();
  }

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
    } else if (G.praise > 0 && !r.dead) {
      g.globalAlpha = clamp(G.praise / 1.1, 0, 1) * 0.8;
      g.font = '600 20px ui-sans-serif, system-ui, sans-serif';
      g.fillText('THAT IS THE WHOLE GAME', G.W / 2, P.H / 2 - 40);
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
      grav: attract.grav, speed: 0.35,
      evo: prog.activeCore(), mood: 'neutral', t: t, glow: 0.45, corrupt: 0
    });
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
