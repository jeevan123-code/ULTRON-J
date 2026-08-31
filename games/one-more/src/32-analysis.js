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
  var PAT = OM.patterns;
  var KEY = 'onemore.deaths.v1';
  var CAP = 260;                 // rolling history; enough to read, cheap to store
  var MIN_FOR_READ = 12;         // below this, any pattern is noise

  var log = OM.store.get(KEY, []);
  if (!Array.isArray(log)) log = [];

  function record(summary) {
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
    void: 'nerve'
  };
  var FAMILY_COPY = {
    timing: {
      name: 'TIMING',
      line: 'You flip late into static geometry.',
      fix: 'Commit to the flip when you see the gap, not when you reach it.'
    },
    prediction: {
      name: 'PREDICTION',
      line: 'Moving geometry catches you out.',
      fix: 'Read where it will be, not where it is. Watch the guide rails.'
    },
    commitment: {
      name: 'COMMITMENT',
      line: 'Bars and blocks catch you mid-decision.',
      fix: 'Pick a surface early and stay on it through the obstacle.'
    },
    nerve: {
      name: 'NERVE',
      line: 'The floor disappearing is what gets you.',
      fix: 'A gap is not a wall. Ride the ceiling across it.'
    }
  };

  function tally() {
    var byFamily = {}, byCause = {}, byPat = {}, n = log.length;
    var airborne = 0, lateFlip = 0, times = [];
    for (var i = 0; i < n; i++) {
      var d = log[i];
      var fam = FAMILY[d.cause] || 'timing';
      byFamily[fam] = (byFamily[fam] || 0) + 1;
      byCause[d.cause] = (byCause[d.cause] || 0) + 1;
      if (d.pat) byPat[d.pat] = (byPat[d.pat] || 0) + 1;
      if (d.air) airborne++;
      if (d.sf > 0.9) lateFlip++;
      times.push(d.t);
    }
    times.sort(function (a, b) { return a - b; });
    return {
      n: n, byFamily: byFamily, byCause: byCause, byPat: byPat,
      airborne: airborne, lateFlip: lateFlip,
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
    var possible = Object.keys(FAMILY_COPY).length;
    var even = 1 / possible;
    if (topShare < Math.max(0.42, even * 1.6)) {
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
      fix: copy.fix,
      share: topShare,
      count: s.byFamily[top],
      n: s.n
    };
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
    prediction: { mover: 1, laser: 1, piston: 1, gate: 1 },
    commitment: { bar: 1, block: 1 },
    nerve: { hole: 1 }
  };

  function trialPatterns(family) {
    var want = FAMILY_TYPES[family] || FAMILY_TYPES.timing;
    var out = [];
    for (var i = 0; i < PAT.list.length; i++) {
      var p = PAT.list[i], hit = 0;
      for (var j = 0; j < p.items.length; j++) if (want[p.items[j].t]) hit++;
      if (hit >= 1 && hit / p.items.length >= 0.5) out.push(p);
    }
    return out.length >= 4 ? out : PAT.list.slice();
  }

  OM.analysis = {
    record: record,
    read: read,
    trend: trend,
    tally: tally,
    trialPatterns: trialPatterns,
    families: FAMILY_COPY,
    familyOf: function (cause) { return FAMILY[cause] || 'timing'; },
    clear: function () { log = []; OM.store.del(KEY); },
    history: function () { return log.slice(); }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
