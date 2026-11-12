// The rules of measurement: what a number or a curve of the page may say. Statistics of a stretch, scales, holes, stretches of a state and the words for them, as plain functions of the data, so the checks run them through node.
'use strict';
const SLOW_FAN = .85, NOT_COOLER = 1.5, NEAR_LIMIT = 20;  // the lines the live view draws as well: fans 15 % slower than the middle of the others, no more than 1.5 °C cooler, 20 °C to the thermal limit
// Where the watts of one Spark come from. Said wherever they stand alone: at the figure of its tile in the dock, at its watts on its tag in the scene, on the card of the GB10 package and at the row of nerd mode.
const GPU_POWER_NOTE = 'GPU power as nvidia-smi reports it, averaged by the driver. A whole Spark draws more: the GB10 does not report that.';
// A number in words: so many digits after the point, thousands apart, a dash when it was not read.
const figure = (v, digits = 0) => v == null || !Number.isFinite(v) ? '–' : v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
// What is open on a Spark whose fans are slow by the lines above, in the words of the rule: slower by more than so much, at this speed, and cooler by no more than so much.
const slowFanWord = fan => `Its fans turn more than ${Math.round((1 - SLOW_FAN) * 100)} % slower than the middle of the others, at ${figure(fan)} RPM, while it is no more than ${NOT_COOLER} °C cooler than they are.`;
// The highest reading of some live traces (each with its values in v), null where none of them holds a reading: a peak nobody read is none.
const peakOf = traces => traces.reduce((hi, s) => (s ? s.v : []).reduce((top, v) => v != null && (top == null || v > top) ? v : top, hi), null);
// The middle one of some numbers, null of none. Of an even count the lower middle: a value that was read, not one made up between two.
const middleOf = list => { const s = list.filter(v => v != null).sort((a, b) => a - b); return s.length ? s[(s.length - 1) >> 1] : null; };
function niceStep(span, count) {  // the step of a scale: 1, 2 or 5 times a power of ten, so that about `count` steps span the range
  const raw = span / Math.max(1, count), power = 10 ** Math.floor(Math.log10(raw)), part = raw / power;
  return (part <= 1 ? 1 : part <= 2 ? 2 : part <= 5 ? 5 : 10) * power;
}
function axisOf(lo, hi, count, least = 0) {  // a scale for values from lo to hi: round ends that hold both, and the marks between them. A flat trace gets room around it instead of a scale of no height, and no scale spans less than `least`: it does not zoom into less than its row can show
  if (lo == null || hi == null) return { lo: 0, hi: 1, ticks: [0, 1] };
  if (hi - lo < 1e-9) { const room = Math.max(Math.abs(hi) * .05, .5); lo -= room; hi += room; }
  if (hi - lo < least) { const mid = (lo + hi) / 2; lo = mid - least / 2; hi = mid + least / 2; }
  const step = niceStep(hi - lo, count), from = Math.floor(lo / step + 1e-9) * step, to = Math.ceil(hi / step - 1e-9) * step, ticks = [];
  for (let k = 0; from + k * step <= to + step * 1e-6; k++) ticks.push(+(from + k * step).toFixed(10));
  return { lo: from, hi: to, ticks };
}
const CLOCK_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800, 1209600, 2419200, 4838400];
/* The marks of a time axis: at most `count` round moments of the local clock, and the step between them. behind: the minutes the
   local clock is behind UTC at a moment. Where the clocks change inside the stretch, each side of the change is marked by its own
   clock: a mark of a day stays at local midnight on both sides, an hour that comes twice is marked at both of its moments, one that
   never comes is not, and a stretch shorter than the change keeps its marks. One change per stretch: a sheet spans 30 days at most. */
function timeTicks(from, to, count, behind) {
  const first = behind(from), last = behind(to), pieces = [[from, to, first]];  // each piece: from when to when, and the minutes its clock is behind UTC
  if (last !== first) {  // the change, to the second: the first whole second the new clock holds
    let lo = Math.floor(from), hi = Math.ceil(to);
    while (hi - lo > 1) { const mid = Math.floor((lo + hi) / 2); if (behind(mid) === first) lo = mid; else hi = mid; }
    pieces.splice(0, 1, [from, hi - 1e-3, first], [hi, to, last]);  // marks stand on whole seconds: the first piece ends just before the change
  }
  const ends = (s, [a, b, off]) => [Math.ceil((a - off * 60) / s) * s, Math.floor((b - off * 60) / s) * s, off * 60];  // the first and the last mark of a piece by its local clock, and what leads back from there
  const fits = s => pieces.reduce((n, piece) => { const [lo, hi] = ends(s, piece); return n + Math.max(0, (hi - lo) / s + 1); }, 0) <= count, ticks = [];
  let step = CLOCK_STEPS.find(fits);
  if (!step) for (step = 2 * CLOCK_STEPS[CLOCK_STEPS.length - 1]; !fits(step); step *= 2);
  for (const piece of pieces) { const [lo, hi, back] = ends(step, piece); for (let at = lo; at <= hi; at += step) ticks.push(at + back); }
  return { step, ticks };
}
function timeWord(t, step, first) {  // a moment on a time axis: seconds only where the marks are closer than a minute, the day on the first mark and at every midnight
  const d = new Date(t * 1000), two = v => String(v).padStart(2, '0'), day = `${d.getDate()} ${d.toLocaleString('en-GB', { month: 'short' })}`;
  if (step >= 86400) return day;
  const time = `${two(d.getHours())}:${two(d.getMinutes())}${step < 60 ? ':' + two(d.getSeconds()) : ''}`;
  return first || (d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0) ? `${day}, ${time}` : time;
}
// Where a word of a time axis stands, by its middle, or null where it finds no room: 8 px to the word before it (free: where that one ended), and its end inside the axis. A word at an end of the axis is moved in beside its mark instead of running out or being left out.
const wordPlace = (x, half, free, width) => { const at = Math.min(Math.max(x, half), width - half); return at - half < free + 8 || at + half > width ? null : at; };
// Whether the word beside a cursor stands before it: where, 7 px after the cursor and as wide as it is, it would not end before `end`, the end of the curve.
const wordBefore = (x, wide, end) => x + 7 + wide > end;
const sameDay = (a, b) => new Date(a * 1000).toDateString() === new Date(b * 1000).toDateString();  // Whether two moments lie on one day of the local calendar.
const columnAt = (ts, t, reach) => {  // the column of a stretch a moment falls into: the nearest one, and none further away than `reach` (how far a column stands for its readings, columnReach)
  if (!ts || !ts.length || t == null) return -1;
  let lo = 0, hi = ts.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (ts[mid] < t) lo = mid + 1; else hi = mid; }
  if (lo > 0 && t - ts[lo - 1] <= ts[lo] - t) lo--;
  return Math.abs(ts[lo] - t) <= reach ? lo : -1;
};
// The time of the point a moment falls on, so a mark stands on a point and the figures between two marks count whole points. In a hole, where no point is within reach, the moment itself.
const snapTo = (ts, t, reach) => { const i = columnAt(ts, t, reach); return i < 0 ? t : ts[i]; };
// The marks that lie in the stretch on the sheet. One the stretch has left behind is gone: no curve shows its moment any more.
const marksWithin = (marks, from, to) => marks.filter(t => t >= from && t <= to);
/* The figures of one trace over a stretch of time. A trace is what the history answers per column: its mean, its lowest and highest
   reading and how many readings stand behind it. Nothing is said that was not kept: where the lowest reading of a column is missing,
   the minimum is only a bound (the true one is no higher), and a stretch without a reading has no figure at all. */
function stretchStats(trace, from, to) {
  const out = { last: null, lastT: null, mean: null, min: null, max: null, n: 0, columns: 0, bound: false };
  let sum = 0;
  for (let i = 0; i < trace.t.length; i++) {
    const v = trace.mean[i], t = trace.t[i];
    if (v == null || (from != null && t < from) || (to != null && t > to)) continue;
    const n = trace.n && trace.n[i] ? trace.n[i] : 1, low = trace.low ? trace.low[i] : null, peak = trace.peak ? trace.peak[i] : null;
    sum += v * n; out.n += n; out.columns++;
    out.last = v; out.lastT = t;
    out.max = Math.max(out.max ?? -Infinity, peak ?? v);
    out.min = Math.min(out.min ?? Infinity, low ?? v);
    if (low == null) out.bound = true;
  }
  if (out.n) out.mean = sum / out.n;
  return out;
}
// How far apart the readings of a stretch lie: single samples one sampling interval, everything kept by the minute 60 s. A stretch that mixes both counts by the minute: its coarser part decides what a hole is.
const stepOf = (tier, interval) => tier === 'raw' || tier === 'memory' ? interval : 60;
/* Which value a row shows, and what it is: the point under the cursor while one is on the sheet (none in a hole, never the value of
   now in its place); else the newest reading of the Spark itself; else the last point of the whole stretch. at: the column the value
   is of, -1 where it is no point of the stretch. */
function shownValue(mean, i, hovering, newest) {
  if (hovering) return { v: i < 0 ? null : mean[i], at: i, what: 'cursor' };
  if (newest != null) return { v: newest, at: -1, what: 'now' };
  for (let k = mean.length - 1; k >= 0; k--) if (mean[k] != null) return { v: mean[k], at: k, what: 'last' };
  return { v: null, at: -1, what: 'none' };
}
// How tall one curve is where every Spark is a card and all of them are to stand on the panel at once, between 44 and 96 px. room: the height of the panel. top: where its head ends. n: the cards. A card adds 40 px around its curve, the room above the cards and the time axis under them take 31 px, every gap between two cards 4 px.
const curveHeight = (room, top, n) => Math.min(96, Math.max(44, Math.floor((room - top - 31 - 4 * (n - 1)) / Math.max(1, n)) - 40));
// Whether the address of the page asks for the wide form of the cooling view: ?cooling=wide, alone or among other wishes, read wish by wish (the same letters inside the value of another wish ask for nothing).
const wideAsked = search => search.replace(/^\?/, '').split('&').includes('cooling=wide');
// The readings of all Sparks as one figure for the head of a view: a single value, or from the lowest to the highest; a dash where there is none. A reading that is missing is left out: it is no reading of 0.
const spreadWord = list => { const read = list.filter(v => v != null); if (!read.length) return '–'; const lo = figure(Math.min(...read)), hi = figure(Math.max(...read)); return lo === hi ? lo : `${lo}–${hi}`; };
/* The line the name of a dot is written on in a picture of dots: above its dot, above the name of a neighbour that already stands there, and below the dot
   once a name above would be higher than it can be read. x: the middle of the name. y: its dot. placed: the middle and the line of every name so far. top: the highest line a name can be read on. */
function namePlace(x, y, placed, top) {
  const taken = line => placed.some(q => Math.abs(q[0] - x) < 48 && Math.abs(q[1] - line) < 13);
  let line = y - 11;
  while (taken(line)) line -= 13;
  if (line >= top) return line;
  line = y + 18;
  while (taken(line)) line += 13;
  return line;
}
// By how much the fans of a Spark ran slower over a stretch, in percent, from its mean and the middle of the others' means: one rule for its line and for the sentence behind it. Nothing without one of the two means, and nothing where the means over the stretch do not show what its points did (no share that rounds to 0 %, and none below it).
const slowerShare = (own, rest) => { const part = own == null || !rest ? null : (1 - own / rest) * 100; return part == null || part < 0.5 ? '' : figure(part); };
function slowerWords(name, own, rest) {  // a stretch of slower fans in words: short for its line (who, and by how much), and in full for what stands behind it (the mean of this Spark against the middle of the others). Without one of the two means, neither a share nor figures; and none where the means over the stretch do not show what its points did (no share that rounds to 1 %)
  const share = slowerShare(own, rest);
  if (!share) return { short: `${name} slower`, long: `${name}: fans slower than the others` };
  return { short: `${name} ${share} % slower`, long: `${name}: fans at ${figure(own)} against ${figure(rest)} RPM, ${share} % slower` };
}
// Whether a row of fans carries the sign for slower fans: at the column under the cursor while one stands on the board (never in a hole, never where the judgement is missing), else only while the slow stretch holds up to now.
const slowerShown = (flags, i, hovering, now) => hovering ? i >= 0 && flags[i] === true : !!now;
// What a calm bar says of the marks of its board, in a few words: the marked stretch from a to b with its length, one marked point, one mark that waits for its second, nothing without a mark. say: how a stretch and a moment are worded there (stretch(a, b), at(t)).
const marksWord = (a, b, mark, say) => a != null ? (b > a ? `${say.stretch(a, b)}, ${lengthWord(b - a)}` : `One point, ${say.at(a)}`) : mark != null ? `Mark at ${say.at(mark)}` : '';
// What stands beside the value of a row in the calm form (what: which value shownValue gave). The unit alone for a reading of now or under the cursor: there the plot under the pointer says the moment. The last point of a stretch says that it is one (last: those words), and no reading says only that.
const quietWord = (what, unit, last) => what === 'none' ? 'no reading' : what === 'last' ? [unit, last].filter(Boolean).join(', ') : unit;
function besideFigure(trace, i, hovering, a, b) {  // the figure under a small curve of the table beside the others, and what it is: the point under the cursor, else the mean of the marked stretch, else the newest point
  if (hovering) return { v: i < 0 ? null : trace.mean[i], what: 'cursor' };
  const st = stretchStats(trace, a, b);
  return a != null ? { v: st.mean, what: 'marked' } : { v: st.last, what: 'newest' };
}
const BESIDE_WORDS = { cursor: 'its value at the cursor', marked: 'its mean over the marked stretch', newest: 'its newest point' };  // the same three, as the table says them
/* What a pointer does to a drag across a plot: one step from the drag before to the drag after, and what the sheet has to do then.
   A drag begins with a press of the main button on a plot that has a moment under it; a plot that has drawn nothing gives none. Its
   end is where the pointer is, once that is more than a few pixels from where it began; back within them it has none again, and over
   a place without a moment it stays as it is. When the button comes up, a press without a move sets a mark, and so does a drag that
   came back to its start; a drag zooms. And it is dropped without doing anything when the pointer comes with no button held (the
   button came up somewhere else) or the browser takes the pointer away. e: type ('down', 'move', 'up' or 'cancel'), x on the screen,
   t the moment under the pointer or null, main (the main button was pressed), held (it is down). Gives back the drag, null for none,
   and what to do, if anything. */
function dragStep(drag, e) {
  if (e.type === 'down') return { drag: e.main && e.t != null ? { x: e.x, from: e.t, to: null } : null };
  if (!drag || e.type === 'cancel' || (e.type === 'move' && !e.held)) return { drag: null };
  if (e.type === 'move') return { drag: e.t == null ? drag : { ...drag, to: Math.abs(e.x - drag.x) > 5 ? e.t : null } };
  return { drag: null, act: drag.to == null ? ['mark', drag.from] : ['zoom', Math.min(drag.from, drag.to), Math.max(drag.from, drag.to)] };
}
/* The moment under a place of a plot. x: the place on the screen, in pixels from the left edge of the drawing. shown and drawn: how wide
   the drawing is on the screen and in its own units; a browser lays it out to a fraction of a pixel, or larger, and it is drawn in whole
   units. left and right: the room beside the curve, in those units. The moment is held inside the stretch. */
function momentAt(x, shown, drawn, left, right, from, to) {
  const own = shown ? x * drawn / shown : x;
  return from + Math.min(1, Math.max(0, (own - left) / (drawn - left - right))) * (to - from);
}
function zoomTo(a, b, least, latest) {  // a stretch of the sheet as the whole sheet: around its middle, no shorter than `least` seconds, and ending no later than `latest`, the moment on the page
  const span = Math.max(b - a, least), mid = (a + b) / 2;
  return { span, end: Math.min(latest, Math.max(b, mid + span / 2)) };
}
// Whether an answer of the history is a stretch the page can draw: its columns of time and its traces by their keys. Anything else, an error said as JSON or an empty answer, is none.
const isStretch = answer => !!answer && Array.isArray(answer.t) && !!answer.series && typeof answer.series === 'object';
const ASK_LOST = 30;  // seconds after which a question to the history counts as lost
/* Whether the sheet may ask the history again by itself. Never while a question is out, unless it has been out for longer than a lost
   one: a history that is slow is waited for (a new choice of the reader does not come through here, it overtakes). Live: once the
   moment has moved on by a column, no sooner than after 10 s and no later than after 60 s. Looking back: as soon as the moment lies
   before the end of what was loaded, however little (the curves would show what came after it), or a column or more behind it.
   out: the seconds the last question has been out, null when none is. to: the end of what was loaded, null when nothing was.
   at: where the sheet should end. */
function mayAsk({ out, to, width, at, past }) {
  if (out != null && out <= ASK_LOST) return false;
  if (to == null) return true;
  const ahead = at - to;
  return past ? ahead < 0 || ahead >= width : Math.abs(ahead) >= Math.min(60, Math.max(10, width));
}
function gapOf(width, tier, interval) {  // how far two neighbours of a trace may lie apart before the line between them is a hole: two and a half columns, and no less than two and a half readings
  return 2.5 * Math.max(width, stepOf(tier, interval));
}
function linePath(ts, vs, x, y, gap) {  // a trace as the path of a line. A column without a value is passed over, and the line goes on behind it where the next value lies within `gap`: a single missed reading is no hole. A hole longer than `gap` breaks the line: nothing is drawn across what was not read
  let d = '', last = null;
  for (let i = 0; i < ts.length; i++) {
    if (vs[i] == null) continue;
    d += `${last == null || ts[i] - last > gap ? 'M' : 'L'}${x(ts[i]).toFixed(1)} ${y(vs[i]).toFixed(1)}`;
    last = ts[i];
  }
  return d;
}
function bandPath(ts, means, lows, peaks, x, y, gap) {  // the band from the lowest to the highest reading of every column, piece by piece. Like the line of the means it passes over a column without a reading and breaks at a hole longer than `gap`. A column that has a mean and did not keep both ends has no band, and ends the piece
  const pieces = [];
  let run = [], last = null;
  const close = () => { if (run.length > 1) pieces.push('M' + run.map(p => `${p[0]} ${p[1]}`).join('L') + 'L' + run.slice().reverse().map(p => `${p[0]} ${p[2]}`).join('L') + 'Z'); run = []; };
  for (let i = 0; i < ts.length; i++) {
    if (means[i] == null) continue;
    if (lows[i] == null || peaks[i] == null) { close(); last = null; continue; }
    if (last != null && ts[i] - last > gap) close();
    run.push([x(ts[i]).toFixed(1), y(peaks[i]).toFixed(1), y(lows[i]).toFixed(1)]);
    last = ts[i];
  }
  close();
  return pieces.join('');
}
/* The stretches of time a state held, each with its beginning, its end and the time of its last column. Neighbouring columns that
   say yes are one stretch. A column that says no ends it, and so does a hole longer than `gap`, as for a line; a column that was not
   read is passed over like a missed reading. Every column stands for `reach` seconds from its time on, and for no longer than up to
   a column that says no: after a hole the first reading of a column can lie late in it. Shorter than `least` is none. */
function spansWhere(ts, flags, reach, gap, least = 0) {
  const spans = [];
  let open = null;
  const end = (at = Infinity) => { if (open && (open[1] = Math.min(open[1], at)) - open[0] >= least) spans.push(open); open = null; };
  for (let i = 0; i < ts.length; i++) {
    if (flags[i] == null) continue;
    if (!flags[i]) end(ts[i]); else if (open && ts[i] - open[2] > gap) end();
    if (flags[i]) open = [open ? open[0] : ts[i], ts[i] + reach, ts[i]];
  }
  end();
  return spans;
}
/* One stretch a state held, as a line of "Earlier in this stretch". what: the word of its lane, with its figures if it has any.
   held: the seconds it held inside the stretch, from what was recorded: the stretch itself only says in which points it held at all,
   and it bridges a reading that was missed. span: the stretch in words. */
const earlierWord = (what, held, span) => `${what} for ${heldWord(held, true)}, within ${span}.`;
// Whether a recording begins later than its stretch: its first reading lies more than three points after the start. Less than that is the room between two readings, and nothing is missing.
const beginsLate = (first, from, reach) => first - from > 3 * reach;
function laneNote(width, tier, interval) {  // what stands under the lanes of a Spark: what three of them are counted from, and what the two that are judged from the points of the curves can show at this resolution, and cannot
  const counted = 'The first three lanes are time nvidia-smi counted.';
  if ((tier === 'raw' || tier === 'memory') && width <= interval) return `${counted} The last two are judged reading by reading.`;
  return `${counted} The last two are judged from the means of each point (${lengthWord(columnReach(width, tier, interval))}): a shorter spell inside a point does not show, and two means do not prove that both held at once.`;
}
// What a lane says whose state could be judged in no point of a stretch. own: its own reading has a value somewhere in the stretch (the fans of the Spark, its distance to the limit); without one, and for a brake nvidia-smi counts, it was not recorded. few: wherever its fans were read, fewer than two other Sparks had a fan reading. Not judged is not the same as not recorded.
const unjudgedWord = (own, few) => !own ? 'not recorded' : few ? 'not judged: fewer than two other Sparks with a fan reading' : 'not judged: a reading it needs was not recorded';
// From when on a lane says anything, where that is later than the first reading of its Spark. A brake nvidia-smi counts (own: undefined) was not recorded before. A state that is judged from several readings could not be judged before: its own reading may stand in the stretch from the start.
const lateWord = (own, when) => `, ${own === undefined ? 'recorded' : 'judged'} from ${when}`;
// How far the history is written behind the clock, in seconds: it is written every 4 s, and then only what is older than one sampling interval and a second. The newest column of a live stretch begins that far before its end, and more by what it is wide.
const writtenBehind = interval => 5 + interval;
/* Whether a state still holds at the end of a stretch that ends now. Only on a live sheet. Only if the stretch itself ends no further
   before the moment on the page (now) than a line would bridge: one whose renewal is still out says nothing about now. Only if the last
   column the state was read in says yes. And only if that column lies no further from the end than a line would bridge on top of what
   the history is written behind the clock (behind, writtenBehind). */
function holdsToNow(ts, flags, to, gap, live, now, behind) {
  if (!live || now - to > gap) return false;
  for (let i = ts.length - 1; i >= 0; i--) if (flags[i] != null) return !!flags[i] && to - ts[i] <= gap + behind;
  return false;
}
// How far one column stands for its readings: as far as it is wide, and no less than from one reading to the next.
const columnReach = (width, tier, interval) => Math.max(width, stepOf(tier, interval));
/* How long a state held in all, from what was recorded. shares: per column the part of its time the state held, from 0 to 1 (1 or 0
   for a state that is judged column by column). counts: how many readings or minutes stand behind each column; each: the seconds one
   of them stands for. Time nobody read counts for nothing, however wide the column is. Without counts every column is one reading.
   ts and to: when each column begins and when the stretch ends. A column stands for its readings from its time on and counts only as
   far as it lies in the stretch: the last one may reach past the end, like the minute that is still running. */
const heldSeconds = (shares, counts, each, ts, to) => shares.reduce((sum, share, i) => sum + (share || 0) * Math.min((counts ? counts[i] || 0 : 1) * each, Math.max(0, to - ts[i])), 0);
// The same in words. A state that held in some column did hold: less than a second is said as that, not as none.
const heldWord = (seconds, any) => !any ? 'none' : seconds < 1 ? 'under 1 s' : lengthWord(seconds);
// The speed below which the fans of a Spark count as slow at one moment: 15 % under the middle of the fans of the others, null with fewer than two of them read.
const slowBelow = fans => { const read = fans.filter(v => v != null); return read.length < 2 ? null : middleOf(read) * SLOW_FAN; };
// The line of that rule on a curve of fans, column by column: the speed below which the fans of a Spark count as slow, from the fans of the others.
const fanFloor = others => (others[0] || []).map((_, i) => slowBelow(others.map(o => o[i])));
/* Column by column: do the fans of one Spark turn more than 15 % slower than the middle of the others while it is no more than 1.5 °C
   cooler. Slower is decided on the fans of the others; as fast as they are needs no temperature. Whether a slower one is no cooler is
   asked of the others whose fans and whose warmth were both read, and both middles are theirs: a middle of fans and a middle of
   warmth over different Sparks compare nothing. Null where that cannot be said: its fans unread, fewer than two others read, or
   slower fans without its own warmth or without two others to compare with. */
function slowFanFlags(own, others, heat, heats) {
  return own.map((fan, i) => {
    const line = slowBelow(others.map(o => o[i]));
    if (fan == null || line == null) return null;
    if (fan >= line) return false;
    const both = others.map((o, k) => [o[i], heats[k][i]]).filter(p => p[0] != null && p[1] != null), fair = slowBelow(both.map(p => p[0]));
    return heat[i] == null || fair == null ? null : fan < fair && heat[i] >= middleOf(both.map(p => p[1])) - NOT_COOLER;
  });
}
// The warmer of two readings column by column, the one that was read where only one was.
const warmerOf = (a, b) => a.map((v, i) => v == null ? (b[i] ?? null) : b[i] == null ? v : Math.max(v, b[i]));
// The sum of two readings column by column, null where one of them was not read.
const sumOf = (a, b) => a.map((v, i) => v == null || b[i] == null ? null : v + b[i]);
const lengthWord = s => {  // a length of time in words, as short as it stays exact enough to read: seconds, minutes, hours and minutes, days and hours
  s = Math.round(s);
  if (s < 120) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 120) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h${m % 60 ? ' ' + (m % 60) + ' min' : ''}`;
  const hours = Math.round(m / 60);  // from two days on to the hour: rounded like the minutes above, not cut
  return `${Math.floor(hours / 24)} d${hours % 24 ? ' ' + (hours % 24) + ' h' : ''}`;
};
function resolutionWord(tier, width, interval) {  // what one point of a curve stands for: a single reading, or the mean of a stretch. A single one only where a column is no wider than the readings lie apart: a wider one holds two of them now and then. A stretch asked for with its band is kept by the minute or as single samples, never mixed
  if (tier === 'minute') return width <= 60 ? 'one-minute means' : `means of ${lengthWord(width)}, from one-minute means`;
  return width <= interval ? `every reading, ${figure(interval, interval % 1 ? 1 : 0)} s apart` : `means of ${lengthWord(width)}, read every ${figure(interval, interval % 1 ? 1 : 0)} s`;
}
function headFigures(n, past) {  // the four figures at the head of a Spark, each as a distance to its limit where the Spark names one: value, unit, what it is, a note and its state. past: looking back, where the fans are the one mean the recording keeps
  const fans = (n.fans || []).filter(f => f != null), each = fans.length > 1 ? fans.map(f => figure(f)).join(' and ') : null, stopped = fans.some(f => f === 0) && (fans.some(f => f > 0) || (n.gpu_c || 0) >= 60);
  return [
    n.tlimit == null ? ['–', '°C', 'to the thermal limit', 'The distance to the limit was not read.', '']
      : [figure(n.tlimit), '°C', 'to the thermal limit', n.gpu_c == null ? 'GPU temperature not read.' : `GPU at ${figure(n.gpu_c)} °C.`, n.tlimit < NEAR_LIMIT && (n.util || 0) >= 50 ? 'warn' : ''],
    n.mhz == null ? ['–', 'MHz', 'GPU clock', 'The clock was not read.', '']
      : n.mhz_max ? [figure(n.mhz / n.mhz_max * 100), '%', 'of its top clock', `${figure(n.mhz)} of ${figure(n.mhz_max)} MHz.`, n.latched ? 'bad' : '']
        : [figure(n.mhz), 'MHz', 'GPU clock', 'Its top clock was not read.', n.latched ? 'bad' : ''],
    [figure(n.w, 1), 'W', 'GPU power', n.w == null ? 'Power was not read.' : n.w_limit ? `Limit ${figure(n.w_limit)} W.` : 'No power limit reported.', ''],
    [figure(n.fan), 'RPM', past ? 'fans' : each ? `fans, mean of ${fans.length === 2 ? 'both' : fans.length}` : 'fan', n.fan == null ? 'No fan reading.' : past ? 'Mean of the fans, as recorded.' : each ? `${each} RPM.` : 'One fan read.', stopped ? 'bad' : ''],
  ].map(([value, unit, what, note, state]) => ({ value, unit, what, note, state }));
}
// What a figure of the head keeps in sight under its word in the calm form: its note while it carries a state, nothing otherwise. What cannot wait is not kept behind a button.
const urgentNote = fig => fig.state ? fig.note : '';
// The notes of the figures of a head that are not in sight, as one paragraph for the box of the bar: each after the word of its figure.
const figureNotes = figs => figs.filter(f => !f.state).map(f => `${f.what[0].toUpperCase()}${f.what.slice(1)}: ${f.note}`).join(' ');
