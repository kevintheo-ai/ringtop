"""The lens on the open Spark, driven without a browser: what wheel, pinch and keys do to its picture."""

from tests.fixtures import needs_node
from tests.test_page_scene import DOTS, DRAG, FOUND, MIDDLE, NARROW, WATCH, WIDE, near, opened, scene

# A wheel, a pinch or a key as the page hears it, counting whether the page kept the browser from acting on it itself.
HEAR = """
globalThis.kept = 0;
globalThis.turn = (el, at, more) => el.fire('wheel', { clientX: at[0], clientY: at[1], deltaX: 0, deltaMode: 0, preventDefault() { kept++; }, ...more });
globalThis.pinch = (kind, at, scale) => hole.fire(kind, { clientX: at[0], clientY: at[1], scale, preventDefault() { kept++; } });
globalThis.key = (name, more) => pageHears('keydown', { key: name, preventDefault() {}, ...more });
null
"""
CARD = "globalThis.card = dot('cx7')"  # the place every zoom of a check goes to: where the dot of the network card lies


@needs_node
def test_zooming_the_open_spark_keeps_what_stands_under_the_pointer_and_moves_everything_else_away_from_it():
    """The scene zooms around a place of the page. Zoomed by a fifth at the dot of the network card, that dot lies
    where it lay, on the very next frame and when the lens has come to rest, and the fan lies a fifth further from
    it. The scene still finds each part under its dot. Asked for far more, the zoom stops at its limit of 8; asked
    all the way back, every dot lies where it lay at first, and the view is the one the Spark opened with."""
    start, one, two, found, most, back = scene(
        [
            opened(NARROW) + f"; {WATCH}; {CARD}; [{DOTS}, far(card), Scene.zoomed()]",
            f"Scene.zoom(1.2, ...card); server.draw(1, 16.7); [{DOTS}, far(card)]",
            f"server.draw(60, 50); [{DOTS}, far(card), Scene.zoomed()]",
            FOUND,
            "Scene.zoom(100, ...card); server.draw(60, 50); far(card)",
            f"Scene.zoom(.001, ...card); server.draw(60, 50); [{DOTS}, far(card), Scene.zoomed()]",
        ]
    )
    card, wide = start[0]["cx7"], start[1]
    assert near(one[0]["cx7"], card) and near(two[0]["cx7"], card), (card, one, two)
    assert wide * 1.01 < one[1] < wide * 1.19, (wide, one[1])  # one frame on: under way, not there yet
    assert abs(two[1] / wide - 1.2) < 0.005 and abs(most / wide - 8) < 0.05, (two[1] / wide, most / wide)
    assert len(found) == 3 and all(part == under for part, under in found), found
    assert all(near(back[0][part], start[0][part]) for part in start[0]) and abs(back[1] / wide - 1) < 0.005, back
    assert [start[2], two[2], back[2]] == [False, True, False], (start[2], two[2], back[2])


@needs_node
def test_a_part_asked_for_comes_to_the_middle_of_the_hole_and_the_machine_turns_around_it():
    """Asked to show the die, the scene zooms in and brings it to the middle of the hole. Dragging then turns the
    machine around the die: it stays in the middle. A part is shown as large from wherever the view stood: the fan
    is as wide on the page asked for from the opening view as asked for from a zoom of three. A part the model
    does not have changes nothing."""
    start, shown, turned, odd, fan = scene(
        [
            opened(NARROW) + f"; {DOTS}",
            "Scene.hover('gb10_die_gpu'); Scene.centre('gb10_die_gpu'); server.draw(60, 50);"
            " [dot('gb10_die_gpu'), Scene.zoomed()]",
            f"{DRAG}; server.draw(30, 50); dot('gb10_die_gpu')",
            f"Scene.home(); Scene.hover(null); server.draw(60, 50); Scene.centre('no_such_part'); server.draw(30, 50);"
            f" [{DOTS}, Scene.zoomed()]",
            "(() => { const sizes = [];"
            " for (const from of [1, 3]) { Scene.home(); server.draw(60, 50); Scene.zoom(from, 200, 300);"
            " server.draw(60, 50); Scene.centre('fan_left'); server.draw(60, 50); sizes.push(wide('fan_left', 280)); }"
            " return sizes; })()",
        ]
    )
    assert near(shown[0], MIDDLE, 1) and shown[1] is True, (shown, MIDDLE)
    assert near(turned, MIDDLE, 1.5), (turned, MIDDLE)
    assert all(near(odd[0][part], start[part]) for part in start) and odd[1] is False, (start, odd)
    assert fan[0] > 100 and abs(fan[0] - fan[1]) <= 2, fan


@needs_node
def test_home_takes_back_zoom_shift_the_part_in_the_middle_and_the_turn_and_a_new_spark_opens_at_home():
    """Home takes everything back at once: every dot lies where it lay when the Spark opened, after a part was
    brought to the middle and the machine turned around it. A machine that was only turned is away from home too,
    and home turns it back. The view counts as home from the moment it is asked for. Another Spark opens with the
    view every Spark opens with, and nothing can be zoomed while a Spark closes or none stands open."""
    start, home, turned, other, closed = scene(
        [
            opened(NARROW) + f"; {DOTS}",
            f"Scene.centre('gb10_die_gpu'); server.draw(60, 50); {DRAG}; server.draw(30, 50); Scene.home();"
            f" (asked => {{ server.draw(60, 50); return [{DOTS}, asked, Scene.zoomed()]; }})(Scene.zoomed())",
            f"{DRAG}; server.draw(30, 50);"
            f" (was => {{ Scene.home(); server.draw(60, 50); return [was, Scene.zoomed(), {DOTS}]; }})(Scene.zoomed())",
            "Scene.zoom(3, 200, 300); setView('node', S.nodes[2].name); server.draw(100, 50); Scene.zoomed()",
            "setView('ring'); Scene.zoom(3, 200, 300); Scene.centre('cx7');"
            " (closing => { server.draw(60, 50); Scene.zoom(3, 200, 300); Scene.centre('cx7');"
            " return [closing, Scene.zoomed()]; })(Scene.zoomed())",
        ]
    )
    assert all(near(home[0][part], start[part]) for part in start), (start, home)
    assert home[1:] == [False, False], home[1:]
    assert turned[:2] == [True, False] and all(near(turned[2][part], start[part]) for part in start), (start, turned)
    assert other is False and closed == [False, False], (other, closed)


@needs_node
def test_with_motion_unwanted_the_lens_is_there_on_the_next_frame():
    """Reduce Motion: no run-out. One frame after a step of zoom the fan lies where it comes to rest, twice as far
    from the place of the zoom, and one frame after home every dot lies where it lay at first, turn and all."""
    start, first, rest, home = scene(
        [
            opened(NARROW) + f"; {WATCH}; calm.matches = true; server.draw(2, 50); {CARD}; [{DOTS}, far(card)]",
            "Scene.zoom(2, ...card); server.draw(1, 16.7); far(card)",
            "server.draw(40, 50); far(card)",
            f"{DRAG}; Scene.home(); server.draw(1, 16.7); {DOTS}",
        ]
    )
    assert abs(first - rest) < 0.2 and abs(first / start[1] - 2) < 0.01, (start[1], first, rest)
    assert all(near(home[part], start[0][part], 0.2) for part in start[0]), (start, home)


@needs_node
def test_when_the_hole_changes_its_place_under_a_zoomed_view_it_goes_on_showing_what_lies_in_it():
    """The view is zoomed in at the right edge of a wide hole. Then the hole becomes narrow, as it does when the
    window shrinks or the time machine takes room: the scene fits itself to the new hole, and the shift of the lens,
    asked for in the old one, would show a stretch of the page far beside it, with nothing of the machine. The shift
    is held inside the hole as it lies now: the hole shows the edge of what lies in it, and there stands the die."""
    before, after = scene(
        [
            opened(WIDE) + "; Scene.zoom(8, 18 + 660, 280); server.draw(60, 50); Scene.zoomed()",
            f"server.place('#hole', {NARROW}); server.draw(60, 50);"
            " (() => { let found = 0; for (let y = 60; y < 500; y += 5) found += wide('gb10_die_gpu', y); return found; })()",
        ]
    )
    assert before is True and after > 0, (before, after)


@needs_node
def test_the_wheel_and_a_pinch_over_the_open_spark_zoom_at_the_pointer_and_the_page_itself_stays_as_it_is():
    """Over the open Spark the wheel belongs to the scene. A turn of the wheel zooms at the pointer: the others
    move away from the place under it by the factor of the turn. So does a turn over a label, a pinch as Chrome
    sends it (a wheel with Ctrl held) and a pinch as Safari and other WebKit web views send it (the distance of the
    fingers against the start of the pinch, event after event). Every one of these events is kept from the browser:
    the page neither scrolls nor zooms as a whole."""
    wide, wheel, label, chrome, safari, again, kept = scene(
        [
            HEAR + "; " + opened(NARROW) + f"; {WATCH}; {CARD}; far(card)",
            "turn(hole, card, { deltaY: -250 }); server.draw(60, 50); [far(card), dot('cx7')]",
            "turn(document.querySelector('#callouts'), card, { deltaY: 250 }); server.draw(60, 50); far(card)",
            "turn(hole, card, { deltaY: -50, ctrlKey: true }); server.draw(60, 50); far(card)",
            "pinch('gesturestart', card, 1); pinch('gesturechange', card, 1.25); pinch('gesturechange', card, 1.6);"
            " pinch('gestureend', card, 1.6); server.draw(60, 50); far(card)",
            "pinch('gesturestart', card, 1); pinch('gesturechange', card, .5); server.draw(60, 50); far(card)",
            "[kept, card]",
        ]
    )
    for seen, times in ((wheel[0], 2**0.5), (label, 1), (chrome, 2), (safari, 3.2), (again, 1.6)):
        assert abs(seen / wide - times) < 0.02, (times, seen / wide)
    assert near(wheel[1], kept[1]), (wheel, kept)  # the place under the pointer stayed
    assert kept[0] == 8, kept  # three turns of the wheel and five events of the two pinches


@needs_node
def test_the_wheel_is_left_to_the_page_where_no_spark_stands_open_and_only_kept_while_one_opens():
    """On the ring and on every other view the wheel is the page's own: nothing is zoomed, and the browser may
    scroll. While a Spark is still opening, the wheel is kept from the browser already (a pinch would zoom the whole
    page) but does not zoom yet."""
    ring, why, opening, done = scene(
        [
            HEAR + "; turn(hole, [300, 300], { deltaY: -250 }); server.draw(20, 50); [kept, Scene.zoomed()]",
            "setView('why'); turn(hole, [300, 300], { deltaY: -250, ctrlKey: true }); [kept, Scene.zoomed()]",
            f"server.place('#hole', {NARROW}); setView('node', S.nodes[1].name); server.draw(5, 50);"
            " turn(hole, [300, 300], { deltaY: -250 }); [kept, Scene.opened(), Scene.zoomed()]",
            "server.draw(100, 50); [Scene.opened(), Scene.zoomed()]",
        ]
    )
    assert ring == [0, False] and why == [0, False], (ring, why)
    assert opening == [1, False, False] and done == [True, False], (opening, done)


@needs_node
def test_plus_minus_and_zero_work_the_lens_of_the_open_spark_and_no_other_key_changes_its_meaning():
    """With a Spark open, plus zooms in around the middle of the hole, minus zooms out again, zero takes the view
    back, turn and all. Not while a field is typed in, not with Cmd, Ctrl or Alt held (those belong to the browser),
    and not without an open Spark: then zero does nothing and the digits still change the view. Like any key, they
    end the tour. A Spark that is still opening is not zoomed yet."""
    middle = f"[{MIDDLE[0]}, {MIDDLE[1]}]"  # the keys zoom around the place a part is shown at
    plus, minus, zero, typed, held, digits, tour, opening = scene(
        [
            HEAR + "; " + opened(NARROW) + f"; {WATCH}; (wide => {{ key('+'); key('='); server.draw(60, 50);"
            f" return [far({middle}) / wide, Scene.zoomed()]; }})(far({middle}))",
            f"(wide => {{ key('-'); server.draw(60, 50); return far({middle}) / wide; }})(far({middle}))",
            f"{DRAG}; server.draw(20, 50); key('0'); server.draw(60, 50); [Scene.zoomed(), V, VN === S.nodes[1].name]",
            "key('+', { target: document.createElement('input') }); Scene.zoomed()",
            "key('+', { metaKey: true }); key('-', { ctrlKey: true }); key('0', { altKey: true }); Scene.zoomed()",
            "setView('ring'); server.draw(60, 50); key('+'); key('0'); const ring = [V, Scene.zoomed()]; key('2'); [ring, V]",
            "Tour.toggle(true); (on => { key('+'); return [on, Tour.isOn()]; })(Tour.isOn())",
            "setView('node', S.nodes[1].name); server.draw(5, 50); key('+'); [Scene.opened(), Scene.zoomed()]",
        ]
    )
    assert abs(plus[0] - 1.25**2) < 0.02 and plus[1] is True, plus
    assert abs(minus - 0.8) < 0.01, minus
    assert zero == [False, "node", True], zero
    assert typed is False and held is False, (typed, held)
    assert digits == [["ring", False], "why"], digits
    assert tour == [True, False], tour
    assert opening == [False, False], opening  # a Spark that is still opening is not zoomed by a key either


@needs_node
def test_what_lies_outside_the_hole_dims_while_the_open_spark_is_zoomed():
    """The scene fills the whole window, behind the head and the foot of the page: at zoom 1 that is sky and ice,
    zoomed in it would be bright parts of the machine behind the words. The last pass of a frame is told where the
    hole lies (in pixels of the canvas, from its bottom left) and how much to dim what lies outside it: nothing at
    home, all of it from a zoom of one and a half on (a tenth of the light left over still shows as a ghost of the
    machine once the screen has brightened it), softly in between, over an edge of 18 pixels of the page."""
    home, zoomed, between, back = scene(
        [
            opened(NARROW) + "; globalThis.canvas = document.querySelector('#scene').getContext('webgl2');"
            " globalThis.panes = []; globalThis.veils = [];"
            " canvas.uniform4f = (where, ...box) => panes.push(box);"
            " canvas.uniform2f = (where, veil, edge) => { if (edge === 36) veils.push(veil); };"
            " server.draw(2, 50); [panes.at(-1), veils.at(-1)]",
            "Scene.zoom(2, 200, 300); server.draw(60, 50); [panes.at(-1), veils.at(-1)]",
            "Scene.zoom(.625, 200, 300); server.draw(60, 50); veils.at(-1)",
            "Scene.home(); server.draw(60, 50); veils.at(-1)",
        ]
    )
    assert home == [[36, 250, 776, 1130], 0], home  # the narrow hole, twice as many pixels as the page counts
    assert zoomed[0] == home[0] and zoomed[1] == 1, zoomed
    assert abs(between - 0.5) < 1e-3 and back == 0, (between, back)


# A drag over the hole from one place by so many pixels, with the keys and buttons that are held meanwhile.
PULL = """
globalThis.pull = (by, more, button = 0) => { hole.fire('pointerdown', { clientX: 250, clientY: 300, pointerId: 1, button, buttons: 1, ...more });
  hole.fire('pointermove', { clientX: 250 + by[0], clientY: 300 + by[1], buttons: 1, ...more }); hole.fire('pointerup', { button }); };
globalThis.fan = () => dot('fan_left');
null
"""


@needs_node
def test_the_zoomed_picture_is_moved_by_a_drag_with_shift_or_the_right_button_and_by_a_wheel_with_shift():
    """The view of a part moves freely. Zoomed in, a drag with Shift held moves
    the picture by as far as the pointer went, at once, without a run-out; so does a drag with the right button, and
    two fingers pushed with Shift held (a wheel with Shift). A plain drag still turns the machine. At zoom 1 there
    is nothing to move: the picture fills the hole, and a drag with Shift neither moves nor turns it."""
    home, start, shift, right, wheel, plain = scene(
        [
            HEAR + PULL + "; " + opened(NARROW) + f"; {WATCH}; {CARD};"
            " (was => { pull([40, -30], { shiftKey: true }); server.draw(20, 50); return [was, fan()]; })(fan())",
            "Scene.zoom(3, ...card); server.draw(60, 50); fan()",
            "pull([40, -30], { shiftKey: true }); server.draw(1, 16.7); fan()",
            "pull([-20, 10], { buttons: 2 }, 2); server.draw(1, 16.7); fan()",
            "turn(hole, card, { shiftKey: true, deltaX: 30, deltaY: -20 }); server.draw(1, 16.7); [fan(), kept]",
            "(was => { pull([40, -30], {}); server.draw(20, 50); return [was, fan()]; })(fan())",
        ]
    )
    assert near(home[0], home[1], 0.2), home
    assert near(shift, [start[0] + 40, start[1] - 30]), (start, shift)
    assert near(right, [shift[0] - 20, shift[1] + 10]), (shift, right)
    assert near(wheel[0], [right[0] - 30, right[1] + 20]) and wheel[1] == 1, (right, wheel)  # and kept from the browser
    moved = [plain[1][0] - plain[0][0], plain[1][1] - plain[0][1]]
    assert not near(moved, [40, -30], 3) and not near(moved, [0, 0], 3), moved  # a turn, not a move by the drag


@needs_node
def test_moving_the_picture_stops_at_the_edge_of_what_the_hole_showed_and_ends_like_any_drag():
    """However far the picture is pushed, the hole never shows anything it did not show at zoom 1: pushed all the
    way to the left at a zoom of three, the hole shows the right third of what lay in it, and the fan lies exactly
    where that puts it. The click that ends a drag with Shift picks nothing; a drag with the right button is
    followed by no click, so the next click picks as ever. And the menu of the browser stays away from the scene
    while a Spark is open, over the hole and over the labels: the right button belongs to the drag there."""
    start, pushed, clicks, menu = scene(
        [
            HEAR + PULL + "; " + opened(NARROW) + f"; {WATCH}; {CARD}; fan()",
            "Scene.zoom(3, ...card); server.draw(60, 50); pull([-5000, 0], { shiftKey: true }); server.draw(2, 50);"
            " (left => { pull([5000, 0], { buttons: 2 }, 2); pull([-5000, 0], { buttons: 2 }, 2); server.draw(2, 50);"
            " return [left, fan()]; })(fan())",
            "Scene.home(); server.draw(60, 50); Scene.zoom(1.2, ...card); server.draw(60, 50);"
            " pull([30, 0], { shiftKey: true }); click(...dot('cx7')); const after_shift = VP;"
            " pull([-30, 0], { buttons: 2 }, 2); click(...dot('cx7')); [after_shift, VP]",
            "(() => { const menu = el => el.fire('contextmenu', { preventDefault() { kept++; } }), from = kept;"
            " menu(hole); menu(document.querySelector('#callouts')); const open = kept - from;"
            " setView('ring'); menu(hole); menu(document.querySelector('#callouts')); return [open, kept - from - open]; })()",
        ]
    )
    left, right_edge, width = 18, 18 + 370, 370
    want = left + 3 * (start[0] - (right_edge - width / 3))
    assert abs(pushed[0][0] - want) < 1 and near(pushed[0], pushed[1]), (start, pushed, want)
    assert clicks == [None, "cx7"], clicks
    assert menu == [2, 0], menu


@needs_node
def test_a_picture_moved_while_the_lens_still_runs_in_stays_inside_what_the_hole_showed():
    """The lens runs in to a zoom of eight, and the reader pushes the picture at once, as far as a zoom of eight
    lets it go. The push was taken at once and in full, while the picture was drawn at less than twice its size:
    for some frames the hole showed what lies far beside it, and the machine was gone from the page. The picture is
    held inside the hole at the zoom it is drawn with; at rest it lies where the bound of a zoom of eight puts it."""
    start, soon, rest = scene(
        [
            HEAR + PULL + "; " + opened(NARROW) + f"; {WATCH}; {CARD}; fan()",
            "Scene.zoom(8, ...card); pull([-5000, 0], { shiftKey: true }); server.draw(1, 16.7); fan()",
            "server.draw(60, 50); fan()",
        ]
    )
    left, right_edge, width = 18, 18 + 370, 370
    assert soon[0] > left - width, (start, soon)  # was some two thousand pixels to the left of the page
    assert abs(rest[0] - (left + 8 * (start[0] - (right_edge - width / 8)))) < 1, (start, rest)


@needs_node
def test_a_turn_of_the_machine_ends_its_way_home():
    """Home turns the machine back over the better part of a second. A reader who took the view back and turned the
    machine again at once had that turn taken from his hand frame by frame: the machine went home after all, and the
    button that takes the view back stayed away. A turn ends the way home: the machine stays as it was turned."""
    start, turned = scene(
        [
            opened(NARROW) + f"; {DOTS}",
            f"{DRAG}; server.draw(30, 50); Scene.home(); server.draw(2, 16.7); {DRAG}; server.draw(60, 50);"
            f" [{DOTS}, Scene.zoomed()]",
        ]
    )
    moved = [part for part in start if part in turned[0] and not near(turned[0][part], start[part], 3)]
    assert turned[1] is True and moved, (start, turned)


@needs_node
def test_a_double_click_means_the_part_its_first_click_fell_on():
    """The first click of a double click picks the part, and the lens sets off with it at once. By the time the
    double click is told, a fifth of a second later, the part has left the place of the pointer: the double click
    asked what lay there now. Nothing lay where the die had been, and the view was taken back; the board lay where
    the network card had been, and the board was picked and brought to the middle. A double click means the part
    its first click fell on, and brings that one to the middle as asking for it does."""
    twice = (
        "(() => {{ Scene.home(); setPart(null); server.draw(60, 50); const at = dot('{part}'); click(...at);"
        " server.draw(4, 50); const under = Scene.part(at[0], at[1]); click(...at, {{ detail: 2 }});"
        " hole.fire('dblclick', {{ clientX: at[0], clientY: at[1], detail: 2 }}); server.draw(60, 50);"
        " return [under, VP, dot('{part}'), Scene.zoomed()]; }})()"
    )
    asked = (
        "Scene.home(); setPart(null); server.draw(60, 50); setPart('{part}'); Scene.centre('{part}');"
        " server.draw(60, 50); dot('{part}')"
    )
    steps = [opened(NARROW) + "; null"]
    for part in ("gb10_die_gpu", "cx7"):
        steps += [twice.format(part=part), asked.format(part=part)]
    _, die, die_asked, card, card_asked = scene(steps)
    assert die[0] is None and card[0] == "pcb", (die, card)  # what the double click found under the pointer
    assert die[1] == "gb10_die_gpu" and die[3] is True and near(die[2], die_asked, 2), (die, die_asked)
    assert card[1] == "cx7" and card[3] is True and near(card[2], card_asked, 2), (card, card_asked)


@needs_node
def test_a_pinch_ends_the_tour_in_the_form_safari_says_it_as_in_the_form_of_a_wheel():
    """The tour hands the page back at the first thing a hand does. A pinch reaches the page in two forms: as a
    wheel with Ctrl held (Chrome, Firefox) and in events of its own (Safari, a WebKit web view). Both zoom
    the open Spark, so both end the tour. In the second form it ran on, and took the zoomed view away at its
    next stop."""
    ended = "(on => {{ pageHears('{kind}', {{ target: hole, {more} }}); return [on, Tour.isOn()]; }})(Tour.isOn())"
    _, wheel, safari = scene(
        [
            opened(NARROW) + "; null",
            "Tour.toggle(true); " + ended.format(kind="wheel", more="deltaY: -50, ctrlKey: true"),
            "Tour.toggle(true); " + ended.format(kind="gesturestart", more="scale: 1"),
        ]
    )
    assert wheel == [True, False] and safari == [True, False], (wheel, safari)
