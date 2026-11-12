"""The made-up clusters the demo can play (--demo-form): their node maps, and what their Sparks show beyond the ring of
four the demo always played. Plain tables; core/demo.py plays them."""

from __future__ import annotations

BOARD = "demo-gb10"  # the board of another maker's machine: the page draws its Spark as a plain box
FIRST_PART_AT = 2  # where find4 runs the first part of its ring engine: the head ringtop has to find
# every form by its name: how many Sparks, how they are cabled ("ring", "switch", or not at all), whether the map
# names the head, and the place of the Spark with the other board (None: no Spark sends a board, as ever)
FORMS = {
    "ring4": (4, "ring", True, None),
    "one": (1, None, True, None),
    "ring2": (2, "ring", True, None),
    "ring3": (3, "ring", True, 1),
    "ring6": (6, "ring", True, None),
    "switch4": (4, "switch", True, 1),
    "find4": (4, "ring", False, None),
}


def demo_map(form: str = "ring4") -> dict:
    """The node map of a made-up cluster, as config/nodes.json holds one: Sparks spark-0 and on by rank, in a ring
    each cabled to the next and to the one before, on a switch to no other Spark; the first is the head where the
    form names one."""
    count, cabling, named, _ = FORMS[form]
    nodes = []
    for i in range(count):
        node: dict = {"name": f"spark-{i}", "rank": i, "head": named and i == 0}
        if cabling == "ring":
            peers: dict = {}
            peers.setdefault(str((i + 1) % count), []).append("rocep1s0f0")
            peers.setdefault(str((i - 1) % count), []).append("rocep1s0f1")
            node["roce_peer_hcas"] = peers
        elif cabling == "switch":
            node["roce_hcas"] = ["rocep1s0f0", "rocep1s0f1"]
        nodes.append(node)
    return {"ssh_user": "demo", "nodes": nodes}


def round_of(form: str = "ring4") -> dict:
    """What the Sparks of a made-up cluster show beyond the ring of four, as the fields of its Round: the board each
    one reads (empty: none is sent), and the program each runs as its part of the ring engine (empty: every one the
    first part, as ever; find4 has its first part at FIRST_PART_AT and the others in turn after it)."""
    count, _, named, foreign = FORMS[form]
    boards = [] if foreign is None else [BOARD if i == foreign else None for i in range(count)]
    parts = [] if named else [f"VLLM::Worker_TP{(i - FIRST_PART_AT) % count}" for i in range(count)]
    return {"boards": boards, "tp": parts}
