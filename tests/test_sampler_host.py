"""The sampler's fast readers of /proc and /sys: CPU, disk, sensors and the ring ports. What a reader could not read
is None in what it sends, never a zero and never left out."""

import glob
import os
import tempfile
import types

from tests.fixtures import hub_for, sampler_namespace, slow_files


def made_up_files(namespace, files):
    """Stands in for the files a reader opens: `files` maps a path to its text, and a path it does not hold cannot
    be read. Gives the mapping back, so a check can change a file between two readings."""
    namespace["read"] = lambda path: files.get(path)
    return files


def test_a_file_the_node_could_not_read_is_no_reading_of_zero():
    """/proc/stat could not be read once. The load of the CPUs then counted on from "cpu 0 0 0 0", a made-up line
    of zeros: no figure that time, and against the next real reading the load since the machine booted, sent as
    the load since the last sample. The cores came as an empty list, which says there are none. Both are None,
    and the reading after it has nothing to count from: no figure across the hole."""
    namespace = sampler_namespace()
    files = made_up_files(namespace, {})

    def stat(busy, idle):
        files["/proc/stat"] = f"cpu {busy} 0 0 {idle} 0 0 0 0\ncpu0 {busy} 0 0 {idle} 0 0 0 0"
        return namespace["cpu_percent"](), namespace["cores"]()

    assert stat(200, 800) == (None, [None])  # the first look: nothing to count from yet
    assert stat(250, 850) == (50.0, [50])
    del files["/proc/stat"]
    assert (namespace["cpu_percent"](), namespace["cores"]()) == (None, None)  # the cores were []
    assert stat(9100, 1900) == (None, [None])  # was (82.7, [89]): the busy share since boot, and a mean over the hole
    assert stat(9150, 1950) == (50.0, [50])


def test_a_node_without_an_nvme_drive_counts_no_sectors():
    """The disk rate is counted from the sectors of the NVMe drives in /proc/diskstats. A machine without such a
    drive, or a list that could not be read, sent 0 sectors read and 0 written: two samples of that are 0.0 MB/s,
    measured, on the tile and in the curve. No drive is no count of zero: the sectors are None, and the hub
    makes no rate of them. The space of the root file system is read as before."""
    namespace = sampler_namespace()
    drive = " 259 0 nvme0n1 10 0 4000 0 20 0 800 0 0 0 0\n 259 1 nvme0n1p1 1 0 8 0 1 0 8 0 0 0 0\n"
    other = "   8 0 sda 5 0 999 0 5 0 999 0 0 0 0\n"
    files = made_up_files(namespace, {"/proc/diskstats": drive + other})
    read = namespace["disk"]()
    assert (read["read"], read["write"]) == (4000, 800) and read["total"] >= read["free"] > 0, read
    files["/proc/diskstats"] = other
    none = namespace["disk"]()
    assert (none["read"], none["write"]) == (None, None) and none["total"] == read["total"], none  # was (0, 0)
    del files["/proc/diskstats"]
    assert (namespace["disk"]()["read"], namespace["disk"]()["write"]) == (None, None)  # not read: was (0, 0)
    hub = hub_for()
    for t in (100.0, 102.0):
        hub.ingest("dgx0", {"t": t, "fabric": {}, "disk": namespace["disk"]()})
    node = hub.nodes["dgx0"]
    assert node["disk_read"] is None and node["disk_write"] is None, node  # was 0.0 MB/s each
    assert not hub.history["dgx0.disk_read"] and node["disk_free_gb"] is not None


def test_a_fan_that_was_not_read_keeps_its_place():
    """The fans of a Spark come as a list, in the order of their hwmon folders. A fan whose speed could not be
    read was left out of it, and the fan after it stood in its place: the hub, the page and the list for
    Prometheus then took the second fan for the first. It stays in its place, as None. A fan that reads 0 is a
    reading: it stands still."""
    namespace = sampler_namespace()
    namespace["glob"] = types.SimpleNamespace(glob=lambda pattern: [f"/sys/class/hwmon/hwmon{i}" for i in (3, 1, 2)])
    hwmon = "/sys/class/hwmon/hwmon"
    files = made_up_files(
        namespace,
        {
            hwmon + "1/name": "acpi_fan",
            hwmon + "1/fan1_input": "2600",
            hwmon + "2/name": "acpi_fan",
            hwmon + "2/fan1_input": "2700",
            hwmon + "3/name": "nvme",
            hwmon + "3/temp1_input": "61800",
        },
    )
    whole = namespace["sensors"]()
    assert whole["fans"] == [2600, 2700] and whole["nvme_c"] == 61.8, whole
    del files[hwmon + "1/fan1_input"]
    assert namespace["sensors"]()["fans"] == [None, 2700]  # was [2700]: the second fan in the place of the first
    files[hwmon + "1/fan1_input"], files[hwmon + "2/fan1_input"] = "0", "no number"
    assert namespace["sensors"]()["fans"] == [0, None]  # was [0]
    hub = hub_for()
    hub.ingest("dgx0", {"t": 100.0, "fabric": {}, "sensors": namespace["sensors"]()})
    assert hub.nodes["dgx0"]["fans"] == [0, None] and hub.nodes["dgx0"]["fan"] == 0, hub.nodes["dgx0"]


def ring_port(folder, name, files):
    """A made-up RDMA device under `folder`, as /sys shows one: every file of its port 1 that `files` names. A text
    of None is a file that is there and cannot be read (a folder stands in its place)."""
    for path, text in files.items():
        full = os.path.join(folder, name, "ports", "1", path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if text is None:
            os.makedirs(full)
        else:
            with open(full, "w") as f:
                f.write(text + "\n")


def test_a_ring_port_is_named_with_what_was_read_of_it():
    """The sampler left a ring port out of its sample when it could not read one of its two traffic counters, read
    a state it could not read as "down", and counted an error counter it could not read as 0. The hub then saw
    a port that is gone, a link that went down, and a count of errors that fell and came back as new ones.
    Every port is named with what was read of it, and each field that was not read is None. A counter the device
    does not have (no such file) is no counter nobody read: it adds nothing, and a device without the counters
    of its traffic is left out, as before."""
    namespace = sampler_namespace()
    link, rdma = namespace["LINK_ERRORS"], namespace["RDMA_ERRORS"]
    whole = {"state": "4: ACTIVE", "rate": "200 Gb/sec (4X HDR)", "counters/port_xmit_data": "1000"}
    whole.update({"counters/port_rcv_data": "2000"}, **{"counters/" + c: "1" for c in link})
    whole.update({"hw_counters/" + c: "2" for c in rdma})
    less = {path: text for path, text in whole.items() if path not in ("state", "hw_counters/" + rdma[0])}
    with tempfile.TemporaryDirectory() as folder:
        namespace["glob"] = types.SimpleNamespace(glob=lambda pattern: glob.glob(os.path.join(folder, "*")))
        ring_port(folder, "rocep1s0f0", whole)
        ring_port(folder, "rocep1s0f1", {**whole, "counters/port_xmit_data": None, "rate": "no number"})
        ring_port(folder, "roceP2p1s0f0", {**less, "counters/" + link[0]: None})
        ring_port(folder, "roceP2p1s0f1", {**less, "state": "1: DOWN", "counters/port_rcv_data": "x"})
        ring_port(folder, "other0", {"state": "4: ACTIVE", "rate": "10 Gb/sec"})
        got = namespace["fabric"]()
    stamps = [port.pop("t") for port in got.values()]
    assert all(isinstance(stamp, float) for stamp in stamps), stamps  # each port says when its traffic was read
    assert got["rocep1s0f0"] == {"tx": 1000, "rx": 2000, "up": True, "rate": 200.0, "err": 13}, got["rocep1s0f0"]
    unread = {"tx": None, "rx": 2000, "up": True, "rate": None, "err": 13}  # was left out of the sample
    assert got["rocep1s0f1"] == unread, got["rocep1s0f1"]
    # no file of its state: unknown, was "down". One error counter that is there and unread: no count, was 12
    assert got["roceP2p1s0f0"] == {"tx": 1000, "rx": 2000, "up": None, "rate": 200.0, "err": None}, got["roceP2p1s0f0"]
    # a counter this device does not have is none of its errors: the sum of those it has. A state that reads down is down
    assert got["roceP2p1s0f1"] == {"tx": 1000, "rx": None, "up": False, "rate": 200.0, "err": 11}, got["roceP2p1s0f1"]
    assert set(got) == {"rocep1s0f0", "rocep1s0f1", "roceP2p1s0f0", "roceP2p1s0f1"}, set(
        got
    )  # no traffic counters: no port


def test_a_state_file_that_reads_empty_says_nothing_of_the_link():
    """Whether a ring port is up is read from the `state` file of its port: "4: ACTIVE", or another word for a link
    that is not. A file that could be read and held nothing was sent as "down" (`"ACTIVE" in ""`), and the hub
    wrote "Link ... went down" of a state nobody read. An empty reading is no reading: None, as for a file that
    cannot be read. Down is a file that says something, and that is not ACTIVE."""
    namespace = sampler_namespace()
    files = {"rate": "200 Gb/sec (4X HDR)", "counters/port_xmit_data": "1000", "counters/port_rcv_data": "2000"}
    states = ("4: ACTIVE\n", "", "\n", "1: DOWN\n")  # the second holds no byte, the third the end of a line
    hub, seen = hub_for(), []
    with tempfile.TemporaryDirectory() as folder:
        namespace["glob"] = types.SimpleNamespace(glob=lambda pattern: glob.glob(os.path.join(folder, "*")))
        ring_port(folder, "rocep1s0f0", files)
        for k, text in enumerate(states):
            with open(os.path.join(folder, "rocep1s0f0", "ports", "1", "state"), "w") as f:
                f.write(text)
            port = namespace["fabric"]()["rocep1s0f0"]
            hub.ingest("dgx0", {"t": 100.0 + 2 * k, "fabric": {"rocep1s0f0": port}})
            seen.append((port["up"], hub.edges_view()[0]["up"], [e["text"] for e in hub.events if e["kind"] == "link"]))
    assert seen[0] == (True, True, []), seen
    assert seen[1] == seen[2] == (None, None, []), seen  # was (False, False, ["Link f0 went down"]) for each
    assert seen[3] == (False, False, ["Link f0 went down"]), seen  # a state that says down is down, and said once


def test_each_ring_port_and_the_disk_name_the_moment_their_counters_were_read():
    """The traffic of a ring port and the sectors of the disk become rates in the hub, and a rate is right only over
    the moment its counters were read. The sample is stamped when its round begins, and these are read after the
    GPU, the cores, the CPU and the memory, later by as much as those took: more in one round than in the next.
    Each port says when its data counters were read, also the one read after the files of another; the disk says
    when its list was read."""
    namespace, clock = sampler_namespace(), [1000.0]
    devices = ["/sys/class/infiniband/rocep1s0f0", "/sys/class/infiniband/rocep1s0f1"]
    port = {"state": "4: ACTIVE", "rate": "200 Gb/sec (4X HDR)", "counters/port_xmit_data": "1000"}
    port["counters/port_rcv_data"] = "2000"
    files = {f"{d}/ports/1/{path}": text for d in devices for path, text in port.items()}
    files["/proc/diskstats"] = " 259 0 nvme0n1 10 0 4000 0 20 0 800 0 0 0 0\n"
    opened = slow_files(namespace, files, clock)
    namespace["glob"] = types.SimpleNamespace(glob=lambda pattern: list(devices))
    got = namespace["fabric"]()
    first, second = (got[d.rsplit("/", 1)[1]]["t"] for d in devices)
    assert first == opened[devices[0] + "/ports/1/counters/port_xmit_data"] == 1000.0, (got, opened)
    assert second == opened[devices[1] + "/ports/1/counters/port_xmit_data"] == 1001.0, (got, opened)
    clock[0] += 0.5  # the sensors and the zones come between
    disk = namespace["disk"]()
    assert disk["t"] == opened["/proc/diskstats"] == 1002.5 and disk["read"] == 4000, (disk, opened)
