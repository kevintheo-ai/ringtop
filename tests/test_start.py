"""The start: what happens in which order when ringtop comes up."""

import contextlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

import ringtop
from ringtop_parts.connect.server import Handler
from ringtop_parts.connect.shell import node_commands
from tests.fixtures import NoStderr, ring_map


def test_started_by_its_full_path_a_second_ringtop_ends_before_it_writes_anything():
    """As the service starts it: by the full path of ringtop.py, from another folder, with a history file and a
    heartbeat. On a port that is taken it ends with an error, and neither file nor folder of the history exists."""
    with tempfile.TemporaryDirectory() as folder, socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        store, beat = Path(folder) / "history" / "history.db", Path(folder) / "beat" / "ringtop.json"
        files = ["--store", str(store), "--heartbeat", str(beat), "--runs-cmd", "true"]
        done = subprocess.run(
            [
                sys.executable,
                str(Path(ringtop.__file__).resolve()),
                "--demo",
                "--port",
                str(taken.getsockname()[1]),
                *files,
            ],
            cwd="/",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert done.returncode != 0 and "Address already in use" in done.stderr, (done.returncode, done.stderr[-300:])
        assert "ringtop on http" not in done.stdout, done.stdout
        assert not store.parent.exists() and not beat.parent.exists(), list(Path(folder).iterdir())


def fake_services(seen):
    """Stand-ins for what main() would open on this machine: the web server, a node stream and a thread. Each
    one notes in `seen` that it was built or started."""

    class Server:
        def __init__(self, address, handler):
            seen.order.append("server")
            seen.server = (address, handler)

        def serve_forever(self):
            seen.order.append("serving")

    class Stream:
        def __init__(self, hub, node, commands, remake=None):
            self.hub, self.node, self.commands, self.remake, self.process = hub, node, commands, remake, None

        def start(self):
            seen.order.append("stream " + self.node["name"])
            seen.streams.append(self)

    class Thread:
        def __init__(self, target, args=(), daemon=None):
            seen.threads.append((target, args, daemon))

        def start(self):
            seen.order.append("thread")

    return Server, Stream, Thread


def fake_ring(seen, found):
    """Stand-ins for the two ways main() gets a ring: the demo, and the node map `found` read from the head node."""

    class Show:
        ROUND = 300.0

        def __init__(self, hub, at, faults=False, form="ring4"):
            seen.demo, seen.faults, seen.form = (hub, at), faults, form

        def start(self):
            seen.order.append("demo")

    def discover(target, repo):
        seen.order.append("discover")
        seen.asked = (target, repo)
        return found

    return Show, discover


def put_back(real, handler):
    """Gives the module and the Handler back what the stand-ins replaced."""
    for name, value in real.items():
        setattr(ringtop, name, value)
    for name, value in handler.items():
        if value is None and name == "hub":
            with contextlib.suppress(AttributeError):
                del Handler.hub
        else:
            setattr(Handler, name, value)


def started(argv, found=None):
    """main() with the world outside replaced by stand-ins: what it built, started and asked for, in order.

    Nothing listens, nothing is reached over SSH and no thread runs; the store, if asked for, is a real file."""
    seen = types.SimpleNamespace(order=[], streams=[], threads=[], sleeps=[], exits=[], demo=None)
    (server, stream, thread), (show, discover) = fake_services(seen), fake_ring(seen, found)
    stand_ins = {
        "Listener": server,
        "NodeStream": stream,
        "Demo": show,
        "discover": discover,
        "threading": types.SimpleNamespace(Thread=thread),
        "time": types.SimpleNamespace(sleep=seen.sleeps.append, time=time.time),
        "atexit": types.SimpleNamespace(register=lambda *call: seen.exits.append(call)),
    }
    real = {name: getattr(ringtop, name) for name in stand_ins}
    handler = {name: Handler.__dict__.get(name) for name in ("hub", "allowed_hosts")}
    argv_before, said = sys.argv, io.StringIO()
    try:
        for name, stand_in in stand_ins.items():
            setattr(ringtop, name, stand_in)
        sys.argv = ["ringtop.py", *argv]
        try:
            with contextlib.redirect_stdout(said), contextlib.redirect_stderr(said):
                ringtop.main()
        except SystemExit as stop:
            stop.said, stop.order = said.getvalue(), seen.order  # what it said before it gave up, what it had opened
            raise
        seen.hub, seen.hosts, seen.said = Handler.hub, Handler.allowed_hosts, said.getvalue()
    finally:
        sys.argv = argv_before
        put_back(real, handler)
    return seen


def test_started_against_a_ring_the_port_comes_first_and_every_node_gets_its_sampler():
    """The order of a start against a real ring: the port, the history, the node map, one sampler per node in the
    order of the ranks (all with one salt), then the helpers, then the page. Told with stand-ins: nothing is reached."""
    found = {"nodes": ring_map(), "hostname": "dgx0", "repo": "/r/spark", "memguard_gib": 4, "shape": "tp4-ring"}
    with tempfile.TemporaryDirectory() as folder:
        store, beat = Path(folder) / "h" / "history.db", Path(folder) / "beat.json"
        asked = ["user@head", "--port", "18999", "--interval", "3", "--engine-port", "8888", "--repo", "/asked"]
        kept = ["--store", str(store), "--heartbeat", str(beat), "--runs-cmd", "echo run", "--watch-stdin"]
        seen = started([*asked, *kept], found)
        assert store.exists()  # opened after the port, before anything is asked of the ring
        seen.hub.store.db.close()
    assert seen.order[:6] == ["server", "discover", "stream dgx0", "stream dgx1", "stream dgx2", "stream dgx3"]
    assert seen.order[6:] == ["thread"] * 7 + ["serving"], seen.order
    assert seen.server == (("127.0.0.1", 18999), Handler) and seen.asked == ("user@head", "/asked")
    assert seen.sleeps == [0.2] * 4  # one SSH handshake at a time
    hub = seen.hub
    assert (hub.interval, hub.memguard_gib, hub.shape) == (3.0, 4, "tp4-ring") and hub.store is not None
    assert [n["name"] for n in hub.cluster["nodes"]] == ["dgx0", "dgx1", "dgx2", "dgx3"]
    salts = {stream.commands[0][-1].split()[-1] for stream in seen.streams}
    assert len(salts) == 1 and len(next(iter(salts))) == 32, salts  # hidden settings compare between nodes
    for stream, node in zip(seen.streams, hub.cluster["nodes"]):
        assert stream.hub is hub and stream.node == node
        assert stream.commands == node_commands(
            node, hub.cluster, "dgx0", "user@head", 3.0, "8888", "/r/spark", next(iter(salts))
        )
    targets = [(target.__name__, args) for target, args, _ in seen.threads]
    assert all(daemon is True for _, _, daemon in seen.threads)
    assert targets[0] == ("run", ()) and seen.threads[0][0].__self__ is hub.store  # the store writes in its own thread
    # beside the writer and after the port: the lowest values the history misses are read from its samples
    assert targets[1] == ("catch_up", ()) and seen.threads[1][0].__self__ is hub.store
    assert targets[2] == ("backfill", (hub.store, "user@head"))  # once, on an empty history
    assert targets[3] == ("heartbeat", (hub, beat)) and targets[4] == ("poll_runs", (hub, "echo run"))
    assert len(targets) == 7  # and the watch on stdin and the ticker, which take what they need from the start
    assert len(seen.exits) == 1  # the samplers' SSH sessions end with ringtop
    assert "localhost" in seen.hosts and "ringtop on http://127.0.0.1:18999" in seen.said


def test_started_as_a_demo_nothing_is_asked_of_a_ring():
    """The demo start: a made-up ring of four Sparks, the demo at the second asked for, no node map, no sampler, no
    backfill; without --store nothing is kept, and on another address than loopback it warns."""
    seen = started(["--demo", "--demo-at", "550", "--bind", "0.0.0.0", "--port", "18998"])
    assert seen.order == ["server", "demo", "thread", "serving"], seen.order
    hub, at = seen.demo
    assert hub is seen.hub and at == 250.0  # the second of the round, whatever round was asked for
    assert (hub.interval, hub.memguard_gib, hub.shape, hub.store) == (2.0, 3, "tp4-ring", None)
    assert [n["name"] for n in hub.cluster["nodes"]] == ["spark-0", "spark-1", "spark-2", "spark-3"]
    assert hub.cluster["ring"] and hub.cluster["nodes"][0]["head"] and not hub.cluster["nodes"][1]["head"]
    assert not seen.streams and not seen.sleeps and len(seen.threads) == 1 and len(seen.exits) == 1
    assert seen.server[0] == ("0.0.0.0", 18998) and "no login and is now reachable on 0.0.0.0" in seen.said
    with tempfile.TemporaryDirectory() as folder:
        kept = started(["--demo", "--store", str(Path(folder) / "h.db")])
        kept.hub.store.db.close()
    assert [thread[0].__name__ for thread in kept.threads] == ["run", "catch_up", "ticker"]  # no backfill


def test_a_start_that_cannot_work_ends_with_a_word():
    """A target that is no user@host, an interval under half a second, or seconds that are no number anything can
    wait for (nan, inf): an error of the command line, before anything is opened."""
    no_number = "invalid finite value"
    for argv, word in (
        (["bad;target"], "target must look like user@host"),
        (["--interval", "0.2"], "at least 0.5"),
        (["--demo", "--interval", "nan"], no_number),
        (["--demo", "--interval", "inf"], no_number),
        (["--demo", "--demo-at", "nan"], no_number),
        (["--demo", "--demo-at=-inf"], no_number),
        (["--demo", "--runs-cmd", "   "], "--runs-cmd needs a command"),  # blanks: its thread would end at once
    ):
        try:
            seen = started(argv)
        except SystemExit as stop:
            assert stop.code == 2 and word in stop.said, (stop.code, stop.said)
            assert stop.order == [], (argv, stop.order)  # not even the port
        else:
            raise AssertionError(f"started with {argv}: {seen.order}")


def test_the_address_it_prints_is_one_a_browser_opens():
    """The line a start prints names the page. An IPv6 address stands in brackets there, or it is no address."""
    for bind, said in (("::1", "ringtop on http://[::1]:18997"), ("127.0.0.1", "ringtop on http://127.0.0.1:18997")):
        seen = started(["--demo", "--bind", bind, "--port", "18997"])
        assert said in seen.said.splitlines(), seen.said


def test_a_moment_that_cannot_be_built_does_not_end_the_ticker():
    """The thread that hands the page its moments outlives a moment it cannot build (a figure reckoned from a reading
    that was not there): it says so on stderr, the page keeps the moment before, and the next one is tried. Without
    that, one such moment froze the page for good. The same trouble tick after tick is said once, and again once a
    good moment lay between."""

    class Done(BaseException):
        """Ends the loop of the ticker once the check has seen enough."""

    beats, naps = [], []

    def beat():
        beats.append(len(beats))
        if len(beats) in (1, 2, 4):
            raise TypeError("unsupported operand type(s) for +: 'NoneType' and 'float'")

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 5:
            raise Done

    real, said = ringtop.time, io.StringIO()
    ringtop.time = types.SimpleNamespace(sleep=nap)
    try:
        with contextlib.redirect_stderr(said), contextlib.suppress(Done):
            ringtop.ticker(types.SimpleNamespace(beat=beat), 2.0)
    finally:
        ringtop.time = real
    assert len(beats) == 5 and naps == [2.0] * 5, (beats, naps)  # every tick was tried, each after its pause
    lines = said.getvalue().splitlines()
    assert len(lines) == 2 and all("moment not built" in line and "NoneType" in line for line in lines), lines


def test_a_trouble_the_ticker_cannot_say_does_not_end_it_either():
    """The ticker says a moment it could not build on stderr. Where stderr cannot be written (the disk under the log
    of the service is full, nobody reads the pipe any more), saying it threw, out of the very net that keeps the
    loop: the page stood still for good. The trouble then goes unsaid, and the next moment is tried."""

    class Done(BaseException):
        """Ends the loop of the ticker once the check has seen enough."""

    beats, naps = [], []

    def beat():
        beats.append(len(beats))
        raise TypeError("no moment")

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 3:
            raise Done

    real = ringtop.time
    ringtop.time = types.SimpleNamespace(sleep=nap)
    try:
        with contextlib.redirect_stderr(NoStderr()), contextlib.suppress(Done):
            ringtop.ticker(types.SimpleNamespace(beat=beat), 2.0)
    finally:
        ringtop.time = real
    assert len(beats) == 3 and naps == [2.0] * 3, (beats, naps)


def test_a_heartbeat_that_cannot_be_written_is_missed_and_the_next_one_tried():
    """Every minute ringtop writes a small file for whatever watches the service. Where it cannot be written (a full
    disk), writing it threw out of the loop: no heartbeat came any more after the disk had room again, and the
    watcher called a service stale that was running. A heartbeat that cannot be written is one missed."""

    class Done(BaseException):
        """Ends the loop of the heartbeat once the check has seen enough."""

    naps = []
    with tempfile.TemporaryDirectory() as folder:
        blocked = Path(folder) / "in-the-way"
        blocked.write_text("a file where the folder of the heartbeat should be")
        beat = blocked / "ringtop.json"

        def nap(seconds):
            naps.append(seconds)
            if len(naps) == 2:
                blocked.unlink()  # the disk has room again
            if len(naps) == 3:
                raise Done

        hub = types.SimpleNamespace(lock=contextlib.nullcontext(), nodes={"dgx0": {"live": True}})
        real = ringtop.time
        ringtop.time = types.SimpleNamespace(sleep=nap, time=real.time, strftime=real.strftime, gmtime=real.gmtime)
        try:
            with contextlib.suppress(Done):
                ringtop.heartbeat(hub, beat)
        finally:
            ringtop.time = real
        assert naps == [60, 60, 60] and json.loads(beat.read_text())["status"] == "ok", naps


def test_a_node_map_from_a_file_is_read_here_and_nothing_is_asked_of_a_head():
    """--nodes FILE, for a cluster without spark-ds41f: the node map comes from a file on this machine and nothing is
    asked of a head. Every sampler runs without a checkout ("-"), and a target is only the way in: every Spark is
    reached by its name and through the target, none as the target itself. A file that cannot be read or holds no
    node map ends the start with a word before any sampler; --nodes beside --repo is an error of the command line."""
    with tempfile.TemporaryDirectory() as folder:
        path, broken = Path(folder) / "nodes.json", Path(folder) / "broken.json"
        path.write_text(json.dumps(ring_map()))
        broken.write_text("{ not json")
        seen = started(["user@gate", "--nodes", str(path), "--interval", "3"])
        for bad, word in (
            (broken, "Could not read the node map " + str(broken)),
            (Path(folder) / "missing.json", "Could not read the node map " + str(Path(folder) / "missing.json")),
            (path.with_name("empty.json"), "The node map lists no nodes"),
        ):
            if bad.name == "empty.json":
                bad.write_text("{}")
            try:
                started(["--nodes", str(bad)])
            except SystemExit as stop:
                assert str(stop.code).startswith(word) and stop.order == ["server"], (stop.code, stop.order)
            else:
                raise AssertionError(f"started from {bad}")
    try:
        started(["--nodes", str(path), "--repo", "/r"])
    except SystemExit as stop:
        assert stop.code == 2 and "--nodes" in stop.said and stop.order == [], (stop.code, stop.said)
    else:
        raise AssertionError("started with --nodes and --repo")
    assert "discover" not in seen.order and seen.order[:5] == ["server", *(f"stream dgx{i}" for i in range(4))]
    hub, salt = seen.hub, seen.streams[0].commands[0][-1].split()[-1]
    assert (hub.shape, hub.memguard_gib, hub.interval) == (None, None, 3.0)
    for stream, node in zip(seen.streams, hub.cluster["nodes"]):
        here = socket.gethostname()
        assert stream.commands == node_commands(node, hub.cluster, here, "user@gate", 3.0, "auto", None, salt, False)
        name = node["name"]  # the head too by its name, then through the target: never as the target itself
        assert [command[-2] for command in stream.commands] == [f"user@{name}", f"user@{name}.local", f"user@{name}"]
        assert stream.commands[2][-4:-2] == ["-J", "user@gate"] and stream.commands[0][-1].split()[6] == "-"


def test_a_map_without_a_head_starts_the_look_for_it_and_a_map_with_one_does_not():
    """Where the node map names no head, a thread looks for it (seek_head) with the samplers it may start anew;
    every sampler can make its commands anew for the role its Spark has then. A map that names the head
    starts no such thread."""
    with tempfile.TemporaryDirectory() as folder:
        headless, named = ring_map(), Path(folder) / "named.json"
        for node in headless["nodes"]:
            node["head"] = False
        (Path(folder) / "headless.json").write_text(json.dumps(headless))
        named.write_text(json.dumps(ring_map()))
        seen = started(["--nodes", str(Path(folder) / "headless.json")])
        kept = started(["--nodes", str(named)])
    looks = [args for target, args, _ in seen.threads if target.__name__ == "seek_head"]
    assert looks == [(seen.hub, seen.streams)], seen.threads
    assert not [t for t, _, _ in kept.threads if t.__name__ == "seek_head"], kept.threads
    node = seen.hub.cluster["nodes"][2]
    node["head"] = True
    remade = seen.streams[2].remake(node)
    salt = seen.streams[2].commands[0][-1].split()[-1]
    assert remade == node_commands(node, seen.hub.cluster, socket.gethostname(), None, 2.0, "auto", None, salt, False)
    assert remade[0][-1].split()[4] == "head" and seen.streams[2].commands[0][-1].split()[4] == "worker"


def test_a_form_of_the_demo_is_played_only_as_a_demo_and_the_one_without_a_head_looks_for_it():
    """--demo-form picks another made-up cluster; without it the demo is the ring of four it always was, and only
    that ring has the shape of the ring engine. Without --demo, or with a form the demo does not know, it is an error
    of the command line. In find4 the map names no head: the look for it starts, with no sampler to start anew."""
    six, plain, find = (started(["--demo", *more]) for more in (["--demo-form", "ring6"], [], ["--demo-form", "find4"]))
    assert (six.form, len(six.hub.cluster["nodes"]), six.hub.shape) == ("ring6", 6, None)
    assert (plain.form, len(plain.hub.cluster["nodes"]), plain.hub.shape) == ("ring4", 4, "tp4-ring")
    assert [args for target, args, _ in find.threads if target.__name__ == "seek_head"] == [(find.hub, [])]
    assert not [t for t, _, _ in six.threads if t.__name__ == "seek_head"], six.threads
    for argv, word in ((["--demo-form", "one"], "--demo-form needs --demo"), (["--demo", "--demo-form", "x"], "x")):
        try:
            started(argv)
        except SystemExit as stop:
            assert stop.code == 2 and word in stop.said and stop.order == [], (stop.code, stop.said)
        else:
            raise AssertionError(f"started with {argv}")


def test_a_spark_found_to_be_the_head_of_a_checkout_map_without_one_is_sampled_on_itself():
    """A spark-ds41f map that names no head was read on the target, but the target is no head then. The
    Spark the look finds got "ssh TARGET" as its first command, and its sampler ran on the target under its name.
    Where the map names no head the target is only the way in, as with --nodes: every Spark, the one found too, is
    reached by its own name first and through the target last. A map that names the head keeps the target first."""
    headless = ring_map()
    for node in headless["nodes"]:
        node["head"] = False
    seen = started(["user@gate"], {"nodes": headless, "hostname": "gate", "repo": "/r/spark"})
    node = seen.hub.cluster["nodes"][2]
    node["head"] = True
    found = seen.streams[2].remake(node)
    by_name = "user@dgx2"
    assert [command[-2] for command in found] == [by_name, by_name + ".local", by_name], found
    assert found[0][-1].split()[4] == "head" and found[2][-4:-2] == ["-J", "user@gate"], found
    assert all(c[-2] != "user@gate" for s in seen.streams for c in s.commands), [s.commands for s in seen.streams]
    named = started(["user@gate"], {"nodes": ring_map(), "hostname": "gate", "repo": "/r/spark"})
    assert named.streams[0].commands[0][-2] == "user@gate"  # the head of a map that names it: the target first
