// The curves of the Spark page: one plot per reading with its scale, its band, its line and its limit, the time axis under them, and the cursor and the two marks they all share.
'use strict';
const PLOT = { gutter: 44, right: 10, top: 6, bottom: 6, calm: [2, 50] };  // the room around every curve, the same on every plot of a sheet: one moment is one x on all of them. calm: the room left and right of a plot in the calm form, which carries its scale at its right
// How many digits after the point the marks of a scale need, from the step between two of them.
const tickDigits = step => step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step) - 1e-9));
/* One plot. opt: word (what it shows, for a screen reader), tall, bare (no scale: a small one in a table), lane (no curve: only where a state held), calm (the calm form: the scale at the right in larger figures, the curve from the left edge),
   fixed [lo, hi] (a reading with natural ends), floor (a value the scale always holds), digits (how many digits after the point its row shows: the scale is never finer).
   paint(view): from, to, t, mean, low, peak, gap, width (seconds per column), reach (how far a column stands for its readings, if further than it is wide), limit { at: a value or one per column, word }, zone [lo, hi], spans [[from, to]], range [lo, hi] (a scale shared with other plots). */
function makePlot(host, opt) {
  const height = opt.height || (opt.lane ? 12 : opt.bare ? 30 : opt.tall ? 72 : 46), [gl, gr] = opt.calm ? PLOT.calm : [PLOT.gutter, PLOT.right], left = opt.bare ? 0 : gl, right = opt.bare ? 0 : gr, top = opt.lane ? 0 : PLOT.top, bottom = opt.lane ? 0 : PLOT.bottom, foot = opt.calm ? 4 : 3;
  const svg = draw('svg', { class: 'plot' + (opt.lane ? ' lane' : ''), height, role: 'img', 'aria-label': opt.word }, host);
  const grid = draw('g', { class: 'grid' }, svg), zone = draw('rect', { class: 'zone' }, svg), band = draw('path', { class: 'band' }, svg), limit = draw('path', { class: 'limit' }, svg);
  const limitWord = draw('text', { class: 'limit-word', 'text-anchor': 'end' }, svg), line = draw('path', { class: 'line' }, svg), held = draw('g', { class: 'held' }, svg);
  const sel = draw('rect', { class: 'sel', y: 0, height }, svg), marks = [draw('line', { class: 'mark', y1: 0, y2: height }, svg), draw('line', { class: 'mark', y1: 0, y2: height }, svg)];
  const cur = draw('line', { class: 'cur', y1: 0, y2: height }, svg), dot = draw('circle', { class: 'dot', r: opt.calm ? 4 : 3 }, svg), none = draw('text', { class: 'none', x: left + 8, y: height / 2 + 4 }, svg), word = draw('text', { class: 'cur-word', y: opt.lane ? height - 2 : 12 }, svg);  // the word beside the cursor: at the top of a curve, and in a lane on the lane itself, which has no room above
  let v = null, width = 0, axis = { lo: 0, hi: 1, ticks: [] }, at = null, picked = [null, null];  // at, picked: the moments of the cursor and of the two marks. The plot keeps them and puts them back whenever it is drawn again
  const X = t => left + (t - v.from) / (v.to - v.from) * (width - left - right);  // Where a moment stands on this plot.
  const Y = y => top + (1 - (y - axis.lo) / (axis.hi - axis.lo)) * (height - top - bottom);  // Where a value stands on this plot.
  const hide = (node, off) => { node.style.display = off ? 'none' : ''; };  // Takes a mark of the plot away, or brings it back.
  const limitAt = () => !v.limit ? null : Array.isArray(v.limit.at) ? middleOf(v.limit.at) : v.limit.at;  // The limit as one value: its middle where it was read column by column.
  function scale() {  // The scale for the stretch on the plot: the natural ends of the reading, a range shared with other plots, or round ends around every value and the limit.
    if (opt.fixed) return { lo: opt.fixed[0], hi: opt.fixed[1], ticks: axisOf(opt.fixed[0], opt.fixed[1], opt.tall ? 2 : 1).ticks };
    if (v.range) return { lo: v.range[0], hi: v.range[1], ticks: [v.range[0], v.range[1]] };  // a scale shared with other plots is drawn as it is said beside them, not rounded once more
    let lo = null, hi = null;
    const take = y => { if (y != null) { lo = lo == null ? y : Math.min(lo, y); hi = hi == null ? y : Math.max(hi, y); } };
    v.mean.forEach((y, i) => { if (y != null) { take(v.low && v.low[i] != null ? v.low[i] : y); take(v.peak && v.peak[i] != null ? v.peak[i] : y); } });
    if (lo != null) { take(limitAt()); take(opt.floor); }
    return axisOf(lo, hi, opt.tall ? 4 : 3, 4 * 10 ** -(opt.digits || 0));  // at least four steps of the last digit its row shows: marks that read differently
  }
  function paintScale() {  // The marks of the scale as hairlines, with their values beside them: all of them on a tall plot, the two ends on a small one. In the calm form its words are larger: there a tall plot says all of them only where its marks stand at least 15 px apart.
    grid.textContent = '';
    if (opt.bare || opt.lane) return;
    const digits = tickDigits(axis.ticks.length > 1 ? axis.ticks[1] - axis.ticks[0] : 1), apart = (height - top - bottom) / Math.max(1, axis.ticks.length - 1), all = opt.tall && (!opt.calm || apart >= 15);
    axis.ticks.forEach((tick, k) => {
      const y = Y(tick).toFixed(1);
      draw('line', { x1: left, x2: width - right, y1: y, y2: y }, grid);
      if (all || k === 0 || k === axis.ticks.length - 1) draw('text', opt.calm ? { x: width - right + 8, y: +y + 4, 'text-anchor': 'start' } : { x: left - 7, y: +y + 3.5, 'text-anchor': 'end' }, grid).textContent = figure(tick, digits);
    });
  }
  function paintLimit(any) {  // The limit as a dashed line with its word, and the zone before it as a wash. Without a reading on the plot there is none.
    const at = any ? limitAt() : null, z = any && v.zone ? [Math.max(axis.lo, v.zone[0]), Math.min(axis.hi, v.zone[1])] : null;
    limit.setAttribute('d', at == null ? '' : Array.isArray(v.limit.at) ? linePath(v.t, v.limit.at, X, Y, v.gap) : `M${left} ${Y(at).toFixed(1)}L${width - right} ${Y(at).toFixed(1)}`);
    limitWord.textContent = at == null ? '' : v.limit.word;
    if (at != null) { limitWord.setAttribute('x', width - right - 3); limitWord.setAttribute('y', Y(at) < 16 ? Y(at) + 12 : Y(at) - 4); }
    hide(zone, !z || z[1] <= z[0]);
    if (z && z[1] > z[0]) { zone.setAttribute('x', left); zone.setAttribute('width', width - left - right); zone.setAttribute('y', Y(z[1]).toFixed(1)); zone.setAttribute('height', (Y(z[0]) - Y(z[1])).toFixed(1)); }
  }
  function paint(view) {  // Draws a stretch into the plot: its scale, the band of lowest to highest reading, the line of the means, the limit, and where a state held. The cursor and the marks go back to their moments on it.
    v = view; width = host.clientWidth || 0;
    if (width < 60) return;
    svg.setAttribute('width', width); svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    axis = scale();
    const any = v.mean.some(y => y != null);
    paintScale();
    paintLimit(any && !opt.lane);
    none.textContent = any || opt.lane || opt.bare ? '' : 'no reading in this stretch';
    band.setAttribute('d', opt.lane || !v.low || !v.peak ? '' : bandPath(v.t, v.mean, v.low, v.peak, X, Y, v.gap));
    line.setAttribute('d', opt.lane ? '' : linePath(v.t, v.mean, X, Y, v.gap));
    held.textContent = '';
    if (opt.lane) draw('rect', { class: 'track', x: left, width: width - left - right, y: 2, height: height - 4 }, held);
    for (const [a, b] of v.spans || []) {  // a state that held: the whole height of a lane, a thin foot under a curve
      const x0 = X(Math.max(v.from, a)), x1 = X(Math.min(v.to, b)), wide = Math.max(1.5, x1 - x0);  // never thinner than can be seen, and a stretch that begins at the very end of the plot still shows: it held
      if (x1 >= x0) draw('rect', { x: Math.min(x0, width - right - wide).toFixed(1), width: wide.toFixed(1), y: opt.lane ? 2 : height - foot, height: opt.lane ? height - 4 : foot }, held);
    }
    cursor(at); select(...picked);
  }
  function cursor(t) {  // Moves the cursor to a moment, or takes it away. It snaps to the column the moment falls into and puts a dot on the line there; the word beside it (say) goes with it, and stands before it where it would run past the end of the curve (wordBefore), yet begins no earlier than the curve: on a plot too narrow for both it stands over the cursor. Gives back that column.
    at = t;
    const on = !!v && width >= 60 && t != null && t >= v.from && t <= v.to, i = on ? columnAt(v.t, t, v.reach ?? v.width) : -1, y = i < 0 || opt.lane ? null : v.mean[i];
    hide(cur, !on); hide(dot, y == null); hide(word, !on);
    if (on) { const x = X(i < 0 ? t : v.t[i]).toFixed(1), wide = 2 * wordHalf(word, 3.3), far = wordBefore(+x, wide, width - right); cur.setAttribute('x1', x); cur.setAttribute('x2', x); word.setAttribute('x', far ? Math.max(+x - 7, left + wide) : +x + 7); word.setAttribute('text-anchor', far ? 'end' : 'start'); }
    if (y != null) { dot.setAttribute('cx', X(v.t[i]).toFixed(1)); dot.setAttribute('cy', Y(y).toFixed(1)); }
    return i;
  }
  function select(a, b) {  // Shows the two marks and shades the stretch between them. A mark that is not set, or lies outside the stretch on the plot, is not drawn.
    picked = [a, b];
    const ready = !!v && width >= 60, inside = t => ready && t != null && t >= v.from && t <= v.to;
    [a, b].forEach((t, k) => { hide(marks[k], !inside(t)); if (inside(t)) { marks[k].setAttribute('x1', X(t).toFixed(1)); marks[k].setAttribute('x2', X(t).toFixed(1)); } });
    const both = ready && a != null && b != null, x0 = both ? X(Math.max(v.from, Math.min(a, b))) : 0, x1 = both ? X(Math.min(v.to, Math.max(a, b))) : 0;
    hide(sel, !both || x1 <= x0);
    if (both && x1 > x0) { sel.setAttribute('x', x0.toFixed(1)); sel.setAttribute('width', (x1 - x0).toFixed(1)); }
  }
  function timeAt(clientX) {  // The moment under a place of the screen, held inside the stretch on the plot; null before anything was drawn.
    if (!v || width < 60) return null;
    const box = svg.getBoundingClientRect();
    return momentAt(clientX - box.left, box.width, width, left, right, v.from, v.to);
  }
  cursor(null); select(null, null); hide(zone, true);
  return { svg, paint, cursor, select, timeAt, say: text => { word.textContent = text; if (v) cursor(at); }, inner: () => Math.max(0, (host.clientWidth || 0) - left - right) };
}
// Half the width of a word that was drawn: measured, and guessed from its letters (so many pixels half a letter) where the drawing cannot measure or is not shown.
const wordHalf = (text, guess) => { const wide = typeof text.getComputedTextLength === 'function' ? text.getComputedTextLength() : 0; return wide > 0 ? wide / 2 : text.textContent.length * guess; };
function makeAxis(host) {  // Builds the time axis under plots in the calm form, whose curves begin at the left edge: round moments of the local clock, and a dot for every event of the stretch. Gives back how to draw a stretch.
  const svg = draw('svg', { class: 'plot axis', height: 22, 'aria-hidden': 'true' }, host), [gl, gr] = PLOT.calm;
  return (from, to, events) => {
    const width = host.clientWidth || 0, inner = width - gl - gr, X = t => gl + (t - from) / (to - from) * inner;
    if (width < 60) return;
    svg.setAttribute('width', width); svg.setAttribute('viewBox', `0 0 ${width} 22`); svg.textContent = '';
    const { step, ticks } = timeTicks(from, to, Math.max(2, Math.floor(inner / 64)), t => new Date(t * 1000).getTimezoneOffset());
    const dated = ticks.some(t => timeWord(t, step, false).includes(','));  // a midnight among the marks names the day: then the first mark need not
    let free = -Infinity;  // where the last word ended: a word that would run into it is left out, its mark stays
    ticks.forEach((t, k) => {
      const x = X(t), text = draw('text', { y: 16, 'text-anchor': 'middle' }, svg);
      draw('line', { x1: x.toFixed(1), x2: x.toFixed(1), y1: 0, y2: 4 }, svg);
      text.textContent = timeWord(t, step, k === 0 && !dated);
      const half = wordHalf(text, 3.2), at = wordPlace(x, half, free, width);
      if (at == null) { text.remove(); return; }
      text.setAttribute('x', at.toFixed(1));
      free = at + half;
    });
    for (const e of events || []) if (e.t >= from && e.t <= to && e.level !== 'info') draw('title', {}, draw('circle', { class: e.level, cx: X(e.t).toFixed(1), cy: 3, r: 2.5 }, svg)).textContent = e.text;
  };
}
