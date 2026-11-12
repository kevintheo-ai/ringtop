"""The lowest value of every minute: kept beside the one-minute rows, and made good from the samples."""

from __future__ import annotations

import array
import contextlib
import math
import sqlite3
import sys
import time

RAW_KEEP = 2 * 86400  # every sample, on disk: the stretch a lowest value can be made good from
# Empties the lowest values of a stretch that stand in doubt: those of a minute whose next minute, the earliest one
# anybody wrote after it, has no row of lowest values. An emptied row is still a row.
DOUBTFUL = """
    UPDATE minute_low SET d = x'' WHERE t >= ? AND t < ? AND length(d) > 0 AND EXISTS (
        SELECT 1 FROM minute
        WHERE minute.t = (SELECT MIN(t) FROM minute AS later WHERE later.t > minute_low.t)
        AND NOT EXISTS (SELECT 1 FROM minute_low AS kept WHERE kept.t = minute.t))
"""


def slot(row, key: int) -> float:
    """One value of a row of floats; NaN where there is no row, or none that long."""
    return row[key] if row is not None and key < len(row) else math.nan


def lower(a: float, b: float) -> float:
    """The lower of two values, and unknown (NaN) once one of them is: the lowest of a part is not the lowest of all."""
    return min(a, b) if a == a and b == b else math.nan


def same(a, b) -> bool:
    """Whether two rows of floats say the same, slot by slot: a slot that is missing counts as NaN, and NaN is the
    same as NaN. No row at all is not the same as any."""
    if b is None:
        return False
    pairs = ((slot(a, key), slot(b, key)) for key in range(max(len(a), len(b))))
    return all(x == y or (x != x and y != y) for x, y in pairs)


def lowest(a, b) -> array.array:
    """Two rows of lowest values as one: slot by slot the lower, and the value where only one row has one."""
    out = array.array("f", [math.nan] * max(len(a), len(b)))
    for key in range(len(out)):
        x, y = slot(a, key), slot(b, key)
        out[key] = min(x, y) if x == x and y == y else (x if x == x else y)
    return out


def whole_from(now: float) -> float:
    """The first minute that still has every one of its samples at a moment: a quarter of an hour inside the two
    days they are kept. The pruner goes by the same clock, and a clock is set back a little now and then."""
    return (now - RAW_KEEP + 900) // 60 * 60 + 60


def roll_back(db: sqlite3.Connection) -> None:
    """Ends the transaction of a write that failed. When the database is full, SQLite has rolled it back by itself
    already: the ROLLBACK is then an error of its own, and not the one to hand on."""
    with contextlib.suppress(sqlite3.Error):
        db.execute("ROLLBACK")


def read_lows(db: sqlite3.Connection, t0: float, t1: float) -> dict:
    """The lowest values the minutes of a stretch kept, by minute, each a row of floats."""
    out = {}
    for t, data in db.execute("SELECT t, d FROM minute_low WHERE t >= ? AND t <= ?", (t0, t1)):
        out[t] = array.array("f")
        out[t].frombytes(data)
    return out


class Lows:
    """The part of the Store that keeps the lowest value of every minute. Holds no state of its own.

    They live in a table of their own, one float per key: the stand before this one writes the one-minute rows as
    they are and has to go on working on the same file. A lowest value is the lowest of all samples of its minute,
    and none is better than one that stands too high: a writer that kept none leaves minutes without one, or with
    one of a part of the minute, and every start makes that good from the samples (fill_lows)."""

    def merge_low(self, t: float, row: dict[str, list]) -> None:
        """One piece of a minute joins its lowest values: the lower of what is kept and what comes. A minute that
        stands there without any was begun by a writer that kept none: this piece is only a part of it, so it gets
        none here (fill_lows reads it from the samples)."""
        found = next(self.db.execute("SELECT d FROM minute_low WHERE t=?", (t,)), None)
        if not found and next(self.db.execute("SELECT 1 FROM minute WHERE t=?", (t,)), None):
            return
        values = {self.key_id(name): cell[3] for name, cell in row.items()}
        if found:
            slots = array.array("f")
            slots.frombytes(found[0])
            for key, old in enumerate(slots):
                if old == old:
                    values[key] = min(old, values.get(key, old))
        self.db.execute("INSERT OR REPLACE INTO minute_low VALUES (?,?)", (t, self.row(values)))

    def fill_lows(self, now: float | None = None, piece: int = 120) -> int:
        """Makes the lowest values of the last two days good from the samples: writes them where a minute has none,
        or one that stands too high. That is so after the first start of this stand, and after a time the stand
        before it wrote the file (it adds to a minute and knows no lowest value). `piece` minutes per transaction,
        so the writer never waits long. Gives back how many minutes it wrote. `now` holds the clock still."""

        def clock() -> float:
            return time.time() if now is None else now

        end = clock()
        t0, written = whole_from(end), 0
        while t0 < end:
            with self.writing:
                # Which minutes still have all their samples is sure only here: under this lock nothing is dropped,
                # and the two days may have moved on while the fill waited for it. A minute that has lost some of
                # its samples would get a lowest value that stands too high.
                first = max(t0, whole_from(clock()))
                self.db.execute("BEGIN")
                try:
                    written += self.fill_piece(first, t0 + piece * 60)
                    self.db.execute("COMMIT")
                except BaseException:  # whatever stopped it: the writer shares this connection and needs it free
                    roll_back(self.db)
                    raise
            t0 += piece * 60
        return written

    def fill_piece(self, t0: float, t1: float) -> int:
        """The minutes from t0 up to t1: the lowest value of each from its samples, joined with the one it kept
        (what the writer once measured is never raised) and written where that changes it. Gives back how many
        minutes were written. A minute without samples, read from old engine logs, gets none."""
        lows: dict[float, array.array] = {}
        for t, data in self.db.execute("SELECT t, d FROM raw WHERE t >= ? AND t < ?", (t0, t1)):
            slots = array.array("f")
            slots.frombytes(data)
            low = lows.setdefault(t // 60 * 60, array.array("f"))
            low.extend([math.nan] * (len(slots) - len(low)))
            for key, value in enumerate(slots):
                if value == value and not low[key] <= value:  # also true while nothing stands there yet (NaN)
                    low[key] = value
        kept = read_lows(self.db, t0, t1)
        written = 0
        for minute, low in lows.items():
            old = kept.get(minute)
            new = low if old is None else lowest(low, old)
            if not same(new, old):
                self.db.execute("INSERT OR REPLACE INTO minute_low VALUES (?,?)", (minute, new.tobytes()))
                written += 1
        return written

    def doubt_lows(self, now: float | None = None, piece: int = 1440) -> int:
        """Takes back the lowest values nobody can vouch for any more, and gives back how many minutes that were.

        A writer that keeps none (the stand before this one) goes on with a minute this stand began and leaves its
        lowest value as it stood: too high, if a lower sample came after. Within the two days of samples fill_lows
        reads the true one. Older than that, only the neighbourhood shows it: the minute has a lowest value, and
        the next minute anybody wrote has none. Such a minute keeps its row, emptied: it has no lowest value then
        (none is better than one that stands too high), and the minute before it still has a neighbour with a row,
        so that the next start takes back no more. `piece` minutes per hold of the lock, so the writer never waits
        long. `now` holds the clock still."""
        doubted, t0 = 0, None
        while True:
            with self.writing:  # the bound is asked under the lock, like the one of fill_lows
                before = whole_from(time.time() if now is None else now)
                if t0 is None:
                    oldest = next(self.db.execute("SELECT MIN(t) FROM minute_low"))[0]
                    t0 = before if oldest is None else oldest
                if t0 >= before:
                    return doubted
                doubted += self.db.execute(DOUBTFUL, (t0, min(t0 + piece * 60, before))).rowcount
            t0 += piece * 60

    def catch_up(self, now: float | None = None) -> None:
        """What a start makes good in the history, beside the writer: lowest values that stand in doubt are taken
        back, then those that are missing or stand too high are read from the samples. In this order: once a minute
        has its lowest value from the samples, the doubtful one before it has a neighbour like any other. A failure,
        whatever stopped it, is said on stderr in one line and stops nothing. `now` holds the clock still."""
        try:
            doubted, written = self.doubt_lows(now), self.fill_lows(now)
            if doubted:
                minutes = "minute" if doubted == 1 else "minutes"
                why = "a writer that kept none went on after this stand, and the samples are gone"
                print(f"ringtop: lowest values of {doubted} {minutes} taken back: {why}", file=sys.stderr, flush=True)
            if written:
                print(f"ringtop: lowest values of {written} minutes read from the samples", file=sys.stderr, flush=True)
        except Exception as problem:  # whatever it is: in a thread of its own nobody else would say it
            print(f"ringtop: lowest values not read from the samples: {problem!r}", file=sys.stderr, flush=True)
