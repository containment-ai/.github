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
    file is the expression of the LAST REUSE.toml annotation matching it (any
    precedence; REUSE 3.3 applies only that one), else the configured default.
    An annotation naming any copyright holder besides ours marks the path
    THIRD-PARTY. This checker adds no tier map of its own: the tiers stay
    where `reuse lint` reads them.

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
  H011  baseline grew: an entry absent from the baseline at the comparison
        ref (--no-growth-against REF)

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
is the only way to grow the list, and with --no-growth-against REF (how the
gate runs) an entry REF's baseline lacks is H011, unless this script or its
config also changed since REF (a rule change may legitimately surface old
files; the growth is then printed).

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
    "H011": "baseline grew",
}

# Files covered by REUSE.toml instead of an inline header (HEADER-SPEC section 5).
BUILTIN_EXEMPT = (
    "*.json", "*.jsonc", "*.json5", "*.jsonl", "*.ndjson",
    "*.lock", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "go.sum",
    "LICENSES/*", "LICENSE", "LICENSE.*", "LICENSE-*", "LICENCE", "LICENCE.*", "LICENCE-*",
    "COPYING", "COPYING.*", "COPYING-*", "NOTICE", "NOTICE.*",
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
# Pre-D25 marking, matched only on header-shaped lines (a comment line that IS
# a licence tag or a copyright notice), so prose that quotes the strings is not
# a finding. LEGACY_ID_RE is the identifier alone: third-party files may carry
# an upstream "All rights reserved", never our pre-D25 identifier.
LEGACY_ID_RE = re.compile(_LEAD + r"SPDX-License-Identifier:.*\bLicenseRef-Proprietary\b")
LEGACY_RE = re.compile(_LEAD + r"(?:SPDX-License-Identifier:.*\bLicenseRef-Proprietary\b"
                       r"|(?:Copyright|\(c\)|©).*\bAll rights reserved\b)", re.IGNORECASE)
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
    """REUSE 3.3 path globbing: `**` crosses `/`; `*` and `?` do not; `\\*` is literal.

    Same semantics as glob_to_regex in scripts/check_reuse_license_map.py."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("\\*", i):
            out.append(re.escape("*"))
            i += 2
        elif pattern.startswith("**/", i):
            out.append("(?:.*/)?")  # `**/` also matches at the annotation root
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def load_annotations(root: Path, files: list[str]) -> list[Annotation]:
    nested = [f for f in files if f.endswith("/REUSE.toml")]
    if nested:
        # REUSE 3.3 permits nested REUSE.toml files; this gate resolves the
        # root file only, so it refuses rather than resolve a path wrongly.
        raise InputError(f"nested REUSE.toml not supported by this gate: {', '.join(nested[:5])}")
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
        expr = ann.get("SPDX-License-Identifier", "")
        if isinstance(expr, list):
            # REUSE 3.3 allows a list; its entries apply together (AND).
            expr = " AND ".join(f"({e})" if " " in str(e).strip() else str(e) for e in expr)
        out.append(Annotation(
            patterns=[reuse_glob(p) for p in paths],
            copyright=cr,
            expression=str(expr),
        ))
    return out


_YEARS_RE = re.compile(r"\b\d{4}(?:\s*-\s*\d{4})?\b")
_JOINERS_RE = re.compile(r"[,;&()]|\band\b", re.IGNORECASE)
# Notice words are not holders: "Copyright (C) 2026 Containment.ai LLC" names
# only us. Without this, the word "Copyright" would read as another holder and
# silently switch a first-party path to the third-party rules.
_NOTICE_RE = re.compile(r"SPDX-FileCopyrightText:|\bcopyright\b|\(c\)|©", re.IGNORECASE)


def names_other_holder(copyright_text: str, holder: str) -> bool:
    """True when the annotation names any copyright holder besides ours.

    A joint notice (upstream authors AND us, the normal marking for a vendored
    file we modified) is third-party: the gate must never demand our marking on
    it. Our holder, years and joining words are removed; anything left is
    another holder."""
    for line in copyright_text.splitlines():
        rest = _JOINERS_RE.sub(" ", _YEARS_RE.sub(" ", _NOTICE_RE.sub(" ", line.replace(holder, " "))))
        if any(ch.isalpha() for ch in rest):  # Unicode-aware: any script names a holder
            return True
    return False


def resolve(path: str, annotations: list[Annotation], cfg: Config) -> tuple[str, bool]:
    """(expected expression, third_party) for a path.

    REUSE 3.3: exclusively the LAST matching annotation applies; its precedence
    then says whether it or the file's own header wins. Either way the header
    a first-party file should carry is that annotation's expression, so both
    values come from the one deciding annotation. No match: the configured
    default."""
    deciding = None
    for ann in annotations:
        if any(p.match(path) for p in ann.patterns):
            deciding = ann
    if deciding is None:
        return cfg.default_expression, False
    return deciding.expression, names_other_holder(deciding.copyright, cfg.holder)


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
    exempt = data.get("exempt", [])
    if not isinstance(exempt, list) or not all(isinstance(g, str) and g for g in exempt):
        # A bare string would become one-character globs, including "*",
        # which exempts every file: refuse rather than fail open.
        raise InputError(f"{CONFIG_NAME}: exempt must be an array of non-empty strings")
    baseline = data.get("baseline", "")
    if not isinstance(baseline, str):
        raise InputError(f"{CONFIG_NAME}: baseline must be a string path")
    return Config(
        years=str(data["years"]),
        holder=str(data["holder"]),
        default_expression=str(data["default-expression"]),
        agpl_ai_use=form,
        exempt=tuple(exempt),
        baseline=baseline,
    )


def read_baseline(root: Path, cfg: Config, report: Report, writing: bool = False) -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()
    if not cfg.baseline:
        return entries
    path = root / cfg.baseline
    if not path.is_file() and writing:
        return entries  # --write-baseline is about to create it (first adoption)
    if not path.is_file():
        raise InputError(f"baseline {cfg.baseline} named in {CONFIG_NAME} does not exist")
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0] not in CODES or parts[0] in ("H009", "H010", "H011"):
            report.findings.append(("H010", cfg.baseline, f"line {n}: {raw!r}"))
            continue
        entries.add((parts[0], parts[1]))
    return entries


# --- per-file inspection --------------------------------------------------------

def tracked_files(root: Path) -> list[str]:
    """Tracked files plus untracked files git does not ignore: the set `reuse
    lint` walks, so a new file is inspected before it is staged, not only in CI."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard"],
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputError(f"git ls-files failed: {exc}") from exc
    return sorted({p for p in out.decode("utf-8", "surrogateescape").split("\0") if p})


def glob_match(path: str, patterns: tuple[str, ...]) -> bool:
    name = path.rsplit("/", 1)[-1]
    for pat in patterns:
        if "/" in pat:
            if reuse_glob(pat).match(path):
                return True
        elif fnmatch.fnmatchcase(name, pat):
            return True
    return False


def commentable(path: str, root: Path | None = None) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in COMMENT_NAMES or name.startswith("Dockerfile.") or name.lower() in COMMENT_EXT:
        return True  # the last arm: an extension-like dotfile name such as `.env`
    dot = name.rfind(".")
    if dot > 0 and name[dot:].lower() in COMMENT_EXT:
        return True
    if root is not None and dot <= 0:
        # An extensionless script (a git hook, a bin/ wrapper) can carry a `#`
        # header: treat a shebang as comment syntax.
        try:
            with (root / path).open("rb") as fh:
                return fh.read(2) == b"#!"
        except OSError:
            return True  # let the reader raise the InputError
    return False


def head_lines(path: Path, rel: str) -> tuple[list[str], bool] | None:
    """(first WINDOW lines with REUSE-Ignore blocks blanked, file has content).

    None means a binary file. A file that cannot be read is NOT skipped: it is
    an InputError (exit 2), because a gate that cannot look must not pass.
    "Has content" is judged from the file's bytes, not from the filtered window,
    so leading blank lines or an ignore block over the window cannot make a
    real source file look empty."""
    try:
        with path.open("rb") as fh:
            raw = fh.read(65536)
            more = bool(fh.read(1))
    except OSError as exc:
        raise InputError(f"cannot read {rel}: {exc}") from exc
    if b"\0" in raw[:8000]:
        return None
    has_content = bool(raw.strip()) or more
    lines = raw.decode("utf-8", "replace").splitlines()[:WINDOW]
    out, ignoring = [], False
    for line in lines:
        if IGNORE_START in line:
            ignoring = True
        out.append("" if ignoring else line)
        if IGNORE_END in line:
            ignoring = False
    return out, has_content


def inspect(lines: list[str], expected: str, third_party: bool, cfg: Config) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    copies = [(i, m.group(1)) for i, l in enumerate(lines) if (m := COPY_RE.match(l))]
    lics = [(i, m.group(1)) for i, l in enumerate(lines) if (m := LIC_RE.match(l))]
    ais = [(i, m.group(1)) for i, l in enumerate(lines) if (m := AI_RE.match(l))]
    legacy = [i for i, l in enumerate(lines) if LEGACY_RE.match(l)]

    if third_party:
        # Tier-independent checks first. An upstream "All rights reserved" is
        # legitimate here; our pre-D25 identifier and a second licence line are not.
        legacy_id = [i for i, l in enumerate(lines) if LEGACY_ID_RE.match(l)]
        if legacy_id:
            found.append(("H006", f"line {legacy_id[0] + 1}: {lines[legacy_id[0]].strip()[:80]!r}"))
        if len(lics) > 1:
            found.append(("H008", f"{len(lics)} licence lines"))
        if ais:
            found.append(("H007", f"AI-USE line on line {ais[0][0] + 1} of a third-party file"))
        if copies and not any(names_other_holder(c, cfg.holder) for _, c in copies):
            found.append(("H007", f"only {cfg.holder} named as copyright holder of a third-party file"))
        if lics and lics[0][1] != expected:
            found.append(("H004", f"{lics[0][1]!r}, REUSE.toml says {expected!r}"))
        return found

    if legacy:
        found.append(("H006", f"line {legacy[0] + 1}: {lines[legacy[0]].strip()[:80]!r}"))
    if len(copies) > 1 or len(lics) > 1 or len(ais) > 1:
        found.append(("H008", f"{len(copies)} copyright, {len(lics)} licence and {len(ais)} AI-USE lines"))
    if not copies and not lics and not ais:
        if not legacy:
            found.append(("H001", "no SPDX-FileCopyrightText, SPDX-License-Identifier or AI-USE line"))
        return found
    if not (copies and lics and ais) or not (lics[0][0] == copies[0][0] + 1 and ais[0][0] == copies[0][0] + 2):
        have = [n for n, xs in (("copyright", copies), ("licence", lics), ("AI-USE", ais)) if xs]
        found.append(("H002", f"have {', '.join(have)}; need all three on consecutive lines in that order"))
    if copies and copies[0][1] != f"{cfg.years} {cfg.holder}":
        found.append(("H003", f"{copies[0][1]!r}, expected {cfg.years + ' ' + cfg.holder!r}"))
    if lics and lics[0][1] != expected:
        found.append(("H004", f"{lics[0][1]!r}, REUSE.toml says {expected!r}"))
    if ais:
        want = AI_USE_NOTICE if (cfg.agpl_ai_use == "notice" and "AGPL" in expected) else AI_USE_D25
        if ais[0][1] not in (want, _ascii(want)):
            found.append(("H005", f"{ais[0][1]!r}, expected {want!r}"))
    return found


def run(root: Path, writing: bool = False) -> tuple[Report, list[tuple[str, str]]]:
    cfg = load_config(root)
    report = Report()
    baseline = read_baseline(root, cfg, report, writing)
    files = tracked_files(root)
    annotations = load_annotations(root, files)
    tracked = set(files)
    raw: list[tuple[str, str, str]] = []
    for rel in files:
        if glob_match(rel, BUILTIN_EXEMPT):
            report.skip("REUSE.toml-only type (HEADER-SPEC section 5)")
            continue
        if cfg.exempt and glob_match(rel, cfg.exempt):
            report.skip(f"exempt glob in {CONFIG_NAME}")
            continue
        if not commentable(rel, root):
            report.skip("no known comment syntax")
            continue
        sidecar = rel + ".license"
        if sidecar in tracked:
            # REUSE reads a .license sidecar INSTEAD of the file it describes.
            got = head_lines(root / sidecar, sidecar)
            source = f" (read from {sidecar})"
        else:
            got = head_lines(root / rel, rel)
            source = ""
        if got is None:
            report.skip("binary")
            continue
        lines, has_content = got
        if not has_content and not source:
            report.skip("empty")
            continue
        report.checked += 1
        expected, third_party = resolve(rel, annotations, cfg)
        for code, detail in inspect(lines, expected, third_party, cfg):
            raw.append((code, rel, detail + source))
    current = {(c, p) for c, p, _ in raw}
    for code, rel, detail in raw:
        if (code, rel) not in baseline:
            report.findings.append((code, rel, detail))
    for code, rel in sorted(baseline - current):
        why = "file is no longer tracked" if rel not in tracked else "finding no longer occurs; remove the entry"
        report.findings.append(("H009", rel, f"baseline {code}: {why}"))
    return report, sorted(current)


def baseline_growth(root: Path, cfg: Config, ref: str, report: Report) -> None:
    """H011 for each baseline entry the baseline at `ref` lacks."""
    if not cfg.baseline:
        return
    git = ["git", "-C", str(root)]
    shown = subprocess.run(git + ["show", f"{ref}:{cfg.baseline}"], capture_output=True)
    if shown.returncode != 0:
        exists = subprocess.run(git + ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], capture_output=True)
        if exists.returncode != 0:
            raise InputError(f"--no-growth-against: {ref!r} is not a commit")
        print(f"check_headers: no baseline at {ref}; growth check skipped (first adoption)")
        return
    def entries(text: str) -> set[tuple[str, str]]:
        out = set()
        for line in text.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and not parts[0].startswith("#"):
                out.add((parts[0], parts[1]))
        return out
    before = entries(shown.stdout.decode("utf-8", "replace"))
    now = entries((root / cfg.baseline).read_text(encoding="utf-8"))
    grown = sorted(now - before)
    if not grown:
        return
    script = Path(__file__).resolve()
    rules = [CONFIG_NAME]
    try:
        rules.append(str(script.relative_to(root.resolve())))
    except ValueError:
        pass  # the script lives outside the checked repository (org workflow)
    changed = subprocess.run(git + ["diff", "--quiet", ref, "--", *rules], capture_output=True)
    if changed.returncode == 1:
        print(f"check_headers: baseline grew by {len(grown)} entr{'y' if len(grown) == 1 else 'ies'} "
              f"since {ref}, allowed because {' or '.join(rules)} changed too:")
        for code, rel in grown:
            print(f"  + {code} {rel}")
        return
    for code, rel in grown:
        report.findings.append(("H011", rel, f"baseline {code} is new since {ref}; fix the file instead"))


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
    ap.add_argument("--no-growth-against", metavar="REF", default=None,
                    help="fail (H011) on baseline entries absent from the baseline at REF")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        report, current = run(root, writing=args.write_baseline)
        if args.write_baseline:
            print(f"check_headers: wrote {len(current)} entries to {write_baseline(root, current)}")
            return 0
        if args.no_growth_against:
            baseline_growth(root, load_config(root), args.no_growth_against, report)
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
