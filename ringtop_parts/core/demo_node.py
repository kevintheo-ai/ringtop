"""One Spark of the made-up ring at one tick: the sample its sampler would send, slow facts and all."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ringtop_parts.core.demo_engine import head_engine, log_lines, own_engine

if TYPE_CHECKING:
    from ringtop_parts.core.demo import Round


def ring_ports(ring: Round, i: int) -> dict:
    """The counters of the four RDMA functions of a Spark: two cables, the second function of each carries less."""
    return {
        "rocep1s0f0": {
            "tx": int(ring.tx * (1 + i * 0.04)),
            "rx": int(ring.rx),
            "up": True,
            "rate": 200.0,
            "err": 0,
        },
        "rocep1s0f1": {
            "tx": int(ring.tx),
            "rx": int(ring.rx * (1 + i * 0.04)),
            "up": True,
            "rate": 200.0,
            "err": 0,
        },
        "roceP2p1s0f0": {"tx": int(ring.tx * 0.3), "rx": int(ring.rx * 0.3), "up": True, "rate": 200.0, "err": 0},
        "roceP2p1s0f1": {"tx": int(ring.tx * 0.3), "rx": int(ring.rx * 0.3), "up": True, "rate": 200.0, "err": 0},
    }


def fast_readings(ring: Round, i: int, busy: bool, hot: bool) -> dict:
    """What a sampler reads every tick: GPU, CPU, memory, disk, fans and sensors, thermal zones, pressure, the engine's
    cgroup and the ring ports. Spark 1 runs hot for a while, the last one turns its fans slower late in the round."""
    return {
        "t": ring.now,
        "cpu": 14 + 30 * busy,
        "cpu_c": 62 + 12 * busy + i,
        "gpu": {
            "w": (17 + 42 * busy + 7 * math.sin(ring.t / 5 + i)) * (0.9 + 0.05 * i),
            "c": 88 if hot else 49 + 13 * busy + 2 * i,
            "mhz": 1640 if hot else 2190 - 4 * i,
            "util": 96 if busy else 2,
            "limit": 120.0,
            "events": "0x0000000000000040" if hot else "0x0000000000000000",
        },
        "mem": {"MemAvailable": int((26.5 - 2 * busy - 0.6 * i) * 2**30), "MemTotal": 134 * 2**30},
        "disk": {
            "read": ring.sectors_read,
            "write": ring.sectors_written,
            "free": 2500 * 2**30,
            "total": 3722 * 2**30,
        },
        "sensors": {
            "fans": [  # late in the round the last Spark turns its fans slower than the rest
                round(rpm * (0.78 if i == len(ring.names) - 1 and 142 <= ring.t < 215 else 1))
                for rpm in (2180 + 900 * busy + 30 * i, 2240 + 900 * busy - 20 * i)
            ],
            "nvme_c": 54 + 6 * busy,
            "nic_c": 62 + 9 * busy,
            "wifi_c": 58 + 4 * busy,
        },
        "zones": {
            "TSOC": 76.0 + 8 * busy,
            "TS0P": 74.0 + 8 * busy,
            "TS1P": 64.0 + 4 * busy,
            "TUNC": 70.0 + 3 * busy,
            "TGPU": 65.0 + 6 * busy,
        },
        "psi": {
            "cpu_some": int(ring.now * 1200),
            "io_some": int(ring.now * 900),
            "io_full": int(ring.now * 800),
            "memory_some": 0,
        },
        "cg": {
            "disk": {"rbytes": int(ring.now * 8e6), "wbytes": 0, "rios": int(ring.now * 1900), "wios": 0},
            "cpu_us": int(ring.now * 2.9e6),
            "throttled": 0,
            "mem": 9 * 2**30,
            "peak": 10 * 2**30,
            "oom": 0,
            "pids": 185,
            "psi": {"cpu_some": int(ring.now * 1100), "io_some": int(ring.now * 2100), "memory_some": 0},
        },
        "fabric": ring_ports(ring, i),
    }


def engine_box(ring: Round, track: tuple | None) -> dict:
    """The container docker shows on a Spark: the ring engine (stopped while every Spark serves alone), or the engine
    the Spark runs on its own, with the port docker published for it."""
    return (
        {
            "name": "solo-" + track[0].split("-")[0],
            "image": "vllm/vllm-openai:demo",
            "image_id": "befccf0e7e40",
            "layers": "1c0f15582537",
            "running": True,
            "status": "running",
            "model": track[0],
            "published": "8001",
            "args": f"serve /models/{track[0]} --served-model-name {track[0]}",
        }
        if track and track[1]
        else {
            "name": "spark-ds41f",
            "image": "spark-ds41f:demo",
            "image_id": "79d148c2cb3e",
            "layers": "5a1e9c0b77d2",
            "cpuset": "5-9,15-19",
            "running": not ring.alone,
            "status": "exited" if ring.alone else "running",
            "config": "config/cluster.json",
            "model": "deepseek-v4.1-flash",
            "args": "--port 8888 --served-model-name deepseek-v4.1-flash --max-model-len 1048576",
        }
    )


def nvml_fields(ring: Round, i: int, busy: bool) -> dict:
    """The GPU fields only NVML offers: energy, mean clock and activity as running sums, the CPU-GPU links."""
    return {
        "energy_mj": int(ring.joules * 1000),
        "freq_acc": int(ring.now * (2190e9 - 4e9 * i)),
        "af_acc": int(ring.now * (2190e9 - 4e9 * i) * (0.015 + 0.2 * busy)),
        "below_app_ns": 0,
        "c2c_links": 8,
        "c2c_up": 8,
        "c2c_err": 0,
    }


def memory_deep(ring: Round, i: int, busy: bool) -> dict:
    """Where the unified memory went and how the kernel fights for it. Spark 2 keeps most of it as page cache and has
    few big blocks left."""
    return {
        "mem": {
            "MemTotal": 134 * 2**30,
            "MemFree": (6 + 9 * (i != 2)) * 2**30,
            "MemAvailable": 26 * 2**30,
            "Cached": (11 + 14 * (i == 2)) * 2**30,
            "AnonPages": 6 * 2**30,
            "Slab": 2 * 2**30,
        },
        "vm": {
            "compact_migrate_scanned": int(ring.now * 40000),
            "pgmigrate_fail": int(ring.now * (120 if busy else 4)),
            "allocstall": 0,
            "pswpout": 0,
            "pgmajfault": int(ring.now * 2),
            "oom_kill": 1 if i == 0 else 0,
        },
        "blocks_16m": 8 if i == 2 else 420,
        "free_big": 8 * 2**30,
    }


def key_threads(i: int) -> list:
    """The threads that decide the speed: the rank's main thread and the transport proxy."""
    return [
        {
            "comm": "VLLM::Worker_TP",
            "pct": 76.0 if i == 0 else 14.0,
            "core": 18,
            "wait": 0.04,
            "wakes": 128,
            "preempted": 4.0,
            "role": "rank main",
            "migrated": 1.3,
        },
        {
            "comm": "sparknet-proxy",
            "pct": 99.8,
            "core": 7 + i,
            "wait": 0.12,
            "wakes": 0,
            "preempted": 11.0,
            "role": "transport proxy",
            "migrated": 0.0,
        },
    ]


def cable_counters(ring: Round, i: int) -> dict:
    """The counters of both cables of one Spark. The head pauses its neighbours ten times as much, and one lane of
    the last Spark counts errors."""
    return {
        group: {
            "tx_global_pause_duration": int(ring.pauses * 66 * (10 if i == 0 else 1)),
            "rx_global_pause_duration": int(ring.pauses * 60),
            "tx_pause_ctrl_phy": ring.pauses * (10 if i == 0 else 1),
            "rx_pause_ctrl_phy": ring.pauses,
            "rx_corrected_bits_phy": int(ring.now * 400),
            "rx_err_lane_0_phy": int(ring.now * (770 if i == 3 and group == "f1" else 60)),
            "rx_err_lane_1_phy": int(ring.now * 40),
            "tx_bytes_phy": int(ring.tx * 8),
            "rx_bytes_phy": int(ring.rx * 8),
            "outbound_pci_stalled_rd": 0,
            "outbound_pci_stalled_wr": 0,
            "uncorrectable_blocks": 0,
            "corrected_blocks": int(ring.now * 10),
            "link_down_events_phy": 0,
        }
        for group in ("f0", "f1")
    }


def startup(ring: Round, i: int) -> dict:
    """How the engine's container started: when each stage was reached, and its memory budget."""
    return {
        "started": int(ring.start),
        "marks": {
            "loaded": {"at": 68},
            "free_at_start": {"at": 97, "value": str(114 - i)},
            "kv": {"at": 98},
            "ready": {"at": 111},
        },
        "memory": {
            "weights": 70.56,
            "kv_cache": 10.5,
            "workspace": 1.54,
            "cudagraph": 2.4,
            "non_torch_cuda": 16.3,
            "free_memory": 23.7,
        },
    }


def slow_facts(ring: Round, i: int, busy: bool, hot: bool, track: tuple | None) -> dict:
    """What a sampler reads every 15 s: memory pressure, clocks, what sits on the GPU, the container, threads, link
    and cable counters, deep memory, who else ran on the engine's cores."""
    return {
        "psi": 22.0 if hot else 0.0,
        "mhz_max": 3003.0,
        "apps": [{"gb": 84.2, "name": "sglang::scheduler" if i == 0 else "VLLM::EngineCore"}]
        if ring.alone
        else [{"gb": 89.4, "name": ring.tp[i] if ring.tp else "VLLM::Worker_TP0"}],
        "top": [{"gb": 5.1, "name": "VLLM::Worker_TP"}, {"gb": 1.5, "name": "vllm"}],
        "journal": [{"t": ring.now, "kind": "memguard", "text": "low headroom during steady: 8 GB left"}]
        if hot
        else [],
        "box": engine_box(ring, track),
        "threads": [
            {
                "name": "VLLM::Worker",
                "pct": 480 if busy else 8,
                "threads": 15,
                "cores": [5, 6, 7, 8, 9],
            },
            {"name": "pt_nccl_watchdg", "pct": 3, "threads": 6, "cores": []},
            {"name": "sparknet-proxy", "pct": 41 if busy else 1, "threads": 1, "cores": [15]},
        ],
        "links": {
            "rocep1s0f0": {
                "local_ack_timeout_err": ring.acks if i == 1 else 0,
                "tx_pause_ctrl_phy": ring.pauses,
            },
            "rocep1s0f1": {"local_ack_timeout_err": 0, "tx_pause_ctrl_phy": ring.pauses - ring.pauses // 15},
        },
        "capacity": [718] * 5 + [1024] * 5 + [718] * 5 + [1024] * 5,
        "mhz_app": 2418.0,
        "nvml": nvml_fields(ring, i, busy),
        "memory": memory_deep(ring, i, busy),
        "clocks": [2800] * 5 + [3880 + c for c in range(5)] + [2800] * 5 + [3890] * 5,
        "perf_limited": 0,
        "intruders": [{"name": "dockerd", "ms": 8.0}, {"name": "node", "ms": 6.5}],
        "irq": {
            "by_kind": {"timer": 26000.0, "ipi": 1600.0, "wifi": 150.0},
            "by_core": {str(c): 2800.0 for c in range(5, 10)},
        },
        "key_threads": key_threads(i),
        "cables": cable_counters(ring, i),
        "startup": startup(ring, i),
    }


def rare_readings() -> dict:
    """What a sampler reads once a minute: PCIe links, devlink health, who sets the fan speed, firmware."""
    return {
        "pcie": {
            "rocep1s0f0": {"gt": "32.0 GT/s", "x": 4, "gt_max": "32.0 GT/s", "x_max": 4, "aer": 0},
            "nvme0": {"gt": "32.0 GT/s", "x": 4, "gt_max": "32.0 GT/s", "x_max": 4, "aer": 0},
        },
        "devlink": {"reporters": 20, "unhealthy": 0, "recovered": 0},
        "cooling": [{"type": "Fan", "cur": 0, "max": 100}, {"type": "Fan", "cur": 0, "max": 100}],
        "firmware": {
            "bios": "5.36",
            "driver": "580.178.04",
            "vbios": "9A.0B.34",
            "nic_fw": "28.50.1002",
            "kernel": "demo-64k",
            "thp": "never",
            "governor": "performance",
            "swappiness": "60",
            "ssd": "Demo SSD",
            "ssd_fw": "1.0",
        },
    }


def engine_env(i: int) -> dict:
    """The environment of the engine's container as the sampler sends it: harmless settings with their value, the
    rest as a digest. One Spark logs at another level, one has another PATH."""
    return {
        "NCCL_ALGO": ["v", "Ring"],
        "VLLM_LOGGING_LEVEL": ["v", "INFO" if i != 1 else "DEBUG"],
        "HF_TOKEN": ["h", "a" * 24],
        "PATH": ["h", ("b" if i != 3 else "c") * 24],
    }


def connections() -> list:
    """Three open connections to the engine: an idle one, a request being read, one being answered."""
    return [
        {"bytes_received": 10355, "lastsnd": 9000, "lastrcv": 9000, "port": "37254"},
        {
            "bytes_sent": 1800000,
            "bytes_received": 5000,
            "lastsnd": 200,
            "lastrcv": 41000,
            "port": "37260",
        },
        {
            "bytes_sent": 3100000000,
            "bytes_received": 10000000,
            "lastsnd": 1800,
            "lastrcv": 1900,
            "port": "48210",
        },
    ]


def core_load(ring: Round, busy: bool) -> list:
    """Busy percent of the 20 cores: the engine's ten work, the others idle."""
    return [
        round((62 if busy and (5 <= c <= 9 or 15 <= c <= 19) else 4) + 20 * math.sin(ring.t / 3 + c * 0.7) * busy)
        for c in range(20)
    ]


def node_sample(ring: Round, i: int, track: tuple | None, head: bool | None = None) -> dict:
    """The whole sample of Spark number i at this tick, as a real sampler would send it. `track` is what the Spark
    serves alone in the last minute of the round, None while the ring engine plays. `head`: whether its sampler runs
    as the head and reads the ring engine; None, the first Spark does. Its board goes with the readings of every
    minute where the round names one (Round.boards)."""
    head = i == 0 if head is None else head
    busy = ring.phase != "idle"
    hot = i == 1 and 110 <= ring.t < 135
    sample = fast_readings(ring, i, busy, hot)
    if ring.t % 15 < ring.interval:
        if i == 0:
            ring.pauses += 300 if busy else 0
            ring.acks += 2 if 110 <= ring.t < 135 else 0
        sample["slow"] = slow_facts(ring, i, busy, hot, track)
        sample["rare"] = rare_readings()
        if ring.boards and ring.boards[i]:
            sample["rare"]["firmware"]["board"] = ring.boards[i]
        sample["slow"]["box"]["env"] = engine_env(i)
        if head:
            sample["conn"] = connections()
    sample["cores"] = core_load(ring, busy)
    if track and track[1]:  # its own engine answers on its published port
        sample["own"] = own_engine(ring, i, track)
    lines = log_lines(ring, i, hot)
    if lines:
        sample["log"] = lines
    if head:
        sample.update(head_engine(ring))
    return sample
