"""The start with a wall: one more address for the calm page, bound late if it must be, and never every address."""

import contextlib
import http.client
import io
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from typing import ClassVar

import ringtop
from ringtop_parts.connect.server import PAGE, Handler, Listener
from ringtop_parts.connect.server import WALL as WALL_PAGE
from tests.fixtures import NoStderr
from tests.test_start import started

NOWHERE = "192.0.2.7"  # an address of no machine (TEST-NET-1): it can never be bound


def test_every_wall_address_gets_a_thread_of_its_own_after_the_main_port_is_bound():
    """The main page binds first and hard, as it always did. Each address asked for with --wall, once, is handed
    to a thread that ends with ringtop; they start last, when the page has its hub."""
    seen = started(["--demo", "--port", "18996", "--wall", "100.64.0.9", "--wall", "::1", "--wall", "100.64.0.9"])
    assert seen.order == ["server", "demo", "thread", "thread", "thread", "serving"], seen.order
    assert seen.server == (("127.0.0.1", 18996), Handler)  # the one listener main() builds itself
    assert seen.threads[0][0].__name__ == "ticker"
    walls = [(target.__name__, args, daemon) for target, args, daemon in seen.threads[1:]]
    assert walls == [("wall_listener", ("100.64.0.9", 18996, ()), True), ("wall_listener", ("::1", 18996, ()), True)], (
        walls
    )
    assert started(["--demo", "--port", "18996"]).order == ["server", "demo", "thread", "serving"]  # without: as before


class Done(BaseException):
    """Ends the loop of a wall listener once the check has seen enough."""


def wall_thread(plan, out, senders=()):
    """wall_listener run in this thread with stand-ins. `plan` says what becomes of each listener it builds, in
    order: "away" (the address cannot be bound), "dies" (it serves, then fails), "ends" (it serves, then comes
    back), "serves" (it serves, and the check ends there). Gives back every listener it tried to build with what
    became of it, how many were closed, and every pause it took. `senders`: who may read it, as the start hands
    them on; `wall_thread.given` keeps what each listener was built with."""
    built, naps, closed, fates = [], [], [], list(plan)
    wall_thread.given = []

    class Server:
        def __init__(self, address, handler, wall=False, senders=()):
            self.fate = fates.pop(0)
            built.append((address, handler, wall, self.fate))
            wall_thread.given.append(senders)
            if self.fate == "away":
                raise OSError(49, "Can't assign requested address")

        def serve_forever(self):
            if self.fate == "dies":
                raise RuntimeError("selector gone")
            if self.fate == "serves":
                raise Done

        def server_close(self):
            closed.append(self.fate)

    real = {name: getattr(ringtop, name) for name in ("Listener", "time")}
    ringtop.Listener, ringtop.time = Server, types.SimpleNamespace(sleep=naps.append)
    try:
        with contextlib.redirect_stdout(out), contextlib.suppress(Done):
            ringtop.wall_listener("100.64.0.9", 18995, senders)
    finally:
        for name, value in real.items():
            setattr(ringtop, name, value)
    return built, closed, naps


WALL = (("100.64.0.9", 18995), Handler, True)  # what a wall listener is built with


def test_a_wall_address_that_is_not_there_yet_is_tried_again_and_said_once():
    """The address of a tunnel is not there while the tunnel is down, and ringtop may start before it. Binding it
    fails twice: that is said once, on stdout (a line on stderr would read as a failure of the service), with the
    address and the reason; every try comes 15 s after the one before; the third one binds, and the listener that
    serves is a wall listener."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err):
        built, closed, naps = wall_thread(["away", "away", "serves"], out)
    assert built == [(*WALL, "away"), (*WALL, "away"), (*WALL, "serves")] and closed == [], (built, closed)
    assert naps == [15.0, 15.0] and ringtop.WALL_RETRY == 15.0, naps
    lines = out.getvalue().splitlines()
    assert len(lines) == 2 and err.getvalue() == "", (lines, err.getvalue())
    assert "100.64.0.9" in lines[0] and "Can't assign requested address" in lines[0] and "15 s" in lines[0], lines[0]
    assert lines[1].startswith("ringtop wall on http://100.64.0.9:18995"), lines[1]


def test_a_wall_address_that_binds_at_once_says_so_and_one_nobody_can_be_told_of_is_still_tried():
    """With the address there, nothing is said but where the calm page is. And where stdout cannot be written (a
    full disk under the log), saying it must not end the thread: the address is tried again all the same."""
    out = io.StringIO()
    built, closed, naps = wall_thread(["serves"], out)
    assert built == [(*WALL, "serves")] and closed == naps == [], (built, closed, naps)
    here = "ringtop wall on http://100.64.0.9:18995 (the calm page only, for every address that reaches it)"
    assert out.getvalue().splitlines() == [here]
    built, closed, naps = wall_thread(["away", "away", "away", "serves"], NoStderr())
    assert len(built) == 4 and closed == [] and naps == [15.0] * 3, (built, closed, naps)


def test_a_wall_listener_that_stops_serving_is_bound_again_by_the_same_thread():
    """Late binding held only until the first success: a wall listener whose loop failed left its address shut
    until ringtop was started again, while the main page went on. Now the thread that serves an address never
    ends. A listener that fails, or simply comes back from serving, is closed, said once on stdout with the
    reason, and bound anew 15 s later; an address that is away by then is waited for like at the start."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err):
        built, closed, naps = wall_thread(["dies", "away", "ends", "serves"], out)
    assert [fate for *_, fate in built] == ["dies", "away", "ends", "serves"], built
    assert all(listener[:3] == WALL for listener in built) and closed == ["dies", "ends"], (built, closed)
    assert naps == [15.0, 15.0, 15.0], (
        naps
    )  # after the failure, after the try that found the address away, after the end
    here = "ringtop wall on http://100.64.0.9:18995 (the calm page only, for every address that reaches it)"
    lines = out.getvalue().splitlines()
    assert [lines[0], lines[3], lines[5]] == [here] * 3 and len(lines) == 6 and err.getvalue() == "", (lines, err)
    assert "100.64.0.9 stopped" in lines[1] and "selector gone" in lines[1] and "15 s" in lines[1], lines[1]
    assert "100.64.0.9 not bound" in lines[2] and "Can't assign requested address" in lines[2], lines[2]
    assert "100.64.0.9 stopped" in lines[4] and "15 s" in lines[4], lines[4]


def test_for_real_a_wall_listener_that_died_answers_again_on_the_same_address():
    """The same with a real socket: the loop of the first listener fails at once, the thread closes it and binds
    the address anew, and a request to it gets the calm page. (The pause between the two is a fifth of a second
    here; the third listener ends the thread.)"""

    class Mortal(Listener):
        lives: ClassVar[list] = []

        def __init__(self, *args, **more):
            if len(Mortal.lives) == 2:
                raise SystemExit  # the check is over: a thread that ends this way says nothing
            super().__init__(*args, **more)

        def serve_forever(self, *args, **more):
            Mortal.lives.append(self)
            if len(Mortal.lives) == 1:
                raise RuntimeError("selector gone")
            super().serve_forever(*args, **more)

    port, out = free_port(), io.StringIO()
    real = (ringtop.Listener, ringtop.WALL_RETRY)
    ringtop.Listener, ringtop.WALL_RETRY = Mortal, 0.2
    try:
        with contextlib.redirect_stdout(out):
            thread = threading.Thread(target=ringtop.wall_listener, args=("127.0.0.1", port), daemon=True)
            thread.start()
            deadline = time.time() + 10
            while len(Mortal.lives) < 2 and time.time() < deadline:
                time.sleep(0.02)
            assert len(Mortal.lives) == 2, out.getvalue()
            assert asked("127.0.0.1", port, "/") == (200, WALL_PAGE.read_bytes())
            assert asked("127.0.0.1", port, "/api/state")[0] == 404  # and it is a wall listener still
            Mortal.lives[1].shutdown()
            thread.join(timeout=10)
        assert not thread.is_alive() and out.getvalue().count("stopped") == 2, out.getvalue()
    finally:
        ringtop.Listener, ringtop.WALL_RETRY = real


def test_a_wall_address_is_one_ip_address_and_never_the_one_of_the_main_page():
    """A wall listener sends less than the main one, so which of the two answers on an address must never be open:
    not every address (0.0.0.0, ::), not the address of the main page however it is spelled, and not beside a main
    page that listens on every address, which would answer on the wall address until the wall listener has it.
    A name is no address: it may resolve to anything. Each is an error of the command line, before the port."""
    for argv, word in (
        (["--wall", "0.0.0.0"], "one address"),
        (["--wall", "::"], "one address"),
        (["--wall", "127.0.0.1"], "main page"),
        (["--bind", "::1", "--wall", "0:0:0:0:0:0:0:1"], "main page"),
        (["--bind", "0.0.0.0", "--wall", "100.64.0.9"], "every address"),
        (["--bind", "::", "--wall", "100.64.0.9"], "every address"),
        (["--wall", "wall.example.org"], "IP address"),
        (["--wall", "localhost"], "IP address"),
        (["--wall", ""], "IP address"),
        (["--wall", "100.64.0.9", "--wall", "::"], "one address"),
    ):
        try:
            seen = started(["--demo", *argv])
        except SystemExit as stop:
            assert stop.code == 2 and word in stop.said, (argv, stop.code, stop.said)
            assert stop.order == [], (argv, stop.order)  # not even the port
        else:
            raise AssertionError(f"started with {argv}: {seen.order}")


def free_port():
    """A port nobody listens on right now, on both loopback addresses as far as this machine has them."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def asked(host, port, path):
    """One real request: its status and its body."""
    link = http.client.HTTPConnection(host, port, timeout=20)
    try:
        link.request("GET", path)
        answer = link.getresponse()
        return answer.status, answer.read()
    finally:
        link.close()


def test_started_for_real_a_wall_address_that_cannot_be_bound_does_not_end_ringtop():
    """As the service starts it, by its full path from another folder, with one wall address no machine has and one
    on the loopback. ringtop comes up and stays up; the main page answers on its address with everything, the
    loopback wall listener with the calm page and with nothing of the API; the address that cannot be bound is said
    once on stdout, and stderr stays empty."""
    port = free_port()
    argv = [sys.executable, str(Path(ringtop.__file__).resolve()), "--demo", "--port", str(port)]
    with tempfile.TemporaryDirectory() as folder:
        out, err = Path(folder) / "out", Path(folder) / "err"
        with out.open("w") as o, err.open("w") as e:
            running = subprocess.Popen([*argv, "--wall", NOWHERE, "--wall", "::1"], cwd="/", stdout=o, stderr=e)
        try:
            deadline = time.time() + 30
            while time.time() < deadline and out.read_text().count("\n") < 3 and running.poll() is None:
                time.sleep(0.1)
            said = out.read_text().splitlines()
            assert running.poll() is None and f"ringtop on http://127.0.0.1:{port}" in said, (running.poll(), said)
            away = [line for line in said if NOWHERE in line]
            assert len(away) == 1 and "trying again every 15 s" in away[0], said
            assert asked("127.0.0.1", port, "/")[1] == PAGE.read_bytes()
            assert asked("127.0.0.1", port, "/api/state")[0] == 200
            everybody = "(the calm page only, for every address that reaches it)"
            if f"ringtop wall on http://[::1]:{port} {everybody}" in said:  # a machine with IPv6
                assert asked("::1", port, "/") == (200, WALL_PAGE.read_bytes())
                for path in ("/api/state", "/api/events", "/metrics", "/page/main.js", "/assets/spark.glb"):
                    assert asked("::1", port, path)[0] == 404, path
            else:
                assert sum("::1" in line for line in said) == 1, said
            assert running.poll() is None and err.read_text() == "", err.read_text()
        finally:
            running.terminate()
            running.wait(timeout=20)


def test_a_main_port_that_is_taken_still_ends_the_start_with_a_wall_asked_for():
    """Late binding is for the wall addresses alone. A second ringtop on the port of the first must end as it
    always did, before it opens anything, and no wall listener comes up."""
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = str(taken.getsockname()[1])
        argv = [sys.executable, str(Path(ringtop.__file__).resolve()), "--demo", "--port", port, "--wall", "::1"]
        done = subprocess.run(argv, cwd="/", capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 and "Address already in use" in done.stderr, (done.returncode, done.stderr[-300:])
    assert "ringtop" not in done.stdout, done.stdout


def test_no_spelling_of_every_address_gets_past_the_wall_option_under_any_python():
    """The check for "every address" asked the address itself, and an older Python answers differently: under 3.9
    `::ffff:0.0.0.0` passed as a single address, and this machine takes IPv4 on such a socket: a wall listener on
    every IPv4 address. And beside --wall a main page on every address was refused only when it was spelled
    0.0.0.0 or ::, while `--bind 0` is the same to a socket. Now an address of the command line is read by one
    reader only (`ipaddress`), and what it does not read as one IP address is refused: the short forms a socket
    takes for 0.0.0.0, a name, and any IPv4 address inside an IPv6 one. Beside --wall the same holds for --bind.
    The suite runs this under both interpreters."""
    for argv, word in (
        (["--wall", "::ffff:0.0.0.0"], "inside an IPv6"),
        (["--wall", "::ffff:0:0"], "inside an IPv6"),
        (["--wall", "::ffff:127.0.0.1"], "inside an IPv6"),
        (["--wall", "::ffff:100.64.0.9"], "inside an IPv6"),
        (["--wall", "0:0:0:0:0:ffff:0:0"], "inside an IPv6"),
        (["--wall", "0"], "IP address"),
        (["--wall", "0.0"], "IP address"),
        (["--wall", "0x0.0.0.0"], "IP address"),
        (["--wall", "00.0.0.0"], "IP address"),
        (["--wall", "0.0.0.0 "], "IP address"),
        (["--wall", "[::]"], "IP address"),
        (["--wall", "*"], "IP address"),
        (["--wall", "0:0:0:0:0:0:0:0"], "one address"),
        (["--wall", "::0.0.0.0"], "one address"),
        (["--bind", "0", "--wall", "100.64.0.9"], "IP address"),
        (["--bind", "", "--wall", "100.64.0.9"], "IP address"),
        (["--bind", "localhost", "--wall", "100.64.0.9"], "IP address"),
        (["--bind", "macbook.local", "--wall", "100.64.0.9"], "IP address"),
        (["--bind", "::ffff:0.0.0.0", "--wall", "100.64.0.9"], "inside an IPv6"),
        (["--bind", "::ffff:127.0.0.1", "--wall", "100.64.0.9"], "inside an IPv6"),
        (["--bind", "0:0:0:0:0:0:0:0", "--wall", "100.64.0.9"], "every address"),
    ):
        try:
            seen = started(["--demo", *argv])
        except SystemExit as stop:
            assert stop.code == 2 and word in stop.said, (argv, stop.code, stop.said[-200:])
            assert stop.order == [], (argv, stop.order)  # not even the port
        else:
            raise AssertionError(f"started with {argv}: {seen.order}")
    for bind in ("0", "localhost", "0.0.0.0"):  # without --wall, --bind means what it always meant
        assert started(["--demo", "--bind", bind]).order[0] == "server", bind


def test_a_wall_address_is_bound_as_the_address_that_was_checked():
    """What is handed to the socket is the address as `ipaddress` writes it, not the text that was typed: one
    address spelled two ways is one listener, and nothing a socket reads more freely gets there."""
    given = ["0:0:0:0:0:0:0:1", "::1", "100.64.0.9", "100.64.0.9"]
    assert ringtop.wall_addresses(given, "127.0.0.1") == ["::1", "100.64.0.9"]
    assert ringtop.wall_addresses([], "0") == []  # nothing asked for: --bind is not looked at
    seen = started(["--demo", "--port", "18994", "--wall", "0:0:0:0:0:0:0:1"])
    assert [args for _, args, _ in seen.threads[1:]] == [("::1", 18994, ())], seen.threads
