"""The rules of the page, run through node: what the page may claim, now and looking back."""

import json

from tests.fixtures import LOOK_BACK, TRACKS, hub_for, needs_node, page_rules, ring_map


@needs_node
def test_the_time_machine_shows_the_last_sample_before_the_moment_never_a_later_one():
    """A sample after the cursor would show a run's speed before the run's own start event."""
    got = page_rules(
        "return [sampleAt([100,110,120],109,25), sampleAt([100,110,120],110,25), sampleAt([100,110,120],99,25),"
        " sampleAt([100,110,120],145,25), sampleAt([100,110,120],146,25), sampleAt([],5,25), sampleAt(null,5,25)];"
    )
    assert got == [0, 1, -1, 2, -1, -1, -1], got


@needs_node
def test_a_hole_in_the_recording_stays_a_hole_in_the_time_machine():
    """Full samples lie one interval apart: a minute without any is a hole, not the value of a neighbour."""
    got = page_rules(
        "return [reachOf(1800,'raw',2), reachOf(1800,'memory',2), reachOf(7200,'raw',2), reachOf(21600,'minute',2),"
        " reachOf(1800,'mixed',2), reachOf(2592000,'minute',2)];"
    )
    assert got == [6.25, 6.25, 25, 150, 150, 9000], got


@needs_node
def test_looking_back_takes_every_value_from_the_recording():
    """The page shows one recorded sample: its values, its time, and the run and the events as they stood at that time."""
    got, later = page_rules(LOOK_BACK + "return [momentOf(live, got, 103.5, 6.25), momentOf(live, got, 104.2, 6.25)];")
    assert got["past"] and got["t"] == 102  # the time of the sample shown, not of the cursor
    assert got["engine"]["tok_s"] == 51 and got["engine"]["state"] == "writing"  # the sample of 102, not the one of 104
    assert got["run"]["source"] == "none" and got["events"] == []  # the run started at 103: this sample is from before
    a, b = got["nodes"]
    assert a["live"] and a["w"] == 10, a  # one missed sample of a Spark is bridged by its last one within reach
    assert not b["live"] and "nothing was recorded" in b["reason"]
    assert a["mem_total_gb"] == 128  # the size of the machine is no reading
    assert later["t"] == 104 and later["engine"]["tok_s"] == 52
    assert later["run"]["name"] == "bench" and later["run"]["started"] == 103  # the run arrives with its first sample
    assert [e["text"] for e in later["events"]] == ["Started: bench"]


@needs_node
def test_one_sample_looks_the_same_wherever_the_cursor_stands_on_it():
    """The page draws a sample once and skips the redraw while the cursor stays on it: nothing may depend on where."""
    got = page_rules(
        "const live = { cluster: { nodes: [{ name: 'a', rank: 0, head: true }] }, identity: { interval: 10 }, nodes: [{ name: 'a' }], edges: [] };"
        "const rec = { t: [0, 20, 40], from: 0, to: 60, series: { 'engine.tok_s': [5, 6, 7], 'a.w': [9, null, 11], 'a.fan': [null, 2000, null] },"
        " events: [{ t: 21, kind: 'run', text: 'Started: x', level: 'info' }, { t: 39, kind: 'node', text: 'late', level: 'warn' }] };"
        "const same = (r, t) => JSON.stringify(momentOf(live, rec, 20, r)) === JSON.stringify(momentOf(live, rec, t, r));"
        "return [same(25, 39.9), same(15, 30), momentOf(live, rec, 39.9, 25).nodes[0].w, momentOf(live, rec, 30, 15).nodes[0].w,"
        " momentOf(live, rec, 39.9, 25).events.length, momentOf(live, rec, 39.9, 25).t];"
    )
    assert got == [True, True, 9, None, 0, 20], got


@needs_node
def test_no_engine_values_only_mean_not_serving_when_the_head_was_read():
    """The engine is read through the head. A moment with readings of other Sparks but none of the head knows nothing
    about the engine: that is not "not serving"."""
    got = page_rules(
        LOOK_BACK
        + "const quiet = { ...got, series: { 'a.w': [10, 11, 12, 20] } }, blind = { ...got, series: { 'b.w': [10, 11, 12, 20] } };"
        + "const pick = m => [m.engine.state, m.engine.word || null, m.engine.error, m.why.headline];"
        + "return [pick(momentOf(live, quiet, 110, 6.25)), pick(momentOf(live, blind, 110, 6.25)), pick(momentOf(live, got, 115, 2))];"
    )
    asked, blind, nothing = got
    assert asked[:2] == ["offline", None] and "did not answer" in asked[2] and "did not answer" in asked[3], asked
    assert blind[:2] == ["offline", "No record"] and "head" in blind[2] and "serving" not in blind[3], blind
    assert nothing[:2] == ["offline", "No record"] and "nothing was recorded" in nothing[2], nothing


@needs_node
def test_a_link_nobody_read_right_now_is_not_read_and_looking_back_not_recorded():
    """The cards of the network chip and of the ports say in a word how the links of a Spark are. Where the state
    or the errors of a link are unknown they said "not recorded", the word of the look back, at a moment that is
    now: for a Spark that is away, and for a port whose files its sampler could not read. Right now that is "not
    read"; "not recorded" is said of the past. The page has both words for this (readWord, the counters of a card)."""
    got = page_rules(
        "const unknown = { up: null, errors: null }, fine = { up: true, errors: false };"
        "return [linksUpWord([unknown, fine]), linksUpWord([unknown, fine], true), linkErrorsWord([unknown, fine]),"
        " linkErrorsWord([unknown, fine], true), linksUpWord([fine]), linkErrorsWord([fine]), linksUpWord([])];"
    )
    assert got[:2] == ["link state not read", "link state not recorded"], got  # live it said "not recorded" too
    assert got[2:4] == ["errors not read", "errors not recorded"], got
    assert got[4:] == ["1 of 1 links up", "no errors", "–"], got  # what was read is said as ever


@needs_node
def test_errors_that_were_read_on_one_link_are_said_whatever_another_link_could_say():
    """The card of the network chip says of the links of a Spark whether they had errors, and how many of them
    had. With one link that was not read it said "errors not read" of all of them and a dash for their number,
    also where another link was read to have errors: errors that were seen, and no word of them. Errors that were
    read are said and counted, whatever another link could say. "No errors" is said where every link was read and
    none has any; that nobody knows is said where no link that was read has errors and one was not read."""
    got = page_rules(
        "const unknown = { up: null, errors: null }, bad = { up: true, errors: true }, fine = { up: true, errors: false };"
        "const said = links => [linkErrors(links), linkErrorsWord(links), linkErrorsWord(links, true)];"
        "return [said([unknown, bad]), said([bad, unknown, bad, fine]), said([unknown, fine]), said([fine, fine]),"
        " said([fine, bad]), said([unknown]), said([])];"
    )
    assert got[0] == [1, "errors", "errors"], got  # was [None, "errors not read", "errors not recorded"]
    assert got[1] == [2, "errors", "errors"], got  # was the same three: two links with errors, and no word of them
    assert got[2] == [None, "errors not read", "errors not recorded"], got  # none seen and one not read: nobody knows
    assert got[3] == [0, "no errors", "no errors"], got  # every link was read, and none has errors
    assert got[4] == [1, "errors", "errors"] and got[5] == got[2], got
    assert got[6] == [0, "no errors", "no errors"], got  # a Spark without links, as before


@needs_node
def test_looking_back_never_borrows_the_state_of_today():
    """What was not recorded stays unknown: the state and the speed of a link, throttle reasons, a power limit, the
    engine of today and its memory guard. Only what a Spark is built with (memory, disk, top clock) is taken from today."""
    got = page_rules(LOOK_BACK + "return momentOf(live, got, 110, 6.25);")
    edge = got["edges"][0]
    assert edge["gbps"] == 4 and edge["rx"] == 8
    assert edge["up"] is None and edge["errors"] is None, edge  # today's link is down with errors: then it is unknown
    assert edge["capacity"] is None, edge  # a link that runs at 200 today may have run at 100 then
    assert [n["throttle"] for n in got["nodes"]] == [None, None]
    assert [n.get("w_limit") for n in got["nodes"]] == [None, None] and got["nodes"][0]["mem_total_gb"] == 128
    assert got["identity"] == {"interval": 2}, got["identity"]
    words = page_rules(
        "const unknown = { up: null, errors: null }, bad = { up: false, errors: true }, fine = { up: true, errors: false };"
        "return [linkNote(unknown, ', '), linkNote(bad, ', '), linkNote(fine, ', '),"
        " linksUpWord([unknown, unknown], true), linksUpWord([fine, bad], true), linksUpWord([], true),"
        " linkErrorsWord([unknown], true), linkErrorsWord([fine, bad], true), linkErrorsWord([fine], true), linkErrorsWord([], true),"
        " throttleWord({ throttle: null }), throttleWord({ throttle: [] }), throttleWord({ throttle: ['thermal'] })];"
    )
    rates = page_rules(
        "return [linkRate({ gbps: 35.7, capacity: 200 }), linkRate({ gbps: 35.7, capacity: null }), linkRate({ gbps: null, capacity: null }),"
        " asRecorded(null, '95th percentile'), asRecorded(3.2, '95th percentile')];"
    )
    assert rates == ["35.7 of 200 Gb/s", "35.7 Gb/s", "– Gb/s", "not recorded", "95th percentile, as recorded"], rates
    assert words == [
        "",
        ", down, errors",
        "",
        "link state not recorded",
        "1 of 2 links up",
        "–",
        "errors not recorded",
        "errors",
        "no errors",
        "no errors",
        "No reading of the throttle reasons.",
        "Not throttling.",
        "Slowing down: thermal.",
    ], words


@needs_node
def test_a_link_counts_each_direction_once_from_whichever_end_was_read():
    """Both ends count what they send and what they receive. With one end silent the other still knows both directions:
    half the traffic must not stand there as the whole."""
    got = page_rules(
        "const ab = (gbps, rx) => ({ from: 0, to: 1, gbps, rx }), ba = (gbps, rx) => ({ from: 1, to: 0, gbps, rx });"
        "return [linkWays([ab(10, 4), ba(5, 9)], 0, 1), linkWays([ab(10, 4), ba(null, null)], 0, 1), linkWays([ab(null, null), ba(5, 9)], 0, 1),"
        " linkWays([ab(10, 4)], 0, 1), linkWays([ba(5, 9)], 0, 1), linkWays([ab(null, null), ba(null, null)], 0, 1), linkWays([], 0, 1),"
        " linkWays([ab(10, 4), ab(20, 6), ba(5, 9), ba(7, 11)], 0, 1), linkWays([ab(10, 4), ab(20, 6), ba(null, null), ba(null, null)], 0, 1)];"
    )
    assert got[:7] == [[10, 5], [10, 4], [9, 5], [10, 4], [9, 5], [None, None], [None, None]], got
    assert got[7:] == [[30, 12], [30, 10]], got  # two Sparks share two cables: both count, in each direction


@needs_node
def test_two_cables_between_two_sparks_count_from_the_end_that_read_them_all():
    """Two Sparks alone share two cables. Where one end read one of them and the other end read both, the cable the
    sender did not read fell out: the label said "120 Gb/s · 30 %" for 120 + 60 Gb/s, and the card of the engine 160
    for 220, called the whole. A direction counts as its sender counts it where the sender read every cable, else as
    the other end receives it where that end did; where neither end read all of them it is unknown. An end that sees
    fewer cables than the other one is not the whole either."""
    got = page_rules(
        "const e = (from, to, gbps, rx, group = 'f0') => ({ from, to, gbps, rx, group, capacity: 200, up: true, errors: false });"
        "const pair = [e(0, 1, 120, 20), e(0, 1, null, null, 'f1'), e(1, 0, 20, 120), e(1, 0, 20, 60, 'f1')];"
        "return [linkWays(pair, 0, 1), chipWord(pair, 0, 1), ringTraffic([{ rank: 0, live: true }, { rank: 1, live: true }], pair),"
        " linkWays([e(0, 1, 120, 20), e(0, 1, null, null, 'f1'), e(1, 0, 20, null), e(1, 0, 20, 60, 'f1')], 0, 1),"
        " linkWays([e(0, 1, 10, 4), e(0, 1, 20, 6, 'f1'), e(1, 0, 5, 9)], 0, 1)];"
    )
    assert got[0] == [180, 40], got[0]  # was [120, 40]: the second cable, read at the far end, fell out
    assert got[1] == "180 Gb/s · 45 %", got[1]  # was "120 Gb/s · 30 %"
    assert got[2] == {"sum": 220, "read": 2, "of": 2}, got[2]  # was 160
    assert got[3] == [None, 40], got[3]  # one cable read at each end, not the same one: unknown, not 120
    assert got[4] == [30, 10], got[4]  # the far end sees one of two cables: what it sends is known where it arrives


@needs_node
def test_the_label_of_a_cable_says_the_fuller_direction_against_the_rate_of_one_direction():
    """The label of a cable in the scene added both directions up and set beside it how full the fuller one is: a
    cable with 150 Gb/s one way and 20 back stood as "170 Gb/s · 75 %", one with 150 each way as "300 Gb/s · 75 %",
    beside a rate of 200 Gb/s per port. The figure is the fuller direction, the share is that direction against the
    rate of one direction; two Sparks alone share two cables, and a direction then carries what both carry."""
    got = page_rules(
        "const e = (from, to, gbps, rx, more = {}) => ({ from, to, gbps, rx, capacity: 200, up: true, errors: false, ...more });"
        "return [chipWord([e(0, 1, 150, 20), e(1, 0, 20, 150)], 0, 1), chipWord([e(0, 1, 150, 20), e(1, 0, null, null)], 0, 1),"
        " chipWord([e(0, 1, 30, null), e(1, 0, null, null)], 0, 1), chipWord([e(0, 1, null, null), e(1, 0, null, null)], 0, 1),"
        " chipWord([e(0, 1, 120, 20), e(0, 1, 60, 20), e(1, 0, 20, 120), e(1, 0, 20, 60)], 0, 1),"
        " chipWord([e(0, 1, 150, 20, { capacity: null }), e(1, 0, 20, 150, { capacity: null })], 0, 1),"
        " chipWord([e(0, 1, 150, 20, { errors: true }), e(1, 0, 20, 150)], 0, 1), chipWord([e(0, 1, 4.8, 1), e(1, 0, 1, 4.8)], 0, 1),"
        " chipWord([e(0, 1, 150, 20), e(1, 0, 20, 150), e(1, 2, 190, 190, { errors: true }), e(2, 1, 190, 190)], 0, 1)];"
    )
    assert got[0] == "150 Gb/s · 75 %", got[0]  # was "170 Gb/s · 75 %"
    assert got[1] == "150 Gb/s · 75 %", got[1]  # one end silent: the other one knows both directions
    assert got[2] == "30.0 Gb/s · 15 %", got[2]  # one direction read: that one, never "no reading"
    assert got[3] == "no reading", got[3]
    assert got[4] == "180 Gb/s · 45 %", got[4]  # two cables: 120 + 60 against 2 x 200; was "220 Gb/s · 45 %"
    assert got[5] == "150 Gb/s", got[5]  # looking back the rate is not kept: no share; was "170 Gb/s"
    assert got[6] == "150 Gb/s · 75 % · errors", got[6]
    assert got[7] == "4.8 Gb/s · 2 %", got[7]  # was "5.8 Gb/s · 2 %"
    assert got[8] == got[0], got[8]  # the cables of other Sparks are no part of this label


@needs_node
def test_the_busiest_port_of_a_spark_is_its_fuller_direction_never_a_sum():
    """The card of the ports of a Spark set "Gb/s now" beside "200 Gb/s per port": every port in both directions
    added up, so a Spark with two cables at 150 each way stood at 600 beside a rate of 200. Beside the rate of a port
    stands a figure of the same kind: the fuller direction of its busiest port. A direction nobody read counts for
    nothing, and with none read there is no figure."""
    got = page_rules(
        "const e = (gbps, rx) => ({ gbps, rx });"
        "return [busiestPort([e(150, 20), e(30, 190)]), busiestPort([e(null, null), e(30, null)]), busiestPort([e(null, null)]),"
        " busiestPort([]), busiestPort(null)];"
    )
    assert got == [190, 30, None, None, None], got


@needs_node
def test_the_traffic_of_the_ring_counts_every_direction_of_every_cable_once():
    """The card of the engine added up what every Spark sent and received: each transfer counted twice, once at its
    sender and once at its receiver (the demo showed four cables at 284.4 Gb/s together and the card at 568.7). It
    counts each direction of each cable once, as its sender counts it or else as the far end receives it. A Spark
    is in the sum where every direction it sends is known; one that is away is still known through its neighbours,
    but a direction neither end read leaves its sender out, and the note says how many Sparks the sum covers."""
    got = page_rules(
        "const live = r => ({ rank: r, live: true }), away = r => ({ rank: r, live: false }), nodes = [0, 1, 2, 3].map(live);"
        "const e = (from, to, gbps, rx) => ({ from, to, gbps, rx });"
        "const ring = (k = {}) => [e(0, 1, 10, 20), e(0, 3, 80, 70), e(1, 2, 30, 40), e(1, 0, 20, 10), e(2, 3, 50, 60), e(2, 1, 40, 30),"
        " e(3, 0, 70, 80), e(3, 2, 60, 50)].map(x => k[x.from] ? { ...x, ...k[x.from](x) } : x);"
        "const none = () => ({ gbps: null, rx: null });"
        "return [ringTraffic(nodes, ring()), ringTraffic([live(0), live(1), away(2), live(3)], ring({ 2: none })),"
        " ringTraffic([live(0), live(1), away(2), away(3)], ring({ 2: none, 3: none })),"
        " ringTraffic(nodes, ring({ 1: x => x.to === 0 ? none() : {}, 0: x => x.to === 1 ? { rx: null } : {} })),"
        " ringTraffic(nodes, [0, 1, 2, 3].flatMap(r => [e(r, null, 10 + r, 5), e(r, null, 20, 5)])),"
        " ringTraffic(nodes, [0, 1, 2, 3].flatMap(r => [e(r, null, r === 2 ? null : 10 + r, 5), e(r, null, 20, 5)])),"
        " ringTraffic([live(0), live(1)], [e(0, 1, 10, 30), e(0, 1, 20, 40), e(1, 0, 30, 10), e(1, 0, 40, 20)]),"
        " ringTraffic([{ ...live(0), net: 0 }], []), ringTraffic([live(0)], []), ringTraffic([away(0)], []),"
        " ringTraffic(nodes, ring().filter(x => !(x.from === 1 && x.to === 0)))];"
    )
    assert got[0] == {"sum": 360, "read": 4, "of": 4}, got[0]  # was 720: every Spark's sent plus received
    assert got[1] == {"sum": 360, "read": 4, "of": 4}, got[1]  # Spark 2 away: what it sends, its neighbours received
    assert got[2] == {"sum": 140, "read": 2, "of": 4}, got[2]  # 2 and 3 away: the cable between them nobody read
    assert got[3] == {"sum": 310, "read": 3, "of": 4}, got[3]  # one cable read one way only: its other way left out
    assert got[4] == {"sum": 126, "read": 4, "of": 4}, got[4]  # on a switch: what each Spark sends
    assert got[5] == {"sum": 94, "read": 3, "of": 4}, got[5]  # on a switch nobody else knows what a port sends
    assert got[6] == {"sum": 100, "read": 2, "of": 2}, got[6]  # two Sparks alone: both cables, each way once
    assert got[7] == {"sum": 0, "read": 1, "of": 1}, got[7]  # one Spark alone, its ports read: nothing on a ring
    assert got[8] == got[9] == {"sum": 0, "read": 0, "of": 1}, got[8:10]  # its ports not read, or away: not 0
    assert got[10] == {"sum": 360, "read": 4, "of": 4}, got[10]  # a port of Spark 1 never read: Spark 0 received it


def unread_ports(node_map, unread, fabric):
    """What the page gets of a hub of four Sparks that answer every sample, each port at 10 Gb/s each way, while the
    Sparks in `unread` send `fabric` in place of their ports from the first sample on (None as a reader that failed
    sends, {} where there is no RDMA device): its Sparks and its edges as JSON."""
    hub, dev = hub_for(node_map), ("rocep1s0f0", "roceP2p1s0f0", "rocep1s0f1", "roceP2p1s0f1")
    count = 5e9 / 8 / 4  # counts of 4 bytes per second for 5 Gb/s on each of the two functions of a port
    for k in range(6):
        ports = {
            d: {"tx": int(count * 2 * k), "rx": int(count * 2 * k), "up": True, "rate": 200.0, "err": 0} for d in dev
        }
        for n in hub.cluster["nodes"]:
            sample = {"fabric": fabric if n["rank"] in unread else ports, "gpu": {}, "mem": {}}
            hub.ingest(n["name"], {"t": 1_800_000_000.0 + 2 * k, **sample})
    nodes = [{"rank": n["rank"], "live": n["live"], "net": n.get("net")} for n in hub.nodes.values()]
    return json.dumps(nodes), json.dumps(hub.edges_view())


@needs_node
def test_a_spark_whose_ports_nobody_read_is_no_spark_that_sends_nothing():
    """A Spark answered, but its sampler could not read its ports (a reader that failed, or no RDMA device): it has
    no edge of its own. The card of the engine counted it as read with 0: "0.0 Gb/s, all Sparks" where no Spark read
    its ports, and on a ring of four with one such Spark 60 of 80, called the whole. Its directions on a ring are
    known at the far end, as what its neighbours receive; on a switch nobody knows them, and with no edge at all it is
    not read. Not read is unknown, never 0."""
    switch = {
        "nodes": [
            {"name": f"dgx{i}", "rank": i, "head": i == 0, "roce_hcas": ["rocep1s0f0", "roceP2p1s0f0"]}
            for i in range(4)
        ]
    }
    cases = [
        (ring_map(), (), None),
        (ring_map(), (2,), None),
        (ring_map(), (2,), {}),
        (switch, (), None),
        (switch, (2,), None),
        (ring_map(), (0, 1, 2, 3), None),
        (ring_map(), (0, 1, 2, 3), {}),
    ]
    calls = ", ".join(
        f"((N, E) => [ringTraffic(N, E).sum, readWord(ringTraffic(N, E), false)])({n}, {e})"
        for n, e in (unread_ports(*c) for c in cases)
    )
    got = page_rules(f"return [{calls}];")
    assert got[0] == [80, "all Sparks"], got[0]  # every port read: eight directions of 10 Gb/s
    assert got[1] == got[2] == [80, "all Sparks"], got[1:3]  # Spark 2 unread: its neighbours received; was 60
    assert got[3] == [80, "all Sparks"], got[3]  # on a switch: four Sparks, two ports each
    assert got[4] == [60, "3 of 4 read"], got[4]  # on a switch nobody else knows what it sends; was "all Sparks"
    assert got[5] == got[6] == [0, "0 of 4 read"], got[5:]  # no Spark read its ports: was "0.0 Gb/s, all Sparks"


@needs_node
def test_traffic_nobody_read_is_a_dash_in_the_list_of_links_and_no_part_of_a_sum_called_whole():
    """A cable whose traffic was not read stood in the list of ring links of nerd mode as "0.0", and the traffic of
    the ring was added up over the Sparks that had a reading and called that of "all Sparks"."""
    got = page_rules(
        "const e = (gbps, rx) => ({ gbps, rx, up: true, errors: false, capacity: 200 });"
        "const cells = [linkCells(e(35.72, 4), e(120, 9)), linkCells(e(null, null), e(null, null)),"
        " linkCells(e(null, 4), null), linkCells(e(10, 4), e(null, 2))].map(c => [c.out, c.back, c.last, c.tone]);"
        "const node = (net, live = true) => ({ live, net });"
        "const sums = [[node(1.5), node(2)], [node(1.5), node(null), node(2)], [node(null)], [node(1.5), node(9, false)]]"
        ".map(nodes => readSum(nodes, 'net'));"
        "return { cells, sums, words: sums.map(s => readWord(s, false)), past: readWord(sums[1], true) };"
    )
    assert got["cells"] == [
        ["35.7", "120", "60%", ""],
        ["–", "–", "–", ""],  # was "0.0", "0.0" and "0%"
        ["–", "4.0", "2%", ""],
        ["10.0", "–", "5%", ""],
    ], got["cells"]
    assert got["sums"] == [
        {"sum": 3.5, "read": 2, "of": 2},
        {"sum": 3.5, "read": 2, "of": 3},
        {"sum": 0, "read": 0, "of": 1},
        {"sum": 1.5, "read": 1, "of": 2},  # a Spark that is away is not read, whatever it last said
    ], got["sums"]
    assert got["words"] == ["all Sparks", "2 of 3 read", "0 of 1 read", "1 of 2 read"], got["words"]
    assert got["past"] == "2 of 3 recorded", got["past"]


@needs_node
def test_a_link_whose_state_nobody_read_is_not_called_down_in_the_list_of_links():
    """The Spark at the end of a cable is away: whether its link is up is not known. The list of ring links in nerd
    mode called every link "down" that was not known to be up."""
    got = page_rules(
        "const e = (up, more = {}) => ({ gbps: 10, rx: 4, up, errors: false, capacity: 200, ...more });"
        "return [linkCells(e(null), null), linkCells(e(false), null), linkCells(e(true), null),"
        " linkCells(e(null, { gbps: null, rx: null, errors: null }), null)].map(c => [c.last, c.tone]);"
    )
    assert got == [["5%", ""], ["down", "warn"], ["5%", ""], ["–", ""]], got  # the first was "down"


@needs_node
def test_a_link_read_as_down_at_its_other_end_is_called_down_in_the_list_of_links():
    """A cable has two ends. The list of ring links in nerd mode asked only the first of them whether the link is up:
    with the Spark at that end away (its state is unknown) and the other end reading the link as down, the row said
    how full the cable is. The ring itself draws such a link as down, and errors were asked of both ends already."""
    got = page_rules(
        "const e = up => ({ gbps: 10, rx: 4, up, errors: false, capacity: 200 });"
        "return [linkCells(e(null), e(false)), linkCells(e(true), e(false)), linkCells(e(false), e(true)),"
        " linkCells(e(true), e(null)), linkCells(e(null), e(null))].map(c => [c.last, c.tone]);"
    )
    down = ["down", "warn"]
    assert got == [down, down, down, ["5%", ""], ["5%", ""]], got  # the first two said "5%"


@needs_node
def test_a_link_without_a_line_rate_is_not_said_to_be_so_many_percent_full():
    """How full a cable is needs the rate it runs at. Where nobody read that rate, the list of ring links in nerd
    mode counted against 200 Gb/s."""
    got = page_rules(
        "const e = capacity => ({ gbps: 10, rx: 4, up: true, errors: false, capacity });"
        "return [linkCells(e(100), null), linkCells(e(null), null), linkCells(e(0), null)].map(c => c.last);"
    )
    assert got == ["10%", "–", "–"], got  # the second was "5%"


@needs_node
def test_a_list_nobody_read_adds_up_to_nothing_known_not_to_zero():
    """The table of the Sparks in nerd mode adds up two lists: how often the key threads of the engine changed core,
    and the time other programs took on its cores. A list that was not read counted as an empty one: 0."""
    got = page_rules(
        "return [sumOver([{ ms: 8 }, { ms: 6.5 }], t => t.ms), sumOver([], t => t.ms), sumOver(null, t => t.ms),"
        " sumOver(undefined, t => t.ms)];"
    )
    assert got == [14.5, 0, None, None], got  # the third and fourth were 0


@needs_node
def test_a_sum_with_a_part_nobody_read_is_not_known():
    """How often a key thread of the engine changed core is a rate between two looks: at its first look at a thread
    the sampler sends the thread without one. The table of the Sparks in nerd mode counted such a thread as 0: after
    a start of the sampler it said "0.0 /s" where nothing was measured yet, and later a sum that left a thread out."""
    got = page_rules(
        "const moved = list => sumOver(list, t => t.migrated);"
        "return [moved([{ migrated: null }, { migrated: null }]), moved([{ migrated: 1.3 }, { migrated: null }]),"
        " moved([{ migrated: 1.3 }, {}]), moved([{ migrated: 1.3 }, { migrated: 0 }])];"
    )
    assert got == [None, None, None, 1.3], got  # the first was 0, the second and third 1.3


@needs_node
def test_escape_closes_the_open_view_before_it_leaves_the_moment():
    """In front of a Spark at a moment of the past, Escape steps back to the ring and keeps the moment: finding it again
    costs more than opening the Spark again."""
    got = page_rules(
        "return [escapeDoes({ nerd: true, view: 'node', past: true, strip: true }), escapeDoes({ view: 'node', past: true, strip: true }),"
        " escapeDoes({ view: 'ring', past: true, strip: true }), escapeDoes({ view: 'ring', strip: true }), escapeDoes({ view: 'why' }),"
        " escapeDoes({ view: 'ring' })];"
    )
    assert got == ["nerd", "view", "live", "strip", "view", "view"], got


@needs_node
def test_a_moment_outside_the_loaded_stretch_is_loading_not_empty():
    """Before the recording of a stretch has arrived nobody knows what it holds: the page says so."""
    got = page_rules(
        LOOK_BACK
        + "return [momentOf(live, null, 110, 6.25), momentOf(live, got, 500, 6.25), momentOf(live, got, 115, 2)];"
    )
    for state in got[:2]:  # no recording yet, and a moment the loaded stretch does not cover
        assert state["loading"] is True
        assert "Loading" in state["why"]["headline"] and "recorded" not in state["engine"]["error"], state["why"]
        assert all(not n["live"] and "loading" in n["reason"] for n in state["nodes"])
    covered = got[2]  # inside the stretch, but no sample near it: that is a real hole
    assert covered["loading"] is False and "nothing was recorded" in covered["engine"]["error"]


@needs_node
def test_slow_fans_are_named_by_spark_not_by_speed():
    """Two Sparks with the same slow fans are both slow; the others are the Sparks that are not named."""
    setup = "const mk = (name, fan, c) => ({ name, fan, gpu_c: c, zones: {} });"
    got = page_rules(
        setup
        + "const twins = [mk('a',1500,70), mk('b',1500,70), mk('c',3000,70), mk('d',3000,70)];"
        + "const cool = [mk('a',2000,76), mk('b',2000,60), mk('c',3000,70), mk('d',3000,70), mk('e',3000,70)];"
        + "const real = [mk('x',2100,76), mk('y',2600,70), mk('z',2600,71), mk('w',2650,70)];"
        + "const still = [mk('a',0,70), mk('b',0,70), mk('c',0,70)];"
        + "return { twins: [oddFans(twins).map(n => n.name), coolingWord(twins)], cool: [oddFans(cool).map(n => n.name), coolingWord(cool)],"
        + " real: [oddFans(real).map(n => n.name), coolingWord(real)], still: [oddFans(still).map(n => n.name), coolingWord(still)],"
        + " few: oddFans([mk('a',1000,70), mk('b',3000,70)]).length, one: coolingWord([mk('a',2600,70)]) };"
    )
    assert got["twins"][0] == ["a", "b"]
    assert got["twins"][1][0] == "a and b turn their fans slower than the others"
    assert "the others 3,000 RPM" in got["twins"][1][1] and "1,500 RPM" in got["twins"][1][1]
    assert got["cool"][0] == ["a"]  # b turns as slowly but is ten degrees cooler: that is allowed
    assert "the others 2,000 to 3,000 RPM" in got["cool"][1][1], got["cool"][1][1]
    assert got["real"][0] == ["x"] and got["real"][1][0] == "x turns its fans slower than the others"
    # the rule lets a Spark be up to 1.5 °C cooler: the sentence says what the rule says, not "it is not cooler"
    assert got["real"][1][1] == (
        "2,100 RPM at 76 °C, the others 2,600 to 2,650 RPM. "
        "It is no more than 1.5 °C cooler than the middle of all Sparks."
    ), got["real"][1][1]
    assert got["twins"][1][1].endswith(" None of them is more than 1.5 °C cooler than the middle of all Sparks."), got[
        "twins"
    ][1][1]
    assert got["still"][0] == [] and "∞" not in got["still"][1][1] and "Infinity" not in got["still"][1][1]
    assert got["few"] == 0
    assert got["one"] == ["Cooling", "2,600 RPM at 70 °C on the warmest sensor."], got["one"]


@needs_node
def test_cooling_calls_only_like_fans_alike_and_names_a_fan_that_stands_still():
    """With fewer than three Sparks, or with two slow ones out of three, nobody can be named: that is still not "alike".
    And one fan standing still while its twin makes up for it shows in no average."""
    got = page_rules(
        "const mk = (name, fan, c, fans) => ({ name, fan, gpu_c: c, zones: {}, fans: fans || [fan, fan] });"
        "const two = [mk('a',1200,70), mk('b',3500,70)], three = [mk('a',1200,70), mk('b',1300,70), mk('c',2900,70)];"
        "const near = [mk('a',2578,70), mk('b',2644,71), mk('c',2600,70)], dead = [mk('a',3000,70,[0,6000]), mk('b',3000,70), mk('c',3050,70)];"
        "return { two: coolingWord(two), three: coolingWord(three), near: coolingWord(near), dead: coolingWord(dead),"
        " who: stoppedFans(dead).map(n => n.name), none: stoppedFans(near).length, alone: [aloneWord(1), aloneWord(4)] };"
    )
    assert got["two"][0] == "The fans turn at different speeds" and "1,200 to 3,500 RPM" in got["two"][1], got["two"]
    assert got["three"][0] == "The fans turn at different speeds", got["three"]
    assert got["near"][0] == "All 3 Sparks cool alike"
    uneven = page_rules(
        "const mk = (name, fan, fans) => ({ name, fan, gpu_c: 70, zones: {}, fans });"
        "return coolingWord([mk('a', 3000, [1000, 5000]), mk('b', 3000, [3000, 3000])]);"
    )
    assert uneven[0] == "The fans turn at different speeds", uneven  # the same average, but not the same fans
    assert got["dead"][0] == "a has a fan that stands still" and "0 / 6,000 RPM" in got["dead"][1], got["dead"]
    assert got["who"] == ["a"] and got["none"] == 0
    assert got["alone"] == [
        "the ring engine does not answer, 1 Spark works on its own",
        "the ring engine does not answer, 4 Sparks work on their own",
    ], got["alone"]


@needs_node
def test_a_fan_nobody_read_is_a_dash_and_no_fan_at_zero():
    """A Spark lists its fans in an order, and one of them can go unread for a sample: it then stands in the list
    as null, in its place. The rules counted a null as 0 RPM: "The fans turn at different speeds" for Sparks whose
    fans all turn alike, and "0 RPM" for the fan nobody read beside the one that stands still. A fan nobody read is
    a dash where the fans are named one by one, and counts for nothing where their speeds are compared."""
    got = page_rules(
        "const mk = (name, fan, fans) => ({ name, fan, gpu_c: 70, zones: {}, fans });"
        "const rest = [mk('b', 2650, [2640, 2660]), mk('c', 2620, [2610, 2630])];"
        "const half = [mk('a', 2600, [null, 2600]), ...rest], still = [mk('a', 1300, [0, 2600, null]), ...rest];"
        "return { word: coolingWord(half), still: coolingWord(still), who: stoppedFans(half).length,"
        " speeds: typeof fanSpeeds === 'function' && [fanSpeeds(half[0]), fanSpeeds(rest[0]), fanSpeeds({}), fanSpeeds({ fans: null })] };"
    )
    assert got["word"][0] == "All 3 Sparks cool alike", got["word"]  # was "The fans turn at different speeds"
    assert got["still"][1].startswith("0 / 2,600 / – RPM at 70 °C"), got["still"]  # was "0 / 2,600 / 0 RPM"
    assert got["who"] == 0  # unread is not a fan that stands still
    assert got["speeds"] == [["–", "2,600"], ["2,640", "2,660"], [], []], got["speeds"]  # each fan in its place


@needs_node
def test_who_sets_the_fans_is_only_said_when_it_was_read():
    """A state that could not be read is unknown, never zero; a level asked for through ACPI shows beside a quiet floor."""
    got = page_rules(
        "const fan = (cur, max = 100) => ({ type: 'Fan', cur, max }), floor = (cur, max = 10) => ({ type: 'dgx_ec_fan_floor', cur, max });"
        "return [fanSetter({ cooling: [fan(null, null), fan(null, null)] }), fanSetter({ cooling: [floor(null)] }),"
        " fanSetter({ cooling: [floor(0), fan(3), fan(0)] }), fanSetter({ cooling: [floor(4, null)] }),"
        " fanSetter({ cooling: [fan(0), fan(0)] }), fanSetter({ cooling: [floor(0), fan(0)] }), fanSetter({}),"
        " fanSetter({ cooling: [floor(2), fan(3)] }), fanSetter({ cooling: [floor(0), fan(null)] }), fanSetter({ cooling: [floor(null), fan(5)] })];"
    )
    assert got == [
        "",
        "",
        "a level of 3 of 100 asked for through ACPI",
        "a floor of 4 through dgx-spark-fan-control",
        "the firmware alone",
        "the firmware; dgx-spark-fan-control is loaded and asks for nothing",
        "",
        "a floor of 2 of 10 through dgx-spark-fan-control and a level of 3 of 100 asked for through ACPI",
        "",
        "a level of 5 of 100 asked for through ACPI",
    ], got


@needs_node
def test_any_key_ends_the_tour_even_with_the_tour_button_in_focus():
    """Started with a click, the button keeps the focus: a 2 pressed then must not be swallowed."""
    got = page_rules(
        "const btn = { closest: s => s === '#tour-btn' ? {} : null }, page = { closest: () => null };"
        "return [tourStops('keydown', { key: '2', target: btn }), tourStops('keydown', { key: 'Enter', target: btn }),"
        " tourStops('keydown', { key: ' ', target: btn }), tourStops('keydown', { key: 'Enter', target: page }),"
        " tourStops('pointerdown', { target: btn }), tourStops('touchstart', { target: btn }), tourStops('wheel', { target: btn }),"
        " tourStops('pointerdown', { target: page }), tourStops('keydown', { key: 'k', target: page }),"
        " tourStops('keydown', { key: 'K', target: btn }), tourStops('keydown', { key: 'Shift', target: page }),"
        " tourStops('keydown', { key: 'r', metaKey: true, target: page }), tourStops('keydown', { key: 'Escape', target: {} })];"
    )
    assert got == [True, False, False, True, False, False, True, True, False, False, False, False, True], got


@needs_node
def test_a_lost_stream_never_takes_the_place_of_looking_back():
    """While the page shows a moment of the past, a blip of the stream must not relabel it and then stick."""
    got = page_rules(
        "return [linkStatus(true, false), linkStatus(true, true), linkStatus(false, true), linkStatus(false, false)];"
    )
    assert got == [[False, "Looking back"], [False, "Looking back"], [True, "Live"], [False, "Reconnecting"]], got


@needs_node
def test_the_sign_beside_the_hoops_also_stands_when_no_draft_survives():
    got = page_rules("return [hoopsWord([0, 0]), hoopsWord([0.78, null, 0.33]), hoopsWord([0.5]), hoopsWord([])];")
    assert got == ["drafts kept 0 → 0 %", "drafts kept 78 → 33 %", "", ""], got


@needs_node
def test_single_tracks_add_up_only_what_each_spark_s_own_engine_says():
    """The sum in the core is the sum of the engines that answered and write. A Spark that works without an engine to
    ask, or whose engine is silent, is counted as "without a reading", never with a guessed speed."""
    got = page_rules(
        TRACKS
        # a reader's trickle is no writing: it must not reach the sum, so it is not zero here
        + "const reader = { model: 'x', state: 'reading', tok_s: 0.4, running: 1, waiting: 0, ttft_p95: null };"
        + "const st = alone([node('a', null), node('b', writing(30.5, { running: 2, waiting: 1 })), node('c', writing(4.25, { ttft_p95: 2.4 })),"
        + " node('d', reader), node('e', { model: 'y', state: 'offline' }), { name: 'f', live: false, own: writing(99) }],"
        + " { why: { own: { a: 'sglang::scheduler', b: 'm' } } });"
        + "const t = tracksOf(st);"
        + "return [[t.tok_s, t.running, t.waiting, t.ttft, t.asked, t.writing, t.reading, t.idle, t.blind, t.timed], t.rows.map(r => r.kind), tracksWord(t), tracksFace(t),"
        + " ['writing', 'reading', 'idle', 'asleep'].map(state => tracksOf({ ...st, engine: { state } })),"
        + " tracksOf(alone([node('a', null)], { why: { own: { a: 'x' } } })),"
        + " tracksFace(tracksOf(alone([node('d', reader), node('g', { model: 'z', state: 'asleep', tok_s: 0, running: 0, waiting: 0 })])))];"
    )
    figures, kinds, word, face, serving, nobody, readers = got
    assert figures == [34.75, 4, 1, 2.4, 3, 2, 1, 0, 2, 2], figures  # the slowest first token of the 2 that have one
    assert kinds == ["blind", "writing", "writing", "reading", "blind", "none"], kinds
    assert word == "2 writing · 1 reading · 2 without a reading", word
    assert face == {"word": "Single tracks", "tone": "writing", "goal": 34.75, "sub": word}, face
    assert serving == [None] * 4, serving  # while the ring engine answers, whatever it does, its numbers stand
    assert nobody is None  # no engine of its own answers anywhere: the page keeps what it said before
    assert readers["goal"] is None and readers["tone"] == "reading", readers  # nobody writes: no number, not a zero
    assert readers["sub"] == "1 reading · 1 idle", readers


@needs_node
def test_a_tile_and_a_spark_name_the_own_engine_and_its_speed():
    got = page_rules(
        TRACKS
        + "return [ownNote(writing(30.4, { model: 'mistral-small-4' }), 'mistral-small-4'), ownNote({ model: 'm', state: 'offline' }, 'm'),"
        + " ownNote({ model: 'm', state: 'reading' }, ''), ownNote(null, 'sglang::scheduler'), ownNote(null, ''),"
        + " ownNote({ model: null, state: 'writing', tok_s: 12 }, ''),"
        + " ownSpeed(node('a', writing(30)), { state: 'offline' }), ownSpeed(node('a', writing(30)), { state: 'writing' }),"
        + " ownSpeed({ name: 'a', live: false, own: writing(30) }, { state: 'offline' }), ownSpeed(node('a', { state: 'reading', tok_s: 0.4 }), { state: 'offline' }),"
        + " ownSpeed(node('a', null), { state: 'offline' })];"
    )
    assert got[:6] == [
        "30 tok/s · mistral-small-4",  # the speed first: a narrow tile cuts the end of the line
        "no answer · m",
        "reading · m",
        "runs sglang::scheduler",
        "",
        "12 tok/s · own engine",  # looking back, the model was not recorded
    ], got
    assert got[6:] == [30, 0, 0, 0, 0], got  # sparks fly from a Spark only for tokens its own engine wrote


@needs_node
def test_an_engine_that_answers_without_its_request_counts_is_not_said_to_be_silent():
    """The server gives an engine that answers without its request counts as one nobody can read, and says that it
    answers. The page then does not say "does not answer" of it: not of the ring engine in the core, and not of
    a Spark's own engine on its tile."""
    got = page_rules(
        "const bare = { state: 'offline', error: 'The engine answers without its request counters.', answers: true };"
        "return [silentWord({ state: 'offline', error: 'x' }), silentWord(bare), aloneWord(2, bare),"
        " ownNote({ model: 'm', state: 'offline', error: bare.error }, 'm'), ownNote({ model: 'm', state: 'offline' }, 'm')];"
    )
    assert got == [
        "the ring engine does not answer",
        "the ring engine answers without its request counters",
        "the ring engine answers without its request counters, 2 Sparks work on their own",
        "no request counts · m",
        "no answer · m",
    ], got


@needs_node
def test_the_tracks_of_a_run_are_listed_in_the_order_of_the_sparks_and_count_only_what_was_told():
    got = page_rules(
        "const nodes = [{ name: 'c' }, { name: 'b' }, { name: 'a' }];"  # the order of the Sparks, not of the alphabet
        "return [trackRows([{ node: 'a', name: 'y' }, { node: 'zz', name: 'lost' }, { node: 'c', name: 'x' }, null, 'junk'], nodes).map(r => r.node),"
        " trackRows('junk', nodes), trackRows(undefined, nodes), trackRows({ node: 'a' }, nodes),"
        " [{ done: 3, total: 10 }, { done: 0, total: 7 }, { done: 5 }, {}, { done: null, total: null }, { total: 10 }].map(trackCount),"
        " [{ done: 3, total: 10 }, { done: 12, total: 10 }, { done: 1 }, null, { done: -1, total: 4 }, { total: 10 }].map(trackShare),"
        " [{ name: 'Forms', done: 24, total: 30 }, { name: 'Film test' }, null].map(trackWord),"
        " tracksShown([1, 2, 3, 4], 4), tracksShown([1, 2, 3, 4, 5, 6], 4),"
        " [jobOf([{ node: 'a', name: 'y' }, { node: 'c', name: 'x' }], 'c').name, jobOf([{ node: 'a', name: 'y' }], 'b'), jobOf([], 'a')]];"
    )
    assert got == [
        ["c", "a", "zz"],
        [],
        [],
        [],
        ["3 of 10", "0 of 7", "5 done", "", "", ""],  # a total without a count: how far it is, nobody said
        [0.3, 1, None, None, 0, None],
        ["Forms · 24 of 30", "Film test", ""],
        {"rows": [1, 2, 3, 4], "more": 0},
        {
            "rows": [1, 2, 3],
            "more": 3,
        },  # a big cluster: three lines and "and 3 more", never a panel that pushes the rest out
        ["x", None, None],  # a tile shows the job of its own Spark and of no other
    ], got


@needs_node
def test_the_speed_line_adds_the_engines_that_were_read_and_bridges_no_hole():
    got = page_rules(
        "const a = { t: [0, 2, 4, 6], v: [10, 10, 10, 10] }, b = { t: [1, 3, 5], v: [1, 2, 3] }, late = { t: [100, 102], v: [7, 7] },"
        " slow = { t: [0, 60, 120], v: [5, 5, 5] };"
        "return [sumTrace([a, b], 3), sumTrace([a], 3) === a, sumTrace([null, undefined], 3), sumTrace([a, late], 3), sumTrace([a, slow], 3),"
        " spacingOf([0, 2, 4, 6, 600, 602]), spacingOf([5]), spacingOf([]), spacingOf([0, 2, 100]),"
        " sumTrace([{ t: [0, 2, 100], v: [10, 10, 10] }, { t: [10], v: [1] }], 3),"
        " sumTrace([{ t: [0, 40], v: [10, 10] }, slow], 3)];"
    )
    both, same, none, hole, mixed, spacing, one, empty, few, lone, far = got
    # 40 s after its sample the one-minute trace still counts: a reach of a few seconds for every trace would drop it
    assert far == {"t": [0, 40, 60, 120], "v": [15, 15, 15, 15]}, far
    assert few == 2 and lone["v"] == [10, 10, 1, 10], (few, lone)  # one hole among three samples is no sampling rate
    assert both == {"t": [0, 1, 2, 3, 4, 5, 6], "v": [10, 11, 11, 12, 12, 13, 13]}, both  # each one's last value
    assert same is True and none is None
    assert hole == {"t": [0, 2, 4, 6, 100, 102], "v": [10, 10, 10, 10, 7, 7]}, hole  # 94 s later, a counts no more
    # a trace kept as one-minute values reaches a minute far, one sampled every 2 s only a few seconds
    assert mixed == {"t": [0, 2, 4, 6, 60, 120], "v": [15, 15, 15, 15, 5, 5]}, mixed
    assert [spacing, one, empty] == [2, 0, 0]  # the usual distance, whatever holes there are


@needs_node
def test_looking_back_shows_the_single_tracks_as_they_were_recorded():
    got = page_rules(
        "const live = { t: 1000, cluster: { ring: true, nodes: [{ name: 'a', rank: 0, head: true }, { name: 'b', rank: 1 }] }, identity: { interval: 2 },"
        " nodes: [{ name: 'a', live: true, own: null }, { name: 'b', live: true, own: { model: 'today', state: 'writing', tok_s: 99 } }], edges: [],"
        " why: { own: { a: 'today-work' } }, run: { tracks: [{ node: 'b', name: 'today-job' }] } };"
        "const rec = { t: [100, 102, 104], tier: 'raw', from: 90, to: 120, events: [], series: { 'a.w': [30, 31, 32], 'b.w': [20, 21, 22],"
        " 'b.own_tok_s': [40, 41, 0.2], 'b.own_running': [1, 1, 1], 'b.own_waiting': [0, 2, 0], 'b.own_ttft_p95': [1.5, 1.6, 1.7] } };"
        "const m = momentOf(live, rec, 102.5, 6.25), later = momentOf(live, rec, 104.5, 6.25), t = tracksOf(m);"
        "return [m.nodes.map(n => n.own), later.nodes[1].own.state, [t.tok_s, t.writing, t.blind, m.run.tracks === undefined], m.why.headline, later.why.headline,"
        " KEPT_NODE.filter(k => k.startsWith('own_'))];"
    )
    owns, later, sums, headline, quiet, kept = got
    assert owns == [
        None,
        {"model": None, "state": "writing", "tok_s": 41, "running": 1, "waiting": 2, "ttft_p95": 1.6},
    ], owns
    assert later == "reading"  # 0.2 tokens/s with a request running: a prompt being read
    assert sums == [41, 1, 0, True], sums  # nothing of today: not its model, its job, or what the server names now
    assert headline == "The engine did not answer at this moment. 1 Spark wrote on its own: 41 tokens per second.", (
        headline
    )
    assert quiet == "The engine did not answer at this moment. 1 Spark served on its own without writing.", quiet
    assert kept == ["own_tok_s", "own_running", "own_waiting", "own_ttft_p95"], kept


@needs_node
def test_what_nobody_read_is_neither_zero_nor_idle():
    """A count that was not read is no "0 running", and a moment without a recorded speed is no "without writing"."""
    got = page_rules(
        TRACKS
        + "const t = tracksOf(alone([node('b', { model: 'm', state: 'writing', tok_s: 5 })]));"
        + "const past = tracksOf(alone([node('b', { model: null, state: 'reading', tok_s: null, running: 1, waiting: 0 })]));"
        + "return [t.running, t.waiting, t.tok_s, tracksPast(past)];"
    )
    assert got == [None, None, 5, "1 Spark served on its own, no speed was recorded."], got


@needs_node
def test_a_tile_says_below_the_memory_guard_when_free_memory_is_under_it():
    """Under the line of the memory guard is below it, up to 2 GB above it is near it; unread is neither."""
    got = page_rules(
        "return [guardWord(0.4, 32), guardWord(32, 32), guardWord(33.9, 32), guardWord(34.1, 32),"
        " guardWord(null, 32), guardWord(5, null)];"
    )
    near = "Near the 32 GB memory guard"
    assert got == ["Below the 32 GB memory guard", near, near, "", "", ""], got


@needs_node
def test_a_line_about_one_spark_at_a_moment_of_the_past_names_it():
    """The page of one Spark shows the lines about that Spark, also looking back: each carries its name as a field.
    A line about several Sparks carries none."""
    got = page_rules(
        "const live = { cluster: { nodes: [{ name: 'a', rank: 0, head: true }, { name: 'b', rank: 1 }] },"
        " identity: { interval: 2 }, nodes: [], edges: [] };"
        "const rec = { t: [100], tier: 'raw', from: 90, to: 120, events: [],"
        " series: { 'engine.tok_s': [50], 'a.gpu_c': [90], 'a.cap_pct': [40], 'a.mhz': [800] } };"
        "return momentOf(live, rec, 100, 6.25).why.points;"
    )
    assert got == [
        {"level": "warn", "text": "a was running hot: 90 °C.", "node": "a"},
        {"level": "warn", "text": "a spent 40 % of the time at its power cap.", "node": "a"},
        {"level": "bad", "text": "a ran its GPU at 800 MHz while the engine was writing.", "node": "a"},
        {"level": "warn", "text": "1 of 2 Sparks have no reading at this moment."},
    ], got


@needs_node
def test_escape_closes_an_explaining_box_before_it_leaves_anything_else():
    """One step back out is what Escape does. A box that explains what is on the page is the last thing a reader
    opened: it goes first, whatever else is open, and without one the order is as it was."""
    got = page_rules(
        "return [escapeDoes({ box: true, nerd: true, view: 'node', past: true, strip: true }), escapeDoes({ box: true, view: 'ring' }),"
        " escapeDoes({ box: false, nerd: true, view: 'node' }), escapeDoes({ view: 'cooling' })];"
    )
    assert got == ["box", "box", "nerd", "view"], got


@needs_node
def test_connections_nobody_read_are_not_said_to_be_none():
    """The Requests tab of the deep view lists the open connections to the engine. A list nobody read (the head is
    away, or has not told yet) was written as "No connections right now.". That is said only of a list that was
    read and is empty; a list with connections needs no word."""
    got = page_rules(
        "return [connectionsWord(null), connectionsWord(undefined), connectionsWord([]), connectionsWord([{ port: '1' }])];"
    )
    assert got == [
        "The connections were not read.",
        "The connections were not read.",
        "No connections right now.",
        "",
    ], got


@needs_node
def test_the_far_end_of_a_cable_says_its_port_where_two_cables_lead_to_the_same_spark():
    """A cable of a Spark is named by the Spark at its other end. Two Sparks alone share two cables: named so, both
    read the same. One rule for every place that names a cable: the port goes with the name where another cable of
    the same Spark leads to the same one, and only there; a cable nobody is at the other end of has no name."""
    got = page_rules(
        "const nodes = [{ name: 'a', rank: 0 }, { name: 'b', rank: 1 }, { name: 'c', rank: 2 }];"
        "const ring = [{ from: 1, to: 0, group: 'f0' }, { from: 1, to: 2, group: 'f1' }];"
        "const pair = [{ from: 1, to: 0, group: 'f0' }, { from: 1, to: 0, group: 'f1' }];"
        "const lost = [{ from: 1, to: 7, group: 'f0' }, { from: 1, to: 7, group: 'f1' }];"
        "return [ring, pair, lost].map(mine => mine.map(e => farEnd(e, mine, nodes)));"
    )
    assert got == [["a", "c"], ["a f0", "a f1"], [None, None]], got


@needs_node
def test_a_spark_that_answers_without_a_fan_reading_is_one_the_headline_of_cooling_leaves_out():
    """The headline of the cooling view speaks of the Sparks that have a fan reading and a warmest sensor. A Spark
    that answers and whose fans were not read is left out of it, and nothing named it. The rule that finds these
    Sparks: it answers, and there is no reading of its fans. A fan that stands still is a reading (0 RPM), and a
    Spark out of reach is not one of them: nothing of it was read at all. What is said of them names each one,
    is another sentence looking back (there a reading is recorded or not), and is nothing where there is none."""
    got = page_rules(
        "const n = (name, live, fan) => ({ name, live, fan });"
        "const who = fansUnread([n('a', true, 2600), n('b', true, null), n('c', false, null), n('d', true, 0), n('e', true, undefined)]);"
        "return [who, fansUnread([]), fansUnreadWord([], false), fansUnreadWord([], true),"
        " fansUnreadWord(['b'], false), fansUnreadWord(['b', 'e'], false), fansUnreadWord(['b', 'e', 'f'], true)];"
    )
    assert got[:4] == [["b", "e"], [], "", ""], got
    # the sentence says who the headline leaves out and why: no reading of the fans; it says nothing of the fans themselves
    assert got[4] == "Left out: b (no fan reading).", got[4]
    assert got[5] == "Left out: b and e (no fan reading).", got[5]
    assert got[6] == "Left out: b, e and f (no fan reading recorded).", got[6]
