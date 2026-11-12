// The scene, its lens: how far the picture of the open Spark is zoomed, around which place, and which part stands in its middle.
'use strict';
// The lens on the open Spark: takes steps of zoom, a part to show and the way home, and gives the camera the lens of every frame.
function sceneLens(shared) {  // seam
  const { midOf, project, sub, toWorld, view } = shared;  // seam
  const now = { z: 1, q: [0, 0], aim: [0, 0, 0] }, goal = { z: 1, q: [0, 0], part: null };  // the lens as it is drawn, and as it was asked for
  let last = 0, homing = false, before = null;  // homing: the machine turns back to how it opened. before: the lens as it was asked for when the first part was picked
  const button = $('#lens-home');  // takes the view back; it shows only while there is something to take back
  // The hole the scene shows through, in units of the page: its middle and half its size. Read from where the hole lies, never from a fixed size.
  const hole = () => { const b = view.hole; return { mid: [2 * (b.left + b.width / 2) / view.cssW - 1, 1 - 2 * (b.top + b.height / 2) / view.cssH], half: [b.width / view.cssW, b.height / view.cssH] }; };
  // One part of the open Spark by its name, or nothing: without an open Spark, without a model, or for a name the model does not have.
  const partOf = name => shared.focusNode && shared.model && name != null ? shared.model.parts[shared.model.index.get(name)] : undefined;
  function sizeOf(p, q) {  // How large one part of the open Spark is drawn at zoom 1: the longer side of its box on the page, as a share of the shorter side of the hole.
    const at = q.index * 6, xs = [], ys = [];
    for (let c = 0; c < 8; c++) { const [x, y] = project(toWorld(p, [0, 1, 2].map(k => p.box[at + (c >> k & 1) * 3 + k]))); xs.push(x); ys.push(y); }
    return Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / view.zoom / Math.min(view.hole.width, view.hole.height);
  }
  // One step of zoom around a place of the page, given in pixels; without a place, around the place a part is shown at. Only an open Spark is zoomed.
  function zoomBy(k, px, py) { if (shared.focusNode && shared.focusGoal) Object.assign(goal, zoomAt(goal, k, px == null ? base() : [px / view.cssW * 2 - 1, 1 - py / view.cssH * 2], hole())); }
  // Where the middle of the open machine lies at zoom 1, in units of the page: beside the labels where they stand in one column, else in the middle of the hole. A part that is shown starts from there and is brought there: its own label stays, and would lie over it in the middle of a narrow hole.
  const base = () => [view.shift[0] + view.nudge, view.shiftOpen];
  function zoomOn(name) {  // Brings one part of the open Spark to the middle of the hole, as large as half of it; the camera then looks at that part and turns around it.
    const q = partOf(name);
    if (!q || !shared.focusGoal) return;
    Object.assign(goal, zoomOnto(sizeOf(shared.focusNode, q), base(), hole(), base()), { part: name });
    homing = false;
  }
  function zoomPick(name) {  // A part of the open Spark is picked: it comes to the middle of the hole, twice as near as the Spark opens, and the camera turns around it. No part is picked any more: the lens goes back to where it stood before the first one was.
    if (name == null) { if (before) Object.assign(goal, before); before = null; return; }
    if (!partOf(name) || !shared.focusGoal) return;
    before = before || { z: goal.z, q: goal.q.slice(), part: goal.part };
    Object.assign(goal, zoomPicked(goal, base(), hole(), base()), { part: name });
    homing = false;
  }
  function zoomOut() {  // Takes the view back to the one a Spark opens with: no zoom, no shift, no part in the middle, and the machine turned back the short way round.
    Object.assign(goal, { z: 1, q: [0, 0], part: null });
    before = null;  // nothing older to return to
    shared.orbit = [Math.atan2(Math.sin(shared.orbit[0]), Math.cos(shared.orbit[0])), shared.orbit[1]];
    homing = true;
  }
  function zoomMove(dx, dy) {  // Moves the picture of the open Spark by so many pixels of the page, as far as the hole lets it: at zoom 1, and so without an open Spark, not at all. A hand moves it, so it is there at once, without a run-out.
    const to = zoomHeld(goal.z, [goal.q[0] + 2 * dx / view.cssW, goal.q[1] - 2 * dy / view.cssH], hole());
    now.q = now.q.map((v, k) => v + to[k] - goal.q[k]);
    goal.q = to;
  }
  // A hand turned the machine: its way home ends there, and the turn stays.
  const zoomTurned = () => { homing = false; };
  // Whether there is anything to take back: a zoom, a shift, a part in the middle, or a machine that was turned.
  const zoomed = () => !lensHome(goal, homing ? [0, 0] : shared.orbit);
  // The lens of this frame, for the camera: a step closer to what was asked for, the shift held inside the hole as it lies now (the one asked for and the one drawn), and the machine a step closer to how it opened if it was sent home. Shows the button that takes the view back while there is something to take back.
  function lensAt(t) {
    const dt = Math.min(.05, Math.max(0, t - last)), p = shared.focusNode, q = partOf(goal.part);
    last = t;
    goal.q = zoomHeld(goal.z, goal.q, hole());  // the hole may lie elsewhere than when this was asked
    const aim = q ? sub(toWorld(p, midOf(p, q)), toWorld(p, [0, shared.model.stackMid, 0])) : [0, 0, 0];
    Object.assign(now, zoomEased(now, { z: goal.z, q: goal.q, aim }, dt, calm.matches));
    now.q = zoomHeld(now.z, now.q, hole());  // what is drawn is held at the zoom it is drawn with: a push that a nearer zoom allows, made while the lens still runs in, would show what lies far beside the hole
    if (homing) {
      const left = calm.matches ? 0 : Math.exp(-dt / ZOOM_EASE);
      shared.orbit = shared.orbit.map(v => Math.abs(v * left) < 1e-3 ? 0 : v * left);
      homing = shared.orbit.some(v => v !== 0);
    }
    if (button.hidden === zoomed()) button.hidden = !zoomed();
    return now;
  }

  Object.assign(shared, { lensAt, zoomBy, zoomMove, zoomOn, zoomOut, zoomPick, zoomTurned, zoomed });  // seam
}  // seam
