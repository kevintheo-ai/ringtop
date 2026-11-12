"""The deep view: the log in order, link counts, the environment without its secrets."""

import json
import time

from tests.fixtures import engine_sample, hub_for, sampler_namespace


def test_link_counters_stay_absolute_for_the_deep_view():
    hub = hub_for()
    hub._links("dgx0", {"rocep1s0f0": {"packet_seq_err": 5}})
    hub._links("dgx0", {"rocep1s0f0": {"packet_seq_err": 7}})
    row = next(n for n in hub.nerd_view(0)["nodes"] if n["name"] == "dgx0")
    assert row["link_counts"] == {"rocep1s0f0": {"packet_seq_err": 7}}


def test_log_lines_arrive_in_order_and_can_be_followed():
    hub = hub_for()
    hub.ingest("dgx0", {"t": time.time(), "fabric": {}, "log": [{"t": 1, "text": "one"}, {"t": 2, "text": "two"}]})
    assert [e["text"] for e in hub.nerd_view(0)["log"]] == ["one", "two"]
    seen = hub.nerd_view(0)["seq"]
    hub.ingest("dgx1", {"t": time.time(), "fabric": {}, "log": [{"t": 3, "text": "three"}]})
    new = hub.nerd_view(seen)["log"]
    assert [e["text"] for e in new] == ["three"] and new[0]["node"] == "dgx1"


def test_log_catches_up_in_order_and_starts_at_the_newest_lines():
    hub = hub_for()
    hub.ingest("dgx0", {"t": time.time(), "fabric": {}, "log": [{"t": i, "text": str(i)} for i in range(700)]})
    first = hub.nerd_view(0)
    assert first["log"][0]["text"] == "100" and first["seq"] == 700  # a first look: the newest 600
    resume = hub.nerd_view(50)
    assert (
        resume["log"][0]["text"] == "50" and resume["seq"] == 650 and len(resume["log"]) == 600
    )  # paused: nothing skipped
    again = hub.nerd_view(resume["seq"])
    assert [e["text"] for e in again["log"]][:1] == ["650"] and again["seq"] == 700


def test_environment_compares_nodes_without_ever_showing_a_secret():
    ns = sampler_namespace()
    view = ns["env_view"](
        [
            "NCCL_DEBUG=INFO",
            "VLLM_API_KEY=sk-supersecret123",
            "SPARK_PATH=https://user:hunter2@host/x",
            "HF_TOKEN="
            + "hf_"
            + "abcdefgh12345678",  # split: a made-up value, and the secret scanner should stay quiet
            "PATH=/usr/bin",
            "SPARK_ID=" + "a" * 40,
        ]
    )
    assert view["NCCL_DEBUG"] == ["v", "INFO"] and view["PATH"][0] == "h"
    for name in ("VLLM_API_KEY", "SPARK_PATH", "HF_TOKEN", "SPARK_ID"):
        assert view[name][0] == "h" and "secret" not in view[name][1] and "hunter2" not in view[name][1]
    other = dict(view, HF_TOKEN=ns["env_view"](["HF_TOKEN=hf_other_value_12345"])["HF_TOKEN"], NCCL_DEBUG=["v", "WARN"])
    hub = hub_for()
    hub.env = {"dgx0": view, "dgx1": other, "dgx2": view, "dgx3": {k: v for k, v in view.items() if k != "PATH"}}
    rows = {r["name"]: r for r in hub.env_compare()}
    assert (
        rows["HF_TOKEN"]["same"] is False
        and rows["HF_TOKEN"]["value"] is None
        and rows["HF_TOKEN"]["per"]["dgx1"] == "other"
    )
    assert rows["NCCL_DEBUG"]["per"]["dgx1"] == "WARN" and rows["PATH"]["per"]["dgx3"] == "missing"
    text = json.dumps(rows)
    for secret in ("sk-supersecret", "hunter2", "hf_abc", view["HF_TOKEN"][1], view["VLLM_API_KEY"][1]):
        assert secret not in text


def test_environment_never_reaches_the_page_through_the_node():
    hub = hub_for()
    hub.ingest("dgx0", {"t": time.time(), "slow": {"box": {"name": "x", "env": {"HF_TOKEN": ["h", "abc123"]}}}})
    assert "abc123" not in json.dumps(hub.view()) and "abc123" not in json.dumps(hub.nerd_view(0, True), default=sorted)


def test_the_environment_of_a_container_that_is_gone_is_not_compared_any_more():
    """The environment of the engine comes with its container, every 15 s. When a Spark has no engine container any
    more, its last environment stood on in the comparison: the page went on saying what it sets, and that it differs
    from the others."""
    hub, now = hub_for(), time.time()
    hub.ingest("dgx0", {"t": now, "slow": {"box": {"name": "x", "env": {"NCCL_ALGO": ["v", "Ring"]}}}})
    hub.ingest("dgx1", {"t": now, "slow": {"box": {"name": "x", "env": {"NCCL_ALGO": ["v", "Tree"]}}}})
    row = hub.env_compare()[0]
    assert row["per"] == {"dgx0": "Ring", "dgx1": "Tree"} and row["same"] is False, row
    hub.ingest("dgx1", {"t": now + 15, "slow": {"box": None, "apps": []}})  # its container is gone
    row = hub.env_compare()[0]
    assert row["per"] == {"dgx0": "Ring"} and row["same"] is True, row  # "Tree" stood on, and "differs" with it


def test_the_deep_view_of_the_engine_counts_nothing_from_a_counter_that_is_missing():
    """How deep drafts were verified on average is the tokens drafted at every position over the drafts, both
    between two readings. A counter the older reading did not hold was taken for a count of zero there: a position
    that showed up in between went in with all it ever counted against the drafts of the window, and drafts the
    older reading did not hold made the whole life of the engine the window. And an engine that sends neither
    figure of its scheduler was said to have it switched off."""
    hub = hub_for()

    def reading(drafts, *made):
        counted = {f"spec_decode_num_draft_tokens_per_pos_total:{p}": float(m) for p, m in enumerate(made)}
        kept = {f"spec_decode_num_accepted_tokens_per_pos_total:{p}": m * 0.5 for p, m in enumerate(made)}
        return {**counted, **kept, **({"spec_decode_num_drafts_total": float(drafts)} if drafts else {})}

    def depth(new, old):
        return hub.engine_detail(new, old, {}, {})["spec_depth"]

    assert depth(reading(200, 200, 100), reading(100, 100, 50)) == 1.5  # the window: 150 tokens in 100 drafts
    assert depth(reading(200, 200, 100), reading(200, 200, 100)) == 1.5  # nothing new: since the engine started
    assert depth(reading(200, 200, 100, 90), reading(100, 100, 50)) == 1.95, "was 2.4"  # a position came up
    assert depth(reading(200, 200, 100), reading(None, 100, 50)) == 1.5, "was 0.75"  # the drafts had no count yet
    assert depth(reading(None, 200, 100), reading(100, 100, 50)) is None  # and now they have none: no depth
    assert depth(reading(10), reading(None)) is None  # drafts, and no position counted: was a depth of 0.0
    switched = {"scheduler_prefill_compute_share": 0.18}
    states = [
        hub.engine_detail(new, {}, {}, {})["scheduler_active"]
        for new in ({}, {**switched}, {"scheduler_prefill_compute_share": 0.0})
    ]
    assert states == [None, True, False], states  # the first was False
    assert hub.engine_detail({"scheduler_local_prefill_backlog_tokens": 40.0}, {}, {}, {})["scheduler_active"] is True


def test_memory_of_the_api_process_nobody_read_is_not_zero_gigabytes():
    """The deep view shows how much memory the API server of the engine holds, from a figure the engine sends about
    its own process. An engine that does not send it had "0.00 GB"."""
    hub = hub_for()
    assert hub.engine_detail({}, {}, {}, {})["process"]["rss_gb"] is None  # was 0.0
    assert hub.engine_detail({"process_resident_memory_bytes": 1.6 * 2**30}, {}, {}, {})["process"]["rss_gb"] == 1.6
    assert hub.engine_detail({"process_resident_memory_bytes": 0.0}, {}, {}, {})["process"]["rss_gb"] == 0.0


def test_the_deep_view_shows_no_figures_of_an_engine_nobody_reads_any_more():
    """The deep view takes latencies, speculation, the scheduler and the details of the engine from the newest
    reading of the ring engine. When the engine stopped answering, or the head stopped sending, that reading stayed
    the newest for good: the deep view went on showing its figures, hours later, beside a page that says "not
    serving"."""
    parts = {"engine", "speculation", "latency", "scheduler"}
    hub, now = hub_for(), time.time()
    hub.scrapes.append((now - 10, engine_sample(0, 1000.0)["engine"], {}))
    hub.scrapes.append((now, engine_sample(0, 2000.0)["engine"], {}))
    assert parts <= set(hub.nerd_view(0, True)) and hub.engine_view()["state"] == "writing"
    hub.engine_error = "Nothing answers on the vLLM port."  # the head asked, and nothing answered
    silent = hub.nerd_view(0, True)
    assert not parts & set(silent) and hub.engine_view()["state"] == "offline", sorted(silent)  # all four stood on
    assert {"log", "nodes", "env", "cables"} <= set(silent)  # what does not come from the engine stays
    gone = hub_for()  # the head sends nothing any more: its last reading is too old to stand
    gone.scrapes.append((now - 70, engine_sample(0, 1000.0)["engine"], {}))
    gone.scrapes.append((now - 60, engine_sample(0, 2000.0)["engine"], {}))
    assert not parts & set(gone.nerd_view(0, True)) and gone.engine_view()["state"] == "offline"


def test_connections_nobody_read_are_not_an_empty_list():
    """Who is connected to the engine, only the head tells, every few seconds. Before its first word, and while it
    is away, the deep view held an empty list, and the page wrote "No connections right now." of connections nobody
    had read. Not read is None; an empty list is the head saying that nobody is connected."""
    hub = hub_for()
    assert hub.nerd_view(0, True)["connections"] is None  # was []
    hub.ingest("dgx0", {"t": time.time(), "conn": []})
    assert hub.nerd_view(0, True)["connections"] == []  # read: nobody is connected
    hub.ingest("dgx0", {"t": time.time(), "conn": [{"port": "37254"}]})
    assert hub.nerd_view(0, True)["connections"] == [{"port": "37254"}]
    hub.node_down("dgx0", "ssh: timed out")
    assert hub.nerd_view(0, True)["connections"] is None  # was []
