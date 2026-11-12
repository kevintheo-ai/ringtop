"""Messages that name the Sparks they are about: by the neutral names the page shows, picked from a closed table
by the place of a Spark in the ring, and nothing else of the moment in any byte that goes out. All on 127.0.0.1."""

import contextlib
import io

from ringtop_parts.connect.notify import Trying, send, turn
from ringtop_parts.core import alerts
from ringtop_parts.core.alerts import GAP_MARK, MANY, NEUTRAL, TEXTS, begun, message
from tests.catcher import CANARY, Catcher, topic_command
from tests.fixtures import needs_node
from tests.test_notify import TOOK, exact
from tests.test_page_measure import measure
from tests.test_start_notify import T0, phone

HOSTILE = "\x00\x1b[2J\r\nTitle: injected\r\n\r\nX-"  # a name of a Spark that would break a header, and a screen


def ring(names, live, places=None, links=()):
    """A moment of a ring: the Sparks by name and place (rank), which of them answer, its links as (from, to, up)."""
    places = list(range(len(names))) if places is None else places
    return {
        "cluster": {
            "ring": True,
            "nodes": [{"name": n, "rank": p, "head": i == 0} for i, (n, p) in enumerate(zip(names, places))],
        },
        "nodes": [{"name": n, "head": i == 0, "live": up} for i, (n, up) in enumerate(zip(names, live))],
        "edges": [{"from": a, "to": b, "group": "f0", "up": up} for a, b, up in links],
        "engine": {"state": "idle"},
    }


def told(moment, looks=3):
    """What a catcher gets when the phone thread looks at a moment a few times, every wait nothing: each request,
    with the port of the catcher taken out."""
    with Catcher() as server, topic_command() as command, contextlib.redirect_stdout(io.StringIO()):
        state, trying = begun(), Trying()
        for i in range(looks):
            state = turn(phone(command, server.address), state, trying, moment, T0 + 2 * i)
        got = server.caught(1)
    return [request.replace(str(server.port).encode(), b"PORT") for request in got]


def test_a_message_names_the_sparks_it_is_about_by_their_neutral_names_and_by_nothing_else():
    """The third Spark of four is away: the message names spark-3, as the page does with ?names=neutral. Sparks
    named in every way that could break a header or a screen give the very same bytes: only the place of a
    Spark picks its name, never what it is called."""
    plain = told(ring([f"dgx{i}" for i in range(4)], [True, True, False, True]))
    hostile = told(ring([f"{HOSTILE}{i}" for i in range(4)], [True, True, False, True]))
    assert len(plain) == 1 and plain == hostile, (plain, hostile)
    assert plain[0] == exact("away on", "PORT", names=("spark-3",))
    assert b"spark-3" in plain[0] and b"dgx" not in plain[0] and b"injected" not in plain[0]
    digits = plain[0].partition(b"\r\nUser-Agent")[2]  # past host, length and charset: digits only in the names
    assert {sign for sign in digits.decode() if sign.isdigit()} == {"3"}, digits


def test_a_link_is_named_by_both_its_ends():
    """A link of the ring is down between the second and the third Spark: the message names both of them."""
    names, live = [f"dgx{i}" for i in range(4)], [True] * 4
    links = [(0, 1, True), (1, 2, False), (2, 3, True), (3, 0, True)]
    got = told(ring(names, live, links=links))
    assert got == [exact("link on", "PORT", names=("spark-2", "spark-3"))]
    assert b"spark-2, spark-3" in got[0], got
    two_down = told(ring(names, live, links=[(1, 2, False), (3, 0, False)]))
    assert b"spark-1, spark-2, spark-3, spark-4" in two_down[0], two_down


def test_more_than_four_or_one_that_has_no_place_is_said_in_one_fixed_word():
    """Up to four Sparks are named, in the order of their places. Five or more, or one whose place is no place of
    the table (a text, a truth value, a number out of it), give the one fixed word instead of the names."""
    names = [f"dgx{i}" for i in range(16)]
    four = told(ring(names, [i not in (1, 4, 8, 15) for i in range(16)]))
    assert b"spark-2, spark-5, spark-9, spark-16" in four[0], four
    five = told(ring(names, [i not in (1, 4, 8, 13, 15) for i in range(16)]))
    assert MANY.encode() in five[0] and b"spark-" not in five[0], five
    for place in (True, "2", 2.0, 16, -1, None, [2]):
        got = told(ring(["dgx0", "dgx1"], [True, False], places=[0, place]))
        assert MANY.encode() in got[0] and b"spark-" not in got[0], (place, got)


def test_send_takes_a_key_and_names_of_the_table_and_nothing_else():
    """Whatever a caller hands send as names, only names of the closed table get into the gap; anything else
    turns the gap into the fixed word. A message without a gap stays as it is, whatever names come with it."""
    with Catcher() as server:
        for names, gap in (
            (("spark-2", "spark-1"), "spark-1, spark-2"),
            (("spark-1",) * 3, "spark-1"),
            (("dgx1",), MANY),
            ("spark-1", MANY),  # a text, not a list of names
            (("spark-1", "spark-1\r\nTitle: x"), MANY),
            (("spark-17",), MANY),
            ((), MANY),
            (None, MANY),
        ):
            assert send(server.address, CANARY, "fan on", names=names) == TOOK, names
            assert server.caught(1)[-1].endswith(message("fan on")["body"].replace(MANY, gap).encode()), names
            server.got.clear()
    for key in ("away off", "link off", "engine on", "engine off", "quiet"):
        assert message(key, names=("spark-1",)) == message(key), key
    assert message("away on", names=("spark-4",))["body"] == TEXTS["away on"]["body"].replace(GAP_MARK, "spark-4")


def test_every_named_text_has_its_gap_once_and_no_other_text_has_one():
    """away, latch, fan and link name their Sparks when they begin, in one gap of their text; their ends say that
    every one is well again, and the engine and the word of the cap name nobody."""
    for key, text in TEXTS.items():
        gaps = (text["title"] + text["body"]).count(GAP_MARK)
        assert gaps == (1 if key in ("away on", "latch on", "fan on", "link on") else 0), (key, gaps)
    assert MANY.isascii() and MANY.isprintable() and not any(sign.isdigit() for sign in MANY)
    assert tuple(f"spark-{n}" for n in range(1, 17)) == NEUTRAL


@needs_node
def test_the_names_are_the_ones_the_page_shows_with_neutral_names():
    """page/neutral.js names the Spark at place N spark-(N+1) (aliasPairs). The table of the messages is the same,
    place for place."""
    cluster = "{ nodes: [" + ", ".join(f"{{ name: 'dgx-{p}', rank: {p} }}" for p in range(16)) + "] }"
    shown = measure(f"return aliasPairs({cluster}).map(pair => pair[1]);")
    assert shown == list(NEUTRAL) == [alerts.alias(place) for place in range(16)], shown
