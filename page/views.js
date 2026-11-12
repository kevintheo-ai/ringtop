// The other views: one node up close, why, memory, cooling, events and the runs.
'use strict';
/* ---- the other views: one node up close, why, memory, cooling, events, the runs ---- */
const VIEWS = [['ring', 'Ring'], ['why', 'Why'], ['memory', 'Memory'], ['cooling', 'Cooling'], ['events', 'Events'], ['run', 'Runs']];
let V = 'ring', VN = null, VP = null;
const panel = $('#panel');
function surfaces() {  // Shows what the view on the page needs: run and engine beside the ring, the sheet for a Spark, the panel for every other view and for one part of a Spark.
  const sheet = V === 'node' && !VP;
  show($('#now'), V === 'ring'); show($('#engine'), V === 'ring'); show(panel, V !== 'ring' && !sheet); show($('#spark'), sheet);
  const roomy = V === 'cooling' && Cooling.wide();
  document.body.classList.toggle('sparking', V === 'node' || roomy);  // a Spark up close, or cooling in its wide form: the sheet takes the width, the scene stands in a narrow column
  document.body.classList.toggle('roomy', roomy);  // the ring in that narrow column goes without its tags: they would lie on one another
  if (sheet) Spark.open(VN); else if (V !== 'node') Spark.close();
  if (V === 'cooling') Cooling.open(); else Cooling.close();  // cooling stands on a board of its own and is built once, like the sheet
  if (V === 'run') Runs.open(); else Runs.close();  // and so do the runs
}
function setPart(name) {  // Picks one part of the open Spark, or none, in the scene and in the panel.
  VP = name;
  Scene.select(name);
  surfaces();
  if (S) paintPanel();
}
function setView(view, node = null) {  // Changes the view: the ring, one of the panels, or one Spark up close, which the scene then flies to. A Spark this ring does not have (an old link) leads to the ring. A change before this one that still waits for its fading is made first: this one is decided from the view the page is on by then.
  settle();
  if (view === 'node' && !(S && S.nodes.some(n => n.name === node))) { view = 'ring'; node = null; }
  if (view === V && node === VN) { if (VP) setPart(null); return; }  // the same view again changes nothing, except that a click on the open Spark leads from one of its parts back to its sheet
  const go = () => {
    V = view; VN = node; VP = null;
    Scene.focus(view === 'node' ? node : null);
    surfaces();
    panel.scrollTop = 0;
    for (const b of $('#views').children) b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false');
    for (const [name, t] of tiles) t.tile.classList.toggle('picked', name === node);
    if (S) paintPanel();
  };
  faded(go, !!lastFrame);  // no transition for a deep link: the page has not drawn yet
}
function buildNav() {  // Builds the buttons for the views and for nerd mode, once.
  for (const [view, word] of VIEWS) {
    const b = make('button', '', $('#views'), word);
    b.dataset.view = view;
    b.setAttribute('aria-current', view === 'ring' ? 'page' : 'false');
    b.addEventListener('click', () => setView(view));
  }
  if (NEUTRAL) return;  // nerd mode shows logs and settings as they are: with neutral names it is not offered
  const nerd = make('button', '', $('#views'), 'Nerd');
  nerd.title = 'Nerd mode (N)';
  nerd.addEventListener('click', () => { Time.live(); Nerd.toggle(true); });
}
function paintPanel() {  // Repaints the panel of the open view from the moment on the page and keeps how far it was scrolled.
  if (V === 'ring') return;
  if (V === 'node' && !VP) { Spark.tick(); return; }  // the sheet of a Spark is built once and follows the moment by itself
  if (V === 'cooling') { Cooling.tick(); return; }  // and so does the cooling view
  if (V === 'run') { Runs.tick(); return; }  // and the runs
  const top = panel.scrollTop;
  panel.textContent = '';
  ({ why: paintWhy, memory: paintMemory, events: paintEvents, node: paintNode })[V]();
  panel.scrollTop = top;
}
// The button at the top of a panel that leads back to the ring.
function backButton() { make('button', 'back', panel, '‹ Ring').addEventListener('click', () => setView('ring')); }
const fixed = (v, d) => v == null ? '–' : v.toFixed(d);  // A number with a fixed count of digits, a dash when it was not read.
function stats(parent, rows) {  // A grid of small figures, each with its word.
  const g = make('div', 'grid3', parent);
  for (const [word, value] of rows) { const c = make('div', '', g); make('b', '', c, value); make('span', '', c, word); }
}
function memBar(parent, n) {  // The memory of a Spark as one bar: the model, everything else and what is free, with the mark of the memory guard.
  const total = n.mem_total_gb, free = n.mem_free_gb;
  if (!total || free == null) return make('p', 'p-note', parent, 'No memory reading.');
  const model = (n.apps || []).reduce((a, x) => a + x.gb, 0), other = Math.max(0, total - free - model);
  const bar = make('div', 'bar', parent);
  for (const [v, cls, word] of [[model, 'm', 'Model'], [other, 'o', (n.apps || []).length ? 'Everything else' : 'In use'], [free, 'f', 'Free']]) {
    if (v <= .05) continue;
    const part = make('i', cls, bar);
    part.style.flexGrow = v;
    part.title = `${word}: ${v.toFixed(1)} GB`;
  }
  const guard = S.identity.memguard_gib;
  if (guard != null) { const g = make('b', 'guard', bar); g.style.right = (guard / total * 100).toFixed(1) + '%'; g.title = `Memory guard: ${guard} GB free`; }
  return bar;
}
function eventRows(parent, list) {  // A list of events, each with its time, its Spark and its text.
  for (const e of list) {
    const row = make('div', 'ev ' + e.level, parent);
    const when = new Date(e.t * 1000);
    make('time', '', row, when.toDateString() === new Date().toDateString() ? clock(e.t, true) : when.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }));
    const text = make('p', '', row);
    if (e.node) make('b', '', text, e.node.split('-').pop() + '  ');
    text.appendChild(document.createTextNode(e.text));
  }
}
function paintWhy() {  // The Why view: the headline, where the time of a request goes, what else holds the speed back, and how far drafts survive.
  const e = S.engine, t = e.timing || {};
  make('h2', '', panel, S.why.headline);
  const parts = [['Waiting', t.queue, 'var(--amber)'], ['Reading', t.prefill, 'var(--teal)'], ['Writing', t.decode, 'var(--violet)']].filter(p => p[1] > 0);
  if (parts.length) {
    make('p', 'p-sub', panel, 'Where the time of an average request goes');
    const bar = make('div', 'bar', panel);
    for (const [word, v, color] of parts) { const i = make('i', '', bar); i.style.flexGrow = v; i.style.background = color; i.title = word; }
    const legend = make('div', 'legend', panel);
    for (const [word, v, color] of parts) { const l = make('span', '', legend); make('i', '', l).style.background = color; l.appendChild(document.createTextNode(`${word} ${seconds(v)}`)); }
  }
  const more = S.why.points.filter(p => p.text !== S.why.headline);
  if (more.length) {
    const list = make('ul', 'points', panel);
    for (const p of more) make('li', p.level, list, p.text);
  }
  const drafts = e.spec || [];
  if (drafts.filter(v => v != null).length > 1) {  // the same shares the hoops on the beam are drawn from
    make('p', 'p-sub', panel, `Drafts that survive, by position${e.spec_length != null ? ` · mean ${e.spec_length.toFixed(2)} tokens` : ''}`);
    const bars = make('div', 'n-spec', panel);
    drafts.forEach((v, i) => { const col = make('i', '', bars); col.title = `position ${i + 1}: ${v == null ? 'no drafts' : Math.round(v * 100) + ' % kept'}`; if (v != null) make('b', '', col).style.height = (v * 100).toFixed(1) + '%'; });
    const ends = make('div', 'n-spec-x', panel);
    make('span', '', ends, 'first drafted token'); make('span', '', ends, `position ${drafts.length}`);
    make('p', 'p-note', panel, 'The engine drafts several tokens ahead and keeps the ones the model agrees with. Tall bars far to the right mean long drafts survive, so fewer model steps are needed. The hoops on the beam show the same shares.');
  }
  if (!e.past) stats(panel, [['per request', seconds(t.total)], ['tokens in', whole(e.prompt_avg)], ['tokens out', whole(e.output_avg)]]);
}
function paintMemory() {  // The Memory view: one bar per Spark, and a click opens that Spark.
  make('h2', '', panel, 'Memory on each Spark');
  for (const n of S.nodes) {
    const row = make('button', 'memrow', panel);
    row.addEventListener('click', () => setView('node', n.name));
    const head = make('div', 'memhead', row);
    make('b', '', head, n.name);
    make('span', '', head, !n.live ? 'unreachable' : `${fixed(n.mem_free_gb, 1)} GB free${n.psi ? `, stalled ${n.psi.toFixed(0)} %` : ''}`);
    memBar(row, n);
  }
  const legend = make('div', 'legend', panel);
  for (const [word, color] of [['Model', 'var(--violet)'], ['Everything else', 'rgba(255,255,255,.3)'], ['Free', 'rgba(78,230,199,.32)'], ['Memory guard', 'var(--amber)']]) { const l = make('span', '', legend); make('i', '', l).style.background = color; l.appendChild(document.createTextNode(word)); }
}
function paintEvents() {  // The Events view: what happened, newest first.
  make('h2', '', panel, 'What happened');
  if (!S.events.length) { make('p', 'p-note', panel, 'Nothing yet. Kernel errors, memory stops, link problems and runs show up here.'); return; }
  eventRows(panel, S.events.slice().reverse());
}
function chart(parent, word, key, value, n) {  // A half-hour chart of one reading of a Spark, with its value now in the head.
  const box = make('div', 'chart', parent), head = make('span', '', box);
  head.appendChild(document.createTextNode(word)); make('b', '', head, value);
  const s = series.get(n.name + '.' + key), svg = draw('svg', { class: 'trace', viewBox: '0 0 100 30', preserveAspectRatio: 'none', 'aria-hidden': 'true' }, box);
  let lo = Infinity, hi = -Infinity;
  if (s) for (const v of s.v) { if (v < lo) lo = v; if (v > hi) hi = v; }
  if (lo === Infinity) return;
  const pad = Math.max((hi - lo) * .15, .5), line = tracePath(s, S.t - WINDOW, lo - pad, hi + pad, 30, S.identity.interval * 3);
  draw('path', { class: 'fill', d: fillUnder(line, 30) }, svg);
  draw('path', { d: line }, svg);
}
// One part of the open Spark in the panel. A Spark that is gone leads back to the ring, one out of reach back to its sheet.
function paintNode() {
  const n = S.nodes.find(x => x.name === VN);
  if (!n) { setView('ring'); return; }
  if (!n.live) { setPart(null); return; }
  paintPart(n);
}
