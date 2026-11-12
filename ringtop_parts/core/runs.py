"""Which run is running, and what is kept of it: the run a source names, when that is the run known before, when it
has ended, and the record of it."""

from __future__ import annotations

from ringtop_parts.core.figures import num

RUN_SAME = 30.0  # seconds the start a source names may move and still be the start of the same run
RUN_QUIET = 30.0  # seconds a source has to name no run before the run it named is believed to have ended
STEP_STATES = ("done", "failed", "running", "pending")  # the states of a station of a queue the page knows


def named(run: dict) -> dict | None:
    """The run a run source names in what the page shows as running: its source, its name and the start it gives.
    None where nobody outside names what runs: the engine serving, a benchmark process, a failed source, nothing.
    A name is a text that says something. A list, a number or an object in its place names no run: the record of
    one would be none this program reads again (is_record)."""
    name = run.get("name")
    if run.get("source") not in ("command", "lab") or not isinstance(name, str) or not name:
        return None
    return {"source": run["source"], "name": name, "started": num(run.get("started")) or None}


def same_run(known: dict, said: dict) -> bool:
    """Whether a source names the run that is known: the same source, the same name, and a start less than RUN_SAME
    from the one it named last. A source that gives no start says nothing against it. The same name with a start
    further off is that job begun anew."""
    if (known["source"], known["name"]) != (said["source"], said["name"]):
        return False
    before, now = known["started"], said["started"]
    return before is None or now is None or abs(now - before) < RUN_SAME


def step(known: dict | None, said: dict | None, heard: bool, now: float) -> tuple[dict | None, float | None, bool]:
    """One look at what the source of a run says. Gives the run that is open after it, the moment the run known
    before ended (None while it has not), and whether the run now open has only just started.

    `known` is the run that was open, `said` the run a source names now (named), `heard` whether the source of the
    known run can be heard. While the source names the known run, nothing happened, and the run goes by the start
    it named last. A source that cannot be heard says nothing: the run stays. A source that is heard and names no
    run is believed once it has said so for RUN_QUIET; the run then ended at the moment it first said so, which
    the run keeps as `quiet` until then. Another run named ends the known one at once: at that first moment where
    the source had named none before, else now."""
    if known and said and same_run(known, said):
        return {**known, "started": said["started"] or known["started"], "quiet": None}, None, False
    if known and not said:
        if not heard:
            return known, None, False
        quiet = now if known["quiet"] is None else known["quiet"]
        if now - quiet < RUN_QUIET:
            return {**known, "quiet": quiet}, None, False
        return None, quiet, False
    ended = None if not known else now if known["quiet"] is None else known["quiet"]
    return ({**said, "quiet": None} if said else None), ended, bool(said)


def count_of(value) -> float | None:
    """A count a run source gives, where it is a finite number: yes and no are none, and a text is none."""
    return None if isinstance(value, bool) else num(value)


def clean_steps(value, keep: int | None = 64) -> list[dict] | None:
    """The stations of a queue as a run source names them: of each its name, its state, the seconds it took and
    the seconds it took the time before. They come from a command outside and the page shows them, so only the
    known fields in the known shapes get through, and `keep` stations at most: 64 for the record of a run, all of
    them (None) for the moment, whose count and running station the page says. None where the source gives no
    list: that is not a queue without stations."""
    if not isinstance(value, list):
        return None
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        station = {"name": item["name"][:120]} if isinstance(item.get("name"), str) else {}
        if item.get("state") in STEP_STATES:
            station["state"] = item["state"]
        station.update({key: item[key] for key in ("seconds", "was") if count_of(item.get(key)) is not None})
        if station:
            out.append(station)
    return out[:keep]


def told(run: dict) -> dict:
    """What a source says of its run beside name and start, as the record keeps it: the queue it belongs to, how
    far it is, its stations as named now, and how many tracks it names (Sparks that work through jobs of their
    own). What the source does not say, or says in no known shape, is None."""
    group, tracks = run.get("group"), run.get("tracks")
    return {
        "group": group[:120] if isinstance(group, str) else None,
        "done": count_of(run.get("done")),
        "total": count_of(run.get("total")),
        "steps": clean_steps(run.get("steps")),
        "tracks": len(tracks) if isinstance(tracks, list) else None,
    }


def opened(run: dict, now: float) -> dict:
    """The record of a run that was just seen for the first time, from what `step` holds of it: its id (the
    millisecond it was first seen, which it keeps), when it was first seen, and that it is open. Its sums count
    from this moment (`counted_from`; a later one once ringtop was away from the run), and it was not written to
    the history yet (`saved`)."""
    seen = {"id": round(now * 1000), "first_seen": now, "last_heard": now, "counted_from": now, "saved": None}
    return {**run, **seen, "ended": None, "open": True}


def closed(record: dict, ended: float | None) -> dict:
    """The record of a run that has ended, at the moment given; None where nobody saw it end."""
    return {**{key: value for key, value in record.items() if key != "quiet"}, "ended": ended, "open": False}


# What a record has to hold to be read, by what each field is: a text that says something, yes or no, a finite
# number, a finite number or nothing. These are the fields the hub and the card of a run count and decide with.
RECORD_TEXTS = ("source", "name")
RECORD_FLAGS = ("open",)
RECORD_NUMBERS = ("id", "first_seen", "last_heard", "counted_from", "sparks", "lives", "gpu_from")
RECORD_NUMBERS += ("token_s", "token_gap_s", "gpu_read_s", "gpu_gap_s")
RECORD_MAYBE = ("started", "saved", "ended", "tokens", "engine_steps", "tok_s_peak", "gpu_wh")


def is_record(value) -> bool:
    """Whether what a row of the history holds is the record of a run as this program reads one: an object with
    every field it counts and decides with, each of its kind. Anything else is none: no object, a field missing,
    a text where a number belongs. What a source says beside that (queue, counts, stations, tracks) and the model
    are not asked for: they are shown, and the page takes them only in the shapes it knows."""
    if not isinstance(value, dict):
        return False
    return (
        all(isinstance(value.get(key), str) and value[key] for key in RECORD_TEXTS)
        and all(isinstance(value.get(key), bool) for key in RECORD_FLAGS)
        and all(count_of(value.get(key)) is not None for key in RECORD_NUMBERS)
        and all(key in value and (value[key] is None or count_of(value[key]) is not None) for key in RECORD_MAYBE)
    )
