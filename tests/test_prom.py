"""The moment as Prometheus text: the form of every line, the units, and that nothing unread is ever a number."""

import functools
import json
import re

from ringtop_parts.core.prom import METRICS, exposition
from tests.fixtures import demo_round, hub_for

# text format 0.0.4, strictly: a name, labels whose values mask backslash, quote and line end, one finite number
LABEL = r'[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\\n]|\\\\|\\"|\\n)*"'
SAMPLE = re.compile(rf"(ringtop_[a-z0-9_]+)(?:\{{{LABEL}(?:,{LABEL})*\}})? -?\d+(?:\.\d+)?(?:e[+-]\d+)?")
HEAD = re.compile(r"# (HELP|TYPE) (ringtop_[a-z0-9_]+) (\S.*)")


def as_read(moment):
    """A moment as the server reads it: through JSON, like the one the ticker keeps."""
    return json.loads(json.dumps(moment))


@functools.cache
def played():
    """Moments of the demo, each built by its made-up clock: the first tick, the ring engine writing, the last Spark
    away, and every Spark serving alone while the ring engine is off."""
    got = {}

    def last(word, ticks, at, **more):
        demo_round(ticks, at=at, each=lambda hub: got.update({word: hub.view()}), **more)

    last("first", 1, 0.0)
    last("writing", 30, 100.0)
    last("away", 12, 150.0)
    last("alone", 14, 240.0, start=1_800_000_100.0)
    return {word: as_read(moment) for word, moment in got.items()}


def spark(name, **changes):
    """One Spark of a moment made by hand, every figure of the list read."""
    node = {"name": name, "rank": 0, "head": False, "peers": {}, "live": True, "reason": None, "since": 1.0}
    node.update(w=62.2, util=96, gpu_c=64, mhz=2186, tlimit=12, cpu_pct=44, cpu_c=75)
    node.update(mem_free_gb=23.5, mem_total_gb=119.0, fan=3115.0, fans=[3110, 3120], nvme_c=60, nic_c=71)
    node.update(disk_read=40.0, disk_write=6.5, disk_free_gb=2500.0, disk_total_gb=3722.0)
    node.update(cap_pct=12.5, therm_pct=0.0, brake_pct=0.07, net=128.32)
    return {**node, **changes}


def small():
    """A moment made by hand, in the shape the hub builds: two Sparks, a cable each, an engine that writes, a run."""
    engine = {"state": "writing", "running": 4.0, "waiting": 0.0, "tok_s": 300.2, "kv": 0.0475, "prefix": 0.725}
    engine.update(ttft_p95=3.0, itl_p50=0.035, watts=124.4, watts_from=2, j_per_token=0.414)
    engine.update(finished=15.0, errors=0.0, preemptions=1.0)
    cable = {"from": 0, "to": 1, "group": "f0", "gbps": 31.59, "rx": 0.07, "up": True, "capacity": 200.0}
    loose = {"from": 1, "to": None, "group": "f1", "gbps": 0.0, "rx": 0.0, "up": False, "capacity": 200.0}
    return {
        "t": 1762858800.25,
        "cluster": {"ring": True, "nodes": [{"name": "a", "rank": 0, "head": True}, {"name": "b", "rank": 1}]},
        "identity": {"interval": 2.0, "model": "some-model", "image": "some/image:tag"},
        "engine": engine,
        "nodes": [spark("a", head=True), spark("b", rank=1)],
        "edges": [{**cable, "errors": False}, {**loose, "errors": True}],
        "run": {"source": "command", "name": "Prefill sweep", "done": 22, "total": 24, "started": 1762858700.0},
    }


def told(moment):
    """The lines of the list that carry a number, without the comments."""
    return [line for line in exposition(moment).split("\n") if line and not line.startswith("#")]


def power(lines):
    """What the list tells of the GPU power: of how many Sparks, and the line their sum would be told in."""
    each = [float(line.rsplit(" ", 1)[1]) for line in lines if line.startswith("ringtop_node_gpu_power_watts")]
    return len(each), f"ringtop_cluster_gpu_power_watts {sum(each):.15g}"


def test_every_line_of_the_list_is_one_prometheus_reads():
    """Text format 0.0.4: a line names a figure in a comment, or gives a name, its labels and one finite number.
    The text ends with a line end and holds no empty line."""
    for word, moment in {**played(), "small": small()}.items():
        text = exposition(moment)
        assert text.endswith("\n") and "\n\n" not in text and "\r" not in text, word
        for line in text[:-1].split("\n"):
            assert SAMPLE.fullmatch(line) or HEAD.fullmatch(line), (word, line)
    assert exposition({}) == ""  # nothing read, nothing told


def test_help_and_type_stand_once_before_the_lines_of_every_figure():
    """The lines of one figure stand together, under one HELP and one TYPE of its name. A figure without a line has
    neither."""
    kinds = {metric.name: metric.kind for metric in METRICS}
    for word, moment in {**played(), "small": small()}.items():
        lines, seen, at = exposition(moment)[:-1].split("\n"), [], 0
        while at < len(lines):
            first, second = HEAD.fullmatch(lines[at]), HEAD.fullmatch(lines[at + 1])
            assert first and second and (first.group(1), second.group(1)) == ("HELP", "TYPE"), (word, lines[at])
            name = first.group(2)
            assert second.group(2) == name and second.group(3) == kinds[name], (word, lines[at + 1])
            own = at + 2
            while own < len(lines) and not lines[own].startswith("#"):
                assert SAMPLE.fullmatch(lines[own]).group(1) == name, (word, lines[own])
                own += 1
            assert own > at + 2, (word, name)
            seen.append(name)
            at = own
        assert len(seen) == len(set(seen)) and seen == [name for name in kinds if name in seen], (word, seen)


def test_the_table_names_every_figure_once_in_the_units_prometheus_counts_in():
    names = [metric.name for metric in METRICS]
    assert names and len(names) == len(set(names)), names
    for metric in METRICS:
        assert re.fullmatch(r"ringtop_[a-z0-9_]+", metric.name), metric.name
        assert metric.kind in ("gauge", "counter"), metric
        assert (metric.kind == "counter") == metric.name.endswith("_total"), metric.name
        assert not re.search(r"_(gb|gib|mb|mhz|pct|percent|gbps|ms)(_|$)", metric.name), metric.name
        assert metric.help.endswith(".") and "\n" not in metric.help and "\\" not in metric.help, metric.name


def test_every_figure_of_the_table_is_told_where_it_was_read():
    """No row of the table reads a key the hub does not write. The moment made by hand holds them all; the demo
    plays GPUs that name no distance to their limit and count no time at one, and everything else."""

    def figures(moment):
        return {SAMPLE.fullmatch(line).group(1) for line in told(moment)}

    every = {metric.name for metric in METRICS}
    assert figures(small()) == every, every - figures(small())
    assert every - figures(played()["writing"]) == {
        "ringtop_node_gpu_thermal_margin_celsius",
        "ringtop_node_gpu_power_cap_time_ratio",
        "ringtop_node_gpu_thermal_slowdown_time_ratio",
        "ringtop_node_gpu_power_brake_time_ratio",
    }, every - figures(played()["writing"])


def test_a_figure_is_told_in_the_base_unit_its_name_ends_in():
    """Percent of the page become shares of 1, MHz hertz, Gb/s bytes per second, MB/s bytes per second, and the
    sizes the hub names _gb bytes: it divides by 2**30, so they are GiB. A product of floats carries no noise."""
    lines = told(small())
    for line in (
        "ringtop_moment_timestamp_seconds 1762858800.25",
        "ringtop_sample_interval_seconds 2",
        'ringtop_engine_state{state="writing"} 1',
        "ringtop_engine_output_tokens_per_second 300.2",
        "ringtop_engine_requests_running 4",
        "ringtop_engine_kv_cache_usage_ratio 0.0475",
        "ringtop_engine_prefix_cache_hit_ratio 0.725",
        "ringtop_engine_time_to_first_token_p95_seconds 3",
        "ringtop_engine_inter_token_latency_p50_seconds 0.035",
        "ringtop_engine_gpu_joules_per_token 0.414",
        "ringtop_engine_requests_finished_total 15",
        "ringtop_engine_request_errors_total 0",
        "ringtop_engine_preemptions_total 1",
        "ringtop_cluster_gpu_power_watts 124.4",  # 62.2 W twice, and no 124.4000000001
        "ringtop_cluster_gpu_power_read_nodes 2",
        'ringtop_node_live{node="a"} 1',
        'ringtop_node_gpu_power_watts{node="a"} 62.2',
        'ringtop_node_gpu_utilization_ratio{node="a"} 0.96',
        'ringtop_node_gpu_temperature_celsius{node="a"} 64',
        'ringtop_node_gpu_clock_hertz{node="a"} 2186000000',
        'ringtop_node_gpu_thermal_margin_celsius{node="a"} 12',
        'ringtop_node_cpu_utilization_ratio{node="a"} 0.44',
        'ringtop_node_board_temperature_celsius{node="a"} 75',
        'ringtop_node_memory_available_bytes{node="a"} 25232932864',  # 23.5 * 2**30
        'ringtop_node_memory_total_bytes{node="a"} 127775277056',  # 119 * 2**30
        'ringtop_node_fan_mean_rpm{node="a"} 3115',
        'ringtop_node_fan_rpm{node="a",fan="1"} 3110',
        'ringtop_node_fan_rpm{node="b",fan="2"} 3120',
        'ringtop_node_ssd_temperature_celsius{node="a"} 60',
        'ringtop_node_nic_temperature_celsius{node="a"} 71',
        'ringtop_node_disk_read_bytes_per_second{node="a"} 40000000',
        'ringtop_node_disk_write_bytes_per_second{node="a"} 6500000',
        'ringtop_node_disk_free_bytes{node="a"} 2684354560000',  # 2500 * 2**30
        'ringtop_node_disk_total_bytes{node="a"} 3996467068928',  # 3722 * 2**30
        'ringtop_node_gpu_power_cap_time_ratio{node="a"} 0.125',
        'ringtop_node_gpu_thermal_slowdown_time_ratio{node="a"} 0',
        'ringtop_node_gpu_power_brake_time_ratio{node="a"} 0.0007',
        'ringtop_node_ring_traffic_bytes_per_second{node="a"} 16040000000',  # 128.32 Gb/s
        'ringtop_link_transmit_bytes_per_second{node="a",port="f0",peer="b"} 3948750000',  # 31.59 Gb/s
        'ringtop_link_receive_bytes_per_second{node="a",port="f0",peer="b"} 8750000',
        'ringtop_link_up{node="a",port="f0",peer="b"} 1',
        'ringtop_link_capacity_bytes_per_second{node="a",port="f0",peer="b"} 25000000000',  # 200 Gb/s
        'ringtop_link_recent_errors{node="a",port="f0",peer="b"} 0',
        'ringtop_link_up{node="b",port="f1"} 0',  # a port the node map names no peer for: no label, not an empty one
        'ringtop_link_recent_errors{node="b",port="f1"} 1',
        'ringtop_link_transmit_bytes_per_second{node="b",port="f1"} 0',
        'ringtop_run_info{name="Prefill sweep",source="command"} 1',
        "ringtop_run_done_items 22",
        "ringtop_run_total_items 24",
    ):
        assert line in lines, line
    assert len(lines) == len(set(lines)) == 16 + 2 * 23 + 2 * 5 + 3, len(lines)  # no line twice, none beside these


def test_a_reading_nobody_took_has_no_line_and_is_never_a_zero():
    """At the first tick no rate has two readings to count from: the speed of the engine, the traffic of a Spark and
    of a cable, what its disk reads. None of them has a line. A zero that was read is told as one."""
    text = exposition(played()["first"])
    for unread in (
        "ringtop_engine_output_tokens_per_second",
        "ringtop_engine_time_to_first_token_p95_seconds",
        "ringtop_engine_gpu_joules_per_token",
        "ringtop_node_ring_traffic_bytes_per_second",
        "ringtop_node_disk_read_bytes_per_second",
        "ringtop_link_transmit_bytes_per_second",
        "ringtop_link_receive_bytes_per_second",
    ):
        assert unread not in text, unread
    lines = text.split("\n")
    for read in (
        'ringtop_engine_state{state="idle"} 1',
        "ringtop_engine_requests_waiting 0",
        "ringtop_engine_requests_finished_total 0",
        'ringtop_link_up{node="dgx0",port="f0",peer="dgx1"} 1',
        'ringtop_run_info{source="none"} 1',
    ):
        assert read in lines, read


def test_a_fan_nobody_read_has_no_line_and_the_fan_after_it_keeps_its_number():
    """The fans of a Spark are numbered from 1 in the order the Spark lists them, and a fan whose speed was not
    read keeps its place in that list, as None. It has no line, and it is no fan at 0 RPM; the fan after it is
    still fan 2. Through the hub, from a reading of the sensors with its first fan unread."""
    hub = hub_for()
    node = hub.nodes["dgx0"]
    hub._sensors(node, {"sensors": {"fans": [None, 3120], "nvme_c": 60.0}})
    moment = small()
    moment["nodes"][0].update(fans=node["fans"], fan=node["fan"])
    lines = told(moment)
    assert 'ringtop_node_fan_rpm{node="a",fan="2"} 3120' in lines, [x for x in lines if "fan" in x]
    assert not [line for line in lines if line.startswith('ringtop_node_fan_rpm{node="a",fan="1"}')]
    assert 'ringtop_node_fan_mean_rpm{node="a"} 3120' in lines  # the mean of the one fan that was read
    assert 'ringtop_node_fan_rpm{node="b",fan="1"} 3110' in lines  # the other Spark as ever


def test_no_figure_of_the_table_stands_for_a_reading_that_is_none_or_missing():
    """Every reading of a moment taken away, once as None and once with its key: what is left names the state of
    the engine and the run, which are words and not readings, and says that the power of no Spark was read, which
    is counted and not unread. Nothing else."""

    def none(part, key):
        part[key] = None

    for take in (none, dict.pop):
        moment = small()
        for part in (moment["engine"], moment["run"], moment["identity"], *moment["nodes"], *moment["edges"]):
            for key in [key for key in part if key not in ("name", "state", "source", "from", "to", "group")]:
                take(part, key)
        take(moment, "t")
        assert told(moment) == [
            'ringtop_engine_state{state="writing"} 1',
            "ringtop_cluster_gpu_power_read_nodes 0",
            'ringtop_run_info{name="Prefill sweep",source="command"} 1',
        ], (take, told(moment))


def test_what_is_no_finite_number_has_no_line():
    """nan and inf are no readings, nor is a number as text, a list or a whole number no float can hold (a run
    source can name any). None of them is told, and none ends the list with an error."""
    gone = ('ringtop_node_gpu_power_watts{node="a"}', "ringtop_engine_output_tokens_per_second", "ringtop_run_done")
    for odd in (float("nan"), float("inf"), -float("inf"), "12", [1], {"a": 1}, 10**400):
        moment = small()
        moment["nodes"][0]["w"] = moment["engine"]["tok_s"] = moment["run"]["done"] = odd
        lines = told(moment)
        assert not [line for line in lines if line.startswith(gone)], (odd, lines)
        assert len(lines) == len(told(small())) - 3 and all(SAMPLE.fullmatch(line) for line in lines), (odd, lines)
        # and it is no part of a sum: the power of the Sparks is that of the one Spark that has a reading
        assert "ringtop_cluster_gpu_power_watts 62.2" in lines and "ringtop_cluster_gpu_power_read_nodes 1" in lines
    moment = small()  # a number a float still holds is one, until the factor to its base unit carries it past that
    moment["nodes"][0]["mem_total_gb"] = moment["run"]["done"] = 1e300
    lines = told(moment)
    assert "ringtop_run_done_items 1e+300" in lines and all(SAMPLE.fullmatch(line) for line in lines), lines
    assert not [line for line in lines if line.startswith('ringtop_node_memory_total_bytes{node="a"}')], lines


def test_a_spark_nobody_reached_yet_has_one_line_that_says_so():
    """Before its first sample a Spark has no key of a reading on its node. The list says that it is not live and
    nothing else of it, the engine nobody read is offline, and no run is a run of source none."""
    hub = hub_for()
    lines = told(as_read(hub.view()))
    for name in ("dgx0", "dgx1", "dgx2", "dgx3"):
        assert [line for line in lines if f'"{name}"' in line] == [f'ringtop_node_live{{node="{name}"}} 0'], name
    rest = [line for line in lines if not line.startswith(("ringtop_node_live", "ringtop_moment_timestamp_seconds"))]
    assert rest == [
        "ringtop_sample_interval_seconds 2",
        'ringtop_engine_state{state="offline"} 1',
        "ringtop_cluster_gpu_power_read_nodes 0",  # counted: there are four Sparks, and the power of none was read
        'ringtop_run_info{source="none"} 1',
    ], rest


def test_a_spark_that_went_away_keeps_no_reading_only_what_it_is():
    """The last Spark of the demo is away for a quarter of a minute. The hub takes every reading off its node and
    keeps what the Spark is, its memory and the size of its disk; the list does the same. Its own ports are unread
    and have no line; the cables to it, read at their other end, still have theirs. The power of the ring is the
    sum of three Sparks and says so, and no energy per token is told of a part."""
    lines = told(played()["away"])
    assert [line for line in lines if 'node="dgx3"' in line] == [
        'ringtop_node_live{node="dgx3"} 0',
        'ringtop_node_memory_total_bytes{node="dgx3"} 143881404416',  # 134 * 2**30
        'ringtop_node_disk_total_bytes{node="dgx3"} 3996467068928',  # 3722 * 2**30
    ]
    assert [line for line in lines if line.startswith("ringtop_node_live")][:3] == [
        f'ringtop_node_live{{node="dgx{i}"}} 1' for i in range(3)
    ]
    assert 'ringtop_link_up{node="dgx0",port="f1",peer="dgx3"} 1' in lines
    assert 'ringtop_link_up{node="dgx2",port="f0",peer="dgx3"} 1' in lines
    assert "ringtop_cluster_gpu_power_read_nodes 3" in lines and power(lines)[0] == 3 and power(lines)[1] in lines
    assert not [line for line in lines if line.startswith("ringtop_engine_gpu_joules_per_token")]
    before = told(played()["writing"])
    assert (
        len([line for line in before if 'node="dgx3"' in line]) > 20
        and "ringtop_cluster_gpu_power_read_nodes 4" in before
    )


def test_the_power_of_the_sparks_is_summed_whether_or_not_the_ring_engine_answers():
    """The GPU power of the cluster is added up from the Sparks, as the page does it: over those that are live and
    whose power was read, told together with how many they are. It does not hang on the ring engine: the hub gives
    its own sum only inside a reading of that engine, and an engine that is off would take the sum away while
    every Spark is still read. The power of no Spark read is no sum, and the count then says 0, which is counted
    and not unread. A moment that holds no Spark says neither."""
    moment = small()
    moment["engine"] = {"state": "offline", "error": "Nothing answers on the vLLM port."}
    moment["nodes"] = [spark("a", w=61.6), spark("b", w=None), spark("c", w=62.2), spark("d", live=False, w=70.0)]
    lines = told(moment)
    assert "ringtop_cluster_gpu_power_watts 123.8" in lines and "ringtop_cluster_gpu_power_read_nodes 2" in lines, lines
    assert [line for line in lines if line.startswith("ringtop_engine_")] == ['ringtop_engine_state{state="offline"} 1']
    for node in moment["nodes"]:
        node["w"] = None
    lines = told(moment)
    assert "ringtop_cluster_gpu_power_read_nodes 0" in lines, lines
    assert not [line for line in lines if line.startswith("ringtop_cluster_gpu_power_watts")], lines
    moment["nodes"] = []
    assert not [line for line in told(moment) if line.startswith("ringtop_cluster_")], told(moment)
    alone = told(played()["alone"])  # the minute of the demo in which the ring engine is off and every Spark serves
    assert 'ringtop_engine_state{state="offline"} 1' in alone and "ringtop_cluster_gpu_power_read_nodes 4" in alone
    assert power(alone)[0] == 4 and power(alone)[1] in alone, power(alone)
    assert not [line for line in exposition(played()["writing"]).split("\n") if "ringtop_engine_gpu_power" in line]


def test_a_name_in_a_label_is_masked_as_the_format_asks():
    """A run source names its run as it likes: backslash, quote and line end are written with a backslash, whatever
    is no text is said as text, and a line stays one line."""
    moment = small()
    moment["run"] = {"source": "command", "name": 'a "b" \\ c\nd {e="f"} 1'}
    lines = told(moment)
    assert 'ringtop_run_info{name="a \\"b\\" \\\\ c\\nd {e=\\"f\\"} 1",source="command"} 1' in lines, lines[-3:]
    assert all(SAMPLE.fullmatch(line) for line in lines)
    moment["run"] = {"source": ["odd"], "name": 7}
    assert told(moment)[-1] == 'ringtop_run_info{name="7",source="[\'odd\']"} 1', told(moment)[-1]


def test_no_command_line_no_error_text_and_no_reply_is_in_the_list():
    """The list holds numbers, the names of the Sparks and their ports, the state of the engine, the name and the
    source of the run. What a process was started with, what an error said, the events, the image and the model
    are not in it."""
    moment = small()
    moment["run"] = {"source": "process", "name": "Benchmark running", "detail": "python3 bench.py --key SECRET"}
    moment["engine"] = {"state": "offline", "error": "Nothing answers on the vLLM port."}
    moment["nodes"][1].update(live=False, reason="ssh: connect to host port 22: Operation timed out")
    moment["nodes"][0].update(box={"env": {"HF_TOKEN": "hidden"}}, top=[{"cmd": "vllm serve /models/x"}])
    moment["events"] = [{"t": 1.0, "node": "b", "kind": "node", "text": "Unreachable: ssh said no", "level": "bad"}]
    text = exposition(moment)
    for word in ("bench.py", "SECRET", "Nothing answers", "ssh", "HF_TOKEN", "vllm serve", "some-model", "some/image"):
        assert word not in text, word
    assert 'ringtop_run_info{name="Benchmark running",source="process"} 1' in text
    for word, moment in played().items():
        text, hidden = exposition(moment), [event["text"] for event in moment["events"]]
        hidden += [node["reason"] for node in moment["nodes"] if node.get("reason")]
        hidden += [moment["identity"]["image"], moment["identity"]["config"], "Demo window", "Release suite"]
        hidden += [track["model"] for track in moment["run"].get("tracks") or []]
        assert hidden and not [said for said in hidden if said in text], (word, [s for s in hidden if s in text])
