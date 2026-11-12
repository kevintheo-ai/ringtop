"""The sampler's readers of the ring links in detail: the RDMA counters of every port."""

import json
import types

from tests.fixtures import sampler_namespace


def test_an_rdma_tool_that_failed_is_no_ring_without_devices():
    """The link counters come from one call of `rdma`. A call that ended with an error printed nothing, and nothing
    was read as an empty list: no devices, which the hub takes for "no counter moved". A call that failed is None;
    one that worked and lists no device is an empty reading."""
    namespace = sampler_namespace()

    def rdma(code, text):
        done = types.SimpleNamespace(returncode=code, stdout=text, stderr="")
        namespace["subprocess"] = types.SimpleNamespace(run=lambda *a, **k: done)
        return namespace["link_detail"]()

    rows = [{"ifname": "rocep1s0f0", "port": 1, "out_of_sequence": 3, "np_cnp_sent": 0, "state": "x"}, {"port": 2}]
    assert rdma(0, json.dumps(rows)) == {"rocep1s0f0": {"out_of_sequence": 3, "np_cnp_sent": 0}}
    assert rdma(0, "[]") == {}  # it answered: there is no device
    assert rdma(1, "") is None  # was {}
    assert rdma(1, json.dumps(rows)) is None  # what a call that failed printed is no reading
