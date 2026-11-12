# ruff: noqa
"""What the node works on besides the engine: the lab queue, processes, the journal, the biggest users of GPU and
memory, the cores."""


def lab():
    """The experiment window of the lab (who holds the ring) and its queue of runs, by state."""
    path = os.path.expanduser("~/spark-hold.json")
    try:
        with open(path) as f:
            hold = json.load(f)
    except (OSError, ValueError):
        hold = None
    queue = {}
    if repo != "-":
        for state, sub in (("pending", ""), ("running", "running"), ("done", "done"), ("failed", "failed")):
            found = glob.glob(os.path.join(repo, "results", "private", "lab", "queue", sub, "*.json"))
            queue[state] = sorted(os.path.basename(p) for p in found)
    return {"hold": hold, "queue": queue}


# a flag or field whose name has a word like key, token or secret, also inside hyphens (--secret-access-key, --db-pass);
# whole words only, so --max-num-batched-tokens and --tokenizer-mode stay readable; JSON ("token": "x") and quotes count too.
# One name is one run of [\w.-], so the pattern stays linear even on a hostile 6000-character line.
SECRET = re.compile(
    r'(?i)(bearer\s+|(?<![\w.-])(?=[\w.-]*?(?<![a-z0-9])(?:api[-_]?key|key|token|secret|password|passwd|pass|pwd|credentials?)(?![a-z0-9]))[\w.-]+["\']?(?:\s*[=:]\s*|\s+))(?:"[^"]*"|\'[^\']*\'|[^\s"\',;}]+)|\b(?:sk-|hf_)[A-Za-z0-9_-]{8,}'
)
ENV_SHOW = re.compile(
    r"^(NCCL_|VLLM_|CUDA_|SPARK_|SPARKNET_|OMP_|MKL_|OPENBLAS_|UCX_|TORCH_|PYTORCH_|MALLOC_|RAY_|TILELANG_)"
)
ENV_SECRET = re.compile(r"(?i)(key|token|secret|pass|pwd|credential|auth|cookie|session|private|signature|salt|cert)")
ENV_OPAQUE = re.compile(
    r"://[^/@\s]+@|[A-Za-z0-9+/_=-]{33,}|\bhf_[A-Za-z0-9]{8,}|\bsk-[A-Za-z0-9]{8,}"
    # what looks random: 16+ hex with letters and digits, or 20+ characters mixing upper, lower and digits
    r"|(?<![0-9A-Fa-f])(?=[0-9A-Fa-f]*[A-Fa-f])(?=[0-9A-Fa-f]*\d)[0-9A-Fa-f]{16,}|(?<![\w-])(?=[\w-]*[a-z])(?=[\w-]*[A-Z])(?=[\w-]*\d)[\w-]{20,}"
)


def env_view(env):
    """The environment of the container for the page: name -> ["v", value] for harmless settings, ["h", digest] for
    everything else. The digest only says same or different."""
    out = {}
    for pair in env:
        name, _, value = pair.partition("=")
        # the value is checked too: a harmless name can hold {"password": "x"}; a value hidden by mistake costs only the sight of it
        plain = (
            ENV_SHOW.match(name)
            and not ENV_SECRET.search(name + " " + value)
            and not SECRET.search(value)
            and not ENV_OPAQUE.search(value)
            and "{" not in value
        )
        out[name] = (
            ["v", value[:300]] if plain else ["h", hashlib.sha256((salt + "\0" + value).encode()).hexdigest()[:24]]
        )
    return out


WORK = re.compile(r"servebench|bin/spark bench|lab\.py (run|queue run)|lab_idle_start")


def processes():
    """Benchmark and lab processes on this node, with their age. Only the program's name leaves the node: a command line
    can hold keys. None where ps did not answer or ended with an error: that is not a node without such processes."""
    try:
        done = subprocess.run(["ps", "-eo", "etimes=,args="], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if done.returncode:
        return None
    out = []
    for line in done.stdout.splitlines():
        seconds, _, args = line.strip().partition(" ")
        found = WORK.search(args)
        if found and "ringtop" not in args and seconds.isdigit():
            out.append({"seconds": int(seconds), "command": found.group(0)})
    return out[:6]


JOURNAL = re.compile(r"NVRM: Xid|Out of memory|oom-kill|Killed process|hung_task|page allocation failure", re.I)
journal_at = [time.time() - 86400]


def journal():
    """What the kernel and the memory guard said since the last look; the first look covers a day."""
    start, began, read_all = int(journal_at[0]), time.time(), True
    out = []
    for args, kind in ((["-k"], "kernel"), (["-t", "spark-memguard"], "memguard")):
        try:
            done = subprocess.run(
                ["journalctl", *args, "-S", "@%d" % start, "-o", "short-unix", "--no-pager", "-q"],
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception:
            read_all = False  # look at this window again next time
            continue
        read_all = read_all and done.returncode == 0
        for line in done.stdout.splitlines():
            stamp, _, rest = line.partition(" ")
            if num(stamp) is not None and (kind == "memguard" or JOURNAL.search(rest)):
                out.append({"t": num(stamp), "kind": kind, "text": rest.partition(": ")[2][:160]})
    if read_all:
        journal_at[0] = began
    return sorted(out, key=lambda e: e["t"])[-40:]


def gpu_apps():
    """The programs on the GPU, each with the memory it holds. None where nvidia-smi did not answer or ended with an
    error: that is not a GPU without programs."""
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=used_memory,process_name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=6,
        )
    except Exception:
        return None
    if done.returncode:
        return None
    out = []
    for line in done.stdout.splitlines():
        mib, _, name = line.partition(",")
        if num(mib.strip()) is not None:
            out.append({"gb": round(num(mib.strip()) / 1024, 1), "name": name.strip()[:40]})
    return out


def biggest():
    """The four programs that hold the most memory. Names only, never arguments. None where ps did not answer or
    ended with an error."""
    try:
        done = subprocess.run(["ps", "-eo", "rss=,comm=", "--sort=-rss"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if done.returncode:
        return None
    out = []
    for line in done.stdout.splitlines()[:4]:
        rss, _, name = line.strip().partition(" ")
        if rss.isdigit():
            out.append({"gb": round(int(rss) / 2**20, 1), "name": name[:40]})
    return out


clock = {}


def slow_facts():
    """The readings that change slowly: memory pressure, the clock limits of the GPU, the programs on the GPU, the
    biggest ones in memory, and the journal."""
    for key, field in (("mhz_max", "clocks.max.sm"), ("mhz_app", "clocks.applications.graphics")):
        if key not in clock:  # asked again until the driver answers once; a timeout is no answer
            try:
                done = subprocess.run(
                    ["nvidia-smi", "--query-gpu=" + field, "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=6,
                )
                if done.returncode == 0:
                    clock[key] = num(done.stdout.strip())
            except Exception:
                pass
    pressure = re.search(r"some avg10=([\d.]+)", read("/proc/pressure/memory") or "")
    return {
        "psi": float(pressure.group(1)) if pressure else None,
        "mhz_max": clock.get("mhz_max"),
        "mhz_app": clock.get("mhz_app"),
        "apps": gpu_apps(),
        "top": biggest(),
        "journal": journal(),
    }


last_cores = {}


def cores():
    """Busy percent of every CPU core since the last call. None where /proc/stat could not be read: that is not a
    machine without cores, and the call after it counts no figure across the hole."""
    text = read("/proc/stat")
    if text is None:
        last_cores.clear()
        return None
    out = []
    for line in text.splitlines():
        if not re.match(r"cpu\d", line):
            continue
        name, *rest = line.split()
        v = [int(x) for x in rest[:8]]
        idle, total = v[3] + v[4], sum(v)
        before = last_cores.get(name)
        last_cores[name] = (idle, total)
        out.append(
            round(100 * (1 - (idle - before[0]) / (total - before[1]))) if before and total > before[1] else None
        )
    return out
