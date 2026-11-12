"""The faults the demo plays with --demo-faults: one round tells a phone ten things in order, each fault is what
the hub would make of a real one, and without the switch the round is as it ever was."""

import json
import time

from ringtop_parts.connect.notify import Phone
from ringtop_parts.core import demo_faults
from ringtop_parts.core.alerts import BAD, GOOD, TEXTS, TROUBLES, WAITS, begun, delivered, due, readings, step
from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.demo import Demo
from ringtop_parts.core.demo_faults import AWAY, FAN, FAULT_PACE, LATCH, LINK, SILENT
from ringtop_parts.core.hub import Hub
from tests.fixtures import demo_round, ring_map
from tests.test_start import started

T0 = 1_800_000_000.0


def fault_round(ticks):
    """The round with its faults, read moment by moment as the phone thread reads it: every key that went out
    with the second it went out at, every reading by its second, and the hub."""
    state, sent, read = [begun()], [], {}

    def each(hub):
        now = time.time()  # the made-up clock of the round
        said = readings(json.loads(json.dumps(hub.view())))
        read[round(now - T0)] = said
        state[0] = step(state[0], said, now, FAULT_PACE)
        key = due(state[0])
        if key:
            state[0] = delivered(state[0], key, now)
            sent.append((round(now - T0), key))

    return sent, read, demo_round(ticks, faults=True, each=each)


def test_one_round_with_faults_tells_a_phone_ten_things_in_order_and_the_next_one_shuts_the_cap():
    """A Spark away, a clock stuck, a fan standing, a link down, the engine silent with no run named: one after
    another, each long enough to be said at a twentieth of its wait and over long enough for that to be said. One
    round of five minutes gives the ten messages of the five troubles, each once. The second round would give
    them again: its first is the eleventh message of the day, and the twelfth is the word of the cap. So six
    minutes of this demo show every text there is, and then it is silent."""
    sent, _, _ = fault_round(300)
    assert sent[:10] == [
        (32, "away on"),
        (46, "away off"),
        (66, "latch on"),
        (86, "latch off"),
        (98, "fan on"),
        (112, "fan off"),
        (124, "link on"),
        (138, "link off"),
        (210, "engine on"),
        (228, "engine off"),
    ], sent
    assert sent[10:] == [(332, "away on"), (346, "quiet")], sent[10:]
    assert {key for _, key in sent} == set(TEXTS)  # all eleven


def test_each_fault_reads_as_its_trouble_on_its_spark_and_as_nothing_else():
    """What the phone thread reads off the round: bad for the one trouble on the one thing, for as long as the
    fault plays (the clock is called stuck after five samples), and nothing bad beside it."""
    _, read, hub = fault_round(150)
    bad = {
        t: sorted((trouble, thing) for trouble in TROUBLES for thing, word in said[trouble].items() if word == BAD)
        for t, said in read.items()
    }
    spans = {}
    for t, things in bad.items():
        for thing in things:
            spans.setdefault(thing, []).append(t)
        assert len(things) <= 1, (t, things)  # one after another, never two at once
    assert {thing: (seconds[0], seconds[-1] + 2) for thing, seconds in spans.items()} == {
        ("away", "dgx3"): (20, 40),
        ("latch", "dgx2"): (60, 80),
        ("fan", "dgx1"): (92, 106),
        ("link", "0/f0"): (118, 132),
        ("engine", "ring"): (150, 222),
    }, spans
    assert all(seconds == list(range(seconds[0], seconds[-1] + 2, 2)) for seconds in spans.values()), spans
    # and the hub says of each what it says of a real one. The engine stops twice: silent, and for the tracks
    said, times = [event["text"] for event in hub.events], {"Stopped serving": 2}
    for words in (
        "Unreachable: ",
        "Reachable again",
        "GPU clock stuck at 620 MHz",
        "Link f0 went down",
        "Stopped serving",
        "Serving again",
    ):
        assert sum(text.startswith(words) for text in said) == times.get(words, 1), (words, said)
    assert read[100]["fan"]["dgx1"] == BAD and read[100]["fan"]["dgx0"] == GOOD  # its twin turns: one of two
    assert read[200]["engine"] == {"ring": BAD} and read[250]["engine"] == {"ring": None}  # the tracks: held


def test_every_fault_lasts_longer_than_its_wait_and_is_over_longer_than_the_wait_for_its_end():
    """The table of the faults against the table of the waits: whoever changes one sees here whether the round
    still shows all ten. The clock needs five samples before the hub calls it stuck."""
    faults = {"away": AWAY, "latch": LATCH, "fan": FAN, "link": LINK, "engine": SILENT}
    assert FAULT_PACE == 0.05 and list(faults) == list(TROUBLES)
    before = 0.0
    for trouble, (begins, over, *_) in faults.items():
        on, off = (wait * FAULT_PACE for wait in WAITS[trouble])
        seen = begins + (8 if trouble == "latch" else 0)  # the fifth sample comes 8 s after the first
        assert over - seen >= on + 4, trouble  # two looks to spare
        assert begins - before >= off + 4, trouble
        before = over
    assert Demo.RING - SILENT[1] >= WAITS["engine"][1] * FAULT_PACE + 4  # its end is said before the tracks begin
    assert LATCH[0] >= 30 and LATCH[1] <= 130  # the ring engine writes: a clock can only be seen stuck under load


def test_without_the_switch_the_round_plays_no_fault_and_asks_no_fault_table():
    """--demo alone is the round as it ever was (its digest is held in test_demo.py): the last Spark is away
    from second 160 to 175, and nothing of the faults is even asked."""
    hub = Hub(parse_cluster(ring_map()), 2.0)
    assert Demo(hub).faults is False and Demo(hub, 30.0, True).faults is True
    real = {name: getattr(demo_faults, name) for name in ("away", "spoiled", "silent")}

    def never(*call):
        raise AssertionError("the fault table was asked without --demo-faults")

    gone = []
    for name in real:
        setattr(demo_faults, name, never)
    try:
        demo_round(160, each=lambda hub: gone.append(not hub.nodes["dgx3"]["live"]))
    finally:
        for name, value in real.items():
            setattr(demo_faults, name, value)
    assert [2 * i for i, away in enumerate(gone) if away] == list(range(160, 176, 2)), gone


def test_the_faults_are_asked_for_with_the_demo_and_only_with_it():
    for argv in (["--demo-faults"], ["user@head", "--demo-faults"]):
        try:
            seen = started(argv, {"nodes": ring_map(), "hostname": "dgx0"})
        except SystemExit as stop:
            assert stop.code == 2 and "--demo-faults needs --demo" in stop.said and stop.order == [], stop.said
        else:
            raise AssertionError(f"started with {argv}: {seen.order}")
    plain = started(["--demo", "--ntfy-dry"])
    assert plain.faults is False and plain.threads[0][1][1] == Phone(None, "https://ntfy.sh", None, True, True, 1.0)
    faults = started(["--demo", "--demo-faults", "--ntfy-dry", "--demo-at", "20"])
    assert faults.faults is True and faults.demo[1] == 20.0
    assert faults.threads[0][1][1] == Phone(None, "https://ntfy.sh", None, True, True, 0.05)  # at a twentieth
    assert started(["--demo", "--demo-faults"]).faults is True  # the page shows the faults without a phone as well


def test_the_engine_falls_silent_on_the_spark_that_reads_it_whatever_its_place():
    """The silent engine was played on the Spark at place 0, also where another one is the head (find4):
    a Spark that reads no engine got a word of it, and the head's reading went on. It is played on the sample that
    carries the readings of the ring engine, the head's, wherever it stands."""
    silent = demo_faults.SILENT[0] + 1
    head = demo_faults.spoiled(silent, 2, {"engine": {"x": 1.0}, "hist": {}, "engine_error": None})
    worker = demo_faults.spoiled(silent, 0, {"cpu": 5.0})
    assert head == {"engine": None, "engine_error": "Nothing answers on the vLLM port."} and worker == {"cpu": 5.0}
