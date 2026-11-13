"""What comes in as text and must have the right shape: the node map of the cluster, the run a command names."""

from __future__ import annotations

import json
import re

from ringtop_parts.core.figures import num
from ringtop_parts.core.runs import clean_steps, count_of

SAFE_TARGET = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@-]*$")


def port_group(device: str) -> str:
    """The two PCIe functions of one physical port end in the same fN: they share a cable."""
    m = re.search(r"f(\d+)$", device)
    return f"f{m.group(1)}" if m else device


MOST_SPARKS = 16  # the page has lanes and neutral names for this many (page/scene-world.js, core/alerts.py NEUTRAL)


def node_of(n: dict) -> dict:
    """One node of the map as ringtop uses it: its name, its rank, whether the map names it the head, and the peer
    behind each ring port (peers_of). Ends ringtop on a name that is no safe SSH host, a rank that is no whole number
    and a head that is no yes or no."""
    if n.get("name") is None or not SAFE_TARGET.match(str(n["name"])):
        raise SystemExit(f"Node name not usable as an SSH host: {n.get('name')!r}")
    try:
        rank = int(n["rank"])
    except (KeyError, TypeError, ValueError, OverflowError):  # OverflowError: a rank of 1e999 reads as infinite
        rank = None
    if rank is None or (rank != n["rank"] and not isinstance(n["rank"], str)):  # 1.5 is no rank, "2" is one
        raise SystemExit(f"Rank of {n['name']!r} not usable: {n.get('rank')!r}")
    if n.get("head") not in (None, True, False):  # 0 and 1 are those too; a text is not
        raise SystemExit(f"Head of {n['name']!r} not usable: {n['head']!r}")
    return {"name": n["name"], "rank": rank, "head": bool(n.get("head")), "peers": peers_of(n)}


def peers_of(n: dict) -> dict:
    """The peer behind each ring port of one node, by the port its devices share. Ends ringtop where the map names
    them in another shape: no table of ranks, a peer that is no rank, devices that are no list of names."""
    hcas, peers = n.get("roce_peer_hcas") or {}, {}
    for peer, devices in hcas.items() if isinstance(hcas, dict) else [(None, None)]:
        if not str(peer).isdecimal() or not isinstance(devices, list) or not all(isinstance(d, str) for d in devices):
            raise SystemExit(f"Ring ports of {n['name']!r} not usable: {hcas!r}")
        for device in devices:
            peers[port_group(device)] = int(peer)
    return peers


def parse_cluster(node_map: dict) -> dict:
    """The node map as ringtop uses it: the nodes by rank with the peer behind each ring port, the SSH user, and whether
    they form a ring. Ends ringtop with a word on a map it cannot show: no nodes, a node node_of refuses, a rank twice,
    more than MOST_SPARKS Sparks, more than one head. A map that names no head is one: ringtop finds the head itself
    (core/heads.py). The one Spark of a map of one is its head."""
    listed = node_map.get("nodes") if isinstance(node_map, dict) else None
    if not isinstance(listed, list) or not listed or not all(isinstance(n, dict) for n in listed):
        raise SystemExit("The node map lists no nodes")
    nodes = sorted((node_of(n) for n in listed), key=lambda node: node["rank"])
    ranks = [n["rank"] for n in nodes]
    twice = sorted({rank for rank in ranks if ranks.count(rank) > 1})
    if twice:
        raise SystemExit(f"Rank {twice[0]} stands twice in the node map")
    if len(nodes) > MOST_SPARKS:
        raise SystemExit(f"The node map has {len(nodes)} Sparks; ringtop shows at most {MOST_SPARKS}")
    heads = [n["name"] for n in nodes if n["head"]]
    if len(heads) > 1:
        raise SystemExit(f"The node map names more than one head: {', '.join(map(str, heads))}")
    if len(nodes) == 1:
        nodes[0]["head"] = True
    user = node_map.get("ssh_user")
    if user is not None and not SAFE_TARGET.match(str(user)):
        raise SystemExit(f"SSH user not usable: {user!r}")
    return {"user": user, "nodes": nodes, "ring": len(nodes) > 1 and all(n["peers"] for n in nodes)}


RUN_TEXT, RUN_NUMBERS = ("name", "group", "holder", "until", "detail"), ("started", "done", "total")
# the dash (U+2013) the page writes for whatever nobody read: `whole` in page/base.js, `figure` in page/measure.js
UNREAD = chr(0x2013)


def parse_runs(text: str) -> dict | None:
    """Output of --runs-cmd: one JSON object, or a list whose first entry is shown. It goes into every moment, so it
    becomes JSON any browser reads: a number that is not finite, or that no float holds, is None wherever it stands.
    Of the run only the fields a run source may give pass, each in its kind: its texts, its start and counts, its
    stations (clean_steps, every one of them: the page counts them and finds the one that runs), its tracks and the
    answers it gives as tables; whatever else it prints stays here. A run whose name is no text that says something
    is refused with a ValueError. Whether it names a run at all is read from the text as it was printed: only null
    or an empty list name none, a number no browser reads in their place is a source that failed. A whole number is
    read as a float there, which never fails (whole)."""
    said = json.loads(text, parse_int=float)
    if isinstance(said, list):
        said = said[0] if said else None
    if said is None:
        return None
    if not isinstance(said, dict) or not isinstance(said.get("name"), str) or not said["name"]:
        raise ValueError("needs an object with a name")
    value = json.loads(text, parse_constant=lambda _: None, parse_float=lambda s: num(float(s)), parse_int=whole)
    value = value[0] if isinstance(value, list) else value
    run = {key: value[key] for key in RUN_TEXT if isinstance(value.get(key), str)}
    # the Hub counts with the start: a moment that is no number would end every view with an error; the pages count
    # with how far the run is and how much it has to do: a count that is no number is one nobody read
    run.update({key: value[key] for key in RUN_NUMBERS if count_of(value.get(key)) is not None})
    steps = clean_steps(value.get("steps"), keep=None)
    if steps is not None:  # a station whose name nobody can read is called by the dash the page writes for that
        run["steps"] = [{**station, "name": station.get("name") or UNREAD} for station in steps]
    if "tracks" in value:
        run["tracks"] = clean_tracks(value["tracks"])
    if isinstance(value.get("replies"), list):
        run["replies"] = [reply for reply in value["replies"] if isinstance(reply, dict)]
    return run


def whole(text: str):
    """A whole number as JSON prints it, where a float holds it (num), else None. One of more than 309 digits fits
    in no float and is not read at all: Python refuses to read one of more than 4300 digits."""
    return None if len(text.lstrip("-")) > 309 else num(int(text))


TRACK_TEXT, TRACK_NUMBERS = ("node", "model", "name"), ("done", "total", "started")


def clean_tracks(value) -> list[dict]:
    """The tracks a run source names: one per Spark that works through jobs of its own. They come from a command
    outside and the page shows them, so only the known fields in the known shapes get through."""
    out = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        track = {k: item[k][:120] for k in TRACK_TEXT if isinstance(item.get(k), str)}
        track.update(
            {k: item[k] for k in TRACK_NUMBERS if not isinstance(item.get(k), bool) and num(item.get(k)) is not None}
        )
        if track:
            out.append(track)
    return out[:64]
