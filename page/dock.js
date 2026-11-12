// The dock: one tile per Spark with its power, its trace and what it says about itself.
'use strict';
/* ---- the nodes ---- */
const tiles = new Map();
function buildDock(cluster) {  // Builds one tile per Spark, once, and keeps the elements each tile is painted through.
  const dock = $('#dock');
  for (const node of cluster.nodes) {
    const tile = make('div', 'tile', dock);
    tile.dataset.node = node.name;
    tile.tabIndex = 0;
    tile.setAttribute('role', 'button');
    tile.setAttribute('aria-label', 'Open ' + node.name);
    const head = make('div', 't-head', tile);
    const dot = make('i', '', head);
    make('b', '', head, node.name);
    const note = make('span', '', head);
    const mid = make('div', 't-mid', tile);
    const power = make('strong', '', mid);
    const value = document.createTextNode('');
    power.appendChild(value);
    make('small', '', power, 'W GPU');
    power.title = GPU_POWER_NOTE;
    const svg = draw('svg', { class: 'trace', viewBox: '0 0 100 26', preserveAspectRatio: 'none', 'aria-hidden': 'true' }, mid);
    const fill = draw('path', { class: 'fill' }, svg);
    const path = draw('path', {}, svg);
    const cursor = draw('line', { y1: 0, y2: 26 }, svg);
    const stats = make('div', 't-stats', tile);
    const stat = name => { const s = make('span', '', stats); const v = document.createTextNode(''); s.appendChild(v); make('em', '', s, name); return v; };
    tiles.set(node.name, { tile, dot, note, value, svg, fill, path, cursor, temp: stat('GPU'), mem: stat('Free RAM'), net: stat(cluster.ring ? 'Ring traffic' : 'Fabric traffic'), clock: stat('Clock'), job: make('i', 't-job', tile) });
  }
}
function paintJob(t, job, note) {  // the job a run source names for this Spark: a thin bar along the foot of its tile, its words behind the note
  const share = trackShare(job), word = trackWord(job);
  t.job.style.width = share == null ? '0' : (share * 100).toFixed(1) + '%';
  t.note.title = word ? `${note} (${word})` : note;
}
function renderDock(state) {  // Paints every tile for one moment: its note, its job and its power trace, all traces on one scale.
  const tmin = state.t - WINDOW, jobs = trackRows(state.run && state.run.tracks, state.nodes);
  let lo = Infinity, hi = -Infinity;
  for (const n of state.nodes) { const s = series.get(n.name + '.w'); if (s) for (const v of s.v) { if (v < lo) lo = v; if (v > hi) hi = v; } }
  if (lo === Infinity) { lo = 0; hi = 1; }
  const pad = Math.max((hi - lo) * .15, 1);
  for (const n of state.nodes) {
    const t = tiles.get(n.name);
    t.tile.classList.toggle('down', !n.live);
    const note = nodeNote(n, state.identity);
    t.note.textContent = note.text; t.note.className = note.cls;
    paintJob(t, jobOf(jobs, n.name), note.text);
    t.dot.style.setProperty('--tone', toneOf(note.cls));
    const line = tracePath(series.get(n.name + '.w'), tmin, lo - pad, hi + pad, 26, state.identity.interval * 3);
    t.path.setAttribute('d', line);
    t.fill.setAttribute('d', fillUnder(line, 26));
  }
  renderDockValues();
}
const fmt = (v, d, unit) => v == null ? '–' : v.toFixed(d) + ' ' + unit;  // A reading with digits and a unit, a dash when it was not read.
// Writes the numbers of every tile: those of the moment the pointer rests on, otherwise the current ones, and moves the cursor lines.
function renderDockValues() {
  if (!S) return;
  const x = hoverT == null ? null : (hoverT - (S.t - WINDOW)) / WINDOW * 100;
  const at = (n, key) => hoverT != null ? valueAt(n.name + '.' + key, hoverT) : (n.live ? n[key] : null);
  for (const n of S.nodes) {
    const t = tiles.get(n.name);
    const w = at(n, 'w');
    t.value.textContent = w == null ? '–' : Math.round(w);
    t.temp.textContent = fmt(at(n, 'gpu_c'), 0, '°C');
    t.mem.textContent = fmt(at(n, 'mem_free_gb'), 0, 'GB');
    { const v = at(n, 'net'); t.net.textContent = fmt(v, v != null && v >= 100 ? 0 : 1, 'Gb/s'); }
    t.clock.textContent = ghz(at(n, 'mhz'));
    t.svg.classList.toggle('on', x != null);
    if (x != null) { t.cursor.setAttribute('x1', x); t.cursor.setAttribute('x2', x); }
  }
  const speed = $('#speed');
  speed.classList.toggle('on', x != null);
  if (x != null) { const l = speed.querySelector('line'); l.setAttribute('x1', x); l.setAttribute('x2', x); }
}

