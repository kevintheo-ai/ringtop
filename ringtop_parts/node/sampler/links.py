# ruff: noqa
"""The ring links in detail: the RDMA counters of every port, and what ethtool says about each cable."""

RDMA_DETAIL = (
    "out_of_sequence",
    "packet_seq_err",
    "local_ack_timeout_err",
    "req_transport_retries_exceeded",
    "rnr_nak_retry_err",
    "roce_adp_retrans",
    "roce_slow_restart",
    "out_of_buffer",
)
CABLE_COUNTERS = (
    "rx_pause_ctrl_phy",
    "tx_pause_ctrl_phy",
    "tx_global_pause_duration",
    "rx_global_pause_duration",
    "tx_pause_storm_warning_events",
    "tx_pause_storm_error_events",
    "rx_discards_phy",
    "tx_discards_phy",
    "rx_crc_errors_phy",
    "rx_pcs_symbol_err_phy",
    "rx_symbol_err_phy",
    "rx_corrected_bits_phy",
    "rx_err_lane_0_phy",
    "rx_err_lane_1_phy",
    "rx_buffer_passed_thres_phy",
    "outbound_pci_stalled_rd",
    "outbound_pci_stalled_wr",
    "outbound_pci_stalled_rd_events",
    "outbound_pci_stalled_wr_events",
    "link_down_events_phy",
    "tx_bytes_phy",
    "rx_bytes_phy",
    "rx_vport_rdma_unicast_bytes",
    "tx_vport_rdma_unicast_bytes",
)


def rdma_counters():
    """Every counter of every PCIe function in one 5 ms call. None where the call failed: what it printed then, or
    did not print, is no reading of a ring without devices."""
    done = subprocess.run(["rdma", "-j", "statistic", "show"], capture_output=True, text=True, timeout=4)
    if done.returncode:
        return None
    out = {}
    for row in json.loads(done.stdout or "[]"):
        if row.get("ifname"):
            out[row["ifname"]] = {k: v for k, v in row.items() if isinstance(v, (int, float)) and k != "port"}
    return out


def cable_counters():
    """The counters of each cable: ethtool for one function of each physical port, because the *_phy counters of both
    functions are the same cable."""
    out = {}
    for d in sorted(glob.glob("/sys/class/infiniband/*")):
        group = re.search(r"f(\d+)$", os.path.basename(d))
        key = "f" + group.group(1) if group else os.path.basename(d)
        nets = glob.glob(d + "/device/net/*")
        if key in out or not nets:
            continue
        name = os.path.basename(nets[0])
        row = {}
        text = subprocess.run(["ethtool", "-S", name], capture_output=True, text=True, timeout=4).stdout
        for line in text.splitlines():
            k, _, value = line.strip().partition(": ")
            if k in CABLE_COUNTERS:
                row[k] = num(value)
        fec = subprocess.run(
            ["ethtool", "--include-statistics", "--show-fec", name], capture_output=True, text=True, timeout=4
        ).stdout
        for k, value in re.findall(r"^\s*(corrected_blocks|uncorrectable_blocks|corrected_bits):\s*(\d+)", fec, re.M):
            row[k] = int(value)
        out[key] = row
    return out


def link_detail():
    """Hardware counters per PCIe function, in the shape the deep view has always read. None where they could not
    be read."""
    counters = rdma_counters()
    if counters is None:
        return None
    return {dev: {c: row.get(c) for c in row} for dev, row in counters.items()}
