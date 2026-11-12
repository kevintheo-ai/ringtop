# ruff: noqa
"""The GPU, read by one nvidia-smi that keeps running: power, temperature, clock, load, and the reasons it slows
down."""

gpu, gpu_seen, gpu_proc = {}, [0.0], [None]
GPU_BASE = (
    ("power.draw", "w"),
    ("temperature.gpu", "c"),
    ("clocks.sm", "mhz"),
    ("utilization.gpu", "util"),
    ("clocks_event_reasons.active", "events"),
    ("power.limit", "limit"),
)
GPU_MORE = (
    ("temperature.gpu.tlimit", "tlimit"),
    ("pstate", "pstate"),
    ("power.draw.instant", "w_now"),
    ("clocks_event_reasons_counters.sw_power_cap", "cap_us"),
    ("clocks_event_reasons_counters.sw_thermal_slowdown", "sw_therm_us"),
    ("clocks_event_reasons_counters.hw_thermal_slowdown", "hw_therm_us"),
    ("clocks_event_reasons_counters.hw_power_brake_slowdown", "brake_us"),
)
TEXT_FIELDS = {"events", "pstate"}


def gpu_columns():
    """The fields nvidia-smi is asked for: all of them when the driver knows them, else only the base ones. Older
    drivers refuse the whole query over one unknown field."""
    both = GPU_BASE + GPU_MORE
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-gpu=" + ",".join(f for f, _ in both), "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return both if done.returncode == 0 else GPU_BASE
    except Exception:
        return GPU_BASE


def gpu_loop():
    """Keeps one nvidia-smi running that prints a line per interval and takes every line into `gpu`; starts it again
    when it dies."""
    columns = gpu_columns()
    fields = ",".join(f for f, _ in columns)
    while True:
        try:
            p = subprocess.Popen(
                [
                    "nvidia-smi",
                    "--query-gpu=" + fields,
                    "--format=csv,noheader,nounits",
                    "-lms",
                    str(max(500, int(interval * 1000))),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return
        gpu_proc[0] = p
        for line in p.stdout:
            f = [x.strip() for x in line.split(",")]
            if len(f) == len(columns):
                gpu.update({key: (value if key in TEXT_FIELDS else num(value)) for (_, key), value in zip(columns, f)})
                gpu_seen[0] = time.time()
        p.wait()
        time.sleep(5)  # it died (driver trouble): try again; gpu_now stops reporting the old values meanwhile


threading.Thread(target=gpu_loop, daemon=True).start()


def gpu_now(now):
    """The latest GPU reading, or nothing when it is older than a few intervals: a helper that died must not leave old
    values standing."""
    return dict(gpu) if now - gpu_seen[0] < max(10.0, 5 * interval) else {}
