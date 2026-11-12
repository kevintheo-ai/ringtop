"""How a try to the phone ends at its limit: the word is that of the limit, whatever the try says as it is broken
off, and a try ended before it wrote its request writes nothing, however late its socket is shut. All on
127.0.0.1."""

import socket
import threading
import time

from ringtop_parts.connect import notify
from ringtop_parts.connect.notify import send
from ringtop_parts.core import alerts
from tests.catcher import CANARY, Catcher, trickle
from tests.test_start_notify import stand_ins


class Lingering(notify.Try):
    """A try whose end takes its time after the socket is shut: the try wakes up meanwhile and says its own word."""

    def end(self) -> bool:
        """Ends the try as ever, then waits a little."""
        out = super().end()
        time.sleep(0.3)
        return out


class Late(notify.Try):
    """A try whose limit comes right after it holds its connection, and before it writes its request."""

    def hold(self, link) -> bool:
        """Holds the connection, then lets the limit come and waits until the try is marked as ended."""
        held = super().hold(link)
        threading.Thread(target=self.end, daemon=True).start()
        while not self.over:
            time.sleep(0.001)
        return held


def test_at_the_limit_the_word_is_timeout_whatever_the_try_says_as_it_is_broken_off():
    """The try is ended at its limit, wakes up from its shut socket and says what went wrong for it (the server hung
    up). That is not what happened: the limit ran out, and so the word is "timeout", with whether it may be out.
    The server sends a byte now and then, so no wait of the socket runs out: only the shut socket wakes the try."""
    with stand_ins(Try=Lingering), Catcher(trickle) as phone:
        for _ in range(3):
            assert send(phone.address, CANARY, "away on", limit=0.5) == ("timeout", True)
            for worker in notify.FLYING:
                worker.join(5)


def test_a_try_ended_before_it_wrote_its_request_writes_nothing_however_late_its_socket_is_shut():
    """The limit may come between holding the connection and writing the request, and the socket is shut only a
    moment after that. In that moment the try writes nothing: once it was ended it does not begin to send, and it
    says that nothing left."""
    real = socket.socket.shutdown

    def lagging(sock, how):
        time.sleep(0.5)
        real(sock, how)

    with Catcher() as phone:
        socket.socket.shutdown = lagging
        try:
            assert notify.post(Late(), phone.address, CANARY, alerts.message("away on"), 5.0) == ("timeout", False)
        finally:
            socket.socket.shutdown = real
        time.sleep(0.8)
        assert not any(phone.got), phone.got
