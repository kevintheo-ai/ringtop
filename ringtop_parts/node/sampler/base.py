# ruff: noqa
"""The sampler: runs on every node as `python3 -u - INTERVAL ROLE PORT REPO SALT` and prints one JSON line per interval.
Its files are joined into one program before they are sent and share one namespace (ringtop_parts/connect/shell.py);
this one holds what all of them use."""

import calendar, ctypes, glob, hashlib, json, os, re, subprocess, sys, threading, time, urllib.request

interval, is_head, port_hint, repo = float(sys.argv[1]), sys.argv[2] == "head", sys.argv[3], sys.argv[4]
salt = sys.argv[5] if len(sys.argv) > 5 else ""


def num(x):
    """The value as a float, or None when it is no number."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rest_until(next_at, now):
    """How long a loop sleeps until its next round is due, and when that is. A round that ended late is not caught
    up: the next one starts at once and the rounds keep their interval from there."""
    return (next_at - now, next_at) if next_at >= now else (0.0, now)


def read(path):
    """The text of a file without the white space around it, or None when it cannot be read. A file that answers
    "try again" is one of these (the clock of a core that sleeps does): Python raises a TypeError for it in a file
    opened as text, no OSError. So is one whose bytes are no text."""
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, TypeError, ValueError):
        return None


def read_int(path):
    """The whole number a file holds, or None."""
    value = read(path)
    return int(value) if value and value.lstrip("-").isdigit() else None
