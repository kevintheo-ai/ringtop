"""The moment as Prometheus text: one table of the figures told, and a line for each of them that was read."""

from __future__ import annotations

import math
from typing import NamedTuple

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"  # the text format this part writes, as a server names it
GIB = 2**30  # the hub divides the bytes of memory and disk by this, under keys that end in _gb
GBIT = 1e9 / 8  # bytes per second in one Gb/s: the page counts a link in bits, Prometheus counts in bytes


class Metric(NamedTuple):
    """One figure of the list: its name, gauge or counter, the rows of the moment it is read from (a key of ROWS),
    its key in such a row (None: a row that is there counts 1), the sentence a reader gets with it, and the factor
    that turns the reading into the base unit its name ends in."""

    name: str
    kind: str
    rows: str
    key: str | None
    help: str
    scale: float = 1.0


# The whole list, one figure a line: a new one is a new line here. The formatter would break every line into seven.
# fmt: off
METRICS = (
    Metric("ringtop_moment_timestamp_seconds", "gauge", "moment", "t", "When ringtop built the moment all these figures are of, in seconds since 1970."),
    Metric("ringtop_sample_interval_seconds", "gauge", "identity", "interval", "Seconds between two samples of a Spark."),
    Metric("ringtop_engine_state", "gauge", "state", None, "What the ring engine does, as the label state: writing, reading, idle, asleep or offline. Always 1."),
    Metric("ringtop_engine_output_tokens_per_second", "gauge", "engine", "tok_s", "Tokens the ring engine wrote per second, over the last 8 seconds."),
    Metric("ringtop_engine_requests_running", "gauge", "engine", "running", "Requests the ring engine works on."),
    Metric("ringtop_engine_requests_waiting", "gauge", "engine", "waiting", "Requests that wait for the ring engine."),
    Metric("ringtop_engine_kv_cache_usage_ratio", "gauge", "engine", "kv", "How full the KV cache of the ring engine is, 0 to 1."),
    Metric("ringtop_engine_prefix_cache_hit_ratio", "gauge", "engine", "prefix", "Share of prompt tokens the ring engine took from its prefix cache, 0 to 1, over the last 8 seconds (since it started where nothing was asked in between)."),
    Metric("ringtop_engine_time_to_first_token_p95_seconds", "gauge", "engine", "ttft_p95", "95th percentile of the time to the first token, over the last 5 minutes (since the engine started where that window is empty)."),
    Metric("ringtop_engine_inter_token_latency_p50_seconds", "gauge", "engine", "itl_p50", "Median time between two steps of output, over the last 5 minutes (since the engine started where that window is empty)."),
    Metric("ringtop_engine_gpu_joules_per_token", "gauge", "engine", "j_per_token", "GPU energy per token written: the GPU power of all Sparks over the tokens per second. No line while a Spark is not read or the engine writes less than one token per second."),
    Metric("ringtop_engine_requests_finished_total", "counter", "engine", "finished", "Requests the ring engine finished since it started, however they ended."),
    Metric("ringtop_engine_request_errors_total", "counter", "engine", "errors", "Requests the ring engine ended with an error since it started."),
    Metric("ringtop_engine_preemptions_total", "counter", "engine", "preemptions", "Times the ring engine set a request aside to make room, since it started."),
    Metric("ringtop_cluster_gpu_power_watts", "gauge", "cluster", "watts", "GPU power of the Sparks whose power was read, summed. ringtop_cluster_gpu_power_read_nodes says of how many."),
    Metric("ringtop_cluster_gpu_power_read_nodes", "gauge", "cluster", "read", "How many Sparks ringtop_cluster_gpu_power_watts is the sum of: those that are live and whose power was read."),
    Metric("ringtop_node_live", "gauge", "node", "live", "1 while the Spark sends samples, 0 while it does not."),
    Metric("ringtop_node_gpu_power_watts", "gauge", "node", "w", "GPU power the Spark draws."),
    Metric("ringtop_node_gpu_utilization_ratio", "gauge", "node", "util", "Load of the GPU, 0 to 1 (the page shows percent).", 0.01),
    Metric("ringtop_node_gpu_temperature_celsius", "gauge", "node", "gpu_c", "Temperature of the GPU."),
    Metric("ringtop_node_gpu_clock_hertz", "gauge", "node", "mhz", "Clock of the GPU (the page shows MHz).", 1e6),
    Metric("ringtop_node_gpu_thermal_margin_celsius", "gauge", "node", "tlimit", "Degrees left before the GPU starts to slow itself down."),
    Metric("ringtop_node_cpu_utilization_ratio", "gauge", "node", "cpu_pct", "Share of time the CPUs were busy since the sample before, 0 to 1 (the page shows percent).", 0.01),
    Metric("ringtop_node_board_temperature_celsius", "gauge", "node", "cpu_c", "The warmest thermal zone of the Spark, which the page calls the board temperature."),
    Metric("ringtop_node_memory_available_bytes", "gauge", "node", "mem_free_gb", "Memory free for use (MemAvailable of the kernel), from a reading rounded to 0.1 GiB.", GIB),
    Metric("ringtop_node_memory_total_bytes", "gauge", "node", "mem_total_gb", "Memory of the Spark, from a reading rounded to 1 GiB.", GIB),
    Metric("ringtop_node_fan_mean_rpm", "gauge", "node", "fan", "Mean speed of the fans of the Spark."),
    Metric("ringtop_node_fan_rpm", "gauge", "fan", "rpm", "Speed of one fan, the fans numbered from 1 in the order the Spark lists them."),
    Metric("ringtop_node_ssd_temperature_celsius", "gauge", "node", "nvme_c", "Temperature of the SSD."),
    Metric("ringtop_node_nic_temperature_celsius", "gauge", "node", "nic_c", "Temperature of the network card behind the ring ports."),
    Metric("ringtop_node_disk_read_bytes_per_second", "gauge", "node", "disk_read", "What the NVMe drives read since the sample before (the page shows MB/s).", 1e6),
    Metric("ringtop_node_disk_write_bytes_per_second", "gauge", "node", "disk_write", "What the NVMe drives wrote since the sample before (the page shows MB/s).", 1e6),
    Metric("ringtop_node_disk_free_bytes", "gauge", "node", "disk_free_gb", "Free space on the root file system, from a reading rounded to 1 GiB.", GIB),
    Metric("ringtop_node_disk_total_bytes", "gauge", "node", "disk_total_gb", "Size of the root file system, from a reading rounded to 1 GiB.", GIB),
    Metric("ringtop_node_gpu_power_cap_time_ratio", "gauge", "node", "cap_pct", "Share of time the GPU spent at its power cap since the last sample that read its counter (as a rule the one before), 0 to 1.", 0.01),
    Metric("ringtop_node_gpu_thermal_slowdown_time_ratio", "gauge", "node", "therm_pct", "Share of time the GPU slowed down for heat since the last sample that read its counters (as a rule the one before), 0 to 1.", 0.01),
    Metric("ringtop_node_gpu_power_brake_time_ratio", "gauge", "node", "brake_pct", "Share of time the power brake held the GPU back since the last sample that read its counter (as a rule the one before), 0 to 1.", 0.01),
    Metric("ringtop_node_ring_traffic_bytes_per_second", "gauge", "node", "net", "What all ring ports of the Spark sent and received together (the page shows Gb/s: bytes times 8 over 1e9).", GBIT),
    Metric("ringtop_link_transmit_bytes_per_second", "gauge", "link", "gbps", "What the Spark sends through this ring port (the page shows Gb/s: bytes times 8 over 1e9).", GBIT),
    Metric("ringtop_link_receive_bytes_per_second", "gauge", "link", "rx", "What the Spark receives through this ring port (the page shows Gb/s: bytes times 8 over 1e9).", GBIT),
    Metric("ringtop_link_up", "gauge", "link", "up", "1 while the link of this ring port is up, 0 while it is down."),
    Metric("ringtop_link_capacity_bytes_per_second", "gauge", "link", "capacity", "Line rate of the link (200 Gb/s is 25e9 bytes per second).", GBIT),
    Metric("ringtop_link_recent_errors", "gauge", "link", "errors", "1 while this ring port counted new errors within the last two minutes, else 0."),
    Metric("ringtop_run_info", "gauge", "run_info", None, "The run ringtop shows, as the labels name and source: command, lab, process, engine, error or none. Always 1."),
    Metric("ringtop_run_done_items", "gauge", "run", "done", "How far the run is, in whatever its source counts."),
    Metric("ringtop_run_total_items", "gauge", "run", "total", "How much the run has to do in all, in whatever its source counts."),
)
# fmt: on


def part(name: str):
    """Reads from one part of the moment that is a single object without labels: its identity, the engine, the run."""
    return lambda moment: [({}, moment.get(name) or {})]


def engine_state(moment: dict) -> list:
    """The state of the ring engine as a label, where the moment names one."""
    state = (moment.get("engine") or {}).get("state")
    return [({"state": state}, {})] if state else []


def run_info(moment: dict) -> list:
    """The run as two labels: its source, and its name where it has one. Nothing else of a run becomes a label: what
    it says beside its name may be a command line."""
    run = moment.get("run") or {}
    return [({"name": run.get("name"), "source": run["source"]}, {})] if run.get("source") else []


def cluster(moment: dict) -> list:
    """The Sparks taken together, added up as the page adds them: the GPU power of those that are live and whose
    power was read, and how many they are. The count is told where it is 0 too, a sum of none is not; a moment
    that holds no Spark has neither."""
    sparks = moment.get("nodes") or []
    powers = [reading(node.get("w"), 1.0) for node in sparks if node.get("live")]
    read = [watts for watts in powers if watts is not None]
    return [({}, {"watts": sum(read) if read else None, "read": len(read)})] if sparks else []


def nodes(moment: dict) -> list:
    """Every Spark, told apart by its name."""
    return [({"node": node.get("name")}, node) for node in moment.get("nodes") or []]


def fans(moment: dict) -> list:
    """Every fan of every Spark whose fans were read, numbered from 1 in the order the Spark lists them."""
    return [
        ({"node": node.get("name"), "fan": str(number)}, {"rpm": rpm})
        for node in moment.get("nodes") or []
        for number, rpm in enumerate(node.get("fans") or [], 1)
    ]


def links(moment: dict) -> list:
    """Every ring port of every Spark: the Spark, its port, and the Spark at the other end of the cable where the
    node map names it."""
    names = {node.get("rank"): node.get("name") for node in (moment.get("cluster") or {}).get("nodes") or []}
    return [
        ({"node": names.get(edge.get("from")), "port": edge.get("group"), "peer": names.get(edge.get("to"))}, edge)
        for edge in moment.get("edges") or []
    ]


# where the figures of the table are read from: each gives the rows of a moment as (labels, the readings of that row)
ROWS = {
    "moment": lambda moment: [({}, moment)],
    "identity": part("identity"),
    "engine": part("engine"),
    "state": engine_state,
    "cluster": cluster,
    "node": nodes,
    "fan": fans,
    "link": links,
    "run": part("run"),
    "run_info": run_info,
}


def reading(value, scale: float) -> float | None:
    """A reading in the base unit of its figure, a yes or a no as 1 or 0. None where there is nothing to tell: it
    was not read, it is no number, or no finite one (a run source can name a whole number no float holds)."""
    if not isinstance(value, (bool, int, float)):
        return None
    try:
        told = float(value) * scale
    except OverflowError:
        return None
    return told if math.isfinite(told) else None


def masked(text) -> str:
    """The value of a label as the text format asks: backslash, quote and line end written with a backslash."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def line(name: str, labels: dict, value: float) -> str:
    """One line of the list: the figure, the labels that are known, and the number in 15 digits, which is all of a
    reading and none of the noise a product of two floats ends in."""
    said = ",".join(f'{key}="{masked(text)}"' for key, text in labels.items() if text is not None)
    return f"{name}{{{said}}} {value:.15g}" if said else f"{name} {value:.15g}"


def exposition(moment: dict) -> str:
    """The moment as Prometheus text, format 0.0.4: for every figure of the table that has a reading its HELP, its
    TYPE and one line per reading. What was not read has no line: unknown is never told as 0."""
    out = []
    for metric in METRICS:
        told = []
        for labels, row in ROWS[metric.rows](moment):
            value = 1.0 if metric.key is None else reading(row.get(metric.key), metric.scale)
            if value is not None:
                told.append(line(metric.name, labels, value))
        if told:
            out += [f"# HELP {metric.name} {metric.help}", f"# TYPE {metric.name} {metric.kind}", *told]
    return "".join(text + "\n" for text in out)
