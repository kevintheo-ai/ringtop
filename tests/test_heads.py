"""Which Spark is the head where the node map names none: the rules of one look, and what the hub does with them."""

import random

from ringtop_parts.core import heads
from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.hub import Hub
from tests.fixtures import engine_sample, ring_map


def spark(name, *programs, live=True):
    """One Spark as the hub holds it: live or not, and the programs on its GPU (None: they were not read)."""
    apps = None if programs == (None,) else [{"gb": 88.0, "name": p} for p in programs]
    return {"name": name, "live": live, "apps": apps}


def worker(k):
    return f"VLLM::Worker_TP{k}"


RING_OF_FOUR = [spark("dgx0", worker(0)), spark("dgx1", worker(1)), spark("dgx2", worker(2)), spark("dgx3", worker(3))]


def test_the_head_is_the_spark_with_the_first_part_of_an_engine_over_several():
    """A Spark is taken for the head where it runs the first part of an engine (…_TP0) while another runs a later
    part. In a ring of four that is the Spark with TP0. A Spark that runs an engine of its own on its one
    GPU, or the first part with nobody running a later one, is no head; two with the first part are both candidates;
    a Spark that is away, or whose programs were not read, counts neither way."""
    assert heads.candidates(RING_OF_FOUR) == ["dgx0"]
    moved = [spark("dgx0", worker(1)), spark("dgx1", worker(2)), spark("dgx2", worker(0)), spark("dgx3", worker(3))]
    assert heads.candidates(moved) == ["dgx2"]
    assert heads.candidates([spark("dgx0", worker(0)), spark("dgx1", "VLLM::EngineCore")]) == []
    assert heads.candidates([spark("dgx0", worker(0), "python3"), spark("dgx1")]) == []
    assert heads.candidates([spark("dgx0", worker(0)), spark("dgx1", worker(0)), spark("dgx2", worker(1))]) == [
        "dgx0",
        "dgx1",
    ]
    away = [spark("dgx0", worker(0)), spark("dgx1", worker(1), live=False)]
    assert heads.candidates(away) == [] and heads.candidates([*away, spark("dgx2", worker(2))]) == ["dgx0"]
    assert heads.candidates([spark("dgx0", worker(0)), spark("dgx1", None)]) == []


def test_a_head_is_set_only_after_two_looks_in_a_row_and_kept_when_nothing_is_found():
    """The head is set, or changed, once the same one Spark looked like it in two looks in a row. No candidate
    leaves a head that was found, and without one says so on the engine; several leave it as well, and without one
    say that. A look while a live Spark's programs are not known changes nothing."""
    none, several = heads.WORDS["none"], heads.WORDS["several"]
    assert heads.look(RING_OF_FOUR, None, None) == (None, "dgx0", None)  # once: remembered, not set
    assert heads.look(RING_OF_FOUR, None, "dgx0") == ("dgx0", "dgx0", None)
    assert heads.look(RING_OF_FOUR, "dgx0", "dgx0") == ("dgx0", "dgx0", None)
    idle = [spark("dgx0"), spark("dgx1"), spark("dgx2"), spark("dgx3")]
    assert heads.look(idle, None, "dgx0") == (None, None, none) and heads.look(idle, "dgx0", "dgx0")[:2] == (
        "dgx0",
        None,
    )
    two = [spark("dgx0", worker(0)), spark("dgx1", worker(0)), spark("dgx2", worker(1))]
    assert heads.look(two, None, None) == (None, None, several) and heads.look(two, "dgx2", None)[:2] == ("dgx2", None)
    unread = [*RING_OF_FOUR[:3], spark("dgx3", None)]
    assert heads.look(unread, None, "dgx0") == (None, "dgx0", None) and heads.look(unread, "dgx1", "x") == (
        "dgx1",
        "x",
        None,
    )
    moved = [spark("dgx0", worker(1)), spark("dgx1", worker(2)), spark("dgx2", worker(0)), spark("dgx3", worker(3))]
    assert heads.look(moved, "dgx0", "dgx0") == ("dgx0", "dgx2", None)  # the engine moved: one look is not enough
    assert heads.look(moved, "dgx0", "dgx2") == ("dgx2", "dgx2", None)


def headless_hub():
    node_map = ring_map()
    for node in node_map["nodes"]:
        node["head"] = False
    return Hub(parse_cluster(node_map), 2.0)


def show(hub, sparks):
    """Puts what each Spark sent on the hub: whether it is live, and its programs."""
    with hub.lock:
        for one in sparks:
            hub.nodes[one["name"]].update(live=one["live"], apps=one["apps"])


def test_the_hub_takes_a_head_it_found_as_if_the_old_one_went_away():
    """set_head: the flag moves on the map and on the Sparks, what only the head told (its facts, the connections, the
    readings of the engine) is forgotten, the engine waits for the new head, and an event says which Spark it is."""
    hub = headless_hub()
    with hub.lock:
        hub.info, hub.connections, hub.engine_error = {"kernel": "x"}, [{"port": "1"}], None
        hub.scrapes.append((1.0, {"generation_tokens_total": 1.0}, {}))
    hub.set_head("dgx2", 1000.0)
    assert [n["head"] for n in hub.cluster["nodes"]] == [False, False, True, False]
    assert [n["head"] for n in hub.nodes.values()] == [False, False, True, False]
    assert (hub.info, hub.connections, list(hub.scrapes)) == ({}, None, [])
    assert hub.engine_error == "Waiting for the head node"
    assert [(e["node"], e["kind"], e["text"]) for e in hub.events] == [("dgx2", "head", heads.WORDS["found"])]
    assert [n["head"] for n in hub.view()["cluster"]["nodes"]] == [False, False, True, False]


def test_the_hub_looks_for_a_head_and_says_on_the_engine_why_there_is_none():
    """look_for_head: no candidate puts the word on the engine; the same one in two looks sets it and gives the names
    whose role changed; the engine moving to another Spark moves the head after two more looks."""
    hub = headless_hub()
    show(hub, [spark("dgx0"), spark("dgx1"), spark("dgx2"), spark("dgx3")])
    assert hub.look_for_head(1.0) == () and hub.view()["engine"]["error"] == heads.WORDS["none"]
    show(hub, RING_OF_FOUR)
    assert hub.look_for_head(2.0) == () and hub.look_for_head(3.0) == ("dgx0",)
    assert hub.look_for_head(4.0) == ()
    show(hub, [spark("dgx0", worker(1)), spark("dgx1", worker(2)), spark("dgx2", worker(0)), spark("dgx3", worker(3))])
    assert hub.look_for_head(5.0) == () and hub.look_for_head(6.0) == ("dgx0", "dgx2")
    assert [e["node"] for e in hub.events if e["kind"] == "head"] == ["dgx0", "dgx2"]


def test_a_thousand_looks_at_flickering_readings_never_give_two_heads_or_a_change_after_one_look():
    """A thousand looks at Sparks whose programs flicker by chance: not read, none, the first part wandering between
    them, Sparks going away. Never two Sparks with the role of head, never a change after a single look, and a look
    while a live Spark's programs are not known never changes anything."""
    chance, hub = random.Random(5), headless_hub()
    names, last_found, changes = ["dgx0", "dgx1", "dgx2", "dgx3"], None, 0
    for t in range(1000):
        first = chance.choice(names) if chance.random() < 0.8 else None
        sparks = []
        for k, name in enumerate(names):
            roll = chance.random()
            programs = (None,) if roll < 0.08 else () if roll < 0.15 else (worker(0 if name == first else k + 1),)
            sparks.append(spark(name, *programs, live=chance.random() > 0.05))
        show(hub, sparks)
        before = ([n["head"] for n in hub.cluster["nodes"]], hub.head_last, hub.engine_error)
        unknown = any(s["live"] and s["apps"] is None for s in sparks)
        found = heads.candidates(sparks)
        moved = hub.look_for_head(float(t))
        assert sum(n["head"] for n in hub.cluster["nodes"]) <= 1 and sum(n["head"] for n in hub.nodes.values()) <= 1
        if unknown:
            assert moved == () and before == (
                [n["head"] for n in hub.cluster["nodes"]],
                hub.head_last,
                hub.engine_error,
            )
            continue
        if moved:
            changes += 1
            assert found == [moved[-1]] and last_found == moved[-1], (t, found, last_found, moved)
        last_found = found[0] if len(found) == 1 else None
    assert changes > 5, changes  # what this check stands on: the head did move, often


def test_the_words_of_the_head_are_plain_and_final():
    """The three sentences the look for a head may say, word for word: plain
    ASCII, no name of a machine, nothing left to fill in. The event names its Spark in its own field: the list and
    the timeline of the page put the name in front of the text already."""
    assert heads.WORDS == {
        "none": "No Spark shows TP0 of a multi-Spark engine. Name the head in --nodes.",
        "several": "Several Sparks look like the head; none chosen. Name it in --nodes.",
        "found": "Read as the head; token rate now comes from it.",
    }
    for word in heads.WORDS.values():
        assert word.isascii() and not any(mark in word for mark in ("DGX", "GB10", "{", "}")), word


def test_only_the_spark_taken_for_the_head_is_read_for_the_ring_engine():
    """The hub took readings of the ring engine, the head's facts and the connections from whichever Spark
    sent them. After the head moved, the old head's sampler still had lines on their way: the new head's window of
    the engine began with a reading of the old one. Only the Spark the hub takes for the head is read for them now;
    the others are read for everything else, as before."""
    hub = headless_hub()
    hub.set_head("dgx1", 1.0)
    late = {**engine_sample(2.0, 500.0), "info": {"kernel": "old"}, "conn": [{"port": "1"}], "cpu": 12.0}
    hub.ingest("dgx0", {**late, "engine_error": "from the old head"})
    with hub.lock:
        assert (len(hub.scrapes), hub.engine_error, hub.info, hub.connections) == (
            0,
            "Waiting for the head node",
            {},
            None,
        )
        assert hub.nodes["dgx0"]["live"]  # the old head is read for everything else
    hub.ingest("dgx1", late)
    with hub.lock:
        assert (len(hub.scrapes), hub.engine_error, hub.info, hub.connections) == (
            1,
            None,
            {"kernel": "old"},
            [{"port": "1"}],
        )
