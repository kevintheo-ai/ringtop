"""Why it is as fast as it is, in plain words: what holds the engine or a Spark back, worst first."""

from __future__ import annotations


def own_words(own: dict | None) -> str:
    """What a Spark's own engine does, for the line that names it. Nothing where there is no engine anybody can ask,
    and no count of requests the engine did not send."""
    if not own:
        return ""
    state = own.get("state")
    if state == "offline":  # its port is silent, or it answers without saying what it does (then with an error)
        return (
            "its engine answers without its request counters, " if own.get("error") else "its engine does not answer, "
        )
    queue = [f"{own['running']:.0f} running"] if own.get("running") is not None else []
    queue += [f"{own['waiting']:.0f} waiting"] if own.get("waiting") else []
    if state == "writing":
        return ", ".join([f"{own.get('tok_s') or 0:.0f} tokens/s", *queue]) + ", "
    if state == "reading":
        return ", ".join(["reading prompts", *queue]) + ", "
    return "its engine is asleep, " if state == "asleep" else "its engine is idle, "


THROTTLE_BITS = {0x4: "power cap", 0x8: "hardware slowdown", 0x20: "thermal", 0x40: "thermal", 0x80: "power brake"}
IDLE_BIT = 0x1  # the GPU is idle: set in the same mask, and no reason it slows down
LATCH_MHZ = 1000  # below this while working: the GB10 clock latch. The line spark-ds41f's doctor draws
LATCH_SAMPLES = 5  # in a row, before it is said
NEAR_LIMIT_C = 20  # a GPU closer than this to its thermal limit while working is worth a word


def throttle_reasons(mask: str | None) -> list[str] | None:
    """Why a GPU slows down, from its reasons mask. None when the mask was not read: unknown is not "no reason".
    A bit the table has no word for is a reason all the same, named by its value: "no reason" is only said of a
    mask that sets none, the bit for an idle GPU aside."""
    try:
        value = int(mask, 16)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value < 0:  # no mask
        return None
    named = sorted({label for bit, label in THROTTLE_BITS.items() if value & bit})
    rest = value & ~(IDLE_BIT | sum(THROTTLE_BITS))
    return named + [f"reason {1 << i:#x}" for i in range(rest.bit_length()) if rest >> i & 1]


def own_work(n: dict) -> str | None:
    """What loads a Spark when the ring engine does not: its own engine, or the biggest program on its GPU."""
    if not n["live"] or (n.get("util") or 0) < 50:
        return None
    box = n.get("box") or {}
    if box.get("running"):  # a container with the cluster label is the ring engine itself, whatever its port says
        if box.get("config"):
            return None
        # the engine that answered names itself: docker is looked at every 15 s, the box may still carry the one before
        return (n.get("own") or {}).get("model") or box.get("model") or box.get("name")
    apps = sorted(n.get("apps") or [], key=lambda a: a.get("gb") or 0, reverse=True)
    return apps[0].get("name") if apps else None


def _point(level: str, text: str, node: str | None = None) -> dict:
    """One line of the diagnosis, with how bad it is. A line about one Spark carries its name as `node`: the page of
    that Spark shows the lines about it. A line about the engine carries none."""
    return {"level": level, "text": text} if node is None else {"level": level, "text": text, "node": node}


def _sparks(count: int) -> str:
    """So many Sparks in words: one is "1 Spark"."""
    return f"{count} Spark" if count == 1 else f"{count} Sparks"


def fan_points(n: dict) -> list[dict]:
    """Fans of one Spark that stand still: all of them while it is warm, or one beside a twin that turns."""
    fans = [f for f in (n.get("fans") or []) if f is not None]
    if n.get("fan") == 0 and (n.get("gpu_c") or 0) >= 60:
        still = "the fan stands" if len(fans) == 1 else "the fans stand"  # one reading is one fan, no more is known
        return [_point("bad", f"{n['name']}: {still} still at {n['gpu_c']:.0f} °C.")]
    if len(fans) > 1 and min(fans) == 0 < max(fans):  # its twin makes up for it: no average shows this one
        each, still = " / ".join(f"{f:,.0f}" for f in fans), fans.count(0)
        said = "one of its {} fans stands" if still == 1 else f"{still} of its {{}} fans stand"
        return [_point("bad", f"{n['name']}: {said.format(len(fans))} still ({each} RPM).")]
    return []


def clock_points(n: dict) -> list[dict]:
    """What slows the GPU of one Spark, or is about to: the clock latch, a reason it names, heat, its limit near."""
    if n.get("latched"):
        return [
            _point(
                "bad",
                f"{n['name']} has its GPU clock stuck at {n['mhz']:.0f} MHz under load, with no reason given. This looks like "
                "the GB10 clock latch: a restart does not clear it, taking the power away for a minute does.",
            )
        ]
    if n.get("throttle"):
        return [_point("warn", f"{n['name']} is slowing down: {', '.join(n['throttle'])}.")]
    if (n.get("gpu_c") or 0) >= 85:
        return [_point("warn", f"{n['name']} runs hot at {n['gpu_c']:.0f} °C.")]
    if n.get("tlimit") is not None and n["tlimit"] < NEAR_LIMIT_C and (n.get("util") or 0) >= 50:
        return [_point("warn", f"{n['name']} is {n['tlimit']:.0f} °C from its thermal limit under load.")]
    return []


def memory_points(n: dict, guard: float | None) -> list[dict]:
    """Memory of one Spark running short: below the memory guard or close to it, or tasks stalling for it."""
    out = []
    free = n.get("mem_free_gb")
    if guard is not None and free is not None and free <= guard + 2:
        where = "below" if free < guard else "close to"
        out.append(_point("warn", f"{n['name']} has {free:.1f} GB free, {where} the {guard} GB memory guard."))
    if (n.get("psi") or 0) >= 10:
        out.append(_point("warn", f"{n['name']} is short of memory: tasks stalled {n['psi']:.0f} % of the last 10 s."))
    return out


def node_points(n: dict, guard: float | None) -> list[dict]:
    """Everything worth a word about one Spark, in the order it is said: fans, clock and heat, memory. Every line
    carries the name of the Spark."""
    if not n["live"]:
        return [_point("bad", f"{n['name']} is unreachable.", n["name"])]
    said = (*fan_points(n), *clock_points(n), *memory_points(n, guard))
    return [_point(point["level"], point["text"], n["name"]) for point in said]


def answers_alone(n: dict) -> bool:
    """Whether a Spark's own engine answers on its port: it says what it does, or it answers without the counts of
    its requests. That one is given like a silent engine, with the word why (its error); its port is not silent."""
    own = n.get("own") or {}
    return own.get("state") not in (None, "offline") or bool(own.get("error"))


def own_engines(live: list[dict]) -> dict[str, str]:
    """What each Spark works on by itself while the ring engine is silent: {Spark: model or program}. Nothing when
    one model runs on every Spark and none answers on a port of its own: that is the ring engine under another label."""
    running = [n for n in live if (n.get("box") or {}).get("running")]
    own = {n["name"]: what for n in live if (what := own_work(n))}
    answering = any(answers_alone(n) for n in live)
    if not answering and len(own) == len(live) > 1 and len(running) == len(live) and len(set(own.values())) == 1:
        return {}  # one model on every Spark is one engine across the cluster, unless each answers on a port of its own
    return own


def own_point(n: dict, what: str) -> dict:
    """The line for a Spark that works on its own: what it runs, how fast, and how much its GPU holds."""
    sizes = [a.get("gb") for a in n.get("apps") or []]  # of every program on that GPU: the biggest need
    whole = sizes and all(g is not None for g in sizes)  # not be the one named. One unread: no sum
    size = f", {sum(sizes):.1f} GB on the GPU" if whole and sum(sizes) else ""
    text = f"{n['name']} runs {what} on its own: {own_words(n.get('own'))}GPU {n['util']:.0f} % busy{size}."
    return _point("info", text, n["name"])


def silent(engine: dict, nodes: list[dict], points: list[dict]) -> dict:
    """The diagnosis while the ring engine does not answer: why, and what each Spark does on its own meanwhile.
    `points` are the lines about the Sparks, which follow in the order of the Sparks."""
    live = [n for n in nodes if n["live"]]
    running = [n for n in live if (n.get("box") or {}).get("running")]
    own = own_engines(live)
    said = [_point("bad", engine.get("error") or "No data.")]
    # a container whose engine answers on a port of its own is that Spark's own engine waiting for work, not this
    answers = [n["name"] for n in running if answers_alone(n)]
    engines = [n for n in running if n["name"] not in own and n["name"] not in answers]
    # counted among the Sparks that can be seen: what runs on one that is away, nobody knows. And not said of an
    # engine that answers without its request counters: its port is not silent
    if engines and not engine.get("answers"):
        seen = _sparks(len(live)) if len(live) == len(nodes) else f"the {_sparks(len(live))} that can be reached"
        text = f"The engine's container runs on {len(engines)} of {seen}, but nothing answers on its port."
        said.append(_point("warn", text))
    said += [own_point(n, own[n["name"]]) for n in live if n["name"] in own]
    busy = "is working on its own" if len(own) == 1 else "are working on their own"
    # an engine that answers without its request counters may be serving: nobody knows, and "not serving" is not said
    said_of = "Nobody knows what the {} does" if engine.get("answers") else "The {} is not serving"
    return {
        "headline": f"{said_of.format('ring engine')}; {len(own)} of {_sparks(len(nodes))} {busy}."
        if own
        else f"{said_of.format('engine')}.",
        "points": [*said, *points],
        "own": own,  # the tiles name each Spark's own work from this
    }


def engine_points(engine: dict) -> list[dict]:
    """What holds a serving engine back: requests queueing, prompts being read, a full cache, drafts thrown away."""
    out = []
    state = engine["state"]
    t = engine.get("timing") or {}
    parts = [t.get("queue"), t.get("prefill"), t.get("decode")]
    total = sum(parts) if None not in parts else 0
    if state in ("reading", "writing") and total > 0:
        waiting, reading = parts[0] / total, parts[1] / total
        if engine.get("waiting") and waiting >= 0.15:
            out.append(_point("warn", f"Requests are queueing: {waiting:.0%} of their time is spent waiting."))
        if reading >= 0.5:
            out.append(_point("info", f"Most of the time goes to reading prompts: {reading:.0%}."))
            if engine.get("prefix") is not None and engine["prefix"] < 0.3:
                out.append(_point("info", f"Only {engine['prefix']:.0%} of those prompts come from the cache."))
    if (engine.get("kv") or 0) >= 0.9:
        out.append(_point("warn", f"The KV cache is {engine['kv']:.0%} full, requests may be pushed out."))
    if engine.get("accepted") is not None and engine["accepted"] < 0.4 and state == "writing":
        out.append(_point("info", f"Speculation is often rejected: {engine['accepted']:.0%} of drafts survive."))
    return out


def diagnose(engine: dict, nodes: list[dict], guard: float | None) -> dict:
    """Why it is as fast as it is, in plain words, worst first."""
    points = [point for n in nodes for point in node_points(n, guard)]
    state = engine["state"]
    if state == "offline":
        return silent(engine, nodes, points)
    points += engine_points(engine)
    points.sort(key=lambda p: {"bad": 0, "warn": 1}.get(p["level"], 2))
    if state in ("idle", "asleep") and not points:
        headline = "Nothing is running." if state == "idle" else "The engine is asleep."
    else:
        headline = points[0]["text"] if points else "Nothing is holding it back right now."
    return {"headline": headline, "points": points}
