// The cooling view: the fans and the warmest sensor of every Spark over a stretch of time anybody can pick, where fans ran slower than the others, and fan speed against warmth.
'use strict';
const Cooling = (() => {
  const el = $('#panel'), WINDOWS = [['30 min', 1800], ['2 h', 7200], ['24 h', 86400], ['2 d', 172800], ['7 d', 604800], ['30 d', 2592000]];
  const KINDS = [['fan', 'Fans', 'RPM'], ['heat', 'Warmest sensor', '°C']];
  /* Every sentence of the view that explains, in one place: the paragraphs of the box behind the "i" of the bar (titles: their headings, in the order they stand), the rule of each reading,
     and what the buttons and signs say of themselves. The view shows name, value, unit, state and curve; these words wait until somebody asks. */
  const TEXTS = {
    titles: { now: 'Now', then: 'At this moment', stretch: 'Time range', reading: 'Reading the curves', fan: 'Fans', heat: 'Warmest sensor', scale: 'Scale', picture: 'Fan speed vs. warmest sensor', setter: 'Fan control' },
    stretch: (span, length, point, late) => `${span} (${length}). Each point: ${point}.${late}`,
    noFans: ' No fan readings in this range.',
    begins: when => ` Recording begins ${when}.`,
    reading: 'Move the pointer over a curve to read one moment on every curve. Click to set a mark. A second click sets another, and the figures then cover the range between them. Drag across a curve to zoom, down to six sampling intervals (12 s at the default 2 s). Data older than 2 days resolves to one-minute points at best.',
    fan: 'Mean of both fans; no per-fan history. Dashed: 15 % below the lower median of the other Sparks. Foot: fans below the dashed line while the warmest sensor is at most 1.5 °C cooler than the others\' lower median. Both need readings from at least two other Sparks.',
    heat: 'Per point, the higher of the board\'s hottest thermal zone and the GPU temperature. Band: higher of the two lowest readings to higher of the two highest.',
    scale: 'All Sparks share one scale per quantity. It spans every mean and, for fans, the dashed line. Bands beyond it are clipped, so a single outlier (a fan sample read as 0, say) does not flatten the curves. The min and max figures state the true values.',
    dots: (which, small) => `Large dots: ${which}. Small dots: every point of ${small}.`,
    dot: { cursor: when => `one per Spark, reading at the cursor (${when}). Amber: a Spark whose fans count as slower at that point`, marked: 'one per Spark, mean over the marked range. Amber: a Spark with a period flagged Slower overlapping the range', now: 'one per Spark, live reading. Amber: a Spark whose fans count as slower now, or with one fan at 0 RPM while the other turns', then: 'one per Spark, reading at this moment. Amber: a Spark whose fans count as slower at this moment' },
    small: { marked: 'the marked range', all: 'the time range above' },
    setBy: who => `Fan speed is set by ${who}`,
    every: ' (read from the Linux kernel cooling devices every 60 s).',
    never: 'Ringtop reads fan speeds and never sets them.',
    figures: 'mean, min, max and the number of minutes or readings behind them, for every curve over the whole range or the marked range',
    info: 'Definitions and sampling',
    about: 'Measurement notes',
    slower: 'Fans below the dashed line while the warmest sensor is at most 1.5 °C cooler than the others\' lower median',
    wide: 'Wide view',
    beside: 'Narrow view beside the ring',
    page: 'Open this Spark\'s page',
    mark: 'Click to set both marks to this period, on every curve.',
    failed: problem => `History request failed: ${problem}.`,
    nothing: 'No fan or temperature data to plot.',
    fansNow: each => `Its fans now: ${each} RPM.`,
    warmNow: zone => `Warmest sensor now: ${zone}.`,
    more: (name, n) => `${name}: ${n} more earlier period${n === 1 ? '' : 's'} flagged Slower.`,
  };
  const SIGNS = { wide: 'M9.5 2v4.5H14M9.5 6.5l4-4M6.5 14V9.5H2M6.5 9.5l-4 4', narrow: 'M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9' };  // the sign on the button that changes the form: arrows inwards while the view is wide, outwards while it stands beside the ring
  let ui = null, wide = wideAsked(location.search);  // wide: the form of the view. It opens beside the ring unless the address asks for the wide form, and its button changes it for as long as it stays open
  // the board the view stands on: one stretch of time, one cursor and two marks for the curves of every Spark. Its first stretch is a day
  const B = makeBoard([el], { open: () => !!ui, keys: () => S.cluster.nodes.flatMap(c => ['fan', 'cpu_c', 'gpu_c'].map(key => `${c.name}.${key}`)), room: () => ui.rows[0].plot.inner(),
    drawn: () => drawn(), read: () => read(), callout: true, failed: problem => ui.bar.say(TEXTS.failed(problem.message || problem)) }, 86400);

  const others = name => S.cluster.nodes.map(c => c.name).filter(o => o !== name);  // The other Sparks of the cluster, by name.
  const rowOf = (name, kind) => ui.rows.find(r => r.node === name && r.kind === kind);  // The row of one reading of one Spark.
  function firstRead() {  // The first moment of the stretch the history holds a fan reading of any Spark, null when it holds none.
    const firsts = S.cluster.nodes.map(c => (B.got.series[`${c.name}.fan`] || []).findIndex(v => v != null)).filter(i => i >= 0);
    return firsts.length ? B.got.t[Math.min(...firsts)] : null;
  }
  function late() {  // What the view adds about its own recording: that the stretch holds no fan reading, or where the recording begins inside it; nothing otherwise.
    const first = firstRead();
    return first == null ? TEXTS.noFans : beginsLate(first, B.got.from, B.got.reach) ? TEXTS.begins(B.when(first, true)) : '';
  }
  function texts() {  // What the box of the bar shows, as titled paragraphs: the sentence of this moment, the stretch and what one point stands for, how to read the curves, the rule of each reading, how their scale is made, the picture, and who sets the fans.
    const got = B.got, T = TEXTS.titles;
    return [[S.past ? T.then : T.now, ui.said],
      [T.stretch, got ? TEXTS.stretch(B.fromTo(got.from, got.to, got.live), lengthWord(got.to - got.from), resolutionWord(got.tier, got.width, S.identity.interval), late()) : ''],
      [T.reading, TEXTS.reading], [T.fan, TEXTS.fan], [T.heat, TEXTS.heat], [T.scale, TEXTS.scale], [T.picture, ui.what],
      [T.setter, `${ui.setter} ${TEXTS.never}`.trim()]];
  }
  function reshape(on) {  // Changes the form of the view, beside the ring or wide, and builds it again on the same stretch of time.
    if (on === wide || !ui) return;
    wide = on;
    surfaces();  // first the room of the form, then the view that is measured into it
    ui.bar.shut(); B.reset(); build(); paintHead();
    B.load();
  }
  function addRow(parent, name, kind, unit) {  // Adds the row of one reading of one Spark: its name leads to the page of that Spark, and the row of its fans carries the sign for slower fans.
    const row = { ...makeRow(B, parent, name, unit, { calm: true, digits: 0, height: ui.tall }), node: name, kind };
    row.id.textContent = '';
    button(row.id, 'ch-open', name, () => setView('node', name)).title = TEXTS.page;
    if (kind === 'fan') { row.chip = make('i', 'ch-chip', row.id, 'Slower'); row.chip.title = TEXTS.slower; show(row.chip, false); }
    ui.rows.push(row);
  }
  function buildHead() {  // Builds the head: the headline with the button that changes the form, a line for what cannot wait, and the two figures of all Sparks together.
    const head = make('div', 'cool-head', el), word = wide ? TEXTS.beside : TEXTS.wide;
    ui.head = make('h2', '', head);
    const form = button(head, 'cool-form', '', () => reshape(!wide));
    form.title = word; form.setAttribute('aria-label', word);
    draw('path', { d: SIGNS[wide ? 'wide' : 'narrow'] }, draw('svg', { viewBox: '0 0 16 16', 'aria-hidden': 'true' }, form));
    ui.note = make('p', 'cool-alarm', el);
    ui.keys = make('div', 'cool-keys', el);
    for (const [kind, title, unit] of KINDS) { const k = make('div', 'cool-key', ui.keys); make('b', '', k, title); ui.key[kind] = make('strong', '', k); make('span', '', k, unit); }
  }
  function buildLists() {  // Beside the ring: one list per reading, a row per Spark, the time axis under it, and under the fans where they ran slower.
    for (const [kind, title, unit] of KINDS) {
      const part = make('section', 'sp-part', el), head = make('div', 'sp-h', part);
      make('h3', '', head, title); make('span', 'cool-unit', head, unit);
      for (const c of S.cluster.nodes) addRow(part, c.name, kind, unit);
      ui.axes.push(makeAxis(make('div', 'ch-axis', part)));
      if (kind === 'fan') ui.earlier = make('ul', 'sp-open sp-earlier', part);
    }
  }
  function buildCards() {  // Wide: one card per Spark with its fans and its warmest sensor side by side, the two time axes under the cards, and a place for what follows them.
    const cards = make('div', 'cool-cards', el), axes = make('div', 'cool-axes', el);
    for (const c of S.cluster.nodes) {
      const card = make('section', 'cool-card', cards);
      for (const [kind, , unit] of KINDS) addRow(make('div', 'cool-cell', card), c.name, kind, unit);
    }
    for (let k = 0; k < KINDS.length; k++) ui.axes.push(makeAxis(make('div', 'ch-axis', axes)));
    ui.more = make('div', 'cool-more', el);
    ui.earlier = make('ul', 'sp-open sp-earlier', ui.more);
  }
  function build() {  // Builds the view, once per opening and once more when its form changes: head, bar, the curves of every Spark in the form that was picked, and the picture of fans against warmth.
    el.textContent = ''; el.classList.add('record', 'calm'); el.classList.toggle('narrow', !wide); el.classList.toggle('wide', wide); el.classList.remove('figures');
    ui = { rows: [], axes: [], key: {}, spans: {}, flags: {}, now: {}, said: '', what: '', setter: '', more: null, tall: 72 };
    buildHead();
    ui.bar = makeQuietBar(B, el, el, WINDOWS, late, { figures: TEXTS.figures, info: TEXTS.info, about: TEXTS.about, texts });
    if (wide) { el.appendChild(ui.keys); ui.tall = curveHeight(el.clientHeight, ui.keys.getBoundingClientRect().bottom - el.getBoundingClientRect().top, S.cluster.nodes.length); }  // wide: the two figures stand over the two columns of the cards, under the bar, and a curve is as tall as lets every card stand on the panel
    if (wide) buildCards(); else buildLists();
    const part = make('section', 'sp-part', ui.more || el);
    make('h3', '', make('div', 'sp-h', part), TEXTS.titles.picture);
    ui.picture = make('div', 'cool-pic', part);
  }
  function traces() {  // Every reading the view draws, from the stretch that was loaded: per Spark its fans and its warmest sensor, each with mean, lowest, highest and count per column.
    const got = B.got, full = (what, key) => got.t.map((_, i) => ((got[what] || {})[key] || [])[i] ?? null), out = { fan: {}, heat: {} };
    for (const c of S.cluster.nodes) {
      const of = (what, key) => full(what, `${c.name}.${key}`), warm = what => warmerOf(of(what, 'cpu_c'), of(what, 'gpu_c'));
      out.fan[c.name] = { t: got.t, mean: of('series', 'fan'), low: of('low', 'fan'), peak: of('peak', 'fan'), n: of('n', 'fan') };
      out.heat[c.name] = { t: got.t, mean: warm('series'), low: warm('low'), peak: warm('peak'), n: warm('n') };  // as many readings as the reading that has more of them
    }
    return out;
  }
  function scaleOf(list) {  // One scale for the same reading of every Spark, so their curves can be compared: round ends that hold every mean and every line drawn on them. A single reading far off (a fan read as 0 once) does not flatten every curve: its band is cut at the edge, its figure stands in the row.
    const all = list.flat().filter(v => v != null), axis = axisOf(all.length ? Math.min(...all) : null, all.length ? Math.max(...all) : null, 4, 4);
    return [axis.lo, axis.hi];
  }
  function drawn() {  // Draws every curve from the stretch that was loaded: the fans with the line of the rule and a foot where they ran slower than the others, the warmest sensor, both on one scale each; and lists what held.
    const got = B.got, all = traces(), floors = {};
    ui.traces = all;
    for (const c of S.cluster.nodes) {
      const rest = others(c.name);
      floors[c.name] = fanFloor(rest.map(o => all.fan[o].mean));
      ui.flags[c.name] = slowFanFlags(all.fan[c.name].mean, rest.map(o => all.fan[o].mean), all.heat[c.name].mean, rest.map(o => all.heat[o].mean));
      ui.spans[c.name] = spansWhere(got.t, ui.flags[c.name], got.reach, got.gap);
    }
    for (const [kind] of KINDS) {
      const range = scaleOf([...Object.values(all[kind]).map(t => t.mean), ...(kind === 'fan' ? Object.values(floors) : [])]), [lo, hi] = range, held = list => list.map(v => v == null ? null : clamp(v, lo, hi));  // held: a band inside the scale
      for (const c of S.cluster.nodes) {
        const row = rowOf(c.name, kind), floor = floors[c.name];
        row.trace = all[kind][c.name];
        row.plot.paint(B.view({ mean: row.trace.mean, low: held(row.trace.low), peak: held(row.trace.peak), range,
          ...(kind === 'fan' ? { spans: ui.spans[c.name], limit: floor.some(v => v != null) ? { at: floor, word: '' } : undefined } : {}) }));
      }
    }
    for (const axis of ui.axes) axis(got.from, got.to, got.events || []);
    paintEarlier();
  }
  function earlierLine(name, s, held, still) {  // One stretch of slower fans as a line to click: by how much, then for how long from what was recorded, and when; the figures behind it as its tooltip. A click marks it on every curve.
    const got = B.got, [from, , to] = s, when = B.fromTo(from, Math.min(s[1], got.to), still), b = button(make('li', 'warn', ui.earlier), '', '', () => B.setMarks([from, to]));
    const words = slowerWords(name, stretchStats(ui.traces.fan[name], from, to).mean, middleOf(others(name).map(o => stretchStats(ui.traces.fan[o], from, to).mean)));
    make('b', '', b, words.short);
    make('span', '', b, `${heldWord(held, true)}, ${when}`);
    b.title = `${earlierWord(words.long, held, when)} ${TEXTS.mark}`;
  }
  function paintEarlier() {  // Lists where the fans of a Spark ran slower than the others in the stretch, newest first per Spark, each with the time it held from what was recorded; and keeps which Spark is slower up to now.
    const got = B.got;
    ui.earlier.textContent = '';
    for (const c of S.cluster.nodes) {
      const spans = ui.spans[c.name], flags = ui.flags[c.name], counts = (got.n || {})[`${c.name}.fan`];
      const now = holdsToNow(got.t, flags, got.to, got.gap, got.live, S.t, writtenBehind(S.identity.interval));
      const inside = s => heldSeconds(flags.map((v, i) => v && got.t[i] >= s[0] && got.t[i] <= s[2] ? 1 : 0), counts, got.step, got.t, got.to);  // from what was recorded: the stretch itself bridges a reading that was missed
      ui.now[c.name] = now;
      for (const s of spans.slice(-2).reverse()) earlierLine(c.name, s, inside(s), now && s === spans[spans.length - 1]);
      if (spans.length > 2) make('li', 'more', ui.earlier, TEXTS.more(c.name, spans.length - 2));
    }
  }
  function paintPicture() {  // Fan speed against the warmest sensor, one dot per Spark: at the cursor, else as the mean of the marked stretch, else now; behind them, small, every point of the stretch they are taken from.
    const got = B.got, [a, b] = B.stretch(), on = B.hover != null, i = on ? columnAt(got.t, B.hover, got.reach) : -1, live = S.nodes.filter(n => n.live && n.fan != null && warmest(n)), odd = [...stoppedFans(live), ...oddFans(live)];
    const points = S.cluster.nodes.map(c => {
      const fan = ui.traces.fan[c.name], heat = ui.traces.heat[c.name], n = live.find(x => x.name === c.name), inside = k => a == null || (got.t[k] >= a && got.t[k] <= b);
      const trail = got.t.map((_, k) => [heat.mean[k], fan.mean[k]]).filter((p, k) => p[0] != null && p[1] != null && inside(k));
      const dot = on ? (i < 0 ? [null, null] : [heat.mean[i], fan.mean[i]]) : a != null ? [stretchStats(heat, a, b).mean, stretchStats(fan, a, b).mean] : n ? [warmest(n)[1], n.fan] : [null, null];
      const slow = on ? i >= 0 && ui.flags[c.name][i] === true : a != null ? ui.spans[c.name].some(s => s[0] <= b && s[2] >= a) : odd.includes(n);
      return { name: c.name, trail: trail.filter((_, k) => k % Math.ceil(trail.length / 90 || 1) === 0), dot: dot[0] == null || dot[1] == null ? null : dot, slow };
    });
    ui.what = TEXTS.dots(on ? TEXTS.dot.cursor(B.when(B.hover, true)) : a != null ? TEXTS.dot.marked : S.past ? TEXTS.dot.then : TEXTS.dot.now, a != null ? TEXTS.small.marked : TEXTS.small.all);
    const room = ui.picture.clientWidth;  // read before the picture is taken away: a panel measured without it would lose the place it was scrolled to
    ui.picture.textContent = '';
    drawPicture(ui.picture, points, room);
  }
  function drawPicture(host, points, room) {  // Draws that picture as wide as its place: RPM upwards, °C to the right, both with their marks; a Spark whose fans count as slow in amber, with its name.
    const xs = points.flatMap(p => [...p.trail.map(t => t[0]), ...(p.dot ? [p.dot[0]] : [])]), ys = points.flatMap(p => [...p.trail.map(t => t[1]), ...(p.dot ? [p.dot[1]] : [])]);
    if (!xs.length) { make('p', 'sp-none', host, TEXTS.nothing); return; }
    const W = Math.max(260, room || 332), H = 200, L = 48, R = 12, T = 26, B0 = 26, x = axisOf(Math.min(...xs), Math.max(...xs), 4, 4), y = axisOf(Math.min(...ys), Math.max(...ys), 3, 400);
    const X = c => L + (c - x.lo) / (x.hi - x.lo) * (W - L - R), Y = v => H - B0 - (v - y.lo) / (y.hi - y.lo) * (H - T - B0);
    const svg = draw('svg', { class: 'cool', width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Fan speed in RPM against the warmest sensor in °C, one dot per Spark' }, host);
    draw('title', {}, svg).textContent = ui.what;
    for (const v of y.ticks) { draw('line', { class: 'grid', x1: L, x2: W - R, y1: Y(v), y2: Y(v) }, svg); draw('text', { x: L - 7, y: Y(v) + 4, 'text-anchor': 'end' }, svg).textContent = figure(v); }
    for (const c of x.ticks) draw('text', { x: X(c), y: H - 7, 'text-anchor': 'middle' }, svg).textContent = `${figure(c)} °C`;
    draw('text', { x: L - 7, y: 11, 'text-anchor': 'end' }, svg).textContent = 'RPM';
    for (const p of points) { const g = draw('g', { class: p.slow ? 'odd' : '' }, svg); for (const [c, v] of p.trail) draw('circle', { class: 'trail', cx: X(c).toFixed(1), cy: Y(v).toFixed(1), r: 2 }, g); }
    const placed = [];  // the middle and the line of every name so far: a name stands above its dot, above the name of a neighbour in the same place, and below the dot where no room is left above (namePlace)
    for (const p of points.filter(q => q.dot)) {
      const g = draw('g', { class: p.slow ? 'odd' : '' }, svg), cx = X(p.dot[0]), cy = Y(p.dot[1]), name = p.name.split('-').pop().slice(0, 8), half = name.length * 3.5;  // half: half the width of the name, as it is guessed here
      draw('title', {}, draw('circle', { class: 'now', cx: cx.toFixed(1), cy: cy.toFixed(1), r: 6 }, g)).textContent = `${p.name}: ${figure(p.dot[1])} RPM at ${figure(p.dot[0])} °C${p.slow ? ', slower than the others' : ''}`;
      const end = cx > W - 40, at = Math.min(W - R, Math.max(L + 2, cx)), mid = end ? at - half : Math.max(at, L + 2 + half), ly = namePlace(mid, cy, placed, 11);  // a name at the right edge ends at its dot, and one at the left edge begins where the curves begin: neither reaches into the figures of a scale
      placed.push([mid, ly]);
      draw('text', { class: 'name', x: end ? at : mid, y: ly, 'text-anchor': end ? 'end' : 'middle' }, g).textContent = name;
    }
  }
  function read() {  // Writes what follows the cursor and the marks: value and figures of every row, with what belongs to a reading of now as its tooltip, the sign for slower fans, the bar, and the picture.
    const got = B.got, on = B.hover != null, i = on ? columnAt(got.t, B.hover, got.reach) : -1;
    for (const row of ui.rows) {
      const n = S.nodes.find(x => x.name === row.node), warm = n && n.live ? warmest(n) : null, newest = !n || !n.live ? null : row.kind === 'fan' ? n.fan : warm && warm[1];
      const shown = rowFigures(B, row, newest), each = n && (n.fans || []).length > 1 ? n.fans.map(f => figure(f)).join(' and ') : '';
      row.value.title = shown.what !== 'now' || S.past ? '' : row.kind === 'fan' ? (each && TEXTS.fansNow(each)) : warm ? TEXTS.warmNow(warm[0]) : '';
      if (row.chip) show(row.chip, slowerShown(ui.flags[row.node], i, on, ui.now[row.node]));
    }
    ui.bar.paint();
    paintPicture();
  }
  function paintHead() {  // Writes what the moment on the page says about cooling: the headline, the two figures of all Sparks together, what cannot wait (a fan that stands still, no reading at all, a Spark the headline leaves out), and keeps the rest for the box of the bar. The headline is said of the Sparks that have both readings (coolingWord); each figure spans every Spark that has its reading: a warmest sensor does not fall out because the fans beside it were not read. A Spark that answers without a fan reading is named under the headline (fansUnreadWord): the headline counts fewer Sparks than the ring holds.
    const nodes = S.nodes.filter(n => n.live && n.fan != null && warmest(n)), [headline, note] = nodes.length ? coolingWord(nodes) : ['Cooling', 'No fan reading from any Spark.'], who = [...new Set(nodes.map(fanSetter).filter(Boolean))];
    const urgent = !nodes.length || stoppedFans(nodes).length > 0, live = S.nodes.filter(n => n.live), unread = nodes.length ? fansUnreadWord(fansUnread(S.nodes), !!S.past) : '';  // with no Spark under the headline, its line says so of all of them: not once more by name
    ui.head.textContent = headline;
    ui.note.textContent = [urgent ? note : '', unread].filter(Boolean).join(' '); ui.said = urgent ? '' : note;
    ui.key.fan.textContent = spreadWord(live.filter(n => n.fan != null).map(n => n.fan));
    ui.key.heat.textContent = spreadWord(live.filter(n => warmest(n)).map(n => Math.round(warmest(n)[1])));
    ui.setter = !who.length ? '' : (who.length === 1 ? TEXTS.setBy(who[0]) : nodes.filter(n => fanSetter(n)).map(n => `${n.name}: ${fanSetter(n)}`).join('; ')) + TEXTS.every;
  }
  function tick() {  // With every moment while the view is open: the head follows it, the newest values too unless a cursor reads another moment, and the board asks for its stretch again once it has moved on.
    if (!ui) return;
    paintHead();
    if (B.got && B.hover == null) read();
    B.tick();
  }
  function open() {  // Opens the view on the panel; it is built once and follows the moment by itself.
    if (ui) return;
    B.reset();
    build();
    paintHead();
    B.load();
  }
  function close() {  // Leaves the panel to the other views: nothing of the board stays on it, the box of the bar is shut, and whatever is still on its way is dropped.
    if (!ui) return;
    ui.bar.shut();
    ui = null;
    B.reset();
    el.classList.remove('record', 'calm', 'narrow', 'wide', 'figures'); el.textContent = '';
    wide = wideAsked(location.search);  // the choice is not kept: the next time it opens as the address asks
  }
  return { open, close, tick, reshape, isOpen: () => !!ui, wide: () => wide };
})();
