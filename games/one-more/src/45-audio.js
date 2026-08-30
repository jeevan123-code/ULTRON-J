/* ONE MORE — procedural audio. No files: every sound is synthesised, so the
   whole game stays a single document and still has a soundtrack that reacts.
   The music is a step sequencer whose layers arrive as you survive; near a
   personal record it strips back to almost nothing, which is the loudest thing
   it can do at that moment. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var ctx = null, master = null, musicBus = null, sfxBus = null, noiseBuf = null;
  var started = false, muted = false, musicOn = true;
  var seq = { next: 0, step: 0, bpm: 108, intensity: 0, quiet: false };

  function ensure() {
    if (ctx) return ctx;
    var AC = root.AudioContext || root.webkitAudioContext;
    if (!AC) return null;
    try { ctx = new AC(); } catch (e) { return null; }
    master = ctx.createGain(); master.gain.value = 0.9; master.connect(ctx.destination);
    musicBus = ctx.createGain(); musicBus.gain.value = 0.34; musicBus.connect(master);
    sfxBus = ctx.createGain(); sfxBus.gain.value = 0.85; sfxBus.connect(master);
    // one second of white noise, reused for every percussive//textural sound
    noiseBuf = ctx.createBuffer(1, 44100, 44100);
    var d = noiseBuf.getChannelData(0);
    for (var i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return ctx;
  }

  function now() { return ctx ? ctx.currentTime : 0; }

  function env(node, t, a, d, peak) {
    var g = node.gain;
    g.setValueAtTime(0.0001, t);
    g.exponentialRampToValueAtTime(Math.max(0.0002, peak), t + a);
    g.exponentialRampToValueAtTime(0.0001, t + a + d);
  }

  function tone(freq, t, dur, peak, type, bus, slideTo) {
    if (!ctx) return;
    var o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type || 'sine';
    o.frequency.setValueAtTime(freq, t);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(Math.max(20, slideTo), t + dur);
    env(g, t, Math.min(0.012, dur * 0.2), dur, peak);
    o.connect(g); g.connect(bus || sfxBus);
    o.start(t); o.stop(t + dur + 0.05);
  }

  function noise(t, dur, peak, filterHz, q, bus, sweepTo) {
    if (!ctx) return;
    var s = ctx.createBufferSource(); s.buffer = noiseBuf;
    var f = ctx.createBiquadFilter();
    f.type = 'bandpass'; f.frequency.setValueAtTime(filterHz, t); f.Q.value = q || 1;
    if (sweepTo) f.frequency.exponentialRampToValueAtTime(Math.max(40, sweepTo), t + dur);
    var g = ctx.createGain();
    env(g, t, 0.004, dur, peak);
    s.connect(f); f.connect(g); g.connect(bus || sfxBus);
    s.start(t); s.stop(t + dur + 0.05);
  }

  /* ---------- sfx ---------- */
  var SFX = {
    flip: function (dir) {
      var t = now();
      noise(t, 0.055, 0.30, dir > 0 ? 1500 : 2100, 2.2, sfxBus, dir > 0 ? 700 : 3000);
      tone(dir > 0 ? 300 : 420, t, 0.09, 0.16, 'triangle', sfxBus, dir > 0 ? 170 : 250);
    },
    land: function () { var t = now(); noise(t, 0.05, 0.11, 320, 1.1); },
    near: function () {
      var t = now();
      tone(1760, t, 0.09, 0.075, 'sine', sfxBus, 2400);
      noise(t, 0.05, 0.05, 5200, 5);
    },
    perfect: function () {
      var t = now();
      [1318, 1975, 2637].forEach(function (f, i) { tone(f, t + i * 0.022, 0.2, 0.10, 'sine'); });
    },
    death: function () {
      var t = now();
      noise(t, 0.42, 0.55, 900, 0.6, sfxBus, 60);
      tone(180, t, 0.5, 0.32, 'sawtooth', sfxBus, 32);
      tone(90, t, 0.65, 0.22, 'sine', sfxBus, 26);
    },
    record: function () {
      var t = now();
      [523, 659, 784, 1046, 1318].forEach(function (f, i) {
        tone(f, t + i * 0.07, 0.42, 0.15, 'triangle');
      });
    },
    mutation: function () {
      var t = now();
      tone(70, t, 0.75, 0.28, 'sawtooth', sfxBus, 190);
      noise(t, 0.6, 0.11, 400, 0.7, sfxBus, 2600);
    },
    world: function () {
      var t = now();
      [196, 294, 392].forEach(function (f, i) { tone(f, t + i * 0.09, 0.7, 0.11, 'sine'); });
    },
    ui: function () { var t = now(); tone(880, t, 0.035, 0.05, 'square'); },
    level: function () {
      var t = now();
      [440, 554, 659, 880].forEach(function (f, i) { tone(f, t + i * 0.06, 0.35, 0.12, 'triangle'); });
    }
  };

  /* ---------- adaptive music ----------
     Layers arrive with survival time. `quiet` is the record-approach state: it
     mutes everything except a heartbeat, which makes the last few seconds of a
     personal best feel like the room went silent. */
  function step(t) {
    var i = seq.intensity, s = seq.step;
    var root0 = 55;

    if (seq.quiet) {
      if (s % 8 === 0) tone(root0, t, 0.34, 0.5, 'sine', musicBus, root0 * 0.75);
      if (s % 8 === 3) tone(root0 * 0.99, t, 0.22, 0.28, 'sine', musicBus);
      return;
    }
    // drone
    if (s % 16 === 0) tone(root0, t, 2.4, 0.30, 'sine', musicBus);
    // kick
    if (i > 0.12 && s % 4 === 0) {
      tone(120, t, 0.19, 0.60, 'sine', musicBus, 42);
      noise(t, 0.05, 0.13, 180, 0.8, musicBus);
    }
    // hat
    if (i > 0.34 && s % 2 === 1) noise(t, 0.035, 0.05 + i * 0.05, 8200, 3, musicBus);
    // bass figure
    if (i > 0.5) {
      var pat = [0, 0, 7, 0, 5, 0, 3, 0];
      var n = pat[s % 8];
      if (n || s % 8 === 0) tone(root0 * 2 * Math.pow(2, n / 12), t, 0.16, 0.22, 'square', musicBus);
    }
    // tension pad
    if (i > 0.72 && s % 16 === 8) {
      tone(root0 * 3, t, 1.9, 0.10, 'sawtooth', musicBus);
      tone(root0 * 3 * 1.005, t, 1.9, 0.08, 'sawtooth', musicBus);
    }
    if (i > 0.9 && s % 8 === 6) noise(t, 0.3, 0.05, 300, 0.5, musicBus, 3000);
  }

  function pump() {
    if (!ctx || !musicOn || muted) return;
    var spb = 60 / (seq.bpm + seq.intensity * 26) / 2;   // eighth notes
    var t = now();
    while (seq.next < t + 0.12) {
      if (seq.next < t) seq.next = t + 0.01;
      step(seq.next);
      seq.next += spb;
      seq.step = (seq.step + 1) % 64;
    }
  }

  OM.audio = {
    unlock: function () {
      if (!ensure()) return;
      if (ctx.state === 'suspended') ctx.resume();
      if (!started) { started = true; seq.next = now() + 0.05; }
    },
    setMuted: function (m) { muted = m; if (master) master.gain.value = m ? 0 : 0.9; },
    setMusic: function (on) {
      musicOn = on;
      if (musicBus) musicBus.gain.value = on ? 0.34 : 0;
    },
    play: function (name, arg) {
      if (muted || !ctx) return;
      var f = SFX[name]; if (f) { try { f(arg); } catch (e) {} }
    },
    music: function (intensity, quiet) {
      seq.intensity = intensity;
      seq.quiet = !!quiet;
      pump();
    },
    stopMusic: function () { seq.intensity = 0; seq.quiet = false; },
    ready: function () { return !!ctx; }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
