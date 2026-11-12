# ruff: noqa
"""Reads the speed of past runs from the engine logs that are already on the head node, one line per 10 s, and prints
them as one-minute averages and peaks. Runs there once, as `python3 - DAYS`."""

import calendar, glob, gzip, json, os, re, subprocess, sys, time

LINE = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S* .*Avg prompt throughput: ([\d.]+) tokens/s, Avg generation throughput: ([\d.]+) tokens/s, Running: (\d+) reqs, Waiting: (\d+) reqs, GPU KV cache usage: ([\d.]+)%, Prefix cache hit rate: ([\d.]+)"
)
cutoff, minutes = time.time() - int(sys.argv[1]) * 86400, {}


def run(*cmd):
    """The output of one command, with whatever is not UTF-8 replaced."""
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120).stdout


def take(line):
    """Keeps one throughput line of an engine log under its minute, when it is one and not older than the days asked
    for."""
    m = LINE.match(line)
    if m:
        t = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
        if t >= cutoff:
            minutes.setdefault(t // 60 * 60, []).append([float(x) for x in m.groups()[1:]])


names = [n for n in run("docker", "ps", "--format", "{{.Names}}").split() if "ds41f" in n or "vllm" in n]
engine = set()
for part in (run("docker", "inspect", "--format", "{{.HostConfig.CpusetCpus}}", *names).strip() if names else "").split(
    ","
):
    a, _, b = part.strip().partition("-")
    if a.isdigit():
        engine.update(range(int(a), int(b or a) + 1))
rest = set(os.sched_getaffinity(0)) - engine
if rest:
    os.sched_setaffinity(0, rest)  # one core of the ones the engine does not use
for path in sorted(glob.glob(os.path.expanduser("~/ds41f-logs/*.log.gz"))):
    if os.path.getmtime(path) >= cutoff:
        with gzip.open(path, "rt", errors="replace") as f:
            for line in f:
                take(line)
for name in names:
    for line in run("docker", "logs", "--timestamps", name).splitlines():
        take(line)
print(
    json.dumps(
        {str(t): [[sum(c) / len(c), max(c)] for c in zip(*rows)] for t, rows in minutes.items()}, separators=(",", ":")
    )
)
