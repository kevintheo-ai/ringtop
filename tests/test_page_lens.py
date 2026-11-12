"""The rules of the page for the open Spark under the pointer: what a click does, and how its picture zooms."""

from tests.fixtures import needs_node, page_rules


@needs_node
def test_a_click_on_the_scene_picks_a_part_opens_a_spark_or_leads_back_to_the_ring():
    """What a click on the scene does, as one rule: on a part of the open Spark it picks that part, on the picked
    part it lets it go, beside the parts it lets a picked part go; else it opens the Spark under the pointer; else,
    with a Spark open, it leads back to the ring. While a Spark is still opening, its parts cannot be picked."""
    got = page_rules(
        "const on = { opened: true, view: 'node', hit: 'a' }, off = { opened: false, part: null, picked: null };"
        "return ["
        " sceneClick({ ...on, part: 'cx7', picked: null }), sceneClick({ ...on, part: 'cx7', picked: 'cx7' }),"
        " sceneClick({ ...on, part: 'fan', picked: 'cx7' }), sceneClick({ ...on, part: null, picked: 'cx7' }),"
        " sceneClick({ ...on, part: null, picked: null }), sceneClick({ ...off, hit: 'b', view: 'ring' }),"
        " sceneClick({ ...on, part: null, picked: null, hit: null }), sceneClick({ ...off, hit: null, view: 'ring' }),"
        " sceneClick({ ...off, hit: null, view: 'why' }),"
        " sceneClick({ opened: false, part: 'cx7', picked: 'fan', hit: null, view: 'node' }) ];"
    )
    assert got[:4] == [["part", "cx7"], ["part", None], ["part", "fan"], ["part", None]], got[:4]
    assert got[4:6] == [["node", "a"], ["node", "b"]], got[4:6]
    assert got[6:] == [["ring"], ["none"], ["none"], ["ring"]], got[6:]


# A hole that lies off the middle of the page, as the scene has it beside the panels; what a lens shows at a place of
# the page (the place of the picture at zoom 1 that it draws there); and a rounding that makes numbers comparable.
LENS = """
const hole = { mid: [-.3, .1], half: [.35, .7] }, home = { z: 1, q: [0, 0] };
const shows = (lens, at) => at.map((v, k) => (v - lens.q[k]) / lens.z);
const round = v => Array.isArray(v) ? v.map(round) : Math.round(v * 1e6) / 1e6;
"""


def close(a, b, by=1e-9):
    """Whether two lists of numbers agree, entry by entry."""
    return len(a) == len(b) and all(abs(x - y) <= by for x, y in zip(a, b))


@needs_node
def test_a_turn_of_the_wheel_zooms_by_a_factor_that_fits_the_wheel():
    """One event of the wheel zooms by two to the power of how far it turned: a notch of 100 pixels by 15 %, towards
    the reader out and away from them in. A wheel that counts in lines turns 25 pixels per line. A pinch on a
    trackpad arrives as a wheel with Ctrl held and small counts: it weighs ten times as much. No single event zooms
    by more than half or double, and an event that says nothing zooms by nothing."""
    got = page_rules(
        "return [{ deltaY: 100 }, { deltaY: -100 }, { deltaY: 3, deltaMode: 1 }, { deltaY: -5, ctrlKey: true },"
        " { deltaY: 10000 }, { deltaY: -10000 }, { deltaY: 0 }, {}, { deltaY: -1, deltaMode: 2 }].map(zoomStep);"
    )
    assert close(got[:4], [2**-0.2, 2**0.2, 2**-0.15, 2**0.1]), got[:4]
    assert got[4:] == [0.5, 2, 1, 1, 2], got[4:]


@needs_node
def test_zooming_keeps_what_stands_under_the_pointer_and_never_goes_past_its_bounds():
    """A step of zoom scales the picture around the place of the pointer: what stood there stands there afterwards,
    after one step and after ten. The zoom stays between 1 and its limit, and back at 1 the picture lies exactly
    where it lay. Whatever is asked, the hole never shows anything it did not show at zoom 1: zooming at its very
    corner keeps the corner, and a shift beyond is held at the edge."""
    got = page_rules(
        LENS
        + """
        const at = [-.2, .3], once = zoomAt(home, 2, at, hole);
        let ten = home; for (let i = 0; i < 10; i++) ten = zoomAt(ten, 1.2, at, hole);
        let far = home; for (let i = 0; i < 40; i++) far = zoomAt(far, 2, at, hole);
        let back = far; for (let i = 0; i < 40; i++) back = zoomAt(back, .5, at, hole);
        const corner = [hole.mid[0] + hole.half[0], hole.mid[1] - hole.half[1]], edge = zoomAt(home, 4, corner, hole);
        const pushed = zoomHeld(4, [9, -9], hole), seen = lens => [-1, 1].map(s => shows(lens, hole.mid.map((m, k) => m + s * hole.half[k])));
        return { once: [once.z, round(once.q), round(shows(once, at))], ten: [round(ten.z), round(shows(ten, at))],
          far: far.z, max: ZOOM_MAX, back: [back.z, back.q.map(Math.abs)], edge: round(shows(edge, corner)), corner: round(corner),
          pushed: round(seen({ z: 4, q: pushed })), outside: round(seen(zoomAt(home, 3, [.9, -.9], hole))),
          kept: zoomAt({ ...home, part: 'cx7' }, 2, at, hole).part };
        """
    )
    assert got["once"] == [2, [0.2, -0.3], [-0.2, 0.3]], got["once"]
    assert abs(got["ten"][0] - 1.2**10) < 1e-5 and got["ten"][1] == [-0.2, 0.3], got["ten"]
    assert got["far"] == got["max"] == 8 and got["back"] == [1, [0, 0]], (got["far"], got["max"], got["back"])
    assert got["edge"] == got["corner"], (got["edge"], got["corner"])
    low, high = [-0.65, -0.6], [0.05, 0.8]  # the two corners of the hole
    for seen in (got["pushed"], got["outside"]):  # what the hole shows from corner to corner lies inside the hole
        assert all(low[k] - 1e-6 <= seen[0][k] <= seen[1][k] <= high[k] + 1e-6 for k in (0, 1)), seen
    assert got["pushed"][0][0] == low[0] and got["pushed"][1][1] == high[1], got["pushed"]  # held at the very edge
    assert got["kept"] == "cx7", got["kept"]  # a step of zoom leaves the part in the middle alone


@needs_node
def test_a_double_click_brings_a_part_to_the_middle_as_large_as_half_the_hole():
    """Asked to show one part, the lens zooms until the part fills half the shorter side of the hole, at least
    twice and at most to its limit, and shifts until the middle of the part lies in the middle of the hole. Where
    the bounds do not let it lie there (a small zoom, a part near the edge), it lies as near as they allow."""
    got = page_rules(
        LENS
        + """
        const base = [-.25, .2], lies = lens => base.map((v, k) => lens.z * v + lens.q[k]);
        const small = zoomOnto(.05, base, hole), middle = zoomOnto(.2, base, hole), big = zoomOnto(.4, base, hole), none = zoomOnto(0, base, hole), odd = zoomOnto(NaN, base, hole);
        const off = zoomOnto(.4, [.04, .75], hole), held = zoomHeld(off.z, off.q, hole);
        return { z: [small.z, middle.z, big.z, none.z, odd.z], lies: [small, middle, big].map(l => round(lies(l))), mid: hole.mid,
          off: [round(off.q), round(held)] };
        """
    )
    assert got["z"] == [8, 2.5, 2, 8, 2], got[
        "z"
    ]  # a part of no size as far in as it goes, one nobody measured the least
    assert got["lies"] == [got["mid"]] * 3, got["lies"]
    assert got["off"][0] == got["off"][1] == [-0.05, -0.8], got["off"]  # as far towards the middle as the hole lets it


@needs_node
def test_the_lens_runs_out_softly_and_what_stands_under_the_pointer_stands_still_meanwhile():
    """The lens does not jump to where it was asked to be: every frame covers the same share of what is left of
    zoom, shift and aim, 63 % in 0.12 s. Because all three move by the same share, the place under the pointer shows
    the same spot on every frame of the way, also while further steps of the wheel arrive. With motion unwanted the
    lens is there at once, and once it is as good as there it is there exactly."""
    got = page_rules(
        LENS
        + """
        const at = [-.2, .3], rest = { z: 1, q: [0, 0], aim: [0, 0, 0] }, there = { z: 3, q: [.4, -.6], aim: [.1, 0, -.2] };
        const step = zoomEased(rest, there, .12, false), still = zoomEased(rest, there, .12, true);
        let now = rest, goal = { ...zoomAt(rest, 2, at, hole), aim: [0, 0, 0] }, drift = 0, frames = 0;
        for (; frames < 400 && now.z !== goal.z; frames++) {
          if (frames % 3 === 0 && frames < 30) goal = { ...zoomAt(goal, 1.15, at, hole), aim: [0, 0, 0] };
          now = zoomEased(now, goal, 1 / 60, false);
          const spot = shows(now, at); drift = Math.max(drift, Math.abs(spot[0] - at[0]), Math.abs(spot[1] - at[1]));
        }
        const near = zoomEased({ z: 2.9995, q: [.3999, -.5999], aim: [.09999, 0, -.19999] }, there, 1 / 60, false);
        return { step: [round(step.z), round(step.q), round(step.aim)], still, drift, frames, end: [now.z === goal.z, now.q, goal.q], near };
        """
    )
    share = 1 - 2.718281828459045**-1
    assert close(
        [got["step"][0], *got["step"][1], *got["step"][2]],
        [1 + 2 * share, 0.4 * share, -0.6 * share, 0.1 * share, 0, -0.2 * share],
        1e-6,
    ), got["step"]
    assert got["still"] == {"z": 3, "q": [0.4, -0.6], "aim": [0.1, 0, -0.2]}, got["still"]
    assert got["drift"] < 1e-9 and 30 < got["frames"] < 120, (got["drift"], got["frames"])
    assert got["end"][0] and got["end"][1] == got["end"][2], got["end"]
    assert got["near"] == {"z": 3, "q": [0.4, -0.6], "aim": [0.1, 0, -0.2]}, got["near"]


@needs_node
def test_the_view_is_at_home_only_when_nothing_is_zoomed_moved_brought_to_the_middle_or_turned():
    """The button that takes the view back shows while there is something to take back: a zoom, a shift, a part in
    the middle, or a machine that was turned. A turn too small to see does not count."""
    got = page_rules(
        "const home = { z: 1, q: [0, 0], part: null };"
        "return [lensHome(home, [0, 0]), lensHome(home, [.0004, -.0004]), lensHome({ ...home, z: 1.5 }, [0, 0]),"
        " lensHome({ ...home, q: [0, -.01] }, [0, 0]), lensHome({ ...home, part: 'cx7' }, [0, 0]),"
        " lensHome(home, [.3, 0]), lensHome(home, [0, -.2]), lensHome({ ...home, q: [-0, 0] }, [0, 0])];"
    )
    assert got == [True, True, False, False, False, False, False, True], got


@needs_node
def test_plus_and_minus_zoom_by_a_quarter_and_zero_takes_the_view_back():
    """The keys of the lens: plus zooms in by a quarter, also from the key that carries the plus unshifted; minus
    zooms out by as much as plus zooms in; zero takes the view back. No other key is one of them."""
    got = page_rules("return ['+', '=', '-', '0', '1', '_', 'a', ' ', 'ArrowRight', 'Escape', ''].map(zoomKey);")
    assert got == [1.25, 1.25, 0.8, 0, None, None, None, None, None, None, None], got


@needs_node
def test_the_second_click_of_a_double_click_does_nothing_and_a_zoomed_view_is_not_left_by_a_click_beside_it():
    """A double click arrives as two clicks and then itself. The second click must not undo the first (it would let
    the part go that the first one picked): whatever lies under it, it does nothing. And a click beside every
    machine leaves the open Spark for the ring only from the view the Spark opened with: in a zoomed view it would
    throw the reader out on the first click of the double click that takes the view back."""
    got = page_rules(
        "const on = { opened: true, view: 'node', hit: null, part: null, picked: null };"
        "return [sceneClick({ ...on, part: 'cx7', picked: 'cx7', count: 2 }), sceneClick({ ...on, part: 'cx7', count: 2 }),"
        " sceneClick({ ...on, count: 2 }), sceneClick({ ...on, hit: 'b', count: 3 }),"
        " sceneClick({ ...on, home: false }), sceneClick({ ...on, home: true }), sceneClick({ ...on }),"
        " sceneClick({ ...on, home: false, hit: 'b' }), sceneClick({ ...on, home: false, picked: 'cx7' }),"
        " sceneClick({ ...on, home: false, part: 'fan' })];"
    )
    assert got[:4] == [["none"]] * 4, got[:4]
    assert got[4:7] == [["none"], ["ring"], ["ring"]], got[4:7]
    assert got[7:] == [["node", "b"], ["part", None], ["part", "fan"]], got[7:]  # zoomed, a click still picks and opens


@needs_node
def test_a_double_click_brings_the_part_under_it_to_the_middle_and_beside_the_parts_takes_the_view_back():
    """What a double click on the scene does, as one rule: on a part of the open Spark it asks for that part in the
    middle, beside the parts for the view the Spark opened with, and without an open Spark for nothing."""
    got = page_rules(
        "return [sceneDouble({ opened: true, part: 'cx7' }), sceneDouble({ opened: true, part: null }),"
        " sceneDouble({ opened: false, part: null }), sceneDouble({ opened: false, part: 'cx7' })];"
    )
    assert got == [["centre", "cx7"], ["home"], ["none"], ["none"]], got


@needs_node
def test_a_click_on_a_part_asks_for_it_in_the_middle_twice_as_near_and_never_zooms_out_for_it():
    """The lens a click on a part asks for: the part in the middle of the hole at twice the view the Spark opened
    with. A lens that stands nearer already keeps its zoom and only brings the part to the middle. A double click
    never shows a part smaller than a click does. The page may name another place than the middle of the hole to
    show the part at: beside a column of labels the middle of the hole is not the middle of what is free."""
    got = page_rules(
        LENS
        + """
        const base = [-.25, .2], lies = lens => round(base.map((v, k) => lens.z * v + lens.q[k]));
        const fresh = zoomPicked(home, base, hole), near = zoomPicked({ z: 5, q: [1, -1] }, base, hole), half = zoomPicked({ z: 1.5, q: [.1, 0] }, base, hole);
        const at = [-.1, .1];
        return { z: [fresh.z, near.z, half.z, ZOOM_PICK], lies: [fresh, near, half].map(lies), mid: hole.mid, least: zoomOnto(.9, base, hole).z,
          beside: [lies(zoomPicked(home, base, hole, at)), lies(zoomOnto(.2, base, hole, at))] };
        """
    )
    assert got["z"] == [2, 5, 2, 2], got["z"]
    assert got["lies"] == [got["mid"]] * 3, got["lies"]
    assert got["least"] == 2, got["least"]
    assert got["beside"] == [[-0.1, 0.1], [-0.1, 0.1]], got["beside"]  # where the page asks for it, not mid-hole


@needs_node
def test_escape_lets_a_picked_part_go_before_it_leaves_the_spark():
    """Escape steps back out one step at a time. With a part of the open Spark picked, the first step lets the part
    go (the lens returns to where it stood, the sheet of the Spark comes back); only the next one leaves the Spark.
    Nerd mode still goes first, and without a picked part nothing changed."""
    got = page_rules(
        "return [escapeDoes({ view: 'node', part: 'cx7' }), escapeDoes({ view: 'node', part: null }),"
        " escapeDoes({ nerd: true, view: 'node', part: 'cx7' }), escapeDoes({ view: 'node', part: 'cx7', past: true, strip: true }),"
        " escapeDoes({ view: 'ring', part: null, past: true })];"
    )
    assert got == ["part", "view", "nerd", "part", "live"], got


@needs_node
def test_shift_or_the_right_button_turn_a_drag_and_a_wheel_into_moving_the_picture():
    """Moving the picture of the open Spark: a drag moves it instead of turning the machine while Shift is held or
    the right button is down. A wheel moves it instead of zooming while Shift is held: by as far as the wheel turned,
    the picture going with the fingers, sideways and up and down, lines and pages counted like in a zoom. A pinch
    with Shift held still zooms."""
    got = page_rules(
        "return { drag: [{}, { shiftKey: true }, { buttons: 2 }, { buttons: 1 }, { buttons: 3 }, { shiftKey: true, buttons: 1 }].map(dragMoves),"
        " wheel: [{ deltaY: 40 }, { shiftKey: true, deltaX: 30, deltaY: -20 }, { shiftKey: true, deltaY: 3, deltaMode: 1 },"
        " { shiftKey: true, ctrlKey: true, deltaY: -5 }, { shiftKey: true }, { shiftKey: true, deltaX: -1, deltaMode: 2 }].map(wheelMoves) };"
    )
    assert got["drag"] == [False, True, True, False, True, True], got["drag"]
    assert got["wheel"] == [None, [-30, 20], [0, -75], None, [0, 0], [500, 0]], got["wheel"]


@needs_node
def test_a_label_wants_to_show_by_how_far_the_view_is_zoomed_and_whether_its_part_can_be_seen():
    """How visible the label of a part wants to be. Not at all while another part stands in front of its part, or
    its part lies outside the hole: a label must not point at what cannot be seen, whoever picked it. Whole for the
    picked part and for the part under the pointer, at any zoom. For every other part whole up to a zoom of 1.25 and
    gone from 2 on, which is as near as a click on a part goes: zoomed in, the labels would lie over the very thing
    the reader came to see."""
    got = page_rules(
        "const seen = { inside: true, hidden: false, picked: false, pointed: false };"
        "return { zooms: [1, 1.25, 1.625, 2, 8].map(zoom => labelShows({ ...seen, zoom })),"
        " kept: [labelShows({ ...seen, zoom: 8, picked: true }), labelShows({ ...seen, zoom: 3, pointed: true })],"
        " gone: [labelShows({ ...seen, zoom: 1, hidden: true }), labelShows({ ...seen, zoom: 1, inside: false }),"
        " labelShows({ ...seen, zoom: 1, hidden: true, picked: true }), labelShows({ ...seen, zoom: 4, inside: false, pointed: true })] };"
    )
    assert got["zooms"] == [1, 1, 0.5, 0, 0], got["zooms"]
    assert got["kept"] == [1, 1] and got["gone"] == [0, 0, 0, 0], got
