"""The history on disk: every sample for two days, one-minute rows for three months, events, log lines and the
records of runs."""

from __future__ import annotations

import array
import collections
import contextlib
import math
import sqlite3
import sys
import threading
import time
from pathlib import Path

from ringtop_parts.store_lows import RAW_KEEP, Lows, lower, read_lows, roll_back, slot
from ringtop_parts.store_runs import RUNS_TABLE, RunRows

MINUTE_KEEP = 90 * 86400  # one-minute averages, peaks and lowest values, on disk
RAW_SPAN = 2 * 3600  # asked for more than this, the one-minute table answers


def stretch_rows(db: sqlite3.Connection, t0: float, t1: float, band: bool) -> tuple[str, list, list]:
    """The rows that answer a stretch of the past: the tier they are, the rows, and one-minute rows from before them.

    A short stretch of the last two days is answered by every sample ('raw'); where one-minute rows lie before its
    first sample, they still know something and come along ('mixed'). Anything else is answered by the one-minute
    rows ('minute'), and so is a short stretch that holds no sample but one-minute rows. A band says what stands
    behind a column, samples or minutes: a stretch that would be mixed then comes from the minutes alone."""

    def read(table: str) -> list:
        return db.execute(f"SELECT t, d FROM {table} WHERE t >= ? AND t <= ? ORDER BY t", (t0, t1)).fetchall()  # noqa: S608

    if not (t1 - t0 <= RAW_SPAN and t0 >= time.time() - RAW_KEEP):
        return "minute", read("minute"), []
    rows = read("raw")
    if not rows:  # no sample to lie before: every one-minute row that begins in it answers, also one reaching past it
        minutes = read("minute")
        return ("minute" if minutes else "raw"), minutes, []
    # A one-minute row stands for the 60 s from its time on: it lies wholly before the first sample up to 60 s before it.
    older = db.execute("SELECT t, d FROM minute WHERE t >= ? AND t <= ? ORDER BY t", (t0, rows[0][0] - 60)).fetchall()
    if older and band:
        return "minute", read("minute"), []
    return ("mixed" if older else "raw"), rows, older


class Store(Lows, RunRows):
    """History on disk: the curves are already there when the page opens, and survive a restart.

    Two rolling tables of fixed-width rows: every sample for two days, one-minute averages and peaks for three months.
    The lowest value of every minute stands in a table beside them (store_lows.py), the records of runs in one of
    their own (store_runs.py).
    """

    def __init__(self, path: Path, interval: float):
        """Opens the history file, makes its tables on first use and learns the traces it already holds."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.interval = path, interval
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS keys(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS raw(t REAL PRIMARY KEY, d BLOB) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS minute(t REAL PRIMARY KEY, d BLOB) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS minute_low(t REAL PRIMARY KEY, d BLOB) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS events(t REAL, node TEXT, kind TEXT, text TEXT, level TEXT);
            CREATE INDEX IF NOT EXISTS events_t ON events(t);
            CREATE TABLE IF NOT EXISTS logs(seq INTEGER PRIMARY KEY, t REAL, node TEXT, text TEXT);
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
            """
            + RUNS_TABLE
        )
        self.ids: dict[str, int] = dict(self.db.execute("SELECT name, id FROM keys"))
        self.queue: collections.deque = collections.deque()
        self.flushed_rows = 0
        self.minute_counts: dict[float, dict[int, int]] = {}  # samples each minute still being written holds, by key
        self.writing = threading.Lock()  # one connection, two writers (the flusher and the once-only backfill)

    def add(self, key: str, t: float, value: float) -> None:
        """Queues one value of a trace for the next flush."""
        self.queue.append(("p", key, t, value))

    def add_event(self, event: dict) -> None:
        """Queues one event for the next flush."""
        self.queue.append(("e", event))

    def add_log(self, line: dict) -> None:
        """Queues one log line for the next flush."""
        self.queue.append(("l", line))

    def key_id(self, name: str) -> int:
        """The number a trace is stored under. A trace seen for the first time gets a new one."""
        if name not in self.ids:
            self.ids[name] = (
                self.db.execute("INSERT OR IGNORE INTO keys(name) VALUES (?)", (name,)).lastrowid
                or next(self.db.execute("SELECT id FROM keys WHERE name=?", (name,)))[0]
            )
        return self.ids[name]

    def row(self, values: dict[int, float], width: int = 1) -> bytes:
        """A row of 32-bit floats, one slot per key (or `width` per key); a key without a value is NaN."""
        size = (max(values) + 1) * width if values else 0
        slots = array.array("f", [math.nan] * size)
        for key, value in values.items():
            for i, part in enumerate(value if width > 1 else [value]):
                slots[key * width + i] = part
        return slots.tobytes()

    def flush(self, now: float | None = None) -> None:
        """Writes every bucket that can no longer change, leaves the current one to fill up."""
        now = time.time() if now is None else now
        items = self._pending = getattr(self, "_pending", [])
        while self.queue:
            items.append(self.queue.popleft())
        raw: dict[float, dict] = {}
        minutes: dict[float, dict] = {}
        keep = []
        events, logs, runs = [], [], []
        step = self.interval
        for item in items:
            if item[0] in "elr":  # an event, a log line, the record of a run: written with this flush as they are
                {"e": events, "l": logs, "r": runs}[item[0]].append(item[1])
                continue
            _, key, t, value = item
            bucket = t // step * step
            if bucket + step > now - 1:
                keep.append(item)  # the nodes report a moment apart: this row is still being filled
                continue
            raw.setdefault(bucket, {})[key] = value
        self._pending = keep
        with self.writing:
            self.write(raw, minutes, events, logs, runs)
        self.flushed_rows += len(raw)

    def write(self, raw: dict, minutes: dict, events: list, logs: list, runs=()) -> None:
        """Writes one flush in a single transaction: every sample, its minute, events, log lines and the records of
        runs. When it fails, for whatever reason, nothing of it stays, and the error that stopped it goes on to
        the caller."""
        counted = {t: dict(count) for t, count in self.minute_counts.items()}
        known = dict(self.ids)
        self.db.execute("BEGIN")
        try:
            for t, row in raw.items():
                self.merge_raw(t, row)
                minute = minutes.setdefault(t // 60 * 60, {})
                for k, v in row.items():
                    total = minute.setdefault(k, [0.0, 0, v, v])
                    total[0] += v
                    total[1] += 1
                    total[2] = max(total[2], v)
                    total[3] = min(total[3], v)
            for e in events:
                self.db.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?)", (e["t"], e["node"], e["kind"], e["text"], e["level"])
                )
            for line in logs:
                self.db.execute(
                    "INSERT OR REPLACE INTO logs VALUES (?,?,?,?)", (line["seq"], line["t"], line["node"], line["text"])
                )
            for record in runs:
                self.write_run(record)
            for t, row in minutes.items():
                self.merge_low(t, row)  # first: it has to see whether the minute stood there before this piece
                self.merge_minute(t, row)
            self.db.execute("COMMIT")
        except BaseException:  # not only an error of SQLite: left open, the transaction fails every write after it
            roll_back(self.db)
            self.minute_counts = counted  # the minutes hold the samples they held before, no more
            self.ids = known  # and the ids handed out inside the transaction are gone with it
            # The file knows the ids best. Where it cannot be read either, those of before the write stay, and the
            # error to hand on is still the one that stopped the write.
            with contextlib.suppress(sqlite3.Error):
                self.ids = dict(self.db.execute("SELECT name, id FROM keys"))
            raise

    def merge_raw(self, t: float, row: dict[str, float]) -> None:
        """A node reporting late fills in its own slots and leaves the others' values alone."""
        values = {self.key_id(k): v for k, v in row.items()}
        found = next(self.db.execute("SELECT d FROM raw WHERE t=?", (t,)), None)
        if found:
            slots = array.array("f")
            slots.frombytes(found[0])
            values = {i: v for i, v in enumerate(slots) if v == v} | values
        self.db.execute("INSERT OR REPLACE INTO raw VALUES (?,?)", (t, self.row(values)))

    def merge_minute(self, t: float, row: dict[str, list]) -> None:
        """A minute arrives in pieces (one flush after another): add to what is there, as count-weighted average."""
        counts = self.minute_counts
        count = counts.get(t)
        old = {}
        found = next(self.db.execute("SELECT d FROM minute WHERE t=?", (t,)), None)
        if found:
            slots = array.array("f")
            slots.frombytes(found[0])
            old = {i // 2: (slots[i], slots[i + 1]) for i in range(0, len(slots) - 1, 2) if slots[i] == slots[i]}
        if count is None or t not in counts:
            # Memory knows nothing of this minute: it is new, or a restart forgot it. What stands on disk then weighs
            # as many samples as the file holds of it beside those of this piece.
            held = self.samples_of(t) if old else {}
            piece = {self.key_id(name): cell[1] for name, cell in row.items()}
            count = {key: max(held.get(key, 0) - piece.get(key, 0), 0) or 1 for key in old}
        merged = {}
        for name, (total, n, peak, _) in row.items():
            key = self.key_id(name)
            earlier = count.get(key, 1 if key in old else 0)  # a part no sample stands behind counts as one
            if key in old and earlier:
                avg = (old[key][0] * earlier + total) / (earlier + n)
                peak = max(old[key][1], peak)
            else:
                avg = total / n
            merged[key] = (avg, peak)
            count[key] = earlier + n
        for key, value in old.items():
            merged.setdefault(key, value)
        counts[t] = count
        for stale in [m for m in counts if m < t - 300]:
            counts.pop(stale)
        self.db.execute("INSERT OR REPLACE INTO minute VALUES (?,?)", (t, self.row(merged, 2)))

    def samples_of(self, minute: float) -> dict[int, int]:
        """How many samples of each key the file holds for one minute, those of the write under way included."""
        held: collections.Counter = collections.Counter()
        for (data,) in self.db.execute("SELECT d FROM raw WHERE t >= ? AND t < ?", (minute, minute + 60)):
            slots = array.array("f")
            slots.frombytes(data)
            held.update(key for key, value in enumerate(slots) if value == value)
        return held

    def prune(self, now: float | None = None) -> None:
        """Drops what is older than the tables keep: samples after two days, minutes, events and the records of runs
        after three months, all but the newest 20,000 log lines."""
        now = time.time() if now is None else now
        with self.writing:
            self.db.execute("DELETE FROM raw WHERE t < ?", (now - RAW_KEEP,))
            self.db.execute("DELETE FROM minute WHERE t < ?", (now - MINUTE_KEEP,))
            self.db.execute("DELETE FROM minute_low WHERE t < ?", (now - MINUTE_KEEP,))
            self.db.execute("DELETE FROM events WHERE t < ?", (now - MINUTE_KEEP,))
            self.db.execute("DELETE FROM runs WHERE began < ?", (now - MINUTE_KEEP,))
            self.db.execute("DELETE FROM logs WHERE seq <= (SELECT MAX(seq) FROM logs) - 20000")

    def run(self) -> None:
        """Flushes every 4 s and prunes every 10 minutes, for as long as ringtop runs. A write that fails, whatever
        stopped it, is said on stderr; it does not stop the live view, and the next write is tried. Where stderr
        cannot be written either (the full disk holds the log too), the failure goes unsaid."""
        last_prune = 0.0
        while True:
            time.sleep(4)
            try:
                self.flush()
                if time.time() - last_prune > 600:
                    last_prune = time.time()
                    self.prune()
            except Exception as problem:  # a full disk must not stop the live view, and nothing may end this loop
                with contextlib.suppress(OSError, ValueError):
                    print(f"ringtop: history not saved: {problem!r}", file=sys.stderr, flush=True)

    def reader(self) -> sqlite3.Connection:
        """A read-only connection of its own, so that reading never waits for the writer."""
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)

    def recent(self, seconds: float) -> list[tuple[float, dict[str, float]]]:
        """Every sample of the last seconds given, oldest first, each as its time and the values by trace."""
        names = {i: n for n, i in self.ids.items()}
        out = []
        db = self.reader()
        try:
            for t, data in db.execute("SELECT t, d FROM raw WHERE t >= ? ORDER BY t", (time.time() - seconds,)):
                slots = array.array("f")
                slots.frombytes(data)
                out.append((t, {names[i]: v for i, v in enumerate(slots) if v == v and i in names}))
        finally:
            db.close()
        return out

    def saved_events(self, limit: int) -> list[dict]:
        """The newest events it holds, at most `limit`, oldest first."""
        rows = self.db.execute(
            "SELECT t, node, kind, text, level FROM events ORDER BY t DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(zip(("t", "node", "kind", "text", "level"), r)) for r in reversed(rows)]

    def saved_logs(self, limit: int) -> list[dict]:
        """The newest log lines it holds, at most `limit`, oldest first."""
        rows = self.db.execute("SELECT seq, t, node, text FROM logs ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(("seq", "t", "node", "text"), r)) for r in reversed(rows)]

    def backfilled(self) -> bool:
        """Whether the earlier runs were already read from the engine logs. Asked over a connection of its own: at the
        start a writer is already at work on the shared one."""
        db = self.reader()
        try:
            return bool(next(db.execute("SELECT 1 FROM meta WHERE k='backfill'"), None))
        finally:
            db.close()

    def backfill(self, minutes: dict[str, list]) -> int:
        """Old engine logs, as one-minute rows. A minute that was really measured stays as it is."""
        fields = (
            "engine.prompt_tok_s",
            "engine.tok_s",
            "engine.running",
            "engine.waiting",
            "engine.kv",
            "engine.prefix",
        )
        scale = (1, 1, 1, 1, 0.01, 0.01)
        added = 0
        with self.writing:
            ids = [self.key_id(f) for f in fields]
            self.db.execute("BEGIN")
            try:
                for stamp, row in minutes.items():
                    values = {i: (avg * f, peak * f) for i, f, (avg, peak) in zip(ids, scale, row)}
                    added += self.db.execute(
                        "INSERT OR IGNORE INTO minute VALUES (?,?)", (float(stamp), self.row(values, 2))
                    ).rowcount
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('backfill', ?)", (str(int(time.time())),))
                self.db.execute("COMMIT")
            except BaseException:  # a row from outside that is no pair of numbers must not leave the transaction open
                roll_back(self.db)
                raise
        return added

    def series(self, names: list[str], t0: float, t1: float, points: int, band: bool = False) -> dict:
        """What the page draws: one shared time axis, then average and peak per key, thinned to about `points` columns
        of `width` seconds. With `band` also the lowest value of every column and how many rows stand behind it:
        samples, or minutes, and never both in one answer (a stretch whose samples begin later than its minutes
        then comes from the minutes alone). A column with a minute whose lowest value was not kept has none.
        An answer is one stand of the file: what the writer adds while it is read is in none of its parts."""
        points = max(10, min(points, 4000))
        width = max((t1 - t0) / points, 1e-3)
        ids = [self.ids.get(n) for n in names]
        buckets: dict[int, list] = {}

        def pour(rows, stride: int, lows: dict) -> None:
            for t, data in rows:
                slots = array.array("f")
                slots.frombytes(data)
                bucket = buckets.setdefault(int((t - t0) // width), [t, [[0.0, 0, -math.inf, math.inf] for _ in ids]])
                for cell, key in zip(bucket[1], ids):
                    if key is None or key * stride >= len(slots) or slots[key * stride] != slots[key * stride]:
                        continue
                    value = slots[key * stride]
                    cell[0] += value
                    cell[1] += 1
                    cell[2] = max(cell[2], slots[key * stride + 1] if stride == 2 else value)
                    cell[3] = lower(cell[3], value if stride == 1 else slot(lows.get(t), key))

        db = self.reader()
        try:
            # One stand of the file for the rows and for their lowest values: the writer goes on between the two.
            db.execute("BEGIN")
            tier, rows, older = stretch_rows(db, t0, t1, band)
            minutes = tier == "minute"
            pour(rows, 2 if minutes else 1, read_lows(db, t0, t1) if band and minutes else {})
            pour(older, 2, {})  # only without a band, where no lowest value is asked for
        finally:
            db.close()
        cells = [buckets[k] for k in sorted(buckets)]
        out = {"t": [round(b[0], 1) for b in cells], "tier": tier, "width": round(width, 3), "series": {}, "peak": {}}
        for i, name in enumerate(names):
            column = [b[1][i] for b in cells]
            out["series"][name] = [round(c[0] / c[1], 3) if c[1] else None for c in column]
            out["peak"][name] = [round(c[2], 3) if c[1] else None for c in column]
            if band:
                out.setdefault("low", {})[name] = [round(c[3], 3) if c[1] and c[3] == c[3] else None for c in column]
                out.setdefault("n", {})[name] = [c[1] for c in column]
        return out

    def size(self) -> dict:
        """How big the history is: bytes on disk, rows of samples and of minutes, and the time of the first minute."""
        db = self.reader()
        try:

            def count(table: str) -> int:
                return next(db.execute(f"SELECT COUNT(*) FROM {table}"))[0]  # noqa: S608

            first = next(db.execute("SELECT MIN(t) FROM minute"), (None,))[0]
            wal = Path(str(self.path) + "-wal")
            total = self.path.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
            return {"bytes": total, "raw_rows": count("raw"), "minute_rows": count("minute"), "first": first}
        finally:
            db.close()
