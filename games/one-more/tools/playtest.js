#!/usr/bin/env node
/* ONE MORE — automated playtest.
 *
 * Loads the real built game in a real browser and plays it with a bot, so the
 * difficulty curve is a measurement instead of an opinion.
 *
 * The bot looks ahead through the live obstacle list using the shipping physics
 * and picks the action with the longest survivable horizon. Give it a reaction
 * delay and some jitter and it stops being a solver and starts being a
 * stand-in for a person: PERFECT never blinks, GOOD is a strong player, HUMAN
 * is roughly a competent one, SLOPPY is somebody on a bus.
 *
 *   node tools/playtest.js [--runs 6] [--headed] [--shots]
 */
'use strict';
var path = require('path');
var chromium = require('/opt/node22/lib/node_modules/playwright').chromium;

var args = process.argv.slice(2);
function flag(n, d) { var i = args.indexOf('--' + n); return i >= 0 ? (args[i + 1] || true) : d; }
/* Eleven, not five. A PERFECT run lasts minutes and its length has a long tail,
   so five samples put its median anywhere: three consecutive runs of an
   unchanged build gave 4:04, 1:10 and 2:53, and the middle one reported that a
   slower reaction survived longer. That was the sample size talking, not the
   game, and a curve that says something different every time it is measured is
   not a measurement. */
var RUNS = parseInt(flag('runs', 11), 10);
var SHOTS = args.indexOf('--shots') >= 0;
var FILE = 'file://' + path.join(__dirname, '..', 'dist', 'one-more.html');

var PROFILES = [
  { name: 'PERFECT', reaction: 0.000, jitter: 0.000, miss: 0.00 },
  { name: 'GOOD',    reaction: 0.110, jitter: 0.030, miss: 0.00 },
  { name: 'HUMAN',   reaction: 0.190, jitter: 0.055, miss: 0.02 },
  { name: 'SLOPPY',  reaction: 0.300, jitter: 0.110, miss: 0.07 }
];

/* The bot, injected into the page. It only reads state the game already
   exposes and drives it through the same OM.game.flip() a finger would. */
function installBot() {
  var P = OM.phys, PAT = OM.patterns;

  function hits(list, holes, x, y, t) {
    var scratch = [];
    for (var i = 0; i < list.length; i++) {
      var o = list[i];
      if (o.x > x + P.R || o.x + (o.w || 0) < x - P.R) continue;
      scratch.length = 0;
      var rects = PAT.rectsOf(o, t, scratch);
      for (var j = 0; j < rects.length; j++) {
        var q = rects[j];
        if (P.circleRectDist2(x, y, P.R, q.x, q.y, q.w, q.h) <= P.R * P.R) return true;
      }
    }
    return false;
  }

  // How far can we get from this state with this flip schedule? Returns px.
  function horizon(st, px, t, speed, g, list, holes, flips, limit) {
    var DX = 10, fi = 0, x = px;
    var s = { y: st.y, vy: st.vy, grav: st.grav, grounded: st.grounded };
    for (var d = 0; d < limit; d += DX) {
      while (fi < flips.length && flips[fi] <= x) { s.grav = -s.grav; s.grounded = false; fi++; }
      var out = P.stepPlayer(s, DX / speed, g, x + DX, holes);
      x += DX;
      if (out === 'void') return d;
      if (s.y > P.FLOOR + P.VOID_DEATH || s.y < P.CEIL - P.VOID_DEATH) return d;
      if (hits(list, holes, x, s.y, t + (x - px) / speed)) return d;
    }
    return limit;
  }

  window.__bot = {
    /* Returns the EARLIEST world-x at which a flip still clears everything in
       the lookahead, or null if standing pat is fine. Earliest, not latest:
       a person flips when the need becomes visible, leaving themselves margin.
       Planning the last survivable instant and then adding reaction delay is
       not a hard player, it is a dead one. */
    decide: function () {
      var r = OM.game.run;
      if (!r || r.dead) return null;
      var speed = r.speed, g = P.gravityFor(speed, 1);
      var list = r.gen.obstacles, holes = r.gen.holes;
      var LIMIT = 900, STEPX = 20, N = 46;
      var s0 = { y: r.y, vy: r.vy, grav: r.grav, grounded: r.grounded };

      var noFlip = horizon(s0, r.px, r.t, speed, g, list, holes, [], LIMIT);
      if (noFlip >= LIMIT) return null;                 // nothing to do yet

      var bestScore = noFlip, bestFx = null, k, fx, h;
      for (k = 0; k < N; k++) {
        fx = r.px + 2 + k * STEPX;
        h = horizon(s0, r.px, r.t, speed, g, list, holes, [fx], LIMIT);
        if (h > bestScore + 1) { bestScore = h; bestFx = fx; }
      }
      if (bestScore < LIMIT) {                          // one flip is not enough: plan two
        for (k = 0; k < N; k++) {
          fx = r.px + 2 + k * STEPX;
          for (var j = k + 1; j < N; j++) {
            h = horizon(s0, r.px, r.t, speed, g, list, holes, [fx, r.px + 2 + j * STEPX], LIMIT);
            if (h > bestScore + 1) { bestScore = h; bestFx = fx; }
            if (bestScore >= LIMIT) break;
          }
          if (bestScore >= LIMIT) break;
        }
      }
      return bestFx === null ? null : { at: bestFx, score: bestScore };
    }
  };
}

(async function main() {
  var browser = await chromium.launch({ headless: args.indexOf('--headed') < 0 });
  var page = await browser.newPage({ viewport: { width: 1280, height: 720 } });

  var errors = [];
  page.on('console', function (m) { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', function (e) { errors.push('pageerror: ' + e.message); });

  await page.goto(FILE, { waitUntil: 'load' });
  await page.waitForFunction('window.OM && OM.game && OM.ui');
  await page.evaluate(installBot);

  if (SHOTS) {
    await page.waitForTimeout(2200);               // let the attract loop get moving
    await page.screenshot({ path: path.join(__dirname, '..', 'dist', 'shot-menu.png') });
  }

  console.log('\n  ONE MORE — automated playtest');
  console.log('  ' + '-'.repeat(62));
  console.log('  ' + pad('PROFILE', 10) + pad('REACTION', 11) + pad('RUNS', 6) +
              pad('MEDIAN', 10) + pad('BEST', 10) + 'WORLD REACHED');
  console.log('  ' + '-'.repeat(62));

  var summary = [];
  for (var p = 0; p < PROFILES.length; p++) {
    var prof = PROFILES[p];
    var times = [], worlds = {};
    for (var n = 0; n < RUNS; n++) {
      var res = await page.evaluate(function (cfg) {
        return new Promise(function (resolve) {
          // fresh save each run so records do not leak between profiles
          OM.progress.data.best = 0;
          OM.progress.data.ghost = null;
          OM.ui.hideAll();                 // go through the same path a tap does
          OM.game.start('endless', {});
          OM.audio.setMuted(true);

          /* The human model: the player only re-reads the screen every
             `reaction` seconds, and acts on that reading with some jitter.
             Slower reading means committing earlier on less information, which
             is exactly how reaction time actually costs you a run. */
          var DT = 1 / 120, t = 0, guard = 0;
          var interval = Math.max(0.035, cfg.reaction);
          var nextLook = 0;
          while (OM.game.state === 'playing' && t < cfg.cap && guard++ < 500000) {
            if (t >= nextLook) {
              nextLook = t + interval * (1 + (Math.random() - 0.5) * 0.4);
              if (Math.random() >= cfg.miss) {                   // else: a lapse, skip this look
                var d = window.__bot.decide();
                var r0 = OM.game.run;
                // act if the flip is needed before the next time we look
                var reach = r0.speed * (interval + cfg.jitter);
                if (d && d.at <= r0.px + reach) OM.game.flip();
              }
            }
            OM.game.stepHeadless(DT);
            t += DT;
          }
          var r = OM.game.run;
          resolve({ time: r.t, world: r.world.name, cause: r.cause,
                    near: r.nearMiss, perfect: r.perfect, flips: r.flips });
        });
      }, { reaction: prof.reaction, jitter: prof.jitter, miss: prof.miss, cap: 400 });
      times.push(res.time);
      worlds[res.world] = (worlds[res.world] || 0) + 1;
      if (SHOTS && p === 1 && n === 0) {
        var marks = [10, 34, 72, 130, 200];
        for (var mi = 0; mi < marks.length; mi++) {
          await page.evaluate(function (until) {
            OM.ui.hideAll();
            OM.game.start('endless', {});
            OM.audio.setMuted(true);
            var DT = 1 / 120, t = 0, nextLook = 0;
            while (OM.game.state === 'playing' && t < until) {
              if (t >= nextLook) {
                nextLook = t + 0.045;
                var d = window.__bot.decide(), r0 = OM.game.run;
                if (d && d.at <= r0.px + r0.speed * 0.08) OM.game.flip();
              }
              OM.game.stepHeadless(DT); t += DT;
            }
            OM.game.draw();
          }, marks[mi]);
          await page.waitForTimeout(750);          // let any queued result screen fire
          await page.evaluate(function () { OM.ui.hideAll(); OM.game.draw(); });
          await page.screenshot({ path: path.join(__dirname, '..', 'dist', 'shot-t' + marks[mi] + '.png') });
        }
      }
    }
    times.sort(function (a, b) { return a - b; });
    var med = times[Math.floor(times.length / 2)];
    var best = times[times.length - 1];
    var top = Object.keys(worlds).sort(function (a, b) { return worlds[b] - worlds[a]; })[0];
    summary.push({ prof: prof, med: med, best: best });
    console.log('  ' + pad(prof.name, 10) + pad(Math.round(prof.reaction * 1000) + 'ms', 11) +
      pad(String(RUNS), 6) + pad(fmt(med), 10) + pad(fmt(best), 10) + top);
  }
  console.log('  ' + '-'.repeat(62));

  // sanity: a better player must actually do better
  var monotone = true;
  for (var i = 1; i < summary.length; i++) if (summary[i].med > summary[i - 1].med * 1.15) monotone = false;
  console.log('  skill ordering holds: ' + (monotone ? 'yes' : 'NO — slower reaction survived longer'));

  if (SHOTS) {
    await page.evaluate(function () { OM.ui.showResult(OM.game.run.summary || { mode: 'endless', day: 0, time: 91.4, cause: 'spike', nearMiss: 14, perfect: 5, flips: 88, world: OM.phys.WORLDS[1], result: { xp: 240, record: true, achievements: [], levelUp: false, level: 4 } }); });
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(__dirname, '..', 'dist', 'shot-result.png') });
    console.log('  screenshots written to dist/');
  }

  if (errors.length) {
    console.log('\n  CONSOLE ERRORS (' + errors.length + '):');
    errors.slice(0, 10).forEach(function (e) { console.log('    ' + e); });
  } else {
    console.log('  no console errors.');
  }
  console.log('');
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})();

function pad(s, n) { s = String(s); while (s.length < n) s += ' '; return s; }
function fmt(sec) {
  var m = Math.floor(sec / 60), s = sec - m * 60;
  return (m < 10 ? '0' + m : m) + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
}
