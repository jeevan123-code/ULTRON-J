/* ONE MORE — the read.
 *
 * The game watches how you die and tells you. Not with invented flattery and
 * not with a fake global percentile: with your own numbers, held against your
 * own baseline, and only once there is enough of them to mean anything.
 *
 * Every claim this file makes is checkable against the recorded history. When
 * there is nothing honest to say, it says nothing.
 */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var PAT = OM.patterns, P = OM.phys;
  var KEY = 'onemore.deaths.v1';
  var CAP = 260;                 // rolling history; enough to read, cheap to store
  var MIN_FOR_READ = 12;         // below this, any pattern is noise

  var log = OM.store.get(KEY, []);
  if (!Array.isArray(log)) log = [];

  function record(summary) {
    /* Practice deaths never enter the history at all. Tagging them and
       filtering them at every consumer would work too, but they would still be
       competing for the 260 slots the rolling history has, so a player who
       drilled a lot would quietly shorten the memory the read is built from.
       Keeping them out is one line here instead of a filter at five call sites
       that all have to stay in step. */
    if (summary.mode === 'practice') return;
    var c = summary.context || {};
    log.push({
      t: Math.round(summary.time * 10) / 10,
      cause: summary.cause,
      pat: c.pat || null,
      air: c.airborne ? 1 : 0,
      sf: Math.round((c.sinceFlip || 0) * 100) / 100,
      muts: c.mutations || [],
      world: c.worldId,
      fr: Math.round((c.flipRate || 0) * 100) / 100,
      /* Which mode this death happened in, and for a Trial which family it was
         drilling. Without these a Trial is invisible in its own history, and the
         one question the Trial exists to answer — did it work — has no data. */
      md: summary.mode || null,
      fam: summary.family || null,
      at: Date.now()
    });
    while (log.length > CAP) log.shift();
    OM.store.set(KEY, log);
  }

  /* Group deaths by the family of thing that killed you. Individual pattern ids
     are too granular to be actionable — "you die on moving geometry" is a thing
     a person can practise; "you die on t4_mover_gate" is trivia. */
  var FAMILY = {
    spike: 'timing', block: 'timing', bar: 'commitment',
    mover: 'prediction', gate: 'prediction', piston: 'prediction', laser: 'prediction',
    rotor: 'prediction', orbit: 'prediction',
    void: 'nerve'
  };
  var FAMILY_COPY = {
    timing: {
      name: 'TIMING',
      noun: 'static geometry',
      line: 'You flip late into static geometry.',
      me: 'I flip late into static geometry',
      fix: 'Commit to the flip when you see the gap, not when you reach it.'
    },
    prediction: {
      name: 'PREDICTION',
      noun: 'moving geometry',
      line: 'Moving geometry catches you out.',
      me: 'moving geometry catches me out',
      fix: 'Read where it will be, not where it is. Watch the guide rails.'
    },
    commitment: {
      name: 'COMMITMENT',
      noun: 'bars and blocks',
      line: 'Bars and blocks catch you mid-decision.',
      me: 'bars and blocks catch me mid-decision',
      fix: 'Pick a surface early and stay on it through the obstacle.'
    },
    nerve: {
      name: 'NERVE',
      noun: 'the void',
      line: 'The floor disappearing is what gets you.',
      me: 'the disappearing floor is what gets me',
      fix: 'A gap is not a wall. Ride the ceiling across it.'
    }
  };

  /* The bar a family has to clear before it is called a weakness, against an
     even split of every family that COULD occur rather than the ones that
     happen to have. Defined once: the weakness read, the history and anything
     later that wants to say "lopsided" must all mean the same thing by it. */
  var EVEN = 1 / Object.keys(FAMILY_COPY).length;
  var WEAK_AT = Math.max(0.42, EVEN * 1.6);
  var FAMILY_ORDER = ['timing', 'prediction', 'commitment', 'nerve'];

  function tally() {
    var byFamily = {}, byCause = {}, byPat = {}, n = log.length;
    var airborne = 0, lateFlip = 0, rushed = 0, transit = 0, nonVoid = 0;
    var flipsTotal = 0, secsTotal = 0, times = [];
    for (var i = 0; i < n; i++) {
      var d = log[i];
      var fam = FAMILY[d.cause] || 'timing';
      byFamily[fam] = (byFamily[fam] || 0) + 1;
      byCause[d.cause] = (byCause[d.cause] || 0) + 1;
      if (d.pat) byPat[d.pat] = (byPat[d.pat] || 0) + 1;
      if (d.air) airborne++;
      if (d.sf > 0.9) lateFlip++;
      if (d.sf < P.PERFECT_WINDOW) rushed++;
      /* Falling through a hole is airborne by definition and already has a
         family of its own, so void deaths come out of both halves of the
         mid-flip fraction rather than inflating it. */
      if (d.cause !== 'void') { nonVoid++; if (d.air) transit++; }
      /* die() stores flipRate as flips / max(1, t). Undoing that exactly gives a
         duration-weighted flip rate, instead of a mean that the many very short
         runs would drag around. */
      var secs = Math.max(1, d.t);
      flipsTotal += (d.fr || 0) * secs;
      secsTotal += secs;
      times.push(d.t);
    }
    times.sort(function (a, b) { return a - b; });
    return {
      n: n, byFamily: byFamily, byCause: byCause, byPat: byPat,
      airborne: airborne, lateFlip: lateFlip,
      rushed: rushed, transit: transit, nonVoid: nonVoid,
      flipRate: secsTotal > 0 ? flipsTotal / secsTotal : 0,
      median: times.length ? times[Math.floor(times.length / 2)] : 0,
      recentMedian: (function () {
        var r = log.slice(-15).map(function (d) { return d.t; }).sort(function (a, b) { return a - b; });
        return r.length ? r[Math.floor(r.length / 2)] : 0;
      })(),
      earlyMedian: (function () {
        var r = log.slice(0, 15).map(function (d) { return d.t; }).sort(function (a, b) { return a - b; });
        return r.length ? r[Math.floor(r.length / 2)] : 0;
      })()
    };
  }

  /* The headline. One sentence, only when the evidence supports it.
     Returns null rather than inventing something to say. */
  function read() {
    var s = tally();
    if (s.n < MIN_FOR_READ) {
      return { kind: 'none', need: MIN_FOR_READ - s.n };
    }
    // strongest over-representation among families
    var fams = Object.keys(s.byFamily);
    var top = null, topShare = 0;
    for (var i = 0; i < fams.length; i++) {
      var share = s.byFamily[fams[i]] / s.n;
      if (share > topShare) { topShare = share; top = fams[i]; }
    }
    /* A family counts as a weakness only if it is genuinely lopsided against an
       even split of ALL the families that could occur — not of the ones that
       happen to appear. Measuring against the observed set means somebody who
       dies to exactly one thing scores 1/1 = "even", and gets told they have no
       weakness at the precise moment they most obviously do. */
    var even = EVEN;
    if (topShare < WEAK_AT) {
      return {
        kind: 'balanced',
        headline: 'NO SINGLE WEAKNESS',
        line: 'Your deaths are spread evenly. Speed is what is beating you now.',
        share: topShare, n: s.n
      };
    }
    var copy = FAMILY_COPY[top];
    return {
      kind: 'weakness',
      family: top,
      headline: copy.name,
      line: copy.line,
      me: copy.me,
      fix: copy.fix,
      share: topShare,
      /* The same baseline the threshold above is judged against: an even split
         across every family that could occur. Carrying it means a share can be
         quoted as a multiple without the reader having to know what 'even' is. */
      expected: even,
      mult: topShare / even,
      count: s.byFamily[top],
      n: s.n
    };
  }

  /* ---- habits: what you were doing, not what hit you ----
   *
   * The family read names the geometry that beats you. A habit names what you
   * were doing when it did, which is the half of the answer you can act on
   * during the very next run.
   *
   * Each one is measured against what it would be if dying had nothing to do
   * with your flip timing — derived from YOUR flip rate, not from a constant.
   * A fixed threshold cannot work here. At one flip per second you are already
   * mid-flip about 57% of the time, so "57% of your deaths were mid-flip" says
   * precisely nothing; for somebody flipping half as often the same number is
   * damning. Comparing against a baseline the player generates themselves is
   * the only version of this that is not a horoscope.
   */
  var HABITS = [
    {
      /* A surface-to-surface flip takes TRANSIT_T (~0.57s), so 0.9s since the
         last one means the flip was long finished: you were sitting still on a
         surface and never moved. That is a reading failure, not an execution
         one, and it wants the opposite advice from the case below. */
      key: 'late', me: 'I react late', count: 'lateFlip', of: 'n', floor: 0.30, ratio: 1.5,
      expect: function (fr) { return Math.exp(-0.9 * fr); },
      headline: 'YOU REACT LATE',
      fix: 'Flip when you see the gap, not when you reach it.'
    },
    {
      /* Dying inside the perfect-switch window means the input happened and was
         simply the wrong one. */
      key: 'rushed', me: 'I flip into things', count: 'rushed', of: 'n', floor: 0.45, ratio: 1.35,
      expect: function (fr) { return 1 - Math.exp(-P.PERFECT_WINDOW * fr); },
      headline: 'YOU FLIP INTO IT',
      fix: 'Read the far side before you commit. A late flip beats a wrong one.'
    },
    {
      /* Caught in the air rather than on a surface. The null is just the share
         of the time a flip keeps you there: TRANSIT_T seconds of every one. */
      key: 'transit', me: 'I die crossing', count: 'transit', of: 'nonVoid', floor: 0.55, ratio: 1.25,
      expect: function (fr) { return Math.min(0.95, P.TRANSIT_T * fr); },
      headline: 'YOU DIE CROSSING',
      fix: 'Cross on the clear stretches, so you arrive before the obstacle does.'
    }
  ];

  /* The strongest habit, or nothing at all. Ranked by how far each one clears
     its own baseline, since the three are not measured on the same scale.
     A habit must also clear an absolute floor, so that a small expected value
     cannot turn a handful of deaths into a dramatic-looking multiple. */
  function habit() {
    var s = tally();
    if (s.n < MIN_FOR_READ || s.flipRate <= 0) return null;
    var fr = Math.min(4, Math.max(0.2, s.flipRate));
    var best = null, bestMult = 0;
    for (var i = 0; i < HABITS.length; i++) {
      var h = HABITS[i], denom = s[h.of], count = s[h.count];
      if (denom < MIN_FOR_READ || count < 5) continue;
      var share = count / denom;
      var exp = Math.max(0.02, h.expect(fr));
      var mult = share / exp;
      if (share < h.floor || mult < h.ratio) continue;
      if (mult > bestMult) {
        bestMult = mult;
        best = { key: h.key, headline: h.headline, me: h.me, fix: h.fix, share: share,
                 expected: exp, mult: mult, count: count, n: denom };
      }
    }
    return best;
  }

  /* ---------- the read as a history ----------
   *
   * "You used to flip late; now you flip into things" says more than either
   * half on its own, and the log has always had the order to prove it.
   *
   * Trial deaths come out. A Trial is deliberately built almost entirely from
   * one family, so leaving them in would show every player who took up drilling
   * a dramatic "shift" towards the thing they chose to practise. Nightmare and
   * daily stay in: unlike the trial verdict, this is not attributing a change to
   * anything — it is describing what has been killing you, and those deaths
   * count. Buckets are by position in the log for the same reason the verdict
   * is: recorded order cannot move, wall clocks can. */
  function normalLog() {
    var out = [];
    for (var i = 0; i < log.length; i++) if (log[i].md !== 'trial') out.push(log[i]);
    return out;
  }

  function dominant(pool, lo, hi) {
    var counts = {}, n = hi - lo, i;
    for (i = lo; i < hi; i++) {
      var f = FAMILY[pool[i].cause] || 'timing';
      counts[f] = (counts[f] || 0) + 1;
    }
    var top = null, best = 0;
    for (var k in counts) if (counts[k] > best) { best = counts[k]; top = k; }
    if (!top || n <= 0) return null;
    var share = best / n;
    if (share < WEAK_AT) return null;         // no dominant family in this half
    return { family: top, name: FAMILY_COPY[top].name, noun: FAMILY_COPY[top].noun,
             share: share, count: best, n: n };
  }

  /* Only when the thing that beats you has actually changed, and only when both
     halves are lopsided enough to have a "the thing" at all. Two halves that are
     both a spread of everything is not a story, and neither is a 51/49 wobble
     between the same two families. */
  function shift() {
    var pool = normalLog();
    if (pool.length < MIN_FOR_READ * 2) return null;
    var mid = Math.floor(pool.length / 2);
    var a = dominant(pool, 0, mid), b = dominant(pool, mid, pool.length);
    if (!a || !b || a.family === b.family) return null;
    return { from: a, to: b };
  }

  /* The same history as a shape rather than a sentence: each bucket is a slice
     of your deaths in order, split by family. It asserts nothing, so it needs
     only enough per bucket to not be single deaths. */
  function weaknessBands(want) {
    var pool = normalLog();
    if (pool.length < MIN_FOR_READ * 2) return null;
    var b = Math.max(4, Math.min(want || 8, Math.floor(pool.length / 6)));
    var out = [];
    for (var k = 0; k < b; k++) {
      var lo = Math.floor(k * pool.length / b), hi = Math.floor((k + 1) * pool.length / b);
      var counts = {};
      for (var i = lo; i < hi; i++) {
        var f = FAMILY[pool[i].cause] || 'timing';
        counts[f] = (counts[f] || 0) + 1;
      }
      out.push({ n: hi - lo, counts: counts });
    }
    return { order: FAMILY_ORDER, buckets: out, n: pool.length };
  }

  /* ---------- the read before there is a read ----------
   *
   * The statistical read is silent until death twelve, and for the eleven runs
   * before that the panel has only ever offered a countdown. That is a promise
   * with nothing under it, on exactly the runs where a new player most needs
   * something.
   *
   * This is not a statistic and never becomes one. Every clause is a fact about
   * the death that just happened, measured against the one constant the physics
   * guarantees: a crossing covers TRANSIT_X pixels at every speed, so it costs
   * TRANSIT_X / speed seconds. Holding the age of your last flip against that
   * number is the whole lesson, and it is available on death one.
   *
   * It says what was true. It does not say what you should have done — there is
   * no way to know from one death whether the gap you needed was even there. */
  function moment(summary) {
    if (!summary || !summary.cause) return null;
    var c = summary.context || {};
    var speed = c.speed > 0 ? c.speed : P.BASE_SPEED;
    var cross = P.TRANSIT_X / speed;
    var label = (OM.causeLabel ? OM.causeLabel(summary.cause) : 'SOMETHING').toLowerCase();
    label = label.charAt(0).toUpperCase() + label.slice(1);
    var sf = c.sinceFlip;
    var cs = cross.toFixed(2) + 's';

    var where;
    if (summary.cause === 'void') where = 'The floor ran out from under you.';
    else if (c.airborne) {
      where = label + ' caught you crossing to the ' +
              (c.grav > 0 ? 'floor' : 'ceiling') + '.';
    } else {
      where = label + ' caught you on the ' + (c.grav > 0 ? 'floor' : 'ceiling') + '.';
    }

    var when;
    if (!(sf >= 0) || sf > 20) {
      when = 'You had not flipped yet. A crossing costs ' + cs + ' at this speed.';
    } else if (c.airborne && sf < cross) {
      when = 'That flip was ' + sf.toFixed(2) + 's old. A crossing takes ' + cs +
             ' at this speed \u2014 it had not finished.';
    } else {
      when = 'Your last flip was ' + sf.toFixed(2) + 's earlier. A crossing costs ' +
             cs + ' at this speed.';
    }
    return { where: where, when: when, cross: cross, speed: speed };
  }

  /* ---------- did the drilling work? ----------
   *
   * A Trial points the generator at your weakness and then, until now, never
   * came back to tell you whether it helped. Every death carries a timestamp
   * and a mode, so the answer is already in the log: take the moment of your
   * first Trial in a family and compare that family's share of your NORMAL
   * deaths before it against after it.
   *
   * Three things keep this from turning into flattery.
   *
   * Trial deaths are excluded from both sides. A Trial is made almost entirely
   * of one family, so counting its deaths would push that family's share up
   * afterwards and make successful practice look like decline.
   *
   * Only endless and daily count — the two modes that run the same curve from
   * zero. Nightmare starts at 245s in a different part of the world with a
   * different mix of obstacles, and a player who took up Nightmare after their
   * first Trial would otherwise see that change attributed to the Trial.
   * Deaths recorded before this field existed have no mode and are excluded
   * for the same reason: they might be Trials, and counting a Trial as normal
   * play on the 'before' side would manufacture an improvement.
   *
   * And it reports a rise exactly as readily as a fall.
   *
   * The split is by position in the log, not by wall clock. Timestamps are
   * whatever the device says they are and can move backwards; the order deaths
   * were recorded in cannot. It also means a verdict goes quiet again once the
   * rolling history has scrolled past the trial — at that point the evidence
   * for it genuinely is gone. */
  var NORMAL = { endless: 1, daily: 1 };
  var MIN_PER_SIDE = 12;
  var FLAT = 0.06;               // under six points, call it unchanged

  function trialEffect(family) {
    if (!FAMILY_COPY[family]) return null;
    var first = -1, trials = 0, i, d;
    for (i = 0; i < log.length; i++) {
      d = log[i];
      if (d.md !== 'trial' || d.fam !== family) continue;
      trials++;
      if (first < 0) first = i;
    }
    if (first < 0) return null;

    var before = { n: 0, count: 0 }, after = { n: 0, count: 0 };
    for (i = 0; i < log.length; i++) {
      d = log[i];
      if (!NORMAL[d.md]) continue;
      var side = i < first ? before : after;
      side.n++;
      if ((FAMILY[d.cause] || 'timing') === family) side.count++;
    }
    if (before.n < MIN_PER_SIDE || after.n < MIN_PER_SIDE) return null;

    before.share = before.count / before.n;
    after.share = after.count / after.n;
    var delta = after.share - before.share;
    return {
      family: family, name: FAMILY_COPY[family].name,
      noun: FAMILY_COPY[family].noun, trials: trials, from: first,
      before: before, after: after, delta: delta,
      direction: Math.abs(delta) < FLAT ? 'flat' : (delta < 0 ? 'down' : 'up')
    };
  }

  /* The strongest measurable trial result, for callers that have no particular
     family in mind. Strongest means largest movement in either direction: a
     drill that made things worse is the more useful thing to be told. */
  function trialEffects() {
    var out = [], fams = Object.keys(FAMILY_COPY);
    for (var i = 0; i < fams.length; i++) {
      var e = trialEffect(fams[i]);
      if (e) out.push(e);
    }
    out.sort(function (a, b) { return Math.abs(b.delta) - Math.abs(a.delta); });
    return out;
  }

  /* Are you actually getting better? Median of your last 15 runs against your
     first 15. Honest, and it does not need a server. */
  function trend() {
    var s = tally();
    if (s.n < 24) return null;
    var d = s.recentMedian - s.earlyMedian;
    return { delta: d, recent: s.recentMedian, early: s.earlyMedian,
             pct: s.earlyMedian > 0 ? d / s.earlyMedian : 0 };
  }

  /* Build a Trial: a run composed mostly of what you are bad at.
     It returns tier weights the generator can use directly, so the Trial is
     made of the same proven-fair patterns as everything else — it is a
     different selection, never different rules. */
  var FAMILY_TYPES = {
    timing: { spike: 1, block: 1 },
    prediction: { mover: 1, laser: 1, piston: 1, gate: 1, rotor: 1, orbit: 1 },
    commitment: { bar: 1, block: 1 },
    nerve: { hole: 1 }
  };

  /* The family decides WHICH patterns a Trial may draw from. Your own record
     decides how often each one comes up.
   *
   * byPat is too granular to say out loud — being told you die on
   * t4_mover_gate is trivia — but a Trial never has to name anything, only
   * select, and there it is the sharpest signal in the log.
   *
   * The pool comes back as a multiset: a pattern appears once per unit of
   * weight, because the generator already picks uniformly from whatever pool it
   * is handed, so this needs no change at all to the thing that builds the
   * world. Same proven patterns, same rules, different frequencies.
   *
   * Every eligible pattern keeps a weight of at least one. A Trial made only of
   * what you have already failed could never show you the one you are about to,
   * and drilling a fixed list is how you get good at a list. The extra weight is
   * capped relative to your worst pattern, so no single obstacle can take over
   * the run — at the cap it is four picks in place of one, not the whole pool. */
  var WEIGHT_MAX = 4;

  function trialPatterns(family) {
    var want = FAMILY_TYPES[family] || FAMILY_TYPES.timing;
    var base = [], i, k;
    for (i = 0; i < PAT.list.length; i++) {
      var p = PAT.list[i], hit = 0;
      for (var j = 0; j < p.items.length; j++) if (want[p.items[j].t]) hit++;
      if (hit >= 1 && hit / p.items.length >= 0.5) base.push(p);
    }
    if (base.length < 4) base = PAT.list.slice();

    var byPat = tally().byPat, top = 0;
    for (i = 0; i < base.length; i++) top = Math.max(top, byPat[base[i].id] || 0);
    if (!top) return base;                    // nothing failed yet: no opinion

    var out = [];
    for (i = 0; i < base.length; i++) {
      var w = 1 + Math.min(WEIGHT_MAX - 1,
                Math.round((WEIGHT_MAX - 1) * (byPat[base[i].id] || 0) / top));
      for (k = 0; k < w; k++) out.push(base[i]);
    }
    return out;
  }

  /* What the game says about you, in your own voice, with the number under it.
   *
   * "I survived 47.30s" is what every runner's share button produces and it
   * travels nowhere — nobody can disagree with it, so nobody replies. A claim
   * about how you play invites one.
   *
   * Returns null below the evidence gate. A share button that manufactured a
   * read at run three would break the one rule this whole layer exists for, and
   * the caller falls back to the time instead. */
  function shareClaim() {
    var hb = habit();
    if (hb) {
      return hb.me + ': ' + Math.round(hb.share * 100) + '% of my deaths, ' +
             hb.mult.toFixed(1) + '\u00d7 what my own flip rate explains';
    }
    var rd = read();
    if (rd.kind === 'weakness') {
      return rd.me + ': ' + Math.round(rd.share * 100) + '% of my last ' + rd.n +
             ' deaths, ' + rd.mult.toFixed(1) + '\u00d7 an even spread';
    }
    return null;
  }

  OM.analysis = {
    record: record,
    shareClaim: shareClaim,
    read: read,
    habit: habit,
    moment: moment,
    shift: shift,
    weaknessBands: weaknessBands,
    trialEffect: trialEffect,
    trialEffects: trialEffects,
    trend: trend,
    tally: tally,
    trialPatterns: trialPatterns,
    families: FAMILY_COPY,
    familyOf: function (cause) { return FAMILY[cause] || 'timing'; },
    clear: function () { log = []; OM.store.del(KEY); },
    history: function () { return log.slice(); }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
