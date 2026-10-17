#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Containment.ai LLC
# SPDX-License-Identifier: LicenseRef-Containment-Commercial
# AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation
"""Fail-closed tests for gate_mode.py, the reusable workflow's `mode` input.

SW-REQ-SC-014. mode=report may downgrade a findings verdict and nothing else:

  * CRASH: a tool that raises (exit 1, no verdict line)       -> fails in report
  * CRASH after printing a verdict-shaped line                -> fails in report
  * exit 2, death by a signal                                 -> fails in report
  * exit 1 with the verdict line                              -> 0 in report, 1 in enforce
  * REAL check_headers.py on a tree with a finding            -> 0 in report, 1 in enforce
  * REAL check_reuse_lint.py on a non-compliant tree          -> 0 in report, 1 in enforce
  * a bad mode or an unknown tool                             -> exit 2

The real-run arms prove the verdict patterns still match what the tools print.
The reuse arm needs reuse installed at the pinned version, as in
test_check_reuse_lint.py; it fails rather than skips without it.

Run: python3 license-headers/test_gate_mode.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
GATE = SCRIPTS / "gate_mode.py"

sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True  # no __pycache__ left in the checked tree
import test_check_headers as tch  # noqa: E402
import test_check_reuse_lint as tcrl  # noqa: E402


def gate(mode: str, tool: Path | str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATE), "--mode", mode, str(tool), *args],
                          capture_output=True, text=True, env=env)


class FakeTool(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="gate-mode-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def tool(self, body: str, name: str = "check_headers.py") -> Path:
        p = self.dir / name
        p.write_text("import os, signal, sys\n" + body, encoding="utf-8")
        return p

    def test_crash_fails_in_report_mode(self) -> None:
        for name in ("check_headers.py", "check_reuse_lint.py"):
            with self.subTest(name):
                t = self.tool("raise RuntimeError('injected crash')\n", name)
                r = gate("report", t)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("RuntimeError: injected crash", r.stderr)
                self.assertIn("::error::", r.stdout)
                self.assertNotIn("::warning::", r.stdout)

    def test_crash_after_a_verdict_line_fails_in_report_mode(self) -> None:
        t = self.tool("print('check_headers: 3 finding(s)', file=sys.stderr)\n"
                      "raise RuntimeError('injected crash')\n")
        r = gate("report", t)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_exit_2_fails_in_report_mode(self) -> None:
        r = gate("report", self.tool("sys.exit(2)\n"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_signal_fails_in_report_mode(self) -> None:
        r = gate("report", self.tool("os.kill(os.getpid(), signal.SIGKILL)\n"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_findings_verdict_is_downgraded_in_report_mode_only(self) -> None:
        t = self.tool("print('H001 a.py: no header')\n"
                      "print('check_headers: 1 finding(s)', file=sys.stderr)\nsys.exit(1)\n")
        r = gate("report", t)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("H001 a.py", r.stdout)
        self.assertIn("::warning::", r.stdout)
        self.assertEqual(gate("enforce", t).returncode, 1)

    def test_clean_run_passes_in_both_modes(self) -> None:
        t = self.tool("sys.exit(0)\n")
        self.assertEqual(gate("report", t).returncode, 0)
        self.assertEqual(gate("enforce", t).returncode, 0)

    def test_bad_mode_exits_2(self) -> None:
        self.assertEqual(gate("warn", self.tool("sys.exit(0)\n")).returncode, 2)

    def test_unknown_tool_exits_2(self) -> None:
        self.assertEqual(gate("report", self.tool("sys.exit(1)\n", "other.py")).returncode, 2)


class RealCheckHeaders(tch.Fixture):
    def test_real_findings_are_downgraded_in_report_mode(self) -> None:
        self.write("src/bare.rs", "fn bare() {}\n")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True, env=self.env)
        r = gate("enforce", tch.CHECKER, "--root", str(self.root), env=self.env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("H001 src/bare.rs", r.stdout)
        r = gate("report", tch.CHECKER, "--root", str(self.root), env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::per-file header check", r.stdout)


class RealReuseLint(unittest.TestCase):
    def test_real_non_compliance_is_downgraded_in_report_mode(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="gate-mode-reuse-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "LICENSES").mkdir()
        (root / "LICENSES/LicenseRef-Test.txt").write_text("test licence\n", encoding="utf-8")
        (root / "a.py").write_text("print(1)\n", encoding="utf-8")  # no licence information
        self.env = tcrl.isolated_env(root)
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=self.env)
        r = gate("enforce", tcrl.WRAPPER, "--root", str(root), env=self.env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        r = gate("report", tcrl.WRAPPER, "--root", str(root), env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::reuse lint", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
