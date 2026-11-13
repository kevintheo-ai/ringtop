// The rules that decide what the page may claim: plain functions of the data that touch neither the page nor the scene, so the checks run them through node.
'use strict';
const TRACED = ['w', 'gpu_c', 'mem_free_gb', 'net', 'util', 'mhz', 'cpu_pct', 'cpu_c', 'disk_read', 'disk_write', 'fan', 'nvme_c', 'nic_c'];
function hoopsWord(drafts) {  // the sign beside the hoops on the beam: the share of drafts that survive at the first and the last position
  const kept = drafts.filter(v => v != null);
  return kept.length > 1 ? `drafts kept ${Math.round(kept[0] * 100)} → ${Math.round(kept[kept.length - 1] * 100)} %` : '';
}
/* what a link, a set of links and a GPU say about themselves. A state that was not read or not recorded is null: neither fine nor broken */
const linkNote = (e, sep) => `${e.up === false ? sep + 'down' : ''}${e.errors ? sep + 'errors' : ''}`;
// How many of these links are up, null when the state of one was not read.
const linksUp = links => links.some(x => x.up == null) ? null : links.filter(x => x.up).length;
// The same in words for a label: so many of so many links up. A state nobody knows was not read, at a moment of the past (past) not recorded.
const linksUpWord = (links, past) => !links.length ? '–' : linksUp(links) == null ? `link state not ${past ? 'recorded' : 'read'}` : `${linksUp(links)} of ${links.length} links up`;
// How many of these links had errors lately: errors that were read are counted, whatever another link could say. null where no link was read to have any and one was not read: that is no count of none.
const linkErrors = links => links.filter(x => x.errors).length || (links.some(x => x.errors == null) ? null : 0);
// The same in words: errors, no errors, or that nobody knows: not read, at a moment of the past (past) not recorded.
const linkErrorsWord = (links, past) => linkErrors(links) == null ? `errors not ${past ? 'recorded' : 'read'}` : linkErrors(links) ? 'errors' : 'no errors';
// Whether a GPU is slowing down and why, as a sentence; reasons that were not read are said as not read.
const throttleWord = n => n.throttle == null ? 'No reading of the throttle reasons.' : n.throttle.length ? 'Slowing down: ' + n.throttle.join(', ') + '.' : 'Not throttling.';
// What a tile says about free memory at the memory guard: below its line, up to 2 GB above it, else nothing. Unread is neither.
const guardWord = (free, guard) => guard == null || free == null || free > guard + 2 ? '' : `${free < guard ? 'Below' : 'Near'} the ${guard} GB memory guard`;
const linkRate = e =>`${e.gbps == null ? '–' : e.gbps.toFixed(1)}${e.capacity == null ? '' : ' of ' + e.capacity.toFixed(0)} Gb/s`;  // looking back, the speed a link ran at is not kept: then only what flowed
// The note under a figure of the past: its word and that it is as recorded, or that it was not recorded.
const asRecorded = (v, word) => v == null ? 'not recorded' : word + ', as recorded';
function linkWays(edges, a, b) {  // what flows from a to b and from b to a on the cables between them: each direction as its sender counts it, or else as the other end receives it. No end names the port at the far end, so the cables of a pair cannot be matched one by one: an end counts where it sees every cable of the pair and read each one, and where neither end does the direction is unknown, never a part of it called the whole
  const ab = edges.filter(e => e.from === a && e.to === b), ba = edges.filter(e => e.from === b && e.to === a);  // two Sparks alone share two cables: every cable counts
  const whole = (list, key, n) => list.length && list.length === n && list.every(e => e[key] != null) ? list.reduce((s, e) => s + e[key], 0) : null;
  const way = (out, back) => { const n = Math.max(out.length, back.length); return whole(out, 'gbps', n) ?? whole(back, 'rx', n); };
  return [way(ab, ba), way(ba, ab)];
}
function chipWord(edges, a, b) {  // the label of the cable between two Sparks in the scene: the fuller direction in Gb/s and how full it is, one figure against the same rate, then errors or down. Two Sparks alone share two cables: a direction carries what both carry, against the rate of both
  const edge = (edges || []).filter(e => (e.from === a && e.to === b) || (e.from === b && e.to === a));
  const ways = linkWays(edge, a, b).filter(v => v != null);  // both directions, also when only one end was read
  const oneWay = edge.filter(e => e.from === (edge[0] || {}).from), cap = oneWay.reduce((sum, e) => sum + (e.capacity || 0), 0);  // what the cables of this pair carry in one direction
  const top = Math.max(...ways), err = edge.some(e => e.errors), down = edge.some(e => e.up === false);  // looking back, the state of a link is unknown: that is not "down"
  return !ways.length ? 'no reading' : `${top.toFixed(top >= 100 ? 0 : 1)} Gb/s${cap ? ` · ${Math.round(top / cap * 100)} %` : ''}${err ? ' · errors' : down ? ' · down' : ''}`;
}
// The fuller direction of the busiest port among these links of one Spark, in Gb/s: a figure of the same kind as the rate of a port; null where no direction was read.
const busiestPort = edges => { const read = (edges || []).flatMap(e => [e.gbps, e.rx]).filter(v => v != null); return read.length ? Math.max(...read) : null; };
function linkCells(ab, ba) {  // one cable in the list of ring links: what flows out and back in Gb/s as text, and its last cell with its tone: errors, down, or how full the fuller way is. A way nobody read is a dash, and counts for nothing; a link is down only where that was read, at either of its ends; how full it is needs the rate it runs at
  const out = ab.gbps, back = ba ? ba.gbps : ab.rx, word = v => v == null ? '–' : v.toFixed(v >= 100 ? 0 : 1);
  const errors = ab.errors || (ba && ba.errors), down = [ab, ba].some(e => e && e.up === false), read = [out, back].filter(v => v != null), full = read.length && ab.capacity ? Math.round(Math.max(...read) / ab.capacity * 100) + '%' : '–';
  return { out: word(out), back: word(back), last: errors ? 'errors' : down ? 'down' : full, tone: errors ? 'rose' : down ? 'warn' : '' };
}
// The far end of one cable of a Spark in words: the Spark it leads to, with its port where another cable of the same Spark leads to the same one (two Sparks alone share two cables: each is told apart); null where nobody is at the other end. mine: every cable of that Spark. nodes: the Sparks of the cluster.
const farEnd = (e, mine, nodes) => { const peer = nodes.find(c => c.rank === e.to); return !peer ? null : mine.some(x => x !== e && x.to === e.to) ? `${peer.name} ${e.group}` : peer.name; };
// One reading added up over the Sparks that are live and have it, with how many of them do: a sum is only said together with what it is the sum of.
const readSum = (nodes, key) => { const read = nodes.filter(n => n.live && n[key] != null); return { sum: read.reduce((a, n) => a + n[key], 0), read: read.length, of: nodes.length }; };
function ringTraffic(nodes, edges) {  // what the ring carries, every direction of every cable once (as its sender counts it, or else as the far end receives it), with how many Sparks the sum covers, as readSum gives it: a Spark is in it where every direction it sends is known, one without any cable where its ports were read. Not read is unknown, never 0
  const list = edges || [];
  const sent = n => {
    const mine = list.filter(e => e.from === n.rank), alone = mine.filter(e => e.to == null).map(e => e.gbps);  // on a switch nobody else knows what a port sends
    const peers = new Set([...mine.map(e => e.to), ...list.filter(e => e.to === n.rank).map(e => e.from)].filter(r => r != null));  // every Spark it has a cable to, seen from either end: a port it did not read is known at the far end
    const ways = [...alone, ...[...peers].map(to => linkWays(list, n.rank, to)[0])];
    if (!ways.length) return n.live && n.net != null ? 0 : null;  // no cable at all: it sends nothing on the ring, where its ports were read
    return ways.some(v => v == null) ? null : ways.reduce((a, v) => a + v, 0);
  };
  const read = nodes.map(sent).filter(v => v != null);
  return { sum: read.reduce((a, v) => a + v, 0), read: read.length, of: nodes.length };
}
// The note under such a sum: all Sparks, or how many of them were read (looking back: recorded).
const readWord = (s, past) => s.read === s.of ? 'all Sparks' : `${s.read} of ${s.of} ${past ? 'recorded' : 'read'}`;
// What stands in place of the list of connections to the engine: that nobody read it (the head is away or has not told yet), that it was read and is empty, or nothing.
const connectionsWord = list => list == null ? 'The connections were not read.' : list.length ? '' : 'No connections right now.';
// What a list of readings adds up to, by one figure of each entry; null where the list itself was not read, and where an entry has no such figure: no list is not a list of nothing, and a sum that leaves a part out is not the sum.
const sumOver = (list, pick) => list && list.every(x => pick(x) != null) ? list.reduce((a, x) => a + pick(x), 0) : null;
function escapeDoes({ box, nerd, view, part, past, strip }) {  // one step back out. A box that explains what is on the page goes first: it is the last thing that was opened. A picked part of the open Spark is let go before the Spark is left. The open view goes before the moment of the past: finding a moment again costs more than opening a Spark again
  return box ? 'box' : nerd ? 'nerd' : part ? 'part' : view !== 'ring' ? 'view' : past ? 'live' : strip ? 'strip' : 'view';
}

/* ---- single tracks: while the ring engine is silent, every Spark may serve a model of its own ----
   What the page says about them comes from each Spark's own engine (n.own, read at the port docker published for it) and
   from the tracks a run source names (run.tracks). Never from the ring engine's numbers, and never from a guess. */
const TRACK_KINDS = [['writing', 'writing'], ['reading', 'reading'], ['idle', 'idle'], ['blind', 'without a reading']];
function trackKind(n, named) {  // what one Spark does on its own: the state of its engine; 'blind' when it works but no engine answers; 'none'
  const own = n.live ? n.own : null;
  if (own && own.state !== 'offline') return own.state === 'asleep' ? 'idle' : own.state;
  return own || (n.live && named[n.name]) ? 'blind' : 'none';
}
/* The pairs of Sparks the scene joins with a lane, as places in the cluster [a, b, chord]: every pair the cables of
   the moment join (edges, from and to), once. A pair of neighbours on the ring runs from a to the next, every other
   pair is a chord across. A ring whose cables join only neighbours, or that has none read yet, is drawn by its order
   as ever; Sparks whose cables name no other Spark (on a switch, or one alone) have no pair. */
function lanePairs(cluster, edges) {
  const n = cluster.nodes.length, at = new Map(cluster.nodes.map((c, i) => [c.rank, i])), next = i => (i + 1) % n, found = new Map();
  for (const e of edges || []) {
    const a = at.get(e.from), b = at.get(e.to);
    if (a == null || b == null || a === b) continue;
    const [i, j] = n === 2 ? [0, 1] : next(a) === b ? [a, b] : next(b) === a ? [b, a] : [Math.min(a, b), Math.max(a, b)];
    found.set(i + '-' + j, [i, j, n !== 2 && next(i) !== j]);
  }
  const pairs = [...found.values()];
  if (cluster.ring && pairs.every(p => !p[2])) return Array.from({ length: n === 2 ? 1 : n }, (_, i) => [i, next(i), false]);
  return pairs.sort((p, q) => p[2] - q[2] || p[0] - q[0] || p[1] - q[1]);
}
const KNOWN_BOARDS = ['P4242'];  // the boards of the machine the 3D model shows, the DGX Spark: a Spark that read another one is drawn as a plain box
const foreignBoard = n => { const b = ((n && n.firmware) || {}).board; return typeof b === 'string' && b !== '' && !KNOWN_BOARDS.includes(b); };  // whether a Spark read a board the model does not show; one not read is none
const untestedSetup = state => state.cluster.nodes.length !== 4 || !state.cluster.ring || state.nodes.some(foreignBoard);  // a cluster unlike the one ringtop was made on: not four Sparks in a ring, or a machine of another maker
const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
const sameOf = list => list.length && list.every(v => v === list[0]) ? list[0] : null;  // the one value every reading agrees on, or null
function deepWords(nodes, edges) {  // the hints of the deep view that say how the machines are built, from what was read: with the figure where every Spark that read it read the same, else the same hint without it
  const said = c => NUMBER_WORDS[c] || String(c);
  const cores = sameOf(nodes.filter(n => (n.capacity || []).length).map(n => n.capacity.length));
  const fans = sameOf(nodes.filter(n => Array.isArray(n.fans) && n.fans.length).map(n => n.fans.length));
  const rate = sameOf((edges || []).filter(e => e.capacity != null).map(e => e.capacity));
  const functions = sameOf(nodes.filter(n => n.link_counts && Object.keys(n.link_counts).length).map(n => Object.keys(n.link_counts).length));
  return {
    cores: cores ? `All ${cores} cores together.` : 'All cores together.',
    fans: fans > 1 ? `Mean of the ${said(fans)} fans.` : 'Mean of the fans.',
    full: rate ? `Fuller direction against ${rate} Gb/s` : 'Fuller direction', rate,
    counters: `All counters of the RDMA layer, per Spark, summed over its ${functions ? said(functions) + ' ' : ''}PCIe functions. Most stay at zero on a healthy ring.`,
  };
}
const cableRate = (edges, rank, group) => { const e = (edges || []).find(x => x.from === rank && x.group === group); return e && e.capacity != null ? e.capacity : null; };  // the line rate the link of one cable read, by the rank of its Spark and its port; null where none was read
const fullShare = (c, rate) => c.gb_tx != null && rate ? Math.max(c.gb_tx, c.gb_rx || 0) / rate * 100 : null;  // how full the fuller direction of a cable is, in percent of its line rate; null without a reading of either
const LINE_KINDS = [['', ''], ['6 4', 'dashed'], ['2 3', 'dotted'], ['10 3 2 3', 'double']];  // a chart's lines in turn: four colours, and each four of them with a pattern of their own, solid first: the dashes of the line and the border of its mark
const lineKind = i => LINE_KINDS[Math.floor(i / 4) % LINE_KINDS.length];  // the kind of the line of a chart at place i: its dashes and the border of its mark
const lanesLack = (drawn, pairs) => pairs.some(([a, b]) => !drawn.some(([c, d]) => c === a && d === b));  // whether a pair of Sparks on a cable has no lane among those drawn
function tracksOf(state) {  // the single tracks of one moment. null while the ring engine answers, and when no Spark's own engine does
  if (!state || state.engine.state !== 'offline') return null;
  const named = (state.why && state.why.own) || {};
  const rows = state.nodes.map(n => ({ name: n.name, kind: trackKind(n, named), own: n.live && n.own ? n.own : null }));
  const asked = rows.filter(r => r.kind !== 'blind' && r.kind !== 'none'), writers = rows.filter(r => r.kind === 'writing');
  if (!asked.length) return null;
  const sum = (list, key) => { const read = list.map(r => r.own[key]).filter(v => v != null); return read.length ? read.reduce((s, v) => s + v, 0) : null; };  // a value nobody read is not zero
  const firsts = asked.map(r => r.own.ttft_p95).filter(v => v != null);
  const t = { rows, asked: asked.length, tok_s: writers.length ? sum(writers, 'tok_s') : null, running: sum(asked, 'running'), waiting: sum(asked, 'waiting'), ttft: firsts.length ? Math.max(...firsts) : null, timed: firsts.length };  // timed: engines that have a first-token time
  for (const [kind] of TRACK_KINDS) t[kind] = rows.filter(r => r.kind === kind).length;
  return t;
}
const tracksWord = t => TRACK_KINDS.filter(([kind]) => t[kind]).map(([kind, word]) => `${t[kind]} ${word}`).join(' · ');  // short: the line stands between the tags of two Sparks
const tracksFace = t => ({ word: 'Single tracks', tone: t.writing ? 'writing' : t.reading ? 'reading' : 'idle', goal: t.tok_s, sub: tracksWord(t) });  // what the core shows: no number when nobody writes
function tracksPast(t) {  // the second sentence of the headline of a moment of the past
  const n = t.writing || t.asked, who = `${n} Spark${n === 1 ? '' : 's'}`, own = n === 1 ? 'its' : 'their';
  if (t.writing) return `${who} wrote on ${own} own: ${Math.round(t.tok_s)} tokens per second.`;
  const unread = t.rows.some(r => r.own && r.own.state !== 'offline' && r.own.tok_s == null);  // no speed kept at this moment: that is not "did not write"
  return unread ? `${who} served on ${own} own, no speed was recorded.` : `${who} served on ${own} own without writing.`;
}
function ownNote(own, alone) {  // what a tile says about the engine a Spark runs on its own. alone: the name the server gives its work, if it names any
  if (!own) return alone ? `runs ${alone}` : '';
  const what = own.model || 'own engine';  // looking back, the model was not recorded
  const silent = own.error ? 'no request counts' : 'no answer';  // its port is silent, or it answers without the counts of its requests: the server says which
  return `${own.state === 'writing' ? Math.round(own.tok_s) + ' tok/s' : own.state === 'offline' ? silent : own.state} · ${what}`;  // the speed first: a narrow tile cuts the end
}
const ownSpeed = (n, e) => e.state === 'offline' && n.live && n.own && n.own.state === 'writing' ? n.own.tok_s || 0 : 0;  // tokens per second a Spark's own engine writes; the sparks that fly from it
function ownPast(o) {  // the own engine of a Spark at a moment of the past, from the four values that were kept. Its model was not
  if (o.own_tok_s == null && o.own_running == null) return null;
  const busy = (o.own_running || 0) + (o.own_waiting || 0) > 0;
  return { model: null, state: o.own_tok_s >= 1 ? 'writing' : busy ? 'reading' : 'idle', tok_s: o.own_tok_s, running: o.own_running, waiting: o.own_waiting, ttft_p95: o.own_ttft_p95 };
}
function trackRows(tracks, nodes) {  // the tracks a run source names, in the order of the Sparks. One that names no Spark of this cluster comes last
  const place = name => { const i = nodes.findIndex(n => n.name === name); return i < 0 ? nodes.length : i; };
  return (Array.isArray(tracks) ? tracks : []).filter(t => t && typeof t === 'object').sort((a, b) => place(a.node) - place(b.node));
}
const jobOf = (jobs, name) => jobs.find(j => j.node === name) || null;  // the job a run source names for one Spark
const tracksShown = (all, room) => all.length > room ? { rows: all.slice(0, room - 1), more: all.length - room + 1 } : { rows: all, more: 0 };  // the lines a panel has room for: all, or one less and a word how many more there are
const trackCount = job => job.total > 0 && job.done != null ? `${job.done} of ${job.total}` : job.done ? `${job.done} done` : '';  // a total without a count says nothing about how far it is
// How far a job is, from 0 to 1, null unless it names a total and a count.
const trackShare = job => job && job.total > 0 && job.done != null ? Math.min(1, Math.max(0, job.done / job.total)) : null;
const trackWord = job => job ? [job.name, trackCount(job)].filter(Boolean).join(' · ') : '';  // A job in words: its name and how far it is.
function spacingOf(ts) {  // the usual distance between two samples of a trace: the median, so a long hole does not count
  if (ts.length < 2) return 0;
  const steps = ts.slice(1).map((t, i) => t - ts[i]).sort((a, b) => a - b);
  return steps[(steps.length - 1) >> 1];  // of two distances the smaller: one of them may be a hole
}
function sumTrace(list, reach) {  // several traces as one: at every moment one of them was read, the sum of each one's last value. A value reaches two and a half samples far, at least `reach`: a hole is not bridged
  const all = list.filter(s => s && s.t.length);
  if (all.length < 2) return all[0] || null;
  const far = all.map(s => Math.max(reach, Math.min(2.5 * spacingOf(s.t), 150))), at = all.map(() => 0), out = { t: [], v: [] };  // 150 s: two and a half one-minute values, the coarsest a trace is kept at
  for (const t of [...new Set(all.flatMap(s => s.t))].sort((a, b) => a - b)) {
    let sum = 0;
    all.forEach((s, k) => {
      while (at[k] + 1 < s.t.length && s.t[at[k] + 1] <= t) at[k]++;
      if (s.t[at[k]] <= t && t - s.t[at[k]] <= far[k]) sum += s.v[at[k]];
    });
    out.t.push(t); out.v.push(sum);
  }
  return out;
}
function warmest(n) {  // the hottest sensor of a Spark, with its name
  let best = null;
  for (const [zone, c] of Object.entries(n.zones || {})) if (c != null && (!best || c > best[1])) best = [zone, c];
  if (!best && n.cpu_c != null) best = ['board', n.cpu_c];  // without named zones the board reading stands in for them: it is their rounded maximum
  if (n.gpu_c != null && (!best || n.gpu_c > best[1])) best = ['GPU', n.gpu_c];
  return best;
}
function oddFans(nodes) {  // the Sparks whose fans turn more than 15 % slower than the middle one although they are no cooler: none with fewer than three
  if (nodes.length < 3) return [];
  const middle = list => list.slice().sort((a, b) => a - b)[list.length >> 1];
  const fan = middle(nodes.map(n => n.fan)), heat = middle(nodes.map(n => warmest(n)[1]));
  return nodes.filter(n => n.fan < fan * .85 && warmest(n)[1] >= heat - 1.5);  // strictly slower: fans that all stand still are no odd one out
}
function fanSetter(n) {  // who decides how fast the fans turn, from the cooling devices the kernel lists. A state that could not be read is unknown, never zero
  const list = n.cooling || [], floor = list.find(c => c.type === 'dgx_ec_fan_floor'), acpi = list.filter(c => c.type === 'Fan');
  const of = c => `${c.cur}${c.max != null ? ' of ' + c.max : ''}`, asked = [];
  if (floor && floor.cur > 0) asked.push(`a floor of ${of(floor)} through dgx-spark-fan-control`);
  const level = acpi.filter(c => c.cur > 0).sort((a, b) => b.cur - a.cur)[0];  // a quiet floor does not hide a level somebody asked for
  if (level) asked.push(`a level of ${of(level)} asked for through ACPI`);
  if (asked.length) return asked.join(' and ');
  if ([floor, ...acpi].some(c => c && c.cur == null)) return '';  // "nobody asks for anything" needs every state read
  return floor ? 'the firmware; dgx-spark-fan-control is loaded and asks for nothing' : acpi.length ? 'the firmware alone' : '';
}
const stoppedFans = nodes => nodes.filter(n => (n.fans || []).some(f => f === 0) && n.fans.some(f => f > 0));  // one fan stands still while its twin turns: the average of the two hides it
const namesWord = names => names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1] : names[0];  // Names in a row, as a sentence lists them: a, b and c.
// The speed of each fan of a Spark as the page writes it, in the order the Spark lists them: a fan that was not read keeps its place, as a dash.
const fanSpeeds = n => (n.fans || []).map(v => v == null ? '–' : Math.round(v).toLocaleString('en-US'));
function coolingWord(nodes) {  // the headline of the cooling view and the line under it, for Sparks that all have a fan reading and a warmest sensor
  const odd = oddFans(nodes), rest = nodes.filter(n => !odd.includes(n)), rpm = v => Math.round(v).toLocaleString('en-US');  // the others are the Sparks not named, whatever their speed
  const range = (list, word) => { const lo = word(Math.min(...list)), hi = word(Math.max(...list)); return lo === hi ? lo : `${lo} to ${hi}`; };
  const fans = list => range(list.map(n => n.fan), rpm) + ' RPM', heats = list => range(list.map(n => warmest(n)[1]), v => String(Math.round(v))) + ' °C';
  const stopped = stoppedFans(nodes);
  if (stopped.length) return [`${namesWord(stopped.map(n => n.name))} ${stopped.length > 1 ? 'have' : 'has'} a fan that stands still`,
    stopped.map(n => `${stopped.length > 1 ? n.name + ': ' : ''}${fanSpeeds(n).join(' / ')} RPM at ${Math.round(warmest(n)[1])} °C`).join('; ') + '.'];
  if (!odd.length) {  // nobody can be named, with two Sparks or with half of them slow: fans far apart are still not "alike"
    const speeds = nodes.flatMap(n => (n.fans || []).length ? n.fans : [n.fan]).filter(v => v != null), alike = Math.min(...speeds) >= Math.max(...speeds) * .85;  // every single fan: two Sparks with the same average need not have the same fans
    return [nodes.length < 2 ? 'Cooling' : alike ? `All ${nodes.length} Sparks cool alike` : 'The fans turn at different speeds', `${fans(nodes)} at ${heats(nodes)} on the warmest sensor.`];
  }
  return [`${namesWord(odd.map(n => n.name))} ${odd.length > 1 ? 'turn their' : 'turns its'} fans slower than the others`,
    `${fans(odd)} at ${heats(odd)}, the others ${fans(rest)}. ${odd.length > 1 ? 'None of them is' : 'It is no'} more than 1.5 °C cooler than the middle of all Sparks.`];  // what oddFans asks, not "it is not cooler": the rule lets it be a little cooler
}
// The Sparks that answer and whose fans were not read, by name: the headline of the cooling view is said of the Sparks with a fan reading and a warmest sensor, and leaves these out. A fan that stands still is a reading. A Spark that does not answer is not one of them: nothing of it was read.
const fansUnread = nodes => nodes.filter(n => n.live && n.fan == null).map(n => n.name);
/* What the cooling view says under its headline of the Sparks it leaves out for want of a fan reading (fansUnread); nothing where there is none. past: the page looks back, where a reading is recorded or not.
   The sentence names the Sparks the headline leaves out and gives the one reason, that no fan reading is there; it says nothing of the fans themselves: not that they stand still, turn slowly or have failed. */
const fansUnreadWord = (names, past) => !names.length ? '' : `Left out: ${namesWord(names)} (no fan reading${past ? ' recorded' : ''}).`;
// What is said of a ring engine nobody can read: its port is silent, or it answers without the counts of its requests (the server says which). "Off" would be more than anybody read.
const silentWord = e => e.answers ? 'the ring engine answers without its request counters' : 'the ring engine does not answer';
const aloneWord = (n, e = {}) => `${silentWord(e)}, ${n} Spark${n === 1 ? ' works' : 's work'} on ${n === 1 ? 'its' : 'their'} own`;  // the line under the core while Sparks work on their own
function tourStops(type, e) {  // does this key, click or turn of the wheel hand the page back
  const onButton = !!(e.target && e.target.closest && e.target.closest('#tour-btn'));
  if (type === 'keydown') {  // K and the button toggle the tour themselves; every other key ends it, also with the button in focus. Shift alone and shortcuts with Cmd, Ctrl or Alt belong to the system (a screenshot, another window) and leave it running, on purpose
    return !(e.key === 'k' || e.key === 'K' || e.metaKey || e.ctrlKey || e.altKey || e.key === 'Shift' || (onButton && (e.key === 'Enter' || e.key === ' ')));
  }
  return !(onButton && type !== 'wheel');  // a press on the button is the button's own click
}
const KEPT_ENGINE = ['tok_s', 'prompt_tok_s', 'steps_s', 'running', 'waiting', 'kv', 'prefix', 'accepted', 'ttft_p95', 'itl_p50', 'one_token_share', 'j_per_token'];
const KEPT_OWN = ['own_tok_s', 'own_running', 'own_waiting', 'own_ttft_p95'];  // of the engine a Spark runs on its own: see ownPast
const KEPT_NODE = [...TRACED, 'cap_pct', 'tlimit', ...KEPT_OWN], SIZES = ['mem_total_gb', 'mhz_max', 'disk_total_gb'];  // what a Spark is built with is no reading. A power limit or the speed of a link is a setting or a state: those are not taken from today
/* How far back a moment may reach for its sample: two and a half steps of what the stretch holds. Full samples lie one
   interval apart, one-minute averages a minute, and a long stretch is thinned to 720 columns. */
const reachOf = (span, tier, interval) => 2.5 * Math.max(span / 720, tier === 'raw' || tier === 'memory' ? interval : 60);
function sampleAt(ts, t, reach) {  // the last sample at or before t. Never one from after t, and none when it lies further back than reach: a hole is not shown as its neighbour
  if (!ts || !ts.length || ts[0] > t) return -1;
  let lo = 0, hi = ts.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (ts[mid] <= t) lo = mid; else hi = mid - 1; }
  return t - ts[lo] <= reach ? lo : -1;
}
function runAt(events, t) {  // which run the events put at this moment
  const runs = events.filter(e => e.kind === 'run');
  const before = runs.filter(e => e.t <= t).pop(), after = runs.find(e => e.t > t);
  if (before && before.text.startsWith('Started: ')) return { source: 'history', name: before.text.slice(9), started: before.t, past: true };
  if (!before && after && after.text.startsWith('Finished: ')) return { source: 'history', name: after.text.slice(10), past: true };  // it began before this stretch
  return { source: 'none', past: true };
}
function momentOf(live, got, t, reach) {  // one moment of the past as a state for every surface, from the recording and from nothing of today
  const loading = !got || t < got.from || t > got.to;  // the recording of this moment has not arrived: nobody knows yet what it holds
  const ts = got && got.t, i = loading ? -1 : sampleAt(ts, t, reach), all = loading ? [] : got.events || [];
  const at = i < 0 ? t : ts[i];  // the time of the sample shown. Values, run and events are all as of then: one sample looks the same wherever the cursor stands on it, so the page may draw it once
  const val = key => {  // the last value of one trace at or before the sample, within reach: one missed sample of one Spark is not a hole
    const s = i < 0 ? null : got.series[key];
    if (s) for (let j = i; j >= 0 && at - ts[j] <= reach; j--) if (s[j] != null) return s[j];
    return null;
  };
  const none = loading ? 'loading this moment' : 'nothing was recorded at this moment';
  const e = { past: true, timing: {}, spec: [], finished: null };
  for (const k of KEPT_ENGINE) e[k] = val('engine.' + k);
  const nodes = live.cluster.nodes.map(c => {
    const o = { name: c.name, rank: c.rank, head: c.head, throttle: null }, today = live.nodes.find(n => n.name === c.name) || {};  // throttle reasons are not kept: unknown, not "none"
    for (const k of KEPT_NODE) o[k] = val(c.name + '.' + k);
    for (const k of SIZES) o[k] = today[k];
    o.live = KEPT_NODE.some(k => o[k] != null);
    o.own = ownPast(o);
    o.fans = o.fan != null ? [o.fan] : [];
    if (!o.live) o.reason = none;
    return o;
  });
  const known = e.tok_s != null || e.running != null, recorded = nodes.some(n => n.live), head = nodes.find(n => n.head), asked = !!(head && head.live);
  e.state = !known ? 'offline' : e.tok_s >= 1 ? 'writing' : (e.running || 0) + (e.waiting || 0) > 0 ? 'reading' : 'idle';
  if (!known) {  // the engine is read through the head: "not serving" needs a reading of the head from that moment, otherwise nobody asked the engine
    e.error = asked ? 'the engine did not answer at this moment' : recorded ? 'no engine data at this moment: the head was not read' : none;
    if (!asked) e.word = loading ? 'Loading' : 'No record';
  }
  e.tokens_per_step = e.steps_s && e.tok_s != null ? e.tok_s / e.steps_s : null;
  const edges = live.edges.map(x => {
    const n = live.cluster.nodes.find(c => c.rank === x.from), tx = n ? val(`${n.name}.${x.group}.tx`) : null;
    return { ...x, gbps: tx, rx: n ? val(`${n.name}.${x.group}.rx`) : null, errors: null, up: null, capacity: null };  // whether a link was up, had errors, and how fast it ran is not kept: unknown, not fine
  });
  const points = [];
  for (const n of nodes) {
    if (!n.live) continue;
    const say = (level, text) => points.push({ level, text, node: n.name });  // a line about one Spark carries its name, like the lines of the server: the page of that Spark shows them
    if (n.gpu_c >= 85) say('warn', `${n.name} was running hot: ${Math.round(n.gpu_c)} °C.`);
    if (n.cap_pct >= 20) say('warn', `${n.name} spent ${Math.round(n.cap_pct)} % of the time at its power cap.`);
    if (e.state === 'writing' && n.mhz != null && n.mhz < 1000) say('bad', `${n.name} ran its GPU at ${Math.round(n.mhz)} MHz while the engine was writing.`);
  }
  const silent = nodes.filter(n => !n.live).length;
  if (silent && !loading) points.push({ level: 'warn', text: `${silent} of ${nodes.length} Sparks have no reading at this moment.` });
  const headline = loading ? 'Loading this moment from the recording.'
    : !known ? (asked ? 'The engine did not answer at this moment.' : recorded ? 'Nothing was recorded about the engine at this moment.' : 'Nothing was recorded at this moment.')
    : e.state === 'writing' ? `Writing at ${Math.round(e.tok_s)} tokens per second.` : e.state === 'reading' ? 'Reading prompts, no tokens yet.' : 'Idle.';
  const tracks = loading ? null : tracksOf({ engine: e, nodes });  // Sparks that served on their own while the ring engine was silent
  // of today only what cannot have been different: the Sparks, their sizes, the sampling interval. The engine of today (model, version, memory guard) says nothing about then
  return { t: at, past: true, loading, cluster: live.cluster, identity: { interval: live.identity.interval }, engine: e, nodes, edges,
    run: loading ? { source: 'none', past: true, loading: true } : runAt(all, at), why: { headline: tracks ? `${headline} ${tracksPast(tracks)}` : headline, points }, events: all.filter(x => x.t <= at).slice(-40) };
}
const linkStatus = (past, online) => past ? [false, 'Looking back'] : online ? [true, 'Live'] : [false, 'Reconnecting'];  // looking back wins: no stream changes the moment on the page

/* ---- the calm page for a wall and a phone: how its tiles stand, when it is live, what a tile shows ---- */
// How many columns the tiles of n Sparks stand in on the calm page. Wide, they fill the half beside the speed without scrolling: as near to a square of tiles as n allows, so never more rows than columns. Upright they stand under each other, however many they are, and the page scrolls: side by side on a phone their figures would be too small to read from an arm's length. Never fewer than one.
const wallCols = (n, wide) => wide ? Math.max(1, Math.ceil(Math.sqrt(n))) : 1;
// Whether a moment that arrived is news for the calm page: its time lies after the one on the page (shown: null before the first). When a stream is opened again the server sends the newest moment once more, and that one is none.
const wallNews = (t, shown) => t != null && (shown == null || t > shown);
const WALL_AGAIN = 5;  // seconds a stale page waits before it opens its stream once more
/* What the calm page says of its stream, asked every second. open: the stream stands. since: the seconds since the last new moment came, null before the first. interval: the sampling interval that moment named. opened: the seconds since the stream was last opened.
   Fresh, it is live or reconnecting in the words of the main page (linkStatus); before the first moment a stream that stands is connecting. Without a new moment for longer than the silence that takes a Spark off the main page (15 s, or four intervals where that is more: the line the server draws) it is stale, whatever the stream says of itself: not live, and no word stands for it here, the page says since when.
   again: a stale page opens its stream anew, at most every WALL_AGAIN seconds. A connection can be dead without an error: a phone that slept, a network that changed. Before the first moment nothing is stale, and a connection can be as dead: a stream that brought no moment for longer than the silence since it was opened is opened anew too. */
function wallStatus(open, since, interval, opened) {
  const silence = Math.max(15, 4 * (interval || 0));
  if (since == null) return { on: false, word: open ? 'Connecting' : linkStatus(false, false)[1], stale: false, again: opened > silence };
  if (since > silence) return { on: false, word: null, stale: true, again: opened >= WALL_AGAIN };
  const [on, word] = linkStatus(false, open);
  return { on, word, stale: false, again: false };
}
/* The three figures of a Spark's tile on the calm page, as whole numbers in text: GPU temperature in °C, fan speed in RPM, free memory in GB. A dash for one that was not read, and for all three of a Spark that is not live: what it still carries is not of now. A reading of 0 is a reading.
   stopped: one of its fans stands still while another turns (stoppedFans); the fan figure is their mean, which hides that. */
function wallFigures(n) {
  const word = key => !n.live || n[key] == null ? '–' : Math.round(n[key]).toLocaleString('en-US');
  return { temp: word('gpu_c'), fan: word('fan'), mem: word('mem_free_gb'), stopped: !!n.live && stoppedFans([n]).length > 0 };
}

/* ---- the open Spark under the pointer: what a click and a double click on the scene do ---- */
function sceneClick({ opened, part, picked, hit, view, home = true, count = 1 }) {  // what a click on the scene does. On a part of the open Spark: pick it, or let it go if it is the picked one; beside the parts a picked part is let go. Else open the Spark under the pointer, or leave the open one for the ring. The second click of a double click does nothing: it would undo the first. And a view that is not the one the Spark opened with is not left by a click beside the machines: there the way back is the double click
  if (count > 1) return ['none'];
  if (opened && (part || picked)) return ['part', part === picked ? null : part];
  return hit ? ['node', hit] : view === 'node' && home ? ['ring'] : ['none'];
}
const sceneDouble = ({ opened, part }) => !opened ? ['none'] : part ? ['centre', part] : ['home'];  // what a double click on the scene does: on a part of the open Spark it brings that part to the middle, beside the parts it takes the view back

/* ---- the lens on the open Spark: its picture is drawn larger around a place of the page, the camera stays where it is ----
   A lens is a zoom z and a shift q: what the camera shows is drawn z times as large and moved by q. Places and shifts are in units
   of the page, -1 to 1 from left to right and from bottom to top. hole: { mid, half }, the part of the page the scene shows through. */
const ZOOM_MAX = 8, ZOOM_PICK = 2, ZOOM_RATE = .002, ZOOM_EASE = .12;  // how far the lens zooms in; how near a click on a part brings it; how fast a wheel zooms, as the power of two one pixel of its turn stands for; the seconds in which the lens covers 63 % of the way it has left
function zoomStep(e) {  // the factor one event of the wheel zooms by. A wheel that counts in lines or pages turns further per count, and a pinch (it arrives as a wheel with Ctrl held, in small counts) weighs ten times as much. Never more than half or double at once
  const turn = -(+e.deltaY || 0) * (e.deltaMode === 1 ? 25 : e.deltaMode ? 500 : 1) * (e.ctrlKey ? 10 : 1) * ZOOM_RATE;
  return 2 ** Math.max(-1, Math.min(1, turn));
}
// The shift of a lens, held so that the hole never shows anything it did not show at zoom 1: the picture cannot be pushed out of it.
const zoomHeld = (z, q, hole) => q.map((v, k) => Math.min((hole.mid[k] - hole.half[k]) * (1 - z), Math.max((hole.mid[k] + hole.half[k]) * (1 - z), v)));
function zoomAt(lens, k, at, hole) {  // a lens after one step of zoom: k times as large, within 1 and ZOOM_MAX, and shifted so that the place `at` goes on showing what it showed. Whatever else the lens carries stays
  const z = Math.min(ZOOM_MAX, Math.max(1, lens.z * k)), by = z / lens.z;
  return { ...lens, z, q: zoomHeld(z, lens.q.map((v, i) => at[i] + by * (v - at[i])), hole) };
}
// A lens at zoom z that shows one place of the picture at `at`, as near to it as the bounds allow. base: where that place lies at zoom 1. at: where the page wants it, the middle of the hole unless it says otherwise.
const zoomCentred = (z, base, hole, at = hole.mid) => ({ z, q: zoomHeld(z, at.map((m, k) => m - z * base[k]), hole) });
// The lens a click on a part asks for: the part in the middle of the hole at ZOOM_PICK times the view the Spark opened with. A lens that stands nearer already keeps its zoom and only brings the part to the middle.
const zoomPicked = (lens, base, hole, at) => zoomCentred(Math.max(lens.z, ZOOM_PICK), base, hole, at);
// The lens a double click on a part asks for: zoomed until the part fills half the shorter side of the hole, never less than a click asks for and at most ZOOM_MAX. size: its longer side as a share of that shorter side at zoom 1; a size nobody could measure asks for the least.
const zoomOnto = (size, base, hole, at) => zoomCentred(Math.min(ZOOM_MAX, Math.max(ZOOM_PICK, .5 / size || 0)), base, hole, at);
function zoomEased(now, goal, dt, still) {  // one frame of a lens on its way to where it was asked to be. Zoom, shift and aim (where the camera looks beside the middle of the machine) cover the same share of what is left: so the place under the pointer shows the same spot all the way. There at once when motion is unwanted, and exactly there once it is as good as there
  const share = still ? 1 : 1 - Math.exp(-dt / ZOOM_EASE), on = (a, b) => a.map((v, i) => v + (b[i] - v) * share), near = (a, b, by) => a.every((v, i) => Math.abs(v - b[i]) < by);
  const next = { z: now.z + (goal.z - now.z) * share, q: on(now.q, goal.q), aim: on(now.aim, goal.aim) };
  return Math.abs(next.z - goal.z) < 1e-3 * goal.z && near(next.q, goal.q, 1e-3) && near(next.aim, goal.aim, 1e-4) ? { z: goal.z, q: goal.q.slice(), aim: goal.aim.slice() } : next;
}
function labelShows({ zoom, picked, pointed, inside, hidden }) {  // how visible the label of one part of the open Spark wants to be, from 0 to 1. Not at all while another part stands in front of its part or its part lies outside the hole: a label points at nothing that cannot be seen. Whole for the picked part and the part under the pointer. For the others whole up to a zoom of 1.25 and gone from 2 on, evenly less in between: zoomed in, they would lie over what the reader came to see
  if (hidden || !inside) return 0;
  if (picked || pointed) return 1;
  return 1 - Math.min(1, Math.max(0, (zoom - 1.25) / .75));
}
const dragMoves = e => !!(e.shiftKey || e.buttons & 2);  // whether a drag over the open Spark moves its picture instead of turning the machine: with Shift held, or with the right button down
function wheelMoves(e) {  // how far a wheel moves the picture of the open Spark, in pixels of the page, or null when it zooms. It moves with Shift held and no pinch: two fingers pushed with Shift, or a wheel with Shift, which browsers turn sideways. The picture goes with the fingers
  if (!e.shiftKey || e.ctrlKey) return null;
  const unit = e.deltaMode === 1 ? 25 : e.deltaMode ? 500 : 1;
  return [-(+e.deltaX || 0) * unit || 0, -(+e.deltaY || 0) * unit || 0];
}
const zoomKey = key => key === '+' || key === '=' ? 1.25 : key === '-' ? .8 : key === '0' ? 0 : null;  // what a key asks of the lens: a factor to zoom by, 0 to take the view back, null for every other key. The key that carries the plus unshifted counts as plus
// Whether the view of the open Spark is the one it opens with: nothing zoomed, moved or brought to the middle, and the machine not turned by more than the eye sees. orbit: how far it was turned and tilted.
const lensHome = (lens, orbit) => lens.z === 1 && !lens.part && lens.q.every(v => Math.abs(v) < 1e-9) && orbit.every(v => Math.abs(v) < 1e-3);
