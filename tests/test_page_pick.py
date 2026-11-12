"""A part of the open Spark, picked: what a click, a double click, Escape, the button in the hole and the tour do to
the lens, driven without a browser."""

import json

from ringtop_parts.connect.server import PAGE
from tests.fixtures import needs_node
from tests.test_page_scene import DOTS, DRAG, MIDDLE, NARROW, near, opened, scene
from tests.test_page_sheet import moments
from tests.test_page_zoom import HEAR

# A double click as a browser says it: two clicks, the second counted as such, then the double click itself. A place
# beside every part and every machine. The button that takes the view back.
TWICE = """
globalThis.twice = (el, x, y, more) => { for (const count of [1, 2]) el.fire('click', { clientX: x, clientY: y, detail: count, ...more });
  el.fire('dblclick', { clientX: x, clientY: y, detail: 2, ...more }); };
globalThis.free = () => { for (let y = 70; y < 490; y += 10) for (let x = 30; x < 380; x += 10) if (!Scene.part(x, y) && !Scene.pick(x, y)) return [x, y]; };
globalThis.homeButton = document.querySelector('#lens-home');
null
"""
TAG = "document.querySelector('#callouts').children.find(el => el.dataset.part === 'fan_left')"  # the label of the fan


@needs_node
def test_a_click_on_a_part_brings_it_to_the_middle_twice_as_near_and_letting_it_go_leads_the_lens_back():
    """A click on a part of the open Spark goes nearer to that part, not all the way, just
    twice as near, to see what it is. The click that picks a part brings it to the middle of the hole beside the
    labels (where the machine stands when it opens: the label of the part stays, and would lie over it in the very
    middle of a narrow hole) at twice the opening view, with the run-out of the lens (the camera now looks at the part, so what lies before or behind it
    shifts a little against it: the fan lies about twice as far from the card, not exactly). A click on it again
    lets it go, and the lens returns to where it stood before: every dot lies where it lay. A part this model does
    not have (the tour may pick one) leaves the lens alone."""
    start, picked, back, unknown = scene(
        [
            opened(NARROW) + f"; Scene.hover('fan_left'); server.draw(10, 50); [{DOTS}, far(dot('cx7'))]",
            "click(...dot('cx7')); server.draw(1, 16.7); (first => { server.draw(60, 50);"
            " return [VP, first, dot('cx7'), far(dot('cx7')), Scene.zoomed()]; })(far(dot('cx7')))",
            f"click(...dot('cx7')); server.draw(60, 50); [VP, {DOTS}, Scene.zoomed()]",
            "setPart('lpddr_0'); server.draw(30, 50); (seen => { setPart(null); return seen; })([VP, Scene.zoomed()])",
        ]
    )
    assert unknown == ["lpddr_0", False], unknown  # picked on the page, but the model has no such part to go to
    wide = start[1]
    assert picked[0] == "cx7" and picked[4] is True, picked
    assert wide * 1.02 < picked[1] < wide * 1.6, (picked[1], wide)  # one frame on: under way, not there yet
    assert near(picked[2], MIDDLE, 1) and 1.8 < picked[3] / wide < 2.4, (picked, wide)
    assert back[0] is None and back[2] is False, back
    assert all(near(back[1][part], start[0][part]) for part in start[0]), (start, back)


@needs_node
def test_a_lens_that_stands_nearer_keeps_its_zoom_for_a_picked_part_and_returns_to_where_it_stood():
    """From a lens that stood at one and a half, a click on a part goes to two and letting go leads back to one and
    a half, exactly where it stood. From a lens that stood at four the click keeps the four and only brings the
    part to the middle; a click on another part moves on to that one, still at four; and letting that one go leads
    back to where the lens stood before the first of the two was picked, not to where it stood before an earlier
    pick that is long let go."""
    wide, half, four = scene(
        [
            opened(NARROW) + "; Scene.hover('fan_left'); server.draw(10, 50); far(dot('cx7'))",
            "Scene.zoom(1.5, 250, 300); server.draw(60, 50); (was => { click(...dot('cx7')); server.draw(60, 50);"
            " const there = [dot('cx7'), far(dot('cx7'))]; click(...dot('cx7')); server.draw(60, 50);"
            " return [was, there, [dot('cx7'), far(dot('cx7'))]]; })([dot('cx7'), far(dot('cx7'))])",
            "Scene.zoom(4 / 1.5, 250, 300); Scene.hover('cx7'); server.draw(60, 50);"
            " (was => { click(...dot('cx7')); Scene.hover('fan_left'); server.draw(60, 50);"
            " const card = [VP, dot('cx7'), far(dot('cx7'))];"
            " click(...dot('fan_left')); Scene.hover('cx7'); server.draw(60, 50);"
            " const fan = [VP, dot('fan_left'), far(dot('cx7'))];"
            " click(...dot('fan_left')); server.draw(60, 50); return [was, card, fan, [VP, dot('cx7')]]; })(dot('cx7'))",
        ]
    )
    was, there, again = half
    assert near(there[0], MIDDLE, 1) and 1.8 < there[1] / wide < 2.4, (there, wide)
    assert abs(was[1] / wide - 1.5) < 0.01 and near(again[0], was[0]) and abs(again[1] / wide - 1.5) < 0.01, half
    was, card, fan, let_go = four
    assert card[0] == "cx7" and near(card[1], MIDDLE, 1) and 3.6 < card[2] / wide < 4.8, (card, wide)
    assert fan[0] == "fan_left" and near(fan[1], MIDDLE, 1) and 3.6 < fan[2] / wide < 4.8, (fan, wide)
    assert let_go[0] is None and near(let_go[1], was), (was, let_go)


@needs_node
def test_escape_and_the_way_back_to_the_sheet_let_the_part_go_and_the_lens_return_and_home_forgets_where_it_stood():
    """Every way a part is let go leads the lens back: Escape (which lets the part go first and leaves the Spark
    only on the next press), and a click on the open Spark in the dock, which leads from a part back to its sheet.
    After the view was taken back with a part still picked, letting the part go leaves the view at home, also when
    the part was picked from a zoomed view: there is no older place to return to. With motion unwanted the lens is on the part one frame after the click."""
    start, escape, again, sheet, home, still = scene(
        [
            HEAR + "; " + opened(NARROW) + f"; {DOTS}",
            f"click(...dot('cx7')); server.draw(60, 50); key('Escape'); server.draw(60, 50); [V, VP, {DOTS}]",
            "key('Escape'); [V, VP]",
            "setView('node', S.nodes[1].name); server.draw(100, 50); click(...dot('cx7')); server.draw(60, 50);"
            f" setView('node', S.nodes[1].name); server.draw(60, 50); [V, VP, {DOTS}]",
            "Scene.zoom(3, 250, 300); Scene.hover('cx7'); server.draw(60, 50); click(...dot('cx7')); server.draw(60, 50);"
            " Scene.home(); Scene.hover(null); server.draw(60, 50);"
            f" (picked => {{ setPart(null); server.draw(60, 50); return [picked, VP, {DOTS}, Scene.zoomed()]; }})(VP)",
            "calm.matches = true; click(...dot('cx7')); server.draw(1, 16.7); [VP, dot('cx7')]",
        ]
    )
    assert escape[:2] == ["node", None] and all(near(escape[2][p], start[p]) for p in start), (start, escape)
    assert again == ["ring", None], again
    assert sheet[:2] == ["node", None] and all(near(sheet[2][p], start[p]) for p in start), (start, sheet)
    assert home[:2] == ["cx7", None] and home[3] is False, home
    assert all(near(home[2][p], start[p]) for p in start), (start, home)
    assert still[0] == "cx7" and near(still[1], MIDDLE, 1), still


@needs_node
def test_a_double_click_on_a_part_brings_it_to_the_middle_and_keeps_it_picked():
    """A double click on a part of the open Spark picks it and brings it to the middle of the hole, zoomed in until
    it fills half of it: the second of its two clicks does not let the part go again, on the part and on its label.
    On the part that is already picked it does the same, and the part is picked afterwards. The double click goes
    nearer than the click: the fan is wider on the page after it."""
    clicks, first, again, label, sizes = scene(
        [
            TWICE + "; " + opened(NARROW) + "; (tag => { const seen = [];"
            " for (const count of [1, 2]) { click(...dot('fan_left'), { detail: count }); seen.push(VP); }"
            " setPart(null);"
            " for (const count of [1, 2]) { document.querySelector('#callouts').fire('click', { target: tag, detail: count });"
            f" seen.push(VP); }} setPart(null); return seen; }})({TAG})",
            "twice(hole, ...dot('cx7')); server.draw(60, 50); [VP, dot('cx7'), Scene.zoomed()]",
            "twice(hole, ...dot('cx7')); server.draw(60, 50); [VP, dot('cx7'), Scene.zoomed()]",
            f"setPart(null); server.draw(60, 50); (tag => {{ twice(document.querySelector('#callouts'), 0, 0, {{ target: tag }});"
            f" server.draw(60, 50); return [VP, dot('fan_left'), Scene.zoomed()]; }})({TAG})",
            "(twiced => { setPart(null); server.draw(60, 50); click(...dot('fan_left')); server.draw(60, 50);"
            " return [twiced, wide('fan_left', 280)]; })(wide('fan_left', 280))",
        ]
    )
    assert clicks == ["fan_left"] * 4, (
        clicks
    )  # after the first and after the second click, on the part and on its label
    for seen, part in ((first, "cx7"), (again, "cx7"), (label, "fan_left")):
        assert seen[0] == part and near(seen[1], MIDDLE, 1) and seen[2] is True, (part, seen)
    assert sizes[0] > sizes[1] * 1.3 > 50, sizes


@needs_node
def test_a_double_click_beside_the_parts_and_the_button_take_the_view_back_and_a_single_click_does_not_leave_it():
    """Zoomed in, a single click beside every machine does not lead back to the ring: it is the first click of the
    double click that takes the view back, and that double click does: every dot lies where it lay when the Spark
    opened, and the Spark is still open. The button in the corner of the hole does the same. It shows only while
    there is something to take back: not at home, from the first frame of a zoom on, also for a machine that was
    only turned, and it is gone again once the view is asked back."""
    start, single, double, turned, pressed = scene(
        [
            TWICE + "; " + opened(NARROW) + f"; [{DOTS}, homeButton.hidden]",
            "Scene.zoom(3, 380, 490); server.draw(60, 50);"
            " (at => { click(...at); return [!!at, V, Scene.zoomed(), homeButton.hidden]; })(free())",
            f"twice(hole, ...free()); server.draw(60, 50); [{DOTS}, V, Scene.zoomed(), homeButton.hidden]",
            f"{DRAG}; server.draw(2, 50); [Scene.zoomed(), homeButton.hidden]",
            f"homeButton.fire('click', {{ stopPropagation() {{}} }}); server.draw(60, 50);"
            f" [{DOTS}, V, Scene.zoomed(), homeButton.hidden]",
        ]
    )
    assert start[1] is True, start[1]  # hidden at home
    assert single == [True, "node", True, False], single  # a place beside every machine was found, and the click stayed
    for seen in (double, pressed):
        assert all(near(seen[0][part], start[0][part]) for part in start[0]), (start, seen)
        assert seen[1:] == ["node", False, True], seen[1:]
    assert turned == [True, False], turned


def test_the_button_that_takes_the_view_back_is_a_button_of_the_hole_with_its_word_as_its_name():
    """The page carries the button inside the hole, hidden until the scene shows it, with the word it shows as the
    name a screen reader says, and the style sheet gives it a ring for the keyboard and keeps a double click on the
    scene of an open Spark from selecting text."""
    page, style = PAGE.read_text(), (PAGE.parent / "style.css").read_text()
    hole = page[page.index('<div class="hole" id="hole">') : page.index('<section id="timebar"')]
    assert '<button id="lens-home" type="button" hidden aria-label="Reset view"' in hole, hole
    assert ">Reset view</button>" in hole, hole
    assert "#lens-home:focus-visible{outline:" in style and "#lens-home[hidden]{display:none}" in style
    assert "user-select:none" in style[style.index("body.sparking .hole{-webkit-user-select") :][:80]  # only there
    assert "\n.hole{-webkit-user-select" not in style  # on the ring the speed in the middle can still be selected


@needs_node
def test_the_tour_shows_a_part_through_the_same_lens_and_the_next_stop_starts_from_the_opening_view():
    """On the tour a Spark opens, and partway through its stop one of its parts is picked: the same pick as a
    click, so the lens goes to that part, softly, and the tour goes on. The next stop starts with the view every
    Spark opens with. The time machine changes nothing about it: looking back, a click on a part goes as near."""
    then = json.loads(moments())["past"]["t"]
    stop, moved_on, _, past = scene(
        [
            HEAR + f"; server.place('#hole', {NARROW});"
            " globalThis.setInterval = step => { globalThis.tourStep = step; return 1; }; Tour.toggle(true);"
            " (() => { for (let i = 0; i < 400 && !(V === 'node' && VP && Scene.zoomed()); i++) { server.draw(5, 50); tourStep(); }"
            " const picked = [V, VP, Tour.isOn()]; server.draw(40, 50); return [...picked, Scene.zoomed(), dot(VP)]; })()",
            "(spark => { for (let i = 0; i < 400 && VN === spark; i++) { server.draw(5, 50); tourStep(); }"
            " return [VN !== spark, VP, Scene.zoomed(), Tour.isOn()]; })(VN)",
            "Tour.toggle(false); setView('node', S.nodes[1].name); server.draw(100, 50);"
            f" Time.toggle(true); Time.go({then[len(then) // 2]}); null",  # the recording arrives before the next step
            "server.draw(20, 50);"
            " (() => { const was = [Time.isPast(), S.nodes[1].live]; click(...dot('cx7')); server.draw(60, 50);"
            " return [was, VP, dot('cx7'), Scene.zoomed()]; })()",
        ]
    )
    assert stop[:4] == ["node", stop[1], True, True] and stop[1], stop
    assert near(stop[4], MIDDLE, 1.5), stop
    assert moved_on == [True, None, False, True], moved_on
    assert past[0] == [True, True] and past[1] == "cx7" and near(past[2], MIDDLE, 1) and past[3] is True, past
