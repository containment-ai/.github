#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Containment.ai LLC
# SPDX-License-Identifier: LicenseRef-Containment-Commercial
# AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation
# REUSE-IgnoreStart (fixtures below quote header tags; the header above is outside it)
"""Fail-closed tests for scripts/check_reuse_lint.py.

SW-REQ-SC-014. The wrapper must never report a pass it did not measure:

  * reuse absent, the wrong version, or no version line  -> exit 2
  * reuse exits 0 without its compliance line            -> exit 2
  * a REAL reuse run on a tree with a missing licence    -> exit 1
  * CONTROL: a real run on a compliant tree              -> exit 0
  * REPOSITORY: a real run on this repository            -> exit 0

The real-run arms need reuse installed at the pinned version in this
interpreter. They FAIL rather than skip when it is absent, so the gate cannot
silently stop measuring (install: .github/requirements/requirements-reuse.txt).

Run: python3 scripts/test_check_reuse_lint.py
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
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


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(WRAPPER), *args], capture_output=True, text=True)


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
            "print('Congratulations!' if os.environ.get('LC_ALL') == 'C' else 'Herzlichen Glückwunsch!')\n",
            encoding="utf-8")
        r = run("--reuse-cmd", f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_reuse_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", str(self.dir / "no-such-reuse")).returncode, 2)

    def test_wrong_version_exits_2(self) -> None:
        r = run("--reuse-cmd", self.fake("reuse, version 6.1.0", 0, "Congratulations!"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("pinned to 6.2.0", r.stderr)

    def test_no_version_line_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("", 0, "Congratulations!")).returncode, 2)

    def test_rc0_without_verdict_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 0, "")).returncode, 2)

    def test_crash_rc_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 3, "boom")).returncode, 2)

    def test_dev_build_of_the_pinned_version_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0.dev1", 0, "Congratulations!")).returncode, 2)

    def test_post_release_of_the_pinned_version_exits_2(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0.post1", 0, "Congratulations!")).returncode, 2)

    def test_warning_line_before_the_banner_is_tolerated(self) -> None:
        r = run("--reuse-cmd", self.fake("DeprecationWarning: something\nreuse, version 6.2.0", 0,
                                         "Congratulations!"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_lint_failure_exits_1(self) -> None:
        self.assertEqual(run("--reuse-cmd", self.fake("reuse, version 6.2.0", 1, "not compliant")).returncode, 1)


class RealReuse(unittest.TestCase):
    def tree(self, files: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="reuse-lint-"))
        self.addCleanup(shutil.rmtree, root, True)
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        return root

    def test_control_compliant_tree_passes(self) -> None:
        root = self.tree({"REUSE.toml": COMPLIANT_REUSE, "LICENSES/LicenseRef-Test.txt": "test licence\n",
                          "a.py": "print(1)\n"})
        r = run("--root", str(root))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_licence_text_fails(self) -> None:
        root = self.tree({"REUSE.toml": COMPLIANT_REUSE, "a.py": "print(1)\n"})
        r = run("--root", str(root))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_unlicensed_file_fails(self) -> None:
        root = self.tree({"LICENSES/LicenseRef-Test.txt": "test licence\n", "a.py": "print(1)\n"})
        r = run("--root", str(root))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_this_repository_passes(self) -> None:
        r = run("--root", str(REPO))
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
# REUSE-IgnoreEnd
