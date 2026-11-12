// The panel of what is running: the run, how far it is, and the Sparks that work through jobs of their own.
'use strict';
/* ---- what is running ---- */
let lastRun;
function renderRun(state) {  // Shows the run of this moment; when another run takes over, the scene marks the lap and the panel fades to it.
  const r = state.run || { source: 'none' };
  const id = r.source + '|' + (r.name || '');
  const lap = lastRun !== undefined && id !== lastRun;
  if (lap) Scene.lap();
  faded(() => paintRun(r, state.t), lap);  // every painting goes this way: one that still waits for its fading is made before the next, never after it
  lastRun = id;
}
const TRACK_ROOM = 4;  // lines the run panel has for tracks before it would push the numbers below out of a small window
function paintTracks(r) {  // one line per Spark that works through jobs of its own: Spark, job, how far. Gives back how many there are
  const all = trackRows(r.tracks, S ? S.nodes : []), { rows, more } = tracksShown(all, TRACK_ROOM), list = $('#run-tracks');
  show(list, rows.length > 0);
  if (more) list.dataset.more = `and ${more} more`; else delete list.dataset.more;
  while (list.children.length > rows.length) list.lastChild.remove();
  while (list.children.length < rows.length) { const li = make('li', '', list); for (const tag of ['b', 'span', 'em', 'i']) make(tag, '', li); }
  rows.forEach((row, k) => {
    const [name, job, count, bar] = list.children[k].children, share = trackShare(row);
    name.textContent = row.node || row.model || 'track';
    job.textContent = job.title = row.name || '';
    count.textContent = trackCount(row);
    bar.style.width = share == null ? '0' : (share * 100).toFixed(1) + '%';
  });
  return all.length;
}
function paintSteps(r) {  // the steps of a queue as dots, and the line that says where it stands
  const steps = r.steps || [], box = $('#stations'), key = steps.map(s => s.name).join('\u0000');
  show(box, steps.length > 1);
  if (box.dataset.key !== key) { box.dataset.key = key; box.textContent = ''; steps.forEach(() => make('li', '', box)); }
  steps.forEach((s, i) => {
    const li = box.children[i], words = s.state === 'running' ? 'running now' : s.state === 'failed' ? 'failed' : s.state === 'done' ? 'done' : 'waiting';
    li.dataset.state = s.state;
    li.title = `${s.name}: ${words}${typeof s.seconds === 'number' ? ', ' + span(s.seconds) : ''}`;  // 0 s is a time too
  });
  const done = steps.filter(s => s.state === 'done' || s.state === 'failed').length, next = steps.find(s => s.state === 'pending');
  const line = steps.length > 1 ? `${r.group ? r.group + ': ' : ''}step ${Math.min(done + 1, steps.length)} of ${steps.length}${next ? ', next ' + next.name : ''}` : '';
  $('#run-next').textContent = line;
  show($('#run-next'), !!line);
  $('#now').classList.toggle('can', steps.length > 1);
}
function paintRun(r, now) {  // Writes the run panel: name, count, bar, time, who holds the cluster, tracks, steps and detail. A count nobody read is a dash, and no bar stands for it: not read is not none done.
  const counted = r.total > 0, read = counted && r.done != null, tracks = paintTracks(r), time = runTime(r, now);
  const hold = r.holder ? `held by ${r.holder}${r.until ? ', ' + r.until : ''}` : '';
  const joined = tracks > 0 && hold && time ? `${time}, ${hold}` : '';  // with a line per Spark the panel has room for one more line only: who holds the cluster joins the time
  $('#run-name').textContent = r.source === 'none' ? 'Nothing running' : r.name;
  $('#run-count').textContent = counted ? `${whole(r.done)} of ${whole(r.total)}` : r.done ? `${whole(r.done)} done` : tracks ? `${tracks} track${tracks === 1 ? '' : 's'}` : '';
  show($('#run-track'), read);
  if (read) $('#run-fill').style.width = Math.min(100, r.done / r.total * 100).toFixed(1) + '%';
  $('#run-time').textContent = $('#run-time').title = joined || time;
  $('#run-hold').textContent = hold && hold[0].toUpperCase() + hold.slice(1);
  show($('#run-hold'), !!hold && !joined);
  $('#now').classList.toggle('tracks', tracks > 0);
  paintSteps(r);
  $('#run-detail').textContent = r.detail || '';
  show($('#run-detail'), !!r.detail);
}

