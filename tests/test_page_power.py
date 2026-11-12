"""The watts on the page, driven without a browser: every place that shows them says they are those of the GPU.

The watts ringtop has are what nvidia-smi reports as power.draw. Nothing measures what a whole Spark draws."""

import json

from tests.fixtures import needs_node
from tests.test_page_sheet import HEADINGS, OPEN, answer, moments, sheet

PANEL = "document.querySelector('#panel').under().map(e => e.text).filter(Boolean)"  # every text of the panel
# The four sentences about the watts, as they were written for the page: held here word for word.
FOAM = "Metal foam on the front: the air comes in here. The pores glow with the GPU power of this Spark."
NODES = "One line per Spark: GPU utilisation, GPU clock, GPU temperature, GPU power, free memory, fan speed, network card temperature."
SOURCE = "GPU power as nvidia-smi reports it, averaged by the driver. A whole Spark draws more: the GB10 does not report that."
SHEET = "Watts from nvidia-smi power.draw, the value the driver averages. GPU only: a whole Spark draws more, but the GB10 reports no whole-device power, so the page cannot show it. Nothing is measured at the wall socket."


@needs_node
def test_the_tile_and_the_tag_of_a_spark_say_whose_watts_they_show():
    """The tile of a Spark in the dock showed its watts as a figure with a "W", and so did its tag in the scene: as
    if they were what the machine draws. Both say "W GPU"."""
    got = sheet(
        [
            "String(Math.round(S.nodes[0].w))",
            "(t => [t.value.text, t.tile.under().find(e => e.matches('small')).text])(tiles.get(S.nodes[0].name))",
            "document.querySelector('#tags').children[0].under().map(e => e.text).filter(Boolean)",
        ]
    )
    watts = got[0]
    assert got[1] == [watts, "W GPU"], got[1]  # was "W"
    assert got[2][1] == f"{watts} W GPU", got[2]  # the first Spark serves in the ring: its tag shows its watts


@needs_node
def test_the_cards_of_the_parts_say_whose_watts_they_show():
    """The cards of the parts of an open Spark showed its watts under the word "watts", and the card of the GB10
    package a bar and a curve called "Power": the GPU power nvidia-smi reports, said as if it were what the part or
    the machine draws. They say "GPU watts" and "GPU power", looking back too, and so does the short line of the
    package."""
    then = json.loads(moments())["past"]["t"]
    cards = ("gb10_package", "fin_stack", "foam_front", "foam_rear")
    got = sheet(
        [
            "setView('node', S.nodes[1].name); null",
            *(f"setPart('{part}'); {PANEL}" for part in cards),
            "[partShort('gb10_package', S.nodes[1]), 'GPU ' + Math.round(S.nodes[1].w) + ' W']",
            f"setPart(null); Time.toggle(true); Time.go({then[len(then) // 2]}); null",
            f"setPart('gb10_package'); [S.nodes[1].live, {PANEL}]",
        ]
    )
    for card, said in zip(cards, got[1:5]):
        assert said.count("GPU watts") == 1 and "watts" not in said, (card, said)  # was "watts" on each of them
    package = got[1]
    assert package.count("GPU power") == 1 and package.count("GPU power, 30 min") == 1, package
    assert "Power" not in package and "Power, 30 min" not in package, package  # the bar and the curve of the package
    assert got[5][0] == got[5][1], got[5]  # was "51 W"
    live, back = got[7]
    assert live is True and back.count("GPU power") == 1 and "Power" not in back, got[7]  # its line without a bar


@needs_node
def test_nerd_mode_says_whose_watts_it_lists():
    """Nerd mode lists the watts of every Spark twice: as a column "W" in its line of the live view, and as the rows
    "Power" and "Power, instant" of the Nodes tab. A click on the first row draws it over time under that name, away
    from the heading "GPU" it stood under. The rows are called "GPU power", the curve with them, and the narrow
    column keeps its "W" and says "GPU power" as its tooltip."""
    heads = "document.querySelector('#n-right').under().filter(e => e.matches('div.n-mx'))[0].children.slice(0, 8)"
    rows = "document.querySelector('#n-pane').under().filter(e => e.matches('tr'))"
    got = sheet(
        [
            "Nerd.toggle(true); null",
            f"{heads}.map(c => [c.text, c.title || ''])",
            "Nerd.tab('nodes'); null",
            f"{rows}.filter(r => r.children[r.children.length - 1].text === 'W').map(r => r.children[0].text)",
            f"{rows}.find(r => r.children[0].text === 'GPU power').fire('click', {{}}); null",
            "document.querySelector('#n-pane').under().map(e => e.text).filter(t => /power \\(W\\)$/i.test(t))",
        ]
    )
    assert got[1][4] == ["W", "GPU power"], got[1]  # was a "W" that said nothing of itself
    assert [title for word, title in got[1] if word != "W"] == [""] * 7, got[1]
    assert got[3] == ["GPU power", "GPU power, instant"], got[3]  # were "Power" and "Power, instant"
    assert got[5] == ["GPU power (W)"] * 2, got[5]  # the curve the click drew (was "Power (W)"), and the one there


@needs_node
def test_the_front_foam_says_whose_power_its_pores_glow_with():
    """The pores of the metal foam glow with the GPU power of the Spark: the scene takes their light from that
    reading. The card of the front foam said they glow "with the power this Spark draws", which nothing measures."""
    got = sheet([f"setView('node', S.nodes[1].name); setPart('foam_front'); {PANEL}"])
    assert got[0][-1] == FOAM, got[0]


@needs_node
def test_the_line_per_spark_of_nerd_mode_says_whose_power_its_column_holds():
    """The heading over the line per Spark of nerd mode lists the columns as its tooltip, and called the column of
    the watts "power". It names every column of the GPU as one of the GPU."""
    got = sheet(
        [
            "Nerd.toggle(true); null",
            "(h => [h.text, h.title])(document.querySelector('#n-right').under().find(e => e.matches('h3')))",
        ]
    )
    assert got[1] == ["Nodes", NODES], got[1]


@needs_node
def test_the_watts_of_one_spark_say_where_they_come_from():
    """Wherever the watts of one Spark stand alone, one sentence says where they come from and that a whole Spark
    draws more: as the tooltip of the figure on its tile, of the watts on its tag in the scene and of their row in
    nerd mode, and as a note on the card of the GB10 package. The tile and the tag said nothing, the card had no
    note. A tag that shows the speed of an engine says nothing of watts, and the row of the instant power keeps
    the hint it had."""
    tags = "document.querySelector('#tags').children.slice(0, 2).map(t => t.under().find(e => e.matches('span')))"
    rows = "document.querySelector('#n-pane').under().filter(e => e.matches('tr'))"
    got = sheet(
        [
            "tiles.get(S.nodes[0].name).tile.under().find(e => e.matches('strong')).title",
            f"{tags}.map(s => [s.text.replace(/^[0-9]+ /, ''), s.title || ''])",
            f"setView('node', S.nodes[1].name); setPart('gb10_package'); {PANEL}",
            "setPart(null); setView('ring'); Nerd.toggle(true); Nerd.tab('nodes'); null",
            f"{rows}.filter(r => r.children[r.children.length - 1].text === 'W').map(r => r.children[0].title)",
        ]
    )
    assert got[0] == SOURCE, got[0]  # the tile had no tooltip at its figure
    assert got[1] == [["W GPU", SOURCE], ["tok/s", ""]], got[1]  # the second Spark serves on its own
    assert got[2][-1] == SOURCE, got[2]  # the card ended with its curve
    assert got[4] == [f"{SOURCE} Click to plot it over time.", "Instantaneous GPU power: spikes the average hides."], (
        got[4]
    )


@needs_node
def test_the_box_of_the_sheet_says_where_the_watts_come_from():
    """The sheet of a Spark names its GPU power at its head and draws it as a curve. Its box said what a curve is
    drawn with and what every lane counts, and nothing of where these watts come from. It says so in a paragraph
    under the word the curve carries, after the one about the curves."""
    got = sheet([answer({"gpu_c": "60 + k"}), OPEN, f"[{HEADINGS}, explained('GPU power')]"])
    headings, said = got[2]
    assert headings[headings.index("Curves") + 1] == "GPU power", headings
    assert said == SHEET, said
