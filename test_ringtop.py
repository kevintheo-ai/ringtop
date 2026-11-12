"""Runs every check of ringtop. Run: python3 test_ringtop.py (or pytest)."""

import importlib
import sys
from pathlib import Path


def main() -> int:
    """Runs each test_* function of tests/test_*.py, names the ones that fail and gives back how many did."""
    failed = 0
    for path in sorted((Path(__file__).resolve().parent / "tests").glob("test_*.py")):
        module = importlib.import_module(f"tests.{path.stem}")
        for name, check in sorted(vars(module).items()):
            if name.startswith("test_") and callable(check):
                try:
                    check()
                except Exception as problem:
                    failed += 1
                    print(f"FAIL {name}: {problem!r}")
    print("all checks passed" if not failed else f"{failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
