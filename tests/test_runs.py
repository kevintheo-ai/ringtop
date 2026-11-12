"""Which run is running: what counts as a run a source names, and when that is the run known before."""

import json

from ringtop_parts.core.cluster import parse_runs
from ringtop_parts.core.runs import RUN_QUIET, RUN_SAME, count_of, is_record, named, same_run, step, told
from tests.fixtures import hub_for


def test_only_a_run_source_names_a_run():
    """The page shows something as running at every moment: what the run command or the lab queue names, a
    benchmark the head found, the engine serving, a source that failed, or nothing. Only the first two are runs
    somebody outside named; a start that is no moment is no start."""
    job = {"source": "command", "name": "Job 1", "started": 100.0, "group": "Queue 9", "done": 3}
    assert named(job) == {"source": "command", "name": "Job 1", "started": 100.0}
    assert named({"source": "lab", "name": "step 2", "steps": []})["started"] is None
    assert named({"source": "command", "name": "Job 1", "started": float("nan")})["started"] is None
    for other in ("process", "engine", "error", "none"):
        assert named({"source": other, "name": "Benchmark running", "started": 100.0}) is None, other
    assert named({"source": "command"}) is None and named({"source": "lab", "name": ""}) is None


def test_a_name_that_is_no_text_names_no_run():
    """The name of a run is the word of a command outside, or of the head. A name that was a list, a number or an
    object passed as one: the hub opened a record under it, said "Started: ['nightly']" and wrote the record to the
    history, and the next start read that row as no record, since a record has a text for a name (is_record). The
    run was missing from the list and did not go on. Only a text that says something names a run, and the record
    the hub opens for it is one this program reads. The run command is refused such a run where it is read
    (parse_runs: the source has failed); one that reaches the hub another way names none."""
    for odd in (["nightly"], {"job": 1}, 7, 2.5, True, float("nan"), "", None):
        assert named({"source": "command", "name": odd, "started": 100.0}) is None, odd
        assert named({"source": "lab", "name": odd}) is None, odd
    hub = hub_for()
    for said in ('{"name":["nightly"],"started":1000.5}', '{"name":{"job":1}}', '{"name":7}', '{"name":NaN}'):
        try:
            parse_runs(said)  # as the run command prints it
        except ValueError:
            pass
        else:
            raise AssertionError(f"took {said} as a run")
        with hub.lock:
            hub.external_run = json.loads(said)
        hub.view()
        assert hub.runs_view() == {"open": None, "runs": []}, said
        assert [e["text"] for e in hub.events if e["kind"] == "run"] == [], said
    with hub.lock:
        hub.external_run = parse_runs('{"name":"nightly","started":1000.5}')
    hub.view()
    record = hub.runs_view()["open"]
    assert record["name"] == "nightly" and is_record(record), record


def test_the_same_run_is_the_same_source_and_name_with_a_start_that_moved_by_less_than_half_a_minute():
    known = {"source": "command", "name": "Job 1", "started": 1000.0}
    assert RUN_SAME == 30.0
    for start, same in ((1000.0, True), (1005.0, True), (995.0, True), (1029.9, True), (1030.0, False), (970.0, False)):
        assert same_run(known, {**known, "started": start}) is same, start
    assert same_run(known, {**known, "started": None})  # a source that gives no start says nothing against it
    assert same_run({**known, "started": None}, known)
    assert not same_run(known, {**known, "name": "Job 2"})
    assert not same_run(known, {**known, "source": "lab"})  # the same name from another source is another run


def test_one_look_at_the_source_starts_a_run_leaves_it_or_ends_it():
    """Every way one look at a run source can go: the run that is open after it, the moment the one known before
    ended, and whether the open one has only just started."""
    job = {"source": "command", "name": "Job 1", "started": 1000.0}
    assert RUN_QUIET == 30.0 and step(None, None, True, 5.0) == (None, None, False)
    run, ended, started = step(None, job, False, 1000.0)
    assert run == {**job, "quiet": None} and ended is None and started
    run, ended, started = step(run, {**job, "started": 1005.0}, True, 1010.0)  # named again, its start 5 s on
    assert run["started"] == 1005.0 and (ended, started) == (None, False)
    assert step(run, {**job, "started": None}, True, 1020.0)[0]["started"] == 1005.0  # no start given: the known one
    assert step(run, None, False, 2000.0) == (run, None, False)  # not heard: nothing is known
    quiet, ended, started = step(run, None, True, 2000.0)  # heard, and it names no run
    assert quiet == {**run, "quiet": 2000.0} and (ended, started) == (None, False)
    assert step(quiet, None, True, 2029.9) == (quiet, None, False)
    assert step(quiet, None, False, 2100.0) == (quiet, None, False)  # not heard meanwhile: still nothing known
    assert step(quiet, None, True, 2030.0) == (None, 2000.0, False)  # believed: it ended when that was first said
    back, ended, started = step(quiet, job, True, 2020.0)  # named again in time: nothing happened
    assert back == {**run, "started": 1000.0} and (ended, started) == (None, False)  # by the start named last
    other = {"source": "command", "name": "Job 2", "started": 2010.0}
    assert step(run, other, True, 2010.0) == ({**other, "quiet": None}, 2010.0, True)  # another run: ended now
    assert step(quiet, other, True, 2010.0) == ({**other, "quiet": None}, 2000.0, True)  # or when it fell quiet
    again = {**job, "started": 1900.0}  # the same job with a start far from the known one: begun anew
    assert step(run, again, True, 1900.0) == ({**again, "quiet": None}, 1900.0, True)


def test_a_count_of_a_run_source_that_is_no_finite_number_is_none():
    """How far a run is, and how long a station took, come from a command outside. What it gives as a count is kept
    where it is a finite number. A whole number of hundreds of digits is none: no float holds it, and counting with
    it would fail. Neither is yes or no, or a text."""
    huge = 10**400
    assert [count_of(value) for value in (3, 2.5, huge, -huge, True, "3", None)] == [
        3,
        2.5,
        None,
        None,
        None,
        None,
        None,
    ]
    said = told({"group": "Queue 9", "done": huge, "total": 24, "steps": [{"name": "a", "seconds": huge, "was": 5}]})
    assert (said["done"], said["total"], said["steps"]) == (None, 24, [{"name": "a", "was": 5}]), said
    assert named({"source": "command", "name": "Job 1", "started": huge})["started"] is None
