/* ONE MORE — the glyphs.
 *
 * A set of marks that look like they mean something, generated rather than
 * drawn, so they share a family resemblance without any of them being a
 * picture of anything. Each one is a ring, a few chords across it and a few
 * points on it, chosen by hashing its name — which makes them consistent
 * forever, identical for every player, and free to store.
 *
 * They are never explained. The game shows one when something rare has
 * happened and lets that sit. Nothing about a glyph gates anything, nothing
 * about them has to be solved, and a player who never wonders about them loses
 * nothing at all — which is the only honest way to put a mystery in a game
 * whose actual subject is a tap.
 */
(function (root) {
  'use strict';
  var OM = root.OM || (root.OM = {});

  function hash(str, salt) {
    var h = 2166136261 ^ (salt | 0);
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    return h / 4294967296;
  }

  OM.glyphs = {
    /* Deterministic from the name. Two calls with the same id anywhere in the
       game — the archive, a results screen, a wall in the background — draw the
       identical mark, which is what makes them read as a writing system rather
       than as noise. */
    draw: function (g, id, x, y, r, alpha) {
      var chords = 2 + Math.floor(hash(id, 1) * 3);
      var dots = 1 + Math.floor(hash(id, 2) * 3);
      var open = hash(id, 3) > 0.55;
      var tilt = hash(id, 4) * Math.PI;
      g.save();
      g.translate(x, y);
      g.rotate(tilt);
      g.globalAlpha = alpha == null ? 1 : alpha;
      g.strokeStyle = '#ffffff';
      g.fillStyle = '#ffffff';
      g.lineWidth = Math.max(0.8, r * 0.075);
      g.lineCap = 'round';

      g.beginPath();
      if (open) {
        var a0 = hash(id, 5) * 6.2832;
        g.arc(0, 0, r, a0, a0 + 4.4);
      } else {
        g.arc(0, 0, r, 0, 6.2832);
      }
      g.stroke();

      for (var c = 0; c < chords; c++) {
        var s = hash(id, 10 + c) * 6.2832;
        var e = s + 1.4 + hash(id, 20 + c) * 3.2;
        g.beginPath();
        g.moveTo(Math.cos(s) * r, Math.sin(s) * r);
        g.lineTo(Math.cos(e) * r, Math.sin(e) * r);
        g.stroke();
      }
      for (var d = 0; d < dots; d++) {
        var da = hash(id, 30 + d) * 6.2832;
        var dr = r * (0.3 + hash(id, 40 + d) * 0.7);
        g.beginPath();
        g.arc(Math.cos(da) * dr, Math.sin(da) * dr, Math.max(1, r * 0.11), 0, 6.2832);
        g.fill();
      }
      g.restore();
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
