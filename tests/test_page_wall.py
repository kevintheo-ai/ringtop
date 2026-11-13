"""The calm page for a wall and a phone, as a text and driven without a browser."""

import functools
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ringtop_parts.connect.server import PAGE, WALL, WALL_PARTS
from ringtop_parts.core.wall import wall_moment
from tests.fixtures import needs_node, page_scripts, page_text
from tests.test_page import BROWSER
from tests.test_prom import played

WALL_NAMES = ["wall.css", "base.js", "rules.js", "neutral.js", "faces.js", "wall.js"]
# every text the page holds, and what its corner, its speed, its run, its tiles and its foot say
TEXTS = "server.texts()"
SAID = (
    "({ link: $('#link').lastElementChild.text, dot: $('#link').firstElementChild.style['--dot'],"
    " core: [$('#core-state').text, $('#core-num').text, $('#core-sub').text, $('#speed').classList.contains('wordy')],"
    " run: [$('#run-name').text, $('#run-count').text, $('#run-track').hidden, $('#run-fill').style.width, $('#run-time').text],"
    " tiles: $('#tiles').children.map(t => t.under().map(e => e.text).filter(Boolean).join(' ')),"
    " foot: $('#power').under().map(e => e.text).filter(Boolean), stale: $('#wall').classList.contains('stale') })"
)


def wall_tags():
    """The scripts the calm page names, in the order it runs them."""
    return re.findall(r'<script src="page/([^"]+)"></script>', WALL.read_text())


@functools.cache
def moments():
    """Three moments of the demo as a wall gets them: the ring engine writing, a Spark away, every Spark alone."""
    return {word: wall_moment(played()[word]) for word in ("writing", "away", "alone")}


def whole(value):
    """A reading as the page writes it: a whole number, a half rounded up, thousands apart."""
    return f"{int(value + 0.5):,}"


def spark(k, **more):
    """One Spark of a made-up moment with every figure of a tile read."""
    node = {
        "name": f"box{k}",
        "rank": k,
        "head": k == 0,
        "live": True,
        "gpu_c": 60 + k,
        "fan": 2400,
        "fans": [2400, 2400],
    }
    return {**node, "mem_free_gb": 24, "mem_total_gb": 128, "w": 50, "util": 90, "own": None, **more}


def made(count, t=2000.0, **more):
    """A moment for a wall of a cluster of `count` Sparks, made by hand: the ring engine writes."""
    nodes = [spark(k) for k in range(count)]
    return {
        "t": t,
        "cluster": {
            "ring": count > 1,
            "nodes": [{"name": n["name"], "rank": n["rank"], "head": n["head"]} for n in nodes],
        },
        "identity": {"interval": 2, "memguard_gib": 3, "model": "m"},
        "engine": {"state": "writing", "tok_s": 1234.4, "running": 2, "waiting": 0},
        "nodes": nodes,
        "run": {"source": "none"},
        "why": {},
        **more,
    }


def wall(steps, search="", first=None):
    """Loads the calm page without a browser, sends it `first` down its stream (the demo while the ring engine
    writes, unless told) and runs `steps` in it one after the other; gives back what each step returned. No error
    may fall on the way. search: what stands behind the "?" of the address, "?names=neutral" for neutral names."""
    first = first or moments()["writing"]
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "moments.json"
        file.write_text(json.dumps({"first": first, "next": first, "steps": list(steps), "search": search}))
        loader = str(Path(__file__).with_name("page_loader.js"))
        done = subprocess.run(
            ["node", loader, "sheet", str(file), *page_scripts(folder, WALL)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    assert done.returncode == 0 and done.stdout, done.stderr[-600:]
    seen = json.loads(done.stdout)
    assert seen["errors"] == [] and seen["started"] and seen["ok"] is None, (seen["errors"][:4], seen["started"])
    assert seen["asked"] == [], seen["asked"]  # it asks for nothing but its stream
    return seen["steps"]


def test_the_calm_page_names_only_its_own_parts_in_the_order_of_their_table():
    """The calm page loads its style and five scripts, each a file the server sends from the table of the wall, in
    the order of that table; nothing stands in the page itself. It loads no scene, no measure and not the style of
    the main page: on a wall listener none of them would be sent."""
    page = WALL.read_text()
    assert list(WALL_PARTS) == ["/page/" + name for name in WALL_NAMES]
    assert all(
        file == WALL.parent / name and file.is_file() for name, (file, _) in zip(WALL_NAMES, WALL_PARTS.values())
    )
    assert wall_tags() == [name for name in WALL_NAMES if name.endswith(".js")], wall_tags()
    assert page.count("<script") == len(wall_tags()) and "<style" not in page and " style=" not in page
    assert re.findall(r'<link rel="stylesheet" href="([^"]+)">', page) == ["page/wall.css"]
    named = [u for u in re.findall(r'(?:src|href)="([^"]+)"', page) if not u.startswith("data:")]
    assert sorted("/" + name for name in named) == sorted(WALL_PARTS), named
    assert not re.search(r"scene|measure\.js|style\.css|api/(state|events|nerd|history|replies|runs)|/metrics", page)
    assert "viewport-fit=cover" in page and '<html lang="en">' in page and "<title>Ringtop</title>" in page


def test_the_calm_page_asks_the_server_for_its_stream_and_for_nothing_else():
    """Its script opens the stream for a wall. No other address of the server stands in it, and nothing of a
    moment runs as markup."""
    script = (WALL.parent / "wall.js").read_text()
    assert re.findall(r"""['"`](/?api/[^'"`]*|/?metrics|/?assets/[^'"`]*)['"`]""", script) == ["api/wall"]
    assert "fetch(" not in script and "XMLHttpRequest" not in script
    for text in (script, WALL.read_text(), (WALL.parent / "wall.css").read_text()):
        assert ".innerHTML" not in text and "insertAdjacentHTML" not in text
        assert "http://" not in text.replace("http://www.w3.org", "") and "https://" not in text


def test_every_script_of_the_calm_page_says_what_it_is_runs_strict_and_parses():
    """One syntax error and the page sits on "Connecting" forever; all its scripts joined have to parse as well,
    since they share one world."""
    for name in wall_tags():
        rows = (WALL.parent / name).read_text().split("\n")
        assert rows[0].startswith("// ") and rows[0].endswith(".") and rows[1] == "'use strict';", (name, rows[:2])
    sheet = (WALL.parent / "wall.css").read_text()
    assert sheet.startswith("/* ") and sheet.split("\n")[0].endswith(". */"), sheet[:80]
    if not shutil.which("node"):
        return
    with tempfile.TemporaryDirectory() as folder:
        scripts = page_scripts(folder, WALL)
        joined = Path(folder) / "joined.js"
        joined.write_text("\n".join(Path(script).read_text() for script in scripts))
        for script in [*scripts, str(joined)]:
            done = subprocess.run(["node", "--check", script], capture_output=True, text=True)
            assert done.returncode == 0, done.stderr[:400]


@needs_node
def test_the_scripts_of_the_calm_page_name_nothing_that_nobody_declares_and_say_what_each_function_is_for():
    """The five scripts are parsed as the one program they are in the browser: every name they leave undeclared is
    one the browser gives, so nothing of the main page is missed on a wall. And every function a reader meets first
    says in a sentence what it is for; none of the page's own script is longer than 50 statements."""
    files = [str(WALL.parent / name) for name in wall_tags()]
    tool = Path(__file__).parent
    names = subprocess.run(
        ["node", "--expose-internals", str(tool / "page_names.js"), *files], capture_output=True, text=True, timeout=60
    )
    assert names.returncode == 0 and names.stdout, names.stderr[-600:]
    assert set(json.loads(names.stdout)) <= BROWSER, sorted(set(json.loads(names.stdout)) - BROWSER)
    said = subprocess.run(
        ["node", "--expose-internals", str(tool / "page_sentences.js"), *files],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert said.returncode == 0 and said.stdout, said.stderr[-600:]
    found = json.loads(said.stdout)
    own = [f for f in found["named"] if f["file"] == "wall.js"]
    silent = [f"{f['file']}:{f['line']} {f['name']}" for f in found["named"] if not f["said"]]
    assert len(own) >= 8 and not silent, (len(own), silent[:12])
    long = [(f["name"], f["statements"]) for f in found["sizes"] if f["file"] == "wall.js" and f["statements"] > 50]
    assert not long, long


def test_the_calm_page_takes_its_colours_from_the_main_page():
    """The calm page has a sheet of its own (the one of the main page is 58 KB of rules for its header, main and
    footer) and repeats the names of the colours and the fonts. They are the same, sign for sign."""
    first = r":root\{[^}]*\}"
    main, calm = ((PAGE.parent / name).read_text() for name in ("style.css", "wall.css"))
    assert re.search(first, calm) and re.search(first, calm).group(0) == re.search(first, main).group(0)


def test_the_calm_page_sizes_a_tile_in_container_units_only_where_the_browser_knows_them():
    """Wide, the text of a tile is sized by the place of the tiles, in container units, with a size in units of
    the window before it "for a browser without those units". Both were plain declarations, and both hold a
    var(): such a declaration is taken as it stands, whatever its units, so the second replaced the first, and
    a browser without the units found it worth nothing only when it reckoned the size. The tile then had the size
    of the page, not the first one. So the sheet asks (@supports): the size in container units stands in a block
    only a browser that knows them reads, the size for every other browser before it, and no container unit
    stands where every browser reads it. The size for every other browser stands in the same block as the question
    (one moved into @media print reaches no screen), and no rule after the question sizes a tile anew (a later
    size in window units, in a block of its own, would win over the one in container units)."""
    sheet = re.sub(r"/\*.*?\*/", "", (WALL.parent / "wall.css").read_text(), flags=re.S)
    tile_sizes_hold(sheet)
    fallback = re.findall(r"\.tile\{[^{}]*font-size:[^{};]*\}(?=\s*@supports)", sheet)[0]
    assert red(tile_sizes_hold, sheet.replace(fallback, "@media print{" + fallback + "}", 1))
    for later in ("@media (min-width:1px){.tile{font-size:2vw}}", "#tiles .tile{ font: 600 2vw/1 sans-serif}"):
        assert red(tile_sizes_hold, sheet + later), later


def tile_sizes_hold(sheet: str) -> None:
    """Asserts of a sheet what the check above holds: one question for container units, the size in them only in its
    block, and the size for every other browser before it, in the same block."""
    unit = r"\dcq(?:w|h|i|b|min|max)\b"
    blocks = re.findall(r"@supports \(([^()]*)\)\{((?:[^{}]|\{[^{}]*\})*)\}", sheet)
    assert [bool(re.search(unit, asked)) for asked, _ in blocks] == [True], blocks  # one question, for such a unit
    asked, inside = blocks[0]
    assert re.fullmatch(r"\.tile\{font-size:[^{};]*\}", inside) and len(re.findall(unit, inside)) == 2, inside
    before, after = sheet.split(f"@supports ({asked}){{{inside}}}")
    assert not re.search(unit, before + after), "a container unit where every browser reads it"
    first = list(re.finditer(r"\.tile\{[^{}]*font-size:([^{};]*)\}", before))
    assert first and "vw" in first[-1][1] and "vh" in first[-1][1], first  # the size for every other browser
    assert around(sheet, first[-1].start()) == around(sheet, len(before)), "the size for every other browser elsewhere"
    for selectors, said in re.findall(r"([^{}]+)\{([^{}]*)\}", after):
        tile = any(re.search(r"(?<![\w-])\.tile(?![\w-])", last) for last in last_parts(selectors))
        assert not (tile and re.search(r"(?:^|;)\s*font(?:-size)?\s*:", said, re.I)), (selectors, said)


def around(sheet: str, at: int) -> list:
    """The at-rules (@media, @supports) whose blocks hold the place `at` of a sheet, the outermost first."""
    held, start = [], 0
    for sign in re.finditer(r"[{};]", sheet[:at]):
        if sign[0] == "{":
            held.append(sheet[start : sign.start()].strip())
        elif sign[0] == "}":
            held.pop()
        start = sign.end()
    return [prelude for prelude in held if prelude.startswith("@")]


def red(check, sheet: str) -> bool:
    """Whether a check of a sheet fails on it."""
    try:
        check(sheet)
    except AssertionError:
        return True
    return False


def test_every_figure_of_the_calm_page_keeps_digits_of_one_width():
    """The speed, the count of the run, the three figures of every tile and the GPU power change with every moment,
    so they are set in digits of one width: a digit that changes does not push the ones beside it. The figures of
    a tile had it from the rule of the three together (.t-stats), and the rule of each figure then said its font
    with the shorthand `font`, which sets every property of a font anew: there the digits went back to widths of
    their own (measured in WebKit at 21 px: "111" 30.5 px wide, "888" 41.0 px). A rule that says the font of a
    figure in short says the digits after it, as the speed, the count of the run and the power did already."""
    sheet = re.sub(r"/\*.*?\*/", "", (WALL.parent / "wall.css").read_text(), flags=re.S)
    for figure in (".num", "#run-count", ".t-stats strong", "#power strong"):
        told = ";".join(re.findall(rf"(?:^|[{{}}])\s*{re.escape(figure)}\{{([^{{}}]*)\}}", sheet, re.M))
        after = re.split(r"(?:^|;)font:[^;]*", told)[-1]  # what stands after the last shorthand of its rules
        assert "font-variant-numeric:tabular-nums" in after, (figure, told)


def test_no_later_rule_of_the_calm_page_takes_the_digits_of_one_width_from_a_figure():
    """The check above reads the rules of the four figures by their selectors. A rule further on that picks a figure
    by another selector and says its font once more in short (`.tile .t-stats strong{font:...}`) took the digits of
    one width back, and that check stayed green; in Chromium, wide at 1600 x 900, "111" of a tile was 59.2 px wide
    again and "888" 79.6 px. So every rule of the sheet that picks an element a figure is written in (a strong, every element, the speed,
    the count of the run) says the digits of one width after the last declaration that sets them anew (font,
    font-variant), wherever it stands. The suite has no browser to reckon the cascade with: the rules are held as
    text, by the last part of each selector. Written with a space (`.num{ font:...}`), picked
    as `.num[class]` or `:is(strong)`, or set back by `font-variant-numeric:normal`, a figure loses the digits of
    one width just as well; each of those is held."""
    sheet = re.sub(r"/\*.*?\*/", "", (WALL.parent / "wall.css").read_text(), flags=re.S)
    digits_hold(sheet)
    for later in (
        ".num{ font:600 1em var(--num)}",
        ".num[class]{font:600 1em var(--num)}",
        ".num.num{font:600 1em var(--num)}",
        ".t-stats :is(strong){font:600 1em var(--num)}",
        ".t-stats strong{font-variant-numeric:normal}",
    ):
        assert red(digits_hold, sheet + later), later


def digits_hold(sheet: str) -> None:
    """Asserts that every rule of a sheet that picks an element a figure is written in leaves its digits of one
    width: the last declaration of its font (font, font-variant, font-variant-numeric) says tabular-nums."""
    for selectors, said in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
        figure = r"(?<![\w-])(?:strong|\.num|#run-count)(?![\w-])|\*"
        if not any(re.search(figure, last) for last in last_parts(selectors)):
            continue
        sets = re.findall(r"(?:^|;)\s*(font(?:-variant(?:-numeric)?)?)\s*:([^;]*)", said, re.I)
        assert not sets or (sets[-1][0].lower() != "font" and "tabular-nums" in sets[-1][1].lower()), (selectors, said)


def last_parts(selectors: str) -> list:
    """The last part of each selector of a list: what a rule picks. What stands in parentheses (:is, :not) belongs to
    its part, commas and spaces too."""
    return [[part for part in outside(one.strip(), " \t\n>+~") if part][-1] for one in outside(selectors, ",")]


def outside(text: str, signs: str) -> list:
    """A text split at the signs that stand outside parentheses."""
    parts, part, depth = [], "", 0
    for sign in text:
        depth += (sign == "(") - (sign == ")")
        if depth == 0 and sign in signs:
            parts, part = [*parts, part], ""
        else:
            part += sign
    return [*parts, part]


@needs_node
def test_a_word_of_the_main_page_the_calm_page_repeats_is_still_a_word_of_the_main_page():
    """What the calm page says in the words of the main page (that nothing runs, what a figure of a tile is, the
    line about neutral names) it says in the same words. Its script lists them as MAIN_WORDS; each still stands in
    the main page as it is sent."""
    words = wall(["Object.values(MAIN_WORDS).filter(word => typeof word === 'string')"])[0]
    there = page_text()
    assert len(words) >= 8 and all(word in there for word in words), [word for word in words if word not in there]


@needs_node
def test_the_calm_page_loads_starts_and_shows_a_moment_without_a_browser():
    """Its five scripts run in node against a document that keeps what it is given, with no scene and no WebGL.
    The page opens the stream for a wall, takes a moment of the demo and shows it: Live in the corner, the speed as
    a number with the line of the core under it, the run with its count, bar and time, one tile per Spark with its
    line and three figures, and the GPU power with how many Sparks it is the sum of."""
    streams, said = wall(["server.streams()", SAID])
    writing = moments()["writing"]
    assert streams == ["api/wall"], streams
    assert said["link"] == "Live" and said["dot"] == "var(--teal)" and not said["stale"], said
    speed = whole(writing["engine"]["tok_s"])
    assert said["core"] == ["Writing", speed, "4 running · 0 waiting", False], said["core"]
    assert said["run"][:4] == ["Prefill sweep", "22 of 24", False, "91.7%"] and " in, about " in said["run"][4], said[
        "run"
    ]
    assert len(said["tiles"]) == 4 and said["tiles"][0].startswith("dgx0 head "), said["tiles"]
    first = writing["nodes"][0]
    figures = f"{whole(first['gpu_c'])} °C GPU {whole(first['fan'])} RPM Fans {whole(first['mem_free_gb'])} GB Free RAM"
    assert said["tiles"][0] == f"dgx0 head {figures}", said["tiles"][0]
    watts = whole(sum(n["w"] for n in writing["nodes"])) + " W"
    assert said["foot"] == ["GPU power", watts, "4 of 4 read"], said["foot"]


@needs_node
def test_the_calm_page_shows_a_word_where_nobody_writes_and_a_dash_where_nothing_was_read():
    """While no token is written the speed is the word of the core, large, and no number; with single tracks it is
    the sum of the Sparks that write. A Spark that is away keeps its tile: unreachable, three dashes, and the GPU
    power says of how many Sparks it is the sum; with no Spark read, the sum is a dash and never 0 W."""
    idle = {
        **moments()["writing"],
        "t": moments()["writing"]["t"] + 2,
        "engine": {"state": "idle"},
        "run": {"source": "none"},
    }
    dark = {**idle, "t": idle["t"] + 2, "nodes": [{**n, "live": False, "w": None} for n in idle["nodes"]]}
    away, alone = moments()["away"], moments()["alone"]
    later = max(dark["t"], away["t"], alone["t"])
    got = wall(
        [
            f"server.say({json.dumps(idle)}); {SAID}",
            f"server.say({json.dumps(dark)}); {SAID}",
            f"server.say({json.dumps({**away, 't': later + 2})}); {SAID}",
            f"server.say({json.dumps({**alone, 't': later + 4})}); {SAID}",
        ]
    )
    assert got[0]["core"] == ["Idle", "", "ready for requests", True], got[0]["core"]
    run = got[0]["run"]  # the bar is hidden, whatever it was last as wide as
    assert run[:3] == ["Nothing running", "", True] and run[4] == "Requests and queued runs show up here.", run
    assert all("Unreachable – °C GPU – RPM Fans – GB Free RAM" in tile for tile in got[1]["tiles"]), got[1]["tiles"]
    assert got[1]["foot"] == ["GPU power", "–", "0 of 4 read"], got[1]["foot"]
    assert got[2]["tiles"][3] == "dgx3 Unreachable – °C GPU – RPM Fans – GB Free RAM", got[2]["tiles"]  # no word of ssh
    assert got[2]["foot"][2] == "3 of 4 read" and got[2]["core"][0] == "Writing", got[2]
    tracks = whole(sum(n["own"]["tok_s"] for n in alone["nodes"] if n["own"]))
    assert got[3]["core"] == ["Single tracks", tracks, "3 writing · 1 without a reading", False], got[3]["core"]
    assert got[3]["tiles"][1].startswith("dgx1 43 tok/s · mistral-small-4 "), got[3]["tiles"]


@needs_node
def test_the_calm_page_has_a_tile_for_every_spark_of_one_and_of_sixteen():
    """A cluster of one Spark and one of sixteen: a tile each, the columns of both forms of the page as the rule
    gives them, and the rows of the wide form, where nothing scrolls."""
    form = (
        "[$('#tiles').children.length, ...['--cols-tall', '--cols-wide', '--rows-wide'].map(k => $('#tiles').style[k])]"
    )
    assert wall([form], first=made(1))[0] == [1, 1, 1, 1]
    assert wall([form], first=made(5))[0] == [5, 1, 3, 2]
    got = wall([form, SAID], first=made(16))
    assert got[0] == [16, 1, 4, 4], got[0]
    assert got[1]["tiles"][15] == "box15 worker 75 °C GPU 2,400 RPM Fans 24 GB Free RAM", got[1]["tiles"][15]
    assert got[1]["core"][1] == "1,234" and got[1]["foot"] == ["GPU power", "800 W", "16 of 16 read"], got[1]


@needs_node
def test_a_moment_that_stops_coming_makes_the_calm_page_stale_and_a_repeated_one_does_not_make_it_live():
    """The stream stands and no new moment comes. After the silence that takes a Spark off the main page the corner
    says since when, the figures are marked stale and the stream is opened anew. The server then sends the newest
    moment once more: it is no news, and the page stays stale. The next new one makes it live again. A stale page
    tries again, and not more often than every 5 s."""
    writing = moments()["writing"]
    newer = {**writing, "t": writing["t"] + 2}
    look = "[$('#link').lastElementChild.text, $('#wall').classList.contains('stale'), server.streams().length]"
    got = wall(
        [
            "globalThis.later = seconds => { const base = Date.now(); Date.now = () => base + seconds * 1000; }; later(14); watch(); "
            + look,
            "later(2); watch(); " + look,
            f"server.say({json.dumps(writing)}); " + look,
            "later(4); watch(); " + look,
            "later(2); watch(); " + look,
            f"server.say({json.dumps(newer)}); " + look,
            "$('#link').firstElementChild.style['--dot']",
        ]
    )
    assert got[0] == ["Live", False, 1], got[0]
    assert got[1][1:] == [True, 2] and got[1][0] not in ("Live", "Reconnecting", "Connecting", ""), got[1]
    assert re.search(r"\d\d:\d\d:\d\d", got[1][0]), got[1][0]  # since when, to the second
    assert got[2] == [got[1][0], True, 2], got[2]  # the moment it had already: no news
    assert got[3][1:] == [True, 2] and got[4][1:] == [True, 3], got[3:5]  # 4 s later not yet, 6 s later once more
    assert got[5] == ["Live", False, 3] and got[6] == "var(--teal)", got[5:]


@needs_node
def test_a_calm_page_without_its_first_moment_opens_a_stream_anew_that_brings_none():
    """The page has no moment yet: its stream stands and brings a word that is no moment, then nothing. The corner
    says Connecting, and that was all: the page waited on that one stream for as long as it was open. After the
    silence it opens the stream anew, and after the next silence once more; the first moment makes it live."""
    look = "[$('#link').lastElementChild.text, $('#wall').classList.contains('stale'), server.streams().length]"
    got = wall(
        [
            "globalThis.later = seconds => { const base = Date.now(); Date.now = () => base + seconds * 1000; }; later(14); watch(); "
            + look,
            "later(2); watch(); watch(); " + look,
            "stream.onopen(); later(14); watch(); " + look,
            "later(2); watch(); " + look,
            f"server.say({json.dumps(moments()['writing'])}); " + look,
        ],
        first={"cluster": {"ring": True, "nodes": []}},  # a word of the stream that is no moment
    )
    assert got[0] == ["Connecting", False, 1], got[0]
    assert got[1] == ["Reconnecting", False, 2], got[1]  # was Connecting on its first stream, for good
    assert got[2] == ["Connecting", False, 2] and got[3][2] == 3, got[2:4]  # the new one stands, and brings none
    assert got[4] == ["Live", False, 3], got[4]


@needs_node
def test_a_stream_that_breaks_says_reconnecting_and_another_cluster_starts_the_calm_page_anew():
    """A cut of the stream is said in the corner in the words of the main page, and the figures stay: they still
    hold. A moment of another cluster means ringtop came back on other machines, and the page starts anew; one
    without a time or a cluster is passed over."""
    writing = moments()["writing"]
    other = json.dumps({**writing, "t": writing["t"] + 4}).replace("dgx", "rig")
    got = wall(
        [
            "location.reload = () => { globalThis.anew = (globalThis.anew || 0) + 1; }; stream.onerror(); " + SAID,
            f"server.say({{}}); server.say({json.dumps({'t': writing['t'] + 2})}); [globalThis.anew || 0, $('#link').lastElementChild.text]",
            f"server.say({other}); [globalThis.anew, $('#tiles').children[0].children[0].children[1].text]",
        ]
    )
    assert got[0]["link"] == "Reconnecting" and got[0]["dot"] == "var(--amber)" and not got[0]["stale"], got[0]
    assert got[0]["core"][0] == "Writing" and len(got[0]["tiles"]) == 4, got[0]
    assert got[1] == [0, "Reconnecting"], got[1]
    assert got[2] == [1, "dgx0"], got[2]  # asked to start anew, and nothing of the other cluster was painted


@needs_node
def test_with_neutral_names_no_element_of_the_calm_page_holds_a_real_name():
    """The address asks for neutral names. The moments still carry the names of the Sparks (dgx0 to dgx3), the name
    a run source gave its run, and what the Sparks work on by themselves. After each of them no text, title or
    attribute of the page holds one of these; the Sparks are spark-1 to spark-4, the run is "Test run", the button
    for the names is pressed and the foot says that the names are neutral. Without the wish, nothing is replaced."""
    away, alone = moments()["away"], moments()["alone"]
    sent = json.dumps([moments()["writing"], away, alone])
    assert all(
        word in sent for word in ("dgx0", "Prefill sweep", "Stall probe", "mistral-small-4", "sglang::scheduler")
    )
    steps = [
        TEXTS,
        f"server.say({json.dumps({**away, 't': alone['t'] + 2})}); {TEXTS}",
        f"server.say({json.dumps({**alone, 't': alone['t'] + 4})}); {TEXTS}",
        "[$('#names').getAttribute('aria-pressed'), $('#about').hidden, $('#about').text, $('#run-name').text]",
        "$('#tiles').children.map(t => t.under().map(e => e.text).filter(Boolean).slice(0, 2).join(' '))",
    ]
    got = wall(steps, "?names=neutral")
    outside = re.compile(r"dgx|Prefill|Stall probe|Release suite|Demo |mistral|sglang|sensenova|nemotron|ssh")
    for texts in got[:3]:
        assert len(texts) > 20 and not [text for text in texts if outside.search(text)], texts
    assert got[3] == ["true", False, "Shown with neutral names for the Sparks and the runs (H).", "Test run"], got[3]
    assert got[4] == [
        "spark-1 runs a program",
        "spark-2 43 tok/s · an engine",
        "spark-3 25 tok/s · an engine",
        "spark-4 53 tok/s · an engine",
    ], got[4]
    plain = wall(steps[2:])
    assert plain[1][:2] == ["false", True] and plain[2][1] == "dgx1 43 tok/s · mistral-small-4", plain[1:]
    assert any("dgx0" in text for text in plain[0])


@needs_node
def test_the_switch_for_the_names_says_what_is_on_and_that_the_real_names_still_reach_the_device():
    """The words the calm page has of its own. The button is one short word that says what is on while it is
    pressed, and it is pressed while neutral names are shown. What it says of itself names in either state the key
    that does the same, and that the real names still reach the device: the switch is for a picture and protects
    nothing. With neutral names on it says what they are: spark-1 to spark-N, and "Test run". The corner of a stale
    page ends with the time. None of them is a placeholder any more."""
    words = (
        "[WALL_TEXTS.names, WALL_TEXTS.namesTitle(true), WALL_TEXTS.namesTitle(false), WALL_TEXTS.stale('17:27:25')]"
    )
    button = "[$('#names').text, $('#names').title, $('#names').getAttribute('aria-pressed')]"
    (name, on, off, stale), plain = wall([words, button])
    assert name == "Neutral" and plain == [name, off, "false"], (name, plain)
    assert wall([button], "?names=neutral")[0] == [name, on, "true"]
    for said in (on, off):
        assert "(H)" in said and "the real names still reach this device" in said, said
    assert "spark-1 to spark-N" in on and '"Test run"' in on and "picture" in off, (on, off)
    assert stale.endswith(" 17:27:25") and len(stale) <= 26, stale  # with a 12-hour clock: three signs more
    assert "PLACEHOLDER" not in (WALL.parent / "wall.js").read_text()


@needs_node
def test_the_calm_page_shows_the_sign_of_the_demo_only_where_the_server_says_so():
    """The calm page carries the sign of the demo in its head like the main page: shown while the moments name the
    demo, also with neutral names, and hidden for a moment without that field, as a real cluster sends it."""
    first = moments()["writing"]
    real = {**first, "t": first["t"] + 2, "identity": {k: v for k, v in first["identity"].items() if k != "demo"}}
    sign = "document.querySelector('#demo').hidden"
    assert first["identity"]["demo"] is True, first["identity"]
    assert wall([sign, f"server.say({json.dumps(real)}); {sign}"]) == [False, True]
    assert wall([f"[NEUTRAL, {sign}]"], search="?names=neutral") == [[True, False]]
