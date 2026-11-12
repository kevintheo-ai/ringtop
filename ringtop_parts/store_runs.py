"""The records of runs on disk: one row per run under its id, written again whenever the record moves on."""

from __future__ import annotations

import json

RUNS_TABLE = "CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, began REAL, open INTEGER, d TEXT)"


class RunRows:
    """The part of the Store that keeps the records of runs. Holds no state of its own.

    A record is a flat JSON object (core/runs.py, core/run_sums.py) and is stored as that text: a field it gains
    later needs no change of the table. Beside it stand what the table is asked by: the id of the run, when it
    began and whether it is open. `began` is the moment ringtop first saw the run, by its own clock: the table is
    ordered and cleaned by it, and neither may hang on the start a command outside names. That start stays in
    the record."""

    def add_run(self, record: dict) -> None:
        """Queues the record of one run for the next flush: it takes the place of the row the run had."""
        self.queue.append(("r", record))

    def write_run(self, record: dict) -> None:
        """Writes one record as the row of its run, inside the transaction of a flush."""
        row = (
            record["id"],
            record["first_seen"],
            1 if record.get("open") else 0,
            json.dumps(record, separators=(",", ":")),
        )
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?)", row)

    def saved_runs(self, limit: int) -> list:
        """The newest rows it holds, at most `limit`, the run ringtop saw last first, each as what its text says: a
        record, as this program writes them, or whatever else stands there, and None for a text that is no JSON.
        What of it is a record is for the one who reads to tell (core/runs.py, is_record). Asked over a connection
        of its own: reading never waits for the writer."""
        db = self.reader()
        try:
            rows = db.execute("SELECT d FROM runs ORDER BY began DESC, id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            db.close()
        return [read_row(text) for (text,) in rows]


def read_row(text) -> object:
    """What the text of one row says, or None where it is no JSON this program can read: no JSON at all, or brackets
    nested deeper than the parser follows (it gives up with a RecursionError, which is no ValueError)."""
    try:
        return json.loads(text)
    except (TypeError, ValueError, RecursionError):
        return None
