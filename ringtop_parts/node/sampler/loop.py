# ruff: noqa
"""The sampling loop: one JSON line per interval with what was read fast, whatever the threads beside it have ready
(the slow readings, and its own engine on a Spark that runs one), and the ring engine's metrics on the head node.
Every fast reader has its own guard: one that fails is None in its sample, and the other readings arrive."""

threading.Thread(target=background, daemon=True).start()
threading.Thread(target=own_loop, daemon=True).start()
next_at = time.time()
while True:
    next_at += interval
    now = time.time()
    sample = {
        "t": now,
        "gpu": safe(gpu_now, now),
        "cores": safe(cores),
        "cpu": safe(cpu_percent),
        "cpu_c": safe(cpu_temp),
        "mem": safe(memory),
        "fabric": safe(fabric),
        "disk": safe(disk),
        "sensors": safe(sensors),
        "zones": safe(zones),
        "psi": safe(psi, "/proc/pressure/%s"),
        "cg": safe(engine_cgroup),
    }
    take_pending(sample)
    if is_head:
        candidates = [(info.get("container") or {}).get("port"), port_hint, port[0], "8000", "8888"]
        sample["engine"], sample["engine_error"] = None, "Nothing answers on the vLLM port."
        for candidate in [c for c in candidates if c and c != "auto"]:
            try:
                sample["engine"], sample["hist"] = scrape(candidate)
                sample["engine_error"] = None
                port[0] = candidate
                break
            except Exception:
                continue
    print(json.dumps(sample, separators=(",", ":")), flush=True)
    pause, next_at = rest_until(next_at, time.time())
    time.sleep(pause)
