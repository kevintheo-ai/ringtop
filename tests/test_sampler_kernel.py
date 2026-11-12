"""The sampler and the kernel: the cores it keeps off."""

import tempfile
import types

from tests.fixtures import hub_for, sampler_namespace


def test_the_sampler_moves_off_the_engine_again_when_the_engine_moves():
    ns = sampler_namespace()
    state = {"self": set(range(8))}
    calls = []

    def setaff(pid, cores):
        calls.append((pid, set(cores)))
        if pid == 100:
            state["self"] = set(cores)

    ns["os"] = types.SimpleNamespace(
        sched_getaffinity=lambda pid: set(state["self"]), sched_setaffinity=setaff, listdir=lambda path: ["100"]
    )
    ns["gpu_proc"][0] = types.SimpleNamespace(
        pid=999, poll=lambda: 0
    )  # nvidia-smi died: its number may belong to someone else now
    ns["pin_away"]({0, 1})
    assert state["self"] == set(range(2, 8)) and all(pid != 999 for pid, _ in calls)
    ns["pin_away"]({4, 5})
    assert state["self"] == {0, 1, 2, 3, 6, 7}


class Nvml:
    """Stands in for the NVML library: the fields of the GPU answer, and of the CPU-GPU links the first `links`
    do, each up, the first one with two errors of the first kind. With `links` None the call for them fails."""

    def __init__(self, links):
        self.links = links

    def nvmlDeviceGetFieldValues(self, device, count, row):
        about_links = row[0].fieldId in (171, 231, 232, 233)
        if about_links and self.links is None:
            return 1  # the call failed
        for slot in row:
            slot.vt, slot.ret = 3, int(about_links and slot.scopeId >= self.links)  # a link there is not: no answer
            slot.v.ull = (
                1 if slot.fieldId == 171 else 2 if (slot.fieldId, slot.scopeId) == (231, 0) else 7 * (not about_links)
            )
        return 0


def test_nvml_fields_that_did_not_answer_are_not_zero():
    """The state and the errors of the CPU-GPU links come from a call of their own to NVML. Their three figures
    started at 0 and stayed there when that call failed: no link, none up, no error, where nothing was read; the
    deep view showed "0" link errors. Each is None until a field of its kind answered. The other fields of the
    same reading arrive as before."""
    ns = sampler_namespace()
    ns["nv"].update(lib=Nvml(2), dev=None)
    read = ns["nvml"]()
    assert (read["c2c_links"], read["c2c_up"], read["c2c_err"], read["energy_mj"]) == (2, 2, 2, 7), read
    ns["nv"].update(lib=Nvml(None))
    failed = ns["nvml"]()
    assert (failed["c2c_links"], failed["c2c_up"], failed["c2c_err"]) == (None, None, None), failed  # was (0, 0, 0)
    assert failed["energy_mj"] == 7  # what the first call read is there
    ns["nv"].update(lib=Nvml(0))  # the call works and no link answers: nothing was read of them either
    assert ns["nvml"]()["c2c_links"] is None


def test_a_cgroup_file_that_could_not_be_read_counts_nothing():
    """What the engine's container read from disk, its CPU time, how often it was throttled and its OOM kills are
    counters in files of its cgroup. A file that could not be read gave 0 for its counters, and the hub counts
    rates from them: the next reading then gave the whole count of the container's life as megabytes or cores per
    second. A counter from a file that was not read is None. A file that was read and names no device (a
    container that has done no I/O yet) is a count of zero."""
    ns = sampler_namespace()
    with tempfile.TemporaryDirectory() as base:
        ns["cg"][0] = base
        files = {
            base + "/io.stat": "259:0 rbytes=4096 wbytes=0 rios=2 wios=0\n259:1 rbytes=4096 wbytes=8 rios=1 wios=1",
            base + "/cpu.stat": "usage_usec 5000000\nuser_usec 1\nnr_throttled 3",
            base + "/memory.events": "low 0\noom_kill 1",
            base + "/memory.current": "1073741824",
            base + "/pids.current": "9",
        }
        ns["read"] = lambda path: files.get(path)
        whole = ns["engine_cgroup"]()
        assert whole["disk"] == {"rbytes": 8192, "wbytes": 8, "rios": 3, "wios": 1}, whole
        assert (whole["cpu_us"], whole["throttled"], whole["oom"], whole["pids"]) == (5000000, 3, 1, 9), whole
        files[base + "/io.stat"] = ""
        assert ns["engine_cgroup"]()["disk"] == {"rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0}  # read: no I/O yet
        for gone in ("/io.stat", "/cpu.stat", "/memory.events"):
            del files[base + gone]
        unread = ns["engine_cgroup"]()
    assert unread["disk"] == {"rbytes": None, "wbytes": None, "rios": None, "wios": None}, unread  # was four zeros
    assert (unread["cpu_us"], unread["throttled"], unread["oom"]) == (None, None, None), unread  # was (0, 0, 0)
    assert (unread["mem"], unread["pids"]) == (1073741824, 9)
    hub = hub_for()
    node = hub.nodes["dgx0"]
    hub.ingest("dgx0", {"t": 100.0, "fabric": {}, "cg": whole})
    hub.ingest("dgx0", {"t": 102.0, "fabric": {}, "cg": unread})  # the hub takes it: no error, and no rate
    assert (node["eng_read_mb"], node["eng_cores"], node["eng_throttled"], node["eng_oom"]) == (None,) * 4, node
    assert node["eng_mem_gb"] == 1.0 and node["eng_pids"] == 9
    hub.ingest("dgx0", {"t": 104.0, "fabric": {}, "cg": {**whole, "cpu_us": 9000000}})
    assert node["eng_cores"] == 1.0, node["eng_cores"]  # four seconds of CPU in the 4 s since its last reading
