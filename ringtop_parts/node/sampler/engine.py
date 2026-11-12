# ruff: noqa
"""The engine as the node sees it: the vLLM metrics of a port, the container docker shows, and the engine a Spark runs
on its own."""

LINE = re.compile(r"^vllm:([\w:]+)(?:\{(.*)\})?\s+(\S+)")
KEEP = set(
    (
        "num_requests_running num_requests_waiting kv_cache_usage_perc generation_tokens_total prompt_tokens_total "
        "prompt_tokens_cached_total iteration_tokens_total_count iteration_tokens_total_sum "
        "spec_decode_num_accepted_tokens_total spec_decode_num_draft_tokens_total prefix_cache_queries_total "
        "prefix_cache_hits_total num_preemptions_total"
    ).split()
)
for name in (
    "e2e_request_latency_seconds",
    "request_queue_time_seconds",
    "request_prefill_time_seconds",
    "request_decode_time_seconds",
    "request_prompt_tokens",
    "request_generation_tokens",
):
    KEEP.update((name + "_sum", name + "_count"))
KEEP.update(
    (
        "spec_decode_num_drafts_total scheduler_prefill_compute_share scheduler_local_prefill_backlog_tokens "
        "sink_draft_cuts_total sink_draft_zero_rejections_total sink_fallthroughs_total sink_flagged_rows_total "
        "request_prefill_kv_computed_tokens_sum request_prefill_kv_computed_tokens_count "
        "request_inference_time_seconds_sum request_inference_time_seconds_count request_num_preemptions_sum "
        "request_params_max_tokens_sum request_params_max_tokens_count"
    ).split()
)
BY_LABEL = {
    "prompt_tokens_by_source_total": "source",
    "request_success_total": "finished_reason",
    "engine_sleep_state": "sleep_state",
    "spec_decode_num_accepted_tokens_per_pos_total": "position",
    "spec_decode_num_draft_tokens_per_pos_total": "position",
    "num_requests_waiting_by_reason": "reason",
    "scheduler_compute_pressure": "class",
}
HISTOGRAMS = (
    "time_to_first_token_seconds_bucket",
    "inter_token_latency_seconds_bucket",
    "request_queue_time_seconds_bucket",
    "e2e_request_latency_seconds_bucket",
    "request_prefill_time_seconds_bucket",
    "request_decode_time_seconds_bucket",
    "request_time_per_output_token_seconds_bucket",
    "iteration_tokens_total_bucket",
    "request_prompt_tokens_bucket",
    "request_generation_tokens_bucket",
    "request_prefill_kv_computed_tokens_bucket",
)
PLAIN = re.compile(
    r"^(http_requests_total|process_resident_memory_bytes|process_cpu_seconds_total|process_open_fds|process_start_time_seconds)(?:\{(.*)\})?\s+(\S+)"
)
CACHE_LABELS = (
    "kv_cache_size_tokens",
    "kv_cache_memory_bytes",
    "num_gpu_blocks",
    "block_size",
    "gpu_memory_utilization",
    "kv_cache_max_concurrency",
)


def plain_metric(line, values):
    """A line that is no vllm: figure. What every Python server tells about its process is kept, and HTTP requests
    are added up by method, route and status."""
    plain = PLAIN.match(line)
    if plain and num(plain.group(3)) is not None:
        label = dict(re.findall(r'(\w+)="([^"]*)"', plain.group(2) or ""))
        key = (
            plain.group(1)
            if plain.group(1) != "http_requests_total"
            else "http:%s %s %s" % (label.get("method"), label.get("handler"), label.get("status"))
        )
        values[key] = values.get(key, 0.0) + num(plain.group(3))


def cache_config(labels, values):
    """The size of the KV cache, which vLLM tells as labels of one line and not as a figure."""
    label = dict(re.findall(r'(\w+)="([^"]*)"', labels))
    for wanted in CACHE_LABELS:
        if num(label.get(wanted)) is not None:
            values["cache:" + wanted] = num(label[wanted])
    if "cache:kv_cache_size_tokens" in values:
        values["kv_size_tokens"] = values["cache:kv_cache_size_tokens"]


def vllm_metric(name, labels, value, values, hist):
    """One vllm: figure goes where it belongs: a counter that is kept (added up over its labels), one that is kept
    per label, a bucket of a histogram, or the cache's size. Everything else is left out."""
    if name in KEEP:
        values[name] = values.get(name, 0.0) + value
    elif name in BY_LABEL:
        label = re.search(BY_LABEL[name] + '="([^"]*)"', labels)
        if label:
            key = name + ":" + label.group(1)
            values[key] = values.get(key, 0.0) + value
    elif name in HISTOGRAMS:
        le = re.search('le="([^"]*)"', labels)
        if le:
            bucket = hist.setdefault(name[:-7], {})
            bucket[le.group(1)] = bucket.get(le.group(1), 0.0) + value
    elif name == "cache_config_info":
        cache_config(labels, values)


def metrics(text):
    """What a /metrics text of vLLM says: the figures by name, and the histograms by name and bucket. A value that
    is no number, or not a number at all (NaN), is left out."""
    values, hist = {}, {}
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            plain_metric(line, values)
            continue
        value = num(m.group(3))
        if value is None or value != value:
            continue
        vllm_metric(m.group(1), m.group(2) or "", value, values, hist)
    return values, hist


SCRAPE_LIMIT = 3.0  # seconds: for every step of the socket, and for the pieces of an answer since the question began


def scrape(port):
    """Reads /metrics of the engine on this port of this machine. A port where something else answers is an error:
    another service must never be taken for vLLM. The answer is read piece by piece, and has failed when a piece
    comes later than SCRAPE_LIMIT seconds after the question began, when no piece comes for SCRAPE_LIMIT seconds
    (the limit of the socket for one step), or when it ends before the length it named."""
    # ponytail: no limit over the whole question. The time since it began is looked at only when a piece of the body
    # has come: an answer that falls silent is ended by the socket up to SCRAPE_LIMIT seconds after its last piece
    # (just under twice the limit in all when its head came within it), and connecting and the head of the answer
    # keep the limit of the socket per step. A limit over all of it needs a socket loop of our own, worth it once an
    # engine is seen to send its head in slow pieces or to fall silent in its answer
    until, pieces = time.monotonic() + SCRAPE_LIMIT, []
    with urllib.request.urlopen("http://127.0.0.1:%s/metrics" % port, timeout=SCRAPE_LIMIT) as r:
        while True:
            piece = r.read1(65536)
            if not piece:
                break
            pieces.append(piece)
            if time.monotonic() > until:
                raise OSError("the answer took longer than %s s" % SCRAPE_LIMIT)
        # what is left of the length the answer named (None where it named none: chunked, or to the end of the
        # connection). read() raised when an answer ended with bytes left; read1() just comes back empty
        if r.length:
            raise OSError("the answer ended %s bytes before the length it named" % r.length)
    text = b"".join(pieces).decode("utf-8", "replace")
    values, hist = metrics(text)
    if not (values or hist) or not re.search(r"^vllm:", text, re.M):  # what any server says of its process is no engine
        raise ValueError("something else answers on this port")
    return values, hist


def fetch(port, path):
    """The JSON one path of the engine's port answers with, or None."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%s%s" % (port, path), timeout=3) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def published(item, inside):
    """The host port docker published a container port on, on this machine. Read, never guessed."""
    for bind in ((item.get("NetworkSettings") or {}).get("Ports") or {}).get("%s/tcp" % inside) or []:
        if bind.get("HostIp") in ("127.0.0.1", "0.0.0.0", "") and str(bind.get("HostPort") or "").isdigit():
            return str(bind["HostPort"])
    return None


def container():
    """The engine container as docker shows it, the running one with the cluster label before any other: its image,
    arguments with secrets hidden, settings and published port. None without docker or without an engine container;
    when docker does not answer in time, the container of the last look."""
    try:
        names = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=8
        ).stdout.split()
        if not names:
            return None
        items = json.loads(
            subprocess.run(["docker", "inspect"] + names, capture_output=True, text=True, timeout=8).stdout or "[]"
        )
    except Exception:
        return box_now[0]  # a look that failed says nothing new: the container of the last look stands
    best = None
    for item in items:
        labels = item.get("Config", {}).get("Labels") or {}
        image = item.get("Config", {}).get("Image", "")
        if "spark.cluster-config" in labels or "ds41f" in item.get("Name", "") or "vllm" in image.lower():
            rank = (bool(item.get("State", {}).get("Running")), "spark.cluster-config" in labels)
            if best is None or rank > best[0]:
                best = (rank, item, labels, image)
    if not best:
        return None
    _, item, labels, image = best
    args = item.get("Args") or []

    def arg(flag):
        for at, word in enumerate(args):  # vLLM takes both: --port 9000 and --port=9000
            if word == flag and at + 1 < len(args):
                return args[at + 1]
            if word.startswith(flag + "="):
                return word[len(flag) + 1 :]
        return None

    state = item.get("State", {})
    shown = " ".join(args)
    layers = None
    try:  # the image id depends on the storage driver; the list of layer digests does not
        done = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{json .RootFS.Layers}}", item.get("Image") or image],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if done.returncode == 0 and done.stdout.strip():
            layers = hashlib.sha256(done.stdout.strip().encode()).hexdigest()[:12]
    except Exception:
        pass
    return {
        "name": item.get("Name", "").lstrip("/"),
        "id": item.get("Id"),
        "image": image,
        "running": bool(state.get("Running")),
        "image_id": (item.get("Image") or "")[7:19],
        "layers": layers,
        "cpuset": (item.get("HostConfig") or {}).get("CpusetCpus"),
        "args": SECRET.sub(r"\1***", shown)[:6000],
        "env": env_view((item.get("Config") or {}).get("Env") or []),
        "status": state.get("Status"),
        "started": state.get("StartedAt"),
        "config": labels.get("spark.cluster-config"),
        "port": arg("--port"),
        "model": arg("--served-model-name"),
        "max_len": arg("--max-model-len"),
        "published": published(item, arg("--port") or "8000"),
    }  # vLLM listens on 8000 unless told otherwise


def own_target(box, engine_port):
    """The port to ask a Spark's own engine at, or None. Its own engine is a running vLLM container that is not the ring
    engine, asked only at the port docker published for it. No published port, no question: a port is never guessed
    and never looked for."""
    if not box or not box.get("running") or box.get("config") or not box.get("published"):
        return None
    return (
        None if box["published"] == engine_port else box["published"]
    )  # the head reads that port as the engine already


def own_reading(box, target):
    """What its own engine counts at the published port, with the model and the name of its container. An engine that
    does not answer is said so, not left out."""
    out = {"model": box.get("model"), "name": box.get("name"), "engine": None, "hist": {}}
    try:
        out["engine"], out["hist"] = scrape(target)
    except Exception:
        out["error"] = "Nothing answers on its published port."
    return out


OWN_EVERY, own_last = 2.0, [None]


def own_pause():
    """Seconds until its own engine may be asked again, 0 when a question is due: at most every 2 s by the clock, and
    never more often than samples can carry the answers. A round that comes late is followed by a full wait: a
    question never catches up."""
    if own_last[0] is None:
        return 0.0
    return max(0.0, max(OWN_EVERY, interval) - (time.monotonic() - own_last[0]))


def own_round():
    """One question to its own engine, or None when there is none to ask. One look at the box: the port asked and the
    name given belong to the same container. What it read waits in `pending` for the next sample, with the moment it
    was asked for; a newer reading takes the place of one no sample took."""
    box = box_now[0]
    target = own_target(box, port[0])
    if not target:
        return None
    own_last[0] = time.monotonic()
    asked = time.time()  # before the question: an answer that takes long must not move the moment of its reading
    reading = own_reading(box, target)
    reading["t"] = asked  # it becomes a rate: it needs its own moment, not the one of the sample that carries it
    pending["own"] = reading
    return reading


def own_loop():
    """The thread of its own engine: a port that hangs holds this thread for the 3 s it waits, never the samples.
    Without an engine to ask it looks again every second."""
    while True:
        wait = own_pause()
        if wait <= 0 and safe(own_round) is None:
            wait = 1.0
        if wait > 0:
            time.sleep(wait)
