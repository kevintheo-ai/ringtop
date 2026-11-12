// Nerd mode, the deep tabs: nodes, links, engine, requests, sync and history side by side, and what Nerd offers the page.
'use strict';
// The deep side of nerd mode: builds the tabs and their tables, and gives back what the page may ask of Nerd.
function nerdDeep(shared) {  // seam
  const { cpus, filterEl, paintHead, paintSides, paintTime, root, rose, section, setPaused, short, toggle } = shared;  // seam
  Object.assign(shared, { paintPane, paintTabs });  // seam
  /* ---- deep tabs: everything the Sparks say, side by side ---- */
  const tabsEl = $('#n-tabs'), pane = $('#n-pane'), bodyEl = root.querySelector('.n-body'), footEl = root.querySelector('.n-time');
  const TABS = [['live', 'Live'], ['nodes', 'Nodes'], ['links', 'Links'], ['engine', 'Engine'], ['requests', 'Requests'], ['sync', 'In sync'], ['history', 'History']];
  let replies = [], replyPick = 0, repliesAt = 0;
  shared.tab = 'live';  // seam
  const where = make('span', 'n-where', null);
  for (const [id, word] of TABS) { const b = make('button', 'n-tab', tabsEl, word); b.type = 'button'; b.dataset.tab = id; b.addEventListener('click', () => setTab(id)); }
  tabsEl.appendChild(where);
  // Marks the open tab.
  function paintTabs() { for (const b of tabsEl.querySelectorAll('.n-tab')) b.setAttribute('aria-selected', String(b.dataset.tab === shared.tab)); }
  function setTab(id) {  // Opens one tab: the live side with the log, a deep table, or the history.
    shared.tab = id;
    bodyEl.hidden = footEl.hidden = id !== 'live';
    pane.hidden = id === 'live';
    pane.scrollTop = 0;
    paintTabs();
    if (id === 'history') History.open(); else { History.close(); paintPane(); }
    if (id === 'live') paintSides();
  }
  // A number with thousands separators and a fixed count of digits, a dash when it was not read.
  const M = (v, d = 0) => v == null ? '–' : (+v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  // The middle value of the readings that exist, null when there is none.
  const median = list => { const a = list.filter(v => v != null).sort((x, y) => x - y); return a.length ? a[a.length >> 1] : null; };
  const engineCores = n => cpus(n.box && n.box.cpuset);  // The cores the engine of a Spark is pinned to.
  // The mean of the readings that exist, null when there is none.
  const meanOf = list => { const a = list.filter(v => v != null); return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null; };
  // The key thread of a Spark with a given role, an empty object when it was not seen.
  const role = (n, r) => (n.key_threads || []).find(t => t.role === r) || {};
  const NODE_TABLE = [
    ['GPU'],
    ['Load', n => n.util, 0, '%', { key: 'util', hint: 'Coarse GPU load from the driver.' }],
    ['Clock now', n => n.mhz, 0, 'MHz', { key: 'mhz', hint: 'Shader clock at this moment.' }],
    ['Clock, 15 s mean', n => n.avg_mhz, 0, 'MHz', { key: 'avg_mhz', hint: 'True average clock over the last 15 s, from the NVML power-balancing counters.' }],
    ['Clock against target', n => n.avg_mhz && n.mhz_app ? n.avg_mhz / n.mhz_app * 100 : null, 0, '%', { hint: 'Mean clock against the application clock the GPU is set to run at (not the 3 GHz maximum it never reaches).' }],
    ['Activity', n => n.af_pct, 2, '%', { key: 'af_pct', hint: 'NVML activity factor, next to the coarse load figure.' }],
    ['GPU power', n => n.w, 1, 'W', { key: 'w', hint: GPU_POWER_NOTE }],
    ['GPU power, instant', n => n.w_now, 1, 'W', { hint: 'Instantaneous GPU power: spikes the average hides.' }],
    ['Time at power cap', n => n.cap_pct, 1, '%', { key: 'cap_pct', warnAbove: 1, hint: 'Share of time held at the power limit, from the driver\'s microsecond counter. Not the momentary bit.' }],
    ['Time in thermal slowdown', n => n.therm_pct, 1, '%', { warnAbove: 0.5, hint: 'Share of time slowed for heat, software and hardware together.' }],
    ['Time in power brake', n => n.brake_pct, 1, '%', { warnAbove: 0.1, hint: 'Share of time the hardware power brake was on.' }],
    ['Temperature', n => n.gpu_c, 0, '°C', { key: 'gpu_c', warnAbove: 85, hint: 'GPU temperature.' }],
    ['Room to slowdown', n => n.tlimit, 0, '°C', { key: 'tlimit', warnBelow: 8, hint: 'Degrees left before the GPU starts slowing itself.' }],
    ['Performance state', n => n.pstate, null, '', { hint: 'P0 is full speed, P8 idle.' }],
    ['CPU-GPU links up', n => n.c2c_links ? `${n.c2c_up}/${n.c2c_links}` : null, null, '', { hint: 'The chip-to-chip links between CPU and GPU, the path to the shared memory.' }],
    ['CPU-GPU link errors', n => n.c2c_err, 0, '', { warnAbove: 0, redAbove: 0, hint: 'Interrupt and replay errors on those links since the driver started.' }],
    ['CPU'],
    ['Busy', n => n.cpu_pct, 0, '%', { key: 'cpu_pct', hint: w => w.cores }],
    ['Engine cores, real clock', n => meanOf([...engineCores(n)].map(c => (n.clocks || [])[c])), 0, 'MHz', { hint: 'Mean clock actually delivered on the cores the engine is pinned to (cpuinfo_avg_freq), sleeping cores left out.' }],
    ['Cores with a limit active', n => n.perf_limited, 0, '', { warnAbove: 0, hint: 'Cores whose frequency the platform has limited (perf_limited).' }],
    ['Scheduler thread', n => role(n, 'scheduler').pct, 0, '%', { hint: 'CPU of the engine scheduler thread, on the head only. Near 100 % is normal: its loop polls.' }],
    ['Rank main thread', n => role(n, 'rank main').pct, 0, '%', { hint: 'The rank\'s main thread. This is mostly spinning while the GPU works, so a high figure is not necessarily work.' }],
    ['Transport proxy', n => role(n, 'transport proxy').pct, 0, '%', { hint: 'The thread that moves ring traffic. It polls, so about 100 % is normal.' }],
    ['Proxy runs on core', n => role(n, 'transport proxy').core, 0, '', { hint: 'Which core the transport proxy is on. It should not move.' }],
    ['Waiting for a core', n => meanOf((n.key_threads || []).map(t => t.wait)), 2, 'ms/s', { warnAbove: 20, hint: 'How long the key engine threads sat runnable without a CPU, per second.' }],
    ['Thread moves', n => sumOver(n.key_threads, t => t.migrated), 1, '/s', { hint: 'How often the key threads changed core.' }],
    ['Interrupts on engine cores', n => n.irq ? Object.values(n.irq.by_core).reduce((a, b) => a + b, 0) : null, 0, '/s', { hint: 'Hover for the sources.', title: n => n.irq ? Object.entries(n.irq.by_kind).map(([k, v]) => `${k} ${M(v)}/s`).join('  ') : '' }],
    ['Other programs on engine cores', n => sumOver(n.intruders, t => t.ms), 1, 'ms/s', { hint: 'CPU time other programs took on the engine\'s cores.', title: n => (n.intruders || []).map(t => `${t.name} ${t.ms} ms/s`).join('  ') }],
    ['Waiting for CPU, system', n => n.psi_cpu, 2, '%', { key: 'psi_cpu', hint: 'Share of time some task could not get a CPU (pressure stall information).' }],
    ['Temperature zones'],
    ...['TSOC', 'TS0P', 'TS1P', 'TUNC', 'TGPU', 'TS0E', 'TS1E'].map(z => [{ TSOC: 'SoC (hottest)', TS0P: 'CPU cluster 0', TS1P: 'CPU cluster 1', TUNC: 'Uncore', TGPU: 'GPU side', TS0E: 'Efficiency cluster 0', TS1E: 'Efficiency cluster 1' }[z], n => (n.zones || {})[z], 1, '°C', { key: 'zone.' + z, hint: 'ACPI zone ' + z + '.' }]),
    ['Memory'],
    ['Free for use', n => n.mem_free_gb, 1, 'GB', { key: 'mem_free_gb', low: true, hint: 'MemAvailable from the kernel.' }],
    ['Model and KV on GPU', n => n.gpu_apps_gb, 1, 'GB', { hint: 'Memory the driver reports for the compute process. Unified memory: there is no separate GPU total.' }],
    ['Engine on the host', n => n.eng_mem_gb, 1, 'GB', { key: 'eng_mem_gb', hint: 'Host memory of the engine container, peak on hover.', title: n => n.eng_peak_gb != null ? `peak ${n.eng_peak_gb} GB` : '' }],
    ['Page cache', n => n.memory && n.memory.Cached, 1, 'GB', { hint: 'Files the kernel keeps in memory.' }],
    ['Big free blocks (≥16 MiB)', n => n.blocks_16m, 0, '', { key: 'blocks_16m', low: true, hint: 'How many large contiguous pieces are free. Low means fragmented: big allocations can fail even with plenty free.' }],
    ['Compaction scans', n => n.compact_scan_s, 0, '/s', { key: 'compact_scan_s', hint: 'Pages the kernel scanned to defragment memory.' }],
    ['Failed page moves', n => n.migrate_fail_s, 1, '/s', { hint: 'Compaction attempts that failed, usually against memory pinned for the GPU.' }],
    ['Allocation stalls', n => n.alloc_stall_s, 2, '/s', { warnAbove: 0, hint: 'Tasks that had to wait for memory to be reclaimed.' }],
    ['Swapped out', n => n.swap_out_s, 1, '/s', { warnAbove: 0, hint: 'Pages pushed out to swap.' }],
    ['Waiting for memory', n => n.psi_mem, 2, '%', { warnAbove: 5, hint: 'Share of time some task stalled on memory.' }],
    ['OOM kills since boot', n => n.oom_kills, 0, '', { warnAbove: 0, hint: 'Processes the kernel killed for memory.' }],
    ['Disk'],
    ['Engine reads', n => n.eng_read_mb, 1, 'MB/s', { key: 'eng_read_mb', hint: 'Read by the engine container: the on-disk table of this model.' }],
    ['Engine read ops', n => n.eng_iops, 0, '/s', { key: 'eng_iops', hint: 'Read operations per second by the engine.' }],
    ['Waiting for disk, system', n => n.psi_io, 2, '%', { key: 'psi_io', warnAbove: 10, hint: 'Share of time some task stalled on I/O.' }],
    ['SSD temperature', n => n.nvme_c, 0, '°C', { key: 'nvme_c', warnAbove: 80, hint: 'NVMe composite temperature.' }],
    ['SSD free', n => n.disk_free_gb, 0, 'GB', { low: true, hint: 'Free space on the root filesystem.' }],
    ['Board'],
    ['Fans', n => n.fan, 0, 'rpm', { key: 'fan', hint: w => w.fans }],
    ['Network chip', n => n.nic_c, 0, '°C', { key: 'nic_c', warnAbove: 95, hint: 'ConnectX temperature, highest since boot on hover.', title: n => n.nic_peak != null ? `highest ${n.nic_peak} °C` : '' }],
    ['PCIe at full speed', n => { const p = Object.values(n.pcie || {}); return p.length ? `${p.filter(d => d.gt === d.gt_max && d.x === d.x_max).length}/${p.length}` : null; }, null, '', { hint: 'Devices (network, SSD) on their full PCIe link. Hover for the link.', title: n => Object.entries(n.pcie || {}).map(([k, d]) => `${k} ${d.x} lanes ${d.gt}`).join('\n') }],
    ['PCIe errors', n => n.pcie ? Object.values(n.pcie).reduce((a, d) => a + d.aer, 0) : null, 0, '', { warnAbove: 0, hint: 'Corrected and uncorrected PCIe errors since boot.' }],
    ['Network driver health', n => n.devlink ? (n.devlink.unhealthy ? `${n.devlink.unhealthy} bad` : 'healthy') : null, null, '', { hint: 'mlx5 health reporters.' }],
  ];
  const BUILD = [['BIOS', 'bios'], ['GPU driver', 'driver'], ['GPU VBIOS', 'vbios'], ['Network firmware', 'nic_fw'], ['Kernel', 'kernel'], ['Transparent huge pages', 'thp'], ['CPU governor', 'governor'], ['Swappiness', 'swappiness'], ['SSD model', 'ssd'], ['SSD firmware', 'ssd_fw']];
  function table(parent, heads) {  // A table with a head row; gives back its body to fill.
    const t = make('table', 'tb', parent), head = make('tr', '', make('thead', '', t));
    for (const h of heads) make('th', '', head, h);
    return make('tbody', '', t);
  }
  // Everything known about one Spark: the moment on the page and the deep readings, joined.
  function fullNode(name) { return { ...((S && S.nodes.find(n => n.name === name)) || {}), ...((shared.data && shared.data.nodes.find(n => n.name === name)) || {}) }; }
  function paintNodes() {  // The Nodes tab: every reading of every Spark side by side, odd ones marked, and what software and firmware each runs.
    const names = S.cluster.nodes.map(n => n.name), nodes = names.map(fullNode), words = deepWords(nodes, (LIVE || S).edges);  // the hints that say how the machines are built: from what they read
    const body = table(pane, ['', ...names.map(short), '']);
    for (const r of NODE_TABLE) {
      if (r.length === 1) { const g = make('tr', 'g', body); const c = make('td', '', g, r[0]); c.colSpan = names.length + 2; continue; }
      const [label, get, d, unit, o] = r, values = nodes.map(get);
      const tr = make('tr', o.key ? 'can' : '', body), first = make('td', '', tr, label);
      first.title = (typeof o.hint === 'function' ? o.hint(words) : o.hint) + (o.key ? ' Click to plot it over time.' : '');
      if (o.key) tr.addEventListener('click', () => History.plot(label, unit, o.key));
      const nums = values.filter(v => typeof v === 'number'), mid = median(nums);
      values.forEach((v, i) => {
        let cls = '';
        if (typeof v === 'number' && v != null) {
          if (o.warnAbove != null && v > o.warnAbove) cls = o.redAbove != null ? 'ro' : 'am';
          else if (o.warnBelow != null && v < o.warnBelow) cls = 'am';
          else if (o.low && mid && v < mid * .5) cls = 'am';
        }
        const c = make('td', cls, tr, typeof v === 'string' ? v : d == null ? (v ?? '–') : M(v, d));
        if (o.title) c.title = o.title(nodes[i]);
      });
      make('td', 'u', tr, unit);
    }
    const g = make('tr', 'g', body); make('td', '', g, 'Software and firmware').colSpan = names.length + 2;
    for (const [word, key] of BUILD) {
      const tr = make('tr', '', body), values = nodes.map(n => (n.firmware || {})[key]);
      make('td', '', tr, word);
      const seen = new Set(values.filter(Boolean)), differs = seen.size > 1 || (seen.size === 1 && values.some(v => !v));
      values.forEach(v => make('td', differs ? 'am' : 'dimmed', tr, v ?? '–').title = v || '');
      make('td', 'u', tr, differs ? 'differs' : '');
    }
  }
  function paintLinks() {  // The Links tab: every cable once with traffic, pauses and losses, then every RDMA counter that is not zero.
    const cables = shared.data.cables || {}, names = S.cluster.nodes.map(n => n.name), words = deepWords(names.map(fullNode), (LIVE || S).edges);
    const peer = (name, group) => { const n = S.cluster.nodes.find(x => x.name === name), e = S.edges.find(x => x.from === n.rank && x.group === group), to = e && S.cluster.nodes.find(x => x.rank === e.to); return to ? short(to.name) : '?'; };
    section(pane, 'Cables', 'each cable once, seen from the sending end', 'Read from the Ethernet counters of one PCIe function per port: the second function shows the same cable.');
    const body = table(pane, ['Cable', 'Out', 'In', 'Full', 'Stopped', 'Pause/s', 'Fixed bits/s', 'Lanes', 'Lost', 'PCIe', 'Down', 'Drop']);
    const tips = ['', 'Gb/s sent on this cable', 'Gb/s received', words.full, 'Share of time this end was held back by pause frames, then the share it held the other end back. Total since boot on hover.', 'Pause frames sent per second. Total since boot on hover.', 'Bits the forward error correction repaired, per second. Rises on healthy links.', 'Errors per second on each of the two lanes. A big gap between them points at a weak cable or connector.', 'Uncorrectable blocks since boot. Data really lost.', 'Share of the last second the network chip stalled on PCIe, read and write.', 'Real link failures since boot.', 'Packets dropped since boot.'];
    pane.querySelectorAll('.tb:last-of-type th').forEach((th, i) => { th.title = tips[i] || ''; });
    for (const name of names) for (const group of Object.keys(cables[name] || {}).sort()) {
      const c = cables[name][group], tr = make('tr', 'can', body);
      tr.addEventListener('click', () => History.plotCable(name, group));
      make('td', '', tr, `${short(name)} → ${peer(name, group)}`).title = `${name} ${group}`;
      make('td', '', tr, M(c.gb_tx, 1)); make('td', '', tr, M(c.gb_rx, 1));
      const rank = (S.cluster.nodes.find(x => x.name === name) || {}).rank, share = fullShare(c, cableRate((LIVE || S).edges, rank, group));
      make('td', '', tr, share != null ? M(share, 1) + ' %' : '–');  // against the line rate its own link reads
      make('td', c.stop_tx > 1 || c.stop_rx > 1 ? 'am' : '', tr, c.stop_tx == null ? '–' : `${M(c.stop_tx, 2)} / ${M(c.stop_rx, 2)} %`).title = `held back ${c.stop_total_s ?? '?'} s since boot`;
      make('td', '', tr, M(c.pause_tx_s, 1)).title = `${M(c.pause_total)} since boot`;
      make('td', '', tr, M(c.corrected_s));
      const lanes = [c.lane0_s, c.lane1_s], lop = Math.max(...lanes.map(v => v || 0)) > 8 * (Math.min(...lanes.map(v => v || 0)) + 1) && Math.max(...lanes.map(v => v || 0)) > 100;
      make('td', lop ? 'am' : '', tr, `${M(c.lane0_s)} / ${M(c.lane1_s)}`);
      make('td', c.uncorrectable > 0 ? 'ro' : '', tr, M(c.uncorrectable));
      make('td', (c.pci_rd || c.pci_wr) ? 'am' : '', tr, `${M(c.pci_rd)}/${M(c.pci_wr)}`);
      make('td', c.link_down > 0 ? 'am' : '', tr, M(c.link_down));
      make('td', c.discards > 0 ? 'ro' : '', tr, M(c.discards));
    }
    make('p', 'n-note', pane, 'Pause and corrected-bit counters rise on healthy links. Red means data was really lost: uncorrectable blocks or discards. Latency on the wire cannot be read passively; the time the sender was held back is the nearest measure.');
    section(pane, 'Every RDMA counter', 'non-zero only, red when it rose in the last 30 s', words.counters);
    const now = Date.now(), rows = new Map();
    for (const n of shared.data.nodes) for (const dev in n.link_counts || {}) for (const [k, v] of Object.entries(n.link_counts[dev])) { if (v == null || k === 'lifespan') continue; const r = rows.get(k) || rows.set(k, { name: k, per: {}, any: 0 }).get(k); r.per[n.name] = (r.per[n.name] || 0) + v; r.any += v; }
    const shown = [...rows.values()].filter(r => r.any > 0).sort((a, b) => a.name.localeCompare(b.name));
    if (!shown.length) make('p', 'p-note', pane, 'All counters are at zero.');
    else {
      const t2 = table(pane, ['Counter', ...names.map(short)]);
      for (const r of shown) {
        const tr = make('tr', '', t2); make('td', '', tr, r.name);
        for (const n of names) {
          const v = r.per[n], key = r.name + '|' + n, was = rose.get(key);
          if (v != null) rose.set(key, { v, at: was && v > was.v ? now : was ? was.at : 0 });
          const fresh = v != null && rose.get(key).at && now - rose.get(key).at < 30000;
          make('td', fresh ? (/rx_write|duplicate/.test(r.name) ? 'te' : 'ro') : '', tr, M(v));
        }
      }
    }
  }
  function bars(parent, rows, label) {  // A list of horizontal bars, each a share, scaled to the biggest.
    const box = make('div', '', parent), top = Math.max(...rows.map(r => r.share), .01);
    for (const r of rows) {
      const row = make('div', 'hbar', box);
      make('span', '', row, label(r));
      const track = make('span', '', row); make('i', '', track).style.width = (r.share / top * 100).toFixed(1) + '%';
      make('b', '', row, r.share >= .1 ? Math.round(r.share * 100) + '%' : (r.share * 100).toFixed(1) + '%');
    }
  }
  // A two-column list of names and values, with a tooltip where a name has one.
  const pairs = (parent, list) => { const b = make('div', 'n-kv two', parent); for (const [k, v, hint] of list) { const a = make('span', '', b, k); if (hint) a.title = hint; make('span', '', b, v ?? '–'); } };
  function flagsOf(args) {  // The flags of a command line as pairs of name and value; a flag without a value counts as on.
    return (args || '').split(/\s+(?=--)/).filter(p => p.startsWith('--')).map(p => { const name = p.split(/\s+/, 1)[0]; return [name.slice(2), p.slice(name.length).trim() || 'on']; });  // a value may hold spaces
  }
  // The Engine tab: where the time goes, lengths of prompts and answers, where prompt tokens came from, HTTP by route, the cold start and the engine flags.
  function paintEngine() {
    const e = shared.data.engine || {}, st = S.engine;
    if (!e.steps) { make('p', 'p-note', pane, 'Waiting for the engine.'); return; }
    const grid = make('div', 'grid3', pane), col = () => make('div', '', grid);
    const a = col();
    section(a, 'Where the time goes');
    pairs(a, [
      ['Tokens per second', M(st.tok_s, 1), 'Output tokens per second.'], ['Model steps per second', M(st.steps_s, 1)], ['Tokens per step', M(st.tokens_per_step, 2), 'Output tokens per step. More than 1 is speculation working.'],
      ['Steps that made 1 token', pct(st.one_token_share), 'No draft survived in those steps.'], ['Verified draft depth', M(e.spec_depth, 2), 'How far verification got into a draft on average.'],
      ['Reading speed', st.prefill_tok_s != null ? M(st.prefill_tok_s) + ' tok/s' : '–', 'Prompt tokens really computed per second of prefill. Tokens from the cache do not count.'],
      [`GPU power, ${readWord({ read: st.watts_from ?? 0, of: S.nodes.length }, false)}`, M(st.watts) + ' W'], ['Energy per token', st.j_per_token != null ? M(st.j_per_token, 2) + ' J' : '–', 'GPU share only: a Spark has no whole-device power sensor.'],
      ['Preemptions', M(e.preempted)],
    ]);
    section(a, 'Tokens per step', 'share of steps', 'Each bar is the share of steps that produced at most that many tokens. Many 1-token steps mean speculation is not paying off.');
    bars(a, e.steps.filter(r => r.n > 0).slice(0, 12), r => r.le == null ? 'more' : '≤ ' + M(r.le));
    const b = col();
    section(b, 'Prompt length', 'tokens, share of requests');
    bars(b, e.prompt_len.filter(r => r.n > 0).slice(0, 9), r => r.le == null ? 'more' : '≤ ' + size(r.le));
    section(b, 'Actually computed', 'prompt tokens not from cache');
    bars(b, e.computed_len.filter(r => r.n > 0).slice(0, 9), r => r.le == null ? 'more' : '≤ ' + size(r.le));
    section(b, 'Answer length', 'tokens, share of requests');
    bars(b, e.output_len.filter(r => r.n > 0).slice(0, 9), r => r.le == null ? 'more' : '≤ ' + size(r.le));
    const c = col();
    section(c, 'Where prompt tokens came from');
    pairs(c, Object.entries(e.sources).map(([k, v]) => [k.replace(/_/g, ' '), M(v)]));
    section(c, 'Sink rows flagged', 'by rank', 'Counted from the engine log: vllm:sink_* metrics only count committed outputs.');
    pairs(c, Object.entries(e.sink_ranks).sort().map(([k, v]) => ['rank ' + k, M(v)]));
    section(c, 'HTTP by route');
    const hb = table(c, ['Route', '2xx', '4xx', '5xx']);
    for (const h of e.http) { const tr = make('tr', '', hb); make('td', '', tr, h.route.replace('GET none', 'GET (no route)')); for (const k of ['2xx', '4xx', '5xx']) make('td', k !== '2xx' && h.by[k] ? 'am' : '', tr, M(h.by[k])); }
    section(c, 'API server process');
    pairs(c, [['Resident memory', M(e.process.rss_gb, 2) + ' GB'], ['CPU time', M(e.process.cpu_s) + ' s'], ['Open files', M(e.process.fds)], ['Scheduler share limits', e.scheduler_active == null ? null : e.scheduler_active ? 'on' : 'off', 'Prefill compute-share scheduling. These counters stand still while it is off. A dash where the engine sends neither of its figures.']]);
    section(pane, 'Cold start', 'seconds after the container started', 'Read once from the start of the engine log on each Spark.');
    const nodes = S.cluster.nodes.map(n => fullNode(n.name));
    const start = table(pane, ['', ...nodes.map(n => short(n.name)), '']);
    const row = (word, get, unit) => { const tr = make('tr', '', start); make('td', '', tr, word); nodes.forEach(n => make('td', '', tr, get(n) ?? '–')); make('td', 'u', tr, unit); };
    const mark = (n, m) => (((n.startup || {}).marks || {})[m] || {});
    row('Model loaded', n => mark(n, 'loaded').at, 's'); row('Memory free at start', n => mark(n, 'free_at_start').value, 'GB'); row('KV cache built', n => mark(n, 'kv').at, 's');
    row('Serving', n => mark(n, 'ready').at, 's');
    for (const k of ['weights', 'kv_cache', 'workspace', 'cudagraph', 'non_torch_cuda', 'free_memory']) row(k.replace(/_/g, ' '), n => ((n.startup || {}).memory || {})[k], 'GB');
    const head = nodes.find(n => n.head && n.box) || nodes.find(n => n.box);
    if (head) {
      section(pane, 'Engine flags', `${flagsOf(head.box.args).length} on the command line`);
      const box = make('div', 'grid2', pane);
      for (const part of [0, 1]) { const list = flagsOf(head.box.args).filter((_, i) => i % 2 === part); pairs(box, list.map(([k, v]) => [k, v.length > 48 ? v.slice(0, 46) + '…' : v, v])); }
    }
  }
  // A byte count in B, KB, MB or GB.
  const kb = v => v == null ? '–' : v >= 1e9 ? (v / 1e9).toFixed(1) + ' GB' : v >= 1e6 ? (v / 1e6).toFixed(1) + ' MB' : v >= 1e3 ? (v / 1e3).toFixed(0) + ' KB' : v + ' B';
  async function loadReplies() {  // Fetches the answers of the run that a private add-on may offer, at most every 4 s.
    if (Date.now() - repliesAt < 4000) return;
    repliesAt = Date.now();
    try { const r = await fetch('api/replies'); if (r.ok) replies = await r.json(); if (shared.tab === 'requests') paintPane(); } catch { /* restarting */ }
  }
  // The Requests tab: the open connections to the engine as the kernel sees them, and the answers of the run where an add-on supplies them.
  function paintRequests() {
    const list = shared.data.connections || [], none = connectionsWord(shared.data.connections);
    section(pane, 'Open connections to the engine', 'what can be known without touching it', 'From the kernel socket table. vLLM keeps no list of running requests and logs no text, so size, age and bytes are the honest limit here.');
    if (none) make('p', 'p-note', pane, none);
    else {
      const body = table(pane, ['Port', 'State', 'Silent for', 'Received', 'Sent']);
      for (const c of list) {
        const tr = make('tr', '', body), sent = c.bytes_sent || 0, streaming = c.lastsnd < 2500;
        make('td', '', tr, c.port);
        make('td', sent === 0 ? 'te' : streaming ? 'te' : 'dimmed', tr, sent === 0 ? 'request in, no answer yet' : streaming ? 'sending' : 'idle');
        make('td', '', tr, seconds((c.lastrcv || 0) / 1000)); make('td', '', tr, kb(c.bytes_received)); make('td', '', tr, kb(c.bytes_sent));
      }
    }
    loadReplies();
    section(pane, 'Answers of the run', replies.length ? `the last ${replies.length}, private add-on` : 'needs a private add-on', 'What the model wrote. vLLM itself never shows this; a local add-on can read it from the run\'s own files.');
    if (!replies.length) { make('p', 'n-note', pane, 'The open-source version never shows the text of answers: vLLM lists no running requests, and nothing here reads them. Only a local add-on that reads your own result files can.'); return; }
    const grid = make('div', 'grid2', pane), left2 = make('div', '', grid), right2 = make('div', '', grid);
    const body = table(left2, ['Case', 'Finish', 'Seconds', 'Prompt', 'Cached', 'Output', 'Thinking']);
    replies.forEach((r, i) => {
      const tr = make('tr', 'can' + (i === replyPick ? ' pick' : ''), body), u = r.usage || {};
      tr.addEventListener('click', () => { replyPick = i; paintPane(); });
      make('td', '', tr, `${r.intern ? 'internal ' : ''}${r.id ?? i}`); make('td', r.finish && r.finish !== 'stop' ? 'am' : '', tr, r.finish ?? '–');
      make('td', '', tr, M(r.seconds, 1)); make('td', '', tr, M(u.prompt_tokens)); make('td', '', tr, M(u.cached_tokens)); make('td', '', tr, M(u.completion_tokens)); make('td', '', tr, u.reasoning_tokens != null ? M(u.reasoning_tokens) : r.reasoning_chars ? M(r.reasoning_chars) + ' ch' : '–');
    });
    const picked = replies[Math.min(replyPick, replies.length - 1)];
    if (picked) {
      const meta = make('p', 'n-note', right2, '');
      meta.textContent = `Case ${picked.id ?? ''}${picked.variant ? ' · ' + picked.variant : ''}${picked.part ? ' · part ' + picked.part : ''}${picked.model ? ' · ' + picked.model : ''}${picked.error ? ' · error: ' + picked.error : ''}`;
      make('div', 'r-text', right2, picked.reply ?? '');
    }
  }
  function paintSync() {  // The In sync tab: the environment of the engine, Spark against Spark; hidden values only say same or different.
    const rows = shared.data.env || [], names = S.cluster.nodes.map(n => n.name);
    const off = rows.filter(r => !r.same);
    section(pane, 'Engine environment', `${rows.length} variables, ${off.length} differ`, 'Compared node against node. Only harmless settings show a value. Anything that could be a key or a password shows only same or different; its value never reaches this page or any file.');
    if (!rows.length) { make('p', 'p-note', pane, 'No container environment read yet.'); return; }
    const tools = make('div', 'n-tools', pane), only = make('button', 'n-btn', tools, 'Differences only');
    only.type = 'button'; only.setAttribute('aria-pressed', String(!!paintSync.only));
    only.addEventListener('click', () => { paintSync.only = !paintSync.only; paintPane(); });
    const body = table(pane, ['Variable', ...names.map(short)]);
    for (const r of paintSync.only ? off : rows) {
      const tr = make('tr', '', body); const td = make('td', r.same ? '' : 'am', tr, r.name); td.title = r.hidden ? 'Value hidden: only compared.' : '';
      for (const n of names) {
        const v = r.per[n] ?? 'missing';
        const shown = r.hidden ? (v === 'same' ? '= hidden' : v === 'other' ? '≠ different' : 'missing') : v;
        make('td', r.same ? 'dimmed' : v === 'missing' || v === 'other' ? 'ro' : 'am', tr, shown.length > 44 ? shown.slice(0, 42) + '…' : shown).title = shown;
      }
    }
  }
  function paintPane() {  // Repaints the open deep tab from the newest answer and keeps how far it was scrolled.
    if (!S || !shared.data || shared.tab === 'live' || shared.tab === 'history') return;
    const top = pane.scrollTop;
    pane.textContent = '';
    ({ nodes: paintNodes, links: paintLinks, engine: paintEngine, requests: paintRequests, sync: paintSync })[shared.tab]();
    pane.scrollTop = top;
  }
  const History = (() => {
    const RANGES = [['30 min', 1800], ['2 h', 7200], ['6 h', 21600], ['24 h', 86400], ['7 days', 604800], ['30 days', 2592000]];
    const COLORS = ['var(--violet)', 'var(--teal)', 'var(--amber)', 'var(--rose)'];
    let span = 7200, end = null, extra = [], timer2 = 0, got = null, visible = false, tracks = [], asking = 0;
    const namesAll = () => S.cluster.nodes.map(n => n.name);  // The names of all Sparks.
    const per = key => namesAll().map(n => n + '.' + key);  // The trace of one reading for every Spark.
    const cross = make('div', '', document.body), tip = make('div', '', document.body), shade = make('div', '', document.body);
    cross.id = 'h-cross'; tip.id = 'h-tip'; shade.id = 'h-brush'; cross.hidden = tip.hidden = shade.hidden = true;
    function base() {  // The charts every history starts with: speed, requests, caches, speculation, energy, and power, heat and clock per Spark.
      const N = namesAll().map(short);
      return [
        { name: 'Tokens per second', unit: 'tok/s', keys: ['engine.tok_s', 'engine.prompt_tok_s'], labels: ['written', 'read'], peak: true },
        { name: 'Requests', unit: '', keys: ['engine.running', 'engine.waiting'], labels: ['running', 'waiting'] },
        { name: 'Cache', unit: '%', scale: 100, top: 100, keys: ['engine.kv', 'engine.prefix'], labels: ['KV full', 'prefix reused'] },
        { name: 'Speculation', unit: '', keys: ['engine.one_token_share', 'engine.accepted'], labels: ['1-token steps', 'accepted'], top: 1 },
        { name: 'Energy per token', unit: 'J', keys: ['engine.j_per_token'], labels: ['GPU share'] },
        { name: 'GPU power', unit: 'W', keys: per('w'), labels: N },
        { name: 'GPU temperature', unit: '°C', keys: per('gpu_c'), labels: N, tight: true },
        { name: 'GPU clock', unit: 'MHz', keys: per('mhz'), labels: N, tight: true },
        { name: 'Time at power cap', unit: '%', keys: per('cap_pct'), labels: N },
        { name: 'Engine disk reads', unit: 'MB/s', keys: per('eng_read_mb'), labels: N },
        { name: 'Big free blocks', unit: '', keys: per('blocks_16m'), labels: N },
      ];
    }
    // A moment as hours and minutes, with the date when asked.
    const hhmm = (t, wide) => new Date(t * 1000).toLocaleString('en-GB', wide ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
    async function load() {  // Asks the server for the stretch on show and draws it; while it ends now it asks again every 10 s or every minute.
      if (!S) return;
      tracks = [...extra, ...base()];
      const to = end ?? Date.now() / 1000, keys = [...new Set(tracks.flatMap(t => t.keys))], mine = ++asking, wide = span;
      try {
        const res = await fetch(`api/history?keys=${encodeURIComponent(keys.join(','))}&from=${to - wide}&to=${to}&points=720&events=1`);
        if (res.ok) { const body = await res.json(); if (mine !== asking) return; got = { ...body, from: to - wide, to, wide }; if (visible) draw(); }
      } catch { /* restarting */ }
      clearTimeout(timer2);
      if (visible && end == null) timer2 = setTimeout(load, span <= 7200 ? 10000 : 60000);
    }
    // Draws the history: the buttons for the stretch, one chart per track with a crosshair that reads every line, and drag to zoom.
    function draw() {
      if (!visible) return;
      const keepScroll = pane.scrollTop;
      pane.textContent = '';
      const tools = make('div', 'n-tools', pane);
      for (const [word, sec] of RANGES) { const b = make('button', 'n-btn', tools, word); b.type = 'button'; b.setAttribute('aria-pressed', String(span === sec)); b.addEventListener('click', () => { span = sec; end = null; load(); }); }
      const earlier = make('button', 'n-btn', tools, '◀ earlier'); earlier.type = 'button'; earlier.addEventListener('click', () => { end = (end ?? Date.now() / 1000) - span / 2; load(); });
      const later = make('button', 'n-btn', tools, 'later ▶'); later.type = 'button'; later.disabled = end == null; later.addEventListener('click', () => { const next = (end ?? 0) + span / 2; end = next >= Date.now() / 1000 - 5 ? null : next; load(); });
      const nowB = make('button', 'n-btn', tools, 'now'); nowB.type = 'button'; nowB.disabled = end == null; nowB.addEventListener('click', () => { end = null; load(); });
      const store = shared.data && shared.data.store;
      make('span', '', tools, got ? `${got.tier === 'raw' ? 'every sample' : got.tier === 'mixed' ? 'every sample, earlier as one-minute averages' : got.tier === 'memory' ? 'memory only, since this start' : 'one-minute averages'}${store ? ` · kept on disk since ${hhmm(store.first || got.from, true)}, ${(store.bytes / 1e6).toFixed(0)} MB` : ''}` : 'loading…');
      make('span', '', tools, 'drag to zoom');
      if (!got) return;
      const events = got.events || [];
      tracks.forEach((track, index) => {
        const row = make('div', 'h-row', pane), head = make('div', 'h-name', row), box = make('div', 'h-chart', row);
        head.appendChild(document.createTextNode(track.name + (track.unit ? ` (${track.unit})` : '')));
        if (track.user) { const x = make('button', '', head, '✕'); x.title = 'Remove'; x.addEventListener('click', () => { extra = extra.filter(t => t !== track); load(); }); }
        track.labels.forEach((word, i) => {  // the mark of every line: its colour, past the fourth line with the pattern of its dashes
          const line = make('small', '', head), mark = make('i', '', line), border = lineKind(i)[1];
          mark.style.background = COLORS[i % 4];
          if (border) Object.assign(mark.style, { background: 'none', width: '12px', height: '0', borderRadius: '0', borderTop: `3px ${border} ${COLORS[i % 4]}` });
          line.appendChild(document.createTextNode(word));
        });
        const svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 1000 100'); svg.setAttribute('preserveAspectRatio', 'none'); box.appendChild(svg);
        const scale = track.scale || 1, all = track.keys.flatMap(k => (got.series[k] || []).filter(v => v != null).map(v => v * scale));
        const top = track.top ?? (track.tight ? Math.max(...all, 1) + 1 : Math.max(...all, .001) * 1.12);
        const bot = track.tight && all.length ? Math.max(0, Math.min(...all) - 2) : 0;
        const gap = (got.tier === 'raw' ? S.identity.interval * 8 : 240) + got.wide / 720 * 2.5;
        track.keys.forEach((key, i) => {
          const vals = got.series[key] || [];
          let d = '', last = null;
          vals.forEach((v, j) => {
            if (v == null) return;
            const x = (got.t[j] - got.from) / got.wide * 1000, y = 100 - ((v * scale - bot) / (top - bot || 1)) * 96 - 2;
            d += (last == null || got.t[j] - last > gap ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1);
            last = got.t[j];
          });
          if (!d) return;
          const line = document.createElementNS(SVG, 'path'); line.setAttribute('d', d); line.setAttribute('stroke', COLORS[i % 4]);
          if (lineKind(i)[0]) line.setAttribute('stroke-dasharray', lineKind(i)[0]);  // the fifth line on: the colours again, dashed
          svg.appendChild(line);
        });
        if (index === 0) for (const e of events) if (e.t > got.from) { const tick = document.createElementNS(SVG, 'line'), x = (e.t - got.from) / got.wide * 1000; for (const [a, v] of [['x1', x], ['x2', x], ['y1', 0], ['y2', 14], ['stroke', e.level === 'bad' ? 'var(--rose)' : e.level === 'warn' ? 'var(--amber)' : 'rgba(255,255,255,.35)']]) tick.setAttribute(a, v); tick.setAttribute('vector-effect', 'non-scaling-stroke'); const title = document.createElementNS(SVG, 'title'); title.textContent = `${hhmm(e.t, true)}${e.node ? ' ' + short(e.node) : ''}: ${e.text}`; tick.appendChild(title); svg.appendChild(tick); }
        const timeAt2 = ev => { const b = box.getBoundingClientRect(); return got.from + clamp((ev.clientX - b.left) / b.width) * got.wide; };
        box.addEventListener('mousemove', ev => {
          if (History.drag) return;
          const b = box.getBoundingClientRect(), when = timeAt2(ev);
          let best = 0; for (let k = 0; k < got.t.length; k++) if (Math.abs(got.t[k] - when) < Math.abs(got.t[best] - when)) best = k;
          cross.hidden = tip.hidden = false;
          cross.style.cssText = `left:${ev.clientX}px;top:${pane.getBoundingClientRect().top}px;height:${pane.clientHeight}px`;
          const lines = [hhmm(got.t[best], true), ...track.keys.map((k, i) => { const v = (got.series[k] || [])[best], p = (got.peak[k] || [])[best]; return `${track.labels[i].padEnd(12)} ${v == null ? '–' : (v * scale).toFixed(v * scale < 10 ? 2 : 1)}${got.tier !== 'raw' && p != null && track.peak ? '  peak ' + (p * scale).toFixed(0) : ''}`; })];
          tip.textContent = lines.join('\n');
          tip.style.left = Math.min(ev.clientX + 12, innerWidth - 230) + 'px'; tip.style.top = (ev.clientY + 14) + 'px';
        });
        box.addEventListener('mouseleave', () => { cross.hidden = tip.hidden = true; });
        box.addEventListener('pointerdown', ev => { History.drag = { a: timeAt2(ev), x: ev.clientX, top: pane.getBoundingClientRect().top }; box.setPointerCapture(ev.pointerId); cross.hidden = tip.hidden = true; });
        box.addEventListener('pointermove', ev => { const dr = History.drag; if (!dr) return; shade.hidden = false; shade.style.cssText = `left:${Math.min(dr.x, ev.clientX)}px;width:${Math.abs(ev.clientX - dr.x)}px;top:${dr.top}px;height:${pane.clientHeight}px`; });
        box.addEventListener('pointerup', ev => { const dr = History.drag; History.drag = null; shade.hidden = true; if (dr && Math.abs(ev.clientX - dr.x) > 5) { const b2 = timeAt2(ev); span = Math.max(60, Math.abs(b2 - dr.a)); end = Math.max(b2, dr.a); load(); } });
      });
      const axis = make('div', 'h-axis', pane);
      for (let i = 0; i <= 6; i++) make('span', '', axis, hhmm(got.from + got.wide * i / 6, got.wide > 86400));
      pane.scrollTop = keepScroll;
    }
    return {
      drag: null,
      open() { visible = true; got = null; pane.textContent = ''; load(); },
      close() { visible = false; clearTimeout(timer2); cross.hidden = tip.hidden = shade.hidden = true; },
      plot(label, unit, key) { const N = namesAll().map(short); extra = [{ name: label, unit, keys: per(key), labels: N, user: true }, ...extra.filter(t => t.name !== label)]; setTab('history'); },
      plotCable(name, group) { const label = `${short(name)} ${group} sender stopped`; extra = [{ name: label, unit: '%', keys: [`${name}.${group}.stop_pct`], labels: ['stopped'], user: true }, ...extra.filter(t => t.name !== label)]; setTab('history'); },
    };
  })();
  shared.History = History;  // seam
  return {
    toggle,
    isOpen: () => shared.open,
    isPaused: () => shared.paused,
    tab: id => { if (!NEUTRAL && TABS.some(t => t[0] === id)) setTab(id); },
    key(e) {
      if (/^[1-7]$/.test(e.key)) { setTab(TABS[+e.key - 1][0]); return; }
      if (e.key === '/') { e.preventDefault(); filterEl.focus(); filterEl.select(); }
      else if (e.key === ' ' && !(e.target.matches && e.target.matches('button'))) { e.preventDefault(); setPaused(!shared.paused); }
    },
    tick() { if (shared.open) { paintHead(); if (shared.tab === 'live') paintTime(); } },
  };
}  // seam
