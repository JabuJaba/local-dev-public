# Sprint 36b Model x Role Benchmark Results

**Date**: 2026-05-08  
**Sprint**: 36b Phase 3  

---

## Planner Candidates

| Model | Pass Rate | Hallucinations | Score | Median Time | Total Time |
|---|---|---|---|---|---|
| qwen3.5:9b | 50% | 0 | 14/18 | 6s | 57s |
| qwen3.6-64k:latest | 67% | 0 | 15/18 | 25s | 188s |
| **gemma4:26b (multi-role)** | **67%** | **0** | **16/18** | **19s** | **123s** |

Note: gemma4:26b was benchmarked in multi-role mode and outscored dedicated planner candidates (16 vs 15 pts).
Winner: **gemma4:26b** — same pass rate as qwen3.6-64k, higher raw score, 35% faster.

---

## Executor Candidates

| Model | Pass Rate | Pass Count | Notes | Total Time |
|---|---|---|---|---|
| **gemma4:26b** | **100%** | **3/3** | All Bash ops correct | 56s |
| qwen3-coder:30b-a3b-q4_K_M | 67% | 2/3 | Append: no newline separator | 61s |

qwen3-coder failure: `echo 'bench_line2' >> file` omitted newline, merging lines (`bench verifiedbench_line2`).

Winner: **gemma4:26b** — 100% vs 67%.

> **Caveat — small sample.** n=3 is a pilot, not a durable decision. A single extra failure would invert the ranking (67% vs 67%). The choice of `gemma4:26b` as executor is consistent with the larger n=40 benchmark recorded in `ADR-011` for general coding pass rate, but the *Bash-specific* claim here should be re-run at n≥20 before being treated as load-bearing. The qualitative finding (qwen3-coder omits newlines in append) is reproducible and is the real signal.

---

## Phase 2 Pre-Benchmark Finding

| Model | Executor Behavior | File Modified? |
|---|---|---|
| qwen3.6-64k:latest | Reported success, output plausible | NO — Bash hallucination |
| gemma4:26b | Used Bash correctly, appended line | YES |

---

## VRAM Policy (Phase 4)

| Scenario | Load time | tok/s |
|---|---|---|
| qwen3.6-64k warm | 12.0s | 17.1 |
| gemma4:26b cold (swap from qwen3.6) | 6.2s | 31.5 |
| gemma4:26b warm | 0.2s | 30.8 |

**Policy: `role_specialized`** — swap is 6s (< 30s threshold), two-model pipelines viable.

---

## Final Assignments (Phase 6)

| Role | Model | Rationale |
|---|---|---|
| planner | gemma4:26b | 16/18 pts, 0 hallucinations, 19s median |
| executor | gemma4:26b | 3/3 Bash (small n — see caveat above) |
| fallback | qwen3.6-64k (Modelfile built from qwen3.6:35b-a3b with `num_ctx 65536`) | >32K context tasks or gemma4 unavailable |

Single model for both roles: no swap overhead in normal pipelines.  
`qwen3.6-64k` reserved for context-heavy tasks (>50KB, per `escalation_triggers.context_kb_limit`). Build it with `ollama create qwen3.6-64k -f Modelfile.qwen3.6-64k`.
