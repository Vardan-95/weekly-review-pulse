"""Full regression suite runner — Doc/Evaluation/Phase6-Orchestration-
Hardening.md: "Run all Phase 1-5 test suites together in CI against the
assembled system."

Confirmed by hand (2026-08-30): a single `pytest` invocation given all six
phase directories at once fails to collect every phase after the first —
each phase folder defines its own top-level `pulse` AND `tests` package
(`tests/__init__.py`), so the first phase pytest imports wins those two
names in `sys.modules`/`sys.path` for the rest of the process, and every
other phase's `from pulse import ...` / `tests.test_*` imports then resolve
against the wrong phase (or fail outright) — the exact collision
`pulse/integration/phase_loader.py` exists to solve for Phase 6's own code.
Retrofitting that alias trick onto five already-frozen, already-verified
phases' test files just to let one shared pytest process import all of them
isn't worth doing — the standard, correct answer for "several independent
Python packages that happen to share top-level names" is to give each its
own process. This script does exactly that: one `python -m pytest`
subprocess per phase directory, run in-process isolation, results
aggregated into a single pass/fail summary a CI job can key off of.

Usage: `python scripts/run_full_regression.py` from anywhere (paths are
resolved relative to this file, not the current working directory).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PHASE_DIRS = [
    "Phase1-Foundations",
    "Phase2-Ingestion-Safety",
    "Phase3-Reasoning",
    "Phase4-Rendering",
    "Phase5-MCP-Delivery",
    "Phase6-Orchestration-Hardening",
]


def main() -> int:
    results: list[tuple[str, int, str]] = []

    for phase in PHASE_DIRS:
        phase_dir = REPO_ROOT / phase
        print(f"\n=== {phase} ===", flush=True)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(phase_dir),
            capture_output=True,
            text=True,
        )
        print(proc.stdout)
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
        last_line = next((line for line in reversed(proc.stdout.strip().splitlines()) if line.strip()), "")
        results.append((phase, proc.returncode, last_line))

    print("\n=== Full regression summary ===")
    all_ok = True
    for phase, code, last_line in results:
        status = "PASS" if code == 0 else "FAIL"
        if code != 0:
            all_ok = False
        print(f"{status:4} {phase:30} {last_line}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
