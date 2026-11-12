"""The records of runs on disk: they survive a restart, a record is one row, and old ones go with the events."""

import contextlib
import io
import sqlite3
import tempfile
import time
from pathlib import Path

from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.hub import Hub
from ringtop_parts.store import MINUTE_KEEP, Store
from tests.fixtures import ring_map


def record(run_id, started, **more):
    told = {"id": run_id, "source": "command", "name": f"Job {run_id}", "started": started}
    seen = {"first_seen": (started or 0.0) + 5, "ended": None, "open": True}
    return {**told, **seen, "tokens": None, "gpu_wh": 1.25, "steps": [{"name": "a"}], **more}


def test_the_record_of_a_run_survives_a_restart_and_is_one_row_under_its_id():
    """A record is written when its run starts, again while it runs, and when it ends: always the same row, under
    the id of the run. What comes back is what was written, the newest run first, and no more than asked for."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "history.db"
        store, now = Store(path, 2.0), time.time()
        assert store.saved_runs(10) == []
        store.add_run(record(1, now - 900, open=False, ended=now - 700))
        store.add_run(record(2, now - 600))
        store.flush()
        store.add_run(record(2, now - 598, tokens=4100.0))  # the same run a minute on: its start moved, it counted
        store.add_run(record(3, None, name="Single tracks", first_seen=now - 300))  # a run whose source gives no start
        store.flush()
        again = Store(path, 2.0)
        saved = again.saved_runs(10)
        assert [(r["id"], r["open"]) for r in saved] == [(3, True), (2, True), (1, False)], saved
        assert saved[1] == record(2, now - 598, tokens=4100.0)  # as written: None stays None, a list a list
        assert again.saved_runs(2) == saved[:2]
        again.add_run(record(2, now - 598, tokens=9000.0, open=False, ended=now - 100))
        again.flush()
        assert [(r["id"], r["open"], r["tokens"]) for r in Store(path, 2.0).saved_runs(10)][1] == (2, False, 9000.0)


def test_records_of_runs_are_kept_as_long_as_the_events():
    with tempfile.TemporaryDirectory() as folder:
        store, now = Store(Path(folder) / "history.db", 2.0), time.time()
        store.add_run(record(1, now - MINUTE_KEEP - 3600, open=False, ended=now - MINUTE_KEEP))
        store.add_run(record(2, now - MINUTE_KEEP + 3600, open=False, ended=now - MINUTE_KEEP + 7200))
        store.flush()
        store.prune(now)
        assert [r["id"] for r in store.saved_runs(10)] == [2]


def test_the_table_of_runs_is_kept_and_ordered_by_the_clock_of_ringtop():
    """The column the table is ordered and cleaned by held the start a run source names. That start is the word of
    a command outside: one of four months ago had its record deleted by the next clean-up, though the run was
    seen today, and one of tomorrow stood first for good. The column holds the moment ringtop first saw the run.
    The start the source named stays in the record as it was said."""
    with tempfile.TemporaryDirectory() as folder:
        store, now = Store(Path(folder) / "history.db", 2.0), time.time()
        long_ago, tomorrow = now - MINUTE_KEEP - 30 * 86400, now + 86400
        store.add_run(record(1, tomorrow, first_seen=now - 600, open=False, ended=now - 500))
        store.add_run(record(2, long_ago, first_seen=now - 300, open=False, ended=now - 200))
        store.add_run(record(3, now - 100, first_seen=now - 95))
        store.flush()
        assert [r["id"] for r in store.saved_runs(10)] == [3, 2, 1]  # the run ringtop saw last comes first
        store.prune(now)
        saved = store.saved_runs(10)
        assert [(r["id"], r["started"]) for r in saved] == [(3, now - 100), (2, long_ago), (1, tomorrow)], saved
        store.add_run(record(4, now - 50, first_seen=now - MINUTE_KEEP - 60, open=False, ended=now - MINUTE_KEEP))
        store.flush()
        store.prune(now)  # seen more than three months ago, whatever start its source names now
        assert [r["id"] for r in store.saved_runs(10)] == [3, 2, 1]


def test_a_history_file_from_before_gets_its_table_of_runs():
    """A history written by the stand before has no table of runs: the first start on it makes one, and leaves
    everything else as it was."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "history.db"
        old = Store(path, 2.0)
        old.add_event({"t": 5.0, "node": None, "kind": "run", "text": "Started: Job 1", "level": "info"})
        old.flush()
        old.db.execute("DROP TABLE runs")
        old.db.close()
        again = Store(path, 2.0)
        assert again.saved_runs(10) == [] and again.saved_events(10)[0]["text"] == "Started: Job 1"


def test_a_row_nested_too_deep_to_read_is_no_record_and_stops_no_start():
    """What a row says is read by the JSON parser of the standard library. On brackets nested thousands deep it
    gives up with a RecursionError, which is no ValueError: it was not caught, reading the table failed, and the
    hub did not start. Such a text is like any other that is no JSON this program reads: it says nothing, the
    start passes it over and says so in its one line, and the row stays in the file."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "history.db"
        store, now = Store(path, 2.0), time.time()
        store.add_run(record(1, now - 600))
        store.flush()
        deep = ["[" * 100_000 + "]" * 100_000, '{"a":' * 100_000 + "1" + "}" * 100_000]
        db = sqlite3.connect(path)
        for k, text in enumerate(deep):  # each newer than the record, and marked as open
            db.execute("INSERT INTO runs VALUES (?,?,?,?)", (2 + k, now + k, 1, text))
        db.commit()
        db.close()
        saved = Store(path, 2.0).saved_runs(10)
        assert saved == [None, None, record(1, now - 600)], [type(row) for row in saved]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hub = Hub(parse_cluster(ring_map()), 2.0, store=Store(path, 2.0))  # a start reads the table
        # three rows: the two, and the short record of this file, which lacks the sums a record of the hub has
        assert hub.runs_view() == {"open": None, "runs": []} and "3 rows are no records" in out.getvalue(), (
            out.getvalue()
        )
        db = sqlite3.connect(path)
        kept = [text for (text,) in db.execute("SELECT d FROM runs WHERE id > 1 ORDER BY id")]
        db.close()
        assert kept == deep  # as they were
