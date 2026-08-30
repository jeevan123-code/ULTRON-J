#!/usr/bin/env node
/* ONE MORE — bundler.
 * Inlines every script and stylesheet into one file. There are no binary assets
 * to pack because the character, the world, the effects and the entire audio
 * track are generated at runtime, so "the whole game" really is one document.
 *
 *   dist/one-more.html   standalone page (hosting, itch, Pages, a phone)
 *   dist/artifact.html   same game as body-content only, for publishing
 */
'use strict';
var fs = require('fs'), path = require('path');
var ROOT = path.join(__dirname, '..');

function read(p) { return fs.readFileSync(path.join(ROOT, p), 'utf8'); }

var html = read('index.html');
var css = read('styles.css');

// keep source order exactly as index.html declares it
var scripts = [];
html.replace(/<script src="([^"]+)"><\/script>/g, function (_, src) { scripts.push(src); return _; });
var code = scripts.map(function (s) {
  return '/* ==== ' + s + ' ==== */\n' + read(s);
}).join('\n');

// </script> inside a string literal would close the tag early
function safe(js) { return js.replace(/<\/script>/gi, '<\\/script>'); }

var body = html
  .replace(/<link rel="stylesheet"[^>]*>/, '')
  .replace(/<script src="[^"]+"><\/script>\s*/g, '');

var inner = body.match(/<body>([\s\S]*)<\/body>/)[1].trim();
var built = Date.now();

var standalone = body
  .replace('</head>', '<style>\n' + css + '\n</style>\n<!-- built ' + new Date(built).toISOString() + ' -->\n</head>')
  .replace('</body>', '<script>\n' + safe(code) + '\n</script>\n</body>');

// The artifact host supplies <!doctype>, <head> and <body>, so ship content only.
var artifact = '<title>ONE MORE</title>\n<style>\n' + css + '\n</style>\n' +
               inner + '\n<script>\n' + safe(code) + '\n</script>\n';

fs.mkdirSync(path.join(ROOT, 'dist'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'dist/one-more.html'), standalone);
fs.writeFileSync(path.join(ROOT, 'dist/artifact.html'), artifact);

function kb(s) { return (Buffer.byteLength(s) / 1024).toFixed(1) + ' KB'; }
console.log('  dist/one-more.html  ' + kb(standalone) + '   (' + scripts.length + ' modules inlined)');
console.log('  dist/artifact.html  ' + kb(artifact));
