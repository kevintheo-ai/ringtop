"""When a phone is told: how long a trouble has to last, one open message per trouble, the cap of a day, what a
restart keeps, and how a message is made of its key (the texts themselves: tests/test_alerts_texts.py). Every
clock here is made up."""

import json

from ringtop_parts.core import alerts
from ringtop_parts.core.alerts import (
    BAD,
    CAP,
    CAP_REOPENS,
    DAY,
    GOOD,
    TEXTS,
    TROUBLES,
    WAITS,
    begun,
    delivered,
    due,
    kept,
    message,
    step,
)

T0 = 1_800_000_000.0
# The waits are twice the ones most checks here count in seconds for. Those checks run at half the pace (HALF),
# so each wait is the one they count with again; the checks of the waits themselves run at full pace.
HALF = 0.5


def said(**troubles):
    """Readings as `readings` gives them, of the troubles named: {thing: BAD, GOOD or None} each."""
    return {trouble: troubles.get(trouble, {}) for trouble in TROUBLES}


def looks(start, end, reading, every=2.0):
    """One look every `every` seconds from `start` up to, not at, `end`, each with the same readings."""
    return [(T0 + start + i * every, reading) for i in range(int((end - start) / every))]


def play(state, moments, deliver=True, pace=HALF):
    """Steps through moments [(now, readings)] as the phone thread does: after each look at most one message
    goes out, and is taken as delivered. Gives the state and every (second since T0, key) that went out."""
    out = []
    for now, reading in moments:
        state = step(state, reading, now, pace)
        key = due(state)
        if key and deliver:
            state = delivered(state, key, now)
            out.append((now - T0, key))
    return state, out


def test_the_waits_tell_a_phone_later_and_stand_in_one_table():
    """The waits, chosen to tell a phone later rather than sooner, stand in one table and change only there."""
    assert WAITS == {
        "away": (240.0, 120.0),
        "latch": (120.0, 120.0),
        "fan": (120.0, 120.0),
        "link": (120.0, 120.0),
        "engine": (1200.0, 120.0),
    }
    before = WAITS["fan"]
    WAITS["fan"] = (10.0, 4.0)
    try:
        bad, good = said(fan={"dgx1": BAD}), said(fan={"dgx1": GOOD})
        _, out = play(begun(), looks(0, 30, bad) + looks(30, 60, good), pace=1.0)
        assert out == [(10.0, "fan on"), (34.0, "fan off")], out
    finally:
        WAITS["fan"] = before


def test_a_trouble_is_told_once_it_lasted_its_wait_and_its_end_once_that_lasted():
    for trouble, (on, off) in WAITS.items():
        bad, good = said(**{trouble: {"x": BAD}}), said(**{trouble: {"x": GOOD}})
        state, out = play(begun(), looks(0, on + 40, bad) + looks(on + 40, on + 200, good), pace=1.0)
        assert out == [(on, f"{trouble} on"), (on + 40 + off, f"{trouble} off")], (trouble, out)
        assert state["told"][trouble] is False and due(state) is None
        _, short = play(begun(), looks(0, on - 2, bad) + looks(on - 2, on + 300, good), pace=1.0)
        assert short == [], (trouble, short)  # over before its wait: nothing is said, and no end of nothing


def test_a_trouble_that_is_there_at_the_start_is_told_once_after_the_normal_wait():
    """Every Spark starts as "Connecting", which is not live: those seconds lie under the wait of `away`. A
    Spark that stays away from the start is told after the same two minutes as any other."""
    start = said(away=dict.fromkeys(("dgx0", "dgx1", "dgx2", "dgx3"), BAD))
    there = said(away={"dgx0": GOOD, "dgx1": GOOD, "dgx2": GOOD, "dgx3": BAD})
    _, out = play(begun(), looks(0, 8, start) + looks(8, 400, there))
    assert out == [(120.0, "away on")], out
    _, none = play(begun(), looks(0, 8, start) + looks(8, 400, said(away=dict.fromkeys(start["away"], GOOD))))
    assert none == []


def test_a_change_under_the_wait_starts_the_wait_anew_and_sends_nothing():
    bad, good = said(fan={"dgx1": BAD}), said(fan={"dgx1": GOOD})
    flutter = [
        moment for i in range(200) for moment in looks(i * 50, i * 50 + 48, bad) + looks(i * 50 + 48, i * 50 + 50, good)
    ]
    state, out = play(begun(), flutter)
    assert out == []  # 48 s bad, 2 s good, for nearly three hours: never a minute in a row
    state, out = play(state, looks(10_000, 10_100, bad))
    assert out == [(10_060.0, "fan on")], out  # the wait counts from the last change
    flutter = [
        moment
        for i in range(100)
        for moment in looks(10_100 + i * 50, 10_148 + i * 50, good) + looks(10_148 + i * 50, 10_150 + i * 50, bad)
    ]
    state, out = play(state, flutter)
    assert out == [] and state["told"]["fan"] is True  # and the end of it flutters the same way: not said


def test_what_nobody_knows_starts_no_message_and_ends_none():
    bad, good, unknown = said(latch={"dgx1": BAD}), said(latch={"dgx1": GOOD}), said(latch={"dgx1": None})
    state, out = play(begun(), looks(0, 40, bad) + looks(40, 42, unknown) + looks(42, 200, bad))
    assert out == [(102.0, "latch on")], out  # a minute in a row, and a look that read nothing breaks the row
    state, out = play(state, looks(200, 4000, unknown) + looks(4000, 4040, good) + looks(4040, 8000, unknown))
    assert out == [] and state["told"]["latch"] is True  # the load ended: an hour of that frees no clock
    state, out = play(state, looks(8000, 8100, said()))  # the Spark is not even named any more: as unknown
    assert out == [] and state["told"]["latch"] is True
    state, out = play(state, looks(8100, 8200, good))
    assert out == [(8160.0, "latch off")], out


def test_one_message_stands_for_a_trouble_however_many_things_have_it():
    """A second Spark with the same trouble is no second message, and the trouble is over when every thing that
    had it has been good for the wait."""
    moments = looks(0, 100, said(fan={"dgx1": BAD, "dgx2": GOOD}))
    moments += looks(100, 200, said(fan={"dgx1": BAD, "dgx2": BAD}))
    moments += looks(200, 300, said(fan={"dgx1": GOOD, "dgx2": BAD}))
    moments += looks(300, 400, said(fan={"dgx1": GOOD, "dgx2": GOOD}))
    _, out = play(begun(), moments)
    assert out == [(60.0, "fan on"), (360.0, "fan off")], out


def test_with_every_spark_away_one_message_goes_out():
    """All four at once: `away` is told, once. Of the other troubles nothing is known then, and they are silent,
    the ones that were open before included."""
    names = ("dgx0", "dgx1", "dgx2", "dgx3")
    there = {**said(away=dict.fromkeys(names, GOOD), fan={**dict.fromkeys(names, GOOD), "dgx1": BAD})}
    there["engine"], there["link"] = {"ring": GOOD}, {"0/f0": GOOD}
    gone = said(away=dict.fromkeys(names, BAD), latch=dict.fromkeys(names), fan=dict.fromkeys(names))
    gone["engine"], gone["link"] = {"ring": None}, {"0/f0": None}
    state, out = play(begun(), looks(0, 100, there) + looks(100, 3000, gone))
    assert out == [(60.0, "fan on"), (220.0, "away on")], out
    assert state["told"] == {"away": True, "latch": False, "fan": True, "link": False, "engine": False}


def test_after_a_gap_without_a_moment_every_wait_starts_anew():
    """The Mac slept, or the ticker hung: what was read before the gap does not count towards a wait. Neither
    does a clock that went back."""
    bad = said(link={"0/f0": BAD})
    assert alerts.GAP == 60.0
    _, out = play(begun(), looks(0, 50, bad) + looks(200, 300, bad))
    assert out == [(260.0, "link on")], out
    _, out = play(begun(), looks(0, 50, bad) + looks(110, 200, bad))  # 62 s between two looks: a gap
    assert out == [(170.0, "link on")], out
    _, out = play(begun(), looks(0, 50, bad) + looks(108, 200, bad))  # 60 s: none
    assert out == [(60.0 + 48, "link on")], out
    _, out = play(begun(), looks(1000, 1050, bad) + looks(0, 100, bad))  # the clock was set back
    assert out == [(60.0, "link on")], out
    state, _ = play(begun(), looks(0, 100, bad))
    state, out = play(state, looks(5000, 5100, said(link={"0/f0": GOOD})))
    assert out == [(5060.0, "link off")], out  # what the phone was told stands across the gap


def test_a_restart_tells_nothing_twice_and_nothing_sooner():
    """What a start keeps for the next is what the phone was told, and when messages went out: plain JSON without
    a name in it. Twenty restarts while a fan stands: no second message. The waits start anew with every start."""
    bad = said(fan={"dgx1": BAD, "dgx2": GOOD})
    state, out = play(begun(), looks(0, 100, bad))
    assert out == [(60.0, "fan on")]
    for restart in range(1, 21):
        saved = json.dumps(kept(state))
        assert json.loads(saved) == {"told": ["fan"], "sent": [T0 + 60.0], "hushed": False}, saved
        state, out = play(begun(json.loads(saved)), looks(restart * 1000, restart * 1000 + 300, bad))
        assert out == [] and state["told"]["fan"] is True, (restart, out)
    # the end is told when every thing has been good for the wait after the start: nobody kept which one it was
    fresh = begun(json.loads(json.dumps(kept(state))))
    half = said(fan={"dgx1": GOOD, "dgx2": None})
    state, out = play(fresh, looks(30_000, 30_400, half))
    assert out == [] and state["told"]["fan"] is True  # one of them nobody can read: silence is no all-clear
    state, out = play(state, looks(30_400, 30_500, said(fan={"dgx1": GOOD, "dgx2": GOOD})))
    assert out == [(30_460.0, "fan off")], out
    # a trouble that was open and not told yet when the start came waits its whole wait again
    state, _ = play(begun(), looks(0, 100, bad), deliver=False)
    assert due(state) == "fan on" and kept(state) == {"told": [], "sent": [], "hushed": False}
    _, out = play(begun(kept(state)), looks(100, 200, bad))
    assert out == [(160.0, "fan on")], out


def test_what_was_kept_and_cannot_be_read_starts_from_nothing():
    """A file that is missing or broken: start as if nothing had ever been told. At most one message per
    trouble comes twice that way."""
    empty = begun()
    assert kept(empty) == {"told": [], "sent": [], "hushed": False}
    for broken in (None, "x", 7, [], {"told": 7, "sent": "no", "hushed": "yes"}, {"told": {"fan": True}}):
        assert begun(broken) == empty, broken
    odd = {"told": ["fan", "nonsense", ["fan"], 3, "fan"], "sent": [T0, "a", None, True, float("nan"), T0 - 5]}
    assert kept(begun(odd)) == {"told": ["fan"], "sent": [T0 - 5, T0], "hushed": False}
    many = begun({"sent": [T0 + i for i in range(500)], "hushed": True})
    assert kept(many) == {"told": [], "sent": [T0 + i for i in range(500 - CAP, 500)], "hushed": True}
    # the things of a trouble the start before told of are not known: every one has to be good first
    assert begun({"told": ["away"]})["held"] == {"away"} and begun()["held"] == set()


def test_no_more_than_twelve_messages_go_out_in_a_day_whatever_happens():
    """A fan that stands and turns again every 200 s, for three days: 1 296 changes, each worth a message. Eleven
    go out, the twelfth says that Ringtop is silent now, and then nothing until only six lie in the last day."""
    bad, good = said(fan={"dgx1": BAD}), said(fan={"dgx1": GOOD})
    moments = [
        moment for i in range(1296) for moment in looks(i * 200, i * 200 + 200, bad if i % 2 == 0 else good, every=10.0)
    ]
    _, out = play(begun(), moments)
    times, keys = [t for t, _ in out], [key for _, key in out]
    assert (CAP, CAP_REOPENS, DAY) == (12, 6, 86400.0) and set(keys) <= set(TEXTS)
    for t in times:
        assert sum(1 for other in times if t - DAY < other <= t) <= CAP, t
    assert keys[:CAP] == ["fan on", "fan off"] * 5 + ["fan on", "quiet"], keys[:CAP]
    assert times[CAP - 1] == 2260.0 and times[CAP] >= times[5] + DAY, times[:14]  # silent until six are a day old
    assert keys.count("quiet") == 3 and len(keys) > 2 * CAP, keys
    for at in (i for i, key in enumerate(keys) if key == "quiet"):
        assert sum(1 for t in times if times[at] - DAY < t <= times[at]) == CAP, at
        after = times[at + 1] if at + 1 < len(times) else None
        if after is not None:
            assert sum(1 for t in times[: at + 1] if after - DAY < t <= after) <= CAP_REOPENS, at
    # after the silence the first word is the state as it is then, not the change that was held back
    state = begun({"told": ["fan"], "sent": [T0 + i for i in range(CAP)], "hushed": True})
    state, out = play(state, looks(100, 300, good))
    assert out == [] and due(state) is None and state["hushed"] is True
    state, out = play(state, looks(DAY + 6, DAY + 200, good))
    assert out[0][1] == "fan off" and state["hushed"] is False, out


def test_the_word_of_the_cap_is_one_of_the_twelve_whatever_the_rhythm():
    """Troubles of every length, from a minute to two hours, for a fortnight: in no day do more than twelve
    messages go out, the word of the cap among them, and every word of the cap is the twelfth of its day. A
    rhythm that falls on the edge of the day (the check above) would hide a word of the cap that is not counted."""
    bad, good = said(fan={"dgx1": BAD}), said(fan={"dgx1": GOOD})
    lengths = [61, 65, 70, 95, 130, 200, 400, 1300, 3600, 7000, 75, 610]
    moments, start, i = [], 0, 0
    while start < 14 * DAY:
        length = lengths[(i * 7) % len(lengths)]
        moments += looks(start, start + length, bad if i % 2 == 0 else good, every=5.0)
        start, i = start + length, i + 1
    _, out = play(begun(), moments)
    times = [t for t, _ in out]
    in_day = [sum(1 for other in times if t - DAY < other <= t) for t in times]
    assert max(in_day) == CAP and [key for _, key in out].count("quiet") >= 10, (max(in_day), len(out))
    assert all((key == "quiet") == (count == CAP) for (_, key), count in zip(out, in_day)), out


def test_what_did_not_go_out_and_is_no_longer_so_is_dropped():
    """Six hours without a network, troubles coming and going: nothing queues. When the phone can be reached
    again it gets at most one message per trouble, each one the state of that moment."""
    names = ("dgx0", "dgx1", "dgx2", "dgx3")
    state = begun()
    for hour in range(6):
        base = hour * 3600
        came = said(away={"dgx3": BAD}, fan={"dgx1": BAD}, link={"0/f0": BAD}, engine={"ring": BAD})
        went = said(away={"dgx3": GOOD}, fan={"dgx1": GOOD}, link={"0/f0": GOOD}, engine={"ring": GOOD})
        state, out = play(state, looks(base, base + 1800, came) + looks(base + 1800, base + 3600, went), deliver=False)
        assert out == []
    assert due(state) is None  # each came and went: neither is news any more
    now = said(away=dict.fromkeys(names, BAD), fan={"dgx1": BAD}, link={"0/f0": BAD}, engine={"ring": None})
    state, _ = play(state, looks(21_600, 22_000, now), deliver=False)
    state, out = play(state, looks(22_000, 22_100, now))
    assert [key for _, key in out] == ["away on", "fan on", "link on"], out
    assert [t for t, _ in out] == [22_000.0, 22_002.0, 22_004.0]  # one message per look
    assert len(out) <= len(TROUBLES) and due(state) is None


def test_a_message_that_may_have_gone_out_counts_and_goes_once_more_at_most():
    """A try that reached the server without its answer may have reached the phone: it counts towards the cap,
    the phone counts as told, and the message goes once more while it is still so. That second one is the last
    of it, however it ends: no more than two copies of one message reach a phone."""
    bad = said(fan={"dgx1": BAD})
    state, _ = play(begun(), looks(0, 70, bad), deliver=False)
    assert due(state) == "fan on" and state["again"] is None
    state = delivered(state, "fan on", T0 + 70, sure=False)
    assert state["told"]["fan"] is True and state["sent"] == [T0 + 70] and state["again"] == "fan on"
    state = step(state, bad, T0 + 72, HALF)
    assert due(state) == "fan on"  # once more, and it stays due while that fails without reaching anyone
    once = delivered(state, "fan on", T0 + 102, sure=False)
    assert once["sent"] == [T0 + 70, T0 + 102] and once["again"] is None
    assert due(step(once, bad, T0 + 104, HALF)) is None
    sure = delivered(state, "fan on", T0 + 102)
    assert sure["again"] is None and due(step(sure, bad, T0 + 104, HALF)) is None
    # it is over before the second copy got out: the end is told instead, and that is the end of the copy too
    state, _ = play(state, looks(72, 140, said(fan={"dgx1": GOOD})), deliver=False)
    assert due(state) == "fan off"
    state = delivered(state, "fan off", T0 + 140)
    assert state["again"] is None and due(step(state, said(fan={"dgx1": GOOD}), T0 + 142, HALF)) is None


def test_the_second_copy_leaves_the_last_place_of_the_day_to_the_word_of_the_cap():
    """The twelfth message of a day is the word of the cap, whatever else is due. A second copy that would take
    that place is not sent, and the word of the cap is never sent twice."""
    bad = said(fan={"dgx1": BAD})
    full = begun({"sent": [T0 - 1000 + i for i in range(CAP - 2)]})
    state, _ = play(full, looks(0, 70, bad), deliver=False)
    state = delivered(state, "fan on", T0 + 70, sure=False)
    assert len(state["sent"]) == CAP - 1 and state["again"] is None and due(state) is None
    state, _ = play(state, looks(72, 200, said(fan={"dgx1": GOOD})), deliver=False)
    assert due(state) == "quiet"
    state = delivered(state, "quiet", T0 + 200, sure=False)
    assert state["hushed"] is True and state["again"] is None and len(state["sent"]) == CAP


def test_twelve_a_day_hold_when_no_try_is_ever_sure():
    """Every try reaches the server and no answer comes back: each message goes twice, both count, and still no
    more than twelve leave in a day, the last of them the word of the cap."""
    bad, good = said(fan={"dgx1": BAD}), said(fan={"dgx1": GOOD})
    durations = [65, 70, 130, 200, 400, 3600, 61, 95]
    moments, start = [], 0
    for i in range(600):
        moments += looks(start, start + durations[i % len(durations)], bad if i % 2 == 0 else good, every=5.0)
        start += durations[i % len(durations)]
    state, times, keys = begun(), [], []
    for now, reading in moments:
        state = step(state, reading, now, HALF)
        key = due(state)
        if key:
            state = delivered(state, key, now, sure=False)
            times.append(now)
            keys.append(key)
    assert max(sum(1 for t in times if at - DAY < t <= at) for at in times) == CAP
    for at, key in zip(times, keys):
        assert (key == "quiet") == (sum(1 for t in times if at - DAY < t <= at) == CAP), (at - T0, key)
    assert keys[:3] == ["fan on", "fan on", "fan off"] and "quiet" in keys
    assert all(keys[i : i + 3] != [keys[i]] * 3 for i in range(len(keys) - 2))  # never a third copy


def test_a_clock_set_back_opens_the_cap_no_sooner():
    """Twelve messages, then the clock goes back: their times lie ahead of it now. They count as sent just now,
    so the cap stays shut until a day of the clock has passed from there, and a clock set back by a year shuts it
    for a day, not for a year."""
    bad, good = said(fan={"dgx1": BAD}), said(fan={"dgx1": GOOD})

    def flutter(start, count):
        """A fan that stands and turns again every 70 s, `count` times, from second `start`."""
        return [
            m for i in range(count) for m in looks(start + 70 * i, start + 70 * i + 70, bad if i % 2 == 0 else good)
        ]

    state, out = play(begun(), flutter(0, 30))
    assert len(out) == CAP and out[-1][1] == "quiet" and state["hushed"] is True
    for back in (7200.0, 3600.0 * 24 * 365):
        later, after = play(state, flutter(2100 - back, 40))
        assert after == [], (back, after)  # 46 min after the jump: still shut
        assert all(now - T0 <= 2100 - back for now in later["sent"]), back  # counted as sent at the jump
        _, opened = play(later, flutter(2100 - back + DAY - 2000, 60))
        assert opened and opened[0][0] >= 2100 - back + DAY, (back, opened[:2])  # a day of the clock later


def test_the_fault_round_of_the_demo_waits_a_twentieth():
    """At the pace of the fault round the doubled waits come out as the waits of the round before them: the
    engine is told after a minute, its end after six seconds."""
    bad, good = said(engine={"ring": BAD}), said(engine={"ring": GOOD})
    _, out = play(begun(), looks(0, 100, bad) + looks(100, 200, good), pace=0.05)
    assert out == [(60.0, "engine on"), (106.0, "engine off")], out


def test_a_message_is_a_key_of_the_table_with_the_look_of_its_kind():
    """Title, body, how urgent and which sign: all four from the key alone (and the names of the gap, with none
    given its fixed word: tests/test_notify_names.py). The demo marks its titles."""
    fan_on = {**TEXTS["fan on"], "body": TEXTS["fan on"]["body"].replace(alerts.GAP_MARK, alerts.MANY)}
    assert message("fan on") == {**fan_on, "priority": "high", "tags": "warning"}
    assert message("fan off") == {**TEXTS["fan off"], "priority": "default", "tags": "white_check_mark"}
    assert message("quiet") == {**TEXTS["quiet"], "priority": "default", "tags": "warning"}
    for key in TEXTS:
        real, demo = message(key), message(key, demo=True)
        assert demo == {**real, "title": real["title"] + " (demo)"}, key
        assert all(isinstance(part, str) and part.isascii() and part for part in demo.values()), key
    for no_key in ("fan", "fan on\r\nTitle: x", "", "dgx1 on", None):
        try:
            message(no_key)
        except KeyError:
            continue
        raise AssertionError(f"a message was made of {no_key!r}")
