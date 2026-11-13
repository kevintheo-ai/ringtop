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


def test_each_cable_names_the_moment_its_counters_were_asked_for():
    """What ethtool counts of a cable becomes rates in the hub, every 15 s. The cables are read one after the other,
    each with two calls of ethtool, after the NVML fields: each row names the moment its counters were asked for."""
    namespace, clock, asked = sampler_namespace(), [1000.0], {}
    nets = {"/sys/class/infiniband/rocep1s0f0": "enp1s0f0np0", "/sys/class/infiniband/rocep1s0f1": "enp1s0f1np1"}

    def ethtool(command, **_):
        if command[1] == "-S":
            asked[command[2]] = clock[0]
        clock[0] += 0.25  # each call of ethtool takes its time
        return types.SimpleNamespace(stdout="     tx_bytes_phy: 900\n" if command[1] == "-S" else "")

    def find(pattern):
        if pattern == "/sys/class/infiniband/*":
            return sorted(nets)
        device = pattern[: -len("/device/net/*")]
        return [device + "/device/net/" + nets[device]]

    namespace["subprocess"] = types.SimpleNamespace(run=ethtool)
    namespace["glob"] = types.SimpleNamespace(glob=find)
    namespace["time"] = types.SimpleNamespace(time=lambda: clock[0])
    rows = namespace["cable_counters"]()
    stamps = (rows["f0"]["t"], rows["f1"]["t"])
    assert stamps == (asked["enp1s0f0np0"], asked["enp1s0f1np1"]) == (1000.0, 1000.5), (rows, asked)
    assert rows["f1"]["tx_bytes_phy"] == 900, rows
