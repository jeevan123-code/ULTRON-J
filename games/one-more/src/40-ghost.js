/* ONE MORE — ghost recording and playback.
   A ghost is not a video. It is world-x, y and gravity sampled at a fixed rate,
   delta-encoded, a couple of bytes per frame. That is what makes racing your own
   record cost nothing and what would make sharing one over a wire cheap later.
   x is recorded as well as y, so the ghost occupies a real position in the world
   and you can watch your record run pull ahead of you or fall behind. */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});
  var RATE = 24;
  var MAX = RATE * 420;          // seven minutes, then recording simply stops

  OM.GhostRecorder = function () {
    var xs = [], ys = [], gs = [], acc = 0, n = 0, lastX = 0, x0 = null;
    return {
      sample: function (dt, x, y, grav) {
        acc += dt;
        while (acc >= 1 / RATE && n < MAX) {
          acc -= 1 / RATE;
          if (x0 === null) { x0 = Math.round(x); lastX = x0; }
          var xi = Math.round(x);
          xs.push(xi - lastX);            // deltas stay two digits
          lastX = xi;
          ys.push(Math.round(y));
          gs.push(grav > 0 ? 1 : 0);
          n++;
        }
      },
      finish: function () { return n > RATE ? { r: RATE, x0: x0, dx: xs, y: ys, g: gs } : null; }
    };
  };

  OM.GhostPlayer = function (data) {
    if (!data || !data.y || !data.y.length) return null;
    var rate = data.r || RATE, len = data.y.length;
    var xs = new Float64Array(len), acc = data.x0 || 0;
    for (var i = 0; i < len; i++) { acc += data.dx[i]; xs[i] = acc; }
    return {
      duration: len / rate,
      at: function (t) {
        var f = t * rate;
        if (f < 0) f = 0;
        var i = Math.floor(f);
        if (i >= len - 1) {
          return { x: xs[len - 1], y: data.y[len - 1], grav: data.g[len - 1] ? 1 : -1, done: true };
        }
        var m = f - i;
        return {
          x: xs[i] + (xs[i + 1] - xs[i]) * m,
          y: data.y[i] + (data.y[i + 1] - data.y[i]) * m,
          grav: data.g[i] ? 1 : -1,
          done: false
        };
      }
    };
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
