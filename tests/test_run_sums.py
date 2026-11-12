"""What a run adds up: tokens and steps from the counters of the ring engine, GPU energy from the power of the Sparks,
each with what was not read."""

from ringtop_parts.core.run_sums import (
    as_saved,
    count_engine,
    count_peak,
    count_power,
    empty_sums,
    gain,
    power_gaps,
    resumed,
    tail_gaps,
)

TOKENS, STEPS = "generation_tokens_total", "iteration_tokens_total_count"


def reading(tokens, steps=None, born=None):
    out = {TOKENS: tokens}
    if steps is not None:
        out[STEPS] = steps
    if born is not None:
        out["process_start_time_seconds"] = born
    return out


def a_run(first_seen=1000.0):
    return {"first_seen": first_seen, "counted_from": first_seen, **empty_sums()}


def test_a_counter_gains_across_a_restart_of_the_engine_what_the_new_life_shows():
    """Between two readings of one life a counter gained their difference. After a restart it began at zero again:
    what it shows was all gained since the reading before. A restart is what figures.restarted says it is: another
    start time, or without one a count of written tokens that fell."""
    assert gain(reading(1410.0), reading(1000.0), TOKENS) == 410.0
    assert gain(reading(1000.0), reading(1000.0), TOKENS) == 0.0
    assert gain(reading(120.0), reading(1000.0), TOKENS) == 120.0  # it fell: a new life
    assert gain(reading(5000.0, born=2.0), reading(1000.0, born=1.0), TOKENS) == 5000.0  # another start time
    assert gain(reading(40.0, steps=20.0), reading(1000.0, steps=300.0), STEPS) == 20.0  # the tokens say it for all


def test_tokens_are_counted_from_reading_to_reading_and_a_reading_counts_once():
    run, bases = a_run(), {}
    assert (run["tokens"], run["engine_steps"], run["token_s"], run["lives"]) == (None, None, 0.0, 0)
    count_engine(run, bases, 999.0, reading(1000.0, 300.0), 15.0)  # the reading of just before the run was seen
    assert (run["tokens"], run["lives"], run["token_gap_s"]) == (None, 1, 0.0)  # one reading is no count yet
    count_engine(run, bases, 1001.0, reading(1040.0, 310.0), 15.0)
    count_engine(run, bases, 1003.0, reading(1100.0, 330.0), 15.0)
    assert (run["tokens"], run["engine_steps"], run["token_s"]) == (100.0, 30.0, 4.0), run
    before = dict(run)
    count_engine(run, bases, 1003.0, reading(1100.0, 330.0), 15.0)  # the same reading at another look
    count_engine(run, bases, 1001.0, reading(1040.0, 310.0), 15.0)  # or an older one
    assert run == before
    count_engine(run, bases, 1603.0, reading(9100.0, 2330.0), 15.0)  # ten minutes unread: the counter went on
    assert (run["tokens"], run["token_s"], run["token_gap_s"], run["lives"]) == (8100.0, 604.0, 0.0, 1), run


def test_a_reading_without_a_counter_is_no_reading_of_it():
    """A counter the engine does not send in one reading is not zero there. The next reading that holds it counts
    from the last one that did; a counter that never comes stays unknown."""
    run, bases = a_run(), {}
    count_engine(run, bases, 1000.0, reading(1000.0), 15.0)
    count_engine(run, bases, 1002.0, {"num_requests_running": 1.0}, 15.0)
    count_engine(run, bases, 1004.0, reading(1090.0), 15.0)
    assert (run["tokens"], run["token_s"], run["engine_steps"]) == (90.0, 4.0, None), run


def test_a_restart_of_the_engine_is_counted_through_and_said():
    run, bases = a_run(), {}
    count_engine(run, bases, 1000.0, reading(5000.0, 1500.0, born=1.0), 15.0)
    count_engine(run, bases, 1002.0, reading(5060.0, 1520.0, born=1.0), 15.0)
    count_engine(run, bases, 1090.0, reading(300.0, 100.0, born=2.0), 15.0)  # a new life: 300 written since
    count_engine(run, bases, 1092.0, reading(360.0, 120.0, born=2.0), 15.0)
    assert (run["tokens"], run["engine_steps"], run["lives"], run["token_s"]) == (420.0, 140.0, 2, 92.0), run


def test_tokens_nobody_could_count_are_said_as_a_gap():
    """A run whose engine is first read a minute after it began has no count of that minute, and one whose engine
    was last read a minute before it ended has none of that one. Neither makes the count smaller in silence."""
    run, bases = a_run(1000.0), {}
    count_engine(run, bases, 900.0, reading(700.0), 15.0)  # a reading from long before the run: not its beginning
    assert bases == {} and run["lives"] == 0
    count_engine(run, bases, 1060.0, reading(1000.0), 15.0)
    count_engine(run, bases, 1062.0, reading(1050.0), 15.0)
    assert (run["tokens"], run["token_gap_s"]) == (50.0, 60.0), run
    tail_gaps(run, bases, 1070.0, 15.0)  # ended 8 s after its last reading: within what a reading stands for
    assert run["token_gap_s"] == 60.0
    tail_gaps(run, bases, 1122.0, 15.0)  # ended a minute after it
    assert run["token_gap_s"] == 120.0
    never, none = a_run(1000.0), {}
    tail_gaps(never, none, 1300.0, 15.0)  # the ring engine was never read in this run: no count, no gap to a count
    assert (never["tokens"], never["token_gap_s"], never["lives"]) == (None, 0.0, 0)


def test_the_peak_is_the_highest_speed_whose_window_lies_in_the_run():
    """The speed of the engine is counted over the last seconds before a reading. At the start of a run that window
    reaches back into what ran before: such a speed is not one of this run."""
    run = a_run(1000.0)
    count_peak(run, 1004.0, 400.0, 10.0)  # the tail of the run before
    assert run["tok_s_peak"] is None
    count_peak(run, 1010.0, 41.0, 10.0)
    count_peak(run, 1012.0, None, 10.0)  # no speed at this reading
    count_peak(run, 1014.0, 38.5, 10.0)
    assert run["tok_s_peak"] == 41.0
    count_peak(run, 1016.0, 0.0, 10.0)
    assert run["tok_s_peak"] == 41.0


SPARKS = ("dgx0", "dgx1", "dgx2", "dgx3")


def powered(run, bases, seconds, watts=10.0, names=SPARKS, away=None):
    """Samples of the GPU power of the Sparks named, every 2 s over the seconds given; `away`: a Spark and the
    seconds from which to which it sends none."""
    for second in range(seconds[0], seconds[1] + 1, 2):
        for name in names:
            if away and name == away[0] and away[1] < second < away[2]:
                continue
            count_power(run, bases, name, run["first_seen"] + second, watts, 15.0)


def test_gpu_energy_is_the_power_of_every_spark_times_the_time_between_its_samples():
    """Four Sparks that draw 10 W of GPU power each for six minutes used 4 Wh of GPU energy. A sample stands for the
    time since the sample before (the driver averages what it reports), and counts once however often it is seen."""
    run, bases = a_run(), {}
    assert (run["gpu_wh"], run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (None, 0.0, 0.0, 0)
    powered(run, bases, (0, 360))
    assert round(run["gpu_wh"], 9) == 4.0 and (run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (1440.0, 0.0, 4)
    before = dict(run)
    powered(run, bases, (300, 360))  # the same samples at another look
    assert run == before
    power_gaps(run, bases, 4, run["first_seen"] + 361.0, 15.0)
    assert run == before  # ended a second after its last samples: nothing missing


def test_a_spark_that_was_away_makes_the_energy_a_part_and_says_so():
    """A Spark that sent no sample for a third of the run was not read in that third. Its energy of then is in no
    sum: the sum is smaller, and the record says by how many seconds of how many Sparks. It is never filled in."""
    run, bases = a_run(), {}
    powered(run, bases, (0, 360), away=("dgx3", 120, 240))
    assert round(run["gpu_wh"], 6) == round(4.0 - 10.0 * 120 / 3600, 6), run["gpu_wh"]
    assert (run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (1320.0, 120.0, 4), run
    late, bases = a_run(), {}
    powered(late, bases, (0, 360), names=SPARKS[:3])
    powered(late, bases, (300, 360), names=SPARKS[3:])  # first read five minutes into the run
    assert (late["gpu_read_s"], late["gpu_gap_s"], late["gpu_from"]) == (1140.0, 300.0, 4), late
    gone, bases = a_run(), {}
    powered(gone, bases, (0, 360), away=("dgx3", 200, 999))  # away from 200 s to the end
    power_gaps(gone, bases, 4, gone["first_seen"] + 360.0, 15.0)
    assert (gone["gpu_read_s"], gone["gpu_gap_s"], gone["gpu_from"]) == (1280.0, 160.0, 4), gone


def test_a_spark_nobody_read_in_a_run_is_a_gap_of_the_whole_run():
    run, bases = a_run(), {}
    powered(run, bases, (0, 360), names=SPARKS[:3])
    assert (run["gpu_from"], run["gpu_gap_s"]) == (3, 0.0)
    power_gaps(run, bases, 4, run["first_seen"] + 360.0, 15.0)
    assert round(run["gpu_wh"], 9) == 3.0 and (run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (
        1080.0,
        360.0,
        3,
    )
    none, bases = a_run(), {}
    power_gaps(none, bases, 4, none["first_seen"] + 100.0, 15.0)  # no Spark read its GPU power: no energy, not 0 Wh
    assert (none["gpu_wh"], none["gpu_gap_s"], none["gpu_from"]) == (None, 400.0, 0)
    old, bases = a_run(), {}
    count_power(old, bases, "dgx0", old["first_seen"] - 600.0, 10.0, 15.0)  # a sample from long before the run
    assert bases == {} and old["gpu_from"] == 0


def test_a_run_ringtop_comes_back_to_keeps_its_sums_and_says_what_nobody_counted():
    """ringtop is restarted while a run goes on. The record of the run was last saved a while before it stopped; what
    it counted after that is lost, and while it was away it counted nothing. Back on the run, the sums go on from
    the readings of that moment, and the time from the save to then is a gap: of the tokens, and of every Spark
    that was being read."""
    run, bases = a_run(1000.0), {"engine": {}, "power": {}}
    count_engine(run, bases["engine"], 1000.0, reading(5000.0), 15.0)
    count_engine(run, bases["engine"], 1060.0, reading(7400.0), 15.0)
    powered(run, bases["power"], (0, 60), names=SPARKS[:3])
    saved = {**run, "saved": 1060.0}
    back = resumed(saved, 1100.0)
    assert (back["counted_from"], back["tokens"], back["token_gap_s"], back["gpu_gap_s"]) == (
        1100.0,
        2400.0,
        40.0,
        120.0,
    )
    assert saved["counted_from"] == 1000.0 and saved["token_gap_s"] == 0.0  # the record that came is not changed
    bases = {"engine": {}, "power": {}}
    count_engine(back, bases["engine"], 1000.0, reading(5000.0), 15.0)  # a reading from before it was away: not one
    assert bases["engine"] == {}
    count_engine(back, bases["engine"], 1102.0, reading(9000.0), 15.0)  # the first reading after: counts from here
    count_engine(back, bases["engine"], 1104.0, reading(9080.0), 15.0)
    assert (back["tokens"], back["token_s"], back["token_gap_s"], back["lives"]) == (2480.0, 62.0, 40.0, 1), back
    for name in SPARKS:  # all four are read now: three were read before, one never
        count_power(back, bases["power"], name, 1102.0, 10.0, 15.0)
        count_power(back, bases["power"], name, 1104.0, 10.0, 15.0)
    # 180 s from before, and 4 s of each Spark since: its first sample stands for the 2 s since the sums count on.
    # The one never read before was unread for the 100 s from the first sight of the run to that moment
    assert (back["gpu_from"], back["gpu_read_s"], back["gpu_gap_s"]) == (4, 196.0, 220.0), back
    unread = resumed({**a_run(1000.0), "saved": 1000.0}, 1100.0)  # nothing was being counted: no gap in a count
    assert (unread["token_gap_s"], unread["gpu_gap_s"], unread["counted_from"]) == (0.0, 0.0, 1100.0)


def test_the_first_sample_of_a_spark_stands_for_the_time_since_the_sums_began():
    """A sample of the GPU power stands for the time before it. In the middle of a run that is the time since the
    sample of that Spark before; for its first sample in the run it is the time since the sums began to count, as
    long as that is no more than the silence: a Spark that comes 14 s into a run was read for those 14 s, by the
    rule that holds between any two samples. Later than the silence, the time before is a gap as it was, and no
    energy is made up for it. A sample that was current when the sums began is where they begin, and counts
    nothing; one older than that by more than the silence is not a beginning."""
    run, bases = a_run(1000.0), {}
    count_power(run, bases, "dgx0", 999.0, 36.0, 15.0)  # the sample that was current when the run began
    assert (run["gpu_wh"], run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (None, 0.0, 0.0, 1), run
    count_power(run, bases, "dgx1", 1014.0, 36.0, 15.0)  # first read 14 s into the run: 36 W over 14 s
    assert round(run["gpu_wh"], 9) == round(36.0 * 14.0 / 3600.0, 9), run["gpu_wh"]
    assert (run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (14.0, 0.0, 2), run
    count_power(run, bases, "dgx2", 1015.0, 36.0, 15.0)  # exactly the silence: still read
    assert (run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (29.0, 0.0, 3), run
    energy = run["gpu_wh"]
    count_power(run, bases, "dgx3", 1015.5, 36.0, 15.0)  # past it: nobody read this Spark until now
    assert (run["gpu_wh"], run["gpu_read_s"], run["gpu_gap_s"], run["gpu_from"]) == (energy, 29.0, 15.5, 4), run
    edge, held = a_run(1000.0), {}
    count_power(edge, held, "dgx0", 984.9, 36.0, 15.0)  # older than the beginning by more than the silence
    assert held == {} and edge["gpu_from"] == 0
    count_power(edge, held, "dgx0", 985.0, 36.0, 15.0)  # by exactly the silence: where its count begins
    assert held == {"dgx0": 985.0} and (edge["gpu_wh"], edge["gpu_read_s"], edge["gpu_gap_s"]) == (None, 0.0, 0.0)
    back = resumed({**a_run(1000.0), "saved": 1050.0}, 1100.0)  # ringtop is back on the run: its sums count from 1100
    count_power(back, {}, "dgx0", 1110.0, 36.0, 15.0)  # 10 s read; never read before, so the 100 s before are a gap
    assert (round(back["gpu_wh"], 9), back["gpu_read_s"], back["gpu_gap_s"]) == (0.1, 10.0, 100.0), back


def test_the_time_after_the_last_sample_of_a_spark_is_not_counted_and_is_a_gap_only_past_the_silence():
    """A run rarely ends on a sample. The seconds between the last sample of a Spark and the end are in no sum:
    nothing is made up for them. They are not said either while they are no more than the silence, which in
    normal running is one beat at most. Past the silence the Spark was not read from its last sample on, and that
    is a gap."""
    run, bases = a_run(), {}
    powered(run, bases, (0, 60))
    before = dict(run)
    assert (before["gpu_read_s"], before["gpu_gap_s"]) == (240.0, 0.0)
    power_gaps(run, bases, 4, run["first_seen"] + 75.0, 15.0)  # ended 15 s after its last samples
    assert run == before  # neither counted on to the end nor called a gap
    power_gaps(run, bases, 4, run["first_seen"] + 75.5, 15.0)
    assert (run["gpu_wh"], run["gpu_read_s"], run["gpu_gap_s"]) == (before["gpu_wh"], 240.0, 4 * 15.5), run


def test_the_tokens_have_a_gap_at_an_end_of_a_run_only_where_the_engine_was_unread_for_longer_than_the_silence():
    """A counter needs two readings: the tokens written before the first reading of a run and after its last one
    are in no count, whatever the rule. That time is said as a gap where it is longer than the silence, at either
    end, and not said where it is not. A reading up to the silence older than the beginning is the one the count
    begins at; an older one is not."""
    run, bases = a_run(1000.0), {}
    count_engine(run, bases, 1015.0, reading(1000.0), 15.0)  # first read exactly the silence after the run began
    count_engine(run, bases, 1017.0, reading(1040.0), 15.0)
    assert (run["tokens"], run["token_s"], run["token_gap_s"]) == (40.0, 2.0, 0.0), run
    tail_gaps(run, bases, 1032.0, 15.0)  # ended exactly the silence after its last reading
    assert run["token_gap_s"] == 0.0
    tail_gaps(run, bases, 1032.5, 15.0)
    assert run["token_gap_s"] == 15.5
    late, held = a_run(1000.0), {}
    count_engine(late, held, 1015.5, reading(1000.0), 15.0)  # first read past the silence
    assert late["token_gap_s"] == 15.5
    edge, held = a_run(1000.0), {}
    count_engine(edge, held, 984.9, reading(900.0), 15.0)  # older than the beginning by more than the silence
    assert held == {}
    count_engine(edge, held, 985.0, reading(900.0), 15.0)  # by exactly the silence: where the count begins
    assert held[TOKENS][0] == 985.0 and edge["token_gap_s"] == 0.0


def test_a_spark_that_was_read_before_ringtop_was_away_and_never_after_is_a_gap_from_then_on():
    """ringtop comes back to a run and one of the Sparks it had been reading never answers again. That Spark was
    not read from the moment the sums count on: its time from there to the end of the run is a gap, like the time
    of a Spark nobody read in a run at all. The time ringtop was away is the gap it was."""
    run, bases = a_run(1000.0), {}
    powered(run, bases, (0, 60))  # four Sparks, read for a minute
    back = resumed({**run, "saved": 1060.0}, 1100.0)
    assert (back["gpu_from"], back["gpu_read_s"], back["gpu_gap_s"]) == (4, 240.0, 160.0), back
    after = {}
    for second in range(1100, 1161, 2):
        for name in SPARKS[:3]:  # the fourth is gone
            count_power(back, after, name, float(second), 10.0, 15.0)
    assert (back["gpu_from"], back["gpu_read_s"], back["gpu_gap_s"]) == (4, 420.0, 160.0), back
    power_gaps(back, after, 4, 1160.0, 15.0)
    assert (back["gpu_read_s"], back["gpu_gap_s"]) == (420.0, 220.0), back  # 60 s of one Spark more
    whole, held = a_run(1000.0), {}
    powered(whole, held, (0, 60))
    power_gaps(whole, held, 4, 1060.0, 15.0)  # a run ringtop was never away from: every Spark it read is in the count
    assert (whole["gpu_read_s"], whole["gpu_gap_s"]) == (240.0, 0.0), whole


def test_the_row_of_an_open_run_says_the_gaps_only_the_memory_of_ringtop_knows():
    """What the sums of a run were last counted to is held in memory and gone when ringtop stops. A Spark that fell
    silent 40 s before the record was saved had those 40 s in no sum and in no gap. Back on the run, ringtop
    counted the time since the save as the gap of every Spark it had read; the gap from the last sample of that
    Spark on, which the end of the run would have said, was lost with the bases: of 200 Spark-seconds 160 were
    told. The same held for the tokens of an engine last read before the save, and for a Spark that never came
    back after ringtop had been away once and was away again. The row the history gets says those gaps as an end
    would (as_saved); the record in memory stays as it is, since there a Spark that comes back says its own gap."""
    run, bases = a_run(1000.0), {"engine": {}, "power": {}}
    powered(run, bases["power"], (0, 60), names=SPARKS[:2], away=("dgx1", 20, 999))  # dgx1: nothing after 20 s
    count_engine(run, bases["engine"], 1000.0, reading(5000.0), 15.0)
    count_engine(run, bases["engine"], 1020.0, reading(5400.0), 15.0)  # the engine: not read after 20 s either
    run["saved"], before = 1060.0, dict(run, saved=1060.0)
    row = as_saved(run, bases["engine"], bases["power"], 1060.0, 15.0)
    assert run == before and (run["gpu_gap_s"], run["token_gap_s"]) == (0.0, 0.0)  # in memory nothing is said yet
    assert (row["gpu_read_s"], row["gpu_gap_s"], row["token_s"], row["token_gap_s"]) == (80.0, 40.0, 20.0, 40.0), row
    near = as_saved(run, bases["engine"], {"dgx0": 1060.0, "dgx1": 1045.0}, 1060.0, 15.0)
    assert near["gpu_gap_s"] == 0.0  # a last sample no older than the silence is no gap, as at an end
    back, after = resumed(row, 1080.0), {}
    assert (back["gpu_gap_s"], back["token_gap_s"]) == (80.0, 60.0), back  # and the 20 s ringtop was away
    for second in range(1080, 1101, 2):  # dgx1 never comes back
        count_power(back, after, "dgx0", float(second), 10.0, 15.0)
    again = as_saved({**back, "saved": 1100.0}, {}, after, 1100.0, 15.0)  # saved once more, then away a second time
    assert (back["gpu_gap_s"], again["gpu_gap_s"]) == (80.0, 100.0), again  # dgx1: unread since the sums count on
    power_gaps(back, after, 2, 1100.0, 15.0)  # the run ends here: every one of its 200 Spark-seconds is told
    assert (back["gpu_read_s"], back["gpu_gap_s"]) == (100.0, 100.0), back  # was 100 and 60
    twice, later = resumed(again, 1110.0), {}
    for second in range(1110, 1121, 2):
        count_power(twice, later, "dgx0", float(second), 10.0, 15.0)
    power_gaps(twice, later, 2, 1120.0, 15.0)  # or it ends here, after the second time away: 240 Spark-seconds
    assert (twice["gpu_read_s"], twice["gpu_gap_s"]) == (110.0, 130.0), twice
    read, none = a_run(1000.0), {"engine": {}, "power": {}}
    powered(read, none["power"], (0, 60), names=SPARKS[:2])
    whole = as_saved(read, none["engine"], none["power"], 1060.0, 15.0)
    assert whole == read and whole is not read  # nothing missing: the row is the record, as a copy


def test_the_time_of_the_tokens_around_a_restart_of_ringtop_is_counted_or_a_gap_and_never_neither():
    """Around a restart of ringtop the time of the tokens was told nowhere in two cases. An engine read before
    ringtop was away and never since: the end of the run knew no reading to count a gap from. An engine never
    read before ringtop was away and read after: nothing was added for the time away (rightly, nothing was being
    counted), and the gap of its first reading reached back only to the moment the sums count on, not to the
    beginning of the run. In both the time is a gap. An engine read before and never since is unread from the
    moment ringtop is back, however short that was, as a Spark is. A run whose engine was never read at all has
    no count and no gap in one, as before."""
    run, bases = a_run(1000.0), {}
    count_engine(run, bases, 1000.0, reading(5000.0), 15.0)
    count_engine(run, bases, 1060.0, reading(6200.0), 15.0)
    back = resumed({**run, "saved": 1060.0}, 1100.0)  # read before; ringtop away for 40 s
    assert (back["token_s"], back["token_gap_s"], back["lives"]) == (60.0, 40.0, 1), back
    soon = dict(back)
    tail_gaps(soon, {}, 1115.0, 15.0)  # the run ends 15 s after ringtop came back, the engine unread: those 15 s too
    assert soon["token_gap_s"] == 55.0
    row = as_saved({**back, "saved": 1160.0}, {}, {}, 1160.0, 15.0)  # a save, the engine still unread: said in the row
    assert (back["token_gap_s"], row["token_gap_s"]) == (40.0, 100.0), row
    again = resumed(row, 1170.0)  # ringtop away a second time, for 10 s, and the engine unread to the end
    tail_gaps(again, {}, 1200.0, 15.0)
    tail_gaps(back, {}, 1200.0, 15.0)  # or never away again, and unread to the end
    assert (back["token_gap_s"], again["token_gap_s"]) == (140.0, 140.0), (back, again)  # was 40 and 50: of 200 s
    assert back["token_s"] + back["token_gap_s"] == 200.0
    late, held = resumed({**a_run(1000.0), "saved": 1060.0}, 1100.0), {}  # never read before ringtop was away
    assert (late["token_gap_s"], late["lives"]) == (0.0, 0)  # nothing was being counted: no gap in a count yet
    count_engine(late, held, 1114.0, reading(900.0), 15.0)  # first read 14 s after ringtop came back
    count_engine(late, held, 1204.0, reading(2700.0), 15.0)
    counted = (late["tokens"], late["token_s"], late["token_gap_s"], late["lives"])
    assert counted == (1800.0, 90.0, 114.0, 1), late  # the gap was 0: of 204 s, 90 were told
    never = resumed({**a_run(1000.0), "saved": 1060.0}, 1100.0)
    tail_gaps(never, {}, 1300.0, 15.0)  # never read at all: no count, and no gap in one
    assert (never["tokens"], never["token_gap_s"], never["lives"]) == (None, 0.0, 0), never


def test_a_clock_set_back_while_ringtop_was_away_makes_no_gap_smaller():
    """The time ringtop was away from a run is a gap: from the last save to the moment it is back. With the clock
    set back in between, that moment lies before the save, and the gap came out below zero: every gap the record
    had shrank by it, four Sparks and two minutes took 480 s off, and a share could read 100 % with a part
    missing. How long ringtop was away is not known then. It was not less than nothing."""
    run, bases = a_run(1000.0), {"engine": {}, "power": {}}
    count_engine(run, bases["engine"], 1000.0, reading(5000.0), 15.0)
    count_engine(run, bases["engine"], 1060.0, reading(6200.0), 15.0)
    powered(run, bases["power"], (0, 60), away=("dgx3", 20, 40))  # one Spark was away for 20 s: a gap it has
    saved = {**run, "saved": 1060.0, "token_gap_s": 5.0}
    assert (saved["gpu_gap_s"], saved["gpu_from"]) == (20.0, 4)
    back = resumed(saved, 940.0)  # the clock reads two minutes less than at the save
    assert (back["token_gap_s"], back["gpu_gap_s"]) == (5.0, 20.0), back  # were -115 and -460
    assert back["counted_from"] == 940.0  # the sums count on from the moment the clock shows now
    assert resumed(saved, 1060.0)["gpu_gap_s"] == 20.0 and resumed(saved, 1061.0)["gpu_gap_s"] == 24.0


def test_a_spark_first_read_after_ringtop_was_away_was_not_read_before_either():
    """Back on a run, ringtop adds the time it was away as a gap of the Sparks that had been read, and the end of
    the run says the Sparks never read for all of it. A Spark first read after ringtop came back is neither: its
    time before stood in no sum and in no gap. The record counts Sparks, not names, so it is told by the number:
    a Spark that makes one more than were ever read in the run was unread from the moment the run was first seen
    to the moment the sums count on. Said once, with its first sample; what comes after that goes by the rules
    of every first sample. A run ringtop was never away from has no such time."""
    run, bases = a_run(1000.0), {}
    powered(run, bases, (0, 60), names=SPARKS[:3])
    back, after = resumed({**run, "saved": 1060.0}, 1080.0), {}
    assert (back["gpu_from"], back["gpu_read_s"], back["gpu_gap_s"]) == (3, 180.0, 60.0), back
    for name in SPARKS[:3]:  # the three that were read before are read again: nothing is new
        count_power(back, after, name, 1080.0, 10.0, 15.0)
    assert (back["gpu_from"], back["gpu_gap_s"]) == (3, 60.0), back
    count_power(back, after, "dgx3", 1082.0, 10.0, 15.0)  # a fourth, never read before: its 80 s to here
    assert (back["gpu_from"], back["gpu_read_s"], back["gpu_gap_s"]) == (4, 182.0, 140.0), back  # the gap was 60
    count_power(back, after, "dgx3", 1084.0, 10.0, 15.0)
    assert (back["gpu_read_s"], back["gpu_gap_s"]) == (184.0, 140.0), back  # said once
    other, held = resumed({**run, "saved": 1060.0}, 1080.0), {}
    for name in ("dgx3", "dgx0", "dgx1"):  # by number: whichever three come first stand for the three read before
        count_power(other, held, name, 1080.0, 10.0, 15.0)
    count_power(other, held, "dgx2", 1100.0, 10.0, 15.0)  # the fourth comes 20 s later: those 20 s are a gap as well
    assert (other["gpu_from"], other["gpu_read_s"], other["gpu_gap_s"]) == (4, 180.0, 160.0), other
    whole, base = a_run(1000.0), {}
    powered(whole, base, (0, 60), names=SPARKS[:3])
    count_power(whole, base, "dgx3", 1070.0, 10.0, 15.0)  # never away: a late Spark has the gap it always had
    assert (whole["gpu_from"], whole["gpu_gap_s"]) == (4, 70.0), whole
    odd, none = resumed({**run, "saved": 1060.0}, 940.0), {}  # the clock set back to before the run was first seen
    for name in SPARKS:
        count_power(odd, none, name, 940.0, 10.0, 15.0)
    assert (odd["gpu_from"], odd["gpu_gap_s"]) == (4, 0.0), odd  # no gap is made smaller by it


def test_a_clock_set_back_after_ringtop_came_back_makes_the_tail_of_the_tokens_no_smaller():
    """An engine read before ringtop was away and never since is unread from the moment ringtop came back to the
    end: a gap. With the clock set back after that moment, the end lies before it, and the gap came out below
    zero: 90 s taken off what the record said. How long that was is not known then. It was not less than nothing,
    as for the time away itself (resumed)."""
    run, bases = a_run(1000.0), {}
    count_engine(run, bases, 1000.0, reading(5000.0), 15.0)
    count_engine(run, bases, 1060.0, reading(6200.0), 15.0)
    back = resumed({**run, "saved": 1060.0, "token_gap_s": 5.0}, 1100.0)  # read before; ringtop away for 40 s
    tail_gaps(back, {}, 1005.0, 15.0)  # the run ends with the clock 95 s behind the moment ringtop came back
    assert back["token_gap_s"] == 45.0, back  # was -50


def test_a_clock_set_back_makes_the_gpu_gaps_at_the_end_of_a_run_no_smaller():
    """The same for the GPU energy as for the tokens: a Spark read before ringtop was away and never since is unread
    from the moment ringtop came back, one never read in the run for all of it. With the clock set back to before
    those moments, the end lay before them and both gaps came out below zero: 380 s taken off for four Sparks, and
    one Spark never read took 10 s off. They are no less than nothing."""
    run, bases = a_run(1000.0), {}
    powered(run, bases, (0, 60))
    back = resumed({**run, "saved": 1060.0}, 1100.0)  # four Sparks read before; ringtop away for 40 s
    assert back["gpu_gap_s"] == 160.0, back
    power_gaps(back, {}, 4, 1005.0, 15.0)  # the run ends with the clock 95 s behind the moment ringtop came back
    assert back["gpu_gap_s"] == 160.0, back  # was -220: 4 x -95 taken off
    three, held = a_run(1000.0), {}
    powered(three, held, (0, 60), names=SPARKS[:3])
    power_gaps(three, held, 4, 990.0, 15.0)  # a fourth never read; the end before the run was first seen
    assert three["gpu_gap_s"] == 0.0, three  # was -10
