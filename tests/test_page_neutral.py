"""The neutral lens of the page, run through node: with neutral names, nothing of the outside is left in what the
page takes in."""

from tests.fixtures import needs_node
from tests.test_page_measure import measure

MOMENT = """
const moment = { t: 100, cluster: { ring: true, nodes: [{ name: 'dgx-alpha', rank: 0, head: true }, { name: 'dgx-beta', rank: 1 },
    { name: 'dgx-gamma', rank: 2 }, { name: 'dgx-delta', rank: 3 }] },
  identity: { model: 'm-1', image: 'img:1', kernel: '7.0.0-1019-nvidia-64k', config: 'config/lab.local.json', page_kb: 64, interval: 2 },
  engine: { state: 'offline', error: 'Nothing answers on the vLLM port.' },
  nodes: [{ name: 'dgx-alpha', rank: 0, head: true, live: true, reason: null, w: 20.5, fans: [2600, 2610],
      apps: [{ gb: 84.4, name: 'VLLM::EngineCore' }], top: [{ gb: 3.7, name: 'dockerd' }], threads: [{ name: 'gloo_tcp_loop', pct: 3 }],
      key_threads: [{ name: 'pt_main' }], intruders: ['backupd'],
      box: { name: 'solo-x', id: 'c5c7', running: true, model: 'mistral', args: 'serve /models/x --port 8001' },
      own: { model: 'mistral', state: 'writing', tok_s: 30 } },
    { name: 'dgx-beta', rank: 1, head: false, live: false, reason: 'ssh: connect to host dgx-beta port 22: Connection refused' },
    { name: 'dgx-gamma', rank: 2, live: true, apps: [{ gb: 84.2, name: 'sglang::scheduler' }],
      box: { name: 'spark-ds41f', running: false, model: 'deepseek' } },
    { name: 'dgx-delta', rank: 3, live: true, box: { name: 'solo-y', running: true, model: null },
      own: { model: 'solo-y', state: 'writing', tok_s: 12 } }],
  edges: [{ from: 0, to: 1, group: 'f0', gbps: 1.5, up: true }],
  events: [{ t: 1, node: 'dgx-beta', kind: 'node', text: 'Unreachable: ssh: connect to host dgx-beta port 22: Connection refused', level: 'bad' },
    { t: 2, node: 'dgx-alpha', kind: 'kernel', text: 'NVRM: Xid (PCI:000f:01:00): 79, pid=4242, name=python', level: 'bad' },
    { t: 3, node: 'dgx-alpha', kind: 'memguard', text: 'low headroom during steady: 8 GB left', level: 'warn' },
    { t: 4, node: 'dgx-alpha', kind: 'engine', text: 'Own engine answers: mistral', level: 'info' },
    { t: 5, node: null, kind: 'cooling', text: 'Start of x: fans 2,600 RPM, warmest sensor 70 °C on dgx-alpha', level: 'info' },
    { t: 6, node: 'dgx-beta', kind: 'node', text: 'Reachable again', level: 'info' },
    { t: 7, node: 'dgx-delta', kind: 'engine', text: 'Own engine answers: solo-y', level: 'info' }],
  why: { headline: 'The ring engine is not serving; 3 of 4 Sparks are working on their own.',
    own: { 'dgx-alpha': 'mistral', 'dgx-gamma': 'sglang::scheduler', 'dgx-delta': 'solo-y' },
    points: [{ level: 'bad', text: 'Nothing answers on the vLLM port.' },
      { level: 'info', text: 'dgx-alpha runs mistral on its own: 30 tokens/s.', node: 'dgx-alpha' },
      { level: 'bad', text: 'dgx-beta is unreachable.', node: 'dgx-beta' },
      { level: 'info', text: 'dgx-gamma runs sglang::scheduler on its own: GPU 96 % busy, 84.2 GB on the GPU.', node: 'dgx-gamma' },
      { level: 'info', text: 'dgx-delta runs solo-y on its own: 12 tokens/s, 1 running, GPU 96 % busy.', node: 'dgx-delta' }] },
  run: { source: 'command', name: 'Single tracks', detail: '/home/user/x.py failed',
    tracks: [{ node: 'dgx-alpha', model: 'mistral', name: 'Job A', done: 1, total: 2 }] },
  history: { 'dgx-alpha.fan': [[1, 2], [2600, 2610]], 'dgx-alpha.f0.tx': [[1], [0.5]], 'engine.tok_s': [[1], [30]] } };
const pairs = [...aliasPairs(moment.cluster), ...workNames(moment)];
"""
OUTSIDE = (
    "dgx-",
    "VLLM",
    "solo-y",
    "ds41f",
    "lab.local",
    "nvidia-64k",
    "port 22",
    "Xid",
    "low headroom",
    "dockerd",
    "sglang",
    "solo-x",
    "gloo",
    "pt_main",
    "backupd",
    "/home/user",
    "8001",
)


@needs_node
def test_with_neutral_names_nothing_of_the_outside_is_left_in_a_moment():
    """The names of the Sparks become spark-1 to spark-N everywhere, also as keys and inside sentences. And what the
    outside wrote word for word is gone: kernel and profile, the last words of ssh, lines of the journal, the names
    of programs, the container, the detail of a run and the names a run source gave it. What a Spark works on keeps
    its name where that is a model: the name of a container or of a program gives way to neutral words, wherever it
    stands. Every reading stays."""
    got = measure(
        MOMENT
        + "const before = JSON.stringify(moment), out = neutralState(moment, pairs);"
        + "return { text: JSON.stringify(out), same: JSON.stringify(moment) === before, pairs, out };"
    )
    assert [word for word in OUTSIDE if word in got["text"]] == []
    assert got["same"]  # the moment as it came is not touched
    assert got["pairs"] == [
        ["dgx-alpha", "spark-1"],
        ["dgx-beta", "spark-2"],
        ["dgx-gamma", "spark-3"],
        ["dgx-delta", "spark-4"],
        ["sglang::scheduler", "a program"],  # the biggest program on a GPU: no engine of its own answers there
        ["solo-y", "an engine"],  # a container that was told no name to serve under: the server names the container
    ], got["pairs"]
    out = got["out"]
    names = ["spark-1", "spark-2", "spark-3", "spark-4"]
    assert [n["name"] for n in out["cluster"]["nodes"]] == names == [n["name"] for n in out["nodes"]]
    assert out["why"]["own"] == {"spark-1": "mistral", "spark-3": "a program", "spark-4": "an engine"}, out["why"][
        "own"
    ]
    assert [[p.get("node"), p["text"]] for p in out["why"]["points"]] == [
        [None, "Nothing answers on the vLLM port."],
        ["spark-1", "spark-1 runs mistral on its own: 30 tokens/s."],
        ["spark-2", "spark-2 is unreachable."],
        ["spark-3", "spark-3 runs a program on its own: GPU 96 % busy, 84.2 GB on the GPU."],
        ["spark-4", "spark-4 runs an engine on its own: 12 tokens/s, 1 running, GPU 96 % busy."],
    ], out["why"]["points"]
    assert out["run"] == {
        "source": "command",
        "name": "Test run",
        "detail": None,
        "group": None,
        "holder": None,
        "until": None,
        "tracks": [{"node": "spark-1", "model": "mistral", "name": "Test run", "done": 1, "total": 2}],
    }, out["run"]
    assert out["history"] == {
        "spark-1.fan": [[1, 2], [2600, 2610]],
        "spark-1.f0.tx": [[1], [0.5]],
        "engine.tok_s": [[1], [30]],
    }, out["history"]
    assert [[e["t"], e["node"], e["kind"], e["level"], e["text"]] for e in out["events"]] == [
        [1, "spark-2", "node", "bad", "Unreachable"],
        [2, "spark-1", "kernel", "bad", "Kernel error, text not shown"],
        [3, "spark-1", "memguard", "warn", "Memory guard message, text not shown"],
        [4, "spark-1", "engine", "info", "Own engine answers: mistral"],
        [5, None, "cooling", "info", "Start of x: fans 2,600 RPM, warmest sensor 70 °C on spark-1"],
        [6, "spark-2", "node", "info", "Reachable again"],
        [7, "spark-4", "engine", "info", "Own engine answers: an engine"],
    ], out["events"]
    assert out["identity"] == {
        "model": "m-1",
        "image": "img:1",
        "kernel": None,
        "config": None,
        "page_kb": 64,
        "interval": 2,
    }, out["identity"]
    first, second, third, fourth = out["nodes"]
    assert third["apps"] == [{"gb": 84.2}] and third["box"] is None and fourth["box"] is None, (third, fourth)
    assert fourth["own"] == {"model": "an engine", "state": "writing", "tok_s": 12}, fourth
    assert first["apps"] == [{"gb": 84.4}] and first["top"] == [] and first["box"] is None, first
    assert first["threads"] == [] and first["key_threads"] == [] and first["intruders"] == [], first
    assert first["own"] == {"model": "mistral", "state": "writing", "tok_s": 30} and first["fans"] == [2600, 2610]
    assert first["w"] == 20.5 and first["live"] is True and second["live"] is False and second["reason"] is None
    # one of the server's own sentences, never the words of an exception: it stays
    assert out["engine"] == {"state": "offline", "error": "Nothing answers on the vLLM port."}, out["engine"]
    assert out["edges"] == [{"from": 0, "to": 1, "group": "f0", "gbps": 1.5, "up": True}], out["edges"]


@needs_node
def test_a_spark_named_like_a_word_of_the_page_does_not_change_that_word():
    """A Spark may be called node or run. The kind of an event, the source of a run and the state of an engine are
    words the page works with: they are not names, whatever they spell."""
    got = measure(
        "const s = { cluster: { nodes: [{ name: 'node', rank: 0 }, { name: 'run', rank: 1 }] }, identity: {},"
        " nodes: [{ name: 'node', live: true, own: { state: 'idle' } }, { name: 'run', live: true }], engine: { state: 'idle' },"
        " run: { source: 'history', name: 'run of node' }, why: { headline: 'x', points: [], own: {} },"
        " events: [{ t: 1, node: 'node', kind: 'node', text: 'Reachable again', level: 'info' },"
        " { t: 2, node: null, kind: 'run', text: 'Started: bench', level: 'info' }] };"
        "const out = neutralState(s, aliasPairs(s.cluster));"
        "return [out.events.map(e => [e.kind, e.node]), out.run, out.nodes.map(n => n.name), out.nodes[0].own.state];"
    )
    assert got == [
        [["node", "spark-1"], ["run", None]],
        {"source": "history", "name": "spark-2 of spark-1", "detail": None},
        ["spark-1", "spark-2"],
        "idle",
    ], got


@needs_node
def test_every_name_is_replaced_once_and_only_as_a_whole_name():
    """spark-1 is no part of spark-1c9d, of myspark-1 or of spark-1-old. And two Sparks whose real names are each
    other's neutral ones are swapped, not both turned into one."""
    got = measure(
        "const prefix = renamer([['spark-1c9d', 'spark-1'], ['spark-1', 'spark-2']]);"
        "const swap = renamer([['spark-2', 'spark-1'], ['spark-1', 'spark-2']]);"
        "return [prefix('spark-1c9d, spark-1 and myspark-1 or spark-1-old; spark-1.fan spark-1c9d.f0.tx'),"
        " swap('spark-2 before spark-1, spark-1.w'), renamer([['a.b', 'spark-1']])('axb a.b a.b.w'),"
        " renamer([])('spark-1 stays'), prefix('spark-1'), prefix('')];"
    )
    assert got == [
        "spark-1, spark-2 and myspark-1 or spark-1-old; spark-2.fan spark-1.f0.tx",
        "spark-1 before spark-2, spark-2.w",
        "axb spark-1 spark-1.w",
        "spark-1 stays",
        "spark-2",
        "",
    ], got


@needs_node
def test_the_history_is_asked_under_the_names_the_server_keeps():
    """The page builds the keys of its traces from the names it shows. The server keeps them under the real ones."""
    got = measure(
        "const prefix = [['spark-1c9d', 'spark-1'], ['spark-1', 'spark-2']], swap = [['spark-2', 'spark-1'], ['spark-1', 'spark-2']];"
        "return [realKeys(['spark-1.fan', 'spark-2.f0.tx', 'engine.tok_s', 'spark-1.zone.TGPU'], prefix),"
        " realKeys(['spark-1.w', 'spark-2.w'], swap), realKeys([], prefix)];"
    )
    assert got == [
        ["spark-1c9d.fan", "spark-1.f0.tx", "engine.tok_s", "spark-1c9d.zone.TGPU"],
        ["spark-2.w", "spark-1.w"],
        [],
    ], got


@needs_node
def test_with_neutral_names_a_run_keeps_its_figures_and_loses_every_name_a_run_source_wrote():
    """The run board shows what a run source outside of ringtop wrote: the name of the run, of its queue, of its
    steps and of the job on every track, who holds the ring and until when. With neutral names each of them gives way
    to "Test run" or is left out, also in the events that say a run started or finished. How far a run is, since
    when it runs, the state of every step and the model of a track stay. A run ringtop names itself stays as it is."""
    got = measure(
        "const cluster = { nodes: [{ name: 'dgx-alpha', rank: 0 }, { name: 'dgx-beta', rank: 1 }] }, pairs = aliasPairs(cluster);"
        "const state = run => ({ cluster, identity: {}, nodes: [], events: ["
        " { t: 1, node: null, kind: 'run', text: 'Started: Job A, round 9', level: 'info' },"
        " { t: 2, node: null, kind: 'run', text: 'Finished: Job C', level: 'info' },"
        " { t: 3, node: null, kind: 'run', text: 'Queue 8 paused', level: 'info' },"
        " { t: 4, node: null, kind: 'engine', text: 'Serving again', level: 'info' }], run });"
        "const command = { source: 'command', name: 'Job A, round 9', group: 'Queue 8', holder: 'Lab window',"
        " until: 'until Tuesday', done: 3, total: 9, started: 50, has_replies: true, detail: '/x.py', mode: 'nightly',"
        " steps: [{ name: 'Job C', state: 'done', seconds: 12, was: 10 },"
        " { name: 'Job A, round 9', state: 'running' }, { name: 'Job D', state: 'pending', was: 30 },"
        " { name: 'Follow-up', state: 'special', seconds: 'long' }],"
        " tracks: [{ node: 'dgx-alpha', model: 'mistral', name: 'Job B v2', done: 1, total: 30, started: 60 },"
        " { node: 'dgx-beta', model: 'model-65b' }, { node: 'Mac mini', model: 'm', name: 'Job E', done: 'three' }] };"
        "const lab = { source: 'lab', name: 'job-a', steps: [{ name: 'job-a', state: 'running' }], holder: 'lab-user',"
        " until: '22:00' };"
        "const own = [{ source: 'engine', name: 'Serving requests', started: 5 }, { source: 'none' },"
        " { source: 'process', name: 'Benchmark running', detail: 'servebench', started: 7 }];"
        "const out = neutralState(state(command), pairs);"
        "return [out.run, out.events.map(e => e.text), neutralState(state(lab), pairs).run,"
        " own.map(run => neutralState(state(run), pairs).run),"
        " neutralHistory({ t: [], series: {}, events: state(null).events }, pairs, pairs).events.map(e => e.text)];"
    )
    run, events, lab, own, past = got
    assert run == {
        "source": "command",
        "name": "Test run",
        "group": None,
        "holder": None,
        "until": None,
        "detail": None,
        "done": 3,
        "total": 9,
        "started": 50,
        "has_replies": True,
        "steps": [
            {"name": "Test run 1", "state": "done", "seconds": 12, "was": 10},
            {"name": "Test run 2", "state": "running"},
            {"name": "Test run 3", "state": "pending", "was": 30},
            {"name": "Test run 4"},  # a state the page does not know and a time that is no number do not pass
        ],
        "tracks": [
            {"node": "spark-1", "model": "mistral", "name": "Test run", "done": 1, "total": 30, "started": 60},
            {"node": "spark-2", "model": "model-65b"},
            {"model": "m", "name": "Test run"},  # a track on a machine that is no Spark of this cluster
        ],
    }, run  # `mode`, a field the page does not know, does not pass either
    assert events == ["Started: Test run", "Finished: Test run", "Test run", "Serving again"] == past, (events, past)
    assert lab == {
        "source": "lab",
        "name": "Test run",
        "group": None,
        "holder": None,
        "until": None,
        "detail": None,
        "steps": [{"name": "Test run 1", "state": "running"}],
    }, lab
    assert own == [
        {"source": "engine", "name": "Serving requests", "started": 5, "detail": None},
        {"source": "none", "detail": None},
        {"source": "process", "name": "Benchmark running", "detail": None, "started": 7},
    ], own


@needs_node
def test_a_stretch_of_the_history_comes_back_under_neutral_names():
    """Every trace under its neutral key, the events like those of a moment, and nothing added that was not asked
    for: an answer without a band has none afterwards either."""
    got = measure(
        "const pairs = [['dgx-alpha', 'spark-1'], ['dgx-beta', 'spark-2']];"
        "const answer = { t: [1, 2], tier: 'raw', width: 2, series: { 'dgx-alpha.fan': [2600, null], 'engine.tok_s': [3, 4] },"
        " peak: { 'dgx-alpha.fan': [2610, null] }, low: { 'dgx-beta.w': [1, 2] }, n: { 'dgx-beta.w': [30, 30] },"
        " events: [{ t: 1, node: 'dgx-beta', kind: 'kernel', text: 'NVRM: Xid 79 on dgx-beta', level: 'bad' },"
        " { t: 2, node: null, kind: 'run', text: 'Started: bench on dgx-alpha', level: 'info' }] };"
        "const before = JSON.stringify(answer);"
        "const bare = neutralHistory({ t: [1], tier: 'minute', width: 60, series: { 'dgx-alpha.w': [5] }, peak: {} }, pairs, pairs);"
        "return [neutralHistory(answer, pairs, pairs), bare, Object.keys(bare).sort(), JSON.stringify(answer) === before];"
    )
    out, bare, keys, untouched = got
    assert out == {
        "t": [1, 2],
        "tier": "raw",
        "width": 2,
        "series": {"spark-1.fan": [2600, None], "engine.tok_s": [3, 4]},
        "peak": {"spark-1.fan": [2610, None]},
        "low": {"spark-2.w": [1, 2]},
        "n": {"spark-2.w": [30, 30]},
        "events": [
            {"t": 1, "node": "spark-2", "kind": "kernel", "text": "Kernel error, text not shown", "level": "bad"},
            {"t": 2, "node": None, "kind": "run", "text": "Started: Test run", "level": "info"},
        ],
    }, out
    assert bare == {"t": [1], "tier": "minute", "width": 60, "series": {"spark-1.w": [5]}, "peak": {}}, bare
    assert keys == ["peak", "series", "t", "tier", "width"] and untouched, (keys, untouched)


@needs_node
def test_neutral_names_are_on_when_the_address_or_the_kept_choice_says_so():
    """And a link to one Spark finds it under its neutral name and under its real one; where a name is both, the
    neutral one counts, since that is what the page shows."""
    got = measure(
        "const asked = ['?names=neutral', '?x=1&names=neutral', '?names=neutral&y=2', '', '?names=neutralx',"
        " '?xnames=neutral', '?names=real', undefined];"
        "const pairs = [['dgx-alpha', 'spark-1'], ['spark-1', 'spark-2']];"
        "return [asked.map(a => neutralWanted(a, null)), neutralWanted('', 'neutral'), neutralWanted('', 'real'),"
        " neutralWanted('?names=neutral', 'real'), ['spark-1', 'dgx-alpha', 'spark-2', 'nobody'].map(n => nodeAlias(n, pairs))];"
    )
    assert got == [
        [True, True, True, False, False, False, False, False],
        True,
        False,
        True,
        ["spark-1", "spark-1", "spark-2", "nobody"],
    ], got


@needs_node
def test_an_event_is_told_apart_by_the_words_it_came_with_not_by_the_renamed_ones():
    """A Spark may be called like the first word the page tells an event by. Renamed first, the outage of a Spark
    called Unreachable began with its neutral name, was no outage any more and kept the last words of ssh; and with
    a Spark called Started, a run that started only said "Test run". An event is told apart as it came, and the
    sentence the page puts in its place is not renamed afterwards."""
    got = measure(
        "const state = name => ({ cluster: { nodes: [{ name, rank: 0 }] }, identity: {}, nodes: [{ name, live: false }],"
        " why: { own: {} }, events: ["
        " { t: 1, node: name, kind: 'node', text: `Unreachable: ssh: connect to host ${name} port 22: Connection refused`, level: 'bad' },"
        " { t: 2, node: null, kind: 'run', text: 'Started: bench', level: 'info' },"
        " { t: 3, node: name, kind: 'engine', text: `Own engine answers: m on ${name}`, level: 'info' }] });"
        "const texts = name => { const s = state(name), pairs = aliasPairs(s.cluster);"
        " return [neutralState(s, pairs).events, neutralHistory({ t: [], series: {}, events: s.events }, pairs, pairs).events]"
        ".map(list => list.map(e => [e.node, e.text])); };"
        "return [texts('Unreachable'), texts('Started'), texts('dgx-alpha')];"
    )
    events = [["spark-1", "Unreachable"], [None, "Started: Test run"], ["spark-1", "Own engine answers: m on spark-1"]]
    assert got == [[events, events]] * 3, got


@needs_node
def test_a_spark_called_like_something_every_object_has_gets_its_neutral_name():
    """What each Spark works on is kept by its name. Asked for a Spark called constructor or toString, an object
    answers with what every object has: a function. That was taken for the name of a program, and the lens threw.
    Only what the server put there under the name counts, and only a text is a name."""
    got = measure(
        "const s = { cluster: { nodes: [{ name: 'constructor', rank: 0 }, { name: 'toString', rank: 1 }] }, identity: {},"
        " nodes: [{ name: 'constructor', live: true }, { name: 'toString', live: true, own: { model: 7 } }],"
        " why: { own: {}, points: [] }, events: [] };"
        "const work = workNames(s), out = neutralState(s, [...aliasPairs(s.cluster), ...work]);"
        "return [work, out.nodes.map(n => n.name), out.cluster.nodes.map(n => n.name)];"
    )
    assert got == [[], ["spark-1", "spark-2"], ["spark-1", "spark-2"]], got


@needs_node
def test_what_a_spark_works_on_never_takes_the_place_of_a_spark():
    """A Spark called worker runs an engine that answers as worker, and its container was told no name to serve
    under. The name went on the list a second time, as what a Spark works on, and the later entry won: the Spark
    itself was shown as "an engine". The name of a Spark of this cluster is never the name of its work."""
    got = measure(
        "const s = { cluster: { nodes: [{ name: 'worker', rank: 0 }, { name: 'dgx-b', rank: 1 }] }, identity: {},"
        " nodes: [{ name: 'worker', live: true, own: { model: 'worker', state: 'writing' } },"
        " { name: 'dgx-b', live: true, own: { model: 'solo-y' } }],"
        " why: { own: { worker: 'worker', 'dgx-b': 'solo-y' }, points: [] }, events: [] };"
        "const work = workNames(s), out = neutralState(s, [...aliasPairs(s.cluster), ...work]);"
        "return [work, out.nodes.map(n => n.name), out.cluster.nodes.map(n => n.name), Object.keys(out.why.own)];"
    )
    names = ["spark-1", "spark-2"]
    assert got == [[["solo-y", "an engine"]], names, names, names], got


@needs_node
def test_a_key_is_renamed_only_where_it_names_a_spark():
    """A trace is kept under NAME.reading, what a Spark works on under NAME. A Spark may be called like a reading:
    with a Spark called running, the engine's own trace engine.running came back as engine.spark-1, and nobody found
    the curve that was asked for. Only the name a key begins with is replaced, and only that of a Spark, which may
    hold dots itself; the way back to the names the server keeps goes the same way."""
    got = measure(
        "const one = [['running', 'spark-1']], dotted = [['dgx1.local', 'spark-1'], ['dgx1', 'spark-2']];"
        "const swap = [['spark-2', 'spark-1'], ['box-a', 'spark-2']];"
        "const answer = keys => ({ t: [1], series: Object.fromEntries(keys.map(k => [k, [1]])) });"
        "const there = (keys, pairs) => Object.keys(neutralHistory(answer(keys), pairs, pairs).series);"
        "const state = { cluster: { nodes: [{ name: 'running', rank: 0 }] }, identity: {}, nodes: [{ name: 'running', live: true }],"
        " why: { own: { running: 'm' }, points: [] }, events: [],"
        " history: { 'engine.running': [[1], [2]], 'running.gpu_c': [[1], [60]] } };"
        "const out = neutralState(state, one);"
        "return [there(['engine.running', 'running.gpu_c', 'running.running'], one),"
        " realKeys(['engine.running', 'spark-1.gpu_c', 'spark-1.running'], one),"
        " there(['dgx1.local.gpu_c', 'dgx1.gpu_c', 'other.w'], dotted), realKeys(['spark-1.gpu_c', 'spark-2.gpu_c'], dotted),"
        " there(['spark-2.w', 'box-a.w', 'box-a'], swap), realKeys(['spark-1.w', 'spark-2.w', 'spark-2'], swap),"
        " Object.keys(out.history), Object.keys(out.why.own)];"
    )
    assert got == [
        ["engine.running", "spark-1.gpu_c", "spark-1.running"],
        ["engine.running", "running.gpu_c", "running.running"],
        ["spark-1.gpu_c", "spark-2.gpu_c", "other.w"],
        ["dgx1.local.gpu_c", "dgx1.gpu_c"],
        ["spark-1.w", "spark-2.w", "spark-2"],
        ["spark-2.w", "box-a.w", "box-a"],
        ["engine.running", "spark-1.gpu_c"],
        ["spark-1"],
    ], got
