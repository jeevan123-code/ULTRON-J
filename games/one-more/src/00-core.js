/* ONE MORE — core utilities, deterministic RNG, storage, formatting.
   Every file attaches to the global OM namespace and is wrapped in an IIFE so
   the dev <script> tags and the single-file bundle behave identically. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});

  /* ---------- math ---------- */
  var M = OM.math = {
    clamp: function (v, a, b) { return v < a ? a : (v > b ? b : v); },
    lerp: function (a, b, t) { return a + (b - a) * t; },
    // frame-rate independent exponential approach
    approach: function (a, b, rate, dt) { return b + (a - b) * Math.exp(-rate * dt); },
    smooth: function (t) { return t * t * (3 - 2 * t); },
    sign: function (v) { return v < 0 ? -1 : 1; },
    rand: function (a, b) { return a + Math.random() * (b - a); }
  };

  /* ---------- deterministic RNG (mulberry32) ----------
     Used for the Daily Challenge so every player on a given day gets a
     byte-identical world. */
  OM.rng = function (seed) {
    var a = (seed >>> 0) || 1;
    function next() {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    return {
      next: next,
      range: function (lo, hi) { return lo + next() * (hi - lo); },
      int: function (lo, hi) { return Math.floor(lo + next() * (hi - lo + 1)); },
      pick: function (arr) { return arr[Math.floor(next() * arr.length)]; },
      chance: function (p) { return next() < p; }
    };
  };

  /* String -> 32bit seed, so "2026-08-30" maps to a stable world. */
  OM.hashSeed = function (str) {
    var h = 2166136261 >>> 0;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  };

  /* ---------- time ---------- */
  // 107.283 -> "01:47.28"
  OM.fmtTime = function (sec, decimals) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    var d = decimals == null ? 2 : decimals;
    var m = Math.floor(sec / 60);
    var s = sec - m * 60;
    var ss = s.toFixed(d);
    if (s < 10) ss = '0' + ss;
    return (m < 10 ? '0' + m : '' + m) + ':' + ss;
  };

  OM.fmtDelta = function (sec) {
    var s = Math.abs(sec);
    return (s < 10 ? s.toFixed(2) : s.toFixed(1)) + 's';
  };

  // UTC day index — the daily challenge rolls over at 00:00 UTC worldwide.
  OM.dayIndex = function (date) {
    var d = date || new Date();
    return Math.floor(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) / 86400000);
  };
  OM.dayKey = function (idx) {
    var ms = idx * 86400000;
    var d = new Date(ms);
    var p = function (n) { return n < 10 ? '0' + n : '' + n; };
    return d.getUTCFullYear() + '-' + p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate());
  };
  OM.msUntilNextDay = function () {
    var now = Date.now();
    return (Math.floor(now / 86400000) + 1) * 86400000 - now;
  };

  /* ---------- storage (never throws; private mode / blocked cookies are fine) ---------- */
  OM.store = {
    get: function (key, fallback) {
      try {
        var raw = root.localStorage.getItem(key);
        if (raw == null) return fallback;
        return JSON.parse(raw);
      } catch (e) { return fallback; }
    },
    set: function (key, value) {
      try { root.localStorage.setItem(key, JSON.stringify(value)); return true; }
      catch (e) { return false; }
    },
    del: function (key) {
      try { root.localStorage.removeItem(key); return true; } catch (e) { return false; }
    }
  };

  /* ---------- tiny event bus ---------- */
  OM.bus = (function () {
    var map = {};
    return {
      on: function (name, fn) { (map[name] || (map[name] = [])).push(fn); return fn; },
      off: function (name, fn) {
        var l = map[name]; if (!l) return;
        var i = l.indexOf(fn); if (i >= 0) l.splice(i, 1);
      },
      emit: function (name, payload) {
        var l = map[name]; if (!l) return;
        for (var i = 0; i < l.length; i++) { try { l[i](payload); } catch (e) { /* a listener must never kill the loop */ } }
      }
    };
  })();
})(typeof globalThis !== 'undefined' ? globalThis : this);
