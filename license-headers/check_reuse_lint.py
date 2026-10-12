#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Containment.ai LLC
# SPDX-License-Identifier: LicenseRef-Containment-Commercial
# AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation
"""Run `reuse lint` at the pinned version, and refuse to run any other.

SW-REQ-SC-014 (License Compliance Checking). The `reuse-lint` gate.

`reuse lint` is the REUSE 3.3 conformance check: every file has copyright and
licence information, every licence named has its text in LICENSES/, and no
expression is invalid. scripts/check_reuse_license_map.py and
scripts/check_headers.py check what `reuse lint` cannot see; neither replaces
it, and until this gate no workflow ran it.

The version is pinned (PINNED below, installed hash-locked from the lock file
next to this script, `requirements-reuse.txt`, or the repository's
`.github/requirements/reuse.txt`) because reuse and license-expression decide
which identifiers are valid. A different version can change the verdict with
no change to this repository, so a mismatch is exit 2, not a run.

Exit codes: 0 = compliant; 1 = `reuse lint` reported non-compliance (its
report is printed); 2 = reuse is missing, the wrong version, or did not run.

Run: python3 scripts/check_reuse_lint.py [--root DIR] [--reuse-cmd CMD]
Install: pip install --require-hashes -r <that lock file>
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

PINNED = "6.2.0"
LOCK_CANDIDATES = ("requirements-reuse.txt", "../.github/requirements/reuse.txt")


def install_hint() -> str:
    here = Path(__file__).resolve().parent
    for rel in LOCK_CANDIDATES:
        lock = (here / rel).resolve()
        if lock.is_file():
            return f"pip install --require-hashes -r {lock}"
    return f"pip install reuse=={PINNED} (hash-locked)"
VERSION_RE = re.compile(r"\bversion\s+(\d+(?:\.\d+)+)\b")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", default=".", help="repository root (default: .)")
    ap.add_argument("--reuse-cmd", default=None,
                    help="command that runs reuse (default: this interpreter's `-m reuse`)")
    args = ap.parse_args(argv)
    cmd = shlex.split(args.reuse_cmd) if args.reuse_cmd else [sys.executable, "-m", "reuse"]
    root = str(Path(args.root).resolve())

    try:
        ver = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"check_reuse_lint: ERROR: cannot run reuse ({exc}). Install it: {install_hint()}", file=sys.stderr)
        return 2
    first = (ver.stdout or ver.stderr).splitlines()[0] if (ver.stdout or ver.stderr) else ""
    m = VERSION_RE.search(first)
    if ver.returncode != 0 or not m:
        print(f"check_reuse_lint: ERROR: reuse is not installed or did not report a version "
              f"(rc {ver.returncode}: {first[:120]!r}). Install it: {install_hint()}", file=sys.stderr)
        return 2
    if m.group(1) != PINNED:
        print(f"check_reuse_lint: ERROR: reuse {m.group(1)} found, the gate is pinned to {PINNED}. "
              f"Install it: {install_hint()}", file=sys.stderr)
        return 2

    try:
        lint = subprocess.run(cmd + ["--root", root, "lint"], capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"check_reuse_lint: ERROR: reuse lint did not complete ({exc})", file=sys.stderr)
        return 2
    out = lint.stdout + lint.stderr
    if lint.returncode == 0 and "Congratulations!" in out:
        summary = [l for l in out.splitlines() if l.startswith("* Files with")]
        print("check_reuse_lint: reuse " + PINNED + " lint PASS; " + "; ".join(s[2:] for s in summary))
        return 0
    if lint.returncode == 1:
        print(out)
        print("check_reuse_lint: reuse lint FAIL (REUSE 3.3 non-compliance, report above)", file=sys.stderr)
        return 1
    # Any other outcome (a crash, rc 0 without the compliance line) is not a verdict.
    print(out[-4000:], file=sys.stderr)
    print(f"check_reuse_lint: ERROR: reuse lint returned rc {lint.returncode} without a verdict", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
