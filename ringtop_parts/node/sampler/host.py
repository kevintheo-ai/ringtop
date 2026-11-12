# ruff: noqa
"""What the node says without any tool: CPU, memory, sensors, disk and the ring ports, read from /proc and /sys."""

last_cpu = None


def cpu_percent():
    """How busy the CPUs were since the last call, in percent. None the first time, and where /proc/stat could not
    be read: the call after that has nothing to count from either, a made-up line of zeros would give it the load
    since boot."""
    global last_cpu
    text = read("/proc/stat")
    if text is None:
        last_cpu = None
        return None
    v = [int(x) for x in text.splitlines()[0].split()[1:9]]
    idle, total = v[3] + (v[4] if len(v) > 4 else 0), sum(v)
    out = None
    if last_cpu and total > last_cpu[1]:
        out = round(100 * (1 - (idle - last_cpu[0]) / (total - last_cpu[1])), 1)
    last_cpu = (idle, total)
    return out


def cpu_temp():
    """The warmest thermal zone in degrees Celsius, or None."""
    temps = [read_int(p) for p in glob.glob("/sys/class/thermal/thermal_zone*/temp")]
    temps = [t for t in temps if t and t > 0]
    return round(max(temps) / 1000, 1) if temps else None


def memory():
    """Total and available memory in bytes."""
    out = {}
    for line in (read("/proc/meminfo") or "").splitlines():
        key, _, value = line.partition(":")
        if key in ("MemTotal", "MemAvailable"):
            out[key] = int(value.split()[0]) * 1024
    return out


def sensors():
    """Fans, and the temperatures of SSD, network card and Wi-Fi: hwmon knows what nvidia-smi does not. The fans
    come in the order of their folders, and one whose speed could not be read keeps its place, as None."""
    out = {"fans": [], "nvme_c": None, "nic_c": None, "wifi_c": None, "nvme_alarm": 0, "nic_peak": None}
    for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = read(h + "/name") or ""
        if name == "acpi_fan":
            out["fans"].append(read_int(h + "/fan1_input"))
            continue
        milli = read_int(h + "/temp1_input")
        if milli is None:
            continue
        c = round(milli / 1000, 1)
        if name == "nvme":
            out["nvme_c"] = c
            out["nvme_alarm"] = read_int(h + "/temp1_alarm") or 0
        elif name == "mlx5":
            out["nic_c"] = max(out["nic_c"] or 0, c)
            peak = read_int(h + "/temp1_highest")
            if peak:
                out["nic_peak"] = max(out["nic_peak"] or 0, round(peak / 1000, 1))
        elif name.startswith("mt79"):
            out["wifi_c"] = c
    return out


def disk():
    """Sectors read and written on the NVMe drives since boot, and the free and total space of the root file system.
    The sectors are None where no NVMe drive is listed or the list could not be read: no drive is no count of zero."""
    sectors = None
    for line in (read("/proc/diskstats") or "").splitlines():
        f = line.split()
        if len(f) > 9 and re.fullmatch(r"nvme\d+n\d+", f[2]):
            sectors = sectors or [0, 0]
            sectors[0] += int(f[5])
            sectors[1] += int(f[9])
    out = {"read": sectors[0] if sectors else None, "write": sectors[1] if sectors else None}
    try:
        fs = os.statvfs("/")
    except OSError:
        return out
    out.update(free=fs.f_bavail * fs.f_frsize, total=fs.f_blocks * fs.f_frsize)
    return out


LINK_ERRORS = ("link_downed", "link_error_recovery", "symbol_error", "port_rcv_errors", "port_xmit_discards")
RDMA_ERRORS = ("out_of_sequence", "packet_seq_err", "local_ack_timeout_err", "req_transport_retries_exceeded")


def counts(paths):
    """The whole numbers the counter files at these paths hold, one for each file that is there: None for one that
    could not be read or holds no number. A path without a file adds nothing: a device that has no such counter is
    not a device whose counter nobody read."""
    out = []
    for path in paths:
        try:
            with open(path) as f:
                text = f.read().strip()
        except FileNotFoundError:
            continue
        except Exception:
            out.append(None)
            continue
        out.append(int(text) if text.lstrip("-").isdigit() else None)
    return out


def fabric():
    """The counters of every RDMA port: data sent and received, whether the link is up, its rate and its errors. A
    port is named with what was read of it: a field that could not be read is None, never 0 and never "down", and
    the port is never left out for it. A state file that reads empty said nothing, which is not read: down is one
    that says something other than ACTIVE. Left out is only a device that has no counters of its traffic at all."""
    out = {}
    for d in sorted(glob.glob("/sys/class/infiniband/*")):
        port = d + "/ports/1/"
        data = counts([port + "counters/port_xmit_data", port + "counters/port_rcv_data"])
        if len(data) < 2:
            continue
        state, rate = read(port + "state"), re.match(r"([\d.]+)", read(port + "rate") or "")
        errors = counts(
            [port + "counters/" + c for c in LINK_ERRORS] + [port + "hw_counters/" + c for c in RDMA_ERRORS]
        )
        out[os.path.basename(d)] = {
            "tx": data[0],
            "rx": data[1],
            "up": "ACTIVE" in state if state else None,
            "rate": float(rate.group(1)) if rate else None,
            "err": sum(errors) if errors and None not in errors else None,
        }
    return out
