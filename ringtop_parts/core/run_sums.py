"""What a run adds up: tokens and steps from the counters of the ring engine, GPU energy from the GPU power of the
Sparks, each with what nobody could count.

Every sum hangs on the readings, never on how often somebody looks: a counter is counted from the reading it was
last counted to, the power of a Spark from its sample before, and a reading counts once. `bases` holds what was
last counted to: per counter that reading with its moment, per Spark the moment of that sample."""

from __future__ import annotations

from ringtop_parts.core.figures import num, restarted

TOKENS = "generation_tokens_total"
# the field of a record with the counter of the ring engine it is the gain of
COUNTED = (("tokens", TOKENS), ("engine_steps", "iteration_tokens_total_count"))


def empty_sums() -> dict:
    """The sums of a run nothing was counted into yet. Tokens and steps are unknown until two readings of the
    engine lie in the run: that is not zero. `token_s` are the seconds between the readings the tokens were counted
    over, `token_gap_s` the seconds of the run nobody could count them in, `lives` the lives of the engine seen.
    GPU energy is unknown until a sample of a Spark stands for time in the run. `gpu_read_s` are the seconds its
    power was read over, added up over the Sparks, `gpu_gap_s` the seconds it was not, `gpu_from` the Sparks that
    were read at all."""
    engine = {"tokens": None, "engine_steps": None, "token_s": 0.0, "token_gap_s": 0.0, "lives": 0, "tok_s_peak": None}
    return {**engine, "gpu_wh": None, "gpu_read_s": 0.0, "gpu_gap_s": 0.0, "gpu_from": 0}


def gain(new: dict, old: dict, key: str) -> float:
    """What a counter gained from one reading to a later one that both hold it. Across a restart of the engine
    (figures.restarted, or this counter fell) it began at zero again: what it shows was all gained since. What the
    life before counted after its last reading is lost with it."""
    before, after = old[key], new[key]
    return after if restarted(new, old) or after < before else after - before


def count_engine(record: dict, bases: dict, t: float, reading: dict, silence: float) -> None:
    """Counts one reading of the ring engine, taken at `t`, into the record of a run. A reading that was counted
    already changes nothing, and one without a counter is no reading of that counter: the next one counts from the
    last that held it. The first reading of a run may be up to `silence` older than the moment its sums count from
    (the one that was current when it began); an older one is not its beginning. Where the first reading comes
    later than `silence` after that moment, the seconds before it are a gap (_token_time)."""
    for field, key in COUNTED:
        base = bases.get(key)
        if num(reading.get(key)) is None or (base is not None and t <= base[0]):
            continue
        if base is None and t < record["counted_from"] - silence:
            continue
        bases[key] = (t, reading)
        if base is not None:
            record[field] = (record[field] or 0.0) + gain(reading, base[1], key)
        if key == TOKENS:
            _token_time(record, base, t, reading, silence)


def _token_time(record: dict, base: tuple | None, t: float, reading: dict, silence: float) -> None:
    """The time behind the count of tokens after one more reading: the seconds the count now covers, the lives of
    the engine it ran through, and with the first reading since the sums count on the seconds before it nobody
    counted, where they are more than `silence`. Those reach back to the moment the sums count on where the
    engine was read before it: what lies further back is counted, or said already. Where this is the first
    reading of the run at all they reach back to the moment the run was first seen: of an engine never read,
    nothing was said for the time ringtop was away (resumed), nor for the time before."""
    if base is None:
        late = t - (record["counted_from"] if record["lives"] else record["first_seen"])
        record["lives"] = record["lives"] or 1
        record["token_gap_s"] += late if late > silence else 0.0
    else:
        record["token_s"] += t - base[0]
        record["lives"] += 1 if restarted(reading, base[1]) else 0


def count_peak(record: dict, t: float, tok_s: float | None, window: float) -> None:
    """Keeps the highest speed of the engine in a run. `tok_s` is its speed at the reading taken at `t`, counted
    over the `window` seconds before it: while that window reaches back before the run, the speed is not one of
    this run. A reading without a speed leaves the peak as it is."""
    if tok_s is not None and t - record["first_seen"] >= window:
        record["tok_s_peak"] = max(record["tok_s_peak"] or 0.0, tok_s)


def tail_gaps(record: dict, bases: dict, ended: float, silence: float) -> None:
    """Closes the sums of a run that ended at `ended`: where the last reading the tokens were counted to is more
    than `silence` older than the end, the seconds after it are a gap. Where it is not, what was written after it
    is in no count and is not said: a counter needs two readings, and that is one beat at most in normal running.
    An engine that was read before ringtop was away from the run and never since (`bases` holds what was read
    since the sums count on) was not read from that moment on: a gap however short, as for a Spark read before
    and never since (power_gaps); with the clock set back to before that moment, no less than nothing (resumed).
    A run whose engine was never read has no count, and no gap in one."""
    base = bases.get(TOKENS)
    if base is None and record["lives"]:
        record["token_gap_s"] += max(0.0, ended - record["counted_from"])
    elif base is not None and ended - base[0] > silence:
        record["token_gap_s"] += ended - base[0]


def count_power(record: dict, bases: dict, name: str, t: float, watts: float, silence: float) -> None:
    """Counts one sample of the GPU power of one Spark, taken at `t`, into the record of a run: its watts times
    the seconds since the sample of that Spark before it. The driver averages the power it reports, so a sample
    stands for the time before it. For the first sample of a Spark in the run that is the time since the moment
    the sums count from: a Spark that comes a few seconds into a run was read for those seconds, by the same rule.
    A sample that was counted already changes nothing. Two samples further apart than `silence` have a gap between
    them: nobody read the Spark then, and no energy is made up for it. The same holds where the first sample of a
    Spark comes later than `silence` after the moment the sums count from. A sample that was current at that
    moment is where the count of its Spark begins, and counts nothing; one that is older than the moment by more
    than `silence` is not a beginning.

    The record counts the Sparks read at all, not their names. A Spark that makes one more than were ever read
    in the run was not read before the moment the sums count from either. Where ringtop was away from the run,
    that moment lies after the first sight of the run, and the time between is a gap nothing else says: the time
    away is added for the Sparks read before it (resumed), and the end says a whole run only for the Sparks never
    read at all (power_gaps)."""
    before = bases.get(name)
    if (before is not None and t <= before) or (before is None and t < record["counted_from"] - silence):
        return
    bases[name] = t
    if len(bases) > record["gpu_from"]:  # one more of the Sparks read at all, at any one time
        record["gpu_from"] = len(bases)
        record["gpu_gap_s"] += max(0.0, record["counted_from"] - record["first_seen"])
    span = t - (record["counted_from"] if before is None else before)  # the time this sample stands for
    if span > silence:
        record["gpu_gap_s"] += span
    elif span > 0:
        record["gpu_wh"] = (record["gpu_wh"] or 0.0) + watts * span / 3600.0
        record["gpu_read_s"] += span


def power_gaps(record: dict, bases: dict, sparks: int, ended: float, silence: float) -> None:
    """Closes the GPU energy of a run of `sparks` Sparks that ended at `ended`. A Spark whose last sample is more
    than `silence` older than the end was not read from then on. One that was read before ringtop was away from
    the run and never since (`bases` holds what was read since the sums count on) was not read from that moment
    on. One that was never read in the run was not read in all of it. All three are gaps, and the energy is the
    part that was read. With the clock set back to before those moments, the last two are no less than nothing
    (resumed).

    A run rarely ends on a sample. Where the last sample of a Spark is no more than `silence` older than the end,
    the time after it is neither counted nor said: one beat at most in normal running. Nothing is made up for it."""
    for t in bases.values():
        if ended - t > silence:
            record["gpu_gap_s"] += ended - t
    left = max(0, record["gpu_from"] - len(bases))  # read before ringtop was away, and not since
    record["gpu_gap_s"] += left * max(0.0, ended - record["counted_from"])
    record["gpu_gap_s"] += (sparks - record["gpu_from"]) * max(0.0, ended - record["first_seen"])


def as_saved(record: dict, engine: dict, power: dict, now: float, silence: float) -> dict:
    """The record of an open run as the history gets it at `now`: a copy that also says the gaps only `engine` and
    `power` know, the bases of its tokens and of its GPU energy, which are gone when ringtop stops. The engine or
    a Spark whose last reading is more than `silence` older than this moment was not read from then on, and one
    that was read before ringtop was away and never since was not read since the sums count on: gaps, by the rules
    of an end (tail_gaps, power_gaps). Whoever takes the run up from this row (resumed), or closes it because
    nobody saw it end, has sums that say everything up to this save. A Spark that was never read in the run is
    not said here: the end of the run says it for all of the run, and the page does until then. The record that
    came is not changed: while ringtop runs, a Spark that comes back says its own gap."""
    row = dict(record)
    tail_gaps(row, engine, now, silence)
    power_gaps(row, power, row["gpu_from"], now, silence)  # of the Sparks that were read at all
    return row


def resumed(record: dict, now: float) -> dict:
    """The record of a run ringtop comes back to at `now`, after it was away while the run went on. Its sums stand
    as they were last saved, with what was unread before that save said in them (as_saved). From that save until
    now nobody counted: a gap for the tokens, where they were being counted, and for every Spark that was being
    read. The sums count on from this moment (`counted_from`), from the readings that are current now. Where the
    clock was set back meanwhile and shows a moment before the save, how long ringtop was away is not known: no
    gap is added, and none is taken away."""
    away = max(0.0, now - record["saved"])
    tokens = record["token_gap_s"] + (away if record["lives"] else 0.0)
    return {
        **record,
        "counted_from": now,
        "token_gap_s": tokens,
        "gpu_gap_s": record["gpu_gap_s"] + record["gpu_from"] * away,
    }
