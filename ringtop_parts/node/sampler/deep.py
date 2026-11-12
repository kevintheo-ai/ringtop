# ruff: noqa
"""The deep readings: memory, core clocks, who else ran on the engine's cores, interrupts, cooling, PCIe, firmware, the
cold start and the open connections."""

VM_KEEP = (
    "pgmajfault",
    "pswpin",
    "pswpout",
    "oom_kill",
    "compact_stall",
    "compact_fail",
    "compact_success",
    "compact_migrate_scanned",
    "compact_free_scanned",
    "pgmigrate_fail",
    "pgmigrate_success",
)
MEM_KEEP = (
    "MemTotal",
    "MemFree",
    "MemAvailable",
    "Buffers",
    "Cached",
    "AnonPages",
    "Slab",
    "KernelStack",
    "PageTables",
    "SecPageTables",
    "Percpu",
    "VmallocUsed",
    "Shmem",
    "Mlocked",
    "SwapTotal",
    "SwapFree",
)


def memory_deep():
    """Where the unified memory went, how fragmented it is, and whether the kernel is fighting for it."""
    mem, vm = {}, {"allocstall": 0}
    for line in (read("/proc/meminfo") or "").splitlines():
        k, _, v = line.partition(":")
        if k in MEM_KEEP and v.strip():
            mem[k] = int(v.split()[0]) * 1024
    for line in (read("/proc/vmstat") or "").splitlines():
        k, _, v = line.partition(" ")
        if k.startswith("allocstall") and v.isdigit():
            vm["allocstall"] += int(v)
        elif k in VM_KEEP and v.isdigit():
            vm[k] = int(v)
    page, blocks, free_big = os.sysconf("SC_PAGE_SIZE"), 0, 0
    for line in (read("/proc/buddyinfo") or "").splitlines():
        if "Normal" not in line:
            continue
        for order, count in enumerate(int(x) for x in line.split("Normal")[1].split()):
            if page << order >= 16 * 2**20:
                blocks += count
                free_big += count * (page << order)
    return {"mem": mem, "vm": vm, "blocks_16m": blocks, "free_big": free_big}


def core_clocks():
    """The frequency each core really delivered, not the one asked for, and how many cores were limited. A core that
    sleeps has no number. How many are limited is None unless the flag of every core was read, and where no core is
    listed: a flag nobody read is no core without a limit."""
    out, flags = [], []
    for i in range(len(capacity)):
        value = read_int("/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_avg_freq" % i)
        out.append(round(value / 1000) if value else None)
        flags.append(read_int("/sys/devices/system/cpu/cpu%d/cpufreq/perf_limited" % i))
    return out, sum(1 for flag in flags if flag) if flags and None not in flags else None


last_others = [0.0, {}]


def intruders(allowed, own):
    """Who else ran on the engine's cores since the last look: by program name, in milliseconds per second. None
    for the first look, which has nothing to compare with: that is not a look that found nobody."""
    # ponytail: /proc only tells the core a task sat on at the moment of reading, so a task counts with its whole time when
    # it sits on an engine core then; the exact split per core needs perf or eBPF, which this tool never runs on the ring
    now, ticks_per_s, found, seen = time.time(), os.sysconf("SC_CLK_TCK"), {}, {}
    for path in glob.glob("/proc/[0-9]*/task/[0-9]*/stat"):
        if path.split("/")[2] in own:
            continue
        text = read(path)
        if not text:
            continue
        comm, rest = text[text.index("(") + 1 : text.rindex(")")], text[text.rindex(")") + 2 :].split()
        ticks, core = int(rest[11]) + int(rest[12]), int(rest[36])
        seen[path] = ticks
        before = last_others[1].get(path)
        if before is not None and core in allowed and ticks > before:
            found[comm] = found.get(comm, 0) + ticks - before
    dt = now - last_others[0]
    first = not last_others[0]
    last_others[0], last_others[1] = now, seen
    if first or dt <= 0:
        return None
    return [
        {"name": k[:24], "ms": round(v / ticks_per_s * 1000 / dt, 1)}
        for k, v in sorted(found.items(), key=lambda kv: -kv[1])[:6]
    ]


last_irq = [0.0, {}]


def irq_noise(allowed):
    """Interrupts per second on the engine's cores, by source: timer, network, disk, Wi-Fi."""
    lines = (read("/proc/interrupts") or "").splitlines()
    if not lines:
        return None
    cpus = [int(c[3:]) for c in lines[0].split()]
    totals = {}
    for line in lines[1:]:
        name, _, rest = line.partition(":")
        parts = rest.split()
        counts = [int(x) for x in parts[: len(cpus)] if x.isdigit()]
        label = " ".join(parts[len(counts) :])
        kind = (
            "timer"
            if "arch_timer" in label
            else "nvme"
            if "nvme" in label
            else "network"
            if "mlx5" in label
            else "wifi"
            if "mt79" in label
            else "ipi"
            if name.strip().startswith("IPI")
            else "other"
        )
        for cpu, count in zip(cpus, counts):
            if cpu in allowed:
                totals[(cpu, kind, name.strip())] = count
    now, (before_t, before) = time.time(), last_irq
    last_irq[0], last_irq[1] = now, totals
    if not before_t or now <= before_t:
        return None
    by_kind, by_core = {}, {}
    for (cpu, kind, line), count in totals.items():
        if (cpu, kind, line) not in before:
            continue  # a source that just appeared has only its count since boot
        rate = max(0, count - before[(cpu, kind, line)]) / (now - before_t)
        by_kind[kind] = round(by_kind.get(kind, 0) + rate, 1)
        by_core[str(cpu)] = round(by_core.get(str(cpu), 0) + rate, 1)
    return {"by_kind": by_kind, "by_core": by_core}


def cooling():
    """Who sets the fan speed: the firmware alone (state 0), or a floor someone set. Only ever read here."""
    out = []
    for d in sorted(glob.glob("/sys/class/thermal/cooling_device*")):
        kind = read(d + "/type") or ""
        if kind in ("Fan", "dgx_ec_fan_floor"):  # the ACPI fans, and the floor of dgx-spark-fan-control
            out.append({"type": kind, "cur": read_int(d + "/cur_state"), "max": read_int(d + "/max_state")})
    return out


def pcie_links():
    """Link speed and width of the network chip and the disk against what they should be, and PCIe errors."""
    out = {}
    for path in sorted(glob.glob("/sys/class/infiniband/*")) + sorted(glob.glob("/sys/class/nvme/nvme*")):
        d = path + "/device/"
        total = lambda f: int((re.search(r"TOTAL_\w+\s+(\d+)", read(d + f) or "") or [0, 0])[1])
        out[os.path.basename(path)] = {
            "gt": read(d + "current_link_speed"),
            "x": read_int(d + "current_link_width"),
            "gt_max": read(d + "max_link_speed"),
            "x_max": read_int(d + "max_link_width"),
            "aer": total("aer_dev_correctable") + total("aer_dev_nonfatal") + total("aer_dev_fatal"),
        }
    return out


def devlink_health():
    """How many health reporters the network card has, how many are not healthy, and how often they recovered."""
    text = subprocess.run(["devlink", "-j", "health", "show"], capture_output=True, text=True, timeout=4).stdout
    rows = [r for group in json.loads(text or "{}").get("health", {}).values() for r in group]
    return {
        "reporters": len(rows),
        "unhealthy": sum(r.get("state") != "healthy" for r in rows),
        "recovered": sum(int(r.get("recover", 0)) for r in rows),
    }


def firmware():
    """What this node runs, read once: BIOS, kernel, driver and firmware versions and a few settings. Differences
    between nodes explain a lot."""

    def first(*cmd):
        return (
            safe(lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout.strip()) or ""
        ).split("\n")[0][:60] or None

    def bracket(path):
        m = re.search(r"\[(\w+)\]", read(path) or "")
        return m.group(1) if m else None

    driver = re.search(r"\b(\d{3}\.\d+\.\d+)\b", read("/proc/driver/nvidia/version") or "")
    fw = sorted(set(read(p) or "" for p in glob.glob("/sys/class/infiniband/*/fw_ver")))
    return {
        "bios": read("/sys/class/dmi/id/bios_version"),
        "board": read("/sys/class/dmi/id/board_name"),
        "kernel": os.uname().release,
        "driver": driver.group(1) if driver else None,
        "vbios": first("nvidia-smi", "--query-gpu=vbios_version", "--format=csv,noheader"),
        "nic_fw": " ".join(fw) or None,
        "thp": bracket("/sys/kernel/mm/transparent_hugepage/enabled"),
        "swappiness": read("/proc/sys/vm/swappiness"),
        "governor": read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
        "isolated": re.findall(r"\b(?:isolcpus|nohz_full|rcu_nocbs)=\S+", read("/proc/cmdline") or ""),
        "ssd": read("/sys/class/nvme/nvme0/model"),
        "ssd_fw": read("/sys/class/nvme/nvme0/firmware_rev"),
    }


START_MARKS = (
    ("loaded", r"Model loading took ([\d.]+) GiB memory and ([\d.]+) seconds"),
    ("free_at_start", r"Initial free memory ([\d.]+) GiB"),
    ("kv", r"GPU KV cache size: ([\d,]+) tokens"),
    ("init", r"init engine .* took ([\d.]+) s"),
    ("ready", r"Application startup complete"),
)
started_seen = [None]


def startup(box):
    """The cold start of this container, read once per start: how long each stage took and the memory budget of this
    rank."""
    began = box.get("started") or ""
    if began == started_seen[0] or not began or began.startswith("0001"):
        return None
    t0 = calendar.timegm(time.strptime(began[:19], "%Y-%m-%dT%H:%M:%S"))
    done = subprocess.run(
        ["docker", "logs", "--timestamps", "--since", str(t0), "--until", str(t0 + 900), box["name"]],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=20,
    )
    out = {"started": t0, "marks": {}, "memory": {}}
    for line in (done.stdout + done.stderr).splitlines():
        stamp, _, text = line.partition(" ")
        try:
            at = calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")) - t0
        except ValueError:
            continue
        for mark, pattern in START_MARKS:
            found = re.search(pattern, text)
            if found and mark not in out["marks"]:
                out["marks"][mark] = {"at": at, "value": found.group(1) if found.groups() else None}
        if "[memory_breakdown]" in text:
            out["memory"] = {k: float(v) for k, v in re.findall(r"(\w+)=([\d.]+) GiB", text)}
    if "ready" in out["marks"] or time.time() - t0 > 900:
        started_seen[0] = began  # finished: no need to read this log again
    return out


def connections(p):
    """Open connections to the engine: how many requests are in flight, how old they are and how much came back. Never
    their content. None where ss ended with an error: that is not an engine nobody is connected to."""
    done = subprocess.run(
        ["ss", "-H", "-tin", "state", "established", "( sport = :%s )" % p], capture_output=True, text=True, timeout=4
    )
    if done.returncode:
        return None
    out, peer = [], None
    for line in done.stdout.splitlines():
        if not line.startswith((" ", "\t")):
            fields = line.split()
            peer = fields[-1] if len(fields) >= 4 else None
            continue
        row = {k: int(v) for k, v in re.findall(r"\b(bytes_sent|bytes_received|lastsnd|lastrcv):(\d+)", line)}
        if peer:
            row["port"] = peer.rpartition(":")[2]
            out.append(row)
    return sorted(out, key=lambda r: -r.get("lastrcv", 0))[:40]


def health(p):
    """The status code the engine's /health answers with, or None when nothing answers."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%s/health" % p, timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None
