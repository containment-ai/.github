#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Containment.ai LLC
# SPDX-License-Identifier: LicenseRef-Containment-Commercial
# AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation
# REUSE-IgnoreStart (fixtures below quote header tags; the header above is outside it)
"""Fail-closed tests for scripts/check_reuse_lint.py.

SW-REQ-SC-014. The wrapper must never report a pass it did not measure:

  * reuse absent, the wrong version, or no version line  -> exit 2
  * reuse exits 0 without its compliance line            -> exit 2
  * a PASS without its file counts, or below --min-files  -> exit 2
  * license-expression / boolean.py differ from the lock   -> exit 2
  * a REAL reuse run on a tree with a missing licence    -> exit 1
  * CONTROL: a real run on a compliant tree              -> exit 0
  * REPOSITORY: a real run on this repository            -> exit 0

The real-run arms need reuse installed at the pinned version in this
interpreter. They FAIL rather than skip when it is absent, so the gate cannot
silently stop measuring (install: .github/requirements/requirements-reuse.txt).

Run: python3 scripts/test_check_reuse_lint.py
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
WRAPPER = SCRIPTS / "check_reuse_lint.py"

COMPLIANT_REUSE = """\
version = 1

[[annotations]]
path = "**"
SPDX-FileCopyrightText = "2026 Containment.ai LLC"
SPDX-License-Identifier = "LicenseRef-Test"
"""


# What a real `reuse lint` PASS prints: its population counts, then the verdict.
PASS_OUT = ("* Files with copyright information: 5 / 5\n"
            "* Files with license information: 5 / 5\n\n"
            "Congratulations! Your project is compliant with version 3.3 of the REUSE Specification :-)")


# Complete pinned-format synthetic non-compliance; no repository is scanned.
FAIL_OUT = ("# SUMMARY\n\n"
            "* Files with copyright information: 0 / 5\n"
            "* Files with license information: 5 / 5\n\n"
            "Unfortunately, your project is not compliant with version "
            "3.3 of the REUSE Specification :-(\n\n\n"
            "# RECOMMENDATIONS\n\n* Add the missing copyright information.\n")


def isolated_env(home: Path | None = None) -> dict[str, str]:
    """No global/system git config, as in test_check_headers.py: the verdict must
    depend on the fixture only (templateDir hooks, autocrlf and defaultBranch
    otherwise participate)."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}
    if home is not None:
        env["HOME"] = str(home)
    return env


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(WRAPPER), *args], capture_output=True, text=True, env=env)


class FakeReuse(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="fake-reuse-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def fake(self, version_line: str, lint_rc: int = 0, lint_out: str = "") -> str:
        p = self.dir / "fake_reuse.py"
        p.write_text(
            "import sys\n"
            "if '--version' in sys.argv:\n"
            f"    print({version_line!r}); sys.exit(0)\n"
            f"print({lint_out!r}); sys.exit({lint_rc})\n",
            encoding="utf-8",
        )
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}"

    def test_locale_is_pinned_for_the_verdict(self) -> None:
        # A fake that prints a translated banner unless the wrapper pins the locale.
        p = self.dir / "fake_locale.py"
        p.write_text(
            "import os, sys\n"
            "if '--version' in sys.argv:\n"
            "    print('reuse, version 6.2.0'); sys.exit(0)\n"
            "print('* Files with copyright information: 5 / 5')\n"
            "print('* Files with license information: 5 / 5')\n"
            "print('Congratulations!' if os.environ.get('LC_ALL') == 'C' else 'Herzlichen Glückwunsch!')\n",
            encoding="utf-8")
        r = run("--reuse-cmd", f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_reuse_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", str(self.dir / "no-such-reuse")).returncode, 2)

    def test_wrong_version_exits_2(self) -> None:
        r = run("--reuse-cmd", self.fake("reuse, version 6.1.0", 0, PASS_OUT))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("pinned to 6.2.0", r.stderr)

    def test_no_version_line_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("", 0, PASS_OUT)).returncode, 2)

    def test_rc0_without_verdict_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 0, "")).returncode, 2)

    def test_crash_rc_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 3, "boom")).returncode, 2)

    def test_dev_build_of_the_pinned_version_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0.dev1", 0, PASS_OUT)).returncode, 2)

    def test_post_release_of_the_pinned_version_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0.post1", 0, PASS_OUT)).returncode, 2)

    def test_warning_line_before_the_banner_is_tolerated(self) -> None:
        r = run("--reuse-cmd", self.fake("DeprecationWarning: something\nreuse, version 6.2.0", 0, PASS_OUT))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_lint_failure_exits_1(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 1, FAIL_OUT)).returncode, 1)


    def crashing_reuse(self, prefix: str = "") -> str:
        p = self.dir / "crashing_reuse.py"
        p.write_text("import sys\n"
                     "if '--version' in sys.argv:\n"
                     "    print('reuse, version 6.2.0'); sys.exit(0)\n"
                     f"print({prefix!r})\n"
                     "raise RuntimeError('synthetic REUSE crash')\n", encoding="utf-8")
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}"

    def gated_reuse(self, mode: str, cmd: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "gate_mode.py"),
                               "--mode", mode, str(WRAPPER), "--reuse-cmd", cmd],
                              capture_output=True, text=True)

    def test_child_crash_exit_one_is_not_findings(self) -> None:
        r = run("--reuse-cmd", self.crashing_reuse())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("synthetic REUSE crash", r.stderr)
        self.assertNotIn("lint FAIL (REUSE", r.stderr)

    def test_exit_one_without_output_is_not_findings(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 1)).returncode, 2)

    def test_unknown_exit_one_output_is_not_findings(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 1, "not compliant")).returncode, 2)

    def test_incomplete_noncompliance_report_is_not_findings(self) -> None:
        for report in (FAIL_OUT.replace("# SUMMARY", ""),
                       FAIL_OUT.replace("# RECOMMENDATIONS", ""),
                       FAIL_OUT.replace("* Files with license information: 5 / 5\n", "")):
            with self.subTest(report=report):
                self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 1, report)).returncode, 2)

    def test_inconsistent_noncompliance_counts_are_not_findings(self) -> None:
        for report in (FAIL_OUT.replace("license information: 5 / 5", "license information: 5 / 6"),
                       FAIL_OUT.replace("license information: 5 / 5", "license information: 6 / 5"),
                       FAIL_OUT.replace("# SUMMARY", "# SUMMARY\n# SUMMARY"),
                       FAIL_OUT.replace("* Files with license information: 5 / 5", "* Files with license information: 5 / 5\n* Files with license information: 5 / 5")):
            with self.subTest(report=report):
                self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 1, report)).returncode, 2)

    def test_child_crash_after_complete_report_is_not_findings(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.crashing_reuse(FAIL_OUT)).returncode, 2)

    def test_report_mode_does_not_downgrade_child_crash(self) -> None:
        r = self.gated_reuse("report", self.crashing_reuse())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("::warning::", r.stdout)

    def test_enforce_mode_still_fails_child_crash(self) -> None:
        self.assertEqual(self.gated_reuse("enforce", self.crashing_reuse()).returncode, 2)

    def test_complete_noncompliance_is_reported_in_report_mode(self) -> None:
        r = self.gated_reuse("report", self.fake("reuse, version 6.2.0", 1, FAIL_OUT))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning::", r.stdout)

    def test_complete_noncompliance_still_fails_enforce_mode(self) -> None:
        self.assertEqual(self.gated_reuse("enforce", self.fake("reuse, version 6.2.0", 1, FAIL_OUT)).returncode, 1)

    def test_noncompliance_does_not_apply_the_pass_population_floor(self) -> None:
        r = run("--min-files", "10", "--reuse-cmd", self.fake("reuse, version 6.2.0", 1, FAIL_OUT))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    # Anti-vacuity (Claude review of #2445 at 5729be15, W1).
    def test_reuse_lint_pass_without_file_counts_exits_2(self) -> None:
        r = run("--reuse-cmd", self.fake("reuse, version 6.2.0", 0, "Congratulations!"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("without its file counts", r.stderr)

    def test_reuse_lint_pass_below_min_files_exits_2(self) -> None:
        r = run("--min-files", "6", "--reuse-cmd", self.fake("reuse, version 6.2.0", 0, PASS_OUT))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("below the floor of 6", r.stderr)

    def test_reuse_lint_pass_at_min_files_passes(self) -> None:
        r = run("--min-files", "5", "--reuse-cmd", self.fake("reuse, version 6.2.0", 0, PASS_OUT))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_reuse_lint_one_count_missing_exits_2(self) -> None:
        out = PASS_OUT.replace("* Files with license information: 5 / 5\n", "")
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 0, out)).returncode, 2)

    def test_reuse_lint_zero_min_files_exits_2(self) -> None:
        r = run("--min-files", "0", "--reuse-cmd", self.fake("reuse, version 6.2.0", 0, PASS_OUT))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


class Closure(unittest.TestCase):
    """Claude review W3 at b4706986: license-expression and boolean.py decide the
    verdict too, so their versions are asserted against the lock at gate time."""

    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        # No __pycache__ in the checked repository: a .pyc left behind is an
        # unlicensed file to reuse lint (the org copy's repo does not ignore it).
        prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
        try:
            import check_reuse_lint
        finally:
            sys.dont_write_bytecode = prev
        self.mod = check_reuse_lint
        lock = self.mod.lock_file()
        self.assertIsNotNone(lock)
        self.pins = {}
        for line in lock.read_text(encoding="utf-8").splitlines():
            name, _, rest = line.strip().partition("==")
            if rest:
                self.pins[name.lower()] = rest.split()[0]

    def patched(self, versions: dict[str, str | None]):
        import importlib.metadata as md
        def version(name: str) -> str:
            v = versions.get(name)
            if v is None:
                raise md.PackageNotFoundError(name)
            return v
        return mock.patch("importlib.metadata.version", side_effect=version)

    def test_reuse_lint_locked_closure_is_accepted(self) -> None:
        with self.patched({n: self.pins[n.lower()] for n in self.mod.CLOSURE}):
            self.assertIsNone(self.mod.closure_mismatch())

    def test_reuse_lint_other_license_expression_is_refused(self) -> None:
        v = {n: self.pins[n.lower()] for n in self.mod.CLOSURE}
        v["license-expression"] = "0.0.1"
        with self.patched(v):
            self.assertIn("license-expression 0.0.1 installed", self.mod.closure_mismatch() or "")

    def test_reuse_lint_missing_boolean_py_is_refused(self) -> None:
        v = {n: self.pins[n.lower()] for n in self.mod.CLOSURE}
        v["boolean.py"] = None
        with self.patched(v):
            self.assertIn("boolean.py is not installed", self.mod.closure_mismatch() or "")

    def test_reuse_lint_missing_lock_file_is_refused(self) -> None:
        with mock.patch.object(self.mod, "lock_file", return_value=None):
            self.assertIn("no lock file", self.mod.closure_mismatch() or "")


class RealReuse(unittest.TestCase):
    def tree(self, files: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="reuse-lint-"))
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        self.env = isolated_env(root)
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=self.env)
        return root

    def test_control_compliant_tree_passes(self) -> None:
        root = self.tree({"REUSE.toml": COMPLIANT_REUSE, "LICENSES/LicenseRef-Test.txt": "test licence\n",
                          "a.py": "print(1)\n"})
        r = run("--root", str(root), env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_licence_text_fails(self) -> None:
        root = self.tree({"REUSE.toml": COMPLIANT_REUSE, "a.py": "print(1)\n"})
        r = run("--root", str(root), env=self.env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_unlicensed_file_fails(self) -> None:
        root = self.tree({"LICENSES/LicenseRef-Test.txt": "test licence\n", "a.py": "print(1)\n"})
        r = run("--root", str(root), env=self.env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_this_repository_passes(self) -> None:
        # A floor any real repository clears (the org copy of this file runs it
        # on a 16-file repository); the gate's own floor is in run-prepush-gates.sh.
        r = run("--root", str(REPO), "--min-files", "10")
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
# REUSE-IgnoreEnd
