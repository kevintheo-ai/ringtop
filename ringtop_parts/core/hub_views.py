"""What the page gets every tick: the engine's numbers, the links, who the engine is, what runs, and all of it."""

from __future__ import annotations

import time

from ringtop_parts.core.diagnose import diagnose
from ringtop_parts.core.figures import (
    QUANTILE_WINDOW,
    RATE_WINDOW,
    UNCOUNTED,
    engine_speed,
    engine_work,
    recent_quantile,
    rounded,
    scrape_before,
    window_mean,
)

IDLE_GRACE = 30.0  # seconds the engine may rest, or go unread, before "working since" starts anew
INFO_KEEP = 40.0  # seconds the head's facts stand without a new word of it: four of its readings, one every 10 s


class Views:
    """The part of the Hub that says what the page shows. Holds no state of its own."""

    def _at_least(self, seconds: float, reach: float | None = None):
        """The newest scrape that is at least this much older than the latest one."""
        return scrape_before(self.scrapes, seconds, reach)

    def facts(self) -> dict:
        """What the head last told about itself (its container, the lab queue, benchmarks, the model), as long as
        that may stand: nothing once it is older than INFO_KEEP. A head that is away has none (node_down)."""
        return self.info if time.time() - self.info_at <= INFO_KEEP else {}

    def engine_read(self) -> bool:
        """Whether a reading of the ring engine stands as of now: there is one, the head sent it lately, and the
        head has not said since that the engine does not answer."""
        return bool(self.scrapes) and time.time() - self.scrapes[-1][0] <= self.silence and not self.engine_error

    def engine_view(self) -> dict:
        """The ring engine's numbers for the page, from its newest reading and the ones 8 s and 5 min before it.
        Once per reading the figures are kept as curves. "offline" when the head sent none lately, or an error, or
        when the engine answers without saying what it does: then with the word that it answers."""
        if not self.engine_read():
            return {"state": "offline", "error": self.engine_error or "No data from the head node"}
        t1, new, hist = self.scrapes[-1]
        if self._unread_spell():
            self.busy_since = self.idle_since = None  # nobody read the engine meanwhile: what it did then is not known
        t0, old, _ = self._at_least(RATE_WINDOW, self.reach)
        speed = engine_speed(new, old, t1, t0)
        if speed["state"] is None:  # no count of its requests, no tokens written: what it does, and since when, is
            self.busy_since = self.idle_since = None  # not known, and no figure of this reading stands for it
            return {"state": "offline", "error": UNCOUNTED, "answers": True}
        tok_s, steps = speed["tok_s"], speed["steps_s"]
        self._busy(speed["state"], t1)
        fresh = t1 != self.speed_at  # one point per scrape, however often the page is asked for
        self.speed_at = t1
        self._keep(
            fresh,
            t1,
            tok_s=tok_s,
            prompt_tok_s=speed["prompt_tok_s"],
            steps_s=steps,
            running=speed["running"],
            waiting=speed["waiting"],
            kv=new.get("kv_cache_usage_perc"),
        )
        _, older, old_hist = self._at_least(QUANTILE_WINDOW)
        ttft_p95, ttft_recent = recent_quantile(hist, old_hist, "time_to_first_token_seconds", 0.95)
        itl_p50, itl_recent = recent_quantile(hist, old_hist, "inter_token_latency_seconds", 0.5)
        self._keep(fresh, t1, ttft_p95=ttft_p95, itl_p50=itl_p50)
        # the power of the ring is the sum over all of its Sparks. With one away or unread it is a part, given with
        # how many Sparks it is of: no energy per token is counted from a part, and no point of a curve kept
        read = [n["w"] for n in self.nodes.values() if n["live"] and n.get("w") is not None]
        whole = sum(read) if len(read) == len(self.nodes) else None
        work = engine_work(new, old, older, hist, old_hist, tok_s, whole)
        self._keep(
            fresh,
            t1,
            prefill_tok_s=work["prefill_tok_s"],
            one_token_share=work["one_token_share"],
            j_per_token=work["j_per_token"],
            watts=whole,
            accepted=work["accepted"],
            prefix=work["prefix"],
        )
        return {
            "state": speed["state"],
            "running": speed["running"],
            "waiting": speed["waiting"],
            "tok_s": rounded(tok_s, 1),
            "steps_s": rounded(steps, 1),
            "tokens_per_step": rounded(tok_s / steps, 2)
            if steps and tok_s is not None
            else None,  # output only: prompts are counted apart
            "accepted": rounded(work["accepted"], 3),
            "spec": [row["rate"] for row in work["survival"]["positions"]][:16],  # the ring view draws one ring per
            "spec_length": work["survival"]["mean_length"],  # draft position from this
            "kv": rounded(new.get("kv_cache_usage_perc"), 4),
            "kv_tokens": new.get("kv_size_tokens"),
            "prefix": rounded(work["prefix"], 3),
            "prefill_tok_s": rounded(work["prefill_tok_s"], 0),
            "one_token_share": rounded(work["one_token_share"], 3),
            "j_per_token": rounded(work["j_per_token"], 3),
            "watts": rounded(sum(read), 0) if read else None,  # no Spark read its power: no sum
            "watts_from": len(read),  # how many Sparks that sum is of: the page says so where it is not all
            "health": self.facts().get("health"),
            "ttft_p95": ttft_p95,
            "ttft_recent": ttft_recent,
            "itl_p50": itl_p50,
            "itl_recent": itl_recent,
            "finished": work["finished"],
            "errors": new.get("request_success_total:error"),  # a counter the engine did not send is not 0
            "preemptions": new.get("num_preemptions_total"),
            "busy_since": self.busy_since,
            "timing": {
                "queue": rounded(window_mean(new, older, "request_queue_time_seconds"), 3),
                "prefill": rounded(window_mean(new, older, "request_prefill_time_seconds"), 3),
                "decode": rounded(window_mean(new, older, "request_decode_time_seconds"), 3),
                "total": rounded(window_mean(new, older, "e2e_request_latency_seconds"), 3),
            },
            "prompt_avg": rounded(window_mean(new, older, "request_prompt_tokens"), 0),
            "output_avg": rounded(window_mean(new, older, "request_generation_tokens"), 0),
        }

    def _unread_spell(self) -> bool:
        """Whether nobody read the engine for longer than IDLE_GRACE at some point since the reading of the last
        look. Between any two readings that came since then: two can come between two looks, and the hole then
        lies before the newest two."""
        since = self.speed_at
        times = ([] if since is None else [since]) + [t for t, _, _ in self.scrapes if since is None or t > since]
        return any(later - earlier > IDLE_GRACE for earlier, later in zip(times, times[1:]))

    def _busy(self, state: str, t1: float) -> None:
        """Since when the engine has been working. An idle spell of up to half a minute does not end that; a spell
        nobody read the engine for longer than that does (engine_view forgets both clocks then)."""
        if state in ("idle", "asleep"):
            self.idle_since = self.idle_since or t1
            if t1 - self.idle_since > IDLE_GRACE:
                self.busy_since = None
        else:
            self.idle_since = None
            self.busy_since = self.busy_since or t1

    def _keep(self, fresh: bool, t: float, **figures) -> None:
        """Keeps figures of the engine as curves, under engine.NAME: only for a reading that was not kept yet."""
        if fresh:
            for key, value in figures.items():
                self.remember(f"engine.{key}", t, value)

    def edges_view(self) -> list[dict]:
        """The ring links for the page: from which Spark to which, the traffic both ways, up or down, and whether errors
        came within the last two minutes. Of a port nobody can read (its Spark is away) none of that is known: its
        state, its errors, its traffic and its line rate are None. On a Spark that answers each of them is None
        where it was not read. Errors that were seen to rise lately stand; "no errors" needs the count of the
        port read at the last look."""
        if len(self.cluster["nodes"]) < 2:  # one Spark alone has no link: an empty socket is no link that is down
            return []
        by_name = {n["name"]: n for n in self.cluster["nodes"]}
        now = time.time()
        out = []
        for (name, group), port in sorted(self.ports.items()):
            node = by_name[name]
            lately = bool(port.get("err_at") and now - port["err_at"] < 120)
            known = self.nodes[name]["live"] and (lately or port.get("err_read"))
            out.append(
                {
                    "from": node["rank"],
                    "to": node["peers"].get(group),
                    "group": group,
                    "gbps": rounded(port.get("tx"), 2),
                    "rx": rounded(port.get("rx"), 2),
                    "up": port.get("up"),
                    "capacity": port.get("rate"),
                    "errors": lately if known else None,
                }
            )
        return out

    def identity_view(self) -> dict:
        """What is running and on what: model, context length, image, profile, container state, versions, cluster shape,
        memory guard and sampling interval, and whether it is the demo. What the head tells of it is None where its word is
        too old to stand."""
        info = self.facts()
        box = info.get("container") or {}
        models = (info.get("models") or {}).get("data") or []
        model = models[0] if models else {}
        return {
            "model": model.get("id") or box.get("model"),
            "context": model.get("max_model_len") or box.get("max_len"),
            "image": box.get("image"),
            "config": box.get("config"),
            "container": box.get("status"),
            "vllm": (info.get("version") or {}).get("version"),
            "kernel": info.get("kernel"),
            "page_kb": int(info["page_size"] / 1024) if info.get("page_size") else None,
            "shape": self.shape,
            "memguard_gib": self.memguard_gib,
            "interval": self.interval,
            # only where the demo feeds the hub: the moment of a real cluster is as before
            **({"demo": True} if self.demo else {}),
        }

    def run_view(self, engine: dict) -> dict:
        """The one run the page shows, from the first source that has one: the run command, the lab queue, a benchmark
        process, the engine serving requests, or none. A benchmark started when the head read how long it ran,
        not when the page looked."""
        info = self.facts()
        if self.external_error:
            return {"source": "error", "name": "Run source failed", "detail": self.external_error}
        if self.external_run:
            return {
                "source": "command",
                **{k: v for k, v in self.external_run.items() if k != "replies"},
                "has_replies": bool(self.external_run.get("replies")),
            }
        lab = info.get("lab") or {}
        hold, queue = lab.get("hold"), lab.get("queue") or {}
        if hold or queue.get("running"):
            steps = []
            for state in ("done", "failed", "running", "pending"):
                steps += [{"name": name.rsplit(".", 1)[0], "state": state} for name in queue.get(state, [])]
            steps.sort(key=lambda step: step["name"])
            running = (queue.get("running") or [""])[0].rsplit(".", 1)[0]
            return {
                "source": "lab",
                "name": (hold or {}).get("current") or running or "Experiment window open",
                "steps": steps,
                "holder": (hold or {}).get("holder"),
                "until": (hold or {}).get("expected_end"),
            }
        processes = info.get("processes") or []
        if processes:
            first = max(processes, key=lambda item: item["seconds"])
            return {
                "source": "process",
                "name": "Benchmark running",
                "detail": first["command"],
                "started": self.info_at - first["seconds"],
            }
        if engine.get("state") in ("reading", "writing"):
            return {"source": "engine", "name": "Serving requests", "started": engine.get("busy_since")}
        return {"source": "none"}

    def view(self) -> dict:
        """The whole state the page draws from: cluster, identity, engine, nodes, links, run, the why and the latest
        events."""
        with self.lock:
            self.silent_nodes(time.time())
            engine = self.engine_view()
            run = self.run_view(engine)
            self.note_changes(engine, run)
            return {
                "t": round(time.time(), 2),
                "cluster": {
                    "ring": self.cluster["ring"],
                    "nodes": [{"name": n["name"], "rank": n["rank"], "head": n["head"]} for n in self.cluster["nodes"]],
                },
                "identity": self.identity_view(),
                "engine": engine,
                "nodes": list(self.nodes.values()),
                "edges": self.edges_view(),
                "run": run,
                "why": diagnose(engine, list(self.nodes.values()), self.memguard_gib),
                "events": sorted(self.events, key=lambda e: e["t"])[-40:],
            }
