"""What the page gets about the ring engine and the run: states, speed, timing, who runs."""

import time

from tests.fixtures import engine_sample, hub_for


def test_engine_states_and_speed():
    hub = hub_for()
    now = time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 1000.0)["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 2000.0)["engine"], {}))
    view = hub.engine_view()
    assert view["state"] == "writing" and view["tok_s"] == 100.0
    assert view["steps_s"] == round(100 / 3, 1) and view["tokens_per_step"] == 3.0
    hub.scrapes.append((now + 1, engine_sample(0, 2000.0, running=0.0)["engine"], {}))
    assert hub.engine_view()["state"] == "idle"


def test_power_nobody_read_is_not_zero_watts():
    """The watts of the ring are the sum over its Sparks. With no Spark that read its power, there is no sum: the
    page must not say 0 W (the curve never did)."""
    hub, now = hub_for(), time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 1000.0)["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 2000.0)["engine"], {}))
    assert hub.engine_view()["watts"] is None
    hub.nodes["dgx0"].update(live=True, w=41.6)
    assert hub.engine_view()["watts"] == 42


def test_the_power_of_the_ring_says_how_many_sparks_it_is_the_sum_of():
    """The watts of the ring are the GPU power of its Sparks added up. With a Spark away, or one that did not read
    its power, the sum of the others stood as the power of the ring: energy per token was counted from it, and both
    were kept as curves. A part is given as a part (with how many Sparks it is of), and no energy per token and no
    point of a curve is made of it."""
    hub, now = hub_for(), time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 1000.0)["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 2000.0)["engine"], {}))
    for node in hub.nodes.values():
        node.update(live=True, w=40.0)
    view = hub.engine_view()
    assert (view["watts"], view["watts_from"], view["j_per_token"]) == (160, 4, 1.6), view
    assert hub.history["engine.watts"][-1] == (now, 160.0) and hub.history["engine.j_per_token"][-1] == (now, 1.6)
    hub.nodes["dgx1"]["w"] = None  # one Spark answers and did not read its power
    hub.nodes["dgx3"]["live"] = False  # and one is away
    hub.scrapes.append((now + 2, engine_sample(0, 2200.0)["engine"], {}))
    part = hub.engine_view()
    assert (part["watts"], part["watts_from"], part["j_per_token"]) == (80, 2, None), part  # was 0.8 J per token
    assert len(hub.history["engine.watts"]) == 1 and len(hub.history["engine.j_per_token"]) == 1, hub.history


def test_running_without_tokens_means_reading():
    hub = hub_for()
    now = time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 5.0)["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 5.0)["engine"], {}))
    assert hub.engine_view()["state"] == "reading"


def test_engine_offline_says_why():
    hub = hub_for()
    hub.ingest("dgx0", {"t": time.time(), "engine": None, "engine_error": "Nothing answers on the vLLM port."})
    view = hub.engine_view()
    assert view["state"] == "offline" and "vLLM" in view["error"]


def test_run_priority_external_then_lab_then_process_then_engine():
    hub = hub_for()
    assert hub.run_view({"state": "idle"}) == {"source": "none"}
    assert hub.run_view({"state": "writing", "busy_since": 5})["source"] == "engine"
    hub.info = {"processes": [{"seconds": 30, "command": "bin/spark bench"}]}
    assert hub.run_view({"state": "writing"})["source"] == "process"
    hub.info = {
        "lab": {
            "hold": {"holder": "spark-lab: test", "current": "step 2", "expected_end": None},
            "queue": {"done": ["a.json"], "running": ["b.json"], "pending": ["c.json"], "failed": []},
        },
        "processes": hub.info["processes"],
    }
    run = hub.run_view({"state": "writing"})
    assert run["source"] == "lab" and run["name"] == "step 2"
    assert [s["state"] for s in run["steps"]] == ["done", "running", "pending"]
    hub.external_run = {"name": "Job 7", "done": 3, "total": 9}
    assert hub.run_view({"state": "writing"})["name"] == "Job 7"
    hub.external_error = "boom"
    assert hub.run_view({"state": "writing"})["source"] == "error"


def test_what_the_head_told_does_not_stand_once_the_head_is_away_or_silent():
    """The head tells every 10 s which container runs, what the lab queue holds and which benchmark runs. Its last
    word stood for good: with the head away the page went on saying "Benchmark running" and "running" of the
    container. And the start of that benchmark was counted from the moment of each look instead of the moment the
    head read it, so it moved on with every look at the same word."""
    hub, start, real = hub_for(), time.time(), time.time
    bench = [{"seconds": 50, "command": "bin/spark bench"}]
    facts = {"container": {"status": "running", "image": "x"}, "processes": bench, "kernel": "k", "page_size": 65536}

    def look():
        view = hub.view()
        return view["run"].get("source"), view["run"].get("started"), view["identity"]["container"]

    try:
        time.time = lambda: start
        hub.ingest("dgx0", {"t": start, "info": facts})
        assert look() == ("process", start - 50, "running"), look()
        time.time = lambda: start + 8  # the same word of the head, looked at 8 s later
        assert look() == ("process", start - 50, "running"), look()  # the start was start - 42
        time.time = lambda: start + 41  # its samples keep coming, its facts do not: more than four of their readings
        hub.ingest("dgx0", {"t": start + 41})
        assert look() == ("none", None, None), look()  # was a benchmark that runs, in a container that runs
        assert hub.view()["identity"]["kernel"] is None
        time.time = lambda: start + 50
        hub.ingest("dgx0", {"t": start + 50, "info": facts, "conn": [{"port": "37254"}]})
        assert look() == ("process", start, "running") and hub.connections, look()
        hub.node_down("dgx1", "ssh: timed out")  # a worker that goes away takes nothing of the head's with it
        assert look() == ("process", start, "running") and hub.connections, look()
        hub.node_down("dgx0", "ssh: timed out")
        assert look() == ("none", None, None) and hub.connections is None, (look(), hub.connections)
    finally:
        time.time = real


def test_mean_time_per_request_uses_the_window():
    hub = hub_for()
    now = time.time()
    old = engine_sample(0, 1000.0, request_queue_time_seconds_sum=1.0, request_queue_time_seconds_count=1.0)["engine"]
    new = engine_sample(0, 2000.0, request_queue_time_seconds_sum=7.0, request_queue_time_seconds_count=4.0)["engine"]
    hub.scrapes.append((now - 10, old, {}))
    hub.scrapes.append((now, new, {}))
    assert hub.engine_view()["timing"]["queue"] == 2.0


def test_the_ring_view_gets_draft_survival_by_position():
    """The rings on the beam are drawn from this: one share per draft position, nothing when the engine does not speculate."""

    def drafts(made, kept):
        return {
            "spec_decode_num_drafts_total": made,
            "spec_decode_num_draft_tokens_per_pos_total:0": made,
            "spec_decode_num_accepted_tokens_per_pos_total:0": kept,
            "spec_decode_num_draft_tokens_per_pos_total:1": made * 0.5,
            "spec_decode_num_accepted_tokens_per_pos_total:1": kept * 0.25,
        }

    hub, now = hub_for(), time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 1000.0, **drafts(100.0, 60.0))["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 2000.0, **drafts(300.0, 220.0))["engine"], {}))
    view = hub.engine_view()
    assert view["spec"] == [0.8, 0.4] and view["spec_length"] == 2.0
    plain = hub_for()
    plain.scrapes.append((now - 10, engine_sample(0, 1000.0)["engine"], {}))
    plain.scrapes.append((now, engine_sample(0, 2000.0)["engine"], {}))
    assert plain.engine_view()["spec"] == [] and plain.engine_view()["spec_length"] is None


def test_the_shares_of_accepted_drafts_and_cached_prompts_are_of_the_last_seconds():
    """Drafts accepted and prompt tokens from the cache are shares of the rate window (8 s), not of the five minutes
    the latencies look back over: a share that just changed shows at once."""
    hub = hub_for()
    now = time.time()

    def reading(drafted, accepted, queries, hits, generated):
        return {
            "generation_tokens_total": generated,
            "num_requests_running": 1.0,
            "spec_decode_num_draft_tokens_total": drafted,
            "spec_decode_num_accepted_tokens_total": accepted,
            "prefix_cache_queries_total": queries,
            "prefix_cache_hits_total": hits,
        }

    hub.scrapes.append((now - 200, reading(0.0, 0.0, 0.0, 0.0, 0.0), {}))
    hub.scrapes.append(
        (now - 8, reading(1000.0, 900.0, 1000.0, 100.0, 5000.0), {})
    )  # so far 90 % accepted, 10 % cached
    hub.scrapes.append((now, reading(1100.0, 920.0, 1100.0, 180.0, 5400.0), {}))  # the last 8 s: 20 % and 80 %
    view = hub.engine_view()
    assert (view["accepted"], view["prefix"]) == (0.2, 0.8), view
    assert view["tok_s"] == 50.0  # and the speed is of the same window


def test_since_when_the_engine_works_is_not_carried_across_a_spell_nobody_read_it():
    """The engine worked, then nobody could read it for more than ten minutes, then it works again: "serving since"
    is the first reading after the hole, not a moment from before it. A hole of up to half a minute ends nothing,
    like an idle spell that short."""

    def after_a_hole(seconds):
        hub, now = hub_for(), time.time()
        hub.scrapes.append((now - seconds - 10, engine_sample(0, 1000.0)["engine"], {}))
        hub.scrapes.append((now - seconds, engine_sample(0, 2000.0)["engine"], {}))
        hub.busy_since, hub.idle_since = now - seconds - 10, None  # as the last look before the hole left them
        hub.scrapes.append((now, engine_sample(0, 9000.0)["engine"], {}))
        first, again = hub.engine_view()["busy_since"], hub.engine_view()["busy_since"]
        assert first == again  # asked twice for one reading: one answer
        return first - now

    assert after_a_hole(690) == 0
    assert after_a_hole(20) == -30  # the same work goes on
    # the same with an engine that rests: half a minute of grace is not used up by a hole
    hub, now = hub_for(), time.time()
    hub.scrapes.append((now - 700, engine_sample(0, 1000.0, running=0.0)["engine"], {}))
    hub.busy_since, hub.idle_since = now - 900, now - 700
    hub.scrapes.append((now, engine_sample(0, 1000.0, running=0.0)["engine"], {}))
    hub.engine_view()
    assert hub.busy_since is None and hub.idle_since == now


def test_a_spell_nobody_read_the_engine_counts_though_two_readings_came_after_it_before_the_next_look():
    """Since when the engine works starts anew after a spell nobody read it. The spell was looked for between the
    newest two readings only. The page is handed a look every interval and the readings come every interval, and
    their beat wanders: now and then two readings come between two looks. Then the hole lay one reading further
    back, and "serving since" stayed a moment from before it."""
    hub, start, real = hub_for(), time.time(), time.time
    try:
        time.time = lambda: start
        hub.scrapes.append((start - 2, engine_sample(0, 1000.0)["engine"], {}))
        hub.scrapes.append((start, engine_sample(0, 2000.0)["engine"], {}))
        assert hub.engine_view()["busy_since"] == start
        time.time = lambda: start + 42  # nobody read the engine for 40 s; then two readings, then the look
        hub.scrapes.append((start + 40, engine_sample(0, 9000.0)["engine"], {}))
        hub.scrapes.append((start + 42, engine_sample(0, 9500.0)["engine"], {}))
        first, again = hub.engine_view()["busy_since"], hub.engine_view()["busy_since"]
        assert first == again == start + 42, (first - start, again - start)  # was 0: the moment before the hole
        time.time = lambda: start + 46  # readings that follow one another end nothing
        hub.scrapes.append((start + 44, engine_sample(0, 9800.0)["engine"], {}))
        hub.scrapes.append((start + 46, engine_sample(0, 9900.0)["engine"], {}))
        assert hub.engine_view()["busy_since"] == start + 42
    finally:
        time.time = real


def test_after_a_restart_no_figure_of_the_ring_engine_mixes_two_lives():
    """The ring engine restarts inside the five minutes its latencies look back over. Every figure of the page is
    then of the new life alone: no speed from the counters of both, no mean over the requests of both, no "working
    since" from before the restart. Its start time tells the two lives apart, also where the new one has already
    counted past the old; an engine that names no start time is told by the counter that fell."""
    hub, start, real = hub_for(), time.time(), time.time
    slow, fast = {"1": 10.0, "5": 10.0, "+Inf": 10.0}, {"1": 12.0, "5": 40.0, "+Inf": 40.0}

    def read(seconds, generated, born, done, waited, first_token):
        time.time = lambda: start + seconds
        life = {"process_start_time_seconds": born} if born else {}
        waits = {"request_queue_time_seconds_count": done, "request_queue_time_seconds_sum": waited}
        sample = engine_sample(start + seconds, generated, **life, **waits)
        hub.ingest("dgx0", {**sample, "hist": {"time_to_first_token_seconds": first_token}})
        return hub.engine_view()

    try:
        read(0, 1000.0, 100.0, 1.0, 10.0, slow)
        read(10, 2000.0, 100.0, 2.0, 20.0, slow)
        old = read(20, 3000.0, 100.0, 3.0, 30.0, slow)
        assert (old["tok_s"], old["timing"]["queue"], old["busy_since"]) == (100.0, 10.0, start), old
        new = read(22, 5000.0, 900.0, 10.0, 50.0, fast)  # another start time, and more tokens than the old life had
        assert new["tok_s"] is None and new["state"] == "reading", new  # one reading of the new life: no speed yet
        assert new["timing"]["queue"] == 5.0, new["timing"]  # its 10 requests waited 50 s: not 40 s over 9 of both
        assert (new["ttft_p95"], new["ttft_recent"]) == (4.7143, False), new  # of its own 40 requests, since it began
        assert new["busy_since"] == start + 22, new["busy_since"]
        assert read(24, 5200.0, 900.0, 10.0, 50.0, fast)["tok_s"] == 100.0  # the two readings of the new life
        fell = read(26, 30.0, None, 1.0, 2.0, fast)  # no start time: the tokens it counted fell
        assert fell["tok_s"] is None and fell["busy_since"] == start + 26, fell
    finally:
        time.time = real


def test_a_counter_the_engine_does_not_send_leaves_no_curve_of_zeros():
    """A rate that is not known is not kept: the curve of prompt tokens per second of an engine that never sent
    that counter has no points, where it had a 0 for every reading (kept for 90 days as if measured)."""
    hub, now = hub_for(), time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 1000.0)["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 2000.0)["engine"], {}))
    assert hub.engine_view()["tok_s"] == 100.0
    assert hub.history["engine.tok_s"][-1] == (now, 100.0) and not hub.history["engine.prompt_tok_s"], hub.history


def test_drafts_and_cached_prompts_nobody_counted_are_not_said_to_be_none():
    """An engine that sends how many tokens it drafted and looked up, but not how many it accepted or found in the
    cache: both shares are unknown. The page gets none, and the diagnosis does not say that 0 % of drafts survive."""
    hub, now = hub_for(), time.time()

    def reading(drafted, generated):
        return {
            "generation_tokens_total": generated,
            "num_requests_running": 1.0,
            "spec_decode_num_draft_tokens_total": drafted,
            "prefix_cache_queries_total": drafted,
        }

    hub.scrapes.append((now - 8, reading(1000.0, 5000.0), {}))
    hub.scrapes.append((now, reading(1100.0, 5400.0), {}))
    view = hub.view()
    assert view["engine"]["state"] == "writing" and view["engine"]["tok_s"] == 50.0
    assert (view["engine"]["accepted"], view["engine"]["prefix"]) == (None, None), view["engine"]
    assert not any("drafts survive" in point["text"] for point in view["why"]["points"]), view["why"]
    assert not hub.history["engine.accepted"] and not hub.history["engine.prefix"]  # and no curve of zeros


def test_requests_done_failed_and_pushed_out_are_none_without_their_counters():
    """Finished and failed requests and preemptions are counters of the engine. One it does not send is not known:
    the page gets none, not "0 done" and 0 failed."""
    hub, now = hub_for(), time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 1000.0)["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 2000.0)["engine"], {}))
    view = hub.engine_view()
    assert (view["finished"], view["errors"], view["preemptions"]) == (None, None, None), view
    counted = {"request_success_total:stop": 5.0, "request_success_total:error": 1.0, "num_preemptions_total": 0.0}
    hub.scrapes.append((now + 2, engine_sample(0, 2200.0, **counted)["engine"], {}))
    view = hub.engine_view()
    assert (view["finished"], view["errors"], view["preemptions"]) == (6.0, 1.0, 0.0), view


def test_a_reading_that_lacks_the_token_count_does_not_start_the_window_anew():
    """One reading of the ring engine without the counter of written tokens gives no speed for that moment, and no
    more: it is no restart. Since when the engine works stands, and the next reading counts its speed from the last
    one that held the counter."""
    hub, start, real = hub_for(), time.time(), time.time

    def read(seconds, counters):
        time.time = lambda: start + seconds
        hub.ingest("dgx0", {"t": start + seconds, "engine": counters, "hist": {}, "engine_error": None})
        return hub.engine_view()

    try:
        read(0, engine_sample(0, 1000.0)["engine"])
        assert read(10, engine_sample(0, 2000.0)["engine"])["tok_s"] == 100.0
        bare = read(20, {"num_requests_running": 1.0})
        assert bare["tok_s"] is None and bare["state"] == "reading" and bare["busy_since"] == start, bare
        again = read(22, engine_sample(0, 3200.0)["engine"])
        assert again["tok_s"] == 100.0 and again["busy_since"] == start, again  # 1200 tokens in the 12 s since
    finally:
        time.time = real


def test_a_ring_engine_that_sends_no_request_counts_is_not_called_idle():
    """The ring engine answers, without the two counts of its requests, and writes no tokens: nobody knows whether
    it rests. The page got "idle" with 0 running and 0 waiting, and both zeros were kept as curves. Now it gets an
    engine nobody can read, with the reason and the word that it does answer, and no curve of zeros."""
    hub, now = hub_for(), time.time()
    bare = {"generation_tokens_total": 1000.0, "kv_cache_usage_perc": 0.2}
    hub.scrapes.append((now - 10, bare, {}))
    hub.scrapes.append((now, bare, {}))
    hub.busy_since = now - 100  # as a look before left it
    view = hub.view()
    assert view["engine"] == {
        "state": "offline",
        "error": "The engine answers without its request counters.",
        "answers": True,
    }, view["engine"]
    assert not hub.history["engine.running"] and not hub.history["engine.waiting"], dict(hub.history)
    assert hub.busy_since is None and hub.idle_since is None  # since when it works or rests is not known either
    assert view["run"] == {"source": "none"}
    # tokens it writes are a reading of their own: it writes, and its queue stays unknown
    hub.scrapes.append((now + 8, {**bare, "generation_tokens_total": 1800.0}, {}))
    wrote = hub.engine_view()
    assert (wrote["state"], wrote["tok_s"], wrote["running"], wrote["waiting"]) == ("writing", 100.0, None, None), wrote
    assert not hub.history["engine.running"] and hub.history["engine.tok_s"][-1] == (now + 8, 100.0)
