"""The way to the nodes and to the run source: the programs ringtop sends, the commands it tries, the samples back."""

from __future__ import annotations

import collections
import contextlib
import json
import shlex
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from ringtop_parts.core.cluster import parse_runs
from ringtop_parts.core.hub import Hub
from ringtop_parts.store import Store

NODE = Path(__file__).resolve().parent.parent / "node"
# The sampler is one program in several files: joined in this order they share one namespace, as one file would.
# A linter reads file by file and a formatter hook rewrites for the newest Python, so every file of a program keeps
# linters off with its first line; tests/test_sampler.py checks the joined text instead.
SAMPLER_PARTS = tuple(
    f"sampler/{name}.py"
    for name in (
        "base",
        "gpu",
        "host",
        "engine",
        "work",
        "logs_threads",
        "links",
        "kernel",
        "deep",
        "background",
        "loop",
    )
)


def program(parts) -> str:
    """One program for a node as the text it is sent as: its files, joined in the order given. Nothing is installed
    over there, the text goes to `python3 -`."""
    return "".join((NODE / part).read_text(encoding="utf-8") for part in parts)


# Finds the checkout and its node map. Runs where the head node is, as `python3 - REPO`.
DISCOVER = program(["discover.py"])
# Runs on every node as `python3 -u - INTERVAL ROLE PORT REPO SALT` and prints one JSON line per interval.
# It stops by itself when the SSH connection goes away (the next print fails).
SAMPLER = program(SAMPLER_PARTS)
# Runs on the head node once, as `python3 - DAYS`: old engine logs hold the speed of every past run, one line per 10 s.
BACKFILL = program(["backfill.py"])
HEAD_LOOK = 15.0  # seconds between two looks for the head of a map that names none: the programs come every 15 s


class NodeStream(threading.Thread):
    """One sampler on one node, reconnecting for as long as ringtop runs."""

    def __init__(self, hub: Hub, node: dict, commands: list[list[str]], remake=None):
        """Takes the Hub to feed, the node to watch and the commands that may reach it, the likeliest first. `remake`
        makes the commands anew for the node, for when it takes another role (retarget)."""
        super().__init__(daemon=True)
        self.hub, self.node, self.commands, self.remake = hub, node, commands, remake
        self.process: subprocess.Popen | None = None
        self.turn = 0  # how often retarget gave the node new commands: a try begun in an older turn is over
        self.turning = threading.Lock()  # retarget and the reordering of the commands, one at a time

    def retarget(self) -> None:
        """The node took another role (core/heads.py): its commands are made anew for it, and the sampler that runs
        ends, so the next one starts with the new role at once. That is no node gone away: nothing marks it down."""
        with self.turning:
            if self.remake:
                self.commands[:] = self.remake(self.node)
            self.turn += 1
        process = self.process
        if process and process.poll() is None:
            process.terminate()

    def stream(self, command: list[str]) -> tuple[bool, str]:
        """Runs the sampler over one command and hands every sample to the Hub, until the stream ends. Says whether a
        sample ever came, and the last word the command left. A command that cannot start is a try that failed."""
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",  # bytes that are no text make a line that is no sample, not the end of this thread
            )
        except OSError as problem:  # no ssh, no room for another process: tried again like any node that is away
            return False, str(problem)[:200]
        self.process = process
        errors: collections.deque = collections.deque(maxlen=3)
        last_words = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
        last_words.start()
        try:
            process.stdin.write(SAMPLER)
            process.stdin.close()
        except OSError:
            pass
        reached = False
        for line in process.stdout:
            try:
                sample = json.loads(line)
            except ValueError:
                continue
            if not isinstance(sample, dict):  # a number or a word some banner printed: no sample, nothing reached
                continue
            reached = True
            try:
                self.hub.ingest(self.node["name"], sample)
            except Exception as problem:  # nothing a sample holds may end this stream, and no stderr that is shut
                with contextlib.suppress(OSError, ValueError):
                    print(f"ringtop: {self.node['name']}: sample skipped: {problem!r}", file=sys.stderr, flush=True)
        process.wait()
        last_words.join(1.0)  # what the command said last may still be on its way through the pipe
        return reached, (errors[-1].strip() if errors else "The connection closed")[:200]

    def run(self) -> None:
        """Keeps the node streaming for as long as ringtop runs: tries its commands in turn, puts the one that worked
        first, marks the node down between tries and waits longer after each failure, up to half a minute. A sampler
        that retarget ended is started anew at once, without a mark."""
        delay = 1.0
        while True:
            turn, reason = self.turn, "No way to reach this node"
            for command in list(self.commands):
                reached, reason = self.stream(command)
                if self.turn != turn:
                    break
                if reached:
                    with self.turning:
                        if self.turn == turn and command in self.commands:  # the list may have changed meanwhile
                            self.commands.remove(command)
                            self.commands.insert(0, command)
                    delay = 1.0
                    break
            if self.turn != turn:  # retarget gave new commands: the next sampler starts now, with the new role
                continue
            self.hub.node_down(self.node["name"], reason)
            time.sleep(delay)
            delay = min(30.0, delay * 2)


def run_python(code: str, args: list[str], target: str | None, timeout: float = 60) -> subprocess.CompletedProcess:
    """Runs one of the programs for the nodes, on the head node over SSH or on this machine, its text piped to `python3
    -`. Gives back the finished process."""
    if target:
        remote = shlex.join(["python3", "-", *args])
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, remote]
    else:
        command = [sys.executable, "-", *args]
    return subprocess.run(command, input=code, capture_output=True, text=True, timeout=timeout)


def backfill(store: Store, target: str | None, days: int = 30) -> None:
    """Once, on an empty history: the speed of past runs from the engine logs that are already on the head node."""
    try:
        result = run_python(BACKFILL, [str(days)], target, timeout=240)
        if result.returncode != 0:  # the reader failed: that is not "no earlier runs"
            raise OSError(result.stderr.strip()[-200:] or f"exit {result.returncode}")
        added = store.backfill(json.loads(result.stdout))
        print(f"ringtop: {added} minutes of earlier runs read from the engine logs", file=sys.stderr, flush=True)
    except (OSError, ValueError, subprocess.TimeoutExpired, sqlite3.Error) as problem:
        print(f"ringtop: earlier runs not read: {problem}", file=sys.stderr, flush=True)


def discover(target: str | None, repo: str | None) -> dict:
    """The checkout and node map as the head node reports them. Ends ringtop with a plain word when the head cannot be
    read or has no node map."""
    found, word = None, None
    try:
        result = run_python(DISCOVER, [repo or "-"], target)
        if result.returncode != 0:
            word = result.stderr.strip()[-300:]
        else:
            found = json.loads(result.stdout)
    except ValueError:
        word = "its answer is no node map"
    except (OSError, subprocess.TimeoutExpired) as problem:  # no ssh on this machine, or a head that hangs
        word = str(problem)[:300]
    if word is not None:
        raise SystemExit(f"Could not read the cluster{f' on {target}' if target else ''}: {word}")
    if not isinstance(found, dict) or not found.get("nodes"):
        raise SystemExit(
            "No config/nodes.json found under ~/projects/spark-ds41f*. Give the checkout with --repo PATH."
        )
    return found


def read_nodes(path: str) -> dict:
    """The node map from a file on this machine (--nodes), in the form of config/nodes.json of spark-ds41f, as
    discover gives it: no checkout, and this machine's name for the sampler that may run right here. Ends ringtop
    with a plain word when the file cannot be read or is no JSON."""
    try:
        node_map = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:  # a missing file, no permission, bytes that are no text, no JSON
        raise SystemExit(f"Could not read the node map {path}: {problem}") from None
    return {"nodes": node_map, "repo": None, "hostname": socket.gethostname()}


def node_commands(
    node: dict,
    cluster: dict,
    hostname: str,
    target: str | None,
    interval: float,
    port: str,
    repo: str | None,
    salt: str = "",
    target_is_head: bool = True,
) -> list[list[str]]:
    """The commands that may start the sampler on one node, the most direct first: this machine itself, the head by the
    target given, the node by its name and by its .local name, a worker through the head. `target_is_head`: whether
    the target is the head node (where discover read the map); where it is only the way in (--nodes), every node is
    reached by its name and through the target."""
    target_is_head = target_is_head and node["head"]
    args = [str(interval), "head" if node["head"] else "worker", port, repo or "-", salt]
    if not target and node["name"] == hostname:
        return [[sys.executable, "-u", "-", *args]]
    ssh = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
    ]
    remote = shlex.join(["python3", "-u", "-", *args])
    user = f"{cluster['user']}@" if cluster.get("user") else ""
    commands = []
    if target and target_is_head:
        commands.append([*ssh, target, remote])
    for host in (node["name"], f"{node['name']}.local"):
        commands.append([*ssh, f"{user}{host}", remote])
    if target and not target_is_head:
        commands.append([*ssh, "-J", target, f"{user}{node['name']}", remote])
    return commands


def seek_once(hub: Hub, streams: list[NodeStream]) -> None:
    """One look for the head of a map that names none (Hub.look_for_head): the samplers of the Sparks whose role it
    changed start anew with their new role."""
    moved = hub.look_for_head(time.time())
    for stream in streams:
        if stream.node["name"] in moved:
            stream.retarget()


def seek_head(hub: Hub, streams: list[NodeStream]) -> None:
    """Looks for the head of a map that names none every HEAD_LOOK seconds, for as long as ringtop runs. In the demo
    there are no samplers to start anew: the hub alone takes the head."""
    while True:
        time.sleep(HEAD_LOOK)
        seek_once(hub, streams)


def poll_runs(hub: Hub, command: str) -> None:
    """Asks the run source every 5 s what is running, for as long as ringtop runs, and hands the Hub the answer or the
    reason there is none."""
    while True:
        error, run = None, None
        try:
            done = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=10)
            if done.returncode:
                error = (done.stderr.strip() or f"exit {done.returncode}")[-200:]
            else:
                run = parse_runs(done.stdout) if done.stdout.strip() else None
        except (OSError, ValueError, RecursionError, subprocess.TimeoutExpired) as problem:  # deeper than json reads
            error = str(problem)[:200]
        with hub.lock:
            hub.external_run, hub.external_error = run, error
        time.sleep(5)
