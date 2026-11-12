// Loads the scripts of the page without a browser, one after the other in one shared context, against a document that
// keeps what it is given and draws nothing. Then it lets the page start, shows it two moments, opens every view and
// draws a few frames. Prints one JSON line with what it saw.
//   node page_loader.js gl|nogl|fail:NAME|neutral|sheet STATES.json FILE.js [FILE.js ...]
// STATES.json: { first, next, nerd, deep, past } as the server would send them, and `hash`: what stands behind the
// address the page is opened with, if anything; `search`: what stands behind its "?", for a check in sheet mode that
// drives the page with neutral names. With "nogl" the canvas has no WebGL.
// With "fail:NAME" the scene breaks while it builds itself: the WebGL call of that name throws, or the canvas refuses
// the listener for the event of that name. With "neutral" the address of the page asks for neutral names: after every
// step the loader looks through every element it knows for a real name of a Spark, and keeps how the history was asked.
// At the end it sends a moment of the same cluster and one of another cluster of the same shape, and says in
// `reloaded` whether the page asked to start anew for each.
// With "sheet" the check drives the page itself: after the first moment of the stream, every entry of `steps` in
// STATES.json is run as a piece of script in the page, and what each gives back is printed as `steps`. A step reaches
// the page's own names and `server` (below): it lets the history wait, gives it another answer, sends a moment down
// the stream, and lets an element hear an event with `fire`, or the window with `pageHears`. It gives an element a
// place of its own with `rect` or with `server.place` (every other one fills the window), lets the words of a
// drawing be measured with `server.measureWords`, lets the page draw frames with `server.draw`, and tells it with
// `server.resized` that the size of what it watches changed. `server.runsAnswer` gives the records of runs the server
// answers with from then on, `server.runsFail` lets it fail with a status. `server.streams` says which streams the page
// opened (a moment goes down the newest), and `server.texts` gives every text the page holds.
// RINGTOP_MODEL in the environment names the 3D model to hand out; without it the page gets none, as on a fresh checkout.
// RINGTOP_NOGL in the environment takes WebGL away in any mode: a check in sheet mode can then drive the page without its scene.
'use strict';
const vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');

const [mode, statesFile, ...files] = process.argv.slice(2);
const failing = mode.startsWith('fail:') ? mode.slice(5) : null;
const fail = name => { throw new Error(`${name} failed`); };
const neutral = mode === 'neutral', historyAsked = [], realFound = new Set();
const states = JSON.parse(fs.readFileSync(statesFile, 'utf8'));
const errors = [], asked = [], frames = [], sources = [];
let drawn = 0;
const fault = (where, e) => errors.push(`${where}: ${e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e}`);
process.on('unhandledRejection', e => fault('rejection', e));

class Style {  // an element's style: whatever is set stays, nothing is laid out
  setProperty(key, value) { this[key] = value; }
  removeProperty(key) { delete this[key]; }
  getPropertyValue(key) { return this[key] == null ? '' : this[key]; }
}
class Classes {  // classList
  constructor() { this.names = new Set(); }
  add(...names) { for (const n of names) this.names.add(n); }
  remove(...names) { for (const n of names) this.names.delete(n); }
  contains(name) { return this.names.has(name); }
  toggle(name, on) { const want = on === undefined ? !this.names.has(name) : !!on; if (want) this.names.add(name); else this.names.delete(name); return want; }
}
class El {  // an element that keeps its children, text, classes and attributes, and finds whatever it is asked for
  constructor(tag) {
    this.tagName = String(tag).toUpperCase(); this.children = []; this.parentNode = null; this.style = new Style(); this.dataset = {};
    this.classList = new Classes(); this.attributes = new Map(); this.found = new Map(); this.text = ''; this.hidden = false; this.listeners = {};
    this.width = 300; this.height = 150; this.value = ''; this.scrollTop = 0; this.title = '';
  }
  get className() { return [...this.classList.names].join(' '); }
  set className(v) { this.classList.names = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this.text; }
  set textContent(v) { this.text = String(v); for (const c of this.children) c.parentNode = null; this.children.length = 0; }
  get childNodes() { return this.children; }
  get options() { return this.children; }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  get firstElementChild() { return this.children[0] || this.querySelector(':first'); }  // children the markup would have given
  get lastElementChild() { return this.children[this.children.length - 1] || this.querySelector(':last'); }
  get nextElementSibling() { const all = this.parentNode ? this.parentNode.children : []; return all[all.indexOf(this) + 1] || null; }
  get parentElement() { return this.parentNode; }
  get isConnected() { return true; }
  get clientWidth() { return this.rect ? this.rect.width : 1064; } get clientHeight() { return this.rect ? this.rect.height : 625; }  // rect: a place of its own a check gave this element; without one it is as large as the window
  get offsetWidth() { return 1064; } get offsetHeight() { return 625; }
  get scrollHeight() { return 625; } get scrollWidth() { return 1064; }
  appendChild(c) { if (c.tagName === '#FRAGMENT') { for (const k of [...c.children]) this.appendChild(k); return c; } c.remove(); this.children.push(c); c.parentNode = this; return c; }
  append(...all) { for (const c of all) this.appendChild(typeof c === 'string' ? Object.assign(new El('#text'), { text: c }) : c); }
  prepend(c) { c.remove(); this.children.unshift(c); c.parentNode = this; }
  insertBefore(c, ref) { c.remove(); const i = ref ? this.children.indexOf(ref) : -1; this.children.splice(i < 0 ? this.children.length : i, 0, c); c.parentNode = this; return c; }
  remove() { const p = this.parentNode; if (p) { const i = p.children.indexOf(this); if (i >= 0) p.children.splice(i, 1); this.parentNode = null; } }
  removeChild(c) { c.remove(); return c; }
  replaceChildren(...all) { this.textContent = ''; this.append(...all); }
  replaceWith(c) { const p = this.parentNode; if (p) { p.insertBefore(c, this); this.remove(); } }
  cloneNode() { return new El(this.tagName); }
  setAttribute(key, value) { this.attributes.set(key, String(value)); }
  getAttribute(key) { return this.attributes.has(key) ? this.attributes.get(key) : null; }
  hasAttribute(key) { return this.attributes.has(key); }
  removeAttribute(key) { this.attributes.delete(key); }
  toggleAttribute(key, on) { if (on === undefined ? !this.attributes.has(key) : on) this.attributes.set(key, ''); else this.attributes.delete(key); }
  querySelector(sel) { if (!this.found.has(sel)) this.found.set(sel, new El('found')); return this.found.get(sel); }
  querySelectorAll() { return []; }
  matches(sel) {  // a tag, a class, or a tag with a class: all the page ever asks of an element
    return String(sel).split(',').some(one => {
      const [tag, cls] = one.trim().split('.');
      return (!tag || this.tagName === tag.toUpperCase()) && (!cls || this.classList.contains(cls) || (this.attributes.get('class') || '').split(/\s+/).includes(cls));
    });
  }
  closest(sel) { for (let el = this; el; el = el.parentNode) if (el.matches(sel)) return el; return null; }
  contains() { return false; }
  addEventListener(type, heard) { if (type === failing) fail(type); (this.listeners[type] = this.listeners[type] || []).push(heard); }
  removeEventListener() {} dispatchEvent() { return true; }
  fire(type, event) { for (const heard of this.listeners[type] || []) heard({ target: this, ...event }); }  // what a browser does with an event: every listener of that kind hears it
  under(out = []) { out.push(this); for (const c of this.children) c.under(out); return out; }  // this element and every one below it, for a check that looks for one
  getBoundingClientRect() { if (this.placed) return this.placed; const { left, top, width, height } = this.rect || { left: 0, top: 0, width: 1064, height: 625 }; return { x: left, y: top, left, top, right: left + width, bottom: top + height, width, height }; }  // the whole window, unless a check gave it a place of its own: with `server.place`, or as its `rect`
  get getComputedTextLength() { return glyph == null ? undefined : () => this.text.length * glyph; }  // a drawing measures its words only once a check said how wide a letter is
  getContext(kind) { return kind === 'webgl2' ? (mode === 'nogl' || process.env.RINGTOP_NOGL ? null : gl) : nothing(); }
  focus() {} blur() {} click() {} scrollIntoView() {} scrollTo() {} setPointerCapture() {} releasePointerCapture() {}
  animate() { return { finished: Promise.resolve(), cancel() {} }; }
  getTotalLength() { return 0; } getBBox() { return { x: 0, y: 0, width: 0, height: 0 }; }
}
// what a 2D canvas gives back: every property is another one of these, every call returns one, as a number it is 0
function nothing() {
  return new Proxy(function () {}, {
    get(_, key) { return key === Symbol.toPrimitive ? () => 0 : key === 'then' ? undefined : key === 'length' ? 0 : key === Symbol.iterator ? function* () {} : nothing(); },
    apply() { return nothing(); }, construct() { return nothing(); }, set() { return true; },
  });
}
// WebGL that accepts everything: constants are numbers of their own, programs link, framebuffers are complete
const constants = new Map();
const K = name => { if (!constants.has(name)) constants.set(name, 0x9000 + constants.size); return constants.get(name); };
const made = () => ({});
const answers = {
  drawingBufferWidth: 2128, drawingBufferHeight: 1250,
  getExtension: made, createProgram: made, createShader: made, createBuffer: made, createTexture: made, createFramebuffer: made,
  createRenderbuffer: made, createVertexArray: made, getUniformLocation: made,
  getParameter: () => 8, getInternalformatParameter: () => [4, 2, 1], getShaderParameter: () => true,
  getProgramParameter: (p, what) => what === K('ACTIVE_UNIFORMS') ? 0 : true, getShaderInfoLog: () => '', getProgramInfoLog: () => '',
  getActiveUniform: () => ({ name: 'u', size: 1, type: 0 }), getAttribLocation: () => 0,
  checkFramebufferStatus: () => K('FRAMEBUFFER_COMPLETE'), isContextLost: () => false, getError: () => 0,
};
const gl = new Proxy(answers, { get: (t, key) => key === failing ? () => fail(key) : key in t ? t[key] : typeof key === 'string' && /^[A-Z][A-Z0-9_]*$/.test(key) ? K(key) : () => undefined });

const selected = new Map();
const document = {
  body: new El('body'), documentElement: new El('html'), activeElement: new El('body'), hidden: false, visibilityState: 'visible',
  createElement: tag => new El(tag), createElementNS: (ns, tag) => new El(tag), createDocumentFragment: () => new El('#fragment'),
  createTextNode: text => Object.assign(new El('#text'), { text: String(text) }),
  querySelector(sel) { if (!selected.has(sel)) selected.set(sel, new El(sel)); return selected.get(sel); },
  querySelectorAll: () => [], addEventListener() {}, removeEventListener() {},
};
let parse = JSON.parse;
const reply = value => ({ ok: true, status: 200, json: async () => parse(JSON.stringify(value)) });
async function fetch(url) {  // the server, from the moments it was given
  const u = String(url);
  asked.push(u.split('?')[0]);
  if (u.startsWith('api/history')) historyAsked.push(decodeURIComponent(u));  // every question for a stretch of the past, as it was asked
  if (u.startsWith('api/state')) return reply(states.first);
  if (u.startsWith('api/nerd')) return reply(u.includes('deep=1') ? states.deep : states.nerd);
  if (u.startsWith('api/history')) {
    if (waiting) await new Promise(go => waiting.push(go));
    return reply(answerNow || states.past);
  }
  if (u.startsWith('api/replies')) return reply([]);
  if (u.startsWith('api/runs')) return runsFail ? { ok: false, status: runsFail, json: async () => ({}) } : reply(runsNow || states.runs || { open: null, runs: [] });  // the records of runs: those of the moments, those a check gave, or the failure it asked for
  if (u.startsWith('assets/spark.glb') && process.env.RINGTOP_MODEL && fs.existsSync(process.env.RINGTOP_MODEL)) {
    const bytes = fs.readFileSync(process.env.RINGTOP_MODEL);
    return { ok: true, status: 200, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
  }
  return { ok: false, status: 404, json: async () => ({}), arrayBuffer: async () => new ArrayBuffer(0) };
}
class Source { constructor(url) { this.url = url; sources.push(this); } close() {} }
// What a check in sheet mode does to the server from inside the page: the history waits until it is let go, answers
// with something else, says how it was asked; a moment goes down the stream.
let waiting = null, answerNow = null, glyph = null, runsNow = null, runsFail = 0;  // glyph: the pixels one letter of a drawing is wide, while a check lets words be measured. runsNow, runsFail: the records of runs a check gave, and the status it lets the server fail with
const server = {
  holdHistory() { waiting = waiting || []; },
  releaseHistory() { const all = waiting || []; waiting = null; for (const go of all) go(); },
  historyAnswers(value) { answerNow = value; },
  historyAsked: () => historyAsked.slice(),
  runsAnswer(value) { runsNow = value; runsFail = 0; },
  runsAsked: () => asked.filter(u => u === 'api/runs').length,
  runsFail(status) { runsFail = status; },
  say(state) { sources[sources.length - 1].onmessage({ data: JSON.stringify(state) }); },  // down the stream the page opened last
  streams: () => sources.map(s => s.url),  // every stream the page opened, in order, by its address
  texts: () => { const seen = new Set(), out = [world.location.hash]; for (const root of [document.body, document.documentElement, ...selected.values()]) held(root, seen, out); return out.filter(text => typeof text === 'string' && text); },  // every text the page holds: what its elements say, their titles, values, attributes and data
  measureWords(pixels) { glyph = pixels; },
  // the page draws so many frames, each `ms` after the one before; like a browser, a frame runs everything that asked for it
  draw(count, ms = 16.7) { for (let i = 0; i < count; i++) { clock += ms; for (const due of frames.splice(0)) due(clock); } },
  // one element gets a place of its own on the page, and the page hears that its size changed
  // the size of what the page watches changed: everything that watches a size hears it, as a browser tells it after a window or a column got wider
  resized() { for (const heard of sized) heard([]); },
  place(selector, box) { document.querySelector(selector).placed = { x: box.left, y: box.top, right: box.left + box.width, bottom: box.top + box.height, ...box }; world.pageHears('resize', {}); },
};
class Watcher { observe() {} unobserve() {} disconnect() {} }
const sized = [];  // what the page asked to hear whenever the size of an element it watches changes
class Sizes extends Watcher { constructor(heard) { super(); sized.push(heard); } }
const pageListens = {};  // what the page listens for on the window itself, by the kind of event
let reloads = 0, reloadMay = false;  // how often the page asked to start anew, and whether the loader has just asked it for a reason to
let clock = 1000;
const world = {
  document, console: { log() {}, warn() {}, info() {}, error: (...a) => errors.push('console.error: ' + a.join(' ')) },
  fetch, EventSource: Source, ResizeObserver: Sizes, IntersectionObserver: Watcher, MutationObserver: Watcher,
  requestAnimationFrame: cb => frames.push(cb), cancelAnimationFrame() {},
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},  // nothing runs later by itself: the test decides what happens
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  performance: { now: () => clock }, devicePixelRatio: 2, innerWidth: 1064, innerHeight: 625, screen: { width: 1064, height: 625 },
  location: { hash: states.hash || '', pathname: '/', search: neutral ? '?names=neutral' : states.search || '', href: 'http://127.0.0.1:8377/', reload: () => { reloads++; if (!reloadMay) errors.push('the page asked to reload'); } },
  history: { replaceState(state, title, address) { const at = String(address).indexOf('#'); world.location.hash = at < 0 ? '' : String(address).slice(at); } },  // the address changes without a new page: what stands behind it is kept
  addEventListener(type, heard) { (pageListens[type] = pageListens[type] || []).push(heard); }, removeEventListener() {}, getComputedStyle: () => new Style(),
  pageHears(type, event) { for (const heard of pageListens[type] || []) heard({ target: document.body, ...event }); },  // an event that reaches the window: from somewhere on the page no element of a check listens on
  CSS: { escape: s => String(s) }, createImageBitmap: async () => ({ width: 1, height: 1, close() {} }),
  TextDecoder, TextEncoder, Blob, URL, queueMicrotask, structuredClone, AbortController, server,
};
world.window = world.self = world;
const context = vm.createContext(world);
parse = vm.runInContext('text => JSON.parse(text)', context);  // what the page gets is made in its own world
const inPage = code => vm.runInContext(code, context);
const settle = async () => { for (let i = 0; i < 40; i++) await new Promise(done => setImmediate(done)); };
const attempt = async (what, code) => { try { inPage(code); await settle(); } catch (e) { fault(what, e); } };
// every text an element holds, and every element under it: what it says, its title and value, its attributes and data
function held(el, seen, out) {
  if (!el || seen.has(el)) return out;
  seen.add(el);
  out.push(el.text, el.title, el.value, ...el.attributes.values(), ...Object.values(el.dataset));
  for (const child of [...el.children, ...el.found.values()]) held(child, seen, out);
  return out;
}
const real = new RegExp(states.first.cluster.nodes.map(n => n.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'));
// what the outside wrote into the moments of the demo: programs and containers by their names, the kernel and the profile,
// and what its run source names: the queue, who holds the ring, every step and the job of every track
const runWords = 'Demo queue|Demo window|Release suite|Short prompts|Long prompts|Eight streams|Prefill sweep|Stall probe|Quality gate|Long documents|Short replies|Lists|Forms';
const outside = new RegExp(`${real.source}|VLLM|sglang|dockerd|systemd|solo-|demo-64k|config/|${runWords}`);
function lookForRealNames(what) {  // with neutral names, no element of the page and not its address may hold the real name of a Spark or a word of the outside
  if (!neutral) return;
  const seen = new Set(), texts = [world.location.hash];
  for (const root of [document.body, document.documentElement, ...selected.values()]) held(root, seen, texts);
  for (const text of texts) if (typeof text === 'string' && outside.test(text)) realFound.add(`${what}: ${text.slice(0, 90)}`);
}
const draw = (count, what) => {
  lookForRealNames(what);
  for (let i = 0; i < count; i++) {
    const next = frames.pop();
    frames.length = 0;
    if (!next) { errors.push(`${what}: no frame was asked for`); return; }
    clock += 16.7;
    try { next(clock); } catch (e) { fault(`${what}, frame ${i}`, e); return; }
    drawn++;
  }
};

(async () => {
  for (const file of files) {
    try { new vm.Script(fs.readFileSync(file, 'utf8'), { filename: path.basename(file) }).runInContext(context); } catch (e) { fault(`loading ${path.basename(file)}`, e); }
  }
  const hashAtFirst = world.location.hash;  // the address while the page still waits for its first moment
  await settle();
  const out = { mode, loaded: files.length, names: {}, ok: null, started: sources.length === 1, said: null, views: [], drawn: 0, hashAtFirst };
  for (const name of ['Scene', 'Nerd', 'Tour', 'Time', 'S', 'LIVE']) { try { out.names[name] = inPage(`typeof ${name}`); } catch (e) { out.names[name] = 'missing: ' + e.message; } }
  try { out.ok = inPage('typeof Scene === "undefined" ? null : Scene.ok !== false && typeof Scene.frame === "function" ? Scene.ok !== false : false'); } catch (e) { fault('Scene.ok', e); }  // null: a page without a scene, the calm one
  if (out.started && mode === 'sheet') {
    try { sources[0].onopen(); sources[0].onmessage({ data: JSON.stringify(states.next) }); } catch (e) { fault('the stream', e); }
    await settle();
    out.steps = [];
    for (const step of states.steps || []) {
      try { out.steps.push(inPage(step) ?? null); } catch (e) { fault(`step ${out.steps.length}`, e); out.steps.push(null); }
      await settle();
    }
  } else if (out.started) {
    try { sources[0].onopen(); sources[0].onmessage({ data: JSON.stringify(states.next) }); } catch (e) { fault('the stream', e); }
    await settle();
    out.said = document.querySelector('#link').lastElementChild.textContent;
    clock += 2500;  // the scene throws no sparks in its first two seconds
    draw(6, 'after the stream');
    const inPanel = cls => `document.querySelector('#panel').under().find(e => e.classList.contains('${cls}'))`;  // one element of the panel by its class, as code for the page
    // "cooling wide": the cooling view, already open, in its other form. "node box": the sheet of a Spark, already open, with all it says only on demand: the box of its bar opened, and a pointer on its first curve
    const onDemand = `(sheet => { sheet.under().find(e => e.classList.contains('q-info')).fire('click', {}); sheet.fire('pointermove', { target: sheet.under().find(e => e.matches('svg.plot')), clientX: 500, button: 0, buttons: 0 }); })(document.querySelector('#spark'))`;
    out.cooling = {};
    for (const view of ['why', 'memory', 'cooling', 'cooling wide', 'events', 'run', 'node', 'node box', 'ring']) {
      await attempt(`view ${view}`, view === 'node' ? `setView('node', S.nodes[1].name)` : view === 'cooling wide' ? 'Cooling.reshape(true)' : view === 'node box' ? onDemand : `setView(${JSON.stringify(view)})`);
      draw(2, `view ${view}`);
      if (view.startsWith('cooling')) {  // the cooling view keeps what it explains in a box and the four figures of every curve behind a button: both are opened, in either form, and the page is looked at while they stand
        await attempt(`${view}: the figures and the box`, `${inPanel('q-fig')}.fire('click', {}); ${inPanel('q-info')}.fire('click', {})`);
        draw(1, `view ${view}, the box open`);
        try { out.cooling[view] = inPage(`({ box: ${inPanel('q-pop')}.children.filter(e => e.tagName === 'H4').length, open: !${inPanel('q-pop')}.hidden, figures: document.querySelector('#panel').classList.contains('figures') })`); } catch (e) { fault(`${view}: the box`, e); }
      }
      if (view === 'node') {
        out.sheet = { parts: document.querySelector('#spark').children.length, shown: !document.querySelector('#spark').hidden, panel: !document.querySelector('#panel').hidden };  // the sheet of one Spark, while it is open
        await attempt('a part of the open Spark is picked', `setPart('cx7')`);  // its panel names the Sparks at the other ends of its links, the labels stand beside the parts, and the lens offers its way back
        draw(3, 'a part picked');
        try { out.part = inPage(`({ panel: !document.querySelector('#panel').hidden, links: document.querySelector('#panel').under().filter(e => e.text.startsWith('Link to ')).length, labels: document.querySelector('#callouts').children.filter(c => c.under().some(e => e.text)).length, home: document.querySelector('#lens-home').hidden === false })`); } catch (e) { fault('the part', e); }
        await attempt('the part is let go', 'setPart(null)');
        draw(1, 'the part let go');
      }
      const sheet = document.querySelector('#spark');
      if (view === 'node box') {  // what stood open while the names were looked for: the headings of the box, and the word beside the cursor
        const pop = sheet.under().find(e => e.classList.contains('q-pop')), word = sheet.under().find(e => e.getAttribute('class') === 'cur-word');
        out.box = { headings: pop && !pop.hidden ? pop.children.filter(e => e.tagName === 'H4').length : 0, word: word ? word.text : '' };
      }
      out.views.push(view);
    }
    await attempt('nerd opens', 'Nerd.toggle(true)');
    draw(4, 'nerd open');
    out.nerdLive = document.querySelector('#n-left').children.length;  // the live side, before any tab is picked
    for (const tab of ['nodes', 'links', 'engine', 'requests', 'sync', 'history', 'live']) { await attempt(`nerd tab ${tab}`, `Nerd.tab(${JSON.stringify(tab)})`); out.views.push('nerd:' + tab); }
    await attempt('nerd closes', 'Nerd.toggle(false)');
    await attempt('tour starts', 'Tour.toggle(true)');
    draw(2, 'tour');
    await attempt('tour ends', 'Tour.toggle(false)');
    await attempt('time machine opens', 'Time.toggle(true)');
    await attempt('time machine goes back', `Time.go(${states.past.t[Math.floor(states.past.t.length / 2)]})`);
    draw(2, 'looking back');
    await attempt('time machine closes', 'Time.toggle(false)');
    draw(2, 'back in the present');
  }
  lookForRealNames('at the end');
  if (neutral && out.started) {  // ringtop comes back: on the same cluster, then on another one of the same shape, whose Sparks get the same neutral names. Did the page ask to start anew?
    const same = JSON.stringify(states.next), other = same.replace(new RegExp(real.source, 'g'), name => 'box' + name);
    out.reloaded = {};
    reloadMay = true;
    for (const [what, moment] of [['same', same], ['other', other]]) {
      const before = reloads;
      try { sources[0].onmessage({ data: moment }); } catch (e) { fault(`a moment of the ${what} cluster`, e); }
      await settle();
      out.reloaded[what] = reloads > before;
    }
    reloadMay = false;
  }
  out.hash = world.location.hash;
  if (neutral) {
    out.real = [...realFound].slice(0, 8);
    out.history = { asked: historyAsked.length, real: historyAsked.filter(u => real.test(u)).length, neutral: historyAsked.filter(u => /[=,]spark-\d/.test(u)).length };
  }
  out.drawn = drawn;
  out.asked = [...new Set(asked)].sort();
  out.errors = errors;
  console.log(JSON.stringify(out));
})();
