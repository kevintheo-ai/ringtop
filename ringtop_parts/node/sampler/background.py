# ruff: noqa
"""The slow side of the sampler: one thread reads whatever can hang, so the sampling loop never waits for a slow
tool."""

info, port, pending, box_now = {}, [None], {}, [None]
handover = threading.Lock()  # around what waits for the next sample: log lines are added to it, not replaced


def leave_log(lines):
    """Adds new lines of the engine's log to the ones that wait for the next sample."""
    with handover:
        pending["log"] = pending.get("log", []) + lines


def take_pending(sample):
    """Moves what the threads beside the sampling loop have ready into its sample, each reading once. Under the lock
    the log lines are added under: lines taken between the look at them and the write would be sent twice."""
    with handover:
        for key in ("slow", "info", "log", "rare", "conn", "own"):
            if key in pending:
                sample[key] = pending.pop(key)


def slow_readings(box, engine):
    """The readings of every 15 s that say why the engine is as fast as it is: its threads, core clocks, NVML,
    cables, memory, links, who else ran on its cores. One that fails is None, which says it was not read: an empty
    list would say there is nothing. The others arrive."""
    found = safe(threads) or (None, None)
    clocks, limited = safe(core_clocks) or (None, None)
    stamp = time.time()  # these become rates: they need the moment they were read, not the sample that carries them
    gpu_fields, cable_rows, memory_now = safe(nvml), safe(cable_counters), safe(memory_deep)
    return dict(
        slow_facts(),
        t=stamp,
        box=box,
        threads=found[0],
        key_threads=found[1],
        links=safe(link_detail),
        cables=cable_rows,
        capacity=capacity,
        nvml=gpu_fields,
        memory=memory_now,
        clocks=clocks,
        perf_limited=limited,
        intruders=safe(intruders, engine, engine_pids()) if engine else None,  # no cores of its own: nobody looked
        irq=safe(irq_noise, engine) if engine else None,
    )


def slow_look():
    """The slow look at this node: which engine container docker shows (the sampling loop asks its port from this),
    the cores it is pinned to (the sampler keeps off them), and the slow readings. Gives back the container and
    the readings, with the cold start of a container that was not read yet."""
    box = box_now[0] = container()
    engine = parse_cpus((box or {}).get("cpuset"))
    if box and box.get("id"):
        cg[0] = "/sys/fs/cgroup/system.slice/docker-%s.scope" % box["id"]
    pin_away(engine)
    slow = slow_readings(box, engine)
    if box:
        start = safe(startup, box)
        if start:
            slow["startup"] = start
    return box, slow


def rare_readings():
    """What changes seldom, read once a minute: PCIe links, devlink health, firmware, who sets the fan speed."""
    return {
        "pcie": safe(pcie_links),
        "devlink": safe(devlink_health),
        "firmware": safe(firmware),
        "cooling": safe(cooling),
    }


def head_facts(box):
    """What only the head node tells, every 10 s: the engine's container, the lab's queue, benchmarks that run, the
    kernel, and what the engine says of itself once its port is known. The sampling loop reads the port from it."""
    found = {
        "container": box or container(),
        "lab": lab(),
        "processes": processes(),
        "kernel": os.uname().release,
        "page_size": os.sysconf("SC_PAGE_SIZE"),
    }
    if port[0]:
        found["models"], found["version"] = fetch(port[0], "/v1/models"), fetch(port[0], "/version")
        found["health"] = health(port[0])
    info.clear()
    info.update(found)
    return found


def background():
    """Everything that can hang stays out of the sampling loop, or a slow tool looks like a dead engine. Each reader
    has its own pace, and what it read waits in `pending` for the next sample."""
    next_info = next_slow = next_log = next_rare = next_conn = 0.0
    box = None
    while True:
        now = time.time()
        if now >= next_slow:
            next_slow = now + 15
            box, pending["slow"] = slow_look()
        if now >= next_rare:
            next_rare = now + 60
            pending["rare"] = rare_readings()
        if box and now >= next_log:
            next_log = now + 5
            lines = engine_log(box["name"])
            if lines:
                leave_log(lines)
        if is_head and port[0] and now >= next_conn:
            next_conn = now + 3
            pending["conn"] = safe(connections, port[0])  # None where the look failed: that is no empty list
        if is_head and now >= next_info:
            next_info = now + 10
            pending["info"] = head_facts(box)
        time.sleep(1)
