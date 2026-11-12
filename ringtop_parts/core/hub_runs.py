"""The run the hub holds open and the runs that ended: events for their two ends, and a record of each."""

from __future__ import annotations

import collections
import time

from ringtop_parts.core.figures import RATE_WINDOW
from ringtop_parts.core.run_sums import (
    as_saved,
    count_engine,
    count_peak,
    count_power,
    empty_sums,
    power_gaps,
    resumed,
    tail_gaps,
)
from ringtop_parts.core.runs import closed, is_record, named, opened, step, told

RUN_KEEP = 200  # records of ended runs the hub holds in memory, the newest
RUN_SAVE = 60.0  # seconds between two writes of the open record to the history


class Runs:
    """The part of the Hub that follows the run a source names and keeps a record of every run."""

    def begin_runs(self) -> None:
        """Starts with the records the history holds, or with none. The newest of them may be of a run that was
        open when ringtop stopped: it is held as loaded until its source names that run again (run_resumed) or it
        turns out to be gone. Whether it is the same run is told by its start: an open record without one, and
        any older open one, is of a run nobody saw end.

        A row that is no record as this program reads one (is_record: written by another stand, or by no stand)
        is passed over and stays in the file as it is. That is said once, on stdout, for all such rows: no row of
        the table stops the start."""
        self.run_open: dict | None = None  # the record of the run a source names as running
        self.run_loaded = False  # it comes from the history, and its source has not named the run since
        self.run_bases: dict = {"engine": {}, "power": {}}  # what its sums were last counted to (run_sums.py)
        self.run_held: dict = {}  # what belongs to its end, as it was at the moment its source first named no run
        self.runs: collections.deque = collections.deque(maxlen=RUN_KEEP)  # the records of the runs that ended
        rows = self.store.saved_runs(RUN_KEEP + 1) if self.store else []
        saved = [row for row in rows if is_record(row)]
        if len(saved) < len(rows):
            odd = len(rows) - len(saved)
            what = "1 row is no record" if odd == 1 else f"{odd} rows are no records"
            print(f"ringtop: {what} of a run this version reads: passed over, left in the history", flush=True)
        for record in reversed(saved):  # the oldest first
            if record["open"] and record is saved[0] and record["started"] is not None:
                self.run_open, self.run_loaded = {**record, "quiet": None}, True
            else:
                self.runs.append(record if not record["open"] else self.run_lost(record, time.time()))

    def save_run(self, record: dict, now: float) -> dict:
        """Writes a record to the history, where there is one, and notes in it when. Gives the record back. Of the
        open run the history gets the row that also says what only the bases know (as_saved): they are gone when
        ringtop stops, and the gaps they stand for with them."""
        if self.store:
            record["saved"] = now
            held = self.run_bases
            row = as_saved(record, held["engine"], held["power"], now, self.silence) if record["open"] else dict(record)
            self.store.add_run(row)
        return record

    def run_heard(self, source: str) -> bool:
        """Whether the source of a run can be heard at this look. The run command: its last answer did not fail.
        The lab queue: the head, which tells of it, sent its word lately and is not away."""
        return self.external_error is None if source == "command" else bool(self.facts())

    def note_run(self, engine: dict, run: dict, now: float) -> None:
        """One look at the run source (step), after the open run counted what the samples brought (count_run): a
        run the source names for the first time has started, the one it named before has ended, each end an
        event with the cooling at that moment, and the record of the run follows what its source says of it.
        The moment a run ended may lie behind this look: its source named no run for a while before that was
        believed. What belongs to the end is held from that first moment on (run_hold).

        The open record is written to the history once a minute for as long as it counts and nobody said its run
        ended: also while its source cannot be heard and the run stays, so a restart of ringtop loses a minute of
        counting at most, however long the source was silent. Not written are a record the history handed over
        whose source has not named the run again (its row says when its sums were last written), and a record
        whose source names no run and is not believed yet (what is counted then is not of a run that ended). That
        holds for as long as the word stands, also where the source cannot be heard after it and nothing is
        believed: the history holds no sums from after an end. A run that is named again after such a silence and
        a restart of ringtop has lost the time since its last row, and says it as a gap."""
        known, said = self.run_open, named(run)
        if known and not self.run_loaded:
            self.count_run(known, engine)
        heard = bool(known) and self.run_heard(known["source"])
        after, ended, started = step(known, said, heard, now)
        if after is not None and after["quiet"] is not None and known["quiet"] is None:
            self.run_held = self.run_hold(after)  # the source names no run, from now on
        if ended is not None:
            self.run_ended(known, ended, now)
        if started:
            after = self.run_started(after, run, engine, now)
        elif self.run_loaded and said is not None:
            after = self.run_resumed(after, engine, now)
        if after is not None and said is not None:
            self.run_told(after, run, now)
        counting = after is not None and not self.run_loaded and after["quiet"] is None
        if counting and now - (after["saved"] or 0.0) >= RUN_SAVE:
            self.save_run(after, now)
        self.run_open = after

    def run_told(self, record: dict, run: dict, now: float) -> None:
        """The source names the open run at this look: its record goes by the source's last word and keeps which
        model on which image runs as the head first said it."""
        record.update(told(run), last_heard=now)
        for key, value in self.identity_view().items():
            if key in ("model", "image"):
                record[key] = record.get(key) or value

    def run_lost(self, record: dict, now: float) -> dict:
        """Closes the record of a run nobody saw end, without an end, and writes it. Its sums are those of its last
        save. That save may lie after the moment its source last named the run: the source could not be heard,
        and the run stayed and was counted (note_run). A Spark never read in the run was not read in that time
        either: a gap, said here. Up to the moment the source last named the run the page counts such a Spark, as
        it does for a run that is open (runShares in page/runcard.js)."""
        unheard = max(0.0, (record["saved"] or record["last_heard"]) - record["last_heard"])
        gone = closed(record, None)
        gone["gpu_gap_s"] += (gone["sparks"] - gone["gpu_from"]) * unheard
        return self.save_run(gone, now)

    def count_run(self, record: dict, engine: dict) -> None:
        """Counts into the record of the open run what the samples brought since the last look: the newest reading
        of the ring engine with its speed at that reading, where it has one, and the newest sample of every Spark
        that is live and read its GPU power. A look without a new reading counts nothing (run_sums.py). A run
        whose source names tracks is written by the engines the Sparks run on their own, which nothing counts
        yet: what the ring engine counts meanwhile is not that run's, and its tokens stay unknown."""
        if self.scrapes and not record.get("tracks"):
            t, reading, _ = self.scrapes[-1]
            count_engine(record, self.run_bases["engine"], t, reading, self.silence)
            if engine.get("state") != "offline":  # the speed of this look is the one at that reading
                count_peak(record, t, engine.get("tok_s"), RATE_WINDOW + self.interval)
        for name, node in self.nodes.items():
            heard = self.heard_at.get(name)
            if node["live"] and node.get("w") is not None and heard is not None:  # unread GPU power is not 0 W
                count_power(record, self.run_bases["power"], name, heard, node["w"], self.silence)

    def run_hold(self, record: dict) -> dict:
        """What belongs to the end of the open run, as it is at this moment: the cooling in words, its sums, and
        what they were counted to."""
        sums = {key: record[key] for key in empty_sums()}
        bases = {part: dict(counted) for part, counted in self.run_bases.items()}
        return {"cooling": self.cooling_words("At the end"), "sums": sums, "bases": bases}

    def run_started(self, run: dict, said: dict, engine: dict, now: float) -> dict:
        """A run was named for the first time: said as an event with the cooling of now. Gives its record, with
        what its source says of it (`said`: the run as the page shows it), whose sums begin at the readings that
        are current at this moment."""
        self.event(now, None, "run", f"Started: {run['name']}")
        self.note_cooling(now, "At the start")
        record = {**opened(run, now), **told(said), **empty_sums(), "sparks": len(self.nodes)}
        self.run_bases = {"engine": {}, "power": {}}
        self.count_run(record, engine)
        return record

    def run_resumed(self, record: dict, engine: dict, now: float) -> dict:
        """The source names the run the history held as open: ringtop was restarted while it went on, and is back
        on it. Nothing is said, the run keeps its id, and its sums count on from the readings of now, with the
        time nobody counted as a gap (resumed)."""
        self.run_loaded = False
        record = resumed(record, now)
        self.run_bases = {"engine": {}, "power": {}}
        self.count_run(record, engine)
        return self.save_run(record, now)

    def run_ended(self, known: dict, ended: float, now: float) -> None:
        """A run has ended at the moment given: said as an event with the cooling of that moment, and its record
        goes to the runs that ended. Where its source had named no run before this look, cooling and sums are the
        ones held from then: what came after is not of the run. A run the history held as open and that its
        source never named again ended while ringtop was away: nobody saw when, and nothing is said of it."""
        if self.run_loaded:
            self.run_loaded = False
            self.runs.append(self.run_lost(known, now))
            return
        held = self.run_held if known["quiet"] is not None else self.run_hold(known)
        record = closed({**known, **held["sums"]}, ended)
        tail_gaps(record, held["bases"]["engine"], ended, self.silence)
        power_gaps(record, held["bases"]["power"], record["sparks"], ended, self.silence)
        self.event(ended, None, "run", f"Finished: {known['name']}")
        if held["cooling"]:
            self.event(ended, None, "cooling", held["cooling"])
        self.runs.append(self.save_run(record, now))

    def runs_view(self, limit: int = 50) -> dict:
        """The records of runs for the page: the one that is open, or None, and the ones that ended, the newest
        first and no more than asked for."""
        with self.lock:
            ended = [dict(record) for record in list(self.runs)[::-1][: max(0, limit)]]
            return {"open": dict(self.run_open) if self.run_open else None, "runs": ended}
