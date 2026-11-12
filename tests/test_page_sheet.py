"""The page of one Spark, driven without a browser: what a pointer, a click and a slow history do to it."""

import functools
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from ringtop_parts.connect.server import MODEL
from tests.fixtures import needs_node, page_moments, page_scripts

# The names every step of a check finds its way around the sheet with: the sheet, its curves (no lane, no time axis),
# what the elements of a class say, the word beside the cursor of a plot (of the first curve unless told), the box
# of the bar with one of its paragraphs by its heading (`explained` opens the box, reads and closes it), the strip
# under the bar (hidden, or its words and the buttons it offers), the list of what held earlier, a clock that
# jumps ahead, a press on a button by its word, and a pointer on the first curve.
TOOLS = """
globalThis.sheet = document.querySelector('#spark');
globalThis.plots = () => sheet.under().filter(e => e.matches('svg.plot') && !/lane|axis/.test(e.getAttribute('class')));
globalThis.said = cls => sheet.under().filter(e => e.classList.contains(cls)).map(e => e.text);
globalThis.word = (plot = plots()[0]) => plot.under().find(e => e.getAttribute('class') === 'cur-word').text;
globalThis.info = () => sheet.under().find(e => e.classList.contains('q-info'));
globalThis.box = () => sheet.under().find(e => e.classList.contains('q-pop'));
globalThis.para = title => { const all = box().children, i = all.findIndex(e => e.tagName === 'H4' && e.text === title); return i < 0 ? null : all[i + 1].text; };
globalThis.explained = title => { info().fire('click', {}); const text = para(title); info().fire('click', {}); return text; };
globalThis.strip = () => { const s = sheet.under().find(e => e.classList.contains('q-strip')); return s.hidden ? 'hidden' : [s.under().find(e => e.tagName === 'P').text, ...s.under().filter(e => e.matches('button') && !e.hidden).map(e => e.text)]; };
globalThis.earlier = () => sheet.under().filter(e => e.matches('ul.sp-earlier')).flatMap(u => u.under().filter(e => e.matches('button')).map(e => [...e.children.map(c => c.text), e.title]));
globalThis.later = seconds => { const base = Date.now(); Date.now = () => base + seconds * 1000; };
globalThis.press = word => sheet.under().find(e => e.matches('button') && e.text === word).fire('click', {});
globalThis.pointer = (type, x, more) => sheet.fire(type, { target: plots()[0], clientX: x, button: 0, buttons: 0, ...more });
null
"""
OPEN = (
    "setView('node', S.nodes[1].name); null"  # the sheet of the second Spark; its history arrives before the next step
)


@functools.lru_cache(maxsize=1)
def moments() -> str:
    """The moments of the demo the page is fed with, as the text of a file: made once for all checks of this file."""
    return json.dumps(page_moments(), default=sorted)


def sheet(steps, search=""):
    """Loads the page without a browser and runs `steps` in it one after the other, each a piece of script; gives back
    what each step returned. No error may fall on the way. search: what stands behind the "?" of the address the
    page is opened with, "?names=neutral" for the page with neutral names."""
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "moments.json"
        file.write_text(json.dumps({**json.loads(moments()), "steps": [TOOLS, *steps], "search": search}))
        done = subprocess.run(
            ["node", str(Path(__file__).with_name("page_loader.js")), "sheet", str(file), *page_scripts(folder)],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "RINGTOP_MODEL": str(MODEL)},
        )
    assert done.returncode == 0 and done.stdout, done.stderr[-600:]
    seen = json.loads(done.stdout)
    assert seen["errors"] == [], seen["errors"][:4]
    return seen["steps"][1:]


@needs_node
def test_a_check_can_open_the_sheet_hold_its_history_and_move_a_pointer_over_a_curve():
    """What the checks of this file stand on: the sheet opens and asks for its stretch once, the answer can be kept
    waiting, and a pointer over a curve is heard like in a browser."""
    got = sheet(
        [
            "server.holdHistory(); " + OPEN,
            "[server.historyAsked().length, sheet.classList.contains('loading'), plots().length > 10]",
            "server.releaseHistory(); null",
            "[sheet.classList.contains('loading'), explained('Time range')]",
            "pointer('pointermove', 500); word()",
            "sheet.fire('pointerleave', {}); word()",
        ]
    )
    assert got[1] == [1, True, True], got[1]  # one question, still out, and the curves stand
    assert got[3][0] is False and " to now" in got[3][1] and "24 h" in got[3][1], got[3]
    assert " Jan, " in got[4] and got[5] == "", got[4:]  # the curve under the pointer says the moment, a day wide back


@needs_node
def test_a_check_can_give_an_element_a_size_of_its_own_and_let_words_be_measured():
    """Every element of the loader is as large as the window and measures no word. A check that asks how a view
    fits its place gives one element a place of its own, and one that asks where a word of an axis may stand lets
    the words of a drawing be measured, so many pixels a letter."""
    got = sheet(
        [
            "globalThis.box = document.createElement('div'); [box.clientWidth, box.clientHeight, box.getBoundingClientRect().bottom]",
            "box.rect = { left: 10, top: 20, width: 300, height: 100 }; [box.clientWidth, box.clientHeight, box.getBoundingClientRect().right, box.getBoundingClientRect().bottom]",
            "globalThis.word = document.createElement('text'); word.textContent = 'twelve'; typeof word.getComputedTextLength",
            "server.measureWords(7); word.getComputedTextLength()",
            "server.measureWords(null); typeof word.getComputedTextLength",
        ]
    )
    assert got[0] == [1064, 625, 625], got[0]
    assert got[1] == [300, 100, 310, 120], got[1]
    assert got[2] == "undefined" and got[3] == 42 and got[4] == "undefined", got[2:]


def answer(series, tier="raw", width=2, step=2, more="", before=0):
    """A step that makes the history answer with these traces of the second Spark, one column every `step` seconds up
    to the moment on the page: each trace is a piece of script that gives the value of column k. `before`: the
    seconds the last column begins before that moment, as the columns of a real stretch do."""
    count = "40"
    traces = ", ".join(f"'dgx1.{key}': t.map((_, k) => {value})" for key, value in series.items())
    return (
        f"{{ const t = [...Array({count}).keys()].map(k => S.t - {before} - {step} * ({count} - 1 - k)), series = {{ {traces} }};"
        f" server.historyAnswers({{ t, tier: '{tier}', width: {width}, series, peak: series, low: series,"
        f" n: Object.fromEntries(Object.keys(series).map(key => [key, t.map(() => 1)])), events: []{more} }}); }} null"
    )


@needs_node
def test_the_marks_of_a_scale_all_read_differently():
    """A GPU temperature that moves in the fourth digit: the row shows one digit, and so do the marks of its scale."""
    got = sheet(
        [
            answer({"gpu_c": "60.0001 + (k % 3) * 0.0001"}),
            OPEN,
            "plots()[0].under().filter(e => e.tagName === 'TEXT' && e.parentNode.getAttribute('class') === 'grid').map(e => e.text)",
        ]
    )
    marks = got[2]
    assert len(marks) > 2 and len(set(marks)) == len(marks), marks


@needs_node
def test_the_lanes_say_how_long_a_state_held_from_what_was_recorded():
    """Forty columns an hour wide, each with one recorded minute. The GPU sat at its power cap for the whole of the
    last one: that is a minute, not an hour. It was slowed for heat for a fraction of a second: the lane draws that,
    so it does not say "none". And near its thermal limit under load it was for forty recorded minutes."""
    got = sheet(
        [
            answer(
                {
                    "cap_pct": "k === 39 ? 100 : 0",
                    "therm_pct": "k === 39 ? 0.01 : 0",
                    "brake_pct": "0",
                    "tlimit": "10",
                    "util": "90",
                },
                tier="minute",
                width=3600,
                step=3600,
                before=3600,
            ),
            OPEN,
            "said('ch-total')",
            "sheet.under().filter(e => e.matches('svg.lane')).map(e => e.under().filter(r => r.tagName === 'RECT' && r.parentNode.getAttribute('class') === 'held' && r.getAttribute('class') !== 'track').length)",
        ]
    )
    assert got[2][:4] == ["60 s", "under 1 s", "none", "40 min"], got[2]
    assert got[3][:4] == [1, 1, 0, 1], got[
        3
    ]  # a bar wherever the lane says the state held, and none where it says none


@needs_node
def test_looking_back_no_state_is_said_to_hold_to_now():
    """The GPU sat at its power cap in the last columns of the stretch. Live, that reads "to now". At a moment of the
    past the same columns end at that moment, and "now" would be a claim about another time."""
    capped = answer({"cap_pct": "k > 34 ? 100 : 0"}, before=2)
    got = sheet(
        [
            capped,
            OPEN,
            "earlier()",
            "Time.toggle(true); Time.go(LIVE.t - 600); null",
            capped,
            "press('24 h'); null",
            "[S.past, earlier()]",
        ]
    )
    assert len(got[2]) == 1, got[2]
    word, held, full = got[2][0]  # its line: the state, then for how long and when; the sentence stands behind it
    assert word == "At its power cap" and held.startswith("10 s, ") and held.endswith(" to now"), got[2]
    assert full.startswith("At its power cap for 10 s, within ") and " to now. " in full, full
    assert got[6][0] is True and len(got[6][1]) == 1 and " to now" not in "".join(got[6][1][0]), got[6]


@needs_node
def test_a_state_that_holds_is_said_to_hold_to_now_though_the_history_is_written_behind_the_clock():
    """On a sheet of half an hour a column is three seconds wide, and a line bridges under eight. The history is
    written up to nine seconds behind the clock: now and then the newest column of a state that still held lay
    further from the end than that, and the list said the state had ended there."""
    got = sheet([answer({"cap_pct": "k > 34 ? 100 : 0"}, width=3.08, before=9), OPEN, "earlier()"])
    assert len(got[2]) == 1 and got[2][0][1].endswith(" to now") and " to now. " in got[2][0][2], got[2]


@needs_node
def test_what_held_earlier_is_said_of_the_stretch_that_is_shown_not_of_where_the_board_is_heading():
    """A brake holds up to now, and its line under "Earlier" says so. The reader drags over a stretch that ended long
    ago: until the history answers, the sheet still shows the stretch that runs to now. A sheet that was drawn again
    meanwhile (its width changed) asked where the board was heading, and the line gave the brake an end although
    nothing it stands beside had changed. Like the stretch in the box, the line hangs on the answer that is shown."""
    got = sheet(
        [
            answer({"cap_pct": "k > 34 ? 100 : 0"}, width=3.08, before=9),
            OPEN,
            "earlier()[0][1]",
            f"server.holdHistory(); pointer('pointerdown', 300, {HELD}); pointer('pointermove', 400, {HELD});"
            " pointer('pointerup', 400); server.resized(); server.draw(1); earlier()[0][1]",
            "server.releaseHistory(); null",
        ]
    )
    assert got[2].endswith(" to now"), got[2]
    assert got[3] == got[2], got[2:4]  # was the same stretch with an end, as if the brake had let go


FIRST_VALUE = "sheet.under().find(e => e.classList.contains('ch-val')).children[0].text"  # the value of the first row
FIRST_COUNT = "sheet.under().find(e => e.matches('dl.ch-stat')).children[3].children[1].text"  # and how many it counts
CLICK = (
    "pointer('pointerdown', {0}); pointer('pointerup', {0});"  # a press and a release at one place of the first curve
)


@needs_node
def test_between_two_single_readings_the_pointer_reads_the_nearer_one():
    """Zoomed in to single readings, a column is far narrower than the two seconds between them. A pointer between
    two of them read a dash on every row; it reads the nearer reading."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}, width=0.02),
            OPEN,
            "press('30 min'); null",
            f"pointer('pointermove', 1004); [{FIRST_VALUE}, word()]",
        ]
    )
    assert got[3][0] == "90.0" and got[3][1].startswith("15 Jan, "), got[
        3
    ]  # 17.8 s before the end: the reading at 18 s


@needs_node
def test_two_marks_on_one_point_give_the_figures_of_that_point():
    """Marks snap to the points of the curves. Two clicks inside one column are that one point, and every row shows
    its figures: before, a stretch that lay inside a column had none at all."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}, tier="minute", width=60, step=60),
            OPEN,
            "press('30 min'); null",
            CLICK.format(684) + " strip()",
            CLICK.format(689) + f" [strip(), {FIRST_COUNT}]",
        ]
    )
    assert got[3][0].startswith("Mark at ") and got[3][1:] == ["Clear"], got[3]
    assert got[4][0][0].startswith("One point, ") and got[4][0][1:] == ["Clear"] and got[4][1] == "1", got[4]


@needs_node
def test_a_mark_that_slides_out_of_the_stretch_is_gone():
    """A live sheet moves on. A mark the stretch has left behind said "Mark at ..." for a moment no curve shows any
    more, and a marked stretch named more than the figures covered."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            OPEN,
            "press('30 min'); null",
            CLICK.format(100) + " strip()",
            "Date.now = (base => () => base + 60000)(Date.now()); server.say({ ...LIVE, t: LIVE.t + 300 }); null",
            "[server.historyAsked().length, strip()]",
        ]
    )
    assert got[3][0].startswith("Mark at "), got[3]
    asked, left = got[5]
    assert asked == 3, got[5]  # asked again
    assert left == "hidden" or (not left[0].startswith("Mark at ") and left[1:] == []), left  # and the mark is gone


@needs_node
def test_the_table_beside_the_others_says_what_the_figure_under_a_curve_is():
    """Under each small curve stands one figure. It followed the marks without a word (the last point of the marked
    stretch) while the rows above said "now". It is the newest point, the mean of a marked stretch or the value at
    the cursor, and the table says which. In the calm form that is all its heading says: that every column shares
    one scale waits in the box of the bar. And with a cursor on the sheet the heading says its moment as well: a
    small curve of the table has no room for a word beside its cursor."""
    cell = "sheet.under().filter(e => e.classList.contains('bs-cell'))[5].under().find(e => e.tagName === 'EM').text"
    note = "sheet.under().filter(e => e.matches('div.sp-h')).pop().children[1].text"
    got = sheet(
        [
            answer({"fan": "2000 + k * 10"}),
            OPEN,
            "press('30 min'); null",
            f"[{cell}, {note}, explained('Beside the others')]",
            CLICK.format(986) + CLICK.format(1008) + f" [{cell}, {note}]",
            f"pointer('pointermove', 1008); [{cell}, {note}, word()]",
        ]
    )
    # the words of the rule (BESIDE_WORDS) are checked, not the sentence around them: that one is polished later
    assert got[3][0] == "2,390" and "its newest point" in got[3][1], got[3]
    assert got[3][2] and got[3][2] not in got[3][1], got[3]  # what the columns share is said in the box, not here
    assert got[4][0] == "2,240" and "its mean over the marked stretch" in got[4][1], got[4]
    value, said, moment = got[5]
    assert value == "2,340" and "its value at the cursor" in said, got[5]
    assert moment.startswith("15 Jan, ") and moment in said, got[5]  # the moment the curve under the pointer says


@needs_node
def test_the_scale_of_a_column_beside_the_others_reads_differently_at_its_two_ends():
    """Every Spark three degrees from its thermal limit, all the same. The column got a tenth of its level as room,
    which is less than the whole degrees its ends are said in: the head of the column read "3 to 3". A shared scale
    is no finer than its ends can say, like the scale of a row."""
    scale = (
        "sheet.under().find(e => e.matches('div.bs-head')).under().filter(e => e.tagName === 'I').map(e => e.text)[2]"
    )
    got = sheet([answer({"tlimit": "3"}), OPEN, scale])
    low, high = (int(end) for end in got[2].split(" to "))
    assert low < 3 < high, got[2]


@needs_node
def test_a_row_without_a_reading_of_now_shows_its_last_point_and_the_distance_that_belongs_to_it():
    """The GPU temperature of this moment was not read. The row then shows the last point of the stretch: a mean of
    its column, so it is called a point, not a reading "at" a time. And the distance to the limit beside it is the
    one recorded with that point, not the one of now."""
    row = "sheet.under().find(e => e.classList.contains('ch-val')).children.map(e => e.text)"
    note = "sheet.under().find(e => e.matches('p.ch-note')).text"
    got = sheet(
        [
            answer({"gpu_c": "60 + k", "tlimit": "40 - k"}),
            OPEN,
            "server.say({ ...LIVE, nodes: LIVE.nodes.map(n => n.name === 'dgx1' ? { ...n, gpu_c: null, tlimit: 30 } : n) }); null",
            f"[{row}, {note}]",
        ]
    )
    (value, tag), note = got[3]
    assert value == "99.0" and tag.startswith("°C, last point, ") and "last at" not in tag, got[3]
    assert note == "1 °C to the limit", note


BAND = "server.historyAsked().filter(u => u.includes('band=1'))"  # the questions of the sheet: only it asks for a band


@needs_node
def test_a_slow_history_is_waited_for_and_not_asked_again():
    """The history takes longer than the page ticks. Asked again with every tick, each answer was dropped for the
    question after it, and the sheet stayed empty for as long as the history stayed slow. One question is out at a
    time; only after half a minute it counts as lost."""
    got = sheet(
        [
            "server.holdHistory(); " + OPEN,
            f"later(5); Spark.tick(); later(5); Spark.tick(); {BAND}.length",
            f"later(25); Spark.tick(); {BAND}.length",
            "server.releaseHistory(); null",
            "[sheet.classList.contains('loading'), explained('Time range')]",
        ]
    )
    assert got[1] == 1, got[1]  # ten seconds and two ticks later it is still the one question
    assert got[2] == 2, got[2]  # out for 35 s: lost, and asked anew
    assert got[4][0] is False and " to now" in got[4][1] and "24 h" in got[4][1], got[
        4
    ]  # and when the history answers, the sheet stands


@needs_node
def test_looking_back_the_head_does_not_say_as_recorded_where_nothing_was():
    """At a moment of the past the head of the sheet says "as recorded" beside the time. It said that too where the
    recording holds nothing of this Spark at that moment, above "nothing was recorded at this moment"."""
    age = "said('sp-age')[0]"
    empty = "server.historyAnswers({ t: [], tier: 'raw', width: 2, series: {}, peak: {}, events: [] })"
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            OPEN,
            "Time.toggle(true); Time.go(LIVE.t - 40); null",
            f"[S.nodes[1].live, {age}]",
            f"{empty}; Time.go(LIVE.t - 600); null",
            f"[S.nodes[1].live, {age}, said('sp-doing')[0]]",
        ]
    )
    assert got[3][0] is True and got[3][1].startswith("as recorded, "), got[3]
    assert got[5][0] is False and got[5][1].startswith("no reading, "), got[5]
    assert "nothing was recorded at this moment" in got[5][2], got[5]


@needs_node
def test_looking_back_a_small_step_of_the_moment_loads_the_stretch_that_ends_there():
    """The time machine steps four seconds back. The sheet kept the stretch it had, which ends after the moment now
    on the page: its curves showed what came later. It asks for the stretch that ends at the moment."""
    got = sheet(
        [
            OPEN,
            "later(60); Time.toggle(true); Time.go(LIVE.t - 600); null",
            f"[S.t, {BAND}.pop()]",
            "later(60); Time.go(S.t - 4); null",
            f"[S.t, {BAND}.pop()]",
        ]
    )
    for moment, asked in (got[2], got[4]):
        assert f"&to={moment:.1f}&" in asked, (moment, asked)
    assert got[4][0] == got[2][0] - 4, (got[2][0], got[4][0])


SEL = "plots()[0].under().find(e => e.getAttribute('class') === 'sel').style.display"  # '' while a stretch is shaded
HELD = "{ buttons: 1 }"  # the main button is down


@needs_node
def test_a_drag_that_ended_off_the_sheet_does_not_follow_the_pointer_afterwards():
    """The pointer leaves the sheet in the middle of a drag, and the button comes up out there. Back on the sheet
    the shaded stretch followed the pointer without a button, and the next release zoomed."""
    got = sheet(
        [
            OPEN,
            "press('30 min'); null",
            f"pointer('pointerdown', 300, {HELD}); pointer('pointermove', 400, {HELD}); sheet.fire('pointerleave', {{}}); {SEL}",
            f"pointer('pointermove', 600); pointer('pointermove', 700); [{SEL}, {BAND}.length]",
            f"pointer('pointerup', 700); {BAND}.length",
        ]
    )
    assert got[2] == "", got[2]  # while it is dragged, the stretch is shaded
    assert got[3] == ["none", 2] and got[4] == 2, got[3:]  # no shade without a button, and no zoom on the release


@needs_node
def test_a_press_off_the_sheet_does_not_take_up_a_drag_that_ended_out_there():
    """A drag leaves the sheet and the button comes up out there, where the sheet does not hear it. Then the button
    goes down off the sheet and the pointer comes back with it held: the old drag went on from where it once began,
    and the release zoomed. The page hears the button come up wherever that is, and the drag ends there."""
    got = sheet(
        [
            OPEN,
            "press('30 min'); null",
            f"pointer('pointerdown', 300, {HELD}); pointer('pointermove', 400, {HELD}); sheet.fire('pointerleave', {{}}); {SEL}",
            f"pageHears('pointerup', {{}}); {SEL}",
            f"pointer('pointermove', 600, {HELD}); pointer('pointermove', 700, {HELD}); [{SEL}, {BAND}.length]",
            f"pointer('pointerup', 700); {BAND}.length",
        ]
    )
    assert got[2] == "" and got[3] == "none", got[2:4]  # shaded while it is dragged, and not once the button is up
    assert got[4] == ["none", 2] and got[5] == 2, got[4:]  # the new press takes up nothing, and its release no zoom


@needs_node
def test_a_drag_brought_back_to_where_it_began_shades_nothing_and_sets_a_mark():
    """A drag grew to a stretch, then the pointer came back to its start in one step. The shade stayed where the
    pointer had been last, and the release zoomed to it. Back at its start a drag is a click again."""
    got = sheet(
        [
            OPEN,
            "press('30 min'); null",
            f"pointer('pointerdown', 300, {HELD}); pointer('pointermove', 500, {HELD}); {SEL}",
            f"pointer('pointermove', 302, {HELD}); {SEL}",
            f"pointer('pointerup', 302); [strip()[0].slice(0, 8), {BAND}.length]",
        ]
    )
    assert got[2] == "" and got[3] == "none", got[2:4]  # shaded while the pointer is away, and not once it is back
    assert got[4] == ["Mark at ", 2], got[4]  # the release is a click: a mark, and no question for another stretch


@needs_node
def test_a_press_on_a_curve_that_has_drawn_nothing_begins_no_drag():
    """The history is still on its way and the curves stand empty. A press there has no moment under it; dragged on
    after the curves had come, it zoomed from the year 1970 to the pointer."""
    got = sheet(
        [
            "server.holdHistory(); " + OPEN,
            f"pointer('pointerdown', 300, {HELD}); pointer('pointermove', 400, {HELD}); server.releaseHistory(); null",
            f"pointer('pointermove', 500, {HELD}); pointer('pointerup', 500); {BAND}",
        ]
    )
    spans = [float(u.split("&to=")[1].split("&")[0]) - float(u.split("&from=")[1].split("&")[0]) for u in got[2]]
    assert spans == [86400.0], spans  # the one question of the opening, and no zoom across decades


@needs_node
def test_looking_back_a_zoom_never_loads_what_came_after_the_moment_on_the_page():
    """A short drag at the right edge is widened to a handful of readings around its middle. Its end was held at the
    newest moment the page knows, not at the moment it shows: at a moment of the past it reached past it."""
    got = sheet(
        [
            OPEN,
            "later(60); Time.toggle(true); Time.go(LIVE.t - 600); null",
            "press('30 min'); null",
            f"pointer('pointerdown', 1008, {HELD}); pointer('pointermove', 1014, {HELD}); pointer('pointerup', 1014); [S.t, {BAND}.pop()]",
        ]
    )
    moment, asked = got[3]
    end = float(asked.split("&to=")[1].split("&")[0])
    assert end <= moment and "&from=" in asked and moment - end < 1, (moment, asked[-80:])


@needs_node
def test_after_a_zoom_the_cursor_stands_under_the_pointer():
    """The pointer rests where the drag ended. The cursor stayed at the moment it had before the zoom, which lies
    somewhere else on the new stretch, until the pointer moved again. And the word beside the cursor says the
    moment the cursor now reads: it went on saying the one from before the zoom."""
    cursor = "plots()[0].under().find(e => e.getAttribute('class') === 'cur').getAttribute('x1')"
    got = sheet(
        [
            OPEN,
            "press('30 min'); null",
            f"pointer('pointerdown', 300, {HELD}); pointer('pointermove', 500, {HELD}); word()",
            "pointer('pointerup', 500); null",
            f"[{cursor}, {BAND}.length, word()]",
        ]
    )
    assert got[4][:2] == ["500.0", 3], got[4]
    assert got[2].startswith("15 Jan, ") and got[4][2].startswith("15 Jan, ") and got[4][2] != got[2], (got[2], got[4])


@needs_node
def test_back_to_now_does_not_call_the_stretch_still_shown_one_that_runs_to_now():
    """The reader zoomed in to a stretch that ended a while ago and presses "Back to now". Until the history
    answers, the sheet still shows the old stretch; the bar wrote it "… to now" as soon as the pointer moved, because
    it asked where the board was heading and not what it shows. The word hangs on the answer that is shown. Since
    the calm form the stretch in words stands in the box of the bar, and a stretch zoomed to on its strip."""
    got = sheet(
        [
            OPEN,
            "press('30 min'); null",
            f"pointer('pointerdown', 300, {HELD}); pointer('pointermove', 500, {HELD}); pointer('pointerup', 500); null",
            "[strip(), explained('Time range')]",
            "server.holdHistory(); press('Back to now'); pointer('pointermove', 400); explained('Time range')",
            "server.releaseHistory(); null",
            "explained('Time range')",
        ]
    )
    zoomed, said = got[3]
    assert " to " in zoomed[0] and "now" not in zoomed[0] and zoomed[0].endswith(", 6 min"), zoomed
    assert zoomed[1:] == ["Back to now"] and " to now" not in said, got[3]  # a stretch that ended before now
    assert got[4] == said, got[3:5]  # the answer is still out: the box says what the curves show
    assert " to now" in got[6] and "6 min" in got[6], got[
        6
    ]  # the answer came: the last minutes, as long as the stretch zoomed to


@needs_node
def test_the_strip_names_a_stretch_as_zoomed_to_only_once_it_is_the_one_that_is_shown():
    """The reader drags over a stretch. Until the history answers, the sheet still shows the stretch before; as soon
    as the pointer moved, the strip of the calm bar wrote that one as the stretch that was zoomed to (the whole half
    hour, "…, 30 min"), because it asked where the board was heading. It names a stretch as zoomed to once the
    answer for it is the one that is shown; the cooling view stands on the same bar."""
    got = sheet(
        [
            OPEN,
            "press('30 min'); null",
            "strip()",
            f"server.holdHistory(); pointer('pointerdown', 300, {HELD}); pointer('pointermove', 500, {HELD});"
            " pointer('pointerup', 500); pointer('pointermove', 400); strip()",
            "server.releaseHistory(); null",
            "strip()",
        ]
    )
    before, heading, there = got[2], got[3], got[5]
    said = [s if s == "hidden" else s[0] for s in (before, heading)]
    assert said[1] == said[0], (before, heading)  # was the half hour still shown, said as the stretch zoomed to
    assert there[1:] == ["Back to now"] and there[0].endswith(", 6 min") and "now" not in there[0], there


@needs_node
def test_the_word_at_the_cursor_goes_with_the_pointer_to_another_curve_at_the_same_moment():
    """The curves of the stack stand on one room: one moment is one place on all of them. A pointer that went
    straight down from one curve to the next read the same moment there, and the board took that for no move at all:
    the word that says the moment stayed at the curve the pointer had left, until the pointer moved sideways."""
    got = sheet(
        [
            OPEN,
            "press('30 min'); null",
            "pointer('pointermove', 300); [word(plots()[0]), word(plots()[1])]",
            "sheet.fire('pointermove', { target: plots()[1], clientX: 300, button: 0, buttons: 0 });"
            " [word(plots()[0]), word(plots()[1])]",
        ]
    )
    here, there = got[2], got[3]
    assert here[0] and here[1] == "", here
    assert there == ["", here[0]], (here, there)  # was the word still at the first curve, and none at the second


@needs_node
def test_an_answer_that_is_no_stretch_leaves_the_sheet_as_it_was():
    """The server answers a question for the history with JSON that is no stretch (an error said in JSON). The sheet
    took it for one: every moment after that threw, and the stretch it had shown was gone. It says the history did
    not answer, keeps what it has, and the moments go on. On the strip of the calm bar that stays said until the
    history answers again."""
    line = "plots()[0].under().find(e => e.getAttribute('class') === 'line').getAttribute('d').length > 20"
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            OPEN,
            "server.historyAnswers({ error: 'the store is busy' }); press('30 min'); null",
            f"Spark.tick(); server.say({{ ...LIVE, t: LIVE.t + 2 }}); [strip(), {line}]",
            "pointer('pointermove', 400); strip()",
        ]
    )
    assert got[3][0] != "hidden" and "no stretch of the history" in got[3][0][0] and got[3][1] is True, got[3]
    # and it goes on saying so while the reader reads the curves it kept, though the recording of this Spark
    # begins late in the stretch, which the strip would say otherwise
    assert got[4] != "hidden" and "no stretch of the history" in got[4][0], got[4]


@needs_node
def test_a_stretch_that_did_not_come_leaves_no_mark_and_no_shade_the_board_has_dropped():
    """Two marks stand on the curves and the reader picks another stretch: the board drops the marks at once. The
    history does not answer. The curves kept the old stretch and went on shading the marked one, while the figures of
    every row covered all of it again and the bar offered nothing to clear. The same with the shade of a drag whose
    zoom did not come. What the board has dropped goes from the curves too."""
    shown = (
        "plots()[0].under().filter(e => ['sel', 'mark'].includes(e.getAttribute('class'))).map(e => e.style.display)"
    )
    fails = "server.historyAnswers({ error: 'the store is busy' }); "
    picked = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            OPEN,
            "press('30 min'); null",
            CLICK.format(300) + CLICK.format(700) + f" [strip(), {shown}]",
            fails + "press('2 h'); null",
            f"[strip(), {shown}]",
        ]
    )
    assert " to " in picked[3][0][0] and picked[3][0][1:] == ["Zoom", "Clear"], picked[3]
    assert picked[3][1] == ["", "", ""], picked[3]
    said, drawn = picked[5]
    assert "no stretch of the history" in said[0] and said[1:] == [] and drawn == ["none", "none", "none"], picked[5]
    dragged = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            OPEN,
            "press('30 min'); null",
            fails + f"pointer('pointerdown', 300, {HELD}); pointer('pointermove', 700, {HELD}); {shown}[0]",
            "pointer('pointerup', 700); null",
            f"[strip()[0], {shown}[0]]",
        ]
    )
    assert dragged[3] == "" and "no stretch of the history" in dragged[5][0] and dragged[5][1] == "none", dragged[3:]


@needs_node
def test_a_link_to_a_spark_this_ring_does_not_have_leads_to_the_ring():
    """`#node=NAME` with a name no Spark of this ring has (an old link, a typing error) threw while the sheet wrote
    its head, and the page stood half built. It leads to the ring, from the start of the page and from an open sheet."""
    got = sheet(
        [
            "setView('node', 'spark-nobody'); [V, VN, Spark.isOpen()]",
            OPEN,
            "setView('node', 'spark-nobody'); [V, VN, Spark.isOpen()]",
        ]
    )
    assert got[0] == ["ring", None, False] and got[2] == ["ring", None, False], got


@needs_node
def test_a_click_on_the_open_spark_leads_from_one_of_its_parts_back_to_its_sheet():
    """A part of the Spark is open in the panel. A click on the same Spark, on its tile or in the scene, did nothing:
    the view was already that Spark. It closes the part and shows the sheet again."""
    shown = "[VP, !document.querySelector('#spark').hidden, !document.querySelector('#panel').hidden]"
    got = sheet([OPEN, f"setPart('fan'); {shown}", f"setView('node', VN); {shown}"])
    assert got[1] == ["fan", False, True] and got[2] == [None, True, False], got


@needs_node
def test_on_a_page_shown_larger_the_cursor_still_stands_under_the_pointer():
    """The page is shown at twice its size: a curve drawn 1064 units wide takes 2128 pixels of the screen. The moment
    under the pointer was counted with the room beside the curve in screen pixels, and the cursor stood beside it."""
    cursor = "plots()[0].under().find(e => e.getAttribute('class') === 'cur').getAttribute('x1')"
    got = sheet(
        [
            OPEN,
            "for (const p of plots()) p.getBoundingClientRect = () => ({ left: 0, width: 2128 }); null",
            f"pointer('pointermove', 1000); {cursor}",
        ]
    )
    assert got[2] == "500.0", got[2]


@needs_node
def test_the_box_of_the_sheet_says_what_the_lanes_are_judged_from():
    """What the lanes are counted or judged from, at the resolution of the stretch, stood as a sentence under them.
    In the calm form it waits in the box of the bar, written for the stretch that is shown when the box opens."""
    got = sheet([answer({"gpu_c": "60 + k"}, tier="minute", width=240, step=240), OPEN, "explained('Lanes')"])
    assert got[2] and "judged from the means of each point (4 min)" in got[2], got[2]


@needs_node
def test_a_lane_that_could_not_be_judged_does_not_say_it_was_not_recorded():
    """The fans of this Spark and its distance to the thermal limit are recorded, and nothing else is: no other Spark
    has a fan reading, and the load of the GPU is missing. The two lanes that are judged from several readings said
    "not recorded" under curves that show the recording. They say that the state could not be judged, and the
    brakes nobody recorded still say that."""
    got = sheet([answer({"fan": "2000", "tlimit": "10"}), OPEN, "said('ch-total')"])
    assert got[2] == [
        "not recorded",
        "not recorded",
        "not recorded",
        "not judged: a reading it needs was not recorded",
        "not judged: fewer than two other Sparks with a fan reading",
    ], got[2]


@needs_node
def test_a_lane_judged_only_later_in_the_stretch_does_not_say_its_recording_began_then():
    """The distance of the GPU to its thermal limit is recorded over the whole stretch, its load only over the second
    half: the lane "near its thermal limit under load" can be judged from there on. It said "recorded from" that
    moment, under a curve that shows the recording from the start. A lane that is judged says from when on it is
    judged; a brake nvidia-smi counts still says from when on it was recorded."""
    got = sheet(
        [
            answer({"gpu_c": "60", "tlimit": "30", "util": "k < 20 ? null : 10", "cap_pct": "k < 20 ? null : 0"}),
            OPEN,
            "said('ch-total')",
        ]
    )
    assert got[2][0].startswith("none, recorded from "), got[2]
    assert got[2][3].startswith("none, judged from ") and got[2][3][18:] == got[2][0][20:], got[2]


@needs_node
def test_a_sheet_closed_while_its_history_was_on_its_way_is_not_left_loading():
    got = sheet(
        [
            "server.holdHistory(); " + OPEN,
            "setView('ring'); [sheet.classList.contains('loading'), Spark.isOpen()]",
            "server.releaseHistory(); null",
            "[sheet.classList.contains('loading'), sheet.children.length]",
        ]
    )
    assert got[1] == [False, False] and got[3] == [False, 0], got  # and the late answer draws nothing into it


@needs_node
def test_before_its_history_has_answered_the_bar_offers_nothing_to_do_with_marks():
    """The sheet stands and its history is still on its way, or never answers. The bar showed "Back to now", "Zoom to
    the marks" and "Clear marks" until the first answer hid them, and a click on the last one threw: there is no
    stretch yet to go back from or to mark anything on. The calm bar offers its stretches, the figures and its box,
    and nothing of the strip: a button counts here as offered unless it or something around it is hidden."""
    bar = (
        "sheet.under().filter(e => e.matches('button') && e.closest('.q-bar') && (() => { for (let x = e; x && x !== sheet;"
        " x = x.parentNode) if (x.hidden) return false; return true; })()).map(e => e.text)"
    )
    got = sheet(["server.holdHistory(); " + OPEN, bar, "server.releaseHistory(); null", bar])
    assert got[1] == got[3] == ["30 min", "2 h", "6 h", "24 h", "2 d", "7 d", "30 d", "Figures", "i"], got


@needs_node
def test_a_brake_that_held_half_of_the_time_is_listed_with_the_time_it_held():
    """In the last five readings nvidia-smi counted the GPU at its power cap for half of the time."""
    got = sheet([answer({"cap_pct": "k > 34 ? 50 : 0"}, before=2), OPEN, "[earlier(), said('ch-total')[0]]"])
    listed, total = got[2]
    assert len(listed) == 1, listed
    word, held, full = listed[0]
    assert word == "At its power cap" and held.startswith("5 s, ") and held.endswith(" to now"), listed
    assert full.startswith("At its power cap for 5 s, within ") and " to now. " in full, full
    assert total.startswith("5 s"), total  # the same five seconds the lane counts in all


@needs_node
def test_a_state_judged_point_by_point_is_listed_with_the_time_that_was_recorded():
    """Near its thermal limit under load for forty minutes, with the distance to the limit unread in one of them. The
    stretch bridges that minute as a line would. Listed as earlier it read "40 min", the length of the stretch,
    beside a lane that counted 39 recorded minutes. The list says the recorded time, for every lane alike."""
    near = {"gpu_c": "60", "tlimit": "k === 20 ? null : 10", "util": "90"}
    got = sheet([answer(near, tier="minute", width=60, step=60, before=60), OPEN, "[earlier(), said('ch-total')[3]]"])
    listed, total = got[2]
    assert total == "39 min", total
    assert len(listed) == 1, listed
    word, held, full = listed[0]
    assert word == "Near its thermal limit under load" and held.startswith("39 min, "), listed
    assert held.endswith(" to now") and full.startswith("Near its thermal limit under load for 39 min, within "), listed


@needs_node
def test_a_state_never_held_for_longer_than_the_stretch_it_is_listed_in():
    """Zoomed in to thirteen seconds, with the GPU at its power cap in every reading. Each reading counted for its
    two seconds, also the last one, which reaches past the end of the sheet (and here every reading the history
    sent from after it): the lane said more than the thirteen seconds of its stretch. A reading counts only as far
    as it lies in the stretch."""
    got = sheet(
        [
            answer({"cap_pct": "100"}, width=0.02),
            OPEN,
            "press('30 min'); null",
            f"pointer('pointerdown', 970, {HELD}); pointer('pointermove', 977.5, {HELD}); pointer('pointerup', 977.5); null",
            "[strip()[0], said('ch-total')[0], earlier()]",
        ]
    )
    bar, total, listed = got[4]
    assert bar.endswith(", 13 s"), bar
    assert total == "13 s" and len(listed) == 1 and listed[0][1].startswith("13 s, "), got[4]
    assert listed[0][2].startswith("At its power cap for 13 s, within "), listed


@needs_node
def test_zoomed_in_to_single_readings_the_bar_does_not_say_the_recording_begins_later():
    """A drag across the readings of the last minute. The stretch begins between two readings: the first one comes
    less than two seconds after its start, and the bar said "Its recording begins ..." for it. In the calm form
    that would stand on the strip under the bar and in the box."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}, width=0.02),
            OPEN,
            "press('30 min'); null",
            f"pointer('pointerdown', 970, {HELD}); pointer('pointermove', 1000, {HELD}); pointer('pointerup', 1000); null",
            "[strip(), explained('Time range')]",
        ]
    )
    zoomed, said = got[4]
    assert zoomed[0].endswith(", 53 s") and zoomed[1:] == ["Back to now"], zoomed  # no word of a late recording
    assert "53 s" in said and "every reading, 2 s apart" in said and "ecording begins" not in said, said


HEADINGS = "(() => { info().fire('click', {}); const all = box().children.filter(e => e.tagName === 'H4').map(e => e.text); info().fire('click', {}); return all; })()"  # the headings of the box, in their order
FORM = "[sheet.classList.contains('calm'), sheet.classList.contains('figures')]"  # calm, and whether the figures show


@needs_node
def test_the_sheet_stands_in_the_calm_form_with_its_sentences_behind_the_bar():
    """The sheet kept two lines of words in sight under its bar: the stretch with what one point stands for, and
    how to read, mark and zoom. In the calm form the bar is one switch for the stretch, a button for the figures and
    one for its box. The box holds those sentences under headings of their own and is filled when it opens; the strip
    under the bar says where the recording of this Spark begins. The four figures of every curve wait behind their
    button and come by themselves with two marks."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            OPEN,
            "press('30 min'); null",
            f"[{FORM}, strip(), {HEADINGS}]",
            "[explained('Time range'), explained('Reading the curves')]",
            f"press('Figures'); {FORM}",
            f"press('Figures'); {FORM}",
            CLICK.format(300) + CLICK.format(700) + f" [{FORM}, strip()]",
            "[info().title, info().getAttribute('aria-label'), sheet.under().find(e => e.classList.contains('q-fig')).title]",
        ]
    )
    form, said, headings = got[3]
    assert form == [True, False], form
    assert said != "hidden" and "15 Jan, " in said[0] and said[1:] == [], said  # where its recording begins
    assert headings.index("Time range") < headings.index("Reading the curves"), headings
    stretch, reading = got[4]
    assert " to now" in stretch and "30 min" in stretch and "every reading, 2 s apart" in stretch, stretch
    assert "15 Jan, " in stretch and len(reading) > 40, got[4]
    assert got[5] == [True, True] and got[6] == [True, False], got[5:7]
    assert got[7][0] == [True, True] and got[7][1][1:] == ["Zoom", "Clear"], got[7]  # two marks bring the figures
    assert all(got[8]), got[8]


@needs_node
def test_a_pointer_on_a_lane_reads_the_same_moment_on_every_curve_and_the_lane_says_it():
    """One cursor reads every plot of the sheet, the lanes too. In the calm form the plot under the pointer says
    which moment that is, and so does a lane: no bar says it any more. A lane stands on the same room as the
    curves above it, so one moment is one place on both."""
    lane = "sheet.under().filter(e => e.matches('svg.lane'))[0]"
    at = "(plot => plot.under().find(e => e.getAttribute('class') === 'cur').getAttribute('x1'))"
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}, width=0.02),
            OPEN,
            "press('30 min'); null",
            f"sheet.fire('pointermove', {{ target: {lane}, clientX: 1004, button: 0, buttons: 0 }});"
            f" [word({lane}), word(), {FIRST_VALUE}, {at}({lane}), {at}(plots()[0])]",
        ]
    )
    said, other, value, on_lane, on_curve = got[3]
    assert said.startswith("15 Jan, ") and other == "", got[3]  # the lane says the moment, the curve does not
    assert value == "90.0" and on_lane == on_curve, got[3]  # the reading 18 s before the end, at one place on both


@needs_node
def test_the_box_of_a_sheet_is_shut_when_another_spark_opens_or_the_sheet_leaves():
    """Escape closes an open box first. A box whose sheet has gone or was built anew for another Spark is no box:
    the sheet shuts it, so the next Escape is not spent on something nobody sees. And a sheet that leaves takes its
    figures with it."""
    got = sheet(
        [
            OPEN,
            "info().fire('click', {}); [box().hidden, !!shutBox]",
            "setView('node', S.nodes[2].name); [!!shutBox, box().hidden]",
            "info().fire('click', {}); press('Figures'); pageHears('keydown', { key: 'Escape' }); [V, box().hidden]",
            "info().fire('click', {}); setView('why'); [!!shutBox, sheet.classList.contains('figures')]",
            "pageHears('keydown', { key: 'Escape' }); V",
        ]
    )
    assert got[1] == [False, True], got[1]  # the box stands open
    assert got[2] == [False, True], got[2]  # another Spark: its sheet begins with a shut box
    assert got[3] == ["node", True], got[3]  # Escape closes the box and nothing else
    assert got[4] == [False, False], got[4]  # the sheet left: no box that counts as open, and no figures kept
    assert got[5] == "ring", got[5]  # and the next Escape leaves the view at once


LANE_WORDS = [
    "At its power cap",
    "Slowed down for heat",
    "Power brake",
    "Near its thermal limit under load",
    "Fans slower than the others",
]


@needs_node
def test_the_box_of_the_sheet_holds_what_stood_between_its_curves_and_lanes():
    """Between the curves of the sheet stood what a curve, its band and its dashed line are, and the rule of every
    lane was the tooltip of its word alone. In the calm form the box of the bar holds them: a paragraph about the
    curves, one for every lane under the word the lane carries on the sheet, and what the lanes are judged from.
    The word of a lane keeps its rule as its tooltip."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            OPEN,
            f"[{HEADINGS}, explained('Curves'), {json.dumps(LANE_WORDS)}.map(explained)]",
            "sheet.under().filter(e => e.matches('div.lane')).map(e => [e.children[0].text, e.children[0].title])",
            "sheet.under().find(e => e.matches('div.sp-h')).children.map(e => e.text)",
        ]
    )
    assert got[4] == ["Against its limits"], got[4]  # the heading of the limits stands alone
    headings, curves, rules = got[2]
    at = headings.index("Curves")
    after = headings[at + 1 : at + 8]  # one curve has a paragraph of its own: where its watts come from
    assert headings.index("Reading the curves") < at and after == ["GPU power", *LANE_WORDS, "Lanes"], headings
    assert curves and len(curves) > 30 and all(rule and len(rule) > 30 for rule in rules), got[2]
    assert "20 °C" in rules[3] and "50 %" in rules[3], rules[3]  # near its thermal limit under load
    assert "15 %" in rules[4] and "1.5 °C" in rules[4], rules[4]  # fans slower than the others
    assert [word for word, _ in got[3]] == LANE_WORDS and [rule for _, rule in got[3]] == rules, got[3]


@needs_node
def test_the_limits_stand_in_one_column_and_the_readings_of_a_group_side_by_side():
    """Every reading of the sheet was a row of its own under the one before. In the calm form the limits keep that
    column: four curves, the five lanes under them and one time axis on one card, each curve over its whole
    width, and beside the name of a curve the distance that belongs to its value. The readings of a group stand
    side by side on a card, two to a line, with a time axis under each column. A reading the stretch holds
    nothing of leaves its place to the next and is named under the card; a group without any reading shows no
    card, and a column without a curve no time axis."""
    cards = "sheet.under().filter(e => e.classList.contains('sp-card'))"
    shape = (
        f"{cards}.map(c => [c.hidden, c.children.map(e => e.className).join(' | '),"
        " c.under().filter(e => e.classList.contains('ch') && !e.classList.contains('lane')).map(e => e.hidden),"
        " c.under().filter(e => e.classList.contains('ch-axis')).map(e => e.hidden)])"
    )
    readings = {"gpu_c": "60 + k", "tlimit": "30", "mem_free_gb": "20", "disk_read": "1", "disk_write": "2", "net": "3"}
    got = sheet(
        [
            answer(readings),
            OPEN,
            shape,
            "[said('sp-none'), sheet.under().find(e => e.matches('p.ch-note')).parentNode.className,"
            " sheet.under().filter(e => e.classList.contains('alone')).map(e => e.children[0].children[0].text)]",
        ]
    )
    stack, compute, memory, heat, network, disk = got[2]
    assert stack[0] is False and stack[1] == " | ".join([*["ch tall"] * 4, *["ch lane"] * 5, "ch-axis"]), stack
    assert stack[2] == [False] * 4 and stack[3] == [False], stack  # the four limits always stand, on one axis
    for card in (compute, memory, heat, network, disk):
        assert card[1] == "sp-cells | sp-cells sp-axes" and len(card[3]) == 2, card
    assert compute[0] is True and heat[0] is True, (compute, heat)  # nothing of them in this stretch: no card
    assert memory[0] is False and memory[2] == [False, True] and memory[3] == [False, True], memory  # one curve
    assert disk[0] is False and disk[2] == [False, False] and disk[3] == [False, False], disk  # two, side by side
    assert network[0] is False and network[2][0] is False and network[3] == [False, True], network  # the sum alone
    unread, beside, alone = got[3]
    unread = unread[-5:]  # the line under every group; before them stands the one of the events
    assert "Engine container" in unread[1] and unread[4] == "" and "CPU busy" in unread[0], unread
    assert beside == "ch-id" and alone == ["Ring ports, both ways"], got[3]  # the distance beside the name


# The four figures of the head: value with unit, its word, what stands under the word, what stands behind the
# figure, and its state.
FIGS = "sheet.under().filter(e => e.classList.contains('sp-fig')).map(f => [f.children[0].children.map(e => e.text).join(' '), f.children[1].text, f.children[2].text, f.title, f.dataset.state])"
# A moment later on the page, in which one fan of the open Spark stands still while its twin turns.
STOPPED = "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, j) => j === 1 ? { ...n, fans: [0, 2600], fan: 1300 } : n) }); null"


@needs_node
def test_the_head_of_the_sheet_keeps_a_note_in_sight_only_for_a_figure_in_a_state():
    """Under each of the four figures of the head stood a second line, like "GPU at 66 °C." or "No power limit
    reported.", and under the name of the Spark its role as a sentence. In the calm form a figure says its value,
    its unit and what it is; its note stands behind it and in the box of the bar, after the word of its figure.
    What cannot wait stays in sight: a figure in a state says its note under its word, and the box does not say
    it a second time. The role is one word beside the name, and the sentence waits in the box."""
    got = sheet(
        [
            OPEN,
            f"[{FIGS}, said('sp-tag'), S.nodes[1].head, explained('This Spark'), explained('Now'), {HEADINGS}.slice(0, 3)]",
            STOPPED,
            f"[{FIGS}, explained('Now')]",
        ]
    )
    figs, tag, head, role, now, headings = got[1]
    assert len(figs) == 4 and all(value and word and note for value, word, _, note, _ in figs), figs
    for _, word, under, note, state in figs:  # in sight only with a state; else behind the figure and in the box
        assert under == (note if state else ""), figs
        assert (f"{word[0].upper()}{word[1:]}: {note}" in now) is not bool(state), (word, now)
    assert tag == ["head" if head else "worker"] and "rank 1 of 4" in role, (tag, role)
    assert headings == ["This Spark", "Now", "Time range"], headings
    figs, now = got[3]
    _, _, under, note, state = figs[3]
    assert state == "bad" and under == note and "0 and 2,600" in under, figs[3]  # a fan that stands still
    assert note not in now, now  # and is not said a second time in the box


# The history answers with forty readings of the fans and of the two temperatures of every Spark, two seconds apart,
# the last one two seconds before the moment on the page: the open Spark turns its fans at 2,000 RPM in the last ten.
SLOW = """
{ const t = [...Array(40).keys()].map(k => S.t - 2 - 2 * (39 - k)), series = {};
  S.cluster.nodes.forEach((c, j) => { series[c.name + '.fan'] = t.map((_, k) => j === 1 && k >= 30 ? 2000 : 2600 + j);
    series[c.name + '.gpu_c'] = t.map(() => 60 + j); series[c.name + '.cpu_c'] = t.map(() => 55); });
  server.historyAnswers({ t, tier: 'raw', width: 2, series, peak: series, low: series, n: Object.fromEntries(Object.keys(series).map(key => [key, t.map(() => 1)])), events: [] }); }
null
"""


@needs_node
def test_what_held_earlier_stands_under_the_heading_of_the_limits_as_short_lines_to_click():
    """What held earlier in the stretch stood in the head of the sheet, above the bar that picks the stretch, a
    sentence a line: with every other stretch the head grew or shrank, and the bar under it moved. In the calm form
    the lines stand under the heading of the limits, over the curves that show them. Each says the state, for how
    long and when, and keeps its sentence behind it; slower fans say by how much. A click marks the stretch on
    every curve, and its figures come."""
    got = sheet(
        [
            SLOW,
            OPEN,
            "press('30 min'); null",
            "[sheet.children[0].under().filter(e => e.matches('ul.sp-earlier')).length, sheet.children.find(e => e.matches('section.sp-part')).children.map(e => e.className), earlier()]",
            "sheet.under().find(e => e.matches('ul.sp-earlier')).under().find(e => e.matches('button')).fire('click', {}); [strip(), sheet.classList.contains('figures')]",
        ]
    )
    in_head, parts, listed = got[3]
    assert in_head == 0 and parts == ["sp-h", "sp-open sp-earlier", "sp-card"], got[3]
    assert len(listed) == 1, listed
    word, held, full = listed[0]
    assert word == "Fans 23 % slower" and held.startswith("20 s, ") and held.endswith(" to now"), listed
    assert full.startswith("Fans slower than the others: 2,000 against 2,602 RPM, 23 % slower for 20 s, within "), full
    said, figures = got[4]
    assert said[0].endswith(", 18 s") and " to " in said[0] and said[1:] == ["Zoom", "Clear"] and figures is True, got[
        4
    ]


# As SLOW, but in the last twelve readings the fans of the open Spark turn at 2,500 RPM while each of the other three
# reads 0 in every third of them (a fan sample read as 0): in every reading two others turn at 3,000, so the open
# Spark is slower than their middle, and over the stretch each of the others has a mean of 2,000.
UNSHOWN = """
{ const t = [...Array(40).keys()].map(k => S.t - 2 - 2 * (39 - k)), series = {}, others = S.cluster.nodes.map(c => c.name).filter((_, j) => j !== 1);
  S.cluster.nodes.forEach((c, j) => { const turn = others.indexOf(c.name);
    series[c.name + '.fan'] = t.map((_, k) => k < 28 ? 2600 + j : j === 1 ? 2500 : k % 3 === turn ? 0 : 3000);
    series[c.name + '.gpu_c'] = t.map(() => 60 + j); series[c.name + '.cpu_c'] = t.map(() => 55); });
  server.historyAnswers({ t, tier: 'raw', width: 2, series, peak: series, low: series, n: Object.fromEntries(Object.keys(series).map(key => [key, t.map(() => 1)])), events: [] }); }
null
"""


@needs_node
def test_the_sentence_behind_slower_fans_says_no_share_the_means_of_the_stretch_do_not_show():
    """Slower fans are judged reading by reading, against the middle of the others in that reading; the sentence
    behind their line says the mean of this Spark against the middle of the others' means over the stretch. Where
    those means do not show what the readings did (here another Spark reads 0 now and then), the line says "Fans
    slower" without a share, but the sentence behind it counted a share of its own: "2,500 against 2,000 RPM, -25 %
    slower", and "0 % slower" where the means are level. One rule gives the share, for the line and the sentence."""
    got = sheet([UNSHOWN, OPEN, "press('30 min'); null", "earlier()"])
    assert len(got[3]) == 1, got[3]
    word, held, full = got[3][0]
    assert word == "Fans slower" and held.startswith("24 s, "), got[3]
    assert full.startswith("Fans slower than the others for 24 s, within "), full  # was ": 2,500 against 2,000 RPM, …"
    assert "% slower" not in full and "against" not in full, full


@needs_node
def test_two_cables_to_the_same_spark_are_told_apart_on_the_sheet():
    """Two Sparks alone share two cables. On the sheet of one of them both cables stood under the same words, "Sent
    to dgx0" and "Received from dgx0" twice, and under the group "To dgx0: …" twice: nobody could tell which curve
    and which rate belongs to which cable. A cable that is not the only one to its Spark says its port as well."""
    twins = "server.say({ ...LIVE, t: LIVE.t + 2, edges: LIVE.edges.map(e => e.from === S.nodes[1].rank ? { ...e, to: S.nodes[0].rank } : e) }); null"
    rows = "sheet.under().filter(e => e.matches('div.ch')).map(e => e.under().find(x => x.tagName === 'B').text).filter(w => /^(Sent to|Received from) /.test(w))"
    got = sheet(
        [
            twins,
            OPEN,
            f"[{rows}, S.edges.filter(e => e.from === S.nodes[1].rank).map(e => e.group), said('sp-facts').find(f => f.startsWith('To '))]",
        ]
    )
    words, ports, facts = got[2]
    assert len(words) == 4 and len(set(words)) == 4, words  # were two pairs of the same words
    assert all("dgx0" in word and any(word.endswith(" " + port) for port in ports) for word in words), (words, ports)
    assert all(f"To dgx0 {port}: " in facts for port in ports), facts  # was "To dgx0: …" twice


@needs_node
def test_what_is_no_curve_stays_under_its_group_and_what_only_explains_waits_in_the_box():
    """Under the curves of a group stands what is a fact of the moment and no curve: sizes, programs, links, who
    sets the fans. That ringtop reads the fans and never sets them stood there too, on every sheet, all the time:
    it explains, and waits in the box. In the table beside the others every Spark said "this Spark" or "open its
    page" under its name: its row says that as its tooltip. An event of the Spark is a line to click, its time and
    what happened; the click sets a mark at its moment."""
    rows = "sheet.under().filter(e => e.classList.contains('bs-row') && !e.classList.contains('bs-head')).map(e => [e.tagName, !!e.title, e.children[0].children.map(c => c.text)])"
    events = "sheet.under().filter(e => e.classList.contains('sp-ev'))"
    happened = ", events: [{ t: S.t - 20, level: 'warn', kind: 'heat', node: 'dgx1', text: 'A thing happened' }]"
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}, more=happened),
            OPEN,
            "press('30 min'); null",
            f"[said('sp-facts'), explained('Fans'), {rows}, {HEADINGS}.slice(-2), {events}.map(e => e.children.map(c => c.text))]",
            f"{events}[0].fire('click', {{}}); strip()",
        ]
    )
    facts, fans, table, last, listed = got[3]
    assert any(facts) and fans and fans not in " ".join(facts), (facts, fans)
    assert last == ["Beside the others", "Fans"], last
    assert [(tag, tip) for tag, tip, _ in table] == [
        ("BUTTON", True),
        ("DIV", True),
        ("BUTTON", True),
        ("BUTTON", True),
    ]
    assert [names for _, _, names in table] == [["dgx0"], ["dgx1"], ["dgx2"], ["dgx3"]], table  # the name alone
    assert len(listed) == 1 and listed[0][0].startswith("15 Jan, ") and listed[0][1] == "A thing happened", listed
    assert got[4][0].startswith("Mark at 15 Jan, ") and got[4][1:] == ["Clear"], got[4]


# A moment later on the page in which the open Spark answers and holds no reading: every figure of it is null, as
# the server sends what it does not hold; what the machine is stays. Its links are read as little.
UNREAD = (
    "const kept = ['name', 'rank', 'head', 'live', 'peers', 'mem_total_gb', 'mhz_max', 'disk_total_gb', 'capacity', 'startup'];"
    "server.say({ ...LIVE, t: LIVE.t + 2, why: { headline: 'x', points: [] },"
    " engine: { state: 'offline', error: 'Nothing answers.' },"
    " nodes: LIVE.nodes.map((n, j) => j === 1 ? Object.fromEntries(Object.keys(n).map(k => [k, kept.includes(k) ? n[k] : null])) : n),"
    " edges: LIVE.edges.map(e => e.from === 1 ? { ...e, gbps: null, rx: null, up: null, errors: null, capacity: null } : e) }); null"
)


@needs_node
def test_a_reading_the_moment_does_not_hold_is_a_dash_on_the_sheet_and_never_a_zero():
    """The server sends a reading it does not hold as null: not measured is unknown, not 0. A Spark that answers
    and holds no reading at all shows a dash for each of the four figures of its head and for the value of every
    curve whose stretch is empty too, and what stands under its groups names no size of 0: where a size cannot be
    said, the sentence has a dash or is not there. A curve with a recorded stretch shows its last point, and says
    so."""
    zero = r"(?<![\w.,])0(\.0+)?(?![\d.,])"  # a figure that reads 0, 0.0, 0.00 on its own: not the end of a name
    got = sheet(
        [
            answer({"mem_free_gb": "20"}),
            OPEN,
            "press('30 min'); null",
            UNREAD,
            f"[{FIGS}.map(f => f[0]), said('sp-doing')[0],"
            " sheet.under().filter(e => e.classList.contains('ch') && !e.classList.contains('lane') && !e.hidden)"
            ".map(e => [e.children[0].children[0].text, ...e.children[1].children.map(c => c.text)]), said('sp-facts'), said('sp-age')[0]]",
        ]
    )
    figs, doing, rows, facts, age = got[4]
    assert [value.split(" ")[0] for value in figs] == ["–", "–", "–", "–"], figs
    assert not re.search(zero, doing) and age.startswith("read at "), (doing, age)  # it answers, with nothing read
    limits, memory = rows[:4], rows[4:]
    assert [(value, said) for _, value, said in limits] == [("–", "no reading")] * 4, limits
    assert len(memory) == 1 and memory[0][0] == "Free memory" and memory[0][1] == "20.0", memory
    assert memory[0][2].startswith("GB, last point, "), memory  # the point of the recording, not a reading of now
    assert any(facts) and not any(re.search(zero, line) for line in facts), facts
    assert all("–" in line for line in facts if line), facts  # each sentence that stands says what it cannot say
