"""Made-up samples for a ring that is not there: one round of every state, through the same path as real nodes."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import ClassVar

from ringtop_parts.core import demo_faults
from ringtop_parts.core.demo_engine import run_word
from ringtop_parts.core.demo_forms import round_of
from ringtop_parts.core.demo_node import node_sample
from ringtop_parts.core.hub import Hub


@dataclass
class Round:
    """The made-up ring at one tick: what the round plays right now, and the counters every sample is read off."""

    names: list
    interval: float
    start: float  # when second 0 of the round was
    now: float = 0.0
    t: float = 0.0  # the second of the round
    phase: str = "idle"
    alone: bool = False  # the ring engine is off and every Spark serves by itself
    serving: bool = False  # the ring engine reads prompts or writes
    rate: float = 0.0  # tokens per second the ring engine writes
    tx: float = 0.0
    rx: float = 0.0
    pauses: int = 0
    acks: int = 0
    sectors_read: int = 0
    sectors_written: int = 0
    generated: float = 0.0
    prompts: float = 0.0
    drafts: float = 0.0
    accepted: float = 0.0
    finished: float = 0.0
    cached: float = 0.0
    steps_done: float = 0.0
    joules: float = 0.0
    buckets: dict = field(default_factory=lambda: {"0.1": 0.0, "0.5": 0.0, "1": 0.0, "5": 0.0, "+Inf": 0.0})
    own_tokens: list = field(default_factory=list)  # of the engine each Spark runs on its own
    own_done: list = field(default_factory=list)
    boards: list = field(default_factory=list)  # the board each Spark reads; empty: none sends one (demo_forms.py)
    tp: list = field(default_factory=list)  # each Spark's part of the ring engine; empty: every one the first part

    def __post_init__(self) -> None:
        """Every Spark starts its own counters at zero."""
        self.own_tokens, self.own_done = [0.0] * len(self.names), [0.0] * len(self.names)

    def advance(self, now: float, t: float, phase: str) -> None:
        """Moves every counter of the ring engine, the ring and the disks on by one tick of this phase."""
        self.now, self.t, self.phase = now, t, phase
        self.alone, self.serving = phase == "tracks", phase in ("reading", "writing")
        self.rate = 0.0
        if phase == "writing":
            self.rate = 310 + 60 * math.sin(t / 7) + 25 * math.sin(t * 1.7)
        self.generated += self.rate * self.interval
        self.joules += (24 + 24 * (phase != "idle")) * self.interval
        self.steps_done += self.rate / 3.1 * self.interval
        self.drafts += self.rate * 0.9 * self.interval
        self.accepted += self.rate * 0.55 * self.interval
        if self.serving:
            self.prompts += 400 * self.interval
            self.cached += 290 * self.interval
            self.finished += 0.5
            for le, part in (("0.1", 0.05), ("0.5", 0.3), ("1", 0.45), ("5", 0.5), ("+Inf", 0.5)):
                self.buckets[le] += part
        gbps = {"reading": 96.0, "writing": 18.0 + self.rate / 40}.get(phase, 0.002)  # alone, nothing crosses the ring
        self.tx += gbps * 1e9 / 8 / 4 * self.interval
        self.rx += gbps * 1e9 / 8 / 4 * self.interval
        self.sectors_read += int({"reading": 2400e6, "writing": 40e6}.get(phase, 0) / 512 * self.interval)
        self.sectors_written += int((6e6 if phase == "writing" else 0) / 512 * self.interval)


class Demo(threading.Thread):
    """Made-up samples through the same path as real nodes: every state of the ring engine in four minutes, then a
    minute in which the ring engine is off and every Spark serves alone."""

    RING = 240.0  # the part of the round the ring engine plays
    ROUND = 300.0
    STEPS: ClassVar[list[str]] = [
        "Short prompts",
        "Long prompts",
        "Eight streams",
        "Prefill sweep",
        "Stall probe",
        "Quality gate",
    ]
    # what each Spark serves in the last minute: model, tokens/s, requests at once, job and its cases. The head runs
    # something outside vLLM, which nobody can ask for a speed
    TRACKS = (
        ("model-65b", None, 1.0, "Long documents", 24),
        ("mistral-small-4", 44.0, 4.0, "Short replies", 30),
        ("sensenova-c2v", 29.0, 2.0, "Lists", 7),
        ("nemotron-3.5-super-vl", 61.0, 1.0, "Forms", 30),
    )

    def __init__(self, hub: Hub, at: float = 0.0, faults: bool = False, form: str = "ring4"):
        """Takes the Hub to feed, the second of the round to start with, whether the round plays the faults
        of demo_faults.py on top (then in place of the quarter of a minute the last Spark is away), and the made-up
        cluster the hub was given (demo_forms.py): what its Sparks show beyond the ring of four."""
        super().__init__(daemon=True)
        self.hub, self.at, self.faults, self.form = hub, at, faults, form  # at: the second of the round it starts with
        self.halt = threading.Event()  # set, the round ends: a check that started it can stop it again

    def phase(self, t: float) -> str:
        """What the made-up cluster does at a second of the round: idle, reading, writing, or tracks when the ring
        engine is off and every Spark serves alone."""
        if t >= self.RING:
            return "tracks"
        if t < 15 or t >= 215:
            return "idle"
        return "reading" if t < 30 or 130 <= t < 142 else "writing"

    def run(self) -> None:
        """Plays the round until it is halted: every tick the counters move on, every Spark sends its sample (the
        last one cannot be reached for a quarter of a minute; the one the hub takes for the head sends the readings
        of the ring engine), and the run source says what is running. With
        `faults`, who is away, what a sample holds and whether a run is named go by demo_faults.py as well."""
        names = [n["name"] for n in self.hub.cluster["nodes"]]
        ring = Round(names, self.hub.interval, time.time() - self.at, **round_of(self.form))
        while not self.halt.is_set():
            now = time.time()
            t = (now - ring.start) % self.ROUND
            ring.advance(now, t, self.phase(t))
            for i, name in enumerate(names):
                gone = demo_faults.away(t, i) if self.faults else name == names[-1] and 160 <= t < 175
                if gone:
                    self.hub.node_down(name, "ssh: connect to host port 22: Operation timed out")
                    continue
                track = self.TRACKS[i % len(self.TRACKS)] if ring.alone else None
                sample = node_sample(ring, i, track, self.hub.nodes[name]["head"])  # what the hub takes it for
                self.hub.ingest(name, demo_faults.spoiled(t, i, sample) if self.faults else sample)
            with self.hub.lock:
                unnamed = self.faults and demo_faults.silent(t)
                self.hub.external_run = None if unnamed else run_word(ring, self)
            self.halt.wait(self.hub.interval)
