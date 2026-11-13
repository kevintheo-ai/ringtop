"""The sampler's GPU readings: values of nvidia-smi and when they expire."""

import contextlib
import time
import types

from tests.fixtures import sampler_namespace


def test_gpu_values_expire_when_nvidia_smi_stops():
    namespace = sampler_namespace()
    now = time.time()
    namespace["gpu"].update(w=50.0)
    namespace["gpu_seen"][0] = now
    assert namespace["gpu_now"](now) == {"w": 50.0}
    assert namespace["gpu_now"](now + 60) == {}


class Done(Exception):
    """Ends the endless loop of gpu_loop() once its nvidia-smi has ended."""


def test_a_line_of_nvidia_smi_keeps_the_moment_it_came():
    """The GPU's counters of time at a limit become shares of time in the hub. A sample copies the latest line of
    nvidia-smi when the sample is due, which is not when nvidia-smi printed it: the line keeps the moment it came,
    set together with its values."""
    namespace, clock = sampler_namespace(), [1000.0]

    def lines():
        for watts in ("50.0", "51.0"):
            clock[0] += 2.0  # nvidia-smi prints a line per interval
            yield watts + ", 61, 2400, 96, 0x0, 240.0\n"

    def ended(_):
        raise Done

    smi = types.SimpleNamespace(stdout=lines(), wait=lambda: 0)
    namespace["subprocess"] = types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=1),  # an older driver: the base fields only
        Popen=lambda *a, **k: smi,
        PIPE=None,
        DEVNULL=None,
    )
    namespace["time"] = types.SimpleNamespace(time=lambda: clock[0], sleep=ended)
    with contextlib.suppress(Done):
        namespace["gpu_loop"]()
    assert namespace["gpu"]["w"] == 51.0 and namespace["gpu"]["t"] == 1004.0, namespace["gpu"]
    assert namespace["gpu_now"](1005.0)["t"] == 1004.0 == namespace["gpu_seen"][0]
