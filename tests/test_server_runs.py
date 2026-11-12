"""The web server: the records of runs at an address of their own."""

import json
import time

from tests.fixtures import demo_round, serving


def test_the_records_of_runs_are_read_at_an_address_of_their_own():
    """/api/runs gives the record of the run that is open and the records of the runs that ended, the newest first,
    to whoever may read the page and with the headers of every other answer. It is read off what the hub holds:
    asking builds no view, which would note events and count once more. The moment the page gets every tick does
    not carry them."""
    hub = demo_round(100, each=lambda hub: hub.view(), start=time.time() - 200)  # 200 s of the demo round
    hub.beat()
    assert "runs" not in json.loads(hub.payload)
    hub.view = None  # whoever asked the hub for a view from here on would fail
    with serving(hub) as ask:
        status, headers, body = ask("/api/runs")
        assert (status, headers["content-type"]) == (200, "application/json"), (status, headers)
        assert headers.get("cache-control") == "no-store" and headers.get("x-content-type-options") == "nosniff"
        assert headers.get("content-length") == str(len(body)), headers
        told = json.loads(body)
        assert told == json.loads(json.dumps(hub.runs_view())) and set(told) == {"open", "runs"}
        names = [record["name"] for record in told["runs"]]
        assert names == ["Prefill sweep", "Eight streams", "Long prompts", "Short prompts"], names
        assert told["open"]["name"] == "Stall probe" and told["open"]["open"] and not told["runs"][0]["open"]
        assert told["runs"][0]["tokens"] > 1000 and told["runs"][0]["gpu_wh"] > 1 and told["runs"][0]["gpu_from"] == 4
        assert [record["name"] for record in json.loads(ask("/api/runs?limit=2")[2])["runs"]] == names[:2]
        for odd in ("limit=x", "limit=-3", "limit=0", "limit=99999999999999999999", "limit=nan", "limit="):
            status, _, body = ask(f"/api/runs?{odd}")
            assert status == 200 and 1 <= len(json.loads(body)["runs"]) <= 4, (odd, status, body[:80])
        for path in ("/api/runs/", "/api/run", "/runs"):
            assert ask(path)[0] == 404, path
        status, headers, said = ask("/api/runs", host="evil.example")
        assert (status, headers["content-type"], said) == (403, "text/plain", b"Host not allowed\n"), (status, said)


def test_one_request_gets_no_more_records_than_the_hub_holds_in_memory():
    hub = demo_round(4)
    with hub.lock:
        for n in range(260):
            hub.runs.append({"id": n, "name": f"Job {n}", "open": False})
    with serving(hub) as ask:
        told = json.loads(ask("/api/runs?limit=100000")[2])
        assert len(told["runs"]) == 200 and told["runs"][0]["id"] == 259 and told["open"] is None  # the newest 200
        assert len(json.loads(ask("/api/runs")[2])["runs"]) == 50  # unless asked otherwise
