"""The whole sampler as a node runs it, from end to end."""

import contextlib
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types

from ringtop_parts.connect import shell
from ringtop_parts.connect.shell import SAMPLER
from tests.fixtures import sampler_namespace, solo_box

# What a Mac lacks and a Spark has, and a note of every address the sampler asks, with its own clock. The sampler
# itself stays as it is: this stands in front of its text.
SHIM = """import os, time, urllib.request
for name in ('sched_getaffinity', 'sched_setaffinity'):
    if not hasattr(os, name):
        setattr(os, name, lambda *a: {0})
_noted, _urlopen = open(os.environ['RINGTOP_ASKED'], 'a'), urllib.request.urlopen
def _asking(url, *a, **k):
    _noted.write('%r %s\\n' % (time.monotonic(), url))
    _noted.flush()
    return _urlopen(url, *a, **k)
urllib.request.urlopen = _asking
"""


@contextlib.contextmanager
def sampler_against(engine):
    """The real sampler in a process of its own, a worker sampled every 0.5 s, beside a stand-in for docker that
    shows one vLLM container published at the port of `engine` (a request handler).

    Gives the port, the lines the sampler printed so far (each with the moment it arrived) and a function that
    tells every address it asked, with the moment by its own clock. A reader thread takes the lines, so a
    sampler that lives on in silence fails a check and never hangs it."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), engine)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = str(server.server_address[1])
    item = solo_box({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]})
    with tempfile.TemporaryDirectory() as folder:
        docker, noted = os.path.join(folder, "docker"), os.path.join(folder, "asked.txt")
        with open(docker, "w") as f:
            f.write(
                f"#!{sys.executable}\nimport sys\n"
                f"print('solo-mistral' if sys.argv[1] == 'ps' else {json.dumps(json.dumps([item]))} if sys.argv[1] == 'inspect' else '')\n"
            )
        os.chmod(docker, 0o755)
        process = subprocess.Popen(
            [sys.executable, "-u", "-", "0.5", "worker", "auto", "-", "salt"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env={**os.environ, "PATH": folder + os.pathsep + os.environ.get("PATH", ""), "RINGTOP_ASKED": noted},
        )
        lines = []

        def read():
            for line in process.stdout:
                lines.append((time.monotonic(), json.loads(line)))

        def asked():
            with open(noted) as f:
                return [(float(row.split(" ", 1)[0]), row.split(" ", 1)[1]) for row in f.read().splitlines()]

        reader = threading.Thread(target=read, daemon=True)
        try:
            process.stdin.write(SHIM + SAMPLER)
            process.stdin.close()
            reader.start()
            yield port, lines, asked
        finally:
            process.kill()
            process.wait(timeout=10)  # gone before its folder is
            reader.join(timeout=10)
            server.shutdown()
            server.server_close()


def wait_for(done, seconds):
    """Waits until `done()` says so, but not longer than this."""
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        time.sleep(0.05)


def own_of(lines):
    """The readings of its own engine among the lines a sampler printed, in the order they came."""
    return [sample["own"] for _, sample in list(lines) if sample.get("own")]


def test_the_sampler_asks_a_published_engine_from_end_to_end():
    """The whole sampler against a stand-in engine: its own engine arrives as `own`, read at the published port and
    nowhere else, every reading once, and no more often than every 2 s."""

    class Engine(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"vllm:generation_tokens_total 7.0\nvllm:num_requests_running 1.0\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with sampler_against(Engine) as (port, lines, asked):
        wait_for(lambda: len(own_of(lines)) >= 3, 30)
        got, rows, questions = own_of(lines), list(lines), asked()
    assert len(got) >= 3, (len(rows), questions)
    assert got[0]["engine"] == {"generation_tokens_total": 7.0, "num_requests_running": 1.0}, got[0]
    assert got[0]["model"] == "mistral-small-4" and got[0]["name"] == "solo-mistral"
    # every address the sampler asked, by its own account: /metrics at the published port, nothing else anywhere
    assert {url for _, url in questions} == {f"http://127.0.0.1:{port}/metrics"}, questions
    # each reading carries the moment it was read and is sent once: no moment comes twice, none out of order
    stamps = [reading["t"] for reading in got]
    assert stamps == sorted(set(stamps)), stamps
    assert len(got) <= len(questions) < len(rows), (len(got), len(questions), len(rows))  # not with every sample
    # the pace, by the sampler's own clock: every question but the first takes its 2 s. Half a second of room for a
    # machine under load; the exact pace is held on a clock moved by hand, in the checks of the engine readings
    times = [at for at, _ in questions]
    assert (len(times) - 1) * 2.0 <= times[-1] - times[0] + 0.5, times


def test_a_round_that_came_late_is_not_caught_up():
    """The loop keeps its rounds an interval apart, on a grid. A round that ended after the next one was due (a
    port that hangs for its 3 s) is followed by the next at once, and the grid starts anew from there: the rounds
    it missed are not run one after the other, each with its own question to the engine."""
    rest_until = sampler_namespace()["rest_until"]
    assert rest_until(102.0, 100.5) == (1.5, 102.0)  # in time: it sleeps to the grid
    assert rest_until(102.0, 102.0) == (0.0, 102.0)
    assert rest_until(102.0, 109.0) == (
        0.0,
        109.0,
    )  # 7 s late: the next round at once, the one after it at 109 + interval
    loop = shell.program(["sampler/loop.py"])
    assert loop.count("rest_until(next_at, time.time())") == 1 and loop.count("time.sleep(") == 1, loop[-300:]


def test_an_engine_that_hangs_does_not_hold_the_samples_back():
    """An engine that takes the question and never answers: the samples of this Spark keep their pace, and after the
    3 s the sampler waits, it says that its engine did not answer."""

    class Hung(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(8)  # longer than the sampler waits

        def log_message(self, *args):
            pass

    with sampler_against(Hung) as (port, lines, asked):
        wait_for(lambda: own_of(lines) and len(lines) >= 9, 30)
        got, rows, questions = own_of(lines), list(lines), asked()
    assert got and got[0]["engine"] is None and got[0]["error"], (got, len(rows))  # said, not left out
    gaps = [later - earlier for (earlier, _), (later, _) in zip(rows, rows[1:])]
    # asked from the sampling loop, every question would hold the samples for the 3 s it waits
    assert len(rows) >= 9 and max(gaps) < 2.5, gaps
    assert {url for _, url in questions} == {f"http://127.0.0.1:{port}/metrics"}, questions


class Done(Exception):
    """Ends the endless sampling loop once it has printed a sample and wants to sleep."""


# every fast reader of the sampling loop, with the key its reading has in a sample and a made-up reading
FAST = {
    "gpu_now": ("gpu", {"w": 50.0}),
    "cores": ("cores", [3, 97]),
    "cpu_percent": ("cpu", 12.5),
    "cpu_temp": ("cpu_c", 61.0),
    "memory": ("mem", {"MemTotal": 2, "MemAvailable": 1}),
    "fabric": ("fabric", {"rocep1s0f0": {"tx": 1}}),
    "disk": ("disk", {"read": 1, "write": 2}),
    "sensors": ("sensors", {"fans": [2600, 2700]}),
    "zones": ("zones", {"TSOC": 70.0}),
    "psi": ("psi", {"cpu_some": 1}),
    "engine_cgroup": ("cg", {"pids": 9}),
}


def loop_round(broken=()):
    """One round of the sampling loop as a worker runs it, with a stand-in for every fast reader, for the threads
    beside it and for the clock. Gives back the samples it printed. `broken` readers raise what a reader of a file
    raises that nobody thought of."""
    namespace, printed = sampler_namespace(), []

    def reader(name, answer):
        def read(*args):
            if name in broken:
                raise TypeError(name + " is broken")
            return answer

        return read

    def sleep(_):
        raise Done

    for name, (_, answer) in FAST.items():
        namespace[name] = reader(name, answer)
    namespace["threading"] = types.SimpleNamespace(Thread=lambda **_: types.SimpleNamespace(start=lambda: None))
    namespace["time"] = types.SimpleNamespace(time=lambda: 5000.0, sleep=sleep)
    namespace["print"] = lambda line, **_: printed.append(json.loads(line))
    with contextlib.suppress(Done):
        exec(compile(shell.program(["sampler/loop.py"]), "loop", "exec"), namespace)
    return printed


def test_one_fast_reader_that_fails_costs_its_own_reading_and_not_the_sampler():
    """The sampling loop reads fast what a sample holds: GPU, cores, CPU, memory, ring ports, disk, sensors. Most
    of these readers stood in the loop unguarded, and whatever one of them raised ended the program: the Spark was
    shown as not reached, and every new sampler ended at the same place for as long as the trouble stayed. Each
    reader has its own guard: its reading is None in that sample, every other reading arrives. The ring ports
    got theirs last, once the hub could take "nobody read the ports" for what it is."""
    whole = loop_round()
    assert len(whole) == 1 and set(whole[0]) == {"t", *(key for key, _ in FAST.values())}, whole
    assert all(whole[0][key] == answer for key, answer in FAST.values()), whole
    for name, (key, _) in FAST.items():
        got = loop_round(broken=(name,))
        assert len(got) == 1, name  # was: no sample at all, the exception came out of the loop
        assert got[0][key] is None and {**got[0], key: whole[0][key]} == whole[0], (name, got[0])
