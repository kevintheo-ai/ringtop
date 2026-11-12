// The page of one Spark: its figures against its limits, what is open on it and what was, every reading of it over a stretch of time anybody can pick, and the same readings of the other Sparks beside it.
'use strict';
const Spark = (() => {
  const el = $('#spark');
  const WINDOWS = [['30 min', 1800], ['2 h', 7200], ['6 h', 21600], ['24 h', 86400], ['2 d', 172800], ['7 d', 604800], ['30 d', 2592000]];
  // every reading drawn as a curve: its key in the history, its word, its unit, the digits it is read to, and how its plot is made (means: digits of a mean of whole numbers)
  const STACK = [['gpu_c', 'GPU temperature', '°C', 1, { tall: true }], ['mhz', 'GPU clock', 'MHz', 0, { tall: true }], ['w', 'GPU power', 'W', 1, { tall: true, floor: 0 }], ['util', 'GPU busy', '%', 0, { tall: true, fixed: [0, 100] }]];
  // every state drawn as a lane: its key and its short word; the rule behind it in full stands in TEXTS.lanes
  const LANES = [['cap_pct', 'At its power cap'], ['therm_pct', 'Slowed down for heat'], ['brake_pct', 'Power brake'], ['near', 'Near its thermal limit under load'], ['fans', 'Fans slower than the others']];
  const GROUPS = [
    ['Compute', [['engine.tok_s', 'Ring engine, all Sparks', 'tokens/s', 0, { floor: 0 }], ['own_tok_s', 'Its own engine', 'tokens/s', 1, { floor: 0 }], ['own_running', 'Own engine, running', 'requests', 0, { floor: 0, means: 1 }],
      ['own_waiting', 'Own engine, waiting', 'requests', 0, { floor: 0, means: 1 }], ['own_ttft_p95', 'Own engine, first token', 's, 95th percentile', 2, { floor: 0 }], ['cpu_pct', 'CPU busy', '%', 0, { fixed: [0, 100] }],
      ['eng_cores', 'Engine container, CPU', 'cores', 2, { floor: 0 }]]],
    ['Memory', [['mem_free_gb', 'Free memory', 'GB', 1, { floor: 0 }], ['eng_mem_gb', 'Engine container', 'GB', 1, { floor: 0 }]]],
    ['Heat', [['cpu_c', 'Board, warmest zone', '°C', 0, {}], ['nvme_c', 'SSD', '°C', 1, {}], ['nic_c', 'Network card', '°C', 0, {}], ['fan', 'Fans, mean of all', 'RPM', 0, {}]]],
    ['Network', [['net', 'Ring ports, both ways', 'Gb/s', 2, { floor: 0, alone: true }]]],  // alone on its line: under it every cable stands with its two directions side by side
    ['Disk', [['disk_read', 'Read', 'MB/s', 1, { floor: 0 }], ['disk_write', 'Written', 'MB/s', 1, { floor: 0 }]]],
  ];
  const BESIDE = [['fan', 'Fans', 'RPM', 0], ['gpu_c', 'GPU', '°C', 0], ['tlimit', 'To the limit', '°C', 0], ['w', 'GPU power', 'W', 0], ['mhz', 'GPU clock', 'MHz', 0]];  // the last figure is the digits of the ends of its scale
  /* Every sentence of the sheet that is no rule, in one place. What explains: the paragraphs of the box behind the "i" of the bar (titles: their headings, in the order they stand; the rule of a lane stands under the word of that lane)
     and what the buttons and lines say of themselves; the sheet shows name, value, unit, state and curve, these words wait until somebody asks. And what stays in sight in a few words: what is no curve (facts), the word at a limit, the distance beside a name. */
  const TEXTS = {
    titles: { spark: 'This Spark', now: 'Now', then: 'At this moment', stretch: 'Time range', reading: 'Reading the curves', curves: 'Curves', power: 'GPU power', lanes: 'Lanes', beside: 'Beside the others', fans: 'Fans' },
    role: (head, rank, count, ring) => `${head ? 'Head' : 'Worker'}, rank ${rank} of ${count} Spark${count === 1 ? '' : 's'}${ring ? ' in a ring' : ''}.`,
    before: 'The Spark before it (left arrow)',
    next: 'The next Spark (right arrow)',
    open: { now: 'Nothing is open on this Spark right now.', then: 'Nothing the recording keeps was open on this Spark at this moment.' },
    mark: 'Mark this stretch on every curve',
    more: (word, n) => `${word}: ${n} more stretch${n === 1 ? '' : 'es'} before that.`,
    stretch: (span, length, point, late) => `${span}, ${length}. One point: ${point}.${late}`,
    none: ' The history holds no reading of this Spark in it.',
    begins: when => ` Its recording begins ${when}.`,
    reading: 'Move over a curve to read one moment on all of them. Click to set a mark, drag to zoom in. A second click marks a stretch, and the figures of every row then cover the points from the first mark to the second, both included.',
    curves: 'Curve: the mean. Band: lowest to highest reading. Dashed: the limit.',
    power: 'Watts from nvidia-smi power.draw, the value the driver averages. GPU only: a whole Spark draws more, but the GB10 reports no whole-device power, so the page cannot show it. Nothing is measured at the wall socket.',
    lanes: { cap_pct: 'The share of time nvidia-smi counts the GPU at its power cap.', therm_pct: 'The share of time nvidia-smi counts the GPU in thermal slowdown, by software or hardware.', brake_pct: 'The share of time nvidia-smi counts the power brake as on.',
      near: `The GPU at least 50 % busy and closer than ${NEAR_LIMIT} °C to its thermal limit.`,
      fans: `Its fans more than ${Math.round((1 - SLOW_FAN) * 100)} % slower than the middle of the other Sparks while it is no more than ${NOT_COOLER} °C cooler. Needs two other Sparks with a fan reading.` },
    unread: which => `No reading in this stretch: ${which}.`,
    limits: { gpu_c: top => `thermal limit, about ${top} °C`, mhz: top => `top clock, ${top} MHz`, mem_free_gb: guard => `memory guard, ${guard} GB` },
    toLimit: degrees => `${degrees} °C to the limit`,
    ofTop: share => `${share} % of its top clock`,
    noEvent: 'No event of this Spark in this stretch.',
    moreEvents: n => `And ${n} earlier in this stretch.`,
    facts: { free: (free, total) => `${free} of ${total} GB are free.`, gpu: list => `On its GPU: ${list}.`, top: list => `Biggest processes: ${list}.`, setter: who => `Fan speed is set by ${who}.`, wifi: degrees => `Wi-Fi card ${degrees} °C.`,
      to: peer => `To ${peer}`, link: (where, rate) => `${where}: ${rate}.` },
    never: 'Ringtop reads the fans and never sets them.',
    beside: 'Every column shares one scale.',
    under: (what, when) => `Under each curve: ${what}${when ? `, ${when}` : ''}.`,
    own: 'this Spark',
    page: 'open its page',
    figures: 'mean, min, max and the number of minutes or readings behind them, for every curve over the whole range or the marked range',
    info: 'Definitions and sampling',
    about: 'Measurement notes',
    failed: problem => `The history did not answer: ${problem}.`,
  };
  let name = null, ui = null;
  // the board the sheet stands on: its stretch of time, the cursor and the marks of every plot, and the questions to the history. Its first stretch is a day
  const B = makeBoard([el], { open: () => !!name, keys: () => asks(), room: () => ui.rows[0].plot.inner(), drawn: () => drawn(), read: () => { paintFigures(); ui.bar.paint(); },
    callout: true, failed: problem => ui.bar.say(TEXTS.failed(problem.message || problem)) }, 86400);

  const here = () => S.nodes.find(n => n.name === name);  // The open Spark at the moment on the page.
  const keyOf = key => key.startsWith('engine.') || key.startsWith(name + '.') ? key : `${name}.${key}`;  // The name a reading of the open Spark is kept under; the ring engine's are kept under their own.
  const means = key => (B.got && B.got.series[key]) || [];  // The means of one reading, column by column; empty when the history holds none.
  const traceOf = key => ({ t: B.got.t, mean: means(key), low: (B.got.low || {})[key], peak: (B.got.peak || {})[key], n: (B.got.n || {})[key] });  // One reading as the history answered it: mean, lowest, highest and count per column.
  const { when, fromTo } = B;  // a moment and a stretch of time in words, as fine as the stretch on the board
  function section(title) {  // A part of the sheet with its heading; gives back the part.
    const part = make('section', 'sp-part', el);
    make('h3', '', make('div', 'sp-h', part), title);
    return part;
  }
  function addRow(parent, [key, word, unit, digits, opt], live) {  // One reading as a calm row of the sheet (makeRow), under its key in the history: a limit 60 px tall over the whole card, a reading of a group 48 px in its column. The distance that belongs to its value stands beside its name. live: where its newest value stands, if not on the Spark itself.
    const row = { ...makeRow(B, parent, word, unit, { ...opt, digits, calm: true, height: opt.tall ? 60 : 48 }), key: keyOf(key), short: key, live };
    row.id.appendChild(row.note);
    if (opt.alone) row.box.classList.add('alone');
    ui.rows.push(row);
    return row;
  }
  function buildHead() {  // The head of the sheet: the Spark with its role in one word and its neighbours, what it does, four figures against its limits, and what is open on it.
    const head = make('div', 'sp-head', el), line = make('div', 'sp-title', head), names = S.cluster.nodes.map(n => n.name), at = names.indexOf(name);
    make('h2', '', line, name);
    ui.tag = make('span', 'sp-tag', line);
    if (names.length > 1) {
      const nav = make('div', 'sp-nav', line);
      for (const [sign, step, word] of [['‹', -1, TEXTS.before], ['›', 1, TEXTS.next]]) { const b = button(nav, '', sign, () => setView('node', names[(at + step + names.length) % names.length])); b.title = word; b.setAttribute('aria-label', word); }
    }
    ui.age = make('span', 'sp-age', line);
    ui.doing = make('p', 'sp-doing', head);
    const figs = make('div', 'sp-figs', head);
    ui.figs = [0, 1, 2, 3].map(() => { const f = make('div', 'sp-fig', figs), top = make('div', '', f); return { f, value: make('strong', '', top), unit: make('span', '', top), what: make('b', '', f), note: make('p', '', f) }; });
    ui.open = make('ul', 'sp-open', head);
  }
  function buildStack() {  // The stack against its limits: under its heading what held earlier in the stretch, as lines to click; then on one card and in one column four curves over the whole width, under them where each brake held, and one time axis for all of them.
    const part = section('Against its limits');
    ui.earlier = make('ul', 'sp-open sp-earlier', part);  // under the bar that picks the stretch they hang on, and over the curves that show them
    const card = make('div', 'sp-card', part);
    for (const spec of STACK) addRow(card, spec);
    ui.lanes = LANES.map(([key, word]) => {
      const box = make('div', 'ch lane', card);
      make('b', 'ch-id', box, word).title = TEXTS.lanes[key];
      const plot = B.add(makePlot(make('div', 'ch-plot', box), { lane: true, calm: true, word }));  // on the same room as the curves above it: one moment is one place on both
      return { key, word, box, plot, total: make('span', 'ch-total', box) };
    });
    ui.axes.push(makeAxis(make('div', 'ch-axis', card)));
    ui.events = make('div', 'sp-events', section('Events of this Spark'));
  }
  function buildGroups() {  // One part per group of readings: its curves side by side on a card, two to a line, a time axis under each column, and under the card what is no curve; every cable of the Spark gets its two directions.
    const node = here(), mine = S.edges.filter(e => node && e.from === node.rank), cables = mine.flatMap(e => {
      const to = farEnd(e, mine, S.cluster.nodes) || e.group;  // the Spark it leads to, with its port where another cable of this Spark leads to the same one
      return [[[`${name}.${e.group}.tx`, `Sent to ${to}`, 'Gb/s', 2, { floor: 0 }], () => (S.edges.find(x => x.from === e.from && x.group === e.group) || {}).gbps], [[`${name}.${e.group}.rx`, `Received from ${to}`, 'Gb/s', 2, { floor: 0 }], () => (S.edges.find(x => x.from === e.from && x.group === e.group) || {}).rx]];
    });
    ui.groups = GROUPS.map(([title, specs]) => {
      const part = section(title), card = make('div', 'sp-card', part), cells = make('div', 'sp-cells', card), under = make('div', 'sp-cells sp-axes', card);
      const rows = specs.map(spec => addRow(cells, spec, spec[0] === 'engine.tok_s' ? () => S.engine.tok_s : spec[0].startsWith('own_') ? () => ((here() || {}).own || {})[spec[0].slice(4)] : null));
      if (title === 'Network') for (const [spec, live] of cables) rows.push(addRow(cells, spec, live));
      const axes = [0, 1].map(() => { const host = make('div', 'ch-axis', under); ui.axes.push(makeAxis(host)); return host; });
      return { title, card, rows, axes, none: make('p', 'sp-none', part), facts: make('p', 'sp-facts', part) };
    });
  }
  function rightTaken(rows) {  // Whether a curve of a group stands in the right column of its card: its rows fill the lines two by two, one that stands alone takes a line, and a hidden one no place.
    let right = false, taken = false;
    for (const row of rows) {
      if (row.box.hidden) continue;
      taken = taken || (right && !row.opt.alone);
      right = !row.opt.alone && !right;
    }
    return taken;
  }
  function buildBeside() {  // The table beside the others: one line per Spark, one column per reading, every column on one scale; its heading says what the figure under each curve is.
    const others = S.cluster.nodes.length - 1, part = section(others === 1 ? 'Beside the other one' : `Beside the other ${others}`), table = make('div', 'sp-beside', part), head = make('div', 'bs-row bs-head', table);
    make('span', '', head, 'Spark');
    ui.scales = BESIDE.map(([, word, unit]) => { const c = make('span', '', head); make('b', '', c, word); make('small', '', c, unit); return make('i', '', c); });  // a column says its reading, its unit and the two ends of its scale, a line each
    for (const c of S.cluster.nodes) {
      const own = c.name === name, row = make(own ? 'div' : 'button', 'bs-row' + (own ? ' own' : ''), table);
      make('b', '', make('span', 'bs-name', row), c.name);
      row.title = own ? TEXTS.own : TEXTS.page;
      if (!own) { row.type = 'button'; row.addEventListener('click', () => setView('node', c.name)); }
      for (const [key, word, , digits] of BESIDE) {
        const cell = make('span', 'bs-cell', row), plot = B.add(makePlot(cell, { bare: true, word: `${word} of ${c.name}` }));
        ui.cells.push({ node: c.name, key: `${c.name}.${key}`, short: key, digits: key === 'gpu_c' || key === 'w' ? 1 : digits, plot, value: make('em', '', cell), trace: null });
      }
    }
    ui.besideNote = make('span', '', part.firstChild);  // the note in its heading: what the figure under each curve is
  }
  function late() {  // What the sheet adds about its own recording: that the stretch holds no reading of this Spark, or where its recording begins inside it; nothing otherwise.
    const begun = firstRead();
    return begun == null ? TEXTS.none : beginsLate(begun, B.got.from, B.got.reach) ? TEXTS.begins(when(begun, true)) : '';
  }
  function texts() {  // What the box of the bar shows, as titled paragraphs: the role of the Spark, the notes of the figures of its head that are not in sight, the stretch and what one point of a curve stands for, how to read, mark and zoom, what a curve is drawn with, the rule of every lane under its word, what the lanes are judged from at this resolution, what the columns beside the others share, and that ringtop only reads the fans.
    const got = B.got, T = TEXTS.titles;
    return [[T.spark, ui.role], [S.past ? T.then : T.now, ui.notes], [T.stretch, got ? TEXTS.stretch(fromTo(got.from, got.to, got.live), lengthWord(got.to - got.from), resolutionWord(got.tier, got.width, S.identity.interval), late()) : ''],
      [T.reading, TEXTS.reading], [T.curves, TEXTS.curves], [T.power, TEXTS.power], ...LANES.map(([key, word]) => [word, TEXTS.lanes[key]]),
      [T.lanes, got ? laneNote(got.width, got.tier, S.identity.interval) : ''], [T.beside, ui.scales ? TEXTS.beside : ''], [T.fans, TEXTS.never]];
  }
  function build() {  // Builds the sheet of the open Spark in the calm form, once per Spark: nothing on it is rebuilt while it is read. The box of the sheet before it is shut.
    if (ui) ui.bar.shut();
    el.textContent = ''; el.classList.add('calm'); el.classList.remove('figures');
    ui = { rows: [], axes: [], cells: [], spans: {}, flags: {}, shares: {}, counted: {}, openText: null };
    buildHead();
    ui.bar = makeQuietBar(B, el, el, WINDOWS, late, { figures: TEXTS.figures, info: TEXTS.info, about: TEXTS.about, texts });
    buildStack(); buildGroups();
    if (S.cluster.nodes.length > 1) buildBeside();
  }

  function doingWord(n) {  // What the Spark does, in one sentence: out of reach, at work on its own as the server words it, or a part of the ring engine.
    if (!n.live) return `Not reachable${n.reason ? ': ' + n.reason : ''}.`;
    const own = (S.why.points || []).find(p => p.node === name && p.level === 'info');
    if (own) return own.text;
    if (S.engine.state === 'offline') { const word = silentWord(S.engine); return `${word[0].toUpperCase()}${word.slice(1)}, and ringtop sees no work of its own on this Spark.`; }
    return `Part of the ring engine, which is ${S.engine.state}${S.engine.tok_s >= 1 ? ` at ${figure(S.engine.tok_s)} tokens/s over all Sparks` : ''}.`;
  }
  function openPoints(n) {  // What is open on the Spark at the moment on the page: the lines the diagnosis has for it, and fans slower than the others'.
    const points = (S.why.points || []).filter(p => p.node === name && p.level !== 'info'), read = S.nodes.filter(x => x.live && x.fan != null && warmest(x));
    if (n.live && read.includes(n) && oddFans(read).includes(n)) points.push({ level: 'warn', text: slowFanWord(n.fan) });
    return points;
  }
  function paintHead() {  // Writes the head from the moment on the page: role, work, age of the reading, the four figures and what is open. A figure says its note only while it carries a state (urgentNote); the other notes stand behind their figures and are kept for the box, like the role as a sentence.
    const n = here(), open = openPoints(n), text = open.map(p => p.level + p.text).join('|') + S.past, figs = headFigures(n.live ? n : {}, S.past);
    ui.tag.textContent = n.head ? 'head' : 'worker';
    ui.role = TEXTS.role(n.head, n.rank, S.cluster.nodes.length, S.cluster.ring); ui.notes = figureNotes(figs);
    ui.doing.textContent = doingWord(n);
    ui.age.textContent = S.past ? `${n.live ? 'as recorded' : 'no reading'}, ${timeWord(S.t, 1, true)}` : n.live ? `read at ${timeWord(S.t, 1, false)}` : 'no reading';  // looking back too, "as recorded" needs a reading of this Spark at that moment
    figs.forEach((fig, k) => { const u = ui.figs[k]; u.value.textContent = fig.value; u.unit.textContent = fig.unit; u.what.textContent = fig.what; u.note.textContent = urgentNote(fig); u.f.title = fig.note; u.f.dataset.state = fig.state; });
    if (text === ui.openText) return;
    ui.openText = text; ui.open.textContent = '';
    if (!open.length) make('li', 'ok', ui.open, S.past ? TEXTS.open.then : TEXTS.open.now);
    for (const p of open) make('li', p.level, ui.open, p.text);
  }
  function paintFacts() {  // Writes under each group what is a fact of the moment and no curve: sizes, programs, links, who sets the fans.
    const n = here(), mine = S.edges.filter(e => e.from === n.rank), gb = list => (list || []).map(a => `${a.name ? a.name + ' ' : ''}${figure(a.gb, 1)} GB`).join(', ');  // with neutral names a program has none: its size alone
    const F = TEXTS.facts, facts = {
      Memory: [n.mem_total_gb ? F.free(figure(n.mem_free_gb, 1), figure(n.mem_total_gb)) : '', (n.apps || []).length ? F.gpu(gb(n.apps)) : '', (n.top || []).length ? F.top(gb(n.top)) : ''],
      Heat: [fanSetter(n) ? F.setter(fanSetter(n)) : '', n.wifi_c != null ? F.wifi(figure(n.wifi_c)) : ''],  // that ringtop never sets the fans explains, and waits in the box
      Network: mine.map(e => { const far = farEnd(e, mine, S.cluster.nodes); return F.link(far ? F.to(far) : e.group, `${linkRate(e)}${linkNote(e, ', ')}`); }),
      Disk: [n.disk_total_gb ? F.free(figure(n.disk_free_gb), figure(n.disk_total_gb)) : ''],
    };
    for (const g of ui.groups) g.facts.textContent = n.live ? (facts[g.title] || []).filter(Boolean).join(' ') : '';
  }

  const firstRead = () => { const i = means(keyOf('gpu_c')).findIndex(v => v != null); return i < 0 ? null : B.got.t[i]; };  // The first moment of the stretch the history holds a reading of this Spark, null when it holds none.
  function laneFlags() {  // Column by column whether each state of the lanes held, null where that cannot be said; per lane the part of each column it held (shares), how many readings stand behind each column (counted) and the seconds it held in all, from the time that was recorded; and for the two that are judged from several readings whether their own reading was recorded at all (own), and whether the fans had too few others to compare with (few).
    const got = B.got, others = S.cluster.nodes.filter(c => c.name !== name).map(c => c.name), heat = who => warmerOf(means(`${who}.cpu_c`), means(`${who}.gpu_c`)), rest = others.map(o => means(`${o}.fan`));
    const fan = means(keyOf('fan')), slow = slowFanFlags(fan, rest, heat(name), others.map(heat)), limit = means(keyOf('tlimit')), busy = means(keyOf('util')), counts = key => (got.n || {})[keyOf(key)];
    const own = { near: limit.some(v => v != null), fans: fan.some(v => v != null) }, few = fan.every((v, i) => v == null || rest.filter(r => r[i] != null).length < 2);  // few: in every column its fans were read in
    const flags = { near: limit.map((v, i) => v == null || busy[i] == null ? null : v < NEAR_LIMIT && busy[i] >= 50), fans: slow };
    const shares = { near: flags.near.map(Number), fans: flags.fans.map(Number) }, counted = { near: counts('tlimit'), fans: counts('fan') };  // judged column by column: a column that says yes counts for all of its recorded time
    for (const key of ['cap_pct', 'therm_pct', 'brake_pct']) {  // shares of time: a column counts for the part of its recorded time the brake held
      const share = means(keyOf(key));
      flags[key] = share.map(v => v == null ? null : v > 0);
      shares[key] = share.map(v => v == null ? null : v / 100);
      counted[key] = counts(key);
    }
    const held = Object.fromEntries(Object.keys(shares).map(key => [key, heldSeconds(shares[key], counted[key], got.step, got.t, got.to)]));
    return { flags, held, shares, counted, own, few };
  }
  function paintLanes() {  // Draws the lanes: where each state held, for how long in all, and from when on it was recorded or could be judged at all; a lane without a judgement in any point says whether it was not recorded or could not be judged.
    const got = B.got, { flags, held, shares, counted, own, few } = laneFlags(), begun = firstRead();
    ui.flags = flags; ui.shares = shares; ui.counted = counted;
    for (const lane of ui.lanes) {
      const list = flags[lane.key], spans = spansWhere(got.t, list, got.reach, got.gap), first = got.t[list.findIndex(v => v != null)];
      ui.spans[lane.key] = spans;
      lane.box.classList.toggle('held', spans.length > 0);  // a lane that held anywhere in the stretch stands out from the ones that did not
      lane.plot.paint(B.view({ mean: [], spans }));
      lane.total.textContent = first == null ? unjudgedWord(own[lane.key], lane.key === 'fans' && few) : `${heldWord(held[lane.key], spans.length > 0)}${beginsLate(first, begun ?? got.from, got.reach) ? lateWord(own[lane.key], when(first, true)) : ''}`;
    }
  }
  function paintCurves() {  // Draws every row from the stretch that was loaded, each curve with what it is held against; a row without any reading steps back into one line of its group.
    const got = B.got, limit = sumOf(means(keyOf('gpu_c')), means(keyOf('tlimit'))), top = middleOf(limit), n = here() || {}, guard = S.identity.memguard_gib;
    const more = {
      gpu_c: top == null ? {} : { limit: { at: top, word: TEXTS.limits.gpu_c(figure(top)) }, zone: [top - NEAR_LIMIT, top] },  // the limit itself is fixed: its middle over the stretch, since both readings behind it are whole degrees
      mhz: n.mhz_max ? { limit: { at: n.mhz_max, word: TEXTS.limits.mhz(figure(n.mhz_max)) } } : {},
      mem_free_gb: guard == null ? {} : { limit: { at: guard, word: TEXTS.limits.mem_free_gb(guard) } },
      fan: { spans: ui.spans.fans },
    };
    for (const row of ui.rows) { row.trace = traceOf(row.key); row.box.hidden = !row.opt.tall && !row.trace.mean.some(v => v != null); }
    for (const g of ui.groups) {  // first what stands at all, then the curves: one that is drawn while its card is hidden has no width
      const missing = g.rows.filter(r => r.box.hidden).map(r => r.word);
      g.none.textContent = missing.length ? TEXTS.unread(missing.join('; ')) : '';
      show(g.card, missing.length < g.rows.length); show(g.axes[1], rightTaken(g.rows));
    }
    for (const row of ui.rows) row.plot.paint(B.view({ mean: row.trace.mean, low: row.trace.low, peak: row.trace.peak, ...more[row.short] }));
    for (const axis of ui.axes) axis(got.from, got.to, (got.events || []).filter(e => e.node === name));
  }
  function paintBeside() {  // Draws the table beside the others: every column on one scale that holds all Sparks and is at least a tenth of its level wide, so a small difference stays small, and no finer than the digits its two ends are said in.
    BESIDE.forEach(([key, , , digits], k) => {
      const cells = ui.cells.filter(c => c.short === key), all = [];
      for (const c of cells) { c.trace = traceOf(c.key); for (const v of c.trace.mean) if (v != null) all.push(v); }  // the means alone: a table of small curves compares levels, the single readings stand in the rows above
      const lo = all.length ? Math.min(...all) : null, hi = all.length ? Math.max(...all) : null, room = all.length ? Math.max(0, Math.abs(lo + hi) / 20 - (hi - lo)) / 2 : 0, axis = axisOf(lo == null ? null : lo - room, hi == null ? null : hi + room, 2, 4 * 10 ** -digits);
      ui.scales[k].textContent = all.length ? `${figure(axis.lo, digits)} to ${figure(axis.hi, digits)}` : 'no reading';
      for (const c of cells) c.plot.paint(B.view({ mean: c.trace.mean, range: [axis.lo, axis.hi], spans: c.node === name && key === 'fan' ? ui.spans.fans : null }));
    });
  }
  function fanWords([from, , to]) {  // A stretch of slow fans in words: short for its line (by how much), and for the sentence behind it this Spark's mean against the middle of the others. Both say a share only where the means over the stretch show one (slowerShare): the sentence has no figures the line does not stand for.
    const others = S.cluster.nodes.filter(c => c.name !== name).map(c => stretchStats(traceOf(`${c.name}.fan`), from, to).mean), own = stretchStats(traceOf(keyOf('fan')), from, to).mean, rest = middleOf(others), share = slowerShare(own, rest);
    return { short: slowerWords('Fans', own, rest).short, long: share ? `: ${figure(own)} against ${figure(rest)} RPM, ${share} % slower` : '' };
  }
  function earlierLine(key, word, s, held, still) {  // One stretch a state held as a line to click: the state, then for how long from what was recorded, and when; its sentence in full stands behind it. A click marks the stretch on every curve.
    const span = fromTo(s[0], Math.min(s[1], B.got.to), still), fans = key === 'fans' ? fanWords(s) : null, b = button(make('li', 'warn', ui.earlier), '', '', () => B.setMarks([s[0], s[2]]));  // no stretch ends after the sheet does
    make('b', '', b, fans ? fans.short : word);
    make('span', '', b, `${heldWord(held, true)}, ${span}`);
    b.title = `${earlierWord(`${word}${fans ? fans.long : ''}`, held, span)} ${TEXTS.mark}.`;
  }
  function paintEarlier() {  // Lists what held earlier in the stretch, newest first: each one a stretch of time with the time the state held in it.
    const got = B.got;
    ui.earlier.textContent = '';
    for (const [key, word] of LANES) {
      const spans = ui.spans[key] || [], now = holdsToNow(got.t, ui.flags[key] || [], got.to, got.gap, got.live, S.t, writtenBehind(S.identity.interval)), share = ui.shares[key] || [];  // live: of the answer that is shown, not of where the board is heading
      const inside = s => heldSeconds(share.map((v, i) => got.t[i] >= s[0] && got.t[i] <= s[2] ? v : 0), ui.counted[key], got.step, got.t, got.to);  // the time the state held in the points of this stretch, from what was recorded: the same count as the lane's
      for (const s of spans.slice(-2).reverse()) earlierLine(key, word, s, inside(s), now && s === spans[spans.length - 1]);  // only the newest stretch can hold to now
      if (spans.length > 2) make('li', 'more', ui.earlier, TEXTS.more(word, spans.length - 2));
    }
  }
  function paintEvents() {  // Lists the events of the Spark in the stretch, newest first; a click sets a mark at its moment.
    const mine = (B.got.events || []).filter(e => e.node === name);
    ui.events.textContent = '';
    if (!mine.length) make('p', 'sp-none', ui.events, TEXTS.noEvent);
    for (const e of mine.slice(-10).reverse()) { const b = button(ui.events, 'sp-ev ' + e.level, '', () => B.mark(e.t)); make('time', '', b, timeWord(e.t, 1, true)); make('span', '', b, e.text); }
    if (mine.length > 10) make('p', 'sp-none', ui.events, TEXTS.moreEvents(mine.length - 10));
  }
  function paintFigures() {  // Writes value and figures of every row (rowFigures) and cell, and beside a value the distance that belongs to it. A cell beside the others: besideFigure; the heading of that table says what the figure under each curve is, and with a cursor on the sheet its moment, since a small curve has no room for a word beside its cursor.
    const got = B.got, hover = B.hover, [a, b] = B.stretch(), n = here() || {}, on = hover != null, i = on ? columnAt(got.t, hover, got.reach) : -1, left = means(keyOf('tlimit'));
    const say = { gpu_c: shown => { const to = shown.what === 'now' ? n.tlimit : shown.at < 0 ? null : left[shown.at]; return to == null ? '' : TEXTS.toLimit(figure(to)); }, mhz: shown => n.mhz_max ? TEXTS.ofTop(figure(shown.v / n.mhz_max * 100)) : '' };  // the distance that belongs to the value shown: the one of now beside a reading of now, the recorded one beside a point
    for (const row of ui.rows) {
      if (row.box.hidden) continue;
      const shown = rowFigures(B, row, row.live ? row.live() : row.key.startsWith('engine.') ? null : n[row.short]);
      row.note.textContent = shown.v != null && say[row.short] ? say[row.short](shown) : '';
    }
    const figs = ui.cells.map(c => besideFigure(c.trace, i, on, a, b));
    ui.cells.forEach((c, k) => { c.value.textContent = figure(figs[k].v, c.digits); });
    if (ui.besideNote && figs.length) ui.besideNote.textContent = TEXTS.under(BESIDE_WORDS[figs[0].what], on ? when(hover, true) : '');
  }
  function drawn() {  // Draws the whole sheet from the stretch that was loaded; the board then puts the cursor and the marks back onto it.
    paintLanes(); paintCurves(); paintEvents(); paintEarlier();
    if (ui.scales) paintBeside();
  }
  // The keys of the history the sheet is drawn from: every row, what the lanes are judged from, and every column of every Spark beside the others.
  const asks = () => [...new Set([...ui.rows.map(r => r.key), ...['tlimit', 'cpu_c', 'gpu_c', 'cap_pct', 'therm_pct', 'brake_pct'].map(keyOf), ...S.cluster.nodes.flatMap(c => [...BESIDE.map(b => `${c.name}.${b[0]}`), `${c.name}.cpu_c`])])];
  function tick() {  // With every moment while the sheet is open: head, facts and newest values follow it, and the board asks for its stretch again once it has moved on.
    if (!name || !ui) return;
    if (!here()) { setView('ring'); return; }
    paintHead(); paintFacts();
    if (B.got && B.hover == null) paintFigures();
    B.tick();
  }
  function open(node) {  // Opens the sheet of a Spark; another Spark starts on the same stretch of time.
    if (node === name && ui) return;
    name = node;
    B.reset();
    build();
    paintHead(); paintFacts();
    B.load();
  }
  function close() {  // Closes the sheet: the box of its bar is shut, its figures go, and whatever is still on its way is dropped.
    if (ui) ui.bar.shut();
    name = null; ui = null;
    B.reset();
    el.classList.remove('figures'); el.textContent = '';
  }
  return { open, close, tick, isOpen: () => !!name };
})();
