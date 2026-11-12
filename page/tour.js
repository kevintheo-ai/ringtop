// The tour: the page shows itself, for a screen on the wall, until any key or click hands it back.
'use strict';
/* ---- the tour: the page shows itself, for a screen on the wall. Any key or click hands it back ---- */
const Tour = (() => {
  const PARTS = ['gb10_die_gpu', 'cx7', 'fan_left', 'lpddr_0', 'ssd_m2', 'thermal_module'];
  const btn = $('#tour-btn'), told = new Map();  // told: the trouble each Spark was last visited for
  let on = false, plan = [], at = -1, began = 0, timer = 0, parted = false;
  function stations() {  // The stops of one lap: the ring, the run if it has steps, why, every Spark that answers, memory, cooling and events.
    const list = [{ view: 'ring', secs: 14, word: 'the ring' }];
    if ((S.run.steps || []).length > 1) list.push({ view: 'run', secs: 8, word: 'the run' });
    list.push({ view: 'why', secs: 9, word: 'why' });
    S.nodes.forEach((n, i) => { if (n.live) list.push({ view: 'node', node: n.name, secs: 13, part: PARTS[i % PARTS.length], word: n.name }); });
    list.push({ view: 'memory', secs: 8, word: 'memory' }, { view: 'cooling', secs: 9, word: 'cooling' }, { view: 'events', secs: 8, word: 'events' });
    return list;
  }
  function show(station) {  // Opens the view of one stop and names it on the button.
    began = performance.now(); parted = false;
    setView(station.view, station.node || null);
    btn.textContent = `Tour: ${station.word}`;
  }
  function trouble() {  // a Spark that needs a look gets one at once, and once per trouble
    for (const n of S.nodes) {
      const note = nodeNote(n, S.identity);
      if (!note.cls) { told.delete(n.name); continue; }
      if (told.get(n.name) === note.text) continue;
      told.set(n.name, note.text);
      return { view: 'node', node: n.name, secs: 16, word: `${n.name} needs a look`, urgent: true };
    }
    return null;
  }
  // Moves the tour on, four times a second: a Spark in trouble first, a part of the open Spark halfway through its stop, then the next stop.
  function tick() {
    if (!on || !S) return;
    const here = plan[at], urgent = here && here.urgent ? null : trouble();
    if (urgent) { plan.splice(at + 1, 0, urgent); at++; show(urgent); return; }
    const k = here ? (performance.now() - began) / 1000 / here.secs : 1;
    btn.style.setProperty('--p', (clamp(k) * 100).toFixed(1) + '%');
    if (here && here.part && !parted && k > .45 && Scene.opened()) { parted = true; setPart(here.part); }
    if (k < 1) return;
    if (here && here.urgent) { plan.splice(at, 1); at--; }      // shown once, not on every lap
    if (at + 1 >= plan.length) { plan = stations(); at = -1; }  // a new lap sees the cluster as it is now
    show(plan[++at]);
  }
  function toggle(want = !on) {  // Starts or ends the tour; it starts live, with nerd mode closed, and lets the scene drift meanwhile.
    if (want === on || !S) return;
    on = want;
    btn.setAttribute('aria-pressed', String(on));
    Scene.drift(on);
    clearInterval(timer);
    if (on) {
      Time.live();
      if (Nerd.isOpen()) Nerd.toggle(false);
      told.clear(); plan = stations(); at = 0; show(plan[0]);
      timer = setInterval(tick, 250);
    } else { btn.textContent = 'Tour'; btn.style.removeProperty('--p'); }
  }
  btn.addEventListener('click', () => toggle());
  for (const type of ['pointerdown', 'wheel', 'gesturestart', 'keydown', 'touchstart']) addEventListener(type, e => { if (on && tourStops(type, e)) toggle(false); }, { capture: true, passive: true });  // gesturestart: a pinch as Safari and other WebKit web views say it; elsewhere it is a wheel
  return { toggle, isOn: () => on };
})();

