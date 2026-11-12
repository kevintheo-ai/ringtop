# ruff: noqa
"""The engine's log and its threads: what it says, and which of its threads use the CPU."""

OWN_POLLS = re.compile(r'"GET /(metrics|v1/models|version|health|load)\b')
REQUEST_TEXT = re.compile(
    r"\b(Received request|Generated response)\b"
)  # with request logging on, prompts and answers would stand here
logs_at, last_stamp = [time.time() - 1800], [""]


def docker_log(name, *window):
    """The lines of a container's log within the window given, or None when docker does not answer."""
    try:
        done = subprocess.run(
            ["docker", "logs", *window, "--timestamps", name],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=8,
        )
    except Exception:
        return None
    return None if done.returncode else (done.stdout + done.stderr).splitlines()


def engine_log(name):
    """New lines of the engine container since the last look, without the polling of this tool, without request texts,
    secrets hidden."""
    # 500 lines per look (every 5 s). --since re-reads the whole log file (0.3 s and growing), so it only runs when the
    # tail does not reach back to the last look, e.g. with request logging on under load; Docker stamps have a fixed width
    if last_stamp[0]:
        lines = docker_log(name, "--tail", "500")
        stamps = [line.partition(" ")[0] for line in lines or [] if re.match(r"\d{4}-\d\d-\d\dT", line)]
        if len(stamps) >= 500 and min(stamps) > last_stamp[0]:
            lines = docker_log(name, "--since", last_stamp[0]) or lines
    else:
        lines = docker_log(name, "--since", "%d" % logs_at[0])
    if lines is None:
        return []
    out, newest = [], last_stamp[0]
    for line in lines:
        stamp, _, text = line.partition(" ")
        if not re.match(r"\d{4}-\d\d-\d\dT", stamp) or stamp <= last_stamp[0]:
            continue
        newest = max(newest, stamp)
        if OWN_POLLS.search(text) or REQUEST_TEXT.search(text):
            continue
        try:
            t = calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        out.append({"t": t, "text": SECRET.sub(r"\1***", text)[:320]})
    last_stamp[0] = newest
    return sorted(out, key=lambda e: e["t"])[-150:]


last_threads = {}


def threads():
    """CPU use of the engine's threads by thread name, and the threads that decide its speed. None where the look
    for the engine's processes failed: that is no engine without threads."""
    try:
        pids = subprocess.run(["pgrep", "-f", "VLLM::"], capture_output=True, text=True, timeout=5).stdout.split()
    except Exception:
        return None
    now, ticks_per_s, seen, groups, each = time.time(), os.sysconf("SC_CLK_TCK"), {}, {}, []
    for pid in pids:
        for path in glob.glob("/proc/%s/task/*/stat" % pid):
            text = read(path)
            if not text:
                continue
            comm, rest = text[text.index("(") + 1 : text.rindex(")")], text[text.rindex(")") + 2 :].split()
            ticks, core = int(rest[11]) + int(rest[12]), int(rest[36])
            folder = path[:-4]
            run = (read(folder + "schedstat") or "0 0 0").split()
            wait = int(run[1]) if len(run) > 1 and run[1].isdigit() else 0
            status = read(folder + "status") or ""
            vol = re.search(r"^voluntary_ctxt_switches:\s+(\d+)", status, re.M)
            forced = re.search(r"^nonvoluntary_ctxt_switches:\s+(\d+)", status, re.M)
            vol, forced = int(vol.group(1)) if vol else 0, int(forced.group(1)) if forced else 0
            seen[path] = (now, ticks, wait, vol, forced)
            before = last_threads.get(path)
            if not before or now <= before[0]:
                continue
            dt = now - before[0]
            pct = (ticks - before[1]) / ticks_per_s / dt * 100
            waits = (wait - before[2]) / 1e6 / dt
            wakes, preempted = (vol - before[3]) / dt, (forced - before[4]) / dt
            group = groups.setdefault(
                comm, {"name": comm[:24], "pct": 0.0, "threads": 0, "cores": set(), "wait": 0.0, "wakes": 0.0}
            )
            group["pct"] += pct
            group["threads"] += 1
            group["wait"] += waits
            group["wakes"] += wakes + preempted
            if pct >= 1:
                group["cores"].add(core)
            each.append(
                {
                    "tid": path.split("/")[4],
                    "pid": pid,
                    "comm": comm,
                    "pct": pct,
                    "core": core,
                    "wait": waits,
                    "wakes": wakes,
                    "preempted": preempted,
                    "folder": folder,
                }
            )
    last_threads.clear()
    last_threads.update(seen)
    return [
        dict(g, pct=round(g["pct"]), wait=round(g["wait"], 1), wakes=round(g["wakes"]), cores=sorted(g["cores"])[:20])
        for g in sorted(groups.values(), key=lambda g: -g["pct"])[:8]
    ], key_threads(each)


last_migrations = {}


def key_threads(each):
    """The threads that decide the speed, by role: rank main thread, scheduler, API server, transport proxy, and the
    worker thread that wakes most often. With how often each one moved to another core."""

    def role(t):
        if t["comm"].startswith("sparknet-proxy"):
            return "transport proxy"
        if t["tid"] != t["pid"]:
            return None
        return (
            "scheduler"
            if t["comm"].startswith("VLLM::EngineCor")
            else "rank main"
            if t["comm"].startswith("VLLM::Worker")
            else "api server"
            if t["comm"] == "vllm"
            else None
        )

    out = [dict(t, role=role(t)) for t in each if role(t)]
    wakers = sorted(
        (t for t in each if t["comm"].startswith("VLLM::Worker") and t["tid"] != t["pid"]), key=lambda t: -t["wakes"]
    )
    if wakers and wakers[0]["wakes"] > 500:
        out.append(dict(wakers[0], role="most wake-ups"))
    now = time.time()
    for t in out:
        m = re.search(r"se\.nr_migrations\s*:\s*(\d+)", read(t["folder"] + "sched") or "")
        moved = int(m.group(1)) if m else None
        before = last_migrations.get(t["tid"])
        last_migrations[t["tid"]] = (now, moved)
        t["migrated"] = (
            round((moved - before[1]) / (now - before[0]), 1)
            if moved is not None and before and before[1] is not None and moved >= before[1] and now > before[0]
            else None
        )
        for gone in ("folder", "pid", "tid"):
            t.pop(gone)
        t.update(
            pct=round(t["pct"], 1),
            wait=round(t["wait"], 2),
            wakes=round(t["wakes"]),
            preempted=round(t["preempted"], 1),
        )
    return out[:12]
