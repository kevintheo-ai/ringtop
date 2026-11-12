"""The page as a text: nothing from the data runs as markup, and its script parses."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ringtop_parts.connect.server import MODEL, PAGE, PAGE_PARTS
from tests.fixtures import needs_node, page_moments, page_scripts, page_text


def test_page_runs_nothing_from_the_data_as_markup():
    page = page_text()
    assert "start();" in page and "const Scene" in page, "the page lost its scripts"  # no check of an empty shell
    assert (
        ".innerHTML" not in page
        and "insertAdjacentHTML" not in page
        and "http://" not in page.replace("http://www.w3.org", "")
    )


def page_tags():
    """The scripts the page names, in the order it runs them."""
    return re.findall(r'<script src="page/([^"]+)"></script>', PAGE.read_text())


def test_page_script_parses():
    """One syntax error and the page sits on "Connecting" forever. All scripts joined have to parse as well: they
    share one world, and a name two of them declare would stop the second one in the browser, where no check looks."""
    if not shutil.which("node"):
        return
    with tempfile.TemporaryDirectory() as folder:
        scripts = page_scripts(folder)
        assert scripts, "the page lost its scripts"
        joined = Path(folder) / "joined.js"
        joined.write_text("\n".join(Path(script).read_text() for script in scripts))
        for script in [*scripts, str(joined)]:
            done = subprocess.run(["node", "--check", script], capture_output=True, text=True)
            assert done.returncode == 0, done.stderr[:400]


def test_the_page_runs_its_scripts_from_files_in_the_order_of_the_table():
    """Neither a script nor a style stands in the page itself: each is a file the server sends from its table, and the
    page runs its scripts in the order of that table, one after the other."""
    page = PAGE.read_text()
    there = [address.removeprefix("/page/") for address, (file, _) in PAGE_PARTS.items() if file.is_file()]
    assert page_tags() == [name for name in there if name.endswith(".js")], page_tags()
    assert len(page_tags()) >= 14, page_tags()
    assert page.count("<script") == len(page_tags())  # none inline, none with async, defer or a type of its own
    assert "<style" not in page and page.count('<link rel="stylesheet" href="page/style.css">') == 1


def test_every_script_of_the_page_says_what_it_is_and_runs_strict():
    """A script without 'use strict' would turn a misspelt name into a global instead of failing."""
    assert page_tags(), "the page names no script"
    for name in page_tags():
        rows = (PAGE.parent / name).read_text().split("\n")
        assert rows[0].startswith("// ") and rows[0].endswith("."), (name, rows[0])  # one sentence: what it does
        assert rows[1] == "'use strict';", (name, rows[1])


def test_no_function_is_declared_by_two_scripts_of_the_page():
    """Two scripts that declare one function do not fail anywhere: the second silently replaces the first."""
    assert page_tags(), "the page names no script"
    seen = {}
    for name in page_tags():
        for found in re.findall(r"^(?:async )?function\s+([A-Za-z_$][\w$]*)", (PAGE.parent / name).read_text(), re.M):
            assert found not in seen, f"{found} is declared in {seen[found]} and in {name}"
            seen[found] = name


@needs_node
def test_the_page_loads_starts_and_draws_without_a_browser():
    """Every script of the page runs in node, one after the other in one shared world, against a document that keeps
    what it is given and a WebGL that accepts everything. The page starts, gets a moment of the ring engine and one
    of single tracks, opens every view, every deep tab, the tour and the time machine, and draws its frames.
    Once with WebGL (the scene is built) and once without (the page stands without it). No error may fall: a name
    that one script expects from another and does not find shows here, long before a browser is opened.
    And three times the scene breaks while it builds itself, early (a shader program), in the middle (a buffer) and
    at its very end (a listener of the canvas): each time the page says why once, and stands without the scene."""
    broken = ("fail:createProgram", "fail:createVertexArray", "fail:webglcontextlost")
    with tempfile.TemporaryDirectory() as folder:
        moments = Path(folder) / "moments.json"
        moments.write_text(json.dumps(page_moments(), default=sorted))
        for mode in ("gl", "nogl", *broken):
            done = subprocess.run(
                ["node", str(Path(__file__).with_name("page_loader.js")), mode, str(moments), *page_scripts(folder)],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "RINGTOP_MODEL": str(MODEL)},  # with the model where there is one
            )
            assert done.returncode == 0 and done.stdout, done.stderr[-600:]
            seen = json.loads(done.stdout)
            if mode in broken:  # the one word the scene leaves when it gives up, and nothing after it
                assert len(seen["errors"]) == 1 and seen["errors"][0].startswith("console.error: "), (
                    mode,
                    seen["errors"][:4],
                )
                assert f"{mode[5:]} failed" in seen["errors"].pop(), mode
            assert seen["errors"] == [], (mode, seen["errors"][:4])
            assert set(seen["names"].values()) == {"object"}, (mode, seen["names"])  # Scene, Nerd, Tour, Time, S, LIVE
            assert seen["ok"] is (mode == "gl"), (mode, seen["ok"])  # the scene itself, or what stands in for it
            assert seen["started"] and seen["said"] == "Live", (mode, seen)
            assert len(seen["views"]) == 16 and seen["drawn"] >= 30, (mode, seen["views"], seen["drawn"])
            # a Spark up close is its sheet: head, bar, the room the bar keeps for its strip, the stack, events, five
            # groups and the table beside the others
            assert seen["sheet"] == {"parts": 11, "shown": True, "panel": False}, (mode, seen["sheet"])
            assert seen["nerdLive"] > 0, (
                mode
            )  # nerd mode opens on its live side and paints it, before any tab is picked
            assert {"api/state", "api/nerd", "api/history", "api/replies"} <= set(seen["asked"]), seen["asked"]


def neutral_walk(link: str = "") -> dict:
    """Loads the page with an address that asks for neutral names, walks it through every view and gives back what
    the loader saw. `link`: what stands behind the address, as in a link somebody kept."""
    with tempfile.TemporaryDirectory() as folder:
        moments = Path(folder) / "moments.json"
        moments.write_text(json.dumps({**page_moments(), "hash": link}, default=sorted))
        text = moments.read_text()  # the moments hold what must not show: other names than the neutral ones, programs
        assert all(word in text for word in ('"name": "dgx0"', "sglang::scheduler", "VLLM::", "solo-", "dockerd"))
        # and what the run source of the demo names: a queue, who holds the ring, steps, the job of a track
        assert all(word in text for word in ("Release suite", "Demo window", "Quality gate", "Demo queue", "Forms"))
        done = subprocess.run(
            ["node", str(Path(__file__).with_name("page_loader.js")), "neutral", str(moments), *page_scripts(folder)],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "RINGTOP_MODEL": str(MODEL)},
        )
    assert done.returncode == 0 and done.stdout, done.stderr[-600:]
    seen = json.loads(done.stdout)
    assert seen["errors"] == [], seen["errors"][:4]
    assert seen["started"] and seen["said"] == "Live" and seen["ok"] is True, seen
    return seen


@needs_node
def test_with_neutral_names_a_link_that_names_a_spark_as_it_is_called_does_not_keep_that_name_in_the_address():
    """A link somebody kept says `#node=dgx2`. With neutral names it opens that Spark under its neutral name, as it
    did; but the address went on showing the real one for as long as the page stayed open. It is gone from the
    address before the page has its first moment (which may take long, or never come), and back under the neutral
    name once the page knows the cluster."""
    seen = neutral_walk("#node=dgx2")
    assert seen["real"] == [], seen["real"]
    assert seen["hashAtFirst"] == "" and seen["hash"] == "#node=spark-3", (seen["hashAtFirst"], seen["hash"])


@needs_node
def test_with_neutral_names_another_cluster_of_the_same_shape_starts_the_page_anew():
    """ringtop comes back on another cluster with as many Sparks in the same order. Under neutral names the two look
    alike, and the page took the new moments for the old cluster: the curves of the last half hour went on with the
    readings of other machines. The page tells a cluster by the names the server sends and starts anew, as it does
    without neutral names; a moment of the same cluster does not start it anew."""
    seen = neutral_walk()
    assert seen["reloaded"] == {"same": False, "other": True}, seen["reloaded"]


@needs_node
def test_with_neutral_names_no_element_of_the_page_holds_a_real_name():
    """The same walk through every view as above, with an address that asks for neutral names and Sparks called dgx0
    to dgx3. It stops too where a view shows more only on demand: the box that explains the cooling view and its
    figures, in both forms of that view, and a part of the open Spark with its panel, the labels and the way back
    of the lens. Afterwards no text, title, value or attribute of any element holds one of those names, nor the address
    of the page; and none holds a word the outside wrote: the name of a program or a container, the kernel, the
    profile, or a name its run source gave a run, a queue, a step or a job. Nerd mode stays shut, since it shows logs and settings as they are, and the server is never asked for
    it. And the history is asked under the real names, the ones the server keeps."""
    seen = neutral_walk()
    assert seen["real"] == [], seen["real"]
    assert "cooling wide" in seen["views"], seen["views"]  # the cooling view in both its forms
    # in each of them the box that explains the view stood open, with the four figures of every curve asked for
    stood = {"box": 8, "open": True, "figures": True}
    assert seen["cooling"] == {"cooling": stood, "cooling wide": stood}, seen["cooling"]
    assert seen["sheet"] == {"parts": 11, "shown": True, "panel": False}, seen["sheet"]
    # and a part of the open Spark was picked: its panel names the Sparks at the other ends of its two links, the
    # labels stand beside the parts, and the lens offers its way back
    assert seen["part"] == {"panel": True, "links": 2, "labels": 10, "home": True}, seen["part"]
    # the sheet of a Spark with all it says on demand: the box of its bar stood open and a cursor on its first curve
    assert "node box" in seen["views"] and seen["box"]["headings"] > 8 and " Jan, " in seen["box"]["word"], seen["box"]
    assert seen["nerdLive"] == 0 and not {"api/nerd", "api/replies"} & set(seen["asked"]), (
        seen["nerdLive"],
        seen["asked"],
    )
    asked = seen["history"]["asked"]
    assert asked > 0 and seen["history"] == {"asked": asked, "real": asked, "neutral": 0}, seen["history"]


def test_what_a_part_takes_from_the_record_was_put_there_before():
    """The scene and nerd mode are each several files that share one record. A part takes the names of earlier parts
    out of it in one line and hands its own on in another. A name taken that nobody put there is undefined without a
    word, and shows only when the line that uses it runs: a resize, a lost context. So every name a part takes has to
    be handed on by the file that builds the whole or by a part it calls earlier."""
    texts = {name: (PAGE.parent / name).read_text() for name in page_tags()}

    def names(listed):
        return {name.strip() for name in listed.split(",") if name.strip()}

    parts = {}  # the function of a part: its file and its text
    for file, text in texts.items():
        found = re.search(r"^function (\w+)\(shared\) \{  // seam$", text, re.M)
        if found:
            parts[found.group(1)] = (file, text)
    wholes = 0
    for name, text in texts.items():
        start = re.search(r"^  const shared = \{(.*)\};  // seam$", text, re.M)
        if not start:
            continue
        wholes += 1
        there = names(start.group(1))
        calls = re.findall(r"^  (?:return )?(\w+)\(shared\);  // seam$", text, re.M)
        assert calls and set(calls) <= set(parts), (name, calls)
        for call in calls:
            for taken in re.findall(r"^  const \{ (.*) \} = shared;  // seam$", parts[call][1], re.M):
                assert names(taken) <= there, (call, sorted(names(taken) - there))
            for given in re.findall(r"^  Object\.assign\(shared, \{ (.*) \}\);  // seam$", parts[call][1], re.M):
                there |= names(given)
        own = sorted(fn for fn, (file, _) in parts.items() if file.startswith(name.removesuffix(".js") + "-"))
        assert sorted(calls) == own, (name, calls, own)  # every part of it is called, once: scene.js calls scene-*.js
    assert wholes == 2, wholes  # the scene and nerd mode


# what the scripts of the page may expect of the browser: every other name has to be declared by one of them
BROWSER = set(
    [
        "Array",
        "Blob",
        "Boolean",
        "CSS",
        "DataView",
        "Date",
        "Error",
        "EventSource",
        "Float32Array",
        "Infinity",
        "JSON",
        "Map",
        "Math",
        "Number",
        "Object",
        "Promise",
        "RegExp",
        "ResizeObserver",
        "Set",
        "String",
        "TextDecoder",
        "URL",
        "Uint16Array",
        "Uint32Array",
        "Uint8Array",
        "addEventListener",
        "clearInterval",
        "clearTimeout",
        "console",
        "createImageBitmap",
        "document",
        "encodeURIComponent",
        "fetch",
        "history",
        "innerHeight",
        "innerWidth",
        "location",
        "matchMedia",
        "performance",
        "requestAnimationFrame",
        "setInterval",
        "setTimeout",
        "undefined",
        "window",
    ]
)


@needs_node
def test_the_scripts_of_the_page_name_nothing_that_nobody_declares():
    """A script that uses a name no script declares fails only when that line runs, and many lines run only on a
    resize, a hover or a slow frame, where no check looks. So the scripts are parsed as the one program they are in
    the browser, and every name they leave undeclared has to be one the browser gives."""
    done = subprocess.run(
        [
            "node",
            "--expose-internals",  # the parser node ships
            str(Path(__file__).with_name("page_names.js")),
            *[str(PAGE.parent / name) for name in page_tags()],
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0 and done.stdout, done.stderr[-600:]
    names = set(json.loads(done.stdout))
    assert names and names <= BROWSER, sorted(names - BROWSER)


@needs_node
def test_every_function_of_the_page_says_what_it_is_for():
    """One sentence per function a reader meets first: at the top of a script and at the top of every block that
    stands for a module (a part of the scene or of nerd mode, the tour, the time machine). A comment on its head
    line or alone on the line above counts; the marker of a seam does not."""
    done = subprocess.run(
        [
            "node",
            "--expose-internals",  # the parser node ships
            str(Path(__file__).with_name("page_sentences.js")),
            *[str(PAGE.parent / name) for name in page_tags()],
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0 and done.stdout, done.stderr[-600:]
    named = json.loads(done.stdout)["named"]
    silent = [f"{f['file']}:{f['line']} {f['name']}" for f in named if not f["said"]]
    assert len(named) > 250 and not silent, (len(silent), silent[:12])


def test_the_ink_and_the_measures_of_a_curve_belong_to_a_class_any_surface_can_carry():
    """A plot takes its ink, its hairlines and the widths of its row from names of the style sheet. They were set on
    the sheet of a Spark alone: a plot in any other place of the page drew no line at all. They belong to the class
    `record`, set there and nowhere else, and the sheet carries it; a surface that shows curves carries it too."""
    style, page = (PAGE.parent / "style.css").read_text(), PAGE.read_text()
    rule = re.search(r"^\.record\{([^}]*)\}", style, re.M)
    assert rule, "the style sheet has no rule for .record"
    for name in ("--sheet", "--rule", "--trace", "--id", "--stat", "--gap"):
        assert f"{name}:" in rule.group(1), name
        assert not re.search(r"#spark\{[^}]*" + name + ":", style), f"{name} is still set on the sheet itself"
    assert re.search(r'<section id="spark" class="record"', page), "the sheet does not carry the class"


def test_the_figures_in_the_head_of_the_cooling_view_keep_digits_of_one_width_in_its_wide_form():
    """The two figures in the head of the cooling view change with every reading, so they are set in digits of one
    width: a digit that changes does not push the ones beside it. The wide form sets them smaller and said so with
    the shorthand `font`, which sets every property of a font anew: there the digits went back to widths of their
    own (measured in WebKit at 15 px: five ones 37 px wide, five eights 49 px). The wide form names the size alone."""
    style = (PAGE.parent / "style.css").read_text()
    rule = re.search(r"^\.cool-key strong\{([^}]*)\}", style, re.M)
    wide = re.search(r"^\.record\.wide \.cool-key strong\{([^}]*)\}", style, re.M)
    assert rule and "font-variant-numeric:tabular-nums" in rule.group(1), "the figures have no digits of one width"
    assert wide and not re.search(r"(?:^|;)font:", wide.group(1)), wide.group(1)


def test_the_calm_form_takes_the_digits_of_one_width_from_no_figure_that_had_them():
    """The value of a row, the four figures of a curve, the figures in the table of the sheet, the share in a line
    under "Earlier" and the figures on the scales of the picture of cooling change while a reader looks at them,
    and are set in digits of one width: a digit that changes does not push the ones beside it. The calm form sets
    them larger and said so with the shorthand `font`, which sets every property of a font anew: there the digits
    went back to widths of their own (measured in WebKit: the value of a row at 26 px, five ones 61 px wide and
    five eights 83 px). The calm form names what it changes, and nothing else."""
    style = (PAGE.parent / "style.css").read_text()

    def rule(selector):
        found = re.search(rf"^{re.escape(selector)}\{{([^}}]*)\}}", style, re.M)
        assert found, f"no rule for {selector}"
        return found.group(1)

    for had, calm in [  # the rule that gives the digits one width (the line under "Earlier" has them from its button)
        (".ch-val strong", ".record.calm .ch-val strong"),
        (".ch-stat dd", ".record.calm .ch-stat dd"),
        (".bs-cell em", "#spark.calm .bs-cell em"),
        (".sp-earlier button", ".record.calm .sp-earlier b"),
        (".cool text", ".record.calm .cool text"),
    ]:
        assert "font-variant-numeric:tabular-nums" in rule(had), f"{had} has no digits of one width"
        assert not re.search(r"(?:^|;)font:", rule(calm)), (calm, rule(calm))
