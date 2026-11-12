// The time machine: every surface shows one moment of the past, from what was recorded and nothing else.
'use strict';
/* ---- the time machine: every surface shows one moment of the past, from what was recorded and nothing else ---- */
const Time = (() => {
  const bar = $('#timebar'), btn = $('#time-btn'), track = $('#tm-track'), head = $('#tm-head'), whenEl = $('#tm-when'), whatEl = $('#tm-what'), noneEl = $('#tm-none');
  const playBtn = $('#tm-play'), speedBtn = $('#tm-speed'), liveBtn = $('#tm-live'), rangesEl = $('#tm-ranges');
  const RANGES = [['30 min', 1800], ['2 h', 7200], ['6 h', 21600], ['24 h', 86400], ['7 d', 604800], ['30 d', 2592000]], SPEEDS = [1, 10, 60, 600];
  const slide = track.querySelector('.slide');
  /* at: the moment picked, null for now. While it is null the strip ends now and moves along; a picked moment holds it still.
     got: the recording of the stretch on the strip (stamped with the stretch it was asked for), null until it has arrived. */
  let open = false, at = null, span = 7200, from = 0, to = 0, got = null, playing = false, speed = 60, asking = 0, drag = false, timer = 0, shown = -2, loaded = 0, later = 0, painted = 0;
  // A moment as weekday, date and time to the second.
  const stamp = t => new Date(t * 1000).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  // A moment in short for the ends of the strip: the time, with the date on stretches longer than a day.
  const brief = t => new Date(t * 1000).toLocaleString('en-GB', span > 86400 ? { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
  const now = () => LIVE ? LIVE.t : Date.now() / 1000;  // The newest moment that arrived, or the clock while none has.
  // The smallest step along the strip that can show something new: a 720th of the stretch, never less than one sample.
  const grain = () => Math.max(span / 720, LIVE ? LIVE.identity.interval : 2);
  function keys() {  // The names of every trace a moment of the past needs: the engine, every Spark and every link.
    const list = KEPT_ENGINE.map(k => 'engine.' + k);
    for (const n of LIVE.cluster.nodes) for (const k of KEPT_NODE) list.push(n.name + '.' + k);
    for (const e of LIVE.edges) { const n = LIVE.cluster.nodes.find(c => c.rank === e.from); if (n) list.push(`${n.name}.${e.group}.tx`, `${n.name}.${e.group}.rx`); }
    return [...new Set(list)];
  }
  // Asks the server for the recording of the stretch on the strip; an answer that arrives after another stretch was asked for is dropped.
  async function load() {
    if (!LIVE || !open) return;
    const mine = ++asking, f = from, t = to;
    loaded = performance.now();
    clearTimeout(later);
    later = setTimeout(() => {  // slow: strip and page say they are loading rather than keep the line and the moment of another stretch
      if (mine !== asking || got) return;
      paintTrack();
      if (at != null) blank();
    }, 250);
    let body = null;
    try { body = await askHistory(keys(), f, t, 720, false); } catch { /* ringtop is restarting, or it gave no stretch */ }
    if (mine !== asking) return;  // another stretch was asked for meanwhile
    clearTimeout(later);
    if (!body) {  // no answer: the page says so and asks again, it never shows another stretch or the values of now in its place
      later = setTimeout(load, 2500);
      paintTrack();
      if (at != null && !have()) blank();
      return;
    }
    body.from = f; body.to = t;
    got = body; shown = -2;
    paintTrack();
    if (at != null) show();
  }
  function frameOn(moment) {  // the stretch on the strip ends now, unless the moment shown lies further back
    const end = now();
    to = moment == null ? end : Math.min(end, moment + span / 2);
    from = to - span;
    got = null;  // the recording of another stretch says nothing about this one
    paintHead();
    load();
  }
  // How far back a moment may reach for its sample on this stretch.
  const reach = () => reachOf(span, got && got.tier, LIVE ? LIVE.identity.interval : 2);
  const index = t => sampleAt(got && got.t, t, reach());  // Which sample of the recording a moment shows, none where a hole lies.
  const past = t => momentOf(LIVE, got, t, reach());  // One moment of the past as a state for the page.
  const have = () => !!got && at >= got.from && at <= got.to;  // is the recording of the picked moment here
  function blank() { shown = -2; series = new Map(); render(past(at)); }  // the picked moment without its recording: every value unknown, the page says it is loading
  function tail(t) {  // the half hour before the moment, so every little trace on the page ends at it
    const out = new Map(), ts = got.t;
    let a = 0, b;
    while (a < ts.length && ts[a] < t - WINDOW) a++;
    for (b = a; b < ts.length && ts[b] <= t; b++);
    for (const key in got.series) {
      const src = got.series[key], T = [], V = [];
      for (let i = a; i < b; i++) if (src[i] != null) { T.push(ts[i]); V.push(src[i]); }
      if (T.length) out.set(key, { t: T, v: V });
    }
    return out;
  }
  function show() {  // Puts the picked moment on the page once its recording is here; the same sample is not drawn twice.
    if (at == null) return;
    paintHead();
    if (!have()) {  // its recording is on the way. The values of now leave at once; a moment of the past may stay for the quarter second a recording normally takes (load() blanks it after that), so playing does not flicker
      if (!S || !S.past) blank();
      return;
    }
    const i = index(at);
    if (i === shown && i >= 0) return;  // the same sample: nothing new to draw
    shown = i;
    series = tail(at);
    render(past(at));
  }
  function paintHead() {  // Places the head on the strip and says which moment it shows and how finely it was recorded.
    const moment = at ?? to;
    head.style.left = (clamp((moment - from) / span) * 100).toFixed(2) + '%';
    whenEl.textContent = at == null ? 'Now' : stamp(at);
    const tier = !got ? 'loading' : got.tier === 'raw' ? 'every sample' : got.tier === 'mixed' ? 'every sample, earlier as one-minute averages' : got.tier === 'memory' ? 'kept in memory since this start' : 'one-minute averages';
    whatEl.textContent = at == null ? 'Drag across the strip to look back, or press Play.' : playing ? `playing at ${speed}×, ${tier}` : tier;
    $('#tm-from').textContent = brief(from); $('#tm-to').textContent = at == null ? 'now' : brief(to);
  }
  function paintTrack() {  // Draws the strip: the speed across the stretch with holes where nothing was recorded, and a mark for every event.
    const ts = got ? got.t : [], vs = got ? got.series['engine.tok_s'] || [] : [];
    let hi = 1, d = '', last = null;
    for (const v of vs) if (v != null && v > hi) hi = v;
    const gap = reach();  // where a moment would find no sample, the line has a hole too
    ts.forEach((t, i) => {
      if (vs[i] == null) return;
      d += (last == null || t - last > gap ? 'M' : 'L') + ((t - from) / span * 1000).toFixed(1) + ' ' + (32 - vs[i] / hi * 28).toFixed(1);
      last = t;
    });
    painted = from; slide.removeAttribute('transform');
    slide.querySelector('.line').setAttribute('d', d);
    slide.querySelector('.fill').setAttribute('d', fillUnder(d, 34));
    const marks = slide.querySelector('.marks');
    marks.textContent = '';
    for (const e of (got && got.events) || []) {
      const strong = e.level === 'bad' || e.level === 'warn', x = ((e.t - from) / span * 1000).toFixed(1);
      const mark = draw('line', { x1: x, x2: x, y1: 0, y2: strong ? 34 : 7, stroke: e.level === 'bad' ? 'var(--rose)' : e.level === 'warn' ? 'var(--amber)' : 'rgba(255,255,255,.4)' }, marks);
      draw('title', {}, mark).textContent = `${stamp(e.t)}${e.node ? ' ' + e.node : ''}: ${e.text}`;
    }
    noneEl.hidden = ts.length > 0;
    noneEl.textContent = ts.length ? '' : got ? 'Nothing was recorded in this stretch.' : 'Loading what was recorded.';
    paintHead();
  }
  function go(t) {  // Picks a moment of the past; the strip follows when the moment lies off it, and a moment at the very end is now.
    if (!LIVE) return;
    if (!open) toggle(true);
    const end = now();
    if (t >= end - 1) return live();
    const first = at == null;
    at = Math.max(t, end - RANGES[RANGES.length - 1][1]);
    document.body.classList.add('replay');
    liveBtn.setAttribute('aria-pressed', 'false'); track.classList.remove('live');
    status();
    Tour.toggle(false);
    if (at < from || at > to) frameOn(at);  // off the strip: the strip follows
    else if (first) load();  // from here on the strip stands still: read it as it stands now, so the recording covers it up to its end (a request from before the strip stopped may end earlier than the moment picked)
    show();  // also while a recording is on its way: the values of now leave the page at once
  }
  function play(want = !playing) {  // Starts or stops playing the recording forward at the chosen speed.
    playing = want;
    playBtn.textContent = playing ? 'Pause' : 'Play';
    clearInterval(timer);
    if (!playing) return paintHead();
    if (at == null) go(from + grain());  // from now there is nothing to play: start where the strip starts
    timer = setInterval(() => { if (at == null) return play(false); go(at + .125 * speed); }, 125);
  }
  function live() {  // Back to now: the live traces return and the strip ends now again.
    const was = at != null;
    at = null; shown = -2;
    if (playing) play(false);
    document.body.classList.remove('replay');
    liveBtn.setAttribute('aria-pressed', 'true'); track.classList.add('live');
    series = liveSeries;
    if (was && LIVE) { status(); render(LIVE); }
    if (open && was) frameOn(null); else paintHead();  // the strip stood still on the moment: it ends now again
  }
  function toggle(want = !open) {  // Opens or closes the strip; closing leads back to now, opening ends the tour and nerd mode.
    if (want === open || !LIVE) return;
    open = want;
    btn.setAttribute('aria-pressed', String(open));
    bar.hidden = !open;
    document.body.classList.toggle('timing', open);
    if (!open) { asking++; clearTimeout(later); return live(); }  // a closed strip asks for nothing and waits for nothing
    Tour.toggle(false);
    if (Nerd.isOpen()) Nerd.toggle(false);
    frameOn(null);
  }
  // The moment under the pointer on the strip.
  const timeAt = e => { const b = track.getBoundingClientRect(); return from + clamp((e.clientX - b.left) / b.width) * span; };
  track.addEventListener('pointerdown', e => { drag = true; track.setPointerCapture(e.pointerId); play(false); go(timeAt(e)); });
  track.addEventListener('pointermove', e => { if (drag) go(timeAt(e)); });
  for (const type of ['pointerup', 'pointercancel']) track.addEventListener(type, () => { drag = false; });
  for (const [word, secs] of RANGES) {
    const b = make('button', 'n-btn', rangesEl, word);
    b.type = 'button'; b.setAttribute('aria-pressed', String(secs === span));
    b.addEventListener('click', () => { span = secs; for (const x of rangesEl.children) x.setAttribute('aria-pressed', String(x === b)); frameOn(at); });
  }
  const step = (dir, big) => go((at ?? now()) + dir * grain() * (big ? 10 : 1));  // One step back or forth along the strip, ten with Shift.
  $('#tm-back').addEventListener('click', e => step(-1, e.shiftKey));
  $('#tm-fwd').addEventListener('click', e => step(1, e.shiftKey));
  playBtn.addEventListener('click', () => play());
  speedBtn.textContent = speed + '×';
  speedBtn.addEventListener('click', () => { speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]; speedBtn.textContent = speed + '×'; paintHead(); });
  liveBtn.addEventListener('click', live);
  btn.addEventListener('click', () => toggle());
  return {
    toggle, live, go,
    isOpen: () => open,
    isPast: () => at != null,
    key(e) {
      if (e.key === ' ' && !(e.target.matches && e.target.matches('button'))) { e.preventDefault(); play(); return true; }
      if (e.key === ',' || e.key === '<') { step(-1, e.shiftKey); return true; }
      if (e.key === '.' || e.key === '>') { step(1, e.shiftKey); return true; }
      return false;
    },
    tick() {  // a new sample arrived: while no moment is picked, the strip ends now, moves along and fills in
      if (!open || drag || at != null) return;  // a picked moment holds the strip still, so it cannot slide out of what is loaded
      to = now(); from = to - span;
      if (performance.now() - loaded > 20000) load();
      slide.setAttribute('transform', `translate(${((painted - from) / span * 1000).toFixed(2)} 0)`);  // the line moves with its labels until it is drawn anew
      paintHead();
    },
  };
})();

