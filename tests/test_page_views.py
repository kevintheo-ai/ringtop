"""The views beside the sheet, driven without a browser: what they say where a reading is missing."""

import json

from tests.fixtures import needs_node
from tests.test_page_sheet import moments, sheet

# A moment in which the ring engine answers and writes, while none of its counts was read: down the stream, one
# sample after the newest one.
UNREAD = (
    "server.say({ ...LIVE, t: LIVE.t + 2, engine: { state: 'writing', tok_s: 12, running: null, waiting: null,"
    " finished: null, prompt_avg: null, output_avg: null, timing: {} } }); null"
)
TEXTS = "(el => el.under().map(e => e.text).filter(Boolean))"  # every text an element and the ones under it hold


@needs_node
def test_a_count_nobody_read_is_a_dash_on_every_view_never_a_zero():
    """The engine answers, and its counts of requests and tokens were not read. The core, the vitals, the Why view and
    the head of nerd mode said "0 running", "0 waiting", "0 tokens in", "0 / 0" and "0 done": counts nobody took.
    A count that was not read is a dash, and two counts are added up only where both were read."""
    got = sheet(
        [
            UNREAD,
            "document.querySelector('#core-sub').text",
            f"{TEXTS}(document.querySelector('#vitals'))",
            "setView('why'); null",
            "document.querySelector('#panel').under().filter(e => e.matches('div.grid3'))"
            ".flatMap(g => g.children.map(c => c.children.map(x => x.text).join(' ')))",
            "Nerd.toggle(true); null",
            "document.querySelector('#n-kpis').children.map(c => c.children.map(x => x.text))",
            "[{ running: 2, waiting: 1 }, { running: null, waiting: 1 }].map(e => coreFace({ state: 'reading', ...e }).sub)",
        ]
    )
    assert got[7] == ["3 requests in progress", "– running · 1 waiting"], got[7]
    assert got[1] == "– running · – waiting", got[1]
    vitals = got[2]
    assert "– running" in vitals and "– waiting" in vitals, vitals
    assert got[4] == ["n/a per request", "– tokens in", "– tokens out"], got[4]
    cards = {card[0]: card[1:] for card in got[6]}
    assert cards["Running / waiting"] == ["– / –", "– done"], cards["Running / waiting"]
    assert cards["Tokens/s"][0] == "12", cards["Tokens/s"]


@needs_node
def test_a_ring_engine_that_answers_without_its_request_counts_is_not_called_silent_on_the_page():
    """The ring engine answers without its request counts: the server gives it as not readable, with the reason. The
    core says that reason, and the sheet of a Spark does not say that the ring engine does not answer."""
    bare = (  # a moment in which no Spark works on its own: the core then speaks of the ring engine
        "server.say({ ...LIVE, t: LIVE.t + 2, why: { headline: 'x', points: [] },"
        " nodes: LIVE.nodes.map(n => ({ ...n, own: null })), engine: { state: 'offline',"
        " error: 'The engine answers without its request counters.', answers: true } }); null"
    )
    silent = "server.say({ ...LIVE, t: LIVE.t + 4, engine: { state: 'offline', error: 'Nothing answers.' } }); null"
    got = sheet(
        [
            bare,
            "document.querySelector('#core-sub').text",
            "setView('node', S.nodes[1].name); null",
            "said('sp-doing')[0]",
            silent,
            "said('sp-doing')[0]",
        ]
    )
    assert got[1] == "The engine answers without its request counters.", got[1]
    assert got[3] == (
        "The ring engine answers without its request counters, and ringtop sees no work of its own on this Spark."
    ), got[3]
    assert got[5] == "The ring engine does not answer, and ringtop sees no work of its own on this Spark.", got[5]


@needs_node
def test_the_traffic_of_the_ring_says_how_many_sparks_it_is_the_sum_of():
    """The traffic of the ring is added up over the Sparks. Where one of them has no reading of it, the sum of the
    others stood under "all Sparks"; and the list of ring links in nerd mode wrote "0.0" for a cable nobody read."""
    part = (
        "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, i) => ({ ...n, net: i ? 1.5 : null })),"
        " edges: LIVE.edges.map((e, i) => i ? e : { ...e, gbps: null, rx: null }) }); null"
    )
    got = sheet(
        [
            f"{TEXTS}(document.querySelector('#vitals'))",
            part,
            f"{TEXTS}(document.querySelector('#vitals'))",
            "Nerd.toggle(true); null",
            "document.querySelector('#n-right').under().filter(e => e.matches('div.n-mx'))[1].children.slice(4, 8)"
            ".map(c => c.text)",
        ]
    )
    assert "all Sparks" in got[0], got[0]
    assert "4.5 Gb/s" in got[2] and "3 of 4 read" in got[2] and "all Sparks" not in got[2], got[2]
    assert got[4][:3] == ["dgx0 ↔ dgx1", "–", "0.0"], got[4]  # what the first Spark sent was not read: was "0.0"


@needs_node
def test_a_link_gets_no_bar_against_a_line_rate_nobody_read():
    """The panel of the network card draws a bar per link: its traffic against the rate the link runs at. Without a
    reading of that rate the bar stood against 200 Gb/s, and without a reading of the traffic it stood empty, like
    a link that carries nothing. Then the line stands without a bar."""
    words = "(cls => document.querySelector('#panel').under().filter(e => e.matches(cls)).map(m => m.under().map(e => e.text).filter(Boolean)[0]).filter(w => w.startsWith('Link to ')).length)"
    blind = "server.say({ ...LIVE, t: LIVE.t + 2, edges: LIVE.edges.map(e => ({ ...e, capacity: null })) }); null"
    unread = "server.say({ ...LIVE, t: LIVE.t + 2, edges: LIVE.edges.map(e => ({ ...e, capacity: 200, gbps: null, rx: null })) }); null"
    got = sheet(
        [
            "setView('node', S.nodes[1].name); setPart('cx7'); null",
            f"[{words}('div.meter'), {words}('div.memhead')]",
            blind,
            f"[{words}('div.meter'), {words}('div.memhead')]",
            unread,
            f"[{words}('div.meter'), {words}('div.memhead')]",
        ]
    )
    assert got[1] == [2, 2], got[1]  # the two links of a Spark in the ring, each a bar with its line
    assert got[3] == [0, 2], got[3]  # no rate: the line without a bar
    assert got[5] == [0, 2], got[5]  # no traffic read: no empty bar either


@needs_node
def test_a_link_gets_no_bar_from_one_way_of_its_traffic_alone():
    """The bar of a link stands for the mean of what it carries out and back in. With one of the two ways not read
    (a counter of it fell back between two samples) the bar counted that way as 0: half as full as the way that
    was read, or empty like a link that carries nothing, beside a line that says the way is not known."""
    rows = "(cls => document.querySelector('#panel').under().filter(e => e.matches(cls)).map(m => m.under().map(e => e.text).filter(Boolean)).filter(w => w[0].startsWith('Link to ')))"
    half = "server.say({ ...LIVE, t: LIVE.t + 2, edges: LIVE.edges.map(e => ({ ...e, capacity: 200, gbps: 60, rx: null })) }); null"
    got = sheet(
        [
            "setView('node', S.nodes[1].name); setPart('cx7'); null",
            half,
            f"[{rows}('div.meter').length, {rows}('div.memhead').length]",
            f"{rows}('div.memhead').map(w => w[1])[0]",
        ]
    )
    assert got[2] == [0, 2], got[2]  # was [2, 2]: each a bar, 15 % full for a link that sends 60 Gb/s
    assert "60.0 out" in got[3] and "– in Gb/s" in got[3], got[3]  # the line still says what was read


@needs_node
def test_two_cables_to_the_same_spark_are_told_apart_on_the_cards_of_its_parts():
    """Two Sparks alone share two cables. The sheet of one of them names each cable with its port; the cards of its
    network card and of its ports found the name of the far end by themselves and said the same words twice: "Link
    to dgx0", "Port to dgx0" and "Traffic to dgx0, 30 min". They ask the rule of the sheet: a cable that is not the
    only one to its Spark says its port, and a ring in which every cable leads to another Spark reads as before."""
    twins = "server.say({ ...LIVE, t: LIVE.t + 2, edges: LIVE.edges.map(e => e.from === S.nodes[1].rank ? { ...e, to: S.nodes[0].rank } : e) }); null"
    words = "document.querySelector('#panel').under().map(e => e.text).filter(w => /^(Link|Port|Traffic) to /.test(w))"
    got = sheet(
        [
            "setView('node', S.nodes[1].name); setPart('cx7'); null",
            words,
            twins,
            f"[{words}, (setPart('qsfp_cage'), {words}), S.edges.filter(e => e.from === S.nodes[1].rank).map(e => e.group)]",
        ]
    )
    assert got[1] == ["Link to dgx2", "Traffic to dgx2, 30 min", "Link to dgx0", "Traffic to dgx0, 30 min"], got[1]
    card, cage, ports = got[3]
    assert len(ports) == 2 and len(set(ports)) == 2, ports
    assert card == [w for p in ports for w in (f"Link to dgx0 {p}", f"Traffic to dgx0 {p}, 30 min")], (
        card
    )  # was each twice
    assert cage == [w for p in ports for w in (f"Port to dgx0 {p}", f"Traffic to dgx0 {p}, 30 min")], cage


@needs_node
def test_the_panel_of_a_part_draws_no_bar_and_no_figure_from_a_reading_nobody_has():
    """The panel of a part of the open Spark drew its bars as if a reading nobody has were 0. With the clock or the
    power of a Spark not read the bar stood empty, as for a GPU that stands still; with its free space not read the
    SSD stood as full; and the ports on its back carried "0.0" Gb/s. Looking back, where the free space is not
    kept, the SSD of every Spark stood as full. A reading nobody has gets its line and no bar, and a dash."""
    then = json.loads(moments())["past"]["t"]
    bars = "document.querySelector('#panel').under().filter(e => e.matches('div.meter')).map(m => m.under().map(e => e.text).filter(Boolean)[0])"
    said = "document.querySelector('#panel').under().map(e => e.text).filter(Boolean)"
    unread = "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, i) => i === 1 ? { ...n, mhz: null, w: null, disk_free_gb: null, net: null } : n) }); null"
    parts = ("gb10_die_gpu", "gb10_package", "ssd_m2")
    got = sheet(
        [
            "setView('node', S.nodes[1].name); null",
            *(f"setPart('{part}'); {bars}" for part in parts),
            unread,
            *(f"setPart('{part}'); [{bars}, {said}]" for part in parts),
            f"setPart('io_plate'); {said}",
            f"setPart(null); Time.toggle(true); Time.go({then[len(then) // 2]}); null",
            f"setPart('ssd_m2'); [S.nodes[1].live, {bars}, {said}]",
        ]
    )
    assert got[1:4] == [["Clock"], ["GPU power"], ["Used"]], got[1:4]  # read: each with its bar
    assert [g[0] for g in got[5:8]] == [[], [], []], got[5:8]  # were the same three bars: empty, empty and full
    assert all(word in g[1] for word, g in zip(("Clock", "GPU power", "Used"), got[5:8])), got[5:8]  # its line stays
    assert "0.0" not in got[8] and "–" in got[8], got[8]  # was "0.0" Gb/s on the ring
    live, drawn, lines = got[10]
    assert live is True and drawn == [] and "Used" in lines, got[10]  # was a full bar for every Spark


@needs_node
def test_the_page_stands_with_a_spark_that_is_away_and_holds_no_reading():
    """The server gives a Spark nobody reaches without any reading: every figure of its node is null, only what the
    machine is stays. No view may fall over that, none may show a figure for it, and no sum may count it."""
    away = (
        "const kept = ['name', 'rank', 'head', 'peers', 'mem_total_gb', 'mhz_max', 'disk_total_gb', 'capacity', 'startup'];"
        "const gone = n => ({ ...Object.fromEntries(Object.keys(n).map(k => [k, kept.includes(k) ? n[k] : null])),"
        " live: false, reason: 'ssh: timed out', since: LIVE.t });"
        "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, i) => i === 3 ? gone(n) : n),"
        " edges: LIVE.edges.map(e => e.from === 3 ? { ...e, gbps: null, rx: null, up: null, errors: null, capacity: null } : e) }); null"
    )
    tile = "(t => [t.value.text, t.temp.text, t.mem.text, t.net.text, t.clock.text])(tiles.get(S.nodes[3].name))"
    got = sheet(
        [
            away,
            f"{TEXTS}(document.querySelector('#vitals'))",
            "Math.round(S.nodes.filter(n => n.live).reduce((a, n) => a + n.w, 0)) + ' W'",
            tile,
            *(f"setView('{view}'); null" for view in ("why", "memory", "cooling", "events", "run", "ring")),
            "setView('node', S.nodes[3].name); null",
            "[said('sp-doing')[0], said('sp-age')[0]]",
            "setView('ring'); Nerd.toggle(true); null",
            *(
                f"Nerd.tab('{tab}'); null"
                for tab in ("nodes", "links", "engine", "requests", "sync", "history", "live")
            ),
            "Nerd.toggle(false); Tour.toggle(true); null",
            "Tour.toggle(false); null",
        ]
    )
    power = got[1][got[1].index("GPU power") + 1 :][:2]
    assert power == [got[2], "3 of 4 read"], power  # the power of the three that answer, said as that
    assert got[3] == ["–", "–", "–", "–", "–"], got[3]
    assert got[11] == ["Not reachable: ssh: timed out.", "no reading"], got[11]


@needs_node
def test_the_power_of_the_cluster_says_how_many_sparks_it_is_the_sum_of():
    """The power of the cluster is added up over the Sparks. A Spark that answers without a reading of its power
    counted among the "4 of 4 live" under a sum of three; and the deep view called the sum of the server "GPU
    power, all Sparks" whatever it was the sum of. The tile of that sum was called "Cluster power", as if it were
    what the machines draw: it is the GPU power nvidia-smi reports, and is called that."""
    part = (
        "server.say({ ...LIVE, t: LIVE.t + 2, nodes: LIVE.nodes.map((n, i) => ({ ...n, w: i ? 40 : null })),"
        " engine: { state: 'writing', tok_s: 100, running: 1, waiting: 0, watts: 120, watts_from: 3, timing: {} } }); null"
    )
    whole = part.replace("i ? 40 : null", "40").replace("watts: 120, watts_from: 3", "watts: 160, watts_from: 4")
    pane = "document.querySelector('#n-pane').under().map(e => e.text).filter(t => t.startsWith('GPU power') || / W$/.test(t))"
    got = sheet(
        [
            part,
            f"{TEXTS}(document.querySelector('#vitals'))",
            "Nerd.toggle(true); Nerd.tab('engine'); Nerd.toggle(false); Nerd.toggle(true); null",  # opened on that tab, nerd mode asks for the deep readings at once
            pane,
            whole,
            f"{TEXTS}(document.querySelector('#vitals'))",
            "Nerd.tab('engine'); null",
            pane,
        ]
    )
    assert "Cluster power" not in got[1] and got[1].count("GPU power") == 1, got[1]  # the tile says whose watts
    assert got[1][got[1].index("GPU power") + 1 :][:2] == ["120 W", "3 of 4 read"], got[1]  # was "4 of 4 live"
    assert got[3] == ["GPU power, 3 of 4 read", "120 W"], got[3]  # was "GPU power, all Sparks"
    assert got[5][got[5].index("GPU power") + 1 :][:2] == ["160 W", "4 of 4 read"], got[5]
    assert got[7] == ["GPU power, all Sparks", "160 W"], got[7]
    # the engine stops answering while the tab still holds its last deep reading: no count that was never given
    off = "server.say({ ...LIVE, t: LIVE.t + 2, engine: { state: 'offline', error: 'Nothing answers.' } }); null"
    assert sheet(
        [
            part,
            "Nerd.toggle(true); Nerd.tab('engine'); Nerd.toggle(false); Nerd.toggle(true); null",
            off,
            "Nerd.tab('engine'); null",
            pane,
        ]
    )[4] == [
        "GPU power, 0 of 4 read",
        "– W",
    ]  # was "GPU power, undefined of 4 read"


@needs_node
def test_the_chart_of_a_link_names_no_peak_that_was_not_read():
    """The two directions of a link in the panel of a part, with their peak in the head. A link that carried nothing
    for half an hour read "peak 1.0 Gb/s", and so did one without any reading: the scale began at 1, and the head
    took its figure from the scale."""
    links = "[...liveSeries.keys()].filter(key => /\\.(tx|rx)$/.test(key))"  # the traces of every direction of a link
    heads = (  # the head of every chart of traffic in the panel: its word and what it says of its peak
        "document.querySelector('#panel').under().filter(e => e.matches('div.chart'))"
        ".map(c => c.children[0].under().map(e => e.text)).filter(head => head[1].startsWith('Traffic to '))"
        ".map(head => head[head.length - 1])"
    )
    got = sheet(
        [
            f"for (const key of {links}) liveSeries.get(key).v.fill(0); null",
            "setView('node', S.nodes[1].name); setPart('cx7'); null",
            heads,
            f"for (const key of {links}) liveSeries.delete(key); paintPanel(); null",
            heads,
        ]
    )
    assert got[2] == ["peak 0.0 Gb/s", "peak 0.0 Gb/s"], got[2]  # the two links of a Spark in the ring
    assert got[4] == ["no reading", "no reading"], got[4]


@needs_node
def test_the_panel_of_a_part_says_none_of_the_link_counters_only_where_they_were_read():
    """The panels of the network card and of the ports list the error and pause counters of the links that moved in
    the last 15 s, and say "None." where none did. They said so too where nobody read the counters (before the
    first slow reading of a Spark, and once these readings stopped coming) and at every moment of the past, where
    the counters are not kept: none moved, for all anybody knows. A reading nobody has is said as that."""
    then = json.loads(moments())["past"]["t"]
    said = (
        "(() => { const w = document.querySelector('#panel').under().map(e => e.text).filter(Boolean),"
        " i = w.findIndex(x => x.startsWith('Counters that moved')); return w.slice(i + 1, i + 2); })()"
    )
    links = (
        "server.say({{ ...LIVE, t: LIVE.t + {at}, nodes: LIVE.nodes.map(n => ({{ ...n, links: {links} }})) }}); null"
    )
    got = sheet(
        [
            "setView('node', S.nodes[1].name); setPart('cx7'); null",
            links.format(at=2, links="{ rocep1s0f0: { tx_pause_ctrl_phy: 0 } }"),
            said,
            links.format(at=4, links="null"),
            f"[{said}, (setPart('qsfp_cage'), {said})]",
            f"setPart(null); Time.toggle(true); Time.go({then[len(then) // 2]}); null",
            f"[(setPart('cx7'), {said}), (setPart('qsfp_cage'), {said})]",
        ]
    )
    assert got[2] == ["None."], got[2]  # read, and none of them moved
    assert got[4] == [["Not read."], ["Not read."]], got[4]  # was "None." on both panels
    assert got[6] == [["Not recorded."], ["Not recorded."]], got[6]  # looking back they are not kept: was "None."


@needs_node
def test_every_figure_of_a_tile_follows_the_pointer_on_its_trace_the_clock_too():
    """A pointer on the trace of a tile reads the Spark at that moment: power, temperature, memory and traffic showed
    the reading of then, the clock went on showing the one of now beside them, although it is recorded like the
    others."""
    clock = "tiles.get(S.nodes[1].name).clock.text"
    got = sheet(
        [
            "liveSeries.set(S.nodes[1].name + '.mhz', { t: [S.t - 600, S.t], v: [1000, 2000] }); null",
            f"setHover(S.t - 600); renderDockValues(); {clock}",
            f"setHover(S.t - 1200); renderDockValues(); {clock}",
            f"setHover(null); renderDockValues(); [{clock}, (S.nodes[1].mhz / 1000).toFixed(2) + ' GHz']",
        ]
    )
    assert got[1] == "1.00 GHz", got[1]  # the reading under the pointer
    assert got[2] == "–", got[2]  # no reading within half a minute of the pointer
    assert got[3][0] == got[3][1], got[3]  # without a pointer the newest one


# The history answers with forty readings of the fans and of the two temperatures of every Spark, two seconds
# apart up to the moment on the page. The second Spark turns its fans at 2,000 RPM for ten of them, the others at
# 2,600 and a little more; it is as warm as they are.
def cooling(slow="k >= 10 && k < 20", before=0):
    """The step that gives the cooling view its stretch and the checks their tools. `slow`: the columns in which the
    second Spark turns its fans at 2,000 RPM, as a piece of script about k. `before`: the seconds the last column
    begins before the moment on the page, as the columns of a real stretch do."""
    return COOLING_STEP.replace("SLOW", slow).replace("BEFORE", str(before))


COOLING_STEP = """
{ const t = [...Array(40).keys()].map(k => S.t - BEFORE - 2 * (39 - k)), series = {};
  S.cluster.nodes.forEach((c, j) => { series[c.name + '.fan'] = t.map((_, k) => j === 1 && (SLOW) ? 2000 : 2600 + j);
    series[c.name + '.gpu_c'] = t.map(() => 60 + j); series[c.name + '.cpu_c'] = t.map(() => 55); });
  server.historyAnswers({ t, tier: 'raw', width: 2, series, peak: series, low: series, n: Object.fromEntries(Object.keys(series).map(key => [key, t.map(() => 1)])), events: [] }); }
globalThis.panel = document.querySelector('#panel');
globalThis.plots = () => panel.under().filter(e => e.matches('svg.plot') && !/axis/.test(e.getAttribute('class')));
globalThis.said = cls => panel.under().filter(e => e.classList.contains(cls)).map(e => e.under().map(x => x.text).join(''));
globalThis.earlier = () => panel.under().filter(e => e.matches('ul.sp-earlier')).flatMap(u => u.under().filter(e => e.matches('button')));
globalThis.drawn = (plot, cls) => plot.under().filter(e => e.getAttribute('class') === cls).map(e => e.getAttribute('d') || e.children.length);
globalThis.info = () => panel.under().find(e => e.classList.contains('q-info'));
globalThis.box = () => panel.under().find(e => e.classList.contains('q-pop'));
globalThis.para = title => { const all = box().children, i = all.findIndex(e => e.tagName === 'H4' && e.text === title); return i < 0 ? null : all[i + 1].text; };
globalThis.explained = title => { info().fire('click', {}); const text = para(title); info().fire('click', {}); return text; };
globalThis.strip = () => { const s = panel.under().find(e => e.classList.contains('q-strip')); return s.hidden ? 'hidden' : [s.under().find(e => e.tagName === 'P').text, ...s.under().filter(e => e.matches('button') && !e.hidden).map(e => e.text)]; };
null
"""
COOLING = cooling()


@needs_node
def test_cooling_shows_fans_and_warmth_of_every_spark_over_a_stretch_on_one_board():
    """The cooling view showed one moment: who is slow now. That the fans of a Spark ran slow for hours last night
    was not to be found there. It stands on a board like the sheet of a Spark: the fans and the warmest sensor of
    every Spark as curves over a stretch anybody can pick, the line of the rule on every curve of fans, a foot where
    they ran slower than the others, that stretch in words with the time it held, and one cursor on all of them.
    The picture of fan speed against warmth follows the cursor and the marks. Leaving the view leaves nothing of it
    on the panel. Since the calm form the sentences about the stretch and the picture wait in the box of
    the bar, and the words of the marks on its strip."""
    picture = "explained('Fan speed vs. warmest sensor')"
    got = sheet(
        [
            COOLING,
            "setView('cooling'); null",
            "[panel.classList.contains('record'), panel.classList.contains('calm'), panel.classList.contains('narrow'), plots().length, explained('Time range')]",
            "earlier().map(b => [b.under().map(x => x.text).filter(Boolean), b.title])",
            "[drawn(plots()[1], 'limit')[0] !== '', drawn(plots()[1], 'held')[0], drawn(plots()[0], 'held')[0], said('ch-val').slice(0, 2), said('ch-stat')[1]]",
            picture,
            f"panel.fire('pointermove', {{ target: plots()[1], clientX: 1050, button: 0, buttons: 0 }}); [said('ch-val')[1], {picture}]",
            f"panel.fire('pointerleave', {{}}); earlier()[0].fire('click', {{}}); [strip(), {picture}, said('ch-stat')[1], panel.classList.contains('figures')]",
            "panel.under().find(e => e.matches('button') && e.text === '2 d').fire('click', {}); null",
            "explained('Time range')",
            "setView('why'); [...['record', 'calm', 'narrow', 'figures'].map(c => panel.classList.contains(c)), plots().length, said('grid3').length]",
        ]
    )
    record, calm, narrow, count, stretch = got[2]
    assert record and calm and narrow and count == 8, got[2]  # the fans and the warmest sensor of four Sparks
    assert (
        " to now (24 h)" in stretch and "every reading, 2 s apart" in stretch and "ecording begins 15 Jan, " in stretch
    ), stretch
    assert len(got[3]) == 1, got[3]
    words, tip = got[3][0]
    assert words[0] == "dgx1 23 % slower" and words[1].startswith("20 s, "), words
    assert tip.startswith("dgx1: fans at 2,000 against 2,602 RPM, 23 % slower for 20 s, within "), tip
    line, foot, none, values, figures = got[4]
    assert line and foot == 1 and none == 0, got[
        4
    ]  # the line of the rule on the curve, a foot only under the slow Spark
    assert values[0].endswith("RPM") and values[1].endswith("RPM") and "now" not in "".join(values), values
    assert figures == "mean2,451min2,000max2,601readings40", figures
    assert got[5].startswith("Large dots: one per Spark, live reading") and "0 RPM" in got[5], got[5]
    for said in (
        got[5],
        got[6][1],
        got[7][1],
    ):  # each of the three says what its amber dots are, between the two kinds of dot
        assert said.count("Amber:") == 1 and said.index("Large dots:") < said.index("Amber:") < said.index(
            "Small dots:"
        ), said
    assert "0 RPM" not in got[6][1] + got[7][1], got[6:8]  # a fan that stands still is only read now
    assert got[6][0].endswith("RPM") and got[6][1].startswith(
        "Large dots: one per Spark, reading at the cursor (15 Jan, "
    ), got[6]
    said, what, marked, figures = got[7]
    assert said[0].endswith(", 18 s") and " to " in said[0] and said[1:] == ["Zoom", "Clear"], said
    assert (
        what.startswith("Large dots: one per Spark, mean over the marked range") and "the marked range" in what[40:]
    ), what
    assert marked == "mean2,000min2,000max2,000readings10" and figures, (marked, figures)  # of the marked stretch alone
    assert (
        " to now (2 d)" in got[9] and "every reading, 2 s apart" in got[9] and "ecording begins 15 Jan, " in got[9]
    ), got[9]
    assert got[10] == [False, False, False, False, 0, 1], got[10]  # another view: the panel is a panel again


# What a browser does with a view transition, as far as the page can tell (CSS View Transitions): the change it is
# handed is made later, in a task of the browser. A transition a newer one overtakes, or one asked for in a hidden
# window, is skipped: its `ready` rejects, and its change is still made later. The first message is the one WebKit
# gives (seen in a probe: three changes of the view in one task); the second stands in for the one of a hidden
# window, which no probe has seen.
# `browserRuns` lets the browser make every change it still owes. One frame is drawn first: before the page has
# drawn, it fades nothing.
FADES = """
globalThis.owes = []; globalThis.fading = null;
document.startViewTransition = change => {
  const t = { finished: Promise.resolve(), updateCallbackDone: Promise.resolve() };
  t.ready = new Promise((_, no) => { t.skip = why => { fading = fading === t ? null : fading; no(new Error(why)); }; });
  owes.push(change);
  if (document.hidden) t.skip('View transition was skipped because document visibility state is hidden.');
  else { if (fading) fading.skip('Old view transition aborted by new view transition.'); fading = t; }
  return t;
};
globalThis.browserRuns = () => { for (const change of owes.splice(0)) change(); };
server.draw(1); null
"""


@needs_node
def test_a_fading_the_browser_skips_is_no_error_and_loses_no_change():
    """A change of the view, and a run that takes over, are faded over where the browser offers a view transition.
    The browser skips the fading when the next one comes before it is done, and in a window nobody sees: it then
    rejects, and nobody caught that (an unhandled rejection in the console, "Old view transition aborted by new
    view transition."). And it makes the change later, by itself: until then the page decided from the view it was
    leaving. Back to the view it had just left, asked for at once, was taken for no change, and the page ended on
    the view before; a run painted in between was painted over by the older one. A skipped fading is caught, and
    every change is made once and in the order it was asked for, whenever the browser gets to it. (`sheet` lets no
    error pass: the rejections fail this check by themselves.)"""
    head = "document.querySelector('#panel').children[0].text"
    run = "server.say({{ ...LIVE, t: LIVE.t + {at}, run: {{ source: 'queue', name: 'Another run', total: 10, done: {done}, started: LIVE.t - 60 }} }})"
    got = sheet(
        [
            FADES,
            f"setView('why'); setView('events'); browserRuns(); [V, {head}]",
            "setView('why'); setView('events'); browserRuns(); V",
            "document.hidden = true; setView('memory'); null",
            f"[V, (browserRuns(), V), {head}]",
            f"{run.format(at=2, done=1)}; {run.format(at=4, done=2)}; browserRuns(); document.querySelector('#run-count').text",
        ]
    )
    assert got[1] == ["events", "What happened"], got[1]  # one fading overtook the other: the last view stands
    assert got[2] == "events", got[2]  # was "why": back to the view it was leaving counted as no change
    assert got[4] == ["memory", "memory", "Memory on each Spark"], got[
        4
    ]  # hidden: made without waiting for the browser
    assert got[5] == "2 of 10", got[5]  # was "1 of 10": the older count, painted when the browser got to it


@needs_node
def test_the_answer_of_an_internal_case_says_so_in_the_table_of_answers():
    """A private add-on may mark an answer as one of an internal case. The table of the answers of the run says
    "internal" before the number of that case, in the words of the rest of the page."""
    answers = "[{ id: 3, intern: true, reply: 'a' }, { id: 4, reply: 'b' }]"
    got = sheet(
        [
            "(asked => { globalThis.fetch = u => u === 'api/replies' ? Promise.resolve({ ok: true, json: async () => "
            + answers
            + " }) : asked(u); })(fetch); Nerd.toggle(true); Nerd.tab('requests'); null",
            "server.texts().filter(t => /^intern/.test(t))",
        ]
    )
    assert got[1] == ["internal 3"], got[1]
