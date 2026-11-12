"""One plot of the page, driven without a browser: what it keeps when it is drawn again."""

from tests.fixtures import needs_node
from tests.test_page_sheet import sheet

# One plot on its own: ten points a hundred seconds apart. `seen` reads its cursor, its two marks and the shade
# between them: shown or not, and where.
PLOT = """
globalThis.plot = makePlot(document.createElement('div'), { word: 'a reading' });
globalThis.stretch = (from, to) => { const t = [...Array(10).keys()].map(k => 1000 + 100 * k); return { from, to, t, mean: t.map((_, k) => k), gap: 250, width: 100, reach: 100 }; };
globalThis.seen = () => ['cur', 'mark', 'sel'].flatMap(cls => plot.svg.under().filter(e => e.getAttribute('class') === cls)
  .map(e => e.style.display === 'none' ? 'off' : e.getAttribute(cls === 'sel' ? 'x' : 'x1')));
null
"""


@needs_node
def test_a_plot_drawn_again_puts_its_cursor_and_its_marks_where_they_belong_on_the_new_stretch():
    """A plot is drawn again whenever its stretch moves on or the reader zooms in. Its cursor and its marks stayed
    where they stood on the old stretch, at the place of another moment, until whoever uses the plot set them again;
    a second user of plots would have had to know that. A plot keeps the moment of its cursor and of its marks and
    puts them back itself: the moment 1400 stands in the middle of the stretch from 1000 and at the left edge of the
    one from 1400, and a mark the new stretch has left behind is not drawn."""
    got = sheet(
        [
            PLOT,
            "plot.paint(stretch(1000, 1900)); plot.cursor(1400); plot.select(1200, 1600); seen()",
            "plot.paint(stretch(1400, 1900)); seen()",
            "plot.cursor(null); plot.select(null, null); plot.paint(stretch(1000, 1900)); seen()",
        ]
    )
    assert got[1] == ["492.9", "268.4", "717.3", "268.4"], got[1]  # cursor, the two marks, where the shade begins
    assert got[2] == ["44.0", "off", "448.0", "44.0"], got[2]  # the same moments on the stretch that begins at 1400
    assert got[3] == ["off", "off", "off", "off"], got[3]  # taken away, they stay away


@needs_node
def test_a_plot_on_a_scale_it_shares_spans_that_scale_and_no_rounder_one():
    """Several plots are compared on one scale, which is said once beside them: "40 to 90". Each plot rounded the
    scale it was handed once more, to two steps: it drew 0 to 100 under a head that said 40 to 90, and its curve was
    half as tall as the words promised. A plot draws the scale it is handed."""
    got = sheet(
        [
            PLOT,
            "plot.paint({ ...stretch(1000, 1900), range: [40, 90] });"
            " plot.svg.under().filter(e => e.tagName === 'TEXT' && e.parentNode.getAttribute('class') === 'grid').map(e => e.text)",
        ]
    )
    assert got[1] == ["40", "90"], got[1]


# The time axis of a sheet on its own, a day long: `words` reads the words under its marks, `marks` counts the marks.
AXIS = """
globalThis.host = document.createElement('div'); globalThis.axis = makeAxis(host);
globalThis.words = () => host.under().filter(e => e.tagName === 'TEXT').map(e => [e.text, +e.getAttribute('x')]);
globalThis.marks = () => host.under().filter(e => e.tagName === 'LINE').length;
null
"""


@needs_node
def test_a_time_axis_measures_its_words_and_leaves_out_the_one_that_finds_no_room():
    """The axis guessed how wide a word is from its letters, 5.8 px each. In larger type the guess is too small and
    two words run into each other; in a narrow one it leaves out words that had room. It measures each word as it is
    drawn: with letters 20 px wide a word takes its room and every second one is left out, each mark stays. Where a
    drawing cannot measure (no browser), the guess stands in."""
    got = sheet(
        [
            AXIS,
            "axis(1794300000, 1794386400, []); [marks(), words().length]",
            "server.measureWords(20); axis(1794300000, 1794386400, []); const w = words(); server.measureWords(null);"
            " [marks(), w.length, Math.min(...w.slice(1).map((x, k) => x[1] - x[0].length * 10 - (w[k][1] + w[k][0].length * 10)))]",
        ]
    )
    assert got[1][0] == got[1][1] and got[1][0] > 8, got[1]  # guessed: every mark has its word
    count, kept, gap = got[2]
    assert count == got[1][0] and kept < count and gap >= 8, got[2]  # measured: fewer words, 8 px between any two


# A plot in the calm form, 72 px tall, and what a check reads of it: the words of its scale with their place and
# anchor, where its line begins, the foot of a state that held, and the word beside its cursor.
CALM = """
globalThis.quietPlot = makePlot(document.createElement('div'), { word: 'a reading', calm: true, height: 72 });
globalThis.scale = p => p.svg.under().filter(e => e.tagName === 'TEXT' && e.parentNode.getAttribute('class') === 'grid').map(e => [e.text, +e.getAttribute('x'), e.getAttribute('text-anchor')]);
globalThis.begins = p => p.svg.under().find(e => e.getAttribute('class') === 'line').getAttribute('d').slice(0, 6);
globalThis.foot = p => p.svg.under().filter(e => e.parentNode.getAttribute('class') === 'held').map(e => [e.getAttribute('y'), e.getAttribute('height')]);
globalThis.beside = p => { const w = p.svg.under().find(e => e.getAttribute('class') === 'cur-word'); return w.style.display === 'none' ? 'off' : [w.text, +w.getAttribute('x'), w.getAttribute('text-anchor')]; };
null
"""


@needs_node
def test_a_calm_plot_carries_its_scale_at_its_right_and_its_curve_from_the_left_edge():
    """The plots of a sheet keep 44 px at their left for the words of the scale. In the calm form a row is its name
    and its value above a curve as wide as the row: the scale stands at the right of the curve, in larger figures,
    and the curve begins at the left edge. A state that held is a foot of 4 px. A plot of the sheet is as it was."""
    got = sheet(
        [
            PLOT + CALM,
            "quietPlot.paint({ ...stretch(1000, 1900), range: [40, 90], spans: [[1200, 1400]] }); [scale(quietPlot), begins(quietPlot), foot(quietPlot)]",
            "plot.paint({ ...stretch(1000, 1900), range: [40, 90], spans: [[1200, 1400]] }); [scale(plot), begins(plot), foot(plot)]",
        ]
    )
    words, line, feet = got[1]
    assert [w[0] for w in words] == ["40", "90"] and all(w[1] == 1064 - 50 + 8 and w[2] == "start" for w in words), (
        words
    )
    assert line.startswith("M2.0 ") and feet == [["68", "4"]], (line, feet)
    words, line, feet = got[2]
    assert (
        all(w[1] == 44 - 7 and w[2] == "end" for w in words) and line.startswith("M44.0") and feet == [["43", "3"]]
    ), got[2]


@needs_node
def test_the_word_beside_the_cursor_of_a_plot_goes_where_the_cursor_goes():
    """A calm form has no line of words that says where the cursor stands. The plot under the pointer says it itself:
    a word beside its cursor, on the other side of it near the right edge, gone with the cursor, and back at its
    place when the plot is drawn again."""
    got = sheet(
        [
            PLOT + CALM,
            "quietPlot.paint(stretch(1000, 1900)); quietPlot.cursor(1400); quietPlot.say('9 Nov, 21:40'); beside(quietPlot)",
            "quietPlot.cursor(1900); beside(quietPlot)",
            "quietPlot.paint(stretch(1400, 1900)); quietPlot.cursor(1400); beside(quietPlot)",
            "quietPlot.cursor(null); beside(quietPlot)",
            "quietPlot.cursor(1400); quietPlot.say(''); beside(quietPlot)",
        ]
    )
    assert got[1] == ["9 Nov, 21:40", 451.8 + 7, "start"], got[1]  # beside the cursor, which snapped to a column
    assert got[2] == ["9 Nov, 21:40", 1014 - 7, "end"], got[2]  # at the right edge it stands before the cursor
    assert got[3][1:] == [2 + 7, "start"] and got[4] == "off", got[3:5]
    assert got[5][0] == "", got[5]


@needs_node
def test_the_word_beside_the_cursor_never_runs_past_the_end_of_its_curve():
    """The word beside a cursor changed to the other side within 96 px of the end of the curve, whatever its width. A
    moment with its seconds is wider than that: just before the change it ran over the end of the curve and touched
    the figures of the scale. The plot measures the word, and a word that is said after the cursor was set finds
    its side again."""
    word = "11 Nov, 01:05:36"  # sixteen letters, 112 px wide where a letter measures 7 px
    got = sheet(
        [
            PLOT + CALM + "server.measureWords(7); null",
            f"quietPlot.paint(stretch(1000, 1900)); quietPlot.say('{word}'); quietPlot.cursor(1800); beside(quietPlot)",
            "quietPlot.cursor(1700); beside(quietPlot)",
            f"quietPlot.say(''); quietPlot.cursor(1800); quietPlot.say('{word}'); beside(quietPlot)",
        ]
    )
    assert got[1] == [word, 901.6 - 7, "end"], got[1]  # 901.6 + 7 + 112 lies past the end of the curve at 1014
    assert got[2] == [word, 789.1 + 7, "start"], got[2]  # a column further left it ends on the curve
    assert got[3] == [word, 901.6 - 7, "end"], got[3]  # said after the cursor was set: the same side


@needs_node
def test_the_word_beside_the_cursor_of_a_narrow_plot_begins_where_its_curve_begins():
    """A word that would run past the end of its curve stands before the cursor. On a plot narrower than twice the
    word and its scale it found no room there either and began left of its plot: on the padding of its card, and on
    a narrower page on the scale of the plot beside it or cut off at the edge of the sheet. Two plots side by side
    are that narrow on a page under 1,030 px (222 px on a page of 900, measured). Before the cursor the word begins
    no earlier than its curve: there it stands over the cursor, whole and on its own plot."""
    word = "11 Nov, 01:05:36"  # sixteen letters, 112 px wide where a letter measures 7 px
    got = sheet(
        [
            PLOT + CALM + "server.measureWords(7);"
            " globalThis.slim = makePlot(Object.assign(document.createElement('div'), { rect: { width: 240 } }), { word: 'a reading', calm: true });"
            " null",
            f"slim.paint(stretch(1000, 1900)); slim.say('{word}'); slim.cursor(1400); beside(slim)",
            "slim.cursor(1100); beside(slim)",
            "slim.cursor(1900); beside(slim)",
        ]
    )
    assert got[1] == [word, 2 + 112, "end"], got[1]  # 85.6 - 7 - 112 lies before the curve, which begins at 2
    assert got[2] == [word, 22.9 + 7, "start"], got[2]  # near the left edge it ends on the curve, as before
    assert got[3] == [word, 190 - 7, "end"], got[3]  # at the right edge it stands before the cursor, as before


@needs_node
def test_the_time_axis_of_calm_plots_keeps_a_word_at_its_end_inside():
    """Under calm plots the axis begins at the left edge: its first word, the one that names the day, would run out
    of it by half its width. It is moved in beside its mark, and so is a word at the right end."""
    got = sheet(
        [
            AXIS + "globalThis.inner = document.createElement('div'); globalThis.quiet = makeAxis(inner);"
            " globalThis.calmWords = () => inner.under().filter(e => e.tagName === 'TEXT').map(e => [e.text, +e.getAttribute('x')]); null",
            "server.measureWords(7); quiet(1794268800, 1794270600, []); const w = calmWords(); server.measureWords(null); w",
        ]
    )
    first, last = got[1][0], got[1][-1]
    assert first[1] == len(first[0]) * 3.5, first  # its mark stands at the left edge (2 px): the word begins at 0
    assert last[1] + len(last[0]) * 3.5 <= 1064, last


@needs_node
def test_a_calm_scale_says_all_its_marks_only_where_they_stand_far_enough_apart():
    """A tall plot says every mark of its scale. In the calm form its words are larger: on a curve 60 px tall five
    marks stand 12 px apart, and their words ran into one another. A calm scale says all its marks where they
    stand at least 15 px apart, and its two ends where they do not; the hairline of every mark stays."""
    said = "(p => p.svg.under().filter(e => e.tagName === 'TEXT' && e.parentNode.getAttribute('class') === 'grid').map(e => e.text))"
    lines = (
        "(p => p.svg.under().filter(e => e.tagName === 'LINE' && e.parentNode.getAttribute('class') === 'grid').length)"
    )
    got = sheet(
        [
            PLOT
            + "globalThis.low = makePlot(document.createElement('div'), { word: 'low', calm: true, tall: true, height: 60 });"
            " globalThis.high = makePlot(document.createElement('div'), { word: 'high', calm: true, tall: true });"
            " globalThis.far = { ...stretch(1000, 1900), mean: [...Array(10).keys()].map(k => 400 * k) }; null",
            f"low.paint(far); high.paint(far); [{said}(low), {lines}(low), {said}(high), {lines}(high)]",
        ]
    )
    assert got[1][0] == ["0", "4,000"] and got[1][1] == 5, got[1]  # 12 px apart: the two ends, and every hairline
    assert got[1][2] == ["0", "1,000", "2,000", "3,000", "4,000"] and got[1][3] == 5, got[1]  # 15 px apart: all
