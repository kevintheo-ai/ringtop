"""Figures from the counters of an engine: rates, quantiles, the state it is in. Plain arithmetic on readings."""

from __future__ import annotations

import math

RATE_WINDOW = 8.0  # seconds behind a tokens-per-second figure
QUANTILE_WINDOW = 300.0  # seconds behind a recent latency figure
# seconds two readings lie apart at least before a speed is counted from them: the moment a reading carries is not
# the moment the engine counted, and over less than this that error is most of the figure
APART = 1.0
# said of an engine whose state nobody can tell: it sent no count of its requests, and no speed says that it writes
UNCOUNTED = "The engine answers without its request counters."


def num(x):
    """The value itself when it is a finite number, else None. A whole number too large for a float is none: nothing
    can count with it, and asking it whether it is finite fails. This never does."""
    if not isinstance(x, (int, float)):
        return None
    try:
        return x if math.isfinite(x) else None
    except OverflowError:
        return None


def rounded(x, digits=2):
    """A finite number rounded to the digits given, else None."""
    x = num(x)
    return round(x, digits) if x is not None else None


def quantile(buckets: list[tuple[float, float]], q: float) -> float | None:
    """Linear interpolation inside a cumulative histogram, as PromQL's histogram_quantile does."""
    if not buckets or buckets[-1][1] <= 0:
        return None
    target = q * buckets[-1][1]
    low, count = 0.0, 0.0
    for le, c in buckets:
        if c >= target:
            if math.isinf(le):
                return low
            return le if c == count else low + (le - low) * (target - count) / (c - count)
        low, count = le, c
    return low


def histogram_delta(new: dict, old: dict | None) -> list[tuple[float, float]]:
    """Cumulative buckets of what happened between two scrapes, or since start if old is missing."""
    old = old or {}
    out = sorted((float("inf") if le == "+Inf" else float(le), count - old.get(le, 0.0)) for le, count in new.items())
    if any(count < 0 for _, count in out):  # the engine restarted in between
        out = sorted((float("inf") if le == "+Inf" else float(le), count) for le, count in new.items())
    return out


def scrape_before(scrapes, seconds: float, reach: float | None = None):
    """The newest reading that is at least this much older than the latest one, or else the oldest there is.

    With `reach`, nothing older than a hole of that length counts: a speed is never averaged across unread time."""
    latest, best = scrapes[-1][0], scrapes[-1]
    for scrape in reversed(scrapes):
        if reach is not None and best[0] - scrape[0] > reach:
            break
        best = scrape
        if latest - scrape[0] >= seconds:
            break
    return best


def gained(new: dict, old: dict, key: str) -> float | None:
    """What a counter gained between two readings. None where one of them does not hold it: a counter that is missing
    is no count of zero."""
    before, after = num(old.get(key)), num(new.get(key))
    return after - before if before is not None and after is not None else None


def counter_rate(new: dict, old: dict, t1: float, t0: float, key: str) -> float | None:
    """What a counter gained per second between two readings. None where that is not known: a reading without the
    counter, a counter that fell (another life of the engine), less than APART between the two."""
    delta = gained(new, old, key)
    return delta / (t1 - t0) if delta is not None and delta >= 0 and t1 - t0 >= APART else None


def requests(new: dict) -> tuple[float | None, float | None]:
    """The requests an engine works on and the ones that wait, as it counts them. None for a count it did not send:
    that is no count of zero."""
    return num(new.get("num_requests_running")), num(new.get("num_requests_waiting"))


def engine_state(new: dict, tok_s: float | None) -> str | None:
    """Writing from 1 token/s; requests without tokens are prompts being read (vLLM counts them with the first token).
    Idle is said of two request counts that were both read as zero. None where the engine names no request, did not
    send both counts and writes no tokens: then nobody knows what it does."""
    if new.get("engine_sleep_state:awake", 1.0) == 0:
        return "asleep"
    running, waiting = requests(new)
    writes = (tok_s or 0.0) >= 1.0
    if (running or 0.0) + (waiting or 0.0) > 0:
        return "writing" if writes else "reading"
    if running is None or waiting is None:
        return "writing" if writes else None
    return "idle"


def recent_quantile(hist: dict, old_hist: dict, name: str, q: float) -> tuple[float | None, bool]:
    """A latency figure of the window between two readings, and whether it is one. In a quiet spell, and where the
    older reading did not hold the histogram yet, it is the figure since the engine started."""
    if name not in hist:
        return None, False
    value = quantile(histogram_delta(hist[name], old_hist[name]), q) if name in old_hist else None
    if value is not None:
        return rounded(value, 4), True
    return rounded(quantile(histogram_delta(hist[name], None), q), 4), False


def restarted(new: dict, old: dict) -> bool:
    """Two readings of one engine, or of two lives of it? Its start time says so; without one, a count of written
    tokens that fell. A reading that does not hold that count says nothing: it is no restart."""
    born, before = new.get("process_start_time_seconds"), old.get("process_start_time_seconds")
    if born is not None and before is not None:
        return born != before
    return (gained(new, old, "generation_tokens_total") or 0.0) < 0


def finished(new: dict) -> float | None:
    """How many requests an engine has finished since it started, whatever the way they ended. None where it sent no
    counter of them: that is not 0 requests done."""
    counts = [value for key, value in new.items() if key.startswith("request_success_total:")]
    return sum(counts) if counts else None


def pace(scrapes, reach: float | None = None) -> dict:
    """Speed, queue and first-token time of one engine from its recent readings: the arithmetic of the ring engine,
    for an engine a Spark runs on its own. A count it did not send is None, and so is a state nobody can tell."""
    t1, new, hist = scrapes[-1]
    t0, old, _ = scrape_before(scrapes, RATE_WINDOW, reach)
    tok_s = counter_rate(new, old, t1, t0, "generation_tokens_total")
    _, _, old_hist = scrape_before(scrapes, QUANTILE_WINDOW)
    ttft, recent = recent_quantile(hist, old_hist, "time_to_first_token_seconds", 0.95)
    running, waiting = requests(new)
    return {
        "state": engine_state(new, tok_s),
        "tok_s": rounded(tok_s, 1),
        "running": running,
        "waiting": waiting,
        "ttft_p95": ttft,
        "ttft_recent": recent,
        "finished": finished(new),
    }


def downsample(points: list[tuple[float, float]], limit: int) -> tuple[list[float], list[float]]:
    """A trace thinned to about `limit` points, evenly picked, the newest always kept: its times and its values as two
    lists."""
    if len(points) > limit:
        step = len(points) / limit
        points = [points[int(i * step)] for i in range(limit)] + [points[-1]]
    return [round(t, 1) for t, _ in points], [v for _, v in points]


SPEC_DRAFTS = "spec_decode_num_drafts_total"
SPEC_KEPT = "spec_decode_num_accepted_tokens_per_pos_total:"  # one counter per position of a draft
SPEC_MADE = "spec_decode_num_draft_tokens_per_pos_total:"


def one_window(new: dict, old: dict, positions: list[int]) -> bool:
    """Whether speculation can be counted between two readings. They have to be of one life of the engine: its start
    time says so, and where a reading carries none, a counter that is gone or differences no single life can give
    (fewer than before, more accepted than drafted, more drafted at one position than drafts were made). The older
    one has to hold every counter the newer one counts from, and something must have been drafted in between."""
    born, before = new.get("process_start_time_seconds"), old.get("process_start_time_seconds")
    if born is not None and before is not None and born != before:
        return False
    if any(key.startswith((SPEC_KEPT, SPEC_MADE)) and key not in new for key in old):
        return False
    drafts = gained(new, old, SPEC_DRAFTS) or 0.0
    for position in positions:
        kept, made = gained(new, old, f"{SPEC_KEPT}{position}"), gained(new, old, f"{SPEC_MADE}{position}")
        late = made is None and f"{SPEC_MADE}{position}" in new  # the older reading did not hold it yet
        if kept is None or kept < 0 or late or (made is not None and not kept <= made <= drafts):
            return False  # a draft holds one token of a position at most, and no more are accepted than drafted
    return drafts > 0


def speculation(new: dict, old: dict) -> dict:
    """How far drafted tokens survive, position by position: between two readings, or over the whole run so far where
    they give no window to count in (one_window). A counter the newer reading does not hold is no count of zero:
    the share, the reach or the length that hangs on it is None."""
    positions = sorted(int(k[len(SPEC_KEPT) :]) for k in new if k.startswith(SPEC_KEPT))
    if not positions:
        return {"positions": [], "mean_length": None}
    recent = one_window(new, old, positions)

    def amount(key: str) -> float | None:
        return gained(new, old, key) if recent else num(new.get(key))

    drafts = amount(SPEC_DRAFTS)
    kept = [amount(f"{SPEC_KEPT}{position}") for position in positions]
    rows = []
    for position, survived in zip(positions, kept):
        made = amount(f"{SPEC_MADE}{position}")
        rows.append(
            {
                "pos": position,
                "rate": round(survived / made, 3) if made and survived is not None else None,
                "reach": round(made / drafts, 3) if drafts and made is not None else None,
            }
        )
    known = drafts and None not in kept
    return {"positions": rows, "mean_length": round(1 + sum(kept) / drafts, 2) if known else None, "recent": recent}


LATENCY_NAMES = (
    ("First token", "time_to_first_token_seconds"),
    ("Per step", "inter_token_latency_seconds"),
    ("Per token", "request_time_per_output_token_seconds"),
    ("Queue", "request_queue_time_seconds"),
    ("Reading", "request_prefill_time_seconds"),
    ("Writing", "request_decode_time_seconds"),
    ("Whole request", "e2e_request_latency_seconds"),
)


def latency_table(hist: dict, old_hist: dict) -> list[dict]:
    """The latency figures of the deep view, median and 95th percentile each: of the window between two readings, or
    since the engine started where that window is empty or the older reading did not hold the histogram yet."""
    rows = []
    for word, name in LATENCY_NAMES:
        if name not in hist:
            continue
        recent = histogram_delta(hist[name], old_hist.get(name))
        whole = histogram_delta(hist[name], None)
        windowed = name in old_hist and quantile(recent, 0.5) is not None
        use, is_recent = (recent, True) if windowed else (whole, False)
        rows.append(
            {
                "name": word,
                "p50": rounded(quantile(use, 0.5), 4),
                "p95": rounded(quantile(use, 0.95), 4),
                "recent": is_recent,
            }
        )
    return rows


def window_ratio(new: dict, old: dict, top: str, bottom: str) -> float | None:
    """A share between two readings, like cache hits of queries. With nothing new in between, a counter the older
    reading did not hold yet, or more of the part than of the whole (no window gives that): the share since the
    engine started. None when the newer reading lacks one of the two counters, or the lower one is zero."""
    if num(new.get(top)) is None or not num(new.get(bottom)):
        return None
    part, whole = gained(new, old, top), gained(new, old, bottom)
    if part is not None and whole is not None and whole > 0 and 0 <= part <= whole:
        return part / whole
    return new[top] / new[bottom]


def window_mean(new: dict, old: dict, name: str) -> float | None:
    """The mean of a figure the engine sums per request (seconds, tokens) between two readings. With nothing new in
    between, or a counter the older reading did not hold yet: the mean since the engine started. None when the newer
    reading lacks the count or the sum, or counted nothing."""
    count_key, sum_key = name + "_count", name + "_sum"
    if not num(new.get(count_key)) or num(new.get(sum_key)) is None:
        return None
    count, total = gained(new, old, count_key), gained(new, old, sum_key)
    if count is not None and total is not None and count > 0 and total >= 0:
        return total / count
    return new[sum_key] / new[count_key]


def engine_speed(new: dict, old: dict, t1: float, t0: float) -> dict:
    """How fast the engine works right now, from two readings a rate window apart: output tokens, steps and prompt
    tokens per second, requests running and waiting, and the state that follows from them. Nothing is rounded. A
    count the engine did not send is None, and so is a state nobody can tell."""
    tok_s = counter_rate(new, old, t1, t0, "generation_tokens_total")
    running, waiting = requests(new)
    return {
        "tok_s": tok_s,
        "steps_s": counter_rate(new, old, t1, t0, "iteration_tokens_total_count"),
        "prompt_tok_s": counter_rate(new, old, t1, t0, "prompt_tokens_total"),
        "running": running,
        "waiting": waiting,
        "state": engine_state(new, tok_s),
    }


def engine_work(
    new: dict, old: dict, older: dict, hist: dict, old_hist: dict, tok_s: float | None, watts: float | None
) -> dict:
    """What the engine made of its work: how fast it reads prompts, the share of steps that wrote one token only,
    energy per token, the share of drafts and of prompt tokens it could use, how far drafts survive, requests done.
    `old` is the reading a rate window back, `older` and `old_hist` the one five minutes back, `watts` the GPU
    power of all Sparks, None where one of them has no reading of it. Nothing is rounded."""
    # prompt tokens computed and seconds of prefill between the two readings: without both there is no speed
    computed = gained(new, older, "request_prefill_kv_computed_tokens_sum")
    seconds = gained(new, older, "request_prefill_time_seconds_sum")
    one_token = None
    if "iteration_tokens_total" in hist and "iteration_tokens_total" in old_hist:  # no older reading: no window
        buckets = histogram_delta(hist["iteration_tokens_total"], old_hist["iteration_tokens_total"])
        upto_one = [count for le, count in buckets if le == 1]  # cumulative: every step of up to one token
        if upto_one and buckets[-1][1] > 0:  # a histogram without a bound at one token cannot say
            one_token = upto_one[0] / buckets[-1][1]
    return {
        "finished": finished(new),
        "prefill_tok_s": computed / seconds if (seconds or 0) > 0 and (computed or 0) > 0 else None,
        "one_token_share": one_token,
        "j_per_token": watts / tok_s if tok_s and tok_s >= 1 and watts else None,
        "accepted": window_ratio(
            new, old, "spec_decode_num_accepted_tokens_total", "spec_decode_num_draft_tokens_total"
        ),
        "prefix": window_ratio(new, old, "prefix_cache_hits_total", "prefix_cache_queries_total"),
        "survival": speculation(new, older),
    }


def node_figures(sample: dict, gpu: dict, memory: tuple, traffic: float | None, reasons: list[str] | None) -> dict:
    """The figures of one Spark from one sample, rounded as the page shows them. What was not read stays None.
    `memory` is (free, total) in bytes, `traffic` what its ring ports carried, `reasons` why its GPU slows down."""
    free, total = memory
    return {
        "w": rounded(gpu.get("w"), 1),
        "w_limit": rounded(gpu.get("limit"), 0),
        "util": rounded(gpu.get("util"), 0),
        "gpu_c": rounded(gpu.get("c"), 0),
        "mhz": rounded(gpu.get("mhz"), 0),
        "throttle": reasons,
        "cpu_pct": rounded(sample.get("cpu"), 0),
        "cpu_c": rounded(sample.get("cpu_c"), 0),
        "mem_free_gb": rounded(free / 2**30, 1) if free is not None else None,
        "mem_total_gb": rounded(total / 2**30, 0) if total else None,
        "net": rounded(traffic, 2),
        "tlimit": rounded(gpu.get("tlimit"), 0),
        "pstate": gpu.get("pstate"),
        "w_now": rounded(gpu.get("w_now"), 1),
    }
