#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Containment.ai LLC
# SPDX-License-Identifier: LicenseRef-Containment-Commercial
# AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation
# REUSE-IgnoreStart (this file quotes header tags; the header above is outside it)
"""Per-file D25 header gate: every hand-written source file states its own licence.

SW-REQ-SC-014 (License Compliance Checking). Owner decision D25 (2026-10-07).

`reuse lint` cannot see any of what this checks. A repository whose REUSE.toml
has a `**` default is compliant to `reuse lint` even if no file carries a
header, carries the wrong one, or carries a pre-D25 "All rights reserved" line.
This gate reads the first lines of every tracked text file and enforces the
three-line header:

    SPDX-FileCopyrightText: <years> <holder>
    SPDX-License-Identifier: <expression>
    AI-USE: see AI-POLICY.md — <notice>

Repository-agnostic. Everything repository-specific comes from two places:

  * `.license-headers.toml` at the repository root: years, holder, default
    expression, the AI-USE form for AGPL files, extra exempt globs, and the
    path of the baseline file.
  * The repository's own `REUSE.toml`. The EXPECTED licence expression of a
    file is what REUSE.toml's last matching `precedence = "override"`
    annotation assigns it, else the configured default. Annotations whose
    copyright does not name the holder mark THIRD-PARTY paths. This checker
    adds no tier map of its own: the tiers stay where `reuse lint` reads them.

Finding codes (each is proven able to fire by scripts/test_check_headers.py):

  H001  no header: none of the three lines in the header window
  H002  incomplete header: the three lines are not all present, in order, on
        consecutive lines
  H003  copyright line is not exactly `<years> <holder>`
  H004  licence expression differs from the one REUSE.toml assigns the path
  H005  AI-USE line is not the canonical text for the file's tier
  H006  pre-D25 marking (`LicenseRef-Proprietary`, "All rights reserved") in
        the header window
  H007  third-party file carries our AI-USE line or names only our holder
  H008  a second copyright or licence tag line in the header window
  H009  baseline entry is stale: the file is gone, or no longer has that finding
  H010  baseline entry names an unknown code or is malformed

Files the gate does not inspect (counted and printed, never silent):
  * binary files; JSON/JSONC/JSON5/JSONL; lockfiles; licence texts; the
    AI-policy and AI-instruction files; CHANGELOGs (HEADER-SPEC section 5)
  * paths matching a configured `exempt` glob
  * file types with no known comment syntax

THE BASELINE. Existing files that predate the gate, or whose bytes must not
change (accepted decision records, signed bundles, fixtures), are listed per
finding code in the baseline file. A baselined (code, path) pair is excused;
any OTHER finding on the same file still fires, so a baseline entry is not an
exemption. The baseline only shrinks: an entry that no longer matches a real
finding is itself a finding (H009), so a fixed file must also leave the list.
`--write-baseline` regenerates it from the current tree; review that diff, it
is the only way to grow the list.

Exit codes: 0 = no findings; 1 = at least one finding (each printed);
2 = inputs could not be read.

Run: python3 scripts/check_headers.py [--root DIR] [--write-baseline]
Standard library only (Python 3.11+, for tomllib).
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".license-headers.toml"
WINDOW = 40  # lines read per file; matches the D25 counter and HEADER-SPEC placement

# Canonical AI-USE texts. D25 is the HEADER-SPEC line 3, used on every tier by
# default. NOTICE is the notice-only form for AGPL-licensed files; it applies
# only where a repository's config opts in with agpl-ai-use = "notice", and
# whether to opt in is that repository's licensing decision, not this script's.
AI_USE_D25 = "AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation"
AI_USE_NOTICE = "AI-USE: see AI-POLICY.md — notice to AI agents; does not restrict rights granted by the AGPL"


def _ascii(text: str) -> str:
    # HEADER-SPEC section 1: files that must stay ASCII use " - " for the em dash.
    return text.replace(" — ", " - ")


CODES = {
    "H001": "no header",
    "H002": "incomplete or out-of-order header",
    "H003": "copyright line differs from the canonical text",
    "H004": "licence expression differs from REUSE.toml",
    "H005": "AI-USE line differs from the canonical text for this tier",
    "H006": "pre-D25 marking in the header",
    "H007": "third-party file carries our marking",
    "H008": "duplicate copyright or licence line",
    "H009": "stale baseline entry",
    "H010": "malformed baseline entry",
}

# Files covered by REUSE.toml instead of an inline header (HEADER-SPEC section 5).
BUILTIN_EXEMPT = (
    "*.json", "*.jsonc", "*.json5", "*.jsonl", "*.ndjson",
    "*.lock", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "go.sum",
    "LICENSES/*", "LICENSE", "LICENSE.*", "COPYING", "COPYING.*", "NOTICE", "NOTICE.*",
    "AI-POLICY.md", "AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md", ".cursor/rules/*",
    "CHANGELOG*", "*.license", ".gitkeep", ".keep",
)

# Extension or exact basename -> True when the format has a comment syntax that
# can carry the header (HEADER-SPEC section 2). Anything else is not inspected.
COMMENT_EXT = {
    # //
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx", ".rs", ".go", ".c", ".h",
    ".cc", ".cpp", ".hpp", ".java", ".kt", ".kts", ".swift", ".dart", ".scala", ".proto",
    ".cedar",
    # #
    ".py", ".sh", ".bash", ".zsh", ".yaml", ".yml", ".toml", ".rb", ".pl", ".r", ".tf", ".hcl",
    ".rego", ".ps1", ".cfg", ".conf", ".env", ".example", ".template", ".tpl", ".service", ".yar",
    # /* */
    ".css", ".scss", ".less",
    # <!-- -->
    ".html", ".htm", ".xml", ".xsd", ".svg", ".md", ".mdx", ".mdc", ".vue", ".svelte",
    # --
    ".sql", ".lua", ".hs", ".adb", ".ads",
    # ;
    ".ini", ".clj", ".asm", ".reg",
    # %
    ".tex", ".erl", ".m",
    # REM
    ".bat", ".cmd",
}
COMMENT_NAMES = {
    "Dockerfile", "Makefile", "Justfile", ".gitignore", ".gitattributes", ".dockerignore",
    ".editorconfig", ".npmrc", ".nvmrc",
}

# A tag counts only at the start of a line, after an optional comment opener.
# Prose that merely mentions a tag mid-sentence is not a header line.
_LEAD = r"^\s*(?:#+|//+|/\*+|\*|<!--|--|;+|%+|REM)?\s*"
_TRAIL = r"\s*(?:\*/|-->)?\s*$"
COPY_RE = re.compile(_LEAD + r"SPDX-FileCopyrightText:\s*(.*?)" + _TRAIL)
LIC_RE = re.compile(_LEAD + r"SPDX-License-Identifier:\s*(.*?)" + _TRAIL)
AI_RE = re.compile(_LEAD + r"(AI-USE:.*?)" + _TRAIL)
LEGACY_RE = re.compile(r"LicenseRef-Proprietary|All rights reserved", re.IGNORECASE)
# REUSE ignores everything between its Ignore-Start/End markers; so does this gate.
# Split literals, so neither REUSE nor this file reads its own markers as markers.
IGNORE_START, IGNORE_END = "REUSE-" "IgnoreStart", "REUSE-" "IgnoreEnd"


@dataclass
class Config:
    years: str
    holder: str
    default_expression: str
    agpl_ai_use: str
    exempt: tuple[str, ...]
    baseline: str


@dataclass
class Annotation:
    patterns: list[re.Pattern]
    precedence: str
    copyright: str
    expression: str


@dataclass
class Report:
    findings: list[tuple[str, str, str]] = field(default_factory=list)  # (code, path, detail)
    checked: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


class InputError(Exception):
    pass


# --- REUSE.toml ---------------------------------------------------------------

def reuse_glob(pattern: str) -> re.Pattern:
    """REUSE 3.3 path globbing: `**` crosses `/`, `*` does not, `\\*` is literal."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("\\*", i):
            out.append(re.escape("*"))
            i += 2
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def load_annotations(root: Path) -> list[Annotation]:
    path = root / "REUSE.toml"
    if not path.is_file():
        raise InputError("REUSE.toml not found; this gate resolves tiers from it")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InputError(f"REUSE.toml unreadable: {exc}") from exc
    out = []
    for ann in data.get("annotations", []):
        paths = ann.get("path", [])
        if isinstance(paths, str):
            paths = [paths]
        cr = ann.get("SPDX-FileCopyrightText", "")
        if isinstance(cr, list):
            cr = "\n".join(cr)
        out.append(Annotation(
            patterns=[reuse_glob(p) for p in paths],
            precedence=ann.get("precedence", "closest"),
            copyright=cr,
            expression=str(ann.get("SPDX-License-Identifier", "")),
        ))
    return out


def resolve(path: str, annotations: list[Annotation], cfg: Config) -> tuple[str, bool]:
    """(expected expression, third_party) for a path. REUSE uses the last match."""
    last_any = None
    last_override = None
    for ann in annotations:
        if any(p.match(path) for p in ann.patterns):
            last_any = ann
            if ann.precedence == "override":
                last_override = ann
    third_party = last_any is not None and cfg.holder not in last_any.copyright
    if last_override is not None:
        return last_override.expression, third_party
    if third_party:
        return last_any.expression, True
    return cfg.default_expression, False


# --- config and baseline --------------------------------------------------------

def load_config(root: Path) -> Config:
    path = root / CONFIG_NAME
    if not path.is_file():
        raise InputError(f"{CONFIG_NAME} not found at the repository root")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InputError(f"{CONFIG_NAME} unreadable: {exc}") from exc
    missing = [k for k in ("years", "holder", "default-expression") if not data.get(k)]
    if missing:
        raise InputError(f"{CONFIG_NAME} lacks {', '.join(missing)}")
    form = data.get("agpl-ai-use", "d25")
    if form not in ("d25", "notice"):
        raise InputError(f'{CONFIG_NAME}: agpl-ai-use must be "d25" or "notice", got {form!r}')
    return Config(
        years=str(data["years"]),
        holder=str(data["holder"]),
        default_expression=str(data["default-expression"]),
        agpl_ai_use=form,
        exempt=tuple(data.get("exempt", [])),
        baseline=str(data.get("baseline", "")),
    )


def read_baseline(root: Path, cfg: Config, report: Report) -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()
    if not cfg.baseline:
        return entries
    path = root / cfg.baseline
    if not path.is_file():
        raise InputError(f"baseline {cfg.baseline} named in {CONFIG_NAME} does not exist")
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0] not in CODES or parts[0] in ("H009", "H010"):
            report.findings.append(("H010", cfg.baseline, f"line {n}: {raw!r}"))
            continue
        entries.add((parts[0], parts[1]))
    return entries


# --- per-file inspection --------------------------------------------------------

def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputError(f"git ls-files failed: {exc}") from exc
    return sorted(p for p in out.decode("utf-8", "surrogateescape").split("\0") if p)


def glob_match(path: str, patterns: tuple[str, ...]) -> bool:
    name = path.rsplit("/", 1)[-1]
    for pat in patterns:
        if "/" in pat:
            if reuse_glob(pat).match(path):
                return True
        elif fnmatch.fnmatchcase(name, pat):
            return True
    return False


def commentable(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in COMMENT_NAMES or name.startswith("Dockerfile."):
        return True
    dot = name.rfind(".")
    return dot > 0 and name[dot:].lower() in COMMENT_EXT


def head_lines(path: Path) -> list[str] | None:
    """First WINDOW lines with REUSE-Ignore blocks blanked, or None if binary/unreadable."""
    try:
        with path.open("rb") as fh:
            raw = fh.read(65536)
    except OSError:
        return None
    if b"\0" in raw[:8000]:
        return None
    lines = raw.decode("utf-8", "replace").splitlines()[:WINDOW]
    out, ignoring = [], False
    for line in lines:
        if IGNORE_START in line:
            ignoring = True
        out.append("" if ignoring else line)
        if IGNORE_END in line:
            ignoring = False
    return out


def inspect(rel: str, lines: list[str], expected: str, third_party: bool, cfg: Config) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    copies = [(i, m.group(1)) for i, l in enumerate(lines) if (m := COPY_RE.match(l))]
    lics = [(i, m.group(1)) for i, l in enumerate(lines) if (m := LIC_RE.match(l))]
    ais = [(i, m.group(1)) for i, l in enumerate(lines) if (m := AI_RE.match(l))]
    legacy = [i for i, l in enumerate(lines) if LEGACY_RE.search(l)]

    if third_party:
        if ais:
            found.append(("H007", f"AI-USE line on line {ais[0][0] + 1} of a third-party file"))
        if copies and all(cfg.holder in c for _, c in copies):
            found.append(("H007", f"only {cfg.holder} named as copyright holder of a third-party file"))
        if lics and lics[0][1] != expected:
            found.append(("H004", f"{lics[0][1]!r}, REUSE.toml says {expected!r}"))
        return found

    if legacy:
        found.append(("H006", f"line {legacy[0] + 1}: {lines[legacy[0]].strip()[:80]!r}"))
    if len(copies) > 1 or len(lics) > 1:
        found.append(("H008", f"{len(copies)} copyright and {len(lics)} licence lines"))
    if not copies and not lics and not ais:
        if not legacy:
            found.append(("H001", "no SPDX-FileCopyrightText, SPDX-License-Identifier or AI-USE line"))
        return found
    if not (copies and lics and ais) or not (lics[0][0] == copies[0][0] + 1 and ais[0][0] == copies[0][0] + 2):
        have = [n for n, xs in (("copyright", copies), ("licence", lics), ("AI-USE", ais)) if xs]
        found.append(("H002", f"have {', '.join(have) or 'none'}; need all three on consecutive lines in that order"))
    if copies and copies[0][1] != f"{cfg.years} {cfg.holder}":
        found.append(("H003", f"{copies[0][1]!r}, expected {cfg.years + ' ' + cfg.holder!r}"))
    if lics and lics[0][1] != expected:
        found.append(("H004", f"{lics[0][1]!r}, REUSE.toml says {expected!r}"))
    if ais:
        want = AI_USE_NOTICE if (cfg.agpl_ai_use == "notice" and "AGPL" in expected) else AI_USE_D25
        if ais[0][1] not in (want, _ascii(want)):
            found.append(("H005", f"{ais[0][1]!r}, expected {want!r}"))
    return found


def run(root: Path) -> tuple[Report, list[tuple[str, str]]]:
    cfg = load_config(root)
    annotations = load_annotations(root)
    report = Report()
    baseline = read_baseline(root, cfg, report)
    files = tracked_files(root)
    tracked = set(files)
    raw: list[tuple[str, str, str]] = []
    for rel in files:
        if glob_match(rel, BUILTIN_EXEMPT):
            report.skip("REUSE.toml-only type (HEADER-SPEC section 5)")
            continue
        if cfg.exempt and glob_match(rel, cfg.exempt):
            report.skip(f"exempt glob in {CONFIG_NAME}")
            continue
        if not commentable(rel):
            report.skip("no known comment syntax")
            continue
        lines = head_lines(root / rel)
        if lines is None:
            report.skip("binary or unreadable")
            continue
        sidecar = rel + ".license"
        if sidecar in tracked:
            side = head_lines(root / sidecar) or []
            lines = side + lines
        if not any(l.strip() for l in lines):
            report.skip("empty")
            continue
        report.checked += 1
        expected, third_party = resolve(rel, annotations, cfg)
        for code, detail in inspect(rel, lines, expected, third_party, cfg):
            raw.append((code, rel, detail))
    current = {(c, p) for c, p, _ in raw}
    for code, rel, detail in raw:
        if (code, rel) not in baseline:
            report.findings.append((code, rel, detail))
    for code, rel in sorted(baseline - current):
        why = "file is no longer tracked" if rel not in tracked else "finding no longer occurs; remove the entry"
        report.findings.append(("H009", rel, f"baseline {code}: {why}"))
    return report, sorted(current)


def write_baseline(root: Path, current: list[tuple[str, str]]) -> Path:
    cfg = load_config(root)
    if not cfg.baseline:
        raise InputError(f"{CONFIG_NAME} names no baseline file")
    path = root / cfg.baseline
    head = (
        "# SPDX-FileCopyrightText: " + f"{cfg.years} {cfg.holder}\n"
        "# SPDX-License-Identifier: " + cfg.default_expression + "\n"
        "# " + AI_USE_D25 + "\n"
        "#\n"
        "# Header-gate baseline (scripts/check_headers.py). One `<code> <path>` per line.\n"
        "# Each entry excuses ONE finding on ONE file; any other finding on that file\n"
        "# still fails. Shrink-only: an entry that no longer matches a finding fails\n"
        "# the gate (H009). Regenerate with `--write-baseline` and review the diff.\n"
    )
    body = "".join(f"{code} {rel}\n" for code, rel in current)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + body, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", default=".", help="repository root (default: .)")
    ap.add_argument("--write-baseline", action="store_true",
                    help="rewrite the baseline from the current findings, then exit 0")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        report, current = run(root)
        if args.write_baseline:
            print(f"check_headers: wrote {len(current)} entries to {write_baseline(root, current)}")
            return 0
    except InputError as exc:
        print(f"check_headers: ERROR: {exc}", file=sys.stderr)
        return 2
    skipped = ", ".join(f"{n} {why}" for why, n in sorted(report.skipped.items()))
    print(f"check_headers: inspected {report.checked} files; not inspected: {skipped or 'none'}")
    if not report.findings:
        print("check_headers: every inspected file carries the D25 header its tier requires")
        return 0
    for code, rel, detail in report.findings:
        print(f"{code} {rel}: {CODES[code]} — {detail}")
    print(f"check_headers: {len(report.findings)} finding(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
# REUSE-IgnoreEnd
