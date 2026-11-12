"""The sampler's slow readings: firmware, interrupts."""

import types

from tests.fixtures import sampler_namespace


def test_isolated_cores_keep_their_masks():
    ns = sampler_namespace()
    ns["read"] = lambda path: "ro quiet isolcpus=2-19 nohz_full=2-19 rcu_nocbs=4" if path == "/proc/cmdline" else None
    ns["subprocess"] = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout=""))
    assert ns["firmware"]()["isolated"] == ["isolcpus=2-19", "nohz_full=2-19", "rcu_nocbs=4"]


def test_an_interrupt_source_that_appears_later_is_no_spike():
    ns = sampler_namespace()
    head = "           CPU0       CPU1\n"
    old = " 11:    1000    2000   GICv3  27 Level     arch_timer\n"
    new = " 99: 9000000 9000000   ITS-MSI  mlx5_comp0@pci:0000:01:00.0\n"
    texts = iter([head + old, head + old.replace("1000 ", "1100 ") + new])
    ns["read"] = lambda path: next(texts)
    assert ns["irq_noise"]({0, 1}) is None
    ns["last_irq"][0] -= 1.0  # one second later
    rates = ns["irq_noise"]({0, 1})
    assert rates["by_kind"].get("network", 0) == 0 and 90 < rates["by_kind"]["timer"] < 110, rates


def test_the_first_look_at_other_programs_is_no_look_at_nobody():
    """Who else ran on the engine's cores is the CPU time other programs gained between two looks. The first look
    has nothing to compare with and gave an empty list: nobody ran there, and the deep view said "0.0 ms/s" for the
    first 15 s of every sampler. It is None: not counted yet. The second look counts."""
    ns = sampler_namespace()

    def stat(
        ticks,
    ):  # one task as /proc shows it: its name, then state, ten fields, user and system ticks, 23 more, its core
        return "7 (dockerd) " + " ".join(["S", *["0"] * 10, str(ticks), "0", *["0"] * 23, "6"])

    texts = iter([stat(100), stat(150)])
    ns["glob"] = types.SimpleNamespace(glob=lambda pattern: ["/proc/7/task/7/stat"])
    ns["read"] = lambda path: next(texts)
    assert ns["intruders"]({6}, set()) is None  # was []
    ns["last_others"][0] -= 1.0  # one second later
    ran = ns["intruders"]({6}, set())
    per_s = 50 / ns["os"].sysconf("SC_CLK_TCK") * 1000  # 50 ticks in about a second
    assert len(ran) == 1 and ran[0]["name"] == "dockerd" and 0.9 * per_s < ran[0]["ms"] <= per_s, ran


def test_cores_whose_limit_flag_was_not_read_are_not_counted_as_unlimited():
    """How many cores the platform limits is counted from a flag per core. A flag that could not be read counted
    as "not limited", and a machine that lists no core at all had 0 of them limited: both said of cores nobody
    looked at. The count is None unless the flag of every core was read. The clock of a core that gave none stays
    its own None, in its place."""
    ns = sampler_namespace()
    ns["capacity"] = [718, 1024, 1024]
    cpu = "/sys/devices/system/cpu/cpu%d/cpufreq/"
    files = {cpu % 0 + "cpuinfo_avg_freq": "2800000", cpu % 1 + "cpuinfo_avg_freq": "3880000"}
    files.update({cpu % 0 + "perf_limited": "0", cpu % 1 + "perf_limited": "1", cpu % 2 + "perf_limited": "0"})
    ns["read"] = lambda path: files.get(path)
    assert ns["core_clocks"]() == ([2800, 3880, None], 1)  # the third core sleeps: no clock, its flag was read
    del files[cpu % 2 + "perf_limited"]
    assert ns["core_clocks"]() == ([2800, 3880, None], None)  # was 1: the flag nobody read counted as not limited
    ns["capacity"] = []
    assert ns["core_clocks"]() == ([], None)  # was ([], 0): no core listed, none looked at
