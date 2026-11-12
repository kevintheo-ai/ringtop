"""The run the hub holds open while something is missing: a Spark that fell silent, ringtop away from the run, a
source that cannot be heard. What nobody counted is said as a gap, whatever a restart of ringtop forgets."""

import tempfile
from pathlib import Path

from ringtop_parts.store import Store
from tests.fixtures import engine_sample
from tests.test_hub_runs import Clock, stored_hub


def look(hub, clock, start, second, sparks, job, error=None, startless=False, engine=True):
    """One interval of a ring of which the Sparks named are read: a sample of each with 36 W of GPU power (the
    head's with the count of the engine, unless the engine is to stay unread), what the run command says (a run
    by its name, with its start unless it is to give none; no run; or why it failed), and the look of the ticker."""
    clock.now = start + second
    for name in sparks:
        read = engine and name == "dgx0"
        head = engine_sample(start + second, 1000.0 + 20 * second) if read else {"t": start + second}
        hub.ingest(name, {**head, "fabric": {}, "gpu": {"w": 36.0}})
    hub.external_run = job and {"name": job, **({} if startless else {"started": start})}
    hub.external_error = error
    hub.view()


def test_a_spark_that_fell_silent_before_ringtop_was_away_is_a_gap_from_its_last_sample_on():
    """A Spark that stops sending in an open run is said as a gap when it comes back or when the run ends: from
    its last sample on, which only the memory of ringtop knew. A restart forgot it. Back on the run, ringtop
    counted the time since the last save as the gap of every Spark it had read, and the 40 s between the last
    sample of that Spark and the save were in no sum and in no gap: the card named a share that was too high, and
    the record stood like that for 90 days. The row the history gets says such a gap at every save, as an end of
    the run would, so read and gap add up to the run whether ringtop was away or not."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 62, 2):  # dgx1 sends its last sample at 20 s
            look(hub, clock, start, second, ("dgx0", "dgx1") if second <= 20 else ("dgx0",), "Job 1")
        held = hub.runs_view()["open"]
        assert (held["saved"], held["gpu_from"]) == (start + 60, 2), held
        assert (held["gpu_read_s"], held["gpu_gap_s"]) == (80.0, 0.0), held  # in memory dgx1 may still come back
        hub.store.flush()  # ringtop stops here
        row = Store(path, 2.0).saved_runs(5)[0]
        assert (row["gpu_read_s"], row["gpu_gap_s"]) == (80.0, 40.0), row  # the history: unread since 20 s; was 0
        clock.now = start + 79
        back = stored_hub(path)
        for second in range(80, 100, 2):  # back on the run after 20 s; dgx1 never answers again
            look(back, clock, start, second, ("dgx0",), "Job 1")
        look(back, clock, start, 100, ("dgx0",), "Job 2")
        ended = back.runs_view()["runs"][0]
        assert (ended["ended"], ended["gpu_from"], ended["gpu_read_s"]) == (start + 100, 2, 100.0), ended
        # dgx1 from its last sample to the end: 80 s. dgx0 while ringtop was away: 20 s. Two Sparks never read: 200 s
        assert ended["gpu_gap_s"] == 300.0, ended  # was 260: the 40 s were missing
        assert ended["gpu_read_s"] + ended["gpu_gap_s"] == 4 * 100.0
        back.store.flush()
        assert Store(path, 2.0).saved_runs(5)[1] == ended  # the end has said every gap: its row adds nothing to it


def test_the_open_record_is_saved_every_minute_while_its_source_cannot_be_heard():
    """A run stays while its source cannot be heard, and its record counts on. It was written to the history only
    at a look where the source named the run: a run command that failed for ten minutes left the row ten minutes
    old, and a restart of ringtop in that time lost ten minutes of counting, said as a gap, where a minute at most
    is the rule. The open record is written once a minute for as long as nobody said its run ended, whether its
    source is heard or not. When the source last named the run stays what it was. A record the history handed
    over is not written again before its source names the run: its row says when its sums were last written,
    and from then on nobody counted."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub, written = stored_hub(path), set()
        for second in range(0, 62, 2):
            look(hub, clock, start, second, ("dgx0",), "Job 1")
        for second in range(62, 662, 2):  # the run command fails for ten minutes
            look(hub, clock, start, second, ("dgx0",), None, "Command timed out after 10 seconds")
            written.add(hub.run_open["saved"])
        assert sorted(written) == [start + second for second in range(60, 661, 60)], written  # each minute, no other
        held = hub.runs_view()["open"]
        assert (held["last_heard"], held["saved"]) == (start + 60, start + 660), held  # was last saved at 60 s
        hub.store.flush()  # ringtop stops here
        row = Store(path, 2.0).saved_runs(5)[0]
        assert (row["open"], row["last_heard"], row["saved"]) == (True, start + 60, start + 660), row
        assert (row["tokens"], row["token_s"], row["gpu_read_s"]) == (13200.0, 660.0, 660.0), row
        clock.now = start + 669
        back = stored_hub(path)
        for second in range(670, 732, 2):  # ringtop is back, and the command fails for a minute more
            look(back, clock, start, second, ("dgx0",), None, "Command timed out after 10 seconds")
        assert back.runs_view()["open"]["saved"] == start + 660  # the row is left as it is
        for second in range(732, 744, 2):  # the command answers again and names the run
            look(back, clock, start, second, ("dgx0",), "Job 1")
        on = back.runs_view()["open"]
        assert (on["id"], on["counted_from"]) == (held["id"], start + 732), on
        assert (on["token_gap_s"], on["gpu_gap_s"]) == (72.0, 72.0), on  # the 72 s nobody counted; was 672 s
        assert (on["tokens"], on["token_s"], on["gpu_read_s"]) == (13400.0, 670.0, 670.0), on


def test_the_open_record_is_not_saved_while_its_source_names_no_run_and_that_is_not_believed_yet():
    """A source that names no run is believed after half a minute, and the run then ended when it first said so:
    what was counted after that moment is not of the run. Until it is believed the record is not written, so the
    history never holds sums from after an end. The end itself is written, with the sums of its moment."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 118, 2):
            look(hub, clock, start, second, ("dgx0",), "Job 1")
        for second in range(118, 148, 2):  # the command answers and names no run, from 118 s on
            look(hub, clock, start, second, ("dgx0",), None)
        held = hub.runs_view()["open"]
        assert (held["quiet"], held["saved"], held["tokens"]) == (start + 118, start + 60, 2920.0), held
        hub.store.flush()
        assert Store(path, 2.0).saved_runs(5)[0]["tokens"] == 1200.0  # the row is the one of 60 s
        look(hub, clock, start, 148, ("dgx0",), None)  # half a minute: believed
        hub.store.flush()
        ended = Store(path, 2.0).saved_runs(5)[0]
        assert (ended["open"], ended["ended"], ended["tokens"]) == (False, start + 118, 2360.0), ended


def test_a_run_nobody_saw_end_says_a_spark_never_read_for_as_long_as_its_sums_reach():
    """The record of a run nobody saw end is closed as it was last saved. A Spark never read in that run is counted
    as not read by the card, up to the moment the source last named the run: that was as far as a row reached
    while a save needed the source. A row written while the source could not be heard reaches further, by the
    time the run stayed and was counted unheard. For that time the hub says the Spark as a gap when it closes the
    record, so the share of the card is over all the sums cover: three of four Sparks read are three quarters.
    A run with a start is closed once its source names no run; one without a start where ringtop starts."""
    for startless in (False, True):
        with tempfile.TemporaryDirectory() as folder, Clock() as clock:
            path, start = Path(folder) / "history.db", clock.now
            hub, three = stored_hub(path), ("dgx0", "dgx1", "dgx2")
            for second in range(0, 62, 2):
                look(hub, clock, start, second, three, "Job 1", startless=startless)
            for second in range(62, 182, 2):  # the run command fails for two minutes: the run stays and is counted
                look(hub, clock, start, second, three, None, "exit 1")
            hub.store.flush()  # ringtop stops here, on its save of 180 s
            clock.now = start + 199
            back = stored_hub(path)
            for second in (200, 210, 220, 230):  # the command answers and names no run: gone, and nobody saw when
                look(back, clock, start, second, (), None)
            gone = back.runs_view()["runs"][0]
            assert (gone["open"], gone["ended"], gone["last_heard"]) == (False, None, start + 60), gone
            # three Sparks read for 180 s each; the fourth unread for the 120 s the source was not heard: was 0
            assert (gone["gpu_from"], gone["gpu_read_s"], gone["gpu_gap_s"]) == (3, 540.0, 120.0), (startless, gone)
            never = (gone["sparks"] - gone["gpu_from"]) * (gone["last_heard"] - gone["first_seen"])  # the card: 60 s
            assert gone["gpu_read_s"] / (gone["gpu_read_s"] + gone["gpu_gap_s"] + never) == 0.75
            back.store.flush()
            assert Store(path, 2.0).saved_runs(5)[0] == gone


def test_an_engine_nobody_read_after_ringtop_came_back_is_a_gap_of_the_tokens_to_the_end():
    """The tokens of a run have a gap at its end where the engine was last read long before it. That gap hung on
    the last reading the tokens were counted to, and a restart of ringtop forgets it. An engine that was read
    before ringtop was away and never answered again had the time from the moment ringtop was back to the end of
    the run in no count and in no gap: a run of 330 s told 180 s counted and 46 s of gap, and its card said
    "Counted over 79 %" where 54 % were true. That time is a gap, as it is for a Spark read before and never
    since."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 198, 2):
            look(hub, clock, start, second, ("dgx0",), "Job 1")
        hub.store.flush()  # ringtop stops here; its last write was at 180 s
        clock.now = start + 225
        back = stored_hub(path)
        for second in range(226, 330, 2):  # back at 226 s: the head is read, the ring engine never again
            look(back, clock, start, second, ("dgx0",), "Job 1", engine=False)
        look(back, clock, start, 330, ("dgx0",), "Job 2", engine=False)
        ended = back.runs_view()["runs"][0]
        assert (ended["ended"], ended["tokens"], ended["lives"]) == (start + 330, 3600.0, 1), ended
        # counted to the write of 180 s; ringtop away from there to 226 s: 46 s; unread from 226 s to the end: 104 s
        assert (ended["token_s"], ended["token_gap_s"]) == (180.0, 150.0), ended  # the gap was 46
        assert ended["token_s"] + ended["token_gap_s"] == 330.0


def test_an_engine_first_read_after_ringtop_was_away_has_all_the_time_before_as_a_gap():
    """An engine that is first read late in a run has the time before that reading as a gap of the tokens. The gap
    was counted from the moment the sums count on, which a restart of ringtop moves: an engine that was still
    loading when ringtop was restarted, and answered 14 s after ringtop was back, told 90 s counted and no gap at
    all in a run of 330 s, and the card said nothing of a part. Of an engine never read before, ringtop counted
    nothing while it was away and nothing before: the gap of its first reading reaches back to the moment the run
    was first seen, with ringtop away in between or not."""
    for away in (False, True):
        with tempfile.TemporaryDirectory() as folder, Clock() as clock:
            path, start = Path(folder) / "history.db", clock.now
            hub = stored_hub(path)
            for second in range(0, 198, 2):  # the engine does not answer yet
                look(hub, clock, start, second, ("dgx0",), "Job 1", engine=False)
            if away:
                hub.store.flush()  # ringtop stops here, and is back at 226 s
                clock.now = start + 225
                hub = stored_hub(path)
            for second in range(226 if away else 198, 330, 2):  # the engine answers from 240 s on
                look(hub, clock, start, second, ("dgx0",), "Job 1", engine=second >= 240)
            look(hub, clock, start, 330, ("dgx0",), "Job 2")
            ended = hub.runs_view()["runs"][0]
            assert (ended["tokens"], ended["lives"]) == (1800.0, 1), (away, ended)
            assert (ended["token_s"], ended["token_gap_s"]) == (90.0, 240.0), (away, ended)  # with ringtop away: was 0


def test_a_spark_first_read_after_ringtop_was_away_has_all_the_time_before_as_a_gap():
    """A Spark that is first read late in a run has the time before its first sample as a gap. After a restart of
    ringtop that gap reached back only to the moment the sums count on. The time ringtop was away is added for the
    Sparks that had been read before, and the end says a whole run only for the Sparks never read at all: a Spark
    first read after the restart had the time before in no sum and in no gap. Four Sparks, 200 s, one of them
    silent for the first 80 s, ringtop away from 62 to 80 s: 660 s read, 60 s of gap, 80 Spark-seconds told
    nowhere, and the card said "91 %" where 82 % were true. What ringtop knows of the time before is the row of
    its last save: a Spark first read after that save is first read after the restart. The record counts Sparks,
    not names: one Spark more than were ever read in the run was unread from the first sight of the run on."""
    three, four = ("dgx0", "dgx2", "dgx3"), ("dgx0", "dgx1", "dgx2", "dgx3")
    told = {}
    for late, away in ((80, (62, 80)), (12, (48, 56)), (80, None), (12, (62, 80))):
        with tempfile.TemporaryDirectory() as folder, Clock() as clock:
            path, start = Path(folder) / "history.db", clock.now
            hub = stored_hub(path)
            for second in range(0, 200, 2):  # dgx1 sends its first sample at `late`; ringtop is away in `away`
                if away and second == away[0]:
                    hub.store.flush()
                    clock.now = start + away[1] - 1
                    hub = stored_hub(path)
                if not away or not away[0] <= second < away[1]:
                    look(hub, clock, start, second, four if second >= late else three, "Job 1")
            look(hub, clock, start, 200, four, "Job 2")
            ended = hub.runs_view()["runs"][0]
            told[late, away] = (ended["gpu_from"], ended["gpu_read_s"], ended["gpu_gap_s"])
            assert ended["gpu_read_s"] + ended["gpu_gap_s"] == 4 * 200.0, (late, away, ended)
    # away with the last write at 60 s: three Sparks for the 20 s away, and dgx1 for the 80 s before: was 60
    assert told[80, (62, 80)] == (4, 660.0, 140.0), told
    # away with the last write at 0 s, where dgx1 was not read yet: three Sparks for 56 s, and dgx1 for 56 s: was 168
    assert told[12, (48, 56)] == (4, 576.0, 224.0), told
    # as before: never away, the late Spark has its 80 s; read before the write of 60 s, it is one of the four
    assert (told[80, None], told[12, (62, 80)]) == ((4, 720.0, 80.0), (4, 720.0, 80.0)), told


def test_a_run_lost_after_its_source_named_no_run_holds_nothing_from_after_that_word():
    """The source of a run names no run, and before the half minute is over it cannot be heard any more. ringtop
    is restarted in that silence, and the run is never named again. Nobody saw it end, but the hub had heard the
    word, and what is counted after it is not of the run if the word was true. For a while the record was written
    on through such a silence: the run was then closed with whatever the engine and the Sparks did until the
    restart, an hour of a run and two hours of silence as 215,000 tokens and 430 Wh where 72,000 and 144 were
    the run, with no mark of a part. While the word stands, believed or not, the record is not written. A run
    lost like this is closed from the row before the word: too little by a minute at most, and nothing from
    after its end."""
    four = ("dgx0", "dgx1", "dgx2", "dgx3")
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 400, 2):  # named for 100 s, "no run" for 10 s, then the command fails for 290 s
            job, error = ("Job 1", None) if second < 100 else (None, None) if second < 110 else (None, "exit 1")
            look(hub, clock, start, second, four, job, error)
        counting = hub.runs_view()["open"]
        assert (counting["quiet"], counting["tokens"]) == (start + 100, 7960.0), counting  # in memory it counts on
        hub.store.flush()  # ringtop stops here, in the silence
        clock.now = start + 419
        back = stored_hub(path)
        for second in range(420, 460, 2):  # back, and the command answers: no run. Gone, and nobody saw when
            look(back, clock, start, second, four, None)
        gone = back.runs_view()["runs"][0]
        assert (gone["open"], gone["ended"], gone["saved"] > start + 400) == (False, None, True), gone
        # the row of 60 s, the last before the word. Was the row of 360 s: 7,200 tokens and 1,440 Spark-seconds
        assert (gone["tokens"], gone["token_s"], gone["gpu_read_s"]) == (1200.0, 60.0, 240.0), gone
        assert gone["token_s"] <= 100.0 and gone["gpu_read_s"] <= 4 * 100.0  # nothing from after the word


def test_the_open_record_is_not_saved_while_a_source_that_named_no_run_cannot_be_heard():
    """A source that names no run is believed once it has said so for half a minute, and until then the record is
    not written. A source that says so for ten seconds and then cannot be heard is believed nothing for as long
    as that lasts: the run stays, and counts on in memory. Its record is not written in that time either: the
    word may have been the end of the run, and the history holds no sums from after an end (the check above).
    The price is known and taken. Is the run named again after a restart of ringtop in that silence, the time
    since the last row is lost and said as a gap: 350 s here, where a minute is the rule. The figures are right.
    Is the source heard again and still names no run, the run ended when it first said so, with the sums of that
    moment."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub, written = stored_hub(path), set()
        for second in range(0, 70, 2):
            look(hub, clock, start, second, ("dgx0",), "Job 1")
        for second in range(70, 80, 2):  # the command answers and names no run, for 10 s
            look(hub, clock, start, second, ("dgx0",), None)
        for second in range(80, 400, 2):  # then it fails, for 320 s
            look(hub, clock, start, second, ("dgx0",), None, "exit 1")
            written.add(hub.run_open["saved"])
        assert written == {start + 60}, written  # nothing is written while the word stands
        held = hub.runs_view()["open"]
        assert (held["quiet"], held["last_heard"], held["tokens"]) == (start + 70, start + 68, 7960.0), held
        hub.store.flush()  # ringtop stops here
        row = Store(path, 2.0).saved_runs(5)[0]
        assert (row["open"], row["saved"], row["tokens"], row["token_s"]) == (True, start + 60, 1200.0, 60.0), row
        clock.now = start + 409
        back = stored_hub(path)
        for second in range(410, 420, 2):  # ringtop is back, and the command names the run again
            look(back, clock, start, second, ("dgx0",), "Job 1")
        on = back.runs_view()["open"]
        assert (on["id"], on["token_gap_s"], on["gpu_gap_s"]) == (held["id"], 350.0, 350.0), on  # lost, and said
        assert (on["tokens"], on["token_s"], on["gpu_read_s"]) == (1360.0, 68.0, 68.0), on
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        for second in range(0, 200, 2):  # as above, with the command failing for 120 s
            job, error = ("Job 1", None) if second < 70 else (None, None) if second < 80 else (None, "exit 1")
            look(hub, clock, start, second, ("dgx0",), job, error)
        assert hub.run_open["saved"] == start + 60
        look(hub, clock, start, 200, ("dgx0",), None)  # it answers again and names no run: said since 70 s
        ended = hub.runs_view()["runs"][0]
        assert (ended["ended"], ended["tokens"], ended["token_s"]) == (start + 70, 1400.0, 70.0), ended
        hub.store.flush()
        assert Store(path, 2.0).saved_runs(5)[0] == ended


def test_the_row_of_a_save_says_a_gap_past_the_silence_of_the_hub_and_none_within_it():
    """The row of an open run says what was unread before the save by the rules of an end, and with the silence
    of the hub: 15 s at this interval. A Spark last read 20 s before the save is unread in the row from its last
    sample on, and so is the engine; a Spark last read 10 s before it is not, as at an end. With no silence at
    all the row would call a gap what one beat explains, and with a longer one it would say nothing here."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub = stored_hub(path)
        assert hub.silence == 15.0
        for second in range(0, 62, 2):  # dgx2 and the engine are read to 40 s, dgx1 to 50 s, the head to the save
            sparks = ("dgx0", "dgx1", "dgx2") if second <= 40 else ("dgx0", "dgx1") if second <= 50 else ("dgx0",)
            look(hub, clock, start, second, sparks, "Job 1", engine=second <= 40)
        hub.store.flush()
        row = Store(path, 2.0).saved_runs(5)[0]
        assert (row["saved"], row["gpu_read_s"], row["token_s"]) == (start + 60, 150.0, 40.0), row
        assert (row["gpu_gap_s"], row["token_gap_s"]) == (20.0, 20.0), row  # dgx2 and the engine; not dgx1's 10 s


def test_the_row_of_a_look_holds_what_the_source_said_at_that_look():
    """The record goes by the last word of its source before it is written: the row of a save holds how far the
    run is and when it was last named as of the look of that save, and from the first row on which model runs on
    which image. Written before the word of the look is taken in, a row would be one look behind, and the first
    one would name no model."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start, rows = Path(folder) / "history.db", clock.now, {}
        hub = stored_hub(path)
        model = {"models": {"data": [{"id": "model-a"}]}, "container": {"image": "image:1", "status": "running"}}
        hub.ingest("dgx0", {"t": start, "info": model})
        for second in range(0, 62, 2):  # the run command counts the run on with every look
            clock.now = start + second
            hub.external_run = {"name": "Job 1", "started": start, "done": second // 2, "total": 100}
            hub.view()
            if second in (0, 60):  # the two looks the record is written at
                hub.store.flush()
                rows[second] = Store(path, 2.0).saved_runs(5)[0]
        first, minute = rows[0], rows[60]
        assert (first["saved"], first["last_heard"], first["done"]) == (start, start, 0), first
        assert (first["model"], first["image"]) == ("model-a", "image:1"), first
        assert (minute["saved"], minute["last_heard"], minute["done"]) == (start + 60, start + 60, 30), minute


def test_a_run_taken_up_again_is_written_at_that_moment_and_adds_up_when_it_is_lost_right_after():
    """Back on a run, ringtop writes its record at once: the row then reaches to that moment, with the time
    ringtop was away as a gap of the Sparks that had been read. Is ringtop stopped again before the next write
    and the run gone when it returns, the record is closed from that row. A Spark never read in the run is unread
    for all the row reaches, counted partly by the hub where it closes the record and partly by the card: three
    of four Sparks read for 60 s of 80 s are 180 of 320 Spark-seconds, whoever counts which part."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub, three = stored_hub(path), ("dgx0", "dgx1", "dgx2")
        for second in range(0, 70, 2):
            look(hub, clock, start, second, three, "Job 1")
        hub.store.flush()  # ringtop stops here; its last write was at 60 s
        clock.now = start + 79
        back = stored_hub(path)
        for second in range(80, 90, 2):  # back at 80 s, and the run is named: taken up
            look(back, clock, start, second, three, "Job 1")
        back.store.flush()  # and stops again, before the write of the next minute
        row = Store(path, 2.0).saved_runs(5)[0]
        assert (row["saved"], row["counted_from"], row["open"]) == (start + 80, start + 80, True), row
        assert (row["gpu_read_s"], row["gpu_gap_s"], row["token_s"], row["token_gap_s"]) == (180.0, 60.0, 60.0, 20.0), (
            row
        )
        clock.now = start + 99
        last = stored_hub(path)
        for second in (100, 110, 120, 130):  # the command answers and names no run: gone, and nobody saw when
            look(last, clock, start, second, (), None)
        gone = last.runs_view()["runs"][0]
        assert (gone["open"], gone["ended"], gone["gpu_from"], gone["gpu_read_s"]) == (False, None, 3, 180.0), gone
        never = (gone["sparks"] - gone["gpu_from"]) * (gone["last_heard"] - gone["first_seen"])  # what the card adds
        assert gone["gpu_read_s"] + gone["gpu_gap_s"] + never == 4 * 80.0, (gone, never)
        assert gone["gpu_read_s"] / (gone["gpu_read_s"] + gone["gpu_gap_s"] + never) == 0.5625


def test_a_clock_set_back_over_a_restart_takes_nothing_off_a_run_that_is_lost_after_it():
    """Where the hub closes a run nobody saw end, it says the Sparks never read as a gap for the time from the
    moment the source last named the run to the last write of the record. With the clock set back while ringtop
    was away, the row written when the run is taken up lies before that moment: the time between is less than
    nothing. Nothing is taken off the gap for it, and nothing is added. The Spark never read stays unread for as
    long as the other three were read, which the card counts up to the moment the source last named the run:
    three quarters. By the clock that was set back that is 14 s more than the row reaches, for the Spark never
    read as for the seconds the three were read: what a clock set back covers twice is not known from inside,
    and no figure is made smaller for it."""
    with tempfile.TemporaryDirectory() as folder, Clock() as clock:
        path, start = Path(folder) / "history.db", clock.now
        hub, three = stored_hub(path), ("dgx0", "dgx1", "dgx2")
        for second in range(0, 62, 2):
            look(hub, clock, start, second, three, "Job 1", engine=False)
        hub.store.flush()  # ringtop stops here, on its write of 60 s
        clock.now = start + 45
        back = stored_hub(path)
        for second in range(46, 56, 2):  # back with the clock at 46 s, 14 s before that write: the run is taken up
            look(back, clock, start, second, three, "Job 1", engine=False)
        back.store.flush()  # and stops again, before the next write
        row = Store(path, 2.0).saved_runs(5)[0]
        assert (row["saved"], row["gpu_read_s"], row["gpu_gap_s"]) == (start + 46, 180.0, 0.0), row
        assert row["last_heard"] - row["saved"] == 14.0  # the row lies before the moment its source last named the run
        clock.now = start + 69
        last = stored_hub(path)
        for second in (70, 80, 90, 100):  # the command answers and names no run: gone, and nobody saw when
            look(last, clock, start, second, (), None)
        gone = last.runs_view()["runs"][0]
        assert (gone["open"], gone["ended"], gone["gpu_from"]) == (False, None, 3), gone
        assert (gone["gpu_read_s"], gone["gpu_gap_s"]) == (180.0, 0.0), gone  # not -14, and not 14
        never = (gone["sparks"] - gone["gpu_from"]) * (gone["last_heard"] - gone["first_seen"])  # what the card adds
        assert (never, gone["gpu_read_s"] / (gone["gpu_read_s"] + gone["gpu_gap_s"] + never)) == (60.0, 0.75)
