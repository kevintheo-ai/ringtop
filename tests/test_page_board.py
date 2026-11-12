"""The board every view with curves stands on, driven without a browser: one stretch, one cursor and two marks for
all its plots, wherever on the page they stand."""

from tests.fixtures import needs_node
from tests.test_page_sheet import answer, sheet

# A board of its own beside the sheet: two elements with one plot each, drawn from one trace of the second Spark.
# `seen` counts what the board asks of its view.
BOARD = """
globalThis.hostA = document.createElement('div'); globalThis.hostB = document.createElement('div');
globalThis.seen = { drawn: 0, read: 0, failed: null };
globalThis.key = S.nodes[1].name + '.gpu_c';
globalThis.board = makeBoard([hostA, hostB], { open: () => true, keys: () => [key], room: () => 300,
  drawn: () => { seen.drawn++; for (const p of [plotA, plotB]) p.paint(board.view({ mean: board.got.series[key] || [] })); },
  read: () => { seen.read++; }, failed: problem => { seen.failed = String(problem); } }, 1800);
globalThis.plotA = board.add(makePlot(hostA, { word: 'a' })); globalThis.plotB = board.add(makePlot(hostB, { word: 'b' }));
globalThis.line = (plot, cls) => plot.svg.under().filter(e => e.getAttribute('class') === cls).map(e => [e.style.display === 'none' ? 'off' : 'on', e.getAttribute('x1')]);
board.load(); null
"""


@needs_node
def test_one_board_reads_one_moment_on_the_plots_of_several_elements():
    """A panel and the tiles under the ring, a sheet and the panel of one of its parts: plots that stand in different
    elements of the page and still show one stretch of time. A pointer on any of them moves the cursor of all, a
    click marks all, and each element is listened on."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            BOARD,
            "[seen.drawn, board.got.t.length, board.span, board.end]",
            "hostB.fire('pointermove', { target: plotB.svg, clientX: 500, button: 0, buttons: 0 });"
            " [board.hover != null, line(plotA, 'cur'), line(plotB, 'cur')]",
            "hostA.fire('pointerdown', { target: plotA.svg, clientX: 900, button: 0, buttons: 1 });"
            " hostA.fire('pointerup', { target: plotA.svg, clientX: 900, button: 0, buttons: 0 });"
            " [board.marks.length, line(plotA, 'mark')[0], line(plotB, 'mark')[0]]",
            "hostB.fire('pointerleave', {}); [board.hover, line(plotA, 'cur')[0][0], seen.failed]",
        ]
    )
    assert got[2] == [1, 40, 1800, None], got[2]  # one stretch loaded, drawn once, half an hour that ends now
    moved, cursor_a, cursor_b = got[3]
    assert moved and cursor_a == cursor_b and cursor_a[0][0] == "on", got[3]  # one moment on both plots
    assert got[4][0] == 1 and got[4][1] == got[4][2] and got[4][1][0] == "on", got[4]  # one mark, on both
    assert got[5] == [None, "off", None], got[5]  # the pointer left: no cursor on either, and nothing failed


# A view in the calm form on a board of its own: two elements with one calm row each, and the calm bar. `told` is
# what the view adds about its own recording; `one` finds an element of the first one by its class, `word` reads
# the word beside the cursor of a row.
QUIET = """
globalThis.host = document.createElement('div'); globalThis.hostB = document.createElement('div');
globalThis.key = S.nodes[1].name + '.gpu_c'; globalThis.told = { late: '' }; globalThis.newest = null;
globalThis.board = makeBoard([host, hostB], { open: () => true, keys: () => [key], room: () => 300, callout: true,
  drawn: () => { const got = board.got; for (const r of [row, rowB]) { r.trace = { t: got.t, mean: got.series[key], low: got.low[key], peak: got.peak[key], n: got.n[key] }; r.plot.paint(board.view({ mean: r.trace.mean })); } },
  read: () => { for (const r of [row, rowB]) rowFigures(board, r, newest); if (globalThis.bar) bar.paint(); }, failed: problem => bar.say(String(problem)) }, 1800);
globalThis.row = makeRow(board, host, 'GPU temperature', '°C', { digits: 1, calm: true });
globalThis.rowB = makeRow(board, hostB, 'GPU temperature', '°C', { digits: 1, calm: true });
globalThis.texts = cls => host.under().filter(e => e.classList.contains(cls)).map(e => e.under().map(x => x.text).join(''));
globalThis.one = cls => host.under().find(e => e.classList.contains(cls));
globalThis.word = r => r.plot.svg.under().find(e => e.getAttribute('class') === 'cur-word').text;
globalThis.over = (r, x) => host.fire('pointermove', { target: r.plot.svg, clientX: x, button: 0, buttons: 0 });
null
"""


@needs_node
def test_a_calm_row_says_its_unit_and_what_its_value_is_only_where_that_is_no_reading_of_now():
    """Every row of the sheet says beside its value what the value is: "°C, now", "°C, at cursor". In the calm form
    the unit stands alone: at the cursor the plot says the moment itself, and now is what a reader expects. Only a
    value that is neither says so: the last point of the stretch, with its time. In a hole of the curve the cursor
    reads a dash."""
    got = sheet(
        [
            answer({"gpu_c": "k === 20 ? null : 60 + k"}),
            QUIET + "board.load(); null",
            "texts('ch-val')[0]",
            "newest = 71.5; board.setMarks([]); texts('ch-val')[0]",
            "over(row, 1050); texts('ch-val')[0]",
            "over(row, 1064 * 20.5 / 40); texts('ch-val')[0]",
        ]
    )
    assert got[2].startswith("99.0°C, last point, "), got[2]  # no reading of now: the last point, and when
    assert got[3] == "71.5°C" and got[4] == "99.0°C", got[3:5]  # now, and at the cursor: the unit alone
    assert got[5] == "–°C", got[5]  # the cursor in a hole of the curve: a dash, never the value beside it


@needs_node
def test_the_plot_under_the_pointer_says_the_moment_of_the_cursor_and_no_other_plot_does():
    """One cursor reads every plot of a board. Which moment it reads stood in the bar; the calm bar has no such
    line. The plot the pointer is on says it beside its cursor, the others show the cursor without a word, and the
    word goes when the pointer leaves."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            QUIET + "board.load(); null",
            "over(row, 500); [word(row), word(rowB), board.hover != null]",
            "over(rowB, 700); [word(row), word(rowB)]",
            "host.fire('pointerleave', {}); [word(row), word(rowB)]",
        ]
    )
    assert got[2][0].startswith("15 Jan, ") and got[2][1] == "" and got[2][2] is True, got[2]
    assert got[3][0] == "" and got[3][1].startswith("15 Jan, "), got[3]
    assert got[4] == ["", ""], got[4]


# The calm bar on that view: two stretches to pick from, and what the view adds about its own recording.
BAR = (
    QUIET
    + """
globalThis.bar = makeQuietBar(board, host, host, [['30 min', 1800], ['2 h', 7200]], () => told.late, { figures: 'what the figures are' });
globalThis.btn = word => host.under().find(e => e.matches('button') && e.text === word);
globalThis.strip = () => { const s = one('q-strip'); return s.hidden ? 'hidden' : [s.under().find(e => e.tagName === 'P').text, ...s.under().filter(e => e.matches('button') && !e.hidden).map(e => e.text)]; };
board.load(); null
"""
)


@needs_node
def test_the_figures_of_every_curve_wait_behind_a_button_and_come_with_two_marks():
    """Mean, lowest, highest and count stood under every curve of a sheet, all the time. In the calm form they wait:
    the button "Figures" brings them for the whole stretch and takes them away again, and two marks bring them by
    themselves, for the marked stretch; then the button has nothing to switch."""
    state = (
        "[host.classList.contains('figures'), btn('Figures').getAttribute('aria-pressed'), !!btn('Figures').disabled]"
    )
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            BAR,
            f"[btn('Figures').title, ...{state}]",
            f"btn('Figures').fire('click', {{}}); {state}",
            f"btn('Figures').fire('click', {{}}); {state}",
            f"board.setMarks([board.got.t[10], board.got.t[20]]); [...{state}, texts('ch-stat')[0]]",
            f"board.setMarks([]); {state}",
        ]
    )
    assert got[2] == ["what the figures are", False, "false", False], got[2]
    assert got[3] == [True, "true", False] and got[4] == [False, "false", False], got[3:5]
    assert got[5] == [True, "true", True, "mean75.0min70.0max80.0readings11"], got[5]  # of the marked stretch
    assert got[6] == [False, "false", False], got[6]


@needs_node
def test_the_strip_under_a_calm_bar_comes_only_while_there_is_something_to_say():
    """The bar of a sheet keeps two lines of words in sight: the stretch, and what cursor and marks read. The calm
    bar is one switch for the stretch. What the marks say, a stretch that was zoomed to, and what the view adds
    about its own recording stand on a strip under it, which is there only while one of them is; it lies over what
    scrolls by, so nothing moves when it comes."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            BAR,
            "[strip(), btn('30 min').getAttribute('aria-pressed'), btn('2 h').getAttribute('aria-pressed')]",
            "board.mark(board.got.t[10]); strip()",
            "board.mark(board.got.t[25]); strip()",
            "btn('Clear').fire('click', {}); strip()",
            "board.zoom(board.got.t[10], board.got.t[25]); null",
            "[strip(), btn('30 min').getAttribute('aria-pressed')]",
            "btn('Back to now').fire('click', {}); null",
            "strip()",
            "told.late = ' The recording begins here.'; bar.paint(); strip()",
            "told.late = ''; bar.paint(); strip()",
            "bar.say('The history did not answer.'); strip()",
            "btn('2 h').fire('click', {}); null",
            "[board.span, btn('2 h').getAttribute('aria-pressed'), strip()]",
        ]
    )
    assert got[2] == ["hidden", "true", "false"], got[2]
    assert got[3][0].startswith("Mark at 15 Jan, ") and got[3][1:] == ["Clear"], got[3]
    assert got[4][0].endswith(", 30 s") and " to " in got[4][0] and got[4][1:] == ["Zoom", "Clear"], got[4]
    assert got[5] == "hidden", got[5]
    zoomed, pressed = got[7]
    assert " to " in zoomed[0] and "now" not in zoomed[0] and zoomed[1:] == ["Back to now"] and pressed == "false", got[
        7
    ]
    assert got[9] == "hidden", got[9]
    assert got[10] == ["The recording begins here."] and got[11] == "hidden", got[10:12]
    assert got[12] == ["The history did not answer."], got[12]
    assert got[14] == [7200, "true", "hidden"], got[14]  # a new stretch came: what was said is gone


# The calm bar with what it explains: a paragraph that says where the stretch begins, and one without a text.
INFO = (
    QUIET
    + """
globalThis.bar = makeQuietBar(board, host, host, [['30 min', 1800], ['2 h', 7200]], () => '', { figures: 'f', info: 'what the button shows', about: 'About these curves',
  texts: () => [['The stretch', 'from ' + board.got.from], ['Nothing to say', '']] });
globalThis.btn = word => host.under().find(e => e.matches('button') && e.text === word);
globalThis.box = () => one('q-pop'); globalThis.info = () => one('q-info');
globalThis.inBox = () => box().children.map(e => e.tagName + ':' + e.text);
board.load(); null
"""
)


@needs_node
def test_what_a_calm_bar_explains_waits_in_a_box_that_its_button_escape_and_a_press_elsewhere_close():
    """What one point of a curve stands for, how a rule is drawn, how to set a mark: on a sheet these sentences
    stand between the curves all the time. The calm bar keeps them in a box behind a small button. The box is
    filled when it opens, with what holds then, and a paragraph without a text is left out. It closes by its
    button, by a press anywhere else on the page, and by Escape, which then closes the box and nothing else: the
    view stays open, and the next Escape leaves it."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            INFO,
            "[box().hidden, info().getAttribute('aria-expanded'), info().title, info().getAttribute('aria-label')]",
            "info().fire('click', {}); [box().hidden, info().getAttribute('aria-expanded'), inBox()]",
            "pageHears('pointerdown', { target: box().children[1] }); pageHears('pointerdown', { target: info() }); box().hidden",
            "pageHears('pointerdown', { target: host }); [box().hidden, info().getAttribute('aria-expanded')]",
            "btn('2 h').fire('click', {}); null",
            "info().fire('click', {}); inBox()",
            "info().fire('click', {}); box().hidden",
            "setView('why'); info().fire('click', {}); pageHears('keydown', { key: 'Escape' }); [box().hidden, V]",
            "pageHears('keydown', { key: 'Escape' }); V",
        ]
    )
    assert got[2] == [True, "false", "what the button shows", "About these curves"], got[2]
    shut, wide, said = got[3]
    assert shut is False and wide == "true" and said[0] == "H4:The stretch" and len(said) == 2, got[3]
    assert got[4] is False and got[5] == [True, "false"], got[4:6]  # a press on the box or its button leaves it
    assert got[7][1].startswith("P:from ") and got[7][1] != said[1], (got[7], said)  # filled anew, for the new stretch
    assert got[8] is True, got[8]  # its button closes it too
    assert got[9] == [True, "why"] and got[10] == "ring", got[9:]  # Escape: first the box alone, then the view


@needs_node
def test_a_box_that_opens_shuts_the_one_that_stood_open():
    """One box at a time on the whole page: Escape and a press elsewhere know one box to shut. The button of a
    second calm bar opened its box and left the first one open and forgotten: neither Escape nor a press beside it
    closed that one any more. No view puts two calm bars on the page today (the sheet of a Spark and the cooling
    view take turns); a box that opens shuts the other one first all the same."""
    two = (
        "globalThis.bar2 = makeQuietBar(board, host, host, [['30 min', 1800]], () => '',"
        " { figures: 'f', info: 'i', about: 'a', texts: () => [['Another', 'box']] });"
        " globalThis.boxes = () => host.under().filter(e => e.classList.contains('q-pop')).map(e => e.hidden);"
        " globalThis.infos = () => host.under().filter(e => e.classList.contains('q-info')); null"
    )
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            INFO,
            two,
            "infos()[0].fire('click', {}); boxes()",
            "infos()[1].fire('click', {}); boxes()",
            "pageHears('keydown', { key: 'Escape' }); [boxes(), !!shutBox]",
        ]
    )
    assert got[3] == [False, True], got[3]
    assert got[4] == [True, False], got[4]  # was [False, False]: both stood open
    assert got[5] == [[True, True], False], got[5]  # and Escape shuts the one that is open: none is left behind


@needs_node
def test_a_failure_of_the_history_stands_in_front_on_the_strip_for_as_long_as_it_holds():
    """The strip under a calm bar says one thing at a time. A failure of the history was said on it at once, over
    the words of the marks, and the next time the strip was written (the pointer moved) the marks stood in front
    again: the failure flashed up and was gone behind them until they were cleared, although the view still did
    not keep up. One state, two faces. The failure stands in front for as long as it holds, whoever writes the
    strip; the marks stay on the curves, "Zoom" and "Clear" stay beside it, and it goes when the history answers
    again."""
    marks = "row.plot.svg.under().filter(e => e.getAttribute('class') === 'mark').map(e => e.style.display === 'none' ? 'off' : 'on')"
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            BAR,
            "board.setMarks([board.got.t[10], board.got.t[25]]); strip()",
            "server.historyAnswers({ no: 'stretch' }); board.load(); null",
            f"[strip(), {marks}]",
            f"over(row, 500); [strip(), {marks}]",
            f"btn('Clear').fire('click', {{}}); [strip(), {marks}]",
            answer({"gpu_c": "60 + k"}) + "; board.load(); null",
            "strip()",
        ]
    )
    failure = "Error: its answer is no stretch of the history"
    assert got[2][0].endswith(", 30 s") and got[2][1:] == ["Zoom", "Clear"], got[2]
    assert got[4] == [[failure, "Zoom", "Clear"], ["on", "on"]], got[4]  # said at once, the marks stay on the curve
    assert got[5] == [[failure, "Zoom", "Clear"], ["on", "on"]], got[5]  # was the words of the marks again
    assert got[6] == [[failure], ["off", "off"]], got[6]  # the marks can be cleared, the failure stays
    assert got[8] == "hidden", got[8]  # the history answers again: nothing is left to say


# A place for everything the strip is laid out with, as a browser would give it: the bar stands 100 px down what
# scrolls, is 48 px tall and sticks to its top; the strip hangs under the bar, 41 px tall; `next` is what follows the
# bar in the flow, after the room the bar keeps for the strip, if it keeps one. `covered`: the strip lies over the
# top of what follows. `lay.anchors`: a browser that anchors the scroll: when something above what is in sight grows
# while the bar sticks, it scrolls by as much itself.
LAYOUT = """
globalThis.lay = { anchors: false };
globalThis.next = make('div', '', host);
{ const room = () => one('q-room'), at = (top, height) => ({ top, bottom: top + height, height, left: 0, right: 300, width: 300 });
  let tall = 0;
  if (room()) Object.defineProperty(room().style, 'height', { get: () => tall + 'px', set: v => { const to = parseFloat(v) || 0; if (lay.anchors && host.scrollTop > 100) host.scrollTop += to - tall; tall = to; } });
  Object.defineProperty(host, 'placed', { get: () => at(0, 400) });
  Object.defineProperty(one('q-bar'), 'placed', { get: () => at(Math.max(100 - host.scrollTop, 0), 48) });
  Object.defineProperty(one('q-strip'), 'placed', { get: () => at(one('q-bar').placed.bottom, 41) });
  if (room()) Object.defineProperty(room(), 'placed', { get: () => at(148 - host.scrollTop, tall) });
  Object.defineProperty(next, 'placed', { get: () => at(148 + tall - host.scrollTop, 20) });
  globalThis.kept = () => tall; }
globalThis.covered = () => !one('q-strip').hidden && one('q-strip').getBoundingClientRect().bottom > next.getBoundingClientRect().top;
globalThis.where = () => next.getBoundingClientRect().top;
null
"""


@needs_node
def test_the_strip_under_a_calm_bar_has_room_of_its_own_and_moves_nothing_a_reader_looks_at():
    """The strip under a calm bar lay over whatever stood right under the bar: with the page at its top that is a
    heading (in the wide cooling view the two figures of its head), and nothing could bring it out from under the
    strip for as long as the strip stood. The bar keeps room for the strip now, as tall as the strip and only
    while it stands. With the page at its top, what follows moves down when the strip comes and up again when it
    goes. Further down, where the bar sticks to the top, nothing a reader looks at moves: the page is scrolled by
    as much as the room took or gave back, and by nothing where the browser did that itself. A failure that is
    said on the strip gets the same room."""
    got = sheet(
        [
            answer({"gpu_c": "60 + k"}),
            BAR,
            LAYOUT,
            "board.mark(board.got.t[10]); [strip() !== 'hidden', covered(), kept(), host.scrollTop, where()]",
            "btn('Clear').fire('click', {}); [strip(), covered(), kept(), host.scrollTop, where()]",
            "host.scrollTop = 300; globalThis.was = where(); board.mark(board.got.t[10]); [kept(), host.scrollTop, where() === was]",
            "btn('Clear').fire('click', {}); [kept(), host.scrollTop, where() === was]",
            "lay.anchors = true; board.mark(board.got.t[10]); [kept(), host.scrollTop, where() === was]",
            "btn('Clear').fire('click', {}); lay.anchors = false; host.scrollTop = 0; bar.say('The history did not answer.'); [kept(), covered()]",
        ]
    )
    assert got[3] == [True, False, 41, 0, 189], got[3]  # was covered: the strip over what follows the bar
    assert got[4] == ["hidden", False, 0, 0, 148], got[4]  # the strip went: its room too
    assert got[5] == [41, 341, True], got[5]  # the bar sticks: scrolled by the room, nothing in sight moved
    assert got[6] == [0, 300, True], got[6]
    assert got[7] == [41, 341, True], got[7]  # the browser scrolled by itself: not once more
    assert got[8] == [41, False], got[8]
