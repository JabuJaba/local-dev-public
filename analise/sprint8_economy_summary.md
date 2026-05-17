# Sprint 8 — Token Economy Summary

**Date measured:** 2026-04-23
**Source code:** `scripts/compute_sprint8_economy.py`
**Source data (not in repo):** `logs/sprint8_run_*.jsonl` (private)

## Headline

| Metric | Value |
|---|---|
| Token reduction vs Claude-only baseline | **37.3%** |
| Tasks resolved locally (no Claude escalation) | 9 / 20 |
| Tasks escalated to Claude | 11 / 20 |
| Success criterion (`spec.md`: ≥20%) | ✅ MET |

## Per-category breakdown

| Category | Resolved | Total | Local economy |
|---|---|---|---|
| `always_local` | 4 | 8 | 57.9% |
| `try_local_first` | 4 | 8 | 40.7% |
| `destructive_local` | 0 | 4 | 0% |

`destructive_local` accounted for 0% local resolution: the model refused or escalated on `rm`/overwrite operations even inside a Docker workspace. This was reclassified as `always_claude` in Sprint 9 — see ADR-011 and the `safety_interceptor` rationale.

## Why this summary is in the repo but the raw log isn't

The raw run log contains task descriptions and file contents from a private project. The numbers above are what is reproducible publicly. If you want to reproduce the methodology on your own workload, the entry point is:

```bash
python scripts/compute_sprint8_economy.py --runs logs/your-run-dir/
```

The script computes:
1. Total tokens that *would have been* spent if every task ran on Claude (baseline)
2. Total tokens actually spent (local turns (no Claude cost) + escalations)
3. The ratio reported as "token economy"

## Caveats

- The 37.3% figure depends on the local-pct distribution of your task mix. Tasks heavy on multi-file edits or long-context reads will favor Claude and bring the economy down.
- Tokens-on-paper, not dollars: Claude Code subscription has a cap, so the dollar savings depend on whether you were hitting the cap before.
- One project, one task mix — not a general claim about all coding workloads.
