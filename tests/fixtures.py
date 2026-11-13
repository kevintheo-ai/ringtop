"""What the checks share: a made-up ring, a hub without network, the sampler's functions, the rules of the page."""

import collections
import contextlib
import http.client
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

from ringtop_parts.connect import shell
from ringtop_parts.connect.server import PAGE, PAGE_PARTS, Handler, Listener
from ringtop_parts.core.cluster import parse_cluster
from ringtop_parts.core.demo import Demo
from ringtop_parts.core.hub import Hub


class NoStderr(io.TextIOBase):
    """A stderr nothing can be written to: the disk under the log of the service is full, or nobody reads the pipe
    any more."""

    def write(self, text):
        raise OSError(28, "No space left on device")


def ring_map(two_rails=False):
    nodes = []
    for i in range(4):
        nxt, prev = (i + 1) % 4, (i - 1) % 4
        nodes.append(
            {
                "name": f"dgx{i}",
                "rank": i,
                "head": i == 0,
                "roce_peer_hcas": {
                    str(nxt): ["rocep1s0f0"] + (["roceP2p1s0f0"] if two_rails else []),
                    str(prev): ["rocep1s0f1"] + (["roceP2p1s0f1"] if two_rails else []),
                },
            }
        )
    return {"ssh_user": "user", "nodes": nodes}


def hub_for(node_map=None, interval=2.0):
    hub = Hub(parse_cluster(node_map or ring_map()), interval)
    hub.engine_error = None  # the head has reported in
    return hub


def counters(tx, rx=0, err=0, up=True):
    return {"tx": tx, "rx": rx, "up": up, "rate": 200.0, "err": err}


def engine_sample(t, generated, running=1.0, waiting=0.0, **extra):
    return {
        "t": t,
        "engine": {
            "num_requests_running": running,
            "num_requests_waiting": waiting,
            "generation_tokens_total": generated,
            "iteration_tokens_total_count": generated / 3,
            "iteration_tokens_total_sum": generated,
            **extra,
        },
        "hist": {},
        "engine_error": None,
    }


def sampler_namespace():
    """The sampler's functions, without its main loop or the nvidia-smi thread: every part but the last, run in one
    namespace as a node runs them, with the arguments ringtop gives a worker."""
    text = shell.program(shell.SAMPLER_PARTS[:-1])
    start = "threading.Thread(target=gpu_loop, daemon=True).start()\n"
    assert text.count(start) == 1, "the line that starts the nvidia-smi thread moved or changed"
    namespace, argv = {}, sys.argv
    sys.argv = ["-", "1.0", "worker", "auto", "-"]
    try:
        exec(compile(text.replace(start, ""), "sampler", "exec"), namespace)
    finally:
        sys.argv = argv
    return namespace


def slow_files(namespace, files, clock, step=0.25):
    """Stands in for the files the sampler's readers open: `files` maps a path to its text, and each file takes
    `step` seconds of `clock` (a list of one moment, which `time.time()` of the namespace gives back), so what is
    read later is read later. A path `files` does not hold is no file. Gives back the moment each path was first
    opened."""
    opened = {}

    def slow_open(path, *args, **kwargs):
        if path not in files:
            raise FileNotFoundError(path)
        opened.setdefault(path, clock[0])
        clock[0] += step
        return io.StringIO(files[path])

    namespace["open"], namespace["time"] = slow_open, types.SimpleNamespace(time=lambda: clock[0])
    return opened


def serve_metrics(namespace, text):
    class Reply:
        length = None  # it names no length: the answer ends where the stand-in says so

        def __init__(self):
            self.left = [text.encode()]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return text.encode()

        def read1(self, size=-1):  # the answer in one piece, then its end
            return self.left.pop() if self.left else b""

    namespace["urllib"] = types.SimpleNamespace(request=types.SimpleNamespace(urlopen=lambda *a, **k: Reply()))


def needs_node(check):
    """The rules of the page run through node. Without node the check is skipped, like the syntax check of the page;
    with node nothing is skipped, whatever the rules give back."""

    def run():
        if shutil.which("node"):
            check()

    run.__name__, run.__doc__ = check.__name__, check.__doc__
    return run


def page_rules(script: str):
    """Runs the rules of the page through node and gives back what `script` returns.

    The rules are the file page/rules.js, the very file the server sends: plain functions that decide what the page
    may claim. They run here on their own, so a rule that reached for the page or the scene would fail."""
    rules = (PAGE.parent / "rules.js").read_text()
    assert rules.split("\n")[1] == "'use strict';" and "function tracksOf" in rules, "the page lost its rules"
    source = rules + "\nconsole.log(JSON.stringify((() => {" + script + "})()));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js") as file:
        file.write(source)
        file.flush()
        done = subprocess.run(["node", file.name], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout)


def page_faces(script: str, search: str = ""):
    """Runs the faces of the page through node and gives back what `script` returns.

    The faces are the file page/faces.js on what it stands on (base.js, rules.js, neutral.js), the very files the
    server sends, and nothing else of the page: no document, no scene, no view. A face that reached for the main
    page would fail here. `search`: what stands behind the "?" of the address the page is opened with."""
    world = (
        "'use strict';\nconst window = globalThis, matchMedia = () => ({ matches: false }),"
        f" location = {{ search: {json.dumps(search)}, pathname: '/wall', hash: '' }};\n"
    )
    files = [(PAGE.parent / name).read_text() for name in ("base.js", "rules.js", "neutral.js", "faces.js")]
    source = world + "\n".join(files) + "\nconsole.log(JSON.stringify((() => {" + script + "})()));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js") as file:
        file.write(source)
        file.flush()
        done = subprocess.run(["node", file.name], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout)


LOOK_BACK = """
const live = { t: 1000, cluster: { ring: true, nodes: [{ name: 'a', rank: 0, head: true }, { name: 'b', rank: 1 }] },
  identity: { interval: 2, model: 'today-model', vllm: '9.9', config: 'today-profile', memguard_gib: 8 },
  nodes: [{ name: 'a', live: true, mem_total_gb: 128, w_limit: 140, throttle: ['thermal'], w: 99 }, { name: 'b', live: true, mem_total_gb: 128, w_limit: 140, throttle: [], w: 98 }],
  edges: [{ from: 0, to: 1, group: 'p0', capacity: 200, gbps: 7, rx: 6, up: false, errors: true }] };
const got = { t: [100, 102, 104, 110], tier: 'raw', from: 90, to: 120,
  series: { 'engine.tok_s': [50, 51, 52, 60], 'engine.running': [1, 1, 1, 2], 'a.w': [10, null, 12, 20], 'a.p0.tx': [1, 2, 3, 4], 'a.p0.rx': [5, 6, 7, 8] },
  events: [{ t: 103, kind: 'run', text: 'Started: bench', level: 'info' }, { t: 109, kind: 'run', text: 'Finished: bench', level: 'info' }] };
"""


TRACKS = """
const node = (name, own, more = {}) => ({ name, live: true, own, ...more });
const writing = (tok_s, more = {}) => ({ model: 'm', state: 'writing', tok_s, running: 1, waiting: 0, ttft_p95: 1.5, ...more });
const alone = (nodes, more = {}) => ({ engine: { state: 'offline' }, nodes, why: { own: {} }, run: { source: 'none' }, ...more });
"""


def docker_answers(namespace, items):
    """`docker ps -a` and `docker inspect` as the sampler sees them, from a list of inspect items."""

    def run(cmd, **_):
        if cmd[:2] == ["docker", "ps"]:
            return types.SimpleNamespace(stdout="\n".join(i["Name"].lstrip("/") for i in items), returncode=0)
        if cmd[:2] == ["docker", "inspect"]:
            return types.SimpleNamespace(stdout=json.dumps(items), returncode=0)
        return types.SimpleNamespace(stdout="", returncode=1)

    namespace["subprocess"] = types.SimpleNamespace(run=run)


def solo_box(ports, args=("serve", "/models/mistral", "--served-model-name", "mistral-small-4"), **changes):
    """One vLLM container as `docker inspect` shows it, started like a single track."""
    item = {
        "Name": "/solo-mistral",
        "Id": "6bd435914533",
        "Image": "sha256:befccf0e7e4089aa",
        "Args": list(args),
        "State": {"Running": True, "Status": "running", "StartedAt": "2026-11-09T18:41:35.5Z"},
        "Config": {"Image": "vllm/vllm-openai:v0.32.0", "Labels": {}, "Env": []},
        "HostConfig": {"CpusetCpus": ""},
        "NetworkSettings": {"Ports": ports},
    }
    for key, value in changes.items():
        item[key] = {**item[key], **value} if isinstance(item.get(key), dict) else value
    return item


def own_reading(generated, running=1.0, waiting=0.0, model="mistral-small-4", **extra):
    engine = engine_sample(0, generated, running, waiting, **extra)["engine"]
    return {"model": model, "name": "solo-mistral", "engine": engine, "hist": {}}


def canon(value):
    """A value as plain JSON, the same on every machine: floats rounded to six places, keys and sets in order."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {str(k): canon(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (set, frozenset)):
        return [canon(v) for v in sorted(value)]
    if isinstance(value, (list, tuple, collections.deque)):
        return [canon(v) for v in value]
    return value


class Ticks:
    """Stands in for the halt event of the demo: every wait is one tick of a made-up clock, and after `left` of them
    the round ends. `each()` runs once per tick, after all nodes have reported."""

    def __init__(self, clock, left, each):
        self.clock, self.left, self.each = clock, left, each

    def is_set(self):
        return self.left <= 0

    def wait(self, seconds):
        self.each()
        self.clock[0] += seconds
        self.left -= 1


def demo_round(
    ticks, interval=2.0, at=0.0, start=1_800_000_000.0, seen=None, each=None, faults=False, node_map=None, form="ring4"
):
    """A hub the demo has fed for so many ticks, in this thread and by a made-up clock that starts at `start`.

    `seen(name, sample)` hears every sample before the hub does, `each(hub)` runs after every tick. While it runs,
    time.time() is the made-up clock for the whole process. `faults`: the round as --demo-faults plays it.
    `node_map` and `form`: another made-up cluster than the ring of the checks (core/demo_forms.py)."""
    clock, real = [start], time.time
    hub = Hub(parse_cluster(node_map or ring_map()), interval)
    ingest = hub.ingest

    def heard(name, sample):
        if seen:
            seen(name, sample)
        ingest(name, sample)

    hub.ingest = heard
    demo = Demo(hub, at, faults, form)
    demo.halt = Ticks(clock, ticks, lambda: each(hub) if each else None)
    time.time = lambda: clock[0]
    try:
        demo.run()
    finally:
        time.time = real
    hub.ingest = ingest
    return hub


def page_text():
    """The page as a browser has it in the end: the page itself and every part of the server's table that exists, as
    one text. A check that reads only the page would pass on an empty shell once its scripts are files of their own."""
    return PAGE.read_text() + "".join(file.read_text() for file, _ in PAGE_PARTS.values() if file.is_file())


def page_scripts(folder, page_file=PAGE):
    """The scripts of the page as files, in the order the page runs them. One that stands inside the page itself is
    written into `folder`; one the page loads by name is the file the server would send. `page_file`: another page
    than the main one, the calm one for a wall."""
    page, out = page_file.read_text(), []
    for attrs, body in re.findall(r"<script([^>]*)>(.*?)</script>", page, re.S):
        named = re.search(r'src="([^"]+)"', attrs)
        if named:
            out.append(str(PAGE.parent / named.group(1).removeprefix("page/")))
        else:
            out.append(str(Path(folder) / f"inline-{len(out)}.js"))
            Path(out[-1]).write_text(body)
    return out


def page_moments(node_map=None, form="ring4"):
    """What the server would send a page, from two stretches of the demo: `first` and the deep views while the ring
    engine writes, `past` the minute before as the time machine gets it, `next` a moment of single tracks later on.
    `node_map` and `form`: another made-up cluster than the ring of the checks (core/demo_forms.py)."""
    got = {}

    def ring(hub):
        view = hub.with_history()
        if view["engine"].get("tok_s") and len(hub.events) > 3:
            newest = max(t for points in hub.history.values() for t, _ in points)
            past = hub.history_range(list(hub.history), newest - 50, newest, 600)
            got.update(first=view, nerd=hub.nerd_view(0, False), deep=hub.nerd_view(0, True), runs=hub.runs_view())
            got["past"] = {**past, "events": hub.events_between(newest - 50, newest)}

    demo_round(30, at=100.0, each=ring, node_map=node_map, form=form)
    demo_round(
        14, at=240.0, start=1_800_000_100.0, each=lambda hub: got.update(next=hub.view()), node_map=node_map, form=form
    )
    return got


# The parts of the made-up Spark: name, where it stands closed, the two corners of its box, where it flies when the
# machine is taken apart, and in which turn. Metres, Y up, front +Z, like the real model. The SSD lies a centimetre
# under the board: from above the board hides it, from the side it shows.
TINY_PARTS = [
    ("shell", (0, 0, 0), (-0.075, 0, -0.075), (0.075, 0.05, 0.075), (0, 0.166, 0), 0),
    ("pcb", (0, 0.01, 0), (-0.07, 0, -0.06), (0.07, 0.004, 0.06), (0, 0, 0), 0),
    ("ssd_m2", (0, -0.002, 0), (-0.02, -0.002, -0.01), (0.02, 0, 0.01), (0, 0, 0), 3),
    ("fan_left", (-0.035, 0.02, 0.02), (-0.03, 0, -0.03), (0.03, 0.02, 0.03), (-0.008, 0.092, 0.006), 2),
    ("cx7", (-0.03, 0.015, -0.03), (-0.014, 0, -0.014), (0.014, 0.002, 0.014), (-0.004, 0.018, 0.006), 6),
    ("gb10_die_gpu", (0.02, 0.016, 0.02), (-0.007, 0, -0.007), (0.007, 0.001, 0.007), (0.014, 0.118, 0.112), 8),
]


def tiny_model() -> bytes:
    """A Spark of six boxes as one glTF binary, for checks of the scene. The real model is no part of a checkout;
    this one is, and a check knows where each of its parts stands. Every part is drawn as one triangle and carries
    its box in the bounds of its positions: the page places, picks and labels a part by that box alone."""
    data = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0) + struct.pack("<9f", *[0, 0, 1] * 3)
    data += struct.pack("<6f", 0, 0, 1, 0, 0, 1) + struct.pack("<3H2x", 0, 1, 2)
    views = [(0, 36), (36, 36), (72, 24), (96, 6)]  # positions, normals, texture places, the three corners
    accessors = [
        {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
        {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"},
    ]
    meshes, nodes = [], []
    for name, at, low, high, apart, turn in TINY_PARTS:
        accessors.append(
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": list(low), "max": list(high)}
        )
        corners = {"POSITION": len(accessors) - 1, "NORMAL": 0, "TEXCOORD_0": 1}
        meshes.append({"primitives": [{"attributes": corners, "indices": 2, "material": 0}]})
        extras = {"label": name.replace("_", " "), "explode": list(apart), "order": turn}
        nodes.append({"name": name, "mesh": len(meshes) - 1, "translation": list(at), "extras": extras})
    scene = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(data)}],
        "bufferViews": [{"buffer": 0, "byteOffset": start, "byteLength": size} for start, size in views],
        "accessors": accessors,
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1]}}],
        "meshes": meshes,
        "nodes": nodes,
    }
    text = json.dumps(scene).encode()
    text += b" " * (-len(text) % 4)
    whole = 12 + 8 + len(text) + 8 + len(data)
    head = struct.pack("<III", 0x46546C67, 2, whole)
    return head + struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(data), 0x004E4942) + data


@contextlib.contextmanager
def serving(hub, wall=False, base=Handler, senders=()):
    """The web server on a free port of this machine, answering from this hub. Gives a function that asks it:
    ask(path, host=None, lines=0) -> (status, headers, body). With `lines`, only so many lines of the body are read
    (a stream never ends). `wall`: a wall listener, which sends the calm page and its stream only. `ask.server` is the
    listener itself and `ask.address` where it listens, for a check that opens connections of its own. `base`: a
    handler a check changed, in place of the one ringtop has. `senders`: who may read a wall listener."""
    handler = type("Served", (base,), {"hub": hub, "allowed_hosts": {"localhost"}})
    server = Listener(("127.0.0.1", 0), handler, wall=wall, senders=senders)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def ask(path, host=None, lines=0):
        link = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=20)
        try:
            link.putrequest("GET", path, skip_host=host is not None)
            if host is not None:
                link.putheader("Host", host)
            link.endheaders()
            answer = link.getresponse()
            body = b"".join(answer.fp.readline() for _ in range(lines)) if lines else answer.read()
            return answer.status, {k.lower(): v for k, v in answer.getheaders()}, body
        finally:
            link.close()

    ask.server, ask.address = server, server.server_address
    try:
        yield ask
    finally:
        server.shutdown()
        server.server_close()
