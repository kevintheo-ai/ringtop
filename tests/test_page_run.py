"""The run on both pages, driven without a browser: how far it is, and what stands where its count was not read."""

import json

from ringtop_parts.core.cluster import parse_runs
from ringtop_parts.core.wall import wall_moment
from tests.fixtures import hub_for, needs_node
from tests.test_page_sheet import sheet
from tests.test_page_wall import SAID, moments, wall

# What both pages say of how far the run is: the count, whether the bar is hidden, and how wide it is filled; on the
# main page the head of nerd mode says the count once more.
PANEL = "[$('#run-count').text, $('#run-track').hidden, $('#run-fill').style.width, $('#n-step').text]"


def run_of(**counts):
    """A run as a run command names it, with the counts it gives: `total`, `done`, both or none."""
    return {"source": "command", "name": "Sweep", **counts}


@needs_node
def test_a_run_whose_count_nobody_read_says_a_dash_and_shows_no_bar_on_the_main_page():
    """A run source may say how much there is to do and not how far it is: `total` without `done`. The run panel
    and the head of nerd mode said "0 of 24" then, and the panel drew a bar filled to 0 %: a count nobody read,
    shown as none done. What was not read is a dash, and no bar stands for it; a count that was read as 0 is
    "0 of 24" with an empty bar, as before."""
    say = "server.say({{ ...LIVE, t: LIVE.t + {at}, run: {run} }}); " + PANEL
    got = sheet(
        [
            "Nerd.toggle(true); null",
            say.format(at=2, run=json.dumps(run_of(total=24))),
            say.format(at=4, run=json.dumps(run_of(total=24, done=0))),
            say.format(at=6, run=json.dumps(run_of(total=24, done=6))),
            say.format(at=8, run=json.dumps(run_of(total=24, done=None))),
            say.format(at=10, run=json.dumps(run_of(done=6))),
        ]
    )
    assert got[1][:2] == ["– of 24", True] and got[1][3] == "– of 24", got[1]  # was "0 of 24" with a bar, twice
    assert got[2] == ["0 of 24", False, "0.0%", "0 of 24"], got[2]
    assert got[3] == ["6 of 24", False, "25.0%", "6 of 24"], got[3]
    assert got[4] == ["– of 24", True, "25.0%", "– of 24"], got[4]  # hidden, whatever it was last as wide as
    assert got[5] == ["6 done", True, "25.0%", ""], got[5]  # no total: how far of how much, nobody can say


@needs_node
def test_a_run_whose_count_nobody_read_says_a_dash_and_shows_no_bar_on_the_calm_page():
    """The calm page writes the run as the main page does, and wrote "0 of 24" beside a bar filled to 0 % for a run
    whose count was not read. A wall gets such a run without `done`, or with None in its place where the source
    wrote something that is no number: both are a dash, and no bar."""
    writing = moments()["writing"]
    first = {**writing, "run": {**run_of(total=24), "started": writing["t"] - 60}}
    later = [
        {**first, "t": first["t"] + 2 * (k + 1), "run": {**first["run"], **counts}}
        for k, counts in enumerate(({"done": 0}, {"done": 6}, {"done": None}))
    ]
    got = [said["run"] for said in wall([SAID, *(f"server.say({json.dumps(m)}); {SAID}" for m in later)], first=first)]
    assert got[0] == ["Sweep", "– of 24", True, None, "60 s in"], got[0]  # was "0 of 24" with a bar
    assert got[1] == ["Sweep", "0 of 24", False, "0.0%", "62 s in"], got[1]
    assert got[2][:4] == ["Sweep", "6 of 24", False, "25.0%"] and got[2][4].startswith("64 s in, about "), got[2]
    assert got[3] == ["Sweep", "– of 24", True, "25.0%", "66 s in"], got[3]


@needs_node
def test_a_count_a_run_command_names_as_no_number_is_one_nobody_read_on_every_page():
    """A run command that printed how far its run is as a text, a yes or a list got it onto the main page as it came:
    the run panel said "NaN of 24" with a bar filled "NaN%" of a text, "1 of 24" of a yes, "3 of 24" of a list, and
    the head of nerd mode with it; a total as a yes was "6 of 1" with a full bar. The hub now leaves out what is no
    number where it reads the command (parse_runs), so every page says what it says of a count the command does
    not name: a dash and no bar for how far, how many are done for how much. The calm page said so already, for a
    wall gets no figure that is no number."""
    hub = hub_for()

    def shown(text):
        """The run of the moment the hub gives while the run command prints `text`."""
        with hub.lock:
            hub.external_run = parse_runs(text)
        return hub.view()["run"]

    runs = [shown('{"name":"Sweep","total":24,"done":' + odd + "}") for odd in ('"x"', "true", "[3]", '"6"')]
    runs += [shown('{"name":"Sweep","done":6,"total":' + odd + "}") for odd in ('"24"', "true", '"x"')]
    say = "server.say({{ ...LIVE, t: LIVE.t + {at}, run: {run} }}); " + PANEL
    main = sheet(
        ["Nerd.toggle(true); null", *(say.format(at=2 * k + 2, run=json.dumps(r)) for k, r in enumerate(runs))]
    )
    told = [[count, hidden, head] for count, hidden, _, head in main[1:]]
    # was "NaN of 24" with a bar "NaN%", "1 of 24", "3 of 24" and "6 of 24" with bars
    assert told[:4] == [["– of 24", True, "– of 24"]] * 4, told
    # was "6 of 24" with a bar, "6 of 1" with a full bar, and "6 done" with "6 of NaN" in the head of nerd mode
    assert told[4:] == [["6 done", True, ""]] * 3, told
    writing = moments()["writing"]
    # as a wall gets the moment, each later than the one before: a moment whose time does not rise is not shown
    walls = [wall_moment({**writing, "t": writing["t"] + 2 * k, "run": r}) for k, r in enumerate(runs)]
    calm = [
        said["run"][1:3]
        for said in wall([SAID, *(f"server.say({json.dumps(m)}); {SAID}" for m in walls[1:])], first=walls[0])
    ]
    assert calm == [["– of 24", True]] * 4 + [["6 done", True]] * 3, calm


@needs_node
def test_a_queue_of_more_than_64_stations_reaches_the_page_whole():
    """The hub cleans the stations a run command names, and kept 64 of them: behind station 64 the run panel said
    "step 64 of 64", and the station that runs and every one that waits were missing from its dots and from the head
    of nerd mode. Every station the command names reaches the page, so the count and the station that runs are the
    ones of the queue."""
    steps = [
        {"name": f"Station {k}", "state": "done" if k < 66 else "running" if k == 66 else "pending"}
        for k in range(1, 71)
    ]
    hub = hub_for()
    with hub.lock:
        hub.external_run = parse_runs(json.dumps({"name": "Sweep", "group": "Queue 9", "steps": steps}))
    run = hub.view()["run"]
    seen = sheet(
        [
            "Nerd.toggle(true); null",
            f"server.say({{ ...LIVE, t: LIVE.t + 2, run: {json.dumps(run)} }});"
            " [$('#run-next').text, $('#n-step').text, $('#stations').children.map(li => li.title)]",
        ]
    )
    line, head, dots = seen[1]
    assert line == "Queue 9: step 66 of 70, next Station 67", line  # was "Queue 9: step 64 of 64"
    assert head == "step 66 of 70: Station 66", head  # was "step 64 of 64"
    assert len(dots) == 70 and dots[65] == "Station 66: running now" and dots[69] == "Station 70: waiting", dots
