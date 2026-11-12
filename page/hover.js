// Hover, pointer and keys: one moment across every trace, one node across scene and dock.
'use strict';
/* ---- hover: one moment across every trace, one node across scene and dock ---- */
let hoverT = null, hoverQueued = false;
function setHover(t) {  // Sets the moment the pointer rests on, or none, and repaints the numbers once in the next frame.
  hoverT = t;
  if (hoverQueued) return;
  hoverQueued = true;
  requestAnimationFrame(() => { hoverQueued = false; renderDockValues(); renderDecomp(); });
}
function hoverFrom(e) {  // The moment under the pointer on a trace, from where it stands across the half hour.
  const svg = e.target.closest && e.target.closest('svg.trace');
  if (!svg || !S) return setHover(null);
  const box = svg.getBoundingClientRect();
  setHover(S.t - WINDOW + clamp((e.clientX - box.left) / box.width) * WINDOW);
}
function highlight(name, on) {  // Lights one Spark up in the dock and in the scene together, or lets it go.
  const t = tiles.get(name);
  if (t) t.tile.classList.toggle('hot', on);
  Scene.hot(name, on);
}
let clickedPart;  // the part the first click of a double click fell on, null beside the parts; undefined when that click ended a drag and picked nothing
// Connects wheel, pinch, double click and the button in the corner of the hole to the lens of the open Spark. Over a Spark that is open or opening the wheel and the right button belong to the scene: they are kept from the browser, so the page neither scrolls nor zooms as a whole and no menu opens. Everywhere else they are the page's own.
function wireLens(hole) {
  let pinch = 1;  // how far apart the fingers of the running pinch were at its last event, against its start
  const zoom = (e, k) => { if (V !== 'node') return; e.preventDefault(); if (Scene.opened()) Scene.zoom(k, e.clientX, e.clientY); };
  const wheel = e => { const by = wheelMoves(e); if (!by) return zoom(e, zoomStep(e)); if (V !== 'node') return; e.preventDefault(); Scene.move(...by); };  // with Shift held it moves the picture
  for (const el of [hole, $('#callouts')]) {  // a label lies over the scene: the wheel over it is the wheel over the scene
    el.addEventListener('wheel', wheel, { passive: false });  // a pinch arrives here too, as a wheel with Ctrl held: Chrome, Firefox
    el.addEventListener('gesturestart', e => { pinch = 1; zoom(e, 1); });  // Safari and other WebKit web views say a pinch in events of their own
    el.addEventListener('gesturechange', e => { const k = e.scale > 0 ? e.scale / pinch : 1; pinch = e.scale > 0 ? e.scale : pinch; zoom(e, k); });
    el.addEventListener('contextmenu', e => { if (V === 'node') e.preventDefault(); });  // the right button moves the picture here
  }
  const twice = part => {  // a double click: the part under it comes to the middle and is the picked one, beside the parts the view goes back
    const [act, name] = sceneDouble({ opened: Scene.opened(), part });
    if (act === 'centre') { if (VP !== name) setPart(name); Scene.centre(name); } else if (act === 'home') Scene.home();
  };
  // a double click means the part its first click fell on: that click picked it, and by now the lens has carried it away from under the pointer
  hole.addEventListener('dblclick', e => twice(!Scene.opened() ? null : clickedPart !== undefined ? clickedPart : Scene.part(e.clientX, e.clientY)));
  $('#callouts').addEventListener('dblclick', e => { const c = e.target.closest('.callout'); if (c) twice(c.dataset.part); });
  const home = $('#lens-home');
  for (const type of ['pointerdown', 'click', 'dblclick']) home.addEventListener(type, e => e.stopPropagation());  // the button lies in the hole: a press on it is no press on the scene
  home.addEventListener('click', () => Scene.home());
}
function lensKey(key) {  // Lets a key work the lens of the open Spark: plus and minus zoom around the place a part is shown at, zero takes the view back. Says whether the key was one of them and a Spark stood open.
  const k = zoomKey(key);
  if (k == null || !Scene.opened()) return false;
  if (k) Scene.zoom(k); else Scene.home();
  return true;
}
// Connects pointer, clicks and keys to the page, once: hover on traces, opening a Spark or a part, the lens of the open Spark, the keys for views, tour, time machine and nerd mode.
function wire() {
  for (const zone of [$('#dock'), $('#speed')]) {
    zone.addEventListener('pointermove', hoverFrom);
    zone.addEventListener('pointerleave', () => setHover(null));
  }
  $('#dock').addEventListener('pointerover', e => { const t = e.target.closest('.tile'); if (t) highlight(t.dataset.node, true); });
  $('#dock').addEventListener('pointerout', e => { const t = e.target.closest('.tile'); if (t) highlight(t.dataset.node, false); });
  $('#tags').addEventListener('pointerover', e => { const t = e.target.closest('.tag'); if (t) highlight(t.dataset.node, true); });
  $('#tags').addEventListener('pointerout', e => { const t = e.target.closest('.tag'); if (t) highlight(t.dataset.node, false); });
  $('#dock').addEventListener('click', e => { const t = e.target.closest('.tile'); if (t) setView('node', t.dataset.node); });
  $('#dock').addEventListener('keydown', e => { const t = e.target.closest('.tile'); if (t && e.key === 'Enter') setView('node', t.dataset.node); });
  $('#tags').addEventListener('click', e => { const t = e.target.closest('.tag'); if (t) setView('node', t.dataset.node); });
  const hole = $('#hole');
  let drag = null, dragged = false;
  hole.addEventListener('pointerdown', e => { if (Scene.opened()) { drag = [e.clientX, e.clientY]; dragged = false; hole.setPointerCapture(e.pointerId); } });
  hole.addEventListener('pointerup', e => { drag = null; if (e.button) dragged = false; });  // no click follows a button other than the main one: nothing to swallow
  hole.addEventListener('pointercancel', () => { drag = null; dragged = false; });
  hole.addEventListener('pointermove', e => {
    if (drag) {
      const dx = e.clientX - drag[0], dy = e.clientY - drag[1];
      if (dragged || Math.hypot(dx, dy) > 3) { dragged = true; if (dragMoves(e)) Scene.move(dx, dy); else Scene.orbit(dx, dy); drag = [e.clientX, e.clientY]; }  // with Shift or the right button the picture moves, else the machine turns
      return;
    }
    if (Scene.opened()) { const q = Scene.part(e.clientX, e.clientY); Scene.hover(q); hole.style.cursor = q ? 'pointer' : 'grab'; }
    else hole.style.cursor = Scene.pick(e.clientX, e.clientY) ? 'pointer' : '';
  });
  hole.addEventListener('click', e => {
    if (dragged) { dragged = false; clickedPart = undefined; return; }
    const opened = Scene.opened(), part = opened ? Scene.part(e.clientX, e.clientY) : null;
    if (!(e.detail > 1)) clickedPart = part;
    const [act, name] = sceneClick({ opened, part, picked: VP, hit: Scene.pick(e.clientX, e.clientY), view: V, home: !Scene.zoomed(), count: e.detail || 1 });
    if (act === 'part') setPart(name); else if (act === 'node') setView('node', name); else if (act === 'ring') setView('ring');
  });
  wireLens(hole);
  $('#callouts').addEventListener('click', e => { const c = e.target.closest('.callout'); if (c && !(e.detail > 1)) setPart(c.dataset.part === VP ? null : c.dataset.part); });  // not the second click of a double click: it would let go what the first one picked
  $('#now').addEventListener('click', () => setView('run'));  // the run of now leads to the runs: its card, its stations, and the runs before it
  addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey || !S) return;
    const typing = e.target.matches && e.target.matches('input,select,textarea');
    if (e.key === 'Escape') {  // one step back out: a box that explains (board.js), then the deep view, then a picked part, then the open view, then the past, then the strip
      ({ box: () => shutBox(), nerd: () => Nerd.toggle(false), part: () => setPart(null), view: () => setView('ring'), live: () => Time.live(), strip: () => Time.toggle(false) })[escapeDoes({ box: !!shutBox, nerd: Nerd.isOpen(), view: V, part: VP, past: Time.isPast(), strip: Time.isOpen() })]();
      return;
    }
    if (typing) return;
    if (e.key === 'n' || e.key === 'N') { if (!NEUTRAL) { Time.live(); Nerd.toggle(); } return; }  // the deep view only knows now; with neutral names it stays shut
    if (Nerd.isOpen()) { Nerd.key(e); return; }
    if (e.key === 'h' || e.key === 'H') { toggleNames(); return; }
    if (e.key === 'k' || e.key === 'K') { Tour.toggle(); return; }
    if (e.key === 't' || e.key === 'T') { Time.toggle(); return; }
    if (Time.isOpen() && Time.key(e)) return;
    if (lensKey(e.key)) return;
    if (e.key >= '1' && e.key <= String(VIEWS.length)) setView(VIEWS[+e.key - 1][0]);
    else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      const names = S.nodes.map(n => n.name), at = names.indexOf(VN);
      setView('node', names[at < 0 ? 0 : (at + (e.key === 'ArrowRight' ? 1 : -1) + names.length) % names.length]);
    }
  });
  addEventListener('pointermove', e => {
    for (const g of document.querySelectorAll('.glass')) {
      const b = g.getBoundingClientRect();
      g.style.setProperty('--mx', (e.clientX - b.left) + 'px');
      g.style.setProperty('--my', (e.clientY - b.top) + 'px');
    }
  }, { passive: true });
}

