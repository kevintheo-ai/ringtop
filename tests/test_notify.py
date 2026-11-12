"""The one way to a phone: where the topic comes from, the exact bytes of a message, and that no failure, no
answer and no detour ever shows the topic. Everything here stays on 127.0.0.1."""

import contextlib
import io
import os
import socket
import tempfile
import threading
import time
import types
from pathlib import Path

from ringtop_parts.connect import notify
from ringtop_parts.connect.notify import send, server_of, topic_from
from ringtop_parts.core import alerts
from ringtop_parts.core.alerts import PLACEHOLDER, TEXTS
from tests.catcher import (
    CANARY,
    HUGE_TAKEN,
    TAKEN,
    TRICKLE_ENDED,
    Catcher,
    answer,
    closed_port,
    huge,
    silent,
    topic_command,
    trickle,
)


@contextlib.contextmanager
def nothing_said():
    """Whatever runs inside may print nothing, neither to stdout nor to stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield
    assert out.getvalue() == "" and err.getvalue() == "", (out.getvalue(), err.getvalue())


def landed():
    """Waits until a try that outlived its limit has ended, so the next check starts with none hanging."""
    for worker in notify.FLYING:
        worker.join(10)
        assert not worker.is_alive()


def test_the_topic_is_what_a_command_prints_and_only_if_it_looks_like_a_secret():
    """--ntfy-topic-cmd names a command, as --runs-cmd does: split into words, no shell, ten seconds. What it
    prints is the topic if it is 32 to 64 signs of A-Z a-z 0-9 _ and -, of at least ten different ones, and
    nothing else is one: a short or a guessable topic is a public one. Nothing the command says is ever printed."""
    with nothing_said():
        with topic_command() as command:
            assert topic_from(command) == CANARY
        edge = "abcdefghij" * 7  # the ends of the length: 32 and 64 pass, 31 and 65 do not
        for good in ("abcdefghij" * 4, "Z9_-xY7wQ3" * 6 + "ab", "0123456789" * 4, edge[:32], edge[:64]):
            with topic_command(good) as command:
                assert topic_from(command) == good
        for bad in (
            "a" * 32,  # one sign over and over: guessed at once
            "0" * 40,
            "-" * 40,
            "ringtop" * 5,
            "Z9_-" * 16,
            "abcdefghi" * 5,  # nine different signs
            "abcdefghij"[:3] * 11,
            "abcdefghij" * 3,  # thirty signs: too short
            "abcdefghij" * 7,  # seventy: too long
            edge[:31],
            edge[:65],
            "",
            "abcdefghij" * 4 + "/",
            "abcdefghij" * 2 + " " + "abcdefghij" * 2,
            "abcdefghij" * 4 + "\n" + "klmnopqrst" * 4,
        ):
            with topic_command(bad) as command:
                assert topic_from(command) is None, bad
        assert topic_from(f"/bin/sh -c 'echo {CANARY}; exit 3'") is None  # a command that failed said nothing
        for no_command in ("/nonexistent/ringtop-topic", "", "   ", "'", "/bin/cat /nonexistent/topic"):
            assert topic_from(no_command) is None, no_command
        began = time.time()
        assert topic_from("/bin/sleep 30", limit=0.3) is None and time.time() - began < 15
    with tempfile.TemporaryDirectory() as folder:  # no shell: what follows a semicolon is a word, never a command
        mark = Path(folder) / "ran"
        assert topic_from(f"/bin/echo {CANARY}; /usr/bin/touch {mark}") is None and not mark.exists()


def test_of_what_the_command_prints_no_more_is_read_than_a_topic_needs():
    """A command that prints far more than a topic (a wrong one in the option) is read a few KB far and then
    ended: no memory fills up, and nothing waits for the end of it. A topic after 6 KB of space is not read, and
    one that ends within TOPIC_READ bytes is: a case of 6 KB that is no topic by its
    signs would pass a limit of 32 KB too."""
    with nothing_said():
        began = time.time()
        assert topic_from("/bin/sh -c 'head -c 65536 /dev/zero; sleep 5'", limit=3.0) is None
        assert time.time() - began < 1.5, time.time() - began  # it stopped reading at a few KB, it did not wait
        with tempfile.TemporaryDirectory() as folder:
            lines = Path(folder) / "lines"
            lines.write_text("\n" * 6000 + CANARY + "\n")  # 6 KB before the topic: only the limit makes it none
            assert topic_from(f"/bin/cat {lines}") is None
            for size, read in ((notify.TOPIC_READ, CANARY), (notify.TOPIC_READ + 1, None)):
                lines.write_text("\n" * (size - len(CANARY) - 1) + CANARY + "\n")  # `size` bytes in all
                assert topic_from(f"/bin/cat {lines}") == read, size
            lines.write_text("\n" * 100 + CANARY + "\n")  # a topic within the first few KB, around it only space
            assert topic_from(f"/bin/cat {lines}") == CANARY


def test_a_server_is_https_anywhere_or_plain_http_on_this_machine_and_nothing_else():
    for good, read in (
        ("https://ntfy.sh", "https://ntfy.sh"),
        ("https://ntfy.sh/", "https://ntfy.sh"),
        ("https://push.example.org:8443", "https://push.example.org:8443"),
        ("https://push.example.org:65535", "https://push.example.org:65535"),
        ("http://127.0.0.1:18700", "http://127.0.0.1:18700"),
        ("http://127.0.0.1:18700/", "http://127.0.0.1:18700"),
        ("http://127.0.0.1:1", "http://127.0.0.1:1"),
    ):
        assert server_of(good) == read, good
    for bad in (
        "http://127.0.0.1:70001",  # no such port: it would fail at every try, and only the log would say so
        "http://127.0.0.1:65536",
        "http://127.0.0.1:0",
        "https://ntfy.sh:99999",
        "https://ntfy.sh:0",
        "http://ntfy.sh",  # the topic would cross the network in the clear
        "http://localhost:18700",
        "http://127.0.0.1",
        "http://127.0.0.2:18700",
        "http://127.0.0.1:18700/topic",
        "https://ntfy.sh/topic",
        "https://ntfy.sh?x=1",
        "https://user:word@ntfy.sh",
        "https://ntfy.sh#x",
        "https://",
        "ntfy.sh",
        "file:///etc/passwd",
        "ftp://ntfy.sh",
        " https://ntfy.sh",
        "https://ntfy.sh\n",
        "",
    ):
        try:
            server_of(bad)
        except ValueError as problem:
            assert "--ntfy-server" in str(problem), bad
        else:
            raise AssertionError(f"{bad!r} passed as a server")


TOOK = (None, False)  # what send gives when the server took the message: no word, and nothing left in doubt


def exact(key: str, port, demo: bool = False, names=()) -> bytes:
    """The request of one message as it has to reach a catcher on a port of 127.0.0.1, byte for byte."""
    message = alerts.message(key, demo, names)
    lines = [
        f"POST /{CANARY} HTTP/1.1",
        f"Host: 127.0.0.1:{port}",
        "Accept-Encoding: identity",
        f"Content-Length: {len(message['body'])}",
        "Content-Type: text/plain; charset=utf-8",
        "User-Agent: ringtop",
        f"Title: {message['title']}",
        f"Priority: {message['priority']}",
        f"Tags: {message['tags']}",
    ]
    return ("\r\n".join(lines) + "\r\n\r\n" + message["body"]).encode("ascii")


def test_a_message_is_exactly_these_bytes():
    """One POST to /TOPIC. The head says what kind of text comes, who sends it, the title, how urgent and the
    sign; the body is the fixed text. Beside that only what http.client writes itself: the host, no encoding,
    the length. No header ntfy would act on beyond those (Click, Icon, Attach, Actions, Email, Markdown, Cache,
    Firebase), and nothing of the ring."""
    with Catcher() as phone, nothing_said():
        assert send(phone.address, CANARY, "fan on") == TOOK
        assert send(phone.address, CANARY, "fan off") == TOOK
        assert send(phone.address, CANARY, "quiet", demo=True) == TOOK
    assert phone.got == [exact("fan on", phone.port), exact("fan off", phone.port), exact("quiet", phone.port, True)]
    assert [request.count(b" (demo)\r\n") for request in phone.got] == [0, 0, 1]


def test_every_body_that_goes_out_is_byte_for_byte_a_text_of_the_table():
    with Catcher() as phone, nothing_said():
        for key in TEXTS:
            assert send(phone.address, CANARY, key) == TOOK, key
    bodies = [request.partition(b"\r\n\r\n")[2] for request in phone.got]
    assert bodies == [alerts.message(key)["body"].encode("ascii") for key in TEXTS] and len(bodies) == 11
    with Catcher() as phone:  # and nothing that is no key of the table ever becomes a message
        for no_key in ("fan", "fan on\r\nTitle: x", "dgx1 is away", ""):
            try:
                send(phone.address, CANARY, no_key)
            except KeyError:
                continue
            raise AssertionError(f"{no_key!r} was sent")
    assert phone.got == []


def test_no_failure_says_the_topic_and_each_ends_within_its_limit():
    """What comes back from a try that failed is one word for the log: the status, or the kind of the failure.
    Never the topic, the address with its path, the answer, or the text of an error. And a try ends at its
    limit, whatever the other side does: says nothing, sends a byte every fifth of a second, or 50 MB. Beside
    the word: whether the message may have reached the server all the same. Not when the server answered with
    a status that is no 2xx (it says it did not take it), not when no connection was made; yes when it got the
    request and the answer fails to come or makes no sense, and yes for 502 and 504, which a gateway in front of
    the server may say after the server has the message. A status below 200 or from 600 on is no final answer:
    yes as well."""
    dead = closed_port()
    cases = (
        (answer(429, "Too Many Requests", body=CANARY.encode()), "http 429", False),
        (answer(500, "Internal Server Error", body=b"topic " + CANARY.encode()), "http 500", False),
        (answer(503, "Service Unavailable"), "http 503", False),
        (answer(502, "Bad Gateway"), "http 502", True),  # a gateway in front of the server: it may have it already
        (answer(504, "Gateway Timeout"), "http 504", True),
        (answer(404, "Not Found"), "http 404", False),
        (answer(403, f"Forbidden {CANARY}"), "http 403", False),
        (answer(304, "Not Modified"), "http 304", False),
        # no final answer, from the server or a box in front of it: it may have the message
        (answer(103, "Early Hints") + TAKEN, "http 103", True),
        (answer(600, "Unknown"), "http 600", True),
        (b"no HTTP at all " + CANARY.encode() + b"\r\n\r\n", "BadStatusLine", True),
        (b"", "RemoteDisconnected", True),
        (silent, "timeout", True),
        (trickle, "timeout", True),  # the head of its answer is whole after 7.8 s, and it says 200
    )
    # what a try left behind says as it ends is heard as well: the catcher hangs up and the try has ended before
    # nothing_said looks at what was printed
    for reply, word, maybe in cases:
        with nothing_said():
            with Catcher(reply) as phone:
                began = time.time()
                # the two that never give a whole answer run into a short limit; the others have the time they need
                said = send(phone.address, CANARY, "away on", limit=0.6 if callable(reply) else 60.0)
                assert not callable(reply) or time.time() - began < 5, (word, time.time() - began)
                assert len(phone.caught(1)) == 1, word
            landed()
        assert said == (word, maybe) and CANARY not in said[0], (word, said)
    with nothing_said():
        assert send(f"http://127.0.0.1:{dead}", CANARY, "away on") == ("ConnectionRefusedError", False)
    HUGE_TAKEN.clear()
    with nothing_said():
        with Catcher(huge) as phone:
            began = time.time()
            assert send(phone.address, CANARY, "away on") == TOOK  # it took the message: the rest is not read
            assert time.time() - began < 8
            deadline = time.time() + 10
            while not HUGE_TAKEN and time.time() < deadline:
                time.sleep(0.02)
        landed()
    assert len(HUGE_TAKEN) == 1 and HUGE_TAKEN[0] < 400, HUGE_TAKEN  # of 800 pieces: the connection was closed on it


def test_at_its_limit_a_try_is_over_with_its_connection_and_the_next_one_may_run():
    """A peer that sends a byte now and then holds no try beyond its limit: the try is ended then and its
    connection shut, so the next one can be made at once. One thread and one connection at the most."""
    TRICKLE_ENDED.clear()
    with Catcher(trickle) as phone:
        for count in (1, 2):
            began = time.time()
            assert send(phone.address, CANARY, "away on", limit=0.4) == ("timeout", True)  # it got the request
            for worker in notify.FLYING:
                worker.join(2)
            assert not any(worker.is_alive() for worker in notify.FLYING) and time.time() - began < 3
            assert len(phone.caught(count)) == count
            deadline = time.time() + 5
            while len(TRICKLE_ENDED) < count and time.time() < deadline:
                time.sleep(0.01)
            assert len(TRICKLE_ENDED) == count, TRICKLE_ENDED  # the peer saw its connection shut


def test_a_handshake_that_never_ends_is_broken_off_at_the_limit_as_well():
    """Over https the handshake is part of the try: a server that never answers it holds the try no longer than
    its limit either, and what it got is no word of the message. The limit is long enough for the handshake to
    have begun, in a suite whose leftover threads take their share of the time as well."""
    said = {"title": "Ringtop", "body": "A text that is written.", "priority": "high", "tags": "warning"}
    with Catcher(silent) as server:
        began = time.time()
        answer = notify.within(3.0, f"https://127.0.0.1:{server.port}", CANARY, said)
        for worker in notify.FLYING:
            worker.join(3)
        took, hangs = time.time() - began, any(worker.is_alive() for worker in notify.FLYING)
        assert answer == ("timeout", False) and not hangs and took < 6, (answer, hangs, took)
        got = b"".join(server.caught(1))
    assert got and CANARY.encode() not in got and b"written" not in got, got  # a greeting of TLS, and nothing else


def test_a_try_still_on_its_way_to_the_server_holds_up_the_next_and_then_sends_nothing():
    """Finding the server (its name, the connection) cannot be broken off. A try that is still at that when its
    limit comes is left to it: no second one is started meanwhile, and when it gets there it sends nothing."""
    gate, real = threading.Event(), socket.create_connection

    def slow(*where, **more):
        gate.wait(10)
        return real(*where, **more)

    with Catcher() as phone:
        socket.create_connection = slow
        try:
            assert send(phone.address, CANARY, "away on", limit=0.3) == ("timeout", False)
            assert send(phone.address, CANARY, "away on", limit=0.3) == ("the try before still hangs", False)
        finally:
            socket.create_connection = real
            gate.set()
        landed()
        time.sleep(0.3)
        assert not any(phone.got), phone.got  # it got there after its limit, and not a byte of the message went
        assert send(phone.address, CANARY, "away on") == TOOK
        assert phone.caught(2) == [b"", exact("away on", phone.port)]  # the way is free again


def test_a_redirect_is_a_failure_and_the_topic_never_travels_on():
    """Whatever a server answers, the request is not sent to a second place: a 3xx is a try that failed."""
    with Catcher() as elsewhere:
        for status in (301, 302, 303, 307, 308):
            for target in (f"{elsewhere.address}/{CANARY}", f"{elsewhere.address}/", f"/{CANARY}/again"):
                with Catcher(answer(status, "Moved", Location=target)) as phone, nothing_said():
                    assert send(phone.address, CANARY, "away on") == (f"http {status}", False), (status, target)
                assert len(phone.got) == 1, (status, target)  # and not asked a second time either
        assert elsewhere.got == []


def test_no_proxy_of_the_environment_is_asked():
    """A proxy the environment names would see the address with the topic in it. None is used."""
    names = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY")
    before = {name: os.environ.get(name) for name in names}
    with Catcher() as proxy, Catcher() as phone:
        try:
            for name in names[:6]:
                os.environ[name] = proxy.address
            for name in names[6:]:
                os.environ.pop(name, None)
            assert send(phone.address, CANARY, "away on") == TOOK
        finally:
            for name, value in before.items():
                os.environ.pop(name, None)
                if value is not None:
                    os.environ[name] = value
        assert len(phone.got) == 1 and proxy.got == []


def test_what_is_no_topic_or_no_server_is_not_sent():
    """send checks for itself where it sends and what it puts into the address, whoever calls it."""
    with Catcher() as phone, nothing_said():
        for no_topic in (
            "",
            "short",
            "a" * 31,
            "a" * 65,
            "a" * 40 + "/x",
            "a" * 40 + "?x=1",
            "../" * 12,
            "a" * 40 + "\r\nX: y",
            "a" * 40,
            "Z9_-" * 16,
            None,
        ):
            assert send(phone.address, no_topic, "away on") == ("no topic", False), no_topic
        for no_server in (
            f"http://localhost:{phone.port}",
            f"{phone.address}/x",
            "http://ntfy.invalid",
            "ntfy.invalid",
            "http://127.0.0.1:70001",
            "http://127.0.0.1:0",
            "",
        ):
            assert send(no_server, CANARY, "away on") == ("no server", False), no_server
    assert phone.got == []


def test_a_text_that_is_not_plain_ascii_is_a_word_in_the_log_and_never_a_traceback():
    """The texts go out as ASCII bytes. One that is not plain ASCII (a dash or quote a writer put in, a line
    break in a title) is not sent: send says so in a word, nothing is printed, no connection is made. And the
    start of the phone thread names the key of each such text once, so it is seen before any message is due."""
    real_texts = dict(alerts.TEXTS)
    alerts.TEXTS["quiet"] = {"title": "Ringtop", "body": "Ringtop is silent now – until tomorrow."}
    alerts.TEXTS["fan on"] = {"title": "Ringtop\r\nClick: x", "body": "A fan stands."}
    alerts.TEXTS["fan off"] = {"title": "Ringtop", "body": "Fans turn again.\x00"}
    try:
        with Catcher() as phone, nothing_said():
            for key in ("quiet", "fan on", "fan off"):
                assert send(phone.address, CANARY, key) == ("text not ascii", False), key
            assert send(phone.address, CANARY, "away off") == TOOK  # the others go as ever
        assert len(phone.got) == 1

        def wait_tick(seen, timeout=15.0):
            raise SystemExit  # the start is all this check wants of the thread

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
            notify.watch(
                types.SimpleNamespace(wait_tick=wait_tick), notify.Phone(None, phone.address, None, True, False)
            )
    finally:
        alerts.TEXTS.clear()
        alerts.TEXTS.update(real_texts)
    assert out.getvalue().splitlines() == [
        "ringtop: phone messages: the text of 'fan on' is not plain ASCII, and it is never sent",
        "ringtop: phone messages: the text of 'fan off' is not plain ASCII, and it is never sent",
        "ringtop: phone messages: the text of 'quiet' is not plain ASCII, and it is never sent",
        "ringtop: phone messages: dry run, nothing is sent",
    ], out.getvalue()
    landed()


def test_a_placeholder_never_leaves_this_machine():
    """While the final wording is not written, a text with the mark goes to a catcher on 127.0.0.1 and nowhere
    else: no topic of a real phone ever gets a placeholder. The check sets a placeholder itself, so it holds
    after the final wording is in the table as well."""
    asked = []
    real_post, real_texts = notify.post, dict(alerts.TEXTS)
    notify.post = lambda *call: asked.append(call) or TOOK  # nothing leaves from here, whatever send decides
    alerts.TEXTS["fan on"] = {"title": "Ringtop", "body": f"{PLACEHOLDER}: not written yet."}
    alerts.TEXTS["fan off"] = {"title": f"Ringtop {PLACEHOLDER}", "body": "A fan turns again."}
    alerts.TEXTS["quiet"] = {"title": "Ringtop", "body": "A text that is written."}
    try:
        with nothing_said():
            for key in ("fan on", "fan off"):
                assert send("https://phone.invalid", CANARY, key) == ("text not written", False), key
                assert send("https://127.0.0.1:18700", CANARY, key) == ("text not written", False), key
            assert asked == []
            assert send("https://phone.invalid", CANARY, "quiet") == TOOK and len(asked) == 1  # a written one goes
            assert send("http://127.0.0.1:18700", CANARY, "fan on") == TOOK and len(asked) == 2  # the catcher gets all
    finally:
        notify.post = real_post
        alerts.TEXTS.clear()
        alerts.TEXTS.update(real_texts)
    landed()
