"""The sampler's engine log and threads: what enters the log, and what never does."""

import types

from tests.fixtures import sampler_namespace


def test_sampler_keeps_secrets_and_its_own_polling_out_of_the_log():
    namespace = sampler_namespace()
    namespace["logs_at"][0] = 100.0
    text = (
        '2026-11-09T11:45:21.123Z (APIServer pid=1) INFO: 127.0.0.1:45510 - "GET /metrics HTTP/1.1" 200 OK\n'
        "2026-11-09T11:45:22.123Z loaded with api_key=hunter2 and more\n"
    )
    namespace["subprocess"] = types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=text, stderr="")
    )
    lines = namespace["engine_log"]("spark")
    assert len(lines) == 1 and "hunter2" not in lines[0]["text"] and "api_key=***" in lines[0]["text"]
    assert namespace["last_stamp"][0].startswith("2026-11-09T11:45:22")
    assert namespace["engine_log"]("spark") == []  # the same lines again are not new
    namespace["subprocess"] = types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="")
    )
    stamp = namespace["last_stamp"][0]
    assert namespace["engine_log"]("spark") == [] and namespace["last_stamp"][0] == stamp


def test_a_warning_without_a_timestamp_does_not_stop_the_log():
    namespace = sampler_namespace()
    text = (
        "WARNING: something the docker client printed\n"
        "2026-11-09T11:45:22.123456789Z (APIServer pid=1) INFO real line\n"
    )
    namespace["subprocess"] = types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=text, stderr="")
    )
    assert len(namespace["engine_log"]("spark")) == 1 and namespace["last_stamp"][0].startswith("2026-11-09")


def test_prompts_and_answers_never_enter_the_log():
    namespace = sampler_namespace()
    text = '2026-11-09T11:45:22.1Z (APIServer) Received request abc: prompt: "secret"\n2026-11-09T11:45:23.1Z (APIServer) Generated response abc: output: "secret"\n'
    namespace["subprocess"] = types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=text, stderr="")
    )
    assert namespace["engine_log"]("spark") == []


def test_a_busy_log_is_filled_from_the_last_look_instead_of_losing_lines():
    namespace = sampler_namespace()
    namespace["last_stamp"][0] = "2026-11-09T11:00:00.000000000Z"
    busy = "".join(f"2026-11-09T11:00:05.{i:09d}Z x Received request r{i}\n" for i in range(500))
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        since = "--since" in cmd
        text = ("2026-11-09T11:00:01.000000000Z Traceback: engine died\n" if since else "") + busy
        return types.SimpleNamespace(returncode=0, stdout=text, stderr="")

    namespace["subprocess"] = types.SimpleNamespace(run=run)
    lines = namespace["engine_log"]("spark")
    assert [e["text"] for e in lines] == ["Traceback: engine died"], lines
    assert calls[-1][calls[-1].index("--since") + 1] == "2026-11-09T11:00:00.000000000Z"
    calls.clear()
    namespace["subprocess"] = types.SimpleNamespace(
        run=lambda cmd, **kw: (
            calls.append(cmd)
            or types.SimpleNamespace(returncode=0, stdout="2026-11-09T11:00:06.000000000Z quiet\n", stderr="")
        )
    )
    assert len(namespace["engine_log"]("spark")) == 1 and len(calls) == 1  # a quiet log needs no second read


def test_migrations_never_go_negative_when_a_thread_id_comes_back():
    ns = sampler_namespace()
    counters = iter(["se.nr_migrations : 10000", "se.nr_migrations : 5"])
    ns["read"] = lambda path: next(counters)
    thread = {
        "tid": "7",
        "pid": "7",
        "comm": "VLLM::EngineCore",
        "pct": 1.0,
        "core": 0,
        "wait": 0.0,
        "wakes": 0.0,
        "preempted": 0.0,
        "folder": "/x/",
    }
    ns["key_threads"]([dict(thread)])
    ns["last_migrations"]["7"] = (ns["last_migrations"]["7"][0] - 1.0, 10000)
    assert ns["key_threads"]([dict(thread)])[0]["migrated"] is None


def test_a_look_for_the_engine_that_failed_is_no_engine_without_threads():
    """The threads of the engine are found with `pgrep`. Where that could not run or did not answer in time, the
    reader gave an empty list, which the slow reading sent on as "no threads, no key threads". That look failed:
    None. A pgrep that ran and found no engine is a reading: no threads."""
    ns = sampler_namespace()

    def late(cmd, **_):
        raise TimeoutError("pgrep took longer than 5 s")

    ns["subprocess"] = types.SimpleNamespace(run=late)
    assert ns["threads"]() is None  # was []
    ns["subprocess"] = types.SimpleNamespace(run=lambda cmd, **_: types.SimpleNamespace(stdout="", returncode=1))
    assert ns["threads"]() == ([], [])
