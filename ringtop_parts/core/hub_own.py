"""The engine a Spark runs apart from the ring: its speed and queue, and when it starts or stops answering."""

from __future__ import annotations

import collections

from ringtop_parts.core.figures import UNCOUNTED, num, pace, restarted

# seconds the port of a running engine must stay silent before an event says so. Longer than the sampler takes to see
# that the container is gone (it looks at docker every 15 s): an engine stopped on purpose ends, it does not fail
OWN_SILENT = 25.0


class Own:
    """The part of the Hub that follows each Spark's own engine. Holds no state of its own."""

    def _own(self, name: str, node: dict, reading: dict, now: float) -> None:
        """The engine a Spark runs apart from the ring: speed and queue from its own counters, like the ring engine's.

        Only figures reach the node (and with it the page), never the counters themselves. An engine that answers
        without the counts of its requests and writes nothing is given like a silent one, with the word why."""
        self.own_at[name] = now
        model = reading.get("model") or reading.get("name") or "an engine"
        values = reading.get("engine")
        if values is None:
            silent = now - self.own_missed.setdefault(name, now)
            if silent >= OWN_SILENT and name in self.own_told:  # held: a slow answer is no event; said once
                self.event(now, name, "engine", f"Own engine stopped answering: {self.own_told.pop(name)}", "warn")
            node["own"] = {"model": model, "state": "offline"}
            return
        self.own_missed.pop(name, None)
        # read by a thread of its own, a reading waits for the next sample: the speed is counted over the moments the
        # readings were taken at. A sampler that sends none (the demo, an older one) is counted by their arrival.
        read_at = reading["t"] if num(reading.get("t")) is not None else now
        scrapes = self._own_window(name, model, values, read_at)
        scrapes.append((read_at, values, reading.get("hist") or {}))
        if self.own_told.get(name) != model:
            self.event(now, name, "engine", f"Own engine answers: {model}")
            self.own_told[name] = model
        figures = pace(scrapes, self.reach)
        if figures["state"] is None:  # it answers without saying what it does: no figure of it stands or is kept
            node["own"] = {"model": model, "state": "offline", "error": UNCOUNTED}
            return
        node["own"] = {"model": model, **figures}
        for key in ("tok_s", "running", "waiting", "ttft_p95"):
            self.remember(f"{name}.own_{key}", now, figures[key])

    def _own_window(self, name: str, model: str, values: dict, read_at: float) -> collections.deque:
        """The readings the speed of a Spark's own engine is counted over, before the newest one joins them. A new
        life of the engine, another model behind the same port, or a clock that went back on the Spark: each
        starts a window of its own, so no speed is counted across it."""
        scrapes = self.own_scrapes.setdefault(name, collections.deque(maxlen=self.scrapes.maxlen))
        if scrapes and (
            restarted(values, scrapes[-1][1]) or self.own_model.get(name) != model or read_at <= scrapes[-1][0]
        ):
            scrapes.clear()
        self.own_model[name] = model
        return scrapes

    def _own_gone(self, name: str, node: dict, now: float) -> None:
        """No running engine container with a published port is left on this Spark: stopped, which is no failure."""
        if name in self.own_told:
            self.event(now, name, "engine", f"Own engine ended: {self.own_told.pop(name)}")
        node["own"] = None
        self.own_scrapes.pop(name, None)
        self.own_missed.pop(name, None)
