// What every part of the page builds on: finding and making elements, the words for numbers and times, and the moment on the page.
'use strict';
const $ = s => document.querySelector(s);  // The first element of the page that matches a selector.
const SVG = 'http://www.w3.org/2000/svg';
const TAU = Math.PI * 2;
const WINDOW = 1800;
const calm = matchMedia('(prefers-reduced-motion: reduce)');
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));  // A value held between two bounds, 0 and 1 unless told otherwise.
// A soft step from 0 to 1 as v goes from a to b, without a kink at either end.
const smooth = (a, b, v) => { const x = clamp((v - a) / (b - a)); return x * x * (3 - 2 * x); };

function draw(tag, attrs, parent) {  // Makes an SVG element with its attributes and hangs it into a parent, if one is given.
  const e = document.createElementNS(SVG, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
// Makes an HTML element with a class and a text and hangs it into a parent; the text goes in as text, never as markup.
function make(tag, cls, parent, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
function show(el, on) { el.hidden = !on; }  // Shows an element or hides it.
let owed = null;  // a change of the page that was handed to a view transition and is not made yet
function settle() { if (owed) owed(); }  // Makes the change a view transition still owes, if any. Whoever decides from what the page shows asks this first.
/* Makes a change of the page, faded over where the browser offers a view transition and motion is wanted. may: whether this change is one to fade.
   The browser makes the change of a transition later, by itself, and it skips the fading when a newer one overtakes it or the window is hidden: then it rejects, which is caught here and is no error.
   Whatever becomes of the fading, the change is made once, and before any change asked for after it: one that is still owed is made as soon as its fading is skipped, and first when the next change comes. */
function faded(change, may = true) {
  settle();
  if (!may || !document.startViewTransition || calm.matches) return change();
  const once = () => { if (owed !== once) return; owed = null; change(); };
  owed = once;
  document.startViewTransition(once).ready.catch(once);
}

const span = s => {  // A length of time in words: seconds up to two minutes, then minutes, then hours and minutes.
  s = Math.max(0, Math.round(s));
  if (s < 120) return s + ' s';
  const m = Math.round(s / 60);
  if (m < 60) return m + ' min';
  const h = Math.floor(m / 60);
  return h + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
};
// The time of day of a moment, with seconds if asked.
const clock = (t, secs) => new Date(t * 1000).toLocaleTimeString([], secs ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
const pct = v => v == null ? 'n/a' : (v * 100).toFixed(v < 0.01 ? 1 : 0) + ' %';  // A share as a percentage, n/a when it was not read.
// A count as a whole number with thousands separators, a dash when it was not read.
const whole = v => v == null ? '–' : Math.round(v).toLocaleString('en-US');
// A duration as milliseconds or seconds, n/a when it was not read.
const seconds = v => v == null ? 'n/a' : v < 1 ? Math.round(v * 1000) + ' ms' : v.toFixed(1) + ' s';
// A big number in short: millions as M, thousands as K.
const size = v => v >= 1e6 ? (v / 1e6).toFixed(1) + ' M' : v >= 1e3 ? Math.round(v / 1e3) + ' K' : String(v);
// A context length in tokens the way model cards write it: 1M, 256K.
const context = v => v >= 1048576 ? (v / 1048576) + 'M' : Math.round(v / 1024) + 'K';
let S = null, LIVE = null;  // S is the moment on the page, LIVE the newest one that arrived

