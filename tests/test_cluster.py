"""What the node map and a run source say: the shape of the cluster, the run and its tracks."""

import json

from ringtop_parts.core.cluster import clean_tracks, parse_cluster, parse_runs, port_group
from tests.fixtures import hub_for, ring_map


def test_cluster_reads_ring_from_node_map():
    cluster = parse_cluster(ring_map(two_rails=True))
    assert cluster["ring"] and cluster["user"] == "user"
    assert cluster["nodes"][0]["peers"] == {"f0": 1, "f1": 3}
    assert cluster["nodes"][3]["peers"] == {"f0": 0, "f1": 2}


def test_switched_map_has_no_ring():
    node_map = {
        "ssh_user": "user",
        "nodes": [
            {"name": "dgx1", "rank": 0, "head": True, "roce_hcas": ["a"]},
            {"name": "dgx2", "rank": 1, "head": False, "roce_hcas": ["a"]},
        ],
    }
    assert parse_cluster(node_map)["ring"] is False


def test_hostile_names_are_refused():
    for bad in ("-oProxyCommand=x", "a b", "a;b", "$(x)"):
        try:
            parse_cluster({"ssh_user": "u", "nodes": [{"name": bad, "rank": 0}]})
        except SystemExit:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_both_rails_of_one_port_share_a_link():
    assert port_group("rocep1s0f0") == port_group("roceP2p1s0f0") == "f0"
    assert port_group("rocep1s0f1") == "f1"


def test_run_command_output():
    assert parse_runs('{"name":"x","done":1}')["done"] == 1
    assert parse_runs('[{"name":"a"},{"name":"b"}]')["name"] == "a"
    assert parse_runs("[]") is None
    try:
        parse_runs('{"done":1}')
    except ValueError:
        return
    raise AssertionError("accepted a run without a name")


def test_a_start_time_that_is_no_number_does_not_reach_the_hub():
    """The Hub counts with the moment a run started. A run source that names it as text would end every view of
    the page with an error, and the ticker with it: what is no number is left out, the run itself stays."""
    for odd in ('"yesterday"', "null", "[1]", '{"at": 5}', "NaN", "1" + "0" * 400):  # the last: no float holds it
        run = parse_runs('{"name":"job","started":' + odd + ',"detail":"x"}')
        assert run == {"name": "job", "detail": "x"}, (odd, run)
    assert parse_runs('{"name":"job","started":1762770000.5}')["started"] == 1762770000.5
    hub = hub_for()
    with hub.lock:
        hub.external_run = parse_runs('{"name":"job","started":"yesterday"}')
    assert hub.view()["run"]["name"] == "job"


def test_a_count_that_is_no_number_does_not_reach_the_hub():
    """How far a run is and how much it has to do are counts the pages count with. A run source that named one as a
    text, a yes or a no, a list, a table or a number no float holds put it in the moment as it came: the main page
    said "NaN of 24" with a bar filled "NaN%", or "1 of 24" of a yes, and a NaN made the moment JSON no browser
    reads. What is no number is left out, as the start is: the pages say of it what they say of a count nobody
    read. A count that is a number passes, 0 too."""
    odds = ('"x"', '"6"', "true", "false", "null", "[3]", '{"n": 3}', "NaN", "Infinity", "-Infinity", "1" + "0" * 400)
    for key, other in (("done", '"total":24'), ("total", '"done":6')):
        for odd in odds:
            run = parse_runs('{"name":"job",' + other + f',"{key}":' + odd + ',"detail":"x"}')
            assert key not in run and len(run) == 3, (key, odd, run)
    assert parse_runs('{"name":"job","done":0,"total":24.5}') == {"name": "job", "done": 0, "total": 24.5}


HOSTILE = (  # a run source that prints numbers no browser reads, fields of the wrong kind and fields nobody knows
    '{"name":"Sweep","detail":NaN,"group":["Queue 9"],"holder":7,"until":Infinity,"started":-Infinity,'
    '"done":1e400,"total":24,"source":"none","extra":[NaN,{"deep":-1e400}],'
    '"steps":[{"name":"a","state":"done","seconds":NaN,"was":1e400},{"name":"b","state":"odd","seconds":5},"junk"],'
    '"tracks":[{"node":"dgx0","name":"job","done":NaN,"total":10,"started":Infinity}],'
    '"replies":[{"id":1,"seconds":NaN,"usage":{"prompt_tokens":Infinity,"completion_tokens":12},"reply":"ok",'
    '"n":[1e400,' + "1" + "0" * 400 + "]},"
    '"junk",7]}'
)


def test_whatever_a_run_source_prints_the_moment_stays_json_every_browser_reads():
    """What a run command prints goes into every moment, and its answers to /api/replies. Python reads NaN,
    Infinity and -Infinity in it as numbers, and 1e400 as an infinite one; written back, they made the moment JSON no
    browser reads, wherever they stood: in the time of a station, the detail, an answer, a field nobody knows. And a
    field of the wrong kind went on as it came: a list as the queue, a number as who holds the ring, a word for the
    source ("none" made the page say "Nothing running"). A number that is not finite, or that no float holds, is read
    as nobody read it, and a run keeps only the fields a run source may give, each in its kind. What the run source of
    a lab prints goes on as it came. A name that is no text is no name."""
    run = parse_runs(HOSTILE)
    json.dumps(run, allow_nan=False)
    assert run == {
        "name": "Sweep",
        "total": 24,
        "steps": [{"name": "a", "state": "done"}, {"name": "b", "seconds": 5}],
        "tracks": [{"node": "dgx0", "name": "job", "total": 10}],
        "replies": [
            {
                "id": 1,
                "seconds": None,
                "usage": {"prompt_tokens": None, "completion_tokens": 12},
                "reply": "ok",
                "n": [None, None],
            }
        ],
    }, run
    hub = hub_for()
    with hub.lock:
        hub.external_run = run
    moment = hub.view()
    json.dumps(moment, allow_nan=False)
    json.dumps(hub.replies(), allow_nan=False)
    assert moment["run"]["source"] == "command" and moment["run"]["has_replies"] is True, moment["run"]
    step = {"name": "Job C, round 1", "state": "done", "seconds": 480, "was": 455}
    lab = {  # every field the run source of a lab prints, for a queue and for single tracks
        "name": "Job A, round 1",
        "group": "Queue 6",
        "done": 12,
        "total": 40,
        "started": 1762770000.5,
        "steps": [step, {"name": "Job A, round 1", "state": "running"}],
        "holder": "Lab window",
        "until": "about 6 pm",
        "replies": [{"id": "c1", "finish": "stop", "seconds": 12.5, "reply": "ok", "usage": {"prompt_tokens": 900}}],
    }
    single = {
        "name": "Single tracks",
        "holder": "Lab window",
        "tracks": [{"node": "dgx0", "model": "m", "name": "Job", "done": 3, "total": 10, "started": 1.5}],
        "replies": [],
    }
    assert parse_runs(json.dumps(lab)) == lab and parse_runs(json.dumps(single)) == single
    for odd in ("NaN", '["Sweep"]', "7", '""', "null", "true", '{"name": "Sweep"}'):
        try:
            parse_runs('{"name":' + odd + "}")
        except ValueError:
            continue
        raise AssertionError(f"took {odd} as a name")


def test_tracks_of_a_run_source_reach_the_page_only_in_known_shapes():
    """What a command outside prints goes to the page: a track keeps its known fields in their known shapes, the rest
    (a path, a list where a name belongs, a text where a list belongs) stays here."""
    tracks = [
        {"node": "a", "name": "job", "done": 3, "total": 10, "started": 5.0, "file": "/private/path", "model": 7},
        "junk",
        {"node": ["a"]},
        {"done": True, "name": "x" * 500},
    ]
    run = parse_runs(json.dumps({"name": "x", "tracks": tracks}))
    assert run["tracks"] == [{"node": "a", "name": "job", "done": 3, "total": 10, "started": 5.0}, {"name": "x" * 120}]
    assert parse_runs('{"name":"x","tracks":"junk"}')["tracks"] == []
    assert "tracks" not in parse_runs('{"name":"x"}')
    assert len(clean_tracks([{"node": str(i)} for i in range(500)])) == 64


def refused(node_map) -> str:
    """The word a node map ringtop cannot show ends the start with. Anything but SystemExit is a traceback."""
    try:
        parse_cluster(node_map)
    except SystemExit as stop:
        assert isinstance(stop.code, str), stop.code
        return stop.code
    raise AssertionError(f"took {node_map!r}")


def test_a_node_map_ringtop_cannot_show_ends_the_start_with_a_word():
    """Two heads, more than sixteen Sparks, a rank twice, a node without a rank or with one that is text, a node
    without a name, a map that lists no nodes: each ends the start with a sentence that says so, never a traceback.
    A map that names no head goes through, so does one of sixteen; the one Spark of a map of one is its head."""
    two = ring_map()
    two["nodes"][2]["head"] = True
    assert refused(two) == "The node map names more than one head: dgx0, dgx2"
    many = {"nodes": [{"name": f"n{i}", "rank": i} for i in range(17)]}
    assert refused(many) == "The node map has 17 Sparks; ringtop shows at most 16"
    twice = ring_map()
    twice["nodes"][3]["rank"] = 1
    assert refused(twice) == "Rank 1 stands twice in the node map"
    for rank in ({}, {"rank": "two"}, {"rank": None}, {"rank": [1]}):
        assert refused({"nodes": [{"name": "dgx0", **rank}]}).startswith("Rank of 'dgx0' not usable"), rank
    assert refused({"nodes": [{"rank": 0}]}) == "Node name not usable as an SSH host: None"
    for odd in ({}, {"nodes": []}, {"nodes": "dgx0"}, {"nodes": ["dgx0"]}, [], "x"):
        assert refused(odd) == "The node map lists no nodes", odd
    headless = ring_map()
    for node in headless["nodes"]:
        node["head"] = False
    cluster = parse_cluster(headless)
    assert cluster["ring"] and not any(n["head"] for n in cluster["nodes"])
    assert len(parse_cluster({"nodes": [{"name": f"n{i}", "rank": i} for i in range(16)]})["nodes"]) == 16
    alone = parse_cluster({"nodes": [{"name": "dgx0", "rank": 0}]})
    assert alone["nodes"][0]["head"] and not alone["ring"]
    assert parse_cluster(ring_map(two_rails=True)) == parse_cluster(ring_map(two_rails=True))  # the test map passes


def test_ring_ports_a_head_or_a_rank_ringtop_cannot_read_end_the_start_with_a_word():
    """Ring ports whose peer is no rank, ports given as a list or a text, a list of devices that is none,
    a head given as text ("false" counted as a head), a rank with a fraction (1.5 was taken as 1): each ends the
    start with a sentence, never a traceback or a wrong reading. A ring of four with two rails reads as before."""
    for ports in ({"x": ["rocep1s0f0"]}, ["rocep1s0f0"], {"1": None}, {"1": "rocep1s0f0"}, {"1": [7]}):
        node = {"name": "dgx1", "rank": 1, "roce_peer_hcas": ports}
        assert refused({"nodes": [{"name": "dgx0", "rank": 0}, node]}).startswith("Ring ports of 'dgx1' not usable"), (
            ports
        )
    assert refused({"nodes": [{"name": "dgx0", "rank": 0, "head": "false"}]}) == "Head of 'dgx0' not usable: 'false'"
    assert refused({"nodes": [{"name": "dgx0", "rank": 1.5}]}) == "Rank of 'dgx0' not usable: 1.5"
    assert parse_cluster(ring_map(two_rails=True))["nodes"][0]["peers"] == {"f0": 1, "f1": 3}
    read = parse_cluster({"nodes": [{"name": "a", "rank": 0, "head": 1}, {"name": "b", "rank": 1.0, "head": 0}]})
    # read as they mean, in the kinds ringtop counts with: rank 1.0 as the whole number 1, head 1 and 0 as yes and no
    assert [repr((n["name"], n["rank"], n["head"])) for n in read["nodes"]] == ["('a', 0, True)", "('b', 1, False)"]


def test_a_peer_that_reads_as_a_digit_but_is_no_number_ends_the_start_with_a_word():
    """A peer such as "²" passed as a digit and then broke the reading of it into a number, a
    traceback. A peer is a whole number in decimal digits, so it ends the start with a sentence like any other."""
    node = {"name": "dgx1", "rank": 1, "roce_peer_hcas": {"²": ["rocep1s0f0"]}}
    assert refused({"nodes": [{"name": "dgx0", "rank": 0}, node]}).startswith("Ring ports of 'dgx1' not usable")


def test_a_whole_number_of_thousands_of_digits_is_none_where_it_stands_and_the_run_passes():
    """A number no float holds is None wherever it stands. One of more than 4300 digits was not read at all: Python
    refuses to turn so many digits into a number, and the whole answer of the run source failed, even where the
    number stood in a field that is dropped. It is None like any other, and the run passes; as the answer itself,
    or as the name of a run, it is still no run."""
    long = "1" * 5000
    run = parse_runs('{"name":"job","done":' + long + ',"total":9,"extra":[' + long + "]}")
    assert run == {"name": "job", "total": 9}, run
    for odd in (long, '{"name":' + long + "}", "[" + long + "]"):
        try:
            parse_runs(odd)
        except ValueError as problem:
            assert str(problem) == "needs an object with a name", (odd[:12], problem)
        else:
            raise AssertionError(f"took {odd[:12]}")


def test_a_rank_no_whole_number_can_hold_ends_the_start_with_a_word():
    """A rank of 1e999 reads as infinite, and turning it into a whole number broke with an OverflowError, a
    traceback. Like every rank that is no whole number, it ends the start with a sentence."""
    for rank in (float("inf"), float("-inf"), float("nan")):
        assert refused({"nodes": [{"name": "dgx0", "rank": rank}]}) == f"Rank of 'dgx0' not usable: {rank!r}", rank
