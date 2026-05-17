# Handoff — Maestro Refactor Complete

**Date**: 2026-05-08  
**Sprint**: 36b — Maestro Validation & Model Benchmarks  
**Status**: All 6 phases delivered

---

## What Was Built

### Phase 0 — Test fixtures
- `tests/test_maestro.py` created: 10 pytest cases covering parse_plan (5 cases), executor success/error, full pipeline, independent steps (Option C), and long-output escalation
- All 10 passing before and after Phase 1 changes

### Phase 1 — Structural fixes (orchestrator/maestro.py)
- `parse_plan(text)`: pure function, `STEP_RE` regex accepts numbered (`1.`, `1)`), bulleted (`-`, `*`), mixed; caps at 5 steps
- Planner prompt rewritten: forces step-decomposition, explicitly blocks task-answering
- `run_executor()`: rc != 0 → returns `ERROR (rc=N): ...`; `subprocess.TimeoutExpired` → structured error string
- `run()`: added `escalation_warnings` (>600 words), `plan_schema` (PlanSchema dataclass), uses `parse_plan()` internally
- `PlanSchema` dataclass: `task`, `steps`, `context_summary` (≤500 chars), `work_dir`

### Phase 2 — Executor role coverage
- Live runs via `claude --bare` → Ollama → model
- **gemma4:26b**: 3/3 PASS (create/append/delete), 252s total
- **qwen3.6-64k finding**: reports success on Bash ops but does NOT modify files (Bash hallucination)

### Phase 3 — Model x role benchmark
| Role | Winner | Score | Rationale |
|---|---|---|---|
| planner | gemma4:26b | 16/18 pts, 67%, 0 hallucinations | Beats qwen3.6 on score (16 vs 15), 35% faster |
| executor | gemma4:26b | 3/3, 100% | Only model with reliable Bash execution |
| multi-role | gemma4:26b | Same model wins both | No swap overhead in normal pipelines |

- qwen3.5:9b planner: 14/18, 50%, 57s — fastest but lower quality
- qwen3-coder:30b executor: 2/3, 67% — append omits newline separator

### Phase 4 — VRAM policy
- Swap qwen3.6→gemma4: **6.2s** (well under 30s threshold)
- Policy: `role_specialized` — two-model pipelines viable
- gemma4:26b: 31.5 tok/s; qwen3.6-64k: 17.1 tok/s
- Document: `orchestrator/VRAM_policy.md`

### Phase 5 — Compaction (PlanSchema structured handoff)
- `run_executor()` now accepts `context_summary` parameter (≤500 chars from planner narrative)
- `run()` builds `PlanSchema` from planner output; passes `context_summary` to each executor step
- Acceptance test: 87.2KB across 3 files, 3-step pipeline, 88s, no overflow

### Phase 6 — Delegation rules extension
- `orchestrator/delegation_rules.yaml` extended with `local_model_assignments` + `escalation_triggers`
- No `routing_matrix.yaml` created — single source of truth confirmed

---

## Key Findings

1. **gemma4:26b wins both planner and executor roles** — single model for normal pipelines, no swap
2. **qwen3.6-64k Bash hallucination** — reports success but doesn't write to files; use as planner fallback only (>50KB context tasks)
3. **qwen3-coder:30b append bug** — no newline on `echo >>` append; unreliable for file ops
4. **Model swap overhead**: 6s — negligible; role-specialized routing viable if needed
5. **PlanSchema prevents context overflow** — each executor step gets bounded prompt (step + ≤500 char summary), not full transcript

---

## Files Changed

| File | Change |
|---|---|
| `orchestrator/maestro.py` | Phase 1 refactor: parse_plan, STEP_RE, PlanSchema, rc checks, escalation_warnings, structured handoff |
| `tests/test_maestro.py` | Created: 10 fixture tests |
| `tests/run_phase2_executor_coverage.py` | Created: live executor coverage script |
| `tests/run_phase3_benchmark.py` | Created: model x role benchmark runner |
| `tests/run_phase4_vram.py` | Created: VRAM/swap measurement script |
| `orchestrator/VRAM_policy.md` | Created: policy doc with empirical measurements |
| `orchestrator/delegation_rules.yaml` | Added: local_model_assignments, escalation_triggers |
| `benchmark/sprint36b_results.md` | Created: benchmark results with corrected winner |
| `benchmark/.benchmark_winners.txt` | Created: machine-readable winners |
| `CLAUDE.md` | Updated: gotchas for executor hallucination, role assignments, VRAM policy, PlanSchema |

---

## Next

- **Sprint 37** (independent): <pipeline-project> safety protocol — sandbox SQLite + worktree isolation
- **Sprint 36c** (if needed): multi-step dependency (Option A/B inter-step context), currently Option C (independent) is in production
- No blocking issues. maestro.py is production-ready for gemma4:26b routing.
