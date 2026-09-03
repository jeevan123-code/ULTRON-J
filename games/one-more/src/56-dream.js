/* ONE MORE — the dream engine and its director.
 *
 * A long run goes visually flat. The worlds escalate, but between arrivals
 * nothing happens that the player has not already seen sixty seconds of, and
 * "more particles" is not an event. So the background occasionally does
 * something: an enormous ring passes through it, the frame cracks, a tunnel
 * opens and recedes, something vast rises behind the world and sinks again.
 *
 * The director is the important half. Spectacle that fires at random is
 * spectacle that fires while you are threading a needle, and a visual event
 * that arrives at the wrong moment is not a reward, it is an obstacle the
 * validator never proved. So an event needs a quiet window: nothing close,
 * nothing recently grazed, not dead, and enough time since the last one. The
 * check is cheap and it runs before the roll, never after.
 *
 * Three rules hold for every event here, and they are what separate this from
 * decoration that got out of hand:
 *
 *   Nothing draws in front of gameplay geometry. Events render with the
 *   backdrop, before the surfaces and obstacles, so the thing that can kill
 *   you is always on top of the thing that cannot.
 *
 *   Nothing changes the controls, the physics, or the world layout. An event
 *   is something the player sees, never something they have to survive.
 *
 *   Nothing exceeds the environment's brightness ceiling. The e2e guard that
 *   holds the backdrop under the geometry covers these too.
 */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var P = OM.phys;
  var CEIL = P.CEIL, FLOOR = P.FLOOR;
  var clamp = OM.math.clamp;

  /* Each event is a function of its own progress, 0 → 1. They own no state,
     which is what lets the director start, stop and skip them freely. */
  var EVENTS = {
    /* A ring the size of the sky, passing through. The signature event: it is
       the one that makes the tunnel look like a detail inside something. */
    loop: {
      dur: 5.5, weight: 4,
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL, mid = (CEIL + FLOOR) / 2;
        var x = W * (1.25 - k * 1.7);
        var s = band * (1.6 + Math.sin(k * Math.PI) * 0.9);
        var a = Math.sin(k * Math.PI) * 0.09;
        g.globalAlpha = a;
        g.lineWidth = 1.6;
        g.beginPath(); g.ellipse(x, mid, s, s * 0.62, 0, 0, 6.2832); g.stroke();
        g.globalAlpha = a * 0.6;
        g.beginPath(); g.ellipse(x, mid, s * 0.82, s * 0.51, 0, 0, 6.2832); g.stroke();
      }
    },
    /* The frame opens into depth. Concentric rings receding to a point, which
       reads as the tunnel briefly having somewhere else to go. */
    tunnel: {
      dur: 4.2, weight: 3,
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL, mid = (CEIL + FLOOR) / 2;
        var cx = W * 0.62, a = Math.sin(k * Math.PI);
        for (var i = 0; i < 9; i++) {
          var f = ((i / 9) + k * 1.4) % 1;
          var s = band * 0.06 + f * f * band * 1.5;
          g.globalAlpha = a * 0.085 * (1 - f);
          g.lineWidth = 1.2;
          g.beginPath(); g.ellipse(cx, mid, s, s * 0.7, 0, 0, 6.2832); g.stroke();
        }
      }
    },
    /* The frame cracks. Straight, sudden, and gone — the only event that
       arrives faster than it leaves. */
    fracture: {
      dur: 2.4, weight: 3,
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL, mid = (CEIL + FLOOR) / 2;
        var a = k < 0.12 ? k / 0.12 : Math.pow(1 - (k - 0.12) / 0.88, 1.6);
        g.globalAlpha = a * 0.13;
        g.lineWidth = 1.1;
        for (var i = 0; i < 7; i++) {
          var h = ((seed + i * 7919) % 1000) / 1000;
          var ox = h * W, oy = mid + (((seed + i * 104729) % 1000) / 1000 - 0.5) * band;
          var ang = (((seed + i * 15485863) % 1000) / 1000 - 0.5) * 2.4;
          var L = band * (0.5 + h * 1.1);
          g.beginPath();
          g.moveTo(ox - Math.cos(ang) * L, oy - Math.sin(ang) * L);
          g.lineTo(ox + Math.cos(ang) * L * 0.6, oy + Math.sin(ang) * L * 0.6);
          g.stroke();
        }
      }
    },
    /* Something vast rises behind the world, and goes back down. It never
       arrives and it never explains itself, which is the point. */
    giant: {
      dur: 7, weight: 2,
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL;
        var rise = Math.sin(k * Math.PI);
        var s = band * 2.2;
        var cx = W * (0.2 + ((seed % 100) / 100) * 0.6);
        var cy = FLOOR + s * 0.95 - rise * s * 0.55;
        g.globalAlpha = rise * 0.075;
        g.lineWidth = 1.5;
        g.beginPath(); g.arc(cx, cy, s, 0, 6.2832); g.stroke();
        for (var i = 1; i <= 4; i++) {
          var yy = cy - s + (2 * s * i) / 5;
          var rr = Math.sqrt(Math.max(0, s * s - (yy - cy) * (yy - cy)));
          g.globalAlpha = rise * 0.05;
          g.beginPath(); g.ellipse(cx, yy, rr, rr * 0.16, 0, 0, 6.2832); g.stroke();
        }
      }
    }
  };

  /* ---- the rare tier ----
   *
   * These are not events, they are sightings. A player should be able to run
   * for an hour and never see one, and the first time they do they should not
   * be certain it happened. So they are slow, quiet, far away, and they never
   * repeat within a run.
   *
   * They are seeded from the run like everything else, which means a Daily
   * shows the same sighting to everyone who plays it that day and a retried
   * seed shows it again. That is the honest consequence of a deterministic
   * world, and a better one than a private die-roll: two people can compare
   * notes and find they saw the same thing. */
  var RARE = {
    /* Something the size of a moon, made of the same geometry as you. */
    observer: {
      dur: 11, weight: 3, name: 'THE OBSERVER',
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL, mid = (CEIL + FLOOR) / 2;
        var a = Math.sin(k * Math.PI);
        var s = band * 1.9, cx = W * 0.5, cy = mid - band * 0.1;
        g.globalAlpha = a * 0.055;
        g.lineWidth = 1.4;
        g.beginPath(); g.arc(cx, cy, s, 0, 6.2832); g.stroke();
        for (var i = 0; i < 9; i++) {
          var t1 = (i / 9) * 6.2832, t2 = ((i * 4) % 9 / 9) * 6.2832;
          g.beginPath();
          g.moveTo(cx + Math.cos(t1) * s, cy + Math.sin(t1) * s);
          g.lineTo(cx + Math.cos(t2) * s, cy + Math.sin(t2) * s);
          g.stroke();
        }
        g.globalAlpha = a * 0.10;                 // the core, unmistakably a core
        g.beginPath(); g.arc(cx, cy, band * 0.05, 0, 6.2832); g.fill();
      }
    },
    /* A light that has never been there before, and will not be again. */
    white_sun: {
      dur: 13, weight: 2, name: 'THE WHITE SUN',
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL, a = Math.sin(k * Math.PI);
        var cx = W * 0.78, cy = FLOOR + band * 0.9 - a * band * 1.15;
        var s = band * 0.42;
        for (var i = 5; i >= 1; i--) {
          g.globalAlpha = a * 0.016 * i;
          g.beginPath(); g.arc(cx, cy, s * (0.5 + i * 0.24), 0, 6.2832); g.fill();
        }
        g.globalAlpha = a * 0.09;
        g.beginPath(); g.arc(cx, cy, s * 0.5, 0, 6.2832); g.fill();
      }
    },
    /* Someone else is doing this too, a long way off, and slightly ahead. */
    second: {
      dur: 9, weight: 3, name: 'THE SECOND',
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL, a = Math.sin(k * Math.PI);
        var x = W * (1.15 - k * 0.55);
        var y = CEIL - band * 0.28 + Math.sin(k * 9) * band * 0.16;
        g.globalAlpha = a * 0.10;
        g.lineWidth = 1.2;
        g.beginPath(); g.arc(x, y, 13, 0, 6.2832); g.stroke();
        g.beginPath(); g.arc(x, y, 3.2, 0, 6.2832); g.fill();
        g.globalAlpha = a * 0.05;                 // its trail, going the same way
        g.beginPath(); g.moveTo(x + 16, y); g.lineTo(x + 190, y + 8); g.stroke();
      }
    },
    /* For a few seconds the tunnel has walls, and an end. */
    the_room: {
      dur: 8, weight: 2, name: 'THE ROOM',
      draw: function (g, W, H, k, seed) {
        var band = FLOOR - CEIL, mid = (CEIL + FLOOR) / 2;
        var a = Math.sin(k * Math.PI);
        g.globalAlpha = a * 0.085;
        g.lineWidth = 1.5;
        var w = band * 1.5, h = band * 0.92;
        g.strokeRect(W * 0.5 - w / 2, mid - h / 2, w, h);
        g.strokeRect(W * 0.5 - w * 0.34, mid - h * 0.34, w * 0.68, h * 0.68);
        for (var c = 0; c < 4; c++) {             // corners joined to the inner box
          var sx2 = W * 0.5 + (c % 2 ? 1 : -1) * w / 2;
          var sy2 = mid + (c < 2 ? -1 : 1) * h / 2;
          g.beginPath();
          g.moveTo(sx2, sy2);
          g.lineTo(W * 0.5 + (c % 2 ? 1 : -1) * w * 0.34,
                   mid + (c < 2 ? -1 : 1) * h * 0.34);
          g.stroke();
        }
      }
    }
  };
  var RARE_NAMES = Object.keys(RARE);
  var RARE_TOTAL = RARE_NAMES.reduce(function (s, n) { return s + RARE[n].weight; }, 0);

  var NAMES = Object.keys(EVENTS);
  var TOTAL = NAMES.reduce(function (s, n) { return s + EVENTS[n].weight; }, 0);

  /* Worlds that may dream, and how often. Origin never does: a player in their
     first forty seconds is learning a rule, and a spectacle then teaches them
     that things happen for no reason. */
  var BY_WORLD = {
    origin: 0, pulse: 26, void: 22, collapse: 18, nightmare: 15
  };

  OM.dream = {
    events: EVENTS,
    rare: RARE,
    byWorld: BY_WORLD,

    Director: function (rng) {
      var d = {
        active: null, k: 0, since: 999, seed: 0, fired: 0,
        isRare: false, seen: {}, onRare: null,
        /* Never inside the first half-minute, whatever the world says. */
        MIN_T: 30,
        /* A sighting needs a run that has gone somewhere. Two minutes in, and
           at most one of each per run — the second time you see a thing it
           stops being a sighting and becomes a feature. */
        RARE_T: 120,
        RARE_CHANCE: 0.06
      };

      /* A quiet window. Threat is the renderer's own reading of what is close
         and lethal, so this is the same number the character uses to decide it
         is alarmed — if the Nanogon is worried, the sky stays still. */
      d.calm = function (run) {
        return !run.dead && run.t > d.MIN_T &&
               run.threat < 0.22 && run.sinceNear > 1.5 && run.sinceFlip > 0.5;
      };

      d.update = function (dt, run, vis) {
        d.since += dt;
        if (d.active) {
          d.k += dt / (d.isRare ? RARE[d.active] : EVENTS[d.active]).dur;
          if (d.k >= 1) { d.active = null; d.isRare = false; d.k = 0; d.since = 0; }
          return;
        }
        var every = BY_WORLD[vis.world] || 0;
        if (!every || !d.calm(run)) return;
        if (d.since < every) return;
        /* Poisson-ish: once past the cooldown, a small chance per second, so
           two runs through the same stretch do not get the same schedule. */
        if (rng.next() > dt * 0.5) return;

        /* A sighting, occasionally, instead of an event. Same quiet window and
           the same draw path — the only differences are how rare it is, how
           long it lasts, and that it is remembered. */
        if (run.t > d.RARE_T && rng.next() < d.RARE_CHANCE) {
          var rpick = rng.next() * RARE_TOTAL, racc = 0, chosen = null;
          for (var ri = 0; ri < RARE_NAMES.length; ri++) {
            racc += RARE[RARE_NAMES[ri]].weight;
            if (rpick <= racc && !d.seen[RARE_NAMES[ri]]) { chosen = RARE_NAMES[ri]; break; }
          }
          if (chosen) {
            d.active = chosen; d.isRare = true; d.seen[chosen] = true;
            d.k = 0; d.seed = Math.floor(rng.next() * 1000000); d.fired++;
            if (d.onRare) d.onRare(chosen);
            return;
          }
        }

        var pick = rng.next() * TOTAL, acc = 0;
        for (var i = 0; i < NAMES.length; i++) {
          acc += EVENTS[NAMES[i]].weight;
          if (pick <= acc) { d.active = NAMES[i]; break; }
        }
        d.active = d.active || NAMES[0];
        d.isRare = false;
        d.k = 0;
        d.seed = Math.floor(rng.next() * 1000000);
        d.fired++;
      };

      d.draw = function (g, W, H) {
        if (!d.active) return;
        g.save();
        g.strokeStyle = '#ffffff';
        g.fillStyle = '#ffffff';
        (d.isRare ? RARE[d.active] : EVENTS[d.active]).draw(g, W, H, clamp(d.k, 0, 1), d.seed);
        g.restore();
      };

      return d;
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
