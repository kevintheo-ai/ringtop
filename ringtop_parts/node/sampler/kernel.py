# ruff: noqa
"""What the kernel knows about the engine's place on the node: its cores, cgroup, pressure and thermal zones, and the
NVML fields nvidia-smi does not offer."""

capacity = sorted(
    glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpu_capacity"), key=lambda p: int(re.search(r"cpu(\d+)/", p).group(1))
)
capacity = [read_int(p) for p in capacity]


def safe(fn, *args):
    """The result of one reading, or None when it fails: one reading that fails must never take the sampler down."""
    try:
        return fn(*args)
    except Exception:
        return None


def parse_cpus(text):
    """The set of cores a list like 5-9,15-19 names."""
    out = set()
    for part in (text or "").split(","):
        a, _, b = part.strip().partition("-")
        if a.isdigit():
            out.update(range(int(a), int(b or a) + 1))
    return out


pinned, off_engine, all_cores = [None], [None], []


def pin_away(engine):
    """Moves the sampler and its nvidia-smi off the cores the engine is pinned to, so measuring does not disturb it."""
    if not all_cores:
        all_cores.append(set(os.sched_getaffinity(0)))
    rest = all_cores[0] - engine  # from all cores, not from the last pinning: the engine can move to other cores
    if pinned[0] == engine or not engine or not rest:
        return
    for tid in os.listdir("/proc/self/task"):
        safe(os.sched_setaffinity, int(tid), rest)
    if gpu_proc[0] is not None and gpu_proc[0].poll() is None:  # a dead helper's number may belong to someone else
        safe(os.sched_setaffinity, gpu_proc[0].pid, rest)
    pinned[0], off_engine[0] = set(engine), rest


def psi(pattern):
    """The stall totals of CPU, IO and memory from the pressure files the pattern names, in microseconds, and when
    they were read (`t`): they become shares of time over that moment."""
    out = {"t": time.time()}
    for name in ("cpu", "io", "memory"):
        for line in (read(pattern % name) or "").splitlines():
            kind, _, rest = line.partition(" ")
            m = re.search(r"total=(\d+)", rest)
            if m:
                out[name + "_" + kind] = int(m.group(1))
    return out


cg = [None]


def engine_cgroup():
    """What the cgroup of the engine's container counts: disk, CPU time, throttling, memory, OOM kills, processes and
    pressure. None without a container. A counter from a file that could not be read is None: sent as 0, the next
    reading would give its whole count as the rate of one interval. A file that was read and names no device (no
    I/O yet) counts zero. `t` is when its files began to be read: the hub counts their rates over that moment."""
    base = cg[0]
    if not base or not os.path.isdir(base):
        return None
    stamp = time.time()
    stat = read(base + "/io.stat")
    disk = dict.fromkeys(("rbytes", "wbytes", "rios", "wios"), None if stat is None else 0)
    for line in (stat or "").splitlines():
        for k, v in re.findall(r"(rbytes|wbytes|rios|wios)=(\d+)", line):
            disk[k] += int(v)
    cpu = dict(l.split() for l in (read(base + "/cpu.stat") or "").splitlines() if len(l.split()) == 2)
    events = dict(l.split() for l in (read(base + "/memory.events") or "").splitlines() if len(l.split()) == 2)

    def count(found, key):
        return int(found[key]) if key in found else None

    return {
        "t": stamp,
        "disk": disk,
        "cpu_us": count(cpu, "usage_usec"),
        "throttled": count(cpu, "nr_throttled"),
        "mem": read_int(base + "/memory.current"),
        "peak": read_int(base + "/memory.peak"),
        "oom": count(events, "oom_kill"),
        "pids": read_int(base + "/pids.current"),
        "psi": psi(base + "/%s.pressure"),
    }


def engine_pids():
    """The process ids inside the engine's container."""
    return set((read((cg[0] or "/nonexistent") + "/cgroup.procs") or "").split())


zone_names = {}


def zones():
    """Every thermal zone in degrees Celsius under its real name from ACPI: TSOC, TS0P, TS1P, TGPU, TUNC, TS0E, TS1E."""
    out = {}
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        if z not in zone_names:
            zone_names[z] = (read(z + "/device/path") or read(z + "/type") or os.path.basename(z)).rsplit(".", 1)[-1]
        t = read_int(z + "/temp")
        if t and t > 0:
            out[zone_names[z]] = round(t / 1000, 1)
    return out


class NvNumber(ctypes.Union):
    """The value of one NVML field, in whichever number type the field has."""

    _fields_ = [
        ("d", ctypes.c_double),
        ("ui", ctypes.c_uint),
        ("ul", ctypes.c_ulong),
        ("ull", ctypes.c_ulonglong),
        ("sll", ctypes.c_longlong),
        ("si", ctypes.c_int),
    ]


class NvField(ctypes.Structure):
    """One NVML field as nvmlDeviceGetFieldValues fills it in: id, scope, time, type, return code and value."""

    _fields_ = [
        ("fieldId", ctypes.c_uint),
        ("scopeId", ctypes.c_uint),
        ("ts", ctypes.c_longlong),
        ("lat", ctypes.c_longlong),
        ("vt", ctypes.c_uint),
        ("ret", ctypes.c_uint),
        ("v", NvNumber),
    ]


NV_FIELDS = {83: "energy_mj", 80: "below_app_ns", 81: "below_base_ns", 272: "freq_acc", 273: "af_acc"}
NV_C2C = (171, 231, 232, 233)  # link status, then interrupt, replay and replay-back-to-back errors, per link
nv = {}


def nvml():
    """NVML fields nvidia-smi does not offer: mean clock and activity over the interval, energy, the CPU-GPU links.
    Read-only. The figures of the links are None until a field of their kind answered: no answer is no link, no
    link up and no error only for somebody who read them."""
    if "lib" not in nv:
        lib, device = ctypes.CDLL("libnvidia-ml.so.1"), ctypes.c_void_p()
        if lib.nvmlInit_v2() or lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(device)):
            return None
        nv.update(lib=lib, dev=device)

    def batch(
        wanted,
    ):  # fields of different kinds answer only in separate calls (measured: mixed, the balancing counters read 0)
        row = (NvField * len(wanted))()
        for slot, (field, scope) in zip(row, wanted):
            slot.fieldId, slot.scopeId = field, scope
        if nv["lib"].nvmlDeviceGetFieldValues(nv["dev"], len(wanted), row):
            return []
        return [
            (f, {0: s.v.d, 1: s.v.ui, 2: s.v.ul, 3: s.v.ull, 4: s.v.sll}.get(s.vt, s.v.si))
            for s, (f, _) in zip(row, wanted)
            if not s.ret
        ]

    out = {"c2c_links": None, "c2c_up": None, "c2c_err": None}
    for field, value in batch([(i, 0) for i in NV_FIELDS]):
        out[NV_FIELDS[field]] = value
    for field, value in batch([(i, link) for i in NV_C2C for link in range(8)]):
        if field == 171:
            out["c2c_links"] = (out["c2c_links"] or 0) + 1
            out["c2c_up"] = (out["c2c_up"] or 0) + int(value > 0)
        else:
            out["c2c_err"] = (out["c2c_err"] or 0) + value
    return out
