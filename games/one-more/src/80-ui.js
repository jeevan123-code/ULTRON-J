/* ONE MORE — screens.
   The only rule that matters here: from death to playing again must be one tap
   and no waiting. Everything else is arranged around not getting in the way of
   that. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var prog = OM.progress, P = OM.phys;
  var doc = root.document;

  var UI = OM.ui = { screen: null, lastMode: 'endless' };
  var $ = function (id) { return doc.getElementById(id); };
  var screens = {};

  UI.init = function () {
    var nodes = doc.querySelectorAll('[data-screen]');
    for (var i = 0; i < nodes.length; i++) screens[nodes[i].getAttribute('data-screen')] = nodes[i];

    doc.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-act]') : null;
      if (!b) return;
      e.stopPropagation();
      OM.audio.unlock();
      OM.audio.play('ui');
      act(b.getAttribute('data-act'));
    });

    $('pause-btn').addEventListener('click', function (e) { e.stopPropagation(); UI.pause(); });

    OM.bus.on('run:end', function (s) { setTimeout(function () { UI.showResult(s); }, 620); });
    OM.bus.on('run:again', function (mode) { UI.startRun(mode); });
    OM.bus.on('run:passed-best', function () { UI.toast('BEST BEATEN'); });

    UI.show('menu');
  };

  function act(a) {
    switch (a) {
      case 'play': UI.startRun('endless'); break;
      case 'daily': UI.showDaily(); break;
      case 'play-daily': UI.startRun('daily'); break;
      case 'again': UI.startRun(UI.lastMode); break;
      case 'menu': UI.show('menu'); OM.game.state = 'idle'; OM.game.run = null; OM.audio.stopMusic(); break;
      case 'records': UI.showRecords(); break;
      case 'garage': UI.showGarage(); break;
      case 'settings': UI.showSettings(); break;
      case 'resume': UI.resume(); break;
      case 'quit': UI.show('menu'); OM.game.state = 'idle'; OM.game.run = null; OM.audio.stopMusic(); break;
      case 'share': UI.share(); break;
    }
  }

  UI.show = function (name) {
    for (var k in screens) screens[k].classList.toggle('on', k === name);
    UI.screen = name;
    $('pause-btn').classList.toggle('on', name === null);
    if (name === 'menu') refreshMenu();
  };

  UI.hideAll = function () {
    for (var k in screens) screens[k].classList.remove('on');
    UI.screen = null;
    $('pause-btn').classList.add('on');
  };

  UI.startRun = function (mode) {
    UI.lastMode = mode;
    UI.hideAll();
    OM.game.start(mode, {});
  };

  UI.pause = function () {
    if (OM.game.state !== 'playing') return;
    OM.game.state = 'paused';
    OM.audio.stopMusic();
    UI.show('pause');
    $('pause-btn').classList.remove('on');
  };
  UI.resume = function () {
    if (OM.game.state !== 'paused') return;
    OM.game.state = 'playing';
    UI.hideAll();
  };

  /* ---------- menu ---------- */
  function refreshMenu() {
    var d = prog.data, li = prog.levelInfo();
    $('menu-best').textContent = d.best > 0 ? 'BEST ' + OM.fmtTime(d.best, 2) : 'NO RUNS YET';
    $('menu-level').textContent = 'LEVEL ' + li.level;
    var tagEl = doc.querySelector('#s-menu .tag');
    if (tagEl) {
      tagEl.textContent = OM.game.portrait
        ? 'Tap to flip gravity. Turn your phone sideways for a wider view.'
        : 'Tap to flip gravity. Survive one more time.';
    }
    var key = OM.dayKey(OM.dayIndex());
    var done = d.daily[key];
    $('daily-badge').textContent = done ? 'today: ' + OM.fmtTime(done, 2) : 'not played today';
  }

  /* ---------- daily ---------- */
  UI.showDaily = function () {
    var idx = OM.dayIndex(), key = OM.dayKey(idx);
    $('d-day').textContent = 'DAY ' + (idx - 20000);
    $('d-date').textContent = key + ' · UTC';
    $('d-best').textContent = prog.data.daily[key] ? OM.fmtTime(prog.data.daily[key], 2) : '—';
    $('d-streak').textContent = prog.dailyStreak() + 'd';
    var ms = OM.msUntilNextDay();
    var h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60;
    $('d-reset').textContent = 'New challenge in ' + h + 'h ' + m + 'm.';
    UI.show('daily');
  };

  /* ---------- results ---------- */
  UI.showResult = function (s) {
    var d = prog.data;
    var best = s.mode === 'endless' ? d.best : (d.daily[OM.dayKey(s.day)] || 0);
    var res = s.result;

    $('r-kicker').textContent = res.record ? 'NEW RECORD' : 'YOU SURVIVED';
    $('r-time').textContent = OM.fmtTime(s.time, 2);

    var dEl = $('r-delta');
    dEl.classList.toggle('record', !!res.record);
    if (res.record) {
      dEl.textContent = s.mode === 'daily' ? 'BEST TODAY' : 'PERSONAL BEST';
    } else if (best > 0) {
      // The number that creates "one more": how close you were, not how far.
      dEl.textContent = OM.fmtDelta(best - s.time) + ' FROM YOUR BEST · ' + OM.fmtTime(best, 2);
    } else dEl.textContent = '';

    $('r-stats').innerHTML =
      stat(s.nearMiss, 'NEAR MISS') + stat(s.perfect, 'PERFECT') +
      stat(s.flips, 'FLIPS') + stat(s.world.name, 'REACHED');

    var li = prog.levelInfo();
    $('r-xpfill').style.width = (li.frac * 100).toFixed(1) + '%';
    $('r-xplabel').textContent = 'LEVEL ' + li.level + '  +' + res.xp + ' XP';

    var un = [];
    if (res.levelUp) un.push('LEVEL ' + res.level + ' REACHED');
    for (var i = 0; i < res.achievements.length; i++) un.push('UNLOCKED · ' + res.achievements[i].name);
    var newCore = prog.cores.filter(function (c) { return c.at === res.level; })[0];
    if (res.levelUp && newCore) un.push('EVOLUTION · ' + newCore.name);
    $('r-unlocks').innerHTML = un.map(function (t) { return '<p>' + t + '</p>'; }).join('');
    if (res.levelUp) OM.audio.play('level');

    UI.show('result');
  };

  function stat(v, k) {
    return '<div><span class="n">' + v + '</span><span class="k">' + k + '</span></div>';
  }

  /* ---------- records ---------- */
  UI.showRecords = function () {
    var d = prog.data, li = prog.levelInfo();
    var causes = Object.keys(d.deaths).sort(function (a, b) { return d.deaths[b] - d.deaths[a]; });
    var CAUSE = { spike: 'Spikes', block: 'Blocks', bar: 'Bars', mover: 'Movers', laser: 'Lasers', void: 'The void' };

    var days = [], today = OM.dayIndex();
    for (var i = 0; i < 7; i++) {
      var k = OM.dayKey(today - i);
      days.push(row(k + (i === 0 ? ' · today' : ''), d.daily[k] ? OM.fmtTime(d.daily[k], 2) : '—'));
    }

    $('rec-body').innerHTML =
      '<div class="split"><div><span class="lbl">BEST RUN</span><span class="val">' +
        (d.best ? OM.fmtTime(d.best, 2) : '—') + '</span></div>' +
      '<div><span class="lbl">LEVEL</span><span class="val">' + li.level + '</span></div>' +
      '<div><span class="lbl">RUNS</span><span class="val">' + d.runs + '</span></div></div>' +

      '<h3>TOTALS</h3><div class="list">' +
        row('Time survived', fmtLong(d.totalTime)) +
        row('Near misses', d.nearMiss) +
        row('Perfect switches', d.perfect) +
        row('Gravity flips', d.flips) +
        row('Daily challenges', d.dailyDone.length + ' · streak ' + prog.dailyStreak() + 'd') +
      '</div>' +

      '<h3>WHAT KILLS YOU</h3><div class="list">' +
        (causes.length ? causes.map(function (c) {
          return row(CAUSE[c] || c, d.deaths[c] + ' × ' + Math.round(d.deaths[c] / d.runs * 100) + '%');
        }).join('') : row('Nothing yet', '—')) +
      '</div>' +

      '<h3>DAILY · LAST 7</h3><div class="list">' + days.join('') + '</div>' +

      '<h3>ACHIEVEMENTS</h3><div class="list">' +
        prog.achievements.map(function (a) {
          var got = d.achievements.indexOf(a.id) >= 0;
          return '<div class="item' + (got ? '' : ' locked') + '"><b>' + a.name +
                 '<i>' + a.line + '</i></b><span>' + (got ? '✓' : '') + '</span></div>';
        }).join('') +
      '</div>' +
      '<p class="muted small">Records are stored on this device only. There is no server yet, so nothing here is a global leaderboard.</p>';
    UI.show('records');
  };

  function row(k, v) { return '<div class="item"><b>' + k + '</b><span>' + v + '</span></div>'; }
  function fmtLong(sec) {
    var h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60;
    return (h ? h + 'h ' : '') + m + 'm ' + Math.floor(sec % 60) + 's';
  }

  /* ---------- garage ---------- */
  UI.showGarage = function () {
    var lv = prog.levelInfo().level, c = prog.data.cosmetics;
    function group(title, list, kind, current, extra) {
      return '<h3>' + title + '</h3><div class="chips">' + (extra || '') + list.map(function (it) {
        var open = lv >= it.at;
        return '<button class="chip' + (current === it.id ? ' on' : '') + '"' +
               (open ? '' : ' disabled') + ' data-kind="' + kind + '" data-id="' + it.id + '">' +
               it.name + '<small>' + (open ? (it.line || 'unlocked') : 'LEVEL ' + it.at) + '</small></button>';
      }).join('') + '</div>';
    }
    var autoChip = '<button class="chip' + (c.core === 'auto' ? ' on' : '') +
      '" data-kind="core" data-id="auto">AUTO<small>follows your level</small></button>';
    $('gar-body').innerHTML =
      group('CORE', prog.cores, 'core', c.core, autoChip) +
      group('TRAIL', prog.trails, 'trail', c.trail) +
      group('DEATH', prog.deaths, 'death', c.death) +
      '<p class="muted small">Level ' + lv + '. Next evolution at level ' +
        (prog.cores.filter(function (x) { return x.at > lv; })[0] || { at: '—' }).at + '.</p>';

    var chips = $('gar-body').querySelectorAll('.chip');
    for (var i = 0; i < chips.length; i++) {
      chips[i].addEventListener('click', function (e) {
        var kind = this.getAttribute('data-kind');
        prog.data.cosmetics[kind] = this.getAttribute('data-id');
        prog.touch(); prog.flush();
        OM.audio.play('ui');
        UI.showGarage();
      });
    }
    UI.show('garage');
  };

  /* ---------- settings ---------- */
  UI.showSettings = function () {
    var s = prog.data.settings;
    var items = [
      ['sound', 'Sound effects'], ['music', 'Music'],
      ['shake', 'Screen shake'], ['haptics', 'Haptics'], ['reduced', 'Reduced motion']
    ];
    $('set-body').innerHTML = items.map(function (it) {
      return '<div class="toggle"><span>' + it[1] + '</span>' +
             '<button data-set="' + it[0] + '" aria-pressed="' + !!s[it[0]] + '"></button></div>';
    }).join('') +
    '<p class="muted small" style="margin-top:22px">ONE MORE stores your records in this browser. Nothing is uploaded.</p>' +
    '<button class="btn small" id="wipe" style="margin-top:8px">ERASE ALL DATA</button>';

    var btns = $('set-body').querySelectorAll('[data-set]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        var k = this.getAttribute('data-set');
        s[k] = !s[k];
        this.setAttribute('aria-pressed', String(s[k]));
        prog.touch(); prog.flush();
        OM.audio.setMuted(!s.sound);
        OM.audio.setMusic(s.music && s.sound);
        OM.audio.play('ui');
      });
    }
    var wipe = $('wipe'), armed = false;
    wipe.addEventListener('click', function () {
      if (!armed) { armed = true; wipe.textContent = 'TAP AGAIN TO CONFIRM'; return; }
      prog.reset();
      UI.toast('DATA ERASED');
      UI.show('menu');
    });
    UI.show('settings');
  };

  /* ---------- share ----------
     No download link: the artifact sandbox blocks page-initiated downloads and
     a dead button is worse than no button. Native share if the device has it,
     clipboard otherwise. */
  UI.share = function () {
    var s = OM.game.run && OM.game.run.summary;
    if (!s) return;
    var text = 'ONE MORE — I survived ' + OM.fmtTime(s.time, 2) +
      (s.mode === 'daily' ? ' on Daily ' + OM.dayKey(s.day) : '') +
      ' · ' + s.perfect + ' perfect switches · reached ' + s.world.name + '. Can you beat it?';
    if (root.navigator && root.navigator.share) {
      root.navigator.share({ title: 'ONE MORE', text: text }).catch(function () {});
      return;
    }
    if (root.navigator && root.navigator.clipboard) {
      root.navigator.clipboard.writeText(text).then(
        function () { UI.toast('RESULT COPIED'); },
        function () { UI.toast('COULD NOT COPY'); }
      );
    } else UI.toast('SHARING UNAVAILABLE');
  };

  var toastT = 0;
  UI.toast = function (msg) {
    var el = $('toast');
    el.textContent = msg;
    el.classList.add('on');
    clearTimeout(toastT);
    toastT = setTimeout(function () { el.classList.remove('on'); }, 1700);
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
