"""The faces of the page: what the core, a Spark and a run say of themselves, on the main page and without it."""

from ringtop_parts.connect.server import PAGE
from tests.fixtures import needs_node, page_faces
from tests.test_page_sheet import sheet

# What the faces say of made-up moments, as one piece of script that gives back every answer: the core in each state
# of the ring engine, with single tracks and with Sparks that work on their own; the line of a Spark, worst first; the
# line of a run. It sets the moment on the page for each question and puts back the one that stood there.
FACES = """(() => {
  const keep = S, out = {}, id = { memguard_gib: 8 }, now = 10000;
  const spark = (more = {}) => ({ name: 'a', rank: 0, head: true, live: true, gpu_c: 50, util: 10, mem_free_gb: 60, ...more });
  const moment = (engine, nodes = [spark()], more = {}) => ({ t: 1000, engine, nodes, identity: { interval: 2, memguard_gib: 8 }, why: { own: {} }, ...more });
  S = moment({ state: 'idle' });
  out.core = [{ state: 'writing', tok_s: 312.4, running: 3, waiting: 1 }, { state: 'reading', running: 2, waiting: 1 }, { state: 'reading', running: 1, waiting: 0 }, { state: 'reading', running: null, waiting: 1 },
    { state: 'idle' }, { state: 'asleep' }, { state: 'offline', error: 'Nothing answers on the vLLM port.' }, { state: 'offline', word: 'No record' }].map(e => Object.values(coreFace(e)));
  S = moment({ state: 'offline' }, [spark({ own: { model: 'm', state: 'writing', tok_s: 44, running: 1, waiting: 0 } }), spark({ name: 'b', head: false, own: { model: 'n', state: 'idle', running: 0, waiting: 0 } })]);
  out.tracks = Object.values(coreFace(S.engine));
  out.own = S.nodes.map(n => nodeNote(n, id).text);
  S = moment({ state: 'offline', answers: true }, [spark(), spark({ name: 'b', head: false })], { why: { own: { b: 'a-program' } } });
  out.alone = Object.values(coreFace(S.engine));
  out.runs = nodeNote(S.nodes[1], id).text;
  S = moment({ state: 'idle' });
  out.notes = [spark({ live: false, reason: 'ssh: timed out' }), spark({ live: false }), spark({ latched: true, mhz: 612.4 }), spark({ throttle: ['thermal', 'power'] }), spark({ gpu_c: 85 }),
    spark({ tlimit: 12.4, util: 50 }), spark({ tlimit: 12.4, util: 49 }), spark({ mem_free_gb: 7 }), spark({ mem_free_gb: 9.5 }), spark(), spark({ head: false })].map(n => Object.values(nodeNote(n, id)));
  S = moment({ state: 'idle' }, [spark()], { past: true });
  out.past = [nodeNote(spark({ live: false }), id), (S.loading = true, nodeNote(spark({ live: false }), id))].map(Object.values);
  out.tones = ['bad', 'warn', 'gone', ''].map(toneOf);
  out.time = [{ source: 'none' }, { source: 'none', loading: true }, { source: 'none', past: true }, { source: 'command' }, { source: 'engine', started: now - 90 },
    { source: 'command', started: now - 300, total: 24, done: 0 }, { source: 'command', started: now - 600, total: 24, done: 24 }, { source: 'command', started: now - 600, total: 24, done: 12 }].map(r => runTime(r, now));
  out.around = clock(now + 600);
  S = keep;
  return out;
})()"""


def said_as_ever(got):
    """Holds the answers of FACES against the sentences the main page said before the faces had a file of their own."""
    assert got["core"] == [
        ["Writing", "writing", 312.4, "3 running · 1 waiting"],
        ["Reading the prompt", "reading", None, "3 requests in progress"],
        ["Reading the prompt", "reading", None, "1 request in progress"],
        ["Reading the prompt", "reading", None, "– running · 1 waiting"],  # a count nobody read is no part of a sum
        ["Idle", "idle", None, "ready for requests"],
        ["Asleep", "asleep", None, "weights are unloaded"],
        ["Not serving", "offline", None, "Nothing answers on the vLLM port."],
        ["No record", "offline", None, ""],
    ], got["core"]
    assert got["tracks"] == ["Single tracks", "writing", 44, "1 writing · 1 idle"], got["tracks"]
    assert got["own"] == ["44 tok/s · m", "idle · n"], got["own"]
    alone = "the ring engine answers without its request counters, 1 Spark works on its own"
    assert got["alone"] == ["Not serving", "offline", None, alone], got["alone"]
    assert got["runs"] == "runs a-program", got["runs"]
    assert got["notes"] == [
        ["bad", "Unreachable: ssh: timed out"],
        ["bad", "Unreachable"],
        ["bad", "GPU clock stuck at 612 MHz"],
        ["warn", "Slowing down: thermal, power"],
        ["warn", "Running hot"],
        ["warn", "12 °C from the thermal limit"],
        ["", "head"],  # near its limit and not busy: nothing to say
        ["warn", "Below the 8 GB memory guard"],
        ["warn", "Near the 8 GB memory guard"],
        ["", "head"],
        ["", "worker"],
    ], got["notes"]
    assert got["past"] == [["gone", "no reading at this moment"], ["gone", "loading this moment"]], got["past"]
    assert got["tones"] == ["var(--rose)", "var(--amber)", "var(--faint)", "var(--teal)"], got["tones"]
    assert got["time"] == [
        "Requests and queued runs show up here.",
        "Loading this moment.",
        "No run was recorded at this moment.",
        "",
        "Running for 90 s",
        "5 min in",
        "10 min in",
        f"10 min in, about 10 min left, done around {got['around']}",  # the time of day as this machine writes it
    ], got["time"]


@needs_node
def test_the_core_a_spark_and_a_run_say_on_the_main_page_what_they_always_said():
    """The word and the line of the core, the one line a Spark says about itself and the line of a run, asked on the
    main page as it stands with all its scripts: every sentence as it was before the faces moved into a file of
    their own."""
    said_as_ever(sheet([FACES])[0])


@needs_node
def test_the_faces_say_the_same_without_the_main_page():
    """The calm page for a wall shows the same core, Sparks and run as the main page and must not say them in words
    of its own. So what says them stands in one script, page/faces.js, on nothing but the base, the rules and the
    neutral lens: asked there without a document, a scene or a view, every sentence is the one of the main page."""
    said_as_ever(page_faces("return " + FACES))


def test_no_other_script_of_the_page_says_what_the_faces_say():
    """What moved is gone from where it stood: a second copy in the script it came from would go its own way with the
    next change of a word, and the two pages would say two things."""
    moved = ("coreFace", "nodeNote", "runTime", "lensed", "toggleNames", "keptNames", "ownWork", "toneOf")
    faces = (PAGE.parent / "faces.js").read_text()
    for name in moved:
        assert f"function {name}(" in faces or f"const {name} = " in faces, name
        for other in ("main.js", "vitals.js", "dock.js", "run.js", "hover.js"):
            text = (PAGE.parent / other).read_text()
            assert f"function {name}(" not in text and f"const {name} = " not in text, (name, other)


@needs_node
def test_the_neutral_lens_is_asked_for_and_works_without_the_main_page():
    """Whether the Sparks go by neutral names is read from the address where the faces stand, and a moment goes
    through the same lens on both pages: as it came without the wish, under neutral names with it; and the lens
    keeps which cluster the moment came from by the names the server sent, with the Spark that is its head."""
    moment = (
        "const s = { cluster: { ring: true, nodes: [{ name: 'dgx0', rank: 0, head: true }] }, identity: {},"
        " engine: { state: 'idle' }, nodes: [{ name: 'dgx0', rank: 0, live: true }], why: { own: {} },"
        " run: { source: 'none' } }, seen = lensed(s);"
        " return [NEUTRAL, seen === s, seen.nodes[0].name, seen.cluster.nodes[0].name, cameAs];"
    )
    assert page_faces(moment) == [False, True, "dgx0", "dgx0", "true0dgx0 head"]
    assert page_faces(moment, "?names=neutral") == [True, False, "spark-1", "spark-1", "true0dgx0 head"]
