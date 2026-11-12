"""The phone thread: when the start gives it a thread, what it says, that nothing ends it, that it holds up
nobody, what it keeps across a restart, and that the topic shows nowhere."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

import ringtop
from ringtop_parts.connect import notify
from ringtop_parts.connect.notify import Phone, Trying, turn, watch
from ringtop_parts.connect.server import API
from ringtop_parts.core.alerts import begun
from tests.catcher import CANARY, Catcher, answer, closed_port, silent, topic_command
from tests.fixtures import engine_sample, hub_for, ring_map, serving
from tests.test_notify import exact
from tests.test_start import started
from tests.test_start_wall import free_port

T0 = 1_800_000_000.0
GONE = {"nodes": [{"name": "dgx0", "head": True, "live": False}], "engine": {"state": "offline"}}
THERE = {"nodes": [{"name": "dgx0", "head": True, "live": True}], "engine": {"state": "idle"}}


def phone(command=None, server="http://127.0.0.1:9", keep=None, dry=False):
    """How the thread is asked for in these checks: every wait is nothing, so a trouble is told at the first look."""
    return Phone(command, server, keep, dry, demo=False, pace=0.0)


@contextlib.contextmanager
def stand_ins(**replaced):
    """Parts of notify replaced by stand-ins for one check, and put back after it."""
    real = {name: getattr(notify, name) for name in replaced}
    for name, stand_in in replaced.items():
        setattr(notify, name, stand_in)
    try:
        yield
    finally:
        for name, value in real.items():
            setattr(notify, name, value)


def never(*call, **more):
    raise AssertionError(f"called with {len(call)} arguments")


@contextlib.contextmanager
def watching(hub, asked):
    """watch in a thread of its own on this hub, until the check is over. The thread is ended from outside: it
    never ends by itself."""
    over, real = threading.Event(), hub.wait_tick

    def wait_tick(seen, timeout=15.0):
        if over.is_set():
            raise SystemExit  # a thread that ends this way says nothing
        return real(seen, 0.05)

    hub.wait_tick = wait_tick
    thread = threading.Thread(target=watch, args=(hub, asked), daemon=True)
    thread.start()
    try:
        yield thread
    finally:
        over.set()
        thread.join(30)
        del hub.wait_tick
        assert not thread.is_alive()


def until(holds, patience=20.0):
    """Waits until something holds, and says whether it did."""
    deadline = time.time() + patience
    while not holds() and time.time() < deadline:
        time.sleep(0.01)
    return holds()


def test_without_its_option_no_thread_is_started_and_with_it_one_beside_the_ticker():
    """Without --ntfy-topic-cmd everything is as it was: no thread, no call. With it, or with --ntfy-dry, one
    more thread that ends with ringtop, started before the ticker and handed the hub and what was asked for."""
    assert [thread[0].__name__ for thread in started(["--demo", "--port", "18990"]).threads] == ["ticker"]
    for alone in (["--ntfy-state", "/tmp/x.json"], ["--ntfy-server", "http://127.0.0.1:18700"]):
        assert [thread[0].__name__ for thread in started(["--demo", *alone]).threads] == ["ticker"], alone
    dry = started(["--demo", "--port", "18990", "--ntfy-dry"])
    assert [thread[0].__name__ for thread in dry.threads] == ["watch", "ticker"]
    target, (hub, asked), daemon = dry.threads[0]
    assert target is ringtop.watch and hub is dry.hub and daemon is True
    assert asked == Phone(None, "https://ntfy.sh", None, True, demo=True, pace=1.0), asked
    real = ["--ntfy-topic-cmd", "/bin/cat /x/topic", "--ntfy-state", "~/r/alerts.json"]
    live = started(["--demo", *real, "--ntfy-server", "http://127.0.0.1:18700/"])
    kept_in = Path.home() / "r" / "alerts.json"
    assert live.threads[0][1][1] == Phone("/bin/cat /x/topic", "http://127.0.0.1:18700", kept_in, False, demo=True)
    found = {"nodes": ring_map(), "hostname": "dgx0"}
    ring = started(["user@head", "--ntfy-topic-cmd", "/bin/cat /x/topic"], found)
    names = [thread[0].__name__ for thread in ring.threads]
    assert names == ["watch", "ticker"], names
    assert ring.threads[0][1] == (ring.hub, Phone("/bin/cat /x/topic", "https://ntfy.sh", None, False, demo=False))


def test_an_option_of_the_phone_that_cannot_work_ends_the_start_with_a_word():
    for argv, word in (
        (["--ntfy-topic-cmd", "   "], "--ntfy-topic-cmd needs a command"),
        (["--ntfy-topic-cmd", ""], "--ntfy-topic-cmd needs a command"),
        (["--ntfy-dry", "--ntfy-server", "http://ntfy.sh"], "--ntfy-server takes"),
        (["--ntfy-server", "https://ntfy.sh/topic"], "--ntfy-server takes"),
        (["--ntfy-server", "http://localhost:18700"], "--ntfy-server takes"),
        (["--ntfy-server", "http://127.0.0.1:70001"], "--ntfy-server takes"),
    ):
        try:
            seen = started(["--demo", *argv])
        except SystemExit as stop:
            assert stop.code == 2 and word in stop.said, (argv, stop.code, stop.said)
            assert stop.order == [], (argv, stop.order)  # not even the port
        else:
            raise AssertionError(f"started with {argv}: {seen.order}")


def test_a_dry_run_says_what_it_would_send_and_asks_for_no_topic():
    """--ntfy-dry works everything out and prints the key of each message it would send, once. It needs no
    topic: the command for one is not run, and nothing is sent."""
    out, state, trying = io.StringIO(), begun(), Trying()
    with stand_ins(topic_from=never, send=never), contextlib.redirect_stdout(out):
        for i, moment in enumerate([GONE] * 5 + [THERE] * 5 + [GONE]):
            state = turn(phone(command="/bin/false", dry=True), state, trying, moment, T0 + 2 * i)
    assert out.getvalue().splitlines() == ["would notify: away on", "would notify: away off", "would notify: away on"]


def test_a_message_that_went_out_is_said_and_one_that_did_not_is_tried_again_ever_later():
    """A try that failed is tried again after 30 s, then after twice as long each time, every 15 minutes at the
    most, without end. It is said once per trouble with the sending, with the word of the failure and nothing
    else; when the message is out, that is said."""
    tried, words = [], ["http 500"] * 8 + ["timeout"] * 2 + [None]
    out, state, trying, clock = io.StringIO(), begun(), Trying(), [T0]

    def send(server, topic, key, demo, limit, names=()):
        tried.append((round(clock[0] - T0), server, topic, key, demo, limit, names))
        return words[len(tried) - 1], False  # a refusal, or nothing left: it did not reach the phone

    with stand_ins(send=send), topic_command() as command, contextlib.redirect_stdout(out):
        asked = phone(command, "http://127.0.0.1:18700")
        while len(tried) < len(words) and clock[0] < T0 + 20_000:
            state = turn(asked, state, trying, GONE, clock[0])
            clock[0] += 2.0
        state = turn(asked, state, trying, GONE, clock[0])
    assert [at for at, *_ in tried] == [0, 30, 90, 210, 450, 930, 1830, 2730, 3630, 4530, 5430], tried
    # the Spark of this moment has no place in the ring (no cluster in it): no name, which the gap says in its word
    assert {call[1:] for call in tried} == {("http://127.0.0.1:18700", CANARY, "away on", False, notify.LIMIT, (None,))}
    assert out.getvalue().splitlines() == [
        "not notified: away on (http 500), next try in 30 s",
        "not notified: away on (timeout), next try in 900 s",
        "notified: away on",
    ], out.getvalue()
    assert state["told"]["away"] is True and len(tried) == 11 and CANARY not in out.getvalue()
    assert len(state["sent"]) == 1  # ten tries that reached no phone took nothing of the cap of the day


def test_without_a_topic_nothing_is_sent_and_it_is_asked_for_again_before_the_next_try():
    """The command gives no topic (the keychain is locked, the entry is not made yet): that is a try that
    failed, said once, and before the next try the command is asked again."""
    topics, sent = [None, None, CANARY], []
    out, state, trying = io.StringIO(), begun(), Trying()

    def send(server, topic, key, demo, limit, names=()):
        sent.append((topic, key))
        return None, False

    with stand_ins(topic_from=lambda command: topics.pop(0), send=send), contextlib.redirect_stdout(out):
        for i in range(60):
            state = turn(phone("/bin/cat /x/topic"), state, trying, GONE, T0 + 2 * i)
    assert sent == [(CANARY, "away on")] and topics == []
    assert out.getvalue().splitlines() == ["not notified: away on (no topic), next try in 30 s", "notified: away on"]


def test_a_message_that_is_no_longer_so_before_it_went_out_is_dropped_and_that_is_said():
    out, state, trying = io.StringIO(), begun(), Trying()

    def refused(*call):
        return "http 503", False

    with stand_ins(topic_from=lambda command: CANARY, send=refused), contextlib.redirect_stdout(out):
        for i, moment in enumerate([GONE] * 3 + [THERE] * 30):
            state = turn(phone("/bin/cat /x/topic"), state, trying, moment, T0 + 2 * i)
    assert out.getvalue().splitlines() == [
        "not notified: away on (http 503), next try in 30 s",
        "dropped: away on (over before it went out)",
    ], out.getvalue()
    assert state["told"]["away"] is False and trying == Trying()  # the next trouble is tried at once again


def test_whatever_goes_wrong_with_a_try_the_log_never_shows_the_topic():
    """Through the real way out, against a catcher that fails in every way: a deadline, a refusal, 429, 500, a
    redirect. Each is one line with the key and one word."""
    dead = closed_port()
    replies = (answer(429, "Too Many"), answer(500, f"Oops {CANARY}", body=CANARY.encode()), silent)
    replies += (answer(302, "Found", Location=f"http://127.0.0.1:{dead}/{CANARY}"),)
    with topic_command() as command:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            for reply in replies:
                # only the one that never answers runs into its limit: the others have all the time they need
                with stand_ins(LIMIT=0.5 if reply is silent else 60.0), Catcher(reply) as server:
                    turn(phone(command, server.address), begun(), Trying(), GONE, T0)
                    assert len(server.caught(1)) == 1
                for worker in notify.FLYING:
                    worker.join(10)
            turn(phone(command, f"http://127.0.0.1:{dead}"), begun(), Trying(), GONE, T0)
    lines = out.getvalue().splitlines()
    words = ["http 429", "http 500", "timeout", "http 302", "ConnectionRefusedError"]
    told = [f"not notified: away on ({word}), next try in 30 s" for word in words]
    told[2] = "maybe notified: away on (timeout), counted, once more in 30 s"  # it got the request, said nothing
    assert lines == told, lines
    assert err.getvalue() == "" and CANARY not in out.getvalue()


def test_for_real_a_trouble_reaches_the_catcher_a_restart_tells_nothing_twice_and_the_topic_is_nowhere():
    """The whole way with a real hub, a real thread, the real way out and a file: every Spark is out of reach,
    the catcher gets the fixed text, the file keeps that the phone was told. A second start with that file
    tells nothing again while the trouble lasts, and its end once. Then the topic is looked for in everything
    that was printed, in the file, and in every answer of the web server."""
    hub = hub_for()
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as folder, Catcher() as server, topic_command() as command:
        file = Path(folder) / "state" / "alerts.json"
        asked = phone(command, server.address, file)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with watching(hub, asked):
                hub.beat()
                assert len(server.caught(1)) == 1
                assert until(lambda: file.is_file() and "away" in file.read_text())
                first = json.loads(file.read_text())
                assert first["told"] == ["away"] and len(first["sent"]) == 1 and first["hushed"] is False, first
            with watching(hub, asked):  # the restart
                for _ in range(5):
                    hub.beat()
                    time.sleep(0.05)
                assert until(lambda: out.getvalue().count("phone messages: on") == 2)
                assert len(server.caught(1)) == 1  # the trouble lasts: not told again
                now = time.time()
                hub.ingest("dgx0", engine_sample(now, 100.0, running=0.0))
                for name in ("dgx1", "dgx2", "dgx3"):
                    hub.ingest(name, {"t": now})
                hub.beat()
                assert len(server.caught(2)) == 2
                assert until(lambda: json.loads(file.read_text())["told"] == [])
        # the whole request, byte for byte: a value of the moment in a header would show here as in the body
        four = ("spark-1", "spark-2", "spark-3", "spark-4")  # every Spark is out of reach: all four by place
        assert server.got == [exact("away on", server.port, names=four), exact("away off", server.port)], server.got
        kept_text = file.read_text()
        assert sorted(json.loads(kept_text)) == ["hushed", "sent", "told"] and len(json.loads(kept_text)["sent"]) == 2
        assert list(file.parent.iterdir()) == [file]  # no spare file left beside it
    said = out.getvalue()
    assert said.splitlines() == [
        "ringtop: phone messages: on",
        "notified: away on",
        "ringtop: phone messages: on",
        "notified: away off",
    ], said
    assert err.getvalue() == ""
    hub.beat()
    with serving(hub) as ask:
        # of a stream the moment that is there: its line and the empty one behind it (the next comes with a tick)
        answers = [ask(path, lines=2 if path in ("/api/events", "/api/wall") else 0)[2] for path in API]
        answers.append(ask("/")[2])
    assert len(answers) == len(API) + 1 == 9 and all(answers)
    for text in (said, kept_text, *(body.decode("utf-8", "replace") for body in answers)):
        assert CANARY not in text and "dgx" not in kept_text


def test_a_catcher_that_never_answers_does_not_hold_up_the_ticker():
    """While a try hangs, the thread that builds the moments goes on as if there were no phone: the phone
    thread holds no lock of the hub while it sends, and no other thread waits for it."""
    hub = hub_for()
    with stand_ins(LIMIT=60.0), Catcher(silent) as server, topic_command() as command:
        asked = phone(command, server.address)
        with contextlib.redirect_stdout(io.StringIO()) as out, watching(hub, asked):
            hub.beat()
            assert len(server.caught(1)) == 1  # the request is out and nobody answers: the try hangs now
            began, before = time.time(), hub.tick
            for _ in range(25):
                hub.beat()
            took = time.time() - began
            assert hub.tick == before + 25 and took < 10.0, took
            assert hub.lock.acquire(timeout=5.0)
            hub.lock.release()
            with serving(hub) as ask:  # and the page is served meanwhile
                assert ask("/api/state")[0] == 200 and ask("/metrics")[0] == 200
            assert any(worker.is_alive() for worker in notify.FLYING) and "notified" not in out.getvalue()
            server.hang_up()  # the try ends, and with it the wait of this check
            assert until(lambda: "maybe notified: away on (" in out.getvalue())  # the server had the request
    for worker in notify.FLYING:
        worker.join(10)


def test_nothing_a_moment_holds_ends_the_thread():
    """A moment that is no table, bytes that are no JSON, a trouble inside the step: each is passed over, said
    once by the kind of the failure and never by its text, and the next moment is read."""
    payloads = [b"[1, 2]", b"[3]", b"no json", json.dumps(GONE).encode(), None, json.dumps(THERE).encode()]
    ticks, naps = iter(range(1, 100)), []

    def wait_tick(seen, timeout=15.0):
        if not payloads:
            raise SystemExit
        return payloads.pop(0), next(ticks)

    out, err = io.StringIO(), io.StringIO()
    real = notify.time
    notify.time = types.SimpleNamespace(time=real.time, sleep=naps.append)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), contextlib.suppress(SystemExit):
            watch(types.SimpleNamespace(wait_tick=wait_tick), phone(dry=True))
    finally:
        notify.time = real
    assert out.getvalue().splitlines() == [
        "ringtop: phone messages: dry run, nothing is sent",
        "ringtop: phone messages: a moment was passed over (AttributeError)",
        "ringtop: phone messages: a moment was passed over (JSONDecodeError)",
        "would notify: away on",
        "would notify: away off",
    ], out.getvalue()
    assert err.getvalue() == "" and naps == [1.0, 1.0, 1.0], naps


def test_a_file_that_cannot_be_read_or_written_costs_nothing_but_a_message_told_twice():
    """What was kept is read once at the start; a file that is missing, broken or in the way starts from
    nothing. One that cannot be written is tried again with the next moment. A dry run touches no file."""

    def taken(*call):
        return None, False

    with tempfile.TemporaryDirectory() as folder, stand_ins(topic_from=lambda command: CANARY, send=taken):
        file, out = Path(folder) / "in-the-way" / "alerts.json", io.StringIO()
        file.parent.write_text("a file where the folder should be")
        payloads = [json.dumps(GONE).encode()] * 3
        ticks = iter(range(1, 100))

        def wait_tick(seen, timeout=15.0):
            if not payloads:
                raise SystemExit
            if len(payloads) == 1 and file.parent.is_file():
                file.parent.unlink()  # what was in the way is gone: from now on the file can be written
            return payloads.pop(0), next(ticks)

        hub = types.SimpleNamespace(wait_tick=wait_tick)
        with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
            watch(hub, phone("/bin/cat /x/topic", keep=file))
        assert out.getvalue().splitlines() == [
            "ringtop: phone messages: on",
            "notified: away on",
            "ringtop: phone messages: what the phone was told is not kept (FileExistsError), tried again",
        ], out.getvalue()
        assert json.loads(file.read_text())["told"] == ["away"]  # written with the first moment it could be
        for broken in ("", "{", "[1]", '{"told": 7}'):
            file.write_text(broken)
            payloads[:] = [json.dumps(GONE).encode()]
            with contextlib.redirect_stdout(io.StringIO()) as again, contextlib.suppress(SystemExit):
                watch(hub, phone("/bin/cat /x/topic", keep=file))
            assert "notified: away on" in again.getvalue(), broken  # told once more, and kept again
            assert json.loads(file.read_text())["told"] == ["away"], broken
        before = file.read_text()
        payloads[:] = [json.dumps(GONE).encode()] * 2
        with contextlib.redirect_stdout(io.StringIO()) as dry, contextlib.suppress(SystemExit):
            watch(hub, phone("/bin/cat /x/topic", keep=file, dry=True))
        # it did not read that the phone was told (it would say nothing then), and it did not write that it is
        assert dry.getvalue().count("would notify: away on") == 1 and file.read_text() == before


def test_started_for_real_the_phone_thread_reads_the_topic_and_sends_nothing_without_a_trouble():
    """As the service starts it, with the demo: the start says that messages are on, without the topic, and
    in a round without trouble no request leaves. The topic is in no argument of the process."""
    port = free_port()
    with tempfile.TemporaryDirectory() as folder, Catcher() as server, topic_command() as command:
        out, err, state = Path(folder) / "out", Path(folder) / "err", Path(folder) / "alerts.json"
        argv = [sys.executable, str(Path(ringtop.__file__).resolve()), "--demo", "--port", str(port)]
        argv += ["--ntfy-topic-cmd", command, "--ntfy-server", server.address, "--ntfy-state", str(state)]
        assert CANARY not in " ".join(argv)
        with out.open("w") as o, err.open("w") as e:
            running = subprocess.Popen(argv, cwd="/", stdout=o, stderr=e)
        try:
            assert until(lambda: "phone messages" in out.read_text() or running.poll() is not None, 30)
            time.sleep(1.0)
            said = out.read_text()
            assert running.poll() is None and "ringtop: phone messages: on" in said.splitlines(), said
            assert CANARY not in said and err.read_text() == "" and server.got == [] and not state.exists()
        finally:
            running.terminate()
            running.wait(timeout=20)
