"""The rules of measurement of the page, run through node: what a number or a curve may say."""

import json
import re
import subprocess
import tempfile

from ringtop_parts.connect.server import PAGE
from tests.fixtures import needs_node


def measure(script: str):
    """Runs the rules of the page, its rules of measurement and its neutral lens through node and gives back what
    `script` returns.

    The files are the ones the server sends; they run here on their own, so a rule that reached for the page would
    fail."""
    rules = [(PAGE.parent / name).read_text() for name in ("rules.js", "measure.js", "neutral.js")]
    assert "function stretchStats" in rules[1], "the page lost its rules of measurement"
    source = "\n".join(rules) + "\nconsole.log(JSON.stringify((() => {" + script + "})()));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js") as file:
        file.write(source)
        file.flush()
        done = subprocess.run(["node", file.name], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout)


@needs_node
def test_a_scale_has_round_ends_that_hold_every_value_and_room_around_a_flat_trace():
    got = measure(
        "return [axisOf(57, 77, 3), axisOf(5, 5, 3), axisOf(null, null, 3), axisOf(0, 100, 2), niceStep(20, 3)];"
    )
    assert got[0] == {"lo": 50, "hi": 80, "ticks": [50, 60, 70, 80]}, got[0]
    assert got[1] == {"lo": 4.5, "hi": 5.5, "ticks": [4.5, 5, 5.5]}, got[1]  # a flat trace is no scale of no height
    assert got[2] == {"lo": 0, "hi": 1, "ticks": [0, 1]}, got[2]  # nothing read: no scale is made up from it
    assert got[3] == {"lo": 0, "hi": 100, "ticks": [0, 50, 100]} and got[4] == 10, got[3:]


@needs_node
def test_the_marks_of_a_time_axis_are_round_moments_of_the_local_clock():
    """An hour of the page shows quarter-hour marks; days are marked at local midnight, not at midnight UTC. And there
    are never more marks than asked for: one more would run into its neighbour's word."""
    got = measure(
        "const utc = () => 0, ahead = () => -60;"
        "return [timeTicks(0, 3600, 6, utc), timeTicks(100, 400, 6, utc), timeTicks(0, 3 * 86400, 4, ahead).ticks,"
        " timeTicks(0, 90 * 86400, 6, utc), timeTicks(0, 3600, 7, utc).ticks.length,"
        " timeTicks(0, 400 * 86400, 2, utc).ticks.length];"
    )
    assert got[0] == {"step": 900, "ticks": [0, 900, 1800, 2700, 3600]}, got[0]  # ten-minute marks would be seven
    assert got[1] == {"step": 60, "ticks": [120, 180, 240, 300, 360]}, got[1]
    assert got[2] == [82800, 169200, 255600], got[2]  # an hour ahead of UTC: local midnight is 23:00 UTC
    assert got[3]["step"] == 28 * 86400 and len(got[3]["ticks"]) == 4, got[3]  # 90 days: every fourth week
    assert got[4] == 7 and got[5] <= 2, got[4:]  # seven fit when seven are asked for; and a year still keeps to two


@needs_node
def test_the_marks_of_a_day_stay_at_local_midnight_across_a_change_of_the_clocks():
    """The clocks go back an hour in the night of day ten. With one fixed offset for the whole axis, every mark after
    that night stood at 23:00 of the day before and carried its date."""
    got = measure(
        "const change = 10 * 86400 + 3600, behind = t => t < change ? -120 : -60;"
        "const days = timeTicks(8 * 86400, 12 * 86400, 6, behind), hours = timeTicks(change - 7200, change + 7200, 6, behind);"
        "return [days.ticks, days.ticks.map(t => (t - behind(t) * 60) % 86400), hours.ticks.map(t => t - change)];"
    )
    assert got[0] == [770400, 856800, 946800, 1033200], got[0]  # 22:00 UTC before the change, 23:00 UTC after it
    assert got[1] == [0, 0, 0, 0], got[1]  # each one midnight by the clock that held at that moment
    assert got[2] == sorted(set(got[2])) and len(got[2]) <= 6, got[2]  # the hour that comes twice makes no mark twice


@needs_node
def test_a_change_of_the_clocks_inside_a_short_stretch_leaves_its_time_axis_its_marks():
    """The clocks go back an hour in the middle of a stretch of a few minutes. By the local clock that stretch ends
    before it begins, and its axis had no mark at all. Each side of the change is marked by its own clock. Where the
    clocks go forward the marks stay in the stretch and in order, and so they do when the stretch begins and ends
    between two seconds."""
    got = measure(
        "const back = t => t < 7200 ? 0 : 60, forward = t => t < 3600 ? -60 : -120;"
        "return [timeTicks(7100, 7300, 5, back), timeTicks(3500, 3700, 5, forward),"
        " timeTicks(7100.5, 7200.5, 5, back).ticks];"
    )
    assert got[0] == {"step": 60, "ticks": [7140, 7200, 7260]}, got[0]  # 01:59 before the change, 01:00 and 01:01 after
    assert got[1] == {"step": 60, "ticks": [3540, 3600, 3660]}, got[1]
    assert got[2] == sorted(set(got[2])) and 0 < len(got[2]) <= 5, got[2]
    assert all(7100.5 <= t <= 7200.5 for t in got[2]), got[2]


@needs_node
def test_a_moment_of_a_time_axis_names_seconds_and_the_day_only_where_they_matter():
    got = measure(
        "const at = (h, m, s) => new Date(2026, 10, 10, h, m, s).getTime() / 1000;"
        "return [timeWord(at(14, 5, 9), 600, false), timeWord(at(14, 5, 9), 10, false), timeWord(at(14, 5, 9), 600, true),"
        " timeWord(at(0, 0, 0), 3600, false), timeWord(at(14, 5, 9), 86400, false)];"
    )
    assert got == ["14:05", "14:05:09", "10 Nov, 14:05", "10 Nov, 00:00", "10 Nov"], got


@needs_node
def test_a_moment_falls_into_its_nearest_column_and_into_none_across_a_hole():
    got = measure(
        "const ts = [100, 110, 120, 200];"
        "return [columnAt(ts, 104, 10), columnAt(ts, 106, 10), columnAt(ts, 150, 10), columnAt(ts, 95, 10),"
        " columnAt(ts, 80, 10), columnAt([], 5, 10), columnAt(ts, null, 10)];"
    )
    assert got == [0, 1, -1, 0, -1, -1, -1], got


@needs_node
def test_the_figures_of_a_stretch_weigh_every_reading_and_say_what_was_not_kept():
    """The mean counts every reading once. Where a column kept no lowest reading, the minimum is only a bound."""
    got = measure(
        "const trace = { t: [0, 60, 120, 180], mean: [10, 20, null, 40], low: [8, null, null, 35], peak: [12, 25, null, 44],"
        " n: [30, 30, 0, 15] };"
        "const whole = { ...trace, low: [8, 15, null, 35] };"
        "return [stretchStats(trace), stretchStats(trace, 50, 130), stretchStats(whole), stretchStats(trace, 100, 140),"
        " stretchStats({ t: [0, 60], mean: [1, 3] })];"
    )
    every, part, whole, hole, bare = got
    assert every == {
        "last": 40,
        "lastT": 180,
        "mean": 20,
        "min": 8,
        "max": 44,
        "n": 75,
        "columns": 3,
        "bound": True,
    }, every
    assert part["mean"] == 20 and part["n"] == 30 and part["max"] == 25 and part["bound"], part
    assert part["min"] == 20, part  # no lowest reading kept: the mean of the minute is all that is known, as a bound
    assert whole["min"] == 8 and whole["bound"] is False, whole
    assert hole == {
        "last": None,
        "lastT": None,
        "mean": None,
        "min": None,
        "max": None,
        "n": 0,
        "columns": 0,
        "bound": False,
    }, hole
    assert bare["mean"] == 2 and bare["n"] == 2 and bare["bound"], bare  # a trace of means alone: each counts once


@needs_node
def test_a_line_and_its_band_break_where_nothing_was_read():
    got = measure(
        "const x = t => t, y = v => v;"
        "return [linePath([0, 10, 20, 100, 110], [1, 2, null, 3, 4], x, y, 25),"
        " bandPath([0, 10, 20, 30, 100, 110], [2, 2, 2, 3, 3, 3], [1, 1, null, 2, 2, 2], [3, 3, 3, 4, 4, 4], x, y, 25),"
        " gapOf(5, 'raw', 2), gapOf(1, 'raw', 2), gapOf(20, 'minute', 2)];"
    )
    assert got[0] == "M0.0 1.0L10.0 2.0M100.0 3.0L110.0 4.0", got[0]
    # two pieces: the column that has a mean and no lowest reading, and the hole of 70 s, each end one. A single
    # column is no band
    assert got[1] == "M0.0 3.0L10.0 3.0L10.0 1.0L0.0 1.0ZM100.0 4.0L110.0 4.0L110.0 2.0L100.0 2.0Z", got[1]
    assert got[2:] == [12.5, 5, 150], got[2:]


@needs_node
def test_one_missed_reading_breaks_neither_a_line_nor_its_band():
    """A column without a reading is passed over, and line and band go on behind it within their reach: a Spark
    misses a single reading now and then, and that is no hole. The band ends where a column has a mean and kept no
    lowest or no highest reading."""
    got = measure(
        "const x = t => t, y = v => v;"
        "return [linePath([0, 10, 20, 30], [1, null, 2, 3], x, y, 25),"
        " bandPath([0, 10, 20, 30], [2, null, 2, 3], [1, null, 1, 2], [3, null, 3, 4], x, y, 25),"
        " bandPath([0, 10, 20, 30, 40], [2, 2, 2, 3, 3], [1, 1, null, 2, 2], [3, 3, 3, 4, 4], x, y, 25),"
        " bandPath([0, 10, 20, 30, 40], [2, 2, 2, 3, 3], [1, 1, 1, 2, 2], [3, 3, null, 4, 4], x, y, 25)];"
    )
    assert got[0] == "M0.0 1.0L20.0 2.0L30.0 3.0", got[0]
    assert got[1] == "M0.0 3.0L20.0 3.0L30.0 4.0L30.0 2.0L20.0 1.0L0.0 1.0Z", got[
        1
    ]  # one band across the missed column
    pieces = "M0.0 3.0L10.0 3.0L10.0 1.0L0.0 1.0ZM30.0 4.0L40.0 4.0L40.0 2.0L30.0 2.0Z"
    assert got[2] == pieces and got[3] == pieces, got[2:]  # a mean without its lowest, or its highest: two pieces


@needs_node
def test_a_state_that_held_is_a_stretch_of_time_with_a_beginning_and_an_end():
    """A stretch has a beginning, an end and the time of its last column. A column that says no ends it, and so does
    a hole longer than a line would bridge; a column that was not read is passed over like a missed reading."""
    got = measure(
        "const ts = [0, 60, 120, 180, 240, 600], on = [1, 1, 0, 1, null, 1];"
        "return [spansWhere(ts, on, 60, 150), spansWhere(ts, on, 60, 150, 100), 0,"
        " spansWhere(ts, [0, 0, 0, 0, 0, 0], 60, 150), spansWhere([0, 60, 300], [1, 1, 1], 60, 150),"
        " spansWhere([0, 60, 120, 180], [1, null, 1, 0], 60, 150), spansWhere([0, 60, 120], [1, 1, 1], 60, 150),"
        " spansWhere([0, 60, 120], [null, null, null], 60, 150)];"
    )
    assert got[0] == [[0, 120, 60], [180, 240, 180], [600, 660, 600]], got[0]
    assert got[1] == [[0, 120, 60]] and got[3] == [], got[1:4]
    assert got[4] == [[0, 120, 60], [300, 360, 300]], got[4]  # a hole longer than the gap is not bridged
    assert got[5] == [[0, 180, 120]], got[5]  # one column that was not read does not cut a stretch in two
    # one-minute rows in columns narrower than a minute: one stretch, not three slivers
    assert got[6] == [[0, 180, 120]] and got[7] == [], got[6:]


@needs_node
def test_a_stretch_of_a_state_ends_no_later_than_the_column_that_says_no():
    """A column is named by its first reading, and after a hole that can lie late in it: a column a minute wide whose
    first reading came two seconds before the next column. It stood for a full minute from then on, and its stretch
    reached 58 s into a column that says the state did not hold. A column that says no ends the stretch at its own
    time at the latest."""
    got = measure(
        "return [spansWhere([58, 60], [1, 0], 60, 150), spansWhere([58, 60, 120], [1, 1, 0], 60, 150),"
        " spansWhere([0, 60, 120], [1, 1, 0], 60, 150), spansWhere([58, 60], [1, null], 60, 150)];"
    )
    assert got[0] == [[58, 60, 58]], got[0]
    assert got[1] == [[58, 120, 60]] and got[2] == [[0, 120, 60]], got[
        1:3
    ]  # a yes after it, and full columns: as before
    assert got[3] == [[58, 118, 58]], got[3]  # a column that was not read says nothing, and ends nothing


@needs_node
def test_how_long_a_state_held_counts_only_the_time_that_was_recorded():
    """A share of time counts for the readings that stand behind its column, not for the width of the column: one
    recorded minute in a column an hour wide is a minute. And a state that held for less than a second did hold."""
    got = measure(
        "const far = [0, 1000, 2000, 3000];"
        "return [heldSeconds([1], [1], 60, far, 9000), heldSeconds([0.5, 1, null, 0], [30, 1, 5, 9], 2, far, 9000),"
        " heldSeconds([1, 1], null, 2, far, 9000), heldSeconds([1, 1, 1], [1, 0, 1], 60, far, 9000),"
        " heldWord(0.004, true), heldWord(0, false), heldWord(90, true),"
        " columnReach(12.3, 'minute', 2), columnReach(4430, 'minute', 2), columnReach(0.02, 'raw', 2),"
        " columnReach(3.08, 'memory', 2)];"
    )
    assert got[:4] == [60, 32, 4, 120], got[:4]  # the column nobody read counts for nothing
    assert got[4:7] == ["under 1 s", "none", "90 s"], got[4:7]
    assert got[7:] == [60, 4430, 2, 3.08], got[
        7:
    ]  # a column reaches as far as it is wide, and no less than one reading


@needs_node
def test_the_time_a_state_held_does_not_reach_past_the_end_of_the_stretch():
    """A column stands for its readings from its time on, and the last one of a stretch can reach past its end. Seven
    readings two seconds apart in a stretch of thirteen seconds counted fourteen seconds at the power cap, and the
    minute that is still running counted for sixty seconds twenty seconds after it began. A column counts only as
    far as it lies in the stretch."""
    got = measure(
        "const ts = [100, 102, 104, 106, 108, 110, 112], all = ts.map(() => 1);"
        "return [heldSeconds(all, all, 2, ts, 113), heldSeconds(all, all, 2, ts, 120),"
        " heldSeconds([1, 1], [1, 1], 60, [0, 60], 80), heldSeconds([0.5], [2], 60, [0], 90),"
        " heldSeconds([1], [1], 60, [100], 90)];"
    )
    assert got == [13, 14, 80, 45, 0], got  # and a column that begins after the end counts for nothing, never less


@needs_node
def test_fans_are_called_slow_by_the_same_line_as_in_the_live_view_and_only_where_that_can_be_said():
    """Slow means: more than 15 % slower than the middle of the others while no more than 1.5 °C cooler. Where a part
    of that was not read, the rule says nothing: neither slow nor fine."""
    got = measure(
        "const others = [[2600, 2600, 2600, 2600, 2600, 2600, 2600, 2600], [2650, 2650, 2650, null, 2650, 2650, 2650, 2650],"
        " [2700, 2700, 2700, null, 2700, 2700, 2700, 2700]];"
        "const heats = [[65, 65, 65, 65, 65, 65, null, null], [65, 65, 65, 65, 65, 65, null, null],"
        " [66, 66, 66, 66, 66, 66, null, null]];"
        "const flags = slowFanFlags([2100, 2600, null, 2100, 2100, 2100, 2100, 2600], others, [70, 70, 70, 70, 50, null, 70, 70],"
        " heats);"
        "const node = (name, fan, gpu_c) => ({ name, fan, gpu_c });"
        "const odd = oddFans([node('a', 2100, 70), node('b', 2600, 65), node('c', 2650, 65), node('d', 2700, 66)]);"
        "return [flags, odd.map(n => n.name), warmerOf([1, null, 3, null], [2, 5, null, null]),"
        " sumOf([1, null, 3], [2, 5, null])];"
    )
    # slow and no cooler; as fast as the others; fan not read; only one other read; slower, but 15 °C cooler;
    # slower, its own temperature not read; slower, no temperature of the others read; as fast as the others is
    # fine whatever the temperatures say
    assert got[0] == [True, False, None, None, False, None, None, False], got[0]
    assert got[1] == ["a"], got[1]  # the live view names the same Spark from the same readings
    assert got[2] == [2, 5, 3, None] and got[3] == [3, None, None], got[2:]


@needs_node
def test_what_one_point_stands_for_a_length_of_time_and_a_number_are_said_in_words():
    got = measure(
        "return [resolutionWord('raw', 2, 2), resolutionWord('raw', 10, 2), resolutionWord('minute', 60, 2),"
        " resolutionWord('minute', 240, 2), resolutionWord('memory', 2, 2), 0,"
        " lengthWord(88 * 60), lengthWord(5280 + 3600 * 3), lengthWord(90),"
        " lengthWord(3 * 86400 + 7200), figure(2573.4), figure(21.34, 1), figure(null)];"
    )
    assert got[:6] == [
        "every reading, 2 s apart",
        "means of 10 s, read every 2 s",
        "one-minute means",
        "means of 4 min, from one-minute means",
        "every reading, 2 s apart",
        0,  # a mixed stretch has no words any more: with a band the server never answers one
    ], got[:6]
    assert got[6:] == [
        "88 min",
        "4 h 28 min",
        "90 s",
        "3 d 2 h",
        "2,573",
        "21.3",
        "–",
    ], got[6:]


@needs_node
def test_a_point_is_called_a_single_reading_only_where_its_column_holds_no_more_than_one():
    """A column half again as wide as the readings lie apart holds two of them now and then: its point is a mean."""
    got = measure(
        "return [resolutionWord('raw', 2.9, 2), resolutionWord('raw', 0.02, 2), resolutionWord('minute', 80, 2),"
        " resolutionWord('minute', 12.3, 2), resolutionWord('memory', 3.08, 2)];"
    )
    assert got == [
        "means of 3 s, read every 2 s",
        "every reading, 2 s apart",
        "means of 80 s, from one-minute means",
        "one-minute means",
        "means of 3 s, read every 2 s",
    ], got


@needs_node
def test_the_head_of_a_spark_gives_distances_to_its_limits_and_says_what_was_not_read():
    got = measure(
        "const n = { tlimit: 36, gpu_c: 60, util: 96, mhz: 2190, mhz_max: 3003, w: 21.34, w_limit: null, fan: 2573,"
        " fans: [2548, 2598] };"
        "const pick = list => list.map(f => [f.value, f.unit, f.what, f.note, f.state]);"
        "return [pick(headFigures(n)), pick(headFigures({ ...n, tlimit: 14, latched: true, fans: [0, 5100], fan: 2550 })),"
        " pick(headFigures({}))];"
    )
    assert got[0] == [
        ["36", "°C", "to the thermal limit", "GPU at 60 °C.", ""],
        ["73", "%", "of its top clock", "2,190 of 3,003 MHz.", ""],
        ["21.3", "W", "GPU power", "No power limit reported.", ""],
        ["2,573", "RPM", "fans, mean of both", "2,548 and 2,598 RPM.", ""],
    ], got[0]
    assert [row[4] for row in got[1]] == ["warn", "bad", "", "bad"], got[
        1
    ]  # near the limit under load, latch, a fan still
    assert [row[0] for row in got[2]] == ["–", "–", "–", "–"], got[2]
    assert got[2][0][3] == "The distance to the limit was not read." and got[2][3][3] == "No fan reading.", got[2]


def test_no_rule_of_measurement_stands_unused():
    """A rule nobody calls is checked here and says nothing on the page. Every function and every first name of a
    `const` that measure.js declares is used by a script of the page, measure.js included."""
    scripts = [file.read_text() for file in sorted(PAGE.parent.glob("*.js"))]
    declared = re.findall(r"^(?:function|const) ([A-Za-z_$][\w$]*)", (PAGE.parent / "measure.js").read_text(), re.M)
    assert len(declared) > 20, declared
    unused = [name for name in declared if sum(len(re.findall(rf"\b{re.escape(name)}\b", s)) for s in scripts) < 2]
    assert not unused, unused


@needs_node
def test_looking_back_the_head_calls_the_recorded_mean_of_the_fans_what_it_is():
    """The recording keeps one figure for the fans of a Spark: the mean of all of them. Looking back, that is not
    "one fan read"."""
    got = measure(
        "const fan = (n, past) => { const f = headFigures(n, past)[3]; return [f.value, f.what, f.note]; };"
        "return [fan({ fan: 2573, fans: [2573] }, true), fan({ fan: 2573, fans: [2573] }, false),"
        " fan({ fan: 2573, fans: [2573] }), fan({}, true)];"
    )
    assert got[0] == ["2,573", "fans", "Mean of the fans, as recorded."], got[0]
    assert got[1] == got[2] == ["2,573", "fan", "One fan read."], got[1:3]  # live, a Spark with one fan read
    assert got[3] == ["–", "fans", "No fan reading."], got[3]


@needs_node
def test_the_head_of_a_spark_counts_only_the_fans_that_were_read():
    """A fan that went unread for a sample stands in the list of a Spark as null, in its place. The head of the
    Spark said "fans, mean of both" over a figure that was the speed of the one fan read, and listed a dash beside
    it. It counts the fans that were read: one of them is "fan" and "One fan read.", the words it has for that."""
    got = measure(
        "const fan = n => { const f = headFigures(n)[3]; return [f.value, f.what, f.note, f.state]; };"
        "return [fan({ fan: 2600, fans: [null, 2600] }), fan({ fan: 2650, fans: [2640, 2660] }),"
        " fan({ fan: null, fans: [null, null] }), fan({ fan: 0, fans: [0, null], gpu_c: 70 })];"
    )
    assert got[0] == ["2,600", "fan", "One fan read.", ""], got[0]  # was "fans, mean of both", a dash "and 2,600 RPM."
    assert got[1] == ["2,650", "fans, mean of both", "2,640 and 2,660 RPM.", ""], got[1]
    assert got[2] == ["–", "fan", "No fan reading.", ""], got[2]
    assert got[3] == ["0", "fan", "One fan read.", "bad"], got[3]  # the one that was read stands still, and it is warm


@needs_node
def test_what_is_open_on_a_spark_says_slow_fans_in_the_words_of_the_rule():
    """The rule lets the Spark be up to 1.5 °C cooler than the others. "It is no cooler" would say more than that."""
    got = measure("return slowFanWord(2114);")
    assert got == (
        "Its fans turn more than 15 % slower than the middle of the others, at 2,114 RPM, "
        "while it is no more than 1.5 °C cooler than they are."
    ), got


@needs_node
def test_a_scale_never_zooms_into_less_than_a_row_can_show():
    """A trace that moves by less than the digits of its row show would get a scale whose marks all read the same.
    Told the least span it may have, a scale is at least that wide, around the middle of the trace."""
    got = measure(
        "return [axisOf(21.3401, 21.3404, 3, 0.4), axisOf(2573, 2574, 4, 4), axisOf(57, 77, 3, 4), axisOf(5, 5, 3, 0.04),"
        " axisOf(5, 5, 3)];"
    )
    assert got[0]["ticks"] == [21, 21.2, 21.4, 21.6], got[
        0
    ]  # four tenths wide: marks a row of one digit can tell apart
    assert got[1]["ticks"] == [2571, 2572, 2573, 2574, 2575, 2576], got[1]
    assert got[2] == {"lo": 50, "hi": 80, "ticks": [50, 60, 70, 80]}, got[2]  # wide enough already: as before
    assert got[3] == got[4] == {"lo": 4.5, "hi": 5.5, "ticks": [4.5, 5, 5.5]}, got[3:]  # a flat trace keeps its room


@needs_node
def test_a_stretch_with_minutes_in_it_counts_its_holes_by_the_minute():
    """Where single samples are no longer kept, a stretch holds one-minute rows. Two of them are a minute apart: a
    line that breaks after two and a half sampling intervals would cut every one of them off from the next."""
    got = measure(
        "return [gapOf(1, 'mixed', 2), gapOf(1, 'minute', 2), gapOf(1, 'memory', 2), gapOf(1, 'raw', 2),"
        " stepOf('mixed', 2), stepOf('minute', 2), stepOf('raw', 2), stepOf('memory', 5)];"
    )
    assert got == [150, 150, 5, 5, 60, 60, 2, 5], got


@needs_node
def test_a_state_holds_to_now_only_on_a_live_sheet_and_only_if_its_last_column_carries_it():
    """ "To now" is a claim about this moment. It needs a live sheet, the state in the last column that was read at
    all, and that column close enough to the end that a line would reach it."""
    got = measure(
        "const ts = [0, 60, 120, 180], holds = (flags, to, live) => holdsToNow(ts, flags, to, 150, live, to, 0);"
        "return [holds([0, 1, 1, 1], 200, true), holds([0, 1, 1, 1], 200, false),"
        " holds([1, 1, 1, 0], 200, true), holds([1, 1, 1, null], 200, true),"
        " holds([1, 1, null, null], 400, true), holds([null, null, null, null], 200, true),"
        " holdsToNow([], [], 200, 150, true, 200, 0)];"
    )
    # holds; looking back nothing holds "to now"; ended one column ago; one missed reading at the end is no end;
    # not read for longer than a line bridges; never read; nothing there
    assert got == [True, False, False, True, False, False, False], got


@needs_node
def test_to_now_allows_for_a_history_written_behind_the_clock_and_needs_a_stretch_that_is_current():
    """The history is written a few seconds behind the clock. On a sheet of half an hour the newest column begins up
    to nine seconds before the end, further than a line bridges there: "to now" came and went while the state held.
    And a stretch that ends well before the moment on the page, its renewal still out, says nothing about now."""
    got = measure(
        "const ts = [970, 973, 976, 979, 982, 985, 988, 991], yes = ts.map(() => 1);"
        "const holds = (now, behind, live = true) => holdsToNow(ts, yes, 1000, 7.7, live, now, behind);"
        "return [holds(1000, 0), holds(1000, 7), holds(1060, 7), holds(1007, 7), holds(1000, 7, false),"
        " writtenBehind(2), writtenBehind(5)];"
    )
    # nine seconds are more than a line bridges; with what the history is behind they are not; a stretch a minute
    # old says nothing about now; one a few seconds old does; looking back nothing does
    assert got[:5] == [False, True, False, True, False], got[:5]
    assert got[5:] == [7, 10], got[5:]  # written every 4 s, what is older than an interval and a second


@needs_node
def test_a_mark_snaps_to_the_point_it_is_set_on_and_a_pointer_finds_the_nearest_reading():
    """A mark stands on a point of the curves, so the figures between two marks count whole points. In a hole it
    stays where it was set. A pointer finds the nearest point as far as a column reaches: no less than from one
    reading to the next, however narrow the columns of a zoom are. And a mark outside the stretch is gone."""
    got = measure(
        "const ts = [100, 160, 220], fine = columnReach(0.02, 'raw', 2);"
        "return [snapTo(ts, 131, 60), snapTo(ts, 129, 60), snapTo(ts, 400, 60), snapTo([], 5, 60),"
        " marksWithin([90, 150], 100, 220), marksWithin([150, 210], 100, 220), marksWithin([10, 20], 100, 220),"
        " columnAt([100, 102, 104], 101.2, fine), columnAt([100, 102, 104], 101.2, 0.02),"
        " columnAt([0, 60, 120], 85, columnReach(12.3, 'minute', 2)), columnAt([100, 102, 104], 120, fine)];"
    )
    assert got[:4] == [160, 100, 400, 5], got[:4]
    assert got[4:7] == [[150], [150, 210], []], got[4:7]
    assert got[7:] == [1, -1, 1, -1], got[7:]  # between two readings a pointer reads the nearer one; in a hole, none


@needs_node
def test_a_row_and_a_cell_say_which_value_they_show():
    """A row shows the point under the cursor, else the newest reading of the Spark itself, else the last point of
    the stretch, and knows which of them it is. A cell of the table beside the others shows the point under the
    cursor, else the mean of the marked stretch, else its newest point."""
    got = measure(
        "const mean = [5, 6, null, 8, null], trace = { t: [0, 60, 120], mean: [10, 20, 60], n: [1, 1, 2] };"
        "return [shownValue(mean, 1, true, 9), shownValue(mean, -1, true, 9), shownValue(mean, -1, false, 9),"
        " shownValue(mean, -1, false, null), shownValue([null, null], -1, false, undefined),"
        " besideFigure(trace, 1, true, null, null), besideFigure(trace, -1, true, 0, 60),"
        " besideFigure(trace, -1, false, 0, 60), besideFigure(trace, -1, false, null, null)];"
    )
    assert got[:5] == [
        {"v": 6, "at": 1, "what": "cursor"},
        {"v": None, "at": -1, "what": "cursor"},  # a cursor in a hole shows no value, not the one of now
        {"v": 9, "at": -1, "what": "now"},
        {"v": 8, "at": 3, "what": "last"},
        {"v": None, "at": -1, "what": "none"},
    ], got[:5]
    assert got[5:] == [
        {"v": 20, "what": "cursor"},
        {"v": None, "what": "cursor"},
        {"v": 15, "what": "marked"},
        {"v": 60, "what": "newest"},
    ], got[5:]


@needs_node
def test_the_sheet_asks_the_history_again_only_when_no_question_is_out_and_the_moment_has_moved():
    """One question at a time: a slow history is waited for, not asked again every other second (each new question
    made the page drop the answer that was on its way). A question out for longer than half a minute is lost. Live,
    the stretch is asked again once the moment has moved on by a column, between 10 and 60 s. Looking back it is
    asked as soon as the moment lies before the end of what is loaded, however little: the curves would show what
    came after it."""
    got = measure(
        "const q = (out, to, width, at, past) => mayAsk({ out, to, width, at, past });"
        "return [q(5, 100, 60, 500, false), q(31, 100, 60, 500, false), q(null, null, 0, 500, false),"
        " q(null, 100, 3, 109, false), q(null, 100, 3, 110, false), q(null, 100, 4430, 159, false),"
        " q(null, 100, 4430, 160, false), q(null, 100, 60, 99.9, true), q(null, 100, 60, 130, true),"
        " q(null, 100, 60, 160, true), q(null, 100, 60, 100, true), q(null, 100, 60, 100, false)];"
    )
    assert got == [False, True, True, False, True, False, True, True, False, True, False, False], got


@needs_node
def test_a_drag_begins_on_a_moment_grows_with_the_pointer_and_ends_with_the_button():
    """A press on a plot that has a moment under it begins a drag; a plot that has drawn nothing gives none. A press
    without a move sets a mark, a drag zooms. A pointer that comes back with no button held ends the drag without
    doing anything: the button came up somewhere else. And a zoom never ends after the moment on the page."""
    got = measure(
        "const down = (t, main = true) => dragStep(null, { type: 'down', x: 100, t, main, held: true }), d = down(50).drag;"
        "return [down(50), down(null), down(50, false),"
        " dragStep(d, { type: 'move', x: 103, t: 51, held: true }), dragStep(d, { type: 'move', x: 130, t: 60, held: true }),"
        " dragStep(d, { type: 'move', x: 130, t: null, held: true }), dragStep(d, { type: 'move', x: 130, t: 60, held: false }),"
        " dragStep(d, { type: 'cancel' }), dragStep(d, { type: 'up' }), dragStep({ ...d, to: 20 }, { type: 'up' }),"
        " dragStep(null, { type: 'up' }), dragStep(null, { type: 'move', x: 5, t: 9, held: false }),"
        " zoomTo(100, 104, 12, 105), zoomTo(100, 400, 12, 1000), zoomTo(100, 104, 12, 1000)];"
    )
    drag = {"x": 100, "from": 50, "to": None}
    assert got[:3] == [{"drag": drag}, {"drag": None}, {"drag": None}], got[:3]  # no moment, or another button: no drag
    assert got[3] == {"drag": drag} and got[4] == {"drag": {**drag, "to": 60}} and got[5] == {"drag": drag}, got[3:6]
    assert got[6] == {"drag": None} and got[7] == {"drag": None}, got[6:8]  # the button is up, or the pointer was taken
    assert got[8] == {"drag": None, "act": ["mark", 50]} and got[9] == {"drag": None, "act": ["zoom", 20, 50]}, got[
        8:10
    ]
    assert got[10] == {"drag": None} and got[11] == {"drag": None}, got[10:12]
    assert got[12:] == [{"span": 12, "end": 105}, {"span": 300, "end": 400}, {"span": 12, "end": 108}], got[12:]


@needs_node
def test_the_end_of_a_drag_follows_the_pointer_back_to_where_it_began():
    """The end of a drag was moved only while the pointer was more than a few pixels from the start. A pointer that
    came back in one step left the end where it had been, and the release zoomed to a stretch the pointer had left.
    The end is wherever the pointer is: back at the start there is none, and the release sets a mark like a click."""
    got = measure(
        "const d = dragStep(null, { type: 'down', x: 100, t: 1000, main: true, held: true }).drag;"
        "const out = dragStep(d, { type: 'move', x: 200, t: 1100, held: true }).drag;"
        "const back = dragStep(out, { type: 'move', x: 102, t: 1002, held: true }).drag;"
        "return [out.to, back.to, dragStep(back, { type: 'up' }),"
        " dragStep(out, { type: 'move', x: 102, t: null, held: true }).drag.to,"
        " dragStep(out, { type: 'move', x: 94, t: 994, held: true }).drag.to];"
    )
    assert got[:3] == [1100, None, {"drag": None, "act": ["mark", 1000]}], got[:3]
    assert got[3:] == [1100, 994], got[3:]  # over a place without a moment it stays; on the other side it goes on


@needs_node
def test_an_answer_of_the_history_is_a_stretch_only_with_its_columns_and_its_traces():
    got = measure(
        "return [isStretch({ t: [], series: {} }), isStretch({ t: [1], series: { a: [2] }, peak: {} }), isStretch({ error: 'x' }),"
        " isStretch(null), isStretch({ t: 5, series: {} }), isStretch({ t: [] }), isStretch([]), isStretch('down')];"
    )
    assert got == [True, True, False, False, False, False, False, False], got


@needs_node
def test_the_moment_under_a_pointer_is_counted_in_the_units_the_plot_is_drawn_in():
    """A browser lays a drawing out to a fraction of a pixel, or zoomed; the plot is drawn in whole units of its
    own. The room beside the curve is in those units, so the place of the pointer has to be brought into them first."""
    got = measure(
        "return [momentAt(317 * 600.4 / 600, 600.4, 600, 44, 10, 0, 1000), momentAt(1000, 2128, 1064, 44, 10, 0, 1010),"
        " momentAt(5, 600, 600, 44, 10, 100, 200), momentAt(900, 600, 600, 44, 10, 100, 200), momentAt(317, 0, 600, 44, 10, 0, 1000)];"
    )
    assert abs(got[0] - 500) < 1e-6, got[0]  # the middle of the curve, on a drawing laid out 0.4 px wider than drawn
    assert abs(got[1] - 456) < 1e-6, got[1]  # shown at twice its size: screen pixel 1000 is unit 500 of the drawing
    assert got[2:] == [100, 200, 500], got[
        2:
    ]  # held inside the stretch; a drawing without a width on the screen: as drawn


@needs_node
def test_the_note_under_the_lanes_says_what_each_kind_of_lane_can_show():
    """Three lanes are time nvidia-smi counted. Two are judged from the points of the curves: where a point is the
    mean of a stretch, a shorter spell inside it does not show, and two means do not prove both held at once."""
    got = measure(
        "return [laneNote(240, 'minute', 2), laneNote(12.3, 'minute', 2), laneNote(10, 'raw', 2), laneNote(2, 'raw', 2),"
        " laneNote(0.02, 'memory', 2)];"
    )
    counted = "The first three lanes are time nvidia-smi counted."
    assert got[0] == (
        counted + " The last two are judged from the means of each point (4 min): a shorter spell inside a point"
        " does not show, and two means do not prove that both held at once."
    ), got[0]
    assert "each point (60 s)" in got[1] and "each point (10 s)" in got[2], got[1:3]  # a minute row is a mean too
    assert got[3] == got[4] == counted + " The last two are judged reading by reading.", got[3:]


@needs_node
def test_a_lane_without_a_judgement_says_whether_it_was_not_recorded_or_could_not_be_judged():
    """A state that is judged from several readings can lack a judgement in every point of a stretch although its
    own reading was recorded: the fans of a Spark with fewer than two others to compare with. That is not "not
    recorded". Without its own reading it is, like a brake nobody counted."""
    got = measure(
        "return [unjudgedWord(false, false), unjudgedWord(false, true), unjudgedWord(undefined, false),"
        " unjudgedWord(true, true), unjudgedWord(true, false)];"
    )
    assert got[:3] == ["not recorded"] * 3, got[:3]
    assert got[3:] == [
        "not judged: fewer than two other Sparks with a fan reading",
        "not judged: a reading it needs was not recorded",
    ], got[3:]


@needs_node
def test_a_lane_that_says_something_only_later_says_whether_it_was_recorded_or_judged_from_then():
    """A lane whose first point lies later than the first reading of its Spark says from when. For a brake nvidia-smi
    counts that is when its recording began. A state that is judged from several readings was judged from then on:
    its own reading may have been recorded all along."""
    got = measure("return [lateWord(undefined, '21:26'), lateWord(true, '21:26')];")
    assert got == [", recorded from 21:26", ", judged from 21:26"], got


@needs_node
def test_a_reading_that_is_missing_is_no_part_of_the_figure_of_all_sparks():
    """The figure of all Sparks in the head of a view runs from the lowest reading to the highest. A reading that is
    missing counted as 0 there: from 0 to 2,400 for one Spark at 2,400 RPM and one without a reading, 0 for none at all."""
    got = measure(
        "return [spreadWord([null]), spreadWord([2400, null]), spreadWord([undefined, 76, 83]), spreadWord([0, 2400])];"
    )
    assert got == ["–", "2,400", "76–83", "0–2,400"], got  # a fan that was read as standing still is a reading


@needs_node
def test_a_stretch_whose_means_do_not_show_slower_fans_is_said_without_a_share():
    """A stretch of slower fans is judged point by point; its line says by how much from the means over the stretch.
    Where those means do not show it (the own mean no lower than the middle of the others), the line said a share
    of 0 % or a negative one: "-25 % slower". It then says who was slower and no figure, as it does without a mean."""
    got = measure(
        "return [slowerWords('dgx1', 2500, 2000), slowerWords('dgx1', 2000, 2000), slowerWords('dgx1', 1999, 2000),"
        " slowerWords('dgx1', 1980, 2000).short];"
    )
    plain = {"short": "dgx1 slower", "long": "dgx1: fans slower than the others"}
    assert got == [plain, plain, plain, "dgx1 1 % slower"], got  # a share that rounds to 0 % is none either


@needs_node
def test_the_wide_form_is_asked_for_by_a_wish_of_its_own_and_not_inside_another():
    """`?cooling=wide` asks for the wide form. The same letters inside the value of another wish did too:
    `?note=?cooling=wide`. The address is read wish by wish."""
    got = measure(
        "return ['?cooling=wide', '?names=neutral&cooling=wide', '?cooling=wide&names=neutral', '?note=?cooling=wide',"
        " '?q=a?cooling=wide', '?cooling=wider', '?xcooling=wide', ''].map(wideAsked);"
    )
    assert got == [True, True, True, False, False, False, False, False], got


@needs_node
def test_the_word_beside_a_cursor_stands_before_it_where_it_would_not_end_on_the_curve():
    """The word beside the cursor of a plot stands after it, 7 px away, and before it where it would run past the end
    of the curve into the figures of the scale. Where that is hangs on how wide the word is, not on a fixed 96 px."""
    got = measure(
        "return [wordBefore(100, 99, 308), wordBefore(202, 99, 308), wordBefore(203, 99, 308), wordBefore(220, 81, 308)];"
    )
    assert got == [False, False, True, False], got  # 202 + 7 + 99 ends on the curve, one pixel on it does not


@needs_node
def test_the_name_of_a_dot_goes_above_it_and_below_once_the_room_above_is_used_up():
    """In a picture of dots every dot carries its name above it, and above the name of a neighbour that sits in the
    same place. Stacked upwards only, the names of dots at the upper edge left the picture. A name that would stand
    higher than it can be read goes below its dot, under the names that are already there."""
    got = measure(
        "const at = (x, y, placed) => namePlace(x, y, placed, 11);"
        "return [at(100, 100, []), at(100, 100, [[100, 89]]), at(100, 100, [[148, 89]]), at(100, 26, []),"
        " at(100, 26, [[100, 15]]), at(100, 26, [[100, 15], [100, 44]]), at(100, 30, [[100, 19]])];"
    )
    assert got[:3] == [89, 76, 89], got[:3]  # above the dot; above a neighbour's name; one far to the side is none
    assert got[3:] == [15, 44, 57, 48], got[3:]  # at the upper edge: one name fits above, the others go below


@needs_node
def test_a_state_listed_as_earlier_says_how_long_it_held_inside_its_stretch():
    """A stretch of a state is the points in which it held at all. Listed as "19:37 to 19:47, 10 min" it reads as
    ten minutes at the power cap, where nvidia-smi counted 18 seconds of them; and a state that is judged point by
    point was read in fewer points than its stretch is long where a reading was missed. Every line says the time
    that was recorded, within its stretch."""
    got = measure(
        "return [earlierWord('At its power cap', 18, '9 Nov, 19:37 to 19:47'),"
        " earlierWord('Fans slower than the others: 2,164 against 2,607 RPM, 17 % slower', 1200, '9 Nov, 23:09 to 23:30'),"
        " earlierWord('Power brake', 0.004, '18:00:00 to now'), earlierWord.length];"
    )
    assert got == [
        "At its power cap for 18 s, within 9 Nov, 19:37 to 19:47.",
        "Fans slower than the others: 2,164 against 2,607 RPM, 17 % slower for 20 min, within 9 Nov, 23:09 to 23:30.",
        "Power brake for under 1 s, within 18:00:00 to now.",
        3,
    ], got  # one form for every lane: what, for how long, within which stretch


@needs_node
def test_a_recording_begins_late_only_if_more_than_the_room_between_readings_is_missing():
    """Zoomed in to single readings, the first reading of a stretch lies up to one interval after its start. That is
    the room between two readings, not a recording that began later."""
    got = measure(
        "const fine = columnReach(0.076, 'raw', 2);"
        "return [beginsLate(100.9, 100, fine), beginsLate(106, 100, fine), beginsLate(107, 100, fine),"
        " beginsLate(100 + 3 * 300, 100, columnReach(300, 'minute', 2)), beginsLate(100 + 3 * 300 + 1, 100, 300)];"
    )
    assert got == [False, False, True, False, True], got


@needs_node
def test_the_peak_of_a_chart_is_its_highest_reading_and_none_where_nothing_was_read():
    """A chart of two traces says its peak in its head. The search for it began at 1: a link without any traffic, or
    without any reading, had a "peak 1.0 Gb/s" nobody measured. The peak is the highest reading of the traces, 0
    where every reading was 0, and none where there is no reading."""
    got = measure(
        "const quiet = { t: [1, 2], v: [0, 0] }, busy = { t: [1, 2], v: [.4, 2.5] };"
        "return [peakOf([quiet, quiet]), peakOf([quiet, busy]), peakOf([undefined, { t: [], v: [] }]),"
        " peakOf([busy, undefined])];"
    )
    assert got == [0, 2.5, None, 2.5], got


@needs_node
def test_a_length_of_days_is_rounded_to_the_hour_not_cut():
    """From two days on a length is said in days and hours. The minutes were cut off instead of rounded: 48 h 59 min
    read "2 d", and a minute short of four days "3 d 23 h". Shorter lengths keep their minutes."""
    got = measure(
        "return [lengthWord(176340), lengthWord(3 * 86400 + 23 * 3600 + 59 * 60), lengthWord(172800),"
        " lengthWord(47 * 3600 + 59 * 60), lengthWord(48 * 3600 + 29 * 60), lengthWord(48 * 3600 + 30 * 60)];"
    )
    assert got == ["2 d 1 h", "4 d", "2 d", "47 h 59 min", "2 d", "2 d 1 h"], got


@needs_node
def test_slow_fans_are_judged_against_the_same_sparks_for_speed_and_for_warmth():
    """The rule compares a Spark with the middle of the others: their fans, and their warmth. The two middles were
    taken over different Sparks: the fans of A and B with the warmth of B and C, or three fans with the warmth of
    one. Slower than the others is decided on their fans, as before. Whether it is no cooler is then asked of the
    others whose fans and whose warmth were both read, at least two of them, and both middles are theirs."""
    got = measure(
        "const one = slowFanFlags([800], [[1000], [1000], [1000]], [60], [[40], [null], [null]]);"
        "const apart = slowFanFlags([800], [[1000], [1000], [null]], [60], [[null], [40], [40]]);"
        "const theirs = slowFanFlags([900], [[3000], [3000], [1000]], [69], [[70], [null], [70]]);"
        "const two = slowFanFlags([800], [[1000], [1000], [null]], [60], [[40], [41], [null]]);"
        "const fast = slowFanFlags([990], [[1000], [1000], [1000]], [60], [[null], [null], [null]]);"
        "return [one[0], apart[0], theirs[0], two[0], fast[0]];"
    )
    # the warmth of one other alone; fans of two, warmth of two, but only one with both; slower than all three, not
    # slower than the two it can be compared with; two others with both readings; as fast as the others needs no warmth
    assert got == [None, None, False, True, False], got


@needs_node
def test_the_line_of_the_fan_rule_is_drawn_where_the_rule_itself_draws_it():
    """A curve of fans carries the line below which they count as slow: 15 % under the middle of the fans of the
    others, column by column, and nothing where fewer than two of them were read. It is the very line the rule
    judges by: fans just above it are not slow, fans just below it are."""
    got = measure(
        "const others = [[1000, 1000, null], [2000, null, null], [3000, 3000, 3000]], line = fanFloor(others);"
        "const heats = [[50, 50, 50], [50, 50, 50], [50, 50, 50]];"
        "return [line, slowFanFlags([1701, 849, 500], others, [50, 50, 50], heats)];"
    )
    assert got == [[1700, 850, None], [False, True, None]], got


@needs_node
def test_a_word_of_a_time_axis_stands_where_it_has_room_or_not_at_all():
    """The words of a time axis stand under their marks. One that would run into the word before it is left out.
    The axis has no room at its sides (the scale stands at the right of its curves): a word at an end is moved in
    beside its mark instead of running out, since its first word names the day."""
    got = measure(
        "return [wordPlace(100, 20, -Infinity, 300), wordPlace(100, 20, 75, 300), wordPlace(100, 20, 72, 300),"
        " wordPlace(10, 20, -Infinity, 300), wordPlace(295, 20, 0, 300), wordPlace(30, 20, 15, 300)];"
    )
    assert got[:3] == [100, None, 100], got[:3]  # room, too near the word before it (8 px between two words), just room
    assert got[3:] == [20, 280, None], got[3:]  # moved in at either end; and still not into the word before it


@needs_node
def test_the_calm_word_of_a_row_is_its_unit_unless_its_value_is_neither_now_nor_under_the_cursor():
    """What stands beside the value of a calm row: the unit for a reading of now or under the cursor, the unit and
    which point it is for the last point of a stretch, and for no reading that alone."""
    got = measure(
        "return [quietWord('now', 'RPM', ''), quietWord('cursor', 'RPM', ''), quietWord('last', 'RPM', 'last point, 21:40'),"
        " quietWord('none', 'RPM', ''), quietWord('last', '', 'last point, 21:40'), quietWord('now', '', '')];"
    )
    assert got == ["RPM", "RPM", "RPM, last point, 21:40", "no reading", "last point, 21:40", ""], got


@needs_node
def test_the_marks_of_a_board_are_said_in_a_few_words():
    """What a calm bar says of the marks: a marked stretch with its length, one marked point, one mark that waits
    for its second, and nothing without a mark. How a moment and a stretch are worded is handed in."""
    got = measure(
        "const say = { stretch: (a, b) => `S(${a},${b})`, at: t => `A(${t})` };"
        " return [marksWord(100, 400, 100, say), marksWord(100, 100, 100, say), marksWord(null, null, 250, say), marksWord(null, null, null, say)];"
    )
    assert got == ["S(100,400), 5 min", "One point, A(100)", "Mark at A(250)", ""], got


@needs_node
def test_the_readings_of_all_sparks_are_one_figure_from_the_lowest_to_the_highest():
    """The head of the cooling view says the fans and the warmth of all Sparks in one figure each."""
    got = measure(
        "return [spreadWord([2579.4, 3226, 2600]), spreadWord([76, 76.2]), spreadWord([83]), spreadWord([])];"
    )
    assert got == ["2,579–3,226", "76", "83", "–"], got


@needs_node
def test_slower_fans_are_said_short_on_their_line_and_in_full_behind_it():
    """A stretch of slower fans is a line to click: who, and by how much. The figures behind it stand in its
    tooltip. Where one of the two means was not read, neither a share nor figures are made up."""
    got = measure(
        "return [slowerWords('dgx1', 2000, 2602), slowerWords('dgx1', null, 2602), slowerWords('dgx1', 2000, 0)];"
    )
    assert got[0] == {"short": "dgx1 23 % slower", "long": "dgx1: fans at 2,000 against 2,602 RPM, 23 % slower"}, got[0]
    assert got[1] == got[2] == {"short": "dgx1 slower", "long": "dgx1: fans slower than the others"}, got[1:]


@needs_node
def test_the_sign_for_slower_fans_follows_the_cursor_and_else_says_what_holds_up_to_now():
    """A row of fans carries a sign while they count as slower: at the column under the cursor while one stands on
    the board (not in a hole, not where the judgement is missing), else only if the slow stretch holds up to now."""
    got = measure(
        "const flags = [false, true, null];"
        " return [slowerShown(flags, 1, true, false), slowerShown(flags, 0, true, true), slowerShown(flags, 2, true, true),"
        " slowerShown(flags, -1, true, true), slowerShown(flags, -1, false, true), slowerShown(flags, 1, false, false)];"
    )
    assert got == [True, False, False, False, True, False], got


@needs_node
def test_a_curve_of_the_wide_form_is_as_tall_as_lets_every_card_stand_on_the_panel():
    """The height of one curve where every Spark is a card: what the panel has under its head, less the time axis
    and the gaps between the cards, shared by the cards, less what a card adds around its curve; between 44 and
    96 px."""
    got = measure(
        "return [curveHeight(507, 129, 4), curveHeight(700, 129, 4), curveHeight(900, 129, 4), curveHeight(700, 129, 2), curveHeight(1100, 625, 4), curveHeight(300, 129, 4)];"
    )
    assert got == [44, 92, 96, 96, 68, 44], got


@needs_node
def test_the_address_asks_for_the_wide_form_of_cooling_only_with_its_own_word():
    got = measure(
        "return ['?cooling=wide', '?names=neutral&cooling=wide', '?cooling=wide&names=neutral', '', '?cooling=wider', '?xcooling=wide', '?cooling=narrow'].map(wideAsked);"
    )
    assert got == [True, True, True, False, False, False, False], got


@needs_node
def test_a_figure_of_a_head_keeps_its_note_in_sight_only_while_it_carries_a_state():
    """In the calm form the head of a Spark says value, unit and word of its four figures. The note of a figure
    waits: behind the figure, and in one paragraph for the box of the bar, each note after the word of its figure.
    What cannot wait does not: a figure in a state (near the limit under load, a clock that is stuck, a fan that
    stands still) says its note under its word, and the paragraph leaves that one out."""
    got = measure(
        "const n = { tlimit: 36, gpu_c: 60, util: 96, mhz: 2190, mhz_max: 3003, w: 21.34, w_limit: null, fan: 2573,"
        " fans: [2548, 2598] };"
        "const calm = headFigures(n), hot = headFigures({ ...n, tlimit: 14, fans: [0, 5100], fan: 2550 });"
        "return [calm.map(urgentNote), figureNotes(calm), hot.map(urgentNote), figureNotes(hot), figureNotes(headFigures({}))];"
    )
    assert got[0] == ["", "", "", ""], got[0]
    assert got[1] == (
        "To the thermal limit: GPU at 60 °C. Of its top clock: 2,190 of 3,003 MHz. "
        "GPU power: No power limit reported. Fans, mean of both: 2,548 and 2,598 RPM."
    ), got[1]
    assert got[2] == ["GPU at 60 °C.", "", "", "0 and 5,100 RPM."], got[2]  # near the limit under load, a fan still
    assert got[3] == "Of its top clock: 2,190 of 3,003 MHz. GPU power: No power limit reported.", got[3]
    assert got[4].startswith("To the thermal limit: The distance to the limit was not read. GPU clock: "), got[4]
