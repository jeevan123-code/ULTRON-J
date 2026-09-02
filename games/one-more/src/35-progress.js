/* ONE MORE — save data, XP, unlocks, records, statistics.
   Everything is local. There is no server, so there is nothing here that
   claims to be a global leaderboard: the only opponents are your own past runs,
   and the UI says exactly that. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var KEY = 'onemore.save.v1';

  var DEFAULT = {
    v: 1, xp: 0, runs: 0, totalTime: 0,
    best: 0, bestAt: 0,
    daily: {},            // dayKey -> best seconds
    trial: {},            // weakness family -> best seconds
    nightmare: 0,         // best in the unlockable hard mode
    practice: 0,          // best at the fixed practice speed, kept apart on purpose
    practiceRuns: 0,
    dailyDone: [],        // dayKeys played, for the streak
    nearMiss: 0, perfect: 0, flips: 0, deaths: {},
    cosmetics: { core: 'auto', trail: 'line', death: 'shatter' },
    achievements: [],
    seen: { tutorial: false },
    /* The archive. Milestones, each written exactly once, with the run that
       earned it and when. Kept as a flat map rather than a list so recording
       one is idempotent — a milestone that could fire twice is a milestone
       that will, on some replay path nobody thought about. */
    marks: {},
    settings: { sound: true, music: true, shake: true, haptics: true, reduced: false, quality: 'high' },
    ghost: null,          // best endless run, for racing your own record
    ghostTime: 0,
    dailyGhost: null      // {key, data} — only today's, so storage stays flat
  };

  function load() {
    var s = OM.store.get(KEY, null);
    if (!s || s.v !== 1) s = JSON.parse(JSON.stringify(DEFAULT));
    for (var k in DEFAULT) if (!(k in s)) s[k] = JSON.parse(JSON.stringify(DEFAULT[k]));
    for (var k2 in DEFAULT.settings) if (!(k2 in s.settings)) s.settings[k2] = DEFAULT.settings[k2];
    for (var k3 in DEFAULT.cosmetics) if (!(k3 in s.cosmetics)) s.cosmetics[k3] = DEFAULT.cosmetics[k3];
    return s;
  }

  var save = load();
  var dirty = false;
  function flush() { if (dirty) { OM.store.set(KEY, save); dirty = false; } }
  function touch() { dirty = true; }
  setInterval(flush, 4000);
  if (root.addEventListener) {
    root.addEventListener('pagehide', flush);
    root.addEventListener('visibilitychange', function () { if (root.document && root.document.hidden) flush(); });
  }

  /* ---- levels ----
     The curve ends where the rewards end. It used to run to 99 while the last
     cosmetic unlocked at 50, so 80% of the climb — 658,000 of 823,000 XP —
     bought nothing at all. It is also re-weighted: the old curve put the final
     evolution about 1,430 runs away, which is not a long tail, it is a wall.
     It is now roughly 600 runs: still a real chase, actually reachable.
     `frac` is clamped at the cap. It previously kept accumulating remainder
     after the level stopped advancing, so the XP bar fill grew without bound —
     43x the bar width at twice the cap — and the label read past 100%. */
  var MAX_LEVEL = 50;
  function needFor(level) { return Math.round(60 + 19 * Math.pow(level - 1, 1.32)); }
  function levelInfo(xp) {
    var lv = 1, rem = xp, need = needFor(1);
    while (rem >= need && lv < MAX_LEVEL) { rem -= need; lv++; need = needFor(lv); }
    if (lv >= MAX_LEVEL) return { level: MAX_LEVEL, into: need, need: need, frac: 1, capped: true };
    return { level: lv, into: rem, need: need, frac: rem / need, capped: false };
  }

  /* ---- cosmetics ----
     Purely visual, unlocked by playing. Nothing here touches the physics: two
     players at level 3 and level 50 have exactly the same game. */
  var CORES = [
    { id: 'core', name: 'CORE', at: 1, line: 'The beginning.' },
    { id: 'pulse', name: 'PULSE', at: 8, line: 'It has a heartbeat now.' },
    { id: 'phase', name: 'PHASE', at: 16, line: 'The shell stops being solid.' },
    { id: 'void', name: 'VOID', at: 26, line: 'Something is missing from it.' },
    { id: 'glitch', name: 'GLITCH', at: 36, line: 'It does not render correctly.' },
    { id: 'singularity', name: 'SINGULARITY', at: 50, line: 'It stopped being a shape.' }
  ];
  var TRAILS = [
    { id: 'line', name: 'LINE', at: 1 },
    { id: 'particle', name: 'PARTICLE', at: 4 },
    { id: 'wave', name: 'WAVE', at: 11 },
    { id: 'shatter', name: 'SHATTER', at: 19 },
    { id: 'void', name: 'VOID', at: 30 }
  ];
  var DEATHS = [
    { id: 'shatter', name: 'GLASS SHATTER', at: 1 },
    { id: 'explode', name: 'EXPLOSION', at: 3 },
    { id: 'implode', name: 'IMPLOSION', at: 9 },
    { id: 'pixel', name: 'PIXEL DISSOLVE', at: 15 },
    { id: 'collapse', name: 'GRAVITY COLLAPSE', at: 23 },
    { id: 'wipe', name: 'ENERGY WIPE', at: 33 }
  ];

  function unlockedIn(list, level) {
    var out = [];
    for (var i = 0; i < list.length; i++) if (level >= list[i].at) out.push(list[i]);
    return out;
  }
  // "auto" tracks your level, so the Nanogon visibly evolves without a menu visit
  function coreFor(level) {
    var pick = CORES[0];
    for (var i = 0; i < CORES.length; i++) if (level >= CORES[i].at) pick = CORES[i];
    return pick.id;
  }
  function activeCore() {
    var lv = levelInfo(save.xp).level;
    return save.cosmetics.core === 'auto' ? coreFor(lv) : save.cosmetics.core;
  }

  /* ---- achievements ---- */
  var ACH = [
    { id: 'first', name: 'FIRST CONTACT', line: 'Finish a run.', test: function (s) { return s.runs >= 1; } },
    { id: 's30', name: 'THIRTY', line: 'Survive 30 seconds.', test: function (s) { return s.best >= 30; } },
    { id: 's60', name: 'ONE MINUTE', line: 'Survive 60 seconds.', test: function (s) { return s.best >= 60; } },
    { id: 's120', name: 'TWO MINUTES', line: 'Survive 120 seconds.', test: function (s) { return s.best >= 120; } },
    { id: 's180', name: 'COLLAPSE', line: 'Reach the fourth world.', test: function (s) { return s.best >= 168; } },
    { id: 's240', name: 'NIGHTMARE', line: 'Reach 240 seconds.', test: function (s) { return s.best >= 240; } },
    { id: 'r25', name: 'ONE MORE', line: 'Play 25 runs.', test: function (s) { return s.runs >= 25; } },
    { id: 'r100', name: 'ONE HUNDRED MORE', line: 'Play 100 runs.', test: function (s) { return s.runs >= 100; } },
    { id: 'p10', name: 'PRECISION', line: '10 perfect switches.', test: function (s) { return s.perfect >= 10; } },
    { id: 'p100', name: 'SURGEON', line: '100 perfect switches.', test: function (s) { return s.perfect >= 100; } },
    { id: 'n250', name: 'CLOSE', line: '250 near misses.', test: function (s) { return s.nearMiss >= 250; } },
    { id: 'd1', name: 'TODAY', line: 'Play a Daily Challenge.', test: function (s) { return s.dailyDone.length >= 1; } },
    { id: 'd7', name: 'SEVEN DAYS', line: 'Play 7 Daily Challenges.', test: function (s) { return s.dailyDone.length >= 7; } },
    { id: 'lv10', name: 'PULSE', line: 'Reach level 10.', test: function (s) { return levelInfo(s.xp).level >= 10; } },
    { id: 'lv25', name: 'PHASE', line: 'Reach level 25.', test: function (s) { return levelInfo(s.xp).level >= 25; } },
    { id: 'hour', name: 'AN HOUR OF THIS', line: 'One hour of total survival.', test: function (s) { return s.totalTime >= 3600; } },
    { id: 'nm_open', name: 'NO WARNINGS', line: 'Unlock Nightmare (survive 120s).', test: function (s) { return s.best >= 120; } },
    { id: 'nm30', name: 'THIRTY IN THE DARK', line: 'Survive 30s in Nightmare.', test: function (s) { return s.nightmare >= 30; } },
    { id: 'trial1', name: 'FACING IT', line: 'Finish a Trial run.', test: function (s) { return Object.keys(s.trial).length >= 1; } },
    { id: 'trial60', name: 'WEAKNESS ADDRESSED', line: 'Survive 60s in a Trial.', test: function (s) {
        for (var k in s.trial) if (s.trial[k] >= 60) return true; return false; } }
  ];

  function checkAchievements() {
    var got = [];
    for (var i = 0; i < ACH.length; i++) {
      var a = ACH[i];
      if (save.achievements.indexOf(a.id) >= 0) continue;
      if (a.test(save)) { save.achievements.push(a.id); got.push(a); touch(); }
    }
    return got;
  }

  /* ---- the archive ----
   *
   * A game about surviving one more time has no ending to remember, so the
   * things worth keeping are the firsts: the first time you lasted a minute,
   * the first time you saw each world, the first Nightmare, the first Trial
   * that worked. They cost one line each and they are the only record of a
   * player's own history the game holds.
   *
   * Every entry is written once and never revised. A milestone that moved
   * would not be a milestone. */
  var MARKS = [
    { id: 'first_run', name: 'THE FIRST RUN', line: 'You tapped once and the world moved.' },
    { id: 'first_min', name: 'ONE MINUTE', line: 'Sixty seconds without touching anything.' },
    { id: 'first_daily', name: 'THE SAME WORLD AS EVERYONE', line: 'Your first Daily Challenge.' },
    { id: 'first_trial', name: 'FACING IT', line: 'You drilled the thing that keeps killing you.' },
    { id: 'first_nightmare', name: 'NO WARNINGS', line: 'You went where the run ends and kept going.' },
    { id: 'w_pulse', name: 'PULSE', line: 'The world started breathing.' },
    { id: 'w_void', name: 'VOID', line: 'Most of it stopped being visible.' },
    { id: 'w_collapse', name: 'COLLAPSE', line: 'Reality stopped being stable.' },
    { id: 'w_nightmare', name: 'NIGHTMARE', line: 'You arrived somewhere that does not want you.' },
    { id: 'five_min', name: 'FIVE MINUTES', line: 'A run long enough to be a story.' }
  ];
  var MARK_BY_ID = {};
  for (var mi = 0; mi < MARKS.length; mi++) MARK_BY_ID[MARKS[mi].id] = MARKS[mi];

  function mark(id, r) {
    if (!MARK_BY_ID[id] || save.marks[id]) return false;
    save.marks[id] = { at: Date.now(), t: r ? Math.round(r.time * 100) / 100 : 0 };
    return true;
  }

  /* Which firsts this run earned. Worlds come from the run's own world table
     rather than a second copy of it here, so adding a world adds its milestone
     and cannot forget to. */
  function markRun(r) {
    var got = [];
    if (mark('first_run', r)) got.push('first_run');
    if (r.time >= 60 && mark('first_min', r)) got.push('first_min');
    if (r.time >= 300 && mark('five_min', r)) got.push('five_min');
    if (r.mode === 'daily' && mark('first_daily', r)) got.push('first_daily');
    if (r.mode === 'trial' && mark('first_trial', r)) got.push('first_trial');
    if (r.mode === 'nightmare' && mark('first_nightmare', r)) got.push('first_nightmare');
    if (r.world && MARK_BY_ID['w_' + r.world.id] && mark('w_' + r.world.id, r)) {
      got.push('w_' + r.world.id);
    }
    return got;
  }

  /* ---- recording a run ---- */
  function commitRun(r) {
    var beforeLevel = levelInfo(save.xp).level;
    if (OM.analysis) OM.analysis.record(r);   // ignores practice runs itself

    /* Practice is a training room, not a run. It banks its own best time and
       touches nothing else.
       No XP: XP is paid by the second, and a lower speed buys more seconds for
       the same skill, so paying it here would make the training room the
       fastest way to level. No lifetime totals and no achievements for the same
       reason. Its best time is stored apart so that "best" keeps meaning one
       thing. */
    if (r.mode === 'practice') {
      var pbest = r.time > save.practice;
      if (pbest) save.practice = r.time;
      save.practiceRuns++;
      touch();
      flush();
      return { xp: 0, record: pbest, achievements: [], levelUp: false,
               level: levelInfo(save.xp).level };
    }

    save.runs++;
    save.totalTime += r.time;
    save.nearMiss += r.nearMiss;
    save.perfect += r.perfect;
    save.flips += r.flips;
    save.deaths[r.cause] = (save.deaths[r.cause] || 0) + 1;

    // XP: time carries it, style tops it up, a record is worth chasing.
    var xp = Math.round(r.time * 2.2 + r.nearMiss * 3 + r.perfect * 7);
    var record = false;
    if (r.mode === 'endless') {
      if (r.time > save.best) { save.best = r.time; save.bestAt = Date.now(); record = true; xp += 60; }
      if (r.ghost && r.time > save.ghostTime) { save.ghost = r.ghost; save.ghostTime = r.time; }
    } else if (r.mode === 'nightmare') {
      if (r.time > save.nightmare) { save.nightmare = r.time; record = true; xp += 80; }
      xp = Math.round(xp * 1.6);
    } else if (r.mode === 'trial') {
      if (!save.trial[r.family] || r.time > save.trial[r.family]) {
        save.trial[r.family] = r.time; record = true;
      }
      xp = Math.round(xp * 1.25);       // drilling your weakness is worth more
    } else if (r.mode === 'daily') {
      var k = OM.dayKey(r.day);
      if (save.dailyDone.indexOf(k) < 0) { save.dailyDone.push(k); xp += 25; }
      if (!save.daily[k] || r.time > save.daily[k]) {
        save.daily[k] = r.time;
        record = true;
        if (r.ghost) save.dailyGhost = { key: k, data: r.ghost };
      }
    }
    save.xp += xp;
    var newMarks = markRun(r);
    touch();
    var got = checkAchievements();
    flush();
    return { xp: xp, record: record, achievements: got, marks: newMarks,
             levelUp: levelInfo(save.xp).level > beforeLevel, level: levelInfo(save.xp).level };
  }

  /* Consecutive-day streak over the Daily Challenge, counted backwards from
     today so that missing yesterday does not silently erase the whole thing
     until you actually miss it. */
  function dailyStreak() {
    var today = OM.dayIndex(), n = 0;
    for (var i = 0; i < 400; i++) {
      if (save.dailyDone.indexOf(OM.dayKey(today - i)) >= 0) n++;
      else if (i > 0) break;                 // today not yet played is fine
    }
    return n;
  }

  OM.progress = {
    data: save,
    flush: flush, touch: touch,
    levelInfo: function () { return levelInfo(save.xp); },
    needFor: needFor,
    maxLevel: MAX_LEVEL,
    commitRun: commitRun,
    dailyStreak: dailyStreak,
    nightmareUnlocked: function () { return save.best >= 120; },
    achievements: ACH,
    marks: MARKS,
    /* The archive in the order it was earned, which is the order it happened
       and the only order it makes sense to read. */
    archive: function () {
      var out = [];
      for (var i = 0; i < MARKS.length; i++) {
        var got = save.marks[MARKS[i].id];
        if (got) out.push({ id: MARKS[i].id, name: MARKS[i].name, line: MARKS[i].line,
                            at: got.at, t: got.t });
      }
      out.sort(function (a, b) { return a.at - b.at; });
      return out;
    },
    cores: CORES, trails: TRAILS, deaths: DEATHS,
    unlockedCores: function () { return unlockedIn(CORES, levelInfo(save.xp).level); },
    unlockedTrails: function () { return unlockedIn(TRAILS, levelInfo(save.xp).level); },
    unlockedDeaths: function () { return unlockedIn(DEATHS, levelInfo(save.xp).level); },
    activeCore: activeCore,
    coreFor: coreFor,
    reset: function () { OM.store.del(KEY); save = load(); OM.progress.data = save; }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
