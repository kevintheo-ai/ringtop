"""The runs of the page, run through node: the records under neutral names, and what a card says of a record."""

import json
import subprocess
import tempfile

from ringtop_parts.connect.server import PAGE
from ringtop_parts.core.cluster import parse_runs
from tests.fixtures import hub_for, needs_node
from tests.test_page_measure import measure
from tests.test_page_sheet import sheet


def card(script: str):
    """Runs the rules of the page, its rules of measurement, its neutral lens and the card of a run through node and
    gives back what `script` returns. The files are the ones the server sends, on their own: a rule of the card that
    reached for the page would fail."""
    parts = [(PAGE.parent / name).read_text() for name in ("rules.js", "measure.js", "neutral.js", "runcard.js")]
    source = "\n".join(parts) + "\nconsole.log(JSON.stringify((() => {" + RECORD + script + "})()));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js") as file:
        file.write(source)
        file.flush()
        done = subprocess.run(["node", file.name], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout)


RECORD = """
const record = { id: 5, source: 'command', name: 'Job A, round 9', group: 'Queue 9', started: 1000, first_seen: 1005,
  last_heard: 1595, counted_from: 1005, saved: 1560, ended: 1600, open: false, done: 24, total: 24, tracks: null,
  steps: [{ name: 'Job B', state: 'done', seconds: 61, was: 58 }, { name: 'Job A', state: 'running' }],
  model: 'model-a', image: 'registry/image:1', sparks: 4, tokens: 24000, engine_steps: 8000, token_s: 596, token_gap_s: 0,
  lives: 1, tok_s_peak: 61.5, gpu_wh: 12.345, gpu_read_s: 2380, gpu_gap_s: 0, gpu_from: 4 };
"""


@needs_node
def test_with_neutral_names_the_record_of_a_run_keeps_no_word_of_its_source():
    """The name of a run, the queue it belongs to and the names of its stations are words a run source wrote. Under
    neutral names a record keeps none of them: the run is "Test run", its stations are counted through, the queue
    is gone. What it counted stays, and so do the model and the image, as in the head of the page: they pass the
    renamer of the page like every text there, so a Spark named inside one of them reads as its neutral name. The
    answer that came is not changed."""
    got = measure(
        RECORD
        + """
        const answer = { open: { ...record, id: 6, open: true, ended: null }, runs: [record] }, before = JSON.stringify(answer);
        const named = { open: null, runs: [{ ...record, model: 'models/dgx3/llm-a', image: 'dgx3:5000/vllm:1' }, { ...record, model: null, image: 7 }] };
        return [neutralRuns(answer), JSON.stringify(answer) === before, neutralRuns({ open: null, runs: [] }),
          neutralRuns(named, renamer([['dgx3', 'spark-4']])).runs.map(r => [r.model, r.image])];"""
    )
    neutral, untouched, empty, renamed = got
    assert untouched and empty == {"open": None, "runs": []}
    # a Spark inside the model or the image goes by its neutral name; what is no text stays what it is
    assert renamed == [["models/spark-4/llm-a", "spark-4:5000/vllm:1"], [None, 7]], renamed
    for record in (neutral["open"], neutral["runs"][0]):
        assert (record["name"], record["group"]) == ("Test run", None), record
        assert record["steps"] == [
            {"name": "Test run 1", "state": "done", "seconds": 61, "was": 58},
            {"name": "Test run 2", "state": "running"},
        ], record["steps"]
        assert (record["tokens"], record["gpu_wh"], record["model"], record["image"]) == (
            24000,
            12.345,
            "model-a",
            "registry/image:1",
        )
    assert (neutral["open"]["id"], neutral["open"]["open"], neutral["runs"][0]["ended"]) == (6, True, 1600)
    for word in ("Job A", "round 9", "Queue 9", "Job B"):
        assert word not in json.dumps(neutral), word


@needs_node
def test_the_card_of_a_run_says_how_long_how_fast_how_many_tokens_and_how_much_gpu_energy():
    """Four figures, in the form of the figures at the head of a Spark: the duration from the start its source named
    to its end, the mean speed (tokens over the seconds they were counted in) with the peak in its note, the tokens
    written, and the GPU energy in watt hours with how many Sparks it was read from. A run that was read whole
    carries no state on any of them. What the box says of how the energy is counted names where the power comes
    from and that it is the GPU's alone, how far apart the samples lie and from when on they are a gap, and the
    two edges of a run: what the first sample of a Spark stands for, and that nothing is counted after the last."""
    figs, texts, clock, energy = card(
        "return [runFigures(record, 5000), RUN_TEXTS, [runWhen(1000, true), runWhen(1600, false)], RUN_TEXTS.energyOf('2', '15')];"
    )
    for fact in ("GPU", "nvidia-smi", "2 s", "15 s", "wall socket", "Wh", "first", "last"):
        assert fact in energy, (fact, energy)
    assert [f["what"] for f in figs] == ["duration", "tokens per second", "tokens written", "GPU energy"], figs
    assert [(f["value"], f["unit"]) for f in figs] == [
        ("10 min", ""),
        ("40", "tok/s"),
        ("24,000", ""),
        ("12.3", "Wh"),
    ], figs
    assert [f["state"] for f in figs] == ["", "", "", ""], figs
    assert clock[0] in figs[0]["note"] and clock[1] in figs[0]["note"], figs[0]  # from when to when, on the local clock
    assert "62" in figs[1]["note"] and "4" in figs[3]["note"] and "GPU" in figs[3]["note"], (
        figs
    )  # the peak; all 4 Sparks
    assert set(texts) >= {"duration", "speed", "tokens", "energy"}


@needs_node
def test_what_a_run_did_not_measure_is_a_dash_with_its_reason_and_never_a_zero():
    """A run of single tracks has no count of tokens; a run whose GPU power nobody read has no energy; a run nobody
    saw end has no duration. Each is a dash with the reason as its note. None of them is a 0, and no figure of any
    record reads NaN, null or undefined."""
    tracks, unread, unseen = card(
        """
        const sums = { tokens: null, engine_steps: null, token_s: 0, token_gap_s: 0, lives: 0, tok_s_peak: null };
        const tracks = runFigures({ ...record, ...sums, tracks: 3 }, 5000);
        const unread = runFigures({ ...record, ...sums, gpu_wh: null, gpu_read_s: 0, gpu_gap_s: 2400, gpu_from: 0 }, 5000);
        const unseen = runFigures({ ...record, ended: null }, 5000);
        return [tracks, unread, unseen];"""
    )
    assert [f["value"] for f in tracks] == ["10 min", "–", "–", "12.3"], tracks
    assert "3 Sparks" in tracks[1]["note"] and tracks[1]["note"] == tracks[2]["note"], tracks  # why: they served alone
    assert [f["value"] for f in unread] == ["10 min", "–", "–", "–"], unread
    assert "ring engine" in unread[1]["note"] and "GPU power" in unread[3]["note"], unread
    assert unseen[0]["value"] == "–" and unseen[0]["state"] == "warn" and unseen[1]["value"] == "40", unseen
    for figs in (tracks, unread, unseen):
        for fig in figs:
            assert fig["value"] not in ("0", "0.00") and not any(
                w in fig["value"] + fig["note"] for w in ("NaN", "null", "undefined")
            ), fig


@needs_node
def test_a_figure_that_covers_a_part_of_its_run_says_how_much():
    """Energy read from three of four Sparks is three quarters of the Spark time; tokens counted over 596 of 656
    seconds are 90 %; an engine that restarted is said. Each such figure carries a state, so its note stays in
    sight. A part is never said to be all: 99.9 % reads 99 %."""
    part, nearly, shares, open_run = card(
        """
        const part = { ...record, gpu_from: 3, gpu_read_s: 1800, gpu_gap_s: 600, token_gap_s: 60, lives: 2 };
        const nearly = { ...record, gpu_gap_s: 1 };
        const open = { ...record, open: true, ended: null, gpu_from: 3, gpu_read_s: 1200, gpu_gap_s: 0 };  // still running at 1405: one Spark never read
        return [runFigures(part, 5000), runFigures(nearly, 5000), runShares(part, 5000), runFigures(open, 1405)];"""
    )
    assert shares == {"tokens": 596 / 656, "energy": 0.75}, shares
    assert [f["state"] for f in part] == ["", "", "warn", "warn"], part
    assert "90 %" in part[2]["note"] and "once" in part[2]["note"], part[2]
    assert "3 of 4" in part[3]["note"] and "75 %" in part[3]["note"] and "GPU" in part[3]["note"], part[3]
    assert nearly[3]["state"] == "warn" and "99 %" in nearly[3]["note"], nearly[3]
    assert open_run[0]["value"] == "405 s" or open_run[0]["value"] == "7 min", open_run[0]  # so far, from its start
    assert open_run[3]["state"] == "warn" and "3 of 4" in open_run[3]["note"] and "75 %" in open_run[3]["note"], (
        open_run[3]
    )


@needs_node
def test_a_run_nobody_saw_end_counts_a_spark_that_was_never_read_as_not_read():
    """A Spark that was never read in a run was not read for all of it. The server says so as a gap where it sees a
    run end, and the card adds it for a run that is open. A run nobody saw end got neither: ringtop was restarted
    while it ran and its source never named it again, so its record was closed as it was last saved. Its card said
    "read from 3 of 4 Sparks, 100 % of Spark-seconds". The card adds the Spark for such a run too, for the time up
    to the moment its source last named the run. To a run whose end was seen it adds nothing: the server said it."""
    shares, unseen, ended = card(
        """
        const part = { gpu_from: 3, gpu_read_s: 1200, gpu_gap_s: 0, last_heard: 1405 };  // three of four Sparks, read for 400 s each
        const unseen = { ...record, ...part, ended: null }, open = { ...unseen, open: true };
        const ended = { ...record, ...part, ended: 1405, gpu_gap_s: 400 };  // seen to end: the server has said the fourth Spark
        return [[runShares(unseen, 5000), runShares(open, 1405), runShares(ended, 5000)].map(share => share.energy),
          runFigures(unseen, 5000)[3], runFigures(ended, 5000)[3]];"""
    )
    assert shares == [0.75, 0.75, 0.75], shares  # was 1 for the run nobody saw end
    for fig in (unseen, ended):
        assert fig["state"] == "warn" and "3 of 4" in fig["note"] and "75 %" in fig["note"], fig


@needs_node
def test_the_card_says_a_part_for_tokens_nobody_counted_around_a_restart_of_ringtop():
    """Two runs of 330 s ringtop was restarted in, as the hub records them (tests/test_hub_runs_away.py): the ring
    engine counted for 180 s and never read again after the restart, and the ring engine first read 240 s in, after
    the restart. Their records hold the unread time as a gap, so the figure of the tokens says its part and
    carries the mark: 54 % and 27 %. With the gaps the hub wrote before, the card said 79 % for the first and
    nothing of a part for the second."""
    now, before = card(
        """
        const run = { ...record, started: 1000, first_seen: 1000, counted_from: 1226, last_heard: 1328, ended: 1330, lives: 1 };
        const never = { ...run, tokens: 3600, token_s: 180 }, late = { ...run, tokens: 1800, token_s: 90 };
        const tokens = (r, gap) => runFigures({ ...r, token_gap_s: gap }, 5000)[2];
        return [[tokens(never, 150), tokens(late, 240)], [tokens(never, 46), tokens(late, 0)]];"""
    )
    assert [(fig["state"], fig["value"]) for fig in now] == [("warn", "3,600"), ("warn", "1,800")], now
    assert "54 %" in now[0]["note"] and "27 %" in now[1]["note"], now
    assert "79 %" in before[0]["note"] and (before[1]["state"], before[1]["note"]) == ("", ""), before


@needs_node
def test_the_card_says_what_happened_to_the_run_beside_its_figures():
    """An open run whose source nobody heard for more than a minute, a run ringtop was restarted in, and a run
    ringtop first saw long after it began: each is one sentence in sight. A run without any of it has none."""
    plain, unheard, away, late, states = card(
        """
        const open = { ...record, open: true, ended: null };
        return [runNotes(record, 5000), runNotes({ ...open, last_heard: 4000 }, 5000), runNotes({ ...record, counted_from: 1300 }, 5000),
          runNotes({ ...record, first_seen: 1400, counted_from: 1400 }, 5000), [runState(record), runState(open), runState({ ...record, ended: null })]];"""
    )
    assert plain == [] and len(unheard) == 1 and len(away) == 1 and len(late) == 1, (plain, unheard, away, late)
    assert "source" in unheard[0] and "restarted" in away[0] and "first saw" in late[0]
    assert states[1:] == ["running", "end not seen"] and states[0].startswith("ended "), states


@needs_node
def test_what_the_box_says_of_a_run_names_its_model_and_image_only_on_the_page_with_real_names():
    """Beside its figures the box says of a run how far it got, how many steps its queue has, which model ran on
    which image, and what it counted per step and per token. For the page with neutral names the sentence about
    model and image is left out, and nothing else: the box shows runs of the past too, and the model of an earlier
    run has no place in a picture of the page that was made to be shown."""
    real, neutral, texts = card(
        "return [runFacts(record, 5000), runFacts(record, 5000, true), [RUN_TEXTS.ran('model-a', 'registry/image:1'), RUN_TEXTS.done('24', '24')]];"
    )
    ran, done = texts
    assert ran in real and done in real, real
    assert neutral == real.replace(ran + " ", ""), (real, neutral)  # that one sentence less
    assert "model-a" not in neutral and "registry" not in neutral and done in neutral, neutral


@needs_node
def test_a_run_is_one_line_of_a_list():
    line, dash, seconds = card(
        """
        const noStart = { ...record, started: null }, open = { ...record, open: true, ended: null };
        return [runLine(record, 5000), runLine({ ...record, tokens: null, token_s: 0, tracks: 2, gpu_wh: null }, 5000),
          [runSeconds(record, 5000), runSeconds(noStart, 5000), runSeconds(open, 1300), runSeconds({ ...record, ended: null }, 5000)]];"""
    )
    # from the start its source named, else from when it was first seen; so far while it is open; unknown without an end
    assert seconds == [600, 595, 300, None], seconds
    told = (line["name"], line["duration"], line["speed"], line["tokens"], line["energy"])
    assert told == ("Job A, round 9", "10 min", "40 tok/s", "24,000 tokens", "12.3 Wh"), line
    assert (dash["speed"], dash["tokens"], dash["energy"]) == ("–", "–", "–"), dash


# What every step of a check finds its way around the runs view with: the panel, what the elements of a class say,
# the card as it stands (name, state, the line of what cannot wait, and of every figure its value, unit, word, state
# and the note in sight), the lines of the list, and the stations.
VIEW = """
globalThis.panel = document.querySelector('#panel');
globalThis.one = cls => panel.under().find(e => e.classList.contains(cls));
globalThis.cardNow = () => ({ name: panel.under().find(e => e.tagName === 'H2').text, tag: one('sp-tag').text, note: one('cool-alarm').text,
  figs: panel.under().filter(e => e.classList.contains('sp-fig')).map(f => { const [top, what, note] = f.children; return [top.children[0].text, top.children[1].text, what.text, f.dataset.state, note.text]; }) });
globalThis.lines = () => panel.under().filter(e => e.matches('button') && e.parentNode && e.parentNode.tagName === 'LI').map(b => [...b.children.map(c => c.text), b.getAttribute('aria-current')]);
globalThis.stations = () => panel.under().filter(e => e.classList.contains('step')).map(e => [e.children[0].text, e.className]);
globalThis.told = figs => figs.map(f => [f.value, f.unit, f.what, f.state, f.state ? f.note : '']);
null
"""


@needs_node
def test_the_runs_view_shows_the_card_of_the_run_of_now_and_every_run_as_a_line_to_pick():
    """The view opens on the run that is running: its name and state, its four figures as the rules of the card give
    them, and under them every run that was recorded as a line, the open one first. A click on a line puts that run
    on the card. The view stands in the calm form beside the ring, and the records come from /api/runs."""
    seen = sheet(
        [
            VIEW,
            "setView('run'); null",
            "({ cls: panel.className, card: cardNow(), lines: lines(), asked: server.runsAsked(), rules: told(runFigures(Runs.shown(), LIVE.t)) })",
            "panel.under().filter(e => e.matches('button') && e.parentNode.tagName === 'LI')[1].fire('click', {}); null",
            "({ card: cardNow(), lines: lines(), rules: told(runFigures(Runs.shown(), LIVE.t)), state: runState(Runs.shown()) })",
        ]
    )
    first, picked = seen[2], seen[4]
    assert set(first["cls"].split()) >= {"record", "calm", "narrow", "runs"} and first["asked"] == 1, first
    assert (first["card"]["name"], first["card"]["tag"]) == ("Prefill sweep", "running"), first["card"]
    assert first["card"]["figs"] == first["rules"] and len(first["rules"]) == 4, first
    assert [fig[2] for fig in first["card"]["figs"]] == [
        "duration",
        "tokens per second",
        "tokens written",
        "GPU energy",
    ]
    assert [(line[0], line[-1]) for line in first["lines"]] == [("Prefill sweep", "true"), ("Eight streams", "false")]
    assert "running" in first["lines"][0][1] and "tok/s" in first["lines"][0][2] and "Wh" in first["lines"][0][2]
    assert picked["card"]["name"] == "Eight streams" and picked["card"]["tag"] == picked["state"], picked["card"]
    assert picked["card"]["tag"].startswith("ended ") and picked["card"]["figs"] == picked["rules"], picked
    assert [line[-1] for line in picked["lines"]] == ["false", "true"], picked["lines"]


@needs_node
def test_the_runs_view_keeps_what_it_explains_in_a_box_and_follows_the_run_while_it_goes_on():
    """What a run is and how each figure is counted waits in the box behind the "i", with what the record says of
    this run beside its figures. While the view is open the card follows every moment, and the records are asked
    for again once those on the page are ten seconds old. Leaving the view empties the panel and drops the run
    that was picked."""
    seen = sheet(
        [
            VIEW,
            "setView('run'); null",
            "one('q-info').fire('click', {}); ({ open: !one('q-pop').hidden, heads: one('q-pop').children.filter(e => e.tagName === 'H4').map(e => e.text), first: one('q-pop').children[1].text })",
            "shutBox(); for (let k = 0; k < 4; k++) server.say({ ...LIVE, t: LIVE.t + 2 }); ({ asked: server.runsAsked(), shut: one('q-pop').hidden })",
            "server.say({ ...LIVE, t: LIVE.t + 2 }); server.runsAsked()",
            "panel.under().filter(e => e.matches('button') && e.parentNode.tagName === 'LI')[1].fire('click', {}); setView('ring'); ({ cls: panel.className, kids: panel.children.length, open: Runs.isOpen() })",
            "setView('run'); null",
            "cardNow().name",
        ]
    )
    box, ticks = seen[2], seen[3]
    assert box["open"] and box["heads"] == [
        "This run",
        "Run",
        "Duration",
        "Tokens per second",
        "Tokens written",
        "GPU energy",
        "Runs kept",
    ], box
    said = box["first"]
    assert "steps in its queue" in said and "deepseek-v4.1-flash on spark-ds41f:demo" in said, said
    assert "written: GPU" not in said and ":  " not in said, said  # a figure without a note adds no word of its own
    assert ticks == {"asked": 1, "shut": True} and seen[4] == 2, (ticks, seen[4])  # 8 s on: not yet; 10 s on: again
    assert seen[5] == {"cls": "", "kids": 0, "open": False} or "runs" not in seen[5]["cls"], seen[5]
    assert seen[7] == "Prefill sweep"  # opened again, it shows the run of now, not the one picked before


@needs_node
def test_the_runs_view_shows_the_stations_of_the_queue_of_the_run_on_the_card():
    """The stations of a queue stand under the card of the run that belongs to it: for a run that ended as its record
    last held them; for the run that is running as the moment on the page names them, with who holds the ring and
    the estimate of when the queue ends, where the run says how far it is."""
    ends = "panel.under().filter(e => e.classList.contains('p-note')).map(e => e.text)"
    live = "{ source: 'command', name: 'Prefill sweep', group: 'Release suite', holder: 'Demo window', started: LIVE.t - 20, done: 10, total: 20, steps: [{ name: 'Prefill sweep', state: 'running' }, { name: 'Stall probe', state: 'pending', was: 40 }] }"
    seen = sheet(
        [
            VIEW,
            "setView('run'); null",
            f"({{ stations: stations(), notes: {ends}, heads: panel.under().filter(e => e.tagName === 'H3').map(e => e.text) }})",
            f"server.say({{ ...LIVE, t: LIVE.t + 2, run: {live} }}); ({{ stations: stations(), notes: {ends} }})",
            "panel.under().filter(e => e.matches('button') && e.parentNode.tagName === 'LI')[1].fire('click', {}); null",
            f"({{ stations: stations(), notes: {ends} }})",
            "queueLeft([{ state: 'done', seconds: 30 }, { state: 'running', was: 50 }, { state: 'pending' }, { state: 'pending', was: 20 }], {}, 0)",
        ]
    )
    names = ["Short prompts", "Long prompts", "Eight streams", "Prefill sweep", "Stall probe", "Quality gate"]
    # the moment on the page shows another run: the stations are those of the record, and nothing is estimated
    assert [name for name, _ in seen[2]["stations"]] == names and seen[2]["heads"] == ["Runs", "Queue steps"], seen[2]
    assert seen[2]["stations"][3][1] == "step running" and not any("queue ends" in n for n in seen[2]["notes"]), seen[2]
    # the moment names this run: its stations as of now, who holds the ring, and 20 s of the run plus 40 s to come
    assert seen[3]["stations"] == [["Prefill sweep", "step running"], ["Stall probe", "step pending"]], seen[3]
    assert seen[3]["notes"][0] == "Release suite, held by Demo window" and seen[3]["notes"][1].startswith(
        "The queue ends around"
    ), seen[3]
    assert [name for name, _ in seen[5]["stations"]] == names and seen[5]["notes"] == ["Release suite"], seen[5]
    assert seen[5]["stations"][2][1] == "step running", seen[5]  # as its source last named them: its own station ran
    assert seen[6] == 50 + 30 + 20, seen[
        6
    ]  # as long as last time, as long as a finished one took, as long as last time


@needs_node
def test_a_station_that_took_0_s_says_so_and_one_nobody_timed_stands_without_a_time():
    """A station that took 0 s took a time that was read, and the queue says it: "0 s", with how it changed against
    the time before. The page asked of the time whether it was there as of a yes or a no, and a 0 is a no: the
    station stood without a time, like one nobody timed, and its change was dropped with it. A time that was not
    read (null, or no number) still stands without one, and against a time before of 0 there is no change to tell.
    The run panel of the main page says the time of a station when the pointer is on its dot, and left out the 0
    there too."""
    steps = [
        {"name": "Warm-up", "state": "done", "seconds": 0, "was": 40},
        {"name": "Short prompts", "state": "done", "seconds": 0},
        {"name": "Long prompts", "state": "done", "seconds": 0, "was": 0},
        {"name": "Eight streams", "state": "done", "seconds": 50, "was": 40},
        {"name": "Long check", "state": "done", "seconds": 50, "was": 0},
        {"name": "Quality gate", "state": "done", "seconds": None, "was": 40},
        {"name": "Stall probe", "state": "done", "seconds": "x"},
        {"name": "Prefill sweep", "state": "running"},
        {"name": "Cool-down", "state": "pending", "was": 40},
    ]
    live = json.dumps({"source": "command", "name": "Prefill sweep", "steps": steps})
    rows = "panel.under().filter(e => e.classList.contains('step')).map(e => [e.children[1].text, ...e.children[1].children.map(c => `${c.className} ${c.text}`)])"
    dots = "document.querySelector('#stations').children.map(li => li.title)"
    seen = sheet(
        [VIEW, "setView('run'); null", f"server.say({{ ...LIVE, t: LIVE.t + 2, run: {live} }}); [{rows}, {dots}]"]
    )
    queue, titles = seen[2]
    assert queue == [
        ["0 s", "down -100 %"],  # was "" with no change
        ["0 s"],  # was ""
        ["0 s"],  # was "": against 0 s before there is no change to tell
        ["50 s", "up +25 %"],
        ["50 s"],  # against a time before of 0 there is no change to tell either (no "+Infinity %")
        [""],
        [""],  # was "NaN h": a text is no time
        ["now"],
        [""],
    ], queue
    assert titles == [
        "Warm-up: done, 0 s",  # was "Warm-up: done"
        "Short prompts: done, 0 s",
        "Long prompts: done, 0 s",
        "Eight streams: done, 50 s",
        "Long check: done, 50 s",
        "Quality gate: done",
        "Stall probe: done",  # was "Stall probe: done, NaN h"
        "Prefill sweep: running now",
        "Cool-down: waiting",
    ], titles


@needs_node
def test_the_estimate_of_a_queue_counts_a_station_that_took_0_s_as_one_that_took_0_s():
    """How long a queue has left is estimated from what was read: a station takes as long as it took the time
    before, else as long as a finished station took on average. Both asked of a time whether it was there as of a
    yes or a no, and a 0 is a no: a station that took 0 s was left out of the mean, and one that took 0 s the time
    before was given the mean. 0 s is a time that was read, and is counted as one; what nobody timed is not."""
    got = card(
        """
        return [
          queueLeft([{ state: 'done', seconds: 0 }, { state: 'done', seconds: 60 }, { state: 'running' }, { state: 'pending' }], {}, 0),
          queueLeft([{ state: 'done', seconds: 40 }, { state: 'running', was: 0 }, { state: 'pending', was: 0 }, { state: 'pending' }], {}, 0),
          queueLeft([{ state: 'done', seconds: 0 }, { state: 'running' }, { state: 'pending' }], {}, 0),
          queueLeft([{ state: 'done' }, { state: 'done', seconds: null }, { state: 'running' }, { state: 'pending', was: 20 }], {}, 0),
          queueLeft([{ state: 'done', seconds: 30 }, { state: 'running', was: 50 }, { state: 'pending' }, { state: 'pending', was: 20 }], {}, 0),
          queueLeft([{ state: 'done', seconds: 40 }, { state: 'done' }, { state: 'done', seconds: null }, { state: 'running' }, { state: 'pending' }], {}, 0)];"""
    )
    # a read time beside unread ones; an unread one taken as 0 s would make the mean 20 s or less
    assert got[5] == 40 + 40, got
    assert got[0] == 30 + 30, got  # was 60 + 60: the mean of the two is 30 s, not the 60 s of the one
    assert got[1] == 0 + 0 + 40, got  # was 40 + 40 + 40: each took 0 s the time before
    assert got[2] == 0, got  # every finished station took 0 s: nothing is left, as before
    assert got[3] == 20 and got[4] == 50 + 30 + 20, got  # what nobody timed is not counted, and the rest as before


@needs_node
def test_a_station_whose_name_nobody_can_read_is_a_dash():
    """A run command may name a station by what is no text (a number, null, a list), by an empty text or by no name
    at all. The hub left such a name out, and the page wrote what stood there then: "undefined: running now" on its
    dot, "step 2 of 5: undefined" in the head of nerd mode, "next undefined" in the line of the queue. A station
    whose name nobody can read is called by the dash the page writes for whatever nobody read. An entry with
    nothing a station has ({}) is none, as before."""
    steps = [
        {"name": "Warm-up", "state": "done"},
        {"name": 5, "state": "running"},
        {"name": None, "state": "pending"},
        {"name": "", "state": "pending"},
        {"state": "pending"},
        {},
    ]
    hub = hub_for()
    with hub.lock:
        hub.external_run = parse_runs(json.dumps({"name": "Prefill sweep", "steps": steps}))
    run = json.dumps(hub.view()["run"])
    rows = "panel.under().filter(e => e.classList.contains('step')).map(e => e.children[0].text)"
    said = "[$('#run-next').text, $('#n-step').text, $('#stations').children.map(li => li.title)]"
    seen = sheet(
        [
            VIEW,
            "Nerd.toggle(true); setView('run'); null",
            f"server.say({{ ...LIVE, t: LIVE.t + 2, run: {run} }}); [{said}, {rows}]",
        ]
    )
    (line, head, dots), names = seen[2]
    assert line == "step 2 of 5, next –", line  # was "next undefined"
    assert head == "step 2 of 5: –", head  # was "step 2 of 5: undefined"
    # was "undefined: running now", "undefined: waiting" twice and ": waiting" for the empty name
    assert dots == ["Warm-up: done", "–: running now", "–: waiting", "–: waiting", "–: waiting"], dots
    assert names == ["Warm-up", "–", "–", "–", "–"], names  # the rows of the queue in the runs view, empty before


@needs_node
def test_the_runs_view_says_that_there_is_no_run_or_why_the_records_did_not_come():
    """Without a record the view says so, with no figure and no list. Where the server does not answer, it says why,
    and keeps the card it shows."""
    seen = sheet(
        [
            VIEW,
            "server.runsAnswer({ open: null, runs: [] }); setView('run'); null",
            "({ card: cardNow(), shown: !panel.under().find(e => e.classList.contains('sp-figs')).hidden, lines: lines().length })",
            "setView('ring'); server.runsAnswer(null); setView('run'); null",
            "server.runsFail(503); for (let k = 0; k < 5; k++) server.say({ ...LIVE, t: LIVE.t + 2 }); null",
            "({ card: cardNow(), lines: lines().length })",
        ]
    )
    never = sheet([VIEW, "server.runsFail(503); setView('run'); null", "cardNow()"])[2]
    empty, failed = seen[2], seen[5]
    assert (empty["card"]["name"], empty["shown"], empty["lines"]) == ("No run yet", False, 0), empty
    assert empty["card"]["note"] and "503" not in empty["card"]["note"], empty
    assert failed["card"]["name"] == "Prefill sweep" and "503" in failed["card"]["note"] and failed["lines"] == 2, (
        failed
    )
    assert never["name"] == "No run yet" and "503" in never["note"], never


@needs_node
def test_the_runs_are_a_view_of_their_own_and_the_run_of_now_leads_to_them():
    """The runs have their button among the views (the sixth, key 6), and a click on the run of now opens them,
    whether or not that run names stations."""
    seen = sheet(
        [
            "VIEWS.map(v => v[0])",
            "S.run = { source: 'none' }; document.querySelector('#now').fire('click', {}); V",
            "setView('ring'); pageHears('keydown', { key: '6', target: document.body }); V",
            "document.querySelector('#views').children.map(b => b.text)",
        ]
    )
    assert seen[0] == ["ring", "why", "memory", "cooling", "events", "run"], seen[0]
    assert seen[1] == "run" and seen[2] == "run", seen[1:3]
    assert seen[3][:6] == ["Ring", "Why", "Memory", "Cooling", "Events", "Runs"], seen[3]


@needs_node
def test_the_list_of_runs_shows_the_newest_few_until_it_is_asked_for_all():
    seen = sheet(
        [
            VIEW,
            "const made = k => ({ id: k, name: 'Job ' + k, source: 'command', started: 1000 + k, first_seen: 1000 + k, last_heard: 1040 + k, counted_from: 1000 + k, ended: 1040 + k, open: false, sparks: 4, tokens: null, token_s: 0, token_gap_s: 0, lives: 0, tok_s_peak: null, gpu_wh: null, gpu_read_s: 0, gpu_gap_s: 160, gpu_from: 0, steps: null, tracks: null }); server.runsAnswer({ open: null, runs: [9, 8, 7, 6, 5, 4, 3, 2, 1].map(made) }); setView('run'); null",
            "({ lines: lines().map(l => l[0]), more: one('run-more').text })",
            "one('run-more').fire('click', {}); ({ lines: lines().length, more: one('run-more').text })",
        ]
    )
    assert seen[2] == {"lines": ["Job 9", "Job 8", "Job 7", "Job 6", "Job 5", "Job 4"], "more": "All 9 runs"}, seen[2]
    assert seen[3]["lines"] == 9 and seen[3]["more"] != "All 9 runs", seen[3]
