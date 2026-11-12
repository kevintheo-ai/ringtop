"""What a sample brings: the figures of one Spark, its clock latch, sensors and disk, lines of the engine's log."""

from __future__ import annotations

import re
import time

from ringtop_parts.core.diagnose import LATCH_MHZ, LATCH_SAMPLES, NEAR_LIMIT_C, throttle_reasons
from ringtop_parts.core.figures import node_figures, num, restarted, rounded

SINK_LINE = re.compile(r"Sink detector, rank (\d+): (\d+) flagged rows")
SLOW_KEEP = 60.0  # seconds the readings of every 15 s stand without a new one: four of their periods
RARE_KEEP = 240.0  # and those of every minute
# the figures of a Spark that are kept as curves, sample by sample
NODE_TRACES = (
    "w",
    "gpu_c",
    "mem_free_gb",
    "net",
    "util",
    "mhz",
    "cpu_pct",
    "cpu_c",
    "disk_read",
    "disk_write",
    "fan",
    "nvme_c",
    "nic_c",
    "cap_pct",
    "therm_pct",
    "brake_pct",
    "tlimit",
    "psi_cpu",
    "psi_io",
    "eng_read_mb",
    "eng_iops",
    "eng_cores",
    "eng_mem_gb",
)


class Ingest:
    """The part of the Hub that takes a sample in. Holds no state of its own: everything lives on the Hub."""

    def ingest(self, name: str, sample: dict) -> None:
        """One sample of one Spark, taken in under the lock: its links first, then its figures and what they mean,
        the curves, what comes only now and then, the log and the engines."""
        now = time.time()
        with self.lock:
            node = self.nodes[name]
            self.heard_at[name] = now
            gpu, mem = sample.get("gpu") or {}, sample.get("mem") or {}
            sent, received = self._fabric(name, sample)
            memory = (mem.get("MemAvailable"), mem.get("MemTotal"))
            traffic = sent + received if sent is not None and received is not None else None
            self._arrived(name, node, now)
            node.update(node_figures(sample, gpu, memory, traffic, self._slowing(name, gpu, now)))
            self._latch(name, node, now)
            self._near_limit(name, node, now)
            self._disk(name, node, sample)
            self._sensors(node, sample)
            self._gpu_time(name, node, gpu, sample)
            self._pressure(name, node, sample)
            self._traces(name, node, sample, now)
            self._seldom(name, node, sample, now)
            self._log_lines(name, sample)
            self._engines(name, node, sample, now)

    def _arrived(self, name: str, node: dict, now: float) -> None:
        """A Spark that was not live sends a sample again: said once, and it is live from this moment."""
        if node["live"]:
            return
        if node["reason"] != "Connecting":
            self.event(now, name, "node", "Reachable again")
        self.own_at[name] = now  # its sampler needs a moment to find the container again: the wait starts here
        node.update(live=True, reason=None, since=now)

    def _slowing(self, name: str, gpu: dict, now: float) -> list[str] | None:
        """Why the GPU slows down right now, each reason an event. Gives the reasons back, None when not read."""
        reasons = throttle_reasons(gpu.get("events"))
        for reason in reasons or ():  # held for 90 s, so a flapping reason is one line
            if now - self.throttled_at.get((name, reason), 0) > 90:
                self.event(now, name, "clock", f"Slowing down: {reason}", "warn")
            self.throttled_at[(name, reason)] = now
        return reasons

    def _near_limit(self, name: str, node: dict, now: float) -> None:
        """A GPU that works within NEAR_LIMIT_C of its thermal limit is worth an event."""
        margin = node.get("tlimit")
        if margin is not None and margin < NEAR_LIMIT_C and (node.get("util") or 0) >= 50:
            if now - self.throttled_at.get((name, "near"), 0) > 900:  # held: a margin that hovers is one line
                self.event(now, name, "clock", f"{margin:.0f} °C from the thermal limit under load", "warn")
            self.throttled_at[(name, "near")] = now

    def _traces(self, name: str, node: dict, sample: dict, now: float) -> None:
        """Keeps what the page draws as curves: the figures of this sample, and the thermal zones by their names."""
        for key in NODE_TRACES:
            self.remember(f"{name}.{key}", now, node.get(key))
        for zone, value in (sample.get("zones") or {}).items():
            self.remember(f"{name}.zone.{zone}", now, value)
        node["zones"] = sample.get("zones") or {}

    def _seldom(self, name: str, node: dict, sample: dict, now: float) -> None:
        """What a sample carries only now and then: the readings of every minute, the open connections, the slow
        facts of every 15 s and the load of every core. The slow ones come from a thread of the sampler: when they
        stop coming while the samples go on, they stand for four of their periods and are unknown after that."""
        if "rare" in sample:
            node.update(sample["rare"])
            self.rare[name] = (now, tuple(sample["rare"]))
        elif name in self.rare and now - self.rare[name][0] > RARE_KEEP:
            node.update(dict.fromkeys(self.rare.pop(name)[1]))
        if "conn" in sample and node["head"]:  # the connections to the engine, from the head alone
            self.connections = sample["conn"]
        slow = sample.get("slow")
        if slow:
            self._slow(name, node, slow, slow.get("t") or sample.get("t", now))
            self.slow_at[name] = now
        elif now - self.slow_at.get(name, now) > SLOW_KEEP:
            self._slow_lost(name, node, now)
        if "cores" in sample:  # None where its reader failed: the load of the sample before does not stand
            node["cores"] = sample["cores"]

    def _slow_lost(self, name: str, node: dict, now: float) -> None:
        """The readings of every 15 s are too old to stand. The node is left as a reading that holds nothing leaves
        it, the hub forgets what it keeps beside the node, and the counters behind the slow rates go: the first
        reading that comes again counts no rate across the hole."""
        del self.slow_at[name]
        self._slow(name, node, {}, now)
        node["links"] = None
        self._beside(name)
        for scope in [scope for scope in self.counters if scope[0] == name and scope[1] in ("nvml", "vm", "cable")]:
            del self.counters[scope]

    def _slow(self, name: str, node: dict, slow: dict, t: float) -> None:
        """The facts a sampler reads every 15 s: deep readings, what runs on the GPU, the container, the counters of
        the links, and what the kernel and the memory guard said (each line an event). The top clock and the
        capacity of the cores are what the machine is: a reading without them leaves the ones that are known."""
        self._deep(name, node, slow, t)
        node.update(
            psi=slow.get("psi"),
            mhz_max=slow.get("mhz_max") or node.get("mhz_max"),
            mhz_app=slow.get("mhz_app"),
            apps=slow.get("apps"),  # a list the reading does not hold is None: not read, which is not empty
            top=slow.get("top"),
            box=slow.get("box"),
            threads=slow.get("threads"),
            capacity=slow.get("capacity") or node.get("capacity") or [],
        )
        self._links(name, slow.get("links"))  # None where they were not read: that is not a Spark without links
        for entry in slow.get("journal") or []:
            level = "warn" if entry["kind"] == "memguard" else "bad"
            self.event(entry["t"], name, entry["kind"], entry["text"], level)

    def _log_lines(self, name: str, sample: dict) -> None:
        """New lines of the engine's log: numbered, kept, stored, and read for what the sink detector flagged."""
        for line in sample.get("log") or []:
            self.log_seq += 1
            entry = {"seq": self.log_seq, "t": line["t"], "node": name, "text": line["text"]}
            self.logs.append(entry)
            if self.store:
                self.store.add_log(entry)
            sink = SINK_LINE.search(line["text"])
            if sink:
                self.sink_ranks[sink.group(1)] = int(sink.group(2))

    def _engines(self, name: str, node: dict, sample: dict, now: float) -> None:
        """What the sample says about the engines: the head's facts, a reading of the ring engine, and the engine
        this Spark runs on its own, or that there is none left to ask. The first two only from the Spark the hub takes
        for the head: a head that was replaced may still have lines on their way."""
        if "info" in sample and node["head"]:
            self.info, self.info_at = sample["info"], now
        if "engine" in sample and node["head"]:
            self.engine_error = sample.get("engine_error")
            if sample["engine"] is not None:
                self._engine_life(sample["engine"])
                self.scrapes.append((now, sample["engine"], sample.get("hist") or {}))
        if sample.get("own"):
            self._own(name, node, sample["own"], now)
        elif (node.get("own") or name in self.own_told) and now - self.own_at.get(name, 0.0) > max(
            15.0, 4 * self.interval
        ):
            self._own_gone(name, node, now)  # the sampler finds no engine to ask any more

    def _engine_life(self, reading: dict) -> None:
        """A reading of the ring engine after it restarted starts the window of its readings anew, as the window of
        an own engine does: no figure is counted across two lives of the engine, neither the speed nor what looks
        back five minutes, and since when it works is not known from the life before."""
        if self.scrapes and restarted(reading, self.scrapes[-1][1]):
            self.scrapes.clear()
            self.busy_since = self.idle_since = None

    def _latch(self, name: str, node: dict, now: float) -> None:
        """The GB10 clock latch: the GPU works flat out, gives no reason, and its clock stays far below normal.

        A restart does not clear it, taking the power away does (spark-ds41f, docs/recovery.md). "No reason" has to be
        read: a GPU whose reasons could not be read may be braking for heat, and that is not the latch."""
        mhz, util = node.get("mhz"), node.get("util")
        no_reason = node.get("throttle") == []
        stuck = mhz is not None and util is not None and mhz < LATCH_MHZ and util >= 50 and no_reason
        self.latch_runs[name] = self.latch_runs.get(name, 0) + 1 if stuck else 0
        latched = self.latch_runs[name] >= LATCH_SAMPLES
        if latched and not node.get("latched"):
            self.event(
                now,
                name,
                "clock",
                f"GPU clock stuck at {mhz:.0f} MHz under load: this looks like the GB10 clock latch",
                "bad",
            )
        node["latched"] = latched

    def _sensors(self, node: dict, sample: dict) -> None:
        """Fans and the temperatures of SSD, network card and Wi-Fi. A sample that does not name them changes
        nothing (an older sampler). One that names them as None says its reader failed: none of them is known then,
        and what the sample before read does not stand."""
        if "sensors" not in sample:
            return
        readings = sample["sensors"] or {}
        fans = readings.get("fans")  # each fan in the place the Spark lists it at, None for one that was not read
        read = [f for f in fans or [] if f is not None]
        node.update(
            fans=fans,
            fan=rounded(sum(read) / len(read), 0) if read else None,  # the mean of the fans that were read
            nvme_c=readings.get("nvme_c"),
            nic_c=readings.get("nic_c"),
            wifi_c=readings.get("wifi_c"),
        )

    def _disk(self, name: str, node: dict, sample: dict) -> None:
        """Free and total space, and megabytes read and written per second since the last sample. Where there is
        nothing to count from, there is no rate, and the one of before does not stand: the first sample, a counter
        that was not read, a counter that went back (a reboot, not a spike). A sample that does not name the disk
        changes nothing; one that names it as None says its reader failed, and nothing of the sample before stands
        but the size of the drive, which is what the machine is."""
        if "disk" not in sample:
            return
        disk = sample["disk"] or {}
        t = sample.get("t", time.time())
        before = self.disk_before.get(name)
        self.disk_before[name] = (t, disk)
        total = rounded(disk["total"] / 2**30, 0) if disk.get("total") is not None else None
        node.update(
            disk_free_gb=rounded(disk["free"] / 2**30, 0) if disk.get("free") is not None else None,
            disk_total_gb=total if total is not None else node.get("disk_total_gb"),
        )
        rate = {}
        if before and t > before[0]:
            for key in ("read", "write"):
                new, old = num(disk.get(key)), num(before[1].get(key))
                if new is not None and old is not None and new >= old:
                    rate[key] = (new - old) * 512 / (t - before[0]) / 1e6
        known = len(rate) == 2
        node.update(
            disk_read=rounded(rate["read"], 1) if known else None,
            disk_write=rounded(rate["write"], 1) if known else None,
        )
