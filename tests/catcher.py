"""Stands in for the server of a phone in the checks: it listens on 127.0.0.1 only, writes down every request as
the bytes that came, and answers as a check tells it to. No check ever sends a byte to another machine."""

import contextlib
import json
import re
import shlex
import socket
import tempfile
import threading
import time
from pathlib import Path

# A topic no phone listens to: of the form a real one has. Wherever a check finds it, it leaked.
CANARY = "CANARY-topic-" + "x7Qk" * 8


def answer(status: int, reason: str = "OK", body: bytes = b"", **headers) -> bytes:
    """One whole HTTP answer as bytes."""
    lines = [f"HTTP/1.1 {status} {reason}", f"Content-Length: {len(body)}"]
    lines += [f"{name.replace('_', '-')}: {value}" for name, value in headers.items()]
    return "\r\n".join(lines).encode() + b"\r\n\r\n" + body


# what ntfy answers a message it took: JSON that names the topic
TAKEN = answer(200, body=json.dumps({"id": "x", "event": "message", "topic": CANARY}).encode())


def silent(link) -> None:
    """Takes the request and never answers. The connection stays open until the catcher closes."""


TRICKLE_ENDED: list[float] = []  # when each trickle ended because the other side shut the connection


def trickle(link) -> None:
    """Answers one byte every fifth of a second, without end: no wait for a byte ever runs out. Notes when the
    other side shut the connection on it."""
    with contextlib.suppress(OSError):
        for byte in TAKEN * 1000:
            link.sendall(bytes([byte]))
            time.sleep(0.2)
        return
    TRICKLE_ENDED.append(time.time())


HUGE_TAKEN: list[int] = []  # of every answer of 50 MB, how many of its 800 pieces the other side took


def huge(link) -> None:
    """Answers that it took the message, with 50 MB behind it, and notes how much of that was taken."""
    pieces = 0
    with contextlib.suppress(OSError):
        link.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 52428800\r\n\r\n")
        for _ in range(800):
            link.sendall(bytes(65536))
            pieces += 1
    HUGE_TAKEN.append(pieces)
    link.close()


class Catcher:
    """A server on a free port of 127.0.0.1. `got`: every request, as its bytes. `reply`: the bytes it answers
    each with, or a function that is handed the connection. `tls`: a context of ssl to serve over https with.
    `address`: what --ntfy-server takes."""

    def __init__(self, reply=TAKEN, tls=None):
        """Binds and listens; requests are taken in threads that end with the check."""
        self.reply, self.tls, self.got, self.links = reply, tls, [], []
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.port = self.listener.getsockname()[1]
        self.address = f"{'https' if tls else 'http'}://127.0.0.1:{self.port}"
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self) -> None:
        """Takes connections until the catcher closes."""
        while True:
            try:
                link, _ = self.listener.accept()
            except OSError:
                return
            self.links.append(link)
            threading.Thread(target=self.take, args=(link,), daemon=True).start()

    def take(self, link) -> None:
        """Reads one request, head and body, writes it down and answers it. Over https a handshake that fails is
        written down as an empty request: nothing came."""
        link.settimeout(5)
        if self.tls:
            try:
                link = self.tls.wrap_socket(link, server_side=True)
            except OSError:  # the other side did not take the certificate
                self.got.append(b"")
                return
        data = b""
        with contextlib.suppress(OSError):
            while b"\r\n\r\n" not in data:
                more = link.recv(65536)
                if not more:
                    break
                data += more
            length = re.search(rb"(?i)\r\ncontent-length: *(\d+)", data)
            whole = data.index(b"\r\n\r\n") + 4 + int(length.group(1)) if length and b"\r\n\r\n" in data else 0
            while len(data) < whole:
                more = link.recv(65536)
                if not more:
                    break
                data += more
        self.got.append(data)
        if callable(self.reply):
            return self.reply(link)
        with contextlib.suppress(OSError):
            link.sendall(self.reply)
        link.close()

    def caught(self, count: int, patience: float = 10.0) -> list:
        """Every request written down so far, after waiting until there are `count` of them, or `patience`
        seconds: a request is written down a moment after it was sent."""
        deadline = time.time() + patience
        while len(self.got) < count and time.time() < deadline:
            time.sleep(0.01)
        return list(self.got)

    def __enter__(self):
        """The catcher itself, for a `with`."""
        return self

    def hang_up(self) -> None:
        """Closes every connection that is still open: whoever waits for an answer on one waits no longer."""
        for link in self.links:
            with contextlib.suppress(OSError):
                link.shutdown(socket.SHUT_RDWR)
            link.close()

    def __exit__(self, *problem) -> None:
        """Closes the listener and every connection that is still open."""
        self.listener.close()
        self.hang_up()


def closed_port() -> int:
    """A port of 127.0.0.1 nobody listens on: a connection to it is refused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def topic_command(topic: str = CANARY):
    """A command that prints a topic, as --ntfy-topic-cmd takes one. The topic lies in a file: it is in no
    argument of any process."""
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "topic"
        file.write_text(topic + "\n")
        yield f"/bin/cat {shlex.quote(str(file))}"
