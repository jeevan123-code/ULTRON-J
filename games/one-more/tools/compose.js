/* ONE MORE — compositional growth of the pattern library.
 *
 * Sixty authored patterns is a lot of hand work and not a lot of world. The
 * cheap way to more is to hand-author another hundred; the honest way is to
 * join the ones that already exist and prove every join.
 *
 * A composition is two static fragments run together with a gap at the tight
 * end of what the generator already puts between patterns. That tightness is
 * the whole point: the second fragment starts before the first has let go of
 * you, so the pair is one problem with one line through it rather than two
 * problems in a row. It is also exactly why each one has to be proven — a line
 * that clears A and a line that clears B say nothing about whether a line
 * exists that clears both.
 *
 * Fair is not the same as interesting, and the fairness proof only answers the
 * first. A bar high up joined to a block on the floor is perfectly survivable
 * and needs no input at all: two things you could have ignored separately, in a
 * row. So a join clears a second gate before it ships. It must need at least
 * one flip, and it must be strictly harder than EITHER half by one of the two
 * measures there are — more flips than either half needs, or less slack than
 * either half leaves. That is the operational form of "the pair is one
 * problem": if the join is no harder than one half alone then nothing was
 * joined, and what you have is scenery with a new id.
 *
 * Only static fragments compose, for the same reason only static patterns
 * appear in practice: their geometry is fixed in space, so a proof at one speed
 * is a proof at every speed, and the combinatorics stay honest. Time-driven
 * fragments would need every pair proven across every phase offset of both
 * halves, and the count of that is not a library, it is a job.
 *
 * Run:  node tools/validate.js --compose
 * Writes src/22-compositions.js, which is the only way a composition ships.
 */
'use strict';
var fs = require('fs');
var path = require('path');

/* 90px between the halves. The generator's own rest between two tier-1
   patterns bottoms out around 91px once the late-game spacing multiplier and
   RUSH are both applied, so this is the tight end of what the world already
   does — a join at this distance is not an exotic new difficulty, it is the
   one case sixty individually-proven patterns never said anything about. */
var GAP = 90;
/* A join is harder than either half, so a composition's tier is the sum of its
   fragments' — which is also what decides the slack budget it has to clear.
   The default admits t1+t1, t1+t2 and t2+t2; --tiersum raises or lowers it. */
var tierArg = process.argv.indexOf('--tiersum');
var MAX_TIER_SUM = tierArg >= 0 ? parseInt(process.argv[tierArg + 1], 10) : 4;

function copyItem(it, dx) {
  var o = {};
  for (var k in it) if (Object.prototype.hasOwnProperty.call(it, k)) o[k] = it[k];
  o.dx = it.dx + dx;
  return o;
}

function compose(a, b, gap) {
  var items = [], i;
  for (i = 0; i < a.items.length; i++) items.push(copyItem(a.items[i], 0));
  var off = a.len + gap;
  for (i = 0; i < b.items.length; i++) items.push(copyItem(b.items[i], off));
  return {
    id: a.id + '+' + b.id,
    tier: Math.min(5, a.tier + b.tier),
    len: a.len + gap + b.len,
    items: items,
    parts: [a.id, b.id]
  };
}

function candidates(PAT) {
  var frags = PAT.list.filter(function (p) {
    return !PAT.isDynamic(p) && p.tier <= 2 && !p.parts;
  }).sort(function (x, y) { return x.id.localeCompare(y.id); });

  var out = [];
  for (var i = 0; i < frags.length; i++) {
    for (var j = 0; j < frags.length; j++) {
      if (i === j) continue;
      if (frags[i].tier + frags[j].tier > MAX_TIER_SUM) continue;
      out.push(compose(frags[i], frags[j], GAP));
    }
  }
  return out;
}

/* Which of the proven joins actually ship.
   Compositions never outnumber the hand-authored patterns at their tier. Past
   that the world stops being the thing sixty patterns were authored to be and
   starts being a shuffle of two of them, and "more content" that all reads the
   same is not more content. The pick is a round robin over first halves, so no
   single fragment ends up carrying a whole tier. */
function select(proven, capFor) {
  var byFirst = {}, order = [];
  proven.forEach(function (p) {
    if (!byFirst[p.parts[0]]) { byFirst[p.parts[0]] = []; order.push(p.parts[0]); }
    byFirst[p.parts[0]].push(p);
  });
  order.sort();
  var taken = {}, out = [], k = 0, guard = 0;
  while (guard++ < 5000) {
    var progress = false;
    for (var i = 0; i < order.length; i++) {
      var bucket = byFirst[order[i]];
      if (k >= bucket.length) continue;
      progress = true;
      var p = bucket[k];
      if ((taken[p.tier] || 0) >= capFor(p.tier)) continue;
      taken[p.tier] = (taken[p.tier] || 0) + 1;
      out.push(p);
    }
    if (!progress) break;
    k++;
  }
  out.sort(function (a, b) { return a.tier - b.tier || a.id.localeCompare(b.id); });
  return out;
}

function emit(shipped, provenCount, attempted, rejected) {
  var proven = shipped;
  var lines = proven.map(function (r) {
    return "    ['" + r.parts[0] + "', '" + r.parts[1] + "', " + r.tier + "]";
  }).join(',\n');
  var body =
'/* ONE MORE — proven compositions.\n' +
' *\n' +
' * GENERATED by `node tools/validate.js --compose`. Do not edit by hand: every\n' +
' * entry below survived the same proof the authored library goes through — a\n' +
' * human-executable line exists from both entry surfaces, at every speed the\n' +
' * pattern can spawn at, with at least its tier\'s slack budget left over.\n' +
' *\n' +
' * ' + attempted + ' candidate joins were put through it. ' + provenCount + ' are both fair and\n' +
' * actually joins — harder than either half alone, in flips or in slack, and\n' +
' * needing at least one flip; ' + rejected + ' were rejected, most of them for being two\n' +
' * things you could have ignored separately rather than for being unfair.\n' +
' *\n' +
' * ' + proven.length + ' of the survivors ship. The rest are held back by a cap, not by the\n' +
' * proof: compositions never outnumber the hand-authored patterns at their tier,\n' +
' * because past that the world stops being the thing sixty patterns were\n' +
' * authored to be and becomes a shuffle of two of them.\n' +
' *\n' +
' * A composition stores only which two fragments it joins. The geometry is\n' +
' * rebuilt from them at load, so there is one copy of every obstacle in the\n' +
' * game and a fragment cannot drift away from the compositions built on it.\n' +
' */\n' +
'(function (root) {\n' +
"  'use strict';\n" +
'  var OM = root.OM, PAT = OM.patterns;\n' +
'  var GAP = ' + GAP + ';\n\n' +
'  var PROVEN = [\n' + lines + '\n  ];\n\n' +
'  function byId(id) {\n' +
'    for (var i = 0; i < PAT.list.length; i++) if (PAT.list[i].id === id) return PAT.list[i];\n' +
'    return null;\n' +
'  }\n' +
'  function shifted(items, dx) {\n' +
'    var out = [];\n' +
'    for (var i = 0; i < items.length; i++) {\n' +
'      var it = items[i], o = {};\n' +
'      for (var k in it) if (Object.prototype.hasOwnProperty.call(it, k)) o[k] = it[k];\n' +
'      o.dx = it.dx + dx;\n' +
'      out.push(o);\n' +
'    }\n' +
'    return out;\n' +
'  }\n\n' +
'  var built = [];\n' +
'  for (var i = 0; i < PROVEN.length; i++) {\n' +
'    var a = byId(PROVEN[i][0]), b = byId(PROVEN[i][1]);\n' +
'    if (!a || !b) continue;\n' +
'    built.push({\n' +
'      id: a.id + \'+\' + b.id,\n' +
'      tier: PROVEN[i][2],\n' +
'      len: a.len + GAP + b.len,\n' +
'      items: shifted(a.items, 0).concat(shifted(b.items, a.len + GAP)),\n' +
'      parts: [a.id, b.id]\n' +
'    });\n' +
'  }\n' +
'  PAT.add(built);\n' +
'})(typeof globalThis !== \'undefined\' ? globalThis : this);\n';
  var out = path.join(__dirname, '..', 'src', '22-compositions.js');
  fs.writeFileSync(out, body);
  return out;
}

module.exports = function (proveOne) {
  var PAT = globalThis.OM.patterns;
  var limitArg = process.argv.indexOf('--limit');
  var LIMIT = limitArg >= 0 ? parseInt(process.argv[limitArg + 1], 10) : 0;
  var frags = PAT.list.filter(function (p) {
    return !PAT.isDynamic(p) && p.tier <= 2 && !p.parts;
  });
  var all = candidates(PAT);
  var list = LIMIT > 0 ? all.slice(0, LIMIT) : all;
  var t0 = Date.now();

  console.log('\n  ONE MORE — composing the pattern library');
  console.log('  ' + '-'.repeat(64));
  console.log('  ' + list.length + ' candidate joins at ' + GAP + 'px, from ' +
              frags.length + ' static fragments');

  /* Each fragment's own difficulty, so a join can be held against its halves and
     not only against its tier's floor. */
  var fragSlack = {}, fragFlips = {};
  frags.forEach(function (f) {
    var r = proveOne(f);
    fragSlack[f.id] = r.ok && isFinite(r.window) ? r.window : Infinity;
    fragFlips[f.id] = r.ok ? r.flips : 0;
  });
  console.log('  fragment slack measured  (' + ((Date.now() - t0) / 1000).toFixed(0) + 's)');

  var fair = [], shippable = [], unfair = [], dull = [];
  list.forEach(function (p, i) {
    var r = proveOne(p);
    if (!(r.ok && r.window >= r.floor)) {
      unfair.push(p.id + (r.ok ? ' ' + Math.round(r.window) + 'ms<' + r.floor
                               : ' unsurvivable @x=' + r.failAt.x));
    } else {
      fair.push(p);
      var halfSlack = Math.min(fragSlack[p.parts[0]], fragSlack[p.parts[1]]);
      var halfFlips = Math.max(fragFlips[p.parts[0]], fragFlips[p.parts[1]]);
      if (r.flips >= 1 && (r.flips > halfFlips || r.window < halfSlack)) shippable.push(p);
      else {
        dull.push(p.id + ' ' + r.flips + ' flips vs ' + halfFlips + ', ' +
                  (isFinite(r.window) ? Math.round(r.window) + 'ms' : 'free') + ' vs ' +
                  (isFinite(halfSlack) ? Math.round(halfSlack) + 'ms' : 'free'));
      }
    }
    if ((i + 1) % 20 === 0) {
      console.log('  ' + (i + 1) + '/' + list.length + '  fair ' + fair.length +
                  '  real joins ' + shippable.length +
                  '  (' + ((Date.now() - t0) / 1000).toFixed(0) + 's)');
    }
  });

  var secs = (Date.now() - t0) / 1000;
  var proven = shippable;
  var rejected = { length: unfair.length + dull.length };
  console.log('  ' + '-'.repeat(64));
  console.log('  ' + list.length + ' attempted \u00b7 ' + fair.length + ' fair \u00b7 ' +
              shippable.length + ' PROVEN-DISTINCT COMBINATIONS  (' + secs.toFixed(1) + 's)');
  var byTier = {};
  shippable.forEach(function (p) { byTier[p.tier] = (byTier[p.tier] || 0) + 1; });
  console.log('  real joins by tier: ' + JSON.stringify(byTier));
  console.log('  rejected as unfair: ' + unfair.length +
              ' \u00b7 rejected as no harder than one half: ' + dull.length);
  unfair.slice(0, 4).forEach(function (r) { console.log('    unfair   ' + r); });
  dull.slice(0, 4).forEach(function (r) { console.log('    no join  ' + r); });

  var authored = {};
  PAT.list.forEach(function (p) { if (!p.parts) authored[p.tier] = (authored[p.tier] || 0) + 1; });
  var capArg = process.argv.indexOf('--cap');
  var CAP = capArg >= 0 ? parseInt(process.argv[capArg + 1], 10) : 0;
  var shipped = select(proven, function (tier) { return CAP > 0 ? CAP : (authored[tier] || 0); });
  var shipTier = {};
  shipped.forEach(function (p) { shipTier[p.tier] = (shipTier[p.tier] || 0) + 1; });
  console.log('  shipping ' + shipped.length + ' of them: ' + JSON.stringify(shipTier) +
              '  (authored: ' + JSON.stringify(authored) + ')');

  if (LIMIT > 0) {
    console.log('  --limit was set; nothing written.\n');
    return;
  }
  console.log('  wrote ' + emit(shipped, shippable.length, list.length, rejected.length) + '\n');
};
