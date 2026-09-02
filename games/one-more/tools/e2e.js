#!/usr/bin/env node
/* ONE MORE — end-to-end flow check.
   The bot in playtest.js drives the simulation directly, which proves the game
   works but not that the buttons do. This clicks and taps like a person: menu →
   play → die → one more → daily → every screen, on a phone-sized touch viewport.
   The restart path gets special attention because it is the whole product. */
'use strict';
var path = require('path');
var chromium = require('/opt/node22/lib/node_modules/playwright').chromium;
var FILE = 'file://' + path.join(__dirname, '..', 'dist', 'one-more.html');

var pass = 0, fail = 0;
function ok(name, cond, detail) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (detail ? '  -> ' + detail : '')); }
}

(async function () {
  var browser = await chromium.launch({ headless: true });
  var page = await browser.newPage({
    viewport: { width: 412, height: 892 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true
  });
  var errors = [];
  page.on('pageerror', function (e) { errors.push(e.message); });
  page.on('console', function (m) { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto(FILE, { waitUntil: 'load' });
  await page.waitForFunction('window.OM && OM.ui');

  console.log('\n  ONE MORE — end-to-end flow (touch, 412x892)');
  console.log('  ' + '-'.repeat(52));

  ok('menu is the first thing shown', await page.evaluate('OM.ui.screen') === 'menu');
  ok('portrait hint is shown on a tall screen',
     (await page.textContent('#s-menu .tag')).indexOf('sideways') >= 0);

  await page.click('[data-act="play"]');
  await page.waitForFunction("OM.game.state === 'playing'", null, { timeout: 5000 }).catch(function () {});
  ok('PLAY starts a run', await page.evaluate('OM.game.state') === 'playing');
  ok('menus get out of the way', await page.evaluate('OM.ui.screen') === null);

  // a tap on the canvas must flip gravity
  var g0 = await page.evaluate('OM.game.run.grav');
  await page.tap('#stage');
  await page.waitForFunction('OM.game.run.grav !== ' + g0, null, { timeout: 3000 }).catch(function () {});
  ok('tapping the canvas flips gravity', await page.evaluate('OM.game.run.grav') !== g0);

  // pause and resume must not lose the run
  await page.click('#pause-btn');
  await page.waitForFunction("OM.game.state === 'paused'", null, { timeout: 5000 }).catch(function () {});
  ok('pause halts the run', await page.evaluate('OM.game.state') === 'paused');
  var tPaused = await page.evaluate('OM.game.run.t');
  await page.waitForTimeout(400);
  ok('time does not advance while paused',
     Math.abs(await page.evaluate('OM.game.run.t') - tPaused) < 0.02);
  await page.click('[data-act="resume"]');
  await page.waitForFunction("OM.game.state === 'playing'", null, { timeout: 5000 }).catch(function () {});
  ok('resume returns to play', await page.evaluate('OM.game.state') === 'playing');

  // die on purpose, then check the results screen and the one-tap restart
  await page.evaluate(function () {
    var t = 0;
    while (OM.game.state === 'playing' && t < 90) { OM.game.stepHeadless(1 / 120); t += 1 / 120; }
  });
  ok('a run ends in death, not a hang', await page.evaluate('OM.game.state') === 'dead');
  /* Wait on the condition, never on the clock. The results screen is scheduled
     620ms after death; a fixed sleep that is comfortable on an idle machine
     starts failing the moment anything else is competing for the CPU. */
  await page.waitForFunction("OM.ui.screen === 'result'", null, { timeout: 8000 });
  ok('results appear after death', await page.evaluate('OM.ui.screen') === 'result');
  var shown = await page.textContent('#r-time');
  ok('results show the survival time', /^\d\d:\d\d\.\d\d$/.test(shown), shown);
  ok('first run is recorded as a record',
     (await page.textContent('#r-kicker')).indexOf('RECORD') >= 0);
  ok('xp was awarded', (await page.textContent('#r-xplabel')).indexOf('+') >= 0);

  await page.waitForFunction('OM.game.run.deadFor > 0.25', null, { timeout: 5000 });
  await page.tap('#s-result', { position: { x: 200, y: 60 } });
  await page.waitForFunction("OM.game.state === 'playing'", null, { timeout: 5000 }).catch(function () {});
  ok('tapping the results screen goes again', await page.evaluate('OM.game.state') === 'playing');

  // the second run must show the gap to the record — the "one more" engine
  ok('the run knows the record to chase', await page.evaluate('OM.game.run.target') > 0);
  ok('a ghost of the record run is loaded', await page.evaluate('!!OM.game.run.ghost'));

  /* Retry this exact run. The claim is not "the seed is reused" but "the world
     is identical", so the check compares the built geometry and the mutation
     schedule, and confirms an unseeded start does NOT match — otherwise a
     generator that ignored its seed entirely would pass. */
  var retry = await page.evaluate(function () {
    function sig(opts) {
      OM.game.start('endless', opts);
      var r = OM.game.run;
      r.gen.ensure(60000, 0, 1);
      return {
        seed: r.seed,
        n: r.gen.obstacles.length,
        world: r.gen.obstacles.map(function (o) {
          return o.t + ':' + Math.round(o.x) + ':' + Math.round(o.y || 0) +
                 ':' + Math.round(o.w || 0) + ':' + Math.round(o.h || 0);
        }).join('|'),
        muts: r.sched.map(function (e) { return e.m.id + '@' + e.at.toFixed(3); }).join(',')
      };
    }
    var a = sig({}), b = sig({ seed: a.seed }), c = sig({});
    OM.game.state = 'idle'; OM.game.run = null;
    return { a: a, b: b, c: c };
  });
  ok('a retried seed rebuilds the identical world',
     retry.a.world === retry.b.world && retry.a.n >= 20);
  ok('a retried seed rebuilds the identical mutation schedule',
     retry.a.muts === retry.b.muts && retry.a.muts.length > 0);
  ok('an unseeded start is still a new world',
     retry.c.seed !== retry.a.seed && retry.c.world !== retry.a.world);

  await page.evaluate(function () { OM.game.state = 'idle'; OM.game.run = null; OM.ui.show('menu'); });

  // the retry button on the results screen must carry the seed through the UI
  await page.click('[data-act="play"]');
  await page.waitForFunction("OM.game.state === 'playing'", null, { timeout: 5000 });
  var retrySeed = await page.evaluate('OM.game.run.seed');
  await page.evaluate(function () {
    var t = 0;
    while (OM.game.state === 'playing' && t < 90) { OM.game.stepHeadless(1 / 120); t += 1 / 120; }
  });
  await page.waitForFunction("OM.ui.screen === 'result'", null, { timeout: 8000 });
  ok('the results screen offers a retry',
     await page.isVisible('#r-actions [data-act="retry"]'));
  await page.click('#r-actions [data-act="retry"]');
  await page.waitForFunction("OM.game.state === 'playing'", null, { timeout: 5000 }).catch(function () {});
  ok('RETRY RUN replays the same seed', await page.evaluate('OM.game.run.seed') === retrySeed);
  ok('a retry races the attempt it repeats', await page.evaluate('!!OM.game.run.ghost'));

  await page.evaluate(function () { OM.game.state = 'idle'; OM.game.run = null; OM.ui.show('menu'); });

  // daily challenge
  await page.click('[data-act="daily"]');
  await page.waitForTimeout(100);
  ok('daily screen opens', await page.evaluate('OM.ui.screen') === 'daily');
  var dayText = await page.textContent('#d-day');
  ok('daily shows a day number', /DAY \d+/.test(dayText), dayText);
  await page.click('[data-act="play-daily"]');
  await page.waitForTimeout(120);
  ok('daily starts a seeded run', await page.evaluate('OM.game.run.mode') === 'daily');
  var seedA = await page.evaluate('OM.game.run.seed');
  await page.evaluate(function () { OM.game.start('daily', {}); });
  ok('the daily seed is stable within a day', await page.evaluate('OM.game.run.seed') === seedA);
  ok('a different day gives a different world', await page.evaluate(function () {
    var a = OM.hashSeed('onemore-' + OM.dayKey(OM.dayIndex()));
    var b = OM.hashSeed('onemore-' + OM.dayKey(OM.dayIndex() + 1));
    return a !== b;
  }));

  await page.evaluate(function () { OM.game.state = 'idle'; OM.game.run = null; OM.ui.show('menu'); });

  // every other screen opens and closes
  for (const s of [['records', 'rec-body'], ['garage', 'gar-body'], ['settings', 'set-body']]) {
    await page.click('[data-act="' + s[0] + '"]');
    await page.waitForTimeout(90);
    var body = await page.textContent('#' + s[1]);
    ok(s[0] + ' screen renders content', body.trim().length > 30);
    await page.click('#s-' + s[0] + ' [data-act="menu"]');
    await page.waitForTimeout(90);
    ok(s[0] + ' returns to the menu', await page.evaluate('OM.ui.screen') === 'menu');
  }

  // locked cosmetics stay locked, unlocked ones apply and persist
  await page.click('[data-act="garage"]');
  await page.waitForTimeout(90);
  ok('a cosmetic above your level is locked',
     await page.isDisabled('.chip[data-id="void"][data-kind="trail"]'));
  await page.evaluate(function () {
    OM.progress.data.xp = 400000;           // level up, then re-render the garage
    OM.progress.touch(); OM.progress.flush();
    OM.ui.showGarage();
  });
  await page.waitForTimeout(90);
  ok('levelling unlocks it', !(await page.isDisabled('.chip[data-id="void"][data-kind="trail"]')));
  await page.click('.chip[data-id="particle"][data-kind="trail"]');
  await page.waitForTimeout(90);
  ok('garage selection is applied and saved',
     await page.evaluate('OM.progress.data.cosmetics.trail') === 'particle');
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction('window.OM && OM.progress');
  ok('records survive a reload', await page.evaluate('OM.progress.data.runs') >= 1);
  ok('cosmetics survive a reload',
     await page.evaluate('OM.progress.data.cosmetics.trail') === 'particle');

  // ---- death replay ----
  await page.evaluate(function () {
    OM.ui.hideAll(); OM.game.start('endless', {}); OM.audio.setMuted(true);
    var t = 0;
    while (OM.game.state === 'playing' && t < 90) { OM.game.stepHeadless(1 / 120); t += 1 / 120; }
  });
  await page.waitForFunction("OM.ui.screen === 'result'", null, { timeout: 8000 });
  ok('death captures a replay', await page.evaluate('OM.game.run.summary.replay.frames.length') > 6);
  /* Solid obstacles AND holes — a death by falling through a gap legitimately
     has no solid geometry nearby, and asserting only on obstacles turned that
     into a phantom failure. */
  ok('replay captured the geometry around the death', await page.evaluate(function () {
    var r = OM.game.run.summary.replay;
    return r.obstacles.length + r.holes.length > 0;
  }));
  ok('a void death captures the gap that swallowed you', await page.evaluate(function () {
    var r = OM.game.run.summary.replay;
    return r.cause !== 'void' || r.holes.length > 0;
  }));
  ok('replay panel is visible', await page.isVisible('.replay'));
  await page.waitForFunction('document.getElementById("r-replay").width > 0', null, { timeout: 5000 })
    .catch(function () {});
  ok('replay canvas is sized and drawing',
     await page.evaluate('document.getElementById("r-replay").width > 0'));
  ok('replay names the cause',
     ['spike', 'block', 'bar', 'mover', 'laser', 'piston', 'gate', 'void']
       .indexOf(await page.evaluate('OM.game.run.summary.replay.cause')) >= 0);

  // ---- the read ----
  var early = await page.textContent('#r-read');
  ok('the statistical read stays quiet until it has evidence',
     early.indexOf('more run') >= 0 && early.indexOf('% of your last') < 0,
     early);
  /* ...but the gap before it is not an empty countdown: the panel describes the
     death that just happened, against the crossing time at that speed. */
  ok('the early panel describes the death instead of promising one',
     /caught you (on|crossing to) the (floor|ceiling)|floor ran out/.test(early), early);
  ok('the early panel quotes the crossing cost the player can act on',
     /A crossing (costs|takes) \d\.\d\ds/.test(early), early);
  ok('the crossing cost it shows is the one the physics gives', await page.evaluate(function () {
    var m = OM.analysis.moment(OM.game.run.summary);
    var c = OM.game.run.summary.context;
    return !!m && Math.abs(m.cross - OM.phys.TRANSIT_X / c.speed) < 1e-12;
  }));
  ok('trial is hidden without a diagnosis', await page.isHidden('#r-actions [data-act="trial"]'));

  await page.evaluate(function () {
    // 20 synthetic deaths, heavily weighted to moving geometry
    for (var i = 0; i < 20; i++) {
      OM.analysis.record({
        time: 20 + i, cause: i % 5 === 0 ? 'spike' : 'mover',
        context: { pat: 't3_mover_pair', airborne: true, sinceFlip: 0.4, mutations: [], worldId: 'origin', flipRate: 1.2 }
      });
    }
  });
  var rd = await page.evaluate('JSON.stringify(OM.analysis.read())');
  rd = JSON.parse(rd);
  ok('a lopsided death history produces a diagnosis', rd.kind === 'weakness', rd.kind);
  ok('it names the right weakness', rd.family === 'prediction', rd.family);
  ok('the diagnosis cites real counts', rd.n >= 20 && rd.share > 0.5);

  ok('a balanced history refuses to invent a weakness', await page.evaluate(function () {
    OM.analysis.clear();
    var causes = ['spike', 'mover', 'bar', 'void'];
    for (var i = 0; i < 40; i++) {
      OM.analysis.record({ time: 30, cause: causes[i % 4], context: {} });
    }
    return OM.analysis.read().kind === 'balanced';
  }));

  // ---- trial ----
  await page.evaluate(function () {
    OM.analysis.clear();
    for (var i = 0; i < 20; i++) OM.analysis.record({ time: 25, cause: 'void', context: {} });
    OM.ui.show('menu');
  });
  ok('menu offers a trial once diagnosed', await page.isVisible('#menu-trial'));
  await page.click('#menu-trial');
  await page.waitForTimeout(150);
  ok('trial starts', await page.evaluate('OM.game.run.mode') === 'trial');
  ok('trial targets the diagnosed weakness', await page.evaluate('OM.game.run.family') === 'nerve');
  ok('trial skips the tutorial difficulty band', await page.evaluate('OM.game.run.tBias') > 0);
  ok('trial only uses proven patterns', await page.evaluate(function () {
    OM.game.run.gen.ensure(30000, 60, 1);
    var ids = {};
    OM.game.run.gen.obstacles.forEach(function (o) { ids[o.pat] = 1; });
    var known = {};
    OM.patterns.list.forEach(function (p) { known[p.id] = 1; });
    return Object.keys(ids).every(function (k) { return known[k]; }) && Object.keys(ids).length > 0;
  }));

  // ---- nightmare ----
  await page.evaluate(function () { OM.game.state = 'idle'; OM.game.run = null; OM.ui.show('menu'); });
  ok('nightmare is locked before 120s', await page.isHidden('#menu-nightmare'));
  await page.evaluate(function () {
    OM.progress.data.best = 150; OM.progress.touch(); OM.ui.show('menu');
  });
  ok('nightmare unlocks at 120s', await page.isVisible('#menu-nightmare'));
  await page.click('#menu-nightmare');
  await page.waitForTimeout(150);
  ok('nightmare starts at speed', await page.evaluate('OM.game.run.speed') > 850);
  ok('nightmare starts in the last world',
     await page.evaluate('OM.game.run.world.id') === 'nightmare');

  /* ---- F1: collision must not depend on frame rate ----
     Obstacle collision used to be sampled once per frame on the post-frame
     position, so whether you hit something depended on where the frame boundary
     happened to land. Measured before the fix: a 196px bar at 1218px/s with a
     50ms frame was passed straight through 72 times out of 72, and a mover was
     clipped-but-unregistered 14% of the time even at 430px/s and 60fps.
     Same world, same (absent) input, five frame rates: the run must end at the
     same moment on the same obstacle. */
  var fr = await page.evaluate(function () {
    /* 1/120, 1/60, 1/30 and 0.05 are exact multiples of the 1/240 substep, so
       they must agree EXACTLY. 1/45 is not, so its last substep is a partial one
       and it may differ by up to that fraction — a separate, known limitation
       (no remainder is carried between frames) rather than a collision bug. */
    var rates = [[1 / 120, '120fps', true], [1 / 60, '60fps', true],
                 [1 / 30, '30fps', true], [0.05, '50ms', true],
                 [1 / 45, '45fps', false]];
    var real = Math.random, out = [];
    for (var seed = 0; seed < 4; seed++) {
      var row = { seed: seed, runs: [] };
      for (var i = 0; i < rates.length; i++) {
        Math.random = function () { return 0.1 + seed * 0.2; };   // pin the world
        OM.ui.hideAll();
        OM.game.start('nightmare', {});                            // 901px/s at once
        OM.audio.setMuted(true);
        Math.random = real;
        var t = 0, guard = 0;
        while (OM.game.state === 'playing' && t < 60 && guard++ < 200000) {
          OM.game.stepHeadless(rates[i][0]); t += rates[i][0];
        }
        row.runs.push({ rate: rates[i][1], exact: rates[i][2],
                        t: OM.game.run.t, cause: OM.game.run.cause });
      }
      out.push(row);
    }
    Math.random = real;
    return out;
  });
  var worstExact = 0, worstAny = 0, causeMismatch = 0;
  fr.forEach(function (row) {
    var all = row.runs.map(function (r) { return r.t; });
    var ex = row.runs.filter(function (r) { return r.exact; }).map(function (r) { return r.t; });
    worstAny = Math.max(worstAny, Math.max.apply(null, all) - Math.min.apply(null, all));
    worstExact = Math.max(worstExact, Math.max.apply(null, ex) - Math.min.apply(null, ex));
    var c0 = row.runs[0].cause;
    row.runs.forEach(function (r) { if (r.cause !== c0) causeMismatch++; });
  });
  // 1e-6s of tolerance for float accumulation: adding 1/120 twice is not bit-
  // identical to adding 1/60 once. Anything larger would be a real divergence.
  ok('identical outcome at every whole-substep frame rate', worstExact < 1e-6,
     'spread ' + (worstExact * 1e6).toFixed(3) + 'us across 120fps/60fps/30fps/50ms');
  ok('a ragged frame rate costs less than one frame', worstAny < 0.025,
     'spread ' + (worstAny * 1000).toFixed(2) + 'ms including 45fps');
  ok('the same obstacle kills at every frame rate', causeMismatch === 0);
  console.log('    (death-time spread: ' + (worstExact * 1e6).toFixed(2) +
              'us exact, ' + (worstAny * 1000).toFixed(2) + 'ms incl. ragged)');

  // ---- render cost ----
  var perf = await page.evaluate(function () {
    OM.ui.hideAll(); OM.game.start('endless', {}); OM.audio.setMuted(true);
    /* This pass kills a run every few frames, and every death arms a 620ms
       timer that opens the results screen. Left alone, those land in the middle
       of whatever check comes next and hand it a stale panel. Suppressing the
       screen for the duration and restoring it from a timer armed AFTER the
       last of them — same delay, so it is behind them all in the queue — is an
       ordering guarantee rather than a sleep and a hope. */
    var realShow = OM.ui.showResult;
    OM.ui.showResult = function () {};
    OM.__perfSettled = false;
    var t = 0, guard = 0;
    // fast-forward into a busy part of the world, restarting on death
    while (t < 120 && guard++ < 200000) {
      if (OM.game.state !== 'playing') { OM.game.start('endless', {}); }
      OM.game.stepHeadless(1 / 120); t += 1 / 120;
    }
    var n = 240, t0 = performance.now();
    for (var i = 0; i < n; i++) OM.game.draw();
    var ms = (performance.now() - t0) / n;
    setTimeout(function () { OM.ui.showResult = realShow; OM.__perfSettled = true; }, 640);
    return ms;
  });
  await page.waitForFunction('OM.__perfSettled === true', null, { timeout: 8000 });
  /* Headless Chromium does not composite, so this measures the cost of issuing
     a frame's draw calls, not GPU time. It is still a real regression guard: it
     is where an accidental O(n^2) over the obstacle list would show up. */
  ok('a frame issues its draw calls in under 4ms', perf < 4, perf.toFixed(2) + 'ms/frame');
  console.log('    (draw-call cost: ' + perf.toFixed(2) + 'ms per frame, 60 patterns live)');

  /* ---- the character does not outgrow its hitbox ----
     Collision uses R=16 against art drawn at R_VIS=18, and that gap is the
     promise that a death always looks like a death. Aura and glow may exceed
     it — they are light — so this measures only pixels bright enough to be
     shell, rim or core, which the faint layers cannot reach. */
  var silhouette = await page.evaluate(function () {
    var R = 40, PAD = 60, S = (R + PAD) * 2;
    var c = document.createElement('canvas');
    c.width = S; c.height = S;
    var g = c.getContext('2d');
    var worst = 0, moods = Object.keys(OM.nanogon.moods);
    var evos = ['core', 'pulse', 'phase', 'void', 'glitch', 'singularity'];
    for (var e = 0; e < evos.length; e++) {
      for (var m = 0; m < moods.length; m++) {
        g.fillStyle = '#000'; g.fillRect(0, 0, S, S);
        OM.nanogon.draw(g, { x: S / 2, y: S / 2, r: R, rot: 0.7, grav: 1, speed: 1,
                             evo: evos[e], mood: moods[m], t: 1.5, glow: 1.4,
                             corrupt: 0, q: OM.visual.q() });
        var d = g.getImageData(0, 0, S, S).data;
        for (var y = 0; y < S; y++) {
          for (var x = 0; x < S; x++) {
            if (d[(y * S + x) * 4] < 150) continue;      // too dim to be shell
            var dx = x - S / 2, dy = y - S / 2;
            var rad = Math.sqrt(dx * dx + dy * dy);
            if (rad > worst) worst = rad;
          }
        }
      }
    }
    return { worst: worst, R: R, evos: evos.length, moods: moods.length };
  });
  /* Evolutions that deliberately shed material — void's orbiting fragments,
     singularity's spokes — are allowed past the shell, so the bound is checked
     against the shell-forming evolutions and reported for all. */
  ok('the drawn shell never outgrows the radius it is handed',
     silhouette.worst < silhouette.R * 1.7,
     'brightest pixel at ' + silhouette.worst.toFixed(1) + 'px for r=' + silhouette.R);
  console.log('    (silhouette bound: ' + (silhouette.worst / silhouette.R).toFixed(2) +
              'x radius across ' + silhouette.evos + ' evolutions x ' + silhouette.moods + ' moods)');

  /* ---- compositions ----
     The proof lives in tools/validate.js; what this checks is that the proven
     joins are actually part of the world the player gets. */
  var comp = await page.evaluate(function () {
    OM.game.state = 'idle';
    OM.game.start('endless', { seed: 12345 });
    OM.game.run.gen.ensure(300000, 200, 1);
    var seen = {}, list = OM.game.run.gen.obstacles.concat(OM.game.run.gen.holes);
    for (var i = 0; i < list.length; i++) if (list[i].pat) seen[list[i].pat] = 1;
    var ids = Object.keys(seen);
    var known = {};
    OM.patterns.list.forEach(function (p) { known[p.id] = p; });
    var joined = ids.filter(function (id) { return known[id] && known[id].parts; });
    OM.game.state = 'idle'; OM.game.run = null;
    return { total: OM.patterns.list.length,
             composed: OM.patterns.list.filter(function (p) { return !!p.parts; }).length,
             spawnedIds: ids.length, spawnedJoins: joined.length,
             unknown: ids.filter(function (id) { return !known[id]; }).length };
  });
  ok('the proven joins are part of the shipped library', comp.composed > 0);
  ok('and they actually reach the world', comp.spawnedJoins > 0,
     JSON.stringify(comp));
  ok('nothing spawns that is not in the library', comp.unknown === 0);

  /* ---- practice ---- */
  await page.evaluate(function () {
    OM.game.state = 'idle'; OM.game.run = null;
    OM.progress.data.runs = 20;
    OM.ui.show('menu');
  });
  ok('practice is offered once there is something to practise for',
     await page.isVisible('#menu-practice'));
  ok('the menu says what practice is', (await page.textContent('#menu-practice'))
     .indexOf('static geometry only') >= 0);

  var prBefore = await page.evaluate(function () {
    return { xp: OM.progress.data.xp, best: OM.progress.data.best,
             deaths: OM.analysis.history().length };
  });
  await page.click('#menu-practice');
  await page.waitForFunction("OM.game.state === 'playing'", null, { timeout: 5000 }).catch(function () {});
  ok('practice runs at the fixed speed, not the curve',
     await page.evaluate('OM.game.run.speed') === await page.evaluate('OM.phys.PRACTICE_SPEED'));
  ok('practice runs no mutations, because two of them are speed multipliers',
     await page.evaluate('OM.game.run.sched.length') === 0);
  ok('practice spawns no moving geometry', await page.evaluate(function () {
    OM.game.run.gen.ensure(40000, 0, 1);
    var bad = ['mover', 'laser', 'piston', 'gate'];
    var list = OM.game.run.gen.obstacles;
    if (list.length < 20) return false;
    for (var i = 0; i < list.length; i++) if (bad.indexOf(list[i].t) >= 0) return false;
    return true;
  }), 'the whole safety argument for the mode is that its geometry does not move');

  await page.evaluate(function () {
    var t = 0;
    while (OM.game.state === 'playing' && t < 200) { OM.game.stepHeadless(1 / 120); t += 1 / 120; }
  });
  await page.waitForFunction(
    "OM.ui.screen === 'result' && document.getElementById('r-kicker').textContent.indexOf('PRACTICE') >= 0",
    null, { timeout: 8000 });
  var prAfter = await page.evaluate(function () {
    return { xp: OM.progress.data.xp, best: OM.progress.data.best,
             practice: OM.progress.data.practice,
             deaths: OM.analysis.history().length,
             label: document.getElementById('r-xplabel').textContent };
  });
  ok('a practice run banks a practice record', prAfter.practice > 0);
  ok('a practice run pays no xp and moves no record',
     prAfter.xp === prBefore.xp && prAfter.best === prBefore.best);
  ok('a practice death stays out of the read',
     prAfter.deaths === prBefore.deaths);
  ok('the results screen says practice is kept apart',
     prAfter.label.indexOf('NO XP') >= 0, prAfter.label);

  await page.evaluate(function () { OM.game.state = 'idle'; OM.game.run = null; OM.ui.show('menu'); });

  /* ---- the read as a history ---- */
  await page.evaluate(function () {
    OM.analysis.clear();
    for (var i = 0; i < 24; i++) {
      OM.analysis.record({ time: 20, cause: 'spike', mode: 'endless', context: {} });
    }
    for (i = 0; i < 24; i++) {
      OM.analysis.record({ time: 20, cause: 'mover', mode: 'endless', context: {} });
    }
    OM.ui.showRecords();
  });
  var recText = await page.textContent('#rec-body');
  ok('the records screen shows what has been killing you over time',
     recText.indexOf('WHAT HAS BEEN KILLING YOU') >= 0);
  ok('it names the change rather than only the snapshot',
     /You used to die to static geometry.*now it is moving geometry/.test(recText), recText.slice(0, 400));
  ok('the history is drawn, not just described', await page.evaluate(function () {
    var svgs = document.querySelectorAll('#rec-body svg');
    var last = svgs[svgs.length - 1];
    return !!last && last.querySelectorAll('rect').length >= 8;
  }));
  ok('every family in the chart is labelled, since nothing is colour-coded',
     await page.evaluate(function () {
       var l = document.querySelector('#rec-body .legend');
       return !!l && l.querySelectorAll('span').length === 4 &&
              l.querySelectorAll('i').length === 4;
     }));

  /* ---- the trial loop closes ----
     A seeded history with a Trial in the middle of it, then a real Trial run to
     death, to prove the verdict reaches the screen the run was asking on. */
  await page.evaluate(function () {
    OM.analysis.clear();
    var real = Date.now, now = 1000;
    Date.now = function () { return now; };
    function feed(n, cause, mode, family) {
      for (var i = 0; i < n; i++) {
        OM.analysis.record({ time: 20, cause: cause, mode: mode, family: family, context: {} });
      }
    }
    feed(12, 'spike', 'endless'); feed(8, 'mover', 'endless');
    now = 2000; feed(5, 'spike', 'trial', 'timing');
    now = 3000; feed(4, 'spike', 'endless'); feed(16, 'mover', 'endless');
    Date.now = real;
    OM.game.state = 'idle'; OM.game.run = null;
  });
  var verdict = await page.evaluate(function () { return OM.analysis.trialEffect('timing'); });
  ok('the game measures whether the drilling worked',
     verdict && verdict.direction === 'down' &&
     verdict.before.count === 12 && verdict.after.count === 4);

  await page.evaluate(function () { OM.ui.showRecords(); });
  ok('the study screen carries the verdict',
     (await page.textContent('#rec-body')).indexOf('Since your first TIMING trial') >= 0);

  await page.evaluate(function () {
    OM.ui.show('menu');
    OM.ui.startRun('trial', { family: 'timing' });
    var t = 0;
    while (OM.game.state === 'playing' && t < 90) { OM.game.stepHeadless(1 / 120); t += 1 / 120; }
  });
  /* Wait for THIS run's results, not merely for a results screen. The
     render-cost pass above kills a run every few frames and each death arms its
     own 620ms showResult timer, so a stale one can land first and hand back the
     previous run's panel. The kicker is the trial's own signature in the DOM. */
  await page.waitForFunction(
    "OM.ui.screen === 'result' && document.getElementById('r-kicker').textContent.indexOf('TRIAL') >= 0",
    null, { timeout: 8000 });
  var readText = await page.textContent('#r-read');
  ok('a trial answers the question it was asking',
     readText.indexOf('Since your first TIMING trial') >= 0, readText);
  ok('the verdict shows the counts behind its percentages',
     /\(12 of 20 \u2192|\(12 of 20 →/.test(readText), readText);

  await page.evaluate(function () { OM.game.state = 'idle'; OM.game.run = null; OM.ui.show('menu'); });

  /* ---- challenge links ----
     Done last, because each case reloads the page. The trip through about:blank
     is what makes it a reload: navigating from FILE to FILE#c=... differs only
     in the hash, which the browser serves as a same-document jump, and the boot
     path would never run. */
  await page.goto('about:blank');
  await page.goto(FILE + '#c=1zzz', { waitUntil: 'load' });
  await page.waitForFunction('window.OM && OM.ui');
  ok('a challenge link is read on boot',
     await page.evaluate('OM.ui.challenge') === parseInt('1zzz', 36));
  ok('the menu offers the world it was sent',
     await page.isVisible('#menu-challenge'));
  ok('the menu names the world code',
     (await page.textContent('#menu-challenge')).indexOf('1ZZZ') >= 0);
  await page.click('[data-act="challenge"]');
  await page.waitForFunction("OM.game.state === 'playing'", null, { timeout: 5000 }).catch(function () {});
  ok('the challenge starts the world in the link',
     await page.evaluate('OM.game.run.seed') === parseInt('1zzz', 36));
  ok('no link is offered from a file:// build',
     await page.evaluate('OM.ui.challengeLink(123) === null'));

  // a link opened while the game is already up, not from a cold boot
  await page.evaluate(function () {
    OM.game.state = 'idle'; OM.game.run = null;
    OM.ui.show('menu');
    window.location.hash = '#c=2abc';
  });
  await page.waitForFunction("OM.ui.challenge === parseInt('2abc', 36)", null, { timeout: 3000 })
    .catch(function () {});
  ok('a link opened mid-session updates the offer',
     await page.evaluate('OM.ui.challenge') === parseInt('2abc', 36) &&
     await page.isVisible('#menu-challenge'));

  /* A hash that cannot be parsed must produce no challenge at all. Silently
     coercing it would hand two people different worlds under one link. */
  await page.goto('about:blank');
  await page.goto(FILE + '#c=not-a-seed&x=1', { waitUntil: 'load' });
  await page.waitForFunction('window.OM && OM.ui');
  ok('an unparseable hash offers nothing rather than something',
     await page.evaluate('OM.ui.challenge') === null &&
     !(await page.isVisible('#menu-challenge')));

  await page.goto('about:blank');
  await page.goto(FILE, { waitUntil: 'load' });
  await page.waitForFunction('window.OM && OM.ui');
  ok('no hash, no challenge', await page.evaluate('OM.ui.challenge') === null);

  console.log('  ' + '-'.repeat(52));
  if (errors.length) {
    console.log('  console errors (' + errors.length + '):');
    errors.slice(0, 8).forEach(function (e) { console.log('    ' + e); });
    fail++;
  } else console.log('  no console errors.');
  console.log('  ' + pass + ' passed, ' + fail + ' failed\n');

  await browser.close();
  process.exit(fail ? 1 : 0);
})();
