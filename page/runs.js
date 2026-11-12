// The runs view: the card of one run with its four figures and a button that saves its picture, the stations of its queue, and every run that was recorded as a list to pick from.
'use strict';
/* A drawing (SVG as text) as a PNG file in memory, drawn by the browser itself, `dense` times as dense as the drawing is large. Nothing
   leaves the page: the image reads the drawing from an address that holds all of it. Fails where the browser cannot read the drawing or
   make a file of it. */
function pngOf(svg, width, height, dense) {
  return new Promise((done, failed) => {
    const image = make('img'), canvas = make('canvas');
    canvas.width = width * dense; canvas.height = height * dense;
    image.onerror = () => failed(new Error('the drawing could not be read'));
    image.onload = () => {
      try {
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(file => file ? done(file) : failed(new Error('no file came of the picture')), 'image/png');
      } catch (problem) { failed(problem); }
    };
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  });
}
const Runs = (() => {
  const el = $('#panel'), T = RUN_TEXTS, AGAIN = 10, FIRST = 6;  // AGAIN: the seconds after which the records are asked for again while the view is open. FIRST: the lines the list shows before it is asked for all
  const SPEED = 'engine.tok_s', COLUMNS = 268;  // the trace the curve of a picture is drawn from, and how many columns of it are asked for: one for every 4 units of the 1072 the curve is wide
  let ui = null, got = null, picked = null, asked = 0, askedAt = 0, told = '', whole = false;  // got: the records as they came; picked: the id of the run on the card, if one was picked; askedAt: the moment they were last asked for; told: why they did not come; whole: the list shows every run
  let saving = false, trouble = '';  // saving: a picture is being made; trouble: what the card says since one could not be made
  const now = () => (LIVE || S).t;  // The newest moment that arrived: a run that is open runs up to now, whatever moment the page looks back at.
  const all = () => got ? [...(got.open ? [got.open] : []), ...got.runs] : [];  // Every run that came, the open one first, then the one that ended last.
  const shown = () => { const list = all(); return list.find(r => r.id === picked) || list[0] || null; };  // The run on the card: the one picked from the list, else the open one, else the one that ended last.
  const silence = () => Math.max(15, 4 * S.identity.interval);  // How far apart two samples of a Spark may lie before the server counts a gap, as the server sets it.
  function texts() {  // What the box of the bar shows, as titled paragraphs: what the record says of this run beside its figures and the notes not in sight, then what a run is and how each figure is counted.
    const r = shown(), run = r ? `${figureNotes(runFigures(r, now()).filter(f => f.note))} ${runFacts(r, now(), NEUTRAL)}`.trim() : '';  // a figure without a note has nothing to add; with neutral names the box names no model and no image
    return [[T.titles.run, run], [T.titles.what, T.what], [T.titles.duration, T.durationOf], [T.titles.speed, T.speedOf],
      [T.titles.tokens, T.tokensOf(figure(S.identity.interval, S.identity.interval % 1 ? 1 : 0))], [T.titles.energy, T.energyOf(figure(S.identity.interval, S.identity.interval % 1 ? 1 : 0), figure(silence()))], [T.titles.kept, T.kept]];
  }
  function build() {  // Builds the view, once per opening: the head with the run and its state, what cannot wait, the four figures, the bar with the box, and the places of the stations and of the list.
    el.textContent = ''; el.classList.add('record', 'calm', 'narrow', 'runs');
    const head = make('div', 'sp-head', el), line = make('div', 'sp-title', head);
    ui = { name: make('h2', '', line), tag: make('span', 'sp-tag', line), note: make('p', 'cool-alarm', head) };
    const figs = make('div', 'sp-figs', head);
    ui.figs = [0, 1, 2, 3].map(() => { const f = make('div', 'sp-fig', figs), top = make('div', '', f); return { f, value: make('strong', '', top), unit: make('span', '', top), what: make('b', '', f), note: make('p', '', f) }; });
    ui.bar = make('div', 'sp-bar q-bar', el);
    ui.save = button(ui.bar, 'run-save', T.save, save); ui.save.title = T.saveTitle;
    const ticks = make('span', 'run-ticks', ui.bar);
    ui.real = NEUTRAL ? null : choice(ticks, T.realName); ui.model = choice(ticks, T.withModel);  // with neutral names the page never held the name of the run: there is nothing to tick
    ui.shut = makeInfo(ui.bar, { texts, info: T.info, about: T.about });
    ui.list = make('section', 'sp-part', el);  // the list first: a long queue has more stations than the panel has room for
    ui.queue = make('section', 'sp-part', el);
  }
  function paintCard() {  // Writes the card of the run that is shown: its name and state, what happened to it, and its four figures. A figure says its note only while it carries a state; the other notes wait in the box. Without a run it says that there is none, or why the records did not come.
    const r = shown();
    show(ui.figs[0].f.parentNode, !!r); show(ui.bar, !!r);
    if (!r) { ui.name.textContent = T.none; ui.tag.textContent = ''; ui.note.textContent = told || T.empty; return; }
    const figs = runFigures(r, now());
    ui.name.textContent = r.name; ui.tag.textContent = runState(r);
    ui.note.textContent = [told, trouble, ...runNotes(r, now())].filter(Boolean).join(' ');
    figs.forEach((fig, k) => { const u = ui.figs[k]; u.value.textContent = fig.value; u.unit.textContent = fig.unit; u.what.textContent = fig.what; u.note.textContent = urgentNote(fig); u.f.title = fig.note; u.f.dataset.state = fig.state; });
  }
  function stationsOf(r) {  // The stations of the queue of a run: as the moment on the page names them while it shows this run, else as the record last held them.
    const live = S.run || {}, same = r.open && live.name === r.name && Array.isArray(live.steps);
    return same ? live.steps : r.steps || [];
  }
  function paintQueue() {  // The stations of the queue the run on the card belongs to, each with the time it took against the time before; for the run that is running, who holds the ring and when the queue is likely to end.
    const r = shown(), steps = r ? stationsOf(r) : [], live = r && r.open && !S.past ? S.run || {} : {};
    ui.queue.textContent = '';
    show(ui.queue, steps.length > 0);
    if (!steps.length) return;
    make('h3', '', make('div', 'sp-h', ui.queue), T.stations);
    const bits = [r.group, live.holder && `held by ${live.holder}`, live.until].filter(Boolean);
    if (bits.length) make('p', 'p-note', ui.queue, bits.join(', '));
    const left = r.open && !S.past ? queueLeft(steps, live, S.t) : 0;  // only the queue that is running has an end ahead of it
    if (left > 0) make('p', 'p-note', ui.queue, `The queue ends around ${clock(S.t + left)}, estimated`);
    for (const s of steps) {
      const row = make('div', 'step ' + (s.state || ''), ui.queue);
      make('div', '', row, s.name || '');
      const timed = typeof s.seconds === 'number';  // 0 s is a time that was read; a time nobody read, or a text in its place, is none
      const when = make('span', '', row, timed ? span(s.seconds) : s.state === 'running' ? 'now' : s.state === 'failed' ? 'failed' : '');
      const change = timed && s.was ? (s.seconds - s.was) / s.was : 0;  // against a time before of 0 there is no change to tell
      if (Math.abs(change) >= .05) make('em', change > 0 ? 'up' : 'down', when, `${change > 0 ? '+' : ''}${Math.round(change * 100)} %`);
    }
  }
  function paintList() {  // The runs that were recorded as lines to click, the open one first: of each its name, when it began and its state, and its four figures in short. A click puts that run on the card. The newest few stand there; a button brings all that came.
    const list = all(), on = shown();
    ui.list.textContent = '';
    show(ui.list, list.length > 0);
    if (!list.length) return;
    make('h3', '', make('div', 'sp-h', ui.list), T.list);
    const rows = make('ul', 'run-list', ui.list);
    for (const r of whole ? list : list.slice(0, FIRST)) {
      const line = runLine(r, now()), b = button(make('li', '', rows), '', '', () => { picked = r.id; paint(); el.scrollTop = 0; });
      b.title = T.show; b.setAttribute('aria-current', String(!!on && on.id === r.id));
      make('b', '', b, line.name); make('span', '', b, `${line.when}, ${line.state}`);
      make('i', '', b, [line.duration, line.speed, line.tokens, line.energy].join(' · '));
    }
    if (list.length > FIRST) button(ui.list, 'run-more', whole ? T.fewer : T.more(list.length), () => { whole = !whole; paintList(); });
  }
  function paint() {  // Writes the whole view from the records that came.
    paintCard(); paintQueue(); paintList();
  }
  async function load() {  // Asks the server for the records of runs and shows them; with neutral names they come without the words of their source. An answer a newer question has overtaken is dropped; where none comes, the view keeps what it shows and says why.
    const id = ++asked;
    askedAt = now();
    try {
      const res = await fetch('api/runs?limit=50');
      if (!res.ok) throw new Error(`status ${res.status}`);
      const answer = await res.json();
      if (id !== asked || !ui) return;
      if (!answer || !Array.isArray(answer.runs)) throw new Error('its answer holds no runs');  // an error said as JSON would be drawn as a list of none
      got = NEUTRAL ? neutralRuns(answer, renamer(renames)) : answer; told = '';  // what stays of a record as text passes the renamer of the moment: the Sparks, and what they work on
    } catch (problem) {
      if (id !== asked || !ui) return;
      told = T.failed(problem.message || problem);
    }
    paint();
  }
  function tick() {  // With every moment while the view is open: the card and the stations follow it (an open run goes on), and the records are asked for again once those on the page are AGAIN seconds old.
    if (!ui) return;
    if (now() - askedAt >= AGAIN) load(); else { paintCard(); paintQueue(); }
  }
  function open() {  // Opens the view on the panel; it is built once and follows the moment by itself.
    if (ui) return;
    build(); paint(); load();
  }
  function close() {  // Leaves the panel to the other views: the box of the bar is shut and whatever is still on its way is dropped. The run that was picked is not kept: the view opens on the run of now.
    if (!ui) return;
    ui.shut();
    ui = null; asked++; picked = null; whole = false; trouble = '';
    el.classList.remove('record', 'calm', 'narrow', 'runs'); el.textContent = '';
  }
  function choice(parent, word) {  // A box to tick with its word beside it, not ticked. Gives back the box.
    const label = make('label', '', parent), box = make('input', '', label);
    box.type = 'checkbox'; box.checked = false;
    make('span', '', label, word);
    return box;
  }
  async function speedOf(r, at) {  // The speed of the ring engine over a run for the curve of its picture, from the history the page has: the means of so many columns from its beginning to its end. null where the history gives no stretch: the picture is then drawn without its curve.
    const from = runBegan(r), to = runEnd(r, at) ?? r.last_heard;
    try {
      const answer = await askHistory([SPEED], from, to, COLUMNS, true);
      return { t: answer.t, v: answer.series[SPEED] || [], gap: gapOf(answer.width || (to - from) / COLUMNS, answer.tier, S.identity.interval) };
    } catch { return null; }
  }
  async function picture(opt = {}, r = shown()) {  // The picture of a run, of the one on the card unless told, as a PNG file in memory, twice as dense as it is large (runPicture, pngOf). opt: real (with the name of the run), model (with the model). The Sparks go by their neutral names whatever the page shows: with neutral names the record carries them already (load), and they are not renamed a second time.
    const at = now(), cluster = (LIVE || S).cluster;
    const svg = runPicture(r, { ...opt, now: at, trace: await speedOf(r, at), pairs: NEUTRAL ? [] : aliasPairs(cluster), ring: !!cluster.ring });
    return pngOf(svg, PICTURE.width, PICTURE.height, 2);
  }
  function hand(file, name) {  // Hands a file to the browser to save under a name: a link with `download`, clicked once. The address the file got is given up a minute later, when the browser has read it.
    const link = make('a', '', document.body), address = URL.createObjectURL(file);
    link.href = address; link.download = name;
    link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(address), 60000);
  }
  async function save() {  // Saves the picture of the run on the card as a PNG file: with the name of the run and with the model only where their boxes are ticked, and a tick holds for one picture. One picture at a time. Where none could be made, the card says so until one is saved.
    const mine = ui, r = shown();
    if (!r || saving) return;
    const opt = { real: !!ui.real && ui.real.checked, model: ui.model.checked };
    saving = true; ui.save.disabled = true;
    try { hand(await picture(opt, r), pictureFile(r)); trouble = ''; } catch { trouble = T.saveFailed; }
    saving = false;
    if (ui !== mine) return;  // the view was left while the picture was made
    ui.save.disabled = false; ui.model.checked = false;
    if (ui.real) ui.real.checked = false;
    paintCard();
  }
  return { open, close, tick, isOpen: () => !!ui, shown, picture };
})();
