"""The sampler's engine readings: vLLM metrics, the container, the engine a Spark runs on its own."""

import contextlib
import http.server
import threading
import types

from tests.fixtures import docker_answers, sampler_namespace, serve_metrics, solo_box


def test_a_port_without_vllm_metrics_is_not_the_engine():
    """Another service on the port must never be taken for vLLM. What every Python server tells about its process
    (memory, CPU seconds, start time, HTTP requests) is kept beside the engine's figures, but is none of them: a
    text without a single vllm: line is not the engine."""
    namespace = sampler_namespace()
    any_server = (
        "process_resident_memory_bytes 5.0e+08\nprocess_start_time_seconds 1.7e+09\n"
        'http_requests_total{method="GET",handler="/metrics",status="2xx"} 9.0\n'
    )
    for text in ('# HELP python_info x\npython_info{version="3"} 1.0\n', any_server):
        serve_metrics(namespace, text)
        try:
            namespace["scrape"]("8000")
        except ValueError:
            continue
        raise AssertionError("took another service for vLLM: " + text[:40])
    serve_metrics(namespace, any_server + "vllm:num_requests_running 0.0\n")
    values, _ = namespace["scrape"]("8000")
    assert values["num_requests_running"] == 0.0 and values["process_start_time_seconds"] == 1.7e09


def test_sampler_parses_real_metric_lines():
    namespace = sampler_namespace()
    sample = "\n".join(
        [
            "# HELP vllm:num_requests_running x",
            'vllm:num_requests_running{engine="0",model_name="m"} 3.0',
            'vllm:request_success_total{engine="0",finished_reason="stop",model_name="m"} 2.0',
            'vllm:engine_sleep_state{engine="0",model_name="m",sleep_state="awake"} 1.0',
            'vllm:cache_config_info{kv_cache_size_tokens="11547894",engine="0"} 1.0',
            'vllm:time_to_first_token_seconds_bucket{engine="0",le="0.5",model_name="m"} 7.0',
            'vllm:time_to_first_token_seconds_bucket{engine="0",le="+Inf",model_name="m"} 9.0',
            'vllm:kv_cache_usage_perc{engine="0",model_name="m"} NaN',
            'python_info{version="3"} 1.0',
        ]
    )
    serve_metrics(namespace, sample)
    values, hist = namespace["scrape"]("8000")
    assert values["num_requests_running"] == 3.0 and values["request_success_total:stop"] == 2.0
    assert values["engine_sleep_state:awake"] == 1.0 and values["kv_size_tokens"] == 11547894.0
    assert hist["time_to_first_token_seconds"] == {"0.5": 7.0, "+Inf": 9.0}
    assert "kv_cache_usage_perc" not in values


def test_a_spark_reads_its_own_engine_only_at_the_port_docker_published():
    """The rule for single tracks: /metrics only at the published port of a running vLLM container. Never a
    port that was guessed, and never one that was looked for."""
    namespace = sampler_namespace()
    published = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]}

    def box(item):
        docker_answers(namespace, [item])
        return namespace["container"]()

    target = namespace["own_target"]
    solo = box(solo_box(published))
    assert solo["published"] == "8001" and solo["model"] == "mistral-small-4" and target(solo, None) == "8001"
    assert target(box(solo_box({})), None) is None  # host network, nothing published: no port is guessed
    assert target(box(solo_box({"8000/tcp": None})), None) is None  # exposed is not published
    other_port = {"9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]}
    assert target(box(solo_box(other_port)), None) is None  # another port of the container is not its API
    moved = solo_box(other_port, args=("serve", "/m", "--port", "9000"))
    assert target(box(moved), None) == "8001"  # the API port the container was started with
    joined = box(solo_box(other_port, args=("serve", "/m", "--port=9000", "--served-model-name=mistral-eq")))
    assert target(joined, None) == "8001" and joined["model"] == "mistral-eq"  # the same, written with an equals sign
    assert box(solo_box(published, args=("serve", "/m", "--port")))["port"] is None  # a flag without its value
    both = {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8001"}, {"HostIp": "::", "HostPort": "8001"}]}
    assert target(box(solo_box(both)), None) == "8001"
    away = {"8000/tcp": [{"HostIp": "192.168.1.7", "HostPort": "8001"}]}
    assert target(box(solo_box(away)), None) is None  # published on another address: 127.0.0.1 would be a guess
    stopped = solo_box(published, State={"Running": False, "Status": "exited"})
    assert target(box(stopped), None) is None
    ring = solo_box(published, Config={"Labels": {"spark.cluster-config": "config/x.json"}})
    assert target(box(ring), None) is None  # the ring engine is read through the head, as before
    assert target(solo, "8001") is None  # the head reads this very port as the engine already: not twice
    assert target(None, None) is None
    assert box(solo_box(published, Config={"Image": "postgres:16"})) is None  # no vLLM container: nothing is asked


def test_a_look_at_docker_that_failed_says_nothing_new():
    """docker did not answer in time: the container of the last look stands. One slow docker must not read as "its
    own engine ended" and, a look later, as "answers" again. A look that worked and found no container is news."""
    namespace = sampler_namespace()

    def slow(cmd, **_):
        raise TimeoutError("docker ps took longer than 8 s")

    namespace["subprocess"] = types.SimpleNamespace(run=slow)
    assert namespace["container"]() is None  # never seen one: none
    docker_answers(namespace, [solo_box({"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]})])
    seen = namespace["box_now"][0] = namespace["container"]()  # as the slow look keeps it
    assert seen["published"] == "8001"
    namespace["subprocess"] = types.SimpleNamespace(run=slow)
    assert namespace["container"]() is seen and namespace["own_target"](namespace["container"](), None) == "8001"
    docker_answers(namespace, [])
    assert namespace["container"]() is None


def test_a_spark_sends_what_its_own_engine_counts_or_says_that_it_did_not_answer():
    namespace = sampler_namespace()
    box = {"name": "solo-mistral", "model": "mistral-small-4", "running": True, "published": "8001"}
    serve_metrics(namespace, 'vllm:generation_tokens_total{model_name="m"} 42.0\nvllm:num_requests_running 2.0\n')
    inner, asked = namespace["urllib"].request.urlopen, []
    namespace["urllib"].request.urlopen = lambda url, **k: (asked.append(url), inner(url, **k))[1]
    got = namespace["own_reading"](box, "8001")
    assert asked == ["http://127.0.0.1:8001/metrics"], asked  # this one address, nothing else
    assert got["model"] == "mistral-small-4" and got["name"] == "solo-mistral" and got["hist"] == {}
    assert got["engine"] == {"generation_tokens_total": 42.0, "num_requests_running": 2.0}

    def refuse(url, **_):
        raise OSError("connection refused")

    namespace["urllib"].request.urlopen = refuse
    silent = namespace["own_reading"](box, "8001")
    assert silent["engine"] is None and silent["model"] == "mistral-small-4" and silent["error"]


class Enough(BaseException):
    """Ends a loop of the sampler that would run for ever, from the stand-ins for its clock and its engine."""


def own_clock(namespace, start=100.0):
    """A clock the checks move by hand in place of the sampler's: a sleep moves it on and is noted, and once it
    passes `until` the loop that sleeps or asks is ended."""
    clock = types.SimpleNamespace(now=start, slept=[], until=None)

    def over():
        if clock.until is not None and clock.now >= clock.until:
            raise Enough

    def sleep(seconds):
        clock.slept.append(round(seconds, 3))
        clock.now += seconds
        over()

    clock.over = over
    namespace["time"] = types.SimpleNamespace(
        monotonic=lambda: clock.now, sleep=sleep, time=lambda: 1_800_000_000.0 + clock.now
    )
    return clock


BOX = {"name": "solo-mistral", "model": "mistral-small-4", "running": True, "published": "8001"}


def asking(namespace, text="vllm:generation_tokens_total 1.0\n"):
    """An engine that answers at once, and the list of every address the sampler asked it at."""
    serve_metrics(namespace, text)
    inner, asked = namespace["urllib"].request.urlopen, []
    namespace["urllib"].request.urlopen = lambda url, **k: (asked.append(url), inner(url, **k))[1]
    return asked


class Looked(list):
    """The box as the background thread leaves it, counting how often it is looked at."""

    looks = 0

    def __getitem__(self, index):
        self.looks += 1
        return super().__getitem__(index)


def test_one_round_for_its_own_engine_is_one_look_one_question_and_one_reading_for_the_next_sample():
    """The thread of its own engine, one round: the box changes under it every 15 s, so port and name come from one
    look; what it read waits with the moment it was read, the newest only, and a sample takes it once."""
    namespace = sampler_namespace()
    clock = own_clock(namespace)
    round_, pending, asked = namespace["own_round"], namespace["pending"], asking(namespace)
    assert round_() is None and "own" not in pending and not asked  # no container: no question, no crash
    namespace["box_now"] = Looked([dict(BOX)])
    got = round_()
    assert namespace["box_now"].looks == 1  # the port asked and the name given belong to the same container
    assert asked == ["http://127.0.0.1:8001/metrics"], asked  # this one address, nothing else
    assert got is pending["own"] and got["model"] == "mistral-small-4" and got["name"] == "solo-mistral"
    assert got["engine"] == {"generation_tokens_total": 1.0} and got["t"] == 1_800_000_100.0  # when it was read
    clock.now += 2.0
    newer = round_()
    assert pending["own"] is newer and newer is not got and newer["t"] == 1_800_000_102.0  # the newest one waits
    assert pending.pop("own") is newer and "own" not in pending  # as the loop takes it: sent once, then gone

    def refuse(url, **_):
        raise OSError("connection refused")

    namespace["urllib"].request.urlopen = refuse
    silent = round_()
    assert silent["engine"] is None and silent["error"] and silent["t"] == 1_800_000_102.0 and pending["own"] is silent


def test_its_own_engine_is_never_asked_where_it_may_not_be():
    """A round asks nothing when there is no running container, when it is the ring engine itself, or at the port
    the head already reads as the ring engine."""
    namespace = sampler_namespace()
    own_clock(namespace)
    round_, asked = namespace["own_round"], asking(namespace)
    for box, ring_port in (
        (None, None),
        (dict(BOX, running=False), None),
        (dict(BOX, config="config/cluster.json"), None),
        (dict(BOX, published=None), None),
        (dict(BOX), "8001"),
    ):
        namespace["box_now"][0], namespace["port"][0] = box, ring_port
        assert round_() is None and not asked and "own" not in namespace["pending"], (box, ring_port)


def test_its_own_engine_is_asked_at_most_every_two_seconds_by_the_clock():
    """The rule is /metrics every 2 s at most. The pace is kept by the clock: a round that comes late is followed by
    a full wait, a question never catches up; and it is never asked more often than samples can carry the answers."""
    for start in (100.0, 0.0):  # a clock that starts at zero (macOS, older Pythons) must not delay the first question
        namespace = sampler_namespace()
        clock = own_clock(namespace, start)
        pause, round_ = namespace["own_pause"], namespace["own_round"]
        namespace["box_now"][0] = dict(BOX)
        asked = asking(namespace)
        assert pause() == 0.0  # never asked: due at once
        round_()
        assert pause() == 2.0 and len(asked) == 1
        clock.now += 1.5
        assert pause() == 0.5
        clock.now += 0.5
        assert pause() == 0.0
        clock.now += 7.0  # the thread came late
        assert pause() == 0.0
        round_()
        assert pause() == 2.0 and len(asked) == 2  # and waits the full 2 s again
        last = namespace["own_last"][0]
        namespace["box_now"][0] = None
        clock.now += 5.0
        assert round_() is None and namespace["own_last"][0] == last  # nothing to ask: the questions' clock stands
        namespace["box_now"][0] = dict(BOX)
        namespace["interval"] = 5.0  # sampled every 5 s: a reading every 2 s would be thrown away unsent
        round_()
        assert pause() == 5.0 and len(asked) == 3


def test_the_thread_of_its_own_engine_keeps_its_pace_whatever_the_engine_does():
    """The whole thread on a clock moved by hand: an engine that answers at once is asked every 2 s, one that hangs
    for 3 s is asked again right after (never sooner than 2 s), and without an engine it looks again every second."""
    namespace = sampler_namespace()
    clock = own_clock(namespace)
    asked, hang = [], [0.0]

    def answer(url, **_):
        clock.over()
        asked.append((clock.now, url))
        clock.now += hang[0]  # the time the engine takes to answer, or to time out
        raise OSError("timed out")

    def run(seconds):
        asked.clear()
        clock.slept.clear()
        clock.until = clock.now + seconds
        with contextlib.suppress(Enough):
            namespace["own_loop"]()

    namespace["urllib"] = types.SimpleNamespace(request=types.SimpleNamespace(urlopen=answer))
    namespace["box_now"][0] = dict(BOX)
    run(30.0)
    assert [t for t, _ in asked] == [100.0 + 2 * k for k in range(15)], asked  # the first at once, then every 2 s
    assert {url for _, url in asked} == {"http://127.0.0.1:8001/metrics"}
    assert namespace["pending"]["own"]["engine"] is None  # it did not answer, and that is said
    hang[0] = 3.0
    run(30.0)
    gaps = [later - earlier for (earlier, _), (later, _) in zip(asked, asked[1:])]
    assert len(gaps) >= 8 and set(gaps[1:]) == {3.0} and gaps[0] >= 2.0, gaps  # right after the hang, never sooner
    namespace["box_now"][0] = None
    clock.now += 10.0  # long after the last question: nothing of its pace is left to wait out
    run(5.0)
    assert not asked and clock.slept == [1.0] * 5, clock.slept  # nothing to ask: one look a second, no question


def test_a_reading_of_its_own_engine_carries_the_moment_it_was_asked_for():
    """The moment of a reading becomes the time a speed is counted over. Taken when the answer had come, a slow
    answer and a quick one after it stood a moment apart for counters seconds apart. It is taken before the
    question: the questions keep their pace of 2 s by the clock, and so do the moments of their readings."""
    namespace = sampler_namespace()
    clock = own_clock(namespace)
    namespace["box_now"][0] = dict(BOX)
    serve_metrics(namespace, "vllm:generation_tokens_total 1.0\n")
    answer, took = namespace["urllib"].request.urlopen, [2.9]

    def slow(url, **k):
        clock.now += took[0]  # the time the engine takes to answer
        return answer(url, **k)

    namespace["urllib"].request.urlopen = slow
    first = namespace["own_round"]()
    assert first["engine"] and first["t"] == 1_800_000_100.0, first["t"]  # was ...102.9: when the answer had come
    took[0] = 0.05
    assert namespace["own_pause"]() == 0.0  # the slow answer used up the pace: the next question is due at once
    second = namespace["own_round"]()
    assert second["t"] == 1_800_000_102.9 and second["t"] - first["t"] >= 2.0, second["t"]  # was 0.05 s after it


def test_an_engine_that_answers_in_slow_pieces_is_cut_off_at_its_deadline():
    """A question to /metrics waited up to 3 s for every single step of the connection, and read the answer in one
    go: an engine that sends its answer in slow pieces, each within those 3 s, held the question for as long as it
    liked. On the head that question stands in the sampling loop. The whole answer has 3 s now: it is read piece
    by piece, and given up as failed once that time is over. A quick answer in several pieces is read whole."""
    namespace = sampler_namespace()
    clock = own_clock(namespace)

    class Pieces:
        """An answer that comes one line at a time, each after `apart` seconds on the clock moved by hand."""

        length = None  # it names no length

        def __init__(self, count, apart):
            self.left, self.apart = count, apart

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read1(self, size=-1):
            if not self.left:
                return b""
            self.left -= 1
            clock.now += self.apart
            return b"vllm:generation_tokens_total 1.0\n"

        def read(self):  # as the answer was read before: all of it, however long it takes
            return b"".join(iter(self.read1, b""))

    def asked(count, apart):
        namespace["urllib"] = types.SimpleNamespace(
            request=types.SimpleNamespace(urlopen=lambda *a, **k: Pieces(count, apart))
        )
        began = clock.now
        try:
            return namespace["scrape"]("8000")[0], clock.now - began
        except OSError:
            return None, clock.now - began

    assert asked(3, 0.1)[0] == {"generation_tokens_total": 3.0}
    values, took = asked(100, 0.5)
    assert values is None and took <= 3.5, (values, took)  # was the whole answer after 50 s
    assert namespace["own_reading"](dict(BOX), "8001")["error"]  # and its own engine is said not to have answered


def test_an_answer_that_ends_before_the_length_it_named_is_no_answer():
    """An engine that names the length of its answer and closes the connection before all of it is sent has not
    answered. Read in one go, http.client said so itself. Read piece by piece, the early end looked like the end,
    and a counter cut in its last line was taken as read: a count that seems to fall. Asked for real here, over
    HTTP on a free port of this machine, because the stand-ins of the other checks name no length. The same answer
    in whole gives its figures, and so does one that names no length and ends with its connection."""
    namespace = sampler_namespace()
    body = b"vllm:num_requests_running 1.0\n" + b"vllm:generation_tokens_total 1234567.0\n" * 40
    whole = {"num_requests_running": 1.0, "generation_tokens_total": 40 * 1234567.0}
    answer, sent = {"named": True, "short": 0}, []

    class Engine(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            if answer["named"]:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            sent.append(len(body) - answer["short"])
            self.wfile.write(body[: sent[-1]])  # and the connection is closed, as HTTP/1.0 does after an answer

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Engine)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = str(server.server_address[1])
        assert namespace["scrape"](port)[0] == whole
        answer["short"] = 5  # the last line ends "... 12345" then
        try:
            values = namespace["scrape"](port)[0]
        except OSError:
            values = None
        assert values is None, values  # was generation_tokens_total 48160458.0 for 49382680.0
        assert namespace["own_reading"](dict(BOX), port)["error"]  # and its own engine is said not to have answered
        answer.update(named=False, short=0)
        assert namespace["scrape"](port)[0] == whole
    finally:
        server.shutdown()
        server.server_close()
    assert sent == [len(body), len(body) - 5, len(body) - 5, len(body)], sent  # all four questions reached it
