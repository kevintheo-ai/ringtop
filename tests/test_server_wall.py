"""A wall listener: what it sends is the calm page, its parts and its stream, and nothing else of ringtop."""

import ast
import contextlib
import http.client
import http.server
import inspect
import io
import json
import socket
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

from ringtop_parts.connect.server import (
    API,
    PAGE,
    PAGE_PARTS,
    WALL,
    WALL_API,
    WALL_OPEN,
    WALL_PARTS,
    Handler,
    Listener,
)
from ringtop_parts.core.wall import wall_moment
from tests.fixtures import demo_round, serving

# Everything a wall listener answers with a 200, written out here on purpose: an address added to its tables shows
# as a failure of this check, and is then a decision.
SENT = [
    "/",
    "/wall",
    "/page/wall.css",
    "/page/base.js",
    "/page/rules.js",
    "/page/neutral.js",
    "/page/faces.js",
    "/page/wall.js",
    "/api/wall",
]
SECRET = "KEEP-THIS-OFF-THE-WALL"


def fed():
    """A hub the demo has fed while the ring engine writes, with one tick built so a stream has a moment at once."""
    hub = demo_round(8, at=40.0, start=time.time() - 16)
    hub.beat()
    return hub


def status(ask, path, **more):
    """The status of one request. Of a stream only the first line is read: it never ends."""
    return ask(path, lines=1 if path.startswith(("/api/events", "/api/wall")) else 0, **more)[0]


def test_a_wall_listener_sends_the_calm_page_its_parts_and_its_stream_and_nothing_else():
    """Every address ringtop knows is asked of a wall listener: each page, every part of both pages, the model
    (which lies on disk for this check) and every address of the API. It answers the nine addresses of the list
    and no other: the main page, its parts, the model, the whole moment, the deep view, the history, the replies,
    the runs and the Prometheus text are not found there."""
    module = sys.modules[Handler.__module__]
    model = module.MODEL
    known = ["/", "/wall", "/assets/spark.glb", *PAGE_PARTS, *WALL_PARTS, *API]
    assert len(set(known)) == 45 and set(SENT) <= set(known), len(set(known))
    try:
        with tempfile.TemporaryDirectory() as folder, serving(fed(), wall=True) as ask:
            module.MODEL = Path(folder) / "spark.glb"
            module.MODEL.write_bytes(b"glTF made up")
            answered = sorted(path for path in set(known) if status(ask, path) == 200)
            assert answered == sorted(SENT), sorted(set(answered) ^ set(SENT))
            hidden = ("/api/state", "/api/events", "/api/nerd?deep=1", "/api/history?keys=dgx0.w", "/api/replies")
            for path in (
                *hidden,
                "/api/runs?limit=5",
                "/metrics",
                "/assets/spark.glb",
                "/page/main.js",
                "/page/style.css",
            ):
                got, headers, body = ask(path)
                assert (got, headers["content-type"], body) == (404, "text/plain", b"Not found\n"), path
            for path in (
                "/index.html",
                "/page/wall.html",
                "/page/index.html",
                "/wall/",
                "/api/wall/",
                "/api",
                "/page/wall.js?x=1",
            ):
                assert status(ask, path) == 404, path
            for path in (
                "/",
                "/wall",
                "/api/wall",
                "/api/state",
            ):  # a Host this machine does not go by: turned away first
                assert ask(path, host="evil.example")[0] == 403, path
    finally:
        module.MODEL = model


def test_what_a_wall_listener_sends_is_the_calm_page_as_it_lies_on_disk():
    """The calm page at both of its addresses, and every part with the type a browser insists on, never cached."""
    with serving(fed(), wall=True) as ask:
        for path in ("/", "/wall", "/wall?names=neutral", "/?names=neutral"):
            got, headers, body = ask(path)
            assert (got, headers["content-type"], body) == (200, "text/html; charset=utf-8", WALL.read_bytes()), path
        for path, (file, kind) in WALL_PARTS.items():
            got, headers, body = ask(path)
            assert (got, headers["content-type"], body) == (200, kind, file.read_bytes()), path
            assert headers["cache-control"] == "no-store" and headers["x-content-type-options"] == "nosniff", path
    assert {"/api/wall": Handler.wall} == WALL_API and API["/api/wall"] is Handler.wall


def test_a_page_that_is_not_on_disk_is_not_found_at_either_listener_and_nothing_is_thrown():
    """The two pages are files beside ringtop.py, read anew for every request. A part and the model were asked for
    on disk before they were read; a page was not. Where its file is not there (a checkout of a stand without the
    calm page, until the restart), reading it threw before an answer was sent: the visitor got none, and the log a
    traceback for every request. A page that is not on disk is not found, like a part or the model; nothing is
    written to stderr, the place of the connection comes back, and with the file back the page is sent again."""
    module = sys.modules[Handler.__module__]
    page, calm, hub, said = module.PAGE, module.WALL, fed(), io.StringIO()
    try:
        with contextlib.redirect_stderr(said), serving(hub) as ask, serving(hub, wall=True) as ask_wall:
            module.PAGE = module.WALL = calm.with_name("no-page.html")  # beside the pages, and not there
            for one, path in ((ask_wall, "/"), (ask_wall, "/wall"), (ask_wall, "/?names=neutral"), (ask, "/")):
                got, headers, body = one(path)
                assert (got, headers["content-type"], body) == (404, "text/plain", b"Not found\n"), path
            assert ask("/wall")[::2] == (404, b"Not found\n")
            assert status(ask_wall, "/page/wall.js") == 200 and status(ask, "/api/state") == 200  # the rest stands
            module.PAGE, module.WALL = page, calm
            assert ask_wall("/")[2] == calm.read_bytes() and ask("/")[2] == page.read_bytes()
            assert until(lambda: ask_wall.server.open == 0), ask_wall.server.open
    finally:
        module.PAGE, module.WALL = page, calm
    assert said.getvalue() == "", said.getvalue()[-400:]


def test_the_stream_for_a_wall_never_carries_the_whole_moment():
    """The word a wall must not get is put into the hub where the whole moment takes it from: the container, the
    programs and the threads of a Spark, why one is away, and an event. The stream of the main page carries it; the
    stream for a wall, read from a wall listener at the same tick, does not, and is what the list makes of that
    very moment."""
    hub = fed()
    with hub.lock:
        for node in hub.nodes.values():
            node.update(box={"name": SECRET, "running": True}, top=[{"name": SECRET}], threads=[SECRET], reason=SECRET)
        hub.events.append({"t": time.time(), "node": None, "kind": "kernel", "text": SECRET, "level": "bad"})
    hub.beat()
    with serving(hub) as ask, serving(hub, wall=True) as ask_wall:
        got, headers, whole = ask("/api/events", lines=2)
        assert got == 200 and whole.count(SECRET.encode()) > 12, whole[:80]
        got, headers, sent = ask_wall("/api/wall", lines=2)
        assert (got, headers["content-type"], headers["cache-control"]) == (200, "text/event-stream", "no-store")
        assert sent.startswith(b'data: {"t":') and sent.endswith(b"}\n\n") and SECRET.encode() not in sent, sent[:200]
        assert b"reason" not in sent and b"box" not in sent and b"events" not in sent and b"edges" not in sent
        moment = json.loads(whole[6:])
        assert json.loads(sent[6:]) == wall_moment(moment) and len(sent) * 5 < len(whole), (len(sent), len(whole))
        assert set(json.loads(sent[6:])) == {"t", "cluster", "identity", "engine", "nodes", "run", "why"}


def test_the_main_listener_sends_the_calm_page_beside_everything_it_always_sent():
    """On the address of the main page the calm page is at /wall, with its parts and its stream: the Mac shows it
    too. And the main page stands where it stood."""
    with serving(fed()) as ask:
        assert ask("/")[2] == PAGE.read_bytes() and ask("/wall")[2] == WALL.read_bytes()
        for path in ("/page/wall.css", "/page/wall.js", "/page/main.js", "/page/style.css", "/api/state", "/metrics"):
            assert status(ask, path) == 200, path
        got, headers, sent = ask("/api/wall", lines=2)
        assert got == 200 and headers["content-type"] == "text/event-stream", headers
        assert "box" not in json.loads(sent[6:])["nodes"][0] and "edges" not in json.loads(sent[6:])


def test_two_listeners_stand_side_by_side_each_with_its_own_family_and_kind():
    """ringtop listens on the loopback for the main page and on another address for the wall, at once. The family
    of an address was set for every server of the process; now each listener has its own, and whether it is a wall
    listener is its own too. Asked over IPv6, the wall listener sends the calm page."""
    handler = type("Served", (Handler,), {"hub": fed(), "allowed_hosts": {"localhost"}})
    main = Listener(("127.0.0.1", 0), handler)
    try:
        wall = Listener(("::1", 0), handler, wall=True)
    except OSError:  # a machine without IPv6: the family of the first one still is its own
        main.server_close()
        return
    threading.Thread(target=wall.serve_forever, daemon=True).start()
    link = http.client.HTTPConnection("::1", wall.server_address[1], timeout=20)
    try:
        families = (main.address_family, main.wall, wall.address_family, wall.wall)
        assert families == (socket.AF_INET, False, socket.AF_INET6, True), families
        assert http.server.ThreadingHTTPServer.address_family == socket.AF_INET  # nothing set for the whole process
        assert main.daemon_threads and wall.daemon_threads
        link.request("GET", "/")
        answer = link.getresponse()
        assert answer.status == 200 and answer.read() == WALL.read_bytes()
        link.request("GET", "/api/state")
        assert link.getresponse().status == 404
    finally:
        link.close()
        wall.shutdown()
        main.server_close()
        wall.server_close()


def closed(sock, within=3.0):
    """Whether the other end has closed this connection: a read ends at once with nothing, or with a reset. Waits
    at most `within` seconds for that."""
    sock.settimeout(within)
    try:
        return sock.recv(1) == b""
    except socket.timeout:
        return False
    except ConnectionError:
        return True


def until(holds, seconds=5.0):
    """Waits until `holds()` is true, at most so many seconds; gives back whether it was."""
    end = time.time() + seconds
    while not holds() and time.time() < end:
        time.sleep(0.01)
    return holds()


def test_a_wall_listener_serves_a_fixed_number_of_connections_and_closes_every_one_beyond_at_once():
    """A connection costs a thread and a file number of the one process that also serves the main page; under a
    service the numbers end at 256, and some 250 connections that say nothing took the main page down with the
    wall. A wall listener serves 32 at once. One beyond that is closed at once and gets no thread; the 32 stay,
    the main page answers all the while, and a place that is given back is taken by the next visitor."""
    hub, held = fed(), []
    with serving(hub) as ask, serving(hub, wall=True) as ask_wall:
        wall = ask_wall.server
        try:
            for count in range(1, WALL_OPEN + 1):
                held.append(socket.create_connection(ask_wall.address[:2], timeout=5))
                assert until(lambda count=count: wall.open == count), (count, wall.open)
            assert WALL_OPEN == 32 and wall.open == 32
            threads = threading.active_count()
            for _ in range(8):
                beyond = socket.create_connection(ask_wall.address[:2], timeout=5)
                held.append(beyond)
                assert closed(beyond, 2.0), "a connection beyond the limit was kept"
            assert wall.open == 32 and threading.active_count() <= threads, (wall.open, threading.active_count())
            assert ask("/")[0] == 200 and ask("/api/state")[0] == 200 and ask.server.open == 0
            assert not closed(held[0], 0.3)  # the ones within the limit stay
            held.pop(0).close()
            assert until(lambda: wall.open == 31), wall.open
            assert ask_wall("/")[:1] == (200,)
        finally:
            for sock in held:
                sock.close()
        assert until(lambda: wall.open == 0), wall.open


def test_a_connection_that_says_nothing_to_a_wall_listener_falls_away_and_a_running_stream_does_not():
    """Nothing ended a connection that never sent its request: it held its place for as long as the device held
    it. A wall listener waits 10 s for a request, for the whole one and for the next on the same connection, then
    closes. The stream for a wall is no such wait: it goes on for as long as it is read. And the main listener is
    as it was, with no deadline. (The check sets the deadline to half a second.)"""
    module = sys.modules[Handler.__module__]
    patience, hub, socks = module.WALL_PATIENCE, fed(), []
    assert patience == 10.0
    module.WALL_PATIENCE = 0.5
    try:
        with serving(hub) as ask, serving(hub, wall=True) as ask_wall:
            quiet, half, stream = (socket.create_connection(ask_wall.address[:2], timeout=5) for _ in range(3))
            at_main = socket.create_connection(ask.address[:2], timeout=5)
            socks += [quiet, half, stream, at_main]
            began = time.time()
            half.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n")  # a request that never ends
            stream.sendall(b"GET /api/wall HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            first = b""
            while not first.endswith(b"}\n\n"):
                more = stream.recv(65536)
                assert more, f"the stream ended before its first moment: {first[:80]!r}"  # an end reads as nothing
                first += more
            assert first.startswith(b"HTTP/1.1 200") and b'data: {"t":' in first, first[:80]
            assert closed(quiet) and closed(half), "a silent connection was kept"
            assert 0.4 < time.time() - began < 3.0, time.time() - began
            time.sleep(max(0.0, 1.5 - (time.time() - began)))  # three deadlines after the stream began
            hub.beat()
            stream.settimeout(5)
            assert stream.recv(65536).startswith(b'data: {"t":')  # the stream still carries the next moment
            assert not closed(at_main, 0.3)  # the main listener waits as long as it always did
            assert until(lambda: ask_wall.server.open == 1), ask_wall.server.open  # the stream alone
    finally:
        module.WALL_PATIENCE = patience
        for sock in socks:
            sock.close()


def test_a_connection_that_falls_silent_after_a_whole_request_falls_away_from_a_wall_listener_too():
    """The deadline of a wall listener holds for every wait on a connection: "for the whole one and for the next on
    the same connection". The check above held the first wait only, so a server that lost its deadline with the
    first answer passed. A visitor asks twice over one connection, as a page loads its parts, and is answered
    twice: the connection is kept between requests. Then it says nothing, and after the deadline the connection
    is closed without a word and its place is free. (The check sets the deadline to half a second.)"""
    module = sys.modules[Handler.__module__]
    patience = module.WALL_PATIENCE
    module.WALL_PATIENCE = 0.5
    try:
        with serving(fed(), wall=True) as ask_wall, socket.create_connection(ask_wall.address[:2], timeout=5) as sock:
            for path in ("/page/wall.css", "/"):
                began = time.time()
                sock.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
                answer = http.client.HTTPResponse(sock)
                answer.begin()
                assert answer.status == 200 and len(answer.read()) > 500, (path, answer.status)
            assert closed(sock), "a connection that fell silent after its answer was kept"
            assert 0.4 < time.time() - began < 3.0, time.time() - began  # kept for the deadline, and no longer
            assert until(lambda: ask_wall.server.open == 0), ask_wall.server.open
    finally:
        module.WALL_PATIENCE = patience


def body_of(method):
    """The statements of one method of the handler, without its sentence, as the parser sees them."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    return tree.body[0].body[1:]


def test_what_is_added_to_the_way_of_the_main_listener_does_not_reach_a_wall_listener():
    """That a wall listener sends nine addresses was held by a list of the addresses ringtop knows. An address
    somebody adds later as a branch of the answer, before the tables are looked at, was on no list: the independent
    check added `/debug` that way, and nothing noticed that a wall listener sent the whole moment for it. So the
    two kinds of listener part first, right after the Host is checked, and a wall listener answers from a function
    of its own that knows the calm page, its parts and its stream. A handler that grew a branch on the way of the
    main listener, and an address added to the API, are found there and not at a wall listener."""

    class Later(Handler):
        def main_answer(self):
            if self.path == "/debug":
                return self.state({})
            return super().main_answer()

    module = sys.modules[Handler.__module__]
    hub = fed()
    module.API["/api/later"] = Handler.state
    try:
        with serving(hub, base=Later) as ask, serving(hub, wall=True, base=Later) as ask_wall:
            for path in ("/debug", "/api/later"):
                got, headers, body = ask(path)
                assert (got, headers["content-type"]) == (200, "application/json") and b'"events"' in body, path
                assert ask_wall(path)[::2] == (404, b"Not found\n"), path
            assert ask_wall("/")[2] == WALL.read_bytes() and ask("/")[2] == PAGE.read_bytes()
    finally:
        del module.API["/api/later"]


def test_the_two_kinds_of_listener_part_before_anything_is_looked_up_and_the_wall_knows_only_its_own():
    """The shape that keeps the promise above, held as a shape: the answer to a GET checks the Host, then hands a
    wall listener to its own function, then the main listener to its own, and does nothing else: a branch put
    there would stand before the parting. And the function of the wall names the calm page, the table of its
    parts and the table of its API and nothing else of the server: no other page, table, model or method."""
    host, wall, main = body_of(Handler.do_GET)
    assert ast.unparse(host.test) == "not host_allowed(self.headers.get('Host'), self.allowed_hosts)", ast.unparse(host)
    assert ast.unparse(wall) == "if self.server.wall:\n    return self.wall_answer()", ast.unparse(wall)
    assert ast.unparse(main) == "return self.main_answer()", ast.unparse(main)
    names, own = set(), set()
    for statement in body_of(Handler.wall_answer):
        for node in ast.walk(statement):
            if isinstance(node, ast.Name):
                names.add(node.id)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                own.add(node.attr)
    assert names == {"self", "path", "part", "answer", "WALL", "WALL_PARTS", "WALL_API", "dict", "parse_qsl"}, names
    assert own == {"path", "send_body"}, own


def test_a_wall_listener_answers_no_method_but_get():
    """The handler has one method that answers, do_GET, and the parting stands in it. Every other method of HTTP
    is refused by the standard library with a 501 before anything of ringtop is asked: HEAD, POST with a body,
    PUT, DELETE, OPTIONS, PATCH, TRACE and CONNECT, at the calm page, at its stream and at the whole moment. A
    second do_ method would be a second way in, with no parting in it: that is why this check counts them."""
    assert [name for name in dir(Handler) if name.startswith("do_")] == ["do_GET"]
    with serving(fed(), wall=True) as ask_wall:
        host, port = ask_wall.address[:2]
        for method in ("HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "TRACE", "CONNECT"):
            for path in ("/", "/api/wall", "/api/state"):
                link = http.client.HTTPConnection(host, port, timeout=20)
                try:
                    link.request(method, path, body=b"deep=1" if method in ("POST", "PUT", "PATCH") else None)
                    answer = link.getresponse()
                    sent = answer.read()
                    assert answer.status == 501, (method, path, answer.status)
                    assert b'"t":' not in sent and b"dgx" not in sent and len(sent) < 600, (method, path, sent[:80])
                finally:
                    link.close()
        assert until(lambda: ask_wall.server.open == 0), ask_wall.server.open
