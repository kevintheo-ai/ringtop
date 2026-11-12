"""The cooling view in its calm form, driven without a browser: its head, the sign for slower fans, what its box
explains, its picture, and what it says looking back."""

from tests.fixtures import needs_node
from tests.test_page_sheet import sheet
from tests.test_page_views import COOLING, cooling

OPEN = "setView('cooling'); null"
# What the head says, and what the rules of the page make of the moment it was written from.
HEAD = (
    "{ const nodes = S.nodes.filter(n => n.live && n.fan != null && warmest(n)), [headline, note] = coolingWord(nodes);"
    " [panel.under().find(e => e.tagName === 'H2').text, said('cool-key'), said('cool-alarm')[0], headline, note,"
    " spreadWord(nodes.map(n => n.fan)), spreadWord(nodes.map(n => Math.round(warmest(n)[1]))), stoppedFans(nodes).length] }"
)
CHIPS = "panel.under().filter(e => e.classList.contains('ch-chip')).map(e => !e.hidden)"
OVER = "panel.fire('pointermove', {{ target: plots()[1], clientX: {x}, button: 0, buttons: 0 }})"
# A moment later on the page, in which one fan of the second Spark stands still while its twin turns.
STOPPED = "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, j) => j === 1 ? { ...n, fans: [0, 2600], fan: 1300 } : n) }); null"


@needs_node
def test_the_head_of_cooling_says_all_sparks_in_two_figures_and_keeps_its_sentence_for_the_box():
    """Under the headline stood a sentence: "Right now: 2,579 to 3,226 RPM at 76 to 83 °C on the warmest sensor."
    The calm form says the same in two figures with their units, and keeps the sentence in the box of the bar. What
    cannot wait stays in sight: a fan that stands still is said under the headline, not behind a button."""
    got = sheet([COOLING, OPEN, HEAD, "explained('Now')", STOPPED, HEAD, "explained('Now')"])
    head, keys, alarm, headline, note, fans, heat, stopped = got[2]
    assert stopped == 0 and head == headline and alarm == "", got[2]
    assert keys == [f"Fans{fans}RPM", f"Warmest sensor{heat}°C"], keys
    assert got[3] == note and " RPM at " in note, (got[3], note)  # the sentence waits in the box
    head, keys, alarm, headline, note, _, _, stopped = got[5]
    assert stopped == 1 and head == headline and "stands still" in head, got[5]
    assert alarm == note and "0 / 2,600 RPM" in alarm, alarm  # what cannot wait is in sight
    assert got[6] is None, got[6]  # and is not said a second time in the box


@needs_node
def test_a_spark_whose_fans_were_not_read_still_counts_in_the_figure_of_the_warmest_sensor():
    """The two figures of the head were taken from the Sparks that have both a fan reading and a warmest sensor. A
    Spark whose fans could not be read fell out of the figure of the warmest sensor too: the hottest Spark of the
    ring, at 88 °C, was gone from "Warmest sensor" because another reading of it was missing. Each figure spans
    every Spark that has that reading."""
    hot = (
        "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, j) => j === 1"
        " ? { ...n, fans: [], fan: null, zones: {}, cpu_c: 70, gpu_c: 88 }"
        " : { ...n, fans: [3000, 3000 + 100 * j], fan: 3000 + 50 * j, zones: {}, cpu_c: 50, gpu_c: 60 + j }) }); null"
    )
    got = sheet([COOLING, OPEN, hot, "said('cool-key')"])
    fans, heat = got[3]
    assert heat == "Warmest sensor60–88°C", heat  # was 60 to 63: without the Spark whose fans nobody read
    assert fans == "Fans3,000–3,150RPM", fans  # the fans of the three that were read


@needs_node
def test_a_spark_whose_fans_were_not_read_is_named_under_the_headline_of_cooling():
    """The headline is said of the Sparks that have a fan reading and a warmest sensor, the two figures of the head
    count every Spark that has the reading. A Spark that answers and whose fans were not read stood under neither:
    "All 3 Sparks cool alike" over a ring of four, and no word of the fourth. It is named in the line under the
    headline, in sight like a fan that stands still: the headline says less than the ring holds. The sentence of
    the moment still waits in the box; what cannot wait stands before it on that line; and where no Spark has a
    fan reading, the line that says so of all of them is not said a second time by name."""
    unread = "server.say({{ ...LIVE, t: LIVE.t + {at}, nodes: LIVE.nodes.map((n, j) => {who} ? {{ ...n, fans: [], fan: null }} : {rest}) }}); null"
    head = (
        "{ const nodes = S.nodes.filter(n => n.live && n.fan != null && warmest(n));"
        " [panel.under().find(e => e.tagName === 'H2').text, said('cool-alarm')[0], nodes.length ? coolingWord(nodes) : null,"
        " fansUnread(S.nodes), fansUnreadWord(fansUnread(S.nodes), false), explained('Now')] }"
    )
    got = sheet(
        [
            COOLING,
            OPEN,
            head,
            unread.format(at=2, who="j === 1", rest="n"),
            head,
            unread.format(at=4, who="j === 1 || j === 3", rest="n"),
            head,
            unread.format(at=6, who="j === 1", rest="j === 2 ? { ...n, fans: [0, 2600], fan: 1300 } : n"),
            head,
            unread.format(at=8, who="true", rest="n"),
            head,
        ]
    )
    assert got[2][1] == "" and got[2][3] == [], got[2]  # every Spark read: nothing under the headline
    headline, line, word, who, said, box = got[4]
    assert who == ["dgx1"] and "dgx1" in said and line == said, got[4]  # was "": the fourth Spark stood nowhere
    assert headline == word[0] and box == word[1], got[4]  # the headline of the three, their sentence in the box
    headline, line, word, who, said, box = got[6]
    assert who == ["dgx1", "dgx3"] and "dgx1" in said and "dgx3" in said and line == said, got[6]
    headline, line, word, who, said, box = got[8]
    assert "stands still" in headline and line == f"{word[1]} {said}" and box is None, got[8]  # both cannot wait
    headline, line, word, who, said, box = got[10]
    assert headline == "Cooling" and line == "No fan reading from any Spark." and len(who) == 4, got[10]


@needs_node
def test_the_fans_of_a_spark_carry_a_sign_while_they_count_as_slower():
    """Where the fans of a Spark ran slower stands as a foot under their curve. The row itself says it too, beside
    the name: while the slow stretch holds up to now, and at the cursor while one reads a moment inside it."""
    got = sheet(
        [
            COOLING,
            OPEN,
            "panel.under().find(e => e.matches('button') && e.text === '30 min').fire('click', {}); null",
            f"[{CHIPS}, panel.under().find(e => e.classList.contains('ch-chip')).title]",
            f"{OVER.format(x=987)}; {CHIPS}",
            f"{OVER.format(x=976)}; {CHIPS}",
            cooling(slow="k >= 30", before=2),
            "panel.fire('pointerleave', {}); panel.under().find(e => e.matches('button') && e.text === '2 h').fire('click', {}); null",
            CHIPS,
        ]
    )
    assert got[3][0] == [False, False, False, False] and got[3][1], got[3]  # one sign per row of fans; slow no more
    assert got[4] == [False, True, False, False], got[4]  # the cursor inside the slow stretch of the second Spark
    assert got[5] == [False, False, False, False], got[5]  # and before it
    assert got[8] == [False, True, False, False], got[8]  # a slow stretch that holds up to now


@needs_node
def test_the_box_of_cooling_holds_every_section_and_the_figures_of_the_stretch():
    """Every sentence that explained the view between its curves stands in the box behind the "i" of the bar, under
    a heading of its own: what holds right now, the stretch and what one point stands for, how to read the curves,
    the rule of each reading, the picture, and who sets the fans. The buttons and signs say what they are."""
    got = sheet(
        [
            COOLING,
            OPEN,
            "info().fire('click', {}); [box().children.filter(e => e.tagName === 'H4').map(e => e.text), box().children.filter(e => e.tagName === 'P').map(e => e.text)]",
            "[info().title, info().getAttribute('aria-label'), panel.under().find(e => e.classList.contains('q-fig')).title,"
            " panel.under().find(e => e.classList.contains('ch-chip')).title, panel.under().find(e => e.classList.contains('ch-open')).title]",
        ]
    )
    titles, texts = got[2]
    assert titles == [
        "Now",
        "Time range",
        "Reading the curves",
        "Fans",
        "Warmest sensor",
        "Scale",
        "Fan speed vs. warmest sensor",
        "Fan control",
    ], titles
    assert len(texts) == len(titles) and all(len(text) > 20 for text in texts), texts
    assert "24 h" in texts[1] and "2 s" in texts[1], texts[1]  # the stretch, and what one point of it stands for
    assert "12 s" in texts[2] and "2 s" in texts[2] and "2 days" in texts[2], texts[2]  # how far a drag zooms in
    assert "15 %" in texts[3] and "1.5 °C" in texts[3], texts[3]  # the figures of the fan rule
    assert all(got[3]), got[3]


@needs_node
def test_the_picture_of_cooling_takes_its_width_before_it_is_taken_away():
    """The picture of fan speed against warmth is drawn anew with every moment, as wide as its place. It was emptied
    first and measured then: for that instant the panel was shorter than what the reader had scrolled to, and the
    browser moved it up, every two seconds. The width is read while the old picture still stands."""
    got = sheet(
        [
            COOLING,
            OPEN,
            "globalThis.pic = panel.under().find(e => e.classList.contains('cool-pic')); globalThis.stood = [];"
            " Object.defineProperty(pic, 'clientWidth', { get() { stood.push(pic.children.length); return 300; } });"
            " server.say({ ...LIVE, t: LIVE.t + 2 }); [stood, pic.children.length, pic.children[0].getAttribute('width')]",
        ]
    )
    assert got[2] == [[1], 1, "300"], got[2]  # measured once, with the old picture in place; drawn at that width


@needs_node
def test_looking_back_cooling_says_nothing_of_now():
    """The fans of the second Spark run slow in the last columns of the stretch. Live, that holds "to now": its row
    carries the sign, and the picture shows the Sparks now. At a moment of the past the same columns end at that
    moment: no word of the view may say now."""
    slow = cooling(slow="k >= 30", before=2)
    words = (
        "[earlier().map(b => b.under().map(x => x.text).join(' ')), explained('Fan speed vs. warmest sensor'),"
        f" {CHIPS}, (() => {{ info().fire('click', {{}}); const t = box().children[0].text; info().fire('click', {{}}); return t; }})()]"
    )
    got = sheet(
        [
            slow,
            OPEN,
            words,
            "Time.toggle(true); Time.go(LIVE.t - 600); null",
            slow,
            "panel.under().find(e => e.matches('button') && e.text === '2 h').fire('click', {}); null",
            f"[S.past, ...{words}]",
        ]
    )
    lines, picture, chips, first = got[2]
    assert len(lines) == 1 and lines[0].endswith(" to now"), lines
    assert picture.startswith("Large dots: one per Spark, live reading") and chips[1] is True and first == "Now", got[2]
    assert picture.index("Amber:") < picture.index("Small dots:") and "0 RPM" in picture, picture
    past, lines, picture, chips, first = got[6]
    assert past is True and len(lines) == 1 and "now" not in lines[0], got[6]
    assert picture.startswith("Large dots: one per Spark, reading at this moment") and chips == [False] * 4, got[6]
    assert (
        picture.index("Amber:") < picture.index("Small dots:") and "0 RPM" not in picture and " now" not in picture
    ), picture
    assert first != "Now", first  # no reading of that moment in this check: the box begins with the time range


# What a check reads of the form of the view: the classes of the panel and of the page, its cards, plots and axes,
# and whether the two figures of the head stand under the bar. `form` is the button that changes the form.
FORM = """
globalThis.form = () => panel.under().find(e => e.classList.contains('cool-form'));
globalThis.shape = () => { const kids = panel.children.map(e => e.className), has = c => panel.under().filter(e => e.classList.contains(c)).length;
  return { panel: ['calm', 'narrow', 'wide'].filter(c => panel.classList.contains(c)), page: ['sparking', 'roomy'].filter(c => document.body.classList.contains(c)),
    cards: has('cool-card'), plots: plots().length, axes: has('ch-axis'), keysUnderBar: kids.indexOf('cool-keys') > kids.findIndex(k => k.includes('q-bar')), button: form().title }; };
null
"""
PRESSED = "panel.under().filter(e => e.matches('button') && e.getAttribute('aria-pressed') === 'true' && e.parentNode.classList.contains('q-seg')).map(e => e.text)"
BESIDE = {
    "panel": ["calm", "narrow"],
    "page": [],
    "cards": 0,
    "plots": 8,
    "axes": 2,
    "keysUnderBar": False,
    "button": "Wide view",
}
WIDE = {
    "panel": ["calm", "wide"],
    "page": ["sparking", "roomy"],
    "cards": 4,
    "plots": 8,
    "axes": 2,
    "keysUnderBar": True,
    "button": "Narrow view beside the ring",
}


@needs_node
def test_cooling_has_a_wide_form_with_a_card_for_every_spark_and_goes_back_beside_the_ring():
    """Beside the ring the view shows one Spark and a half at a time. Its button makes it wide: the panel takes the
    width like the sheet of a Spark, the ring stands small and without its tags, and every Spark is a card with its
    fans and its warmest sensor side by side on one moment. The stretch that was picked stays, marks work as before,
    and the button leads back beside the ring. The choice is not kept: leaving the view from its wide form leaves
    the page as it was, and the view opens beside the ring again."""
    got = sheet(
        [
            COOLING + FORM,
            OPEN,
            "panel.under().find(e => e.matches('button') && e.text === '2 d').fire('click', {}); null",
            f"[shape(), {PRESSED}]",
            "form().fire('click', {}); null",
            f"[shape(), {PRESSED}, said('ch-val').length]",
            "earlier()[0].fire('click', {}); [strip()[1], panel.classList.contains('figures')]",
            "form().fire('click', {}); null",
            f"[shape(), {PRESSED}, strip()]",
            "form().fire('click', {}); setView('why'); [['sparking', 'roomy'].filter(c => document.body.classList.contains(c)), ['record', 'calm', 'wide', 'narrow'].filter(c => panel.classList.contains(c))]",
            "setView('cooling'); null",
            "shape()",
        ]
    )
    assert got[3] == [BESIDE, ["2 d"]], got[3]
    assert got[5] == [WIDE, ["2 d"], 8], got[5]  # the same stretch; every card with two values
    assert got[6] == ["Zoom", True], got[6]  # a stretch of slower fans is marked on the cards as on the rows
    again, pressed, said = got[8]
    assert again == BESIDE and pressed == ["2 d"], got[8]
    assert len(said) == 1 and said[0].startswith("Recording begins 15 Jan, "), (
        said
    )  # a form built anew: its marks are gone
    assert got[9] == [[], []], got[9]  # left from its wide form: the page and the panel are as before
    assert got[11] == BESIDE, got[11]  # and it opens beside the ring again


@needs_node
def test_the_curves_of_the_wide_form_are_as_tall_as_the_panel_lets_every_spark_stand_in():
    """In its wide form the view is there to show every Spark at once. Its curves are as tall as the panel lets all
    cards stand in, never under 44 px and never over 96: on a panel of 1,100 px, under a head that ends at 625 px,
    four cards have 68 px each for their curve."""
    tall = "plots().map(p => p.getAttribute('height'))"
    got = sheet(
        [
            COOLING + FORM,
            OPEN,
            f"form().fire('click', {{}}); [...new Set({tall})]",
            "form().fire('click', {}); panel.rect = { left: 0, top: 0, width: 642, height: 1100 }; form().fire('click', {}); null",
            f"[...new Set({tall})]",
            f"form().fire('click', {{}}); [...new Set({tall})]",
        ]
    )
    assert got[2] == ["44"], got[2]  # no room: the least a curve is drawn at
    assert got[4] == ["68"], got[4]
    assert got[5] == ["72"], got[5]  # beside the ring a curve is 72 px, whatever the panel


@needs_node
def test_a_view_that_leaves_shuts_its_box_and_escape_then_leaves_the_next_view_at_once():
    """Escape closes an open box first. A box whose view has gone is no box: the cooling view shuts it when it
    leaves, so the next Escape is not spent on something nobody sees."""
    got = sheet(
        [
            COOLING,
            OPEN,
            "info().fire('click', {}); [box().hidden, !!shutBox]",
            "setView('why'); !!shutBox",
            "pageHears('keydown', { key: 'Escape' }); V",
        ]
    )
    assert got[2] == [False, True] and got[3] is False and got[4] == "ring", got[2:]


@needs_node
def test_the_box_of_cooling_calls_the_stretch_it_shows_what_it_is_while_another_is_on_its_way():
    """The reader zoomed in to a stretch of slower fans that ended a while ago and presses "Back to now". Until the
    history answers, the curves still show the old stretch: the box does not call it one that runs to now."""
    stretch = "explained('Time range')"
    got = sheet(
        [
            COOLING,
            OPEN,
            "earlier()[0].fire('click', {}); panel.under().find(e => e.matches('button') && e.text === 'Zoom').fire('click', {}); null",
            stretch,
            f"server.holdHistory(); panel.under().find(e => e.matches('button') && e.text === 'Back to now').fire('click', {{}}); {stretch}",
            "server.releaseHistory(); null",
            stretch,
        ]
    )
    assert " to now" not in got[3] and got[4] == got[3], got[3:5]
    assert " to now (" in got[6], got[6]


@needs_node
def test_the_box_of_cooling_says_how_the_scale_of_the_curves_is_made():
    """All Sparks share one scale per reading, and a band that leaves it is cut at its edge. That stood at the end of
    the two paragraphs about the curves, said twice. It is a paragraph of its own in the box, after the two about the
    curves and before the picture."""
    got = sheet(
        [
            COOLING,
            OPEN,
            "info().fire('click', {}); [box().children.filter(e => e.tagName === 'H4').map(e => e.text), para('Scale')]",
        ]
    )
    titles, scale = got[2]
    assert "Scale" in titles and scale and len(scale) > 40, got[2]
    at = titles.index("Scale")
    assert titles[at - 1] == "Warmest sensor" and titles[at + 1].startswith("Fan speed"), titles


@needs_node
def test_the_names_in_the_picture_of_cooling_stay_in_sight_and_apart():
    """Four Sparks with the same fan speed at the same warmth, the highest of the stretch: their dots lie on one
    another in the upper right corner of the picture. The names were stacked upwards only: the second was cut at
    the upper edge, the third and fourth stood outside the picture. Where no room is left above, a name goes below
    its dot."""
    same = (
        "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map(n => "
        "({ ...n, fans: [3000, 3000], fan: 3000, zones: {}, cpu_c: 80, gpu_c: 80 })) }); null"
    )
    names = "panel.under().filter(e => e.getAttribute('class') === 'name').map(e => +e.getAttribute('y'))"
    got = sheet([COOLING, OPEN, same, names])
    lines = got[3]
    assert len(lines) == 4 and len(set(lines)) == 4, lines  # every Spark has its name, each on a line of its own
    assert min(lines) >= 11 and max(lines) <= 190, lines  # and every line lies inside the picture, 200 px tall


@needs_node
def test_a_name_at_the_cool_edge_of_the_picture_keeps_clear_of_the_scale():
    """The coolest Spark lies at the left edge of the picture, right beside the figures of the scale of fan speeds.
    Its name was written around the middle of its dot and reached into those figures. A name at the left edge
    begins where the curves begin, as a name at the right edge ends at its dot."""
    cool = (
        "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, j) => "
        "({ ...n, fans: [3000, 3000], fan: 3000 - 100 * j, zones: {}, cpu_c: 40, gpu_c: 60 + 6 * j })) }); null"
    )
    names = (
        "panel.under().filter(e => e.getAttribute('class') === 'name')"
        ".map(e => [e.text, +e.getAttribute('x'), e.getAttribute('text-anchor')])"
    )
    got = sheet([COOLING, OPEN, cool, names])
    assert len(got[3]) == 4, got[3]
    begins = {word: x - len(word) * 3.5 for word, x, anchor in got[3] if anchor == "middle"}  # 3.5 px half a letter
    assert begins["dgx0"] == 50, begins  # was 36: the scale's figures end at 41, the curves begin at 48
    assert all(left >= 50 for left in begins.values()), begins


@needs_node
def test_a_view_whose_first_stretch_did_not_come_offers_nothing_to_do_with_marks():
    """The cooling view opens while the history does not answer. The strip under its bar came with the failure and
    with "Zoom", "Clear" and "Back to now" beside it, three buttons for marks and a stretch that are not there; a press
    on "Clear" threw. The strip says the failure and nothing else."""
    got = sheet(
        [
            COOLING,
            "server.historyAnswers({ error: 'the store is busy' }); null",
            OPEN,
            "strip()",
        ]
    )
    assert len(got[3]) == 1 and "its answer is no stretch of the history" in got[3][0], got[3]  # the failure, alone
