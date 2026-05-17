# Maestro Validation & Model Benchmarks

**Date**: 2026-05-08  
**Depends on**: Sprint 36 (maestro skeleton, qwen3.6-64k Modelfile)  
**Exit criterion**: All 6 fixture tests pass with declared per-role model assignments, zero manual fixup, total wall-clock < 5 min per full suite run.

---

## Context

Sprint 36 produced a skeleton (`orchestrator/maestro.py`) that was never executed end-to-end until post-sprint. First execution confirmed:
- Pipeline runs (exit 0, agent_count=3, AGENT_CAP respected)
- **Planner hallucination found**: planner answered task directly with invented filenames instead of generating steps
- **Executor graceful degradation**: used Glob/Read correctly, detected missing files

Advisor review identified 4 structural gaps that must be fixed before model benchmarking is meaningful:
1. Plan parser fragile (`isdigit()` drops non-numbered formats)
2. Executor has no inter-step context (multi-step dependencies fail silently)
3. No failure semantics (subprocess rc unchecked; failed step == success in result dict)
4. No test fixtures (benchmarking without fixed suite is vibes-based)

Also confirmed: `claude --bare -p` does multi-turn tool use internally (verified: Glob call + result in single invocation). Planner prompt fix is architecturally viable.

---

## Phases

### Phase 0 — Test fixtures (prerequisite for all benchmarks)

Create `tests/test_maestro.py` with 6 cases:
1. **planner-only**: parse a 3-step plan from planner output — assert steps extracted correctly
2. **executor-only**: run a single step, assert output non-empty
3. **full pipeline**: end-to-end `maestro.run("list 3 files in sprints/")` — assert file list in result
4. **error path**: force executor subprocess to fail (invalid tool) — assert error surfaced, not swallowed
5. **multi-step with dependency**: step 2 references output of step 1 — assert context propagation works
6. **long-output trigger**: task expected to return >600 words — assert escalation flag set (or handoff documented)

**Acceptance**: `pytest tests/test_maestro.py` all 6 passing before any Phase 1 work begins.

---

### Phase 1 — Structural fixes

**1a. Planner prompt fix**

Current: `"Output a numbered list only."` — model interprets list-tasks as "answer directly".

Fix: explicit step-decomposition instruction.

```python
prompt = (
    f"You are a planner. Use your tools to gather information if needed, "
    f"then break this task into 2-5 concrete execution steps.\n"
    f"Each step must be an ACTION (start with a verb: Read, List, Create, Write, Check).\n"
    f"Do NOT answer the task — output only the step list.\n"
    f"Working directory: {work_dir}\n"
    f"Task: {task}\n"
    f"Output format: numbered list, one step per line, no commentary."
)
```

**1b. Plan parser hardening**

Current: `line.strip()[0].isdigit()` — silently drops bullets, sub-lists, code fences.

Fix: accept numbered (`1.`, `1)`) AND bulleted (`-`, `*`) formats; strip leading markers.

```python
import re
STEP_RE = re.compile(r'^(?:\d+[.)]\s*|[-*]\s+)(.*)')

steps = []
for line in plan.splitlines():
    m = STEP_RE.match(line.strip())
    if m:
        steps.append(m.group(1).strip())
```

**Parse tolerance acceptance**: planner output in 3 formats (numbered / bulleted / mixed) all produce the same step list.

**1c. Executor inter-step context**

Decision needed: does executor receive prior step outputs?

Option A — Accumulate: pass `prior_results` list to each executor call (full context, VRAM-heavy for long pipelines).  
Option B — Summary: compress prior outputs to 2-sentence summary before passing.  
Option C — Independent: steps are atomic, no dependency allowed (restrict planner prompt).

**Default for Sprint 36b**: Option C (independent steps) — simplest, no risk of context overflow. Document as architectural decision; revisit in Sprint 36c if multi-step dependency is required.

**1d. Failure semantics**

```python
result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=timeout)
if result.returncode != 0:
    return f"ERROR (rc={result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
```

Add timeout handling: catch `subprocess.TimeoutExpired`, return structured error string.

**Acceptance**: forced-failure test (Phase 0 case 4) passes — error surfaced in `result["results"]`, not swallowed.

---

### Phase 2 — Executor role coverage

Test executor with file-manipulation tools (Edit/Write/Bash) — currently zero coverage.

Tasks:
- `maestro.run("create file scratch/test_exec.txt with content: maestro executor verified")` → file exists on disk
- `maestro.run("append line 'line2' to scratch/test_exec.txt")` → file has 2 lines
- `maestro.run("delete scratch/test_exec.txt")` → file gone

**Acceptance**: all 3 tasks complete without manual intervention, file system matches expected state after each.

---

### Phase 3 — Model x role benchmark

**Scope**: qwen3-marcus removed per user direction.

| Role | Candidates | Metric | Budget |
|---|---|---|---|
| planner | qwen3.5:9b, qwen3.6-64k | step quality (non-hallucination rate), 10-task suite | 60s / 50K tokens per task |
| executor | gemma4:26b, qwen3-coder:30b | Bash correctness, Edit tool use | 120s / 50K tokens per task |
| multi-role (planner+executor) | gemma4:26b | swap penalty vs quality | compare vs role-specialized |

Each candidate runs all 6 fixture tests. Results recorded in `benchmark/sprint36b_results.md`.

Budget enforcement: tasks exceeding 60s wall (planner) or 120s (executor) are marked `escalated` in results, not silently stalled.

Review existing benchmarks in `benchmark/results/` for gemma4:26b and qwen3-coder:30b before running new tests.

**Acceptance**: per-role winner declared with numeric evidence (pass rate, median wall-clock, hallucination count).

---

### Phase 4 — VRAM / swap policy

- qwen3.6-64k resident: 13.3/16GB (83%)
- Two models concurrent: impossible without swap
- Measure: cold-load time for gemma4:26b after qwen3.6 unload
- Measure: tok/s degradation during model swap

Decision outputs:
- If swap < 30s: role-specialized (qwen3.6 planner, gemma4 executor)
- If swap 30-90s: single-model-per-run (one model does both roles)
- If swap > 90s: batch mode only (pre-schedule model per pipeline)

**Acceptance**: policy documented in `orchestrator/VRAM_policy.md`, `delegation_rules.yaml` updated with `local_model_swap_policy` field.

---

### Phase 5 — Compaction strategy

Context risk: 65K window, multi-file reads + multi-step pipeline can overflow.

Options:
- **Sliding window**: drop oldest tool results beyond threshold
- **Structured handoff**: planner outputs JSON summary; executor receives schema, not transcript
- **Summary pass**: after planner, a compression step reduces plan + context to ≤5K tokens

**Default for Sprint 36b**: structured handoff (JSON plan schema) — deterministic, no model-dependent summarization.

Define `PlanSchema`:
```python
@dataclass
class PlanSchema:
    task: str
    steps: list[str]          # max 5
    context_summary: str      # max 500 chars, from planner
    work_dir: str
```

**Acceptance**: pipeline with 5-step task on 3 files (>30KB total) completes without context overflow error.

---

### Phase 6 — Delegation rules extension

**Do NOT create `routing_matrix.yaml`** — extend `orchestrator/delegation_rules.yaml` with per-role local model assignments.

Add section:
```yaml
local_model_assignments:
  planner: <winner from Phase 3>
  executor: <winner from Phase 3>
  fallback: qwen3.6-64k
  swap_policy: <from Phase 4>

escalation_triggers:
  output_word_limit: 600
  context_kb_limit: 50
  destructive: always_claude
```

**Acceptance**: `delegation_rules.yaml` is the single source of truth for routing. No parallel routing file exists.

---

## Ordering

```
Phase 0 (fixtures) → Phase 1 (structural fixes) → Phase 2 (executor coverage)
→ Phase 3 (model benchmark) → Phase 4 (VRAM policy) → Phase 5 (compaction)
→ Phase 6 (delegation rules extension)
```

Rationale: benchmarking (Phase 3) before structural fixes (Phase 1) would measure the bugs, not the models.

---

## Key unknowns resolved pre-sprint

- `claude --bare -p` multi-turn tool use: **CONFIRMED** (verified 2026-05-07, Glob + report in single invocation)
- qwen3.6-64k Modelfile: **BUILT** (`Modelfile.qwen3.6-64k`, tokens_in=14911 verified)
- maestro.run() executes: **CONFIRMED** (exit 0, planner hallucination found, executor graceful)

---

## Non-goals

- Per-agent provider routing (Ollama feature request, not yet supported)
- Sprint 37 (<pipeline-project> safety protocol) — independent, no blockers
- Coder Next / llama-server integration — deferred to Sprint 38+
