/* ONE MORE — screens.
   The only rule that matters here: from death to playing again must be one tap
   and no waiting. Everything else is arranged around not getting in the way of
   that. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var prog = OM.progress, P = OM.phys;
  var doc = root.document;

  var UI = OM.ui = { screen: null, lastMode: 'endless', lastFamily: null };
  var replay = null;
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

    readChallenge();
    root.addEventListener('hashchange', function () {
      readChallenge();
      if (UI.screen === 'menu') refreshMenu();
    });

    UI.show('menu');
  };

  function act(a) {
    switch (a) {
      case 'play': UI.startRun('endless'); break;
      case 'daily': UI.showDaily(); break;
      case 'play-daily': UI.startRun('daily'); break;
      case 'again': UI.startRun(UI.lastMode); break;
      case 'retry': UI.retryRun(); break;
      case 'challenge': UI.startRun('endless', { seed: UI.challenge }); break;
      case 'menu': UI.show('menu'); OM.game.state = 'idle'; OM.game.run = null; OM.audio.stopMusic(); break;
      case 'records': UI.showRecords(); break;
      case 'garage': UI.showGarage(); break;
      case 'settings': UI.showSettings(); break;
      case 'resume': UI.resume(); break;
      case 'quit': UI.show('menu'); OM.game.state = 'idle'; OM.game.run = null; OM.audio.stopMusic(); break;
      case 'share': UI.share(); break;
      case 'trial': UI.startTrial(); break;
      case 'nightmare': UI.startRun('nightmare'); break;
      case 'practice': UI.startRun('practice'); break;
    }
  }

  UI.show = function (name) {
    if (replay && name !== 'result') replay.stop();
    if (name !== 'records') stopSculpture();
    for (var k in screens) screens[k].classList.toggle('on', k === name);
    UI.screen = name;
    $('pause-btn').classList.toggle('on', name === null);
    if (name === 'menu') refreshMenu();
  };

  UI.hideAll = function () {
    if (replay) replay.stop();
    for (var k in screens) screens[k].classList.remove('on');
    UI.screen = null;
    $('pause-btn').classList.add('on');
  };

  UI.startRun = function (mode, opts) {
    UI.lastMode = mode;
    if (replay) replay.stop();
    UI.hideAll();
    OM.game.start(mode, opts || (mode === 'trial' ? { family: UI.lastFamily } : {}));
  };

  /* ---------- challenge links ----------
     A seed is the whole world, so a seed is the whole challenge. It rides in
     the hash where it costs no server and no round trip: open the link and the
     menu offers the exact run somebody else just played.

     Anything unparseable is ignored rather than coerced. A hash that produced
     *some* world for a link meant to produce a specific one would be the worst
     outcome available here — two people would believe they were playing the
     same thing and quietly not be. */
  function parseChallenge(hash) {
    var m = /(?:^|[#&])c=([0-9a-z]{1,7})(?:&|$)/i.exec(hash || '');
    if (!m) return null;
    var n = parseInt(m[1], 36);
    if (!isFinite(n) || n < 0 || n > 0xffffffff) return null;
    return n >>> 0;
  }

  function readChallenge() {
    UI.challenge = parseChallenge(root.location && root.location.hash);
    var cb = $('menu-challenge');
    if (UI.challenge == null) { cb.hidden = true; return; }
    cb.hidden = false;
    cb.querySelector('em').textContent = 'world ' + UI.code(UI.challenge) +
      ' \u00b7 sent to you';
  }

  UI.code = function (seed) { return (seed >>> 0).toString(36).toUpperCase(); };

  /* Only a real link is worth sharing. Under file:// the href is a path on
     somebody else's disk, so there is nothing to offer and we say nothing. */
  UI.challengeLink = function (seed) {
    var loc = root.location;
    if (!loc || !/^https?:$/.test(loc.protocol)) return null;
    return loc.href.split('#')[0] + '#c=' + UI.code(seed).toLowerCase();
  };

  /* The same world again: same obstacles, same mutations, same everything the
     seed derives. Nothing about the layout is stored — only the number it came
     from — so this cannot drift out of step with what the generator would build.
     Daily has no button because Daily is already this: ONE MORE replays it. */
  UI.retryRun = function () {
    var s = OM.game.run && OM.game.run.summary;
    if (!s || s.seed == null || s.mode === 'daily') return;
    UI.startRun(s.mode, { seed: s.seed, day: s.day, family: s.family,
                          pool: s.pool, ghost: s.ghost });
  };

  /* A Trial points the generator at whatever is actually killing you. It is not
     a different game — same physics, same proven patterns, different selection. */
  UI.startTrial = function () {
    var rd = OM.analysis.read();
    if (rd.kind !== 'weakness') { UI.toast('NOT ENOUGH RUNS YET'); return; }
    UI.lastFamily = rd.family;
    UI.startRun('trial', { family: rd.family });
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

    var nb = $('menu-nightmare');
    if (prog.nightmareUnlocked()) {
      nb.hidden = false;
      nb.querySelector('em').textContent = d.nightmare
        ? 'best ' + OM.fmtTime(d.nightmare, 2) : 'no warnings, no warm-up';
    } else nb.hidden = true;

    var cb = $('menu-challenge');
    cb.hidden = UI.challenge == null;

    /* A1 — lead with the read.
       The menu used to open on a tagline explaining the control, which every
       returning player has already understood. What it knows about them is the
       only thing on this screen they cannot get anywhere else, so once there is
       a read, that is what the menu says. It never invents one: below the
       evidence gate this stays hidden and the tagline carries the screen, which
       is also the correct behaviour on somebody's first ever launch.

       Monochrome throughout, per the visual identity — the panel earns its
       prominence from position and the rule down its left edge, not from an
       accent. */
    var mr = $('menu-read');
    var mrd = OM.analysis.read(), mhb = OM.analysis.habit();
    if (mhb) {
      mr.hidden = false;
      mr.innerHTML = '<b>' + mhb.headline + '</b><span>' + mhb.count + ' of your last ' +
        mhb.n + ' deaths, ' + mhb.mult.toFixed(1) + '\u00d7 what your own flip rate ' +
        'explains.</span>';
    } else if (mrd.kind === 'weakness') {
      mr.hidden = false;
      mr.innerHTML = '<b>' + mrd.headline + '</b><span>' + mrd.line + ' ' +
        Math.round(mrd.share * 100) + '% of your last ' + mrd.n + ' deaths.</span>';
    } else {
      mr.hidden = true;
    }

    var pb = $('menu-practice');
    if (d.runs >= 5) {
      pb.hidden = false;
      pb.querySelector('em').textContent =
        (d.practice ? 'best ' + OM.fmtTime(d.practice, 2) + ' \u00b7 ' : '') +
        P.PRACTICE_SPEED + 'px/s, static geometry only';
    } else pb.hidden = true;

    var rd = OM.analysis.read(), tb = $('menu-trial');
    if (rd.kind === 'weakness') {
      tb.hidden = false;
      var best = d.trial[rd.family];
      tb.querySelector('em').textContent = rd.headline.toLowerCase() +
        (best ? ' · best ' + OM.fmtTime(best, 2) : ' · not attempted');
    } else tb.hidden = true;
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
    /* The record this run was chasing, decided when it started. Re-deriving it
       here from the mode got it wrong for everything that is not endless. */
    var best = s.target || 0;
    var res = s.result;

    $('r-kicker').textContent = res.record
      ? (s.mode === 'trial' ? 'BEST TRIAL' : s.mode === 'practice' ? 'BEST PRACTICE' : 'NEW RECORD')
      : (s.mode === 'trial' ? 'TRIAL · ' + (OM.analysis.families[s.family || UI.lastFamily] || { name: '' }).name
         : s.mode === 'practice' ? 'PRACTICE · ' + P.PRACTICE_SPEED + 'PX/S'
                            : 'YOU SURVIVED');
    $('r-time').textContent = OM.fmtTime(s.time, 2);

    var dEl = $('r-delta');
    dEl.classList.toggle('record', !!res.record);
    if (res.record) {
      dEl.textContent = s.mode === 'daily' ? 'BEST TODAY'
                      : s.mode === 'practice' ? 'BEST IN PRACTICE' : 'PERSONAL BEST';
    } else if (best > 0) {
      // The number that creates "one more": how close you were, not how far.
      dEl.textContent = OM.fmtDelta(best - s.time) + ' FROM YOUR BEST · ' + OM.fmtTime(best, 2);
    } else dEl.textContent = '';

    $('r-stats').innerHTML =
      stat(s.nearMiss, 'NEAR MISS') + stat(s.perfect, 'PERFECT') +
      stat(s.flips, 'FLIPS') + stat(s.world.name, 'REACHED');

    doc.querySelector('#r-actions [data-act="retry"]').hidden =
      s.mode === 'daily' || s.seed == null;

    // last moments
    var box = doc.querySelector('.replay');
    if (!replay) replay = OM.ReplayPlayer($('r-replay'));
    if (s.replay && s.replay.frames && s.replay.frames.length > 6) {
      box.classList.remove('off');
      replay.load(s.replay);
      // the element has to be laid out before the canvas can size itself
      requestAnimationFrame(function () { replay.start(); });
    } else {
      box.classList.add('off');
      replay.stop();
    }

    renderRead(s);

    var li = prog.levelInfo();
    $('r-xpfill').style.transform = 'scaleX(' + li.frac.toFixed(4) + ')';
    /* Practice says out loud what it does not do, rather than showing +0 XP and
       leaving the player to work out whether that is a bug. */
    $('r-xplabel').textContent = s.mode === 'practice'
      ? 'PRACTICE · SEPARATE RECORD, NO XP'
      : 'LEVEL ' + li.level + (li.capped ? ' · MAX' : '') + '  +' + res.xp + ' XP';

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

  /* The habit, in the same voice as the rest of the read: the claim, the number
     underneath it, and what to do. The multiple is carried rather than hidden
     because it is the whole reason the claim is worth anything — 61% of deaths
     means nothing until you know it is twice what your own flip rate explains. */
  function habitLine(h) {
    return h.headline + ' · ' + Math.round(h.share * 100) + '% of deaths, ' +
           h.mult.toFixed(1) + '× normal for how often you flip. ' + h.fix;
  }

  /* One honest sentence, or nothing. Never a fabricated percentile, never a
     comparison to players we cannot see. */
  /* Whether the drilling worked, in a sentence, with both raw counts in it so
     the percentages can be checked. It says "since", never "because": the game
     knows what changed, not what caused it, and the difference is the whole
     reason this line is trustworthy. */
  function trialEffectLine(te) {
    var b = Math.round(te.before.share * 100), a = Math.round(te.after.share * 100);
    var counts = ' (' + te.before.count + ' of ' + te.before.n + ' \u2192 ' +
                 te.after.count + ' of ' + te.after.n + ')';
    var head = 'Since your first ' + te.name + ' trial, deaths to ' + te.noun + ' ';
    if (te.direction === 'flat') {
      return head + 'are unchanged: ' + b + '% then, ' + a + '% now' + counts + '.';
    }
    return head + (te.direction === 'down' ? 'have fallen from ' : 'have risen from ') +
           b + '% to ' + a + '%' + counts + '.';
  }

  function renderRead(s) {
    var el = $('r-read'), rd = OM.analysis.read(), hb = OM.analysis.habit(), tr = OM.analysis.trend();
    var html = '';
    if (rd.kind === 'none') {
      /* Before there are twelve deaths there is no read, and a countdown on its
         own is a promise with nothing under it. So the panel talks about the
         death that just happened instead — no statistics, only what was true of
         this one — and the countdown drops to a footnote where it belongs. */
      var mo = OM.analysis.moment(s);
      if (mo) {
        html = '<b>WHAT JUST HAPPENED</b><span>' + mo.where + ' ' + mo.when + '</span>' +
               '<i>' + rd.need + ' more run' + (rd.need === 1 ? '' : 's') +
               ' and the game can tell you what keeps killing you, not just what did.</i>';
      } else {
        html = '<b>READING YOU</b><span>' + rd.need +
               ' more run' + (rd.need === 1 ? '' : 's') +
               ' and the game will tell you what keeps killing you.</span>';
      }
    } else if (rd.kind === 'balanced') {
      html = '<b>' + rd.headline + '</b><span>' + rd.line + '</span>';
    } else {
      html = '<b>' + rd.headline + '</b><span>' + rd.line + ' ' +
             Math.round(rd.share * 100) + '% of your last ' + rd.n + ' deaths.</span>';
    }
    /* A habit is the more specific of the two claims and carries its own advice,
       so it stands in for the family's generic fix rather than stacking a second
       instruction under it. It is also the only thing the balanced read has ever
       had to offer, which is why that case is no longer always quiet. */
    if (hb) html += '<i>' + habitLine(hb) + '</i>';
    else if (rd.kind === 'weakness') html += '<i>' + rd.fix + '</i>';
    /* The early panel is saying something real, so it does not get the muted
       treatment reserved for having nothing to say. */
    el.className = (rd.kind === 'weakness' || hb || rd.kind === 'none') ? 'read' : 'read quiet';
    if (tr && Math.abs(tr.pct) > 0.12) {
      html += '<i>' + (tr.delta > 0 ? 'Improving: ' : 'Slipping: ') +
              'median run ' + OM.fmtTime(tr.early, 2) + ' \u2192 ' + OM.fmtTime(tr.recent, 2) + '</i>';
    }
    /* The payoff the read has always set up and never delivered. After a Trial
       it goes at the top, because on that screen it is the answer to the
       question the run was asking. */
    var te = OM.analysis.trialEffect(s.mode === 'trial' ? (s.family || UI.lastFamily)
                                                        : (rd.family || null));
    if (te) {
      var block = '<i class="verdict">' + trialEffectLine(te) + '</i>';
      if (s.mode === 'trial') { html = block + html; el.className = 'read'; }
      else html += block;
    }

    el.innerHTML = html;
    var tb = doc.querySelector('#r-actions [data-act="trial"]');
    tb.hidden = rd.kind !== 'weakness';
    if (rd.kind === 'weakness') UI.lastFamily = rd.family;
  }

  /* The archive. Firsts only, in the order they happened, with the run that
     earned each one. It says nothing until there is something to say — a list
     of empty slots is a chore list, and this is meant to be a history. */
  function archiveBlock() {
    var a = prog.archive();
    if (!a.length) return '';
    var rows = a.map(function (m) {
      var when = new Date(m.at);
      var stamp = when.getFullYear() + '-' +
        ('0' + (when.getMonth() + 1)).slice(-2) + '-' + ('0' + when.getDate()).slice(-2);
      return '<div class="mark"><canvas class="glyph" data-glyph="' + m.id + '"></canvas>' +
             '<b>' + m.name + '</b>' +
             '<span>' + m.line + '</span>' +
             '<i>' + stamp + (m.t ? ' \u00b7 ' + OM.fmtTime(m.t, 2) : '') + '</i></div>';
    }).join('');
    return '<h3>ARCHIVE</h3><div class="archive">' + rows + '</div>';
  }

  /* Each archive entry carries its own mark, generated from its id so it is the
     same everywhere and forever. They are never explained. */
  function paintGlyphs() {
    var list = doc.querySelectorAll('#rec-body .glyph');
    var dpr = Math.min(root.devicePixelRatio || 1, 2);
    for (var i = 0; i < list.length; i++) {
      var cv = list[i], id = cv.getAttribute('data-glyph');
      var rect = cv.getBoundingClientRect();
      var w = Math.max(1, Math.round(rect.width * dpr));
      var h = Math.max(1, Math.round(rect.height * dpr));
      if (!w || !h) continue;
      cv.width = w; cv.height = h;
      var g = cv.getContext('2d');
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      OM.glyphs.draw(g, id, rect.width / 2, rect.height / 2,
                     Math.min(rect.width, rect.height) * 0.36, 0.5);
    }
  }

  /* ---------- run sculpture ----------
     On the records screen, not the results screen. The one metric that matters
     after a death is how fast the player gets to the next run, and a second
     animated canvas between them and the ONE MORE button buys atmosphere with
     the only currency this game refuses to spend. Here it is something to come
     and look at instead. */
  var sculptRaf = 0, sculptT = 0;
  function stopSculpture() {
    if (sculptRaf) { root.cancelAnimationFrame(sculptRaf); sculptRaf = 0; }
  }
  function startSculpture() {
    var cv = $('rec-sculpt');
    if (!cv) return;
    var s = OM.sculpture.build(prog.data.ghost);
    if (!s) { cv.parentNode.hidden = true; return; }
    cv.parentNode.hidden = false;
    var g = cv.getContext('2d');
    var last = 0;
    stopSculpture();
    function frame(now) {
      if (UI.screen !== 'records') { sculptRaf = 0; return; }
      var dt = last ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;
      sculptT += dt;
      var rect = cv.getBoundingClientRect();
      var dpr = Math.min(root.devicePixelRatio || 1, 2);
      var w = Math.max(1, Math.round(rect.width * dpr));
      var h = Math.max(1, Math.round(rect.height * dpr));
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, rect.width, rect.height);
      OM.sculpture.draw(g, rect.width, rect.height, s, sculptT);
      sculptRaf = root.requestAnimationFrame(frame);
    }
    sculptRaf = root.requestAnimationFrame(frame);
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

    var rd = OM.analysis.read(), hb = OM.analysis.habit(), tr = OM.analysis.trend(), tl = OM.analysis.tally();
    var readBlock = '';
    if (rd.kind === 'weakness') {
      readBlock = '<b>' + rd.headline + '</b><span>' + rd.line + ' ' +
        rd.count + ' of your last ' + rd.n + ' deaths (' + Math.round(rd.share * 100) + '%).</span>' +
        '<i>' + rd.fix + '</i>';
    } else if (rd.kind === 'balanced') {
      readBlock = '<b>' + rd.headline + '</b><span>' + rd.line + '</span>';
    } else {
      readBlock = '<b>READING YOU</b><span>' + rd.need +
        ' more runs before the game can say anything useful about how you play.</span>';
    }
    /* This is the screen you come to in order to study, so the habit sits
       alongside the family advice here rather than replacing it as it does on
       the results screen, and it spells out the baseline it was judged against
       instead of compressing that into a multiple. */
    if (hb) {
      readBlock += '<i>' + hb.headline + ' · ' + hb.count + ' of ' + hb.n + ' deaths (' +
        Math.round(hb.share * 100) + '%), against ' + Math.round(hb.expected * 100) +
        '% expected at your flip rate. ' + hb.fix + '</i>';
    }
    /* On the study screen every family that has a measurement is shown, not just
       the strongest one. This is the page you come to in order to look things
       up, and a drill that made something worse belongs here as much as one
       that worked. */
    var tes = OM.analysis.trialEffects();
    for (var ti = 0; ti < tes.length; ti++) {
      readBlock += '<i class="verdict">' + trialEffectLine(tes[ti]) + '</i>';
    }

    readBlock = '<div class="read' +
      ((rd.kind === 'weakness' || hb) ? '' : ' quiet') + '">' + readBlock + '</div>';
    if (tr) {
      readBlock += '<div class="list">' +
        row('Median run, first 15', OM.fmtTime(tr.early, 2)) +
        row('Median run, last 15', OM.fmtTime(tr.recent, 2)) +
        row('Change', (tr.delta >= 0 ? '+' : '') + OM.fmtDelta(tr.delta)) +
      '</div>';
    }
    var famRows = Object.keys(tl.byFamily).sort(function (a, b) { return tl.byFamily[b] - tl.byFamily[a]; })
      .map(function (f) {
        return row(OM.analysis.families[f].name.charAt(0) + OM.analysis.families[f].name.slice(1).toLowerCase(),
                   tl.byFamily[f] + ' · ' + Math.round(tl.byFamily[f] / tl.n * 100) + '%');
      }).join('');

    $('rec-body').innerHTML =
      '<h3>THE READ</h3>' + readBlock +
      archiveBlock() +
      sparkline(OM.analysis.history()) +
      '<h3>YOUR BEST RUN, AS AN OBJECT</h3>' +
      '<div class="sculpt"><canvas id="rec-sculpt"></canvas></div>' +
      '<p class="muted small" style="text-align:left;margin:0 0 6px">' +
      'Wound from the path you actually took: height is time, radius is where ' +
      'you were in the tunnel, and every mark is a flip.</p>' +
      weaknessChart() +
      (famRows ? '<h3>DEATHS BY KIND</h3><div class="list">' + famRows + '</div>' : '') +
      '<div class="split"><div><span class="lbl">BEST RUN</span><span class="val">' +
        (d.best ? OM.fmtTime(d.best, 2) : '—') + '</span></div>' +
      '<div><span class="lbl">LEVEL</span><span class="val">' + li.level + '</span></div>' +
      '<div><span class="lbl">RUNS</span><span class="val">' + d.runs + '</span></div></div>' +
      (d.nightmare ? '<div class="list">' + row('Nightmare best', OM.fmtTime(d.nightmare, 2)) +
        Object.keys(d.trial).map(function (f) {
          return row('Trial · ' + OM.analysis.families[f].name, OM.fmtTime(d.trial[f], 2));
        }).join('') + '</div>' : '') +

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
      '<p class="muted small">Everything here is measured from your own runs and stored on this device. ' +
      'There is no server yet, so nothing here is a global leaderboard and nothing is compared to other players.</p>';
    UI.show('records');
    paintGlyphs();
    startSculpture();
  };

  function row(k, v) { return '<div class="item"><b>' + k + '</b><span>' + v + '</span></div>'; }

  /* Your last thirty runs as bars, with your best marked. Inline SVG so it
     needs no canvas lifecycle and scales with the layout. It is the clearest
     possible answer to "am I actually getting better". */
  function sparkline(hist) {
    var runs = hist.slice(-30);
    if (runs.length < 6) return '';
    var max = 0, i;
    for (i = 0; i < runs.length; i++) max = Math.max(max, runs[i].t);
    if (max <= 0) return '';
    var W = 100, H = 30, bw = W / runs.length, bars = '', bestI = 0;
    for (i = 0; i < runs.length; i++) if (runs[i].t > runs[bestI].t) bestI = i;
    for (i = 0; i < runs.length; i++) {
      var h = Math.max(0.8, (runs[i].t / max) * (H - 2));
      bars += '<rect x="' + (i * bw + bw * 0.16).toFixed(2) + '" y="' + (H - h).toFixed(2) +
              '" width="' + (bw * 0.68).toFixed(2) + '" height="' + h.toFixed(2) +
              '" fill="' + (i === bestI ? '#e8eaf0' : 'rgba(232,234,240,0.34)') + '"/>';
    }
    return '<h3>LAST ' + runs.length + ' RUNS</h3>' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" ' +
      'style="width:100%;height:64px;display:block;margin:10px 0 4px" role="img" ' +
      'aria-label="Bar chart of your last ' + runs.length + ' run times, longest run highlighted">' +
      bars + '</svg>' +
      '<p class="muted small" style="text-align:left;margin:0 0 6px">' +
      'oldest on the left · longest run highlighted · peak ' + OM.fmtTime(max, 2) + '</p>';
  }
  /* The read as a history. Four families in four weights of the same ink,
     oldest bucket on the left — monochrome, so the legend does the job colour
     would, and the stacking order is fixed so the shape means the same thing
     every time you look at it. */
  var BAND_INK = { timing: 0.88, prediction: 0.62, commitment: 0.38, nerve: 0.18 };
  function bandFill(f) { return 'rgba(232,234,240,' + (BAND_INK[f] || 0.5) + ')'; }

  function weaknessChart() {
    var wb = OM.analysis.weaknessBands(8);
    if (!wb) return '';
    var W = 100, H = 30, bw = W / wb.buckets.length, rects = '', i, k;
    for (i = 0; i < wb.buckets.length; i++) {
      var b = wb.buckets[i], y = 0;
      for (k = 0; k < wb.order.length; k++) {
        var f = wb.order[k], c = b.counts[f] || 0;
        if (!c) continue;
        var h = (c / b.n) * H;
        rects += '<rect x="' + (i * bw + bw * 0.08).toFixed(2) + '" y="' + y.toFixed(2) +
                 '" width="' + (bw * 0.84).toFixed(2) + '" height="' + h.toFixed(2) +
                 '" fill="' + bandFill(f) + '"/>';
        y += h;
      }
    }
    var legend = '';
    for (k = 0; k < wb.order.length; k++) {
      legend += '<span><i style="background:' + bandFill(wb.order[k]) + '"></i>' +
                OM.analysis.families[wb.order[k]].name + '</span>';
    }
    var sh = OM.analysis.shift();
    /* The exclusion is stated either way. DEATHS BY KIND below counts every
       death including Trials, so without this the two panels would quietly
       disagree about the same word and there would be no way to tell why. */
    var note = sh
      ? 'You used to die to ' + sh.from.noun + ' (' + Math.round(sh.from.share * 100) +
        '% of ' + sh.from.n + '); now it is ' + sh.to.noun + ' (' +
        Math.round(sh.to.share * 100) + '% of ' + sh.to.n + '). Trial runs excluded.'
      : 'oldest on the left \u00b7 ' + wb.n + ' deaths, trial runs excluded';
    return '<h3>WHAT HAS BEEN KILLING YOU</h3>' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" ' +
      'style="width:100%;height:64px;display:block;margin:10px 0 6px" role="img" ' +
      'aria-label="Stacked bars showing which kind of obstacle killed you over ' +
      wb.n + ' deaths, oldest on the left">' + rects + '</svg>' +
      '<p class="legend">' + legend + '</p>' +
      '<p class="muted small" style="text-align:left;margin:0 0 6px">' + note + '</p>';
  }

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
      (function () {
        var next = prog.cores.filter(function (x) { return x.at > lv; })[0];
        return '<p class="muted small">Level ' + lv + '. ' +
          (next ? 'Next evolution at level ' + next.at + '.'
                : 'Every evolution unlocked.') + '</p>';
      })();

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
    /* Visual quality is a real choice, not an auto-detected one. A frame-rate
       probe on the first run guesses from whatever the device happened to be
       doing that second, and guesses wrong on the exact phones that most need
       it right. Every tier draws the geometry, the surfaces, the character's
       silhouette and its core — only the layers that exist to look expensive
       scale — so nobody loses anything they need to play. */
    var QUAL = [['high', 'Full'], ['medium', 'Reduced'], ['low', 'Minimal']];
    $('set-body').innerHTML = items.map(function (it) {
      return '<div class="toggle"><span>' + it[1] + '</span>' +
             '<button data-set="' + it[0] + '" aria-pressed="' + !!s[it[0]] + '"></button></div>';
    }).join('') +
    '<div class="toggle"><span>Visual effects</span><span class="qual">' +
      QUAL.map(function (qq) {
        return '<button data-qual="' + qq[0] + '" aria-pressed="' +
               (s.quality === qq[0]) + '">' + qq[1] + '</button>';
      }).join('') + '</span></div>' +
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
    var qbtns = $('set-body').querySelectorAll('[data-qual]');
    for (var qi = 0; qi < qbtns.length; qi++) {
      qbtns[qi].addEventListener('click', function () {
        s.quality = this.getAttribute('data-qual');
        OM.visual.setQuality(s.quality);
        for (var k = 0; k < qbtns.length; k++) {
          qbtns[k].setAttribute('aria-pressed',
            String(qbtns[k].getAttribute('data-qual') === s.quality));
        }
        prog.touch(); prog.flush();
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
     clipboard otherwise.

     What gets shared is the read, not the time. A time is unarguable and so it
     travels nowhere; a claim about how someone plays is the part a reader can
     answer. Below the evidence gate shareClaim() returns null and we fall back
     to the time — manufacturing a read at run three to make a better share
     string is exactly the trade this game does not make. */
  UI.share = function () {
    var s = OM.game.run && OM.game.run.summary;
    if (!s) return;
    var head = 'ONE MORE · ' + OM.fmtTime(s.time, 2) +
      (s.mode === 'daily' ? ' on Daily ' + OM.dayKey(s.day) : '') +
      (s.mode === 'practice' ? ' in practice at ' + P.PRACTICE_SPEED + 'px/s' : '');
    var claim = OM.analysis.shareClaim();
    var text = claim
      ? head + ' — and it says ' + claim + '. What does it say about you?'
      : head + ' · ' + s.perfect + ' perfect switches · reached ' +
        s.world.name + '. Can you beat it?';

    /* The world comes along with the claim, so "can you beat it" is answerable
       on the run that actually beat me rather than on a different one.
       Endless only: the same seed under a Trial or Nightmare builds a different
       world, and Daily already gives everyone today's, so a link there would
       hand them something other than what it appears to. */
    var link = s.mode === 'endless' ? UI.challengeLink(s.seed) : null;
    if (link) text += '\n' + link;
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
