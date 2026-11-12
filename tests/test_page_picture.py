"""The picture of a run, run through node: what the drawing holds, what never gets into it, and how it is saved."""

import re
import time
from xml.etree import ElementTree

from tests.fixtures import needs_node
from tests.test_page_runs import VIEW, card
from tests.test_page_sheet import sheet

SVG = "{http://www.w3.org/2000/svg}"


def drawn(svg: str):
    """A picture as its tree, the words of its texts in the order they stand, and its paths. A picture that is not
    well-formed XML fails here."""
    root = ElementTree.fromstring(svg)
    texts = ["".join(node.itertext()) for node in root.iter(SVG + "text")]
    return root, texts, [node.attrib for node in root.iter(SVG + "path")]


def squashed(text: str) -> str:
    """A text without its blanks: a sentence the picture breaks into lines reads the same."""
    return re.sub(r"\s+", "", text)


@needs_node
def test_the_picture_of_a_run_is_one_drawing_of_1200_by_675_that_refers_to_nothing_outside():
    """The picture is SVG as text: well-formed XML, 1200 by 675, made of plain shapes and words. It names no file,
    no font file, no address and no script, so drawing it asks nobody for anything. A name with signs of markup,
    with a sign XML forbids or with a sign beyond the first plane stays a name: the picture is still well-formed
    and says it letter by letter."""
    plain, spiked = card(
        """
        const spiked = { ...record, name: 'A <b>&amp; "run"\\u0001 \\'x\\' \\u{1F680}</text><script>' };
        return [runPicture(record, { now: 5000 }), runPicture(spiked, { now: 5000, real: true })];"""
    )
    for svg in (plain, spiked):
        root, _, _ = drawn(svg)
        assert root.tag == SVG + "svg", root.tag
        assert (root.get("width"), root.get("height"), root.get("viewBox")) == ("1200", "675", "0 0 1200 675")
        tags = {node.tag.removeprefix(SVG) for node in root.iter()}
        assert tags <= {"svg", "rect", "line", "text", "tspan", "path"}, tags
        for word in ("href", "url(", "@import", "javascript:", "<!", "<?"):
            assert word not in svg, word
        assert svg.count("http") == 1 and 'xmlns="http://www.w3.org/2000/svg"' in svg  # its namespace, nothing else
    assert "A <b>&amp; \"run\" 'x' \U0001f680</text><script>" in drawn(spiked)[1], drawn(spiked)[1]


@needs_node
def test_the_picture_says_the_four_figures_of_the_card_and_no_number_of_its_own():
    """The four figures stand in the picture as the rules of the card give them, in their order, each with its unit
    and its word. Under the name stands from when to when the run went, or that nobody saw it end; the note under
    the duration then says when the source last named it, and not the words of that line once more. A figure says
    its note only while it carries a state, as on the card. The foot says how many Sparks, whether as a ring (only
    where the page said they are one and the run went through the ring engine), and that the energy is that of the
    GPUs. No text of the picture holds a number that is not one of these. What was not measured is a dash, never a
    zero."""
    got, loose, no_ring, ring = card(
        """
        const sums = { tokens: null, engine_steps: null, token_s: 0, token_gap_s: 0, lives: 0, tok_s_peak: null };
        const runs = { whole: record, part: { ...record, gpu_from: 3, gpu_read_s: 1800, gpu_gap_s: 600, token_gap_s: 60, lives: 2 },
          tracks: { ...record, ...sums, tracks: 3, gpu_wh: null, gpu_read_s: 0, gpu_gap_s: 2400, gpu_from: 0 },
          unseen: { ...record, ended: null }, open: { ...record, open: true, ended: null } };
        const trace = { t: [1000, 1300, 1600], v: [30, 50, 40], gap: 400 };
        const each = Object.entries(runs).map(([name, r]) => [name, runPicture(r, { now: 1700, trace, ring: true }), runFigures(r, 1700), runState(r), RUN_TEXTS.pictureFoot(r.sparks, !r.tracks)]);
        return [each, runPicture(record, { now: 1700 }), RUN_TEXTS.pictureFoot(4, false), RUN_TEXTS.pictureFoot(4, true)];"""
    )
    assert no_ring != ring and no_ring in drawn(loose)[1] and ring not in drawn(loose)[1], drawn(loose)[1]
    words = {}
    for name, svg, figs, state, foot in got:
        _, texts, _ = drawn(svg)
        words[name] = texts
        order = [word for f in figs for word in (f"{f['value']} {f['unit']}".strip(), f["what"])]
        rest = iter(texts)
        assert all(word in rest for word in order), (name, order, texts)  # each figure, then its word, one by one
        when = state if figs[0]["state"] else figs[0]["note"]
        assert texts[0] == "Test run" and texts[1] == when and foot in texts, (name, texts)
        if figs[0]["state"]:  # the line under the name and the note under the duration stand one above the other
            assert state.lower() not in figs[0]["note"].lower(), (state, figs[0]["note"])
        assert "GPU" in foot and "4" in foot, foot
        whole = squashed(" ".join(texts))
        for fig in figs:  # the note of the duration without a state is the line under the name
            if fig["note"]:
                assert (squashed(fig["note"]) in whole) == (bool(fig["state"]) or fig is figs[0]), (name, fig)
        notes = [f["note"] for f in figs if f["state"]]
        known = squashed(" ".join([*order, when, foot, *notes]))
        for text in texts:
            assert not re.search(r"\d", text) or squashed(text) in known, (name, text)
        assert not any(bad in svg for bad in ("NaN", "null", "undefined", "Infinity")), name
    assert words["tracks"].count("– tok/s") == 1 and "–" in words["tracks"] and "– Wh" in words["tracks"]
    assert not any(re.fullmatch(r"0(\.0+)?( \S+)?", text) for text in words["tracks"]), words["tracks"]


@needs_node
def test_without_a_tick_the_picture_holds_no_word_of_the_source_of_the_run():
    """As it comes the picture calls the run "Test run" and names no model. The name of the run gets in only where
    it is asked for, and so does the model; the image, the queue and the stations never do. And a Spark is never
    called by its real name: inside the name of a run or of a model it reads as its neutral one, by the rule of
    the neutral lens (a whole name, not a part of a longer one)."""
    plain, real, model, both = card(
        """
        const poison = { ...record, source: 'GIFTQUELLE', name: 'GIFTNAME on dgx3', group: 'GIFTGRUPPE', model: 'GIFTMODELL@dgx3',
          image: 'registry.gift/GIFTIMAGE:1', steps: [{ name: 'GIFTSTATION dgx3', state: 'done', seconds: 61 }] };
        const pairs = [['dgx3', 'spark-3'], ['dgx30', 'spark-4']];
        return [{}, { real: true }, { model: true }, { real: true, model: true }].map(opt => runPicture(poison, { now: 5000, pairs, ...opt }));"""
    )
    for svg in (plain, real, model, both):
        for word in ("GIFTQUELLE", "GIFTGRUPPE", "GIFTIMAGE", "GIFTSTATION", "registry", "dgx3"):
            assert word not in svg, word
    assert "GIFT" not in plain and drawn(plain)[1][0] == "Test run", drawn(plain)[1]
    assert drawn(real)[1][0] == "GIFTNAME on spark-3" and "GIFTMODELL" not in real, drawn(real)[1]
    assert "GIFTMODELL@spark-3" in drawn(model)[1] and "GIFTNAME" not in model, drawn(model)[1]
    assert drawn(both)[1][0] == "GIFTNAME on spark-3" and "GIFTMODELL@spark-3" in drawn(both)[1], drawn(both)[1]
    assert len(drawn(plain)[1]) + 1 == len(drawn(model)[1])  # the model is one text more, nothing else changes


def points(path: dict) -> list:
    """The corners of a line of a picture as (how it gets there, x, y)."""
    return [(how, float(x), float(y)) for how, x, y in re.findall(r"([ML])([\d.]+) ([\d.]+)", path["d"])]


@needs_node
def test_the_picture_draws_the_speed_over_the_run_as_a_thin_line_where_it_was_read():
    """The readings of the speed over the run are one thin line across the picture, from its beginning at the left
    to its end at the right, the highest reading on top, with a word that says what it is. A hole in the readings
    breaks the line, and a reading from before or after the run is not drawn. Without readings there is no line
    and no word for one; and none for a run whose tokens nobody counted, whatever the trace says."""
    label, line, hole, outside, none, one, tracks = card(
        """
        const t = [1000, 1100, 1200, 1300, 1400, 1500, 1600], v = [10, 20, 40, 80, 40, 20, 10], gap = 150;
        const draw = (trace, r = record) => runPicture(r, { now: 5000, trace });
        return [RUN_TEXTS.pictureCurve, draw({ t, v, gap }), draw({ t, v: [10, 20, null, null, null, 20, 10], gap }),
          draw({ t: [900, ...t, 1700], v: [99, ...v, 99], gap }), draw(null), draw({ t: [1300], v: [80], gap }),
          draw({ t, v, gap }, { ...record, tokens: null, token_s: 0, tracks: 3 })];"""
    )
    _, texts, paths = drawn(line)
    assert len(paths) == 1 and label in texts, (paths, texts)
    assert paths[0].get("fill") == "none" and 0 < float(paths[0]["stroke-width"]) <= 3, paths[0]
    way = points(paths[0])
    assert [how for how, _, _ in way] == ["M", "L", "L", "L", "L", "L", "L"], way
    xs, ys = [x for _, x, _ in way], [y for _, _, y in way]
    # across the picture, with the same margin at either side
    assert xs == sorted(xs) and xs[0] < 100 and xs[-1] > 1100 and xs[0] + xs[-1] == 1200, xs
    assert min(ys) == ys[3] and ys[0] == ys[6] == max(ys) and 0 < min(ys) < max(ys) < 675, ys  # 80 on top
    assert [how for how, _, _ in points(drawn(hole)[2][0])] == ["M", "L", "M", "L"], drawn(hole)[2]
    # the same line: what lies outside the run adds nothing, and does not move the scale
    assert points(drawn(outside)[2][0]) == way, drawn(outside)[2]
    for svg in (none, one, tracks):
        assert drawn(svg)[2] == [] and label not in drawn(svg)[1], drawn(svg)[1]


@needs_node
def test_the_file_of_a_picture_is_named_after_the_minute_its_run_began_and_nothing_else():
    """The file a picture is saved as carries the day and the minute its run began, on the local clock: the start its
    source named, else the moment it was first seen. No word of the run gets into the name of a file."""
    names = card(
        "return [1000, 1700000000].map(t => pictureFile({ ...record, started: t }))"
        ".concat(pictureFile({ ...record, started: null, first_seen: 90000 }));"
    )
    assert names == [
        time.strftime("ringtop-run-%Y%m%d-%H%M.png", time.localtime(t)) for t in (1000, 1700000000, 90000)
    ], names


# What a check of saving finds its way around with, beside the names of the runs view: a browser that draws nothing
# and keeps what it was asked for. Every drawing an image was given (`pictures`), every canvas that was turned into
# a file (`drew`: its width, its height, the type), and every file a link was clicked for (`saved`: its name, how
# its address begins). `fails` lets the image or the canvas fail. `ticks` are the boxes of the bar, `save` a click
# on its button.
SAVING = """
(() => {
  globalThis.pictures = []; globalThis.drew = []; globalThis.saved = []; globalThis.fails = null;
  const every = Object.getPrototypeOf(document.createElement('a'));
  Object.defineProperty(every, 'src', { configurable: true, get() { return this.source; },
    set(v) { this.source = String(v); pictures.push(decodeURIComponent(this.source.slice(this.source.indexOf(',') + 1))); queueMicrotask(() => fails === 'image' ? this.onerror() : this.onload()); } });
  every.toBlob = function (done, type) { drew.push([this.width, this.height, type]); done(fails === 'canvas' ? null : new Blob(['png'], { type })); };
  every.click = function () { if (this.tagName === 'A') saved.push([this.download, String(this.href).slice(0, 5)]); };
  globalThis.ticks = () => panel.under().filter(e => e.tagName === 'INPUT');
  globalThis.save = () => one('run-save').fire('click', {});
})();
null
"""


@needs_node
def test_the_runs_view_saves_the_picture_of_the_run_on_the_card_as_a_png_file():
    """The bar of the card has a button that saves the picture of the run on the card, and two boxes that are not
    ticked: the real name of the run, and the model. A click draws the picture in the browser, twice as dense as
    it is large, and hands it over as a PNG file named after the minute the run began. The speed over the run is
    asked of the history the page has. As it comes the picture says "Test run" and no model; a tick puts the name
    or the model in, and holds for one picture: after it both boxes are empty again. The image, the queue and the
    stations are in none of them. What the button says of itself names the name the picture comes with."""
    seen = sheet(
        [
            VIEW,
            SAVING,
            "setView('run'); null",
            "({ button: [one('run-save').text, one('run-save').title], ticks: ticks().map(t => [t.type, t.checked, t.parentNode.children[1].text]), texts: [RUN_TEXTS.save, RUN_TEXTS.saveTitle, RUN_TEXTS.realName, RUN_TEXTS.withModel] })",
            "save(); null",
            "({ saved: saved.slice(), drew: drew.slice(), asked: server.historyAsked().slice(-1)[0], name: pictureFile(Runs.shown()), busy: !!one('run-save').disabled })",
            "ticks().forEach(t => { t.checked = true; }); save(); null",
            "ticks().map(t => t.checked)",
            "save(); null",
            "({ pictures, saved: saved.length, foot: RUN_TEXTS.pictureFoot(4, true), failed: RUN_TEXTS.saveFailed, note: cardNow().note })",
        ]
    )
    bar, first, after, last = seen[3], seen[5], seen[7], seen[9]
    assert bar["button"] == bar["texts"][:2] and all(bar["texts"]), bar
    assert "Test run" in bar["button"][1], bar["button"][1]  # the button says what the picture shows as it comes
    assert bar["ticks"] == [["checkbox", False, bar["texts"][2]], ["checkbox", False, bar["texts"][3]]], bar
    assert first["saved"] == [[first["name"], "blob:"]] and first["drew"] == [[2400, 1350, "image/png"]], first
    assert re.fullmatch(r"ringtop-run-\d{8}-\d{4}\.png", first["name"]) and not first["busy"], first
    for word in ("keys=engine.tok_s", "from=1800000020.0", "band=1"):  # the speed of the ring engine, from its start
        assert word in first["asked"], first["asked"]
    assert after == [False, False] and last["saved"] == 3 and last["failed"] not in last["note"], (after, last)
    plain, full, again = (drawn(svg) for svg in last["pictures"])
    for (_, texts, paths), svg in zip((plain, full, again), last["pictures"]):
        assert len(paths) == 1 and last["foot"] in texts, texts  # the curve, and four Sparks in a ring
        for word in ("spark-ds41f", "Release suite", "Short prompts", "dgx"):
            assert word not in svg, word
    assert plain[1][0] == again[1][0] == "Test run" and "deepseek" not in "".join(plain[1] + again[1]), plain[1]
    assert full[1][0] == "Prefill sweep" and "deepseek-v4.1-flash" in full[1], full[1]


@needs_node
def test_a_picture_that_cannot_be_made_is_said_on_the_card_and_one_without_its_curve_is_still_saved():
    """Where the history gives no stretch, the picture is saved without its curve. Where the browser cannot draw
    the picture or cannot make a file of it, nothing is saved and the card says so, until a picture is saved
    again; the button can be pressed again."""
    seen = sheet(
        [
            VIEW,
            SAVING,
            "setView('run'); null",
            "server.historyAnswers({ error: 'no stretch' }); save(); null",
            "({ saved: saved.length, paths: pictures[0].split('<path').length - 1, note: cardNow().note, failed: RUN_TEXTS.saveFailed })",
            "fails = 'image'; save(); null",
            "({ saved: saved.length, note: cardNow().note, busy: !!one('run-save').disabled })",
            "fails = 'canvas'; save(); null",
            "({ saved: saved.length, note: cardNow().note, busy: !!one('run-save').disabled })",
            "fails = null; save(); null",
            "({ saved: saved.length, note: cardNow().note })",
        ]
    )
    bare, image, canvas, fine = seen[4], seen[6], seen[8], seen[10]
    failed = bare["failed"]
    assert failed and (bare["saved"], bare["paths"]) == (1, 0) and failed not in bare["note"], bare
    assert image == {"saved": 1, "note": image["note"], "busy": False} and failed in image["note"], image
    assert canvas == {"saved": 1, "note": canvas["note"], "busy": False} and failed in canvas["note"], canvas
    assert fine["saved"] == 2 and failed not in fine["note"], fine


@needs_node
def test_with_neutral_names_the_picture_has_no_box_for_the_name_of_the_run():
    """A page with neutral names never held the name of the run, so it offers no box for it: only the one for the
    model, which the page shows under neutral names too. Its picture says "Test run"."""
    seen = sheet(
        [
            VIEW,
            SAVING,
            "setView('run'); null",
            "({ ticks: ticks().map(t => t.parentNode.children[1].text), model: RUN_TEXTS.withModel })",
            "ticks().forEach(t => { t.checked = true; }); save(); null",
            "({ pictures, saved: saved.length })",
        ],
        search="?names=neutral",
    )
    assert seen[3]["ticks"] == [seen[3]["model"]], seen[3]
    _, texts, _ = drawn(seen[5]["pictures"][0])
    assert seen[5]["saved"] == 1 and texts[0] == "Test run" and "deepseek-v4.1-flash" in texts, texts
    for word in ("Prefill", "Release suite", "dgx", "spark-ds41f"):
        assert word not in seen[5]["pictures"][0], word


@needs_node
def test_with_neutral_names_the_model_of_a_run_stands_nowhere_but_in_a_picture_it_was_ticked_for():
    """The runs view shows runs of the past. With neutral names nothing of it names the model or the image of a
    run: not the card, not the list, not a tooltip, and not the box behind the "i", which says both on the page
    with real names. The model gets into a picture where its box is ticked, and nowhere else; a Spark named inside
    it reads as its neutral name there, once."""
    past = "{ id: 7, source: 'command', name: 'Job 7', group: null, started: LIVE.t - 900, first_seen: LIVE.t - 900, last_heard: LIVE.t - 310, counted_from: LIVE.t - 900, saved: LIVE.t - 300, ended: LIVE.t - 300, open: false, done: 24, total: 24, tracks: null, steps: null, model: 'models/dgx3/llm-a', image: 'dgx3:5000/vllm:1', sparks: 4, tokens: 24000, engine_steps: 8000, token_s: 600, token_gap_s: 0, lives: 1, tok_s_peak: 61.5, gpu_wh: 12.3, gpu_read_s: 2400, gpu_gap_s: 0, gpu_from: 4 }"
    seen = sheet(
        [
            VIEW,
            SAVING,
            f"server.runsAnswer({{ open: null, runs: [{past}] }}); setView('run'); null",
            "one('q-info').fire('click', {}); ({ box: one('q-pop').children.map(c => c.text).join(' '), done: RUN_TEXTS.done('24', '24') })",
            "panel.under().map(e => [e.text, e.title, e.getAttribute('aria-label')].join(' ')).join(' ')",
            "shutBox(); save(); null",
            "ticks().forEach(t => { t.checked = true; }); save(); null",
            "pictures.slice()",
        ],
        search="?names=neutral",
    )
    box, page, pictures = seen[3], seen[4], seen[7]
    assert box["done"] in box["box"], box  # the box is open and says what it says of this run
    for word in ("models/", "llm-a", "vllm", "dgx3", "spark-4"):
        assert word not in page and word not in pictures[0], word  # nowhere on the view, and not in a plain picture
    _, texts, _ = drawn(pictures[1])
    assert "models/spark-4/llm-a" in texts and "vllm" not in pictures[1] and "dgx3" not in pictures[1], texts
