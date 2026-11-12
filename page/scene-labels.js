// The scene, its labels: the names and readings beside the parts of an open Spark, each tied to its part by a line.
'use strict';
// The labels of the open Spark: builds them once, fills them from the moment on the page, and places them every frame.
function sceneLabels(shared) {  // seam
  const { LABELS_AT, enter, midOf, project, toModel, toWorld, view } = shared;  // seam
  const CALLOUTS = ['gb10_die_gpu', 'gb10_die_cpu', 'lpddr_2', 'cx7', 'qsfp_cage', 'ssd_m2', 'fan_left', 'fan_right', 'thermal_module', 'fin_stack'];
  /* DOM labels on the open machine: anchors projected every frame, faded out while another part stands in front, the part lies outside the hole, or the view is zoomed in */
  const callouts = [];
  let calloutsOn = false;
  function buildCallouts() {  // Builds the labels of the open Spark with their leader lines, once.
    if (callouts.length) return;
    const holder = $('#callouts'), lines = $('#leaders');
    for (const name of CALLOUTS) {
      const i = shared.model.index.get(name);
      if (i === undefined) continue;
      const el = make('button', 'callout', holder);
      el.type = 'button'; el.dataset.part = name;
      make('b', '', el, partTitle(name, shared.model.parts[i].label));
      callouts.push({ name, i, el, v: make('span', '', el), line: draw('polyline', {}, lines), dot: draw('circle', { r: 2.4 }, lines), y: 0, w: 0, side: -1, placed: false, ty: 0, ax: 0, ay: 0, a: 0 });  // a: how visible it is, from 0 to 1
    }
  }
  function fillCallouts() {  // Writes the short line of every label from the moment on the page.
    if (!shared.focusNode || !S || !callouts.length) return;
    const n = S.nodes.find(x => x.name === shared.focusNode.name);
    if (!n) return;
    for (const c of callouts) { const text = partShort(c.name, n); if (c.v.textContent !== text) { c.v.textContent = text; c.w = 0; } }
  }
  // Hides one label with its line and its dot; when it comes again, it comes anew beside its part.
  function hideCallout(c) { c.el.style.visibility = 'hidden'; c.line.style.opacity = 0; c.dot.style.opacity = 0; c.placed = false; c.a = 0; }
  function anchor(c, p, eye) {  // Finds where the dot of one label lies this frame, and says whether another part stands in front of its part.
    const q = shared.model.parts[c.i], m = midOf(p, q), d = [m[0] - eye[0], m[1] - eye[1], m[2] - eye[2]];
    [c.ax, c.ay] = project(toWorld(p, m));
    for (const other of shared.model.parts) {
      if (other === q || other.skin || other.rotor) continue;
      const at = other.index * 6;
      if ([0, 1, 2].every(k => m[k] > p.box[at + k] && m[k] < p.box[at + 3 + k])) continue;
      if (enter(p.box, at, eye, d) < .985) return true;
    }
    return false;
  }
  const H = 36, GAP = 40;  // how high a label is, and how far the tops of two labels on one side lie apart at least
  function stack(list, hole) {  // Gives the labels of one side their heights: each beside its part, none on another, all inside the hole.
    list.sort((a, b) => a.ay - b.ay);
    let y = hole.top + 4, limit = hole.bottom - H - 4;
    for (const c of list) { c.ty = Math.max(y, c.ay - H / 2); y = c.ty + GAP; }
    for (let k = list.length - 1; k >= 0; k--) { list[k].ty = Math.min(list[k].ty, limit); limit = list[k].ty - GAP; }
  }
  function paint(c, hole) {  // Draws one label at its height with its line and its dot, as visible as it is this frame.
    c.y = c.placed && !calm.matches ? c.y + (c.ty - c.y) * .16 : c.ty;
    c.placed = true;
    if (!c.w) c.w = c.el.offsetWidth;
    const s = c.side, alpha = c.a, x = s ? hole.right - c.w - 4 : hole.left + 4, edge = s ? x : x + c.w, my = c.y + H / 2, bend = edge + (s ? -12 : 12);
    c.el.style.transform = `translate3d(${x.toFixed(1)}px,${c.y.toFixed(1)}px,0)`;
    c.el.style.opacity = alpha.toFixed(2);
    c.el.style.visibility = alpha > .05 ? 'visible' : 'hidden';
    c.el.classList.toggle('on', shared.selected === c.name);
    c.line.setAttribute('points', `${edge.toFixed(1)},${my.toFixed(1)} ${bend.toFixed(1)},${my.toFixed(1)} ${c.ax.toFixed(1)},${c.ay.toFixed(1)}`);
    c.line.style.opacity = (alpha * (shared.selected === c.name ? .95 : .55)).toFixed(2);
    c.dot.setAttribute('cx', c.ax.toFixed(1)); c.dot.setAttribute('cy', c.ay.toFixed(1));
    c.dot.style.opacity = alpha.toFixed(2);
  }
  // Places the labels of the open Spark every frame: each beside its part, on the nearer side, none on top of another. A label fades in and out instead of coming and going at once: it wants to show by how far the view is zoomed and whether its part can be seen (labelShows), and gets there over a quarter of a second.
  function drawCallouts() {
    const p = shared.focusNode, on = !!(p && shared.model && shared.focusGoal && p.open >= LABELS_AT);
    if (!on && !calloutsOn) return;
    calloutsOn = on;
    if (!on) { callouts.forEach(hideCallout); return; }
    const eye = toModel(p, view.eye), hole = view.hole, mid = hole.left + hole.width / 2, sides = [[], []];
    for (const c of callouts) {
      const hidden = anchor(c, p, eye), inside = c.ax >= hole.left && c.ax <= hole.right && c.ay >= hole.top && c.ay <= hole.bottom;
      const want = labelShows({ zoom: view.zoom, picked: shared.selected === c.name, pointed: shared.hovered === c.name, inside, hidden });
      c.a = calm.matches ? want : c.a + (want - c.a) * .16;
      if (!want && c.a < .02) { hideCallout(c); continue; }
      c.side = view.oneSide ? 0 : c.side < 0 || Math.abs(c.ax - mid) > 20 ? (c.ax < mid ? 0 : 1) : c.side;
      sides[c.side].push(c);  // a label on its way out keeps its place until it is gone: none slides over it
    }
    for (const list of sides) { stack(list, hole); for (const c of list) paint(c, hole); }
  }

  Object.assign(shared, { buildCallouts, drawCallouts, fillCallouts });  // seam
}  // seam
