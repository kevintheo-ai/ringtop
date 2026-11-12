"""The sampler's GPU readings: values of nvidia-smi and when they expire."""

import time

from tests.fixtures import sampler_namespace


def test_gpu_values_expire_when_nvidia_smi_stops():
    namespace = sampler_namespace()
    now = time.time()
    namespace["gpu"].update(w=50.0)
    namespace["gpu_seen"][0] = now
    assert namespace["gpu_now"](now) == {"w": 50.0}
    assert namespace["gpu_now"](now + 60) == {}
