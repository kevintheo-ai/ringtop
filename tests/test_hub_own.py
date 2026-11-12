"""The engine a Spark runs on its own: speed, queue and events from its own counters."""

import json
import time

from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.figures import scrape_before
from ringtop_parts.core.hub import Hub
from tests.fixtures import engine_sample, hub_for, own_reading, ring_map


def test_each_spark_shows_the_speed_of_its_own_engine():
    """With the ring engine off every Spark may serve a model of its own: speed and queue come from its own counters,
    by the same arithmetic as the ring engine's."""
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    hub.ingest("dgx1", {"t": now, "gpu": {}, "mem": {}, "fabric": {}})
    assert node.get("own") is None
    hub._own("dgx1", node, own_reading(1000.0, running=2.0, waiting=1.0), now - 10)
    assert node["own"]["tok_s"] is None and node["own"]["state"] == "reading"  # one reading gives no speed yet
    hub._own("dgx1", node, own_reading(1410.0, running=2.0, waiting=1.0), now)
    own = node["own"]
    assert own["tok_s"] == 41.0 and own["state"] == "writing" and own["model"] == "mistral-small-4", own
    assert (own["running"], own["waiting"]) == (2.0, 1.0)
    assert hub.history["dgx1.own_tok_s"][-1] == (now, 41.0)  # the time machine reads these
    assert hub.history["dgx1.own_running"][-1] == (now, 2.0) and hub.history["dgx1.own_waiting"][-1] == (now, 1.0)
    # the page hears figures, never the raw counters of the engine
    assert set(own) == {"model", "state", "tok_s", "running", "waiting", "ttft_p95", "ttft_recent", "finished"}, own
    assert hub.nodes["dgx2"].get("own") is None
    hub.scrapes.append((now - 10, own_reading(1000.0)["engine"], {}))
    hub.scrapes.append((now, own_reading(1410.0)["engine"], {}))
    assert hub.engine_view()["tok_s"] == own["tok_s"]  # one arithmetic for both
    json.loads(json.dumps(hub.view(), allow_nan=False))
    idle = hub_for()
    idle._own("dgx1", idle.nodes["dgx1"], own_reading(5.0, running=0.0), now - 10)
    idle._own("dgx1", idle.nodes["dgx1"], own_reading(5.0, running=0.0), now)
    assert idle.nodes["dgx1"]["own"]["state"] == "idle" and idle.nodes["dgx1"]["own"]["tok_s"] == 0.0


def test_the_first_token_time_of_an_own_engine_comes_from_its_own_histogram():
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    early = dict(own_reading(100.0), hist={"time_to_first_token_seconds": {"1": 10.0, "5": 10.0, "+Inf": 10.0}})
    late = dict(own_reading(900.0), hist={"time_to_first_token_seconds": {"1": 10.0, "5": 30.0, "+Inf": 30.0}})
    hub._own("dgx1", node, early, now - 60)
    hub._own("dgx1", node, late, now)
    # the twenty requests since the first reading all took between 1 and 5 s: the ten fast ones before do not count
    assert node["own"]["ttft_p95"] == 4.8 and node["own"]["ttft_recent"] is True, node["own"]
    assert hub.history["dgx1.own_ttft_p95"][-1] == (now, 4.8)
    assert node["own"]["finished"] is None  # it sent no counter of finished requests: that is not 0 done


def test_an_own_engine_that_restarts_counts_from_its_new_life():
    """A restart sets every counter back: the speed must not be the fall of the counter, nor an average across it."""
    for born in ({"process_start_time_seconds": 100.0}, {}):  # with the start time, and for an engine that gives none
        hub = hub_for()
        now = time.time()
        node = hub.nodes["dgx1"]
        hub._own("dgx1", node, own_reading(90000.0, **born), now - 12)
        hub._own("dgx1", node, own_reading(90400.0, **born), now - 4)
        assert node["own"]["tok_s"] == 50.0
        reborn = {"process_start_time_seconds": 900.0} if born else {}
        hub._own("dgx1", node, own_reading(30.0, **reborn), now - 2)
        assert node["own"]["tok_s"] is None, node["own"]  # one reading of the new life: no speed, none of the old one
        hub._own("dgx1", node, own_reading(230.0, **reborn), now)
        assert node["own"]["tok_s"] == 100.0, node["own"]
    # a new life that has already counted past the old one: only its start time tells, the counter did not fall
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    hub._own("dgx1", node, own_reading(1000.0, process_start_time_seconds=100.0), now - 4)
    hub._own("dgx1", node, own_reading(5000.0, process_start_time_seconds=900.0), now - 2)
    assert node["own"]["tok_s"] is None, node["own"]


def test_no_speed_is_averaged_across_a_hole_in_the_readings():
    """A port that was silent for a minute and answers again: the tokens of that minute divided by the minute would
    stand there as the speed of now. Nothing older than a hole counts, for an own engine and for the ring engine."""
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    hub._own("dgx1", node, own_reading(1000.0), now - 70)
    hub._own("dgx1", node, own_reading(8000.0), now)
    assert node["own"]["tok_s"] is None, node["own"]  # not 100: that was the mean of 70 unread seconds
    hub._own("dgx1", node, own_reading(8100.0), now + 2)
    assert node["own"]["tok_s"] == 50.0, node["own"]  # the two readings after the hole
    for t, tokens in ((now - 70, 1000.0), (now, 8000.0)):
        hub.scrapes.append((t, engine_sample(0, tokens)["engine"], {}))
    assert hub.engine_view()["tok_s"] is None
    hub.scrapes.append((now + 2, engine_sample(0, 8100.0)["engine"], {}))
    assert hub.engine_view()["tok_s"] == 50.0
    slow = Hub(parse_cluster(ring_map()), 30.0)  # sampled every 30 s: two readings 30 s apart are no hole
    slow._own("dgx1", slow.nodes["dgx1"], own_reading(1000.0), now - 30)
    slow._own("dgx1", slow.nodes["dgx1"], own_reading(4000.0), now)
    assert slow.nodes["dgx1"]["own"]["tok_s"] == 100.0
    # the 5-minute figures count requests, not a speed: they keep reaching across
    assert scrape_before([(0.0, "a", {}), (100.0, "b", {}), (400.0, "c", {})], 300.0)[1] == "b"


def test_an_own_engine_that_is_gone_leaves_no_last_speed():
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    plain = {"t": now, "gpu": {}, "mem": {}, "fabric": {}}
    hub.ingest("dgx1", {**plain, "own": own_reading(1000.0)})
    assert node["own"]["model"] == "mistral-small-4"
    hub.ingest("dgx1", plain)
    assert node["own"] is not None  # one sample without it is no news: the sampler may ask less often than it samples
    hub.own_at["dgx1"] -= 60
    hub.ingest("dgx1", plain)
    assert node["own"] is None and "dgx1" not in hub.own_scrapes  # no word of it for a minute
    hub.ingest("dgx1", {**plain, "own": own_reading(1000.0)})
    hub.node_down("dgx1", "ssh: timed out")
    assert node["own"] is None and "dgx1" not in hub.own_scrapes
    hub.ingest("dgx1", {**plain, "own": own_reading(2000.0)})
    assert node["own"]["tok_s"] is None  # back after a gap: no speed across the gap
    silent = {"model": "mistral-small-4", "name": "solo-mistral", "engine": None, "error": "No answer."}
    hub.ingest("dgx1", {**plain, "own": silent})
    assert node["own"] == {"model": "mistral-small-4", "state": "offline"}, node["own"]
    assert not hub.history["dgx1.own_tok_s"]  # a port that is silent has no speed, not speed 0


def test_an_own_engine_that_starts_or_stops_answering_is_an_event():
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    silent = {"model": "mistral-small-4", "name": "solo-mistral", "engine": None, "error": "No answer."}

    def told():
        return [(e["node"], e["text"], e["level"]) for e in hub.events if e["kind"] == "engine"]

    hub._own("dgx1", node, own_reading(10.0), now - 100)
    hub._own("dgx1", node, own_reading(20.0), now - 98)
    assert told() == [("dgx1", "Own engine answers: mistral-small-4", "info")]
    hub._own("dgx1", node, silent, now - 90)
    assert (
        node["own"]["state"] == "offline" and len(told()) == 1
    )  # said on the page at once, an event only when it lasts
    hub._own("dgx1", node, own_reading(30.0), now - 88)
    for ago in (80, 70, 60):
        hub._own("dgx1", node, silent, now - ago)
    # 20 s of silence: still no event. A container that was stopped on purpose is silent too, until the sampler looks
    # at docker again (every 15 s) and stops asking: that must end as "ended", not as a warning
    assert len(told()) == 1
    hub._own("dgx1", node, silent, now - 54)
    assert told()[1:] == [("dgx1", "Own engine stopped answering: mistral-small-4", "warn")]
    hub._own("dgx1", node, silent, now - 40)
    assert len(told()) == 2  # said once
    hub._own("dgx1", node, own_reading(5.0, model="nemotron"), now)
    assert told()[2:] == [("dgx1", "Own engine answers: nemotron", "info")]
    hub.node_down("dgx1", "gone")
    assert [t for t in told() if "stopped" in t[1]] == [told()[1]]  # an unreachable Spark says nothing about its engine
    hub.ingest("dgx1", {"t": now, "gpu": {}, "mem": {}, "fabric": {}, "own": own_reading(9.0, model="nemotron")})
    assert len(told()) == 3  # back with the engine it had: nothing new to tell
    hub.own_at["dgx1"] -= 60
    hub.ingest("dgx1", {"t": now, "gpu": {}, "mem": {}, "fabric": {}})
    assert told()[3:] == [("dgx1", "Own engine ended: nemotron", "info")]  # its container is gone: no failure
    plain = {"t": now, "gpu": {}, "mem": {}, "fabric": {}}
    hub.ingest("dgx1", {**plain, "own": own_reading(1.0, model="nemotron")})
    hub.node_down("dgx1", "gone")
    hub.own_at["dgx1"] -= 60  # it stayed away for a minute: the last word of its engine is old when it returns
    hub.ingest("dgx1", plain)  # back, and its sampler has not found the container yet: a moment without word is no end
    assert len(told()) == 5
    hub.own_at["dgx1"] -= 60
    hub.ingest("dgx1", plain)  # still no engine a while after it came back: it ended while nobody could look
    assert told()[5:] == [("dgx1", "Own engine ended: nemotron", "info")]


def test_another_model_behind_the_same_port_starts_its_own_window():
    """A container replaced by one with another model, with no start time to tell: its higher count minus the old
    engine's count is no speed."""
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    hub._own("dgx1", node, own_reading(1000.0, model="a"), now - 2)
    hub._own("dgx1", node, own_reading(5000.0, model="b"), now)
    assert node["own"]["tok_s"] is None and node["own"]["model"] == "b", node["own"]
    hub._own("dgx1", node, own_reading(5100.0, model="b"), now + 2)
    assert node["own"]["tok_s"] == 50.0


def test_the_speed_of_an_own_engine_is_counted_between_its_readings_not_between_their_arrivals():
    """Its own engine is read by a thread of its own, and a reading waits for the next sample: two readings taken 2 s
    apart may arrive a moment apart, or together. The speed is the tokens over the time between the readings."""
    now = time.time()
    for arrived in (now, now - 1.0, now - 3.5):  # together, a second apart, later than it was read
        hub = hub_for()
        node = hub.nodes["dgx1"]
        hub._own("dgx1", node, dict(own_reading(1000.0), t=500.0), arrived)
        assert node["own"]["tok_s"] is None
        hub._own("dgx1", node, dict(own_reading(1100.0), t=502.0), now)
        assert node["own"]["tok_s"] == 50.0, (arrived, node["own"])
        assert hub.history["dgx1.own_tok_s"][-1] == (now, 50.0)  # the history stays on the clock of the hub
        assert hub.events[-1]["text"] == "Own engine answers: mistral-small-4" and hub.events[-1]["t"] == arrived
        assert hub.own_at["dgx1"] == now  # and so does the watch for an engine that is gone
    plain = hub_for()  # a sampler that sends no moment (the demo, an older one): the arrival counts, as it always has
    plain._own("dgx1", plain.nodes["dgx1"], own_reading(1000.0), now - 2)
    plain._own("dgx1", plain.nodes["dgx1"], dict(own_reading(1100.0), t="soon"), now)  # no number: not believed
    assert plain.nodes["dgx1"]["own"]["tok_s"] == 50.0


def test_a_clock_that_went_back_on_a_spark_gives_no_speed_across_it():
    """The moments of the readings come from the Spark's clock. When it is set back, the newer reading looks older
    than the one before: tokens over that time would be a made-up speed, so the readings start over."""
    hub = hub_for()
    now = time.time()
    node = hub.nodes["dgx1"]
    hub._own("dgx1", node, dict(own_reading(1000.0), t=500.0), now - 6)
    hub._own("dgx1", node, dict(own_reading(1100.0), t=502.0), now - 4)
    assert node["own"]["tok_s"] == 50.0
    hub._own("dgx1", node, dict(own_reading(1200.0), t=400.0), now - 2)
    assert node["own"]["tok_s"] is None, node["own"]
    hub._own("dgx1", node, dict(own_reading(1500.0), t=402.0), now)
    assert node["own"]["tok_s"] == 150.0, node["own"]
    same = hub_for()  # the same moment twice is no time to count over either
    same._own("dgx1", same.nodes["dgx1"], dict(own_reading(1000.0), t=500.0), now - 2)
    same._own("dgx1", same.nodes["dgx1"], dict(own_reading(1100.0), t=500.0), now)
    assert same.nodes["dgx1"]["own"]["tok_s"] is None


def test_two_readings_of_an_own_engine_stamped_a_moment_apart_give_no_speed():
    """A sampler stamped a reading when the answer had come. A slow answer and a quick one after it then carried
    stamps 0.05 s apart for counters 2.9 s apart: 145 tokens stood as 2900 tokens/s, on the tile and in the curve.
    Readings less than a second apart give no speed; the next one a full pace later does."""
    hub, now = hub_for(), time.time()
    node = hub.nodes["dgx1"]
    hub._own("dgx1", node, dict(own_reading(1000.0), t=502.9), now - 2)
    hub._own("dgx1", node, dict(own_reading(1145.0), t=502.95), now)
    assert node["own"]["tok_s"] is None and node["own"]["state"] == "reading", node["own"]  # was 2900.0, "writing"
    assert not hub.history["dgx1.own_tok_s"], list(hub.history["dgx1.own_tok_s"])  # and no point of the curve
    hub._own("dgx1", node, dict(own_reading(1245.0), t=504.95), now + 2)
    assert node["own"]["tok_s"] == 119.5, node["own"]  # 245 tokens over the 2.05 s between the first and the last


def test_an_own_engine_that_sends_no_request_counts_is_not_called_idle():
    """A Spark's own engine answers without the counts of its requests and writes nothing: it was "idle" with 0
    running, kept as curves. Nobody knows what it does: the page hears that it answers without them, no figure of
    it stands and none is kept. Once it writes, that is known from its tokens, and its queue stays unknown."""
    hub, now = hub_for(), time.time()
    node = hub.nodes["dgx1"]

    def bare(generated):
        return {"model": "m", "engine": {"generation_tokens_total": generated}, "hist": {}}

    hub._own("dgx1", node, bare(1000.0), now - 4)
    hub._own("dgx1", node, bare(1000.0), now - 2)
    assert node["own"] == {
        "model": "m",
        "state": "offline",
        "error": "The engine answers without its request counters.",
    }, node["own"]
    assert not any(key.startswith("dgx1.own_") and points for key, points in hub.history.items()), dict(hub.history)
    assert [e["text"] for e in hub.events] == ["Own engine answers: m"]  # it does answer: no word that it stopped
    hub._own("dgx1", node, bare(1100.0), now)
    own = node["own"]
    assert (own["state"], own["tok_s"], own["running"], own["waiting"]) == ("writing", 25.0, None, None), own
    assert not hub.history["dgx1.own_running"] and hub.history["dgx1.own_tok_s"][-1] == (now, 25.0)
