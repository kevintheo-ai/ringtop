"""Who may read a wall listener: the senders named with --wall-from, and nobody else."""

import contextlib
import http.client
import io
import socket
import threading

import ringtop
from ringtop_parts.connect.server import WALL, Handler, Listener, sender_of
from tests.fixtures import serving
from tests.test_server_wall import closed, fed, until
from tests.test_start import started
from tests.test_start_wall import wall_thread

NOBODY = "192.0.2.9"  # an address of no machine (TEST-NET-1): no connection ever comes from it


def other_address():
    """Another IPv4 address this machine has beside the loopback, or None. Nothing is sent to find it."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        found = probe.getsockname()[0]
        return None if found.startswith("127.") else found
    except OSError:
        return None
    finally:
        probe.close()


def test_a_sender_is_compared_as_the_address_it_is_and_not_as_the_text_a_socket_writes():
    """A listener on IPv4 names a sender as ('1.2.3.4', port), one on IPv6 as ('::1', port, flow, scope), and a
    socket that takes both writes an IPv4 sender as '::ffff:1.2.3.4'. The sender is read as the address it is: the
    IPv4 address inside such a one is that IPv4 address, so the spelling neither lets a stranger in nor keeps the
    real sender out, and one address written two ways is one. What is no address at all is nobody."""
    read = [str(sender_of(named)) for named in (("127.0.0.1", 5), ("::ffff:127.0.0.1", 5, 0, 0), ("::1", 5, 0, 0))]
    assert read == ["127.0.0.1", "127.0.0.1", "::1"], read
    assert sender_of(("0:0:0:0:0:0:0:1", 5, 0, 0)) == sender_of(("::1", 5, 0, 0))
    assert [sender_of(named) for named in (("no address", 5), ("", 5), (), None, ("127.0.0.1/8", 5))] == [None] * 5
    four = Listener(("127.0.0.1", 0), Handler, wall=True, senders=("127.0.0.1", "100.64.0.7"))
    six = Listener(("127.0.0.1", 0), Handler, wall=True, senders=("::1",))
    free = Listener(("127.0.0.1", 0), Handler, wall=True)
    main = Listener(("127.0.0.1", 0), Handler, senders=(NOBODY,))
    try:
        for named, served in (
            (("127.0.0.1", 5), True),
            (("100.64.0.7", 5), True),
            (("::ffff:100.64.0.7", 5, 0, 0), True),  # the named sender, as a socket for both families writes it
            (("127.0.0.2", 5), False),
            (("::ffff:127.0.0.2", 5, 0, 0), False),
            (("::1", 5, 0, 0), False),
            (("100.64.0.70", 5), False),
            (("no address", 5), False),
            ((), False),
        ):
            assert four.verify_request(None, named) is served, named
        assert six.verify_request(None, ("0:0:0:0:0:0:0:1", 5, 0, 0)) and six.verify_request(None, ("::1", 5, 0, 0))
        assert not six.verify_request(None, ("::ffff:0.0.0.1", 5, 0, 0)) and not six.verify_request(
            None, ("::2", 5, 0, 0)
        )
        # nobody named: everybody, as before. And the main listener is not asked who may read it
        assert free.verify_request(None, ("203.0.113.5", 5)) and main.verify_request(None, ("127.0.0.1", 5))
    finally:
        for listener in (four, six, free, main):
            listener.server_close()


def said_to(address, source=None, host="127.0.0.1"):
    """One whole request for the calm page from a sender: the status, or None when the connection was closed
    without an answer."""
    link = http.client.HTTPConnection(*address[:2], timeout=10, source_address=(source, 0) if source else None)
    try:
        link.putrequest("GET", "/", skip_host=True)
        link.putheader("Host", host)
        link.endheaders()
        return link.getresponse().status
    except (http.client.RemoteDisconnected, ConnectionError):
        return None
    finally:
        link.close()


def test_a_wall_listener_that_was_told_who_may_read_it_closes_every_other_sender_without_an_answer():
    """Everything that reaches the address of a wall listener could read the calm page. Told who may, it serves
    those senders only. A connection from anybody else is closed where it is accepted: no thread, no answer, not
    even a refusal, and no place among the 32. What the request says plays no part, its Host included: nothing of
    it is read. The main listener is not affected. With a second address of this machine as the sender, where it
    has one: the same listener serves the one that is named and closes the other."""
    hub, other = fed(), other_address()
    with serving(hub, wall=True, senders=(NOBODY,)) as shut, serving(hub, wall=True, senders=("127.0.0.1",)) as mine:
        threads = threading.active_count()
        for _ in range(40):  # more than the listener has places: none of them takes one
            stranger = socket.create_connection(shut.address[:2], timeout=5)
            with contextlib.suppress(ConnectionError):  # it may be closed before the request is written
                stranger.sendall(b"GET /api/wall HTTP/1.1\r\nHost: localhost\r\n\r\n")
            assert closed(stranger, 2.0), "a sender nobody named was kept"
            stranger.close()
        assert shut.server.open == 0 and threading.active_count() <= threads, (shut.server.open, threads)
        assert said_to(shut.address) is None and said_to(shut.address, host="localhost") is None
        assert mine("/")[::2] == (200, WALL.read_bytes()) and mine("/api/state")[0] == 404
        assert said_to(mine.address, host="evil.example") == 403  # a sender that is named is asked for its Host as ever
        if other:
            assert said_to(mine.address, source=other) is None, "the other address of this machine is not named"
        assert until(lambda: mine.server.open == 0), mine.server.open
    with serving(hub, senders=(NOBODY,)) as main:
        assert main("/")[0] == 200 and main("/api/state")[0] == 200  # the main listener serves whoever reaches it
    if other:
        with serving(hub, wall=True, senders=(other,)) as theirs:
            assert said_to(theirs.address, source=other) == 200 and said_to(theirs.address) is None


def test_senders_are_named_as_ip_addresses_and_only_beside_a_wall():
    """--wall-from takes what --wall takes: one IP address as `ipaddress` reads it, never every address, no name,
    no network, no IPv4 address inside an IPv6 one. Without --wall it names the readers of nothing, and is an
    error. Each before the port. The suite runs this under both interpreters."""
    for argv, word in (
        (["--wall-from", "100.64.0.7"], "--wall-from needs --wall"),
        (["--wall", "::1", "--wall-from", "0.0.0.0"], "every address"),
        (["--wall", "::1", "--wall-from", "::"], "every address"),
        (["--wall", "::1", "--wall-from", "100.64.0.0/10"], "IP address"),
        (["--wall", "::1", "--wall-from", "phone.example.org"], "IP address"),
        (["--wall", "::1", "--wall-from", "0"], "IP address"),
        (["--wall", "::1", "--wall-from", ""], "IP address"),
        (["--wall", "::1", "--wall-from", "::ffff:100.64.0.7"], "inside an IPv6"),
        (["--wall", "::1", "--wall-from", "100.64.0.7", "--wall-from", "*"], "IP address"),
    ):
        try:
            seen = started(["--demo", *argv])
        except SystemExit as stop:
            assert stop.code == 2 and word in stop.said and "--wall-from" in stop.said, (argv, stop.said[-200:])
            assert stop.order == [], (argv, stop.order)
        else:
            raise AssertionError(f"started with {argv}: {seen.order}")
    named = ["--wall-from", "100.64.0.7", "--wall-from", "0:0:0:0:0:0:0:1", "--wall-from", "100.64.0.7"]
    seen = started(["--demo", "--port", "18993", "--wall", "::1", "--wall", "100.64.0.9", *named])
    walls = [(target.__name__, args) for target, args, _ in seen.threads[1:]]
    readers = ("100.64.0.7", "::1")  # each once, as `ipaddress` writes it, the same for every wall listener
    assert walls == [("wall_listener", ("::1", 18993, readers)), ("wall_listener", ("100.64.0.9", 18993, readers))]
    assert ringtop.wall_senders([], ["::1"]) == () and ringtop.wall_senders([], []) == ()


def test_the_start_says_on_stdout_who_reaches_a_wall_listener():
    """The line that says where the calm page is says who may read it too: the senders that were named, or that
    it is everybody who reaches the address. And the listener is built with exactly those senders."""
    out = io.StringIO()
    wall_thread(["serves"], out, senders=("100.64.0.7", "::1"))
    assert out.getvalue().splitlines() == [
        "ringtop wall on http://100.64.0.9:18995 (the calm page only, for 100.64.0.7, ::1)"
    ], out.getvalue()
    assert wall_thread.given == [("100.64.0.7", "::1")], wall_thread.given
    out = io.StringIO()
    with contextlib.redirect_stderr(out):
        wall_thread(["away", "serves"], out)
    assert out.getvalue().splitlines()[-1] == (
        "ringtop wall on http://100.64.0.9:18995 (the calm page only, for every address that reaches it)"
    ), out.getvalue()
    assert wall_thread.given == [(), ()], wall_thread.given
