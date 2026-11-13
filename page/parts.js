// What each part of an open Spark is doing, from the same measurements as everything else.
'use strict';
/* ---- what each part of a Spark is doing, from the same measurements as everything else ---- */
const ghz = v => v == null ? '–' : (v / 1000).toFixed(2) + ' GHz';  // A clock in GHz from MHz, a dash when it was not read.
const deg = v => v == null ? '–' : Math.round(v) + ' °C';  // A temperature in whole degrees, a dash when it was not read.
const gbs = (v, d = 0) => v == null ? '–' : v.toFixed(d) + ' GB';  // A size in GB, a dash when it was not read.
// A disk rate in MB/s, or GB/s from a thousand on, a dash when it was not read.
const rate = v => v == null ? '–' : v >= 1000 ? (v / 1000).toFixed(1) + ' GB/s' : v < 10 ? v.toFixed(1) + ' MB/s' : Math.round(v) + ' MB/s';
const nodeEdges = n => S.edges.filter(e => e.from === n.rank);  // The links that leave one Spark.
// Memory in use on a Spark in GB, null unless total and free were both read.
const used = n => n.mem_total_gb && n.mem_free_gb != null ? n.mem_total_gb - n.mem_free_gb : null;
// The links of a Spark, each with the name of its far end as the sheet says it (farEnd): the Spark at its other end, with the port where two of them lead to the same Spark; its port alone where nobody is at the other end.
const edgeRows = n => { const mine = nodeEdges(n); return mine.map(e => ({ e, name: farEnd(e, mine, S.cluster.nodes) || e.group })); };
// One meter and one half-hour chart per link of a Spark. No bar where the rate the link runs at is not known (looking back it is not kept) or a way of its traffic was not read: a bar would stand against a made-up rate, or count the way nobody read as carrying nothing.
function portCharts(box, n, word) {
  for (const { e, name } of edgeRows(n)) {
    const k = `${e.group}.tx`, r = `${e.group}.rx`;
    const text = `${fixed(e.gbps, 1)} out · ${fixed(e.rx, 1)} in Gb/s${linkNote(e, ' · ')}`;
    if (S.past || !e.capacity || e.gbps == null || e.rx == null) { const row = make('div', 'memhead', box); make('span', '', row, `${word} to ${name}`); make('span', '', row, text); }
    else meter(box, `${word} to ${name}`, (e.gbps + e.rx) / 2, e.capacity, text);
    chart2(box, `Traffic to ${name}, 30 min`, [k, r], n);
  }
}
/* what each part of a Spark is doing, from the same measurements as everything else */
const PART_INFO = {
  gb10_die_gpu: { title: 'GB10 GPU', short: n => `${ghz(n.mhz)} · ${deg(n.gpu_c)} · ${fixed(n.util, 0)} %`,
    show: (box, n) => {
      hero(box, [[`${fixed(n.util, 0)}`, '% busy'], [n.mhz == null ? '–' : (n.mhz / 1000).toFixed(2), n.mhz_max ? `of ${(n.mhz_max / 1000).toFixed(2)} GHz` : 'GHz'], [fixed(n.gpu_c, 0), '°C']]);
      meter(box, 'Clock', n.mhz, n.mhz_max || 3000, ghz(n.mhz));
      chart(box, 'GPU busy, 30 min', 'util', `${fixed(n.util, 0)} %`, n);
      chart(box, 'Clock, 30 min', 'mhz', ghz(n.mhz), n);
      chart(box, 'Temperature, 30 min', 'gpu_c', deg(n.gpu_c), n);
      make('p', 'p-note', box, throttleWord(n));
    } },
  gb10_die_cpu: { title: 'GB10 CPU', short: n => `${fixed(n.cpu_pct, 0)} % busy · board ${deg(n.cpu_c)}`,
    show: (box, n) => {
      hero(box, [[`${fixed(n.cpu_pct, 0)}`, '% busy'], [fixed(n.cpu_c, 0), 'board °C'], [String((n.cores || []).length || '–'), 'cores']]);
      make('p', 'p-sub', box, 'Every core, right now');
      coreGrid(box, n);
      chart(box, 'CPU busy, 30 min', 'cpu_pct', `${fixed(n.cpu_pct, 0)} %`, n);
      chart(box, 'Board temperature, 30 min', 'cpu_c', deg(n.cpu_c), n);
    } },
  gb10_package: { title: 'GB10 package', short: n => n.w == null ? '–' : `GPU ${Math.round(n.w)} W`,
    show: (box, n) => {
      hero(box, [[fixed(n.w, 0), 'GPU watts'], [fixed(n.gpu_c, 0), 'GPU °C'], [`${fixed(n.util, 0)}`, '% busy']]);
      if (S.past) { const row = make('div', 'memhead', box); make('span', '', row, 'GPU power'); make('span', '', row, `${fixed(n.w, 0)} W`); }  // looking back no limit is kept: no bar against a limit nobody recorded
      else meter(box, 'GPU power', n.w, n.w_limit || 120, n.w_limit == null ? `${fixed(n.w, 0)} W` : `${fixed(n.w, 0)} of ${fixed(n.w_limit, 0)} W`);  // the GB10 reports no power limit: the bar then stands against 120 W
      chart(box, 'GPU power, 30 min', 'w', `${fixed(n.w, 0)} W`, n);
      make('p', 'p-note', box, GPU_POWER_NOTE);
    } },
  lpddr: { title: 'LPDDR5X memory, 8 chips', short: n => used(n) == null ? '–' : `${gbs(used(n))} of ${gbs(n.mem_total_gb)} in use`,
    show: (box, n) => {
      hero(box, [[fixed(used(n), 0), 'GB in use'], [fixed(n.mem_free_gb, 1), 'GB free'], [fixed(n.psi, 0), '% stalled']]);
      memBar(box, n);
      const model = (n.apps || []).reduce((a, x) => a + x.gb, 0);
      if (model) make('p', 'p-note', box, `The model holds ${model.toFixed(1)} GB.`);
      chart(box, 'Free memory, 30 min', 'mem_free_gb', `${fixed(n.mem_free_gb, 1)} GB`, n);
    } },
  cx7: { title: 'ConnectX-7', short: n => `${n.net == null ? '–' : n.net.toFixed(n.net >= 100 ? 0 : 1) + ' Gb/s'} · ${linkErrorsWord(nodeEdges(n), S.past)}`,
    show: (box, n) => {
      hero(box, [[n.net == null ? '–' : n.net.toFixed(n.net >= 100 ? 0 : 1), 'Gb/s total'], [fixed(n.nic_c, 0), 'chip °C'], [String(linkErrors(nodeEdges(n)) ?? '–'), 'links with errors']]);
      portCharts(box, n, 'Link');
      chart(box, 'Chip temperature, 30 min', 'nic_c', deg(n.nic_c), n);
      counters(box, n);
    } },
  qsfp_cage: { title: 'QSFP ports', short: n => linksUpWord(nodeEdges(n), S.past),
    show: (box, n) => {
      const e = nodeEdges(n);
      hero(box, [[linksUp(e) == null ? '–' : `${linksUp(e)}/${e.length}`, 'links up'], [String(e[0] ? fixed(e[0].capacity, 0) : '–'), 'Gb/s per port'], [fixed(busiestPort(e), 1), 'Gb/s busiest port']]);
      portCharts(box, n, 'Port');
      counters(box, n);
    } },
  ssd_m2: { title: 'M.2 2242 SSD', short: n => n.disk_free_gb == null ? '' : `${gbs(n.disk_free_gb)} free · ${deg(n.nvme_c)}`,
    show: (box, n) => {
      hero(box, [[rate(n.disk_read).split(' ')[0], `${rate(n.disk_read).split(' ')[1] || ''} read`], [rate(n.disk_write).split(' ')[0], `${rate(n.disk_write).split(' ')[1] || ''} write`], [fixed(n.nvme_c, 0), '°C']]);
      meter(box, 'Used', n.disk_total_gb == null || n.disk_free_gb == null ? null : n.disk_total_gb - n.disk_free_gb, n.disk_total_gb, `${fixed(n.disk_free_gb, 0)} GB free of ${fixed(n.disk_total_gb, 0)} GB`);  // looking back the free space is not kept: its line, and no bar that calls the SSD full
      chart(box, 'Read, 30 min', 'disk_read', rate(n.disk_read), n);
      chart(box, 'Write, 30 min', 'disk_write', rate(n.disk_write), n);
      chart(box, 'Temperature, 30 min', 'nvme_c', deg(n.nvme_c), n);
    } },
  thermal_module: { title: 'Cold plate and heat pipes', short: n => 'GPU ' + deg(n.gpu_c),
    show: (box, n) => {
      hero(box, [[fixed(n.gpu_c, 0), 'GPU °C'], [fixed(n.cpu_c, 0), 'board °C'], [fixed(n.fan, 0), 'RPM fans']]);
      chart(box, 'GPU temperature, 30 min', 'gpu_c', deg(n.gpu_c), n);
      chart(box, 'Fan speed, 30 min', 'fan', `${fixed(n.fan, 0)} RPM`, n);
      make('p', 'p-note', box, 'Takes the heat from the GB10 to the fin stack.');
    } },
  fin_stack: { title: 'Heatsink fin stack', short: n => 'Fans ' + (n.fan == null ? '–' : Math.round(n.fan).toLocaleString('en-US') + ' RPM'),
    show: (box, n) => {
      hero(box, [[fixed(n.fan, 0), 'RPM fans'], [fixed(n.gpu_c, 0), 'GPU °C'], [fixed(n.w, 0), 'GPU watts']]);
      chart(box, 'Fan speed, 30 min', 'fan', `${fixed(n.fan, 0)} RPM`, n);
      make('p', 'p-note', box, 'Air from the two blowers carries the heat out here.');
    } },
  fan: { title: null, short: n => (n.fans || []).length ? fanSpeeds(n).join(' / ') + ' RPM' : '',
    show: (box, n) => {
      const f = fanSpeeds(n);  // each fan in its place: one that was not read is a dash, not a fan at 0
      hero(box, f.length ? f.map((v, i) => [v, `RPM, fan ${i + 1}`]).concat([[fixed(n.gpu_c, 0), 'GPU °C']]) : [['–', 'no fan reading yet']]);
      chart(box, 'Fan speed, 30 min', 'fan', n.fan == null ? '–' : `${fixed(n.fan, 0)} RPM`, n);
      chart(box, 'GPU temperature, 30 min', 'gpu_c', deg(n.gpu_c), n);
      if (fanSetter(n)) make('p', 'p-note', box, `Speed set by ${fanSetter(n)}.`);
      make('p', 'p-note', box, 'The machine reports two fans but not which side is which. The spinning you see runs at the measured speed, slowed down.');
    } },
};
function hero(box, cells) {  // The big numbers at the top of a part: value and word, side by side.
  const g = make('div', 'hero', box);
  for (const [value, word] of cells) { const c = make('div', '', g); make('b', '', c, value); make('span', '', c, word); }
}
function meter(box, word, value, max, text) {  // A bar of a value against its most, with its word and its figure. A value nobody read gets its line and no bar: an empty bar would say it is nothing.
  const row = value == null ? box : make('div', 'meter', box), head = make('div', 'memhead', row);
  make('span', '', head, word); make('span', '', head, text);
  if (value == null) return;
  const bar = make('div', 'bar', row), fill = make('i', 'm', bar);
  fill.style.width = (clamp(value / (max || 1)) * 100).toFixed(1) + '%';
}
function chart2(parent, word, keys, n) {  // A half-hour chart of two traces on one scale, sent and received, with the peak in its head.
  const box = make('div', 'chart', parent);
  const series2 = keys.map(k => series.get(n.name + '.' + k));
  const peak = peakOf(series2), hi = Math.max(peak ?? 0, 1), head = make('span', '', box);  // the scale spans 1 Gb/s at least, so a quiet link is a flat line at its foot; the peak in the head is what was read
  head.appendChild(document.createTextNode(word)); make('b', '', head, peak == null ? 'no reading' : `peak ${peak.toFixed(peak >= 100 ? 0 : 1)} Gb/s`);
  const svg = draw('svg', { class: 'trace', viewBox: '0 0 100 30', preserveAspectRatio: 'none', 'aria-hidden': 'true' }, box);
  series2.forEach((s0, i) => { const path = draw('path', { d: tracePath(s0, S.t - WINDOW, 0, hi * 1.1, 30, S.identity.interval * 3) }, svg); if (i) path.style.stroke = 'var(--teal)'; });
}
function counters(box, n) {  // The error and pause counters of the links that moved since the last look, at most six. Where nobody read them, or looking back, where they are not kept, it says that: "None." is a reading.
  const list = Object.entries(n.links || {}).flatMap(([dev, c]) => Object.entries(c).filter(([, v]) => v > 0).map(([k, v]) => [dev, k, v]));
  make('p', 'p-sub', box, 'Counters that moved in the last 15 s');
  if (!list.length) { make('p', 'p-note', box, n.links ? 'None.' : S.past ? 'Not recorded.' : 'Not read.'); return; }
  for (const [dev, k, v] of list.slice(0, 6)) { const row = make('div', 'memhead', box); make('span', '', row, `${dev}: ${k.replace(/_/g, ' ')}`); make('span', '', row, '+' + v.toLocaleString('en-US')); }
}
function coreGrid(box, n) {  // Every CPU core as a cell coloured by how busy it is, the fast cores apart from the efficient ones.
  const caps = n.capacity || [], cut = caps.length ? (Math.min(...caps) + Math.max(...caps)) / 2 : 0, line = make('div', 'cores', box);
  for (const [word, fits] of cut ? [['X925', c => c >= cut], ['A725', c => c < cut]] : [['Cores', () => true]]) {
    const group = make('div', '', line); make('span', '', group, word);
    const cells = make('div', 'n-cells', group);
    (n.cores || []).forEach((v, i) => { if (caps.length && !fits(caps[i])) return; const cell = make('i', '', cells); if (v != null) cell.style.background = `hsl(${250 - v * 2.2} 85% ${16 + v * .44}%)`; cell.title = `core ${i}: ${v == null ? 'n/a' : v + ' %'}`; });
  }
}
// The entry a part reads its numbers from: the eight memory chips share one, the two fans another.
const partKey = name => name.startsWith('lpddr') ? 'lpddr' : name.startsWith('fan_') ? 'fan' : name;
// The title of a part, or the fallback where the part has none of its own.
function partTitle(name, fallback) { const info = PART_INFO[partKey(name)]; return (info && info.title) || fallback; }
// The short line a part carries on its label, empty while its Spark does not answer.
function partShort(name, n) { const info = PART_INFO[partKey(name)]; return info && n.live ? info.short(n) : ''; }
const PASSIVE = {
  shell: ['Aluminium shell. It closes the machine and spreads heat over its whole surface.', n => [[fixed(n.cpu_c, 0), 'board °C']]],
  foam_front: ['Metal foam on the front: the air comes in here. The pores glow with the GPU power of this Spark.', n => [[fixed(n.w, 0), 'GPU watts']]],
  foam_rear: ['Metal foam on the back: the warm air leaves here, above the ports.', n => [[fixed(n.w, 0), 'GPU watts']]],
  grip_left: ['Front grip. No sensor.', () => []],
  grip_right: ['Front grip. No sensor.', () => []],
  io_plate: ['The ports on the back: power, USB-C, HDMI, 10G Ethernet and two QSFP ports for the ring.', n => [[fixed(n.net, 1), 'Gb/s on the ring']]],
  pcb: ['The mainboard carries everything else.', n => [[fixed(n.cpu_c, 0), 'board °C'], [`${fixed(n.cpu_pct, 0)}`, '% CPU'], [`${fixed(n.util, 0)}`, '% GPU']]],
  base_plate: ['Aluminium base plate. No sensor.', () => []],
  bottom_cover: ['Aluminium bottom cover. No sensor.', () => []],
  bottom_pad: ['Magnetic foot of the machine. No sensor.', () => []],
  wifi_card: ['The Wi-Fi card. The ring does not use it.', n => [[fixed(n.wifi_c, 0), '°C']]],
};
function paintPart(n) {  // The panel of one part of the open Spark: its numbers and charts, or a sentence for a part without a sensor.
  const info = PART_INFO[partKey(VP)], plain = PASSIVE[VP];
  make('button', 'back', panel, `‹ ${n.name}`).addEventListener('click', () => setPart(null));
  make('h2', '', panel, partTitle(VP, Scene.label(VP)));
  if (info && info.show) info.show(panel, n);
  else if (plain) { const cells = plain[1](n); if (cells.length) hero(panel, cells); make('p', 'p-note', panel, plain[0]); }
  else make('p', 'p-note', panel, 'No live reading for this part.');
}

