"""The demo round: made-up samples through the same path as real nodes."""

import hashlib
import json
import time

from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.demo import Demo
from ringtop_parts.core.hub import Hub
from tests.fixtures import canon, demo_round, ring_map


def test_the_demo_shows_single_tracks_without_hardware():
    """One phase of the demo round: the ring engine is off and every Spark serves alone, one of them outside vLLM."""
    hub = Hub(parse_cluster(ring_map()), 0.05)
    demo = Demo(hub, at=Demo.ROUND - 45)  # a second of the round at which the slow readings arrive at once
    assert demo.phase(demo.ROUND - 30) == "tracks" and demo.phase(100) == "writing"
    demo.start()
    deadline, own = time.time() + 10, {}
    while time.time() < deadline and not all((own.get(n) or {}).get("tok_s") for n in ("dgx1", "dgx2", "dgx3")):
        time.sleep(0.05)
        view = hub.view()
        own = {n["name"]: n.get("own") for n in view["nodes"]}
    demo.halt.set()
    assert view["engine"]["state"] == "offline"
    assert own["dgx0"] is None  # like a second engine on the head: busy, but with no engine anybody can ask
    assert all(own[n]["state"] == "writing" and own[n]["tok_s"] > 5 for n in ("dgx1", "dgx2", "dgx3")), own
    assert len({own[n]["model"] for n in ("dgx1", "dgx2", "dgx3")}) == 3
    assert view["why"]["headline"] == "The ring engine is not serving; 4 of 4 Sparks are working on their own."
    assert [t["node"] for t in view["run"]["tracks"]] == ["dgx0", "dgx1", "dgx2", "dgx3"]


# every sample, every view of the page and every fifth deep view of a round and a bit, as one digest
GOLDEN_ROUND = "76cc6d6dacf1f79ee7c391e664ffd66bf2862cc990838b8db8d21da45ff50dc9"


def test_a_round_of_the_demo_gives_the_same_samples_and_views_as_ever():
    """The demo plays every state the hub knows: the ring engine reading and writing, a Spark that runs hot, one that
    goes away, the minute of single tracks. 320 s of it by a made-up clock give the same samples and the same views,
    byte for byte, on every run. Whoever changes what the demo plays or what the hub makes of it changes this digest
    in the same commit; whoever only moves code does not."""
    digest, seen = hashlib.sha256(), {"samples": 0, "views": 0, "deep": 0}

    def add(kind, value):
        seen[kind] += 1
        digest.update(f"{kind}\0{json.dumps(canon(value), sort_keys=True, separators=(',', ':'))}\n".encode())

    def each(hub):
        add("views", hub.view())
        if seen["views"] % 5 == 0:
            add("deep", hub.nerd_view(0, True))

    hub = demo_round(160, seen=lambda name, sample: add("samples", [name, sample]), each=each)
    said = {e["text"].split(":")[0] for e in hub.events}
    assert seen == {"samples": 632, "views": 160, "deep": 32}, seen  # one Spark is away for 8 of the 160 ticks
    assert {"Unreachable", "Reachable again", "Own engine answers", "Slowing down", "Started", "Finished"} <= said, said
    assert digest.hexdigest() == GOLDEN_ROUND, digest.hexdigest()
