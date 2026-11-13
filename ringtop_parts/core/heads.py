"""Which Spark is the head where the node map names none: read off the programs every Spark runs on its GPU, one look
at a time. Plain rules; the hub looks every 15 s (connect/shell.py, seek_head) and sets the head they find."""

from __future__ import annotations

import re

PART = re.compile(r"_TP(\d+)$")  # vLLM names each part of an engine over several GPUs after it: VLLM::Worker_TP0, _TP1
# The four sentences of the look for a head, set in here word for word. "none" and
# "several" stand on the engine while there is no head; "found" is the event of the Spark taken for it, whose name
# stands in the event's own field: the page puts it in front of the text. "unread" stands on the engine while there
# is no head and the looks were held for a minute (core/hub.py, HELD_LOOKS).
WORDS = {
    "none": "No Spark shows TP0 of a multi-Spark engine. Name the head in --nodes.",
    "several": "Several Sparks look like the head; none chosen. Name it in --nodes.",
    "found": "Read as the head; token rate now comes from it.",
    "unread": "No head chosen: not every Spark's GPU programs are read. Name it in --nodes.",
}


def parts(node: dict) -> set[int] | None:
    """The parts of an engine over several Sparks this Spark runs: the n of every program on its GPU named …_TP<n>.
    None where that is not known: the Spark is away, or its programs were not read."""
    apps = node.get("apps")
    if not node.get("live") or not isinstance(apps, list):
        return None
    names = [app.get("name") for app in apps if isinstance(app, dict)]
    return {int(m.group(1)) for m in (PART.search(name) for name in names if isinstance(name, str)) if m}


def candidates(nodes: list[dict]) -> list[str]:
    """The Sparks that look like the head, in the order of the map: each runs the first part of an engine (…_TP0)
    while another Spark runs a later part of one. A Spark whose parts are not known counts neither way."""
    known = {node["name"]: parts(node) for node in nodes}
    known = {name: found for name, found in known.items() if found is not None}
    later = {name for name, found in known.items() if any(k >= 1 for k in found)}
    return [name for name, found in known.items() if 0 in found and later - {name}]


def held(nodes: list[dict]) -> bool:
    """Whether a look at the Sparks holds still: a live Spark's programs are not known, and that Spark may be the
    head."""
    return any(node.get("live") and not isinstance(node.get("apps"), list) for node in nodes)


def look(nodes: list[dict], head: str | None, last: str | None) -> tuple[str | None, str | None, str | None]:
    """One look at the Sparks, given the head so far and the one candidate the look before found. Gives the head after
    this look, the one candidate to remember for the next, and the word for the engine while there is no head (None:
    the word stays). A head is set, or changed, only where the same one Spark looked like it twice in a row; nothing
    found and several found leave a head as it is. While a live Spark's programs are not known the look changes
    nothing at all: that Spark may be the one."""
    if held(nodes):
        return head, last, None
    found = candidates(nodes)
    one = found[0] if len(found) == 1 else None
    if one is not None and one == last and one != head:
        return one, one, None
    if head is not None or one is not None:
        return head, one, None
    return None, None, WORDS["several"] if found else WORDS["none"]
