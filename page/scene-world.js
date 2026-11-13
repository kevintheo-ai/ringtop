// The scene, its world: how a cluster stands on the ice, what a moment of data does to it, and the sparks that fly.
'use strict';
// The world of the scene: stands a cluster on the ice, turns each moment of data into light, and lets the sparks fly.
function sceneWorld(shared) {  // seam
  const { CLOSE_S, EX_AT, MAX, OPEN_S, OWN_SPARKS, attr, buffer, buildCallouts, fillCallouts, fire, gl, norm, parts, pose, resize, state, sub, vao } = shared;  // seam
  function sparkMesh(half, R) {  // The plain box that stands for a Spark while its model is not there: a slab with rounded edges.
    const stops = a => { const r = R / a; return [-1, -1 + r * .3, -1 + r * .7, -1 + r, 1 - r, 1 - r * .7, 1 - r * .3, 1]; };
    const out = [];
    const vertex = q => {
      const inner = q.map((v, i) => Math.min(half[i] - R, Math.max(R - half[i], v)));
      const d = norm(sub(q, inner));
      out.push(inner[0] + d[0] * R, inner[1] + d[1] * R, inner[2] + d[2] * R, ...d);
    };
    for (let axis = 0; axis < 3; axis++) for (const sign of [-1, 1]) {
      const u = (axis + 1) % 3, w = (axis + 2) % 3, us = stops(half[u]), ws = stops(half[w]);
      const at = (a, b) => { const q = [0, 0, 0]; q[axis] = sign * half[axis]; q[u] = us[a] * half[u]; q[w] = ws[b] * half[w]; return q; };
      for (let i = 0; i < us.length - 1; i++) for (let j = 0; j < ws.length - 1; j++)
        for (const [a, b] of [[i, j], [i + 1, j], [i + 1, j + 1], [i, j], [i + 1, j + 1], [i, j + 1]]) vertex(at(a, b));
    }
    return new Float32Array(out);
  }

  // Starts a wave on the ice; the six newest are kept.
  function wave(x, z, s) { state.waves.push({ x, z, born: performance.now() / 1000, s }); if (state.waves.length > 6) state.waves.shift(); }

  // Stands a cluster on the ice, once: the Sparks around the core, the lanes of their cables (pairs, from lanePairs), their tags and the chips between them.
  function build(cluster, pairs) {
    const n = cluster.nodes.length;
    const start = n === 4 ? -3 * Math.PI / 4 : -Math.PI / 2;
    const side = n < 2 ? .33 : Math.min(.33, 2 * Math.sin(Math.PI / n) * .24);
    const verts = [];
    let index = 0;
    const lane = (key, points, second) => {
      if (index >= 32) return;  // ponytail: the shader holds 32 lanes (16 nodes); a bigger cluster shows no links beyond that
      let len = 0;
      for (let i = 0; i < points.length - 1; i++) {
        const [ax, az] = points[i], [bx, bz] = points[i + 1];
        const dx = bx - ax, dz = bz - az, l = Math.hypot(dx, dz) || 1, nx = -dz / l * .05, nz = dx / l * .05;
        const q = [[ax + nx, az + nz, len, 1], [ax - nx, az - nz, len, -1], [bx + nx, bz + nz, len + l, 1], [bx - nx, bz - nz, len + l, -1]];
        for (const k of [0, 1, 2, 2, 1, 3]) verts.push(q[k][0], .015, q[k][1], q[k][2], q[k][3], index);
        len += l;
      }
      state.lanes.set(key, { index, phase: 0, speed: 0, energy: 0, speedGoal: 0, energyGoal: 0, second });
      index++;
    };
    state.nodes = cluster.nodes.map((node, i) => {
      const a = start + i * TAU / n, x = Math.cos(a), z = Math.sin(a);
      const parts = shared.model ? shared.model.parts.length : 0;
      return { name: node.name, rank: node.rank, head: node.head, a, x, z, yaw: -x * .5, side, glow: 0, glowGoal: .1, heat: 0, heatGoal: 0, live: 1, liveGoal: 1, hot: 0, hotGoal: 0, load: 0, loadGoal: 0, tone: [.95, .72, .38], order: i, risen: false,
        open: 0, openGoal: 0, spin: i * 1.3, posed: false, atY: 0, pose: new Float32Array(parts * 3), box: new Float32Array(parts * 6), scale: shared.model ? side / shared.model.width : 1, lift: shared.model ? (.012 - shared.model.stackLo) * side / shared.model.width : 0,
        gpu: 0, gpuGoal: 0, cpu: 0, cpuGoal: 0, mem: 0, memGoal: 0, net: 0, netGoal: 0, therm: 0, thermGoal: 0, ssd: 0, ssdGoal: 0 };
    });
    const across = (from, to) => {  // a chord between two Sparks that are no neighbours, beside the one that runs back
      const dx = to.x - from.x, dz = to.z - from.z, l = Math.hypot(dx, dz) || 1, ox = -dz / l * .05, oz = dx / l * .05;
      return [[from.x * .97 + ox, from.z * .97 + oz], [to.x * .97 + ox, to.z * .97 + oz]];
    };
    for (const [i, j, chord] of pairs) {
      const a = state.nodes[i], b = state.nodes[j];
      if (chord) { lane(a.rank + '>' + b.rank, across(a, b), 0); lane(b.rank + '>' + a.rank, across(b, a), 1); continue; }
      const end = a.a + TAU / n, arc = (r, reverse) => {
        const out = [];
        for (let k = 0; k <= 40; k++) { const t = a.a + (end - a.a) * (reverse ? 1 - k / 40 : k / 40); out.push([Math.cos(t) * r, Math.sin(t) * r]); }
        return out;
      };
      lane(a.rank + '>' + b.rank, arc(1.05, false), 0);
      lane(b.rank + '>' + a.rank, arc(.95, true), 1);
    }
    if (!pairs.length && n > 1) {  // Sparks on a switch: every lane runs to the middle. One Spark alone has none
      for (const p of state.nodes) {
        const dx = -p.z * .05, dz = p.x * .05;
        lane(p.rank + '>hub', [[p.x + dx, p.z + dz], [p.x * .22 + dx, p.z * .22 + dz]], 0);
        lane('hub>' + p.rank, [[p.x * .22 - dx, p.z * .22 - dz], [p.x - dx, p.z - dz]], 1);
      }
    }
    shared.laneVerts = verts.length / 6;
    shared.laneVao = vao(() => { buffer(new Float32Array(verts)); attr(0, 3, 24, 0); attr(1, 3, 24, 12); });
    const mesh = sparkMesh([side / 2, side * .17, side / 2], .016);
    shared.sparkVerts = mesh.length / 6;
    shared.sparkVao = vao(() => { buffer(mesh); attr(0, 3, 24, 0); attr(1, 3, 24, 12); });

    if (shared.model) buildCallouts();
    const holder = $('#tags');
    for (const p of state.nodes) {
      p.tag = make('div', 'tag', holder);
      p.tag.dataset.node = p.name;
      make('i', '', p.tag);
      make('b', '', p.tag, p.name.split('-').pop().slice(0, 8) + (p.head ? ' head' : ''));
      p.power = make('span', '', p.tag);
      p.tagDetail = make('small', '', p.tag);
    }
    for (const [i, j, chord] of pairs) {  // a neighbour's chip beside its arc, the chip of a chord a little way along it
      const a = state.nodes[i], b = state.nodes[j], el = make('div', 'linkchip', holder), mid = a.a + TAU / n / 2;
      const world = chord ? [a.x * .62 + b.x * .38, .03, a.z * .62 + b.z * .38] : [Math.cos(mid) * 1.17, .03, Math.sin(mid) * 1.17];
      state.chips.push({ a, b, el, world, w: 0, text: '' });
    }
    state.core = { pill: $('.pill'), sub: $('#core-sub'), hoops: make('div', 'linkchip', holder) };
    state.core.hoops.style.pointerEvents = 'auto';  // it explains itself on hover
    state.ready = true;
    state.born = performance.now() / 1000;
    resize();
    new ResizeObserver(resize).observe($('#hole'));
  }

  // Takes one moment of data into the scene: traffic on the lanes, the state of the engine in core and beam, and for every Spark its load, heat, tag and the glow of its parts.
  function data(s, flows) {
    state.lanes.forEach((lane, key) => {
      const g = flows[key] || 0;
      const scale = g < .02 ? 0 : clamp(Math.log10(1 + g) / Math.log10(201));
      lane.energyGoal = scale;
      lane.speedGoal = g < .02 ? .04 : .25 + 2.3 * scale;
    });
    const e = s.engine, speed = clamp(Math.log10(1 + (e.tok_s || 0)) / 3);
    if (e.state === 'writing' && state.mode !== 'writing' && state.seen) { state.flash = 1; wave(0, 0, 1); }
    if (state.finished != null && e.finished > state.finished) { const a = Math.random() * TAU; wave(Math.cos(a) * .35, Math.sin(a) * .35, .3); }
    if (e.finished != null) state.finished = e.finished;
    state.seen = true;
    state.mode = e.state;
    state.tok = e.tok_s || 0;
    state.actGoal = e.state === 'writing' ? .35 + .65 * speed : e.state === 'reading' ? .75 : e.state === 'idle' ? .16 : 0;
    state.beamGoal = e.state === 'writing' ? .3 + .7 * speed : e.state === 'reading' ? .1 : e.state === 'idle' ? .05 : 0;
    state.chargeGoal = e.state === 'reading' ? 1 : 0;
    state.rateGoal = e.state === 'writing' ? speed : e.state === 'reading' ? .2 : 0;
    const drafts = e.state === 'writing' ? e.spec || [] : [];  // the share of drafts that survive at each position
    if (drafts.length) state.specN = Math.min(16, drafts.length);  // without drafts the last count stays, so the hoops can fade where they stood
    for (let i = 0; i < 16; i++) state.specGoal[i] = i < drafts.length && drafts[i] != null ? clamp(drafts[i]) : 0;
    const hoops = hoopsWord(drafts);
    if (state.core && state.core.hoops.textContent !== hoops) { state.core.hoops.textContent = hoops; state.core.hoops.title = hoops ? `One hoop on the beam per draft position, ${drafts.filter(v => v != null).length} of them, as bright as the share of drafts that survive there.` : ''; }
    for (const p of state.nodes) {
      const n = s.nodes.find(x => x.name === p.name);
      if (!n) continue;
      if (foreignBoard(n) && !p.boxed) { p.boxed = true; p.open = p.openGoal = 0; }  // a machine the model does not show: a plain box from its first board on, shut if it stood open, and it stays one
      const load = clamp((n.w || 0) / (n.w_limit || 120));
      p.loadGoal = n.live ? load : 0;
      p.glowGoal = n.live ? .05 + .7 * load : 0;
      p.liveGoal = n.live ? 1 : 0;
      const note = nodeNote(n, s.identity);
      p.heatGoal = n.live ? Math.max(smooth(72, 90, n.gpu_c || 0), note.cls === 'warn' ? .7 : 0) : 0;
      p.tone = note.cls === 'bad' ? [1, .3, .55] : p.heatGoal > .2 ? [1, .62, .22] : [.95, .72, .38];
      p.ownTok = ownSpeed(n, e);  // what the engine this Spark runs on its own writes: its own sparks, and the first line of its tag
      const watts = n.live && !p.ownTok && n.w != null;  // the first line of the tag shows the watts of the Spark, and then says where they come from
      const text = !n.live ? (s.loading ? 'loading' : s.past ? 'no reading' : 'offline') : p.ownTok ? Math.round(p.ownTok) + ' tok/s' : watts ? Math.round(n.w) + ' W GPU' : 'no power reading';
      if (p.power.textContent !== text) { p.power.textContent = text; p.power.title = watts ? GPU_POWER_NOTE : ''; p.tagW = 0; }
      const detail = n.live ? `${fixed(n.util, 0)} % · ${fixed(n.gpu_c, 0)} °C · ${fixed(used(n), 0)} GB` : '';
      if (p.tagDetail.textContent !== detail) { p.tagDetail.textContent = detail; p.tagW = 0; }
      if (n.live) {
        p.gpuGoal = clamp((n.util || 0) / 100);
        p.cpuGoal = clamp((n.cpu_pct || 0) / 100);
        p.memGoal = n.mem_total_gb && n.mem_free_gb != null ? clamp(1 - n.mem_free_gb / n.mem_total_gb) : 0;
        p.netGoal = clamp(Math.log10(1 + (n.net || 0)) / Math.log10(201));
        p.thermGoal = smooth(45, 92, n.gpu_c || 0);
        p.ssdGoal = clamp(Math.log10(1 + (n.disk_read || 0) + (n.disk_write || 0)) / 3.4);
        p.fanRpm = n.fan ?? null;  // the mean of the fans that were read, as the hub counts it: a fan nobody read is no fan at 0
      } else { p.gpuGoal = p.cpuGoal = p.memGoal = p.netGoal = p.thermGoal = p.ssdGoal = 0; p.fanRpm = 0; }
      p.tag.style.setProperty('--tone', toneOf(note.cls));
    }
    for (const c of state.chips) {
      const text = chipWord(s.edges, c.a.rank, c.b.rank);
      if (text !== c.text) {
        c.text = text; c.w = 0; c.el.textContent = '';
        const [num, ...rest] = text.split(' ');
        make('b', '', c.el, num); c.el.appendChild(document.createTextNode(' ' + rest.join(' ')));
      }
    }
    fillCallouts();
  }

  /* kinds: 0 a token thrown off by the core, 1 a prompt pulled in, 2 dust, 3 the shell letting go, 4 a crumb of a bigger spark, 5 a mote riding the beam */
  function slot(kind) {
    const i = parts.next; parts.next = (i + 1) % MAX;
    parts.kind[i] = kind; parts.hero[i] = 0; parts.hops[i] = 0; parts.seed[i] = Math.random();
    return i;
  }
  function spawn(kind) {  // Lets one spark go, by its kind: a token thrown off by the core, a prompt pulled in, a mote on the beam, or dust.
    const i = slot(kind), a = Math.random() * TAU, c = Math.cos(a), s = Math.sin(a);
    if (kind === 0) {           // one generated token: thrown up and out of the core, then it falls and skips over the ice
      const hero = Math.random() < .07, wide = Math.pow(Math.random(), 1.3), lean = .14 + wide * .8, r = Math.random() * .028;
      const v = (.85 + Math.random() * 1.15) * (1 - .35 * wide) * (hero ? 1.18 : 1), out = Math.sin(lean) * v;  // the flat ones slower: they stay inside the ring
      parts.x[i] = c * r; parts.y[i] = .012 + Math.random() * .02; parts.z[i] = s * r;
      parts.vx[i] = c * out - s * .14; parts.vy[i] = Math.cos(lean) * v; parts.vz[i] = s * out + c * .14;
      parts.max[i] = parts.life[i] = (.9 + Math.random()) * (hero ? 1.35 : 1);
      parts.hero[i] = hero ? 1 : 0;
    } else if (kind === 1) {    // a prompt being pulled in from the ring, on a curve that tightens towards the core
      const r = .85 + Math.random() * .3, v = .5 + Math.random() * .25;
      parts.x[i] = c * r; parts.y[i] = .02 + Math.random() * .03; parts.z[i] = s * r;
      parts.vx[i] = -c * v - s * .32; parts.vy[i] = .01; parts.vz[i] = -s * v + c * .32;
      parts.max[i] = parts.life[i] = 1.05 + Math.random() * .4;
    } else if (kind === 5) {    // a mote of light riding up the beam on a spiral: vx is its turning speed, vz how fast the spiral widens
      const r = .03 + Math.random() * .07;
      parts.x[i] = c * r; parts.y[i] = .02 + Math.random() * .05; parts.z[i] = s * r;
      parts.vx[i] = 1.8 + Math.random() * 1.8; parts.vy[i] = .14 + Math.random() * .24; parts.vz[i] = .008 + Math.random() * .03;
      parts.max[i] = parts.life[i] = 2 + Math.random() * 1.7;
    } else {                    // dust, so an idle ring still breathes
      const r = Math.sqrt(Math.random()) * 1.5;
      parts.x[i] = c * r; parts.y[i] = Math.random() * .4; parts.z[i] = s * r;
      parts.vx[i] = (Math.random() - .5) * .03; parts.vy[i] = .02 + Math.random() * .03; parts.vz[i] = (Math.random() - .5) * .03;
      parts.max[i] = parts.life[i] = 3 + Math.random() * 3;
    }
  }
  function spawnFrom(p) {  // one token of the engine a Spark runs on its own: thrown up from its lid, it falls back around it like any other spark
    const i = slot(0), a = Math.random() * TAU, lean = .1 + Math.random() * .55, v = .45 + Math.random() * .6, out = Math.sin(lean) * v, r = Math.random() * p.side * .3;
    parts.x[i] = p.x + Math.cos(a) * r; parts.y[i] = p.atY + p.side * .3; parts.z[i] = p.z + Math.sin(a) * r;
    parts.vx[i] = Math.cos(a) * out; parts.vy[i] = Math.cos(lean) * v; parts.vz[i] = Math.sin(a) * out;
    parts.max[i] = parts.life[i] = .7 + Math.random() * .8;
  }
  function ownSparks(dt) {  // a spark per token for every Spark that serves on its own, up to OWN_SPARKS a second: more than that the eye cannot tell apart
    for (const p of state.nodes) {
      p.emit = p.ownTok ? (p.emit || 0) + Math.min(p.ownTok, OWN_SPARKS) * dt : 0;
      while (p.emit >= 1) { p.emit--; spawnFrom(p); }
    }
  }
  function crumbs(from, count) {  // a spark that breaks apart, or strikes the ice
    const x = parts.x[from], y = parts.y[from], z = parts.z[from], vx = parts.vx[from], vy = parts.vy[from], vz = parts.vz[from];
    for (let n = 0; n < count; n++) {
      const i = slot(4);
      parts.x[i] = x; parts.y[i] = Math.max(y, .006); parts.z[i] = z;
      parts.vx[i] = vx * .5 + (Math.random() - .5) * .5; parts.vy[i] = Math.abs(vy) * .35 + Math.random() * .42; parts.vz[i] = vz * .5 + (Math.random() - .5) * .5;
      parts.max[i] = parts.life[i] = .2 + Math.random() * .36;
    }
  }

  // Moves the scene on by one frame: everything eases towards what the data said, the Sparks rise and open, and every spark flies, falls and skips over the ice.
  function step(dt, t) {
    state.act += (state.actGoal - state.act) * clamp(dt * 1.5);
    state.beam += (state.beamGoal - state.beam) * clamp(dt * 2.4);
    state.charge += (state.chargeGoal - state.charge) * clamp(dt * 2.4);
    state.rate += (state.rateGoal - state.rate) * clamp(dt * 1.5);
    shared.drift += (shared.driftGoal - shared.drift) * clamp(dt * .8);
    for (let i = 0; i < 16; i++) state.spec[i] += (state.specGoal[i] - state.spec[i]) * clamp(dt * 2);
    state.flash = Math.max(0, state.flash - dt * 1.7);
    state.num += ((shared.holoText ? 1 : 0) - state.num) * clamp(dt * 5);
    shared.focusK = calm.matches ? shared.focusGoal : shared.focusK + (shared.focusGoal - shared.focusK) * clamp(dt * 2.6);
    if (shared.focusK < .002 && !shared.focusGoal) shared.focusNode = null;
    state.lanes.forEach(l => {
      l.speed += (l.speedGoal - l.speed) * clamp(dt * 2.2);
      l.energy += (l.energyGoal - l.energy) * clamp(dt * 2.2);
      if (!calm.matches) l.phase = (l.phase + l.speed * dt) % 1;
    });
    const age = t - state.born;
    for (const p of state.nodes) {
      for (const k of ['glow', 'heat', 'live', 'hot', 'load', 'gpu', 'cpu', 'mem', 'net', 'therm', 'ssd']) p[k] += (p[k + 'Goal'] - p[k]) * clamp(dt * 3);
      const h = p.side * .17, k = calm.matches ? 1 : smooth(.6 + p.order * .22, 1.7 + p.order * .22, age);
      if (!p.risen && k > .25) { p.risen = true; wave(p.x, p.z, .7); }
      if (shared.model && !p.boxed) {
        const was = p.open;
        p.open = calm.matches ? p.openGoal : clamp(p.open + (p.openGoal ? dt / OPEN_S : -dt / CLOSE_S));
        if (p.openGoal && was < EX_AT && p.open >= EX_AT && !calm.matches) burst(p);
        if (!calm.matches) p.spin = (p.spin + dt * (p.fanRpm != null ? p.fanRpm / 60 * TAU / 26 : 3 + 20 * p.load)) % TAU;
        pose(p);
        p.atY = shared.model.ground * p.scale + (k - 1) * h * 2.4 + smooth(.2, .55, p.open) * p.lift;
      } else p.atY = h + (k - 1) * h * 2.4;
    }
    state.reveal = calm.matches ? 1.05 : clamp((age - .5) / 1.8, 0, 1.05);
    state.burst = Math.max(0, state.burst - dt * .75);
    state.sweep = (state.sweep + dt * .65) % 1;
    if (calm.matches) parts.life.fill(0);
    if (age < 2 || calm.matches) return;
    const rate = state.mode === 'writing' ? Math.min(state.tok, 900) : state.mode === 'reading' ? 140 : state.mode === 'idle' ? 3 : 0;
    parts.emit += rate * dt;
    while (parts.emit >= 1) { parts.emit--; spawn(state.mode === 'writing' ? 0 : state.mode === 'reading' ? 1 : 2); }
    parts.motes += (state.mode === 'writing' ? 6 + 30 * state.rate : 0) * dt;
    while (parts.motes >= 1) { parts.motes--; spawn(5); }
    ownSparks(dt);
    const slowing = Math.exp(-dt), crumbling = Math.exp(-dt * 2.8);
    for (let i = 0; i < MAX; i++) {
      if (parts.life[i] <= 0) continue;
      parts.life[i] -= dt;
      const kind = parts.kind[i];
      if (kind === 5) {         // around the beam and up
        const r = Math.hypot(parts.x[i], parts.z[i]) + parts.vz[i] * dt, a = Math.atan2(parts.z[i], parts.x[i]) + parts.vx[i] * dt;
        parts.x[i] = Math.cos(a) * r; parts.z[i] = Math.sin(a) * r; parts.y[i] += parts.vy[i] * dt;
        continue;
      }
      if (kind === 0 || kind === 3 || kind === 4) {  // sparks: air slows them, they fall, the ice throws them back once or twice
        const drag = kind === 4 ? crumbling : slowing;
        parts.vx[i] *= drag; parts.vz[i] *= drag; parts.vy[i] = parts.vy[i] * drag - 1.55 * dt;
        if (parts.hero[i] === 1 && parts.life[i] < parts.max[i] * .52) { parts.hero[i] = 2; crumbs(i, 3 + (Math.random() * 3 | 0)); }
      } else if (kind === 1) {  // the core pulls harder the closer a prompt gets
        const r2 = parts.x[i] * parts.x[i] + parts.z[i] * parts.z[i] + .03, pull = .3 / r2 * dt;
        parts.vx[i] -= parts.x[i] * pull; parts.vz[i] -= parts.z[i] * pull;
        if (r2 < .034) parts.life[i] = Math.min(parts.life[i], .06);
      }
      parts.x[i] += parts.vx[i] * dt; parts.y[i] += parts.vy[i] * dt; parts.z[i] += parts.vz[i] * dt;
      if (kind !== 1 && kind !== 2 && parts.y[i] < .004 && parts.vy[i] < 0) {
        parts.y[i] = .004;
        if (parts.hops[i] < 2 && parts.vy[i] < -.3) {
          parts.vy[i] *= -.36; parts.vx[i] *= .62; parts.vz[i] *= .62; parts.hops[i]++;
          if (kind !== 4 && Math.random() < .45) crumbs(i, 1 + (Math.random() * 2 | 0));
        } else { parts.vy[i] = 0; parts.vx[i] *= .8; parts.vz[i] *= .8; parts.life[i] = Math.min(parts.life[i], .16); }
      }
    }
  }

  function burst(p) {  // the moment the shell lets go
    wave(p.x, p.z, .55);
    const c = Math.cos(p.yaw), s = Math.sin(p.yaw), half = p.side / 2;
    for (let n = 0; n < 340; n++) {
      const i = slot(3);
      const edge = Math.random() * 4 | 0, u = (Math.random() * 2 - 1) * half;
      const lx = edge < 2 ? u : (edge === 2 ? -half : half), lz = edge < 2 ? (edge ? half : -half) : u;
      const x = c * lx + s * lz, z = -s * lx + c * lz, reach = Math.hypot(x, z) || 1, v = .25 + Math.random() * .7;
      parts.x[i] = p.x + x; parts.y[i] = p.atY + Math.random() * p.side * .3; parts.z[i] = p.z + z;
      parts.vx[i] = x / reach * v; parts.vy[i] = .05 + Math.random() * .75; parts.vz[i] = z / reach * v;
      parts.max[i] = parts.life[i] = .9 + Math.random() * 1.1;
      parts.kind[i] = 3;
    }
  }

  /* a spark cools as it flies: white-hot, yellow, orange, a dull red, gone */
  const COOLING = [1, .96, .86, 1, .78, .36, 1, .42, .12, .8, .14, .04];
  // Writes every living spark into the buffer the fire is drawn from, with its colour for how far it has cooled; gives back how many live.
  function writeFire(t) {
    let o = 0, alive = 0;
    for (let i = 0; i < MAX; i++) {
      const life = parts.life[i];
      if (life <= 0) continue;
      const kind = parts.kind[i], full = parts.max[i], age = 1 - life / full, seed = parts.seed[i];
      let size, trail = 0, r, g, b, alpha = Math.min(1, life / .14) * Math.min(1, (full - life) / .03);
      if (kind === 0 || kind === 3 || kind === 4) {
        const cold = kind === 4 ? .34 + .66 * age : kind === 3 ? .1 + .9 * age : age, hero = parts.hero[i] ? 1 : 0;
        const f = Math.min(2.999, cold * 3), at = (f | 0) * 3, u = f - (f | 0);
        const glow = (kind === 4 ? .3 + 3.4 * (1 - age) * (1 - age) : .55 + 8.6 * Math.pow(1 - age, 2.3)) * (1 + .6 * hero) * (.84 + .3 * Math.sin(seed * 6283 + t * (26 + seed * 30)));
        r = (COOLING[at] + (COOLING[at + 3] - COOLING[at]) * u) * glow; g = (COOLING[at + 1] + (COOLING[at + 4] - COOLING[at + 1]) * u) * glow; b = (COOLING[at + 2] + (COOLING[at + 5] - COOLING[at + 2]) * u) * glow;
        size = kind === 4 ? .0019 : (.0026 + .0019 * (1 - age)) * (1 + .9 * hero);
        trail = kind === 4 ? .05 : .11;
        if (kind !== 3) alpha *= 1 - shared.focusK;
      } else if (kind === 1) {
        const near = 1 - age;
        r = .35 * (1.3 + 2.4 * age); g = 1.3 + 2.4 * age; b = .92 * (1.3 + 2.4 * age);
        size = .0026 + .001 * near; trail = .085; alpha *= 1 - shared.focusK;
      } else if (kind === 5) {
        const twinkle = .55 + .45 * Math.sin(seed * 6283 + t * (5 + seed * 9)), tint = seed * seed;
        r = (.42 + .2 * tint) * 2.6 * twinkle; g = (.5 + .5 * tint) * 2.6 * twinkle; b = 2.6 * twinkle;
        size = .0017 + .0016 * seed; alpha = Math.pow(Math.sin(Math.min(1, age) * Math.PI), .8) * (1 - shared.focusK);
      } else {
        r = .7; g = .72; b = 1; size = .0022; alpha = Math.pow(Math.sin(Math.min(1, age) * Math.PI), .7) * .4 * (1 - shared.focusK);
      }
      fire[o] = parts.x[i]; fire[o + 1] = parts.y[i]; fire[o + 2] = parts.z[i]; fire[o + 3] = size;
      fire[o + 4] = parts.vx[i]; fire[o + 5] = parts.vy[i]; fire[o + 6] = parts.vz[i]; fire[o + 7] = trail;
      fire[o + 8] = r; fire[o + 9] = g; fire[o + 10] = b; fire[o + 11] = alpha;
      o += 12; alive++;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, shared.fireBuf);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, fire, 0, o);
    return alive;
  }

  Object.assign(shared, { build, data, step, wave, writeFire });  // seam
}  // seam
