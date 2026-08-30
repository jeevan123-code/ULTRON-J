/* ONE MORE — boot: canvas, input, the frame loop. */
(function (root) {
  'use strict';
  var OM = root.OM;
  var doc = root.document;

  function start() {
    var canvas = doc.getElementById('stage');
    OM.game.attach(canvas);
    OM.ui.init();

    var s = OM.progress.data.settings;
    OM.audio.setMuted(!s.sound);
    OM.audio.setMusic(s.music && s.sound);

    /* ---------- input ----------
       pointerdown, not click: it fires on touch-down rather than touch-up,
       which is the difference between a game that feels instant and one that
       feels like a web page. */
    function press(e) {
      if (OM.ui.screen !== null) return;      // a menu is open; let it have the tap
      e.preventDefault();
      OM.audio.unlock();
      OM.game.flip();
    }
    canvas.addEventListener('pointerdown', press);

    /* The results screen scrolls on a phone, so "tap anywhere to go again" has
       to be a real tap: press and release in the same place, quickly. Firing on
       pointerdown would restart the run every time somebody tried to scroll
       down to read the death analysis. */
    var resultEl = doc.getElementById('s-result');
    var tap = null;
    resultEl.addEventListener('pointerdown', function (e) {
      if (e.target && e.target.closest && e.target.closest('[data-act], canvas')) { tap = null; return; }
      tap = { x: e.clientX, y: e.clientY, t: performance.now() };
    });
    resultEl.addEventListener('pointerup', function (e) {
      if (!tap) return;
      var moved = Math.abs(e.clientX - tap.x) + Math.abs(e.clientY - tap.y);
      var held = performance.now() - tap.t;
      tap = null;
      if (moved > 12 || held > 500) return;                 // that was a scroll or a hold
      if (OM.ui.screen !== 'result') return;
      if (!OM.game.run || OM.game.run.deadFor <= 0.22) return;
      e.preventDefault();
      OM.ui.startRun(OM.ui.lastMode);
    });
    resultEl.addEventListener('pointercancel', function () { tap = null; });

    doc.addEventListener('keydown', function (e) {
      if (e.repeat) return;
      var k = e.key;
      if (k === ' ' || k === 'ArrowUp' || k === 'ArrowDown' || k === 'w' || k === 'W') {
        e.preventDefault();
        OM.audio.unlock();
        if (OM.ui.screen === 'result') {
          if (OM.game.run && OM.game.run.deadFor > 0.22) OM.ui.startRun(OM.ui.lastMode);
        } else if (OM.ui.screen === 'menu') OM.ui.startRun('endless');
        else if (OM.ui.screen === null) OM.game.flip();
      } else if (k === 'Escape' || k === 'p' || k === 'P') {
        if (OM.game.state === 'playing') OM.ui.pause();
        else if (OM.game.state === 'paused') OM.ui.resume();
      }
    });

    // Losing focus mid-run must pause, never kill: a notification should not
    // cost somebody their record.
    doc.addEventListener('visibilitychange', function () {
      if (doc.hidden && OM.game.state === 'playing') OM.ui.pause();
    });
    root.addEventListener('blur', function () {
      if (OM.game.state === 'playing') OM.ui.pause();
    });

    /* ---------- loop ---------- */
    var last = performance.now();
    function frame(now) {
      var dt = (now - last) / 1000;
      last = now;
      // A long stall (tab switch, GC) must not teleport the player through a
      // wall — clamp instead of integrating a two second step.
      if (dt > 0.05) dt = 0.05;

      if (OM.game.state === 'playing' || OM.game.state === 'dead') {
        OM.game.tick(dt);
      } else if (OM.game.state === 'paused') {
        OM.game.draw();
      } else {
        OM.game.drawMenuNanogon(now / 1000);
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})(typeof globalThis !== 'undefined' ? globalThis : this);
