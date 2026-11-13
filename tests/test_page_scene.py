"""The scene of an open Spark, driven without a browser: where its parts and their labels stand, and what a pointer
does to them."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from ringtop_parts.core.demo_forms import demo_map
from tests.fixtures import needs_node, page_moments, page_rules, page_scripts, tiny_model
from tests.test_page_sheet import moments, sheet

# The names every step of a check finds its way around the scene with: the hole the scene shows through, the labels
# of the open Spark (each with its part, whether it shows, where it stands and where the dot on its part lies), the
# ones that show, the dot of one part, a click on the scene, how many pixels wide a part is on one row of the page,
# and how far the dot of the fan lies from a place.
TOOLS = r"""
globalThis.hole = document.querySelector('#hole');
globalThis.labels = () => {
  const lines = document.querySelector('#leaders').children;
  return document.querySelector('#callouts').children.map((el, i) => {
    const place = /translate3d\(([-\d.]+)px,([-\d.]+)px/.exec(el.style.transform || '') || [];
    const dot = lines[2 * i + 1];
    return { part: el.dataset.part, shown: el.style.visibility === 'visible', alpha: +el.style.opacity || 0,
      x: +place[1], y: +place[2], dot: [+dot.getAttribute('cx'), +dot.getAttribute('cy')] };
  });
};
globalThis.showing = () => labels().filter(l => l.shown);
globalThis.dot = part => labels().find(l => l.part === part).dot;
globalThis.click = (x, y, more) => hole.fire('click', { clientX: x, clientY: y, detail: 1, ...more });
globalThis.wide = (part, y) => { let n = 0; for (let x = 0; x < 1064; x++) if (Scene.part(x, y) === part) n++; return n; };
globalThis.far = from => Math.hypot(dot('fan_left')[0] - from[0], dot('fan_left')[1] - from[1]);
null
"""
# The hole as it lies on a page of 1064 by 625: wide beside the panels of the ring, narrow beside the sheet of a Spark.
WIDE = "{ left: 18, top: 60, width: 660, height: 440 }"
NARROW = "{ left: 18, top: 60, width: 370, height: 440 }"
LEFT = 18 + 4  # where a label at the left edge of the hole begins
VOID = "60, 120"  # a place in the narrow hole where no machine stands: beside the open Spark and every other one
FOUND = "showing().map(l => [l.part, Scene.part(l.dot[0], l.dot[1])])"  # the part the scene finds under every dot


def opened(box):
    """The step that gives the hole its place, opens the second Spark and draws until it stands open: five seconds,
    longer than the flight of the camera and the taking apart."""
    return f"server.place('#hole', {box}); setView('node', S.nodes[1].name); server.draw(100, 50); Scene.opened()"


def scene(steps, change=None, **more):
    """Loads the page without a browser, with a Spark of six boxes for a model, and runs `steps` in it one after the
    other, each a piece of script; gives back what each step returned. No error may fall on the way. `change(states)`
    changes the moments of the demo before the page gets them."""
    with tempfile.TemporaryDirectory() as folder:
        model = Path(folder) / "spark.glb"
        model.write_bytes(tiny_model())
        file = Path(folder) / "moments.json"
        states = json.loads(moments())
        if change:
            change(states)
        file.write_text(json.dumps({**states, "steps": [TOOLS, *steps]}))
        done = subprocess.run(
            ["node", str(Path(__file__).with_name("page_loader.js")), "sheet", str(file), *page_scripts(folder)],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "RINGTOP_MODEL": str(model), **more},
        )
    assert done.returncode == 0 and done.stdout, done.stderr[-600:]
    seen = json.loads(done.stdout)
    assert seen["errors"] == [], seen["errors"][:4]
    return seen["steps"][1:]


@needs_node
def test_the_labels_of_an_open_spark_stand_beside_their_parts_and_the_scene_finds_each_part_under_its_dot():
    """A Spark is opened and taken apart. Every part with a label gets one beside the machine, tied to a dot on the
    part. In a wide hole the labels stand on both sides, in a narrow one all at the left edge with the machine to
    the right of them. And the way back holds: asked for the part under a dot, the scene names the part of that
    label. The camera, the place of every part and the ray under the pointer are one reckoning."""
    wide, wide_found, narrow, narrow_found = scene(
        [opened(WIDE) + "; showing()", FOUND, f"server.place('#hole', {NARROW}); server.draw(40, 50); showing()", FOUND]
    )
    assert sorted(label["part"] for label in wide) == ["cx7", "fan_left", "gb10_die_gpu"], wide
    for labels, found, right in ((wide, wide_found, 18 + 660), (narrow, narrow_found, 18 + 370)):
        assert found == [[label["part"], label["part"]] for label in labels], found
        for label in labels:
            assert 18 < label["dot"][0] < right and 60 < label["dot"][1] < 500, label  # the dot lies in the hole
            assert label["alpha"] == 1, label
    assert {label["x"] == LEFT for label in wide} == {True, False}, wide  # some at the left edge, some at the right
    assert all(label["x"] == LEFT for label in narrow), narrow
    assert all(label["dot"][0] > 18 + 176 for label in narrow), narrow  # the machine stands to the right of them
    heights = sorted(label["y"] for label in narrow)
    assert all(below - above >= 39.9 for above, below in zip(heights, heights[1:])), heights  # none on another


@needs_node
def test_a_part_another_part_hides_has_no_label_until_the_machine_is_turned():
    """The SSD of the made-up Spark lies under its board. Seen from above the board stands in front of it: it has no
    label, and no line points through the board. Dragging the machine upright shows it from the side, and its label
    comes. The click that ends a drag is no click on the scene: it picks nothing and leaves nothing."""
    before, after, clicked = scene(
        [
            opened(NARROW) + "; labels()",
            "hole.fire('pointerdown', { clientX: 250, clientY: 300, pointerId: 1 });"
            " hole.fire('pointermove', { clientX: 250, clientY: 240 }); hole.fire('pointerup', {});"
            " server.draw(30, 50); labels()",
            "click(30, 480); [V, VP]",
        ]
    )
    hidden = {label["part"]: label for label in before}["ssd_m2"]
    assert not hidden["shown"], hidden
    seen = {label["part"]: label for label in after}
    assert seen["ssd_m2"]["shown"] and seen["ssd_m2"]["x"] == LEFT, seen["ssd_m2"]
    was = {label["part"]: label["dot"] for label in before}
    assert all(seen[part]["dot"] != was[part] for part in ("cx7", "fan_left", "gb10_die_gpu")), (was, seen)
    assert clicked == ["node", None], clicked


@needs_node
def test_a_click_picks_a_part_lets_it_go_again_and_beside_the_machine_leads_back_to_the_ring():
    """A click on a part of the open Spark picks it, a second click on it lets it go. A click beside every machine
    leaves the Spark for the ring, and its labels go with it."""
    first, second, void, away, left = scene(
        [
            opened(NARROW) + "; click(...dot('cx7')); [V, VN === S.nodes[1].name, VP]",
            "click(...dot('cx7')); [V, VN === S.nodes[1].name, VP]",
            f"Scene.pick({VOID})",
            f"click({VOID}); [V, VP]",
            "server.draw(40, 50); showing().length",
        ]
    )
    assert first == ["node", True, "cx7"] and second == ["node", True, None], (first, second)
    assert void is None, void  # what this check stands on: no machine at that place
    assert away == ["ring", None] and left == 0, (away, left)


@needs_node
def test_a_click_on_another_spark_of_the_ring_opens_that_one():
    """While one Spark stands open, the others stay where they are on the ring, dimmed. A click on one of them
    opens it instead."""
    other, after = scene([opened(NARROW) + "; Scene.pick(30, 480)", "click(30, 480); [V, VN, VP]"])
    assert other not in (None, "dgx1"), other  # what this check stands on: another Spark at that place
    assert after == ["node", other, None], after


def near(a, b, by=0.5):
    """Whether two places of the page agree, to `by` pixels."""
    return abs(a[0] - b[0]) <= by and abs(a[1] - b[1]) <= by


DOTS = "Object.fromEntries(showing().map(l => [l.part, l.dot]))"  # the dot of every part whose label shows
# The fan is pointed at: the part under the pointer keeps its label at any zoom, so a check can follow it.
WATCH = "Scene.hover('fan_left'); server.draw(10, 50)"
DRAG = (  # the machine is dragged a little to the right and up
    "hole.fire('pointerdown', { clientX: 250, clientY: 300, pointerId: 1, button: 0, buttons: 1 });"
    " hole.fire('pointermove', { clientX: 310, clientY: 280, buttons: 1 }); hole.fire('pointerup', { button: 0 })"
)
MIDDLE = [18 + 176 + (370 - 176) / 2, 60 + 440 / 2]  # of the narrow hole beside its labels: where a part is shown


SSD = "labels().find(l => l.part === 'ssd_m2')"  # the label of the part that lies under the board
TILT = (  # the machine is dragged upright, or back down again
    "(by => { hole.fire('pointerdown', { clientX: 250, clientY: 300, pointerId: 1, button: 0, buttons: 1 });"
    " hole.fire('pointermove', { clientX: 250, clientY: 300 + by, buttons: 1 }); hole.fire('pointerup', { button: 0 }); })"
)


@needs_node
def test_a_label_fades_out_when_its_part_gets_hidden_and_fades_in_when_it_shows_again():
    """Labels came and went from one frame to the next whenever a part passed behind another while the machine was
    turned. A label now fades: one frame after its part shows, the label is there but faint; a quarter of a second
    later it is whole. One frame after its part is hidden again it still stands, fainter, and then it is gone. With
    motion unwanted it comes and goes at once, as it did."""
    comes, whole, goes, gone, still = scene(
        [
            opened(NARROW) + f"; {TILT}(-60); server.draw(1, 16.7); {SSD}",
            f"server.draw(30, 50); {SSD}",
            f"{TILT}(60); server.draw(1, 16.7); {SSD}",
            f"server.draw(40, 50); {SSD}",
            f"calm.matches = true; {TILT}(-60); server.draw(1, 16.7); (shown => {{ {TILT}(60); server.draw(1, 16.7);"
            f" return [shown, {SSD}]; }})({SSD})",
        ]
    )
    assert comes["shown"] and 0.05 < comes["alpha"] < 0.5, comes
    assert whole["shown"] and whole["alpha"] > 0.98, whole
    assert goes["shown"] and 0.5 < goes["alpha"] < 0.98 and near(goes["dot"], whole["dot"], 60), (whole, goes)
    assert not gone["shown"] and gone["alpha"] < 0.05, gone
    assert still[0]["shown"] and still[0]["alpha"] == 1 and not still[1]["shown"], still


@needs_node
def test_a_label_that_was_gone_comes_anew_beside_its_part_and_none_flashes_when_a_spark_opens_again():
    """A label that fades out is gone for good: when its part shows again, the label stands at its height beside
    the part from the first frame, however the page changed meanwhile, and does not slide there from where it last
    stood. And a Spark that is closed and opened again shows no label of a part that is hidden as it opens: the
    label of the SSD stood whole when the Spark closed, and no frame of the next opening shows it."""
    first, moved, flash = scene(
        [
            opened(NARROW) + f"; {TILT}(-60); server.draw(40, 50); {TILT}(60); server.draw(40, 50); {SSD}.y",
            "server.place('#hole', { left: 18, top: 150, width: 370, height: 440 }); server.draw(20, 50);"
            f" {TILT}(-60); server.draw(1, 16.7); (comes => {{ server.draw(40, 50); return [comes, {SSD}.y]; }})({SSD}.y)",
            f"setView('ring'); server.draw(60, 50); setView('node', S.nodes[1].name);"
            f" (() => {{ let shown = 0; for (let i = 0; i < 100; i++) {{ server.draw(1, 50); if ({SSD}.shown) shown++; }}"
            f" return [shown, Scene.opened(), showing().length]; }})()",
        ]
    )
    assert abs(moved[0] - moved[1]) < 0.2 and abs(moved[1] - first) > 30, (first, moved)
    assert flash == [0, True, 3], flash


@needs_node
def test_zoomed_in_only_the_picked_part_and_the_part_under_the_pointer_keep_their_labels():
    """Up to a zoom of 1.25 every label stands as at home. Further in they fade, and from a zoom of two on they are
    gone: all but the label of the part under the pointer and of the picked part, which stay whole. Back at home all
    of them return. A part that is moved out of the hole loses its label even while it is pointed at: no label
    points at what cannot be seen."""
    near_home, half, two, pointed, picked, back, outside = scene(
        [
            opened(NARROW) + "; Scene.zoom(1.25, 330, 290); server.draw(60, 50); showing().map(l => [l.part, l.alpha])",
            "Scene.zoom(1.3, 330, 290); server.draw(60, 50); showing().map(l => l.alpha)",
            "Scene.zoom(2 / 1.625, 330, 290); server.draw(60, 50); showing().map(l => l.part)",
            "Scene.hover('fan_left'); server.draw(40, 50); showing().map(l => [l.part, l.alpha])",
            "click(...dot('fan_left')); Scene.hover('cx7'); server.draw(60, 50); showing().map(l => [l.part, l.alpha]).sort()",
            "click(...dot('fan_left')); Scene.hover(null); Scene.home(); server.draw(60, 50); showing().map(l => [l.part, l.alpha]).sort()",
            "Scene.zoom(3, ...dot('fan_left')); Scene.hover('fan_left'); server.draw(60, 50);"
            " (was => { Scene.move(400, 0); server.draw(60, 50); return [was, showing().map(l => l.part).includes('fan_left')]; })"
            "(showing().map(l => l.part).includes('fan_left'))",
        ]
    )
    everyone = [["cx7", 1], ["fan_left", 1], ["gb10_die_gpu", 1]]
    assert sorted(near_home) == everyone, near_home
    assert len(half) == 3 and all(0.4 < alpha < 0.6 for alpha in half), half
    assert two == [] and pointed == [["fan_left", 1]], (two, pointed)
    assert picked == [["cx7", 1], ["fan_left", 1]] and back == everyone, (picked, back)
    assert outside == [True, False], outside


@needs_node
def test_a_label_glides_to_its_new_height_when_the_machine_is_turned():
    """Turning the machine moves the parts, and the labels follow them up and down the edge of the hole. A label
    glides to its new height over a few frames; with motion unwanted it stands there on the next frame."""
    fan = "labels().find(l => l.part === 'fan_left').y"
    before, one, rest, still = scene(
        [
            opened(NARROW) + f"; {fan}",
            f"{TILT}(-60); server.draw(1, 16.7); {fan}",
            f"server.draw(40, 50); {fan}",
            f"calm.matches = true; {TILT}(60); server.draw(1, 16.7); {fan}",
        ]
    )
    assert abs(rest - before) > 5 and min(before, rest) < one < max(before, rest), (before, one, rest)
    assert abs(one - before) < abs(rest - before) * 0.3 and abs(still - before) < 0.2, (before, one, rest, still)


CABLES = """
const ring = { ring: true, nodes: [0, 1, 2, 3].map(i => ({ name: 'dgx' + i, rank: i, head: i === 0 })) };
const edge = (from, to, group) => ({ from, to, group, gbps: 2.1, rx: 2.1, up: true, capacity: 200, errors: false });
const wired = [[0, 1, 'f0'], [0, 3, 'f1'], [1, 2, 'f0'], [1, 0, 'f1'], [2, 3, 'f0'], [2, 1, 'f1'], [3, 0, 'f0'], [3, 2, 'f1']].map(e => edge(...e));
const cross = [...wired, edge(0, 2, 'f2'), edge(2, 0, 'f2')];
const keys = pairs => pairs.flatMap(([a, b]) => [a + '>' + b, b + '>' + a]);
"""


@needs_node
def test_the_lanes_join_the_sparks_their_cables_join_and_a_ring_of_four_keeps_its_lanes():
    """The pairs of Sparks the scene draws a lane between come from the cables of the moment. In a ring of four
    they are the lanes the page drew before, by the order of the ring: each Spark to the next, the same keys in the same
    order, also while only some cables were read or none. A cable across the ring (0 to 2) gets a lane of its own,
    drawn as a chord; one Spark alone gets none, nor do four on a switch, where every lane runs to the switch. A ring
    of two cabled twice is one pair. A pair on a cable that has no lane yet is one the page lacks."""
    got = page_rules(
        CABLES + "const before = [0, 1, 2, 3].flatMap(i => [i + '>' + (i + 1) % 4, (i + 1) % 4 + '>' + i]);"
        " return { wired: lanePairs(ring, wired), early: lanePairs(ring, wired.slice(0, 3)), none: lanePairs(ring, []),"
        " keys: keys(lanePairs(ring, wired)), before, cross: lanePairs(ring, cross),"
        " one: lanePairs({ ring: false, nodes: ring.nodes.slice(0, 1) }, [{ from: 0, to: null, group: 'f0' }]),"
        " two: lanePairs({ ring: true, nodes: ring.nodes.slice(0, 2) }, [edge(0, 1, 'f0'), edge(0, 1, 'f1'), edge(1, 0, 'f0')]),"
        " hub: lanePairs({ ring: false, nodes: ring.nodes }, ring.nodes.map(n => ({ from: n.rank, to: null, group: 'f0' }))),"
        " lack: [lanesLack(lanePairs(ring, []), lanePairs(ring, wired)), lanesLack(lanePairs(ring, []), lanePairs(ring, cross)),"
        " lanesLack(lanePairs(ring, cross), lanePairs(ring, cross))] };"
    )
    order = [[i, (i + 1) % 4, False] for i in range(4)]
    assert got["wired"] == got["early"] == got["none"] == order and got["keys"] == got["before"], got
    assert got["cross"] == [*order, [0, 2, True]], got["cross"]
    assert got["one"] == [] and got["hub"] == [] and got["two"] == [[0, 1, False]], got
    assert got["lack"] == [False, True, False], got["lack"]


SAY = "(change => { const m = structuredClone(LIVE); change(m); server.say(m); return globalThis.reloads || 0; })"
CHORD = "m => m.edges.push({ from: 0, to: 2, group: 'f2', gbps: 1, rx: 1, up: true, capacity: 200, errors: false })"


def with_chord(states):
    """The moments of the demo with a cable across the ring, from the first Spark to the third and back."""
    for key in ("first", "next"):
        for a, b in ((0, 2), (2, 0)):
            states[key]["edges"].append({"from": a, "to": b, "group": "f2", "gbps": 1, "rx": 1, "up": True})


@needs_node
def test_a_new_pair_on_a_cable_or_another_head_starts_the_page_anew_and_nothing_else_does():
    """The page draws the lanes once, from its first moment. A moment whose cables join a pair that has no lane
    (the cable across came later) starts the page anew, as another cluster does; so does a moment with another head,
    so the sign "head" and every view follow a head that was found or moved. The same moment again does not, nor
    one whose readings alone changed, and a page that drew the cable across from the start does not start anew for
    it. Each of the two is checked on a page of its own: a reload is only counted here, so a page goes on with the
    lanes it drew, and a later step would carry the cable across of the one before."""
    counted = "location.reload = () => { globalThis.reloads = (globalThis.reloads || 0) + 1; }; null"
    readings = "m => { m.edges[0].gbps = 9.5; m.edges[1].rx = 0.5; m.nodes[2].temp = 71; }"
    counts = scene([counted, f"{SAY}(m => null)", f"{SAY}({readings})", f"{SAY}({CHORD})"])
    assert counts[1:] == [0, 0, 1], counts
    head = scene([counted, f"{SAY}(m => {{ m.cluster.nodes[0].head = false; m.cluster.nodes[1].head = true; }})"])
    assert head[1:] == [1], head
    again = scene(["location.reload = () => { globalThis.reloads = 1; }; null", f"{SAY}({CHORD})"], change=with_chord)
    assert again[1:] == [0], again


@needs_node
def test_a_spark_of_another_maker_stands_as_a_plain_box_that_does_not_open():
    """The 3D model is the DGX Spark, board P4242. A Spark that read another board (demo-gb10, the second of the ring
    of three) is drawn as a plain box: asked to open it stays shut, and Scene.opened() says no. The others, whose
    board was not read, are the model as ever and open. Which board counts as another is a plain rule."""
    three = page_moments(demo_map("ring3"), "ring3")
    look = "server.draw(100, 50); [VN, Scene.opened(), foreignBoard(S.nodes.find(n => n.name === VN))]"
    got = scene(
        [f"server.place('#hole', {NARROW}); null", *(f"setView('node', S.nodes[{i}].name); {look}" for i in (1, 0, 2))],
        change=lambda states: states.update(three),
    )
    assert got[1:] == [["spark-1", False, True], ["spark-0", True, False], ["spark-2", True, False]], got
    rule = page_rules(
        "return [{ firmware: { board: 'P4242' } }, { firmware: { board: 'demo-gb10' } }, { firmware: { board: '' } },"
        " { firmware: null }, {}, { firmware: { board: 7 } }].map(foreignBoard);"
    )
    assert rule == [False, True, False, False, False, False], rule
    # and what is drawn: the program of the model (the one with its textures) draws every Spark where none read
    # another board, and with one that did, all but that one, which another program draws as the box
    steps = [f"server.place('#hole', {NARROW}); null", "setView('ring'); server.draw(60, 50); null", DRAWN]
    box = scene(steps, change=lambda states: states.update(three))[2]
    plain = scene(steps, change=without_boards(three))[2]
    gone = sorted(set(plain["model"]) - set(box["model"]))
    assert len(gone) == 1 and gone[0] in box["other"], (box, plain)


# Notes, over a few frames, where every program of the scene sets a position (the first three floats it is given),
# by x and z: those of the program of the model, the one that binds its four textures, and those of every other.
DRAWN = """(() => { const gl = document.querySelector('canvas').getContext('webgl2'); let cur = null; const model = new Set(), at = [];
  gl.useProgram = p => { cur = p; };
  gl.uniform1i = (loc, unit) => { if (unit === 3) model.add(cur); };
  gl.uniform3f = (loc, x, y, z) => { at.push([cur, x, z]); };
  server.draw(4, 50);
  const key = ([, x, z]) => [x, z].map(v => Math.round(v * 1000)).join(',');
  return { model: [...new Set(at.filter(a => model.has(a[0])).map(key))], other: [...new Set(at.filter(a => !model.has(a[0])).map(key))] };
})()"""


RING_MOMENT = """
const counts = { rocep1s0f0: {}, rocep1s0f1: {}, roceP2p1s0f0: {}, roceP2p1s0f1: {} };
const spark = i => ({ name: 'dgx' + i, rank: i, head: i === 0, live: true, capacity: Array(20).fill(718), fans: [3194, 3284],
  firmware: { board: 'P4242' }, link_counts: counts, apps: [{ gb: 88.2, name: 'VLLM::Worker_TP' + i }] });
const nodes = [0, 1, 2, 3].map(spark);
const edge = (from, to, group) => ({ from, to, group, gbps: 2.1, rx: 2.1, up: true, capacity: 200, errors: false });
const edges = [[0, 1, 'f0'], [0, 3, 'f1'], [1, 2, 'f0'], [1, 0, 'f1'], [2, 3, 'f0'], [2, 1, 'f1'], [3, 0, 'f0'], [3, 2, 'f1']].map(e => edge(...e));
const moment = (sparks, ring = true) => ({ cluster: { ring, nodes: sparks.map(({ name, rank, head }) => ({ name, rank, head })) }, nodes: sparks });
"""
# what the deep view said before, word for word: the hints that name how a Spark is built
BEFORE = {
    "cores": "All 20 cores together.",
    "fans": "Mean of the two fans.",
    "full": "Fuller direction against 200 Gb/s",
    "rate": 200,
    "counters": "All counters of the RDMA layer, per Spark, summed over its four PCIe functions. Most stay at zero on a "
    "healthy ring.",
}


@needs_node
def test_in_a_ring_of_four_the_page_says_what_it_said_and_another_cluster_is_an_untested_setup():
    """A moment of a ring of four (readings of a real ring, the names of the test map) gives the hints of the
    deep view word for word as before, and is no untested setup. Not four Sparks, not a ring,
    or a machine of another maker is one; a ring of four whose boards were not read is not. Where the Sparks read
    different counts, a hint drops its figure; a line rate nobody agrees on is none. And six Sparks in a chart get six
    lines that all differ, the first four solid as ever."""
    got = page_rules(
        RING_MOMENT + " const odd = nodes.map((n, i) => i ? n : { ...n, capacity: Array(16).fill(1), fans: [1, 2, 3],"
        " link_counts: { a: {}, b: {} } }), unread = nodes.map(n => ({ ...n, firmware: null }));"
        " return { four: deepWords(nodes, edges), odd: deepWords(odd, [...edges, { ...edges[0], capacity: 100 }]),"
        " two: deepWords(nodes.map(n => ({ ...n, link_counts: { a: {}, b: {} } })), []).counters,"
        " none: deepWords([], []), untested: [moment(nodes), moment(unread), moment(nodes.slice(0, 3)),"
        " moment([...nodes, spark(4), spark(5)]), moment(nodes, false), moment(nodes.map((n, i) => i === 2 ?"
        " { ...n, firmware: { board: 'demo-gb10' } } : n))].map(untestedSetup),"
        " lines: Array.from({ length: 16 }, (_, i) => [i % 4, ...lineKind(i)]) };"
    )
    assert got["four"] == BEFORE, got["four"]
    assert got["odd"] == {
        "cores": "All cores together.",
        "fans": "Mean of the fans.",
        "full": "Fuller direction",
        "rate": None,
        "counters": "All counters of the RDMA layer, per Spark, summed over its PCIe functions. Most stay at zero on "
        "a healthy ring.",
    }, got["odd"]
    assert "summed over its two PCIe functions." in got["two"] and got["none"]["cores"] == "All cores together."
    assert got["untested"] == [False, False, True, True, True, True], got["untested"]
    lines = [tuple(line) for line in got["lines"]]
    assert len(set(lines)) == 16 and all(line[1:] == ("", "") for line in lines[:4]), lines


IDENTITY = (  # the identity of a ring of four on the moment that came last, and the line the page writes of it
    "(m => { m.identity = { ...m.identity, model: 'deepseek-v4.1-flash', image: 'spark-ds41f:demo',"
    " container: 'running', context: 1048576 }; renderIdentity(m); return document.querySelector('#identity')"
    ".textContent; })(structuredClone(LIVE))"
)
HINTS = r"server.texts().filter(t => /cores together|fans\.|PCIe functions/.test(t))"


@needs_node
def test_the_identity_line_and_the_deep_view_say_of_a_ring_of_four_what_they_said_and_of_others_that_they_are_untested():
    """The line under the speed says of a ring of four what it said before, with real names and with neutral ones; the
    deep view of the demo the hints it gave. Six Sparks in a ring end that line on "untested setup", and one Spark
    alone is "1 Spark", untested as well."""
    four = "deepseek-v4.1-flash on spark-ds41f:demo. 4 Sparks in a ring, 1M context."
    real = sheet([IDENTITY, "Nerd.toggle(true); null", f"Nerd.tab('nodes'); {HINTS}"])
    assert real == [
        four,
        None,
        ["All 20 cores together. Click to plot it over time.", "Mean of the two fans. Click to plot it over time."],
    ], real
    assert sheet([IDENTITY], search="?names=neutral") == [four]
    for form, said in (("ring6", "6 Sparks in a ring, untested setup."), ("one", "1 Spark, untested setup.")):
        shown = page_moments(demo_map(form), form)
        got = scene(["document.querySelector('#identity').textContent"], change=lambda s, shown=shown: s.update(shown))
        assert got == ["Waiting for the engine. " + said], (form, got)


@needs_node
def test_every_cable_counts_against_the_line_rate_of_its_own_link_and_only_an_unread_rate_gives_no_share():
    """The share of the fuller direction in the deep view: one link that read another line rate took it away from
    every cable, as the rates no longer agreed. Each cable is counted against the rate its own link
    reads: in a ring of four every cable against 200 Gb/s, as before; with one link at 100 Gb/s
    that one against 100 and the seven others as before; a link whose rate was not read has no share, also where
    the seven others read theirs."""
    got = page_rules(
        RING_MOMENT + " const slow = edges.map((e, k) => k === 3 ? { ...e, capacity: 100 } : e),"
        " cable = { gb_tx: 2.15, gb_rx: 2.1 }, shares = list => list.map(e => fullShare(cable, cableRate(list, e.from, e.group)));"
        " return [shares(edges), shares(slow), shares(edges.map(e => ({ ...e, capacity: null }))),"
        " fullShare({ gb_tx: null, gb_rx: 2 }, 200), cableRate(edges, 7, 'f0'),"
        " shares(edges.map((e, k) => k === 5 ? { ...e, capacity: null } : e))];"
    )
    four, slow, unread, untold, nobody, one = got
    share = max(2.15, 2.1) / 200 * 100
    assert four == [share] * 8 and slow == [share] * 3 + [2.15] + [share] * 4, (four, slow)
    assert unread == [None] * 8 and untold is None and nobody is None, (unread, untold, nobody)
    assert one == [share] * 5 + [None] + [share] * 2, one  # one unread among seven read: that one alone has none


@needs_node
def test_the_column_full_of_the_deep_view_counts_every_cable_against_the_line_rate_of_its_own_link():
    """The check above holds the rule of the share; this one the column "Full" of the Links tab that writes it. With
    one link at 100 Gb/s its cable is twice as full as the seven others, and a cable whose link read no rate says
    a dash."""
    rates = (
        "server.say({ ...LIVE, t: LIVE.t + 2, edges: LIVE.edges.map(e => e.from === 0 && e.group === 'f1'"
        " ? { ...e, capacity: 100 } : e.from === 1 && e.group === 'f0' ? { ...e, capacity: null } : e) }); null"
    )
    full = "(all => all.flatMap((e, i) => e.text.includes('→') ? [[e.text, all[i + 3].text]] : []))(document.querySelector('#n-pane').under())"
    got = sheet([rates, "Nerd.tab('links'); Nerd.toggle(true); null", full])[2]
    share = "46.7 %"  # 93.43 Gb/s each way against 200
    assert dict(got) == {
        "dgx0 → dgx1": share,
        "dgx0 → dgx3": "93.4 %",
        "dgx1 → dgx2": "–",
        "dgx1 → dgx0": share,
        "dgx2 → dgx3": share,
        "dgx2 → dgx1": share,
        "dgx3 → dgx0": share,
        "dgx3 → dgx2": share,
    }, got


def without_boards(three):
    """The moments of a ring of three as after a start of ringtop: no Spark has read its board yet."""

    def change(states):
        states.update(three)
        for key in ("first", "next"):
            for node in states[key]["nodes"]:
                (node.get("firmware") or {}).pop("board", None)

    return change


@needs_node
def test_a_spark_whose_other_board_comes_while_it_stands_open_closes_and_stays_a_box():
    """A Spark opened as the model before its board came (the board comes with the readings of every
    minute, so not in the first minute after a start) became a box, but its opening froze: Scene.opened() stayed
    true, also after the ring and back, with labels of a DGX Spark at a box. The board that makes it a box now closes
    it as well, and it stays shut: after the ring and back the program of the model does not draw it, another
    program draws it as the box."""
    three = page_moments(demo_map("ring3"), "ring3")
    board = "m => { m.nodes[1].firmware = { ...(m.nodes[1].firmware || {}), board: 'demo-gb10' }; }"
    got = scene(
        [
            f"server.place('#hole', {NARROW}); setView('node', S.nodes[1].name); server.draw(100, 50); Scene.opened()",
            f"{SAY}({board}); server.draw(60, 50); [Scene.opened(), foreignBoard(S.nodes[1]), globalThis.reloads || 0]",
            "setView('ring'); server.draw(60, 50); setView('node', S.nodes[1].name); server.draw(100, 50); Scene.opened()",
            DRAWN,
        ],
        change=without_boards(three),
    )
    assert got[:3] == [True, [False, True, 0], False], got[:3]
    ring = [f"server.place('#hole', {NARROW}); null", "setView('ring'); server.draw(60, 50); null", DRAWN]
    plain = scene(ring, change=without_boards(three))[2]
    gone = sorted(set(plain["model"]) - set(got[3]["model"]))
    assert len(gone) == 1 and gone[0] in got[3]["other"], (got[3], plain)
