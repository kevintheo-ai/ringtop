"""The faults the demo can play on top of its round, one after another, for whoever wants to see the messages to
a phone without a ring that is in trouble: a Spark that is away, a GPU clock stuck low under load, a fan that
stands beside its twin, a link of the ring that is down, the ring engine silent on its port with no run named.
Asked for with --demo-faults; without it nothing here is called, and the round is as it ever was."""

from __future__ import annotations

# What the waits of the messages are multiplied by while the faults play: at a twentieth, one round of five
# minutes shows the beginning and the end of all five troubles.
FAULT_PACE = 0.05
# When each fault plays, in seconds of the round (from, up to), and which Spark has it. Each lasts longer than
# its wait at that pace, and each starts later than the end of the one before is said (tests/test_demo_faults.py
# holds this table against the waits). The clock is stuck while the ring engine writes: only under load can a
# clock be seen stuck. The silence ends before the minute of single tracks, in which a lab window holds the ring.
AWAY = (20.0, 40.0, 3)
LATCH = (52.0, 80.0, 2)
FAN = (92.0, 106.0, 1)
LINK = (118.0, 132.0, 0)
SILENT = (150.0, 222.0)
STUCK_MHZ = 620  # where the stuck clock stands: far under the line that makes a latch (diagnose.LATCH_MHZ)
PORT = ("rocep1s0f0", "roceP2p1s0f0")  # the two functions of the one port that goes down


def plays(fault: tuple, t: float, i: int | None = None) -> bool:
    """Whether a fault plays at second t of the round, and on Spark number i where it is asked of one."""
    return fault[0] <= t < fault[1] and (i is None or fault[2] == i)


def away(t: float, i: int) -> bool:
    """Whether Spark number i cannot be reached at second t of the round."""
    return plays(AWAY, t, i)


def silent(t: float) -> bool:
    """Whether the ring engine is silent on its port at second t of the round, with no run named by anybody."""
    return plays(SILENT, t)


def spoiled(t: float, i: int, sample: dict) -> dict:
    """The sample of Spark number i at second t of the round with the faults of that second in it: the clock of
    its GPU far down while it works and names no reason, its first fan at zero, both functions of one ring port
    not active, and on the head no reading of the ring engine. The sample handed in is changed and given back.
    Everything else in it stays as the round plays it: the demo shows the trouble, not what would follow from
    it (a ring with a link down goes on writing here)."""
    if plays(LATCH, t, i):
        sample["gpu"]["mhz"] = STUCK_MHZ
    if plays(FAN, t, i):
        sample["sensors"]["fans"][0] = 0
    if plays(LINK, t, i):
        for device in PORT:
            sample["fabric"][device]["up"] = False
    if "engine" in sample and silent(t):  # the head's sample: it alone reads the ring engine
        sample.pop("hist", None)
        sample.update(engine=None, engine_error="Nothing answers on the vLLM port.")
    return sample
