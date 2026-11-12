"""Figures from counters and histograms: quantiles, windows, how far drafted tokens survive."""

import math

from ringtop_parts.core.figures import (
    counter_rate,
    engine_speed,
    engine_work,
    histogram_delta,
    latency_table,
    num,
    pace,
    quantile,
    recent_quantile,
    restarted,
    speculation,
    window_mean,
    window_ratio,
)


def test_quantile_interpolates_like_promql():
    buckets = [(0.5, 10.0), (1.0, 20.0), (math.inf, 20.0)]
    assert quantile(buckets, 0.5) == 0.5
    assert quantile(buckets, 0.75) == 0.75
    assert quantile([(1.0, 0.0), (math.inf, 0.0)], 0.5) is None
    assert quantile([(1.0, 0.0), (math.inf, 4.0)], 0.5) == 1.0


def test_histogram_delta_survives_an_engine_restart():
    assert histogram_delta({"1": 5.0, "+Inf": 8.0}, {"1": 2.0, "+Inf": 3.0}) == [(1.0, 3.0), (math.inf, 5.0)]
    assert histogram_delta({"1": 1.0, "+Inf": 1.0}, {"1": 9.0, "+Inf": 9.0}) == [(1.0, 1.0), (math.inf, 1.0)]


def test_speculation_by_position_uses_the_window():
    old = {
        "spec_decode_num_drafts_total": 100.0,
        "spec_decode_num_accepted_tokens_per_pos_total:0": 60.0,
        "spec_decode_num_draft_tokens_per_pos_total:0": 100.0,
        "spec_decode_num_accepted_tokens_per_pos_total:1": 30.0,
        "spec_decode_num_draft_tokens_per_pos_total:1": 60.0,
    }
    new = {
        "spec_decode_num_drafts_total": 200.0,
        "spec_decode_num_accepted_tokens_per_pos_total:0": 140.0,
        "spec_decode_num_draft_tokens_per_pos_total:0": 200.0,
        "spec_decode_num_accepted_tokens_per_pos_total:1": 70.0,
        "spec_decode_num_draft_tokens_per_pos_total:1": 140.0,
    }
    spec = speculation(new, old)
    assert spec["recent"] is True and spec["positions"][0] == {"pos": 0, "rate": 0.8, "reach": 1.0}
    assert spec["positions"][1] == {"pos": 1, "rate": 0.5, "reach": 0.8} and spec["mean_length"] == 2.2
    quiet = speculation(new, new)
    assert quiet["recent"] is False and quiet["positions"][0]["rate"] == 0.7
    assert speculation({}, {}) == {"positions": [], "mean_length": None}


def test_speculation_never_mixes_two_lives_of_the_engine():
    """An engine that restarted inside the window and already drafted more than its predecessor: the differences would
    mix two lives and give shares below zero or above one. Then only the new life counts."""
    old = {
        "spec_decode_num_drafts_total": 100.0,
        "spec_decode_num_accepted_tokens_per_pos_total:0": 90.0,
        "spec_decode_num_draft_tokens_per_pos_total:0": 100.0,
        "spec_decode_num_accepted_tokens_per_pos_total:1": 10.0,
        "spec_decode_num_draft_tokens_per_pos_total:1": 80.0,
    }
    new = {
        "spec_decode_num_drafts_total": 150.0,
        "spec_decode_num_accepted_tokens_per_pos_total:0": 30.0,  # fewer than before: the counter started again
        "spec_decode_num_draft_tokens_per_pos_total:0": 150.0,
        "spec_decode_num_accepted_tokens_per_pos_total:1": 75.0,  # 65 more accepted than the 60 more drafted
        "spec_decode_num_draft_tokens_per_pos_total:1": 140.0,
    }
    spec = speculation(new, old)
    assert [row["rate"] for row in spec["positions"]] == [0.2, 0.536], spec
    assert spec["recent"] is False and all(0 <= row["rate"] <= 1 for row in spec["positions"])
    assert spec["mean_length"] == 1.7
    # two lives can also give differences that look like one: then only the start time of the engine tells them apart
    first = {
        "process_start_time_seconds": 1000.0,
        "spec_decode_num_drafts_total": 100.0,
        "spec_decode_num_accepted_tokens_per_pos_total:0": 10.0,
        "spec_decode_num_draft_tokens_per_pos_total:0": 20.0,
    }
    second = {
        "process_start_time_seconds": 2000.0,
        "spec_decode_num_drafts_total": 150.0,
        "spec_decode_num_accepted_tokens_per_pos_total:0": 100.0,
        "spec_decode_num_draft_tokens_per_pos_total:0": 140.0,
    }
    spec = speculation(second, first)
    assert spec["recent"] is False and spec["positions"][0]["rate"] == 0.714, spec  # 100 of 140, not 90 of 120
    one_life = speculation(
        second | {"spec_decode_num_drafts_total": 300.0}, first | {"process_start_time_seconds": 2000.0}
    )
    assert one_life["recent"] is True and one_life["positions"][0]["rate"] == 0.75


def test_speculation_takes_no_missing_counter_for_a_count_of_zero():
    """How far drafts survive is counted from three kinds of counters. One a reading does not hold is no count of
    zero. Missing in the older reading, the whole life of a position stood against the few drafts of the window (a
    reach of 1100 %). Missing in the newer one, a position that was drafted a hundred times reached 0 % of the drafts.
    And a position the older reading counted and the newer one does not was left out of the mean of a window that
    still called itself recent."""
    kept, made, drafts = (
        "spec_decode_num_accepted_tokens_per_pos_total:",
        "spec_decode_num_draft_tokens_per_pos_total:",
        "spec_decode_num_drafts_total",
    )
    # the older reading did not hold the position yet: no window to count in, the whole run so far stands
    late = speculation({drafts: 110.0, kept + "0": 80.0, made + "0": 110.0}, {drafts: 100.0})
    assert late == {"positions": [{"pos": 0, "rate": 0.727, "reach": 1.0}], "mean_length": 1.73, "recent": False}, late
    # the newer reading does not say how often the position was drafted: its share and its reach are not known
    before = {drafts: 100.0, kept + "0": 60.0, made + "0": 100.0}
    blind = speculation({drafts: 110.0, kept + "0": 65.0}, before)
    assert blind["positions"] == [{"pos": 0, "rate": None, "reach": None}], blind  # was a reach of 0.0
    # a position that is gone: the two readings are not of one life, only what the newer one holds is counted
    gone = speculation(
        {drafts: 110.0, kept + "0": 65.0, made + "0": 110.0}, {**before, kept + "1": 30.0, made + "1": 60.0}
    )
    assert gone["recent"] is False and gone["positions"] == [{"pos": 0, "rate": 0.591, "reach": 1.0}], gone
    assert gone["mean_length"] == 1.59  # was 1.5, under "recent"
    # without the count of drafts nobody knows how far they reach, or how long they get
    unread = speculation({kept + "0": 65.0, made + "0": 110.0}, {})
    assert unread == {"positions": [{"pos": 0, "rate": 0.591, "reach": None}], "mean_length": None, "recent": False}, (
        unread
    )


def test_more_tokens_drafted_at_a_position_than_drafts_were_made_is_no_window():
    """Every draft holds at most one token of each position. Two readings between which a position gained fifty
    drafted tokens while ten drafts were made are not of one life of the engine, whatever their start times say or
    do not say: counted as a window, that position was reached by 500 % of the drafts. Then the whole run stands."""
    kept, made, drafts = (
        "spec_decode_num_accepted_tokens_per_pos_total:",
        "spec_decode_num_draft_tokens_per_pos_total:",
        "spec_decode_num_drafts_total",
    )
    old = {drafts: 100.0, kept + "0": 50.0, made + "0": 100.0, kept + "1": 5.0, made + "1": 10.0}
    new = {drafts: 110.0, kept + "0": 55.0, made + "0": 110.0, kept + "1": 40.0, made + "1": 60.0}
    spec = speculation(new, old)
    assert spec["recent"] is False and spec["positions"][1] == {"pos": 1, "rate": 0.667, "reach": 0.545}, spec
    fits = speculation({**new, made + "1": 20.0, kept + "1": 10.0}, old)  # ten more drafted in ten drafts: a window
    assert fits["recent"] is True and fits["positions"][1] == {"pos": 1, "rate": 0.5, "reach": 1.0}, fits


def test_latency_table_prefers_the_window():
    hist = {"time_to_first_token_seconds": {"1": 10.0, "2": 20.0, "+Inf": 20.0}}
    old = {"time_to_first_token_seconds": {"1": 10.0, "2": 10.0, "+Inf": 10.0}}
    row = latency_table(hist, old)[0]
    assert row["name"] == "First token" and row["recent"] is True and 1.0 <= row["p50"] <= 2.0
    assert latency_table(hist, hist)[0]["recent"] is False


def test_a_rate_needs_the_counter_in_both_readings_and_one_that_did_not_fall():
    """What a counter gained per second is only known from two readings that both hold it. A reading without the
    counter is no reading of zero: the speed was kept as a measured 0, or as the count of a whole life over a few
    seconds. And a counter that fell belongs to another life of the engine: no rate, not a rate of 0."""
    assert counter_rate({"n": 180.0}, {"n": 100.0}, 108.0, 100.0, "n") == 10.0
    assert counter_rate({"n": 100.0}, {"n": 100.0}, 108.0, 100.0, "n") == 0.0  # read twice, nothing gained: a 0
    assert counter_rate({}, {"n": 100.0}, 108.0, 100.0, "n") is None
    assert counter_rate({"n": 100.0}, {}, 108.0, 100.0, "n") is None  # not 12.5: its whole life so far over 8 s
    assert counter_rate({"n": 5.0}, {"n": 100.0}, 108.0, 100.0, "n") is None
    assert counter_rate({"n": 180.0}, {"n": 100.0}, 100.0, 100.0, "n") is None  # one moment: no time between them
    # what follows for an engine: no speed, and its state from what was read (requests run, no tokens known)
    busy = {"num_requests_running": 1.0}
    own = pace([(100.0, {**busy, "generation_tokens_total": 100.0}, {}), (108.0, busy, {})])
    assert own["tok_s"] is None and own["state"] == "reading", own


def test_no_speed_is_counted_from_two_readings_less_than_a_second_apart():
    """Two readings a moment apart are no stretch to count a speed over: the moment a reading carries is not the
    moment the engine counted (an answer takes time, two samples can arrive together), and over 0.05 s that error
    is the whole figure. 145 tokens between two readings stamped 0.05 s apart stood as 2900 tokens/s. From a
    second apart on the speed is counted as ever, for the ring engine and for an engine a Spark runs on its own."""
    before, after = {"n": 100.0}, {"n": 245.0}
    assert counter_rate(after, before, 100.05, 100.0, "n") is None  # was 2900.0
    assert counter_rate(after, before, 100.99, 100.0, "n") is None
    assert counter_rate(after, before, 101.0, 100.0, "n") == 145.0
    busy = {"num_requests_running": 1.0}
    own = pace(
        [
            (100.0, {**busy, "generation_tokens_total": 100.0}, {}),
            (100.05, {**busy, "generation_tokens_total": 245.0}, {}),
        ]
    )
    assert own["tok_s"] is None and own["state"] == "reading", own  # no speed known: requests run, so it reads
    ring = engine_speed(
        {**busy, "generation_tokens_total": 245.0}, {**busy, "generation_tokens_total": 100.0}, 100.05, 100.0
    )
    assert ring["tok_s"] is None and ring["steps_s"] is None and ring["state"] == "reading", ring


def test_a_share_or_a_mean_is_not_made_of_a_counter_that_is_missing():
    """A share of two counters and a mean per request are only known where the engine sent both counters. One that
    is missing is no count of zero: "0 % of drafts survive" was said of an engine that never sent how many it
    accepted. And a counter the older reading did not hold yet gives no difference: then the figure since the
    engine started stands, not its whole life over what the window counted."""
    both = {"hits": 30.0, "asked": 100.0}
    assert window_ratio({"hits": 60.0, "asked": 200.0}, both, "hits", "asked") == 0.3  # the window: 30 of 100
    assert window_ratio(both, both, "hits", "asked") == 0.3  # nothing new in between: since it started
    assert window_ratio({"asked": 200.0}, {"asked": 100.0}, "hits", "asked") is None  # was 0.0
    assert window_ratio({"asked": 200.0}, both, "hits", "asked") is None  # was 0.0
    assert window_ratio({"hits": 60.0}, both, "hits", "asked") is None
    assert window_ratio({"hits": 60.0, "asked": 200.0}, {"asked": 100.0}, "hits", "asked") == 0.3  # was 0.6
    timed = {"wait_count": 2.0, "wait_sum": 20.0}
    assert window_mean({"wait_count": 4.0, "wait_sum": 26.0}, timed, "wait") == 3.0  # the window: 6 s over 2
    assert window_mean(timed, timed, "wait") == 10.0
    assert window_mean({"wait_count": 4.0}, {"wait_count": 2.0}, "wait") is None  # was 0.0: a wait of no time
    assert window_mean({"wait_sum": 26.0}, timed, "wait") is None
    assert window_mean({"wait_count": 4.0, "wait_sum": 26.0}, {"wait_count": 2.0}, "wait") == 6.5  # was 13.0


def test_a_share_no_window_can_give_is_not_said_of_the_window():
    """A share is a part of a whole. Where two readings give more of the part than of the whole (two lives of the
    engine that look like one, or a reading taken between its two counts), that is no share of the window: 200 % of
    drafts accepted was said. The share since the engine started stands then, as it does for a counter that fell."""
    assert window_ratio({"hits": 110.0, "asked": 110.0}, {"hits": 90.0, "asked": 100.0}, "hits", "asked") == 1.0
    assert window_ratio({"hits": 60.0, "asked": 120.0}, {"hits": 50.0, "asked": 100.0}, "hits", "asked") == 0.5
    assert window_ratio({"hits": 20.0, "asked": 40.0}, {"hits": 30.0, "asked": 30.0}, "hits", "asked") == 0.5  # fell


def test_a_latency_without_a_reading_to_count_from_is_not_called_recent():
    """A histogram the older reading did not hold yet has no window: what it gives is everything since the engine
    started, and the page must not write "5 min" under it."""
    name = "time_to_first_token_seconds"
    hist, old = {name: {"1": 10.0, "2": 20.0, "+Inf": 20.0}}, {name: {"1": 10.0, "2": 10.0, "+Inf": 10.0}}
    assert recent_quantile(hist, old, name, 0.5) == (1.5, True)  # the ten requests since the older reading
    assert recent_quantile(hist, hist, name, 0.5) == (1.0, False)  # nothing new in between: since it started
    assert recent_quantile(hist, {}, name, 0.5) == (1.0, False)  # was (1.0, True)
    assert recent_quantile({}, old, name, 0.5) == (None, False)
    row = latency_table(hist, {})[0]
    assert (row["p50"], row["recent"]) == (1.0, False), row  # the same in the table of the deep view


def test_the_speed_of_reading_prompts_needs_both_counters_in_both_readings():
    """How fast the engine reads prompts is tokens computed over seconds of prefill, both between two readings. A
    counter one of the readings does not hold gives no speed: taken as 0, the tokens of a whole life stood against
    the second the window counted."""

    def speed(new, older):
        return engine_work(new, new, older, {}, {}, None, 0)["prefill_tok_s"]

    read = {"request_prefill_kv_computed_tokens_sum": 8000.0, "request_prefill_time_seconds_sum": 100.0}
    base = {"request_prefill_kv_computed_tokens_sum": 7110.0, "request_prefill_time_seconds_sum": 90.0}
    assert speed(read, base) == 89.0  # 890 tokens in 10 s of reading
    assert speed(read, read) is None  # nothing read in between
    assert speed(read, {"request_prefill_time_seconds_sum": 99.0}) is None  # was 8000.0
    assert speed(read, {"request_prefill_kv_computed_tokens_sum": 7110.0}) is None  # was 8.9: 890 tokens over 100 s
    assert speed({"request_prefill_time_seconds_sum": 100.0}, base) is None


def test_steps_of_one_token_are_counted_up_to_the_bound_of_one_token():
    """The share of steps that wrote one token only is read off the histogram of tokens per step: every step up to
    the bound of one token, over all steps between two readings. The first bound alone is too few where the
    histogram has a finer one before it. And without an older reading to count from there is no window: no share,
    not the one since the engine started under the name of the window."""

    def share(steps, old_hist):
        return engine_work({}, {}, {}, {"iteration_tokens_total": steps}, old_hist, None, 0)["one_token_share"]

    def before(steps):
        return {"iteration_tokens_total": dict.fromkeys(steps, 0.0)}

    fine, plain = {"0.5": 10.0, "1": 40.0, "8": 100.0, "+Inf": 100.0}, {"1": 24.0, "8": 99.0, "+Inf": 100.0}
    assert share(plain, before(plain)) == 0.24
    assert share(fine, before(fine)) == 0.4  # was 0.1: the steps up to half a token alone
    assert share(fine, {"iteration_tokens_total": fine}) is None  # no step in between
    assert share(fine, {}) is None  # was 0.1
    coarse = {"8": 100.0, "+Inf": 100.0}
    assert share(coarse, before(coarse)) is None  # no bound at one token: the histogram cannot say
    below = {"0.5": 10.0, "8": 100.0, "+Inf": 100.0}
    assert share(below, before(below)) is None  # nor can one whose bounds pass one token by; was 0.1, the empty steps


def test_requests_nobody_counted_are_not_zero_requests_done():
    """How many requests an engine has finished is the sum of the counters it sends for that, one per way a request
    can end. An engine that sends none of them has not finished 0 requests: the number is not known."""
    busy = {"num_requests_running": 1.0, "generation_tokens_total": 100.0}
    assert pace([(100.0, busy, {})])["finished"] is None  # was 0
    assert engine_work(busy, busy, busy, {}, {}, None, 0)["finished"] is None  # was 0
    done = {**busy, "request_success_total:stop": 7.0, "request_success_total:length": 2.0}
    assert pace([(100.0, done, {})])["finished"] == 9.0
    assert engine_work(done, done, done, {}, {}, None, 0)["finished"] == 9.0
    assert pace([(100.0, {**busy, "request_success_total:stop": 0.0}, {})])["finished"] == 0.0  # counted: none yet


def test_a_reading_without_the_token_count_is_not_a_restart():
    """Without a start time, a restart is told by the tokens an engine has written: fewer than before. A reading that
    does not hold that counter says nothing about it. Taken as 0 tokens, it passed for a restart and began the window
    of the engine anew."""
    assert restarted({"generation_tokens_total": 30.0}, {"generation_tokens_total": 900.0}) is True
    assert restarted({"generation_tokens_total": 900.0}, {"generation_tokens_total": 900.0}) is False
    assert restarted({}, {"generation_tokens_total": 900.0}) is False  # was True
    assert restarted({"generation_tokens_total": 30.0}, {}) is False
    born = {"process_start_time_seconds": 2.0}  # where both name their start, that alone tells
    assert restarted(born, {"process_start_time_seconds": 1.0, "generation_tokens_total": 900.0}) is True
    assert restarted({**born, "generation_tokens_total": 5.0}, {**born, "generation_tokens_total": 900.0}) is False


def test_requests_nobody_counted_are_neither_zero_requests_nor_an_idle_engine():
    """How many requests an engine works on and how many wait are two counts it sends. An engine that sends neither
    is not idle with 0 running and 0 waiting: its queue is not known, and neither is what it does, unless the tokens
    it writes say so. Idle is said of two counts that were both read as zero."""
    quiet = {"generation_tokens_total": 100.0}
    own = pace([(100.0, quiet, {}), (108.0, quiet, {})])
    assert (own["running"], own["waiting"], own["state"]) == (None, None, None), own  # was 0.0, 0.0, "idle"
    speed = engine_speed(quiet, quiet, 108.0, 100.0)
    assert (speed["running"], speed["waiting"], speed["state"]) == (None, None, None), speed
    # tokens that are written are a reading of their own: it writes, with a queue nobody counted
    wrote = pace([(100.0, quiet, {}), (108.0, {"generation_tokens_total": 500.0}, {})])
    assert (wrote["tok_s"], wrote["state"], wrote["running"]) == (50.0, "writing", None), wrote
    # one of the two counts: requests it names are requests, a zero says nothing of the count that is missing
    assert pace([(100.0, {"num_requests_waiting": 2.0}, {})])["state"] == "reading"
    assert pace([(100.0, {"num_requests_running": 0.0}, {})])["state"] is None  # was "idle"
    rests = {"num_requests_running": 0.0, "num_requests_waiting": 0.0}
    assert pace([(100.0, rests, {})])["state"] == "idle"  # both read, both zero
    assert pace([(100.0, {"engine_sleep_state:awake": 0.0}, {})])["state"] == "asleep"  # it says so itself


def test_a_number_nobody_can_count_with_is_none():
    """num gives a finite number back and None for everything else: what is no number, not a number, a number
    without end, and a whole number too large for a float, which nothing can be multiplied with. It never fails:
    it stands between ringtop and what a command outside wrote."""
    assert [num(value) for value in (3, 2.5, 0, -1.0, 10**300)] == [3, 2.5, 0, -1.0, 10**300]
    for value in (None, "12", [1], float("nan"), float("inf"), -float("inf"), 10**400, -(10**400)):
        assert num(value) is None, repr(value)[:40]
