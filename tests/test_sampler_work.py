"""The sampler's look at the work on a node: processes, journal, GPU programs, secrets that stay hidden."""

import time
import types

from tests.fixtures import sampler_namespace


def test_processes_never_publish_the_command_line():
    namespace = sampler_namespace()
    listing = "120 bash -c export API_KEY=hunter2; servebench --url http://x\n 99 python3 ringtop.py servebench\n"
    listed = types.SimpleNamespace(returncode=0, stdout=listing)
    namespace["subprocess"] = types.SimpleNamespace(run=lambda *a, **k: listed)
    assert namespace["processes"]() == [{"seconds": 120, "command": "servebench"}]


def test_a_tool_that_failed_is_no_empty_list():
    """The programs on the GPU, the biggest programs in memory and the benchmarks that run are read with a tool
    each. Where the tool did not answer in time, or ended with an error, the reader gave an empty list: no program
    on the GPU (the hub made "0.0 GB" of it), nothing in memory, no benchmark. That look failed: None. A tool that
    ran and listed nothing is a reading of nothing."""
    namespace = sampler_namespace()
    readers = ("gpu_apps", "biggest", "processes")

    def late(*a, **k):
        raise TimeoutError("took longer than its time")

    namespace["subprocess"] = types.SimpleNamespace(run=late)
    assert [namespace[name]() for name in readers] == [None, None, None]  # each was []
    failed = types.SimpleNamespace(returncode=9, stdout="Unable to determine the device handle\n", stderr="")
    namespace["subprocess"] = types.SimpleNamespace(run=lambda *a, **k: failed)
    assert [namespace[name]() for name in readers] == [None, None, None]  # each was []
    quiet = types.SimpleNamespace(returncode=0, stdout="", stderr="")
    namespace["subprocess"] = types.SimpleNamespace(run=lambda *a, **k: quiet)
    assert [namespace[name]() for name in readers] == [[], [], []]


def test_sampler_reads_journal_and_gpu_apps():
    namespace = sampler_namespace()
    namespace["journal_at"][0] = 100.0
    calls = []

    def fake(cmd, **k):
        calls.append(cmd)
        if cmd[0] == "journalctl" and "-k" in cmd:
            return types.SimpleNamespace(
                returncode=0,
                stdout="1762.5 h kernel: NVRM: Xid (PCI): 79, GPU gone\n1763.5 h kernel: tee: drop_caches: 3\n",
            )
        if cmd[0] == "journalctl":
            return types.SimpleNamespace(returncode=0, stdout="1764.5 h spark-memguard[9]: low headroom\n")
        if cmd[0] == "ps":
            return types.SimpleNamespace(returncode=0, stdout="5388992 VLLM::Worker_TP\n 1048576 vllm\n")
        return types.SimpleNamespace(returncode=0, stdout="89487, VLLM::Worker_TP0\n[N/A], x\n")

    namespace["subprocess"] = types.SimpleNamespace(run=fake)
    found = namespace["journal"]()
    assert [e["kind"] for e in found] == ["kernel", "memguard"] and found[0]["text"] == "NVRM: Xid (PCI): 79, GPU gone"
    assert calls[0][calls[0].index("-S") + 1] == "@100"
    assert namespace["journal_at"][0] > 100.0  # read completely, so the window moves on
    namespace["journal_at"][0] = 100.0

    def broken(*a, **k):
        raise TimeoutError

    namespace["subprocess"] = types.SimpleNamespace(run=broken)
    assert namespace["journal"]() == [] and namespace["journal_at"][0] == 100.0  # not read: stays for the next look
    namespace["subprocess"] = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout=""))
    assert namespace["journal"]() == [] and namespace["journal_at"][0] == 100.0  # journalctl failed: the same
    namespace["subprocess"] = types.SimpleNamespace(run=fake)
    assert namespace["gpu_apps"]() == [{"gb": 87.4, "name": "VLLM::Worker_TP0"}]
    assert namespace["biggest"]()[0] == {"gb": 5.1, "name": "VLLM::Worker_TP"}


def test_secrets_are_hidden_inside_harmless_names():
    ns = sampler_namespace()
    view = ns["env_view"](['SPARK_CONFIG={"password":"pw"}', "SPARK_X=has token inside", "SPARK_OK=4"])
    assert view["SPARK_CONFIG"][0] == "h" and view["SPARK_X"][0] == "h" and view["SPARK_OK"] == ["v", "4"]
    masked = ns["SECRET"].sub(r"\1***", "--hf x hf_abcdefgh1234 --secret=abc")
    assert "hf_abc" not in masked and "abc" not in masked.split("--secret=")[1]


def test_secrets_in_hyphenated_flags_are_hidden_but_tuning_flags_stay():
    sub = sampler_namespace()["SECRET"].sub
    for flag in (
        "--secret-access-key AKIAEXAMPLE1",
        "--encryption-key s3cr3tvalue",
        "--db-pass hunter2",
        "--hf-token abc123",
    ):
        assert flag.split()[1] not in sub(r"\1***", flag), flag
    keep = "--max-num-batched-tokens 8192 --tokenizer-mode auto --ssl-keyfile /k.pem --bypass-cache on"
    assert sub(r"\1***", keep) == keep
    made_up = "0123" + "4567" + "89ab" + "cdef"  # split: a made-up value, and the secret scanner should stay quiet
    for text in (
        f'--lora-modules {{"name":"sql","token":"{made_up}"}}',
        '"api_key": "hunter2xyz"',
        '--api-key "two words"',
    ):
        masked = sub(r"\1***", text)
        assert not any(s in masked for s in (made_up, "hunter2xyz", "words")), masked
    keep = '--speculative-config {"method":"mtp","num_speculative_tokens":3}'
    assert sub(r"\1***", keep) == keep
    started = time.time()
    for hostile in ("key-" * 1500, "pass_" * 1200, '"key":' * 1000):
        sub(r"\1***", hostile)
    assert time.time() - started < 0.5  # one bad line must not stall the sampler


def test_random_looking_values_stay_hidden_under_harmless_names():
    view = sampler_namespace()["env_view"](
        [
            "SPARKNET_JOIN=0123456789abcdef0123456789abcdef",
            "VLLM_X=Xk9_2mQpL7vRt3ZsWn4bYc",
            "CUDA_CACHE_MAXSIZE=4294967296",
            "VLLM_USAGE_SOURCE=production-docker-image",
            "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,garbage_collection_threshold:0.8",
        ]
    )
    assert view["SPARKNET_JOIN"][0] == "h" and view["VLLM_X"][0] == "h"
    assert all(view[k][0] == "v" for k in ("CUDA_CACHE_MAXSIZE", "VLLM_USAGE_SOURCE", "PYTORCH_CUDA_ALLOC_CONF"))


def test_a_clock_query_that_failed_once_is_asked_again():
    namespace = sampler_namespace()
    answers = iter([TimeoutError("slow"), "2418\n"])

    def run(cmd, **kw):
        if "clocks.max.sm" in cmd[1]:
            return types.SimpleNamespace(returncode=0, stdout="3003\n")
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return types.SimpleNamespace(returncode=0, stdout=answer)

    namespace["subprocess"] = types.SimpleNamespace(run=run)
    for name in ("gpu_apps", "biggest", "journal"):
        namespace[name] = lambda: None
    assert namespace["slow_facts"]()["mhz_app"] is None
    second = namespace["slow_facts"]()
    assert second["mhz_app"] == 2418.0 and second["mhz_max"] == 3003.0
