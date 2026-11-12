// The engine numbers: the word and the number in the core, the vitals, and the speed line under them.
'use strict';
/* ---- engine numbers ---- */
let shown = 0, goal = null;
function renderCore(e) {  // Writes the core: its word, its tone and the line under it, and sets the number the frame loop counts towards.
  const face = coreFace(e);
  $('#core-state').textContent = face.word;
  $('#core-dot').style.setProperty('--tone', TONES[face.tone] || 'var(--faint)');
  $('#core-sub').textContent = face.sub;
  goal = face.goal;
  if (goal == null) { shown = 0; Scene.number(''); $('#core-num').textContent = ''; }
}
/* while the Sparks serve on their own, the first two vitals are sums over their engines; the silent ring engine has none */
const TRACK_VITALS = [
  [t => t.running == null ? 'n/a' : `${whole(t.running)} running`, t => t.waiting == null ? '' : `${whole(t.waiting)} waiting, on ${t.asked} Spark${t.asked === 1 ? '' : 's'}`],
  [t => seconds(t.ttft), t => t.timed ? `slowest of ${t.timed}, 95th percentile` : ''],
];
let speedTrace = null;  // the line under the vitals: tokens per second of every engine that was read
// The line under the vitals for one moment: the ring engine's speed and every Spark's own, added up.
const speedLine = state => sumTrace([series.get('engine.tok_s'), ...state.nodes.map(n => series.get(n.name + '.own_tok_s'))], state.identity.interval * 3);
const VITALS = [
  ['Requests', e => e.past && e.running == null ? 'n/a' : `${whole(e.running)} running`,  // looking back, a count that was not recorded is not zero
    e => e.past && e.waiting == null ? 'not recorded' : `${whole(e.waiting)} waiting${e.finished != null ? ', ' + whole(e.finished) + ' done' : ''}${e.errors ? ', ' + whole(e.errors) + ' failed' : ''}`,
    'Requests the engine works on now, and those waiting for a slot. Done counts every request since the engine started.'],
  ['First token', e => seconds(e.ttft_p95), e => e.past ? asRecorded(e.ttft_p95, '95th percentile') : e.ttft_recent ? '95th percentile, 5 min' : '95th percentile, since start',
    'From the arrival of a request to its first output token: the time 95 of 100 requests stay under, over the last 5 minutes (vLLM time_to_first_token_seconds). Without new requests, since the engine started.'],
  ['Step time', e => seconds(e.itl_p50), e => e.past ? asRecorded(e.itl_p50, 'typical') : e.itl_recent ? 'typical, last 5 min' : 'typical, since start',
    'From one model step to the next: the median of the last 5 minutes (vLLM inter_token_latency_seconds). A step writes several tokens when speculation works, so this is not the time per token.'],
  ['Speculation', e => pct(e.accepted), () => 'of drafts accepted',
    'Drafted tokens the model accepted, as a share of all drafted tokens of the last 8 seconds. By position: the Why view and the hoops on the beam.'],
  ['KV cache', e => pct(e.kv), e => e.kv_tokens ? `of ${size(e.kv_tokens)} tokens` : 'in use',
    'How full the key-value cache of the engine is (vLLM kv_cache_usage_perc).'],
  ['Prefix cache', e => pct(e.prefix), () => 'of prompt reused',
    'Prompt tokens answered from the prefix cache, as a share of all prompt tokens asked for in the last 8 seconds.'],
  ['GPU power', (e, st) => { const s = readSum(st.nodes, 'w'); return s.read ? `${whole(s.sum)} W` : 'n/a'; }, (e, st) => { const s = readSum(st.nodes, 'w'); return st.loading ? 'loading' : `${s.read} of ${s.of} ${st.past ? 'recorded' : 'read'}`; },
    'GPU power of the Sparks that were read, added up, as nvidia-smi reports it. A whole Spark draws more: the GB10 does not report that.'],
  ['Ring traffic', (e, st) => { const s = readSum(st.nodes, 'net'); return s.read ? `${s.sum.toFixed(1)} Gb/s` : 'n/a'; }, (e, st) => readWord(readSum(st.nodes, 'net'), st.past),
    'Sent plus received on the ring ports of the Sparks that were read, from the RDMA counters. A Spark whose ports have no reading is left out, and the note says how many are in the sum.'],
  ['GPU busy', (e, st) => { const live = st.nodes.filter(n => n.live && n.util != null); return live.length ? Math.round(live.reduce((a, n) => a + n.util, 0) / live.length) + ' %' : 'n/a'; }, () => 'average',
    'GPU utilisation, averaged over the Sparks that answer.'],
];
const vitalEls = [];
function buildVitals() {  // Builds the tiles of the vitals, once; each one carries how its number is counted as its tooltip.
  const box = $('#vitals');
  for (const [name, , , meaning] of VITALS) {
    const d = make('div', '', box);
    d.title = meaning;  // every number says how it is counted
    make('dt', '', d, name);
    const dd = make('dd', '', d);
    const value = document.createTextNode('');
    dd.appendChild(value);
    vitalEls.push({ value, note: make('small', '', dd) });
  }
}
function renderVitals(state) {  // Writes every vital for one moment; while the Sparks serve on their own the first two are sums over their engines.
  const e = state.engine, off = e.state === 'offline', tracks = tracksOf(state);
  VITALS.forEach(([, value, note], i) => {
    const gone = off && i < 6, own = tracks && TRACK_VITALS[i];  // the last three come from the Sparks, not from the engine
    vitalEls[i].value.textContent = own ? own[0](tracks) : gone ? 'n/a' : value(e, state);
    vitalEls[i].note.textContent = own ? own[1](tracks) : gone ? '' : note(e, state);
  });
  renderSpeed(state);
  renderDecomp();
}
function renderSpeed(state) {  // Draws the speed line of the last half hour and the area under it, scaled to its highest value.
  const s = speedTrace = speedLine(state), svg = $('#speed');
  let hi = 10;
  if (s) for (const v of s.v) if (v > hi) hi = v;
  const line = tracePath(s, state.t - WINDOW, 0, hi * 1.08, 42, state.identity.interval * 3);
  svg.querySelector('.line').setAttribute('d', line);
  svg.querySelector('.fill').setAttribute('d', fillUnder(line, 42));
}
// The small line under the speed: the speed at the moment the pointer rests on, otherwise steps per second times tokens per step.
function renderDecomp() {
  if (!S) return;
  const e = S.engine, el = $('#decomp');
  if (hoverT != null) {
    const v = nearest(speedTrace, hoverT);
    el.textContent = `${clock(hoverT, true)}: ${v == null ? 'no data' : Math.round(v) + ' tokens/s'}`;
  } else {
    el.textContent = e.steps_s != null && e.tokens_per_step != null && e.state === 'writing' ? `${e.steps_s.toFixed(0)} steps/s × ${e.tokens_per_step.toFixed(1)} tokens each` : '';
  }
}

