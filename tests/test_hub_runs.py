"""The run the hub holds open: which words of a run source start it, leave it as it is, and end it."""

import contextlib
import io
import json
import sqlite3
import subprocess
import tempfile
import time
import types
from pathlib import Path

from ringtop_parts.connect import shell
from ringtop_parts.core.cluster import parse_cluster, parse_runs
from ringtop_parts.core.hub import Hub
from ringtop_parts.core.run_sums import empty_sums
from ringtop_parts.store import Store
from tests.fixtures import engine_sample, hub_for, ring_map

WRITING = {"state": "writing"}
# two stamps a queue wrote five seconds apart, on either side of a full minute: the last line of the job before
# (11 Nov 2026, 01:08:57 in the zone of that queue) and the start line of the job that followed (01:09:02)
BEFORE, STARTED = 1794355737.0, 1794355742.0


def run_events(hub):
    return [e["text"] for e in hub.events if e["kind"] == "run"]


class Clock:
    """Stands in for time.time while a check runs: the moment is the one the check set."""

    def __enter__(self):
        self.real, self.now = time.time, time.time()
        time.time = lambda: self.now
        return self

    def __exit__(self, *problem):
        time.time = self.real


def test_a_start_that_moves_by_seconds_is_the_start_of_the_same_run():
    """Between two jobs a run source may name the job that comes next, with the moment of its last line as the start,
    and a few seconds later with the moment the job really began. The hub told runs apart by their name and the half
    minute their start fell into: two stamps five seconds apart on either side of 01:09:00 were two runs, and the
    job stood as finished and started again four seconds after it began. It happened at four of 33 changes of job
    in one night, exactly the four whose stamps lay on either side of such an edge."""
    hub = hub_for()
    job = {"source": "command", "name": "Job 3"}
    hub.note_changes(WRITING, {**job, "started": BEFORE})
    hub.note_changes(WRITING, {**job, "started": STARTED})
    assert run_events(hub) == ["Started: Job 3"], run_events(hub)  # was Started, Finished, Started
    assert hub.run_open["started"] == STARTED  # the run goes by the start its source named last
    hub.note_changes(WRITING, {**job, "started": STARTED + 29.0})
    assert run_events(hub) == ["Started: Job 3"], run_events(hub)
    hub.note_changes(WRITING, {**job, "started": STARTED + 59.0})  # half a minute on: the same job, begun anew
    assert run_events(hub) == ["Started: Job 3", "Finished: Job 3", "Started: Job 3"], run_events(hub)


def test_a_run_of_the_lab_queue_stays_while_the_head_is_not_heard():
    """What the lab queue runs is told by the head, every 10 s, and its word stands for 40 s. When that word grew
    too old, and when the head went away, the run stood as finished though nobody had seen it end, with a note of
    the cooling; the next word of the head started it again. A source that cannot be heard says nothing: the run
    stays as it is, however long that lasts, and nothing is written."""
    hub = hub_for()
    lab = {"lab": {"hold": {"holder": "lab", "current": "run A", "expected_end": None}, "queue": {}}}
    with Clock() as clock:
        start = clock.now
        hub.ingest("dgx0", {"t": start, "info": lab})
        assert hub.view()["run"]["name"] == "run A" and run_events(hub) == ["Started: run A"]
        clock.now = start + 41  # the samples of the head keep coming, its word about the queue does not
        hub.ingest("dgx0", {"t": start + 41})
        assert hub.view()["run"]["source"] == "none"  # the page shows what it can read: no run
        assert run_events(hub) == ["Started: run A"], run_events(hub)  # was Started, Finished
        clock.now = start + 50
        hub.ingest("dgx0", {"t": start + 50, "info": lab})
        assert hub.view()["run"]["name"] == "run A"
        assert run_events(hub) == ["Started: run A"], run_events(hub)  # was Started, Finished, Started
        hub.node_down("dgx0", "ssh: timed out")
        clock.now = start + 3600
        hub.view()
        assert run_events(hub) == ["Started: run A"], run_events(hub)  # nobody saw it end in that hour
        for second in (3600, 3610, 3620, 3630):  # the head is back and its queue holds nothing: that is a word
            clock.now = start + second
            hub.ingest("dgx0", {"t": start + second, "info": {"lab": {"hold": None, "queue": {}}}})
            hub.view()  # said for half a minute, it is believed: the run ended when the head first said so
            assert len(run_events(hub)) == (2 if second == 3630 else 1), (second, run_events(hub))
        assert run_events(hub) == ["Started: run A", "Finished: run A"], run_events(hub)
        assert hub.events[-1]["t"] == start + 3600


def test_a_run_of_the_run_command_stays_while_the_command_fails():
    """The run command is asked every 5 s. An answer that fails (it exits with an error, takes longer than 10 s,
    prints what is no run) left the hub without a run, and the run stood as finished and, with the next answer,
    as started again. A command that fails says nothing about the run; one that answers with no run does."""
    hub = hub_for()
    job = {"name": "Job 1", "started": BEFORE, "done": 3, "total": 9}
    with Clock() as clock:
        start = clock.now
        hub.external_run = dict(job)
        hub.view()
        for second in (15, 30, 45, 600):  # answers that fail, for ten minutes
            clock.now = start + second
            hub.external_run, hub.external_error = None, "Command timed out after 10 seconds"
            assert hub.view()["run"]["source"] == "error"  # the page says that the source failed
            assert run_events(hub) == ["Started: Job 1"], run_events(hub)  # was Started, Finished
        hub.external_run, hub.external_error = dict(job), None
        hub.view()
        assert run_events(hub) == ["Started: Job 1"], run_events(hub)  # was Started, Finished, Started
        clock.now, hub.external_run = start + 700, None  # it answers, and names no run
        hub.view()
        clock.now = start + 730
        hub.view()  # said for half a minute, it is believed
        assert run_events(hub) == ["Started: Job 1", "Finished: Job 1"], run_events(hub)
        assert hub.events[-1]["t"] == start + 700


class Asked(Exception):
    """Ends poll_runs after its first answer, in place of the pause before the next."""


def polled(hub, printed: str) -> None:
    """One round of poll_runs (connect/shell.py) against a run command that printed `printed` and exited with 0:
    the hub gets the run or the reason there is none, as every 5 s in ringtop. It has to come to its pause: a
    poll_runs that ends instead (in ringtop its thread would be gone, and with it every later answer) fails here."""

    def asked(*_):
        raise Asked

    answer = types.SimpleNamespace(returncode=0, stdout=printed, stderr="")
    real = shell.subprocess, shell.time
    shell.subprocess = types.SimpleNamespace(run=lambda *_, **__: answer, TimeoutExpired=subprocess.TimeoutExpired)
    shell.time = types.SimpleNamespace(sleep=asked)
    try:
        shell.poll_runs(hub, "runs")
    except Asked:
        pass
    else:
        raise AssertionError("poll_runs ended instead of asking again")
    finally:
        shell.subprocess, shell.time = real


def test_a_run_command_that_prints_only_a_number_no_browser_reads_has_failed_and_ends_no_run():
    """A run command that printed NaN, Infinity, 1e400, a number of hundreds of digits or a list with one of them
    first had failed: that is no run and no word of none ("Run source failed"). Once such a number was read
    as None wherever it stands, the whole answer too, and None is the word of a command that names no run: the page
    said "Nothing running", and after half a minute the run that was open was finished, and started again as a
    new run with the next good answer. The shape of an answer is judged as the command printed it; only the numbers
    in a run are read as nobody read them. null and an empty list still name no run."""
    hub = hub_for()
    job = json.dumps({"name": "Job 1", "started": BEFORE, "done": 3, "total": 9})
    odd = ("NaN", "Infinity", "-Infinity", "1e400", "1" + "0" * 400, "[NaN]", '[Infinity, {"name": "Job 1"}]')
    with Clock() as clock:
        start = clock.now
        polled(hub, job)
        hub.view()
        first = hub.run_open["id"]
        for k, printed in enumerate(odd):  # for 70 s and more, past the half minute of a word of no run
            clock.now = start + 15 + 10 * k
            polled(hub, printed)
            run = hub.view()["run"]
            assert (run["source"], run.get("name"), run.get("detail")) == (
                "error",
                "Run source failed",
                "needs an object with a name",
            ), (printed, run)  # was "none"
            assert run_events(hub) == ["Started: Job 1"], (printed, run_events(hub))  # was Finished after 30 s
        clock.now = start + 100
        polled(hub, job)
        hub.view()
        assert run_events(hub) == ["Started: Job 1"] and hub.run_open["id"] == first, run_events(hub)
        # these name no run: said for half a minute, it is believed
        for k, printed in enumerate(("null", "[]", "[null]")):
            clock.now = start + 110 + 20 * k
            polled(hub, printed)
            assert hub.view()["run"]["source"] == "none", printed
        assert run_events(hub) == ["Started: Job 1", "Finished: Job 1"], run_events(hub)


def test_an_answer_nested_too_deep_to_read_is_a_run_source_that_failed_and_the_asking_goes_on():
    """An answer of the run command nested deeper than json can read threw a RecursionError, which poll_runs did
    not catch: the thread that asks the command ended without a word, and the run it last named stood on the page
    for as long as ringtop ran. Such an answer is one that could not be read: the source has failed, and the next
    answer is asked for as after every other."""
    hub = hub_for()
    for deep in ('{"name":"Job 1","x":' + "[" * 100000 + "]" * 100000 + "}", "[" * 100000 + "]" * 100000):
        polled(hub, deep)  # was a RecursionError out of poll_runs: its pause, and the next answer, never came
        run = hub.view()["run"]
        assert run["source"] == "error" and "recursion" in run["detail"], run
    polled(hub, json.dumps({"name": "Job 1"}))
    assert hub.view()["run"]["name"] == "Job 1"


def test_the_events_of_a_stretch_come_in_the_order_of_their_moments():
    """An event may be noted later than it happened: a line of the journal carries the moment the kernel wrote it,
    and the sampler reads the journal every 15 s. Without a store the events of a stretch came in the order they
    were noted. The page takes the run of a past moment from the last run event before it, and shows the last
    forty events before it: both read the list as one that goes by time, as the store always gave it."""
    hub = hub_for()
    hub.event(100.0, None, "run", "Started: Job 2")
    hub.event(40.0, "dgx0", "kernel", "a line the sampler read late", "bad")
    hub.event(90.0, None, "run", "Finished: Job 1")
    hub.event(90.0, None, "cooling", "At the end: fans 2,600 RPM")
    assert [(e["t"], e["kind"]) for e in hub.events_between(0.0, 200.0)] == [
        (40.0, "kernel"),
        (90.0, "run"),
        (90.0, "cooling"),  # two of one moment stay in the order they were noted
        (100.0, "run"),
    ]
    assert [e["t"] for e in hub.events_between(50.0, 95.0)] == [90.0, 90.0]


def test_a_source_that_names_no_run_for_a_moment_does_not_end_the_run():
    """A source that answers and names no run says that none is running. It may say so for a moment only: a queue
    of single tracks has no runner alive while one of its tracks changes jobs, and its run stood as finished and
    started again 51 times in one night, 4 to 65 s apart. The hub believes that word once the source has said it
    for half a minute. Then the run ended at the moment the source first said it, and the event carries that moment."""
    hub = hub_for()
    tracks = {"name": "Single tracks", "tracks": [{"node": "dgx1", "name": "Job 4"}]}
    with Clock() as clock:
        start = clock.now
        hub.external_run = dict(tracks)
        hub.view()
        for second in (100, 110, 129):  # the source names no run, for 29 s
            clock.now, hub.external_run = start + second, None
            hub.view()
        assert run_events(hub) == ["Started: Single tracks"], run_events(hub)  # was Started, Finished
        clock.now, hub.external_run = start + 130, dict(tracks)
        hub.view()
        assert run_events(hub) == ["Started: Single tracks"], run_events(hub)  # was Started, Finished, Started
        for second in (200, 215, 229.5):  # it names none again: the half minute counts from here, not from before
            clock.now, hub.external_run = start + second, None
            hub.view()
        assert run_events(hub) == ["Started: Single tracks"], run_events(hub)
        clock.now = start + 230
        hub.view()
        assert run_events(hub) == ["Started: Single tracks", "Finished: Single tracks"], run_events(hub)
        assert hub.events[-1]["t"] == start + 200, hub.events[-1]["t"] - start  # when the source first named none
        clock.now = start + 300
        hub.view()
        assert len(run_events(hub)) == 2 and hub.run_open is None


def test_what_belongs_to_the_end_of_a_run_is_of_the_moment_it_ended():
    """The end of a run is written half a minute after its source first named no run. The note of the cooling
    beside it lets two runs be compared (were they equally warm at their ends?): it holds fans, warmest sensor and
    GPU clock as they were at the moment the run ended, not as they are when the end is written. Half a minute
    after a run the fans have slowed down and the board has cooled."""
    hub = hub_for()

    def sparks(at, fans, warm, mhz):
        for i, name in enumerate(("dgx0", "dgx1")):
            reading = {"gpu": {"w": 30.0, "c": warm - 10, "mhz": mhz + 6 * i, "util": 90.0}}
            hub.ingest(
                name,
                {
                    "t": at,
                    "fabric": {},
                    **reading,
                    "sensors": {"fans": [fans, fans + 100 * i]},
                    "zones": {"TSOC": warm + 2 * i},
                },
            )

    def cooling():
        return [(e["t"], e["text"]) for e in hub.events if e["kind"] == "cooling"]

    with Clock() as clock:
        start = clock.now
        sparks(start, 3000, 80.0, 2184.0)
        hub.external_run = {"name": "Job 1", "started": start}
        hub.view()
        clock.now, hub.external_run = start + 600, None  # the source names no run: the run ends here
        sparks(start + 600, 3100, 84.0, 2184.0)
        hub.view()
        at_the_end = "At the end: fans 3,100 to 3,200 RPM, warmest sensor 86 °C on dgx1, GPU clock 2.18 to 2.19 GHz"
        assert len(cooling()) == 1, cooling()  # nothing is written yet
        clock.now = start + 630
        sparks(start + 630, 2200, 61.0, 1200.0)  # half a minute later the Sparks are cool and slow
        hub.view()
        assert run_events(hub) == ["Started: Job 1", "Finished: Job 1"], run_events(hub)
        assert cooling()[-1] == (start + 600, at_the_end), cooling()[-1]
        assert [e["t"] for e in hub.events if e["text"] == "Finished: Job 1"] == [start + 600]
        # a run that follows before the half minute is over ends the one before at the same moment, with the same note
        hub.external_run = {"name": "Job 2", "started": start + 630}
        hub.view()
        clock.now, hub.external_run = start + 900, None
        sparks(start + 900, 3050, 82.0, 2184.0)
        hub.view()
        clock.now, hub.external_run = start + 910, {"name": "Job 3", "started": start + 910}
        sparks(start + 910, 2500, 70.0, 2184.0)
        hub.view()
        assert run_events(hub)[-2:] == ["Finished: Job 2", "Started: Job 3"], run_events(hub)
        ended, began = cooling()[-2:]
        assert ended == (
            start + 900,
            "At the end: fans 3,050 to 3,150 RPM, warmest sensor 84 °C on dgx1, GPU clock 2.18 to 2.19 GHz",
        ), ended
        assert began == (
            start + 910,
            "At the start: fans 2,500 to 2,600 RPM, warmest sensor 72 °C on dgx1, GPU clock 2.18 to 2.19 GHz",
        ), began


STATIONS = [{"name": "Job 1", "state": "running"}, {"name": "Job 2", "state": "pending", "was": 61}]


def queue_job(name, started, done, **more):
    """A run as the run command names it: with what the record keeps, and with what it must not keep."""
    kept = {"name": name, "group": "Queue 9", "started": started, "done": done, "total": 9, "steps": STATIONS}
    return {**kept, "holder": "Lab", "until": "about 4 pm", "replies": [{"reply": "secret"}], **more}


def test_a_run_leaves_a_record_with_one_id_from_its_start_to_its_end():
    """Until now a run was two events and nothing else: its name in "Started" and in "Finished". The hub now keeps
    a record of every run a source names, under an id it gets when it is first seen and keeps: what the source
    says of it (queue, how far it is, its stations as last named), which model on which image ran, when it was
    first seen, when its source last named it, and when it ended. The moment the page gets is as it was."""
    hub = hub_for()
    model = {"models": {"data": [{"id": "model-a"}]}, "container": {"image": "image:1", "status": "running"}}
    with Clock() as clock:
        start = clock.now
        hub.ingest("dgx0", {"t": start, "info": model})
        assert hub.runs_view() == {"open": None, "runs": []}
        hub.external_run = queue_job("Job 1", start - 6, 0)
        assert "runs" not in hub.view()
        first = hub.runs_view()["open"]
        told = {
            "id": round(start * 1000),
            "source": "command",
            "name": "Job 1",
            "group": "Queue 9",
            "started": start - 6,
            "first_seen": start,
            "last_heard": start,
            "ended": None,
            "open": True,
            "quiet": None,
            "done": 0,
            "total": 9,
            "steps": STATIONS,
            "model": "model-a",
            "image": "image:1",
        }
        assert {key: first[key] for key in told} == told, first
        clock.now = start + 100
        hub.external_run = queue_job("Job 1", start - 1, 5)  # the same run: its start moved, it is further on
        hub.view()
        later = hub.runs_view()["open"]
        assert (later["id"], later["started"], later["done"], later["last_heard"]) == (
            first["id"],
            start - 1,
            5,
            start + 100,
        )
        clock.now = start + 200
        hub.external_run = queue_job("Job 2", start + 200, 0)  # the next job of the queue
        hub.view()
        told = hub.runs_view()
        ended = told["runs"][0]
        assert told["open"]["name"] == "Job 2" and told["open"]["id"] == round((start + 200) * 1000)
        assert (ended["id"], ended["ended"], ended["open"], ended["done"]) == (first["id"], start + 200, False, 5), (
            ended
        )
        assert "quiet" not in ended and ended["last_heard"] == start + 100
        clock.now, hub.external_run = start + 300, None  # the queue is through: no run named
        hub.view()
        clock.now = start + 330
        hub.view()
        told = hub.runs_view()
        assert told["open"] is None and [r["name"] for r in told["runs"]] == ["Job 2", "Job 1"]  # the newest first
        assert told["runs"][0]["ended"] == start + 300 and told["runs"][0]["last_heard"] == start + 200
        assert hub.runs_view(1)["runs"] == told["runs"][:1]


def test_a_record_keeps_of_a_source_only_the_fields_it_knows_in_the_shapes_it_knows():
    """What a run source says comes from a command outside, and the page shows the record: only the known fields
    get through, in the known shapes, and no more than 64 stations."""
    hub = hub_for()
    odd = [
        {"name": "A" * 300, "state": "done", "seconds": 61.5, "was": 58, "note": "x"},
        {"name": 7, "state": "exploded", "seconds": "long"},
        "no station",
        {"state": "pending", "seconds": True},
    ]
    hub.external_run = {
        "name": "Job 1",
        "group": ["Queue"],
        "done": "three",
        "total": True,
        "steps": odd + STATIONS * 40,
    }
    hub.view()
    record = hub.runs_view()["open"]
    assert (record["group"], record["done"], record["total"]) == (None, None, None), record
    assert record["steps"][:2] == [
        {"name": "A" * 120, "state": "done", "seconds": 61.5, "was": 58},
        {"state": "pending"},
    ]
    assert len(record["steps"]) == 64 and record["steps"][2:4] == STATIONS
    assert (record["model"], record["image"]) == (None, None)  # the head has not said what runs
    hub.external_run = {"name": "Job 1", "steps": "none"}
    hub.view()
    assert hub.runs_view()["open"]["steps"] is None  # no list of stations is not a list of none


def test_a_record_says_when_its_source_last_named_the_run():
    """While the source of a run cannot be heard the run stays open; its record says since when nobody named it."""
    hub = hub_for()
    with Clock() as clock:
        start = clock.now
        hub.external_run = {"name": "Job 1", "started": start}
        hub.view()
        clock.now = start + 50
        hub.view()
        clock.now, hub.external_run, hub.external_error = start + 600, None, "exit 1"
        hub.view()
        record = hub.runs_view()["open"]
        assert (record["open"], record["last_heard"], record["ended"]) == (True, start + 50, None), record


def feed_engine(hub, clock, start, second, tokens, **extra):
    """One sample of the head with a reading of the ring engine, at a second of the check's clock."""
    clock.now = start + second
    hub.ingest("dgx0", engine_sample(start + second, tokens, **extra))


def test_a_record_counts_the_tokens_of_its_run_from_the_readings_of_the_engine():
    """Tokens written, steps of the engine and the highest speed of a run come from the readings of the ring
    engine that lie in the run, the first being the one that was current when the run began. They hang on the
    readings: the page of the ticker looks every interval and every page that opens looks once more, and a look
    without a new reading changes no sum."""
    hub = hub_for()
    with Clock() as clock:
        start = clock.now
        feed_engine(hub, clock, start, 0, 1000.0)
        feed_engine(hub, clock, start, 2, 1000.0)
        hub.external_run = {"name": "Job 1", "started": start + 2}
        hub.view()
        record = hub.runs_view()["open"]
        assert (record["tokens"], record["engine_steps"], record["lives"], record["tok_s_peak"]) == (
            None,
            None,
            1,
            None,
        )
        for second, tokens in ((4, 1080.0), (6, 1160.0), (8, 1240.0), (10, 1320.0), (12, 1400.0), (14, 1480.0)):
            feed_engine(hub, clock, start, second, tokens)
            hub.view()
        record = hub.runs_view()["open"]
        counted = (record["tokens"], record["engine_steps"], record["token_s"], record["token_gap_s"], record["lives"])
        assert counted == (480.0, 160.0, 12.0, 0.0, 1), record
        assert record["tok_s_peak"] == 40.0, record  # 320 tokens in the 8 s before the readings at 12 s and 14 s
        hub.view()
        hub.with_history()  # a page that opens
        clock.now = start + 15  # a look between two readings
        hub.view()
        again = hub.runs_view()["open"]
        assert {key: again[key] for key in empty_sums()} == {key: record[key] for key in empty_sums()}, again
        assert again["last_heard"] == start + 15  # the look was taken: the source named the run at it
        feed_engine(hub, clock, start, 16, 1500.0)
        hub.external_run = {"name": "Job 2", "started": start + 16}  # the next job: the reading of this moment is
        hub.view()  # the last of Job 1 and the first of Job 2
        told = hub.runs_view()
        assert (told["runs"][0]["tokens"], told["runs"][0]["token_s"], told["runs"][0]["tok_s_peak"]) == (
            500.0,
            14.0,
            40.0,
        )
        assert (told["open"]["tokens"], told["open"]["lives"]) == (None, 1)
        feed_engine(hub, clock, start, 18, 1560.0)
        hub.view()
        assert hub.runs_view()["open"]["tokens"] == 60.0  # no token between the two runs is lost or counted twice
        assert hub.runs_view()["open"]["tok_s_peak"] is None  # 2 s in, the speed is still mostly that of Job 1


def test_the_sums_of_a_run_are_those_of_the_moment_it_ended():
    """The end of a run is believed half a minute after its source first named no run. What the engine wrote in
    that half minute, for whoever asked it then, is not of the run."""
    hub = hub_for()
    with Clock() as clock:
        start = clock.now
        feed_engine(hub, clock, start, 0, 1000.0)
        hub.external_run = {"name": "Job 1", "started": start}
        hub.view()
        feed_engine(hub, clock, start, 10, 1400.0)
        hub.view()
        feed_engine(hub, clock, start, 20, 1800.0)
        hub.external_run = None  # the source names no run from here on
        hub.view()
        for second, tokens in ((30, 2200.0), (40, 2600.0), (50, 3000.0)):
            feed_engine(hub, clock, start, second, tokens)
            hub.view()
        ended = hub.runs_view()["runs"][0]
        assert (ended["ended"], ended["tokens"], ended["token_s"]) == (start + 20, 800.0, 20.0), ended


def test_a_run_whose_ring_engine_nobody_read_has_no_count_of_tokens():
    """While every Spark serves a model of its own the ring engine is off: a run of that time has no count of
    tokens, which is not a count of zero, and no gap in one."""
    hub = hub_for()
    with Clock() as clock:
        start = clock.now
        feed_engine(hub, clock, start, -600, 5000.0)  # a reading of the ring engine from ten minutes before
        clock.now = start
        hub.ingest("dgx0", {"t": start, "engine": None, "engine_error": "Nothing answers on the vLLM port."})
        hub.external_run = {"name": "Single tracks", "tracks": [{"node": "dgx1", "name": "Job 4"}]}
        hub.view()
        clock.now = start + 100
        hub.ingest("dgx0", {"t": start + 100, "engine": None, "engine_error": "Nothing answers on the vLLM port."})
        hub.external_run = {"name": "Job 9", "started": start + 100}
        hub.view()
        ended = hub.runs_view()["runs"][0]
        counted = (ended["tokens"], ended["engine_steps"], ended["tok_s_peak"], ended["lives"], ended["token_gap_s"])
        assert counted == (None, None, None, 0, 0.0), ended


def feed_power(hub, clock, start, second, watts):
    """One sample of each Spark named, with the GPU power given; None: a sample that holds no reading of it."""
    clock.now = start + second
    for name, w in watts.items():
        hub.ingest(name, {"t": start + second, "fabric": {}, "gpu": {} if w is None else {"w": w}})


def test_a_record_adds_up_the_gpu_energy_of_its_run_from_the_samples_of_the_sparks():
    """The GPU energy of a run is the GPU power of every Spark times the time between its samples, added up, with
    how many Sparks were read and over how many seconds. It hangs on the samples, not on the looks. A Spark whose
    power is not read is not a Spark that draws 0 W: the sum is a part, and the record says of how much."""
    hub = hub_for()
    with Clock() as clock:
        start = clock.now
        feed_power(hub, clock, start, 0, {"dgx0": 30.0, "dgx1": 60.0})
        hub.external_run = {"name": "Job 1", "started": start}
        hub.view()
        record = hub.runs_view()["open"]
        assert (record["gpu_wh"], record["gpu_from"], record["sparks"]) == (None, 2, 4), record
        for second in range(2, 122, 2):
            feed_power(hub, clock, start, second, {"dgx0": 30.0, "dgx1": 60.0})
            hub.view()
        record = hub.runs_view()["open"]
        assert round(record["gpu_wh"], 9) == 3.0 and (record["gpu_read_s"], record["gpu_gap_s"]) == (240.0, 0.0), record
        hub.view()
        hub.with_history()  # a page that opens
        clock.now = start + 121  # a look between two samples
        hub.view()
        again = hub.runs_view()["open"]
        assert {key: again[key] for key in empty_sums()} == {key: record[key] for key in empty_sums()}, again
        for second in range(122, 242, 2):  # one Spark goes on sending samples, without a reading of its GPU power
            feed_power(hub, clock, start, second, {"dgx0": 30.0, "dgx1": None})
            hub.view()
        hub.external_run = {"name": "Job 2", "started": start + 240}
        hub.view()
        ended = hub.runs_view()["runs"][0]
        assert round(ended["gpu_wh"], 9) == 4.0, ended  # 3 Wh of both in two minutes, 1 Wh of the one in two more
        # read: 240 s of one Spark and 120 s of the other. Not read: 120 s of that one, 240 s each of the two Sparks
        # that sent no sample at all
        assert (ended["gpu_read_s"], ended["gpu_gap_s"], ended["gpu_from"], ended["sparks"]) == (360.0, 600.0, 2, 4), (
            ended
        )


def test_the_gpu_energy_of_a_run_is_that_of_the_moment_it_ended():
    hub = hub_for()
    with Clock() as clock:
        start = clock.now
        feed_power(hub, clock, start, 0, {"dgx0": 36.0})
        hub.external_run = {"name": "Job 1", "started": start}
        hub.view()
        for second in range(2, 102, 2):
            feed_power(hub, clock, start, second, {"dgx0": 36.0})
            hub.external_run = None if second >= 60 else hub.external_run  # no run named from 60 s on
            hub.view()
        ended = hub.runs_view()["runs"][0]
        assert (ended["ended"], round(ended["gpu_wh"], 9), ended["gpu_read_s"]) == (start + 60, 0.6, 60.0), ended
        assert ended["gpu_gap_s"] == 180.0  # the three Sparks nobody read, for the minute of the run: not for more


def test_a_run_of_single_tracks_has_no_count_of_the_ring_engine():
    """In a run of single tracks every Spark serves a model of its own: the tokens of that run are written by
    those engines, which no record counts yet. What the ring engine counts meanwhile is not the run's. With its
    last reading two seconds before such a run and its next at the end, the record said "0 tokens" for a minute
    in which three engines wrote: the record now says how many tracks the source named, and counts no tokens."""
    hub = hub_for()
    silent = {"engine": None, "engine_error": "Nothing answers on the vLLM port."}
    with Clock() as clock:
        start = clock.now
        feed_engine(hub, clock, start, -2, 5000.0)
        clock.now = start
        hub.ingest("dgx0", {"t": start, **silent})
        tracks = [{"node": name, "name": "Job 4", "done": 1, "total": 7} for name in ("dgx1", "dgx2", "dgx3")]
        hub.external_run = {"name": "Single tracks", "tracks": tracks}
        hub.view()
        clock.now = start + 30
        hub.ingest("dgx0", {"t": start + 30, **silent})
        hub.view()
        feed_engine(hub, clock, start, 60, 5000.0)  # the ring engine answers again as the tracks end
        hub.external_run = {"name": "Job 9", "started": start + 60}
        hub.view()
        ended = hub.runs_view()["runs"][0]
        counted = (ended["tracks"], ended["tokens"], ended["engine_steps"], ended["tok_s_peak"], ended["lives"])
        assert counted == (3, None, None, None, 0), ended  # was 0.0 tokens in one life
        assert hub.runs_view()["open"]["tracks"] is None  # a run on the ring engine names no tracks


def stored_hub(path):
    """A hub on a history file, as ringtop starts one: with what that file holds."""
    hub = Hub(parse_cluster(ring_map()), 2.0, store=Store(path, 2.0))
    hub.engine_error = None
    return hub


def beat(hub, clock, start, second, tokens, job):
    """One interval of a ring whose head alone is read: its sample with the engine's count and 36 W of GPU power,
    what the run source names, and the look of the ticker."""
    clock.now = start + second
    hub.ingest("dgx0", {**engine_sample(start + second, tokens), "fabric": {}, "gpu": {"w": 36.0}})
    hub.external_run = job and {"name": job, "started": start}
    hub.view()


def test_a_run_goes_on_under_its_id_when_ringtop_was_restarted_while_it_ran():
    """Every restart of ringtop forgot the run that was running: it stood as "Started" a second time, eleven times
    in two days. The record of the open run is written to the history when the run starts and every minute, and
    a start on that history finds it. When the source then names that run again, it goes on under its id, and
    nothing is said. Its sums stand as they were last saved; from that save until ringtop is back nobody counted,
    and the record says so as a gap, for the tokens and for every Spark that was read."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 72, 2):
            beat(hub, clock, start, second, 1000.0 + 20 * second, "Job 1")
        before = hub.runs_view()["open"]
        assert (before["tokens"], before["saved"]) == (1400.0, start + 60), before  # saved at its start and at 60 s
        hub.store.flush()  # ringtop stops here, ten seconds after its last save
        clock.now = start + 79
        back = stored_hub(path)
        found = back.runs_view()["open"]
        assert (found["id"], found["tokens"], round(found["gpu_wh"], 9)) == (before["id"], 1200.0, 0.6), found
        for second in range(80, 92, 2):
            beat(back, clock, start, second, 1000.0 + 20 * second, "Job 1")
        assert run_events(back) == ["Started: Job 1"], run_events(back)  # was said a second time
        on = back.runs_view()["open"]
        assert (on["id"], on["first_seen"], on["counted_from"]) == (before["id"], start, start + 80), on
        assert (on["tokens"], on["token_s"], on["token_gap_s"], on["lives"]) == (1400.0, 70.0, 20.0, 1), on
        assert (round(on["gpu_wh"], 9), on["gpu_read_s"], on["gpu_gap_s"], on["gpu_from"]) == (0.7, 70.0, 20.0, 1), on
        beat(back, clock, start, 92, 2840.0, "Job 2")
        ended = back.runs_view()["runs"][0]
        assert (ended["id"], ended["ended"], ended["tokens"]) == (before["id"], start + 92, 1440.0), ended
        assert ended["gpu_gap_s"] == 20.0 + 3 * 92.0  # and the three Sparks nobody read, for all of the run
        assert run_events(back) == ["Started: Job 1", "Finished: Job 1", "Started: Job 2"], run_events(back)
        back.store.flush()
        assert [(r["name"], r["open"]) for r in Store(path, 2.0).saved_runs(5)] == [("Job 2", True), ("Job 1", False)]


def test_a_run_that_was_gone_when_ringtop_came_back_has_no_end_anybody_saw():
    """A run that ended while ringtop was away was not seen to end. Its record is closed without an end and without
    an event: it says when its source last named it, and its sums are those of its last save."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 12, 2):
            beat(hub, clock, start, second, 1000.0 + 20 * second, "Job 1")
        hub.store.flush()
        clock.now = start + 600
        back = stored_hub(path)
        assert back.runs_view()["open"]["name"] == "Job 1"
        for second in (600, 610, 620, 630):  # the source is heard and names no run
            beat(back, clock, start, second, 9000.0, None)
        told = back.runs_view()
        gone = told["runs"][0]
        assert told["open"] is None and (gone["name"], gone["open"], gone["ended"]) == ("Job 1", False, None), gone
        assert (gone["last_heard"], gone["tokens"]) == (start, None), gone  # as saved at its start
        assert run_events(back) == ["Started: Job 1"], run_events(back)  # no "Finished" nobody saw
        back.store.flush()
        assert Store(path, 2.0).saved_runs(5)[0]["open"] is False


def test_a_run_without_a_start_is_not_taken_up_again_after_a_restart():
    """Whether a run named after a restart is the one from before is told by its start. A run whose source gives
    none (single tracks) cannot be told from another of that name hours later: its record is closed at the start
    of ringtop, without an end, and the run named then is a new one."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        hub.external_run = {"name": "Single tracks", "tracks": [{"node": "dgx1", "name": "Job 4"}]}
        hub.view()
        first = hub.runs_view()["open"]["id"]
        hub.store.flush()
        clock.now = start + 20
        back = stored_hub(path)
        told = back.runs_view()
        assert told["open"] is None and (told["runs"][0]["id"], told["runs"][0]["ended"]) == (first, None), told
        back.external_run = {"name": "Single tracks", "tracks": [{"node": "dgx1", "name": "Job 4"}]}
        back.view()
        assert back.runs_view()["open"]["id"] == round((start + 20) * 1000) != first
        assert run_events(back) == ["Started: Single tracks", "Started: Single tracks"]


def test_a_number_of_the_run_source_no_float_holds_does_not_fail_a_look():
    """A run command that writes a count of hundreds of digits failed every look at the hub: the page stood still.
    Such a count is unknown, like one that is a text: the look goes through, and the record holds none."""
    hub = hub_for()
    huge = "1" + "0" * 400
    step = '{"name":"a","state":"done","seconds":' + huge + ',"was":' + huge + "}"
    said = '{"name":"Job 1","started":1000.5,"done":' + huge + ',"total":' + huge + ',"steps":[' + step + "]}"
    with hub.lock:
        hub.external_run = parse_runs(said)
    assert hub.view()["run"]["name"] == "Job 1"
    record = hub.runs_view()["open"]
    assert (record["done"], record["total"], record["steps"]) == (None, None, [{"name": "a", "state": "done"}]), record


def test_a_row_of_the_table_of_runs_that_is_no_record_does_not_stop_the_start():
    """A start reads the table of runs and trusted every row of it: a row `{}`, `null`, or a record without one of
    its fields stopped the hub with a KeyError or a TypeError, and ringtop did not come up. Today only ringtop
    writes those rows; the day the shape of a record changes, an older or a newer stand finds rows it cannot read.
    Such a row is passed over and said, in one line on stdout for all of them. The hub starts with the records it
    can read, the newest of them may still be the run that goes on, and the rows stay in the file as they are."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 12, 2):
            beat(hub, clock, start, second, 1000.0 + 20 * second, "Job 1")
        beat(hub, clock, start, 12, 1240.0, "Job 2")  # Job 1 has ended, Job 2 is open
        hub.store.flush()
        whole = Store(path, 2.0).saved_runs(5)[0]
        assert (whole["name"], whole["open"]) == ("Job 2", True), whole
        odd = ["{}", "null", "[1, 2]", '"a text"', "no json {", ""]
        odd += [json.dumps({key: value for key, value in whole.items() if key != "started"})]
        odd += [json.dumps({**whole, **wrong}) for wrong in ({"first_seen": "soon"}, {"open": "yes"}, {"id": True})]
        odd += [json.dumps({**whole, **wrong}) for wrong in ({"gpu_gap_s": None}, {"name": ""}, {"tokens": "many"})]
        db = sqlite3.connect(path)
        for k, text in enumerate(odd):  # each newer than every record, and marked as open
            db.execute("INSERT INTO runs VALUES (?,?,?,?)", (9_000_000_000_000 + k, start + 100 + k, 1, text))
        db.commit()
        db.close()
        clock.now = start + 20
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            back = stored_hub(path)
        told = back.runs_view()
        assert told["open"]["name"] == "Job 2" and [r["name"] for r in told["runs"]] == ["Job 1"], told
        said = out.getvalue().splitlines()
        assert len(said) == 1 and said[0].startswith("ringtop: ") and f"{len(odd)} rows" in said[0], said
        assert err.getvalue() == "", err.getvalue()
        beat(back, clock, start, 22, 1500.0, "Job 2")  # the run that was open goes on under its id, unsaid
        assert run_events(back) == ["Started: Job 1", "Finished: Job 1", "Started: Job 2"], run_events(back)
        assert back.runs_view()["open"]["id"] == whole["id"]
        back.store.flush()
        db = sqlite3.connect(path)
        kept = [text for (text,) in db.execute("SELECT d FROM runs WHERE id >= 9000000000000 ORDER BY id")]
        rows = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        db.close()
        assert kept == odd and rows == len(odd) + 2, (rows, kept)  # nothing was deleted, nothing rewritten


def test_a_start_of_tomorrow_named_by_a_source_does_not_hide_the_run_that_is_open():
    """A start on a history takes the newest record for the run that may still go on. Newest was told by the start
    a source names: a run whose source once named a start of tomorrow stood first from then on, and the run that
    really was open when ringtop stopped was closed without an end and said as started a second time. Newest is
    what ringtop saw last."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now

        def look(hub, second, job, started):
            clock.now = start + second
            hub.ingest(
                "dgx0", {**engine_sample(start + second, 1000.0 + 20 * second), "fabric": {}, "gpu": {"w": 36.0}}
            )
            hub.external_run = {"name": job, "started": started}
            hub.view()

        hub = stored_hub(path)
        look(hub, 0, "Job 1", start + 86400.0)  # the clock of its source is a day ahead
        look(hub, 2, "Job 1", start + 86400.0)
        look(hub, 4, "Job 2", start + 4.0)  # Job 1 has ended, Job 2 is open
        hub.store.flush()
        saved = Store(path, 2.0).saved_runs(5)
        assert [(r["name"], r["open"], r["started"]) for r in saved] == [
            ("Job 2", True, start + 4.0),
            ("Job 1", False, start + 86400.0),  # the start its source named stays what it said
        ], saved
        clock.now = start + 10
        back = stored_hub(path)
        assert back.runs_view()["open"]["name"] == "Job 2", back.runs_view()
        look(back, 12, "Job 2", start + 4.0)
        assert run_events(back) == ["Started: Job 1", "Finished: Job 1", "Started: Job 2"], run_events(back)
