// The neutral lens: what the page takes in with the names of the Sparks and the words of the outside taken away, as plain functions of the data, so the checks run them through node.
'use strict';
const JOURNAL_WORDS = new Map([['kernel', 'Kernel error, text not shown'], ['memguard', 'Memory guard message, text not shown']]);  // a line of the journal is a line of a log: its time, Spark and level stay, its words do not
const PAGE_WORDS = new Set(['kind', 'level', 'state', 'source', 'tier', 'group', 'type', 'pstate']);  // fields whose values are words the page works with, not names: they stay whatever they spell
// Whether the page shows neutral names: its address asks for them with ?names=neutral, or the choice was kept.
const neutralWanted = (search, kept) => /[?&]names=neutral(&|$)/.test(search || '') || kept === 'neutral';
// The real name of every Spark with its neutral one: spark-1 to spark-N, by rank.
const aliasPairs = cluster => cluster.nodes.map(n => [n.name, `spark-${n.rank + 1}`]);
function renamer(pairs) {  // a function that puts the second name of every pair in place of the first in a text. One pass, the longest name first and whole names only: spark-1 is no part of spark-1c9d, and two Sparks that carry each other's new names are swapped, not merged
  if (!pairs.length) return text => text;
  const to = new Map(pairs), names = pairs.map(p => p[0]).sort((a, b) => b.length - a.length).map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const find = new RegExp(`(^|[^\\w-])(${names.join('|')})(?![\\w-])`, 'g');
  return text => text.replace(find, (whole, lead, name) => lead + to.get(name));
}
/* What a Spark works on, where the name of that is no model: the name of a container or of a program, each with the neutral words that
   stand in for it. A model is the name its container was told to serve under (box.model); the server falls back to the container's own
   name, or to the biggest program on the GPU. Joined to the pairs of the Sparks, these names are replaced wherever they stand.
   Only what the server put there under the name of a Spark counts, and only a text is a name: a Spark may be called like something
   every object has (constructor). And the name of a Spark of this cluster is never one of them: it has its neutral name already, and
   a second entry for it would take that away. */
function workNames(state) {
  const named = (state.why && state.why.own) || {}, sparks = state.cluster.nodes.map(c => c.name), out = [];
  for (const n of state.nodes) {
    const model = (n.box || {}).model, words = n.own ? 'an engine' : 'a program';
    const said = Object.prototype.hasOwnProperty.call(named, n.name) ? named[n.name] : null;
    for (const name of [said, (n.own || {}).model]) if (name && typeof name === 'string' && name !== model && name !== words && !sparks.includes(name) && !out.some(p => p[0] === name)) out.push([name, words]);
  }
  return out;
}
function renameDeep(value, rename) {  // a copy of a value with every text in it renamed; the words the page works with stay as they are. Keys stay too: a Spark may be called like a field
  if (typeof value === 'string') return rename(value);
  if (Array.isArray(value)) return value.map(v => renameDeep(v, rename));
  if (!value || typeof value !== 'object') return value;
  const out = {};
  for (const key in value) out[key] = PAGE_WORDS.has(key) ? value[key] : renameDeep(value[key], rename);
  return out;
}
/* A function that renames a key: the name something is kept under by Spark. Such a key begins with the name of a Spark, alone (what it
   works on) or before a dot (NAME.reading), or it belongs to no Spark (engine.tok_s) and stays as it is. Only that first name is replaced,
   the longest one first: a reading may be called like a Spark (engine.running), and a name may hold dots itself. pairs: those of the
   Sparks alone, each name with what stands in for it. */
function keyRenamer(pairs) {
  const sorted = [...pairs].sort((a, b) => b[0].length - a[0].length);
  return key => { const hit = sorted.find(([name]) => key === name || key.startsWith(name + '.')); return hit ? hit[1] + key.slice(hit[0].length) : key; };
}
// An object that is kept by the names of Sparks (what each works on, the traces as NAME.reading) under its renamed keys (keyRenamer); its values are handed on.
const renameKeys = (object, rename) => Object.fromEntries(Object.entries(object).map(([key, value]) => [rename(key), value]));
const RUN_WORD = 'Test run';  // stands in for every name a run source wrote: of a run, of each of its steps, of the job on a track
const STEP_STATES = ['done', 'failed', 'running', 'pending'];  // the states of a step the page knows
// The words of an event about a run with the name of the run taken out: that it started or finished stays.
const runEvent = text => { const said = /^(Started|Finished): /.exec(String(text)); return said ? `${said[1]}: ${RUN_WORD}` : RUN_WORD; };
/* Events without the words of the outside, and with every name in them replaced (rename): a line of the journal gets a fixed sentence, an
   outage loses the last words of ssh (they may name a machine and a port), a run loses its name. An event is told apart by the words it
   came with: a Spark may be called like the first of them. And the sentence the page puts in its place is not renamed afterwards. */
const neutralEvents = (events, rename) => events.map(e => {
  const said = JOURNAL_WORDS.has(e.kind) ? JOURNAL_WORDS.get(e.kind) : e.kind === 'node' && String(e.text).startsWith('Unreachable') ? 'Unreachable' : e.kind === 'run' ? runEvent(e.text) : null;
  return said == null ? renameDeep(e, rename) : { ...renameDeep(e, rename), text: said };
});
// The fields of an object that hold a number, out of the ones asked for: a text in the place of a count does not pass.
const numbersOf = (from, keys) => Object.fromEntries(keys.filter(key => typeof from[key] === 'number').map(key => [key, from[key]]));
/* The run of a moment without the words a run source outside of ringtop wrote (the run command, the lab queue). Its name, the names of
   its steps and the job of every track become "Test run"; its queue, who holds the ring and until when are left out, like its detail.
   What passes is what the page counts with: how far the run is and since when, the state and the times of every step, and of a track
   its Spark (if it is one of this cluster), its model and how far it is. A run ringtop names itself (serving requests, a benchmark,
   none) keeps its name and loses its detail. sparks: the names the Sparks are shown under. */
function neutralRun(run, sparks) {
  if (run.source !== 'command' && run.source !== 'lab') return { ...run, detail: null };
  const out = { source: run.source, name: RUN_WORD, group: null, holder: null, until: null, detail: null, ...numbersOf(run, ['done', 'total', 'started']) };
  if ('has_replies' in run) out.has_replies = !!run.has_replies;
  if (Array.isArray(run.steps)) out.steps = run.steps.map((s, k) => ({ name: `${RUN_WORD} ${k + 1}`, ...(STEP_STATES.includes(s.state) ? { state: s.state } : {}), ...numbersOf(s, ['seconds', 'was']) }));
  if (Array.isArray(run.tracks)) out.tracks = run.tracks.map(t => ({ ...(sparks.includes(t.node) ? { node: t.node } : {}), ...(typeof t.model === 'string' ? { model: t.model } : {}), ...(t.name ? { name: RUN_WORD } : {}), ...numbersOf(t, ['done', 'total', 'started']) }));
  return out;
}
/* One moment as the page takes it in with neutral names. Every name of a Spark is replaced, wherever it stands: as a value, inside a
   sentence, and as a key where the server keeps something by name (why.own, the traces of the first half hour). And what the outside wrote word for word does not pass: kernel and
   profile of the engine, why a Spark is out of reach, lines of the journal, the container and the names of programs, and every name a
   run source gave a run (neutralRun). Readings, models and images stay: they are what the page is about. The moment that came is not changed.
   pairs: the names to replace with what stands in for each, the Sparks first (aliasPairs), then what they work on (workNames). A key
   is renamed by the Sparks of the moment alone, and only where it begins with one (keyRenamer). */
function neutralState(state, pairs) {
  const rename = renamer(pairs), key = keyRenamer(aliasPairs(state.cluster)), out = renameDeep(state, rename);
  if (out.why && out.why.own) out.why.own = renameKeys(out.why.own, key);
  if (out.history) out.history = renameKeys(out.history, key);
  out.identity = { ...out.identity, kernel: null, config: null };
  out.nodes = out.nodes.map(n => ({ ...n, reason: null, box: null, top: [], threads: [], key_threads: [], intruders: [], apps: (n.apps || []).map(a => ({ gb: a.gb })) }));
  out.events = neutralEvents(state.events || [], rename);  // from the events as they came, not as renameDeep left them
  if (out.run) out.run = neutralRun(out.run, out.cluster.nodes.map(n => n.name));
  return out;
}
function neutralHistory(answer, pairs, sparks) {  // a stretch of the history as the page takes it in with neutral names: every trace under its neutral key, its events like those of a moment. The columns are handed on, not copied, and nothing is added that the answer did not hold. pairs: every name that is replaced in a text; sparks: the pairs of the Sparks alone, for the keys
  const rename = renamer(pairs), key = keyRenamer(sparks), out = { ...answer };
  for (const part of ['series', 'peak', 'low', 'n']) if (answer[part]) out[part] = renameKeys(answer[part], key);
  if (answer.events) out.events = neutralEvents(answer.events, rename);
  return out;
}
function realKeys(keys, pairs) {  // the keys of traces as the server keeps them: the real name of each Spark back in the place of its neutral one, where a key begins with it (keyRenamer)
  const real = keyRenamer(pairs.map(([name, alias]) => [alias, name]));
  return keys.map(key => real(key));
}
// The Spark a link means, by the name the page shows: a neutral name stays, a real one becomes its neutral one, and a name nobody has stays what it is.
const nodeAlias = (name, pairs) => pairs.some(p => p[1] === name) ? name : (pairs.find(p => p[0] === name) || [name, name])[1];
/* The record of a run without the words its source wrote: its name becomes "Test run", its stations are counted through and keep their
   state and their seconds, the queue it belongs to is gone. What it counted stays, and so do the model and the image, as in the head of
   the page; like there they pass the renamer of the page (rename: a function that puts neutral names into a text), so a Spark named
   inside one of them reads as its neutral name. Whether they are shown is not decided here: the box of the runs view leaves them out
   under neutral names (runFacts). The record that came is not changed; no record stays none. */
function neutralRecord(record, rename = text => text) {
  if (!record) return null;
  const said = text => typeof text === 'string' ? rename(text) : text;
  const out = { ...record, name: RUN_WORD, group: null, model: said(record.model), image: said(record.image) };
  if (Array.isArray(record.steps)) out.steps = record.steps.map((s, k) => ({ name: `${RUN_WORD} ${k + 1}`, ...(STEP_STATES.includes(s.state) ? { state: s.state } : {}), ...numbersOf(s, ['seconds', 'was']) }));
  return out;
}
// The records of runs as the server gives them (the open one, the ended ones), each without the words of its source (neutralRecord). rename: the renamer of the page, for what stays of them as text.
const neutralRuns = (answer, rename) => ({ open: neutralRecord(answer.open, rename), runs: (answer.runs || []).map(record => neutralRecord(record, rename)) });
