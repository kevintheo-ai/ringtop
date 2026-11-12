# ruff: noqa
"""Finds the spark-ds41f checkout on the head node and prints what ringtop needs of it as JSON: the node map, the
profile of the running engine, its memory guard and its shape. Runs there once, as `python3 - REPO`."""

import glob, json, os, socket, subprocess, sys


def run(*cmd):
    """The output of one command, or nothing when it fails or takes longer than 8 s."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return ""


config = ""
try:
    names = run("docker", "ps", "--format", "{{.Names}}").split()
    for item in json.loads(run("docker", "inspect", *names) or "[]") if names else []:
        config = (item.get("Config", {}).get("Labels") or {}).get("spark.cluster-config") or config
except ValueError:
    pass

wanted = sys.argv[1]
roots = (
    [wanted]
    if wanted != "-"
    else sorted(glob.glob(os.path.expanduser("~/projects/spark-ds41f*")), key=os.path.getmtime, reverse=True)
)
roots = [r for r in roots if os.path.isfile(os.path.join(r, "config", "nodes.json"))]
repo = next((r for r in roots if config and os.path.isfile(os.path.join(r, config))), roots[0] if roots else None)

guard, shape = None, None
path = os.path.join(repo, config) if repo and config else None
for _ in range(6):  # a profile extends another one
    if not path or not os.path.isfile(path):
        break
    with open(path) as f:
        cluster = json.load(f)
    host = dict(cluster.get("host") or {}, **((cluster.get("set") or {}).get("host") or {}))
    guard = guard if guard is not None else host.get("memguard_gib")
    parent = cluster.get("extends") or {}
    shape = shape or parent.get("shape") or cluster.get("default_shape")
    path = os.path.join(repo, parent["config"]) if parent.get("config") else None

nodes = None
if repo:
    with open(os.path.join(repo, "config", "nodes.json")) as f:
        nodes = json.load(f)
print(
    json.dumps(
        {
            "repo": repo,
            "nodes": nodes,
            "config": config,
            "memguard_gib": guard,
            "shape": shape,
            "hostname": socket.gethostname(),
        }
    )
)
