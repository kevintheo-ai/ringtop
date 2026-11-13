"""Counters that become rates: the ring ports and cables, GPU time at a limit, pressure, the slow deep readings."""

from __future__ import annotations

import time

from ringtop_parts.core.cluster import port_group
from ringtop_parts.core.figures import num, rounded

SLOW_REACH = 60.0  # seconds a counter of the readings of every 15 s may go unread and still be counted from


PORT_COUNTERS = ("tx", "rx", "err")  # what a ring port counts: 4-byte units sent and received, and its errors


def read_at(reading: dict, t: float) -> float:
    """When a reading of counters was taken: the moment it names (`t`), else `t`, the moment of the sample that
    carries it (a sampler from before readings named their own). A rate over the moment of the sample is too high
    by as much as the reading came later than in the sample before, and the next one too low."""
    at = num(reading.get("t"))
    return t if at is None else at


def last_read(fabric: dict, basis: dict, t: float) -> dict:
    """What the next sample of a Spark counts its ring ports from: for every device the value each counter was last
    read with, and when (read_at). A counter that was not read this time keeps the reading it has, so a sample
    nobody read does not cost the traffic of the next one as well. A device the sample names no more has none."""
    return {
        device: {
            **basis.get(device, {}),
            **{
                key: (read_at(counters, t), counters[key])
                for key in PORT_COUNTERS
                if num(counters.get(key)) is not None
            },
        }
        for device, counters in fabric.items()
    }


def port_gain(counters: dict, old: dict, key: str, t: float, reach: float) -> tuple[float | None, float]:
    """What one counter of a port gained since it was last read, and over how many seconds. No gain where it was
    not read now or never before, and across more than `reach` seconds: a mean over a hole is no traffic of now."""
    at, before = old.get(key, (t, None))
    after, dt = num(counters.get(key)), t - at
    return (after - before if after is not None and before is not None and 0 < dt <= reach else None), dt


def port_groups(fabric: dict, basis: dict, t: float, reach: float) -> dict[str, dict]:
    """The ring ports of one Spark by cable, from their counters and what each counter last read (`basis`, see
    last_read): Gb/s each way, whether the link is up, its line rate and the errors that are new. The two PCIe
    functions of one port are one cable. Its traffic is the gain of both: None while one of them was not read,
    has no reading before, or fell back. It is up when one function says so, and unknown (None) rather than down
    when none does and one could not say. Its line rate is the one a function names, None where none could read
    it. Its new errors are what its functions were read to gain, each since its own last reading and whatever the
    other could say: a rise that was read is not lost to a twin that was not. `err_read` says whether the count of
    every function was read: only then no gain is a count of none. Each function counts over the moment its
    counters were read (read_at)."""
    groups: dict[str, dict] = {}
    for device, counters in fabric.items():
        group = groups.setdefault(
            port_group(device), {"tx": 0.0, "rx": 0.0, "up": False, "rate": None, "err": 0, "err_read": True}
        )
        up, old = counters.get("up", False), basis.get(device, {})
        group["up"] = True if up or group["up"] else None if None in (up, group["up"]) else False
        rate = num(counters.get("rate"))
        if rate is not None:  # both functions name the same cable
            group["rate"] = max(group["rate"] or 0.0, rate)
        for key in ("tx", "rx"):
            gain, dt = port_gain(counters, old, key, read_at(counters, t), reach)
            known = group[key] is not None and gain is not None and gain >= 0
            group[key] = group[key] + gain * 4 * 8 / dt / 1e9 if known else None  # port_*_data counts 4 bytes
        errors, before = num(counters.get("err")), old.get("err", (t, None))[1]
        group["err_read"] = group["err_read"] and errors is not None
        if errors is not None and before is not None:
            group["err"] += max(0, errors - before)
    return groups


def counted(row: dict, *keys: str) -> float | None:
    """What several counters of one cable add up to. None unless each of them was read: a sum that leaves one out is
    not the count, and no counter at all is no count of zero."""
    values = [num(row.get(key)) for key in keys]
    return sum(values) if None not in values else None


def memory_block(memory: dict | None, vm: dict) -> dict:
    """The deep memory reading of one Spark as its node holds it: where its memory went in GiB, big free blocks, OOM
    kills, and what the kernel did per second to find memory (`vm`: the rates of its counters). Every field is None
    where the reading is missing: the one before does not stand in its place."""
    memory = memory or {}
    return {
        "memory": {k: rounded(v / 2**30, 2) for k, v in memory["mem"].items()} if memory else None,
        "blocks_16m": memory.get("blocks_16m"),
        "free_big_gb": rounded(memory["free_big"] / 2**30, 1) if memory else None,
        "oom_kills": (memory.get("vm") or {}).get("oom_kill"),
        "compact_scan_s": rounded(vm.get("compact_migrate_scanned"), 0),
        "migrate_fail_s": rounded(vm.get("pgmigrate_fail"), 1),
        "alloc_stall_s": rounded(vm.get("allocstall"), 2),
        "swap_out_s": rounded(vm.get("pswpout"), 1),
        "majfault_s": rounded(vm.get("pgmajfault"), 1),
    }


class Rates:
    """The part of the Hub that turns counters into change per second. Holds no state of its own."""

    def _fabric(self, name: str, sample: dict):
        """The ring ports of one Spark: traffic per cable since its last sample, links that went down, errors.
        Gives back what all its ports sent and received in Gb/s, each None unless every cable has that traffic:
        a sum that leaves a cable out is not what the Spark carried, and without a cable there is nothing to add.
        A port the Spark named before and names no more is down, with an event, and carries nothing known. A sample
        that names its ports as None says the reader of them failed: nobody read them, which is neither down nor
        without traffic, and each counter keeps the reading it has for the sample that reads it again."""
        t, fabric = sample.get("t", time.time()), sample.get("fabric", {})
        if fabric is None:
            for key, port in self.ports.items():
                if key[0] == name:
                    port.update(tx=None, rx=None, up=None, rate=None, err_read=False)
            return None, None
        basis = self.previous.get(name) or {}
        self.previous[name] = last_read(fabric, basis, t)
        groups = port_groups(fabric, basis, t, self.reach)

        def total(key: str) -> float | None:
            carried = [group[key] for group in groups.values()]
            return sum(carried) if carried and None not in carried else None

        sent, received = total("tx"), total("rx")
        now = time.time()
        for group_name, group in groups.items():
            self._port(name, group_name, group, now)
        for key, port in self.ports.items():
            if key[0] == name and key[1] not in groups:  # its device is gone from a Spark that answers: that link
                if port.get("was_up"):  # is down, said once. What it carries and how fast it runs, nobody reads
                    self.event(now, name, "link", f"Link {key[1]} went down", "bad")
                port.update(tx=None, rx=None, up=False, rate=None, was_up=False, err_read=False)
        return sent, received

    def _port(self, name: str, group_name: str, group: dict, now: float) -> None:
        """One cable of one Spark: its state for the ring, its traffic as curves where it is known, an event when
        the link went down or counted errors. Down is said of a state that was read, against the state last read
        (`was_up`): a state nobody read is no news, and does not hide the news of the reading after it. Errors a
        function was read to gain are said, also where the count of its twin was not read. Whether every count
        was read this time is kept (`err_read`): without it nobody knows that there are no new ones."""
        port = self.ports.setdefault((name, group_name), {"err_at": None})
        if port.get("was_up") and group["up"] is False:
            self.event(now, name, "link", f"Link {group_name} went down", "bad")
        if group["up"] is not None:
            port["was_up"] = group["up"]
        port.update(tx=group["tx"], rx=group["rx"], up=group["up"], rate=group["rate"])
        port["err_read"] = group["err_read"]
        self.remember(f"{name}.{group_name}.tx", now, group["tx"])  # a first look has no traffic: nothing is kept
        self.remember(f"{name}.{group_name}.rx", now, group["rx"])
        if group["err"]:
            if not port["err_at"] or now - port["err_at"] > 120:
                self.event(now, name, "link", f"Errors on link {group_name}", "warn")
            port["err_at"] = now

    def _rate(self, scope: tuple, t: float, values: dict, reach: float | None = None) -> dict:
        """Change per second of these counters, each since its own last reading: one that was not read this time
        keeps the reading it has, so the next one still has something to count from. Nothing for a counter that went
        back (a restart), for a clock that did not move on, and across more than `reach` seconds without a reading
        (as far as the hub bridges a hole, unless told otherwise): a mean over a hole is no rate of now. A reading
        that names when it was read (`t` among the values) is counted from that moment (read_at); `t` is no counter.
        Such a reading with the moment of the one counted last came once more (a sample copies the line of
        nvidia-smi until a new one is printed): it is no new reading and gives what that one gave."""
        basis, reach, out = self.counters.setdefault(scope, {}), reach or self.reach, {}
        named, t = num(values.get("t")) is not None, read_at(values, t)
        if named and basis.get("t", (None, None))[0] == t:
            return dict(basis["t"][1])
        for key, value in values.items():
            if value is None or key == "t":
                continue
            at, old = basis.get(key, (t, None))
            if old is not None and value >= old and 0 < t - at <= reach:
                out[key] = (value - old) / (t - at)
            basis[key] = (t, value)
        if named:
            basis["t"] = (t, out)  # beside the counters: the moment of this reading and what it gave
        return out

    def _gpu_time(self, name: str, node: dict, gpu: dict, sample: dict) -> None:
        """nvidia-smi counts microseconds spent at each limit; per second that is the share of time, over the moments
        nvidia-smi printed its lines (`t`), not the moments of the samples that copied them."""
        rate = self._rate(
            (name, "gpu"),
            sample.get("t", time.time()),
            {k: gpu.get(k) for k in ("cap_us", "sw_therm_us", "hw_therm_us", "brake_us", "t")},
        )
        share = {key: rounded(value / 1e4, 2) for key, value in rate.items()}
        # slowed down by software or by hardware: the sum of the two that could be counted. Neither counted (a reset
        # of the GPU, not read): no share, which is not the same as none of the time
        thermal = [rate[key] for key in ("sw_therm_us", "hw_therm_us") if key in rate]
        node.update(
            cap_pct=share.get("cap_us"),
            therm_pct=rounded(sum(thermal) / 1e4, 2) if thermal else None,
            brake_pct=share.get("brake_us"),
        )

    def _pressure(self, name: str, node: dict, sample: dict) -> None:
        """Stall time of the whole Spark and of the engine's container as shares of time, and what the container uses of
        disk, CPU and memory, each over the moment it was read. Without a container none of its figures lingers."""
        t = sample.get("t", time.time())
        share = self._rate((name, "psi"), t, sample.get("psi") or {})

        def part(key: str, values: dict = share):
            return rounded(values[key] / 1e4, 2) if key in values else None

        node.update(
            psi_cpu=part("cpu_some"), psi_io=part("io_some"), psi_io_full=part("io_full"), psi_mem=part("memory_some")
        )
        box = sample.get("cg")
        if not box:  # the container is gone: no last value lingers in the table, and no counter for the next one
            self.counters.pop((name, "cg"), None)
            for key in (
                "eng_read_mb",
                "eng_write_mb",
                "eng_iops",
                "eng_cores",
                "eng_throttled",
                "eng_mem_gb",
                "eng_peak_gb",
                "eng_oom",
                "eng_pids",
                "eng_psi_cpu",
                "eng_psi_io",
            ):
                node[key] = None
            return
        rate = self._rate(
            (name, "cg"),
            t,
            {
                **box["disk"],
                "cpu_us": box["cpu_us"],
                "throttled": box["throttled"],
                "t": box.get("t"),  # its pressure files are read with it and count over the same moment
                **{"psi_" + k: v for k, v in box["psi"].items() if k != "t"},
            },
        )
        node.update(
            eng_read_mb=rounded(rate["rbytes"] / 1e6, 1) if "rbytes" in rate else None,
            eng_write_mb=rounded(rate["wbytes"] / 1e6, 1) if "wbytes" in rate else None,
            eng_iops=rounded(rate.get("rios"), 0),
            eng_cores=rounded(rate["cpu_us"] / 1e6, 2) if "cpu_us" in rate else None,
            eng_throttled=box["throttled"],
            eng_mem_gb=rounded(box["mem"] / 2**30, 2) if box.get("mem") is not None else None,
            eng_peak_gb=rounded(box["peak"] / 2**30, 2) if box.get("peak") is not None else None,
            eng_oom=box["oom"],
            eng_pids=box["pids"],
            eng_psi_cpu=part("psi_cpu_some", rate),
            eng_psi_io=part("psi_io_some", rate),
        )

    def _deep(self, name: str, node: dict, slow: dict, t: float) -> None:
        """Readings that come every 15 s: GPU fields from NVML, memory, clocks, cables, who runs on the engine's cores.
        A list the reading does not hold is None: nobody looked, which is not a list of nothing."""
        nv = slow.get("nvml") or {}
        rate = self._rate(
            (name, "nvml"),
            t,
            {k: nv.get(k) for k in ("energy_mj", "below_app_ns", "below_base_ns", "freq_acc", "af_acc")},
            SLOW_REACH,
        )
        node.update(
            energy_w=rounded(rate["energy_mj"] / 1000, 1) if "energy_mj" in rate else None,
            avg_mhz=rounded(rate["freq_acc"] / 1e9, 0) if "freq_acc" in rate else None,
            af_pct=rounded(rate["af_acc"] / rate["freq_acc"] * 100, 2)
            if rate.get("freq_acc") and "af_acc" in rate
            else None,
            below_app_pct=rounded(rate["below_app_ns"] / 1e7, 2) if "below_app_ns" in rate else None,
            c2c_links=nv.get("c2c_links"),
            c2c_up=nv.get("c2c_up"),
            c2c_err=nv.get("c2c_err"),
            clocks=slow.get("clocks"),
            perf_limited=slow.get("perf_limited"),
            intruders=slow.get("intruders"),
            irq=slow.get("irq"),
            key_threads=slow.get("key_threads"),
        )
        for key in ("energy_w", "avg_mhz", "af_pct"):
            self.remember(f"{name}.{key}", t, node.get(key))
        memory = slow.get("memory")  # None where the reading failed: then its block is empty, the old one is gone
        node.update(memory_block(memory, self._rate((name, "vm"), t, memory["vm"], SLOW_REACH) if memory else {}))
        apps = slow.get("apps")  # a reading of its own; without the list of programs their sum is not 0 GB
        node["gpu_apps_gb"] = rounded(sum(a.get("gb", 0) for a in apps), 1) if apps is not None else None
        for key in ("blocks_16m", "compact_scan_s"):
            self.remember(f"{name}.{key}", t, node.get(key))
        box = slow.get("box")
        if box:
            self.env[name] = box.pop("env", None) or {}  # stays here: the page only ever hears same or different
        else:
            self.env.pop(name, None)  # no container: its environment does not stand on in the comparison
        if slow.get("startup"):
            node["startup"] = slow["startup"]
            self.sink_ranks.pop(str(node["rank"]), None)  # a new engine counts from zero
        self._cables(name, slow.get("cables"), t)

    def _cables(self, name: str, cables: dict | None, t: float) -> None:
        """What every cable did since the last look: pause time, corrected bits, lane errors and traffic per second,
        beside the totals its counters hold. None where the cables were not read, and for a total whose counters
        the cable did not send."""
        if cables is None:
            self.cables[name] = None
            return
        out = {}
        for group, row in cables.items():
            r = self._rate((name, "cable", group), t, row, SLOW_REACH)
            paused = num(row.get("tx_global_pause_duration"))
            view = {
                "stop_tx": rounded(r["tx_global_pause_duration"] / 1e4, 2) if "tx_global_pause_duration" in r else None,
                "stop_rx": rounded(r["rx_global_pause_duration"] / 1e4, 2) if "rx_global_pause_duration" in r else None,
                "pause_tx_s": rounded(r.get("tx_pause_ctrl_phy"), 1),
                "pause_rx_s": rounded(r.get("rx_pause_ctrl_phy"), 1),
                "corrected_s": rounded(r.get("rx_corrected_bits_phy"), 0),
                "lane0_s": rounded(r.get("rx_err_lane_0_phy"), 0),
                "lane1_s": rounded(r.get("rx_err_lane_1_phy"), 0),
                "gb_tx": rounded(r["tx_bytes_phy"] * 8 / 1e9, 2) if "tx_bytes_phy" in r else None,
                "gb_rx": rounded(r["rx_bytes_phy"] * 8 / 1e9, 2) if "rx_bytes_phy" in r else None,
                "pci_rd": row.get("outbound_pci_stalled_rd"),
                "pci_wr": row.get("outbound_pci_stalled_wr"),
                "uncorrectable": row.get("uncorrectable_blocks"),
                "corrected_blocks": row.get("corrected_blocks"),
                "link_down": row.get("link_down_events_phy"),
                "discards": counted(row, "rx_discards_phy", "tx_discards_phy"),
                "storm": counted(row, "tx_pause_storm_warning_events", "tx_pause_storm_error_events"),
                "pcs": row.get("rx_pcs_symbol_err_phy"),
                "crc": row.get("rx_crc_errors_phy"),
                "pause_total": row.get("tx_pause_ctrl_phy"),
                "stop_total_s": rounded(paused / 1e6, 1) if paused is not None else None,
            }
            out[group] = view
            self.remember(f"{name}.{group}.stop_pct", t, view["stop_tx"])
            self.remember(f"{name}.{group}.corrected_s", t, view["corrected_s"])
        self.cables[name] = out

    def _links(self, name: str, links: dict | None) -> None:
        """What each link's error and pause counters did since the last look. A counter without a reading before, or
        one that went back since, has no such difference and is left out. None where the counters were not read:
        nobody knows then what moved, which is not "nothing moved", and what they are counted from goes, so the
        reading after the hole shows no difference across it."""
        if links is None:
            self.nodes[name]["links"] = None
            self.link_counts.pop(name, None)
            for key in [key for key in self.link_before if key[0] == name]:
                del self.link_before[key]
            return
        changes = {}
        for device, counters in links.items():
            before = self.link_before.get((name, device)) or {}
            changes[device] = {
                k: v - before[k]
                for k, v in counters.items()
                if v is not None and before.get(k) is not None and v >= before[k]
            }
            self.link_before[(name, device)] = counters
        self.nodes[name]["links"] = changes
        self.link_counts[name] = links
