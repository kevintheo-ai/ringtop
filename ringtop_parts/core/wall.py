"""What a wall may get of a moment: a fixed list of its fields, part by part, each as the kind the list says, and
nothing beside the list."""

from __future__ import annotations

from ringtop_parts.core.figures import num


def number(value):
    """A figure a page can count with: a finite number that is no flag (figures.num). None for anything else."""
    return None if isinstance(value, bool) else num(value)


def text(value):
    """A text, or None for anything else: a table in the place of a name would carry what it likes."""
    return value if isinstance(value, str) else None


def flag(value):
    """Yes or no, or None for anything else."""
    return value if isinstance(value, bool) else None


def numbers(value):
    """A list of figures, each one a number or None in its place (the fans of a Spark). None for no list."""
    return [number(one) for one in value] if isinstance(value, list) else None


def texts(value):
    """A list of the texts in it (why a GPU is slowing down). None for no list."""
    return [one for one in value if isinstance(one, str)] if isinstance(value, list) else None


# The fields of a moment the calm page shows or reckons with, by the part they stand in, each with the kind it has to
# be of. A list of what passes, not of what is held back: a field that is added to a moment later stays in until
# somebody writes it down here, and what stands in a listed field passes only as that kind. Left out on purpose: why
# a Spark is out of reach (the last words of ssh), its container, its programs and threads, the events with their
# lines of the journal, the links, kernel and profile, all a run source says beside the name of its run, and the model
# the head serves: free text nothing on the calm page shows. What a field is listed for is that a script of the calm
# page reads it.
PLACE = {"name": text, "rank": number, "head": flag}  # a Spark as the cluster lists it
IDENTITY = {"interval": number, "memguard_gib": number}
ENGINE = {
    "state": text,
    "word": text,
    "tok_s": number,
    "running": number,
    "waiting": number,
    "error": text,
    "answers": flag,
}
SPARK = {
    **PLACE,
    "live": flag,
    "latched": flag,
    "mhz": number,
    "throttle": texts,
    "gpu_c": number,
    "tlimit": number,
    "util": number,
    "mem_free_gb": number,
    "mem_total_gb": number,
    "fan": number,
    "fans": numbers,
    "w": number,
}
# of the engine a Spark runs on its own
OWN = {
    "model": text,
    "state": text,
    "error": text,
    "tok_s": number,
    "running": number,
    "waiting": number,
    "ttft_p95": number,
}
RUN = {"source": text, "name": text, "done": number, "total": number, "started": number}
PARTS = (("identity", IDENTITY), ("engine", ENGINE), ("run", RUN))


def listed(part, kinds: dict) -> dict | None:
    """The fields of one part that are on its list, each as the kind the list says: one nobody read stays None and
    never becomes a 0, one of another kind is None too, one the part does not have is not made up. None for a part
    that is no table of fields."""
    return {key: kind(part[key]) for key, kind in kinds.items() if key in part} if isinstance(part, dict) else None


def wall_spark(node: dict) -> dict:
    """One Spark for a wall: its listed readings, and the listed figures of the engine it runs on its own, if any."""
    return {**listed(node, SPARK), "own": listed(node.get("own"), OWN)}


def by_spark(own: dict, sparks) -> dict:
    """What each Spark works on by itself, for a wall: the texts that stand under the name of one of these Sparks,
    as a wall gets them. A text under any other key stays in, like a field that is on no list."""
    names = {spark.get("name") for spark in sparks} - {None}
    return {name: what for name, what in own.items() if name in names and isinstance(what, str)}


def wall_moment(moment: dict) -> dict:
    """The moment a wall listener sends: the listed fields of the whole one, in its form, so the rules of the page
    read it as they read the whole. A part that is missing, or that is no table of fields, is left out; of what each
    Spark works on by itself only names pass, and only under the name of a Spark this wall moment lists: the page
    reads them by those names, and whatever else stands there stays in. Every figure in it is a finite number or
    None, so it is JSON any browser reads. The moment that came is not changed."""
    out = {"t": number(moment["t"])} if "t" in moment else {}
    cluster = moment.get("cluster")
    if isinstance(cluster, dict):
        places = [listed(place, PLACE) for place in cluster.get("nodes") or [] if isinstance(place, dict)]
        out["cluster"] = {"ring": flag(cluster.get("ring")), "nodes": places}
    for name, keys in PARTS:
        part = listed(moment.get(name), keys)
        if part is not None:
            out[name] = part
    if isinstance(moment.get("nodes"), list):
        out["nodes"] = [wall_spark(node) for node in moment["nodes"] if isinstance(node, dict)]
    why = moment.get("why")
    if isinstance(why, dict):
        own = why.get("own")
        out["why"] = {"own": by_spark(own, out.get("nodes", ()))} if isinstance(own, dict) else {}
    return out
