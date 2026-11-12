"""The way to the nodes: the commands tried, the programs sent, a stream that survives a bad sample."""

import contextlib
import io
import json
import subprocess
import sys
import threading
import time
import types
from typing import ClassVar

from ringtop_parts.connect import shell
from ringtop_parts.connect.shell import DISCOVER, SAMPLER, NodeStream, node_commands
from ringtop_parts.core.cluster import parse_cluster
from tests.fixtures import NoStderr, hub_for, ring_map


def test_commands_try_name_then_local_then_jump():
    cluster = parse_cluster(ring_map())
    worker = cluster["nodes"][1]
    commands = node_commands(worker, cluster, "laptop", "user@head", 2.0, "auto", "/r")
    assert commands[0][-2] == "user@dgx1" and commands[1][-2] == commands[0][-2] + ".local"
    assert "-J" in commands[2] and commands[2][-2] == "user@dgx1"
    head = cluster["nodes"][0]
    assert node_commands(head, cluster, "laptop", "user@head", 2.0, "auto", "/r")[0][-2] == "user@head"
    local = node_commands(head, cluster, "dgx0", None, 2.0, "auto", "/r")
    assert local == [[sys.executable, "-u", "-", "2.0", "head", "auto", "/r", ""]]


def test_sampler_is_valid_python_and_view_is_strict_json():
    compile(SAMPLER, "sampler", "exec")
    compile(DISCOVER, "discover", "exec")
    hub = hub_for()
    hub.ingest("dgx0", {"t": time.time(), "gpu": {"w": float("nan"), "c": 50.0}, "mem": {}, "fabric": {}})
    json.loads(json.dumps(hub.view(), allow_nan=False))


def test_one_bad_sample_does_not_end_a_node_stream():
    hub = hub_for()
    calls = []

    def ingest(name, sample):
        calls.append(sample)
        if len(calls) == 1:
            raise ValueError("odd sample")

    hub.ingest = ingest
    stream = NodeStream(hub, hub.cluster["nodes"][0], [])
    reached, _ = stream.stream([sys.executable, "-c", 'import sys; sys.stdin.read(); print("{}"); print("{}")'])
    assert reached and len(calls) == 2


def test_a_bad_sample_nobody_can_be_told_of_does_not_end_a_node_stream():
    """A sample the Hub cannot take in is skipped and said on stderr. Where stderr cannot be written, saying it threw
    out of the stream: the thread of that Spark ended, and it was never read again. The sample is skipped unsaid."""
    hub = hub_for()
    calls = []

    def ingest(name, sample):
        calls.append(sample)
        if len(calls) == 1:
            raise ValueError("odd sample")

    hub.ingest = ingest
    stream = NodeStream(hub, hub.cluster["nodes"][0], [])
    with contextlib.redirect_stderr(NoStderr()):
        reached, _ = stream.stream([sys.executable, "-c", 'import sys; sys.stdin.read(); print("{}"); print("{}")'])
    assert reached and len(calls) == 2


def heard(code):
    """What a node stream makes of a command that runs this Python: whether it was reached, its last word, and the
    samples the Hub was handed."""
    hub, samples = hub_for(), []
    hub.ingest = lambda name, sample: samples.append(sample)
    stream = NodeStream(hub, hub.cluster["nodes"][0], [])
    reached, word = stream.stream([sys.executable, "-c", "import sys; sys.stdin.read(); " + code])
    return reached, word, samples


def test_a_command_that_cannot_start_is_a_failed_try_and_not_the_end_of_the_stream():
    """No ssh on the path, no room for another process: the try failed with a word, like a node that is not there.
    An error that leaves the thread would end this node's stream for as long as ringtop runs."""
    stream = NodeStream(hub_for(), hub_for().cluster["nodes"][0], [])
    reached, word = stream.stream(["/nonexistent/ringtop-has-no-such-program"])
    assert reached is False and "No such file" in word, (reached, word)


def test_a_line_that_is_json_but_no_object_is_no_sample():
    """A command that prints a number or a word and ends has not reached the sampler: the next way to the node is
    tried, and the Hub is handed nothing."""
    reached, _, samples = heard('print("null"); print("7"); print(\'"motd"\'); print("[]")')
    assert reached is False and samples == [], (reached, samples)


def test_the_last_word_of_a_command_is_read_before_it_is_said():
    """ssh ends and its last word is still on its way through the pipe: the reason of a failed try is that word, not
    "The connection closed". Here the word comes a moment after the command ended, from a helper it left behind."""
    late = 'import sys, time; time.sleep(0.3); sys.stderr.write("ssh: connect to host dgx1: No route to host\\n")'
    code = f"import subprocess; subprocess.Popen([sys.executable, '-c', {late!r}], stdout=subprocess.DEVNULL)"
    reached, word, _ = heard(code)
    assert reached is False and word == "ssh: connect to host dgx1: No route to host", word


def test_a_head_that_cannot_be_read_ends_the_start_with_a_plain_word():
    """A head node that hangs, an ssh that is not there, an answer that is no node map: each ends the start with a
    sentence that says so, never with a traceback."""
    real = shell.run_python
    done = types.SimpleNamespace

    def hangs(*a, **k):
        raise subprocess.TimeoutExpired("ssh", 60)

    def no_ssh(*a, **k):
        raise FileNotFoundError(2, "No such file or directory: 'ssh'")

    unread = "Could not read the cluster on user@head: "
    cases = (
        (hangs, unread + "Command 'ssh' timed out"),
        (no_ssh, unread + "[Errno 2] No such file"),
        (lambda *a, **k: done(returncode=0, stdout="Welcome to dgx0\n", stderr=""), unread + "its answer is no"),
        (lambda *a, **k: done(returncode=255, stdout="", stderr="ssh: no route\n"), unread + "ssh: no route"),
        (lambda *a, **k: done(returncode=0, stdout="[1, 2]", stderr=""), "No config/nodes.json found"),
        (lambda *a, **k: done(returncode=0, stdout='{"nodes": []}', stderr=""), "No config/nodes.json found"),
    )
    try:
        for answer, word in cases:
            shell.run_python = answer
            try:
                found = shell.discover("user@head", None)
            except SystemExit as stop:
                assert str(stop.code).startswith(word), (word, stop.code)
            else:
                raise AssertionError(f"read a cluster from {word!r}: {found}")
    finally:
        shell.run_python = real


def test_old_logs_that_could_not_be_read_are_not_reported_as_none_found():
    """The reader of old engine logs failed on the head: the line ringtop writes says so, with the reason. It used
    to say "0 minutes of earlier runs read", the same words as for a head that has no old logs."""
    real, said = shell.run_python, io.StringIO()
    try:
        shell.run_python = lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="Permission denied\n")
        with contextlib.redirect_stderr(said):
            shell.backfill(None, "user@head")
        assert said.getvalue() == "ringtop: earlier runs not read: Permission denied\n", said.getvalue()
    finally:
        shell.run_python = real


def test_bytes_that_are_no_text_do_not_end_a_node_stream():
    """A banner in another encoding before the first sample: the line is no sample, the stream goes on."""
    reached, _, samples = heard('sys.stdout.buffer.write(b"\\xff\\xfe banner\\n{}\\n")')
    assert reached and samples == [{}], (reached, samples)


SAMPLES = "import sys, time; sys.stdin.read(); print('{}', flush=True); time.sleep(60)"  # a sampler that runs on


def as_sampler(node):
    """Commands for one Spark that start a stand-in sampler, with its name and the role it has now as arguments."""
    return [[sys.executable, "-c", SAMPLES, node["name"], "head" if node["head"] else "worker"]]


class Watched(NodeStream):
    """A node stream that notes the name and role of every command it starts, in `started`."""

    started: ClassVar[list] = []

    def stream(self, command):
        self.started.append(tuple(command[-2:]))
        return super().stream(command)


def started_to(streams, count):
    """Waits until the streams started `count` commands in all and each of their samplers runs."""
    deadline = time.time() + 20
    while time.time() < deadline:
        if len(Watched.started) >= count and all(s.process and s.process.poll() is None for s in streams):
            break
        time.sleep(0.05)
    assert len(Watched.started) == count, Watched.started


def first_part_on(hub, first):
    """Every Spark live with one part of an engine over all four on its GPU, the first part on Spark `first`."""
    with hub.lock:
        for k, node in enumerate(hub.nodes.values()):
            node.update(live=True, apps=[{"gb": 88.0, "name": f"VLLM::Worker_TP{(k - first) % 4}"}])


def test_a_spark_taken_for_the_head_gets_its_sampler_anew_with_the_role_of_head():
    """One look at a time (seek_once): once the hub takes another Spark for the head, the samplers of the old head
    and the new one end and start anew with the commands of their new role; the others run on. The change is no
    Spark gone away: nothing marks one down and no event says "Unreachable"."""
    node_map = ring_map()
    for node in node_map["nodes"]:
        node["head"] = False
    hub, downs, Watched.started = hub_for(node_map), [], []
    hub.node_down = lambda name, reason: downs.append(name)
    hub.ingest = lambda name, sample: None
    streams = [Watched(hub, node, as_sampler(node), as_sampler) for node in hub.cluster["nodes"]]
    try:
        for stream in streams:
            stream.start()
        started_to(streams, 4)
        for first, count in ((0, 5), (2, 7)):
            first_part_on(hub, first)
            shell.seek_once(hub, streams)
            shell.seek_once(hub, streams)
            started_to(streams, count)
        marked = list(downs)  # before the end of the check: ending the samplers below marks them down, as it should
    finally:
        for stream in streams:
            stream.commands[:] = []
            if stream.process:
                stream.process.terminate()
    seen = Watched.started
    assert sorted(seen[:4]) == [(f"dgx{i}", "worker") for i in range(4)], seen
    assert seen[4] == ("dgx0", "head") and set(seen[5:]) == {("dgx0", "worker"), ("dgx2", "head")}, seen
    assert marked == [] and not [e for e in hub.events if e["text"].startswith("Unreachable")], (marked, hub.events)


def test_a_new_role_that_lands_as_its_sampler_ends_does_not_end_the_stream_of_the_spark():
    """A retarget can land after the sampler ended and before its try was over (stream() still reads the
    last words of the command). The try then put a command first that was no longer in the list: a ValueError ended
    the thread, and that Spark was never reached again. A try of an older turn is now over without a mark: the stream
    starts anew with the commands of the new role, and nothing ends its thread."""
    hub, tries, died, hold = hub_for(), [], [], threading.Event()
    hub.node_down = lambda name, reason: None

    class Late(NodeStream):
        def stream(self, command):
            tries.append(command[0])
            if len(tries) == 1:
                self.retarget()  # lands between the end of the sampler and the end of its try
                return True, "The connection closed"
            hold.wait(5)
            return False, "held"

    stream = Late(hub, hub.cluster["nodes"][1], [["old"]], lambda node: [["new"]])
    before, threading.excepthook = threading.excepthook, lambda seen: died.append(seen.exc_value)
    try:
        stream.start()
        deadline = time.time() + 5
        while len(tries) < 2 and stream.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        alive = stream.is_alive()
    finally:
        stream.commands[:] = []
        hold.set()
        threading.excepthook = before
    assert tries[:2] == ["old", "new"] and died == [] and alive, (tries, died, alive)
