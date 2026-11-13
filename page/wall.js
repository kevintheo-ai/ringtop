// The calm page for a wall and a phone: the stream of moments a wall gets, one moment on five quiet surfaces, and the watch over how fresh it is.
'use strict';
/* Every word the calm page says that the main page does not say, in one place. */
const WALL_TEXTS = {
  names: 'Neutral',  // The button in the head: switches between the names the Sparks have and neutral ones. It is pressed while neutral names are shown, and its word says what is on then.
  namesTitle: on => on ? 'Neutral names are shown (spark-1 to spark-N by rank, "Test run" for runs); the real names still reach this device. Press to show them (H).' : 'The real names are shown. Press for neutral names (H), for a picture or film of this page; the real names still reach this device.',  // What the button says of itself, as its tooltip and for a screen reader. on: neutral names are shown.
  stale: when => `No new data since ${when}`,  // The corner, in place of Live, once no new moment came for longer than the silence. when: the time of day the last one came, with seconds.
};
/* The words the calm page says exactly as the main page says them, with where they stand there. Not placeholders: whoever changes one changes it in both places (a check holds every plain word against the main page). */
const MAIN_WORDS = {
  none: 'Nothing running',  // run.js: the name of the run while there is none
  count: (done, total) => `${done} of ${total}`, done: done => `${done} done`,  // run.js: how far a run is
  unit: 'tok/s',  // nerd-live.js, rules.js: tokens per second, beside a number
  celsius: '°C', gpu: 'GPU', rpm: 'RPM', fans: 'Fans', gb: 'GB', free: 'Free RAM',  // dock.js, cooling.js: a figure of a Spark with its unit and what it is
  power: 'GPU power', watts: sum => `${sum} W`, read: (read, of) => `${read} of ${of} read`,  // vitals.js: the sum over the Sparks that were read, and of how many it is
  neutral: 'Shown with neutral names for the Sparks and the runs (H).',  // main.js: said wherever neutral names are shown
};
const MOMENT_PARTS = ['t', 'cluster', 'identity', 'engine', 'nodes'];  // what a word of the stream must hold to be a moment the page can show
const tilesOf = new Map(), foot = {};  // the elements every tile and the foot are painted through
let shownT = null, gotAt = null, openedAt = 0, open = false, stream = null, clusterNames = '';  // shownT: the time of the moment on the page. gotAt: when it came, by the clock of this device. openedAt: when the stream was last opened. open: the stream stands. clusterNames: the cluster the page was built for, as the server named it

function buildTiles(cluster) {  // Builds one tile per Spark, once, and says how many columns and rows they stand in, for either form of the page (the sheet picks the form).
  const box = $('#tiles'), n = cluster.nodes.length, wide = wallCols(n, true);
  box.textContent = '';
  for (const [key, value] of [['--cols-tall', wallCols(n, false)], ['--cols-wide', wide], ['--rows-wide', Math.ceil(n / wide)]]) box.style.setProperty(key, value);
  for (const node of cluster.nodes) {
    const tile = make('div', 'tile', box), head = make('div', 't-head', tile), dot = make('i', '', head);
    make('b', '', head, node.name);
    const note = make('span', '', head), stats = make('div', 't-stats', tile);
    const stat = (unit, what) => { const cell = make('span', '', stats), value = make('strong', '', cell, '–'); make('small', '', cell, unit); make('em', '', cell, what); return { cell, value }; };
    tilesOf.set(node.name, { tile, dot, note, temp: stat(MAIN_WORDS.celsius, MAIN_WORDS.gpu), fan: stat(MAIN_WORDS.rpm, MAIN_WORDS.fans), mem: stat(MAIN_WORDS.gb, MAIN_WORDS.free) });
  }
}
function showCore(state) {  // Writes the speed: tokens per second as the largest number while tokens are written, else the word of the core in its place; under it the line of the core.
  const face = coreFace(state.engine);
  $('#core-state').textContent = face.word;
  $('#core-dot').style.setProperty('--tone', TONES[face.tone] || 'var(--faint)');
  $('#core-num').textContent = face.goal == null ? '' : whole(face.goal);
  $('#speed').classList.toggle('wordy', face.goal == null);
  $('#core-sub').textContent = face.sub;
}
function showRun(state) {  // Writes the run: its name, how far it is as a count and a bar, and how long it has been going. A count nobody read is a dash, and no bar stands for it: not read is not none done.
  const r = state.run || { source: 'none' }, counted = r.total > 0, read = counted && r.done != null;
  $('#run-name').textContent = r.source === 'none' ? MAIN_WORDS.none : r.name;
  $('#run-count').textContent = counted ? MAIN_WORDS.count(whole(r.done), whole(r.total)) : r.done ? MAIN_WORDS.done(whole(r.done)) : '';
  show($('#run-track'), read);
  if (read) $('#run-fill').style.width = Math.min(100, r.done / r.total * 100).toFixed(1) + '%';
  $('#run-time').textContent = runTime(r, state.t);
}
function showTiles(state) {  // Paints every tile: the one line a Spark says about itself with its tone, and its three figures, a dash for what was not read.
  for (const n of state.nodes) {
    const t = tilesOf.get(n.name);
    if (!t) continue;
    const note = nodeNote(n, state.identity), figures = wallFigures(n);
    t.tile.classList.toggle('down', !n.live);
    t.note.textContent = t.note.title = note.text; t.note.className = note.cls;  // the title: a narrow tile cuts the end of a long line
    t.dot.style.setProperty('--tone', toneOf(note.cls));
    t.temp.value.textContent = figures.temp; t.fan.value.textContent = figures.fan; t.mem.value.textContent = figures.mem;
    t.fan.cell.classList.toggle('stopped', figures.stopped);
  }
}
function showFoot(state) {  // Writes the GPU power of the Sparks that were read, added up, with how many of them that is; a dash where none was read.
  const s = readSum(state.nodes, 'w');
  foot.sum.textContent = s.read ? MAIN_WORDS.watts(whole(s.sum)) : '–';
  foot.read.textContent = MAIN_WORDS.read(s.read, s.of);
}
function take(state) {  // Takes in a moment that arrived (it came through lensed) and shows it. One that is no news is passed over; one of another cluster starts the page anew, as on the main page.
  if (!wallNews(state.t, shownT)) return;
  if (shownT != null && cameAs !== clusterNames) return location.reload();  // ringtop came back on other machines: told by the names the server sent, not by the neutral ones
  if (shownT == null) { clusterNames = cameAs; buildTiles(state.cluster); }
  shownT = state.t; gotAt = Date.now();
  S = state;  // the faces read the moment on the page
  show($('#demo'), (state.identity || {}).demo === true);  // the sign of the demo, by the field the server sends
  showCore(state); showRun(state); showTiles(state); showFoot(state);
}
function watch() {  // Asked every second and with every word of the stream: says in the corner whether the page is live, marks a stale moment, and opens a stream anew that is stale or brings no first moment.
  const now = Date.now(), status = wallStatus(open, gotAt == null ? null : (now - gotAt) / 1000, S && S.identity.interval, (now - openedAt) / 1000), link = $('#link');
  link.lastElementChild.textContent = status.stale ? WALL_TEXTS.stale(clock(gotAt / 1000, true)) : status.word;
  link.firstElementChild.style.setProperty('--dot', status.on ? 'var(--teal)' : 'var(--amber)');
  $('#wall').classList.toggle('stale', status.stale);
  if (status.again) listen();
}
function listen() {  // Opens the stream of moments for a wall, in place of the one before. A word that is no moment of a cluster is passed over.
  if (stream) stream.close();
  openedAt = Date.now(); open = false;
  stream = new EventSource('api/wall');
  stream.onopen = () => { open = true; watch(); };
  stream.onmessage = e => { const state = JSON.parse(e.data); if (!MOMENT_PARTS.every(part => state[part] != null)) return; open = true; take(lensed(state)); watch(); };
  stream.onerror = () => { open = false; watch(); };
}
function start() {  // Starts the page: its fixed words, the switch for the names as a button and as the key H, the stream, and the watch every second and whenever the page is looked at again.
  const names = $('#names'), power = $('#power');
  names.textContent = WALL_TEXTS.names; names.title = WALL_TEXTS.namesTitle(NEUTRAL);
  names.setAttribute('aria-pressed', NEUTRAL);
  names.addEventListener('click', toggleNames);
  addEventListener('keydown', e => { if (!(e.metaKey || e.ctrlKey || e.altKey) && (e.key === 'h' || e.key === 'H')) toggleNames(); });
  $('#core-unit').textContent = MAIN_WORDS.unit;
  make('span', '', power, MAIN_WORDS.power);
  Object.assign(foot, { sum: make('strong', '', power, '–'), read: make('small', '', power) });
  $('#about').textContent = MAIN_WORDS.neutral; show($('#about'), NEUTRAL);
  listen();
  setInterval(watch, 1000);
  document.addEventListener('visibilitychange', watch);  // a phone that wakes up: its timers stood still, and so did its stream
}
start();
