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
    dailyDone: [],        // dayKeys played, for the streak
    nearMiss: 0, perfect: 0, flips: 0, deaths: {},
    cosmetics: { core: 'auto', trail: 'line', death: 'shatter' },
    achievements: [],
    seen: { tutorial: false },
    settings: { sound: true, music: true, shake: true, haptics: true, reduced: false },
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

  /* ---- levels ---- */
  function needFor(level) { return Math.round(70 + 46 * Math.pow(level - 1, 1.32)); }
  function levelInfo(xp) {
    var lv = 1, rem = xp, need = needFor(1);
    while (rem >= need && lv < 99) { rem -= need; lv++; need = needFor(lv); }
    return { level: lv, into: rem, need: need, frac: rem / need };
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

  /* ---- recording a run ---- */
  function commitRun(r) {
    var beforeLevel = levelInfo(save.xp).level;
    if (OM.analysis) OM.analysis.record(r);
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
    touch();
    var got = checkAchievements();
    flush();
    return { xp: xp, record: record, achievements: got,
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
    commitRun: commitRun,
    dailyStreak: dailyStreak,
    nightmareUnlocked: function () { return save.best >= 120; },
    achievements: ACH,
    cores: CORES, trails: TRAILS, deaths: DEATHS,
    unlockedCores: function () { return unlockedIn(CORES, levelInfo(save.xp).level); },
    unlockedTrails: function () { return unlockedIn(TRAILS, levelInfo(save.xp).level); },
    unlockedDeaths: function () { return unlockedIn(DEATHS, levelInfo(save.xp).level); },
    activeCore: activeCore,
    coreFor: coreFor,
    reset: function () { OM.store.del(KEY); save = load(); OM.progress.data = save; }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
