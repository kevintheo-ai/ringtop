// The traces of the last half hour: every sample the page was sent and the lines drawn from them, and the one way the page asks for a stretch of the past.
'use strict';
const liveSeries = new Map();
let series = liveSeries;  // every trace reads this; the time machine swaps in the half hour before the moment it shows
// Adds one sample to a live trace and drops what is older than the half hour on the page; a value that was not read adds nothing.
function push(key, t, v) {
  if (v == null) return;
  let s = liveSeries.get(key);
  if (!s) liveSeries.set(key, s = { t: [], v: [] });
  s.t.push(t); s.v.push(v);
  let cut = 0;
  while (cut < s.t.length && s.t[cut] < t - WINDOW) cut++;
  if (cut) { s.t.splice(0, cut); s.v.splice(0, cut); }
}
function record(state) {  // Keeps one moment in the live traces: the engine's numbers, every Spark's readings and the traffic of every link.
  for (const k of ['tok_s', 'running', 'waiting', 'kv', 'ttft_p95', 'itl_p50']) if (state.engine[k] != null) push('engine.' + k, state.t, state.engine[k]);
  for (const n of state.nodes) if (n.live) for (const k of TRACED) push(n.name + '.' + k, state.t, n[k]);
  for (const n of state.nodes) if (n.live && n.own) push(n.name + '.own_tok_s', state.t, n.own.tok_s);  // the speed of its own engine, for the line of all engines
  for (const e of state.edges) {
    const node = state.nodes.find(n => n.rank === e.from);
    if (node) { push(`${node.name}.${e.group}.tx`, state.t, e.gbps); push(`${node.name}.${e.group}.rx`, state.t, e.rx); }
  }
}
/* The one way the page asks the server for a stretch of the past: traces by their keys, thinned to so many columns, with the events of the
   stretch and, with band, the lowest value and the count of every column. With neutral names the server is asked under the real ones, and
   its answer comes back under the neutral ones. Throws where the server gives no stretch. */
async function askHistory(keys, from, to, points, band) {
  const asked = NEUTRAL ? realKeys(keys, realNames) : keys;
  const res = await fetch(`api/history?keys=${encodeURIComponent(asked.join(','))}&from=${from.toFixed(1)}&to=${to.toFixed(1)}&points=${points}&events=1${band ? '&band=1' : ''}`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const answer = await res.json();
  if (!isStretch(answer)) throw new Error('its answer is no stretch of the history');  // an error said as JSON would be drawn as a stretch, and every moment after it would fail
  return NEUTRAL ? neutralHistory(answer, renames, realNames) : answer;
}
const valueAt = (key, t) => nearest(series.get(key), t);  // What a trace says at a moment, by its name.
function nearest(s, t) {  // what one trace says at a moment: its nearest sample within half a minute. Without a moment: its last
  if (!s || !s.t.length) return null;
  if (t == null) return s.v[s.v.length - 1];
  let lo = 0, hi = s.t.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (s.t[mid] < t) lo = mid + 1; else hi = mid; }
  if (lo > 0 && t - s.t[lo - 1] < s.t[lo] - t) lo--;  // the nearest sample, not the next one
  return Math.abs(s.t[lo] - t) < 30 ? s.v[lo] : null;
}
// A trace as the path of an SVG line across the half hour; where samples are missing the line breaks instead of bridging the hole.
function tracePath(s, tmin, lo, hi, height, gap) {
  if (!s || s.t.length < 2) return '';
  const step = Math.max(1, Math.floor(s.t.length / 140));
  const range = hi - lo || 1;
  const spacing = (s.t[s.t.length - 1] - s.t[0]) / (s.t.length - 1);  // the server thins out older history
  const limit = Math.max(gap, spacing * 3) * step;
  let d = '', last = null;
  for (let i = 0; i < s.t.length; i += step) {
    const x = (s.t[i] - tmin) / WINDOW * 100;
    const y = height - 2 - (s.v[i] - lo) / range * (height - 4);
    d += (last == null || s.t[i] - last > limit ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2);
    last = s.t[i];
  }
  return d;
}
function fillUnder(line, height) {  // The area under a line down to the foot of its chart, piece by piece where the line breaks.
  return line.split('M').filter(Boolean).map(part => {
    const points = part.split('L');
    return `M${part}L${points[points.length - 1].split(' ')[0]} ${height}L${points[0].split(' ')[0]} ${height}Z`;
  }).join('');
}

