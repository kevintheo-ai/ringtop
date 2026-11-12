// The board a view with curves stands on: one stretch of time for all its plots, the cursor and the two marks they share, a drag that zooms in, and the questions to the history.
'use strict';
/* Makes the board of one view. hosts: the elements its plots stand in. The board listens on each of them, so one cursor reads every plot, wherever on the page it stands.
   use: what the view gives it. callout: whether the plot under the pointer says the moment of the cursor. open(): whether the view is open. keys(): the keys of the history its plots are drawn from. room(): how wide one of its curves is, in pixels.
   drawn(): draws the view from the stretch that was loaded. read(): writes what follows the cursor and the marks. failed(problem): says that the history did not answer.
   span: the seconds its stretch covers at first. Gives back what the view reads (got, hover, marks, span, end) and what it does to them. */
function makeBoard(hosts, use, span) {
  const plots = new Map();  // every plot of the board by its drawing, so a pointer finds the plot it is on
  let end = null, got = null, asked = 0, askedAt = 0, out = false, hover = null, pointer = null, marks = [], drag = null;  // out: a question to the history is on its way. pointer: the plot the pointer rests on and where, so the cursor can stay under it

  const goal = () => Math.min(end ?? S.t, S.t);  // Where the stretch ends: at the end the reader zoomed to, else at the moment on the page, and never after that moment.
  const shown = () => marks.map(t => snapTo(got.t, t, got.reach));  // The marks where they stand: each on the point of the curves it was set on. They are kept as they were set, so a stretch that moves on does not carry them off step by step.
  const stretch = () => { const at = shown(); return at.length === 2 ? [Math.min(...at), Math.max(...at)] : [null, null]; };  // The stretch between the two marks, from point to point, or all of it.
  const view = more => ({ from: got.from, to: got.to, t: got.t, gap: got.gap, width: got.width, reach: got.reach, ...more });  // What every plot of the board is drawn from: the stretch that was loaded, and what this plot shows of it.
  const when = (t, first) => timeWord(t, got && got.width < 60 ? 1 : 60, first);  // A moment in words, to the second where the columns are finer than a minute.
  const fromTo = (a, b, now) => `${when(a, true)} to ${now ? 'now' : when(b, !sameDay(a, b))}`;  // A stretch of time in words: the day on its end only where that is another day.
  const busy = on => { for (const host of hosts) host.classList.toggle('loading', on); };  // Shows on every element of the board that a question to the history is out.
  function paintMarks() {  // Shows the marks on every plot and lets the view write what follows them.
    const at = shown();
    for (const p of plots.values()) p.select(at[0], at[1]);
    use.read();
  }
  let spoke = null;  // the plot that says the moment of the cursor
  const speak = () => { spoke = use.callout && hover != null && pointer ? pointer.plot : null; if (use.callout) for (const p of plots.values()) p.say(p === spoke ? when(hover, true) : ''); };  // callout: the plot the pointer is on says which moment the cursor reads, where no bar does
  function paint() {  // Draws the whole view from the stretch that was loaded, and puts cursor and marks back onto it.
    use.drawn();
    if (pointer) hover = pointer.plot.timeAt(pointer.x);  // the cursor stays under the pointer: after a zoom, or once the stretch has moved on, that is another moment
    paintMarks();
    for (const p of plots.values()) p.cursor(hover);
    speak();  // and the word beside it says the moment it reads now, not the one from before
  }
  function setHover(t) {  // Moves the cursor of every plot to one moment, or takes it away, and lets the view read there. The same moment on another plot is a move too: the word that says it goes with the pointer.
    if (!got || (t === hover && (use.callout && t != null && pointer ? pointer.plot : null) === spoke)) return;
    hover = t;
    for (const p of plots.values()) p.cursor(t);
    speak();
    use.read();
  }
  function mark(t) {  // Sets a mark at a moment: the first, the second, and a third click starts over.
    if (t == null) return;
    marks = marks.length >= 2 ? [t] : [...marks, t];
    paintMarks();
  }
  function setMarks(list) {  // Puts the marks where a view wants them: on a stretch it names, or nowhere.
    marks = list;
    paintMarks();
  }
  function zoom(a, b) {  // Makes a stretch of the board the whole board; no shorter than a handful of readings, and never past the moment on the page.
    if (a == null || b == null) return;
    ({ span, end } = zoomTo(a, b, 6 * S.identity.interval, S.t)); marks = [];
    load();
  }
  function pick(seconds) {  // Shows the last so many seconds up to the moment on the page: a new stretch, without the marks of the old one.
    span = seconds; end = null; marks = [];
    load();
  }
  const plotAt = e => { const svg = e.target && e.target.closest ? e.target.closest('svg.plot') : null; return svg ? plots.get(svg) : null; };  // The plot a pointer is on, if any.
  function dragged(type, e, t) {  // One step of the drag (dragStep): keeps what is left of it, shades the stretch it spans, and gives back what the board has to do. A drag that was dropped hands its shade back to the marks.
    const was = drag, step = dragStep(drag, { type, x: e.clientX, t, main: e.button === 0, held: (e.buttons & 1) === 1 });
    drag = step.drag;
    if (drag && drag.to != null) for (const p of plots.values()) p.select(drag.from, drag.to);
    else if (was && was.to != null && !step.act && got) paintMarks();
    return step.act;
  }
  function wire() {  // Listens on every element of the board, once: the pointer moves the cursor, a click sets a mark, a drag zooms in, and a new width redraws. And on the page for a button that comes up anywhere else.
    const resized = new ResizeObserver(() => { if (use.open() && got) requestAnimationFrame(() => { if (use.open() && got) paint(); }); });
    for (const host of hosts) {
      host.addEventListener('pointermove', e => {
        const p = plotAt(e), t = p ? p.timeAt(e.clientX) : null;
        pointer = p ? { plot: p, x: e.clientX } : null;
        dragged('move', e, t);
        setHover(t);
      });
      host.addEventListener('pointerleave', () => { pointer = null; setHover(null); });
      host.addEventListener('pointerdown', e => { const p = plotAt(e); dragged('down', e, p ? p.timeAt(e.clientX) : null); });
      host.addEventListener('pointerup', e => { const act = dragged('up', e, null); if (act) (act[0] === 'mark' ? mark(act[1]) : zoom(act[1], act[2])); });
      host.addEventListener('pointercancel', e => dragged('cancel', e, null));
      resized.observe(host);
    }
    for (const type of ['pointerup', 'pointercancel']) addEventListener(type, e => { if (drag) dragged('cancel', e, null); });  // the button comes up off the board, where the board does not hear it: the drag ends out there. A release on the board came by its own listener first and left no drag
  }
  async function load() {  // Asks the history for the stretch on the board and draws it. An answer a newer question has overtaken is dropped; while one is out, the view keeps what it shows.
    const id = ++asked, to = goal(), from = to - span, points = Math.round(clamp(use.room() || 360, 120, 720)), keys = use.keys(), live = end == null && !S.past, zoomed = end != null;  // live: this stretch was asked for up to now. zoomed: it was asked for with an end of its own
    askedAt = Date.now(); out = true; busy(true);
    try {
      const answer = await askHistory(keys, from, to, points, true);
      if (id !== asked || !use.open()) return;
      got = { ...answer, from, to, live, zoomed, width: answer.width || (to - from) / points };  // what is shown says itself whether it runs to now and whether it was zoomed to: the board may already be heading elsewhere
      got.step = stepOf(got.tier, S.identity.interval); got.reach = columnReach(got.width, got.tier, S.identity.interval); got.gap = gapOf(got.width, got.tier, S.identity.interval);
      marks = marksWithin(marks, from, to);
      paint();
    } catch (problem) {
      if (id !== asked || !use.open()) return;
      if (got) paintMarks();  // the curves keep the stretch they show: the marks a new choice dropped and the shade of the drag that asked go from them, so they and the figures say the same
      use.failed(problem);
    } finally {
      if (id === asked) { out = false; busy(false); }
    }
  }
  function tick() {  // With every moment while the view is open: the stretch is asked for again once it has moved on and no question is out (mayAsk).
    if (mayAsk({ out: out ? (Date.now() - askedAt) / 1000 : null, to: got ? got.to : null, width: got ? got.width : 0, at: goal(), past: !!S.past })) load();
  }
  function reset() {  // Empties the board for a view that opens or closes: no stretch, no plot, no cursor, no mark, and whatever is still on its way is dropped. The span and the end of its stretch stay, so the next view starts on the same stretch of time.
    got = null; asked++; out = false; hover = null; pointer = null; spoke = null; drag = null; marks = [];
    plots.clear(); busy(false);
  }
  wire();
  return {
    get got() { return got; }, get hover() { return hover; }, get marks() { return marks; }, get span() { return span; }, get end() { return end; },
    add: plot => { plots.set(plot.svg, plot); return plot; }, view, shown, stretch, when, fromTo, mark, setMarks, zoom, pick, load, tick, reset,
  };
}
function button(parent, cls, text, act) {  // A button that does one thing.
  const b = make('button', cls, parent, text);
  b.type = 'button';
  b.addEventListener('click', act);
  return b;
}
let shutBox = null;  // closes the box that explains what a calm bar shows, while one stands open: one at a time on the whole page, and Escape asks here first (hover.js)
addEventListener('pointerdown', e => { if (shutBox && !(e.target.closest && e.target.closest('.q-pop,.q-info'))) shutBox(); });  // a press anywhere but on the box or its button closes it
/* What a calm bar explains, kept in a box behind a small button: titled paragraphs under the bar, filled whenever it opens with what holds at that moment and no taller than the room under the bar.
   It closes by its button, by Escape and by a press anywhere else. words: texts() (the paragraphs as pairs of title and text; one without a text is left out), info (what the button says of itself), about (its name for a screen reader). */
function makeInfo(bar, words) {
  const pop = make('div', 'q-pop', bar), b = button(bar, 'q-info', 'i', () => set(pop.hidden)), shut = () => set(false);
  function set(open) {  // Opens the box with what holds at this moment, or closes it, and lets the page know whether it stands open. A box that opens shuts the one that stood open: one at a time on the whole page.
    if (open && shutBox && shutBox !== shut) shutBox();
    pop.hidden = !open; b.setAttribute('aria-expanded', String(open));
    shutBox = open ? shut : shutBox === shut ? null : shutBox;
    if (!open) return;
    pop.style.maxHeight = `${Math.max(140, bar.parentElement.getBoundingClientRect().bottom - bar.getBoundingClientRect().bottom - 22)}px`;  // what is longer scrolls inside the box
    pop.textContent = '';
    for (const [title, text] of words.texts()) if (text) { make('h4', '', pop, title); make('p', '', pop, text); }
  }
  b.title = words.info; b.setAttribute('aria-label', words.about);
  shut();
  return shut;
}
/* The calm bar of a board: the stretch of time as one switch, and a button that shows the four figures of every curve or hides them. What the marks say, a stretch that was zoomed to,
   and what the view adds about its own recording stand on a strip under it, there only while one of them is; a failure it was told of stands there in front of them until the history answers again.
   parent: the element of the view that scrolls; the bar sticks to its top, and keeps room in it for the strip while the strip stands (place).
   root: the element of the view; it carries "figures" while the figures are asked for or a stretch is marked. windows: the stretches to pick from, each a word and its seconds. late(): what the view adds about its own recording, a sentence or nothing. words: what the buttons say of themselves (figures), and with texts() a second button that explains (makeInfo).
   Gives back paint(), say(text) and shut(), which closes what the bar explains: a view that leaves calls it. */
function makeQuietBar(board, parent, root, windows, late, words) {
  const bar = make('div', 'sp-bar q-bar', parent), seg = make('div', 'q-seg', bar), wins = windows.map(([word, secs]) => button(seg, '', word, () => board.pick(secs)));
  const fig = button(bar, 'q-fig', 'Figures', () => { figures = !figures; paint(); });
  const shut = words.texts ? makeInfo(bar, words) : () => {};
  const strip = make('div', 'q-strip', bar), said = make('p', '', strip), room = make('div', 'q-room', parent);  // the strip hangs under the bar; the room is the place in the flow it then lies over, empty and as tall as the strip
  const zoom = button(strip, '', 'Zoom', () => board.zoom(...board.stretch())), clear = button(strip, '', 'Clear', () => board.setMarks([])), now = button(strip, 'q-now', 'Back to now', () => board.pick(board.span));
  let figures = false, told = '', shown = null, kept = 0;  // told: a failure the view reported, and the stretch that was shown then. kept: how tall the room for the strip is
  fig.title = words.figures;
  show(strip, false);
  for (const b of [zoom, clear, now]) show(b, false);  // before the first stretch is here there is nothing to mark on and nothing to go back from: a failure that is said then stands alone, and paint brings the buttons
  function place() {  // Shows the strip while it has something to say and keeps room for it under the bar: what stands right under the bar is not under the strip. Where the bar stands by itself (the page is at its top), what follows moves down while the strip stands. Where the bar sticks to the top of what scrolls, the page is scrolled by as much as what follows moved, so nothing a reader looks at moves when the strip comes or goes; that is measured, not reckoned: a browser that anchors the scroll by itself has moved nothing.
    show(strip, !!said.textContent);
    const tall = strip.hidden ? 0 : Math.ceil(strip.getBoundingClientRect().height);
    if (tall === kept) return;
    const stuck = bar.getBoundingClientRect().bottom > room.getBoundingClientRect().top + .5, before = room.getBoundingClientRect().bottom;
    room.style.height = `${kept = tall}px`;
    if (stuck) parent.scrollTop += room.getBoundingClientRect().bottom - before;
  }
  function paint() {  // Writes the bar: which stretch is picked and whether the figures of every curve show; and the strip: a failure for as long as it holds, else what the marks say, else the stretch that was zoomed to, else what the view adds.
    const { got, end, span, marks, when, fromTo } = board, [a, b] = board.stretch();
    if (!got) return;
    if (got !== shown) { told = ''; shown = got; }
    wins.forEach((w, k) => w.setAttribute('aria-pressed', String(end == null && windows[k][1] === span)));
    show(now, end != null); show(zoom, a != null && b > a); show(clear, marks.length > 0);
    fig.setAttribute('aria-pressed', String(figures || a != null)); fig.disabled = a != null;
    root.classList.toggle('figures', figures || a != null);
    said.textContent = told || marksWord(a, b, marks.length ? board.shown()[0] : null, { stretch: (x, y) => fromTo(x, y), at: t => when(t, true) })  // the failure in front, as say() puts it: the view no longer keeps up, whatever is marked; the marks stay on the curves, and their buttons beside it
      || (got.zoomed ? `${fromTo(got.from, got.to, false)}, ${lengthWord(got.to - got.from)}` : '') || late().trim();  // zoomed: of the stretch that is shown, not of where the board is heading
    place();
  }
  return { paint, shut, say: text => { told = text; shown = board.got; said.textContent = text; place(); } };
}
/* One reading as a row on a board: its name, its value and what that value is, a note, its plot and the four figures of the stretch.
   opt: how its plot is made, with the digits the row is read to. Gives back the parts a view writes into; the view gives the row its trace. */
function makeRow(board, parent, word, unit, opt) {
  const box = make('div', 'ch' + (opt.tall ? ' tall' : ''), parent), id = make('div', 'ch-id', box);
  make('b', '', id, word);
  const val = make('div', 'ch-val', box), value = make('strong', '', val), tag = make('span', '', val), note = make('p', 'ch-note', box), host = make('div', 'ch-plot', box), stat = make('dl', 'ch-stat', box), cells = {};
  for (const k of ['mean', 'min', 'max', 'n']) { const d = make('div', '', stat); cells[k + 'Word'] = make('dt', '', d, k); cells[k] = make('dd', '', d); }
  return { box, id, word, unit, digits: opt.digits || 0, opt, value, tag, note, cells, plot: board.add(makePlot(host, { ...opt, word: unit ? `${word}, ${unit}` : word })), trace: null };
}
/* Writes the value of a row and the figures of its stretch from its trace. The value is the point under the cursor while one stands on the board (none in a hole), else the newest
   reading the view hands in, else the last point of the stretch; beside it stands its unit, and what it is only where a reader would not expect it (quietWord); the figures cover the marked stretch, else all of it. Gives back the value shown. */
function rowFigures(board, row, newest) {
  const { got, hover, when } = board, [a, b] = board.stretch(), on = hover != null, st = stretchStats(row.trace, a, b), shown = shownValue(row.trace.mean, on ? columnAt(got.t, hover, got.reach) : -1, on, newest);
  row.value.textContent = figure(shown.v, row.digits);
  row.tag.textContent = quietWord(shown.what, row.unit, shown.what === 'last' ? `last point, ${when(got.t[shown.at], !sameDay(got.t[shown.at], got.to))}` : '');  // a point is the mean of its column: not a reading "at" a time
  row.cells.mean.textContent = figure(st.mean, row.opt.means ?? row.digits);
  row.cells.min.textContent = figure(st.min, row.digits); row.cells.minWord.textContent = st.bound && st.n ? 'min ≤' : 'min';
  row.cells.minWord.title = st.bound && st.n ? 'The lowest reading was not kept for every minute of this stretch: the true minimum is no higher than this.' : '';
  row.cells.max.textContent = figure(st.max, row.digits);
  row.cells.n.textContent = figure(st.n); row.cells.nWord.textContent = got.tier === 'minute' ? 'minutes' : 'readings';
  return shown;
}
