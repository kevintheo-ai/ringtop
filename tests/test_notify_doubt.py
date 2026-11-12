"""A try to the phone that may have reached it though the server did not say so: the phone thread counts it, sends
it once more, and never a third time; a try that reached nobody takes nothing of the cap. All on 127.0.0.1."""

import contextlib
import io
import time

from ringtop_parts.connect import notify
from ringtop_parts.connect.notify import Trying, turn
from ringtop_parts.core.alerts import BAD, CAP, GOOD, TROUBLES, begun, delivered, due, step
from tests.catcher import CANARY, TAKEN, Catcher, answer, topic_command
from tests.test_start_notify import GONE, T0, THERE, phone, stand_ins

# the head is away, and the link that leaves it is down: two troubles at once, away first in the order
TWO = {
    "nodes": [{"name": "dgx0", "head": True, "live": False}, {"name": "dgx1", "live": True}],
    "edges": [{"from": 1, "to": 0, "group": "f0", "up": False}],
    "engine": {"state": "idle"},
}


def read(**troubles):
    """Readings as `readings` gives them, of the troubles named: {thing: BAD, GOOD or None} each."""
    return {trouble: troubles.get(trouble, {}) for trouble in TROUBLES}


def test_a_second_copy_waits_behind_any_other_message_and_ends_only_with_its_own_trouble():
    """The second copy of a message that may have reached the phone goes when no other message is due: a new
    trouble is told first. A message of another trouble leaves the copy pending; one of its own trouble ends it,
    and so does a day that has no room left for it beside the word of the cap."""
    fan = {"dgx1": BAD}
    state = step(begun(), read(fan=fan), T0, 0.0)
    state = delivered(state, due(state), T0, sure=False)
    assert state["again"] == "fan on"
    state = step(state, read(fan=fan, away={"dgx2": BAD}), T0 + 2, 0.0)
    assert due(state) == "away on"  # the new trouble first
    state = delivered(state, "away on", T0 + 2)
    assert state["again"] == "fan on" and due(state) == "fan on"  # then the copy, still pending
    over = delivered(step(state, read(fan={"dgx1": GOOD}, away={"dgx2": BAD}), T0 + 4, 0.0), "fan off", T0 + 4)
    assert over["again"] is None  # its own trouble moved on: the end was told, and the copy is gone
    full = begun({"sent": [T0 - 100 + i for i in range(CAP - 4)]})
    full = delivered(step(full, read(fan=fan), T0, 0.0), "fan on", T0, sure=False)
    assert full["again"] == "fan on" and len(full["sent"]) == CAP - 3
    full = delivered(step(full, read(fan=fan, away={"dgx2": BAD}), T0 + 2, 0.0), "away on", T0 + 2)
    assert full["again"] == "fan on"
    full = delivered(step(full, read(fan=fan, away={"dgx2": BAD}, link={"0/f0": BAD}), T0 + 4, 0.0), "link on", T0 + 4)
    assert len(full["sent"]) == CAP - 1 and full["again"] is None  # the last place is the word of the cap's


def test_another_message_does_not_wait_behind_the_pause_of_a_second_copy():
    """After a try that may have reached the phone, its second copy waits the pause, and a message of another
    trouble that is due goes at once. A try that reached nobody still holds every message back."""
    tried, clock, answers = [], [T0], {}

    def send(server, topic, key, demo, limit, names=()):
        tried.append((round(clock[0] - T0), key))
        return answers.get(key, (None, False))

    for given, expected in (
        ({"away on": ("timeout", True)}, [(0, "away on"), (2, "link on"), (4, "away on")]),
        ({"away on": ("http 503", False)}, [(0, "away on")]),
    ):
        tried.clear()
        answers.clear()
        answers.update(given)
        state, trying, clock[0] = begun(), Trying(), T0
        with stand_ins(topic_from=lambda command: CANARY, send=send), contextlib.redirect_stdout(io.StringIO()):
            for _ in range(14):  # 28 s: within the first pause
                state = turn(phone("/bin/cat /x/topic"), state, trying, TWO, clock[0])
                clock[0] += 2.0
        assert tried == expected, tried


def test_a_try_that_reached_nobody_holds_every_later_message_back_for_its_pause():
    """A try refused by the server, or one that found nobody, holds back every message with its pause, not only
    its own: the head comes back before the pause is over and leaves the link of another trouble due, and that
    one waits for the end of the pause as well. Kept on purpose."""
    tried, clock = [], [T0]
    link = {**TWO, "nodes": [{"name": "dgx0", "head": True, "live": True}, {"name": "dgx1", "live": True}]}

    def send(server, topic, key, demo, limit, names=()):
        tried.append((round(clock[0] - T0), key))
        return refused if key == "away on" else (None, False)

    for refused in (("http 503", False), ("ConnectionRefusedError", False)):
        tried.clear()
        state, trying, clock[0] = begun(), Trying(), T0
        with stand_ins(topic_from=lambda command: CANARY, send=send), contextlib.redirect_stdout(io.StringIO()):
            for i in range(16):  # 30 s: the first pause, and the look at its end
                state = turn(phone("/bin/cat /x/topic"), state, trying, TWO if i < 2 else link, clock[0])
                clock[0] += 2.0
        assert tried == [(0, "away on"), (30, "link on")], (refused, tried)


def test_a_try_that_may_have_reached_the_phone_counts_and_goes_once_more():
    """A stand-in way out that always gets the message to the server and never its answer: the first try is
    counted and told, the second copy goes after the pause, and then nothing more while the trouble lasts. Its
    end goes out as any message does."""
    tried, out, state, trying, clock = [], io.StringIO(), begun(), Trying(), [T0]

    def send(server, topic, key, demo, limit, names=()):
        tried.append((round(clock[0] - T0), key))
        return ("timeout", True) if key == "away on" else (None, False)

    with stand_ins(topic_from=lambda command: CANARY, send=send), contextlib.redirect_stdout(out):
        for i in range(200):
            state = turn(phone("/bin/cat /x/topic"), state, trying, GONE if i < 100 else THERE, clock[0])
            clock[0] += 2.0
    assert tried == [(0, "away on"), (30, "away on"), (200, "away off")], tried
    assert out.getvalue().splitlines() == [
        "maybe notified: away on (timeout), counted, once more in 30 s",
        "maybe notified: away on (timeout), counted",
        "notified: away off",
    ], out.getvalue()
    assert len(state["sent"]) == 3 and state["told"]["away"] is False


def test_a_server_that_answers_after_the_limit_gets_two_copies_at_most_and_both_count():
    """The whole way out against a catcher that takes every message and answers only after the limit: the
    message reaches it twice, both count towards the cap, and the phone counts as told while the trouble lasts."""

    def late(link):
        time.sleep(1.0)
        with contextlib.suppress(OSError):
            link.sendall(TAKEN)

    out, state, trying, clock = io.StringIO(), begun(), Trying(), [T0]
    with stand_ins(LIMIT=0.3), Catcher(late) as server, topic_command() as command:
        asked = phone(command, server.address)
        with contextlib.redirect_stdout(out):
            for _ in range(400):
                state = turn(asked, state, trying, GONE, clock[0])
                clock[0] += 2.0
                for worker in notify.FLYING:
                    worker.join(5)
        assert len(server.caught(2)) == 2
    assert len(state["sent"]) == 2 and state["told"]["away"] is True and len(server.got) == 2
    assert out.getvalue().splitlines() == [
        "maybe notified: away on (timeout), counted, once more in 30 s",
        "maybe notified: away on (timeout), counted",
    ], out.getvalue()


def test_a_gateway_that_says_502_or_504_counts_like_a_server_that_answered_too_late():
    """A gateway in front of the server may say 502 or 504 once the server has the message: through the whole way
    out, two copies at the most, both counted, and the phone counts as told. A 503 is a refusal, as ever."""
    for status, copies in ((502, 2), (504, 2), (503, 0)):
        out, state, trying, clock = io.StringIO(), begun(), Trying(), [T0]
        with Catcher(answer(status, "Gateway")) as server, topic_command() as command:
            with contextlib.redirect_stdout(out):
                for _ in range(100):
                    state = turn(phone(command, server.address), state, trying, GONE, clock[0])
                    clock[0] += 2.0
            tries = len(server.caught(1))
        assert len(state["sent"]) == copies and state["told"]["away"] is (copies > 0), (status, state["sent"])
        assert tries == (2 if copies else 3), (status, tries)  # a refusal is tried again: at 0, 30, 90 s
        if copies:
            assert out.getvalue().splitlines() == [
                f"maybe notified: away on (http {status}), counted, once more in 30 s",
                f"maybe notified: away on (http {status}), counted",
            ], out.getvalue()


def test_tries_that_reached_nobody_take_nothing_of_the_cap():
    """Six hours in which every try fails before a byte of it left (no name, no connection, no time for the
    handshake) or is refused by the server: the cap of the day is untouched, and when the way is free again
    the phone gets what is so."""
    words = [("gaierror", False), ("http 503", False), ("ConnectionRefusedError", False), ("timeout", False)]
    tried, state, trying, free = [], begun(), Trying(), [False]

    def send(server, topic, key, demo, limit, names=()):
        tried.append(key)
        return (None, False) if free[0] else words[len(tried) % len(words)]

    with stand_ins(topic_from=lambda command: CANARY, send=send), contextlib.redirect_stdout(io.StringIO()):
        for i in range(6 * 1800):
            moment = GONE if (i // 600) % 2 == 0 else THERE  # twenty minutes away, twenty back
            state = turn(phone("/bin/cat /x/topic"), state, trying, moment, T0 + 2 * i)
        assert len(tried) > 40 and state["sent"] == [] and state["told"]["away"] is False, (len(tried), state)
        free[0] = True
        for i in range(6 * 1800, 6 * 1800 + 30):
            state = turn(phone("/bin/cat /x/topic"), state, trying, GONE, T0 + 2 * i)
    assert len(state["sent"]) == 1 and state["told"]["away"] is True
