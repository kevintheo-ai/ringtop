"""History on disk: it survives a restart, keeps average and peak, and never loses what was measured."""

import contextlib
import io
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.hub import Hub
from ringtop_parts.store import Store
from tests.fixtures import NoStderr, ring_map


def test_history_survives_a_restart_and_answers_long_ranges():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "h" / "history.db"
        store = Store(path, 2.0)
        start = time.time() - 600
        for i in range(120):
            store.add("spark-1.w", start + i * 2, 20.0 + i % 3)
            store.add("engine.tok_s", start + i * 2, 100.0)
        store.add_event({"t": start, "node": "spark-1", "kind": "link", "text": "Errors", "level": "warn"})
        store.add_log({"seq": 7, "t": start, "node": "spark-1", "text": "engine line"})
        store.flush()
        again = Store(path, 2.0)
        points = again.recent(3600)
        assert len(points) == 120 and points[0][1]["spark-1.w"] == 20.0
        hub = Hub(parse_cluster(ring_map()), 2.0, store=again)
        assert len(hub.history["engine.tok_s"]) == 120 and hub.log_seq == 7
        assert hub.events[-1]["text"] == "Errors" and hub.logs[-1]["text"] == "engine line"
        fine = again.series(["spark-1.w", "nothing"], start - 1, start + 300, 50)
        assert fine["tier"] == "raw" and len(fine["t"]) <= 51 and fine["series"]["nothing"] == [None] * len(fine["t"])
        wide = again.series(["engine.tok_s"], time.time() - 86400, time.time(), 200)
        assert wide["tier"] == "minute" and all(v == 100.0 for v in wide["series"]["engine.tok_s"] if v is not None)
        assert again.size()["raw_rows"] == 120


def test_one_minute_rows_keep_average_and_peak_when_written_in_pieces():
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        for i, value in enumerate((10.0, 30.0)):
            store.add("a", minute + i * 2, value)
        store.flush()
        store.add("a", minute + 4, 80.0)
        store.flush()
        answer = store.series(["a"], minute - 3600 * 3, minute + 60, 400)
        assert answer["tier"] == "minute" and answer["series"]["a"] == [40.0] and answer["peak"]["a"] == [80.0]


def test_old_minutes_from_engine_logs_never_replace_measured_ones():
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        store.add("engine.tok_s", minute + 2, 50.0)
        store.flush()
        row = [[0.0, 0.0], [999.0, 999.0], [1.0, 1.0], [0.0, 0.0], [12.0, 20.0], [40.0, 40.0]]
        assert store.backfill({str(int(minute)): row, str(int(minute) - 60): row}) == 1
        assert store.backfilled()
        answer = store.series(["engine.tok_s", "engine.kv"], minute - 7200, minute + 60, 400)
        assert answer["series"]["engine.tok_s"] == [999.0, 50.0] and answer["series"]["engine.kv"][0] == 0.12


def test_asking_whether_old_logs_were_read_leaves_the_connection_of_the_writers_alone():
    """At the start ringtop asks whether the old logs were already read, while the thread that makes good the lowest
    values is at work on the connection the writers share. The question went over that connection too, outside their
    lock: on a Python whose SQLite does not serialize a connection by itself (the python3 of macOS) two threads then
    used one connection at once. It reads over a connection of its own, as every other question to the history does."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)

        class InUse:
            """The connection of the writers while one of them is at work: nobody else may touch it."""

            def execute(self, *args):
                raise AssertionError("asked over the connection of the writers, outside their lock")

        writers, store.db = store.db, InUse()
        try:
            assert store.backfilled() is False
        finally:
            store.db = writers
        store.backfill({})
        assert store.backfilled() is True


def test_a_late_node_fills_its_slots_without_erasing_the_others():
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        t = (time.time() - 100) // 2 * 2
        store.add("a", t, 1.0)
        store.flush()
        store.add("b", t, 2.0)
        store.flush()
        assert store.recent(3600)[0][1] == {"a": 1.0, "b": 2.0}


def test_a_failed_write_forgets_the_new_keys():
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        store.add("new", time.time() - 100, 1.0)
        original = store.merge_minute
        store.merge_minute = lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("full"))
        with contextlib.suppress(sqlite3.Error):
            store.flush()
        store.merge_minute = original
        assert "new" not in store.ids


def test_a_write_that_fails_for_any_reason_leaves_the_connection_free():
    """Whatever stops a write, nothing of it stays and the one writing connection is free again: the next flush
    writes. A failure that was no error of SQLite left the transaction open, and every flush after it failed until
    the restart."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        t = (time.time() - 100) // 2 * 2
        store.add("new", t, 1.0)
        original = store.merge_minute
        store.merge_minute = lambda *a: (_ for _ in ()).throw(ValueError("odd row"))
        with contextlib.suppress(ValueError):
            store.flush()
        store.merge_minute = original
        assert not store.db.in_transaction and "new" not in store.ids and store.recent(3600) == []
        store.add("new", t + 2, 2.0)
        store.flush()
        assert store.recent(3600) == [(t + 2, {"new": 2.0})]


def test_a_write_the_full_database_rolled_back_by_itself_still_forgets_its_keys():
    """When the database is full, SQLite rolls the transaction back by itself, and a ROLLBACK after that is an error
    of its own. The write has to forget the ids it handed out all the same (kept, they name rows that are not there,
    and the next new trace gets an id one of them holds), and the error to hand on is the full database."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        t = (time.time() - 100) // 2 * 2
        store.add("first", t, 1.0)
        store.flush()
        pages = store.db.execute("PRAGMA page_count").fetchone()[0]
        store.db.execute(f"PRAGMA max_page_count={pages}")  # not one page more: this is what a full disk looks like
        for i in range(400):
            store.add(f"new{i}", t + 2, float(i))
        said = None
        try:
            store.flush()
        except sqlite3.Error as problem:
            said = str(problem)
        assert said == "database or disk is full", said
        assert not store.db.in_transaction and sorted(store.ids) == ["first"], sorted(store.ids)[:4]
        store.db.execute("PRAGMA max_page_count=1000000")  # room again
        store.add("later", t + 4, 7.0)
        store.flush()
        assert store.ids["later"] == 2 and store.recent(3600)[-1] == (t + 4, {"later": 7.0}), store.ids


def test_a_failed_write_does_not_count_its_samples_into_a_minute():
    """A minute arrives in pieces and is averaged by how many samples each piece brings. A write that fails leaves
    the minute as it stood: the samples of its lost batch stayed counted, and the next piece weighed too little."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        store.add("a", minute, 10.0)
        store.flush()  # the minute holds one sample
        for i in range(1, 6):
            store.add("a", minute + i * 2, 100.0)  # five more that never reach the disk:
        store.add("a", minute + 60, 1.0)  # their batch fails at the minute after them
        real = store.merge_low

        def full(t, row):
            if t == minute + 60:
                raise sqlite3.OperationalError("disk is full")
            return real(t, row)

        store.merge_low = full
        with contextlib.suppress(sqlite3.Error):
            store.flush()
        store.merge_low = real
        store.add("a", minute + 12, 20.0)
        store.flush()
        answer = store.series(["a"], minute - 3600 * 3, minute + 59, 400)
        assert answer["series"]["a"] == [15.0], answer["series"]  # one sample of 10 and one of 20, not six and one


def test_after_a_restart_the_part_of_a_minute_on_disk_weighs_as_many_samples_as_it_holds():
    """A minute arrives in pieces and is averaged by how many samples each piece brings. A restart forgot how many
    the part on disk held and counted it as one: twenty samples of 10 and, after the restart, one of 100 gave a mean
    of 55. The samples of the minute are still in the file and say how many they are, for every trace of the minute,
    also one whose next sample comes a flush later. A part no sample stands behind counts as one, as before."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "h.db"
        store = Store(path, 2.0)
        minute = (time.time() - 7200) // 60 * 60
        for i in range(20):
            store.add("a", minute + i * 2, 10.0)
        for i, value in enumerate((30.0, 50.0)):
            store.add("b", minute + i * 2, value)
        store.flush()
        again = Store(path, 2.0)  # the restart
        again.add("a", minute + 40, 100.0)
        again.flush()
        again.add("b", minute + 42, 100.0)  # a trace that was not in the first piece after the restart
        again.flush()
        span = (minute - 3600 * 3, minute + 59)
        answer = again.series(["a", "b"], *span, 400)
        assert answer["series"]["a"] == [14.286], answer["series"]  # (20 * 10 + 100) / 21, not (10 + 100) / 2
        assert answer["series"]["b"] == [60.0], answer["series"]  # (30 + 50 + 100) / 3, not (40 + 100) / 2
        assert answer["peak"]["a"] == [100.0] and answer["peak"]["b"] == [100.0], answer["peak"]
        logs = [[0.0, 0.0], [999.0, 999.0], [1.0, 1.0], [0.0, 0.0], [12.0, 20.0], [40.0, 40.0]]
        assert again.backfill({str(int(minute) + 60): logs}) == 1  # a minute read from old engine logs: no samples
        again.add("engine.tok_s", minute + 62, 50.0)
        again.flush()
        later = again.series(["engine.tok_s"], minute - 3600 * 3, minute + 119, 400)
        assert later["tier"] == "minute" and later["series"]["engine.tok_s"][-1] == 524.5, later  # (999 + 50) / 2


def test_the_writer_goes_on_after_a_write_that_failed_for_any_reason():
    """The loop that writes the history says a write that failed, whatever stopped it, and tries the next one. An
    exception that was no error of SQLite ended the loop: nothing more was written until the restart, and the queue
    grew for as long as ringtop ran."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        t = (time.time() - 100) // 2 * 2
        store.add("a", t, 1.0)
        merge, naps = store.merge_minute, []
        store.merge_minute = lambda *a: (_ for _ in ()).throw(ValueError("odd row"))

        def nap(seconds):
            """The loop sleeps before every flush: before the second one the fault is gone, the third ends the check."""
            naps.append(seconds)
            if len(naps) == 2:
                store.merge_minute = merge
                store.add("a", t + 2, 2.0)
            if len(naps) == 3:
                raise EOFError("enough")

        module = sys.modules[Store.__module__]
        clock, said = module.time, io.StringIO()
        module.time = types.SimpleNamespace(sleep=nap, time=clock.time)
        try:
            with contextlib.redirect_stderr(said), contextlib.suppress(EOFError):
                store.run()
        finally:
            module.time = clock
        assert naps == [4, 4, 4] and "history not saved: ValueError('odd row')" in said.getvalue(), said.getvalue()
        assert store.recent(3600) == [(t + 2, {"a": 2.0})] and not store.queue  # the first batch is lost, no more


def test_the_writer_goes_on_after_a_failed_write_it_could_not_even_say():
    """A full disk fails the write of the history and, under the log of the service, the line that says so. Saying it
    threw, out of the net that keeps the loop: the writer was gone, and nothing was written any more after the disk
    had room again, until the restart. The failure then goes unsaid, and the next write is tried."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        t = (time.time() - 100) // 2 * 2
        store.add("a", t, 1.0)
        merge, naps = store.merge_minute, []
        store.merge_minute = lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("database or disk is full"))

        def nap(seconds):
            """Before the second flush the disk has room again, the third nap ends the check."""
            naps.append(seconds)
            if len(naps) == 2:
                store.merge_minute = merge
                store.add("a", t + 2, 2.0)
            if len(naps) == 3:
                raise EOFError("enough")

        module = sys.modules[Store.__module__]
        clock = module.time
        module.time = types.SimpleNamespace(sleep=nap, time=clock.time)
        try:
            with contextlib.redirect_stderr(NoStderr()), contextlib.suppress(EOFError):
                store.run()
        finally:
            module.time = clock
        assert naps == [4, 4, 4] and store.recent(3600) == [(t + 2, {"a": 2.0})], (naps, store.recent(3600))


def test_old_engine_logs_that_cannot_be_read_leave_the_connection_free():
    """The rows of old engine logs come from outside. One that is no pair of average and peak stops the reading, and
    nothing of it stays: neither a row, nor the mark that the logs were read, nor an open transaction."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = int((time.time() - 7200) // 60 * 60)
        row = [[0.0, 0.0], [50.0, 60.0], [1.0, 1.0], [0.0, 0.0], [12.0, 20.0], [40.0, 40.0]]
        with contextlib.suppress(ValueError):
            store.backfill({str(minute): row, str(minute + 60): [[50.0]]})
        assert not store.db.in_transaction and not store.writing.locked()
        assert not store.backfilled() and store.size()["minute_rows"] == 0
        store.add("a", minute + 2.0, 9.0)
        store.flush()  # the writer goes on
        assert store.recent(86400) == [(minute + 2.0, {"a": 9.0})]


def test_one_minute_rows_keep_the_lowest_value_when_written_in_pieces():
    """A band from the lowest to the highest value needs the lowest of every minute, and only who asks gets it."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        for i, value in enumerate((10.0, 30.0)):
            store.add("a", minute + i * 2, value)
        store.flush()
        store.add("a", minute + 4, 5.0)
        store.add("a", minute + 60, 7.0)  # the minute after it, in the same column
        store.flush()
        span = (minute - 3600 * 3, minute + 120)
        band = store.series(["a", "nothing"], *span, 10, band=True)  # ten columns: both minutes stand in one
        assert band["tier"] == "minute" and band["low"]["a"] == [5.0] and band["peak"]["a"] == [30.0], band
        assert band["n"]["a"] == [2] and band["series"]["a"] == [11.0], band  # two minutes: the mean of their means
        assert band["low"]["nothing"] == [None] and band["n"]["nothing"] == [0], band
        plain = store.series(["a"], *span, 10)
        assert "low" not in plain and "n" not in plain  # the time machine asks for 400 keys: no more than it draws
        assert plain["width"] == band["width"] == 1092.0, plain["width"]  # seconds a column spans
        # the stand before this one writes minute rows of two columns into the same file: the table keeps its shape
        assert [column[1] for column in store.db.execute("PRAGMA table_info(minute)")] == ["t", "d"]


def test_a_band_of_single_samples_is_their_lowest_and_highest_with_their_count():
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        start = (time.time() - 600) // 4 * 4
        for i, value in enumerate((20.0, 22.0, 21.0, 25.0)):
            store.add("a", start + i * 2, value)
        store.flush()
        band = store.series(["a"], start, start + 40, 10, band=True)  # columns of 4 s: two samples each
        assert band["tier"] == "raw" and band["width"] == 4.0, band
        assert band["series"]["a"] == [21.0, 23.0] and band["n"]["a"] == [2, 2], band
        assert band["low"]["a"] == [20.0, 21.0] and band["peak"]["a"] == [22.0, 25.0], band


def test_a_band_never_mixes_samples_and_minutes():
    """A short stretch whose samples begin later than its minutes was answered from both. With a band the count of a
    column then stood for samples here and for minutes there, and a mean over the stretch weighed the two alike.
    Asked for a band, such a stretch comes from the minutes alone. Without one the answer is what it always was."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        start = (time.time() - 3000) // 60 * 60
        for i, value in enumerate((10.0, 30.0)):  # a minute whose samples are gone
            store.add("a", start + i * 2, value)
        for i, value in enumerate((4.0, 6.0, 8.0)):  # and one, twenty minutes later, that still has them
            store.add("a", start + 1200 + i * 2, value)
        store.flush()
        store.db.execute("DELETE FROM raw WHERE t < ?", (start + 60,))
        span = (start - 300, start + 1500)  # half an hour in columns of a minute, inside the two days of samples
        plain = store.series(["a"], *span, 30)
        assert plain["tier"] == "mixed" and plain["t"] == [start, start + 1200], plain
        assert plain["series"]["a"] == [20.0, 6.0] and plain["peak"]["a"] == [30.0, 8.0], plain
        band = store.series(["a"], *span, 30, band=True)
        assert band["tier"] == "minute" and band["n"]["a"] == [1, 1], band  # one minute each, not one and three
        assert band["t"] == plain["t"] and band["series"] == plain["series"] and band["peak"] == plain["peak"], band
        assert band["low"]["a"] == [10.0, 4.0], band
        covered = store.series(["a"], start + 1100, start + 1500, 30, band=True)  # no minute before its first sample
        assert covered["tier"] == "raw" and covered["n"]["a"] == [3] and covered["low"]["a"] == [4.0], covered
        early = (start - 300, start + 600)  # a stretch without any sample: its minute answers, with a band or without
        for asked in (False, True):
            alone = store.series(["a"], *early, 30, band=asked)
            assert alone["tier"] == "minute" and alone["series"]["a"] == [20.0], (asked, alone)  # no sample, none said


def test_a_minute_without_its_lowest_value_leaves_the_column_without_one():
    """One minute of a column kept no lowest value: the lowest of the others is not the lowest of the column."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        store.add("a", minute, 10.0)
        store.add("a", minute + 60, 4.0)
        store.flush()
        store.db.execute("DELETE FROM minute_low WHERE t=?", (minute,))  # as a writer of before left it
        span = (minute - 3600 * 3, minute + 120)
        band = store.series(["a"], *span, 10, band=True)  # both minutes in one column
        assert band["low"]["a"] == [None] and band["peak"]["a"] == [10.0] and band["n"]["a"] == [2], band


def test_a_band_reads_the_minutes_and_their_lowest_values_from_one_stand():
    """A band is read in two steps: the one-minute rows, then their lowest values. The writer came between the two
    with a lower sample for the minute that is still running: the answer held the mean and the highest value of
    before with the lowest value of after, a stand the file never had. Both are read from one stand of the file."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        store.add("a", minute, 10.0)
        store.flush()
        module = sys.modules[Store.__module__]
        real = module.read_lows

        def late(db, t0, t1):
            """The lowest values, read after the writer has put a lower sample into the same minute."""
            store.add("a", minute + 2, 0.0)
            store.flush()
            return real(db, t0, t1)

        span = (minute - 3600 * 3, minute + 60)
        module.read_lows = late
        try:
            band = store.series(["a"], *span, 400, band=True)
        finally:
            module.read_lows = real
        assert band["tier"] == "minute" and band["series"]["a"] == [10.0] and band["peak"]["a"] == [10.0], band
        assert band["low"]["a"] == [10.0], band  # of the stand its mean is of, not of the one after it
        after = store.series(["a"], *span, 400, band=True)  # and the next answer holds all of the later stand
        assert after["series"]["a"] == [5.0] and after["low"]["a"] == [0.0] and after["peak"]["a"] == [10.0], after


def test_a_minute_that_ends_where_the_samples_begin_is_part_of_the_stretch():
    """A one-minute row stands for the sixty seconds from its time on. Where the samples of a stretch begin exactly
    on the minute after it, it lies wholly before them and still knows something. It was left out: without a band
    the answer had a hole there, and with one it came from the samples alone. A minute its own samples begin in is
    no older row, as before: they say what it says."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        start = (time.time() - 3000) // 60 * 60
        for i, value in enumerate((10.0, 30.0)):  # a minute whose samples are gone
            store.add("a", start + i * 2, value)
        for i, value in enumerate((4.0, 6.0, 8.0)):  # and the minute right after it, which still has them
            store.add("a", start + 60 + i * 2, value)
        store.flush()
        store.db.execute("DELETE FROM raw WHERE t < ?", (start + 60,))
        span = (start - 300, start + 300)  # ten minutes in columns of a minute, inside the two days of samples
        plain = store.series(["a"], *span, 10)
        assert plain["tier"] == "mixed" and plain["t"] == [start, start + 60], plain
        assert plain["series"]["a"] == [20.0, 6.0] and plain["peak"]["a"] == [30.0, 8.0], plain
        band = store.series(["a"], *span, 10, band=True)
        assert band["tier"] == "minute" and band["t"] == [start, start + 60] and band["n"]["a"] == [1, 1], band
        assert band["series"]["a"] == [20.0, 6.0] and band["low"]["a"] == [10.0, 4.0], band
        other = Store(Path(folder) / "other.db", 2.0)  # here the samples that are left begin inside their own minute
        for seconds, value in ((0, 10.0), (10, 30.0), (40, 4.0), (50, 6.0)):  # four samples of one minute
            other.add("a", start + seconds, value)
        other.flush()
        other.db.execute("DELETE FROM raw WHERE t < ?", (start + 40,))
        inside = other.series(["a"], *span, 10, band=True)
        assert inside["tier"] == "raw" and inside["t"] == [start + 40] and inside["n"]["a"] == [2], inside
        assert other.series(["a"], *span, 10)["tier"] == "raw"


def test_a_stretch_without_samples_is_answered_by_its_one_minute_rows():
    """A short stretch of the last two days is answered by its samples and by the one-minute rows before the first
    of them. Without any sample the end of the stretch stood in for that first one: a minute that begins in its
    last sixty seconds, and so reaches past its end, was left out, with a band and without one, and the minutes
    before it were said to come "mixed" with samples that are not there. Such a stretch is answered by the
    one-minute rows that begin in it, like a long one. One nobody recorded at all says what it always said."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        start = (time.time() - 3000) // 60 * 60
        for i, value in enumerate((10.0, 30.0)):
            store.add("a", start + i * 2, value)
        store.flush()
        store.db.execute("DELETE FROM raw")  # the samples are gone, the minute still knows
        short = (start - 30, start + 30)  # one minute long: the one-minute row begins in its middle
        for band in (False, True):
            answer = store.series(["a"], *short, 10, band=band)
            assert answer["tier"] == "minute" and answer["t"] == [start], (band, answer)
            assert answer["series"]["a"] == [20.0] and answer["peak"]["a"] == [30.0], (band, answer)
        banded = store.series(["a"], *short, 10, band=True)
        assert banded["low"]["a"] == [10.0] and banded["n"]["a"] == [1], banded
        empty = store.series(["a"], start - 600, start - 300, 10, band=True)  # nothing was recorded here
        assert empty["tier"] == "raw" and empty["t"] == [] and empty["series"]["a"] == [], empty


class FailingDisk:
    """The connection of a store on a disk that begins to fail: everything goes through to the real connection,
    except that the keys cannot be read once `broken` is set."""

    def __init__(self, db: sqlite3.Connection):
        """Stands in front of the real connection, whole for now."""
        self.db, self.broken = db, False

    def execute(self, sql: str, *more):
        """Runs a statement on the real connection, unless it reads the keys from a disk that is broken."""
        if self.broken and sql.startswith("SELECT name, id FROM keys"):
            raise sqlite3.OperationalError("disk I/O error")
        return self.db.execute(sql, *more)

    def __getattr__(self, name: str):
        """Everything else is the real connection's."""
        return getattr(self.db, name)


def test_a_failed_write_is_undone_even_where_the_keys_cannot_be_read_again():
    """After a write that failed, the store reads its keys from the file again. On a disk that fails, that reading
    fails too. Its error went to the caller in place of the one that stopped the write, the minutes went on counting
    the samples of the lost batch, and the ids handed out in it stayed. The minutes are put back first, the ids are
    those of before the write, and the error handed on is the one that stopped it."""
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "h.db", 2.0)
        minute = (time.time() - 7200) // 60 * 60
        store.add("a", minute, 10.0)
        store.flush()  # the minute holds one sample of one trace
        counted = {t: dict(count) for t, count in store.minute_counts.items()}
        store.db = disk = FailingDisk(store.db)
        real = store.merge_low

        def full(t, row):
            """The batch fails at the minute after, and from then on the disk gives nothing back."""
            if t == minute + 60:
                disk.broken = True
                raise sqlite3.OperationalError("disk is full")
            return real(t, row)

        store.merge_low = full
        for i in range(1, 6):
            store.add("a", minute + i * 2, 100.0)
        store.add("new", minute + 2, 1.0)
        store.add("a", minute + 60, 1.0)
        said = None
        try:
            store.flush()
        except sqlite3.Error as problem:
            said = str(problem)
        store.merge_low = real
        assert said == "disk is full", said
        assert counted and store.minute_counts == counted, (counted, store.minute_counts)
        assert sorted(store.ids) == ["a"] and not store.db.in_transaction, sorted(store.ids)
