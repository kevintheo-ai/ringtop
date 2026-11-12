"""Why it is as fast as it is: the words the page says about the engine and every Spark."""

from ringtop_parts.core.diagnose import diagnose, own_work, throttle_reasons


def test_an_engine_that_answers_without_its_request_counters_is_not_said_to_be_silent_or_stopped():
    """An engine that answers without the counts of its requests is given like a silent one, with the word why.
    The diagnosis took it for silent all the same. Of a Spark's own engine in that state it said that nothing
    answers on the port of "the engine's container"; and of the ring engine its headline said "not serving", where
    nobody knows what it does."""
    uncounted = "The engine answers without its request counters."
    waits = {"name": "solo-mistral", "running": True, "model": "mistral-small-4"}  # a container, the GPU at rest
    own = {
        "name": "a",
        "live": True,
        "util": 3.0,
        "box": waits,
        "own": {"model": "m", "state": "offline", "error": uncounted},
    }
    mute = {"name": "b", "live": True, "util": 3.0, "box": dict(waits), "own": {"model": "m", "state": "offline"}}
    why = diagnose({"state": "offline", "error": "Nothing answers on the vLLM port."}, [own, mute], None)
    texts = [p["text"] for p in why["points"]]
    assert "The engine's container runs on 1 of 2 Sparks, but nothing answers on its port." in texts, texts  # was 2
    # the ring engine answers and does not say what it does: that is not "not serving"
    ring = {"state": "offline", "error": uncounted, "answers": True}
    alone = diagnose(ring, [{"name": "d", "live": True, "util": 2.0}], None)
    assert alone["headline"] == "Nobody knows what the engine does.", alone["headline"]
    assert alone["points"][0] == {"level": "bad", "text": uncounted}, alone["points"]
    busy = {"name": "e", "live": True, "util": 96.0, "box": dict(waits), "apps": [{"name": "x", "gb": 60.0}]}
    both = diagnose(ring, [busy, {"name": "d", "live": True, "util": 2.0}], None)
    assert both["headline"] == "Nobody knows what the ring engine does; 1 of 2 Sparks is working on its own.", both


def test_sparks_that_work_on_their_own_are_named_when_the_ring_engine_is_off():
    """Four Sparks at full load and "not serving" is half the truth: each may run its own engine."""
    nodes = [
        {
            "name": "a",
            "live": True,
            "util": 96.0,
            "box": {"name": "solo-mistral", "running": True, "model": "mistral-small-4"},
            "apps": [{"name": "cuda-other", "gb": 60.0}, {"name": "VLLM::EngineCore", "gb": 26.7}],
        },
        {
            "name": "b",
            "live": True,
            "util": 96.0,
            "box": {"name": "spark-ds41f", "running": False, "model": "deepseek"},
            "apps": [{"name": "python", "gb": 0.2}, {"name": "sglang::scheduler", "gb": 84.2}],
        },
        {"name": "c", "live": True, "util": 3.0, "box": {"name": "idle", "running": True, "model": "m"}, "apps": []},
    ]
    why = diagnose({"state": "offline", "error": "Nothing answers on the vLLM port."}, nodes, None)
    texts = [p["text"] for p in why["points"]]
    assert why["headline"] == "The ring engine is not serving; 2 of 3 Sparks are working on their own."
    blind = dict(nodes[0], apps=[{"name": "cuda-other", "gb": 60.0}, {"name": "VLLM::EngineCore", "gb": None}])
    partly = [p["text"] for p in diagnose({"state": "offline", "error": "x"}, [blind, nodes[2]], None)["points"]]
    assert "a runs mistral-small-4 on its own: GPU 96 % busy." in partly, partly  # one program unread: no sum
    one = diagnose({"state": "offline", "error": "x"}, nodes[:1] + nodes[2:], None)
    assert one["headline"] == "The ring engine is not serving; 1 of 2 Sparks is working on its own.", one["headline"]
    # the memory is what all programs hold on that GPU: the biggest one need not be the engine that gives the name
    assert "a runs mistral-small-4 on its own: GPU 96 % busy, 86.7 GB on the GPU." in texts, texts
    assert "b runs sglang::scheduler on its own: GPU 96 % busy, 84.4 GB on the GPU." in texts
    assert not any(t.startswith("c ") for t in texts) and own_work(nodes[2]) is None
    assert why["own"] == {
        "a": "mistral-small-4",
        "b": "sglang::scheduler",
    }  # the page names them on the tiles from this
    alone = diagnose({"state": "offline", "error": "x"}, [{"name": "d", "live": True, "util": 2.0}], None)
    assert alone["headline"] == "The engine is not serving." and alone["own"] == {}
    # the ring engine's own containers at full load behind a silent port are not work of their own
    label = {"name": "spark-ds41f", "running": True, "model": "deepseek", "config": "config/x.json"}
    ring = [
        {"name": n, "live": True, "util": 96.0, "box": dict(label), "apps": [{"name": "VLLM::EngineCore", "gb": 90.0}]}
        for n in "ab"
    ]
    stuck = diagnose({"state": "offline", "error": "Nothing answers on the vLLM port."}, ring, None)
    assert stuck["headline"] == "The engine is not serving." and stuck["own"] == {}
    assert "The engine's container runs on 2 of 2 Sparks, but nothing answers on its port." in [
        p["text"] for p in stuck["points"]
    ]
    same = [
        dict(n, box={"name": "tf", "running": True, "model": "m1"}) for n in ring
    ]  # no label, but one model on every Spark
    unlabeled = diagnose({"state": "offline", "error": "x"}, same, None)
    assert unlabeled["own"] == {} and unlabeled["headline"] == "The engine is not serving."


def test_an_own_engine_that_waits_for_work_is_not_taken_for_the_ring_engines_container():
    """The ring engine is off and a Spark's own engine has nothing to do: it answers on its own port, so its container
    is not "the engine's container" behind a silent port. One that does not answer, or that nobody asked, still is."""
    box = {"name": "solo-mistral", "running": True, "model": "mistral-small-4"}
    writing = {"model": "mistral-small-4", "state": "writing", "tok_s": 30.0, "running": 1.0, "waiting": 0.0}
    busy = {"name": "a", "live": True, "util": 96.0, "box": dict(box), "own": writing}
    idle = {"name": "c", "live": True, "util": 0.0, "box": dict(box), "own": dict(writing, state="idle", tok_s=0.0)}
    off = {"state": "offline", "error": "Nothing answers on the vLLM port."}
    why = diagnose(off, [busy, idle], None)
    texts = [p["text"] for p in why["points"]]
    assert not any("engine's container" in t for t in texts), texts
    assert why["headline"] == "The ring engine is not serving; 1 of 2 Sparks is working on its own."
    for own in ({"model": "mistral-small-4", "state": "offline"}, None):
        texts = [p["text"] for p in diagnose(off, [busy, dict(idle, own=own)], None)["points"]]
        assert "The engine's container runs on 1 of 2 Sparks, but nothing answers on its port." in texts, (own, texts)
    # with a Spark away, nobody knows what runs there: the line counts among those it can see, and says so
    away = {"name": "z", "live": False, "reason": "ssh: timed out"}
    texts = [p["text"] for p in diagnose(off, [busy, dict(idle, own=None), away], None)["points"]]
    seen = "The engine's container runs on 1 of the 2 Sparks that can be reached, but nothing answers on its port."
    assert seen in texts and "z is unreachable." in texts, texts


def test_fans_that_stand_still_on_a_warm_spark_are_an_alarm():
    nodes = [
        {"name": "a", "live": True, "fan": 0.0, "gpu_c": 71.0},
        {"name": "b", "live": True, "fan": 0.0, "gpu_c": 35.0},  # cold and idle: a fan may rest
        {"name": "c", "live": True, "fan": 2600.0, "gpu_c": 71.0},
        {"name": "d", "live": True, "gpu_c": 71.0},  # no fan reading is no standing fan
        # one of two fans stands still and the other makes up for it: the average looks like any other Spark
        {"name": "e", "live": True, "fan": 3000.0, "fans": [0, 6000], "gpu_c": 50.0},
        {"name": "f", "live": True, "fan": 2650.0, "fans": [2600, 2700], "gpu_c": 71.0},
        {"name": "g", "live": True, "fan": 1667.0, "fans": [0, 0, 5000], "gpu_c": 50.0},  # two of three: not "one"
    ]
    points = diagnose({"state": "writing"}, nodes, None)["points"]
    assert points[0] == {"level": "bad", "text": "a: the fans stand still at 71 °C.", "node": "a"}
    still = {"level": "bad", "text": "e: one of its 2 fans stands still (0 / 6,000 RPM).", "node": "e"}
    assert still in points, points
    still = {"level": "bad", "text": "g: 2 of its 3 fans stand still (0 / 0 / 5,000 RPM).", "node": "g"}
    assert still in points, points
    assert not any(p["text"].startswith(("b:", "c:", "d:", "f:")) for p in points)


def test_throttle_decoding():
    assert throttle_reasons("0x0000000000000000") == []
    assert throttle_reasons("0x0000000000000040") == ["thermal"]
    assert throttle_reasons("0x0000000000000001") == []  # idle is not a slowdown
    assert throttle_reasons("[N/A]") is None and throttle_reasons(None) is None  # not read is not "no reason"


def test_a_reason_bit_the_table_does_not_name_is_still_a_reason():
    """nvidia-smi gives why a GPU slows down as bits. The table names five of them; any other bit that was set
    gave no reason at all, like a mask of zero. "No reason" is what the clock latch is told by: a GPU that named a
    reason the table does not know would have been called latched."""
    assert throttle_reasons("0x0000000000000002") == ["reason 0x2"]  # was []
    assert throttle_reasons("0x0000000000000110") == ["reason 0x10", "reason 0x100"]  # was []
    assert throttle_reasons("0x0000000000000061") == ["thermal"]  # two bits of one word, and idle: as before
    assert throttle_reasons("0x0000000000000046") == ["power cap", "thermal", "reason 0x2"]  # the named ones first
    hot = {"name": "a", "live": True, "throttle": throttle_reasons("0x10"), "mhz": 540.0, "util": 97.0}
    assert diagnose({"state": "idle"}, [hot], None)["points"][0]["text"] == "a is slowing down: reason 0x10."


def test_why_says_what_holds_the_ring_back():
    calm_node = {"name": "a", "live": True}
    busy = {"state": "writing", "waiting": 2, "prefix": 0.1, "timing": {"queue": 2.0, "prefill": 6.0, "decode": 3.0}}
    why = diagnose(busy, [calm_node], None)
    assert "queueing" in why["headline"] and any("reading prompts" in p["text"] for p in why["points"])
    assert any("cache" in p["text"] for p in why["points"])
    ok = diagnose({"state": "writing", "timing": {"queue": 0.0, "prefill": 1.0, "decode": 9.0}}, [calm_node], None)
    assert ok == {"headline": "Nothing is holding it back right now.", "points": []}
    assert diagnose({"state": "idle"}, [calm_node], None)["headline"] == "Nothing is running."
    down = diagnose({"state": "writing"}, [{"name": "b", "live": False}], None)
    assert down["headline"] == "b is unreachable."
    hot = {"name": "c", "live": True, "throttle": ["thermal"], "mem_free_gb": 3.5}
    points = diagnose({"state": "idle"}, [hot], 3)["points"]
    assert len(points) == 2 and points[0]["level"] == "warn"
    assert diagnose({"state": "offline", "error": "boom"}, [calm_node], None)["points"][0]["text"] == "boom"


def test_why_gives_the_speed_of_a_spark_that_serves_on_its_own():
    serving = {
        "name": "a",
        "live": True,
        "util": 96.0,
        "box": {"name": "solo-mistral", "running": True, "model": "mistral-small-4"},
        "apps": [{"name": "VLLM::EngineCore", "gb": 86.7}],
        "own": {"model": "mistral-small-4", "state": "writing", "tok_s": 41.4, "running": 2.0, "waiting": 1.0},
    }
    outside = {
        "name": "b",
        "live": True,
        "util": 96.0,
        "box": {"name": "spark-ds41f", "running": False, "model": "deepseek"},
        "apps": [{"name": "sglang::scheduler", "gb": 84.2}],
    }

    def said(nodes):
        return [p["text"] for p in diagnose({"state": "offline", "error": "x"}, nodes, None)["points"]]

    texts = said([serving, outside])
    assert (
        "a runs mistral-small-4 on its own: 41 tokens/s, 2 running, 1 waiting, GPU 96 % busy, 86.7 GB on the GPU."
        in texts
    )
    # nobody can ask what runs outside a vLLM container how fast it is: no speed is made up for it
    assert "b runs sglang::scheduler on its own: GPU 96 % busy, 84.2 GB on the GPU." in texts, texts
    # the engine that answered names itself: docker is looked at every 15 s, so after a change of container the box
    # still carries the old model for a moment, and the speed would be said of the wrong one
    reading = dict(serving, own={"model": "m", "state": "reading", "tok_s": 0.0, "running": 1.0, "waiting": 0.0})
    assert "a runs m on its own: reading prompts, 1 running, GPU 96 % busy, 86.7 GB on the GPU." in said([reading])
    mute = dict(serving, own={"model": "mistral-small-4", "state": "offline"})
    assert "a runs mistral-small-4 on its own: its engine does not answer, GPU 96 % busy, 86.7 GB on the GPU." in said(
        [mute]
    )
    resting = dict(serving, own={"model": "m", "state": "idle", "tok_s": 0.0, "running": 0.0, "waiting": 0.0})
    assert "a runs m on its own: its engine is idle, GPU 96 % busy, 86.7 GB on the GPU." in said([resting])
    # the same model on every Spark is one engine across the cluster, unless each one answers on a port of its own
    twins = [dict(serving, name=n) for n in "ab"]
    assert diagnose({"state": "offline", "error": "x"}, twins, None)["own"] == {
        "a": "mistral-small-4",
        "b": "mistral-small-4",
    }
    unread = [dict(serving, name=n, own=None) for n in "ab"]
    assert diagnose({"state": "offline", "error": "x"}, unread, None)["own"] == {}


def test_memory_under_the_guard_is_said_as_below_it_not_as_close_to_it():
    """The memory guard is a line of free memory: under it is below it, up to 2 GB above it is close to it."""

    def said(free):
        node = {"name": "a", "live": True, "mem_free_gb": free}
        return [p["text"] for p in diagnose({"state": "idle"}, [node], 32)["points"]]

    assert said(0.4) == ["a has 0.4 GB free, below the 32 GB memory guard."], said(0.4)
    assert said(32.0) == ["a has 32.0 GB free, close to the 32 GB memory guard."], said(32.0)
    assert said(33.9) == ["a has 33.9 GB free, close to the 32 GB memory guard."], said(33.9)
    assert said(34.1) == []


def test_a_single_spark_is_counted_as_one_spark_not_as_one_sparks():
    """Ringtop also watches one Spark alone: "1 of 1 Sparks" is no count of one."""
    off = {"state": "offline", "error": "Nothing answers on the vLLM port."}
    box = {"name": "solo-mistral", "running": True, "model": "mistral-small-4"}
    alone = diagnose(off, [{"name": "a", "live": True, "util": 96.0, "box": dict(box)}], None)
    assert alone["headline"] == "The ring engine is not serving; 1 of 1 Spark is working on its own.", alone["headline"]
    idle = {"name": "a", "live": True, "util": 0.0, "box": dict(box)}
    texts = [p["text"] for p in diagnose(off, [idle], None)["points"]]
    assert "The engine's container runs on 1 of 1 Spark, but nothing answers on its port." in texts, texts
    away = {"name": "z", "live": False, "reason": "ssh: timed out"}
    texts = [p["text"] for p in diagnose(off, [idle, away], None)["points"]]
    seen = "The engine's container runs on 1 of the 1 Spark that can be reached, but nothing answers on its port."
    assert seen in texts, texts


def test_one_fan_that_was_read_and_stands_still_is_not_said_as_fans():
    """Each fan is read by itself. With one reading, one fan is known to stand still: the sentence says no more."""
    one = {"name": "a", "live": True, "fan": 0.0, "fans": [0], "gpu_c": 70.0}
    two = {"name": "b", "live": True, "fan": 0.0, "fans": [0, 0], "gpu_c": 70.0}
    texts = [p["text"] for p in diagnose({"state": "writing"}, [one, two], None)["points"]]
    assert texts == ["a: the fan stands still at 70 °C.", "b: the fans stand still at 70 °C."], texts


def test_every_line_about_one_spark_names_it_and_a_line_about_the_engine_names_none():
    """The page of one Spark shows the lines about that Spark: each carries its name as a field, not only in its
    text. A line about the engine carries no such field."""
    hot = {"name": "a", "live": True, "throttle": ["thermal"], "mem_free_gb": 3.5, "fan": 0.0, "gpu_c": 71.0}
    away = {"name": "b", "live": False}
    busy = {"state": "writing", "waiting": 2, "timing": {"queue": 2.0, "prefill": 6.0, "decode": 3.0}}
    points = diagnose(busy, [hot, away], 3)["points"]
    assert {p["text"]: p.get("node") for p in points} == {
        "a: the fans stand still at 71 °C.": "a",
        "a is slowing down: thermal.": "a",
        "a has 3.5 GB free, close to the 3 GB memory guard.": "a",
        "b is unreachable.": "b",
        "Requests are queueing: 18% of their time is spent waiting.": None,
        "Most of the time goes to reading prompts: 55%.": None,
    }, points
    assert all(set(p) == {"level", "text"} for p in points if p.get("node") is None), points
    alone = {"name": "c", "live": True, "util": 96.0, "box": {"name": "x", "running": True, "model": "m"}}
    idle = {"name": "d", "live": True, "util": 2.0, "box": {"name": "x", "running": True, "model": "m"}}
    off = diagnose({"state": "offline", "error": "boom"}, [alone, idle, away], None)["points"]
    assert [(p["text"], p.get("node")) for p in off] == [
        ("boom", None),
        (
            "The engine's container runs on 1 of the 2 Sparks that can be reached, but nothing answers on its port.",
            None,
        ),
        ("c runs m on its own: GPU 96 % busy.", "c"),
        ("b is unreachable.", "b"),
    ], off


def test_requests_nobody_counted_are_not_said_as_zero_running_and_an_engine_that_answers_is_not_called_silent():
    """An engine that sends no count of its requests: the line about a Spark said "0 running" of its own engine, and
    of a ring engine that answers without them the diagnosis would say that nothing answers on its port."""
    serving = {
        "name": "a",
        "live": True,
        "util": 96.0,
        "box": {"name": "solo-mistral", "running": True, "model": "m"},
    }

    def said(own):
        return diagnose({"state": "offline", "error": "x"}, [dict(serving, own=own)], None)["points"][-1]["text"]

    wrote = {"model": "m", "state": "writing", "tok_s": 41.4, "running": None, "waiting": None}
    assert said(wrote) == "a runs m on its own: 41 tokens/s, GPU 96 % busy.", said(wrote)  # was "…, 0 running, …"
    queued = {"model": "m", "state": "reading", "tok_s": None, "running": None, "waiting": 2.0}
    assert said(queued) == "a runs m on its own: reading prompts, 2 waiting, GPU 96 % busy.", said(queued)
    bare = {"model": "m", "state": "offline", "error": "The engine answers without its request counters."}
    assert said(bare) == "a runs m on its own: its engine answers without its request counters, GPU 96 % busy."
    # the ring engine: its container runs, and it answers. Nobody says that its port is silent
    ring = {"name": "a", "live": True, "util": 3.0, "box": {"running": True, "config": "config/cluster.json"}}
    silent = diagnose({"state": "offline", "error": "Nothing answers on the vLLM port."}, [ring], None)["points"]
    assert [p["text"] for p in silent] == [
        "Nothing answers on the vLLM port.",
        "The engine's container runs on 1 of 1 Spark, but nothing answers on its port.",
    ], silent
    bare_ring = {"state": "offline", "error": "The engine answers without its request counters.", "answers": True}
    assert [p["text"] for p in diagnose(bare_ring, [ring], None)["points"]] == [
        "The engine answers without its request counters."
    ]
