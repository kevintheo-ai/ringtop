"""The web server: who may read the page, what is served from disk, how much one request may ask."""

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import ringtop
from ringtop_parts.connect.server import HISTORY_KEYS, MODEL, PAGE, PAGE_PARTS, WALL, WALL_PARTS, Handler, host_allowed
from ringtop_parts.core.prom import exposition
from tests.fixtures import demo_round, hub_for, page_rules, serving


def test_only_own_addresses_may_read_the_page():
    names = {"localhost", "spark-1", "spark-1.local"}
    good = (
        "127.0.0.1:8377",
        "localhost:8377",
        "[::1]:8377",
        "192.168.1.5:8377",
        "spark-1.local:8377",
        "SPARK-1:8377",
        "10.0.0.2",
    )
    for host in good:
        assert host_allowed(host, names), host
    for host in ("evil.example:8377", "127.0.0.1.evil.example:8377", "1.2.3.4.evil:80", "", None):
        assert not host_allowed(host, names), host


def test_only_the_one_model_file_is_served_from_disk():
    source = Path(sys.modules[Handler.__module__].__file__).read_text()  # the file the web server stands in
    assert source.count('"/assets/') == 1 and 'path == "/assets/spark.glb"' in source and MODEL.name == "spark.glb"


def test_the_time_machine_may_ask_for_every_trace_of_a_big_cluster():
    """One moment of a 16-node ring is 12 engine values, 19 per node and two per link direction, in one request."""
    assert HISTORY_KEYS >= 12 + 16 * 19 + 32 * 2
    kept = page_rules("return KEPT_ENGINE.length * 1000 + KEPT_NODE.length;") if shutil.which("node") else 12019
    assert kept == 12019, kept  # the page asks for as many as this check counts with
    # that the server cuts a longer list at HISTORY_KEYS is asked over HTTP in the check of every address, below


def test_the_page_and_the_model_lie_where_the_server_looks_for_them():
    home = Path(ringtop.__file__).resolve().parent
    assert home / "page" / "index.html" == PAGE and PAGE.is_file()
    assert home / "assets" / "spark.glb" == MODEL  # may be missing from a checkout: without it the page draws a box


def test_every_address_of_the_server_answers_as_it_always_has():
    """One real request to every address, against a hub the demo has fed: status, content type, and the headers that
    keep a browser from caching an answer and from guessing its type."""
    hub = demo_round(8, at=40.0, start=time.time() - 16)  # the engine writes, and its newest sample is of this moment
    hub.beat()  # one tick, so the stream has something to say at once
    module = sys.modules[Handler.__module__]
    model = module.MODEL
    try:
        with tempfile.TemporaryDirectory() as folder, serving(hub) as ask:

            def get(path, **more):
                status, headers, body = ask(path, **more)
                assert headers.get("cache-control") == "no-store", (path, headers)
                if headers["content-type"] != "text/event-stream":
                    assert headers.get("x-content-type-options") == "nosniff", (path, headers)
                    assert headers.get("content-length") == str(len(body)), (path, headers)
                return status, headers["content-type"], body

            def told(path, **more):
                status, kind, body = get(path, **more)
                assert (status, kind) == (200, "application/json"), (path, status, kind)
                return json.loads(body)

            assert get("/") == (200, "text/html; charset=utf-8", PAGE.read_bytes())
            assert get("/?x=1")[0] == 200 and get("/", host="localhost:1")[0] == 200
            module.MODEL = Path(folder) / "spark.glb"
            module.MODEL.write_bytes(b"glTF made up")
            assert get("/assets/spark.glb") == (200, "model/gltf-binary", b"glTF made up")
            module.MODEL = Path(folder) / "none.glb"
            assert get("/assets/spark.glb") == (404, "text/plain", b"Not found\n")
            state = told("/api/state")
            assert set(state) == {
                "t",
                "cluster",
                "identity",
                "engine",
                "nodes",
                "edges",
                "run",
                "why",
                "events",
                "history",
            }, set(state)
            assert len(state["nodes"]) == 4 and state["history"]["engine.tok_s"][0], state["engine"]
            shallow, deep = told("/api/nerd"), told("/api/nerd?deep=1")
            assert {"t", "seq", "log", "nodes", "speculation", "latency", "scheduler"} == set(shallow), set(shallow)
            assert set(deep) - set(shallow) == {"env", "connections", "cables", "store", "engine"}, set(deep)
            assert set(told("/api/nerd?since=abc")) == set(shallow)  # a broken number counts from the start
            assert told(f"/api/nerd?since={shallow['seq']}")["log"] == [] and shallow["log"]
            now = time.time()
            past = told(f"/api/history?keys=engine.tok_s,dgx0.w&from={now - 60}&to={now + 1}&points=20")
            assert past["tier"] == "memory" and set(past["series"]) == {"engine.tok_s", "dgx0.w"}, past
            assert past["t"] and len(past["t"]) == len(past["series"]["dgx0.w"]) and "events" not in past, past
            assert isinstance(told(f"/api/history?keys=dgx0.w&from={now - 60}&events=1")["events"], list)
            crowd = ",".join(f"k{i}" for i in range(HISTORY_KEYS + 50))
            assert len(told("/api/history?keys=" + crowd)["series"]) == HISTORY_KEYS
            for broken in ("from=abc", "to=x", "points=many"):
                assert get("/api/history?keys=dgx0.w&" + broken) == (400, "text/plain", b"Bad range\n"), broken
            assert told("/api/replies") == []
            status, kind, first = get("/api/events", lines=2)
            assert (status, kind) == (200, "text/event-stream") and first.startswith(b'data: {"t":'), first[:60]
            assert first.endswith(b"}\n\n") and json.loads(first[6:])["engine"] == state["engine"]
            for path in ("/nope", "/api", "/api/", "/index.html", "/assets/other.glb", "/assets/", "/./"):
                assert get(path) == (404, "text/plain", b"Not found\n"), path
            for path in ("/", "/api/state", "/assets/spark.glb", "/api/events"):
                assert get(path, host="evil.example") == (403, "text/plain", b"Host not allowed\n"), path
    finally:
        module.MODEL = model


SCRIPT, SHEET = "text/javascript; charset=utf-8", "text/css; charset=utf-8"
PAGE_NAMES = [
    "style.css",
    "base.js",
    "rules.js",
    "measure.js",
    "neutral.js",
    "faces.js",
    "history.js",
    "scene-programs.js",
    "scene-stage.js",
    "scene-labels.js",
    "scene-lens.js",
    "scene-world.js",
    "scene-draw.js",
    "scene.js",
    "run.js",
    "runcard.js",
    "vitals.js",
    "dock.js",
    "hover.js",
    "parts.js",
    "plot.js",
    "board.js",
    "spark.js",
    "cooling.js",
    "runs.js",
    "views.js",
    "nerd-live.js",
    "nerd-deep.js",
    "nerd.js",
    "tour.js",
    "time.js",
    "main.js",
]


def test_the_parts_of_the_page_are_a_fixed_table():
    """What the page may load beside itself: the names above, each one file in the folder of the page, each with the
    type a browser insists on once it is told not to guess."""
    assert sorted(PAGE_PARTS) == sorted("/page/" + name for name in PAGE_NAMES)
    for address, (file, kind) in PAGE_PARTS.items():
        assert file == PAGE.parent / address[len("/page/") :], address
        assert kind == (SHEET if address.endswith(".css") else SCRIPT), address


def test_a_part_of_the_page_is_sent_under_its_exact_address_and_under_no_other():
    """The address is looked up in the table as it came, and nothing of a request ever becomes a path on disk: no
    file beside the parts, no way out of the folder, no other spelling of a name."""
    module = sys.modules[Handler.__module__]
    table = module.PAGE_PARTS
    try:
        with tempfile.TemporaryDirectory() as folder, serving(hub_for()) as ask:
            folder = Path(folder)
            (folder / "base.js").write_text("'use strict';\n")
            (folder / "style.css").write_text("body{}\n")
            (folder / "secret.txt").write_text("not for the page\n")
            module.PAGE_PARTS = {
                "/page/base.js": (folder / "base.js", SCRIPT),
                "/page/style.css": (folder / "style.css", SHEET),
                "/page/later.js": (folder / "later.js", SCRIPT),  # in the table, not yet on disk
            }
            for address, kind, body in (
                ("/page/base.js", SCRIPT, b"'use strict';\n"),
                ("/page/style.css", SHEET, b"body{}\n"),
            ):
                status, headers, sent = ask(address)
                assert (status, headers["content-type"], sent) == (200, kind, body), (address, status, headers)
                assert headers.get("cache-control") == "no-store" and headers.get("x-content-type-options") == "nosniff"
            tricks = (
                "/page/later.js",
                "/page/secret.txt",
                "/page/index.html",
                "/page/",
                "/page",
                "/pagebase.js",
                "/page/base.js/",
                "/page/base.js?x=1",
                "/page/BASE.JS",
                "/page//base.js",
                "/page/./base.js",
                "/page/../page/base.js",
                "/page/../ringtop.py",
                "/page/%2e%2e/ringtop.py",
                "/page/..%2fringtop.py",
                "/page/base.js%00",
                "/page/secret.txt/../base.js",
            )
            for address in tricks:
                status, headers, sent = ask(address)
                assert (status, headers["content-type"], sent) == (404, "text/plain", b"Not found\n"), (address, status)
            assert ask("/page/base.js", host="evil.example")[0] == 403  # the host is asked first, as everywhere
    finally:
        module.PAGE_PARTS = table


def test_the_page_names_only_parts_of_the_table_and_no_file_lies_beside_them():
    """Every file the page loads is in the table and on disk. Every file in the folder of the page is in the table,
    or it is the calm page for a wall or in the table of that one: what lies there is meant to be sent."""
    named = [u for u in re.findall(r'(?:src|href)="([^"]+)"', PAGE.read_text()) if not u.startswith(("data:", "#"))]
    for name in named:
        assert "/" + name in PAGE_PARTS and PAGE_PARTS["/" + name][0].is_file(), name
    beside = {"/page/" + f.name for f in PAGE.parent.iterdir() if f not in (PAGE, WALL) and not f.name.startswith(".")}
    sent = set(PAGE_PARTS) | set(WALL_PARTS)
    assert PAGE.parent.name == "page" and WALL.parent == PAGE.parent and beside <= sent, beside - sent


def test_the_history_gives_a_band_only_to_who_asks_for_one():
    """`band=1` adds the lowest value of every column and how many readings stand behind it. Every answer says how
    many seconds a column spans; without `band` it carries no more than before (the time machine asks 400 keys)."""
    hub = demo_round(8, at=40.0, start=time.time() - 16)
    with serving(hub) as ask:
        now = time.time()
        span = f"/api/history?keys=dgx0.w,nothing&from={now - 60}&to={now + 1}&points=20"
        plain, band = (json.loads(ask(span + more)[2]) for more in ("", "&band=1"))
        assert set(plain) == {"t", "tier", "width", "series", "peak"} and plain["width"] == 3.05, plain  # 61 s in 20
        assert set(band) == set(plain) | {"low", "n"} and band["t"] == plain["t"] and band["t"], band
        w = {key: band[key]["dgx0.w"] for key in ("series", "peak", "low", "n")}
        assert all(len(column) == len(band["t"]) for column in w.values()), w
        assert all(lo <= mean <= hi and n >= 1 for mean, hi, lo, n in zip(*w.values())), w
        assert sum(w["n"]) == len(hub.history["dgx0.w"]) == 8, w  # every sample stands in one column
        assert band["low"]["nothing"] == [None] * len(band["t"]) and band["n"]["nothing"] == [0] * len(band["t"])
        for other in ("&band=0", "&band=yes", "&band="):
            assert "low" not in json.loads(ask(span + other)[2]), other


def test_a_range_of_the_history_that_is_no_finite_number_is_turned_away():
    """`nan` and `inf` read as numbers and are no moments. A range with one of them got an answer that is no JSON
    (NaN, Infinity) or, from a history on disk, an exception: it is a 400 like every other range that is no number."""
    with serving(hub_for()) as ask:
        for broken in ("from=nan", "to=NaN", "from=inf", "to=inf", "to=-inf", "from=-Infinity", "to=1e999"):
            for more in ("", "&band=1"):
                status, headers, body = ask("/api/history?keys=dgx0.w&" + broken + more)
                said = (status, headers["content-type"], body)
                assert said == (400, "text/plain", b"Bad range\n"), (broken, more, status, body[:80])
        status, _, body = ask("/api/history?keys=dgx0.w&from=1&to=5")  # a range of finite numbers is still answered
        assert status == 200 and json.loads(body)["t"] == [], (status, body[:80])


def test_a_range_of_the_history_wider_than_a_number_can_say_is_turned_away():
    """Two ends that are finite numbers can lie further apart than a number can say: from -1e308 to 1e308 the span is
    infinite. The answer then came with status 200 and a column width of Infinity, which is no JSON. Such a range is
    a 400 like one whose end is no moment."""
    with serving(hub_for()) as ask:
        for more in ("", "&band=1"):
            status, headers, body = ask("/api/history?keys=dgx0.w&from=-1e308&to=1e308" + more)
            said = (status, headers["content-type"], body)
            assert said == (400, "text/plain", b"Bad range\n"), (more, status, body[:80])


def test_a_trace_named_twice_takes_no_place_of_the_traces_one_request_may_ask_for():
    """One request for the past may name HISTORY_KEYS traces, and a trace named twice is answered once. The list was
    cut to that many before the doubles were taken out: who named some trace twice got fewer traces than asked for
    and allowed. A trace counts once, in the order asked, and what is over the limit is still cut."""
    with serving(hub_for()) as ask:
        traces = [f"k{i}" for i in range(HISTORY_KEYS + 5)]
        status, _, body = ask("/api/history?keys=" + ",".join(["k0"] * 50 + traces))  # one trace fifty times in front
        series = json.loads(body)["series"]
        assert status == 200 and len(series) == HISTORY_KEYS, len(series)  # not fifty fewer
        assert list(series) == traces[:HISTORY_KEYS], list(series)[:3]


def test_the_newest_moment_is_told_as_prometheus_text():
    """/metrics gives the moment the ticker built last as Prometheus text, to whoever may read the page and with the
    headers of every other answer. It is read off that moment: asking builds no view of its own, which would note
    events and look for silent Sparks once more with every scrape."""
    hub = demo_round(8, at=40.0, start=time.time() - 16)  # the engine writes, and its newest sample is of this moment
    hub.beat()
    hub.view = None  # whoever asked the hub for a view from here on would fail
    with serving(hub) as ask:
        status, headers, body = ask("/metrics")
        assert (status, headers["content-type"]) == (200, "text/plain; version=0.0.4; charset=utf-8"), (status, headers)
        assert headers.get("cache-control") == "no-store" and headers.get("x-content-type-options") == "nosniff"
        assert headers.get("content-length") == str(len(body)), headers
        text = body.decode()
        assert text == exposition(json.loads(hub.payload)) and text.endswith("\n"), text[:200]
        assert 'ringtop_engine_state{state="writing"} 1\n' in text and 'ringtop_node_live{node="dgx3"} 1\n' in text
        assert ask("/metrics?x=1")[2] == body
        for path in ("/metrics/", "/metric", "/api/metrics", "/metrics.txt"):
            assert ask(path)[0] == 404, path
        status, headers, said = ask("/metrics", host="evil.example")
        assert (status, headers["content-type"], said) == (403, "text/plain", b"Host not allowed\n"), (status, said)


def test_a_scrape_without_a_moment_of_now_fails():
    """Before the ticker built its first moment there is nothing to tell. And a moment the ticker could not renew (it
    keeps the one before while no view can be built) is not of now once it is older than the silence that takes a
    Spark off the page. Either is a 503 with a short word: a scrape that fails is the truth then, and the figures of
    a while ago told as today's are not."""
    hub = demo_round(8, at=40.0, start=time.time() - 16)
    with serving(hub) as ask:
        status, headers, body = ask("/metrics")
        assert (status, headers["content-type"], body) == (503, "text/plain", b"No moment of now\n"), (status, body)
        hub.beat()
        assert ask("/metrics")[0] == 200
        moment = json.loads(hub.payload)
        for age, status in ((hub.silence - 5, 200), (hub.silence + 5, 503)):
            with hub.tick_changed:
                hub.payload = json.dumps({**moment, "t": time.time() - age}).encode()
            assert ask("/metrics")[0] == status, age


def test_a_run_name_that_is_no_text_utf8_can_hold_does_not_end_the_list():
    """A run source names its run in JSON, and JSON can spell half a pair of surrogates, which no UTF-8 holds. The
    list is sent all the same, with a question mark in its place: one odd name must not fail every scrape."""
    hub = hub_for()
    with hub.lock:
        hub.external_run = {"name": "job \ud800 7"}
    hub.beat()
    with serving(hub) as ask:
        status, _, body = ask("/metrics")
        assert status == 200 and b'ringtop_run_info{name="job ? 7",source="command"} 1\n' in body, (status, body[-200:])


class Gone:
    """The line to a page that has left: whatever is written to it is a broken pipe."""

    def write(self, body):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        pass


def left_before(path):
    """A handler for one request whose page is gone already. No socket: only what one answer touches."""
    handler = Handler.__new__(Handler)
    handler.wfile, handler.request_version, handler.close_connection = Gone(), "HTTP/1.1", False
    handler.requestline, handler.client_address, handler.command = f"GET {path} HTTP/1.1", ("127.0.0.1", 1), "GET"
    return handler


def test_a_client_that_left_before_its_answer_is_no_error():
    """A page that closes while an answer is on its way is no failure of the server: nothing is thrown (the standard
    library would print a traceback into the log for it), and the connection is done."""
    handler = left_before("/api/state")
    handler.send_body(200, b"{}", "application/json")
    assert handler.close_connection is True


class Hung:
    """The line from a visitor who hung up: reading the request from it is a connection that was reset."""

    def readline(self, limit=-1):
        raise ConnectionResetError(54, "Connection reset by peer")


class Broken:
    """A line that fails in a way that is no end of a connection."""

    def readline(self, limit=-1):
        raise ValueError("no line to read from")


def test_a_visitor_that_hung_up_before_its_request_was_read_is_no_error():
    """A visitor that hangs up before its request is read (or between two requests on one connection) is no failure
    of the server: the reset left the handler, and the standard library printed a traceback into the log of the
    service for every one of them. Nothing is thrown, and the connection is done. Any other error still is one."""
    handler = Handler.__new__(Handler)
    handler.rfile, handler.client_address = Hung(), ("127.0.0.1", 1)
    handler.handle()  # threw ConnectionResetError
    assert handler.close_connection is True
    handler.rfile = Broken()
    try:
        handler.handle()
    except ValueError:
        return
    raise AssertionError("an error that is no end of a connection was passed over")


def test_a_client_that_left_before_the_stream_began_is_no_error():
    """A page that asks for the stream of moments and is gone before its head went out is no failure either: the
    stream ends as it does for a page that leaves later, and nothing is thrown."""
    handler = left_before("/api/events")
    handler.hub = hub_for()
    handler.events()
    assert handler.close_connection is True
