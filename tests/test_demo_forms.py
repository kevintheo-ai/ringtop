"""The made-up clusters of the demo (--demo-form): their maps, and every form through the hub as the page gets it."""

import time

from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.demo_forms import BOARD, FORMS, demo_map, round_of
from tests.fixtures import demo_round


def test_the_ring_of_four_is_the_map_the_demo_always_had():
    """ring4, the form the demo starts with, is the map demo_hub wrote inline before there were forms: four Sparks,
    the first the head, each cabled to the next and the one before. It sends no board and every Spark the first part
    of the ring engine, as ever."""
    before = {
        "ssh_user": "demo",
        "nodes": [
            {
                "name": f"spark-{i}",
                "rank": i,
                "head": i == 0,
                "roce_peer_hcas": {str((i + 1) % 4): ["rocep1s0f0"], str((i - 1) % 4): ["rocep1s0f1"]},
            }
            for i in range(4)
        ],
    }
    assert demo_map("ring4") == before and demo_map() == before
    assert round_of("ring4") == {"boards": [], "tp": []}


def test_every_form_plays_its_round_through_the_hub_without_an_error():
    """Each form, 40 ticks of its round through view() and the deep view: as many Sparks as it has, a ring where it
    is cabled as one, the other board on the Spark that reads it and on no other, and a ring of two cabled twice to
    its one neighbour. One Spark alone has no link at all: no lane, no word of an empty socket."""
    for form, (count, cabling, _, foreign) in FORMS.items():
        views = []
        hub = demo_round(
            40, at=100.0, node_map=demo_map(form), form=form, each=lambda h, views=views: views.append(h.view())
        )
        hub.nerd_view(0, True)
        view = views[-1]
        assert len(view["nodes"]) == count and len(views) == 40, form
        assert view["cluster"]["ring"] is (cabling == "ring"), form
        boards = [(n.get("firmware") or {}).get("board") for n in view["nodes"]]
        assert boards == [BOARD if i == foreign else None for i in range(count)], (form, boards)
        if form == "one":
            assert view["edges"] == [] and view["cluster"]["nodes"][0]["head"], view["edges"]
        if form == "ring2":
            assert {(e["from"], e["to"]) for e in view["edges"]} == {(0, 1), (1, 0)}, view["edges"]
    assert parse_cluster(demo_map("switch4"))["ring"] is False


def test_in_the_form_without_a_head_the_head_is_found_on_the_spark_with_the_first_part_after_two_looks():
    """find4: a ring of four whose map names no head, and whose ring engine runs its first part on the Spark at
    place 2. Before the hub takes a head nobody sends a reading of the engine; one look every 15 s finds that Spark,
    the second sets it, and from then on its readings come and the engine writes."""
    assert [p for p in round_of("find4")["tp"]] == [f"VLLM::Worker_TP{k}" for k in (2, 3, 0, 1)]
    seen = []

    def each(hub):
        if len(seen) % 8 == 0:  # 8 ticks of 2 s: a look every 16 s
            hub.look_for_head(time.time())
        seen.append(([n["head"] for n in hub.cluster["nodes"]], len(hub.scrapes), hub.view()["engine"]["state"]))

    hub = demo_round(40, at=100.0, node_map=demo_map("find4"), form="find4", each=each)
    found = next(i for i, (flags, _, _) in enumerate(seen) if any(flags))
    assert found == 16 and all(scrapes == 0 for _, scrapes, _ in seen[:found]), seen[: found + 1]
    assert all(flags == [False, False, True, False] for flags, _, _ in seen[found:]), seen
    assert seen[-1][1] > 0 and seen[-1][2] == "writing", seen[-1]
    assert [e["node"] for e in hub.events if e["kind"] == "head"] == ["spark-2"]
