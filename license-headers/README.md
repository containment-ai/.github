<!-- SPDX-FileCopyrightText: 2026 Containment.ai LLC -->
<!-- SPDX-License-Identifier: LicenseRef-Containment-Commercial -->
<!-- AI-USE: see AI-POLICY.md — no AI training, no AI-assisted rewrite/reimplementation -->

# License headers

Shared licence checks for containment-ai repositories, run by the reusable workflow
[`.github/workflows/license-headers.yml`](../.github/workflows/license-headers.yml).

| file | what it does |
|---|---|
| `check_reuse_lint.py` | Runs `reuse lint` (REUSE 3.3) at reuse **6.2.0** and refuses any other version. Exit 0 compliant, 1 non-compliant, 2 could not measure (including a pass without reuse's file counts, below `--min-files` (default 1), or with a `license-expression` / `boolean.py` other than the lock pins). |
| `requirements-reuse.txt` | reuse 6.2.0 and its full dependency closure, hash-locked. Install with `pip install --require-hashes -r`. |
| `check_headers.py` | Per-file header check, configured by `.license-headers.toml` at the caller's root. The licence each path should carry is read from the caller's `REUSE.toml`. |
| `test_check_headers.py`, `test_check_reuse_lint.py` | Mutation suites: every finding the checks claim is driven by a fixture and must fail. |

## Adopting it

1. Make `reuse lint` pass locally: `pip install --require-hashes -r license-headers/requirements-reuse.txt`, then `python -m reuse lint`.
2. Add a caller workflow. The shim is in the header of `license-headers.yml`. Pin `uses:` to a commit SHA, and include a `merge_group` trigger in case the check is ever made required.
3. Optional: add `.license-headers.toml` to turn on the per-file header check:

   ```toml
   years = "2026"                      # first-commit year to now, e.g. "2025-2026"
   holder = "Containment.ai LLC"
   default-expression = "LicenseRef-Containment-Commercial"
   agpl-ai-use = "d25"                 # or "notice" for AGPL files, if the repository adopts it
   exempt = ["fixtures/**"]            # paths that carry their licence in REUSE.toml
   baseline = "license-headers-baseline.txt"   # optional; generate with --write-baseline
   min-inspected = 100                 # optional anti-vacuity floor; default 1, never 0
   max-uninspected-by-type = 40        # optional cap on files skipped for no comment syntax
   third-party = 0                     # optional exact count of paths under third-party rules
   max-exempt = 10                     # optional cap on files dropped by the exempt globs
   ```

   Fewer inspected files than `min-inspected` is exit 2, so a check pointed at the
   wrong subtree cannot report clean. Set it about 10% under today's count (the check
   prints it). A tracked `.license` sidecar is read in place of the file it describes,
   whatever that file's type, and a binary sidecar is exit 2. The check reads the
   working tree, so gitignore anything an earlier CI step writes into it. The two
   optional pins are exit 2 on mismatch: more skipped-by-type files than the cap means
   a commentable type the checker does not know yet, and a different third-party count
   means a `REUSE.toml` change reclassified paths that then need no header. More files
   under the exempt globs than `max-exempt` means a new directory matched one (a
   `**/fixtures/**` glob matches that name anywhere). A `.license` sidecar whose file is
   no longer tracked is exit 2.

   The baseline excuses one finding code on one file. It only shrinks: an entry that
   no longer matches a finding fails the check. The reusable workflow also passes
   `--no-growth-against <base commit>` (input `baseline-growth`, default `on`): on a
   pull request, merge group or push, an entry the base commit's baseline lacks fails
   as H011 unless `.license-headers.toml` changed in the same diff. Run locally with
   `--no-growth-against origin/main`.

Adding a caller does not make the check required. That is a ruleset change in the
calling repository.
