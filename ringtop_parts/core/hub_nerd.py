"""Everything the deep view shows: the log, the environment node against node, what the counters say beyond."""

from __future__ import annotations

import math
import time

from ringtop_parts.core.figures import (
    QUANTILE_WINDOW,
    SPEC_DRAFTS,
    SPEC_MADE,
    gained,
    histogram_delta,
    latency_table,
    num,
    one_window,
    rounded,
    speculation,
)


class Nerd:
    """The part of the Hub behind the deep view. Holds no state of its own."""

    def env_compare(self) -> list[dict]:
        """Environment of the engine, node against node. Harmless settings with their value, the rest only as same or different."""
        rows = []
        names = sorted({key for env in self.env.values() for key in env})
        order = [n["name"] for n in self.cluster["nodes"]]
        for key in names:
            cells = {node: (self.env.get(node) or {}).get(key) for node in order if node in self.env}
            present = [c for c in cells.values() if c]
            same = len(present) == len(cells) and len({tuple(c) for c in present}) == 1
            hidden = any(c[0] == "h" for c in present)
            reference = present[0] if present else None
            rows.append(
                {
                    "name": key,
                    "same": same,
                    "hidden": hidden,
                    "value": None if hidden or not same else reference[1],
                    "per": {
                        node: ("missing" if not c else "other" if c != reference else "same")
                        if hidden
                        else ("missing" if not c else c[1])
                        for node, c in cells.items()
                    },
                }
            )
        return rows

    def engine_detail(self, new: dict, old: dict, hist: dict, old_hist: dict) -> dict:
        """What the engine's counters say beyond the headline numbers. A counter that is missing is no count of
        zero: how deep drafts were verified is counted between the two readings only where they give a window
        (one_window), else over the whole run so far, and is None where the engine counts no position; whether
        the scheduler limits shares is None where the engine sends neither of its figures."""

        def spread(name: str) -> list[dict]:
            if name not in hist:
                return []
            recent = histogram_delta(hist[name], old_hist.get(name))
            if not recent or recent[-1][1] <= 0:
                recent = histogram_delta(hist[name], None)
            total, before, rows = (recent[-1][1] if recent else 0), 0.0, []
            for le, count in recent:
                rows.append(
                    {
                        "le": None if math.isinf(le) else le,
                        "n": max(0.0, count - before),
                        "share": max(0.0, count - before) / total if total else 0,
                    }
                )
                before = count
            return rows

        sources = {k.split(":", 1)[1]: new[k] for k in new if k.startswith("prompt_tokens_by_source_total:")}
        http: dict[str, dict] = {}
        for key, value in new.items():
            if key.startswith("http:"):
                method, route, status = key[5:].rsplit(" ", 2)
                http.setdefault(f"{method} {route}", {})[status] = value
        # how far verification went on average, not how many tokens survived: tokens drafted over drafts
        positions = sorted(int(key[len(SPEC_MADE) :]) for key in new if key.startswith(SPEC_MADE))
        recent = one_window(new, old, positions)
        drafts = gained(new, old, SPEC_DRAFTS) if recent else num(new.get(SPEC_DRAFTS))
        made = [gained(new, old, f"{SPEC_MADE}{p}") if recent else num(new.get(f"{SPEC_MADE}{p}")) for p in positions]
        share, backlog = new.get("scheduler_prefill_compute_share"), new.get("scheduler_local_prefill_backlog_tokens")
        resident = num(new.get("process_resident_memory_bytes"))  # of the API process; not sent is not 0 GB
        return {
            "steps": spread("iteration_tokens_total"),
            "prompt_len": spread("request_prompt_tokens"),
            "output_len": spread("request_generation_tokens"),
            "computed_len": spread("request_prefill_kv_computed_tokens"),
            "sources": sources,
            "http": [{"route": k, "by": v} for k, v in sorted(http.items(), key=lambda kv: -sum(kv[1].values()))[:12]],
            "process": {
                "rss_gb": rounded(resident / 2**30, 2) if resident is not None else None,
                "cpu_s": rounded(new.get("process_cpu_seconds_total"), 0),
                "fds": new.get("process_open_fds"),
                "started": new.get("process_start_time_seconds"),
            },
            "cache": {k.split(":", 1)[1]: new[k] for k in new if k.startswith("cache:")},
            "spec_depth": rounded(sum(made) / drafts, 2) if drafts and made and None not in made else None,
            "scheduler_active": None if share is None and backlog is None else bool(share or backlog),
            "preempted": new.get("request_num_preemptions_sum"),
            "sink_ranks": self.sink_ranks,
        }

    def nerd_view(self, since: int = 0, deep: bool = False) -> dict:
        """Everything the deep view shows; only computed while someone has it open. What comes from the ring engine
        (its details, speculation, latencies, the scheduler) is there only while a reading of it stands."""
        with self.lock:
            fresh = [e for e in self.logs if e["seq"] > since]
            log = (
                fresh[:600] if since else fresh[-600:]
            )  # catching up reads forward, a first look starts at the newest 600
            out: dict = {"t": time.time(), "seq": log[-1]["seq"] if log else self.log_seq, "log": log}
            out["nodes"] = [
                {
                    k: n.get(k)
                    for k in (
                        "name",
                        "rank",
                        "head",
                        "live",
                        "cores",
                        "capacity",
                        "threads",
                        "box",
                        "links",
                        "mem_free_gb",
                        "psi",
                        "key_threads",
                    )
                }
                for n in self.nodes.values()
            ]
            for row in out["nodes"]:
                row["link_counts"] = self.link_counts.get(row["name"]) or {}
            if deep:
                out["env"] = self.env_compare()
                out["connections"] = self.connections
                out["cables"] = self.cables
                out["store"] = self.store.size() if self.store else None
            if not self.engine_read():  # no reading of the engine that stands: none of its figures from the last one
                return out
            _, new, hist = self.scrapes[-1]
            _, old, old_hist = self._at_least(QUANTILE_WINDOW)
            if deep:
                out["engine"] = self.engine_detail(new, old, hist, old_hist)
            out["speculation"] = speculation(new, old)
            out["latency"] = latency_table(hist, old_hist)
            out["scheduler"] = {
                "waiting_by_reason": {
                    k.split(":", 1)[1]: v for k, v in new.items() if k.startswith("num_requests_waiting_by_reason:")
                },
                "pressure": {
                    k.split(":", 1)[1]: v for k, v in new.items() if k.startswith("scheduler_compute_pressure:")
                },
                "prefill_share": new.get("scheduler_prefill_compute_share"),
                "backlog": new.get("scheduler_local_prefill_backlog_tokens"),
                "kv_computed": new.get("request_prefill_kv_computed_tokens_sum"),
                "sink": {k[5:-6]: new[k] for k in new if k.startswith("sink_") and k.endswith("_total")},
            }
            return out
