"""The file that keeps what the phone was told: one that cannot be read is broken and ends nothing, one that
cannot be written is said once and tried again, and the spare written beside it takes no name of another."""

import contextlib
import io
import json
import os
import tempfile
import threading
import types
from pathlib import Path

from ringtop_parts.connect.notify import read_kept, watch, write_kept
from tests.catcher import CANARY
from tests.test_start_notify import GONE, phone, stand_ins


def taken(*call):
    return None, False


def watched(file, moments=1, last=None):
    """watch on a stand-in hub that gives `moments` moments in which every Spark is away, then ends: what it
    said. Every message is taken. `last` is called before the last moment is given."""
    payloads, ticks = [json.dumps(GONE).encode()] * moments, iter(range(1, 1000))

    def wait_tick(seen, timeout=15.0):
        if not payloads:
            raise SystemExit
        if last and len(payloads) == 1:
            last()
        return payloads.pop(0), next(ticks)

    out, hub, asked = io.StringIO(), types.SimpleNamespace(wait_tick=wait_tick), phone("/bin/cat /x/topic", keep=file)
    with contextlib.ExitStack() as stack:
        stack.enter_context(stand_ins(topic_from=lambda command: CANARY, send=taken))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(out))
        stack.enter_context(contextlib.suppress(SystemExit))
        watch(hub, asked)
    return out.getvalue()


def test_a_file_too_deep_too_big_or_of_no_text_is_broken_and_the_thread_goes_on():
    """Whatever stands in the file: the start goes on from nothing, into its loop, and keeps anew."""
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "alerts.json"
        for broken in (
            b"[" * 30_000,  # deeper than json can go (RecursionError), and small enough to be read
            b'{"told": ["away"], "sent": [], "hushed": false}' + b" " * 70_000,  # more than any kept file holds
            b"\xff\xfe" + b'{"told": []}',  # no UTF-8
            b'{"sent": [1e999, -1e999, NaN, Infinity]}',
        ):
            file.write_bytes(broken)
            said = watched(file)
            assert said.splitlines() == ["ringtop: phone messages: on", "notified: away on"], (broken[:20], said)
            assert json.loads(file.read_text())["told"] == ["away"], broken[:20]
        assert read_kept(Path("/dev/zero")) is None and read_kept(Path(folder)) is None  # no file, or no end of one
        pipe, read = Path(folder) / "pipe", []
        os.mkfifo(pipe)  # opening it would wait for a writer that never comes
        reader = threading.Thread(target=lambda: read.append(read_kept(pipe)), daemon=True)
        reader.start()
        reader.join(5)
        hung = reader.is_alive()  # it opened the pipe and waits: the writer below would hide that
        if hung:
            with open(pipe, "w"):  # lets the reader go, so that no thread is left behind
                pass
        assert not hung and read == [None], (hung, read)


def test_a_file_that_cannot_be_written_is_said_once_by_its_kind_and_tried_again():
    """The folder takes no file: that is said once, by the kind of the failure and without the path, and every
    change is tried again; once the folder takes it, it is written, in the same run and not only
    in a new one."""
    with tempfile.TemporaryDirectory() as folder:
        shut = Path(folder) / "shut"
        shut.mkdir()
        file = shut / "alerts.json"
        os.chmod(shut, 0o500)
        try:
            said = watched(file, moments=5, last=lambda: os.chmod(shut, 0o700))
        finally:
            os.chmod(shut, 0o700)
        assert said.splitlines() == [
            "ringtop: phone messages: on",
            "notified: away on",
            "ringtop: phone messages: what the phone was told is not kept (PermissionError), tried again",
        ], said
        assert folder not in said and [path.name for path in shut.iterdir()] == ["alerts.json"]  # and no spare
        assert json.loads(file.read_text())["told"] == ["away"]
        file.unlink()
        said = watched(file)
        assert "not kept" not in said and json.loads(file.read_text())["told"] == ["away"]


def test_the_spare_file_takes_no_name_of_another_and_is_not_left_behind():
    """It is written beside the file under a name nobody else has, then put in its place; where that fails,
    it is gone again. A file that is itself called .tmp is kept like any other."""
    value = {"told": ["fan"], "sent": [1.0], "hushed": False}
    with tempfile.TemporaryDirectory() as folder:
        place = Path(folder)
        (place / "alerts.tmp").write_text("not ringtop's")
        assert write_kept(place / "alerts.json", value) is None
        assert (place / "alerts.tmp").read_text() == "not ringtop's" and json.loads(
            (place / "alerts.json").read_text()
        ) == value
        assert write_kept(place / "kept.tmp", value) is None and json.loads((place / "kept.tmp").read_text()) == value
        (place / "a-folder").mkdir()
        before = sorted(path.name for path in place.iterdir())
        assert write_kept(place / "a-folder", value) in ("IsADirectoryError", "OSError", "PermissionError")
        assert sorted(path.name for path in place.iterdir()) == before  # no spare left beside it
        assert write_kept(None, value) is None


def test_a_kept_file_in_a_folder_nobody_may_look_into_is_no_file_and_the_thread_reaches_its_loop():
    """Under a folder without the right to look into it, asking whether the file is one threw
    PermissionError before the reading that catches everything, and the thread of the phone ended before its
    loop. Such a file cannot be read: the start goes on from nothing, and what cannot be kept is said."""
    with tempfile.TemporaryDirectory() as folder:
        locked = Path(folder) / "locked"
        locked.mkdir()
        os.chmod(locked, 0o600)
        try:
            assert read_kept(locked / "alerts.json") is None
            said = watched(locked / "alerts.json")
        finally:
            os.chmod(locked, 0o700)
        assert said.splitlines() == [
            "ringtop: phone messages: on",
            "notified: away on",
            "ringtop: phone messages: what the phone was told is not kept (PermissionError), tried again",
        ], said
