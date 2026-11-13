"""Links and cables: rates from counters, errors that rise, a port that goes away."""

import json
import time

from tests.fixtures import counters, hub_for, ring_map


def test_link_rate_counts_four_byte_units_and_both_rails():
    hub = hub_for(ring_map(two_rails=True))
    base = time.time()
    hub.ingest(
        "dgx0",
        {"t": base, "fabric": {"rocep1s0f0": counters(0), "roceP2p1s0f0": counters(0), "rocep1s0f1": counters(0)}},
    )
    # 1 Gbit/s over 2 s = 62.5 M units of 4 bytes; one rail carries it, the other half of that
    hub.ingest(
        "dgx0",
        {
            "t": base + 2,
            "fabric": {
                "rocep1s0f0": counters(62_500_000),
                "roceP2p1s0f0": counters(31_250_000),
                "rocep1s0f1": counters(0),
            },
        },
    )
    edges = {(e["from"], e["to"]): e for e in hub.edges_view()}
    assert abs(edges[(0, 1)]["gbps"] - 1.5) < 1e-6
    assert edges[(0, 1)]["capacity"] == 200.0  # both functions of a port share one cable
    assert edges[(0, 3)]["gbps"] == 0
    assert hub.nodes["dgx0"]["net"] == 1.5


def test_counter_reset_is_not_a_spike():
    """A counter that fell back gives no traffic for that sample: not a spike, and not 0 Gb/s either (nobody knows
    what the cable carried while its counter was reset)."""
    hub = hub_for()
    base = time.time()
    hub.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": counters(10**12)}})
    hub.ingest("dgx0", {"t": base + 2, "fabric": {"rocep1s0f0": counters(5)}})
    assert {(e["from"], e["to"]): e["gbps"] for e in hub.edges_view()}[(0, 1)] is None


def test_the_traffic_of_a_cable_is_unknown_until_each_of_its_functions_was_read_twice():
    """A cable is its two PCIe functions, and its traffic the gain of both between two readings. A function whose
    counter fell back, or that is seen for the first time, has no gain: the cable then showed what its other function
    carried alone (16 instead of more), a cable seen for the first time showed 0.0 Gb/s, and both went into the
    curves as measured. Such a cable has no traffic for that sample, and neither has the Spark as a whole."""
    hub = hub_for(ring_map(two_rails=True))
    base, unit = time.time(), 62_500_000  # one unit over 2 s is 1 Gb/s: the counters count 4 bytes

    def edges():
        return {(e["from"], e["to"]): (e["gbps"], e["rx"]) for e in hub.edges_view()}

    hub.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": counters(0), "roceP2p1s0f0": counters(10 * unit)}})
    assert edges() == {(0, 1): (None, None)}, edges()  # the first look: nothing to count from yet, was (0.0, 0.0)
    second = {"rocep1s0f0": counters(16 * unit), "roceP2p1s0f0": counters(5)}  # the second function fell back
    hub.ingest(
        "dgx0", {"t": base + 2, "fabric": {**second, "rocep1s0f1": counters(7 * unit), "roceP2p1s0f1": counters(0)}}
    )
    assert edges() == {(0, 1): (None, 0.0), (0, 3): (None, None)}, edges()  # was 16.0, and 0.0 for the new cable
    assert hub.nodes["dgx0"]["net"] is None  # one cable unknown: no sum, was 16.0
    kept = {key: list(points) for key, points in hub.history.items() if points}
    assert set(kept) == {"dgx0.f0.rx"}, kept  # what was received on the first cable was read on both functions
    third = {
        "rocep1s0f0": counters(18 * unit),
        "roceP2p1s0f0": counters(5 + unit),
        "rocep1s0f1": counters(8 * unit),
        "roceP2p1s0f1": counters(unit // 2),
    }
    hub.ingest("dgx0", {"t": base + 4, "fabric": third})
    assert edges() == {(0, 1): (3.0, 0.0), (0, 3): (1.5, 0.0)}, edges()
    assert hub.nodes["dgx0"]["net"] == 4.5 and [v for _, v in hub.history["dgx0.f1.tx"]] == [1.5]
    bare = hub_for()  # a Spark that names no ring port has no traffic to add up: that is not 0 Gb/s
    bare.ingest("dgx0", {"t": base, "fabric": {}})
    bare.ingest("dgx0", {"t": base + 2, "fabric": {}})
    assert bare.nodes["dgx0"]["net"] is None and not bare.history["dgx0.net"], bare.nodes["dgx0"]["net"]


def test_a_line_rate_nobody_could_read_is_not_a_rate_of_zero():
    """How fast a link runs is read from a file of its port. Where that could not be read, the link was given a
    capacity of 0.0 Gb/s. It has none that anybody knows; one function of a cable that names it is enough."""
    base = time.time()
    blind = {"tx": 0, "rx": 0, "up": True, "rate": None, "err": 0}
    hub = hub_for()
    hub.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": blind}})
    assert hub.edges_view()[0]["capacity"] is None, hub.edges_view()[0]  # was 0.0
    two = hub_for(ring_map(two_rails=True))
    two.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": blind, "roceP2p1s0f0": counters(0)}})
    assert two.edges_view()[0]["capacity"] == 200.0, two.edges_view()[0]


def test_link_errors_show_only_when_they_rise():
    hub = hub_for()
    base = time.time()
    hub.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": counters(0, err=7)}})
    hub.ingest("dgx0", {"t": base + 2, "fabric": {"rocep1s0f0": counters(0, err=7)}})
    assert hub.edges_view()[0]["errors"] is False
    hub.ingest("dgx0", {"t": base + 4, "fabric": {"rocep1s0f0": counters(0, err=9)}})
    assert hub.edges_view()[0]["errors"] is True


def test_a_port_that_disappears_stops_showing_traffic():
    """The device of a ring port is gone from a Spark that still answers: that link is down, and it is said once,
    like a link whose state went down (it went without a word). What it carries is not known from then on: it stood
    at 0.0 Gb/s, and at the line rate of the last look."""
    hub = hub_for()
    base = time.time()

    def edges():
        return {(e["from"], e["to"]): e for e in hub.edges_view()}

    hub.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": counters(0), "rocep1s0f1": counters(0)}})
    hub.ingest("dgx0", {"t": base + 2, "fabric": {"rocep1s0f0": counters(10**9), "rocep1s0f1": counters(0)}})
    assert edges()[(0, 1)]["gbps"] > 0
    for k in (2, 3, 4):
        hub.ingest("dgx0", {"t": base + 2 * k, "fabric": {"rocep1s0f1": counters(0)}})
        time.sleep(0.002)  # every sample has its own moment, so a second line would not hide behind the first
    gone = edges()[(0, 1)]
    assert (gone["gbps"], gone["rx"], gone["up"], gone["capacity"]) == (None, None, False, None), gone
    assert [e["text"] for e in hub.events if e["kind"] == "link"] == ["Link f0 went down"], list(hub.events)
    other = edges()[(0, 3)]
    assert (other["gbps"], other["up"], other["capacity"]) == (0.0, True, 200.0), other  # the cable that is there
    hub.ingest("dgx0", {"t": base + 10, "fabric": {"rocep1s0f0": counters(2 * 10**9), "rocep1s0f1": counters(0)}})
    back = edges()[(0, 1)]
    assert (back["gbps"], back["up"], back["capacity"]) == (None, True, 200.0), back  # there again: no rate yet


def test_link_counters_show_only_what_changed():
    """What a link counter did since the last look is the difference of two readings. One that went back (the
    driver was reloaded, the counter reset) has no such difference: it stood as "0 new", which says that nothing
    happened on a counter nobody could compare."""
    hub = hub_for()
    hub._links("dgx0", {"rocep1s0f0": {"packet_seq_err": 5, "tx_pause_ctrl_phy": 100, "gone": None}})
    assert hub.nodes["dgx0"]["links"]["rocep1s0f0"] == {}
    hub._links("dgx0", {"rocep1s0f0": {"packet_seq_err": 7, "tx_pause_ctrl_phy": 90, "gone": None}})
    assert hub.nodes["dgx0"]["links"]["rocep1s0f0"] == {"packet_seq_err": 2}  # the one that went back was 0
    hub._links("dgx0", {"rocep1s0f0": {"packet_seq_err": 7, "tx_pause_ctrl_phy": 95, "gone": None}})
    assert hub.nodes["dgx0"]["links"]["rocep1s0f0"] == {"packet_seq_err": 0, "tx_pause_ctrl_phy": 5}  # counted on


def test_link_counters_nobody_read_are_not_counters_that_stood_still():
    """The card of the network chip names the link counters that moved since the last look, and says "None." where
    none did. A slow reading whose reader of these counters failed says None in their place. The hub took that
    for a reading without devices: nothing moved, so "None." of counters nobody read; and it kept what it counts
    from, so the reading after the hole showed all that happened meanwhile as of the last 15 s. Not read is
    unknown, and what the counters are counted from goes with it. A reading that names no device is a reading."""
    hub = hub_for()
    node = hub.nodes["dgx0"]

    def slow(errors, t):
        hub._slow("dgx0", node, {"links": errors if errors is None else {"rocep1s0f0": {"packet_seq_err": errors}}}, t)
        return node["links"]

    assert slow(5, 100.0) == {"rocep1s0f0": {}}
    assert slow(7, 115.0) == {"rocep1s0f0": {"packet_seq_err": 2}} and "dgx0" in hub.link_counts
    assert slow(None, 130.0) is None and "dgx0" not in hub.link_counts, node["links"]  # was {}: "None." on the card
    assert slow(40, 145.0) == {"rocep1s0f0": {}}, node["links"]  # was 33 "in the last 15 s": across the hole
    assert slow(41, 160.0) == {"rocep1s0f0": {"packet_seq_err": 1}}
    hub._slow("dgx0", node, {"links": {}}, 175.0)
    assert node["links"] == {} and hub.link_counts["dgx0"] == {}  # read: this Spark has no link device


def test_a_new_container_counts_no_rate_from_the_one_before_it():
    """The engine's container went away and another one came: its counters belong to another life. The first sample
    of the new one gives no rate, where the old code took the difference of two containers for megabytes read."""
    hub, t = hub_for(), time.time()
    node = hub.nodes["dgx0"]

    def box(read, cpu):
        disk = {"rbytes": read, "wbytes": 0, "rios": 0, "wios": 0}
        return {
            "disk": disk,
            "cpu_us": cpu,
            "throttled": 0,
            "psi": {},
            "mem": 2**30,
            "peak": 2**30,
            "oom": 0,
            "pids": 9,
        }

    hub.ingest("dgx0", {"t": t, "fabric": {}, "cg": box(1_000_000, 0)})
    hub.ingest("dgx0", {"t": t + 2, "fabric": {}, "cg": box(3_000_000, 4_000_000)})
    assert (node["eng_read_mb"], node["eng_cores"]) == (1.0, 2.0)
    hub.ingest("dgx0", {"t": t + 4, "fabric": {}})  # the container is gone
    assert (node["eng_read_mb"], node["eng_cores"]) == (None, None)
    hub.ingest("dgx0", {"t": t + 6, "fabric": {}, "cg": box(9_000_000, 9_000_000)})  # another one, counted further on
    assert (node["eng_read_mb"], node["eng_cores"]) == (None, None), (node["eng_read_mb"], node["eng_cores"])
    hub.ingest("dgx0", {"t": t + 8, "fabric": {}, "cg": box(11_000_000, 13_000_000)})
    assert (node["eng_read_mb"], node["eng_cores"]) == (1.0, 2.0)


def test_time_at_a_limit_comes_from_the_counters():
    hub = hub_for()
    hub.ingest("dgx0", {"t": 100.0, "gpu": {"cap_us": 1_000_000}})
    hub.ingest("dgx0", {"t": 110.0, "gpu": {"cap_us": 3_000_000}})
    assert hub.nodes["dgx0"]["cap_pct"] == 20.0


def test_time_in_thermal_slowdown_and_at_the_power_brake_is_kept_as_curves():
    """What braked a GPU, and for how long, can only be read back if the shares of time are kept sample by sample."""
    hub = hub_for()
    hub.ingest("dgx0", {"t": 100.0, "gpu": {"cap_us": 0, "sw_therm_us": 0, "hw_therm_us": 0, "brake_us": 0}})
    later = {"cap_us": 0, "sw_therm_us": 1_000_000, "hw_therm_us": 500_000, "brake_us": 2_000_000}
    hub.ingest("dgx0", {"t": 110.0, "gpu": later})
    node = hub.nodes["dgx0"]
    assert (node["cap_pct"], node["therm_pct"], node["brake_pct"]) == (0.0, 15.0, 20.0), node
    kept = {key: [value for _, value in hub.history[f"dgx0.{key}"]] for key in ("cap_pct", "therm_pct", "brake_pct")}
    assert kept == {"cap_pct": [0.0], "therm_pct": [15.0], "brake_pct": [20.0]}, kept  # the first sample has no rate


def test_time_in_thermal_slowdown_nobody_could_count_is_not_kept_as_zero():
    """The two thermal counters fell back (a reset of the GPU) or were not read, while the power cap counted on: there
    is no share of time in thermal slowdown for that sample, and no point of the curve. Zero would say "never braked"."""
    hub = hub_for()
    hub.ingest("dgx0", {"t": 100.0, "gpu": {"cap_us": 1000, "sw_therm_us": 9000, "hw_therm_us": 9000, "brake_us": 0}})
    hub.ingest("dgx0", {"t": 110.0, "gpu": {"cap_us": 5000, "sw_therm_us": 10, "hw_therm_us": 10, "brake_us": 0}})
    node = hub.nodes["dgx0"]
    assert node["cap_pct"] == 0.04 and node["therm_pct"] is None, node
    assert [value for _, value in hub.history["dgx0.therm_pct"]] == []
    # one of the two that this GPU does not report is no reason to keep nothing: the other one is the share
    hub.ingest(
        "dgx0", {"t": 120.0, "gpu": {"cap_us": 5000, "sw_therm_us": 500_010, "hw_therm_us": None, "brake_us": 0}}
    )
    assert hub.nodes["dgx0"]["therm_pct"] == 5.0, hub.nodes["dgx0"]


def test_a_slow_reading_without_the_deep_memory_leaves_none_of_the_reading_before():
    """Every 15 s a sampler reads where the memory of its Spark went. When that reading fails, the block of the
    reading before stood on: big free blocks, page cache, what the kernel did to find memory, all as of then. And
    what sits on the GPU was only renewed together with that block, although it is a reading of its own."""
    hub = hub_for()
    node = hub.nodes["dgx0"]
    counted = {"compact_migrate_scanned": 0, "pgmigrate_fail": 0, "allocstall": 0, "pswpout": 0, "pgmajfault": 0}
    deep = {"mem": {"Cached": 11 * 2**30}, "vm": {**counted, "oom_kill": 1}, "blocks_16m": 420, "free_big": 2**33}
    hub._deep("dgx0", node, {"memory": deep, "apps": [{"gb": 84.2, "name": "x"}]}, 100.0)
    later = {**deep, "vm": {**dict.fromkeys(counted, 150), "oom_kill": 1}}
    hub._deep("dgx0", node, {"memory": later, "apps": [{"gb": 84.2, "name": "x"}]}, 115.0)
    block = ("memory", "blocks_16m", "free_big_gb", "oom_kills", "compact_scan_s", "migrate_fail_s", "alloc_stall_s")
    assert [node[key] for key in block] == [{"Cached": 11.0}, 420, 8.0, 1, 10.0, 10.0, 10.0], node
    assert (node["swap_out_s"], node["majfault_s"], node["gpu_apps_gb"]) == (10.0, 10.0, 84.2), node
    hub._deep("dgx0", node, {"memory": None, "apps": [{"gb": 10.0, "name": "y"}]}, 130.0)
    unread = [node[key] for key in (*block, "swap_out_s", "majfault_s")]
    assert unread == [None] * 9, unread  # all nine stood as of the reading before
    assert node["gpu_apps_gb"] == 10.0, node["gpu_apps_gb"]  # was 84.2: not renewed without the memory reading
    assert [value for _, value in hub.history["dgx0.blocks_16m"]] == [
        420.0,
        420.0,
    ]  # and no point for what was not read


def test_a_list_the_slow_reading_does_not_hold_is_not_an_empty_list():
    """What a sampler reads every 15 s holds lists: the programs on the GPU, the biggest processes, the threads of
    the engine and its key threads, the clocks of the cores, who else ran on the engine's cores, the cables. A
    reading that lacks one of them gave an empty list, and 0 GB on the GPU: nobody there, where nobody had looked."""
    hub = hub_for()
    node = hub.nodes["dgx0"]
    lists = ("apps", "top", "threads", "clocks", "intruders", "key_threads")
    hub._slow("dgx0", node, {**{key: [] for key in lists}, "cables": {}}, 100.0)
    assert [node[key] for key in lists] == [[]] * 6 and node["gpu_apps_gb"] == 0.0, node  # read, and empty
    assert hub.cables["dgx0"] == {}
    hub._slow("dgx0", node, {}, 115.0)
    assert [node[key] for key in lists] == [None] * 6, [node[key] for key in lists]  # each was []
    assert node["gpu_apps_gb"] is None and hub.cables["dgx0"] is None, (node["gpu_apps_gb"], hub.cables)  # 0.0, {}
    json.loads(json.dumps(hub.nerd_view(0, True), allow_nan=False))


def test_a_counter_that_was_not_read_once_does_not_cost_the_next_rate_too():
    """A rate is the change of a counter since the reading before. When a counter was not read once, that empty
    reading took the place of the one to count from, and the next reading had nothing before it either: two rates
    lost for one reading missed. Each counter is counted from its own last reading. Not across a hole, though: what
    was unread for longer than the hub bridges gives no rate, a mean over minutes is no rate of now."""
    hub, scope = hub_for(), ("dgx0", "x")
    assert hub._rate(scope, 0.0, {"a": 10, "b": 1}) == {}
    assert hub._rate(scope, 2.0, {"a": None, "b": 3}) == {"b": 1.0}
    assert hub._rate(scope, 4.0, {"a": 30, "b": 5}) == {"a": 5.0, "b": 1.0}  # a was missing: nothing to count from
    assert hub._rate(scope, 6.0, {"a": 4, "b": 7}) == {"b": 1.0}  # a went back: no rate
    assert hub._rate(scope, 8.0, {"a": 8, "b": 9}) == {"a": 2.0, "b": 1.0}  # and counts on from there
    assert hub._rate(scope, 10.0, {"b": 11}) == {"b": 1.0}  # a reading that does not name a at all
    assert hub.reach == 24.0 and hub._rate(scope, 40.0, {"a": 1000, "b": 41}) == {}  # 32 s and 30 s unread: a hole
    assert hub._rate(scope, 42.0, {"a": 1010, "b": 43}) == {"a": 5.0, "b": 1.0}
    assert hub._rate(scope, 41.0, {"a": 1020, "b": 45}) == {}  # the clock went back: no rate either
    slow = ("dgx0", "nvml")  # what comes every 15 s may miss a reading and still be counted from
    hub._rate(slow, 0.0, {"energy_mj": 0}, 60.0)
    hub._rate(slow, 15.0, {"energy_mj": None}, 60.0)
    assert hub._rate(slow, 30.0, {"energy_mj": 3000}, 60.0) == {"energy_mj": 100.0}
    assert hub._rate(slow, 105.0, {"energy_mj": 9000}, 60.0) == {}  # but not across more than a minute


def test_a_cable_shows_stop_time_and_per_lane_errors():
    hub = hub_for()
    before = {"tx_global_pause_duration": 0, "rx_err_lane_0_phy": 0, "uncorrectable_blocks": 0}
    after = {"tx_global_pause_duration": 1_500_000, "rx_err_lane_0_phy": 770, "uncorrectable_blocks": 2}
    hub._cables("dgx0", {"f0": before}, 100.0)
    hub._cables("dgx0", {"f0": after}, 110.0)
    view = hub.cables["dgx0"]["f0"]
    assert view["stop_tx"] == 15.0 and view["lane0_s"] == 77.0 and view["uncorrectable"] == 2


def test_what_a_cable_did_not_count_is_not_a_count_of_zero():
    """The deep view shows per cable how many packets it dropped, how many pause storms it saw and for how long its
    sender was held back since boot. A cable that sent none of these counters stood at 0, 0 and 0.0 s: nothing
    lost and never held back, said of counters nobody read. And a sum of two counters is none with one missing."""
    hub = hub_for()

    def totals(row):
        hub._cables("dgx0", {"f0": row}, 100.0)
        view = hub.cables["dgx0"]["f0"]
        return view["discards"], view["storm"], view["stop_total_s"]

    assert totals({"rx_err_lane_0_phy": 5}) == (None, None, None), totals({})  # was (0, 0, 0.0)
    counted = {"rx_discards_phy": 2, "tx_discards_phy": 3, "tx_global_pause_duration": 1_500_000}
    storms = {"tx_pause_storm_warning_events": 0, "tx_pause_storm_error_events": 1}
    assert totals({**counted, **storms}) == (5, 1, 1.5)
    assert totals({"rx_discards_phy": 0, "tx_discards_phy": 0, **storms}) == (0, 1, None)  # counted, and none
    assert totals({"rx_discards_phy": 2, "tx_pause_storm_error_events": 1}) == (None, None, None)  # was (2, 1, 0.0)


def test_a_link_that_goes_down_is_said_once_until_it_was_up_again():
    """Down for many samples is one line. The two functions of one port are one cable: one of them down is no link down."""
    hub = hub_for()
    base = time.time()

    def said():
        return [e["text"] for e in hub.events if e["kind"] == "link"]

    hub.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": counters(0), "roceP2p1s0f0": counters(0)}})
    hub.ingest("dgx0", {"t": base + 2, "fabric": {"rocep1s0f0": counters(0, up=False), "roceP2p1s0f0": counters(0)}})
    assert said() == []  # its twin still carries the cable
    for k in (2, 3, 4):
        down = {"rocep1s0f0": counters(0, up=False), "roceP2p1s0f0": counters(0, up=False)}
        hub.ingest("dgx0", {"t": base + 2 * k, "fabric": down})
        time.sleep(0.002)  # every sample has its own moment, so a second line would not hide behind the first
    assert said() == ["Link f0 went down"], said()
    hub.ingest("dgx0", {"t": base + 10, "fabric": {"rocep1s0f0": counters(0), "roceP2p1s0f0": counters(0)}})
    hub.ingest("dgx0", {"t": base + 12, "fabric": {"rocep1s0f0": counters(0, up=False)}})
    assert said() == ["Link f0 went down"] * 2, said()  # up in between: down again is news


UNIT = 62_500_000  # so many counts of 4 bytes over 2 s are 1 Gb/s


def link_events(hub):
    """What the hub said about links, in the order it said it."""
    return [e["text"] for e in hub.events if e["kind"] == "link"]


def test_a_port_whose_counters_were_not_read_is_not_a_port_that_went_down():
    """A sampler names every ring port it finds, with None for what it could not read of it; and where its reader
    of the ports failed as a whole, the sample says so with a None in the place of all of them. The hub took a
    port without counters as a port without traffic twice over (nothing to count from in the sample after it
    either), and a sample without ports as a Spark whose every link went down, each with its event. A port nobody
    read is unknown, nothing went down, and its counter is counted on from its own last reading: the traffic
    since then, over the time since then, but never across more than the hub bridges."""
    hub, base = hub_for(), time.time()

    def both(sent):
        return {"rocep1s0f0": counters(sent), "rocep1s0f1": counters(0)}

    def edge(to=1):
        e = {(e["from"], e["to"]): e for e in hub.edges_view()}[(0, to)]
        return e["gbps"], e["rx"], e["up"], e["capacity"], e["errors"]

    hub.ingest("dgx0", {"t": base, "fabric": both(0)})
    hub.ingest("dgx0", {"t": base + 2, "fabric": both(UNIT)})
    assert edge() == (1.0, 0.0, True, 200.0, False) and hub.nodes["dgx0"]["net"] == 1.0, edge()
    unread = {
        "tx": None,
        "rx": None,
        "up": True,
        "rate": 200.0,
        "err": 0,
    }  # the port is there, its counters were not read
    hub.ingest("dgx0", {"t": base + 4, "fabric": {"rocep1s0f0": unread, "rocep1s0f1": counters(0)}})
    assert edge() == (None, None, True, 200.0, False) and hub.nodes["dgx0"]["net"] is None, edge()
    hub.ingest("dgx0", {"t": base + 6, "fabric": both(5 * UNIT)})  # four units since its last reading, 4 s ago
    assert edge() == (2.0, 0.0, True, 200.0, False) and hub.nodes["dgx0"]["net"] == 2.0, edge()  # was (None, None, ...)
    hub.ingest("dgx0", {"t": base + 8, "fabric": None})  # the reader of the ports failed
    assert edge() == edge(3) == (None, None, None, None, None), (edge(), edge(3))  # was 0 traffic known, "down"
    assert hub.nodes["dgx0"]["net"] is None and link_events(hub) == [], link_events(hub)  # was two links "went down"
    hub.ingest("dgx0", {"t": base + 10, "fabric": both(7 * UNIT)})
    assert edge() == (1.0, 0.0, True, 200.0, False) and link_events(hub) == [], (edge(), link_events(hub))
    hub.ingest("dgx0", {"t": base + 12, "fabric": {"rocep1s0f0": unread, "rocep1s0f1": counters(0)}})
    hub.ingest("dgx0", {"t": base + 70, "fabric": both(99 * UNIT)})  # a minute unread: longer than the hub bridges
    assert hub.reach == 24.0 and edge()[0] is None, edge()  # a mean over a minute is no traffic of now
    hub.ingest("dgx0", {"t": base + 72, "fabric": both(100 * UNIT)})
    assert edge()[0] == 1.0, edge()


def test_a_cable_with_one_function_unread_has_no_traffic_and_counts_on_from_its_own_last_reading():
    """A cable is its two PCIe functions. With the counters of one of them not read, the cable has no traffic for
    that sample: what the other function carried alone is not what the cable carried. The sample after it counts
    each function from its own last reading, so the cable has its traffic again at once."""
    hub, base = hub_for(ring_map(two_rails=True)), time.time()

    def rails(first, second):
        return {"rocep1s0f0": counters(first), "roceP2p1s0f0": counters(second)}

    def gbps():
        return hub.edges_view()[0]["gbps"]

    hub.ingest("dgx0", {"t": base, "fabric": rails(0, 0)})
    hub.ingest("dgx0", {"t": base + 2, "fabric": rails(UNIT, UNIT)})
    assert gbps() == 2.0
    half = {"rocep1s0f0": counters(3 * UNIT), "roceP2p1s0f0": {**counters(0), "tx": None, "rx": None}}
    hub.ingest("dgx0", {"t": base + 4, "fabric": half})
    assert gbps() is None and hub.nodes["dgx0"]["net"] is None, gbps()  # not the 2.0 of the one function that was read
    hub.ingest("dgx0", {"t": base + 6, "fabric": rails(4 * UNIT, 3 * UNIT)})
    assert gbps() == 2.0, gbps()  # one unit over 2 s and two units over 4 s; was None: nothing to count from


def test_a_link_state_nobody_read_is_not_a_link_that_went_down():
    """Whether a link is up is read from a file of its port. Where that could not be read, the sample says None,
    and the hub took it for "down": an event "Link ... went down" and a link drawn as down, of a state nobody
    read. Unknown is neither. A link is down where that was read, and said once, also when the sample before it
    was the one nobody read. Of two functions one that is up makes the cable up; one down and one unread do not
    make it down."""
    hub, base = hub_for(), time.time()

    def state(up):
        hub.ingest("dgx0", {"t": base + 2 * len(seen), "fabric": {"rocep1s0f0": counters(0, up=up)}})
        seen.append(hub.edges_view()[0]["up"])
        time.sleep(0.002)  # every sample has its own moment, so a second line would not hide behind the first
        return seen[-1]

    seen = []
    assert state(True) is True
    assert state(None) is None and link_events(hub) == [], (seen, link_events(hub))  # was False, with the event
    assert state(False) is False and link_events(hub) == ["Link f0 went down"], link_events(hub)
    assert state(None) is None and state(False) is False and link_events(hub) == ["Link f0 went down"]  # said once
    assert state(True) is True and state(None) is None and state(False) is False
    assert link_events(hub) == ["Link f0 went down"] * 2, link_events(hub)  # up in between: down again is news
    two = hub_for(ring_map(two_rails=True))
    two.ingest("dgx0", {"t": base, "fabric": {"rocep1s0f0": counters(0, up=None), "roceP2p1s0f0": counters(0)}})
    assert two.edges_view()[0]["up"] is True  # its twin carries the cable
    down = {"rocep1s0f0": counters(0, up=None), "roceP2p1s0f0": counters(0, up=False)}
    two.ingest("dgx0", {"t": base + 2, "fabric": down})
    assert two.edges_view()[0]["up"] is None and link_events(two) == [], two.edges_view()[0]  # the other may be up


def test_an_error_count_that_was_not_read_is_no_count_of_zero():
    """The errors of a port are the sum of its error counters, and new errors are what that sum gained since the
    reading before. A sampler says None where it could not read them. The hub subtracted the two sums as they
    came: a None ended the whole sample of the Spark with an exception, and the zero an older sampler sent for
    counters it could not read made their whole count "new errors" in the sample after it. A count that was not
    read gives no gain; the next one counts from the last that was read. Whether a link had errors lately is not
    known while its count is not read, unless errors were seen to rise within the last two minutes."""
    hub, base = hub_for(), time.time()

    def errors(count, t):
        hub.ingest("dgx0", {"t": base + t, "fabric": {"rocep1s0f0": counters(0, err=count)}})
        return hub.edges_view()[0]["errors"], link_events(hub)

    assert errors(7, 0) == (False, [])
    assert errors(None, 2) == (None, [])  # was a TypeError in ingest: the sample of the Spark was skipped
    assert errors(7, 4) == (False, [])  # as many as at its last reading: nothing new
    assert errors(None, 6) == (None, [])
    assert errors(9, 8) == (True, ["Errors on link f0"])  # two more than at its last reading: they did happen
    assert errors(None, 10) == (True, ["Errors on link f0"])  # not read now, but seen to rise a moment ago
    hub.node_down("dgx0", "gone")
    assert hub.edges_view()[0]["errors"] is None  # of a Spark that is away nothing is known


def test_errors_one_function_of_a_cable_gained_are_said_while_the_count_of_its_twin_is_unread():
    """A cable is its two PCIe functions, and each counts its own errors. Where the count of one rose in a sample
    that could not read the count of its twin, the hub said nothing: the errors of the cable were not all read.
    But it kept the 9 it had read as what that function counts on from, so the sample after it found nothing new:
    the rise was lost for good. Errors a function was read to gain are said when they are read, whatever its twin
    could say, and once: each function counts on from its own last reading. That there are none still needs the
    count of both. The moment is set by hand: what rose stands for two minutes."""
    start, real, said = time.time(), time.time, ["Errors on link f0"]

    def cable(order):
        """A hub that hears of one cable, and what it says of its errors after one more sample: the function whose
        count rises is the first of the two the sample names (order 1) or the second (order -1)."""
        hub = hub_for(ring_map(two_rails=True))

        def errors(after, risen, twin):
            time.time = lambda: start + after
            both = (counters(0, err=risen), counters(0, err=twin))[::order]
            hub.ingest("dgx0", {"t": start + after, "fabric": dict(zip(("rocep1s0f0", "roceP2p1s0f0"), both))})
            return hub.edges_view()[0]["errors"], link_events(hub)

        return errors

    try:
        for errors in (cable(1), cable(-1)):
            assert errors(0, 7, 0) == (False, [])
            assert errors(2, 9, None) == (True, said)  # was (None, []): two more errors were read, and nothing said
            assert errors(4, 9, 0) == (True, said)  # was (False, []): counted from the 9 by now, the rise was gone
            assert errors(123, 9, 0) == (False, said)  # two minutes after the rise: it was counted once, not again
            assert errors(125, 9, None) == (None, said)  # nothing that was read rose, and one count was not read
            assert errors(127, 9, 3) == (True, said * 2)  # the twin counts on from the 0 it last read: three more
    finally:
        time.time = real


def test_a_ring_port_is_counted_over_the_moment_its_counters_were_read():
    """The sample of a Spark is stamped when its round begins, and its ring ports are read after the GPU, the cores,
    the CPU and the memory: later by as much as those took, more in one round than in another. The traffic was
    counted over the stamps of the samples: a port at 195 Gb/s read 0.15 s later than in the round before showed
    209.6 Gb/s, and 180.4 in the round after. A port that names when its counters were read is counted over that
    moment; one that does not, from an older sampler, over the stamp, as before."""
    unit = 195e9 / 32  # 4-byte units in a second at 195 Gb/s

    def seen(named):
        hub, out = hub_for(), []
        for t, late in ((1000.0, 0.01), (1002.0, 0.16), (1004.0, 0.01)):
            port = counters(round(unit * (t + late - 1000.0)))
            hub.ingest("dgx0", {"t": t, "fabric": {"rocep1s0f0": {**port, "t": t + late} if named else port}})
            out.append({(e["from"], e["to"]): e["gbps"] for e in hub.edges_view()}[(0, 1)])
        return out

    assert seen(True) == [None, 195.0, 195.0], seen(True)
    assert seen(False) == [None, 209.62, 180.38], seen(False)


def test_the_disk_the_pressure_the_cgroup_and_the_gpu_are_counted_over_the_moment_they_were_read():
    """The disk, the pressure files and the engine's cgroup are read after the ring ports, later than the stamp of
    the sample; the line of nvidia-smi that a sample copies was printed before it. Each names when it was read and
    is counted over that moment. Here every one was read 0.3 s later in the second sample than in the first: true
    are 102.4 MB/s from the disk, 20 % of the time stalled, 50 MB/s and 3 cores in the cgroup, half the time at the
    power cap. Without such moments, from an older sampler, the stamps count, as before: 2.3 s over 2."""

    def figures(named):
        hub = hub_for()
        for t, late in ((1000.0, 0.0), (1002.0, 0.3)):
            s = t + late - 1000.0  # seconds since the first reading, by the moments of reading
            disk = {"read": round(s * 200_000), "write": 0}  # sectors of 512 bytes
            cg = {"disk": {"rbytes": round(s * 50e6), "wbytes": 0, "rios": 0, "wios": 0}, "cpu_us": round(s * 3e6)}
            cg.update(throttled=0, psi={}, mem=None, peak=None, oom=0, pids=1)
            readings = {
                "disk": disk,
                "psi": {"cpu_some": round(s * 200_000)},
                "cg": cg,
                "gpu": {"cap_us": round(s * 5e5)},
            }
            if named:
                for reading in readings.values():
                    reading["t"] = t + late
            hub.ingest("dgx0", {"t": t, "fabric": {}, **readings})
        node = hub.nodes["dgx0"]
        return node["disk_read"], node["psi_cpu"], node["eng_read_mb"], node["eng_cores"], node["cap_pct"]

    assert figures(True) == (102.4, 20.0, 50.0, 3.0, 50.0), figures(True)
    assert figures(False) == (117.8, 23.0, 57.5, 3.45, 57.5), figures(False)


def test_the_cables_and_the_kernels_memory_counters_are_counted_over_the_moment_they_were_read():
    """Every 15 s a sampler stamps its slow readings before the NVML fields, and reads the cables and the kernel's
    memory counters after them, with calls of ethtool in between. Each names when it was read and is counted over
    that moment: here 1 s later in the second reading than in the first, at 10 major faults a second and 25 Gb/s on
    the wire. Without such moments, from an older sampler, the stamps count, as before: 16 s over 15."""

    def figures(named):
        hub = hub_for()
        node = hub.nodes["dgx0"]
        for t, late in ((100.0, 0.0), (115.0, 1.0)):
            s = t + late - 100.0
            vm = dict.fromkeys(("compact_migrate_scanned", "pgmigrate_fail", "allocstall", "pswpout"), 0)
            vm["pgmajfault"], row = round(s * 10), {"tx_bytes_phy": round(s * 25e9 / 8)}
            if named:
                vm["t"] = row["t"] = t + late
            memory = {"mem": {}, "vm": vm, "blocks_16m": 0, "free_big": 0}
            hub._deep("dgx0", node, {"memory": memory, "cables": {"f0": row}}, t)
        return node["majfault_s"], hub.cables["dgx0"]["f0"]["gb_tx"]

    assert figures(True) == (10.0, 25.0), figures(True)
    assert figures(False) == (10.7, 26.67), figures(False)


def test_a_line_of_nvidia_smi_that_a_sample_copies_once_more_keeps_its_share():
    """nvidia-smi prints a line per interval, at the pace of the samples but in a phase of its own, so now and then
    two samples copy the same line. Counted once more over no time, that line gave no share: a dash on the page and
    a gap in the curve for one sample. A line with the moment of the one counted last is no new reading: the share
    of the last two lines stands, and the next line is counted over the moments of the lines. Once nvidia-smi sends
    no line at all (the sampler sends none after 10 s), there is no share, as before. A sampler that names no
    moments counts over its samples, as before."""

    def shares(named):
        hub, out = hub_for(), []
        lines = ((999.9, 0), (1001.9, 1_000_000), (1001.9, 1_000_000), (1005.95, 2_012_500))  # moment, cap_us
        for k, (moment, cap) in enumerate(lines):
            line = {"cap_us": cap, "t": moment} if named else {"cap_us": cap}
            hub.ingest("dgx0", {"t": 1000.0 + 2 * k, "gpu": line})
            out.append(hub.nodes["dgx0"]["cap_pct"])
        hub.ingest("dgx0", {"t": 1008.0, "gpu": {}})  # no line for 10 s: the sampler sends none
        out.append(hub.nodes["dgx0"]["cap_pct"])
        return out, [v for _, v in hub.history["dgx0.cap_pct"]]

    assert shares(True) == ([None, 50.0, 50.0, 25.0, None], [50.0, 50.0, 25.0]), shares(True)
    assert shares(False) == ([None, 50.0, 0.0, 50.62, None], [50.0, 0.0, 50.62]), shares(False)
