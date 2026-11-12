"""The lowest value of every minute: kept only when it is the lowest of all its samples, and made good from them."""

import contextlib
import io
import sqlite3
import tempfile
import time
import types
from pathlib import Path

from ringtop_parts import store_lows
from ringtop_parts.store import MINUTE_KEEP, RAW_KEEP, Store
from ringtop_parts.store_lows import lower, same, slot


def low_of(store, minute, keys=("a",)):
    """The lowest values the store gives for one minute, in the order of the keys asked for."""
    band = store.series(list(keys), minute - 3600 * 3, minute + 59, 400, band=True)
    return [band["low"][key][-1] for key in keys]


def the_stand_before(store, t, value, key="a"):
    """Writes one sample the way the stand before this one does: the sample and its minute, and no lowest value."""
    with store.writing:
        store.db.execute("BEGIN")
        store.merge_raw(t, {key: value})
        store.merge_minute(t // 60 * 60, {key: [value, 1, value, value]})
        store.db.execute("COMMIT")


def test_the_lowest_of_a_part_is_not_the_lowest_of_the_whole():
    """One unknown value among those of a column, and the lowest of the column is unknown."""
    nan = float("nan")
    assert lower(3.0, 2.0) == 2.0 and lower(float("inf"), 4.0) == 4.0
    assert lower(3.0, nan) != lower(3.0, nan) and lower(nan, 1.0) != lower(nan, 1.0)  # NaN, whichever side
    assert slot([1.0, 2.0], 1) == 2.0 and slot([1.0], 1) != slot([1.0], 1) and slot(None, 0) != slot(None, 0)
    assert same([1.0, nan], [1.0]) and same([nan], []) and not same([1.0], [2.0]) and not same([1.0], None)


def test_a_minute_begun_by_a_writer_that_kept_no_lowest_value_gets_it_from_the_samples():
    """The stand before this one wrote the first part of a minute and no lowest value. What comes after it is only a
    part of the minute: its lowest would stand too high. The samples of the whole minute say it."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        the_stand_before(store, minute, 3.0)
        store.add("a", minute + 2, 9.0)
        store.flush()
        assert low_of(store, minute) == [None]  # not 9.0
        assert store.fill_lows() == 1
        assert low_of(store, minute) == [3.0]
        store.add("a", minute + 4, 1.0)  # from here on a piece joins what is there
        store.add("b", minute + 4, 6.0)  # and a trace that begins in the middle of the minute has its own lowest
        store.flush()
        assert low_of(store, minute, "ab") == [1.0, 6.0]
        assert store.fill_lows() == 0  # nothing stands wrong any more


def test_a_minute_the_stand_before_went_on_writing_gets_its_true_lowest_value():
    """The way back: this stand began a minute, the stand before it went on writing the same file. It adds to the
    minute and knows no lowest value, so the one kept stands too high until the next start of this stand."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        store.add("a", minute, 5.0)
        store.flush()
        the_stand_before(store, minute + 2, 1.0)  # the rest of that minute
        the_stand_before(store, minute + 60, 4.0)  # and a minute of its own
        the_stand_before(store, minute + 62, 9.0)
        assert low_of(store, minute) == [5.0] and low_of(store, minute + 60) == [None]
        assert store.fill_lows() == 2
        assert low_of(store, minute) == [1.0] and low_of(store, minute + 60) == [4.0]
        assert store.fill_lows() == 0


def test_making_good_never_raises_a_lowest_value_the_writer_kept():
    """A node that reports late overwrites its slot of a sample that was written already: the samples then hold the
    later value only, the minute still knows the lower one. What was measured stays."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        store.add("a", minute + 2, 2.0)
        store.flush()
        store.add("a", minute + 2.5, 7.0)  # the same sample row, a moment later
        store.flush()
        assert store.recent(86400)[0][1] == {"a": 7.0} and low_of(store, minute) == [2.0]
        assert store.fill_lows() == 0 and low_of(store, minute) == [2.0]


def test_lowest_values_are_made_good_only_where_every_sample_of_the_minute_is_still_kept():
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        now = time.time()
        old, kept = (now - RAW_KEEP - 300) // 60 * 60, (now - 7200) // 60 * 60
        for minute in (old, kept):
            for i, value in enumerate((8.0, 2.0, 6.0)):
                store.add("a", minute + i * 2, value)
                store.add("b", minute + i * 2, value + 1)
        store.flush()
        row = [[0.0, 0.0], [50.0, 60.0], [1.0, 1.0], [0.0, 0.0], [12.0, 20.0], [40.0, 40.0]]
        assert store.backfill({str(int(kept) - 600): row}) == 1  # a minute read from old engine logs: no samples
        store.db.execute("DELETE FROM minute_low")
        # the samples of the old minute may be dropped in part already: its lowest would be a guess
        assert store.fill_lows(now) == 1
        assert [t for (t,) in store.db.execute("SELECT t FROM minute_low")] == [kept]
        assert low_of(store, kept, "ab") == [2.0, 3.0]
        store.prune(now + RAW_KEEP)  # the samples go after two days, the lowest values stay with their minutes
        assert [t for (t,) in store.db.execute("SELECT t FROM minute_low")] == [kept]
        store.prune(now + MINUTE_KEEP)
        assert not store.db.execute("SELECT 1 FROM minute_low").fetchall()


def test_a_minute_that_lost_samples_while_the_fill_waited_gets_no_lowest_value():
    """Which minutes still have all their samples is sure only while nothing can drop one: under the lock of the
    writer, by the clock of that moment. A fill that figured its bound once and then waited for the lock, while the
    two days moved on and the pruner ran, gave a minute that had lost its lowest sample one that stands too high."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        start = time.time()
        minute = (start - RAW_KEEP + 3000) // 60 * 60  # 50 minutes inside the two days when the fill begins
        the_stand_before(store, minute, 2.0)  # its lowest sample, and the first to go
        the_stand_before(store, minute + 30, 8.0)
        whole = (start - 7200) // 60 * 60
        the_stand_before(store, whole, 5.0)
        late = minute + 10 + RAW_KEEP  # the moment the two days end between the two samples
        asked = []

        def clock():
            """The fill looks at the clock and then waits for the writer; meanwhile it gets late and the pruner runs."""
            asked.append(1)
            if len(asked) > 1:
                return late
            store.prune(late)
            return start

        real = store_lows.time
        store_lows.time = types.SimpleNamespace(time=clock)  # the clock of the fill alone, not of the whole process
        try:
            written = store.fill_lows()
        finally:
            store_lows.time = real
        assert [t for (t,) in store.db.execute("SELECT t FROM raw ORDER BY t")] == [minute + 30, whole]
        assert low_of(store, minute) == [None], low_of(store, minute)  # not 8.0: its 2.0 is gone, nobody knows it
        assert low_of(store, whole) == [5.0] and written == 1, written  # a minute with all its samples, as before


def test_a_lowest_value_a_writer_without_one_went_on_from_is_taken_back_once_its_samples_are_gone():
    """This stand begins a minute and keeps the lowest value of its part. The stand before it takes the file over,
    goes on with that minute and writes for more than two days; it knows no lowest value. Back on this stand the
    samples of that minute are gone, and nothing can say any more that its lowest value stands too high. Only the
    neighbourhood shows it: the minute written after it has none. So the doubtful one is taken back. Its row
    stays, emptied: the minute before it keeps a neighbour with a row, and the next start takes back no more."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - RAW_KEEP - 7200) // 60 * 60  # two hours older than samples are kept
        store.add("a", minute - 60, 3.0)  # a minute this stand wrote alone
        store.add("a", minute, 5.0)  # and one it began
        store.add("b", minute, 7.0)
        store.flush()
        the_stand_before(store, minute + 2, 1.0)  # the stand before goes on with it: its true lowest is 1.0
        for i in (1, 2, 3):
            the_stand_before(store, minute + i * 60, 4.0)  # and writes minutes of its own
        store.prune()  # the samples of all of them are gone
        assert low_of(store, minute, "ab") == [5.0, 7.0]  # as the stand before left it
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            store.catch_up()
        assert low_of(store, minute, "ab") == [None, None], low_of(store, minute, "ab")  # none, not one too high
        assert low_of(store, minute - 60) == [3.0] and "lowest values of 1 minute taken back" in said.getvalue()
        with contextlib.redirect_stderr(said):
            store.catch_up()  # the next start
        assert low_of(store, minute - 60) == [3.0] and said.getvalue().count("taken back") == 1, said.getvalue()
        rows = store.db.execute("SELECT t, length(d) > 0 FROM minute_low ORDER BY t").fetchall()
        assert rows == [(minute - 60, 1), (minute, 0)], rows


def test_taking_back_goes_in_pieces_and_finds_the_neighbour_beyond_its_piece():
    """Like the fill, the taking-back shares the connection of the writer and holds its lock for one piece of the
    history at a time. The doubtful minute and the neighbour that gives it away may lie in two pieces."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - RAW_KEEP - 7200) // 60 * 60
        for i in (-2, -1, 0):
            store.add("a", minute + i * 60, 5.0)  # this stand wrote two minutes and began a third
        store.flush()
        the_stand_before(store, minute + 2, 1.0)  # the stand before goes on with the third
        the_stand_before(store, minute + 60, 4.0)  # and writes the one after it
        store.prune()
        assert store.doubt_lows(piece=1) == 1 and not store.writing.locked()  # a piece of one minute each
        rows = store.db.execute("SELECT t, length(d) > 0 FROM minute_low ORDER BY t").fetchall()
        assert rows == [(minute - 120, 1), (minute - 60, 1), (minute, 0)], rows
        assert store.doubt_lows(piece=1) == 0


def test_a_lowest_value_nobody_went_on_from_is_never_taken_back():
    """One thing only takes a lowest value back: a minute written after it that has none. Not a history this stand
    wrote alone, not a hole in it, not minutes read from old engine logs before the first lowest value, and not the
    newest minute of a history that stood still since."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        first = (time.time() - RAW_KEEP - 86400) // 60 * 60  # three days ago
        row = [[0.0, 0.0], [50.0, 60.0], [1.0, 1.0], [0.0, 0.0], [12.0, 20.0], [40.0, 40.0]]
        assert store.backfill({str(int(first) - 60 * i): row for i in (1, 2, 3)}) == 3  # old engine logs: no lowest
        written = (0, 60, 120, 3600, 3660)  # three minutes, a hole of an hour, two more, and then nothing
        for seconds in written:
            store.add("a", first + seconds, 5.0)
        store.flush()
        store.prune()
        assert store.doubt_lows() == 0
        kept = store.db.execute("SELECT t FROM minute_low WHERE length(d) > 0 ORDER BY t").fetchall()
        assert [t - first for (t,) in kept] == list(written), kept


def test_a_doubtful_lowest_value_is_taken_back_before_its_neighbour_is_made_good_and_only_outside_the_two_days():
    """At the edge of the two days the minute after a doubtful one still has its samples, and this very start gives
    it a lowest value from them. Looked at after that, the doubtful one would have a neighbour like any other.
    Inside the two days nothing is taken back, whatever the neighbourhood: there the samples say what is true, and
    a lowest value the writer kept is never raised to theirs."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        now = time.time()
        edge = store_lows.whole_from(now)  # the first minute the samples can still make good
        young = (now - 7200) // 60 * 60
        store.add("a", edge - 60, 5.0)  # this stand began the last minute before the edge
        store.add("a", young + 2, 2.0)  # and a minute two hours ago
        store.flush()
        store.add("a", young + 2.5, 7.0)  # where a node reported late: the sample row holds 7.0 now, the minute 2.0
        store.flush()
        the_stand_before(store, edge - 58, 1.0)  # the stand before went on with the first
        for minute in (edge, young + 60):
            the_stand_before(store, minute, 4.0)  # and wrote the minute after each of the two
        with contextlib.redirect_stderr(io.StringIO()):
            store.catch_up(now)
        assert (low_of(store, edge - 60), low_of(store, edge)) == ([None], [4.0])
        assert (low_of(store, young), low_of(store, young + 60)) == ([2.0], [4.0])  # not taken back and read as 7.0


def test_making_good_goes_in_pieces_and_a_failure_is_said_and_stops_nothing():
    """The writer of the history shares the connection: the fill takes it for one piece at a time."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        first = (time.time() - 7200) // 60 * 60
        for i in range(5):
            the_stand_before(store, first + i * 60, float(i))
        pieces, real = [], store.fill_piece

        def one(t0, t1):
            pieces.append((t1 - t0, store.writing.locked(), store.db.in_transaction))
            return real(t0, t1)

        store.fill_piece = one
        assert store.fill_lows(time.time(), piece=2) == 5  # the clock held still: no piece is cut by a new minute
        assert len(pieces) > 1000 and all(piece == (120.0, True, True) for piece in pieces), pieces[:3]  # two days
        assert [t for (t,) in store.db.execute("SELECT t FROM minute_low ORDER BY t")] == [
            first + i * 60 for i in range(5)
        ]
        store.db.execute("DELETE FROM minute_low")
        pieces.clear()
        assert store.fill_lows() == 5 and len(pieces) == 24, len(pieces)  # by default two hours at a time
        store.fill_piece = lambda t0, t1: (_ for _ in ()).throw(sqlite3.OperationalError("disk is full"))
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            store.catch_up()
        told = "lowest values not read from the samples: OperationalError('disk is full')"  # the error with its kind
        assert told in said.getvalue(), said.getvalue()
        assert not store.writing.locked() and not store.db.in_transaction  # the writer goes on


def test_making_good_that_fails_for_any_reason_leaves_the_connection_to_the_writer():
    """The fill shares the one writing connection. Whatever stops a piece of it, also what is no error of SQLite,
    its transaction is rolled back: left open, it made every flush of the writer fail until the restart."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        the_stand_before(store, minute, 3.0)
        store.fill_piece = lambda t0, t1: (_ for _ in ()).throw(ValueError("odd row"))
        with contextlib.suppress(ValueError):
            store.fill_lows()
        assert not store.writing.locked() and not store.db.in_transaction
        store.add("a", minute + 2, 9.0)
        store.flush()  # the writer goes on
        assert store.recent(86400)[-1] == (minute + 2, {"a": 9.0})


def test_whatever_stops_the_making_good_at_a_start_is_said_in_one_line():
    """What a start makes good in the history runs in a thread of its own, beside the writer. An error of SQLite
    was said in one line; anything else, like a row of samples that is no row of floats, ended the thread with a
    traceback. Whatever stops it is said in the one line, with the kind of error it is, and nothing is left open."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        the_stand_before(store, minute, 3.0)
        store.db.execute("UPDATE raw SET d = x'000000' WHERE t = ?", (minute,))  # three bytes are no row of floats
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            store.catch_up()  # and does not raise
        assert said.getvalue().startswith("ringtop: lowest values not read from the samples: ValueError("), (
            said.getvalue()
        )
        assert said.getvalue().count("\n") == 1 and "Traceback" not in said.getvalue(), said.getvalue()
        assert not store.writing.locked() and not store.db.in_transaction
        store.add("a", minute + 62, 9.0)
        store.flush()  # the writer goes on
        assert store.series(["a"], minute + 60, minute + 120, 10)["series"]["a"] == [9.0]
