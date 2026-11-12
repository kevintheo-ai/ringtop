"""The one way from ringtop to a phone: a fixed message to a topic of an ntfy server, and the thread that reads
every moment and sends what is due. The topic is a secret: it comes from a command, lives in a variable for one
try, and is in no line, no file and no error that leaves here."""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import select
import shlex
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ringtop_parts.core.alerts import (
    PLACEHOLDER,
    TEXTS,
    begun,
    delivered,
    due,
    kept,
    message,
    named,
    readings,
    step,
)

# What passes as a topic: 32 to 64 signs nobody guesses, of at least TOPIC_SIGNS different ones (secret). Whoever
# knows a topic reads its messages and may write some, so a short or a plain one is as good as public.
TOPIC = re.compile(r"[A-Za-z0-9_-]{32,64}")
TOPIC_SIGNS = 10
TOPIC_READ = 4096  # bytes of what the command of the topic prints that are read at most: a topic and its end are 65
# Where a message may go: any host over https, or a port of this very machine over plain http (a catcher that
# writes down what would leave). Nothing behind the host: the topic is the whole path.
SERVER = re.compile(r"(https://[A-Za-z0-9.-]+(:[0-9]{1,5})?|http://127\.0\.0\.1:[0-9]{1,5})/?")
LOCAL = "http://127.0.0.1:"
LIMIT = 10.0  # seconds one try to send may take, from its first step to its last
# Statuses a gateway in front of the server may give after the server has the message: they count as "maybe".
# Every other status that is no 2xx (3xx, 4xx, 500, 503) is the server's refusal.
# A status below 200 or from 600 on is no final answer (a 103 before the 200, or nonsense): "maybe" as well.
GATEWAY = (502, 504)
FLYING: list[threading.Thread] = []  # the try that was last started: it may still be on its way to the server
RETRY_FIRST, RETRY_MOST = 30.0, 900.0  # seconds to the next try after a failed one: doubled each time, up to these
KEPT_MOST = 65536  # bytes of the kept file that are read at most: what ringtop keeps there is a few hundred


@dataclass
class Phone:
    """How the messages to a phone were asked for on the command line."""

    command: str | None  # --ntfy-topic-cmd: prints the topic. None in a dry run without one
    server: str  # --ntfy-server, as server_of read it
    keep: Path | None  # --ntfy-state: the file that keeps what the phone was told
    dry: bool  # --ntfy-dry: work out and print, send nothing, touch no file
    demo: bool  # the ring is made up: every title says so
    pace: float = 1.0  # what the waits are multiplied by


@dataclass
class Trying:
    """Where the sending stands between two moments."""

    at: float = 0.0  # no try before this moment
    wait: float = 0.0  # the pause that was last taken after a failed try
    said: tuple | None = None  # the failure that was last said: the key and the word
    only: str | None = None  # the key the pause holds back: after "maybe" its second copy alone; None: every key


def server_of(text: str) -> str:
    """The server of --ntfy-server as messages are sent to it, without a slash at its end. ValueError with the
    word why for anything but https://HOST or http://127.0.0.1:PORT: over plain http to another machine the topic
    would cross the network in the clear, and a path, a query or a login has no place in it. A port is 1 to 65535."""
    if not usable(text):
        raise ValueError("--ntfy-server takes https://HOST[:PORT] or http://127.0.0.1:PORT, and nothing behind it")
    return text.rstrip("/")


def usable(server) -> bool:
    """Whether messages may go to a server: one SERVER takes, with a port there can be (1 to 65535)."""
    return isinstance(server, str) and bool(SERVER.fullmatch(server)) and 0 < place(server)[2] < 65536


def secret(topic) -> bool:
    """Whether a topic is one nobody guesses: TOPIC, of at least TOPIC_SIGNS different signs."""
    return isinstance(topic, str) and bool(TOPIC.fullmatch(topic)) and len(set(topic)) >= TOPIC_SIGNS


def head_of(stream, most: int, deadline: float) -> bytes | None:
    """All a stream gives up to its end, or None where that is more than `most` bytes, or the end does not come
    by the deadline (of time.monotonic)."""
    got = b""
    while len(got) <= most:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([stream], [], [], left)[0]:
            return None
        more = os.read(stream.fileno(), most + 1 - len(got))
        if not more:
            return got
        got += more
    return None


def topic_from(command: str, limit: float = 10.0) -> str | None:
    """The topic a command prints, or None. The command is split into words and run without a shell, like the
    run source, and has `limit` seconds. Of what it prints no more than TOPIC_READ bytes are read: then it is
    ended. None where it fails, prints too much, or prints what is no topic (secret). Nothing it says, and
    nothing that went wrong with it, is ever printed or kept."""
    try:
        child = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:  # no such command, no words in it
        return None
    deadline, word = time.monotonic() + limit, ""
    try:
        printed = head_of(child.stdout, TOPIC_READ, deadline)
        if printed is not None and child.wait(max(0.0, deadline - time.monotonic())) == 0:
            word = printed.decode("utf-8").strip()
    except Exception:  # it hangs, it prints no text: no topic
        word = ""
    finally:
        child.kill()  # nothing where it has ended already
        child.wait()
        child.stdout.close()
    return word if secret(word) else None


def place(server: str) -> tuple[bool, str, int]:
    """Of a server as SERVER takes it: whether it is https, its host, and its port (443 where https names none)."""
    scheme, _, rest = server.rstrip("/").partition("://")
    host, _, port = rest.partition(":")
    return scheme == "https", host, int(port) if port else 443


class Try:
    """One try to post one message, shared by the thread that makes it and the one that waits for it. The one
    that waits ends it at its limit: the connection is shut then, whatever it was waiting for, and a try that
    had not begun to send sends nothing. `out`: it had begun, so the message may have reached the server."""

    def __init__(self) -> None:
        """A try that nobody ended, without a connection yet, of which nothing left."""
        self.lock, self.link, self.over, self.out = threading.Lock(), None, False, False

    def hold(self, link) -> bool:
        """Takes the connection, so that `end` can shut it; False once the try was ended: it goes no further."""
        with self.lock:
            self.link = link
            return not self.over

    def go(self) -> bool:
        """Whether the request may be written now; from then on the message may be out. Not once the try was
        ended: then nothing of the request is written, however late its socket is shut."""
        with self.lock:
            self.out = not self.over
            return self.out

    def end(self) -> bool:
        """Ends the try: from now on it sends nothing, and the socket of its connection is shut (as a socket, so
        that no state of TLS is touched from this thread). Whoever waits on it then, for an answer, one more byte
        or the handshake, waits no longer. Gives whether the message may be out."""
        with self.lock:
            self.over, link, out = True, self.link, self.out
        sock = getattr(link, "sock", None)
        if sock is not None:
            with contextlib.suppress(OSError):
                socket.socket.shutdown(sock, socket.SHUT_RDWR)
        return out


def post(attempt: Try, server: str, topic: str, said: dict, limit: float) -> tuple[str | None, bool]:
    """One POST of one message: the fixed text as the body; title, urgency and sign as headers; beside them only
    what http.client writes itself (Host, Accept-Encoding: identity, Content-Length). It goes through no proxy
    and follows no redirect (http.client does neither): a 3xx is an answer like any other that is no 2xx. Gives
    (None, False) when the server took it (a 2xx), else one word for the log, the status or the kind of what went
    wrong, and whether the message may have reached the server all the same: never once the server answered
    with a status of 300 to 599 (but for GATEWAY), never before a byte of the request left. Never the text of an
    error: it may hold the address.
    Of the answer only its head is read, and none of it is kept."""
    https, host, port = place(server)
    if https:
        context = ssl.create_default_context()  # checks the certificate and the name of the host
        link = http.client.HTTPSConnection(host, port, timeout=limit, context=context)
    else:
        context, link = None, http.client.HTTPConnection(host, port, timeout=limit)
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "User-Agent": "ringtop",
        "Title": said["title"],
        "Priority": said["priority"],
        "Tags": said["tags"],
    }
    try:
        link.sock = socket.create_connection((host, port), limit)  # the name and the way: no byte of the message
        if context:  # the handshake comes after `hold`, so that `end` can break it off
            link.sock = context.wrap_socket(link.sock, server_hostname=host, do_handshake_on_connect=False)
        if not attempt.hold(link):
            return "timeout", False
        if context:
            link.sock.do_handshake()
        if not attempt.go():  # the limit came after the connection was held: nothing of the request is written
            return "timeout", False
        link.request("POST", f"/{topic}", said["body"].encode("ascii"), headers)
        status = link.getresponse().status
        if 200 <= status < 300:
            return None, False
        return f"http {status}", status in GATEWAY or not 300 <= status < 600
    except Exception as problem:  # no network, no name, a peer that says nothing or nonsense: all a failed try
        return "timeout" if isinstance(problem, socket.timeout) else type(problem).__name__, attempt.out
    finally:
        link.close()


def within(limit: float, server: str, topic: str, said: dict) -> tuple[str | None, bool]:
    """Makes one try in a thread of its own and waits `limit` seconds for it: what it gives (post), or "timeout"
    and whether the message may be out by then. The wait of a socket runs out only when no byte comes at all,
    so a peer that sends one now and then could hold a try for hours; this limit holds for the whole of it, and
    at the limit the try is ended, its connection shut (Try.end). What the try says is read before that: once it
    is ended, it wakes up from its shut socket and says a word of its own, and the word is "timeout". Only finding
    the server (its name, the connection) cannot be broken off: while a try is still at that, no other is started,
    and when it gets there it sends nothing. One thread and one connection at the most."""
    if any(worker.is_alive() for worker in FLYING):
        return "the try before still hangs", False
    attempt, out = Try(), []
    worker = threading.Thread(target=lambda: out.append(post(attempt, server, topic, said, limit)), daemon=True)
    FLYING[:] = [worker]
    worker.start()
    worker.join(limit)
    if out:
        return out[0]
    return "timeout", attempt.end()  # a word that comes between the two lines is the limit's too


def send(
    server: str, topic: str, key: str, demo: bool = False, limit: float = LIMIT, names=()
) -> tuple[str | None, bool]:
    """Sends the message of one key of TEXTS to a topic on a server: (None, False) when the server took it, else
    one word for the log, in which the topic never is, and whether the message may have reached the server all
    the same (post). It takes a key and never a text: what is no key is a KeyError; and with it only names of
    the closed table, for the gap of its text (alerts.gap_for: anything else is the fixed word). It checks for
    itself where it sends (usable) and what it puts into the address (secret). A text that is not plain ASCII
    is not sent at all, and one that is still a placeholder goes to a catcher on this machine and nowhere else."""
    said = message(key, demo, names)
    if not usable(server):
        return "no server", False
    if not secret(topic):
        return "no topic", False
    if not plain(said):
        return "text not ascii", False
    if PLACEHOLDER in said["title"] + said["body"] and not server.startswith(LOCAL):
        return "text not written", False
    return within(limit, server, topic, said)


def plain(said: dict) -> bool:
    """Whether every part of a message is plain ASCII, printable, on one line: what goes out as its bytes and
    headers, and can break none of them."""
    return all(part.isascii() and part.isprintable() for part in said.values())


def tell(line: str) -> None:
    """One line on stdout, for the log of the service. Where stdout cannot be written, it goes unsaid."""
    with contextlib.suppress(OSError, ValueError):
        print(line, flush=True)


def read_kept(file: Path | None):
    """What the start before kept in its file, or None: no file asked for, none there, no plain file (a device
    or a pipe has no end to read to), or one that is broken: bigger than KEPT_MOST, deeper than json goes, no
    UTF-8, no JSON, or under a folder nobody may look into. What it holds is checked by the one that takes it
    (alerts.begun)."""
    if file is None:
        return None
    try:
        if not file.is_file():
            return None
        with file.open("rb") as handle:
            data = handle.read(KEPT_MOST + 1)
        return json.loads(data) if len(data) <= KEPT_MOST else None
    except Exception:  # whatever is wrong with it, it is broken, and the start goes on from nothing
        return None


def write_kept(file: Path | None, value: dict) -> str | None:
    """Puts what is to be kept into its file by replacing it, and gives None, or the kind of what went wrong
    (never its text: it names the path). The spare written first lies beside the file, so that replacing stays
    on one disk, under a name nobody else has (mkstemp), and is gone again when anything fails."""
    if file is None:
        return None
    spare = None
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        handle, spare = tempfile.mkstemp(prefix=f".{file.name}.", suffix=".tmp", dir=file.parent)
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(json.dumps(value))
        os.replace(spare, file)
        return None
    except Exception as problem:  # a full disk, no right to write, a folder in the way
        if spare:
            with contextlib.suppress(OSError):
                os.unlink(spare)
        return type(problem).__name__


def keep(file: Path | None, value: dict, failed: str | None) -> str | None:
    """Writes what is kept (write_kept) and gives the kind of its failure, or None. A failure is said once, by
    its kind, until the file is written again: the next change tries anew."""
    now = write_kept(file, value)
    if now and now != failed:
        tell(f"ringtop: phone messages: what the phone was told is not kept ({now}), tried again")
    return now


def attempt(phone: Phone, key: str, names: tuple = ()) -> tuple[str | None, bool]:
    """One try to get the message of a key out, naming the Sparks it is about by their neutral names, as send
    gives it: (None, False) when it is out, else the word of the failure and whether the message may be out all
    the same. A dry run sends nothing and asks for no topic. Else the topic is asked for anew, for this try."""
    if phone.dry:
        return None, False
    topic = topic_from(phone.command or "")
    return ("no topic", False) if topic is None else send(phone.server, topic, key, phone.demo, LIMIT, names)


def turn(phone: Phone, state: dict, trying: Trying, moment: dict, now: float) -> dict:
    """One moment: what it reads is stepped into the state, and if a message is due and it is time for a try,
    one try is made. Gives the state after it. A message that went out is said. One that may have reached the
    server without its answer counts as told and towards the cap (alerts.delivered), is said each time, and its
    second copy waits the pause; another message that is due does not wait behind it. A try that reached nobody
    is said once per key and word, holds every message back, and the next one comes after RETRY_FIRST seconds,
    then after twice as long each time, up to RETRY_MOST, without end. A message that failed and is no longer due
    is dropped, and that is said."""
    state = step(state, readings(moment), now, phone.pace)
    key = due(state)
    if key is None:
        if trying.said:
            tell(f"dropped: {trying.said[0]} (over before it went out)")
        trying.at, trying.wait, trying.said, trying.only = 0.0, 0.0, None, None
        return state
    if now < trying.at and trying.only in (None, key):
        return state
    word, maybe = attempt(phone, key, named(state, key, moment))  # the Sparks as they are now, by place
    if word is None:
        tell(("would notify: " if phone.dry else "notified: ") + key)
        trying.at, trying.wait, trying.said, trying.only = 0.0, 0.0, None, None
        return delivered(state, key, now)
    trying.wait = min(RETRY_MOST, max(RETRY_FIRST, trying.wait * 2))
    trying.at, trying.only = now + trying.wait, key if maybe else None
    if maybe:
        state, trying.said = delivered(state, key, now, sure=False), None
        more = f", once more in {trying.wait:.0f} s" if state["again"] == key else ""
        tell(f"maybe notified: {key} ({word}), counted{more}")
    elif trying.said != (key, word):
        trying.said = (key, word)
        tell(f"not notified: {key} ({word}), next try in {trying.wait:.0f} s")
    return state


def watch(hub, phone: Phone) -> None:
    """Reads every moment the ticker builds and sends what is due, for as long as ringtop runs. It takes the
    moment as the page gets it (wait_tick): it builds no view and holds no lock of the hub, so a try that hangs
    delays this thread and nothing else. What the phone was told is kept in a file where one is asked for, and
    written whenever it changed; a broken file is a start from nothing, and one that cannot be written is said
    once and tried again with every moment (keep). Nothing may end this loop: a moment it cannot read is passed
    over, said once by the kind of the failure (never by its text), and the next one is read."""
    state = begun(None if phone.dry else read_kept(phone.keep))
    saved, trying, seen, said, unkept = kept(state), Trying(), 0, None, None
    for key in TEXTS:
        if not plain(message(key, phone.demo)):
            tell(f"ringtop: phone messages: the text of '{key}' is not plain ASCII, and it is never sent")
    if phone.dry:
        tell("ringtop: phone messages: dry run, nothing is sent")
    else:
        has_topic = topic_from(phone.command or "") is not None
        tell("ringtop: phone messages: " + ("on" if has_topic else "no topic yet, asked for again when one is due"))
    while True:
        try:
            payload, seen = hub.wait_tick(seen)
            if payload:
                state = turn(phone, state, trying, json.loads(payload), time.time())
                if not phone.dry and kept(state) != saved:
                    unkept = keep(phone.keep, kept(state), unkept)
                    saved = saved if unkept else kept(state)
            said = None
        except Exception as problem:  # whatever a moment holds: the thread goes on
            if type(problem).__name__ != said:
                said = type(problem).__name__
                tell(f"ringtop: phone messages: a moment was passed over ({said})")
            time.sleep(1.0)  # and if every look fails at once, it does not spin
