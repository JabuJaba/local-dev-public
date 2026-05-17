# local-dev

Local-first orchestrator that routes coding tasks between **local LLMs** (Ollama / llama.cpp) and **Claude Code** (the subscription CLI), with the goal of reducing token spend while preserving quality. Claude Code is reserved for coordination, review, and escalation; local models handle the bulk of edits, refactors, and analysis.

> **Empirical result:** **37.3%** token reduction over a 20-task production batch (one of my private projects, April 2026). Summary and methodology: `analise/sprint8_economy_summary.md`. The harness is in `scripts/compute_sprint8_economy.py`; the raw run log is private and not in this repo.

---

## About this repository

This is a **personal research project** I built between April and May 2026 to explore how far a single workstation can carry an AI coding workflow. It's not a product — there's no installer, no CI, no support — and it's not a portfolio piece pretending to be one. I'm sharing it because:

1. It documents a real iteration loop (~40 sprints) with explicit decision records (`ADR.md`) showing what I tried, what worked, and what I killed off.
2. The empirical result it claims (37.3% token reduction on a private 20-task batch) is reported, not reproducible from this repo — the raw logs are private. The methodology and code that produced the number are here (`analise/sprint8_economy_summary.md`, `scripts/compute_sprint8_economy.py`).
3. The architecture decisions are the part I'm most willing to defend: a typed verdict schema, two execution paths (interactive vs autonomous), a safety interceptor at the shell-call layer, and explicit role assignments for local models based on benchmark data.

**What's curated:** the five sprints that shaped the current architecture (out of ~40), the matching session handoffs, and the contracts that govern the project's process (`analise/*-contract.md`). Earlier exploratory work is intentionally not included.

**What's still rough:** `CLAUDE.md`, `ADR.md`, `spec.md`, and the handoffs/sprints are written in Portuguese; only this README is in English. Some files reference earlier documents that aren't in the repo — those refs are leftovers, not load-bearing.

**Tests are green on a fresh clone:** `pytest tests/` (29 passed) + `python tests/test_orchestrator_smoke.py` (all checks) + `python tests/test_safety_interceptor.py` (10/10). The safety interceptor needs `LOCAL_DEV_SANDBOX_ROOTS` set to whitelist write paths; the test sets it automatically.

**What I'd want a reviewer to look at first:** `ADR.md` (the decisions and what they replaced) and `orchestrator/maestro.py` (the ~200-line core).

---

## Two execution paths

The project has **two distinct paths**, each with its own model assignments. Conflating them was a real source of confusion early on, so keeping them visually separate matters.

### Path A — Claude Code (interactive)

Claude Code pointed at Ollama via `ANTHROPIC_BASE_URL`. The user runs the session; the local model executes Read/Edit/Write/Bash within `--allowedTools`. Falls back to gemma4 if qwen3.6 stalls, then to a manual handoff.

| Attempt | Model | Why |
|---|---|---|
| 1–2 | `qwen3.6:35b-a3b-q4_k_m` | Best quality at acceptable speed for interactive turns |
| 3 | `gemma4:26b` | Better at Bash specifically; quality slot 3 |
| escalation | manual handoff to Claude Code (Anthropic) | Loss of routing; user pastes context |

### Path B — Maestro (autonomous, batch)

A planner-executor pipeline used by the orchestrator for backlog tasks. No human in the loop per step. Both roles run on the same model to avoid VRAM swap overhead.

| Role | Model | Source |
|---|---|---|
| planner | `gemma4:26b` | Sprint 36b: 16/18 pts, 0 hallucinations |
| executor | `gemma4:26b` | Sprint 36b: 3/3 Bash (small n — see caveat in `benchmark/sprint36b_results.md`) |
| fallback | `qwen3.6-64k` (Modelfile with `num_ctx 65536`) | For >50 KB context only |

### Routing flow

```
                        ┌──────────────────────────┐
   user task ─────────▶ │  fit-evaluator (skill)   │ ── verdict v0.2
                        │  routing_rules.yaml      │
                        └────────────┬─────────────┘
                                     │
                ┌────────────────────┼────────────────────┐
                ▼                    ▼                    ▼
        always_local          try_local_first        always_claude
        (Path A or B)         (Path A or B,          (handoff to
                               escalate on fail)      Claude Code)
```

- **Safety interceptor** rewrites or blocks destructive shell ops before they reach any model.
- **Verdicts** (`.delegation/verdicts/*.json`) record the routing decision, the diff, and the reviewer's call (`ACEITAR`, `RESSALVAS`, `DEVOLVER`, `ASSUMIR-CLAUDE`).
- **`qwen3coder-local`** (`qwen3-coder:30b-a3b-q4_K_M`, the fastest of the three at 37 tok/s) is used by Path B only — it emits legacy `<function=...>` XML that the Anthropic-compat shim doesn't translate, so it is **not** usable via Path A.

---

## Hardware tested on

| Component | Spec |
|---|---|
| CPU | Ryzen 7950X3D, 32 threads (use `-t 16` for llama.cpp) |
| GPU | RTX 5070 Ti, 16 GB VRAM, **sm_120** (Blackwell consumer — do **not** compile with `sm_100`) |
| RAM | 64 GB (allows MoE offload for larger models) |

Other configurations may work; nothing assumes the exact GPU. The 16 GB constraint matters: `qwen3.6:35b-a3b-q4_k_m` (~21 GB in Q4) offloads to CPU and runs at ~17 tok/s; `gemma4:26b` (~15 GB) fits and runs at ~31 tok/s; `qwen3coder-local` (~18 GB) runs at ~37 tok/s. **"MoE A3B is fast" only holds if it fits in VRAM** — the 35B-A3B variant is the slowest of the three on this card.

---

## Requirements

- Windows 11 + PowerShell 5.1, or Linux with bash equivalents (paths in scripts assume Windows).
- [Ollama](https://ollama.com) (tested with `qwen3.6:35b-a3b-q4_k_m`, `gemma4:26b`, `qwen3-coder:30b-a3b-q4_K_M`).
- Optional: a compiled `llama-server` for Qwen3-Coder-Next GGUF batch jobs.
- Python 3.11+ with `pyyaml`, `pytest`, `ruff` (see `tests/` for the canonical environment).

```powershell
ollama pull qwen3.6:35b-a3b-q4_k_m
ollama pull gemma4:26b
ollama create qwen3.6-64k -f Modelfile.qwen3.6-64k    # extends context to 65536
ollama create qwen3coder-local -f Modelfile.qwen3coder
```

---

## Quick start

```powershell
# Start the pipeline (Ollama + optional llama-server)
.\start.ps1

# Check status
.\start.ps1 -Status

# Ask the orchestrator a one-shot question
python .\ask.py "Refactor compute_economy() to use pathlib"
```

Routing rules live in `orchestrator/routing_rules.yaml`. Models, ports, and timeouts in `orchestrator/config.yaml`.

---

## Repo layout

| Path | What's there |
|---|---|
| `orchestrator/` | Maestro (planner+executor), router, safety interceptor, verdict resolver |
| `analise/` | Architecture contracts (`*-contract.md`), benchmarks, refactor roadmap |
| `benchmark/` | Benchmarking harness + the empirical results that drove role assignments |
| `docs/` | Design docs (`docs/design/`), delegation schema, review protocol |
| `sprints/` | Five architectural turning points (the project ran through ~40 sprints; only the ones that shaped the current design are kept) |
| `handoffs/` | Matching session handoffs documenting outcome and follow-up state |
| `backlog/` | Sample `backlog.yaml` showing how tasks are tagged for routing |
| `docker/` | Workspace isolation container (used for destructive tasks) |
| `tests/` | `pytest tests/test_*.py` for unit tests (29 functions across 5 files); `python tests/test_orchestrator_smoke.py` for the integration smoke (107 inline `check(...)` assertions, runs as a script not via pytest) |
| `ADR.md` | Architecture Decision Records — start here for the "why" |
| `CLAUDE.md` | Operational rules used by Claude Code when working in this repo |

---

## Reading order if you want to understand the project

1. `spec.md` — what problem this solves and the success criteria
2. `ADR.md` — the decisions and what was tried before each one
3. `analise/sprint-acceptance-contract.md` — how acceptance was defined
4. `sprints/sprint_maestro_refactor.md` — the refactor that made the pipeline reliable
5. `benchmark/sprint36b_results.md` — the numbers that pinned the role assignments
6. `orchestrator/maestro.py` — the core ~200-line coordinator

---

## What I'd do differently

A few honest notes for anyone considering a similar build:

- **Start with the verdict schema, not the router.** A typed contract for "did this task succeed?" forced the rest of the architecture into shape. The early routing rules were guesses; the verdicts gave them ground truth.
- **Two models in one VRAM is fine; three is not.** `gemma4:26b` + `qwen3.6-64k` can coexist with ~6 s swap. A third model trashes throughput.

- **The delegation skills (`/fit-evaluator`, `/sprint-generator-unified`, `/universal-review-merge`) live in my personal Claude Code config**, not in this repo. They write/read `.delegation/verdicts/*.json` — the JSON contract is documented in `docs/delegation_verdict_schema.md` if you want to reimplement them.

- **Some files referenced from handoffs and sprints (earlier-sprint acceptance docs, isolation reports) are outside the curated set.** The five preserved sprints capture the architectural turning points; the broken xrefs are leftovers, not load-bearing.
- **Local models will refuse destructive ops even when sandboxed.** That's a feature — keep it. Route destructive tasks to Claude with Docker isolation, not to a local "permissive" model.
- **The `num_ctx` default in Ollama silently truncates at 4096 tokens.** This burned multiple sprints. Always set it explicitly in the Modelfile.

---

## License

MIT — see [LICENSE](LICENSE).
