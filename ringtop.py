"""ringtop: see what a vLLM cluster of DGX Sparks is doing right now.

    python3 ringtop.py                  on the head node of a spark-ds41f checkout
    python3 ringtop.py user@head-node   from any machine that reaches the head over SSH
    python3 ringtop.py --demo           made-up data, no hardware needed
    python3 ringtop.py --nodes FILE     a cluster without spark-ds41f: its node map from a file on this machine

Then open http://127.0.0.1:8377. It reads the node map of spark-ds41f, samples every node over
SSH and installs nothing on them. Standard library only; the page never changes anything.
Prometheus, and whatever else reads its text format, finds the newest figures at /metrics.
A calm page for a wall or a phone is at /wall; --wall ADDRESS puts that page, and nothing else, on one more address,
and --wall-from ADDRESS says which senders may read it there.
With --ntfy-topic-cmd COMMAND a phone is told through an ntfy server when a Spark, a fan, a link, a GPU clock or the
engine is in trouble, and when that is over: fixed texts, to the topic the command prints. Without it nothing is sent.

This file is the start: it reads the arguments and connects the parts. The parts are small files:

    ringtop_parts/core/      rules and calculations: figures, the diagnosis, the Hub that holds what the page shows
    ringtop_parts/store.py   the history on disk; store_lows.py keeps the lowest value of every minute beside it
    ringtop_parts/connect/   the only ways outside: SSH to the nodes, the run source, the web server, the phone
    ringtop_parts/node/      the programs that are sent to the nodes as text: sampler, discover, backfill
    page/                    what the browser loads: one page, its style and its scripts
    tests/                   one file of checks per part; python3 test_ringtop.py runs them all
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import ipaddress
import json
import math
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from ringtop_parts.connect.notify import Phone, server_of, watch
from ringtop_parts.connect.server import Handler, Listener
from ringtop_parts.connect.shell import (
    NodeStream,
    backfill,
    discover,
    node_commands,
    poll_runs,
    read_nodes,
    seek_head,
)
from ringtop_parts.core.cluster import SAFE_TARGET, parse_cluster
from ringtop_parts.core.demo import Demo
from ringtop_parts.core.demo_faults import FAULT_PACE
from ringtop_parts.core.demo_forms import FORMS, demo_map
from ringtop_parts.core.hub import Hub
from ringtop_parts.store import Store


def heartbeat(hub: Hub, path: Path) -> None:
    """Every minute while data arrives, a small JSON file: whatever watches this service sees when it goes stale. One
    that cannot be written (a full disk) is a heartbeat missed, and the next one is tried."""
    while True:
        time.sleep(60)
        with hub.lock:
            alive = any(node["live"] for node in hub.nodes.values())
        if alive:
            now = time.time()
            body = {
                "job": path.stem,
                "ts": int(now),
                "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "exit_code": 0,
                "status": "ok",
                "message": "data arriving",
            }
            with contextlib.suppress(OSError):  # the watcher sees the gap; ended here, it would see one for good
                path.parent.mkdir(parents=True, exist_ok=True)
                spare = path.with_suffix(".tmp")
                spare.write_text(json.dumps(body))
                spare.replace(path)


def finite(text: str) -> float:
    """Seconds of the command line as a number. nan and inf are none: nothing can wait that long, or count with it."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


WALL_RETRY = 15.0  # seconds between two tries to bind an address the calm page is asked for on


def one_address(text: str, option: str):
    """An address of the command line as the one IP address it names, read by `ipaddress` and by nothing else.
    ValueError with the word why for what that does not read as an IP address (a name may resolve to anything, and
    a socket takes `0` and other short forms for every address), for an IPv4 address inside an IPv6 one (::ffff:…:
    an older Python does not see every address in such a one, and a socket bound to it listens on IPv4 as well),
    and for every address itself, however it is written."""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        raise ValueError(f"{option} takes an IP address, not {text!r}") from None
    if getattr(address, "ipv4_mapped", None) is not None:
        raise ValueError(f"{option} takes no IPv4 address inside an IPv6 one, and {text} is one")
    if address.is_unspecified:
        raise ValueError(f"{option} names one address, and {text} is every address")
    return address


def wall_addresses(given: list[str], bind: str) -> list[str]:
    """The addresses asked for with --wall, each once and as `ipaddress` writes it: what is bound is what was
    checked. A wall listener sends less than the main one, so which of the two answers on an address is never left
    open. Each has to be one IP address (one_address), and none the address of the main page. And beside --wall
    the main page has to be on one IP address too: on every address it would answer on the wall address until the
    wall listener is bound, and a name says nothing of where it listens. ValueError with the word why. Without
    --wall, --bind is not looked at: it means what it always meant."""
    if not given:
        return []
    main, out = one_address(bind, "--bind beside --wall"), []
    for text in given:
        address = one_address(text, "--wall")
        if address == main:
            raise ValueError(f"--wall {text} is the address of the main page")
        out.append(str(address))
    return list(dict.fromkeys(out))


def wall_senders(given: list[str], walls: list[str]) -> tuple:
    """The senders named with --wall-from, each once and as `ipaddress` writes it: who may read the wall
    listeners, nobody else. Each has to be one IP address (one_address): no name, no network, never every
    address. Named without a wall listener they would be the readers of nothing: ValueError with the word why."""
    if given and not walls:
        raise ValueError("--wall-from needs --wall: it says who may read the address --wall names")
    return tuple(dict.fromkeys(str(one_address(text, "--wall-from")) for text in given))


def read_options() -> argparse.Namespace:
    """The command line, read and checked. A target that is no user@host, an interval under half a second or seconds
    that are no finite number end the start with a word, before anything is opened."""
    parser = argparse.ArgumentParser(description="See what a vLLM cluster of DGX Sparks is doing right now.")
    parser.add_argument("target", nargs="?", help="user@head-node; leave out when running on the head node")
    parser.add_argument(
        "--repo", help="spark-ds41f checkout on the head node (default: newest ~/projects/spark-ds41f*)"
    )
    parser.add_argument(
        "--nodes",
        metavar="FILE",
        help="node map as a JSON file on this machine, in the form of config/nodes.json of spark-ds41f, for a cluster "
        "without that checkout; a target is then only the way in",
    )
    parser.add_argument(
        "--engine-port", default="auto", help="vLLM port on the head node (default: read from the container)"
    )
    parser.add_argument("--port", type=int, default=8377, help="port of this page (default 8377)")
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="address of this page; it has no login, keep it on loopback unless you trust the network",
    )
    parser.add_argument(
        "--wall",
        action="append",
        default=[],
        metavar="ADDRESS",
        help="one more IP address, on the same port, that sends only the calm page and its stream; may be repeated. "
        "Never every address, and --bind has to be one IP address beside it",
    )
    parser.add_argument(
        "--wall-from",
        action="append",
        default=[],
        metavar="ADDRESS",
        help="an IP address that may read the --wall addresses; with one or more given, no other sender is served",
    )
    parser.add_argument("--interval", type=finite, default=2.0, help="seconds between samples (default 2)")
    parser.add_argument("--runs-cmd", help="shell command printing the current run as JSON, polled every 5 s")
    parser.add_argument("--demo", action="store_true", help="made-up data, no hardware needed")
    parser.add_argument(
        "--demo-at",
        type=finite,
        default=0.0,
        metavar="SECOND",
        help="where the demo round starts: 0 to 240 plays the ring engine, 240 to 300 single tracks (default 0)",
    )
    parser.add_argument(
        "--demo-form",
        choices=list(FORMS),
        help="with --demo: another made-up cluster than the ring of four (ring4): one Spark, a ring of 2, 3 or 6, four "
        "on a switch, or a ring of four whose map names no head (find4)",
    )
    parser.add_argument(
        "--demo-faults",
        action="store_true",
        help="with --demo: every round also plays a Spark away, a GPU clock stuck, a fan standing, a link down and "
        "the engine silent, one after another, and the messages to a phone wait a twentieth as long",
    )
    parser.add_argument("--watch-stdin", action="store_true", help="exit when stdin closes, for a parent app")
    parser.add_argument("--heartbeat", help="file to update every minute while data arrives, for a service monitor")
    parser.add_argument(
        "--store", help="file to keep the history in, so it is there after a restart (default: memory only)"
    )
    phone_arguments(parser)
    options = parser.parse_args()
    if options.target and not SAFE_TARGET.match(options.target):
        parser.error("target must look like user@host")
    if options.interval < 0.5:
        parser.error("--interval must be at least 0.5 seconds")
    if options.nodes and options.repo:
        parser.error("--nodes and --repo name two node maps: give one of them")
    if options.demo_form and not options.demo:
        parser.error("--demo-form needs --demo: the forms are made-up clusters")
    options.demo_form = options.demo_form or "ring4"
    if options.demo_faults and not options.demo:
        parser.error("--demo-faults needs --demo: the faults are played on the made-up ring, never on a real one")
    for name in ("runs_cmd", "ntfy_topic_cmd"):
        if getattr(options, name) is not None and not getattr(options, name).strip():
            parser.error(f"--{name.replace('_', '-')} needs a command")
    try:
        options.wall = wall_addresses(options.wall, options.bind)
        options.wall_from = wall_senders(options.wall_from, options.wall)
        options.ntfy_server = server_of(options.ntfy_server)
    except ValueError as problem:
        parser.error(str(problem))
    return options


def phone_arguments(parser: argparse.ArgumentParser) -> None:
    """The options of the messages to a phone. Without --ntfy-topic-cmd, and without --ntfy-dry, none of them
    does anything: no thread, no call."""
    parser.add_argument(
        "--ntfy-topic-cmd",
        metavar="COMMAND",
        help="command printing the secret topic of an ntfy server: a phone that listens to it is told when the "
        "ring is in trouble, in fixed texts (default: nothing is sent)",
    )
    parser.add_argument(
        "--ntfy-server",
        default="https://ntfy.sh",
        metavar="ADDRESS",
        help="the ntfy server: https://HOST, or http://127.0.0.1:PORT to see what would leave (default https://ntfy.sh)",
    )
    parser.add_argument(
        "--ntfy-state", metavar="FILE", help="file keeping what the phone was told, so a restart tells nothing twice"
    )
    parser.add_argument(
        "--ntfy-dry", action="store_true", help="work the messages out and print their keys; send nothing, no topic"
    )


def demo_hub(options: argparse.Namespace, store: Store | None) -> Hub:
    """A hub the demo feeds: a made-up cluster of the form asked for (core/demo_forms.py, a ring of four unless another
    is asked for), and the round started at the second asked for."""
    shape = "tp4-ring" if options.demo_form == "ring4" else None
    hub = Hub(parse_cluster(demo_map(options.demo_form)), options.interval, memguard_gib=3, shape=shape, store=store)
    Demo(hub, options.demo_at % Demo.ROUND, options.demo_faults, options.demo_form).start()
    return hub


def ring_hub(options: argparse.Namespace, store: Store | None, streams: list[NodeStream]) -> Hub:
    """A hub the real ring feeds: the node map is read on the head, or from the file --nodes names, then every node
    gets its sampler, one SSH handshake at a time. The streams started are added to `streams`."""
    found = read_nodes(options.nodes) if options.nodes else discover(options.target, options.repo)
    cluster = parse_cluster(found["nodes"])
    hub = Hub(cluster, options.interval, memguard_gib=found.get("memguard_gib"), shape=found.get("shape"), store=store)
    salt = secrets.token_hex(16)  # the digests of hidden settings can be compared between nodes, and nothing else

    where = (found.get("hostname", ""), options.target, options.interval, options.engine_port, found.get("repo"), salt)
    named = any(node["head"] for node in cluster["nodes"]) and not options.nodes  # read on the head it names

    def commands_for(node: dict) -> list[list[str]]:
        """The commands that may start the sampler of one node, for the role it has now. The target is the head only
        where the map was read on it and names its head; else every node is reached by its own name first."""
        return node_commands(node, cluster, *where, named)

    for node in cluster["nodes"]:
        streams.append(NodeStream(hub, node, commands_for(node), commands_for))
        streams[-1].start()
        time.sleep(0.2)  # one SSH handshake at a time
    return hub


def close_streams(streams: list[NodeStream]) -> None:
    """Ends the SSH sessions of the samplers that still run."""
    for stream in streams:
        if stream.process and stream.process.poll() is None:
            stream.process.terminate()


def watch_stdin(streams: list[NodeStream]) -> None:
    """Ends ringtop when stdin closes: the app that started it is gone."""
    sys.stdin.read()
    close_streams(streams)
    os._exit(0)


def ticker(hub: Hub, interval: float) -> None:
    """Hands the page a fresh moment every interval, for as long as ringtop runs. A moment that cannot be built,
    whatever stopped it, is said on stderr, once for as long as it stays the same trouble; the page keeps the moment
    before, and the next one is tried. Where stderr cannot be written, it goes unsaid."""
    said = None
    while True:
        try:
            hub.beat()
            said = None
        except Exception as problem:  # nothing may end this loop: without it the page stands still for good
            if repr(problem) != said:
                said = repr(problem)
                with contextlib.suppress(OSError, ValueError):  # a full disk under the log, a pipe nobody reads
                    print(f"ringtop: moment not built: {said}", file=sys.stderr, flush=True)
        time.sleep(interval)


def tell(line: str) -> None:
    """One line on stdout, for the log of the service. Where stdout cannot be written (a full disk under the log,
    a pipe nobody reads) it goes unsaid."""
    with contextlib.suppress(OSError, ValueError):
        print(line, flush=True)


def wall_listener(address: str, port: int, senders: tuple = ()) -> None:
    """Serves the calm page on one more address, for as long as ringtop runs: this thread never ends, and ringtop
    never ends over it. The address may not be there yet (a tunnel that is down, a network that comes up after
    ringtop): then it is tried again every WALL_RETRY seconds, without end, and that it is not bound is said once.
    A listener that stops serving, whatever stopped it, is closed, said with the reason, and bound anew after the
    same pause. All of it is said on stdout, since a line on stderr reads as a failure of the service. `senders`:
    the addresses that may read it; the line that says where the page is says who reaches it."""
    host = f"[{address}]" if ":" in address else address
    readers = ", ".join(senders) or "every address that reaches it"
    again, told = f"trying again every {WALL_RETRY:.0f} s", False
    while True:
        try:
            server = Listener((address, port), Handler, wall=True, senders=senders)
        except Exception as problem:  # nothing may end this loop: without it the address stays shut for good
            if not told:
                told = True
                tell(f"ringtop: wall address {address} not bound ({problem}), {again}")
            time.sleep(WALL_RETRY)
            continue
        told = False
        tell(f"ringtop wall on http://{host}:{port} (the calm page only, for {readers})")
        try:
            server.serve_forever()
            problem = "it came back from serving"
        except Exception as trouble:
            problem = repr(trouble)
        with contextlib.suppress(Exception):  # whatever state it is in: the address has to be free for the next one
            server.server_close()
        tell(f"ringtop: wall address {address} stopped ({problem}), {again}")
        time.sleep(WALL_RETRY)


def start_helpers(options: argparse.Namespace, hub: Hub, store: Store | None, streams: list[NodeStream]) -> None:
    """The threads beside the samplers: the writer of the history, the one that reads the lowest values it misses
    from its samples and, once on an empty one, the reader of old logs; the heartbeat; the run source; the watch on
    stdin; the messages to a phone, if asked for; the look for the head of a map that names none; the ticker. The
    samplers end when ringtop does."""
    if store:
        threading.Thread(target=store.run, daemon=True).start()
        threading.Thread(target=store.catch_up, daemon=True).start()
        if not options.demo and not store.backfilled():
            threading.Thread(target=backfill, args=(store, options.target), daemon=True).start()
    atexit.register(close_streams, streams)
    if options.heartbeat:
        threading.Thread(target=heartbeat, args=(hub, Path(options.heartbeat).expanduser()), daemon=True).start()
    if options.runs_cmd:
        threading.Thread(target=poll_runs, args=(hub, options.runs_cmd), daemon=True).start()
    if options.watch_stdin:
        threading.Thread(target=watch_stdin, args=(streams,), daemon=True).start()
    if options.ntfy_topic_cmd or options.ntfy_dry:
        keep = Path(options.ntfy_state).expanduser() if options.ntfy_state else None
        pace = FAULT_PACE if options.demo_faults else 1.0
        phone = Phone(options.ntfy_topic_cmd, options.ntfy_server, keep, options.ntfy_dry, options.demo, pace)
        threading.Thread(target=watch, args=(hub, phone), daemon=True).start()
    if not any(node["head"] for node in hub.cluster["nodes"]):  # a map that names no head: ringtop looks for it
        threading.Thread(target=seek_head, args=(hub, streams), daemon=True).start()
    threading.Thread(target=ticker, args=(hub, options.interval), daemon=True).start()


def main() -> None:
    """Starts ringtop and serves the page until interrupted: the port first, then the history, the ring or the
    demo, the helpers, the names this machine may be asked by, and last a listener for every wall address."""
    options = read_options()
    # the port first: a second ringtop must stop here, before it writes to the same history or opens SSH sessions
    server = Listener((options.bind, options.port), Handler)
    store = Store(Path(options.store).expanduser(), options.interval) if options.store else None
    streams: list[NodeStream] = []
    hub = demo_hub(options, store) if options.demo else ring_hub(options, store, streams)
    start_helpers(options, hub, store, streams)
    Handler.hub = hub
    own = socket.gethostname().lower().split(".")[0]
    Handler.allowed_hosts = {"localhost", own, f"{own}.local"}
    if options.bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"Warning: this page has no login and is now reachable on {options.bind}.", file=sys.stderr)
    host = f"[{options.bind}]" if ":" in options.bind else options.bind  # an IPv6 address in a URL stands in brackets
    print(f"ringtop on http://{host}:{options.port}", flush=True)
    for address in options.wall:  # last: a wall listener answers from the hub the page was just given
        threading.Thread(target=wall_listener, args=(address, options.port, options.wall_from), daemon=True).start()
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == "__main__":
    socket.setdefaulttimeout(None)
    main()
