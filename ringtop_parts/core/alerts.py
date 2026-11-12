"""What a phone is told of, and when: the five troubles of a ring read off a moment, how long each has to last
before it is said, the cap of a day, what a restart keeps, and the fixed texts. No clock and nothing outside:
the moment and the time are handed in."""

from __future__ import annotations

from ringtop_parts.core.diagnose import LATCH_MHZ, fan_points
from ringtop_parts.core.figures import num

# The troubles a phone is told of, in the order they are said in: a Spark that sends nothing, a GPU clock stuck
# low, a fan that stands, a link of the ring that is down, the ring engine silent on its port.
TROUBLES = ("away", "latch", "fan", "link", "engine")
# What a moment says of one trouble on one thing (a Spark, a link, the ring engine). The third reading is None:
# nobody knows. That one starts no message and ends none.
BAD, GOOD = "bad", "good"
# Whether a silent ring engine is no trouble while the run source says a lab window holds the ring (it names
# who holds it, or the tracks of the Sparks): its port is often silent on purpose then. An engine that answers
# is good either way, and the four troubles of the hardware are read as ever. No message then. The one place to
# turn this round.
LAB_SILENCE = True


def away(node: dict) -> str | None:
    """Whether a Spark sends nothing: it is not live. Not known where the moment says neither yes nor no."""
    live = node.get("live")
    return GOOD if live is True else BAD if live is False else None


def latch(node: dict) -> str | None:
    """Whether the GPU clock of a Spark is stuck low: the hub says so after five samples in a row. That it is
    free is only known of a GPU that works at a normal clock: the hub's word falls when the load ends as well,
    and that frees no clock. Not known without load, and of a Spark that is away."""
    if node.get("live") is not True:
        return None
    if node.get("latched") is True:
        return BAD
    util, mhz = num(node.get("util")), num(node.get("mhz"))
    return GOOD if util is not None and mhz is not None and util >= 50 and mhz >= LATCH_MHZ else None


def fan(node: dict) -> str | None:
    """Whether a fan of a Spark stands, as the diagnosis of the page has it: all of them while it is warm, or
    one beside a twin that turns. That they turn is only known when every one was read above zero. Not known of
    a Spark that is away, with a fan nobody read, or with all of them still while it is cool."""
    if node.get("live") is not True:
        return None
    if fan_points(node):
        return BAD
    fans = node.get("fans")
    turning = isinstance(fans, list) and fans and all(num(f) is not None and f > 0 for f in fans)
    return GOOD if turning else None


def links(edges) -> dict[str, str | None]:
    """Every link of the ring by the Spark and the port it leaves from: down or up as it was read, not known
    where nobody read it (its Spark is away)."""
    out = {}
    for edge in edges if isinstance(edges, list) else []:
        if isinstance(edge, dict):
            up = edge.get("up")
            out[f"{edge.get('from')}/{edge.get('group')}"] = BAD if up is False else GOOD if up is True else None
    return out


def lab_holds(run) -> bool:
    """Whether the run source says a lab window holds the ring: it names a holder, or tracks. Only asked
    whether one is there: what stands in it is a text from outside, and is never read."""
    return isinstance(run, dict) and bool(run.get("holder") or run.get("tracks"))


def engine(moment: dict, nodes: list[dict]) -> str | None:
    """Whether the ring engine is silent on its port while the head answers. Good when it says what it does. Not
    known while nobody can ask the head, while it answers without its request counters, and (LAB_SILENCE)
    while a lab window holds the ring."""
    said = moment.get("engine")
    state = said.get("state") if isinstance(said, dict) else None
    if not isinstance(state, str) or not state:
        return None
    if state != "offline":
        return GOOD
    head = any(node.get("head") is True and node.get("live") is True for node in nodes)
    if not head or said.get("answers") or (LAB_SILENCE and lab_holds(moment.get("run"))):
        return None
    return BAD


def readings(moment: dict) -> dict[str, dict[str, str | None]]:
    """What a moment says of every trouble: for each one, every thing it can be read of (a Spark by its name, a
    link by where it leaves from, the ring engine) with BAD, GOOD or None for not known. A part the moment does
    not have gives no reading, and never an error. The names stay in here: no message is made from them."""
    listed = moment.get("nodes")
    nodes = [n for n in listed if isinstance(n, dict) and isinstance(n.get("name"), str)] if listed else []
    return {
        "away": {node["name"]: away(node) for node in nodes},
        "latch": {node["name"]: latch(node) for node in nodes},
        "fan": {node["name"]: fan(node) for node in nodes},
        "link": links(moment.get("edges")),
        "engine": {"ring": engine(moment, nodes)},
    }


# Seconds a trouble has to last without a break before the phone is told of it, and seconds it has to be over
# without a break before the phone is told that. The one table of the waits, chosen to tell a phone later rather
# than sooner. The fault round of the demo runs them at a twentieth (`pace`).
WAITS = {
    "away": (240.0, 120.0),
    "latch": (120.0, 120.0),
    "fan": (120.0, 120.0),
    "link": (120.0, 120.0),
    "engine": (1200.0, 120.0),
}
GAP = 60.0  # seconds without a moment (the Mac slept, the ticker hung) after which every wait starts anew
DAY = 86400.0
CAP = 12  # messages that go out within a day at most; the last of them says that Ringtop is silent now
CAP_REOPENS = 6  # and it speaks again once no more than this many lie within the last day


def begun(saved=None) -> dict:
    """The state a start begins with, from what the start before kept (`kept`), or from nothing where that is
    missing or cannot be read: field by field, so a broken one costs at most one message told twice.

    `told`: what the phone was last told of each trouble, and got. `sent`: when the messages of the last day went
    out. `hushed`: the cap of the day is shut. `held`: the troubles the start before told of; which things had
    them was not kept, so every thing counts as having it until it was read good for the wait. `marks`: of every
    trouble and thing what it reads, since when, and whether it is open (has the trouble, as far as the waits
    go). `seen`: when the moment before came. `again`: the message that may have reached the phone and goes
    once more (`delivered`); not kept across a start."""
    saved = saved if isinstance(saved, dict) else {}
    named, times = saved.get("told"), saved.get("sent")
    on = [trouble for trouble in TROUBLES if isinstance(named, list) and trouble in named]
    times = [t for t in times if not isinstance(t, bool) and num(t) is not None] if isinstance(times, list) else []
    return {
        "told": {trouble: trouble in on for trouble in TROUBLES},
        "sent": sorted(times)[-CAP:],
        "hushed": saved.get("hushed") is True,
        "held": set(on),
        "marks": {trouble: {} for trouble in TROUBLES},
        "seen": None,
        "again": None,
    }


def kept(state: dict) -> dict:
    """What a start keeps for the next one, as plain JSON: what the phone was told, when messages went out, and
    whether the cap is shut. No name of a Spark or a link, and no wait: those start anew."""
    on = [trouble for trouble in TROUBLES if state["told"][trouble]]
    return {"told": on, "sent": list(state["sent"]), "hushed": state["hushed"]}


def marked(mark: dict | None, reading: str | None, held: bool, now: float, anew: bool, waits: tuple) -> dict:
    """One thing after one look at it. What it reads counts from the first look that read the same in a row
    (`anew`: from this look, after a gap). Bad for the first wait opens it, good for the second closes it,
    and a reading nobody knows leaves it as it is. A thing first seen is open only if its trouble is `held`."""
    mark = mark or {"is": None, "since": now, "open": held}
    if anew or reading != mark["is"]:
        mark = {**mark, "is": reading, "since": now}
    lasted = now - mark["since"]
    if reading == BAD and lasted >= waits[0]:
        return {**mark, "open": True}
    if reading == GOOD and lasted >= waits[1]:
        return {**mark, "open": False}
    return mark


def step(state: dict, said: dict, now: float, pace: float = 1.0) -> dict:
    """One look at a moment: the state after it. `said` is what the moment reads (`readings`), `now` the clock,
    `pace` what the waits are multiplied by. A thing the moment does not name reads as not known. After GAP
    seconds without a look, or with a clock that went back, every wait starts anew. A message the cap counts
    leaves it a day after it was sent; one that lies ahead of a clock set back counts as sent now, so a clock
    that goes back opens the cap no sooner (and shuts it for a day at most). A trouble held from the start
    before is let go once every thing known of it is closed. Nothing is changed in the state handed in."""
    anew = state["seen"] is None or not 0 <= now - state["seen"] <= GAP
    marks, held = {}, set(state["held"])
    for trouble in TROUBLES:
        before, reads = state["marks"][trouble], said.get(trouble) or {}
        waits = tuple(wait * pace for wait in WAITS[trouble])
        things = {
            thing: marked(before.get(thing), reads.get(thing), trouble in held, now, anew, waits)
            for thing in {*before, *reads}
        }
        if things and not any(mark["open"] for mark in things.values()):
            held.discard(trouble)
        marks[trouble] = things
    sent = [min(t, now) for t in state["sent"] if now - t < DAY]  # what lies ahead of a clock set back: sent now
    hushed = len(sent) >= CAP or (state["hushed"] and len(sent) > CAP_REOPENS)
    return {**state, "marks": marks, "held": held, "sent": sent, "hushed": hushed, "seen": now}


def due(state: dict) -> str | None:
    """The one message that is to go out now, as a key of TEXTS, or None. A message is due while what the phone
    was told of a trouble is not what is so: the trouble has an open thing (or is held) and the phone was not
    told, or the other way round. So nothing queues: what is no longer so is no longer due. The first trouble in
    the order of TROUBLES goes first; the second copy of a message that may have reached the phone (`again`)
    goes when nothing else is due, while its trouble is still as it says. The last message the cap of the day
    allows is the word that Ringtop is silent now, whatever was due. While the cap is shut, nothing is."""
    if state["hushed"]:
        return None
    wants = {
        trouble: trouble in state["held"] or any(mark["open"] for mark in state["marks"][trouble].values())
        for trouble in TROUBLES
    }
    for trouble in TROUBLES:
        if wants[trouble] != state["told"][trouble]:
            return "quiet" if len(state["sent"]) >= CAP - 1 else f"{trouble} {'on' if wants[trouble] else 'off'}"
    return state["again"]  # set only while the day has room for it (delivered), and only while it is still so


def delivered(state: dict, key: str, now: float, sure: bool = True) -> dict:
    """The state after the message of a key went out: it counts towards the cap of the day, and the phone has
    been told. So it is with a message that may have reached the server though the server did not say so (`sure`
    false), and that one goes once more (`again`) if the day has room for it beside the word of the cap: two
    copies of one message are the most a phone gets. A second copy still to go ends with the next message of its
    own trouble (the copy itself, or the end of it), or when the day has no room left for it; a message of
    another trouble leaves it pending, and a newer first copy takes its place. The word of the cap shuts the cap
    (it is the last the day has room for, so it never goes twice)."""
    sent, pending = [*state["sent"], now], state["again"]
    if pending is not None and (pending.split()[0] == key.split()[0] or len(sent) >= CAP - 1):
        pending = None
    if not sure and state["again"] != key and len(sent) < CAP - 1:
        pending = key
    state = {**state, "sent": sent, "again": pending}
    if key == "quiet":
        return {**state, "hushed": True}
    trouble, word = key.split()
    return {**state, "told": {**state["told"], trouble: word == "on"}}


# The only names a message may carry: the neutral name of the Spark at each place of the ring, as the page shows
# it with ?names=neutral (page/neutral.js, aliasPairs: spark-1 at place 0). A closed table of sixteen; nothing of
# a moment but the number of a place picks one of them (alias).
NEUTRAL = tuple(f"spark-{place + 1}" for place in range(16))
NAMED = ("away", "latch", "fan", "link")  # the troubles whose message names the Sparks it is about, when it begins
GAP_MARK = "<sparks>"  # where the text of such a message names them: once in it
MOST_NAMED = 4  # more Sparks than this, and the gap holds MANY instead of their names
# Every message a phone can get, by its key: two for each trouble and the word of the cap. Fixed texts: no
# value of a moment and no figure ever gets into one, since they pass servers of others; only the gap of a
# named trouble holds names of the table (gap_for). The final wording, set in word for word;
# tests/test_alerts_texts.py holds it too.
TEXTS = {
    "away on": {
        "title": "Ringtop: Spark not reporting",
        "body": "No data arrives from <sparks>. Ringtop cannot tell whether power, network, SSH or a hung reader process is the cause.",
    },
    "away off": {
        "title": "Ringtop: Sparks reporting again",
        "body": "Every Spark sends data to ringtop again.",
    },
    "latch on": {
        "title": "Ringtop: GPU clock far below normal",
        "body": "Under load the GPU clock stays far below normal on <sparks>. Looks like the clock latch: the GPU gives no reason, and a reboot does not clear it.",
    },
    "latch off": {
        "title": "Ringtop: GPU clock normal again",
        "body": "Every GPU that was held low has been seen at normal clock under load again.",
    },
    "fan on": {
        "title": "Ringtop: fan stopped",
        "body": "A fan reads as stopped on <sparks>. This holds for all fans of a warm Spark, or for a fan beside a spinning fan.",
    },
    "fan off": {
        "title": "Ringtop: fans spinning again",
        "body": "Every fan that was stopped reads as spinning again.",
    },
    "link on": {
        "title": "Ringtop: link inactive or port gone",
        "body": "Ends of each affected link: <sparks>. Ringtop cannot tell cable, port, far side or a Spark that is off apart.",
    },
    "link off": {
        "title": "Ringtop: ring links active again",
        "body": "Every link that was down reports active again.",
    },
    "engine on": {
        "title": "Ringtop: engine not answering",
        "body": "The ring's engine does not answer on its port, although the head Spark does. Ringtop cannot tell whether this is intended.",
    },
    "engine off": {
        "title": "Ringtop: engine answering again",
        "body": "The ring's engine answers on its port again and says what it is doing.",
    },
    "quiet": {
        "title": "Ringtop: many changes in a day",
        "body": "Ringtop holds back further messages for a while; the state can change meanwhile and the page shows it. Silence is not an all-clear.",
    },
}
MANY = "at least one Spark"  # the gap of more than MOST_NAMED, of none, or of one that has no place
# The mark of a text that is not written yet. No text carries it now; one that did would go to a catcher on this
# machine and to no other place (connect/notify.py holds it back), so a placeholder put in later cannot leave.
PLACEHOLDER = "PLACEHOLDER"
# How a message shows on the phone, by the last word of its key: how urgent ntfy is to take it, and its sign.
LOOKS = {"on": ("high", "warning"), "off": ("default", "white_check_mark"), "quiet": ("default", "warning")}
DEMO_MARK = " (demo)"  # what the title of a message carries when the ring is made up


def alias(place) -> str | None:
    """The neutral name of the Spark at a place of the ring (its rank), from the closed table NEUTRAL; None for
    what is no place there: a text, a truth value, a number out of the table."""
    if isinstance(place, int) and not isinstance(place, bool) and 0 <= place < len(NEUTRAL):
        return NEUTRAL[place]
    return None


def named(state: dict, key: str, moment: dict) -> tuple:
    """The Sparks the message of a key is about, by their neutral names, as they are when it goes out: of every
    thing that is open in its trouble, its Spark (away, latch, fan) or both ends of its link. A name is picked
    from the table by the place of the Spark in the ring (alias), never taken from a name or a text of the
    moment; a thing that cannot be placed gives None. Nothing for a message without a gap."""
    trouble, _, word = key.partition(" ")
    if trouble not in NAMED or word != "on":
        return ()
    things = [thing for thing, mark in state["marks"][trouble].items() if mark["open"]]
    if trouble == "link":
        edges = moment.get("edges") if isinstance(moment.get("edges"), list) else []
        ends = {f"{e.get('from')}/{e.get('group')}": (e.get("from"), e.get("to")) for e in edges if isinstance(e, dict)}
        return tuple(alias(end) for thing in things for end in ends.get(thing, (None,)))
    cluster = moment.get("cluster") if isinstance(moment.get("cluster"), dict) else {}
    listed = cluster.get("nodes") if isinstance(cluster.get("nodes"), list) else []
    places = {n.get("name"): n.get("rank") for n in listed if isinstance(n, dict) and isinstance(n.get("name"), str)}
    return tuple(alias(places.get(thing)) for thing in things)


def gap_for(names) -> str:
    """What stands in the gap of a text: names of the table, each once, in the order of their places and joined
    by ", ", or MANY for more than MOST_NAMED, for none, and for anything that is no name of the table."""
    names = list(names) if isinstance(names, (list, tuple)) else [None]
    if not names or not all(name in NEUTRAL for name in names) or len(set(names)) > MOST_NAMED:
        return MANY
    return ", ".join(sorted(set(names), key=NEUTRAL.index))


def message(key: str, demo: bool = False, names=()) -> dict:
    """The message of a key as it goes out: title, body, how urgent, and its sign. The one place a message is
    made, and it is made of the key and of names of the table alone (gap_for, where its text has one): a key
    the table does not have is a KeyError, never a text."""
    text, (priority, tags), filled = TEXTS[key], LOOKS[key.split()[-1]], gap_for(names)
    return {
        "title": text["title"].replace(GAP_MARK, filled) + (DEMO_MARK if demo else ""),
        "body": text["body"].replace(GAP_MARK, filled),
        "priority": priority,
        "tags": tags,
    }
