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

import os
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
path = "crates/one/?.rs"
precedence = "override"
SPDX-FileCopyrightText = "2026 Containment.ai LLC"
SPDX-License-Identifier = "{DUAL}"

[[annotations]]
path = "vendor/joint/**"
precedence = "override"
SPDX-FileCopyrightText = "2022 Upstream Author, 2026 Containment.ai LLC"
SPDX-License-Identifier = "MIT AND LicenseRef-Containment-Commercial"

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
        # The verdict must depend on the fixture only: no global/system git
        # config (a global excludesFile ignoring `.env` would hide a fixture).
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(self.root),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t"}
        self.write(".license-headers.toml", CONFIG.format(form=self.form))
        for rel, text in CLEAN.items():
            self.write(rel, text)

    def write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def run_checker(self, *extra: str, after_stage=None) -> subprocess.CompletedProcess:
        git = ["git", "-C", str(self.root)]
        if not (self.root / ".git").exists():
            subprocess.run(git + ["init", "-q"], check=True, env=self.env)
        subprocess.run(git + ["add", "-A"], check=True, env=self.env)
        if after_stage:
            after_stage()
        return subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root), *extra],
                              capture_output=True, text=True, env=self.env)

    def commit(self) -> None:
        git = ["git", "-C", str(self.root)]
        if not (self.root / ".git").exists():
            subprocess.run(git + ["init", "-q"], check=True, env=self.env)
        subprocess.run(git + ["add", "-A"], check=True, env=self.env)
        subprocess.run(git + ["commit", "-q", "-m", "base"], check=True, env=self.env)

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


class RoundOneRegressions(Fixture):
    """Bypasses found in review of the first revision; each must stay closed."""

    def test_missing_tracked_file_exits_2(self) -> None:
        r = self.run_checker(after_stage=lambda: (self.root / "src/main.rs").unlink())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read a mode-000 file")
    def test_unreadable_tracked_file_exits_2(self) -> None:
        target = self.root / "src/main.rs"
        self.addCleanup(lambda: target.chmod(0o644))
        r = self.run_checker(after_stage=lambda: target.chmod(0))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_leading_blank_lines_do_not_make_a_file_empty(self) -> None:
        self.write("src/blank.py", "\n" * 45 + "print(1)\n")
        self.assertFinding("H001", "src/blank.py")

    def test_ignore_block_over_the_window_does_not_make_a_file_empty(self) -> None:
        self.write("src/hidden.py", "# REUSE-" "IgnoreStart\n" + "x = 1\n" * 50 + "# REUSE-" "IgnoreEnd\n")
        self.assertFinding("H001", "src/hidden.py")

    def test_truly_empty_file_is_skipped(self) -> None:
        self.write("src/empty.py", "\n\n")
        self.assertClean()

    def test_extension_like_dotfile_is_inspected(self) -> None:
        self.write(".env", "KEY=value\n")
        self.assertFinding("H001", ".env")

    def test_question_mark_glob_matches_one_character(self) -> None:
        self.write("crates/one/a.rs", header(COMM) + "fn a() {}\n")
        self.assertFinding("H004", "crates/one/a.rs")

    def test_question_mark_glob_does_not_cross_a_slash(self) -> None:
        self.write("crates/one/ab.rs", header(COMM) + "fn ab() {}\n")
        self.assertClean()

    def test_third_party_legacy_identifier_fires(self) -> None:
        self.write("vendor/upstream/old.js", "// SPDX-FileCopyrightText: 2024 Upstream Authors\n"
                                             "// SPDX-License-Identifier: LicenseRef-Proprietary\n")
        self.assertFinding("H006", "vendor/upstream/old.js")

    def test_third_party_upstream_all_rights_reserved_is_allowed(self) -> None:
        self.write("vendor/upstream/lib.js", "// Copyright (c) 2024 Upstream Authors. All rights reserved.\n"
                                             "// SPDX-License-Identifier: MIT\n")
        self.assertClean()

    def test_third_party_duplicate_licence_line_fires(self) -> None:
        self.write("vendor/upstream/lib.js", "// SPDX-FileCopyrightText: 2024 Upstream Authors\n"
                                             "// SPDX-License-Identifier: MIT\n// SPDX-License-Identifier: MIT\n")
        self.assertFinding("H008", "vendor/upstream/lib.js")

    def test_joint_copyright_annotation_is_third_party(self) -> None:
        self.write("vendor/joint/mixed.js", "// " + AI + "\nmodule.exports = 3;\n")
        self.assertFinding("H007", "vendor/joint/mixed.js")

    def test_prose_quoting_the_legacy_strings_is_not_h006(self) -> None:
        self.write("src/doc.py", header(lead="#") + 'MARK = "All rights reserved"  # LicenseRef-Proprietary\n')
        self.assertClean()

    def test_untracked_file_is_inspected(self) -> None:
        r = self.run_checker(after_stage=lambda: self.write("src/unstaged.rs", "fn u() {}\n"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("H001 src/unstaged.rs:", r.stdout)

    def test_sidecar_replaces_the_file_it_describes(self) -> None:
        self.write("src/both.rs", header() + "fn both() {}\n")
        self.write("src/both.rs.license", header(lead="").replace("\n ", "\n").lstrip())
        self.assertClean()  # one header is read, not two, so no H008

    def test_sidecar_finding_names_the_sidecar(self) -> None:
        self.write("src/blob2.rs", header() + "fn blob2() {}\n")
        self.write("src/blob2.rs.license", "SPDX-License-Identifier: LicenseRef-Containment-Commercial\n")
        r = self.run_checker()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("(read from src/blob2.rs.license)", r.stdout)


class RoundTwoRegressions(Fixture):
    """REUSE 3.3 semantics found in review of the org copy."""

    def test_globstar_slash_matches_at_the_root(self) -> None:
        self.write("REUSE.toml", REUSE + f"""
[[annotations]]
path = "**/*.lua"
precedence = "override"
SPDX-FileCopyrightText = "2026 Containment.ai LLC"
SPDX-License-Identifier = "{DUAL}"
""")
        self.write("top.lua", header(COMM, lead="--") + "return 1\n")
        self.assertFinding("H004", "top.lua")

    def test_only_the_last_matching_annotation_applies(self) -> None:
        # crates/dual/** is an override for DUAL; a LATER closest table for the
        # same file decides instead, so a COMM header is correct there.
        self.write("REUSE.toml", REUSE + f"""
[[annotations]]
path = "crates/dual/later.rs"
precedence = "closest"
SPDX-FileCopyrightText = "2026 Containment.ai LLC"
SPDX-License-Identifier = "{COMM}"
""")
        self.write("crates/dual/later.rs", header(COMM) + "fn later() {}\n")
        self.assertClean()

    def test_nested_reuse_toml_exits_2(self) -> None:
        self.write("sub/REUSE.toml", header(lead="#") + "version = 1\n")
        self.assertEqual(self.run_checker().returncode, 2)


class RoundThreeRegressions(Fixture):
    def test_string_exempt_exits_2(self) -> None:
        self.write(".license-headers.toml", CONFIG.format(form="d25").replace('exempt = ["records/**"]', 'exempt = "records/**"'))
        self.assertEqual(self.run_checker().returncode, 2)

    def test_non_latin_holder_is_third_party(self) -> None:
        self.write("REUSE.toml", REUSE + """
[[annotations]]
path = "vendor/jp/**"
precedence = "override"
SPDX-FileCopyrightText = "2024 株式会社"
SPDX-License-Identifier = "MIT"
""")
        self.write("vendor/jp/lib.js", "// " + AI + "\nmodule.exports = 4;\n")
        self.assertFinding("H007", "vendor/jp/lib.js")

    def test_write_baseline_creates_a_missing_baseline(self) -> None:
        (self.root / "baseline.txt").unlink()
        self.write("src/new.rs", "fn new() {}\n")
        r = self.run_checker("--write-baseline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("H001 src/new.rs", (self.root / "baseline.txt").read_text())


class RoundFourRegressions(Fixture):
    def test_joint_inline_copyright_on_third_party_is_allowed(self) -> None:
        self.write("vendor/upstream/mod.js", "// SPDX-FileCopyrightText: 2024 Upstream Authors and 2026 Containment.ai LLC\n"
                                             "// SPDX-License-Identifier: MIT\n")
        self.assertClean()

    def test_list_valued_expression_is_joined_with_and(self) -> None:
        self.write("REUSE.toml", REUSE + """
[[annotations]]
path = "src/both/**"
precedence = "override"
SPDX-FileCopyrightText = "2026 Containment.ai LLC"
SPDX-License-Identifier = ["MIT", "Apache-2.0"]
""")
        self.write("src/both/x.rs", header("MIT AND Apache-2.0") + "fn x() {}\n")
        self.assertClean()

    def test_licence_text_variants_are_exempt(self) -> None:
        for name in ("LICENCE.md", "LICENSE-MIT.md", "COPYING-GPL.md"):
            self.write(name, "licence text\n")
        self.assertClean()


class Hardening(Fixture):
    """Review of the gate as merged (#2445): misclassification, coverage, growth."""

    def test_notice_words_do_not_make_a_path_third_party(self) -> None:
        self.write("REUSE.toml", REUSE + """
[[annotations]]
path = "src/noticed/**"
precedence = "override"
SPDX-FileCopyrightText = "Copyright (C) 2026 Containment.ai LLC"
SPDX-License-Identifier = "LicenseRef-Containment-Commercial"
""")
        self.write("src/noticed/new.rs", "fn new() {}\n")
        self.assertFinding("H001", "src/noticed/new.rs")

    def test_extensionless_shebang_script_is_inspected(self) -> None:
        self.write("bin/tool", "#!/bin/sh\necho hi\n")
        self.assertFinding("H001", "bin/tool")

    def test_extensionless_non_script_is_not_inspected(self) -> None:
        self.write("bin/data", "plain data\n")
        self.assertClean()

    def test_duplicate_ai_use_line_is_h008(self) -> None:
        self.write("src/main.rs", header() + "// " + AI + "\nfn main() {}\n")
        self.assertFinding("H008", "src/main.rs")

    def test_growth_since_ref_is_h011(self) -> None:
        self.commit()
        self.write("src/new.rs", "fn new() {}\n")
        self.write("baseline.txt", "H001 src/new.rs\n")
        r = self.run_checker("--no-growth-against", "HEAD")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("H011 src/new.rs:", r.stdout)

    def test_growth_is_allowed_when_the_rules_changed(self) -> None:
        self.commit()
        self.write("src/new.rs", "fn new() {}\n")
        self.write("baseline.txt", "H001 src/new.rs\n")
        self.write(".license-headers.toml", CONFIG.format(form="d25") + "# rule change\n")
        r = self.run_checker("--no-growth-against", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("allowed because", r.stdout)

    def test_no_growth_passes_when_unchanged(self) -> None:
        self.write("src/new.rs", "fn new() {}\n")
        self.write("baseline.txt", "H001 src/new.rs\n")
        self.commit()
        r = self.run_checker("--no-growth-against", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_baseline_at_ref_skips_growth(self) -> None:
        (self.root / "baseline.txt").unlink()
        self.commit()
        self.write("src/new.rs", "fn new() {}\n")
        self.write("baseline.txt", "H001 src/new.rs\n")
        r = self.run_checker("--no-growth-against", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("first adoption", r.stdout)

    def test_unknown_ref_exits_2(self) -> None:
        self.commit()
        self.assertEqual(self.run_checker("--no-growth-against", "no-such-ref").returncode, 2)

    def test_h011_cannot_be_baselined(self) -> None:
        self.write("baseline.txt", "H011 src/main.rs\n")
        self.assertFinding("H010", "baseline.txt")


class RoundFiveRegressions(Fixture):
    """Codex + Claude review of #2445 at 9f88612a (follow-up PR)."""

    def test_h006_standalone_all_rights_reserved_line(self) -> None:
        # A D25 header followed by a separate rights-reservation line keeps the
        # prohibited pre-D25 marking even though no single line has both words.
        self.write("src/main.rs", header() + "// Copyright 2026 Containment.ai LLC.\n// All rights reserved.\n"
                   "fn main() {}\n")
        self.assertFinding("H006", "src/main.rs")

    def test_h006_standalone_line_is_not_prose(self) -> None:
        # The sentence mid-paragraph is not a header-shaped line.
        self.write("src/main.rs", header() + "// The vendor says all rights reserved by them, see NOTICE.\n"
                   "fn main() {}\n")
        self.assertClean()

    def test_h001_fires_beside_h006_on_a_legacy_only_header(self) -> None:
        # One H006 baseline entry must not excuse a file that has no D25 header.
        self.write("src/legacy.rs", "// Copyright (c) 2026 Containment.ai LLC. All rights reserved.\nfn f() {}\n")
        self.assertFinding("H001", "src/legacy.rs")
        self.assertFinding("H006", "src/legacy.rs")

    def test_utf8_bom_does_not_hide_the_header(self) -> None:
        p = self.root / "src" / "bom.rs"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xef\xbb\xbf" + (header() + "fn f() {}\n").encode("utf-8"))
        self.assertClean()

    def test_summary_counts_files_under_third_party_rules(self) -> None:
        r = self.run_checker()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # vendor/upstream/lib.js and vendor/closest/util.js are third-party.
        self.assertIn("(2 under third-party rules", r.stdout)
        self.assertIn(", 2 against the third-party rule", r.stdout)


class RoundSixRegressions(Fixture):
    """Claude review of #2445 at 55433aeb, W1: a sidecar exists BECAUSE the file
    it describes cannot carry a header, so a sidecar of a binary or REUSE.toml-only
    file must be inspected. Before the fix both shapes below were skipped."""

    SIDECAR_FULL = header(lead="").replace("\n ", "\n").lstrip()
    SIDECAR_NO_AI = ("SPDX-FileCopyrightText: 2026 Containment.ai LLC\n"
                     "SPDX-License-Identifier: LicenseRef-Containment-Commercial\n")

    def write_png(self, rel: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR")

    def test_headers_sidecar_of_binary_file_is_inspected(self) -> None:
        self.write_png("assets/logo.png")
        self.write("assets/logo.png.license", self.SIDECAR_NO_AI)
        self.assertFinding("H002", "assets/logo.png")

    def test_headers_sidecar_of_reuse_only_type_is_inspected(self) -> None:
        # The production shape: hag-action-contract/testvectors/vectors.json.license.
        self.write("vectors/vectors.json", "{}\n")
        self.write("vectors/vectors.json.license", self.SIDECAR_NO_AI)
        self.assertFinding("H002", "vectors/vectors.json")

    def test_headers_complete_sidecar_of_binary_file_passes(self) -> None:
        self.write_png("assets/logo.png")
        self.write("assets/logo.png.license", self.SIDECAR_FULL)
        self.assertClean()

    def test_headers_sidecar_under_exempt_glob_stays_exempt(self) -> None:
        self.write("records/blob.bin", "x\n")
        self.write("records/blob.bin.license", self.SIDECAR_NO_AI)
        self.assertClean()

    def test_headers_binary_without_sidecar_is_still_skipped(self) -> None:
        self.write_png("assets/logo.png")
        self.assertClean()


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


class RoundSevenRegressions(Fixture):
    """Codex + Claude review of #2445 at 5729be15: a binary sidecar must fail
    closed, and neither a config floor nor a CLI floor may let a collapsed file
    population read as clean (anti-vacuity, Claude W1)."""

    def inspected(self) -> int:
        r = self.run_checker()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return int(r.stdout.split("inspected ", 1)[1].split(" ", 1)[0])

    def config_with(self, line: str) -> None:
        self.write(".license-headers.toml", CONFIG.format(form="d25") + line + "\n")

    def test_headers_binary_sidecar_exits_2(self) -> None:
        # Codex's reproduction: a headerless source file plus a NUL-byte sidecar.
        self.write("src/new.rs", "fn new() {}\n")
        (self.root / "src" / "new.rs.license").write_bytes(b"\0not a license\n")
        r = self.run_checker()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("new.rs.license is binary", r.stderr)

    def test_headers_population_below_config_floor_exits_2(self) -> None:
        self.config_with(f"min-inspected = {self.inspected() + 1}")
        r = self.run_checker()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("below the floor", r.stderr)

    def test_headers_population_at_config_floor_passes(self) -> None:
        self.config_with(f"min-inspected = {self.inspected()}")
        self.assertClean()

    def test_headers_population_below_cli_floor_exits_2(self) -> None:
        r = self.run_checker("--min-inspected", str(self.inspected() + 1))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_headers_cli_floor_overrides_config_floor(self) -> None:
        self.config_with("min-inspected = 100000")
        self.assertEqual(self.run_checker("--min-inspected", "1").returncode, 0)

    def test_headers_write_baseline_below_floor_exits_2_and_keeps_baseline(self) -> None:
        # Codex connector on containment-ai/.github#7 at 5b0f05c8.
        before = (self.root / "baseline.txt").read_text(encoding="utf-8")
        self.config_with(f"min-inspected = {self.inspected() + 1}")
        r = self.run_checker("--write-baseline")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual((self.root / "baseline.txt").read_text(encoding="utf-8"), before)

    def skipped_by_type(self) -> int:
        r = self.run_checker()
        return int(r.stdout.split(" no known comment syntax", 1)[0].rsplit(" ", 1)[1])

    def test_headers_uninspected_type_above_cap_exits_2(self) -> None:
        # Claude review W1 at b4706986: a commentable type the checker does not
        # know (here .gradle) is skipped; the cap turns that into exit 2.
        n = self.skipped_by_type()
        self.config_with(f"max-uninspected-by-type = {n}")
        self.assertClean()
        self.write("tools/build.gradle", "apply plugin: 'java'\n")
        r = self.run_checker()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("tools/build.gradle", r.stderr)

    def test_headers_third_party_population_mismatch_exits_2(self) -> None:
        # Claude review W2 at b4706986: a REUSE.toml edit that makes first-party
        # paths read as third-party must not exempt them silently.
        self.config_with("third-party = 2")
        self.assertClean()  # vendor/upstream/lib.js + vendor/closest/util.js
        self.config_with("third-party = 3")
        r = self.run_checker()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("third-party = 3", r.stderr)

    def test_headers_malformed_population_pin_exits_2(self) -> None:
        # 2.0 equals the fixture's third-party count and 1000.0 exceeds its skips,
        # so only type validation can reject them (the rest fail later anyway).
        for bad in ("third-party = 2.0", "max-uninspected-by-type = 1000.0",
                    "third-party = -1", 'third-party = "7"', "max-uninspected-by-type = true"):
            with self.subTest(bad=bad):
                self.config_with(bad)
                self.assertEqual(self.run_checker().returncode, 2, bad)

    def test_headers_zero_or_malformed_floor_exits_2(self) -> None:
        for bad in ("min-inspected = 0", "min-inspected = -3", 'min-inspected = "10"', "min-inspected = true"):
            with self.subTest(bad=bad):
                self.config_with(bad)
                self.assertEqual(self.run_checker().returncode, 2, bad)
        self.config_with("min-inspected = 1")
        self.assertEqual(self.run_checker("--min-inspected", "0").returncode, 2)


class Repository(unittest.TestCase):
    def test_this_repository_passes(self) -> None:
        r = subprocess.run([sys.executable, str(CHECKER), "--root", str(REPO)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-4000:] + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
# REUSE-IgnoreEnd
