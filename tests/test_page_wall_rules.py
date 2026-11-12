"""The rules of the calm page for a wall and a phone: how its tiles stand, when it is live, what a tile shows."""

from tests.fixtures import needs_node, page_rules


@needs_node
def test_the_tiles_of_one_to_sixteen_sparks_stand_in_columns_that_suit_both_forms_of_the_page():
    """Wide, the tiles fill the half beside the speed without scrolling: as near to a square of tiles as their
    number allows, never more rows than columns, and no column more than needed. Upright they stand under each
    other, however many they are. A cluster of no Spark still has one column."""
    wide, upright = page_rules(
        "const n = Array.from({ length: 17 }, (_, k) => k); return [n.map(k => wallCols(k, true)), n.map(k => wallCols(k, false))];"
    )
    assert wide[1:] == [1, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4], wide
    assert upright[1:] == [1] * 16, upright
    assert wide[0] == upright[0] == 1
    for n in range(1, 17):
        cols = wide[n]
        rows = -(-n // cols)
        assert cols * rows >= n and rows <= cols, (n, cols, rows)
        assert cols == 1 or (cols - 1) * (cols - 1) < n, (n, cols)  # one column fewer would need more rows than columns


@needs_node
def test_a_moment_that_came_again_is_no_news_for_the_calm_page():
    """When its stream is opened again the server sends the newest moment once more, at once. Counted as news, a
    ring whose moments have stopped would be called live with every new try. A moment is news only when its time
    lies after the one on the page; the first one always is, and one without a time never."""
    got = page_rules(
        "return [wallNews(100, null), wallNews(100, 100), wallNews(99.5, 100), wallNews(100.01, 100),"
        " wallNews(null, 100), wallNews(undefined, null)];"
    )
    assert got == [True, False, False, True, False, False], got


@needs_node
def test_the_calm_page_says_live_only_while_new_moments_come():
    """Asked every second: the stream stands or not, how long ago the last new moment came, and the interval it
    named. Fresh, the page is live or reconnecting in the words of the main page. Without a new moment for longer
    than the silence that takes a Spark off the main page (15 s, or four intervals where that is more) it is stale,
    whatever the stream says of itself: not live, and no word of the main page stands for it."""
    got = page_rules(
        "const s = (...a) => { const r = wallStatus(...a); return [r.on, r.word, r.stale, r.again]; };"
        " return { first: [s(true, null, null, 1), s(false, null, null, 1), s(true, null, null, 60)],"
        " fresh: [s(true, 0, 2, 0), s(true, 15, 2, 15), s(false, 3, 2, 3)],"
        " stale: [s(true, 15.1, 2, 15.1), s(false, 600, 2, 1)],"
        " slow: [s(true, 39, 10, 0), s(true, 40.5, 10, 0)], unknown: [s(true, 15, null, 0), s(true, 16, null, 0)] };"
    )
    # before the first moment nothing can be stale; a stream that brings none is opened anew all the same (below)
    assert got["first"] == [
        [False, "Connecting", False, False],
        [False, "Reconnecting", False, False],
        [False, "Connecting", False, True],
    ], got["first"]
    assert got["fresh"] == [
        [True, "Live", False, False],
        [True, "Live", False, False],  # the line itself is not over it
        [False, "Reconnecting", False, False],  # a short cut: the figures on the page still hold
    ], got["fresh"]
    assert got["stale"] == [[False, None, True, True], [False, None, True, False]], got["stale"]
    assert got["slow"] == [[True, "Live", False, False], [False, None, True, False]], got["slow"]  # four intervals
    assert got["unknown"] == [[True, "Live", False, False], [False, None, True, False]], got["unknown"]


@needs_node
def test_a_stale_stream_is_opened_again_at_most_every_five_seconds():
    """A connection can be dead without an error: a phone that slept, a network that changed. So a page that is
    stale opens its stream anew, and not more often than every 5 s; one that is not stale never does."""
    got = page_rules(
        "return [0, 4.9, 5, 60].map(opened => [wallStatus(true, 30, 2, opened).again, wallStatus(true, 3, 2, opened).again]);"
    )
    assert got == [[False, False], [False, False], [True, False], [True, False]], got


@needs_node
def test_a_stream_that_brings_no_first_moment_is_opened_again_once_the_silence_is_over():
    """Before its first moment the page is not stale, and so it never opened its stream anew: a connection that
    died without an error before it brought a moment left the corner on "Connecting" for as long as the page was
    open. A stream that brought no moment for longer than the silence since it was opened (15 s: no moment has
    named an interval yet) is opened anew, whether it stands or not. The page says what it said: connecting or
    reconnecting, never live and never stale."""
    got = page_rules(
        "const s = (...a) => { const r = wallStatus(...a); return [r.on, r.word, r.stale, r.again]; };"
        " return { stands: [0, 14.9, 15, 15.1, 600].map(opened => s(true, null, null, opened)),"
        " cut: [0, 15, 15.1].map(opened => s(false, null, null, opened)),"
        " slow: [s(true, null, 10, 40), s(true, null, 10, 40.5)] };"
    )
    stands = [[False, "Connecting", False, again] for again in (False, False, False, True, True)]
    assert got["stands"] == stands, got["stands"]  # the line itself is not over it
    assert got["cut"] == [[False, "Reconnecting", False, again] for again in (False, False, True)], got["cut"]
    assert [row[3] for row in got["slow"]] == [False, True], got["slow"]  # four intervals, where one is known


@needs_node
def test_a_figure_nobody_read_is_a_dash_on_a_tile_and_never_a_zero():
    """The three figures of a Spark on the calm page: GPU temperature, fan speed, free memory, as whole numbers. One
    that was not read is a dash; a Spark that is not live shows three dashes, whatever it still carries; and a
    reading of 0 is a reading."""
    got = page_rules(
        "const f = n => { const r = wallFigures(n); return [r.temp, r.fan, r.mem, r.stopped]; };"
        " return [f({ live: true, gpu_c: 61.6, fan: 2399.6, fans: [2400, 2399], mem_free_gb: 24.4 }),"
        " f({ live: true, gpu_c: null, fan: null, mem_free_gb: null }), f({ live: true }),"
        " f({ live: false, gpu_c: 61.6, fan: 2400, fans: [0, 2400], mem_free_gb: 24.4 }),"
        " f({ live: true, gpu_c: 0, fan: 0, fans: [0, 0], mem_free_gb: 0 }),"
        " f({ live: true, gpu_c: 70, fan: 12345.4, mem_free_gb: 0.4 })];"
    )
    assert got[0] == ["62", "2,400", "24", False], got[0]
    assert got[1] == ["–", "–", "–", False] and got[2] == ["–", "–", "–", False], got[1:3]
    assert got[3] == ["–", "–", "–", False], got[3]  # not live: its last readings are not of now
    assert got[4] == ["0", "0", "0", False], got[4]  # read as zero: both fans stand still, and that is said
    assert got[5] == ["70", "12,345", "0", False], got[5]


@needs_node
def test_a_fan_that_stands_still_beside_one_that_turns_marks_the_fan_figure():
    """The fan figure is the mean of the two fans, which hides one that stands still: 1,200 RPM reads like a quiet
    Spark. The tile marks the figure then, by the rule of the cooling view; two fans that both stand are no mark."""
    got = page_rules(
        "return [[0, 2400], [2400, 0], [2400, 2380], [0, 0], [], null].map(fans => wallFigures({ live: true, fan: 1200, fans }).stopped);"
    )
    assert got == [True, True, False, False, False, False], got
