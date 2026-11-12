// The faces: what the core, a Spark and a run say of themselves and under which names, for every page that shows them.
'use strict';
/* ---- the names the Sparks go by ---- */
const NAMES_KEY = 'ringtop.names';
function keptNames() {  // The choice of names this browser kept: 'neutral', 'real' or none; none too where it can keep nothing.
  try { return window.localStorage.getItem(NAMES_KEY); } catch { return null; }
}
const NEUTRAL = neutralWanted(location.search, keptNames());  // the Sparks under neutral names and nothing the outside wrote word for word: for a film or a picture of the page (neutral.js)
let realNames = [], renames = [];  // from the newest moment: the real name of every Spark with its neutral one (the server keeps the history under the real ones), and with them every other name that is replaced
let cameAs = '';  // the cluster of the newest moment as the server named it: ring or not, and every Spark with its rank, its real name and whether it is the head. Behind the lens another cluster of the same shape carries the same neutral names
function lensed(state) {  // A moment as the page takes it in: the one the server sent, or with neutral names where they are asked for. Keeps which cluster it came from.
  cameAs = state.cluster.ring + state.cluster.nodes.map(n => n.rank + n.name + (n.head ? ' head' : '')).join();
  if (!NEUTRAL) return state;
  realNames = aliasPairs(state.cluster);
  renames = [...realNames, ...workNames(state)];
  return neutralState(state, renames);
}
function toggleNames() {  // Switches between the names the Sparks have and neutral ones. The choice is kept in this browser, and the page starts anew on the ring: the scene builds its signs once, and a link to a Spark would name it wrongly afterwards. Where nothing can be kept, the address carries the choice.
  const on = !NEUTRAL;
  let kept = true;
  try { window.localStorage.setItem(NAMES_KEY, on ? 'neutral' : 'real'); } catch { kept = false; }
  const target = location.pathname + (on && !kept ? '?names=neutral' : '');
  if (target === location.pathname + location.search + location.hash) location.reload(); else location.replace(target);
}
/* ---- the core ---- */
const WORDS = { idle: 'Idle', reading: 'Reading the prompt', writing: 'Writing', asleep: 'Asleep', offline: 'Not serving' };
const TONES = { idle: 'var(--faint)', reading: 'var(--teal)', writing: 'var(--violet)', asleep: 'var(--amber)', offline: 'var(--rose)' };
function coreFace(e) {  // what the core shows: the single tracks while Sparks serve on their own, otherwise the ring engine. goal: the number, null for none
  const tracks = tracksOf(S);
  if (tracks) return tracksFace(tracks);
  const each = `${whole(e.running)} running · ${whole(e.waiting)} waiting`, count = e.running == null || e.waiting == null ? null : e.running + e.waiting, alone = e.state === 'offline' && S ? S.nodes.filter(ownWork).length : 0;  // a sum only of two counts that were both read
  const sub = e.state === 'writing' ? each
    : e.state === 'reading' ? (count == null ? each : `${whole(count)} request${count === 1 ? '' : 's'} in progress`)
    : alone ? aloneWord(alone, e)
    : e.state === 'offline' ? (e.error || '') : e.state === 'asleep' ? 'weights are unloaded' : 'ready for requests';
  return { word: e.word || WORDS[e.state] || e.state, tone: e.state, goal: e.state === 'writing' ? e.tok_s || 0 : null, sub };  // looking back, "not serving" is only said when a recording says so
}
/* ---- a Spark ---- */
const ownWork = n => (S && S.why && S.why.own && S.why.own[n.name]) || '';  // what loads a Spark when the ring engine does not: the server decides, never the ring engine's own container
// The colour of a Spark's dot for the kind of its note: trouble, warning, no reading, or fine.
const toneOf = cls => cls === 'bad' ? 'var(--rose)' : cls === 'warn' ? 'var(--amber)' : cls === 'gone' ? 'var(--faint)' : 'var(--teal)';
// The one line a Spark says about itself, worst first: unreachable, clock stuck, slowing down, hot, near a limit, else its own work or its role.
function nodeNote(n, identity) {
  if (!n.live && S && S.past) return { cls: 'gone', text: S.loading ? 'loading this moment' : 'no reading at this moment' };  // looking back: not recorded is not unreachable
  if (!n.live) return { cls: 'bad', text: `Unreachable${n.reason ? ': ' + n.reason : ''}` };
  if (n.latched) return { cls: 'bad', text: `GPU clock stuck at ${Math.round(n.mhz)} MHz` };
  if (n.throttle && n.throttle.length) return { cls: 'warn', text: `Slowing down: ${n.throttle.join(', ')}` };
  if (n.gpu_c >= 85) return { cls: 'warn', text: 'Running hot' };
  if (n.tlimit != null && n.tlimit < 20 && (n.util || 0) >= 50) return { cls: 'warn', text: `${Math.round(n.tlimit)} °C from the thermal limit` };
  const short = guardWord(n.mem_free_gb, identity.memguard_gib);
  if (short) return { cls: 'warn', text: short };
  const alone = S && S.engine.state === 'offline' ? ownNote(n.own, ownWork(n)) : '';
  return { cls: '', text: alone || (n.head ? 'head' : 'worker') };
}
/* ---- a run ---- */
function runTime(r, now) {  // how long the run has been going, and when it will be done if it says how far it is
  if (!r.started) return r.source !== 'none' ? '' : r.loading ? 'Loading this moment.' : r.past ? 'No run was recorded at this moment.' : 'Requests and queued runs show up here.';
  const elapsed = now - r.started, counted = r.total > 0;
  if (!(counted && r.done > 0 && r.total > r.done)) return counted ? `${span(elapsed)} in` : `Running for ${span(elapsed)}`;
  const rest = elapsed / r.done * (r.total - r.done);
  return `${span(elapsed)} in, about ${span(rest)} left, done around ${clock(now + rest)}`;
}
