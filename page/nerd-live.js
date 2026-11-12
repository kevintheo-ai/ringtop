// Nerd mode, the live side: the log of the engine, the columns beside it, the numbers on top and the time strip.
'use strict';
// The live side of nerd mode: builds the log, the two columns, the numbers on top and the time strip, and hands the deep side what it needs.
function nerdLive(shared) {  // seam
  const root = $('#nerd'), logEl = $('#n-log'), moreEl = $('#n-new'), left = $('#n-left'), right = $('#n-right'), filterEl = $('#n-filter'), nodeEl = $('#n-node'), pauseEl = $('#n-pause'), tl = $('#n-tl'), brushEl = $('#n-brush'), rangeEl = $('#n-range'), legend = $('#n-legend');
  const MAX_ROWS = 1500;
  let seq = 0, timer = 0, query = null, brush = null, waiting = 0, before = null, drag = null, stale = false;
  shared.open = false; shared.paused = false; shared.data = null;  // seam
  let lines = [];
  const rose = new Map();  // counter|node -> { v, at }: when a counter last went up
  const short = name => name.split('-').pop().slice(0, 6);  // A Spark's name in short: its last part, six characters at most.
  // The rank of a Spark by its name, 0 when the cluster does not know it.
  const rankOf = name => { const n = S && S.cluster.nodes.find(x => x.name === name); return n ? n.rank : 0; };
  let onlyLevel = '';
  // Does a log line pass the filters: the Spark picked, the stretch brushed, the search and the level.
  const passes = e => (!nodeEl.value || e.node === nodeEl.value) && (!brush || (e.t >= brush[0] && e.t <= brush[1])) && (!query || query.test(e.node + ' ' + e.text)) && (!onlyLevel || level(e.text) === onlyLevel);
  // How serious a log line is, from its text: bad, warn, or neither.
  const level = text => /\b(ERROR|CRITICAL|FATAL)\b|Traceback/.test(text) ? 'bad' : /\bWARNING\b/.test(text) ? 'warn' : '';
  // Is the log scrolled to its end, so new lines may keep it there.
  const atEnd = () => logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 24;
  // A moment as hours, minutes and seconds on a 24-hour clock.
  const hms = t => new Date(t * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const LOG_LINE = /^\(\w+(?: pid=\d+)?\)\s+[A-Z]+(?:\s+\d\d-\d\d \d\d:\d\d:\d\d)?\s+\[([^\]]+)\]\s*(.*)$/s;  // (APIServer pid=1) INFO 11-09 13:20:42 [loggers.py:336] Engine 000: ...
  function row(e) {  // One log line as an element: time, Spark, where in the engine it comes from, and its text.
    const line = make('div', `n-line r${rankOf(e.node) % 4} ${level(e.text)}`), m = LOG_LINE.exec(e.text);
    make('time', '', line, hms(e.t));
    make('b', '', line, short(e.node));
    const text = make('span', '', line);
    text.title = e.text;
    if (m) { make('em', '', text, m[1] + '  '); text.appendChild(document.createTextNode(m[2])); } else text.textContent = e.text;
    return line;
  }
  function paintMore() {  // Shows how many new lines wait below while the reader has scrolled up.
    moreEl.hidden = !waiting;
    moreEl.textContent = waiting + ' new';
  }
  function paintEmpty() {  // Says why the log is empty: nothing matches, nothing has arrived yet, or this ringtop is too old.
    const none = !logEl.querySelector('.n-line');
    const hint = logEl.querySelector('.n-empty');
    const words = lines.length ? 'No lines match the filter.' : stale ? 'This ringtop is older than this page. Restart it to see the engine log.' : 'No engine lines yet. They arrive every few seconds while the model works.';
    if (none && !hint) make('div', 'n-empty', logEl, words); else if (none) hint.textContent = words;
    if (!none && hint) hint.remove();
  }
  function rebuild() {  // Draws the log anew from the lines that pass the filters, and jumps to its end.
    logEl.textContent = '';
    const frag = document.createDocumentFragment();
    for (const e of lines.filter(passes).slice(-MAX_ROWS)) frag.appendChild(row(e));
    logEl.appendChild(frag);
    waiting = 0; paintMore(); paintEmpty();
    logEl.scrollTop = logEl.scrollHeight;
  }
  function append(list) {  // Adds new lines at the end of the log; a reader who scrolled up stays on the same line.
    const stick = atEnd(), frag = document.createDocumentFragment();
    let added = 0;
    for (const e of list) if (passes(e)) { frag.appendChild(row(e)); added++; }
    if (!added) return;
    logEl.appendChild(frag);
    while (logEl.childElementCount > MAX_ROWS) {  // reading back: the view stays on the same line
      const first = logEl.firstElementChild, h = first.offsetHeight;
      first.remove();
      if (!stick) logEl.scrollTop -= h;
    }
    if (stick) logEl.scrollTop = logEl.scrollHeight; else waiting += added;
    paintMore(); paintEmpty();
  }
  function ingest(d) {  // Takes in one answer of the server: new log lines, in order, and fresh numbers for the columns or the open tab.
    if (d.seq < seq) { lines = []; seq = 0; rebuild(); return; }  // ringtop restarted: the next poll reads its log from the start
    shared.data = d;
    seq = d.seq;
    if (d.log.length) {
      let t = lines.length ? lines[lines.length - 1].t : 0, inOrder = true;
      for (const e of d.log) { if (e.t < t) inOrder = false; t = e.t; }
      lines.push(...d.log);
      if (lines.length > 4000) lines.splice(0, lines.length - 4000);
      if (inOrder) append(d.log);
      else { lines.sort((a, b) => a.t - b.t); rebuild(); }  // nodes catch up on their history at different moments
      paintLevels();
    }
    if (shared.tab === 'live') paintSides(); else shared.paintPane();
  }
  let polling = 0;  // reopening starts a new chain: an answer still on its way must not restart the old one
  // Asks the server once a second while nerd mode is open and not paused; reopening starts a chain of its own.
  async function poll(run = ++polling) {
    if (!shared.open || run !== polling) return;
    if (!shared.paused) {
      try {
        const res = await fetch('api/nerd?since=' + seq + (shared.tab === 'live' ? '' : '&deep=1'));
        if (run !== polling) return;
        if (res.ok) {
          const body = await res.json();
          if (run !== polling) return;
          stale = false; ingest(body);
        } else if (res.status === 404) { stale = true; paintEmpty(); }
      } catch { /* ringtop is restarting: the page shows that already */ }
    }
    timer = setTimeout(poll, 1000, run);
  }
  const heat = pct => `hsl(${250 - pct * 2.2} 85% ${16 + pct * .44}%)`;  // The colour of a core for how busy it is, from cool blue to hot.
  function cpus(text) {  // The cores a cpuset names, as a set: "5-9,15" gives 5 to 9 and 15.
    const set = new Set();
    for (const part of (text || '').split(',')) { if (!part.trim()) continue; const [a, b] = part.split('-').map(Number); if (Number.isFinite(a)) for (let c = a; c <= (Number.isFinite(b) ? b : a); c++) set.add(c); }
    return set;
  }
  function section(parent, title, extra, hint) {  // A heading inside a column, with a word beside it and a tooltip that says how to read it.
    const h = make('h3', '', parent, title);
    if (extra) make('em', '', h, extra);
    if (hint) h.title = hint;
    return h;
  }
  const latPos = v => v == null ? 0 : clamp(Math.log10(Math.max(v, .001) / .001) / Math.log10(120 / .001));  // 1 ms to 2 min, log scale
  function paintLeft(d) {  // The left column: latency per stage, how far drafts survive, the scheduler and the sink detector.
    left.textContent = '';
    if (!d.latency) { make('p', 'p-note', left, 'Waiting for the engine.'); return; }
    section(left, 'Latency', d.latency.some(r => r.recent) ? 'last 5 min' : 'since start', 'Time per request stage, from the engine histograms. Solid bar p50, pale bar p95.');
    const lat = make('div', 'n-kv', left);
    make('span', 'head', lat, ''); make('span', 'head', lat, 'p50'); make('span', 'head', lat, 'p95');
    for (const r of d.latency) {
      make('span', '', lat, r.name); make('span', '', lat, seconds(r.p50)); make('span', '', lat, seconds(r.p95));
      const bar = make('div', 'n-lat', lat);
      const pale = make('i', '', bar), solid = make('i', '', bar);
      pale.style.cssText = `width:${(latPos(r.p95) * 100).toFixed(1)}%;background:rgba(139,125,255,.32)`;
      solid.style.cssText = `width:${(latPos(r.p50) * 100).toFixed(1)}%;background:var(--violet)`;
    }
    const sp = d.speculation || {}, pos = sp.positions || [];
    section(left, 'Speculation', sp.mean_length != null ? 'mean ' + sp.mean_length.toFixed(2) + ' tokens' : '', 'How many drafted tokens survive at each position. Tall bars early mean drafts are good; a higher mean length means fewer model steps per token.');
    if (pos.length) {
      const bars = make('div', 'n-spec', left);
      for (const q of pos) {
        const c = make('i', '', bars); make('b', '', c).style.height = ((q.rate || 0) * 100).toFixed(0) + '%';
        c.title = `position ${q.pos + 1}: ${q.rate == null ? 'no drafts' : Math.round(q.rate * 100) + ' % accepted'}${q.reach != null ? ', reached by ' + Math.round(q.reach * 100) + ' % of drafts' : ''}`;
      }
      const axis = make('div', 'n-spec-x', left); make('span', '', axis, '1'); make('span', '', axis, 'accepted per position'); make('span', '', axis, String(pos.length));
    } else make('p', 'p-note', left, 'No drafts yet.');
    const sc = d.scheduler || {};
    section(left, 'Scheduler', '', 'Pressure near 1 means that class of work is limited by compute. Prefill share is how much of the compute reading new prompts takes.');
    const sch = make('div', 'n-kv two', left);
    const pair = (k, v) => { make('span', '', sch, k); make('span', '', sch, v); };
    for (const k in sc.pressure || {}) pair(`${k} pressure`, fixed(sc.pressure[k], 2));
    for (const k in sc.waiting_by_reason || {}) pair(`waiting for ${k}`, whole(sc.waiting_by_reason[k]));
    pair('prefill share', pct(sc.prefill_share));
    pair('prefill backlog', sc.backlog == null ? 'n/a' : size(sc.backlog) + ' tok');
    pair('KV computed', sc.kv_computed == null ? 'n/a' : size(sc.kv_computed) + ' tok');
    const sink = sc.sink || {};
    if (Object.keys(sink).length) {
      section(left, 'Sink detector', '', 'Rows flagged by the detector for degenerate output; draft cuts and zero rejections say what it did about them.');
      const k = make('div', 'n-kv two', left);
      for (const name in sink) { make('span', '', k, name.replace(/_/g, ' ')); make('span', '', k, whole(sink[name])); }
    }
  }
  function matrix(parent, names, rows, cell) {  // one row per thing, one column per node
    const box = make('div', 'n-mx', parent);
    box.style.gridTemplateColumns = `minmax(0,1fr) repeat(${names.length},34px)`;
    make('span', 'name head', box, '');
    for (const n of names) make('span', 'head' + (n === nodeEl.value ? ' pick' : ''), box, short(n));
    for (const r of rows) {
      make('span', 'name', box, r.name).title = r.name;
      for (const n of names) { const c = cell(r, n); const el = make('span', (n === nodeEl.value ? 'pick ' : '') + (c.cls || ''), box, c.text); if (c.title) el.title = c.title; }
    }
  }
  // The right column: every Spark in one line, the ring links, the CPU cores, the engine threads, the link counters, and whether all Sparks run the same build.
  function paintRight(d) {
    right.textContent = '';
    const names = d.nodes.map(n => n.name);
    const live = new Map((S ? S.nodes : []).map(n => [n.name, n]));
    section(right, 'Nodes', '', 'One line per Spark: GPU utilisation, GPU clock, GPU temperature, GPU power, free memory, fan speed, network card temperature.');
    const nodeBox = make('div', 'n-mx', right);
    nodeBox.style.gridTemplateColumns = 'minmax(0,1fr) repeat(7,minmax(26px,auto))';
    for (const word of ['', 'GPU', 'GHz', '°C', 'W', 'free', 'RPM', 'NIC°']) { const head = make('span', word ? 'head' : 'name head', nodeBox, word); if (word === 'W') head.title = 'GPU power'; }  // the narrow column keeps its unit and says whose watts these are
    for (const n of d.nodes) {
      const st = live.get(n.name) || {}, hot = st.gpu_c >= 85;
      make('span', 'name' + (n.name === nodeEl.value ? ' pick' : ''), nodeBox, short(n.name));
      make('span', '', nodeBox, st.util == null ? '–' : st.util + '%');
      make('span', '', nodeBox, st.mhz == null ? '–' : (st.mhz / 1000).toFixed(2));
      make('span', hot ? 'warn' : '', nodeBox, st.gpu_c == null ? '–' : String(Math.round(st.gpu_c)));
      make('span', '', nodeBox, st.w == null ? '–' : String(Math.round(st.w)));
      make('span', '', nodeBox, st.mem_free_gb == null ? '–' : String(Math.round(st.mem_free_gb)));
      make('span', '', nodeBox, st.fan == null ? '–' : Math.round(st.fan / 100) / 10 + 'k');
      make('span', '', nodeBox, st.nic_c == null ? '–' : String(Math.round(st.nic_c)));
    }
    if (S && S.edges.length) {
      section(right, 'Ring links', 'Gb/s each way', 'Traffic on every cable of the ring, in each direction, and how full the cable is.');
      const seen = new Set(), rows = [], pairOf = e => Math.min(e.from, e.to) + '-' + Math.max(e.from, e.to);
      for (const e of S.edges) {
        if (e.to == null) { rows.push({ a: e.from, b: null, ab: e, ba: null }); continue; }
        const key = pairOf(e), twins = S.edges.filter(x => x.to != null && pairOf(x) === key);
        if (twins.length > 2) { rows.push({ a: e.from, b: e.to, ab: e, ba: null, port: e.group }); continue; }  // two cables between the same two Sparks
        if (seen.has(key)) continue;
        seen.add(key);
        rows.push({ a: e.from, b: e.to, ab: e, ba: S.edges.find(x => x.from === e.to && x.to === e.from) || null });
      }
      const nameOf = r => { const n = S.cluster.nodes.find(x => x.rank === r); return n ? short(n.name) : String(r); };
      const box = make('div', 'n-mx', right);
      box.style.gridTemplateColumns = 'minmax(0,1fr) repeat(3,auto)';
      for (const word of ['', 'out', 'in', 'full']) make('span', word ? 'head' : 'name head', box, word);
      for (const r of rows) {
        const cells = linkCells(r.ab, r.ba);
        make('span', 'name', box, r.b == null ? `${nameOf(r.a)} · ${r.ab.group}` : `${nameOf(r.a)} ↔ ${nameOf(r.b)}${r.port ? ' ' + r.port : ''}`);
        make('span', '', box, cells.out);
        make('span', '', box, cells.back);
        make('span', cells.tone, box, cells.last);
      }
    }
    section(right, 'CPU cores', 'outlined = engine', 'Every core of every Spark. X925 are the fast cores, A725 the efficient ones. The outline marks the cores the engine is pinned to.');
    const caps0 = d.nodes.flatMap(n => n.capacity || []), cut = caps0.length ? (Math.min(...caps0) + Math.max(...caps0)) / 2 : 0;
    const classes = cut ? [['X925', c => c >= cut], ['A725', c => c < cut]] : [['all cores', () => true]];
    const head = make('div', 'n-hhead', right); make('span', '', head, '');
    for (const [word] of classes) make('span', '', head, word);
    for (const n of d.nodes) {
      const line = make('div', 'n-heat', right), pins = cpus(n.box && n.box.cpuset), caps = n.capacity || [];
      make('b', '', line, short(n.name));
      for (const [word, fits] of classes) {
        const cells = make('div', 'n-cells', line);
        (n.cores || []).forEach((v, i) => {
          if (caps.length ? !fits(caps[i]) : word !== classes[0][0]) return;
          const cell = make('i', pins.has(i) ? 'pin' : '', cells);
          if (v != null) cell.style.background = heat(v);
          cell.title = `core ${i} (${word}, capacity ${caps[i] ?? 'unknown'}): ${v == null ? 'n/a' : v + ' %'}${pins.has(i) ? ', pinned to the engine' : ''}`;
        });
      }
    }
    section(right, 'Threads', 'CPU %', 'Engine threads by name and how much CPU they use on each Spark. Hover a number for the cores.');
    const by = new Map();
    for (const n of d.nodes) for (const t of n.threads || []) { const r = by.get(t.name) || by.set(t.name, { name: t.name, sum: 0, per: {} }).get(t.name); r.per[n.name] = t; r.sum += t.pct; }
    const top = [...by.values()].sort((a, b) => b.sum - a.sum).slice(0, 7);
    if (top.length) matrix(right, names, top, (r, n) => { const t = r.per[n]; return t ? { text: t.pct, title: `${t.threads} thread${t.threads === 1 ? '' : 's'}${t.cores.length ? ', on cores ' + t.cores.join(' ') : ''}` } : { text: '–' }; });
    else make('p', 'p-note', right, 'No engine threads seen yet.');
    section(right, 'Link counters', 'red = errors rising', 'Absolute hardware counters. Red when an error counter went up in the last 30 s, yellow for pause and corrected-bit counters, which also rise on healthy links.');
    const now = Date.now(), rows = new Map();
    for (const n of d.nodes) for (const dev in n.link_counts || {}) for (const [k, v] of Object.entries(n.link_counts[dev])) {
      if (v == null) continue;
      const r = rows.get(k) || rows.set(k, { name: k, per: {}, any: 0 }).get(k);
      r.per[n.name] = (r.per[n.name] || 0) + v;
      r.any += v;
    }
    for (const r of rows.values()) for (const n of names) {
      const v = r.per[n];
      if (v == null) continue;
      const key = r.name + '|' + n, was = rose.get(key);
      rose.set(key, { v, at: was && v > was.v ? now : was ? was.at : 0 });
    }
    const list = [...rows.values()].filter(r => r.any > 0).sort((a, b) => a.name.localeCompare(b.name)).slice(0, 8);
    const compact = v => v >= 1e9 ? (v / 1e9).toFixed(1) + 'G' : v >= 1e6 ? (v / 1e6).toFixed(v >= 1e8 ? 0 : 1) + 'M' : v >= 1e4 ? Math.round(v / 1e3) + 'K' : String(v);
    if (list.length) matrix(right, names, list, (r, n) => {
      const v = r.per[n], seen = rose.get(r.name + '|' + n), fresh = seen && now - seen.at < 30000;
      return { text: v == null ? '–' : compact(v), cls: fresh ? (/pause|corrected/.test(r.name) ? 'amber' : 'rose') : '' };
    });
    else make('p', 'p-note', right, rows.size ? 'All counters at zero.' : 'No counters read yet.');
    section(right, 'In sync', '', 'Whether all Sparks run the same build: same layer digests and the same command line. Environment variables are deliberately not read. The arguments of the head are listed below.');
    const boxes = d.nodes.filter(n => n.box), head0 = boxes.find(n => n.head) || boxes[0];
    if (!head0) { make('p', 'p-note', right, 'No engine container seen yet.'); return; }
    const words = new Set((head0.box.args || '').split(/\s+/));
    const same = (a, b) => a.layers && b.layers ? a.layers === b.layers : a.image_id === b.image_id;  // the image id depends on the storage driver, the layers do not
    const build = b => b.layers || b.image_id;
    const off = boxes.filter(n => n !== head0 && (!same(n.box, head0.box) || n.box.args !== head0.box.args));
    const missing = d.nodes.length - boxes.length;
    if (!off.length && !missing) make('p', 'n-sync good', right, `All ${d.nodes.length} run the same build${head0.box.layers ? ' (same layers)' : ''} with the same arguments.`);
    for (const n of off) {
      const extra = (n.box.args || '').split(/\s+/).filter(w => w && !words.has(w));
      make('p', 'n-sync bad', right, `${short(n.name)}: ${!same(n.box, head0.box) ? 'other build ' + build(n.box) : 'other arguments'}${extra.length ? ': ' + extra.join(' ') : ''}`);
    }
    if (missing) make('p', 'n-sync bad', right, `${missing} node${missing === 1 ? ' has' : 's have'} no engine container.`);
    if (head0.box.args) {
      const words2 = head0.box.args.split(/\s+/), flags = [];
      for (let i = 0; i < words2.length; i++) if (words2[i].startsWith('--')) { const v = words2[i + 1] && !words2[i + 1].startsWith('--') ? words2[++i] : 'on'; flags.push([words2[i - (v === 'on' ? 0 : 1)].slice(2), v]); }
      const box = make('div', 'n-kv two', right);
      box.title = head0.box.args;
      for (const [k, v] of flags.slice(0, 16)) { make('span', '', box, k); make('span', '', box, v.length > 26 ? '…' + v.slice(-24) : v); }
    }
  }
  function paintSides() {  // Paints both columns from the newest answer.
    if (!shared.data) return;
    paintLeft(shared.data);
    paintRight(shared.data);
  }
  function paintKpis() {  // The cards on top: speed, requests, first token, step time, drafts, the caches, and why it runs like this.
    const box = $('#n-kpis'), e = S.engine, t = e.timing || {}, parts = [['Queue', t.queue, 'var(--amber)'], ['Reading', t.prefill, 'var(--teal)'], ['Writing', t.decode, 'var(--violet)']].filter(p => p[1] > 0);
    box.textContent = '';
    const card = (word, value, sub, hint, cls) => {
      const c = make('div', 'n-kpi ' + (cls || ''), box);
      if (hint) c.title = hint;
      make('em', '', c, word); make('b', '', c, value); if (sub != null) make('span', '', c, sub);
      return c;
    };
    card('Tokens/s', whole(e.tok_s), e.steps_s != null && e.tokens_per_step != null ? `${e.steps_s.toFixed(0)} steps × ${e.tokens_per_step.toFixed(1)}` : '', 'Generated tokens per second, as model steps per second times tokens per step.');
    card('Running / waiting', `${whole(e.running)} / ${whole(e.waiting)}`, `${whole(e.finished)} done${e.errors ? ` · ${whole(e.errors)} failed` : ''}`, 'Requests running and waiting right now, finished since the engine started.');
    card('First token', seconds(e.ttft_p95), e.ttft_recent ? 'p95, last 5 min' : 'p95, since start', 'How long a request waits for its first token.');
    card('Step time', seconds(e.itl_p50), `${e.tokens_per_step != null ? e.tokens_per_step.toFixed(1) + ' tok/step · ' : ''}p50`, 'Time from one model step to the next. A step writes several tokens when speculation works, so this is not the time per token.');
    card('Drafts accepted', pct(e.accepted), e.one_token_share != null ? `${pct(e.one_token_share)} single-step` : 'speculation', 'Share of drafted tokens the model accepted. A step that made only one token got no draft through.');
    card('KV cache', pct(e.kv), e.kv_tokens ? `of ${size(e.kv_tokens)} tokens` : '', 'How full the attention cache is.');
    card('Prefix cache', pct(e.prefix), e.prefill_tok_s != null ? `reads ${whole(e.prefill_tok_s)} tok/s` : 'of prompt reused', 'Share of prompt tokens served from the prefix cache, and how fast the rest was read.');
    const why = card('Why it runs like this', S.why.headline, null, 'What the page thinks is limiting the ring right now.', 'why');
    if (parts.length) {
      const pipe = make('div', 'n-pipe', why);
      for (const [word, v, color] of parts) { const i = make('i', '', pipe); i.style.background = color; i.style.flexGrow = v; i.title = `${word} ${seconds(v)}`; }
    }
  }
  function paintHead() {  // The head of nerd mode: the cards, the run and its step, and what the core says.
    if (!S) return;
    paintKpis();
    const r = S.run || { source: 'none' }, e = S.engine, steps = r.steps || [], cur = steps.find(q => q.state === 'running');
    const finished = steps.filter(q => q.state === 'done' || q.state === 'failed').length;
    $('#n-name').textContent = r.source === 'none' ? 'Nothing running' : r.name;
    $('#n-step').textContent = steps.length > 1 ? `step ${Math.min(finished + 1, steps.length)} of ${steps.length}${cur && cur.name !== r.name ? ': ' + cur.name : ''}` : r.total ? `${whole(r.done)} of ${whole(r.total)}` : '';
    { const face = coreFace(e); $('#n-speed').textContent = face.goal != null ? `${whole(face.goal)} tok/s · ${face.sub}` : face.word; }  // what the core says: the ring engine, or the Sparks on their own
  }
  const levelsEl = $('#n-levels');
  function paintLevels() {  // The buttons that filter the log by level, each with its count.
    let warn = 0, bad = 0;
    for (const e of lines) { const l = level(e.text); if (l === 'warn') warn++; else if (l === 'bad') bad++; }
    levelsEl.textContent = '';
    for (const [word, value, n] of [['Engine log', '', lines.length], ['Warnings', 'warn', warn], ['Errors', 'bad', bad]]) {
      const b = make('button', '', levelsEl, `${word} ${n}`);
      b.type = 'button'; b.setAttribute('aria-pressed', String(onlyLevel === value));
      b.addEventListener('click', () => { onlyLevel = value; paintLevels(); rebuild(); });
    }
  }
  function paintBrush() {  // Draws the stretch brushed on the time strip, or the one being dragged, and names its ends.
    const b = drag ? [Math.min(drag.a, drag.b ?? drag.a), Math.max(drag.a, drag.b ?? drag.a)] : brush;
    if (!b || !S) { brushEl.setAttribute('width', 0); rangeEl.textContent = ''; return; }
    const tmin = S.t - WINDOW, x0 = clamp((b[0] - tmin) / WINDOW) * 100, x1 = clamp((b[1] - tmin) / WINDOW) * 100;
    brushEl.setAttribute('x', x0); brushEl.setAttribute('width', x1 - x0);
    rangeEl.textContent = `${hms(b[0])} to ${hms(b[1])}`;
  }
  function paintTime() {  // The time strip: speed, running, waiting and KV cache over the last half hour, with marks for warnings and errors.
    if (!S) return;
    const tmin = S.t - WINDOW, H = 40, gap = S.identity.interval * 3;
    const scale = (key, floor) => { const v = series.get(key); let hi = floor; if (v) for (const x of v.v) if (x > hi) hi = x; return hi; };
    const line = tracePath(series.get('engine.tok_s'), tmin, 0, scale('engine.tok_s', 10) * 1.1, H, gap);
    $('#n-tok').setAttribute('d', line);
    $('#n-tok-fill').setAttribute('d', fillUnder(line, H));
    $('#n-running').setAttribute('d', tracePath(series.get('engine.running'), tmin, 0, scale('engine.running', 4) * 1.15, H, gap));
    $('#n-waiting').setAttribute('d', tracePath(series.get('engine.waiting'), tmin, 0, scale('engine.waiting', 4) * 1.15, H, gap));
    $('#n-kv').setAttribute('d', tracePath(series.get('engine.kv'), tmin, 0, 1, H, gap));
    for (const lv of ['warn', 'bad']) {
      let d = '';
      for (const e of S.events) if (e.level === lv && e.t > tmin) { const x = ((e.t - tmin) / WINDOW * 100).toFixed(2); d += `M${x} 0L${x} 7`; }
      $('#n-ev-' + lv).setAttribute('d', d);
    }
    const e = S.engine;
    legend.textContent = '';
    for (const [word, value, color] of [['tok/s', whole(e.tok_s), 'var(--violet)'], ['running', whole(e.running), 'var(--teal)'], ['waiting', whole(e.waiting), 'var(--amber)'], ['KV cache', pct(e.kv), 'var(--rose)']]) {
      const w = make('span', '', legend); make('i', '', w).style.setProperty('--c', color); w.appendChild(document.createTextNode(`${word} ${value}`));
    }
    paintBrush();
  }
  function setBrush(range) { brush = range; paintBrush(); rebuild(); }  // Sets the stretch of time the log is narrowed to, or lifts it.
  function setPaused(on) {  // Pauses or resumes the asking, and says so on the button.
    shared.paused = on;
    pauseEl.setAttribute('aria-pressed', String(on));
    pauseEl.firstChild.textContent = on ? 'Paused ' : 'Pause ';
  }
  function setQuery() {  // Takes the search from the filter box as a pattern; one that is no valid pattern is searched as plain text.
    const q = filterEl.value.trim();
    try { query = q ? new RegExp(q, 'i') : null; } catch { query = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'); }
    rebuild();
  }
  // Opens or closes nerd mode: opening slows the scene, paints everything and starts asking; closing gives the focus back.
  function toggle(on = !shared.open) {
    if (NEUTRAL || on === shared.open) return;  // it shows logs and settings as they are: with neutral names it stays shut
    shared.open = on;
    root.hidden = !on;
    document.body.classList.toggle('nerd', on);
    Scene.throttle(on);
    if (on) {
      before = document.activeElement;
      if (nodeEl.options.length < 2) for (const n of S.cluster.nodes) { const o = make('option', '', nodeEl, n.name); o.value = n.name; }
      paintHead(); paintTime(); paintEmpty(); paintLevels(); shared.paintTabs();
      if (shared.tab === 'history') shared.History.open();
      root.focus();
      poll();
    } else {
      clearTimeout(timer);
      shared.History.close();
      if (before && before.focus) before.focus();
    }
  }
  moreEl.addEventListener('click', () => { logEl.scrollTop = logEl.scrollHeight; waiting = 0; paintMore(); });
  logEl.addEventListener('scroll', () => { if (waiting && atEnd()) { waiting = 0; paintMore(); } }, { passive: true });
  filterEl.addEventListener('input', setQuery);
  filterEl.addEventListener('keydown', e => { if (e.key === 'Enter') logEl.focus(); });
  nodeEl.addEventListener('change', () => { rebuild(); paintSides(); });
  pauseEl.addEventListener('click', () => setPaused(!shared.paused));
  $('#n-close').addEventListener('click', () => toggle(false));
  // The moment under the pointer on the time strip.
  const timeAt = e => { const b = tl.getBoundingClientRect(); return S.t - WINDOW + clamp((e.clientX - b.left) / b.width) * WINDOW; };
  tl.addEventListener('pointerdown', e => { if (!S) return; drag = { a: timeAt(e), b: null, x: e.clientX }; tl.setPointerCapture(e.pointerId); paintBrush(); });
  tl.addEventListener('pointermove', e => { if (drag) { drag.b = timeAt(e); paintBrush(); } });
  tl.addEventListener('pointerup', e => {
    if (!drag) return;
    const moved = drag.b != null && Math.abs(e.clientX - drag.x) > 4, range = moved ? [Math.min(drag.a, drag.b), Math.max(drag.a, drag.b)] : null;
    drag = null;
    setBrush(range);
  });

  Object.assign(shared, { cpus, filterEl, paintHead, paintSides, paintTime, root, rose, section, setPaused, short, toggle });  // seam
}  // seam
