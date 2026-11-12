"""What a phone is told of: the five troubles read off a moment, each as bad, good or not known."""

import json

from ringtop_parts.core import alerts
from ringtop_parts.core.alerts import BAD, GOOD, TROUBLES, readings
from tests.fixtures import demo_round, hub_for


def spark(name="dgx1", **readings_of_it):
    """One Spark as a moment holds it: live, under load, its clock high, both fans turning."""
    node = {"name": name, "head": name == "dgx0", "live": True, "latched": False, "util": 96, "mhz": 2186}
    return {**node, "throttle": [], "fan": 3115.0, "fans": [3110, 3120], "gpu_c": 64, **readings_of_it}


def away(name="dgx1"):
    """A Spark nobody reaches, as the hub leaves it: every reading None."""
    return {
        "name": name,
        "head": name == "dgx0",
        "live": False,
        "latched": None,
        "util": None,
        "mhz": None,
        "fans": None,
    }


def moment(*nodes, engine=None, run=None, edges=()):
    """A moment as the ticker builds one, of the parts the troubles are read from."""
    engine = {"state": "writing"} if engine is None else engine
    return {"nodes": list(nodes), "engine": engine, "run": run or {"source": "none"}, "edges": list(edges)}


def test_a_spark_is_away_when_it_is_not_live_and_there_when_it_is():
    said = readings(moment(spark("dgx0"), away("dgx1")))
    assert TROUBLES == ("away", "latch", "fan", "link", "engine") and tuple(said) == TROUBLES
    assert said["away"] == {"dgx0": GOOD, "dgx1": BAD}
    # of a Spark that is away nothing else is known: its clock, its fans
    assert said["latch"]["dgx1"] is None and said["fan"]["dgx1"] is None
    assert readings(moment({"name": "dgx2", "live": None}))["away"] == {"dgx2": None}  # no yes and no no: not known


def test_the_clock_is_stuck_when_the_hub_says_so_and_free_only_when_seen_high_under_load():
    """`latched` falls when the load ends as well (hub_ingest): that the clock is free again is only known of a
    GPU that works and runs at a normal clock. Without load, nobody knows."""
    for node, word in (
        (spark(latched=True, mhz=620), BAD),
        (spark(), GOOD),
        (spark(util=50, mhz=1000), GOOD),
        (spark(util=49), None),  # no load
        (spark(util=2, mhz=2190), None),
        (spark(mhz=999), None),  # low under load, and not said to be stuck yet: five samples make a latch
        (spark(mhz=None), None),
        (spark(util=None), None),
        (away(), None),
        ({**away(), "latched": True}, None),  # what a Spark that is away last read does not stand
    ):
        assert readings(moment(node))["latch"] == {"dgx1": word}, node


def test_a_fan_stands_when_the_diagnosis_says_so_and_turns_only_when_every_one_was_read_to():
    for node, word in (
        (spark(fans=[0, 3120], fan=1560.0), BAD),  # one beside a twin that turns
        (spark(fans=[0, 0], fan=0, gpu_c=64), BAD),  # all of them, and it is warm
        (spark(fans=[0, None], fan=0, gpu_c=80), BAD),
        (spark(), GOOD),
        (spark(fans=[900], fan=900.0), GOOD),
        (spark(fans=[0, 0], fan=0, gpu_c=41), None),  # all still while it is cool: that may be how it idles
        (spark(fans=[3110, None], fan=3110.0), None),  # one nobody read
        (spark(fans=None, fan=None), None),
        (spark(fans=[], fan=None), None),
        (away(), None),
    ):
        assert readings(moment(node))["fan"] == {"dgx1": word}, node


def test_a_link_is_down_or_up_as_it_was_read_and_not_known_where_it_was_not():
    edges = [
        {"from": 0, "to": 1, "group": "f0", "up": True},
        {"from": 0, "to": 3, "group": "f1", "up": False},
        {"from": 1, "to": 2, "group": "f0", "up": None},
        {"from": 2, "to": 3, "group": "f0"},
    ]
    said = readings(moment(spark("dgx0"), edges=edges))["link"]
    assert said == {"0/f0": GOOD, "0/f1": BAD, "1/f0": None, "2/f0": None}


def test_the_engine_is_in_trouble_only_when_its_port_is_silent_the_head_answers_and_no_lab_holds_the_ring():
    head, silent = spark("dgx0"), {"state": "offline", "error": "Nothing answers on the vLLM port."}
    lab = {"source": "command", "name": "Single tracks", "holder": "Lab window"}
    tracks = {"source": "command", "name": "Single tracks", "tracks": [{"node": "dgx0"}]}
    for state in ("idle", "asleep", "reading", "writing"):
        assert readings(moment(head, engine={"state": state}))["engine"] == {"ring": GOOD}, state
        assert readings(moment(head, engine={"state": state}, run=lab))["engine"] == {"ring": GOOD}, state
    for made, word in (
        (moment(head, engine=silent), BAD),
        (moment(head, engine=silent, run={"source": "error", "name": "Run source failed"}), BAD),
        (moment(away("dgx0"), spark("dgx1"), engine=silent), None),  # nobody can ask the head
        (moment(spark("dgx1"), engine=silent), None),  # no head among the Sparks
        (moment(head, engine={**silent, "answers": True}), None),  # it answers, without its counters
        (moment(head, engine=silent, run=lab), None),
        (moment(head, engine=silent, run=tracks), None),
        (moment(head, engine={}), None),
        (moment(head, engine={"state": None}), None),
    ):
        assert readings(made)["engine"] == {"ring": word}, made


def test_whether_a_lab_holds_the_ring_is_one_switch():
    """A silent engine is no trouble while a lab window holds the ring. It can be turned round in one
    place."""
    made = moment(spark("dgx0"), engine={"state": "offline"}, run={"source": "lab", "name": "x", "holder": "w"})
    assert alerts.LAB_SILENCE is True and readings(made)["engine"] == {"ring": None}
    alerts.LAB_SILENCE = False
    try:
        assert readings(made)["engine"] == {"ring": BAD}
    finally:
        alerts.LAB_SILENCE = True


def test_who_holds_the_ring_is_only_asked_whether_and_never_read():
    """The holder is a text a command outside wrote. Whatever stands in it, the readings are the same as for
    any other holder: nothing of it is ever looked at but that it is there."""
    silent = {"state": "offline"}
    plain = readings(moment(spark("dgx0"), engine=silent, run={"source": "command", "name": "a", "holder": "w"}))
    odd = "\x00\x1b[2J\r\nTitle: x\n" + "‮" * 40 + "A" * 5000
    for holder in (odd, [odd], {"who": odd}, 7):
        run = {"source": "command", "name": odd, "holder": holder, "group": odd}
        assert readings(moment(spark("dgx0"), engine=silent, run=run)) == plain, type(holder)


def test_a_moment_without_its_parts_gives_no_reading_and_does_not_throw():
    nothing = {"away": {}, "latch": {}, "fan": {}, "link": {}, "engine": {"ring": None}}
    for made in ({}, {"nodes": None, "edges": None, "engine": None, "run": None}, json.loads(b"{}")):
        assert readings(made) == nothing, made
    odd = {"nodes": ["dgx0", None, {"live": True}, 7], "edges": [None, "f0", 3], "engine": "offline", "run": [1]}
    assert readings(odd) == nothing  # a Spark without a name is none, a link that is no table is none
    hub = hub_for()
    first = json.loads(hub.wait_tick(-1)[0])  # what a hub holds before its first moment
    assert readings(first) == nothing
    start = readings(json.loads(json.dumps(hub.view())))  # every Spark still "Connecting"
    assert set(start["away"].values()) == {BAD} and len(start["away"]) == 4
    assert set(start["latch"].values()) == set(start["fan"].values()) == {None} and start["engine"] == {"ring": None}


def test_a_round_of_the_demo_reads_as_what_it_plays():
    """The round the demo plays, read moment by moment as the phone thread reads it (through JSON): the last
    Spark is away for a quarter of a minute and nothing else of it is known meanwhile; the ring engine is good
    while it plays; in the minute of single tracks its port is silent and the demo window holds the ring, which
    is no trouble; no fan stands, no link is down, no clock is stuck."""
    seen = {}

    def each(hub):
        made = json.loads(json.dumps(hub.view()))
        seen[round(made["t"] - 1_800_000_000.0)] = readings(made)

    demo_round(160, each=each)
    assert len(seen) == 160
    gone = [t for t, said in seen.items() if said["away"]["dgx3"] == BAD]
    assert gone == list(range(160, 176, 2)), gone
    for t, said in seen.items():
        assert {said["away"][name] for name in ("dgx0", "dgx1", "dgx2")} == {GOOD}, t
        assert BAD not in {*said["latch"].values(), *said["fan"].values(), *said["link"].values()}, (t, said)
        assert said["engine"] == {"ring": None if 240 <= t < 300 else GOOD}, (t, said["engine"])
        if t in gone:
            assert said["latch"]["dgx3"] is None and said["fan"]["dgx3"] is None, t
            assert (said["link"]["3/f0"], said["link"]["3/f1"]) == (None, None), t
    assert seen[100]["latch"] == dict.fromkeys(("dgx0", "dgx1", "dgx2", "dgx3"), GOOD)  # under load, the clock high
    assert set(seen[4]["latch"].values()) == {None}  # idle: nobody knows whether a clock would stick
    assert set(seen[100]["link"].values()) == {GOOD} and len(seen[100]["link"]) == 8
