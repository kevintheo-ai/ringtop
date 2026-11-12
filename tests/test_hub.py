"""The state the page shows: events, runs that start and end, a node that goes away, the history in memory."""

import json
import time

from tests.fixtures import counters, demo_round, hub_for


def test_node_down_stops_flows_and_says_why():
    """A Spark nobody reaches says nothing about its ring ports: what they carry, whether the link is up, how fast
    it runs and whether it counts errors are not known. They stood as 0 Gb/s, down, without errors and at the rate
    of the last look: a cut SSH line read like a cable pulled out of the ring."""
    hub = hub_for()
    base = time.time()
    hub.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": counters(0, err=1)}})
    hub.ingest("dgx0", {"t": base + 2, "fabric": {"rocep1s0f0": counters(10**9, err=3)}})
    edge = hub.edges_view()[0]
    assert edge["gbps"] > 0 and (edge["up"], edge["errors"], edge["capacity"]) == (True, True, 200.0), edge
    hub.node_down("dgx0", "ssh: timed out")
    assert hub.nodes["dgx0"]["live"] is False and hub.nodes["dgx0"]["reason"] == "ssh: timed out"
    edge = hub.edges_view()[0]
    read = (edge["gbps"], edge["rx"], edge["up"], edge["errors"], edge["capacity"])
    assert read == (None, None, None, None, None), edge  # was 0.0, 0.0, False, True, 200.0
    said = [e["text"] for e in hub.events]
    assert said == ["Errors on link f0", "Unreachable: ssh: timed out"], said  # no link is said to have gone down
    json.loads(json.dumps(hub.view(), allow_nan=False))
    hub.ingest("dgx0", {"t": base + 60, "fabric": {"rocep1s0f0": counters(2 * 10**9, err=3)}})
    back = hub.edges_view()[0]
    assert (back["gbps"], back["up"], back["capacity"]) == (None, True, 200.0), back  # read again: no rate yet


def test_a_spark_that_is_away_keeps_no_reading_of_its_last_sample():
    """A Spark nobody reaches kept every figure of its last sample: power, heat, memory, what runs on its GPU, its
    cables and counters in the deep view. Only "live" said that they were old, and not every reader asks (the page
    added its watts to the power of the cluster). Now it holds what it is (its place in the ring, the sizes of the
    machine, how its container started) and why it is away, and not one reading. When it is back, every figure is
    of its new samples."""
    seen, held = [], []

    def look(hub):
        seen.append(dict(hub.nodes["dgx3"]))
        deep = next(row for row in hub.nerd_view(0, True)["nodes"] if row["name"] == "dgx3")
        held.append(("dgx3" in hub.cables, "dgx3" in hub.link_counts, "dgx3" in hub.env, deep))

    demo_round(15, at=150.0, each=look)  # the last Spark of the demo is away from second 160 to 174
    live, away, back = seen[4], seen[5], seen[13]
    assert live["live"] and live["w"] and live["apps"] and live["zones"] and live["firmware"] and live["cores"], live
    assert held[4][:3] == (True, True, True) and held[4][3]["threads"], held[4]
    is_what = {"name", "rank", "head", "peers", "mem_total_gb", "mhz_max", "disk_total_gb", "capacity", "startup"}
    assert {key for key, value in away.items() if value is not None} == is_what | {"live", "reason", "since"}, away
    assert all(away[key] == live[key] for key in is_what) and away["live"] is False, away
    assert set(live) <= set(away)  # the page finds every field it knows, empty
    assert held[5][:3] == (False, False, False), held[5]
    row = held[5][3]
    unread = {key for key, value in row.items() if value is None}
    assert unread == {"cores", "threads", "box", "links", "mem_free_gb", "psi", "key_threads"}, row
    assert row["link_counts"] == {} and row["capacity"] == live["capacity"], row
    # back: live again with the figures of its new sample, and nothing of the slow readings from before
    assert back["live"] and back["w"] and back["zones"] and back["cores"], back
    assert (back["apps"], back["psi"], back["firmware"], back["box"]) == (None, None, None, None), back


def test_a_spark_that_stays_connected_and_sends_nothing_is_not_shown_as_live():
    """A sampler that hangs while SSH still answers sends no line and no end: after the silence that makes the ring
    engine "offline", its Spark is shown as away, with the reason, once. Its next sample makes it live again."""
    hub, start, real = hub_for(), time.time(), time.time
    quiet = {"gpu": {"w": 40.0}, "fabric": {}}
    try:
        time.time = lambda: start
        hub.ingest("dgx0", {"t": start, **quiet})
        hub.ingest("dgx1", {"t": start, **quiet})
        time.time = lambda: start + 10
        hub.ingest("dgx1", {"t": start + 10, **quiet})
        shown = {n["name"]: n for n in hub.view()["nodes"]}
        assert shown["dgx0"]["live"] and shown["dgx1"]["live"]  # 10 s without a line is a slow sample, no more
        time.time = lambda: start + 16
        hub.view()
        shown = {n["name"]: n for n in hub.view()["nodes"]}
        assert shown["dgx0"]["live"] is False and shown["dgx0"]["reason"] == "No sample for 15 s", shown["dgx0"]
        assert shown["dgx0"]["since"] == start + 16 and shown["dgx1"]["live"]  # heard 6 s ago
        assert [e["text"] for e in hub.events] == ["Unreachable: No sample for 15 s"]  # said once
        hub.ingest("dgx0", {"t": start + 17, **quiet})
        assert hub.nodes["dgx0"]["live"] and hub.events[-1]["text"] == "Reachable again"
    finally:
        time.time = real


def test_after_a_spark_was_away_no_rate_is_counted_across_the_gap():
    """A Spark that went away forgets every counter a rate is counted from, not only those of its ring ports: the
    mean over ten minutes of absence must not stand as the load of the moment it is back."""
    hub, t = hub_for(), time.time()

    def sample(at, sectors, micros):
        counted = {"disk": {"read": sectors, "write": sectors}, "gpu": {"cap_us": micros}, "psi": {"cpu_some": micros}}
        return {"t": at, "fabric": {}, **counted}

    def rates():
        node = hub.nodes["dgx0"]
        return node["disk_read"], node["cap_pct"], node["psi_cpu"]

    hub.ingest("dgx0", sample(t, 0, 0))
    hub.ingest("dgx0", sample(t + 2, 400_000, 1_000_000))
    assert rates() == (102.4, 50.0, 50.0)
    hub.latch_runs["dgx0"] = 3  # a clock seen low three samples in a row
    hub.node_down("dgx0", "ssh: timed out")
    assert hub.latch_runs.get("dgx0", 0) == 0  # "in a row" does not reach across an absence
    hub.ingest("dgx0", sample(t + 602, 800_000, 2_000_000))  # back after ten minutes
    assert rates() == (None, None, None), rates()
    hub.ingest("dgx0", sample(t + 604, 1_200_000, 3_000_000))
    assert rates() == (102.4, 50.0, 50.0)


def test_events_tell_what_happened_once():
    hub = hub_for()
    now = time.time()
    hub.ingest("dgx0", {"t": now, "fabric": {}})
    assert not hub.events  # coming up for the first time is not news
    hub.node_down("dgx0", "ssh: timed out")
    hub.node_down("dgx0", "ssh: timed out")
    assert [e["text"] for e in hub.events] == ["Unreachable: ssh: timed out"]
    hub.ingest("dgx0", {"t": now, "fabric": {}})
    assert hub.events[-1]["text"] == "Reachable again"
    throttled = {"t": now, "fabric": {}, "gpu": {"events": "0x40"}}
    hub.ingest("dgx0", throttled)
    hub.ingest("dgx0", throttled)
    assert [e["text"] for e in hub.events].count("Slowing down: thermal") == 1
    line = {"t": 5.0, "kind": "memguard", "text": "low headroom"}
    hub.ingest("dgx0", {"t": now, "fabric": {}, "slow": {"journal": [line], "psi": 0.0, "apps": [], "top": []}})
    hub.ingest("dgx0", {"t": now, "fabric": {}, "slow": {"journal": [line], "psi": 0.0, "apps": [], "top": []}})
    assert [e["text"] for e in hub.events].count("low headroom") == 1 and hub.events[-1]["level"] == "warn"


def test_run_start_and_end_are_events():
    """A run a source names has started. It has finished once the source has named no run for half a minute (it
    may say so for a moment only, tests/test_hub_runs.py), and at once when it names another run or the same job
    with another start."""
    hub, start, real = hub_for(), time.time(), time.time
    try:
        time.time = lambda: start
        hub.note_changes({"state": "writing"}, {"source": "command", "name": "Job 1"})
        hub.note_changes({"state": "writing"}, {"source": "none"})
        assert [e["text"] for e in hub.events] == ["Started: Job 1"]  # was finished with the first such word
        time.time = lambda: start + 30
        hub.note_changes({"state": "writing"}, {"source": "none"})
        assert [e["text"] for e in hub.events] == ["Started: Job 1", "Finished: Job 1"]
        hub.note_changes({"state": "offline"}, {"source": "none"})
        assert hub.events[-1]["text"] == "Stopped serving"
        hub.note_changes({"state": "writing"}, {"source": "command", "name": "Job 1", "started": 100.0})
        hub.note_changes({"state": "writing"}, {"source": "command", "name": "Job 1", "started": 100.0})
        time.time = lambda: start + 32
        hub.note_changes({"state": "writing"}, {"source": "command", "name": "Job 1", "started": 900.0})
        assert [e["text"] for e in hub.events].count("Started: Job 1") == 3
    finally:
        time.time = real


def test_replies_stay_out_of_the_two_second_stream():
    hub = hub_for()
    hub.external_run = {"name": "job", "replies": [{"reply": "secret"}]}
    assert "secret" not in json.dumps(hub.view()) and hub.replies()[0]["reply"] == "secret"


def test_a_run_notes_how_the_sparks_were_cooled_when_it_started_and_ended():
    """Two runs only compare if they ran equally warm: the events keep fans, warmest sensor and GPU clock at both ends."""
    hub = hub_for()
    for i, name in enumerate(("dgx0", "dgx1")):
        hub.ingest(
            name,
            {
                "t": time.time(),
                "fabric": {},
                "gpu": {"w": 30.0, "c": 60.0 + i, "mhz": 2184.0 + 6 * i, "util": 96.0},
                "sensors": {"fans": [2600 + 100 * i, 2700 + 100 * i]},
                "zones": {"TSOC": 76.0 + 2 * i, "TGPU": 70.0},
            },
        )
    start, real = time.time(), time.time
    hub.note_changes({"state": "writing"}, {"source": "command", "name": "Long prompts", "started": start})
    try:
        hub.note_changes({"state": "idle"}, {"source": "none"})
        time.time = lambda: start + 31  # no run named for half a minute: the run has ended, when that was first said
        hub.note_changes({"state": "idle"}, {"source": "none"})
    finally:
        time.time = real
    assert [e["text"] for e in hub.events if e["kind"] == "run"] == ["Started: Long prompts", "Finished: Long prompts"]
    # every single fan counts (an average would hide one that stands still), and the warmest sensor says whose it is
    measured = "fans 2,600 to 2,800 RPM, warmest sensor 78 °C on dgx1, GPU clock 2.18 to 2.19 GHz"
    assert [e["text"] for e in hub.events if e["kind"] == "cooling"] == [
        f"At the start: {measured}",
        f"At the end: {measured}",
    ]
    bare = hub_for()
    bare.note_changes({"state": "writing"}, {"source": "command", "name": "x", "started": time.time()})
    assert [e["text"] for e in bare.events] == ["Started: x"]  # nothing measured, nothing claimed


def test_a_page_that_opens_gets_no_point_older_than_the_half_hour_it_draws():
    """The traces in memory are bounded by how many points they hold, not by how old these are: one that is written
    every 15 s reaches hours back. A page that opened got all of it as its last half hour: old points stretched the
    scales, and the cooling view drew every one of them."""
    hub, now = hub_for(), time.time()
    for k in range(400, -1, -1):  # a slow trace: a point every 15 s for 100 minutes, the newest 7 s old
        hub.history["dgx0.energy_w"].append((now - 15 * k - 7, 40.0 + k))
    hub.history["dgx0.gone"].append((now - 4000, 1.0))  # and one that has had no point for more than an hour
    sent = hub.with_history()["history"]
    times, values = sent["dgx0.energy_w"]
    assert min(times) >= now - 1800 and max(times) >= now - 8, (now - min(times), now - max(times))  # was 6007 s back
    assert len(times) == 120 and max(values) == 159.0, (len(times), max(values))  # every point of the half hour
    assert "dgx0.gone" not in sent, sent.keys()


def test_memory_history_keeps_every_node_when_thinned():
    hub = hub_for()
    start = time.time() - 1000
    for i in range(200):
        hub.history["a"].append((start + i * 2, 1.0))
        hub.history["b"].append((start + i * 2 + 1, 2.0))
    answer = hub.history_range(["a", "b"], start, start + 400, 20)
    assert all(v is not None for v in answer["series"]["a"]) and all(v is not None for v in answer["series"]["b"])


def test_memory_history_gives_mean_lowest_highest_and_count_to_who_asks_for_a_band():
    """Without a store (the demo) a column of the past is counted from the samples in memory, like one from disk."""
    hub = hub_for()
    start = time.time() - 1000
    for i, value in enumerate((10.0, 20.0, 60.0, 30.0)):
        hub.history["a"].append((start + i * 2, value))
    band = hub.history_range(["a", "b"], start, start + 40, 10, band=True)  # columns of 4 s: two samples each
    assert band["tier"] == "memory" and band["width"] == 4.0 and len(band["t"]) == 2, band
    assert band["series"]["a"] == [15.0, 45.0] and band["n"]["a"] == [2, 2], band
    assert band["low"]["a"] == [10.0, 30.0] and band["peak"]["a"] == [20.0, 60.0], band
    assert band["series"]["b"] == [None, None] and band["low"]["b"] == [None, None] and band["n"]["b"] == [0, 0], band
    plain = hub.history_range(["a"], start, start + 40, 10)  # as before: the last sample of a column, no more
    assert plain["series"]["a"] == [20.0, 30.0] and plain["peak"] == {} and "low" not in plain and "n" not in plain
    assert plain["width"] == 4.0


def test_memory_history_puts_a_sample_at_the_very_end_of_a_stretch_into_its_last_column():
    """Without a store a stretch is cut into `points` columns from its beginning. A sample exactly at its end fell
    into a column of its own behind the last one, and that column said a time after the end of the stretch: samples
    at 10, 50 and 100 s of a stretch of 100 s in ten columns stood at 15, 55 and 105 s. It belongs to the last
    column, with every other sample of the last tenth."""
    hub = hub_for()
    start = time.time() - 1000
    for seconds, value in ((10, 1.0), (50, 2.0), (95, 3.0), (100, 5.0)):
        hub.history["a"].append((start + seconds, value))
    band = hub.history_range(["a"], start, start + 100, 10, band=True)
    assert [round(t - start) for t in band["t"]] == [15, 55, 95], [t - start for t in band["t"]]
    assert (
        band["n"]["a"] == [1, 1, 2] and band["series"]["a"] == [1.0, 2.0, 4.0] and band["peak"]["a"] == [1.0, 2.0, 5.0]
    )
    plain = hub.history_range(["a"], start, start + 100, 10)
    assert plain["t"] == band["t"] and plain["series"]["a"] == [1.0, 2.0, 5.0], plain  # the last sample of a column


def test_a_trace_asked_for_twice_is_counted_once():
    """A request may name one trace twice. Without a store its samples then stood twice in every column: the count
    doubled, and a figure that weighs columns by their count weighed this trace twice."""
    hub = hub_for()
    start = time.time() - 1000
    for i, value in enumerate((10.0, 20.0, 60.0, 30.0)):
        hub.history["a"].append((start + i * 2, value))
    once = hub.history_range(["a"], start, start + 40, 10, band=True)
    twice = hub.history_range(["a", "b", "a"], start, start + 40, 10, band=True)
    assert twice["n"]["a"] == once["n"]["a"] == [2, 2], twice["n"]
    assert twice["series"]["a"] == once["series"]["a"] == [15.0, 45.0], twice["series"]
    assert list(twice["series"]) == ["a", "b"], list(twice["series"])  # in the order asked, each once
