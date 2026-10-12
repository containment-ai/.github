#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Containment.ai LLC
# SPDX-License-Identifier: LicenseRef-Containment-Commercial
# AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation
# REUSE-IgnoreStart (fixtures below quote header tags; the header above is outside it)
"""Fail-closed mutation tests for scripts/check_headers.py.

SW-REQ-SC-014. Every finding code the checker claims (H001-H010) is driven by a
throwaway git tree carrying ONE mutation, asserted to exit 1 and to name that
code and that file.

CONTROL ARMS: the unmutated fixture exits 0, and so does this repository. A
checker that failed on everything would pass every mutation arm; the controls
are what make the mutations mean something.

Run: python3 scripts/test_check_headers.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
CHECKER = SCRIPTS / "check_headers.py"

COMM = "LicenseRef-Containment-Commercial"
DUAL = "AGPL-3.0-only OR LicenseRef-Containment-Commercial"
AI = "AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation"
NOTICE = "AI-USE: see AI-POLICY.md — notice to AI agents; does not restrict rights granted by the AGPL"


def header(expr: str = COMM, lead: str = "//", years: str = "2026", ai: str = AI) -> str:
    return (f"{lead} SPDX-FileCopyrightText: {years} Containment.ai LLC\n"
            f"{lead} SPDX-License-Identifier: {expr}\n"
            f"{lead} {ai}\n")


CONFIG = header(lead="#") + """\
years = "2026"
holder = "Containment.ai LLC"
default-expression = "LicenseRef-Containment-Commercial"
agpl-ai-use = "{form}"
exempt = ["records/**"]
baseline = "baseline.txt"
"""

REUSE = header(lead="#") + f"""\
version = 1

[[annotations]]
path = "**"
precedence = "closest"
SPDX-FileCopyrightText = "2026 Containment.ai LLC"
SPDX-License-Identifier = "{COMM}"

[[annotations]]
path = "crates/dual/**"
precedence = "override"
SPDX-FileCopyrightText = "2026 Containment.ai LLC"
SPDX-License-Identifier = "{DUAL}"

[[annotations]]
path = "vendor/upstream/**"
precedence = "override"
SPDX-FileCopyrightText = "2024 Upstream Authors"
SPDX-License-Identifier = "MIT"

[[annotations]]
path = "vendor/closest/**"
precedence = "closest"
SPDX-FileCopyrightText = "2023 Other Upstream"
SPDX-License-Identifier = "Apache-2.0"
"""

CLEAN = {
    "REUSE.toml": REUSE,
    "baseline.txt": "# empty baseline\n",
    "src/main.rs": header() + "\nfn main() {}\n",
    "src/tool.py": "#!/usr/bin/env python3\n" + header(lead="#") + "\nprint(1)\n",
    "src/ascii.sh": header(lead="#", ai=AI.replace(" — ", " - ")) + "\necho ok\n",
    "docs/guide.md": header(lead="<!--").replace("\n", " -->\n") + "\n# Guide\n",
    "crates/dual/lib.rs": header(DUAL) + "\npub fn f() {}\n",
    "vendor/upstream/lib.js": "// SPDX-FileCopyrightText: 2024 Upstream Authors\n"
                              "// SPDX-License-Identifier: MIT\n\nmodule.exports = 1;\n",
    "vendor/closest/util.js": "module.exports = 2;\n",  # third-party via a closest annotation
    "records/old.yaml": "# SPDX-License-Identifier: LicenseRef-Proprietary\nkey: 1\n",
    "data.json": "{}\n",
    "notes.txt": "plain text, no comment syntax\n",
    # Prose that MENTIONS a tag mid-line is not a header line.
    "src/prose.md": header(lead="<!--").replace("\n", " -->\n")
                    + "\nUse the `SPDX-License-Identifier: <EXPR>` line.\n",
}


class Fixture(unittest.TestCase):
    form = "d25"

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="check-headers-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.write(".license-headers.toml", CONFIG.format(form=self.form))
        for rel, text in CLEAN.items():
            self.write(rel, text)

    def write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def run_checker(self, *extra: str) -> subprocess.CompletedProcess:
        git = ["git", "-C", str(self.root)]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        return subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root), *extra],
                              capture_output=True, text=True)

    def assertFinding(self, code: str, rel: str) -> None:
        r = self.run_checker()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lines = [l for l in r.stdout.splitlines() if l.startswith(f"{code} {rel}:")]
        self.assertTrue(lines, f"expected {code} on {rel}; got:\n{r.stdout}")

    def assertClean(self) -> None:
        r = self.run_checker()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class ControlArms(Fixture):
    def test_clean_fixture_passes(self) -> None:
        self.assertClean()

    def test_skipped_files_are_counted_not_silent(self) -> None:
        r = self.run_checker()
        self.assertIn("no known comment syntax", r.stdout)
        self.assertIn("exempt glob", r.stdout)
        self.assertIn("REUSE.toml-only type", r.stdout)


class EachRuleFires(Fixture):
    def test_h001_no_header(self) -> None:
        self.write("src/new.rs", "fn new() {}\n")
        self.assertFinding("H001", "src/new.rs")

    def test_h002_missing_ai_line(self) -> None:
        self.write("src/main.rs", "\n".join(header().splitlines()[:2]) + "\nfn main() {}\n")
        self.assertFinding("H002", "src/main.rs")

    def test_h002_lines_out_of_order(self) -> None:
        a, b, c = header().splitlines()
        self.write("src/main.rs", f"{b}\n{a}\n{c}\nfn main() {{}}\n")
        self.assertFinding("H002", "src/main.rs")

    def test_h002_lines_not_consecutive(self) -> None:
        a, b, c = header().splitlines()
        self.write("src/main.rs", f"{a}\n{b}\n// gap\n{c}\nfn main() {{}}\n")
        self.assertFinding("H002", "src/main.rs")

    def test_h003_wrong_years(self) -> None:
        self.write("src/main.rs", header(years="2025") + "fn main() {}\n")
        self.assertFinding("H003", "src/main.rs")

    def test_h003_wrong_holder(self) -> None:
        self.write("src/main.rs", header().replace("Containment.ai LLC", "Someone Else") + "fn main() {}\n")
        self.assertFinding("H003", "src/main.rs")

    def test_h004_agpl_outside_the_dual_tier(self) -> None:
        self.write("src/main.rs", header(DUAL) + "fn main() {}\n")
        self.assertFinding("H004", "src/main.rs")

    def test_h004_commercial_only_inside_the_dual_tier(self) -> None:
        self.write("crates/dual/lib.rs", header(COMM) + "pub fn f() {}\n")
        self.assertFinding("H004", "crates/dual/lib.rs")

    def test_h005_wrong_ai_text(self) -> None:
        self.write("src/main.rs", header(ai="AI-USE: see AI-POLICY.md") + "fn main() {}\n")
        self.assertFinding("H005", "src/main.rs")

    def test_h005_notice_form_is_not_accepted_while_form_is_d25(self) -> None:
        self.write("crates/dual/lib.rs", header(DUAL, ai=NOTICE) + "pub fn f() {}\n")
        self.assertFinding("H005", "crates/dual/lib.rs")

    def test_h006_legacy_marking(self) -> None:
        self.write("src/main.rs", header() + "// Copyright (c) 2026 Containment.ai LLC. All rights reserved.\n")
        self.assertFinding("H006", "src/main.rs")

    def test_h006_legacy_only_header(self) -> None:
        self.write("src/legacy.yaml", "# SPDX-License-Identifier: LicenseRef-Proprietary\nk: 1\n")
        self.assertFinding("H006", "src/legacy.yaml")

    def test_h007_ai_line_on_third_party(self) -> None:
        self.write("vendor/upstream/lib.js", "// SPDX-FileCopyrightText: 2024 Upstream Authors\n"
                                             "// SPDX-License-Identifier: MIT\n// " + AI + "\n")
        self.assertFinding("H007", "vendor/upstream/lib.js")

    def test_h007_our_holder_alone_on_third_party(self) -> None:
        self.write("vendor/upstream/lib.js", "// SPDX-FileCopyrightText: 2026 Containment.ai LLC\n"
                                             "// SPDX-License-Identifier: MIT\n")
        self.assertFinding("H007", "vendor/upstream/lib.js")

    def test_h004_third_party_relabelled(self) -> None:
        self.write("vendor/upstream/lib.js", "// SPDX-FileCopyrightText: 2024 Upstream Authors\n"
                                             f"// SPDX-License-Identifier: {COMM}\n")
        self.assertFinding("H004", "vendor/upstream/lib.js")

    def test_h007_closest_annotation_marks_third_party(self) -> None:
        self.write("vendor/closest/util.js", "// " + AI + "\nmodule.exports = 2;\n")
        self.assertFinding("H007", "vendor/closest/util.js")

    def test_h008_duplicate_licence_line(self) -> None:
        self.write("src/main.rs", header() + f"// SPDX-License-Identifier: {COMM}\nfn main() {{}}\n")
        self.assertFinding("H008", "src/main.rs")

    def test_h009_stale_baseline_entry(self) -> None:
        self.write("baseline.txt", "H001 src/main.rs\n")  # main.rs is clean
        self.assertFinding("H009", "src/main.rs")

    def test_h009_baseline_entry_for_untracked_file(self) -> None:
        self.write("baseline.txt", "H001 src/gone.rs\n")
        self.assertFinding("H009", "src/gone.rs")

    def test_h010_malformed_baseline(self) -> None:
        self.write("baseline.txt", "H999 src/main.rs\n")
        self.assertFinding("H010", "baseline.txt")

    def test_h010_baseline_cannot_excuse_its_own_codes(self) -> None:
        self.write("baseline.txt", "H009 src/main.rs\n")
        self.assertFinding("H010", "baseline.txt")


class Baseline(Fixture):
    def test_baselined_finding_is_excused(self) -> None:
        self.write("src/new.rs", "fn new() {}\n")
        self.write("baseline.txt", "H001 src/new.rs\n")
        self.assertClean()

    def test_baseline_excuses_only_the_named_code(self) -> None:
        self.write("src/main.rs", header(years="2025") + "fn main() {}\n")
        self.write("baseline.txt", "H001 src/main.rs\n")  # wrong code
        self.assertFinding("H003", "src/main.rs")

    def test_write_baseline_round_trips(self) -> None:
        self.write("src/new.rs", "fn new() {}\n")
        r = self.run_checker("--write-baseline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("H001 src/new.rs", (self.root / "baseline.txt").read_text())
        self.assertClean()


class Exemptions(Fixture):
    def test_reuse_ignore_block_is_not_read(self) -> None:
        self.write("src/quote.rs", header() + "// REUSE-" "IgnoreStart\n// SPDX-License-Identifier: X\n"
                                              "// REUSE-" "IgnoreEnd\nfn q() {}\n")
        self.assertClean()

    def test_ignored_header_is_not_a_header(self) -> None:
        self.write("src/main.rs", "// REUSE-" "IgnoreStart\n" + header() + "// REUSE-" "IgnoreEnd\nfn main() {}\n")
        self.assertFinding("H001", "src/main.rs")

    def test_tracked_sidecar_carries_the_header(self) -> None:
        self.write("src/blob.rs", "fn blob() {}\n")
        self.write("src/blob.rs.license", header(lead="").replace("\n ", "\n").lstrip())
        self.assertClean()

    def test_exempt_glob_is_not_inspected(self) -> None:
        self.write("records/new.yaml", "k: 1\n")
        self.assertClean()


class NoticeForm(Fixture):
    form = "notice"

    def test_notice_form_required_on_agpl_files(self) -> None:
        self.assertFinding("H005", "crates/dual/lib.rs")  # still carries the D25 line

    def test_notice_form_accepted_on_agpl_files(self) -> None:
        self.write("crates/dual/lib.rs", header(DUAL, ai=NOTICE) + "pub fn f() {}\n")
        self.assertClean()

    def test_commercial_files_keep_the_d25_line(self) -> None:
        self.write("crates/dual/lib.rs", header(DUAL, ai=NOTICE) + "pub fn f() {}\n")
        self.write("src/main.rs", header(ai=NOTICE) + "fn main() {}\n")
        self.assertFinding("H005", "src/main.rs")


class InputErrors(Fixture):
    def test_missing_config_exits_2(self) -> None:
        (self.root / ".license-headers.toml").unlink()
        self.assertEqual(self.run_checker().returncode, 2)

    def test_bad_form_exits_2(self) -> None:
        self.write(".license-headers.toml", CONFIG.format(form="loose"))
        self.assertEqual(self.run_checker().returncode, 2)

    def test_missing_reuse_toml_exits_2(self) -> None:
        (self.root / "REUSE.toml").unlink()
        self.assertEqual(self.run_checker().returncode, 2)

    def test_missing_baseline_exits_2(self) -> None:
        (self.root / "baseline.txt").unlink()
        self.assertEqual(self.run_checker().returncode, 2)


class Repository(unittest.TestCase):
    def test_this_repository_passes(self) -> None:
        r = subprocess.run([sys.executable, str(CHECKER), "--root", str(REPO)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
# REUSE-IgnoreEnd
