# containment-ai

Shared GitHub Actions workflows for the [containment-ai](https://github.com/containment-ai) organization.

## Reusable workflows

This `.github` repo hosts org-shared reusable workflows that other containment-ai repos call via `uses:`. Centralizing here means one source of truth — no more N-way copy-paste churn when the workflow needs a fix.

### Catalog

| Workflow | Path | Consumers |
|---|---|---|
| Auto-update PR branches | `.github/workflows/auto-update-pr-branches-reusable.yml` | All 6 containment-ai repos with auto-merge enabled |

### How to consume

Add a thin shim in your repo at `.github/workflows/<name>.yml`:

```yaml
name: Auto-update PR branches on main push

on:
  push:
    branches: [main]
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch:

jobs:
  call:
    uses: containment-ai/.github/.github/workflows/auto-update-pr-branches-reusable.yml@main
    secrets: inherit
    permissions:
      contents: write
      pull-requests: write
      checks: read
      statuses: read
      actions: read
```

Triggers (`on:`) must live in the caller because `workflow_call` workflows cannot declare `push` / `schedule` / `workflow_dispatch` themselves. `secrets: inherit` forwards `CLAUDE_BOT_PR_TOKEN` (used to force `pull_request: synchronize` after rebase — see workflow header for context).

### Background

See [containment-ai/containment-ai-agents#1160](https://github.com/containment-ai/containment-ai-agents/issues/1160) for the consolidation rationale.
