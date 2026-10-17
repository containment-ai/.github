#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Containment.ai LLC
# SPDX-License-Identifier: LicenseRef-Containment-Commercial
# AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation
"""Run one gate tool and apply the reusable workflow's `mode` input to its exit.

SW-REQ-SC-014. Used by .github/workflows/license-headers.yml for both gates
(check_reuse_lint.py and check_headers.py).

mode=enforce: the tool's exit status is returned unchanged.

mode=report: exit 1 becomes exit 0 with a warning annotation, but ONLY when
the tool's last line on stderr is its own findings verdict (VERDICTS below).
An unhandled exception also exits 1, so a bare exit 1 is not proof of
findings: without the verdict line it stays a failure. Exit 2 (could not
measure, or misconfigured), death by a signal and every other status fail in
either mode.

Run: python3 gate_mode.py --mode enforce|report TOOL [TOOL ARGS...]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# The line each tool prints last, on stderr, when (and only when) it exits 1
# with findings. test_gate_mode.py proves each still matches the real tool.
VERDICTS = {
    "check_headers.py": (re.compile(r"check_headers: \d+ finding\(s\)"),
                         "per-file header check: findings (listed above)"),
    "check_reuse_lint.py": (re.compile(r"check_reuse_lint: reuse lint FAIL \(REUSE 3\.3 non-compliance, report above\)"),
                            "reuse lint: the caller is not REUSE 3.3 compliant (report above)"),
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[0] != "--mode":
        print("gate_mode: ERROR: usage: gate_mode.py --mode enforce|report TOOL [ARGS...]", file=sys.stderr)
        return 2
    mode, tool, rest = args[1], args[2], args[3:]
    if mode not in ("enforce", "report"):
        print(f"::error::mode must be enforce or report, got '{mode}'")
        return 2
    if Path(tool).name not in VERDICTS:
        print(f"gate_mode: ERROR: no findings verdict known for {tool!r}", file=sys.stderr)
        return 2
    verdict, what = VERDICTS[Path(tool).name]

    # stdout passes straight through; stderr is captured to read the verdict
    # line, then replayed.
    proc = subprocess.run([sys.executable, tool, *rest], stderr=subprocess.PIPE, text=True)
    sys.stdout.flush()
    sys.stderr.write(proc.stderr)
    sys.stderr.flush()
    rc = proc.returncode
    if rc < 0:
        print(f"::error::{Path(tool).name} was killed by signal {-rc}")
        return 2
    if rc != 1 or mode == "enforce":
        return rc
    last = next((l.strip() for l in reversed(proc.stderr.splitlines()) if l.strip()), "")
    if verdict.fullmatch(last):
        print(f"::warning::{what}. mode=report, so this does not fail the job.")
        return 0
    print(f"::error::{Path(tool).name} exited 1 without its findings verdict (last stderr line: {last[:200]!r}); "
          f"that is a crash, not findings, so mode=report does not downgrade it")
    return 1


if __name__ == "__main__":
    sys.exit(main())
