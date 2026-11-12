"""The sampler's background thread: the slow readers, each at its own pace, and what they leave for the next sample."""

import contextlib
import threading
import types

from ringtop_parts.connect import shell
from tests.fixtures import sampler_namespace

BOX = {"id": "abc123", "name": "spark-ds41f", "cpuset": "5-9", "running": True}


class Done(Exception):
    """Ends the endless loop of background() once the made-up clock has run far enough."""


def background_run(seconds, head=False, port=None, box=BOX, broken=()):
    """background() of the sampler by a made-up clock, with a stand-in for every slow reader.

    Gives back the namespace, what was asked of which reader, and what lay in `pending` after each pass (the passes
    are a second apart, and like the sampling loop this takes away what it found). `broken` readers raise."""
    namespace = sampler_namespace()
    clock, passes, asked = [5000.0], [], []
    told = {"startup": 0}

    def sleep(_):
        passes.append((round(clock[0] - 5000.0), dict(namespace["pending"])))
        namespace["pending"].clear()
        clock[0] += 1.0
        if clock[0] - 5000.0 > seconds:
            raise Done

    def reader(name, answer):
        def read(*args):
            asked.append((name, args))
            if name in broken:
                raise OSError(name + " is broken")
            return answer(*args) if callable(answer) else answer

        return read

    def startup(box_given):  # the cold start of a container is read once, then there is nothing new
        told["startup"] += 1
        return {"started": 1} if told["startup"] == 1 else None

    stand_ins = {
        "container": box,
        "pin_away": None,
        "threads": ([{"name": "VLLM::Worker"}], [{"comm": "VLLM::Worker_TP", "role": "rank main"}]),
        "core_clocks": ([2800, 3880], 1),
        "nvml": {"energy_mj": 7},
        "cable_counters": {"f0": {"tx_bytes_phy": 9}},
        "memory_deep": {"mem": {"MemTotal": 1}},
        "slow_facts": lambda: {"psi": 0.5, "apps": [{"gb": 1.0, "name": "a"}]},
        "link_detail": {"rocep1s0f0": {"out_of_sequence": 0}},
        "intruders": [{"name": "dockerd", "ms": 8.0}],
        "engine_pids": {"41", "42"},
        "irq_noise": {"by_kind": {"timer": 1.0}},
        "startup": startup,
        "pcie_links": {"nvme0": {"x": 4}},
        "devlink_health": {"reporters": 20},
        "firmware": {"bios": "5.36"},
        "cooling": [{"type": "Fan", "cur": 0, "max": 100}],
        "engine_log": lambda name: [{"t": int(clock[0]), "text": "a line of " + name}],
        "connections": lambda p: [{"port": p, "lastrcv": 1}],
        "lab": {"hold": None, "queue": {}},
        "processes": [{"seconds": 3, "command": "servebench"}],
        "fetch": lambda p, path: {"asked": path},
        "health": 200,
    }
    for name, answer in stand_ins.items():
        namespace[name] = reader(name, answer)
    namespace["time"] = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep)
    namespace["is_head"], namespace["capacity"] = head, [718, 1024]
    namespace["port"][0] = port
    with contextlib.suppress(Done):
        namespace["background"]()
    return namespace, asked, passes


def seconds_of(passes, key):
    return [second for second, pending in passes if key in pending]


def test_every_slow_reader_runs_at_its_own_pace_and_leaves_its_reading_for_the_next_sample():
    """On the head with an engine that answers: the slow facts every 15 s, the rare ones every minute, the log every
    5 s, the connections every 3 s, the head's facts every 10 s. The sampling loop never waits for any of them."""
    namespace, asked, passes = background_run(61, head=True, port="8888")
    assert [second for second, _ in passes] == list(range(62))  # one pass a second
    assert seconds_of(passes, "slow") == [0, 15, 30, 45, 60]
    assert seconds_of(passes, "rare") == [0, 60]
    assert seconds_of(passes, "log") == list(range(0, 61, 5))
    assert seconds_of(passes, "conn") == list(range(0, 61, 3))
    assert seconds_of(passes, "info") == list(range(0, 61, 10))
    first = passes[0][1]
    assert first["slow"] == {
        "psi": 0.5,
        "apps": [{"gb": 1.0, "name": "a"}],
        "t": 5000.0,  # the moment the counters were read: they become rates
        "box": BOX,
        "threads": [{"name": "VLLM::Worker"}],
        "key_threads": [{"comm": "VLLM::Worker_TP", "role": "rank main"}],
        "links": {"rocep1s0f0": {"out_of_sequence": 0}},
        "cables": {"f0": {"tx_bytes_phy": 9}},
        "capacity": [718, 1024],
        "nvml": {"energy_mj": 7},
        "memory": {"mem": {"MemTotal": 1}},
        "clocks": [2800, 3880],
        "perf_limited": 1,
        "intruders": [{"name": "dockerd", "ms": 8.0}],
        "irq": {"by_kind": {"timer": 1.0}},
        "startup": {"started": 1},
    }, first["slow"]
    assert "startup" not in passes[15][1]["slow"]  # read once per start of the container
    assert first["rare"] == {
        "pcie": {"nvme0": {"x": 4}},
        "devlink": {"reporters": 20},
        "firmware": {"bios": "5.36"},
        "cooling": [{"type": "Fan", "cur": 0, "max": 100}],
    }
    assert first["log"] == [{"t": 5000, "text": "a line of spark-ds41f"}]
    assert first["conn"] == [{"port": "8888", "lastrcv": 1}]
    assert set(first["info"]) == {"container", "lab", "processes", "kernel", "page_size", "models", "version", "health"}
    assert first["info"]["container"] == BOX and first["info"]["health"] == 200
    assert first["info"]["models"] == {"asked": "/v1/models"} and first["info"]["version"] == {"asked": "/version"}
    assert namespace["info"] == passes[60][1]["info"]  # what the sampling loop reads the engine's port from
    # the engine's cores are found once per slow look, and the sampler keeps off them
    assert [args for name, args in asked if name == "pin_away"] == [({5, 6, 7, 8, 9},)] * 5
    assert ("intruders", ({5, 6, 7, 8, 9}, {"41", "42"})) in asked and ("irq_noise", ({5, 6, 7, 8, 9},)) in asked
    assert namespace["cg"][0] == "/sys/fs/cgroup/system.slice/docker-abc123.scope" and namespace["box_now"][0] == BOX
    assert sum(name == "container" for name, _ in asked) == 5  # docker is looked at with the slow facts, not more often


def test_a_worker_reads_no_head_facts_and_a_node_without_a_container_no_log():
    """A worker never asks for connections or the head's facts. Without an engine container there is no log to read,
    no cgroup, nobody to keep off, and the slow facts still arrive."""
    _, asked, passes = background_run(31, head=False, port="8888")
    assert seconds_of(passes, "conn") == [] and seconds_of(passes, "info") == []
    assert seconds_of(passes, "log") == list(range(0, 31, 5)) and seconds_of(passes, "slow") == [0, 15, 30]
    assert not {"connections", "lab", "processes", "fetch", "health"} & {name for name, _ in asked}
    quiet, _, passes = background_run(16, head=True, port=None, box=None)
    assert seconds_of(passes, "log") == [] and seconds_of(passes, "conn") == []  # no port known: nothing to count
    slow = passes[0][1]["slow"]
    # without cores the engine is pinned to, nobody looks who else ran on them: not read, which was [] ("nobody")
    assert slow["box"] is None and slow["intruders"] is None and slow["irq"] is None and "startup" not in slow
    assert quiet["cg"][0] is None and quiet["box_now"][0] is None
    info = passes[0][1]["info"]  # the head still says what it is, and asks docker once more for a container
    assert info["container"] is None and "models" not in info and "health" not in info
    assert seconds_of(passes, "info") == [0, 10]


def test_a_slow_reader_that_fails_costs_its_own_reading_and_nothing_else():
    """One tool that is missing or hangs must not take the others with it: the rest arrive. Its own reading is
    None, which says that it was not read. It was an empty list, an empty mapping or 0: no threads of the engine,
    no core with a limit, no cables, no link counters, said of what nobody had looked at."""
    broken = ("threads", "core_clocks", "nvml", "cable_counters", "memory_deep", "link_detail", "intruders")
    _, _, passes = background_run(1, head=True, port="8888", broken=(*broken, "irq_noise", "startup", "pcie_links"))
    slow, rare = passes[0][1]["slow"], passes[0][1]["rare"]
    unread = (slow["threads"], slow["key_threads"], slow["clocks"], slow["perf_limited"], slow["cables"], slow["links"])
    assert unread == (None,) * 6, unread  # was ([], [], [], 0, {}, {})
    assert (slow["nvml"], slow["memory"]) == (None, None)
    assert slow["intruders"] is None and slow["irq"] is None and "startup" not in slow
    assert slow["psi"] == 0.5 and slow["box"] == BOX  # what did not fail is there
    assert rare["pcie"] is None and rare["firmware"] == {"bios": "5.36"}
    _, _, passes = background_run(1, head=True, port="8888", broken=("connections",))
    assert passes[0][1]["conn"] is None  # was []: no connection to the engine, said of a look that failed


def log_handover(namespace):
    """One hand-over of log lines with the two threads of the sampler at the worst moment: the background thread
    has looked at the lines that wait and has not yet written them back with its new one, when the sampling loop
    takes what waits. Gives back whether the loop waited for it, and every line the loop then sent, in order."""
    looked, go = threading.Event(), threading.Event()

    class Waiting(dict):
        def get(self, key, default=None):
            found = super().get(key, default)
            if threading.current_thread().name == "adds":
                looked.set()
                go.wait(5)
            return found

    namespace["pending"] = Waiting(log=[{"t": 1, "text": "first"}])
    adds = threading.Thread(target=namespace["leave_log"], args=([{"t": 2, "text": "second"}],), name="adds")
    adds.start()
    assert looked.wait(5)
    sample, later = {}, {}
    takes = threading.Thread(target=namespace["take_pending"], args=(sample,))
    takes.start()
    takes.join(0.3)
    waited = takes.is_alive()
    go.set()
    adds.join(5)
    takes.join(5)
    namespace["take_pending"](later)
    return waited, [line["text"] for line in sample.get("log", []) + later.get("log", [])]


def test_log_lines_are_handed_over_once_while_the_loop_takes_them():
    """New lines of the engine's log are added to the ones that wait for the next sample: looked at, then written
    back with the new ones. The sampling loop takes what waits. When it took between the look and the write, the
    lines it had just sent were written back and sent again with the next sample. Both happen under one lock: the
    loop waits for the background thread, and every line is sent once. Without the lock, the same hand-over sends
    the first line twice."""
    namespace = sampler_namespace()
    assert log_handover(namespace) == (True, ["first", "second"])
    namespace["handover"] = contextlib.nullcontext()  # the hand-over as it was: nothing holds the loop back
    assert log_handover(namespace) == (False, ["first", "first", "second"])
    loop = shell.program(["sampler/loop.py"])
    assert "take_pending(sample)" in loop and "pending.pop" not in loop  # the loop takes under the lock, nowhere else
