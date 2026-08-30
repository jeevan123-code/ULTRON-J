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
  await page.waitForTimeout(120);
  ok('PLAY starts a run', await page.evaluate('OM.game.state') === 'playing');
  ok('menus get out of the way', await page.evaluate('OM.ui.screen') === null);

  // a tap on the canvas must flip gravity
  var g0 = await page.evaluate('OM.game.run.grav');
  await page.tap('#stage');
  await page.waitForTimeout(60);
  ok('tapping the canvas flips gravity', await page.evaluate('OM.game.run.grav') !== g0);

  // pause and resume must not lose the run
  await page.click('#pause-btn');
  await page.waitForTimeout(80);
  ok('pause halts the run', await page.evaluate('OM.game.state') === 'paused');
  var tPaused = await page.evaluate('OM.game.run.t');
  await page.waitForTimeout(400);
  ok('time does not advance while paused',
     Math.abs(await page.evaluate('OM.game.run.t') - tPaused) < 0.02);
  await page.click('[data-act="resume"]');
  await page.waitForTimeout(80);
  ok('resume returns to play', await page.evaluate('OM.game.state') === 'playing');

  // die on purpose, then check the results screen and the one-tap restart
  await page.evaluate(function () {
    var t = 0;
    while (OM.game.state === 'playing' && t < 90) { OM.game.stepHeadless(1 / 120); t += 1 / 120; }
  });
  ok('a run ends in death, not a hang', await page.evaluate('OM.game.state') === 'dead');
  await page.waitForTimeout(900);
  ok('results appear after death', await page.evaluate('OM.ui.screen') === 'result');
  var shown = await page.textContent('#r-time');
  ok('results show the survival time', /^\d\d:\d\d\.\d\d$/.test(shown), shown);
  ok('first run is recorded as a record',
     (await page.textContent('#r-kicker')).indexOf('RECORD') >= 0);
  ok('xp was awarded', (await page.textContent('#r-xplabel')).indexOf('+') >= 0);

  await page.tap('#s-result', { position: { x: 200, y: 60 } });
  await page.waitForTimeout(150);
  ok('tapping the results screen goes again', await page.evaluate('OM.game.state') === 'playing');

  // the second run must show the gap to the record — the "one more" engine
  ok('the run knows the record to chase', await page.evaluate('OM.game.run.target') > 0);
  ok('a ghost of the record run is loaded', await page.evaluate('!!OM.game.run.ghost'));

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
