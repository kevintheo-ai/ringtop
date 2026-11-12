"""What a sample brings to its node: memory, disk, sensors, the clock latch, the thermal limit."""

import time

from ringtop_parts.connect.shell import SAMPLER
from ringtop_parts.core.demo import Round
from ringtop_parts.core.demo_node import node_sample
from ringtop_parts.core.diagnose import LATCH_SAMPLES, NEAR_LIMIT_C, diagnose, fan_points
from tests.fixtures import hub_for, sampler_namespace


def test_zero_free_memory_is_a_value():
    hub = hub_for()
    hub.ingest("dgx0", {"t": time.time(), "mem": {"MemAvailable": 0, "MemTotal": 2**37}, "fabric": {}})
    assert hub.nodes["dgx0"]["mem_free_gb"] == 0


def test_disk_rate_comes_from_sectors_and_is_unknown_across_a_reboot():
    """Megabytes per second from the sectors of two samples. Where there is nothing to count from (the first
    sample, a counter that went back, a counter that was not read), there is no rate: the one of before must not
    stand as a new one, and no point of the curve is kept for it."""
    hub, now = hub_for(), time.time()
    node, space = hub.nodes["dgx0"], {"free": 2**40, "total": 2**41}
    hub.ingest("dgx0", {"t": 100.0, "fabric": {}, "disk": {"read": 2_000_000, "write": 0, **space}})
    assert node["disk_free_gb"] == 1024 and node["disk_read"] is None
    hub.ingest("dgx0", {"t": 102.0, "fabric": {}, "disk": {"read": 2_004_000, "write": 400, **space}})
    assert node["disk_read"] == 1.0 and node["disk_write"] == 0.1
    hub.ingest("dgx0", {"t": 104.0, "fabric": {}, "disk": {"read": 10, "write": 1, **space}})
    assert node["disk_read"] is None and node["disk_write"] is None  # the counter went back: a reboot, no spike
    hub.ingest("dgx0", {"t": 106.0, "fabric": {}, "disk": {"read": 4010, "write": 1, **space}})
    assert node["disk_read"] == 1.0 and node["disk_write"] == 0.0
    hub.ingest("dgx0", {"t": 108.0, "fabric": {}, "disk": space})  # the counters were not read: no error, no rate
    assert node["disk_read"] is None and node["disk_free_gb"] == 1024
    hub.ingest("dgx0", {"t": 110.0, "fabric": {}, "disk": {"read": 8010, "write": 1, **space}})
    assert node["disk_read"] is None  # and nothing to count from in the sample after it
    kept = [value for t, value in hub.history["dgx0.disk_read"] if t >= now]
    assert kept == [1.0, 1.0], kept  # one point per rate that was measured, none for a rate nobody knows


def test_fans_and_sensors_reach_the_node():
    hub = hub_for()
    node = hub.nodes["dgx0"]
    hub._sensors(node, {"sensors": {"fans": [2600, 2700], "nvme_c": 61.8, "nic_c": 71.0, "wifi_c": 66.0}})
    assert node["fans"] == [2600, 2700] and node["fan"] == 2650 and node["nic_c"] == 71.0
    hub._sensors(node, {})  # an older sampler without sensors changes nothing
    assert node["fan"] == 2650


def test_a_reading_the_sample_names_as_failed_leaves_nothing_of_the_one_before():
    """A sampler guards each of its readers: one that fails is None in the sample, and the others arrive. The hub
    took such a None like a sample that does not send the reading at all, and changed nothing: the disk rate, the
    free space, the fans, the temperatures of SSD, network chip and Wi-Fi and the load of the cores stood on as
    today's for as long as the reader kept failing. A reading that failed is unknown. The size of the drive stays:
    that is what the machine is. A sample that does not name a reading at all still changes nothing."""
    hub = hub_for()
    node, space = hub.nodes["dgx0"], {"free": 2**40, "total": 2**41}
    sensors = {"fans": [2600, 2700], "nvme_c": 61.8, "nic_c": 71.0, "wifi_c": 66.0}
    whole = {"fabric": {}, "sensors": sensors, "cores": [3, 97]}
    hub.ingest("dgx0", {"t": 100.0, **whole, "disk": {"read": 2_000_000, "write": 0, **space}})
    hub.ingest("dgx0", {"t": 102.0, **whole, "disk": {"read": 2_004_000, "write": 400, **space}})
    read = ("disk_read", "disk_write", "disk_free_gb", "fans", "fan", "nvme_c", "nic_c", "wifi_c", "cores")
    assert [node[key] for key in read] == [1.0, 0.1, 1024, [2600, 2700], 2650, 61.8, 71.0, 66.0, [3, 97]], node
    hub.ingest("dgx0", {"t": 104.0, "fabric": {}})  # names none of them: nothing changes
    assert [node[key] for key in read] == [1.0, 0.1, 1024, [2600, 2700], 2650, 61.8, 71.0, 66.0, [3, 97]], node
    hub.ingest("dgx0", {"t": 106.0, "fabric": {}, "disk": None, "sensors": None, "cores": None})
    assert [node[key] for key in read] == [None] * 9, [node[key] for key in read]  # each stood as of 102 s
    assert node["disk_total_gb"] == 2048  # what the machine is
    hub.ingest("dgx0", {"t": 108.0, **whole, "disk": {"read": 2_016_000, "write": 400, **space}})
    assert node["disk_read"] is None and node["fan"] == 2650  # read again: no rate across the reading that failed
    hub.ingest("dgx0", {"t": 110.0, **whole, "disk": {"read": 2_020_000, "write": 400, **space}})
    assert node["disk_read"] == 1.0, node["disk_read"]


def test_a_fan_that_was_not_read_keeps_its_place_and_stays_out_of_the_mean():
    """A Spark lists its fans in an order. The hub dropped a fan whose speed was not read from that list, and the
    fan after it stood in its place: "fan 1" of the page was then the second fan. Each fan keeps its place, one
    nobody read as None. The mean is of the fans that were read, and so is what the diagnosis says of a fan that
    stands still."""
    hub = hub_for()
    node = hub.nodes["dgx0"]
    hub._sensors(node, {"sensors": {"fans": [None, 2700], "nvme_c": 61.8}})
    assert node["fans"] == [None, 2700] and node["fan"] == 2700, (node["fans"], node["fan"])  # was [2700]
    hub._sensors(node, {"sensors": {"fans": [0, None], "nvme_c": 61.8}})
    node.update(live=True, gpu_c=64)
    assert node["fans"] == [0, None] and node["fan"] == 0, (node["fans"], node["fan"])
    assert [p["text"] for p in fan_points(node)] == ["dgx0: the fan stands still at 64 °C."]  # one fan was read
    hub._sensors(node, {"sensors": {"fans": [None, None]}})
    assert node["fans"] == [None, None] and node["fan"] is None and fan_points(node) == []
    hub._sensors(node, {"sensors": {"fans": []}})
    assert node["fans"] == [] and node["fan"] is None  # read, and the machine lists no fan


def test_a_clock_stuck_low_under_load_is_called_the_latch():
    """The GB10 clock latch: full load, no throttle reason, and the clock far below a thousand MHz for several samples."""

    def sample(mhz, util, events="0x0000000000000000"):
        return {
            "t": time.time(),
            "fabric": {},
            "gpu": {"w": 10.0, "c": 50.0, "mhz": mhz, "util": util, "events": events},
        }

    hub = hub_for()
    for _ in range(LATCH_SAMPLES - 1):
        hub.ingest("dgx1", sample(540.0, 97.0))
    assert not hub.nodes["dgx1"]["latched"]
    hub.ingest("dgx1", sample(540.0, 97.0))
    assert hub.nodes["dgx1"]["latched"]
    assert [e["level"] for e in hub.events if "clock latch" in e["text"]] == ["bad"]
    hub.ingest("dgx1", sample(540.0, 97.0))
    assert len([e for e in hub.events if "clock latch" in e["text"]]) == 1  # said once, not with every sample
    points = diagnose({"state": "writing"}, list(hub.nodes.values()), None)["points"]
    said = [p for p in points if "dgx1" in p["text"]]
    assert len(said) == 1 and said[0]["level"] == "bad" and "taking the power away" in said[0]["text"]
    hub.ingest("dgx1", sample(2184.0, 97.0))
    assert not hub.nodes["dgx1"]["latched"]
    quiet = hub_for()
    for _ in range(LATCH_SAMPLES + 2):
        quiet.ingest("dgx2", sample(540.0, 3.0))  # an idle GPU may clock down
        quiet.ingest("dgx3", sample(540.0, 97.0, "0x0000000000000020"))  # a thermal brake says so itself
    assert not quiet.nodes["dgx2"]["latched"] and not quiet.nodes["dgx3"]["latched"]
    named = hub_for()  # a reason the table has no word for is a reason all the same: not the latch
    for _ in range(LATCH_SAMPLES + 2):
        named.ingest("dgx1", sample(540.0, 97.0, "0x0000000000000010"))
    assert not named.nodes["dgx1"]["latched"] and named.nodes["dgx1"]["throttle"] == ["reason 0x10"], named.nodes[
        "dgx1"
    ]
    assert [e["text"] for e in named.events] == ["Slowing down: reason 0x10"], list(named.events)  # held: said once
    blind = (
        hub_for()
    )  # the GPU gives no reasons at all: a thermal brake could hide behind that, so it is not called the latch
    for _ in range(LATCH_SAMPLES + 2):
        blind.ingest("dgx1", sample(540.0, 97.0, None))
        blind.ingest("dgx2", sample(540.0, 97.0, "[N/A]"))
    assert not blind.nodes["dgx1"]["latched"] and not blind.nodes["dgx2"]["latched"]
    assert blind.nodes["dgx1"]["throttle"] is None and not [e for e in blind.events if "clock latch" in e["text"]]


def test_a_spark_close_to_its_thermal_limit_under_load_is_flagged_once():
    def sample(margin, util):
        gpu = {"w": 30.0, "c": 80.0, "mhz": 2184.0, "util": util, "tlimit": margin}
        return {"t": time.time(), "fabric": {}, "gpu": gpu}

    hub = hub_for()
    hub.ingest("dgx1", sample(18.0, 96.0))
    hub.ingest("dgx1", sample(17.0, 96.0))
    near = [e for e in hub.events if "thermal limit" in e["text"]]
    assert (
        len(near) == 1 and near[0]["level"] == "warn" and near[0]["node"] == "dgx1"
    )  # held, not said with every sample
    points = diagnose({"state": "writing"}, list(hub.nodes.values()), None)["points"]
    assert any(p["level"] == "warn" and p["text"].startswith("dgx1 is 17 °C from its thermal limit") for p in points)
    hub.ingest("dgx2", sample(18.0, 5.0))  # idle: the margin says nothing about the cooling under load
    hub.ingest("dgx3", sample(float(NEAR_LIMIT_C), 96.0))  # at the line is not below it
    assert len([e for e in hub.events if "thermal limit" in e["text"]]) == 1
    points = diagnose({"state": "writing"}, list(hub.nodes.values()), None)["points"]
    assert not any(p["text"].startswith(("dgx2 is", "dgx3 is")) and "thermal limit" in p["text"] for p in points)


def test_who_sets_the_fan_speed_reaches_the_node():
    """A floor set through ACPI or through dgx-spark-fan-control shows; the sampler only ever reads it."""
    namespace = sampler_namespace()
    assert namespace["cooling"]() == []  # no such devices on this machine
    source = SAMPLER[SAMPLER.index("def cooling") : SAMPLER.index("def cooling") + 600]
    assert "open(" not in source and "write" not in source
    hub = hub_for()
    floor = [{"type": "dgx_ec_fan_floor", "cur": 3, "max": 12}]
    hub.ingest("dgx0", {"t": time.time(), "fabric": {}, "rare": {"cooling": floor}})
    assert hub.nodes["dgx0"]["cooling"] == floor


def test_slow_readings_that_stopped_coming_do_not_stand_for_good():
    """A sampler reads some things every 15 s and some once a minute, in a thread of its own. When that thread gives
    nothing more while the samples keep coming, its last readings stood for good: "short of memory" from a stall
    of long ago, programs on the GPU, the container, who sets the fans. After four of their periods they are not
    known any more (one minute, four minutes). What the machine is stays, and the fast readings go on."""
    hub, start, real = hub_for(), time.time(), time.time
    ring = Round([n["name"] for n in hub.cluster["nodes"]], 2.0, start)
    node, rare, stays = (
        hub.nodes["dgx1"],
        {"pcie", "devlink", "firmware", "cooling"},
        {"mhz_max", "capacity", "startup"},
    )

    def sample(seconds, slow=False):
        """The sample of the second Spark so many seconds on, with or without the slow readings."""
        ring.advance(start + seconds, 0.0 if slow else 2.0, "writing")
        time.time = lambda: start + seconds
        return node_sample(ring, 1, None)

    try:
        fast = hub_for()
        fast.ingest("dgx1", sample(0))
        hub.ingest("dgx1", sample(0, slow=True))
        first = dict(node)
        slow = set(first) - set(fast.nodes["dgx1"]) - rare  # what only a slow reading brings
        assert {"psi", "apps", "box", "memory", "energy_w", "key_threads", "links"} <= slow and stays <= slow, slow
        assert all(first[key] is not None for key in rare) and "dgx1" in hub.cables and "dgx1" in hub.env
        for seconds in (2, 30, 59):
            hub.ingest("dgx1", sample(seconds))
        assert all(node[key] == first[key] for key in slow - {"energy_w", "avg_mhz", "af_pct"}), node  # still stand
        hub.ingest("dgx1", sample(62))
        assert {key for key in slow - stays if node[key] is not None} == set(), node  # each stood as of second 0
        assert all(node[key] == first[key] for key in stays | rare) and node["w"] is not None, node
        assert "dgx1" not in hub.cables and "dgx1" not in hub.env and "dgx1" not in hub.link_counts
        hub.ingest("dgx1", sample(238))
        assert all(node[key] == first[key] for key in rare)  # once a minute: four minutes
        hub.ingest("dgx1", sample(242))
        assert [node[key] for key in sorted(rare)] == [None] * 4, node
        hub.ingest("dgx1", sample(300, slow=True))  # the thread is back
        assert node["apps"] and node["box"] and node["cooling"] and "dgx1" in hub.cables and "dgx1" in hub.env
        assert node["energy_w"] is None and hub.cables["dgx1"]["f0"]["stop_tx"] is None  # no rate across the hole
        assert node["links"] == {"rocep1s0f0": {}, "rocep1s0f1": {}}, node["links"]  # and no count of what moved
    finally:
        time.time = real
