// The card of a run: what the record of a run says as four figures, as notes, as one line of a list and as a picture. Plain functions of the record, so the checks run them through node.
'use strict';
/* Every word of the card of a run, in one place, as the text agent wrote them from the facts named in the report of stage 2. The checks
   hold the facts in them (figures, units, how much was read), not their wording. */
const RUN_TEXTS = {
  duration: 'duration', speed: 'tokens per second', tokens: 'tokens written', energy: 'GPU energy',
  running: 'running', ended: when => `ended ${when}`, endUnseen: 'end not seen',
  fromTo: (from, to) => `${from} to ${to}.`,
  since: from => `Running since ${from}.`,
  lastNamed: when => `Nobody saw it end. The run source last named it ${when}.`,
  mean: 'Mean over the seconds counted, pauses included.',
  peak: speed => `Peak ${speed} tok/s.`,
  ownEngines: n => `${n} Spark${n === 1 ? '' : 's'} ran on ${n === 1 ? 'its' : 'their'} own. What ${n === 1 ? 'its own engine wrote is' : 'their own engines wrote is'} not counted.`,
  engineUnread: 'The ring engine was not read in this run.',
  tokensPart: pct => `Counted over ${pct} % of the run.`,
  restarted: n => `Ring engine restarted ${n === 1 ? 'once' : n + ' times'}.`,
  energyAll: n => `GPU only, read from ${n === 1 ? 'the Spark' : `all ${n} Sparks`}.`,
  energyPart: (from, of, pct) => `GPU only, read from ${from} of ${of} Sparks, ${pct} % of Spark-seconds.`,
  energyNone: 'GPU power was not read in this run.',
  unheard: when => `The run source has not named this run since ${when}.`,
  away: when => `ringtop restarted in this run and counts on from ${when}. The gap is not counted.`,
  seenLate: when => `ringtop first saw this run at ${when}, more than 30 s after the start its source named.`,
  none: 'No run yet', empty: 'No run has been recorded yet.', stations: 'Queue steps', list: 'Runs', show: 'Show this run',
  more: n => `All ${n} runs`, fewer: 'Newest only',
  failed: problem => `Runs request failed: ${problem}.`,
  info: 'Definitions and sampling', about: 'Measurement notes',
  done: (done, total) => `${done} of ${total} done (source's own count).`,
  stationsOf: n => `${n} step${n === 1 ? '' : 's'} in its queue${n >= 64 ? ' (at most 64 are kept)' : ''}.`,
  ran: (model, image) => `Ran ${model}${image ? ' on ' + image : ''}.`,
  perStep: (steps, each) => `${steps} model steps, ${each} tokens written per model step.`,
  perToken: joules => `${joules} J of GPU energy per token over the whole run.`,
  titles: { run: 'This run', what: 'Run', duration: 'Duration', speed: 'Tokens per second', tokens: 'Tokens written', energy: 'GPU energy', kept: 'Runs kept' },
  what: 'A run is what the run source names: the run command (--runs-cmd, asked about every 5 s) or the lab queue. Same source, same name, start less than 30 s from the last named: one run. It ends when the source names another run, or at the moment it first named none, if that lasts 30 s. An unreachable source leaves it open.',
  durationOf: 'From the start the source named to the end; for an open run, to now. Where the source names no start: from the moment ringtop first saw the run.',
  speedOf: 'Mean: tokens written over the seconds between the first and the last reading counted; pauses and prompt reading are included. Peak: the highest speed at a reading, taken over the 8 s or more before it, and counted only once that window lies inside the run (10 s in at the default 2 s interval).',
  tokensOf: interval => `The gain of the ring engine's generation_tokens_total counter between its readings, one per head sample, ${interval} s apart. After an engine restart the new count is added from 0; what the engine before it wrote after its last reading is missing. The Sparks' own engines are not counted.`,
  energyOf: (interval, silence) => `Per Spark, GPU power (nvidia-smi power.draw, driver average) times the time since its previous sample, ${interval} s apart (the first: since counting began), summed over Sparks, in Wh. Time after the last sample is not counted. Gaps over ${silence} s count nothing; unread power is not 0 W. GPU only: nothing is measured at the wall socket.`,
  kept: 'With a history file (--store) the records of runs are kept for 90 days. Without one, the newest 200 are held until ringtop stops. The list shows the newest 50.',
  // The words of the picture of a run: what stands at its curve, and its foot (how many Sparks, as a ring or not, and that the energy is that of the GPUs).
  pictureCurve: 'tokens per second over the run',
  pictureFoot: (n, ring) => `${n} Spark${n === 1 ? '' : 's'}${ring ? ' in a ring' : ''}. GPU energy only; nothing is measured at the wall socket.`,
  // The words of saving that picture: the button with what it says of itself, the two boxes beside it, and what the card says where no picture could be made.
  save: 'Save as image',
  realName: 'real run name',
  withModel: 'model',
  saveTitle: 'Made in the browser and saved as a file; ringtop sends nothing. The image shows "Test run" and no model. Each box beside the button adds what it names, for one image only. Spark names are always replaced.',
  saveFailed: 'The image could not be made.',
};
const runBegan = r => r.started ?? r.first_seen;  // When a run began: the start its source named last, else the moment it was first seen.
const runEnd = (r, now) => r.open ? now : r.ended;  // Up to when a run is told: to now while it is open, to its end, or null where nobody saw it end.
// How long a run took in seconds, so far for an open one; null where nobody saw it end.
const runSeconds = (r, now) => { const end = runEnd(r, now); return end == null ? null : Math.max(0, end - runBegan(r)); };
// The mean speed of a run in tokens per second: what the ring engine wrote over the seconds that count covers. null where nothing was counted.
const runSpeed = r => r.tokens != null && r.token_s > 0 ? r.tokens / r.token_s : null;
/* How much of a run its sums cover, from 0 to 1 each: the tokens over the seconds they were counted and not counted in, the GPU energy over the
   seconds its power was read and not read, added up over the Sparks. A Spark that was never read counts as not read for all of the run: the
   server adds that where it sees a run end. For a run without an end it is added here: for an open one up to now, for one nobody saw end
   up to the moment its source last named it. null where nothing was counted: no count has no share. */
function runShares(r, now) {
  const seen = Math.max(0, (runEnd(r, now) ?? r.last_heard) - r.first_seen), never = r.ended == null ? (r.sparks - r.gpu_from) * seen : 0;
  const share = (read, gap) => read + gap > 0 ? read / (read + gap) : 1;
  return { tokens: r.tokens == null ? null : share(r.token_s, r.token_gap_s), energy: r.gpu_wh == null ? null : share(r.gpu_read_s, r.gpu_gap_s + never) };
}
// A share as whole per cent for a sentence: 100 only where nothing is missing, so a part is never said to be all.
const sharePct = share => share >= 1 ? 100 : Math.min(99, Math.floor(share * 100));
// A moment of a run in words: the time of day to the minute, with the day where asked.
const runWhen = (t, day) => timeWord(t, 60, !!day);
/* The four figures of the card of a run, in the form of the figures at the head of a Spark (headFigures): value, unit, what it is, a note and
   a state. Duration, mean speed with the peak, tokens written, GPU energy. What was not measured is a dash with its reason as the note,
   never a zero; a figure that covers only a part of the run carries the state 'warn' and says how much. now: the moment on the page. */
function runFigures(r, now) {
  const T = RUN_TEXTS, seconds = runSeconds(r, now), began = runBegan(r), shares = runShares(r, now), speed = runSpeed(r);
  const noTokens = r.tracks ? T.ownEngines(r.tracks) : T.engineUnread, restarts = r.lives > 1 ? ' ' + T.restarted(r.lives - 1) : '';
  const part = shares.tokens != null && shares.tokens < 1, counted = part ? T.tokensPart(sharePct(shares.tokens)) : '';
  const all = shares.energy != null && shares.energy >= 1 && r.gpu_from === r.sparks;
  return [
    seconds == null ? ['–', '', T.duration, T.lastNamed(runWhen(r.last_heard, true)), 'warn']
      : [lengthWord(seconds), '', T.duration, r.open ? T.since(runWhen(began, true)) : T.fromTo(runWhen(began, true), runWhen(r.ended, !sameDay(began, r.ended))), ''],
    speed == null ? ['–', 'tok/s', T.speed, noTokens, '']
      : [figure(speed, speed < 10 ? 1 : 0), 'tok/s', T.speed, `${r.tok_s_peak == null ? '' : T.peak(figure(r.tok_s_peak)) + ' '}${T.mean}`, ''],
    r.tokens == null ? ['–', '', T.tokens, noTokens, '']
      : [figure(r.tokens), '', T.tokens, `${counted}${restarts}`.trim(), part || r.lives > 1 ? 'warn' : ''],
    r.gpu_wh == null ? ['–', 'Wh', T.energy, T.energyNone, '']
      : [figure(r.gpu_wh, r.gpu_wh < 10 ? 2 : 1), 'Wh', T.energy, all ? T.energyAll(r.sparks) : T.energyPart(r.gpu_from, r.sparks, sharePct(shares.energy)), all ? '' : 'warn'],
  ].map(([value, unit, what, note, state]) => ({ value, unit, what, note, state }));
}
/* What else the card of a run has to say in sight, each a sentence: that its source is not heard (an open run nobody named for a minute),
   that ringtop was restarted during it, or that ringtop first saw it more than half a minute after it began. The gaps of its sums stand
   with their figures (runFigures). now: the moment on the page. */
function runNotes(r, now) {
  const T = RUN_TEXTS, out = [];
  if (r.open && now - r.last_heard > 60) out.push(T.unheard(runWhen(r.last_heard, !sameDay(r.last_heard, now))));
  if (r.counted_from > r.first_seen) out.push(T.away(runWhen(r.counted_from, !sameDay(r.counted_from, r.first_seen))));
  if (r.started != null && r.first_seen - r.started > 30) out.push(T.seenLate(runWhen(r.first_seen, !sameDay(r.first_seen, r.started))));
  return out;
}
// The state of a run in a word or two: running, when it ended, or that nobody saw it end.
const runState = r => r.open ? RUN_TEXTS.running : r.ended == null ? RUN_TEXTS.endUnseen : RUN_TEXTS.ended(runWhen(r.ended, true));
/* One run as a line of a list: its name, when it began, and its four figures in short. An unknown figure is a dash. now: the moment on the page. */
function runLine(r, now) {
  const [duration, speed, tokens, energy] = runFigures(r, now), short = f => f.value === '–' ? '–' : `${f.value}${f.unit ? ' ' + f.unit : ''}`;
  return { name: r.name, when: runWhen(runBegan(r), true), state: runState(r), duration: short(duration), speed: short(speed), tokens: tokens.value === '–' ? '–' : `${tokens.value} tokens`, energy: short(energy) };
}
/* How many seconds the queue of the run that is running has left, estimated: the rest of that run from how far it is (its count against its
   total since its start), or else as long as its station took the time before, or as long as a finished station took on average; and for
   every station that waits the same. 0 where nothing can be estimated. steps: the stations; run: the run as the moment names it; now: that moment. */
function queueLeft(steps, run, now) {
  const timed = v => typeof v === 'number';  // 0 s is a time that was read; a time nobody read, or a text in its place, is none
  const finished = steps.filter(s => timed(s.seconds)), typical = finished.length ? finished.reduce((a, s) => a + s.seconds, 0) / finished.length : null;
  const before = s => timed(s.was) ? s.was : typical ?? 0;  // as long as the station took the time before, else the mean
  const current = steps.find(s => s.state === 'running');
  let left = run.started && run.total > run.done && run.done > 0 ? (now - run.started) / run.done * (run.total - run.done) : current ? before(current) : 0;
  for (const s of steps) if (s.state === 'pending') left += before(s);
  return left;
}
/* What the box of the card says of one run beside its figures, as one paragraph: how far it got, how many stations its queue has, which
   model ran on which image, the steps of the engine with the tokens each one wrote, and the GPU energy per token. The last only where
   tokens and energy both cover the whole run: a part over a part is no figure. What the record does not hold is left out. now: the moment on the page.
   neutral: the page shows neutral names. Then nothing is said of model and image: the box shows runs of the past too, and the model of
   an earlier run does not belong into a picture of the page that was made to be shown. It gets into the picture of a run by its own box alone (pictureWords). */
function runFacts(r, now, neutral = false) {
  const T = RUN_TEXTS, shares = runShares(r, now), out = [];
  if (r.total > 0 && r.done != null) out.push(T.done(figure(r.done), figure(r.total)));
  if (Array.isArray(r.steps) && r.steps.length) out.push(T.stationsOf(r.steps.length));
  if (r.model && !neutral) out.push(T.ran(r.model, r.image));
  if (r.tokens > 0 && r.engine_steps > 0) out.push(T.perStep(figure(r.engine_steps), figure(r.tokens / r.engine_steps, 2)));
  if (r.tokens > 0 && r.gpu_wh != null && shares.tokens >= 1 && shares.energy >= 1 && r.gpu_from === r.sparks) out.push(T.perToken(figure(r.gpu_wh * 3600 / r.tokens, 2)));
  return out.join(' ');
}
const PICTURE = { width: 1200, height: 675, pad: 64 };  // the picture of a run: its size and the room at its sides, in its own units
// The colours the picture of a run is drawn in unless it is given others: those of a record of the page (style.css).
const PICTURE_LOOK = { ground: '#0b0f27', ink: '#f3f5ff', dim: 'rgba(228,232,255,.64)', rule: 'rgba(228,232,255,.085)', trace: '#d6dcf8', warn: '#ffc46b' };
// A text as it may stand in XML, between two tags or inside an attribute: its signs of markup as numbers, and without the signs XML forbids.
const xmlText = text => String(text).replace(/[^\x09\x0A\x0D\x20-퟿-�\u{10000}-\u{10FFFF}]/gu, '').replace(/[&<>"']/g, sign => `&#${sign.charCodeAt(0)};`);
// A word of no more than so many letters: a longer one ends in an ellipsis.
const cutWord = (word, letters) => { const all = [...word]; return all.length > letters ? all.slice(0, letters - 1).join('').trimEnd() + '…' : word; };
// A sentence as lines of no more than so many letters each, broken between its words.
const wrapWords = (text, letters) => text.split(' ').reduce((lines, word) => { const last = lines.length - 1; if (last >= 0 && lines[last].length + 1 + word.length <= letters) lines[last] += ' ' + word; else lines.push(word); return lines; }, []);
// The size a word is written in so that it stays inside its room: the size asked for, or a smaller one for a long word. wide: how wide a letter is against its size, 0.6 for figures.
// ponytail: a drawing as text measures nothing, so the width is a guess from the count of letters. Measure with a canvas if a wide name ever runs out of the picture.
const fitSize = (word, size, room, wide = .6) => Math.min(size, Math.floor(room / (wide * Math.max(1, [...word].length))));
// One line of words of a picture as an SVG text at its place, in a size and a colour. The words go in as text, never as markup. more: further attributes, as they are written.
const pictureText = (x, y, size, fill, words, more = '') => `<text x="${x}" y="${y}" font-size="${size}" fill="${fill}"${more}>${xmlText(words)}</text>`;
/* What the picture of a run says in words, and no other word gets into it: the name of the run, from when to when it went (or that nobody
   saw it end), its model, its four figures (runFigures) and its foot. As it comes the run is "Test run" (neutralRecord) and no model is
   named: opt.real puts in the name its source gave it, opt.model the model. The image, the queue and the stations are never read here.
   A Spark is never called by its real name: the name and the model pass the renamer of the neutral lens (opt.pairs: aliasPairs). A figure
   keeps its note only while it carries a state, as on the card. opt.now: the moment on the page. opt.ring: the Sparks are cabled as a ring. */
function pictureWords(r, opt) {
  const rename = renamer(opt.pairs || []), shown = opt.real ? r : neutralRecord(r), figs = runFigures(shown, opt.now);
  return { name: rename(String(shown.name || RUN_WORD)), when: figs[0].state ? runState(shown) : figs[0].note, model: opt.model && typeof r.model === 'string' ? rename(r.model) : '',
    figs: figs.map(fig => ({ ...fig, note: urgentNote(fig) })), foot: RUN_TEXTS.pictureFoot(r.sparks, !!opt.ring && !r.tracks) };
}
// The size the value of a figure of the picture may be written in so that it stays in its column with its unit beside it: 68, or smaller for a long value. room: how wide the column is.
const figureSize = (fig, room) => fitSize(fig.value, 68, room - (fig.unit ? [...fig.unit].length * 16 + 12 : 0));
/* One figure of the picture of a run at its place: its value large with its unit beside it, under it its word, and under that its note in
   lines where it has one, with the mark of a state before the word.
   x: where the column begins; room: how wide it is; size: the size of the value, one for all four; paint: the colours, ready for XML. */
function pictureFigure(fig, x, room, size, paint) {
  const unit = fig.unit ? `<tspan dx="5" font-size="26" font-weight="400" fill="${paint.dim}"> ${xmlText(fig.unit)}</tspan>` : '';
  const out = [`<text x="${x}" y="292" font-size="${size}" font-weight="600" fill="${paint.ink}" font-family="ui-rounded,system-ui,-apple-system,'Segoe UI',sans-serif">${xmlText(fig.value)}${unit}</text>`];
  if (fig.state) out.push(`<rect x="${x}" y="318" width="11" height="11" rx="1.5" fill="${paint.warn}"/>`);
  out.push(pictureText(fig.state ? x + 20 : x, 332, 22, fig.state ? paint.ink : paint.dim, fig.what));
  (fig.note ? wrapWords(fig.note, Math.floor(room / 9.5)) : []).slice(0, 4).forEach((line, k) => out.push(pictureText(x, 364 + 24 * k, 18, paint.ink, line)));  // ponytail: four lines of room above the curve; a longer note loses its end
  return out.join('');
}
/* The readings of the speed over a run as the path of a line in a box of its picture: the beginning of the run at the left, its end at the
   right, zero at the foot and the highest reading on top. A hole in the readings breaks the line (linePath), and a reading from before or
   after the run is left out. '' where fewer than two readings lie in the run: one point is no curve.
   trace: { t, v, gap }, the readings by their moments and how far apart two may lie; box: { left, right, top, bottom }. */
function pictureCurve(trace, from, to, box) {
  if (!trace || !(to > from)) return '';
  const inside = trace.t.map((t, i) => i).filter(i => trace.t[i] >= from && trace.t[i] <= to && trace.v[i] != null);
  if (inside.length < 2) return '';
  const ts = inside.map(i => trace.t[i]), vs = inside.map(i => trace.v[i]), top = Math.max(...vs) || 1;
  return linePath(ts, vs, t => box.left + (t - from) / (to - from) * (box.right - box.left), v => box.bottom - Math.max(0, v) / top * (box.bottom - box.top), trace.gap);
}
/* The picture of a run as SVG, as one text: 1200 by 675, with its name, from when to when it went, its four figures and under them, thin,
   its speed over the run. Plain shapes and words in fonts the system has: it names no file and no address, so drawing it asks nobody
   for anything. Which words get in is decided in pictureWords: as it comes no name of the run and no model, and never the image.
   opt: now, real, model, pairs, ring (pictureWords); look (colours other than PICTURE_LOOK); trace ({ t, v, gap }: the readings of the
   speed over the run, drawn only for a run whose tokens were counted). */
function runPicture(r, opt = {}) {
  const { width, height, pad } = PICTURE, right = width - pad, column = (width - 2 * pad) / 4, now = opt.now ?? r.last_heard, said = pictureWords(r, { ...opt, now });
  const paint = Object.fromEntries(Object.entries({ ...PICTURE_LOOK, ...opt.look }).map(([what, colour]) => [what, xmlText(colour)])), name = cutWord(said.name, 56);
  const size = Math.min(...said.figs.map(fig => figureSize(fig, column - 20)));  // the four values in one size: that of the longest
  const out = [`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="system-ui,-apple-system,'Segoe UI',sans-serif">`,
    `<rect width="${width}" height="${height}" fill="${paint.ground}"/>`,
    pictureText(pad, 122, fitSize(name, 54, width - 2 * pad, .52), paint.ink, name, ' font-weight="700"'), pictureText(pad, 168, 24, paint.dim, said.when)];
  if (said.model) out.push(pictureText(right, 168, 24, paint.dim, cutWord(said.model, 44), ' text-anchor="end"'));
  out.push(`<line x1="${pad}" x2="${right}" y1="204" y2="204" stroke="${paint.rule}" stroke-width="2"/>`);
  said.figs.forEach((fig, k) => out.push(pictureFigure(fig, pad + k * column, column - 20, size, paint)));
  const curve = runSpeed(r) == null ? '' : pictureCurve(opt.trace, runBegan(r), runEnd(r, now) ?? r.last_heard, { left: pad, right, top: 482, bottom: 590 });
  if (curve) out.push(pictureText(pad, 466, 18, paint.dim, RUN_TEXTS.pictureCurve), `<line x1="${pad}" x2="${right}" y1="591" y2="591" stroke="${paint.rule}" stroke-width="2"/>`,
    `<path d="${curve}" fill="none" stroke="${paint.trace}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`);
  out.push(pictureText(pad, 636, 22, paint.dim, said.foot), '</svg>');
  return out.join('');
}
// The name of the file the picture of a run is saved as: the day and the minute the run began, on the local clock. No word of the run gets into it.
const pictureFile = r => { const d = new Date(runBegan(r) * 1000), two = v => String(v).padStart(2, '0'); return `ringtop-run-${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}.png`; };
