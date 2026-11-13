"""The state the page shows: fed by the node streams, read by the web server. One class, its parts beside it."""

from __future__ import annotations

import collections
import json
import threading
import time

from ringtop_parts.core import heads
from ringtop_parts.core.figures import QUANTILE_WINDOW, RATE_WINDOW, downsample, num
from ringtop_parts.core.hub_ingest import Ingest
from ringtop_parts.core.hub_nerd import Nerd
from ringtop_parts.core.hub_own import Own
from ringtop_parts.core.hub_rates import Rates
from ringtop_parts.core.hub_runs import Runs
from ringtop_parts.core.hub_views import Views
from ringtop_parts.store import Store

HISTORY_SECONDS = 30 * 60
HISTORY_POINTS = 240  # sent once on page load; the page appends live samples after that
EVENT_KEEP = 200
LOG_KEEP = 4000
# what a Spark is, beside its fields in the cluster: the sizes of the machine and how its container started (told once
# per start). It stands while the Spark is away; everything else on its node is a reading, and does not
IS_WHAT = ("mem_total_gb", "mhz_max", "disk_total_gb", "capacity", "startup")
HEAD_WAIT = "Waiting for the head node"  # what the engine says until the head sent a word of it
# held looks for a head in a row (one every 15 s, connect/shell.py HEAD_LOOK) from which on the engine says why there
# is none: four, the same minute the readings of every 15 s stand without a new one (SLOW_KEEP in hub_ingest.py)
HELD_LOOKS = 4


class Hub(Ingest, Own, Rates, Views, Nerd, Runs):
    """Everything the page shows, fed by the node streams and read by the web server."""

    demo = False  # the demo sets it on the hub it feeds: then every moment says that no real cluster is shown

    def __init__(
        self,
        cluster: dict,
        interval: float,
        memguard_gib: float | None = None,
        shape: str | None = None,
        store: Store | None = None,
    ):
        """Starts with every node not reached yet and, given a store, with the history, events and log lines it kept."""
        self.cluster, self.interval, self.memguard_gib, self.shape = cluster, interval, memguard_gib, shape
        self.store = store
        self.lock = threading.Lock()
        self.tick_changed = threading.Condition()
        self.tick, self.payload = 0, b"{}"
        now = time.time()
        self.nodes = {n["name"]: {**n, "live": False, "reason": "Connecting", "since": now} for n in cluster["nodes"]}
        self.stays = {key for n in cluster["nodes"] for key in n} | {"live", "reason", "since", *IS_WHAT}
        # per Spark and ring device, what each of its counters last read and when: the traffic is counted from this
        self.previous: dict[str, dict[str, dict]] = {}
        self.ports: dict[tuple[str, str], dict] = {}
        keep = int(HISTORY_SECONDS / interval) + 2
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=keep))
        self.scrapes = collections.deque(maxlen=int(QUANTILE_WINDOW / interval) + 2)
        self.reach = max(3 * RATE_WINDOW, 4 * interval)  # readings further apart than this have a hole between them
        self.silence = max(15.0, 4 * interval)  # a Spark that sent nothing for this long is not shown as live
        self.heard_at: dict[str, float] = {}  # when each Spark last sent a sample
        # when each Spark last sent the readings of every 15 s, and when those of every minute, with their names
        self.slow_at, self.rare = {}, {}
        # the word of the engine, the one Spark the last look for a head took for it (core/heads.py), and how many
        # looks in a row were held while there is no head
        self.engine_error, self.head_last, self.head_held = HEAD_WAIT, None, 0
        # what the head last told about itself (container, lab queue, benchmarks, models), and when it told that
        self.info, self.info_at = {}, now
        self.external_run: dict | None = None
        self.external_error: str | None = None
        self.busy_since: float | None = None
        self.idle_since: float | None = now
        self.speed_at: float | None = None
        self.events: collections.deque = collections.deque(maxlen=EVENT_KEEP)
        self.throttled_at: dict[tuple[str, str], float] = {}
        self.latch_runs: dict[str, int] = {}  # samples in a row with a clock stuck low under load
        self.engine_state: str | None = None
        self.begin_runs()  # the run a source names as running, and the records of those that ended (hub_runs.py)
        self.logs: collections.deque = collections.deque(maxlen=LOG_KEEP)
        self.log_seq = 0
        self.link_before: dict[tuple[str, str], dict] = {}
        self.link_counts: dict[str, dict] = {}
        self.disk_before: dict[str, tuple[float, dict]] = {}
        self.counters: dict[tuple, dict] = {}  # per scope, every counter with the moment and value of its last reading
        self.cables: dict[str, dict] = {}
        self.env: dict[str, dict] = {}
        self.connections: list[dict] | None = None  # who is connected to the engine: None until the head told
        self.sink_ranks: dict[str, int] = {}
        self.own_scrapes: dict[str, collections.deque] = {}  # readings of the engine a Spark runs apart from the ring
        self.own_at: dict[str, float] = {}  # when each Spark last sent word of its own engine
        self.own_missed: dict[str, float] = {}  # since when each own engine's port is silent
        self.own_told: dict[str, str] = {}  # the model each own engine was last announced with
        self.own_model: dict[str, str] = {}  # the model behind the readings each window holds
        if store:
            for t, values in store.recent(HISTORY_SECONDS):
                for key, value in values.items():
                    self.history[key].append((t, value))
            self.events.extend(store.saved_events(EVENT_KEEP))
            self.logs.extend(store.saved_logs(LOG_KEEP))
            self.log_seq = self.logs[-1]["seq"] if self.logs else 0

    def event(self, t: float, node: str | None, kind: str, text: str, level: str = "info") -> None:
        """Notes one event, in memory and in the store. The same text for the same node at the same moment is noted
        once."""
        if not any(e["t"] == t and e["node"] == node and e["text"] == text for e in self.events):
            entry = {"t": t, "node": node, "kind": kind, "text": text, "level": level}
            self.events.append(entry)
            if self.store:
                self.store.add_event(entry)

    def remember(self, key: str, t: float, value) -> None:
        """Keeps one value of a trace, in memory and in the store. What is no finite number is not kept."""
        if num(value) is not None:
            self.history[key].append((t, round(float(value), 3)))
            if self.store:
                self.store.add(key, t, float(value))

    def node_down(self, name: str, reason: str) -> None:
        """Marks a node as not reachable and forgets what would go stale meanwhile: its counters, its own engine,
        everything about its ring ports, and every reading of its last sample."""
        with self.lock:
            self._down(name, reason, time.time())

    def _down(self, name: str, reason: str, now: float) -> None:
        """What node_down does, for a caller that holds the lock."""
        node = self.nodes[name]
        if node["live"]:
            self.event(now, name, "node", f"Unreachable: {reason}", "bad")
        if node["live"] or node["reason"] != reason:
            node.update(live=False, reason=reason, since=now)
        self.previous.pop(name, None)
        self.disk_before.pop(name, None)
        self.latch_runs.pop(name, None)
        for scope in [scope for scope in self.counters if scope[0] == name]:
            del self.counters[scope]  # every counter a rate is counted from: no mean across the absence
        node["own"] = None  # nobody knows what its own engine does meanwhile: no speed across the gap, no event
        self.own_scrapes.pop(name, None)
        self.own_missed.pop(name, None)
        for key, port in self.ports.items():
            if key[0] == name:  # nobody reads its ports meanwhile: unknown, which is neither down nor without traffic
                port.update(tx=None, rx=None, up=None, rate=None, was_up=None, err_read=False)
        self._forget(name, node)
        if node["head"]:  # with the head goes what only it tells: which container runs, what runs, who is connected
            self.info, self.connections = {}, None  # nobody reads the connections meanwhile: that is no empty list

    def _forget(self, name: str, node: dict) -> None:
        """Takes every reading off a Spark nobody reaches: on its node, and in what the hub keeps beside it (its
        cables, its link counters and what they are counted from, the environment of its container). Its last sample
        must not stand as today's. What the Spark is stays (IS_WHAT), and every field stays in its place, empty."""
        for key in node:
            if key not in self.stays:
                node[key] = None
        self.slow_at.pop(name, None)
        self.rare.pop(name, None)
        self._beside(name)

    def _beside(self, name: str) -> None:
        """Forgets what the hub keeps of a Spark beside its node, all of it from the readings of every 15 s: its
        cables, its link counters and what they are counted from, the environment of its container."""
        self.cables.pop(name, None)
        self.link_counts.pop(name, None)
        self.env.pop(name, None)
        for key in [key for key in self.link_before if key[0] == name]:
            del self.link_before[key]

    def look_for_head(self, now: float) -> tuple[str, ...]:
        """One look for the head of a map that names none (core/heads.py): takes the Spark the rules find, and says
        on the engine why there is none. Gives the names whose role changed, the old head and the new one, or none.
        Without a head, looks held for a minute say so on the engine; the next look that is not held takes that word
        off again."""
        with self.lock:
            sparks = list(self.nodes.values())
            old = next((node["name"] for node in self.cluster["nodes"] if node["head"]), None)
            head, self.head_last, word = heads.look(sparks, old, self.head_last)
            if old is None:
                self.head_held = self.head_held + 1 if heads.held(sparks) else 0
                if self.head_held >= HELD_LOOKS:
                    word = heads.WORDS["unread"]
                elif word is None and self.engine_error == heads.WORDS["unread"]:
                    word = HEAD_WAIT
            if word is not None:
                self.engine_error = word
            if head == old:
                return ()
            self._set_head(head, now)
            return tuple(name for name in (old, head) if name)

    def set_head(self, name: str, now: float) -> None:
        """Takes another Spark for the head, as if the old one went away: the flag moves on the map and on the
        Sparks, what only the head told is forgotten, the engine waits for the new one, and an event names it."""
        with self.lock:
            self._set_head(name, now)

    def _set_head(self, name: str, now: float) -> None:
        """What set_head does, for a caller that holds the lock. The readings of the engine go with the old head: the
        window of its speed begins anew."""
        for node in (*self.cluster["nodes"], *self.nodes.values()):
            node["head"] = node["name"] == name
        self.info, self.connections = {}, None
        self.scrapes.clear()
        self.busy_since = self.idle_since = None
        self.engine_error = HEAD_WAIT
        self.event(now, name, "head", heads.WORDS["found"])

    def silent_nodes(self, now: float) -> None:
        """A Spark that is connected and has sent nothing for a while is not live: its last figures must not stand
        as today's. Its sampler may hang while SSH still answers. The stream is left alone (a second sampler beside
        a hanging one would ask twice), and the next sample makes the Spark live again."""
        for name, node in self.nodes.items():
            if node["live"] and now - self.heard_at.get(name, now) > self.silence:
                self._down(name, f"No sample for {self.silence:.0f} s", now)

    def note_changes(self, engine: dict, run: dict) -> None:
        """Turns what changed since the last look into events: the engine stopped or serves again, a run ended or
        started, each end of a run with the cooling at that moment."""
        now, state = time.time(), engine["state"]
        if self.engine_state and state != self.engine_state and "offline" in (state, self.engine_state):
            self.event(
                now,
                None,
                "engine",
                "Stopped serving" if state == "offline" else "Serving again",
                "bad" if state == "offline" else "info",
            )
        self.engine_state = state
        self.note_run(engine, run, now)

    def note_cooling(self, now: float, word: str) -> None:
        """Two runs only compare if they ran equally warm: both ends of a run keep fans, warmest sensor and GPU clock."""
        text = self.cooling_words(word)
        if text:
            self.event(now, None, "cooling", text)

    def cooling_words(self, word: str) -> str | None:
        """The cooling of this moment in words, for one end of a run: every fan, the warmest sensor and whose it
        is, the GPU clocks. None where one of the three was read on no Spark: nothing measured, nothing claimed."""
        live = [n for n in self.nodes.values() if n["live"]]
        # every single fan: the average of a Spark would hide one that stands still
        fans = [f for n in live for f in (n.get("fans") or [n.get("fan")]) if f is not None]
        heat = [
            (v, n["name"])
            for n in live
            for v in (*(n.get("zones") or {}).values(), n.get("gpu_c"), n.get("cpu_c"))
            if v is not None
        ]
        clocks = [n["mhz"] / 1000 for n in live if n.get("mhz") is not None]
        if not fans or not heat or not clocks:
            return None

        def span(values: list, unit: str, digits: int = 0) -> str:
            low, high = f"{min(values):,.{digits}f}", f"{max(values):,.{digits}f}"
            return f"{low} {unit}" if low == high else f"{low} to {high} {unit}"

        warmest, where = max(heat)  # the three figures span all Sparks: the warmest sensor says whose it is
        return (
            f"{word}: fans {span(fans, 'RPM')}, warmest sensor {warmest:.0f} °C on {where}, "
            f"GPU clock {span(clocks, 'GHz', 2)}"
        )

    def with_history(self) -> dict:
        """The state for a page that just opened: the view, and every trace of the last half hour thinned to what a page
        draws. The traces in memory are bounded by count, so a slow one reaches further back: what is older than
        the half hour is not sent, nor is a trace without a point in it."""
        state = self.view()
        since = state["t"] - HISTORY_SECONDS
        with self.lock:
            recent = {key: [point for point in points if point[0] >= since] for key, points in self.history.items()}
        state["history"] = {key: downsample(points, HISTORY_POINTS) for key, points in recent.items() if points}
        return state

    def history_range(self, keys: list[str], t0: float, t1: float, points: int, band: bool = False) -> dict:
        """A stretch of the past in columns of `width` seconds. From disk when there is a store; without one, whatever
        is still in memory: the last sample of every column, or with `band` its mean, its highest and lowest value
        and how many samples stand behind it. A key asked for twice is answered once."""
        keys = list(dict.fromkeys(keys))  # in memory a key named twice would put every sample into its column twice
        if self.store:
            return self.store.series(keys, t0, t1, points, band)
        width = max((t1 - t0) / points, 1e-3)
        cells: dict[int, dict[str, list]] = {}
        with self.lock:
            for key in keys:
                for t, value in self.history.get(key, ()):
                    if t0 <= t <= t1:  # nodes report a moment apart: same column
                        column = min(int((t - t0) // width), points - 1)  # a sample at the very end: the last column
                        cells.setdefault(column, {}).setdefault(key, []).append(value)
        order = sorted(cells)

        def each(figure) -> dict:
            return {k: [figure(cells[i][k]) if k in cells[i] else None for i in order] for k in keys}

        out = {"t": [round(t0 + (i + 0.5) * width, 1) for i in order], "tier": "memory", "width": round(width, 3)}
        if not band:
            return {**out, "series": each(lambda values: values[-1]), "peak": {}}
        mean = each(lambda values: round(sum(values) / len(values), 3))
        count = {k: [len(cells[i].get(k, ())) for i in order] for k in keys}
        return {**out, "series": mean, "peak": each(max), "low": each(min), "n": count}

    def events_between(self, t0: float, t1: float) -> list[dict]:
        """The events of a stretch of time, in the order of their moments: from the store when there is one, else
        those still in memory. An event may be noted later than it happened; the page reads the list by time."""
        if self.store:
            db = self.store.reader()
            try:
                rows = db.execute(
                    "SELECT t, node, kind, text, level FROM events WHERE t >= ? AND t <= ? ORDER BY t LIMIT 2000",
                    (t0, t1),
                ).fetchall()
            finally:
                db.close()
            return [dict(zip(("t", "node", "kind", "text", "level"), row)) for row in rows]
        with self.lock:
            return sorted((e for e in self.events if t0 <= e["t"] <= t1), key=lambda e: e["t"])

    def replies(self) -> list:
        """The replies the run source gave with the current run, or an empty list."""
        with self.lock:
            return (self.external_run or {}).get("replies") or []

    def beat(self) -> None:
        """Builds the state once per tick and wakes every open event stream with it."""
        payload = json.dumps(self.view(), separators=(",", ":")).encode()
        with self.tick_changed:
            self.payload = payload
            self.tick += 1
            self.tick_changed.notify_all()

    def wait_tick(self, seen: int, timeout: float = 15.0):
        """Waits for the tick after the one seen: gives the new state and its number, or no state when none came in
        time."""
        with self.tick_changed:
            if self.tick == seen:
                self.tick_changed.wait(timeout)
            return (self.payload if self.tick != seen else None), self.tick
