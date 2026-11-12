"""The engines of the made-up ring: what the head scrapes from the ring engine, what a Spark's own engine says,
the lines of the log, and what the run source names as running."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ringtop_parts.core.demo import Round


def own_engine(ring: Round, i: int, track: tuple | None) -> dict:
    """A reading of the engine a Spark runs on its own, as its sampler sends it. Its counters move on by a tick here."""
    ring.own_tokens[i] += track[1] * (1 + 0.18 * math.sin(ring.t / 5 + i)) * ring.interval
    ring.own_done[i] += track[2] * ring.interval / 40
    answered = float(int(ring.own_done[i]))
    return {
        "model": track[0],
        "name": "solo-" + track[0].split("-")[0],
        "engine": {
            "generation_tokens_total": ring.own_tokens[i],
            "num_requests_running": track[2],
            "num_requests_waiting": 1.0 if i == 1 else 0.0,
            "request_success_total:stop": answered,
            "process_start_time_seconds": ring.start,
        },
        "hist": {
            "time_to_first_token_seconds": {
                "0.5": answered * 0.2,
                "1": answered * (0.9 - 0.2 * i),
                "5": answered,
                "+Inf": answered,
            }
        },
    }


def log_lines(ring: Round, i: int, hot: bool) -> list | None:
    """New lines of the engine's log, every ten seconds: the head reports its speed while it serves, the hot
    Spark what its sink detector flagged. None when this Spark has nothing to say."""
    if i == 0 and ring.t % 10 < ring.interval and ring.serving:
        return [
            {
                "t": int(ring.now),
                "text": f"(APIServer pid=1) INFO [loggers.py:336] Engine 000: Avg generation throughput: {ring.rate:.1f} tokens/s, Running: 4 reqs, Waiting: 0 reqs",
            },
            {
                "t": int(ring.now),
                "text": f"(APIServer pid=1) INFO [metrics.py:136] SpecDecoding metrics: Mean acceptance length: {3.1 + math.sin(ring.t / 9):.2f}",
            },
        ]
    if i == 1 and hot and ring.t % 10 < ring.interval:
        return [
            {
                "t": int(ring.now),
                "text": "(Worker_TP1 pid=1) WARNING [sink.py:416] Sink detector, rank 1: 192 flagged rows",
            }
        ]
    return None


def engine_counters(ring: Round) -> dict:
    """The counters of the ring engine as the head scrapes them from /metrics: everything the round has done so far."""
    drafted = ring.generated / 3.1
    return {
        "spec_decode_num_drafts_total": drafted,
        **{f"spec_decode_num_draft_tokens_per_pos_total:{p}": drafted * 0.92**p for p in range(16)},
        "prompt_tokens_by_source_total:local_compute": ring.prompts * 0.2,
        "prompt_tokens_by_source_total:local_cache_hit": ring.prompts * 0.8,
        "http:POST /v1/chat/completions 2xx": ring.finished,
        "http:GET /v1/models 2xx": ring.finished * 3,
        "http:GET none 4xx": 12.0,
        "process_resident_memory_bytes": 1.6 * 2**30,
        "process_cpu_seconds_total": ring.t * 2,
        "process_open_fds": 73.0,
        "cache:kv_cache_memory_bytes": 11274289152.0,
        **{
            f"spec_decode_num_accepted_tokens_per_pos_total:{p}": drafted * 0.92**p * (0.78 - p * 0.03)
            for p in range(16)
        },
        "num_requests_waiting_by_reason:capacity": 2.0 if 60 < ring.t < 90 else 0.0,
        "scheduler_compute_pressure:decode": 0.8,
        "scheduler_compute_pressure:prefill": 0.3,
        "scheduler_prefill_compute_share": 0.18,
        "sink_flagged_rows_total": ring.finished * 2.0,
        "request_queue_time_seconds_sum": ring.finished * 0.02,
        "request_queue_time_seconds_count": ring.finished,
        "request_prefill_time_seconds_sum": ring.finished * 1.4,
        "request_prefill_time_seconds_count": ring.finished,
        "request_decode_time_seconds_sum": ring.finished * 7.5,
        "request_decode_time_seconds_count": ring.finished,
        "e2e_request_latency_seconds_sum": ring.finished * 8.9,
        "e2e_request_latency_seconds_count": ring.finished,
        "request_prompt_tokens_sum": ring.finished * 3200.0,
        "request_prompt_tokens_count": ring.finished,
        "request_generation_tokens_sum": ring.finished * 7600.0,
        "request_generation_tokens_count": ring.finished,
        "num_requests_running": 4.0 if ring.phase != "idle" else 0.0,
        "num_requests_waiting": 2.0 if 60 < ring.t < 90 else 0.0,
        "kv_cache_usage_perc": 0.09 + 0.05 * math.sin(ring.t / 30),
        "kv_size_tokens": 11554122.0,
        "generation_tokens_total": ring.generated,
        "prompt_tokens_total": ring.prompts,
        "prompt_tokens_cached_total": ring.cached,
        "iteration_tokens_total_count": ring.steps_done,
        "iteration_tokens_total_sum": ring.generated,
        "spec_decode_num_accepted_tokens_total": ring.accepted,
        "spec_decode_num_draft_tokens_total": ring.drafts,
        "prefix_cache_queries_total": ring.prompts,
        "prefix_cache_hits_total": ring.cached,
        "num_preemptions_total": 0.0,
        "request_success_total:stop": ring.finished,
        "request_success_total:error": 0.0,
        "engine_sleep_state:awake": 1.0,
    }


def engine_histograms(ring: Round) -> dict:
    """The histograms of the ring engine: tokens per step, request sizes, first-token and step times."""
    return {
        "iteration_tokens_total": {
            "1": ring.steps_done * 0.24,
            "8": ring.steps_done * 0.99,
            "16": ring.steps_done,
            "+Inf": ring.steps_done,
        },
        "request_prompt_tokens": {
            "1000": ring.finished * 0.1,
            "5000": ring.finished * 0.7,
            "20000": ring.finished,
            "+Inf": ring.finished,
        },
        "request_generation_tokens": {
            "1000": ring.finished * 0.2,
            "5000": ring.finished * 0.6,
            "20000": ring.finished,
            "+Inf": ring.finished,
        },
        "request_prefill_kv_computed_tokens": {
            "500": ring.finished * 0.8,
            "2000": ring.finished,
            "+Inf": ring.finished,
        },
        "time_to_first_token_seconds": dict(ring.buckets),
        "inter_token_latency_seconds": {
            "0.01": 0.0,
            "0.05": ring.finished * 8.0,
            "0.1": ring.finished * 10.0,
            "+Inf": ring.finished * 10.0,
        },
    }


def head_engine(ring: Round) -> dict:
    """What only the head node sends about the ring engine: its counters, histograms and facts while it plays,
    and that nothing answers on its port while every Spark serves alone."""
    if ring.alone:  # the ring engine is stopped: its port is silent
        return {
            "engine": None,
            "engine_error": "Nothing answers on the vLLM port.",
            "info": {
                "container": {"image": "spark-ds41f:demo", "status": "exited", "config": "config/cluster.json"},
                "kernel": "demo-64k",
                "page_size": 65536,
            },
        }
    return {
        "engine": engine_counters(ring),
        "hist": engine_histograms(ring),
        "engine_error": None,
        "info": {
            "container": {
                "image": "spark-ds41f:demo",
                "status": "running",
                "config": "config/cluster.json",
            },
            "models": {"data": [{"id": "deepseek-v4.1-flash", "max_model_len": 1048576}]},
            "version": {"version": "demo"},
            "kernel": "demo-64k",
            "page_size": 65536,
        },
    }


def run_word(ring: Round, show) -> dict | None:
    """What the run source of the demo names as running: nothing while the ring is idle, a step of the release
    suite while the ring engine plays, the tracks of the Sparks in the last minute. `show` is the Demo: its
    round, steps and tracks."""
    step = int(min(ring.t, show.RING - 0.01) / show.RING * len(show.STEPS))
    return (
        None
        if ring.phase == "idle"
        else {
            "name": "Single tracks",
            "group": "Demo queue",
            "started": ring.now - (ring.t - show.RING),
            "holder": "Demo window",
            "tracks": [
                {
                    "node": name,
                    "model": model,
                    "name": job,
                    "done": int((ring.t - show.RING) / (show.ROUND - show.RING) * cases * (0.5 + 0.15 * j)),
                    "total": cases,
                    "started": ring.now - (ring.t - show.RING),
                }
                for j, (name, (model, _, _, job, cases)) in enumerate(zip(ring.names, show.TRACKS))
            ],
        }
        if ring.alone
        else {
            "name": show.STEPS[step],
            "group": "Release suite",
            "done": int((ring.t % 40) / 40 * 24),
            "total": 24,
            "started": ring.now - (ring.t % 40),
            "steps": [
                {"name": n, "state": "done" if j < step else "running" if j == step else "pending"}
                for j, n in enumerate(show.STEPS)
            ],
            "holder": "Demo window",
        }
    )
