// The wiring: the stream of samples, one moment on every surface, the frame loop and the start of the page.
'use strict';
/* ---- wiring ---- */
const LINK = location.hash.slice(1);  // what the address asked for when the page opened: a view, a Spark, a moment
if (NEUTRAL && LINK.startsWith('node=')) history.replaceState(null, '', location.pathname + location.search);  // a link may name a Spark as it is really called: out of the address at once, and back under its neutral name when the page knows the cluster
// Writes the two lines that say what this is: model, image and cluster on top, versions and sampling at the foot; looking back, the date of the moment.
function renderIdentity(state) {
  const i = state.identity, n = state.cluster.nodes.length;
  const what = state.past ? `Looking back at ${new Date(state.t * 1000).toLocaleString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', second: '2-digit' })}.`
    : i.model ? `${i.model}${i.image ? ' on ' + i.image : ''}${i.container && i.container !== 'running' ? ', ' + i.container : ''}.` : 'Waiting for the engine.';
  const where = `${n} Spark${n === 1 ? '' : 's'}${state.cluster.ring ? ' in a ring' : ''}${i.context && !state.past ? ', ' + context(+i.context) + ' context' : ''}${untestedSetup(state) ? ', untested setup' : ''}.`;
  $('#identity').textContent = what + ' ' + where;
  const bits = [];
  if (i.vllm) bits.push('vLLM ' + i.vllm);
  if (i.kernel) bits.push('kernel ' + i.kernel);
  if (i.page_kb) bits.push(i.page_kb + ' KiB pages');
  if (i.config) bits.push('profile ' + i.config);
  const names = NEUTRAL ? 'Shown with neutral names for the Sparks and the runs (H). ' : '';  // said wherever they are shown: these are not the names the Sparks and the runs have
  $('#about').textContent = names + (state.past ? 'Every value on this page is from the recording. Which engine ran then, and with which settings, is not kept. Every spark rising from the ring is one generated token.'
    : `${bits.join(', ')}${bits.length ? '. ' : ''}Sampled every ${i.interval} s over SSH. Every spark rising from the ring is one generated token.`);
}
function setLive(on, text) {  // Sets the word and the dot of the link in the corner.
  const link = $('#link');
  link.lastElementChild.textContent = text;
  link.firstElementChild.style.setProperty('--dot', on ? 'var(--teal)' : 'var(--amber)');
}
let online = false;  // does the stream of samples stand
function status() { setLive(...linkStatus(Time.isPast(), online)); }  // Says in the corner whether the page is live, looking back or cut off.
function flowsOf(state) {  // The traffic of one moment per direction of every link, as the scene draws it.
  const flow = {};
  for (const e of state.edges) {
    const to = e.to == null ? 'hub' : e.to;
    flow[e.from + '>' + to] = (flow[e.from + '>' + to] || 0) + (e.gbps || 0);
    if (e.to == null) flow['hub>' + e.from] = (flow['hub>' + e.from] || 0) + (e.rx || 0);
  }
  return flow;
}
let built = false, lastFrame = 0, clusterNames = '', skip = 0, lanes = [];  // lanes: the pairs of Sparks the scene drew a lane for (lanePairs)
function frame(now) {  // One frame: the scene moves on and the number in the core counts towards its goal.
  if (Nerd.isOpen() && ++skip % 3) { requestAnimationFrame(frame); return; }  // the scene sits behind a dim veil there, a third of the frames is enough
  const dt = Math.min(.05, (now - lastFrame) / 1000 || 0);
  lastFrame = now;
  Scene.frame(now, dt);
  if (goal != null) {
    shown = calm.matches ? goal : shown + (goal - shown) * clamp(dt * 5);
    const text = Math.round(shown).toLocaleString('en-US');
    Scene.number(text);
    const el = $('#core-num');
    if (el.textContent !== text) el.textContent = text;
  }
  requestAnimationFrame(frame);
}
function render(state) {  // one moment on every surface: now, or one the time machine picked
  S = state;
  $('.speed .lb').textContent = state.past ? 'Tokens per second, 30 min before' : 'Tokens per second, last 30 min';
  Scene.data(state, flowsOf(state));
  renderIdentity(state);
  renderCore(state.engine);
  renderRun(state);
  renderVitals(state);
  renderDock(state);
  paintPanel();
  Nerd.tick();
}
function apply(state) {  // Takes in the newest moment (it came through lensed): builds the page on the first one, and shows it unless the page is looking back.
  if (built && (cameAs !== clusterNames || lanesLack(lanes, lanePairs(state.cluster, state.edges)))) return location.reload();  // another cluster, another head, or a cable between two Sparks the scene has no lane for: told by the names the server sent, not by the neutral ones
  clusterNames = cameAs;
  LIVE = state;
  if (!built) {
    built = true;
    S = state;
    lanes = lanePairs(state.cluster, state.edges);
    Scene.build(state.cluster, lanes);
    buildVitals();
    buildDock(state.cluster);
    buildNav();
    wire();
    requestAnimationFrame(frame);
  }
  if (!Time.isPast()) render(state);  // while the page looks back, now only moves the end of the strip
  Time.tick();
}
// Starts the page: loads the model, the first moment and its history, follows a link into a view, then listens to the stream; tries again every 3 s while ringtop is out of reach.
async function start() {
  try {
    await Scene.load();
    const first = lensed(await (await fetch('api/state')).json());
    for (const key in first.history) { const [t, v] = first.history[key]; series.set(key, { t: [...t], v: [...v] }); }
    apply(first);
    const wanted = LINK;  // deep link: #why, #memory, #events, #run, #node=spark-1
    if (wanted.startsWith('node=')) {  // with neutral names a link may name a Spark either way, and the address then shows the neutral one: a link somebody kept does not put the real name back into the picture
      const node = NEUTRAL ? nodeAlias(wanted.slice(5), realNames) : wanted.slice(5);
      if (NEUTRAL) history.replaceState(null, '', `${location.pathname}${location.search}#node=${node}`);
      setView('node', node);
    }
    else if (['why', 'memory', 'cooling', 'events', 'run'].includes(wanted)) setView(wanted);
    else if (wanted === 'nerd') Nerd.toggle(true);
    else if (wanted.startsWith('nerd=')) { Nerd.toggle(true); Nerd.tab(wanted.slice(5)); }
    else if (wanted === 'tour') Tour.toggle(true);
    else if (wanted === 'time') Time.toggle(true);
    else if (/^time=\d+(\.\d+)?$/.test(wanted)) Time.go(+wanted.slice(5));  // one recorded moment, as a link
  } catch (e) {
    setLive(false, 'Cannot reach ringtop');
    setTimeout(start, 3000);
    return;
  }
  const events = new EventSource('api/events');
  events.onopen = () => { online = true; status(); };
  events.onmessage = e => { const s = lensed(JSON.parse(e.data)); record(s); apply(s); online = true; status(); };
  events.onerror = () => { online = false; status(); };
}
start();
