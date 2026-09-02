/* ONE MORE — the visual conductor: design tokens and one escalation signal.
 *
 * Two problems this exists to solve.
 *
 * The look was spread across forty-odd constants in four files — a glow alpha
 * here, a trail opacity there, a shake magnitude in a third place — so nothing
 * could be tuned as a whole and no two systems were guaranteed to agree about
 * what "intense" meant. Tokens live here now.
 *
 * And escalation was sampled independently at four call sites: corruptionAt(t)
 * for the UI, speedFrac for the streaks, worldAt(t) for the backdrop, threat
 * for the character. Four clocks drifting apart is how a game ends up looking
 * busy at one moment and empty at the next. sample() reads them once per frame
 * and hands every system the same numbers.
 *
 * It reports state. It does not decide gameplay: nothing here feeds physics,
 * collision or generation, and the escalation curves it exposes are the ones
 * the game already ran on.
 */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var clamp = OM.math.clamp;

  /* ---------- design tokens ----------
     Monochrome is the whole identity, so the palette is one ink at five
     weights on one ground. Anything that wants to stand out gets brightness,
     size, motion or break-up — never hue. */
  var T = {
    ground: '#08090c',
    ink: [255, 255, 255],

    // character
    bodyWeight: 1.75,          // px, the light half of the silhouette
    bodyWeightLead: 3.1,       // px, the edge facing the direction of travel
    rimAlpha: 0.85,            // leading-edge highlight at full speed
    coreScale: 0.26,           // core radius as a fraction of body radius
    coreHot: 0.50,             // solid hotspot inside the core gradient
    auraScale: 3.0,            // aura radius as a multiple of body radius
    auraAlpha: 0.13,           // aura peak alpha at full glow
    glowRingAlpha: 0.10,
    moteCount: 3,

    // world
    trailAlpha: 0.26,
    trailAlphaGain: 0.5,       // added by intensity
    particleDensity: 1,
    shake: 1,
    distortion: 1,

    // timing, seconds
    flipSettle: 17,            // rotation approach rate
    squashDecay: 11
  };

  function ink(a) { return 'rgba(255,255,255,' + (a < 0.001 ? 0 : a).toFixed(3) + ')'; }

  /* ---------- quality ----------
     A weak phone should be able to drop the expensive layers without losing
     anything it needs to play. Everything gameplay-critical — geometry,
     surfaces, the character's silhouette and core — is drawn at every tier;
     only the layers that exist to look expensive scale. */
  var TIERS = {
    low:    { aura: 0, motes: 0, rim: 0, particles: 0.5, streaks: 0.5, distortion: 0 },
    medium: { aura: 0.6, motes: 1, rim: 1, particles: 0.85, streaks: 0.85, distortion: 0.6 },
    high:   { aura: 1, motes: 1, rim: 1, particles: 1, streaks: 1, distortion: 1 }
  };

  var V = OM.visual = {
    tok: T,
    ink: ink,
    tiers: TIERS,
    quality: 'high',

    setQuality: function (q) { V.quality = TIERS[q] ? q : 'high'; },
    q: function () { return TIERS[V.quality]; },

    /* One read of the run, once per frame, for everybody.
     *
     * The channels are deliberately separate rather than collapsed into a
     * single number, because they mean genuinely different things and a system
     * usually wants one of them: `speed` is how fast the world is moving,
     * `threat` is whether something is about to kill you, `instability` is how
     * far the long-run corruption has come, `atmos` is how much environment
     * has been earned. `intensity` is the master the escalation reads from,
     * and it is what a caller should use when it just wants "how far in". */
    sample: function (run, P) {
      P = P || OM.phys;
      if (!run) {
        return { t: 0, speed: 0, threat: 0, instability: 0, atmos: 0,
                 intensity: 0, world: 'origin', worldIndex: 0, q: V.q() };
      }
      var t = run.t || 0;
      var speed = clamp(((run.speed || P.BASE_SPEED) - P.BASE_SPEED) / 520, 0, 1);
      var instability = P.corruptionAt(t);
      var world = run.world || P.WORLDS[0];
      var wi = 0;
      for (var i = 0; i < P.WORLDS.length; i++) if (P.WORLDS[i].id === world.id) wi = i;

      /* Atmosphere is earned by arriving somewhere, not by a clock, so it steps
         with the world and then eases across the gap to the next one. */
      var next = P.WORLDS[Math.min(wi + 1, P.WORLDS.length - 1)];
      var span = Math.max(1, next.at - world.at);
      var into = wi >= P.WORLDS.length - 1 ? 1 : clamp((t - world.at) / span, 0, 1);
      var atmos = clamp((wi + into) / (P.WORLDS.length - 1), 0, 1);

      return {
        t: t,
        speed: speed,
        threat: clamp(run.threat || 0, 0, 1),
        instability: instability,
        atmos: atmos,
        /* The master. Weighted so the first minute is carried by speed and
           arrival, and the back half is carried by things coming apart. */
        intensity: clamp(atmos * 0.5 + speed * 0.2 + instability * 0.3, 0, 1),
        world: world.id,
        worldIndex: wi,
        q: V.q()
      };
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
