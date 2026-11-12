"""What every part of the sampler uses: how a file is read, and what a file that cannot be read is."""

import io
import os

from tests.fixtures import sampler_namespace


def test_a_file_that_says_try_again_is_not_read_and_does_not_end_its_reader():
    """Some files of /sys answer a read with "try again" (EAGAIN): the clock of a core that sleeps does, on the
    Sparks. Python raises a TypeError for that in a file opened as text, no OSError, and read() caught only the
    latter: the error ended the whole reader that had asked. The clocks of the cores failed on every look as soon
    as one core slept, and all four Sparks of the ring sent no clock of any core. Such a file is not read: None,
    like a file that is not there. The reader goes on to the next core."""
    ns = sampler_namespace()
    asleep, other_end = os.pipe()
    os.set_blocking(asleep, False)  # nobody writes: a read of it answers EAGAIN, as the file of a sleeping core does
    try:
        assert ns["read"](os.dup(asleep)) is None  # was TypeError("can't concat NoneType to bytes")
        cpu = "/sys/devices/system/cpu/cpu%d/cpufreq/"
        texts = {cpu % 0 + "cpuinfo_avg_freq": "2800000\n", cpu % 2 + "cpuinfo_avg_freq": "3880000\n"}
        texts.update({cpu % core + "perf_limited": "0\n" for core in range(3)})

        def opened(path):
            if path == cpu % 1 + "cpuinfo_avg_freq":
                return open(os.dup(asleep))  # the second core sleeps
            if path in texts:
                return io.StringIO(texts[path])
            raise FileNotFoundError(path)

        ns["open"], ns["capacity"] = opened, [718, 1024, 1024]
        assert ns["core_clocks"]() == ([2800, None, 3880], 0)  # was the TypeError: no clock of any core
        assert ns["read"]("/no/such/file") is None and ns["read_int"](cpu % 0 + "cpuinfo_avg_freq") == 2800000
    finally:
        os.close(asleep)
        os.close(other_end)
