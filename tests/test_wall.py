"""The moment for a wall: a fixed list of fields, nothing unread made a number, and no word beside the list."""

import copy
import json
import shutil
import time

from ringtop_parts.core.figures import UNCOUNTED
from ringtop_parts.core.wall import wall_moment
from tests.fixtures import hub_for, needs_node, page_faces
from tests.test_prom import played

# Everything a wall may get of a moment, written out here once more and on purpose: a field added to the list of the
# server shows as a failure of this check, and is then a decision, not a slip.
TOP = {"t", "cluster", "identity", "engine", "nodes", "run", "why"}
IDENTITY = {"interval", "memguard_gib"}  # not the model: no script of the calm page reads it
ENGINE = {"state", "word", "tok_s", "running", "waiting", "error", "answers"}
SPARK = {
    "name",
    "rank",
    "head",
    "live",
    "latched",
    "mhz",
    "throttle",
    "gpu_c",
    "tlimit",
    "util",
    "mem_free_gb",
    "mem_total_gb",
    "fan",
    "fans",
    "w",
    "own",
}
OWN = {"model", "state", "error", "tok_s", "running", "waiting", "ttft_p95"}
RUN = {"source", "name", "done", "total", "started"}
SECRET = "KEEP-THIS-OFF-THE-WALL"


def test_a_wall_gets_these_fields_of_a_moment_and_no_other():
    """Four moments of the demo (its first tick, the ring engine writing, a Spark away, every Spark serving alone),
    each as a wall gets it: every part holds fields of its list only, each with the value the whole moment has."""
    for word, whole in played().items():
        wall = wall_moment(whole)
        assert set(wall) == TOP, (word, set(wall))
        assert wall["t"] == whole["t"] and wall["cluster"] == whole["cluster"], word
        assert set(wall["cluster"]) == {"ring", "nodes"}, word
        assert all(set(place) == {"name", "rank", "head"} for place in wall["cluster"]["nodes"]), word
        assert set(wall["identity"]) == IDENTITY, (word, set(wall["identity"]))
        assert set(wall["engine"]) <= ENGINE and "state" in wall["engine"], (word, set(wall["engine"]))
        assert set(wall["run"]) <= RUN and "source" in wall["run"], (word, set(wall["run"]))
        assert set(wall["why"]) <= {"own"}, (word, set(wall["why"]))
        assert len(wall["nodes"]) == len(whole["nodes"]) == 4, word
        for spark, node in zip(wall["nodes"], whole["nodes"]):
            assert set(spark) <= SPARK and {"name", "rank", "head", "live", "own"} <= set(spark), (word, set(spark))
            assert all(spark[key] == node[key] for key in spark if key != "own"), (word, spark["name"])
            assert spark["own"] is None or set(spark["own"]) <= OWN, (word, spark["own"])
        for part in ("identity", "engine", "run"):
            assert all(wall[part][key] == whole[part][key] for key in wall[part]), (word, part)
    writing, alone = wall_moment(played()["writing"]), wall_moment(played()["alone"])
    assert set(writing["engine"]) == {"state", "tok_s", "running", "waiting"} and writing["engine"]["tok_s"] > 100
    assert set(writing["run"]) == RUN and writing["why"] == {}, writing["run"]
    assert set(writing["nodes"][0]) == SPARK, set(writing["nodes"][0])  # every listed reading, in the full moment
    assert alone["engine"] == {"state": "offline", "error": "Nothing answers on the vLLM port."}, alone["engine"]
    assert alone["nodes"][1]["own"]["state"] == "writing" and alone["why"]["own"], alone["why"]


def planted(whole):
    """A moment with the word a wall must never get in every place the list leaves out: why a Spark is away, its
    container, programs and threads, the events, the links, kernel and profile, what a run source wrote beside the
    name of its run, and a field nobody has thought of yet in every part."""
    moment = copy.deepcopy(whole)
    moment.update(events=[{"t": 1, "kind": "kernel", "text": SECRET}], edges=[{"group": SECRET}], history={SECRET: 1})
    moment["later"] = SECRET
    moment["cluster"].update(later=SECRET)
    moment["cluster"]["nodes"][0].update(peers={SECRET: 1}, later=SECRET)
    moment["identity"].update(kernel=SECRET, config=SECRET, image=SECRET, vllm=SECRET, container=SECRET, later=SECRET)
    moment["identity"].update(model=SECRET)  # what the head serves: free text, and nothing on a wall shows it
    moment["engine"].update(health=SECRET, timing={"queue": SECRET}, later=SECRET)
    moment["run"].update(detail=SECRET, holder=SECRET, until=SECRET, group=SECRET, later=SECRET)
    moment["run"].update(steps=[{"name": SECRET}], tracks=[{"name": SECRET, "node": SECRET}], has_replies=SECRET)
    moment["why"].update(headline=SECRET, points=[{"text": SECRET}], later=SECRET)
    for node in moment["nodes"]:
        node.update(reason=SECRET, box={"name": SECRET, "model": SECRET}, top=[{"name": SECRET}], later=SECRET)
        node.update(threads=[SECRET], key_threads=[SECRET], intruders=[SECRET], apps=[{"name": SECRET}])
        node.update(cooling=[{"type": SECRET}], zones={SECRET: 1}, startup={"args": SECRET}, links=[SECRET])
        node["own"] = {**(node.get("own") or {"state": "idle"}), "name": SECRET, "later": SECRET}
    return moment


def test_no_word_beside_the_list_reaches_a_wall():
    """The word is planted wherever the list leaves a field out, in each of the four moments, and in fields of
    every part that do not exist yet. The whole moment carries it dozens of times; what a wall gets, as the text
    the server sends, never does: the list says what passes, so what is new stays in."""
    for word, whole in played().items():
        moment = planted(whole)
        assert json.dumps(moment).count(SECRET) > 40, word
        sent = json.dumps(wall_moment(moment))
        assert SECRET not in sent, (word, sent[max(0, sent.find(SECRET) - 80) : sent.find(SECRET) + 40])
    away = played()["away"]
    assert "ssh: connect to host" in json.dumps(away)  # the last words of ssh, as the demo plays them
    assert "ssh" not in json.dumps(wall_moment(away))


def test_of_what_the_sparks_work_on_alone_a_wall_gets_only_what_stands_under_the_name_of_a_spark():
    """What each Spark works on by itself reaches a wall as the hub writes it: a text under the name of the Spark.
    The list asked whether it is a text and not what it stands under, so a text somebody puts beside the Sparks
    later went to a wall with them: the one place where a field added to a moment did not stay in. Only what
    stands under the name of a Spark of this moment passes, as the page reads it: by the name of each Spark."""
    moment = copy.deepcopy(played()["alone"])
    own = dict(moment["why"]["own"])
    assert len(own) == 4 and set(own) == {node["name"] for node in moment["nodes"]}, own
    moment["why"]["own"].update({"debug_token": SECRET, SECRET: "a program", "": SECRET, "dgx9": SECRET})
    wall = wall_moment(moment)
    assert wall["why"] == {"own": own} and SECRET not in json.dumps(wall), wall["why"]
    moment["nodes"][2]["name"] = ["dgx2"]  # a name that is no text names no Spark on a wall
    assert wall_moment(moment)["why"] == {"own": {name: own[name] for name in ("dgx0", "dgx1", "dgx3")}}
    assert wall_moment({"why": {"own": {"a": "prog"}}}) == {"why": {"own": {}}}  # no Spark listed: no name passes
    assert wall_moment({"nodes": [{"rank": 1}], "why": {"own": {"a": "prog"}}})["why"] == {"own": {}}


def test_a_reading_nobody_took_stays_none_on_a_wall_and_never_becomes_a_zero():
    """A Spark that is away has no reading: on a wall its figures are None as in the whole moment, never 0, and it is
    not live. A count the engine did not send is None too, and a field a part does not have is not made up."""
    whole = played()["away"]
    gone = wall_moment(whole)["nodes"][-1]
    assert gone["live"] is False and gone["own"] is None, gone
    for key in ("gpu_c", "fan", "fans", "mem_free_gb", "w", "util", "mhz", "tlimit", "throttle", "latched"):
        assert key in gone and gone[key] is None, (key, gone.get(key))
    assert gone["mem_total_gb"] == whole["nodes"][-1]["mem_total_gb"] > 100  # what a Spark is stands while it is away
    unread = copy.deepcopy(played()["writing"])
    unread["engine"].update(running=None, waiting=None, tok_s=None)
    unread["nodes"][0]["own"] = {"model": "m", "state": "writing", "tok_s": None, "running": None}
    wall = wall_moment(unread)
    assert wall["engine"] == {"state": "writing", "tok_s": None, "running": None, "waiting": None}, wall["engine"]
    assert wall["nodes"][0]["own"] == {"model": "m", "state": "writing", "tok_s": None, "running": None}
    assert wall_moment({**unread, "run": {"source": "none"}})["run"] == {"source": "none"}  # no count made up


def test_a_fan_nobody_read_keeps_its_place_on_a_wall():
    """The fans of a Spark come as a list, each fan in its place, and one that was not read is None there. A wall
    gets the list place by place: a list without the place would say of the second fan what was read of the
    first, and nobody could tell a Spark with one fan from one whose other fan was not read. The check of the
    kinds held the place only for what is no number; None that comes as None was in no check of a wall."""
    moment = copy.deepcopy(played()["writing"])
    for fans in ([None, 3120], [3120, None], [None, None], [0, None], [0, 3120, None], [None], []):
        moment["nodes"][1]["fans"] = fans
        wall = wall_moment(moment)
        assert wall["nodes"][1]["fans"] == fans, (fans, wall["nodes"][1]["fans"])
        assert moment["nodes"][1]["fans"] is fans and wall["nodes"][1]["fans"] is not fans  # a list of its own
    moment["nodes"][1]["fans"] = [None, 3120]
    assert '"fans":[null,3120]' in json.dumps(wall_moment(moment), separators=(",", ":"))  # as the stream sends it


def test_a_wall_hears_that_a_ring_engine_nobody_can_read_does_answer():
    """A ring engine that answers without the counts of its requests is given as one nobody can read, with the word
    that it answers (`answers`). The calm page needs that word: without it the line under the core says "the ring
    engine does not answer" of one that does. No moment of the demo carries it, so the field could fall off the
    list of a wall and every check stayed green. What a hub says of such an engine reaches a wall whole, the word
    as the flag it is; and while Sparks work on their own, the page says of the wall moment what it says of the
    whole one."""
    hub, now = hub_for(), time.time()
    bare = {"generation_tokens_total": 1000.0, "kv_cache_usage_perc": 0.2}
    hub.scrapes.append((now - 10, bare, {}))
    hub.scrapes.append((now, bare, {}))
    engine = hub.view()["engine"]
    assert engine == {"state": "offline", "error": UNCOUNTED, "answers": True}, engine
    alone = {**copy.deepcopy(played()["alone"]), "engine": engine}
    for node in alone["nodes"]:
        node["own"] = None  # no engine of a Spark answers: the core speaks of the ring engine
    wall = wall_moment(alone)
    assert wall["engine"] == engine, wall["engine"]
    kinds = [wall_moment({"engine": {"answers": said}})["engine"]["answers"] for said in (False, "yes", 1)]
    assert kinds == [False, None, None], kinds
    if shutil.which("node"):
        said = "(state => { S = state; return coreFace(state.engine).sub; })"
        subs = page_faces(f"return {json.dumps([alone, wall])}.map({said});")
        assert subs == ["the ring engine answers without its request counters, 4 Sparks work on their own"] * 2, subs


def test_the_moment_a_wall_is_made_from_is_not_changed():
    for word, whole in played().items():
        before = copy.deepcopy(whole)
        wall_moment(whole)
        assert whole == before, word


def test_a_moment_that_holds_nothing_gives_a_wall_nothing():
    """A hub starts with a moment that holds nothing, and a part may be missing or no table of fields: a wall gets
    what is there and on the list, and nothing throws."""
    assert wall_moment({}) == {}
    odd = {"t": 5.0, "cluster": None, "identity": [], "engine": "writing", "nodes": None, "run": 7, "why": None}
    assert wall_moment(odd) == {"t": 5.0}, wall_moment(odd)
    bare = {"nodes": [{"name": "a", "live": False}, "no Spark", None], "why": {"own": {"a": "prog", "b": 3}}}
    assert wall_moment(bare) == {"nodes": [{"name": "a", "live": False, "own": None}], "why": {"own": {"a": "prog"}}}


def test_a_field_of_a_wall_moment_is_of_the_kind_its_list_says():
    """The list says which fields pass; what stands in a field is another matter. A run source writes the name and
    the counts of its run as it likes, and a moment hands them on as they came. A table in the place of the name
    would carry anything through a listed field. A count that is no number (not-a-number, a number without end, a
    whole number of 400 digits) would reach the page as something nobody can count with, or make the stream a text
    no browser reads as JSON. So on a wall a number is a finite number and no flag (figures.num), a text is a text,
    a flag is a flag, and a list holds only what is of its kind: anything else is None, as if it was not read."""
    moment = copy.deepcopy(played()["writing"])
    moment["run"].update(name={"inside": SECRET}, done=10**400, total=float("nan"), started="soon " + SECRET)
    moment["engine"].update(state=["writing", SECRET], tok_s=float("inf"), running=True, error={"why": SECRET})
    moment["identity"].update(model=[SECRET], interval="2")
    moment["cluster"].update(ring="yes")
    moment["cluster"]["nodes"][0].update(rank="0", head=1)
    first, second = moment["nodes"][:2]
    first.update(name={"n": SECRET}, live="yes", gpu_c="hot " + SECRET, fan=float("-inf"), mem_free_gb=[SECRET])
    first.update(fans=[0, "x", float("nan"), 3100, True], throttle=["thermal", {"x": SECRET}, 5], latched=0)
    first["own"] = {"model": {"m": SECRET}, "state": 5, "error": [SECRET], "tok_s": 10**400, "running": "2"}
    second.update(fans="both", throttle="thermal")
    moment["why"]["own"] = {"dgx1": {"deep": SECRET}, "dgx2": "a program"}
    moment["t"] = float("nan")
    wall = wall_moment(moment)
    sent = json.dumps(wall, allow_nan=False)  # strict JSON: neither NaN nor Infinity stands in it
    assert SECRET not in sent and len(sent) < 2500, sent[:300]
    assert wall["t"] is None and wall["cluster"]["ring"] is None, (wall["t"], wall["cluster"]["ring"])
    assert wall["cluster"]["nodes"][0] == {"name": "dgx0", "rank": None, "head": None}
    assert wall["run"] == {"source": "command", "name": None, "done": None, "total": None, "started": None}
    assert wall["engine"] == {"state": None, "tok_s": None, "running": None, "waiting": 0.0, "error": None}
    assert wall["identity"] == {"interval": None, "memguard_gib": None}, wall["identity"]
    spark = wall["nodes"][0]
    assert [spark[key] for key in ("name", "live", "gpu_c", "fan", "mem_free_gb", "latched")] == [None] * 6, spark
    assert spark["fans"] == [0, None, None, 3100, None] and spark["throttle"] == ["thermal"], spark
    assert spark["own"] == {"model": None, "state": None, "error": None, "tok_s": None, "running": None}
    assert wall["nodes"][1]["fans"] is None and wall["nodes"][1]["throttle"] is None, wall["nodes"][1]
    assert wall["nodes"][2] == wall_moment(played()["writing"])["nodes"][2]  # what is of its kind passes as it came
    assert wall["why"] == {"own": {"dgx2": "a program"}}, wall["why"]


@needs_node
def test_the_page_says_of_a_wall_moment_what_it_says_of_the_whole_one():
    """The faces and the rules of the page are asked with the whole moment and with what a wall gets of it, while
    the ring engine writes, while a Spark is away and while every Spark serves alone: the core, the line of every
    Spark, the line of the run and the GPU power read the same. One thing differs, and is meant to: a Spark that is
    away says that it is unreachable, without the last words of ssh."""
    script = (
        "const say = state => { S = state; return { core: coreFace(state.engine),"
        " notes: state.nodes.map(n => nodeNote(n, state.identity)), run: runTime(state.run, state.t),"
        " power: readSum(state.nodes, 'w'), tracks: (t => t && { ...t, rows: t.rows.map(r => [r.name, r.kind]) })(tracksOf(state)) }; };"
        " return MOMENTS.map(([whole, wall]) => [say(whole), say(wall)]);"
    )
    pairs = [[whole, wall_moment(whole)] for whole in (played()[word] for word in ("writing", "away", "alone"))]
    (writing, wall_writing), (away, wall_away), (alone, wall_alone) = page_faces(
        f"const MOMENTS = {json.dumps(pairs)}; {script}"
    )
    assert writing == wall_writing and writing["core"]["word"] == "Writing" and writing["power"]["read"] == 4
    assert alone == wall_alone and alone["core"]["word"] == "Single tracks" and alone["tracks"]["writing"] == 3
    assert away["notes"][-1]["text"].startswith("Unreachable: ssh: connect to host"), away["notes"][-1]
    assert wall_away["notes"][-1] == {"cls": "bad", "text": "Unreachable"}, wall_away["notes"][-1]
    assert {**away, "notes": away["notes"][:-1]} == {**wall_away, "notes": wall_away["notes"][:-1]}
    assert away["power"] == {**away["power"], "read": 3, "of": 4}, away["power"]
