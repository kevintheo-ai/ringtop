"""The web server: the pages, their parts from fixed tables, the model, what the Hub knows as JSON or Prometheus text;
and what of all that a wall listener sends."""

from __future__ import annotations

import contextlib
import ipaddress
import json
import math
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qsl

from ringtop_parts.core.hub import Hub
from ringtop_parts.core.hub_runs import RUN_KEEP
from ringtop_parts.core.prom import CONTENT_TYPE, exposition
from ringtop_parts.core.wall import wall_moment

HOME = Path(__file__).resolve().parents[2]  # the folder of ringtop.py: the page and the model lie beside it
PAGE = HOME / "page" / "index.html"
WALL = HOME / "page" / "wall.html"  # the calm page for a wall and a phone
MODEL = HOME / "assets" / "spark.glb"


def parts(names: list[str]) -> dict:
    """A table of parts of a page, by the address a page asks for each under: its file, and the type a browser
    insists on once it is told not to guess."""
    kinds = {name: "css" if name.endswith(".css") else "javascript" for name in names}
    return {f"/page/{name}": (PAGE.parent / name, f"text/{kind}; charset=utf-8") for name, kind in kinds.items()}


# The parts of the page. A fixed table: an address is looked up in it as it came, and nothing of a request ever
# becomes a path on disk.
PAGE_PARTS = parts(
    [
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
)
# The parts of the calm page, in the order it loads them: its own sheet and script, and four scripts it shares with
# the main page. A table of its own, so what a wall may load is written down and not worked out.
WALL_PARTS = parts(["wall.css", "base.js", "rules.js", "neutral.js", "faces.js", "wall.js"])
# What a wall listener gives a visitor it does not know. It shares the threads and the file numbers of the one
# process with the main page: without a limit a device that only opens connections would take both down.
WALL_OPEN = 32  # connections a wall listener serves at once: a few devices, each with its stream and what a page loads
WALL_PATIENCE = 10.0  # seconds it waits for a request, and for a reader to take what it was sent
HISTORY_KEYS = 400  # traces in one request for a stretch of the past: the time machine asks for a whole cluster at once


def host_allowed(header: str | None, names: set[str]) -> bool:
    """Against DNS rebinding: the Host a browser sends must be an IP literal or one of this machine's own names."""
    m = re.fullmatch(r"(\[[0-9a-f:.]+\]|[^:\[\]]+)(?::\d+)?", (header or "").lower())
    if not m:
        return False
    host = m.group(1)
    return host.startswith("[") or host in names or bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host))


def sender_of(client_address):
    """Who a connection came from, as the address it is. A listener on IPv4 is told ('1.2.3.4', port), one on IPv6
    ('::1', port, flow, scope), and a socket that takes both families writes an IPv4 sender as '::ffff:1.2.3.4':
    that one is the IPv4 address inside it. None for what is no address: such a sender is nobody."""
    try:
        address = ipaddress.ip_address(client_address[0])
    except (ValueError, TypeError, IndexError):
        return None
    return getattr(address, "ipv4_mapped", None) or address


class Listener(ThreadingHTTPServer):
    """One address ringtop listens on. `wall`: a wall listener, which sends the calm page, its parts and its stream
    and nothing else of ringtop. The family of its address is its own (the standard library keeps one for every
    server of the process), so one listener on IPv4 can stand beside one on IPv6. `open`: how many connections a
    wall listener serves right now; it serves at most WALL_OPEN. The main listener counts none and has no limit.
    `senders`: the addresses that may read a wall listener; with none named, whoever reaches it may."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type, wall: bool = False, senders: tuple = ()):
        """Binds the address and listens. An address that cannot be bound throws, and nothing is left open."""
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        self.wall, self.open, self.counting = wall, 0, threading.Lock()
        self.senders = frozenset(ipaddress.ip_address(sender) for sender in senders)
        super().__init__(address, handler)

    def verify_request(self, request, client_address) -> bool:
        """Whether a connection is served at all. A wall listener that was told who may read it serves those
        senders and nobody else: the sender is compared as the address it is (sender_of), not as a text. Any other
        connection is closed where it is accepted: no thread, no answer, no place among WALL_OPEN. Nothing of the
        request has been read by then, so nothing it says plays a part, its Host included."""
        return not (self.wall and self.senders) or sender_of(client_address) in self.senders

    def process_request(self, request, client_address) -> None:
        """Hands one connection to a thread of its own. On a wall listener that already serves WALL_OPEN of them it
        is closed here instead, at once and without a thread: it costs nothing that the main page needs."""
        if self.wall:
            with self.counting:
                full = self.open >= WALL_OPEN
                self.open += not full
            if full:
                return self.shutdown_request(request)
        try:
            super().process_request(request, client_address)
        except BaseException:  # no thread could be started: its place is free again, and the failure is said as ever
            self.gone()
            raise

    def process_request_thread(self, request, client_address) -> None:
        """Serves one connection in its thread and gives its place back when it is over, however it ended."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.gone()

    def gone(self) -> None:
        """One connection of a wall listener is over: its place is free for the next."""
        if self.wall:
            with self.counting:
                self.open -= 1


class Handler(BaseHTTPRequestHandler):
    """Answers one request: a page, a part of it from a fixed table, the model file, or the API. Nothing a request
    says ever becomes a path on disk."""

    protocol_version = "HTTP/1.1"
    hub: Hub
    allowed_hosts: ClassVar[set[str]] = set()

    def setup(self) -> None:
        """Takes up one connection. On a wall listener every wait on it ends after WALL_PATIENCE seconds: for a
        request, the whole of it and the next one on the same connection, and for a reader that does not take what
        it was sent. The connection is closed then, without a word. A stream that is read goes on: it waits for the
        next moment, not for the visitor. One that sends a sign every few seconds keeps its place; how many places
        there are is the limit of the listener."""
        self.timeout = WALL_PATIENCE if self.server.wall else None
        super().setup()

    def log_message(self, *args) -> None:
        """Keeps the access log of the standard library quiet: the page asks all the time."""
        pass

    def handle(self) -> None:
        """Answers the requests of one connection, one after another. A visitor that hangs up before its request is
        read, or between two of them, is no failure of ringtop: the connection is done, and nothing is thrown (the
        standard library would print a traceback into the log for each one). Only the end of a connection is
        passed over: any other error is still thrown, and said."""
        with contextlib.suppress(ConnectionError):
            super().handle()

    def send_body(self, status: int, body: bytes, kind: str) -> None:
        """Sends one whole answer with its type and length, never to be cached and never to be guessed at by the
        browser. A page that left before its answer is no failure: the connection is done, and nothing is thrown."""
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        try:
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            self.close_connection = True

    def send_json(self, value, default=None) -> None:
        """Sends a value as compact JSON. `default` turns what JSON does not know (a set) into something it does."""
        self.send_body(200, json.dumps(value, separators=(",", ":"), default=default).encode(), "application/json")

    def do_GET(self) -> None:
        """Answers one request. A Host this machine does not go by is turned away first, whatever it asks for. Then
        the two kinds of listener part for good: a wall listener answers from wall_answer, the main one from
        main_answer. Nothing else belongs here: what is added to the way of the main listener later cannot reach a
        wall listener, and a branch put before the parting would."""
        if not host_allowed(self.headers.get("Host"), self.allowed_hosts):
            return self.send_body(403, b"Host not allowed\n", "text/plain")
        if self.server.wall:
            return self.wall_answer()
        return self.main_answer()

    def wall_answer(self) -> None:
        """All a wall listener answers: the calm page at / and at /wall, a part of that page, and its stream.
        Whatever else is asked of it is not found, and so is the page or a part whose file is not on disk. It looks
        into the tables of the wall and into nothing else of this file: no other page, no other table, not the
        model."""
        path = self.path.split("?", 1)[0]
        if path in ("/", "/wall") and WALL.is_file():
            return self.send_body(200, WALL.read_bytes(), "text/html; charset=utf-8")
        part = WALL_PARTS.get(self.path)  # the whole address as it came: a part has no other spelling
        if part and part[0].is_file():
            return self.send_body(200, part[0].read_bytes(), part[1])
        answer = WALL_API.get(path)
        if answer:
            return answer(self, dict(parse_qsl(self.path.partition("?")[2])))
        return self.send_body(404, b"Not found\n", "text/plain")

    def main_answer(self) -> None:
        """What the main listener answers: the page, the calm page at /wall, a part of either from the fixed
        tables, the model, or one of the API addresses. A page, a part or the model whose file is not on disk is
        not found."""
        path = self.path.split("?", 1)[0]
        page = {"/": PAGE, "/wall": WALL}.get(path)
        if page and page.is_file():
            return self.send_body(200, page.read_bytes(), "text/html; charset=utf-8")
        part = PAGE_PARTS.get(self.path) or WALL_PARTS.get(self.path)  # the whole address as it came
        if part and part[0].is_file():
            return self.send_body(200, part[0].read_bytes(), part[1])
        if path == "/assets/spark.glb":  # the only file served from disk besides the pages and their parts
            if not MODEL.is_file():
                return self.send_body(404, b"Not found\n", "text/plain")
            return self.send_body(200, MODEL.read_bytes(), "model/gltf-binary")
        answer = API.get(path)
        if answer:
            return answer(self, dict(parse_qsl(self.path.partition("?")[2])))
        return self.send_body(404, b"Not found\n", "text/plain")

    def state(self, query: dict) -> None:
        """/api/state: the newest moment with the curves of the last half hour, for a page that just opened."""
        self.send_json(self.hub.with_history())

    def nerd(self, query: dict) -> None:
        """/api/nerd: the deep view. `since` is the last log line the page has, `deep=1` asks for the heavy tables."""
        try:
            since = int(query.get("since") or 0)
        except ValueError:
            since = 0
        self.send_json(self.hub.nerd_view(since, query.get("deep") == "1"), default=sorted)

    def history(self, query: dict) -> None:
        """/api/history: a stretch of the past for the keys asked for, thinned to `points` columns, with the events
        of that stretch on `events=1`, and on `band=1` with the lowest value of every column and how many readings
        stand behind it. A range that is no number is a 400, and so is one that is no moment (nan, inf) or whose ends
        lie further apart than a number can say."""
        try:
            t1 = float(query.get("to") or time.time())
            t0 = float(query.get("from") or t1 - 3600)
            points = max(10, min(int(query.get("points") or 600), 4000))
            if not math.isfinite(t1 - t0):  # an end that is nan or inf gives no finite span either
                raise ValueError("a range has two finite ends a finite time apart")
        except ValueError:
            return self.send_body(400, b"Bad range\n", "text/plain")
        # A key named twice is answered once: it counts once towards the keys one request may name, then the cut.
        keys = list(dict.fromkeys(k for k in query.get("keys", "").split(",") if k))[:HISTORY_KEYS]
        answer = self.hub.history_range(keys, t0, t1, points, query.get("band") == "1")
        if query.get("events") == "1":
            answer["events"] = self.hub.events_between(t0, t1)
        self.send_json(answer)

    def replies(self, query: dict) -> None:
        """/api/replies: the last answers of the run a run source names, if it sends any."""
        self.send_json(self.hub.replies())

    def runs(self, query: dict) -> None:
        """/api/runs: the record of the run that is open and the records of the runs that ended, the newest first,
        at most `limit` of them: 50 unless asked otherwise, and no more than the hub holds in memory. Read off what
        the hub holds; no view is built for it. A limit that is no number counts as none given."""
        try:
            limit = int(query.get("limit") or 50)
        except ValueError:
            limit = 50
        self.send_json(self.hub.runs_view(max(1, min(limit, RUN_KEEP))))

    def metrics(self, query: dict) -> None:
        """/metrics: the moment the ticker built last, as Prometheus text. No view is built for it: a view notes
        events and looks for silent Sparks, and a scrape must leave the hub as it found it. Before the first moment,
        and once the newest is older than the silence that takes a Spark off the page (the ticker keeps a moment
        while it cannot build the next), the answer is a 503: a scrape that fails is the truth then."""
        payload, _ = self.hub.wait_tick(-1)  # no tick has that number: the newest moment at once, without a wait
        moment = json.loads(payload)
        if time.time() - moment.get("t", 0.0) > self.hub.silence:  # a hub starts with a moment that holds nothing
            return self.send_body(503, b"No moment of now\n", "text/plain")
        # a name the run source spelled as half a surrogate pair is no UTF-8: a question mark, not a failed scrape
        self.send_body(200, exposition(moment).encode("utf-8", "replace"), CONTENT_TYPE)

    def events(self, query: dict | None = None) -> None:
        """/api/events: the stream of moments, one per tick, each as the ticker built it."""
        self.stream()

    def wall(self, query: dict | None = None) -> None:
        """/api/wall: the stream of moments for a wall, one per tick: of each moment the fields a wall may get
        (wall_moment), never the moment as the ticker built it."""
        self.stream(wall_moment)

    def stream(self, part=None) -> None:
        """Sends one moment per tick down the connection, for as long as the page listens. A page that leaves ends
        it, whether that is after an hour or before the head of the answer went out. `part`: what of a moment is
        sent, as a function of the moment; all of it unless told."""
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        seen = 0
        try:
            self.end_headers()
            while True:
                payload, seen = self.hub.wait_tick(seen)
                if payload and part:
                    payload = json.dumps(part(json.loads(payload)), separators=(",", ":")).encode()
                self.wfile.write(b"data: " + payload + b"\n\n" if payload else b": still here\n\n")
                self.wfile.flush()
        except OSError:
            pass


# the addresses of the API, each with the method that answers it: looked up by the path, never built from it
API = {
    "/api/state": Handler.state,
    "/api/nerd": Handler.nerd,
    "/api/history": Handler.history,
    "/api/replies": Handler.replies,
    "/api/runs": Handler.runs,
    "/api/events": Handler.events,
    "/api/wall": Handler.wall,
    "/metrics": Handler.metrics,  # where Prometheus looks by default
}
WALL_API = {"/api/wall": Handler.wall}  # the one address of the API a wall listener answers
