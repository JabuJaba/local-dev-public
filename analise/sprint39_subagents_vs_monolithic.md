# Sprint 39 Phase 4 — Sub-agents vs Monolithic comparison

Comparativo entre execução **Sprint 38 V1 monolítico** (planner como agente único livre) e **Sprint 39 Phase 3 sub-agents-instructed** (planner com constraint "só dispatch via Task").

Ambos rodaram `qwen3.6-64k:latest` via shim Anthropic-Ollama. Ambos sobre o mesmo projeto (`<pipeline-project>`).

## Tabela comparativa

| Métrica | Sprint 38 V1 (monolítico) | Sprint 39 Phase 3 (sub-agents-instructed) |
|---|---|---|
| Escopo do prompt | "Execute todas as 4 fases da Sprint 6.36" | "Regenerar 2 arquivos a partir de market_data.parquet" |
| Wall-clock | **142 min** | **13 min** |
| Cumulative tokens_in | 4.530.000 | 444.741 |
| tokens_out | 58.000 | 1.655 |
| ctx_observed (peak) | 64 KB (saturado) | <32k por turno (cumulative 444k) |
| Total tool_uses | 54 | 15 |
| Task/Agent dispatches | 0 | **0** |
| Files correctly produced | 1 (parquet, mas fora-de-escopo) | 2 (data.js + HTML, em escopo) |
| Scope-creep | **SIM** — 4 phases viraram 7 unilateralmente; fez Option B/C fora-de-escopo | NÃO — escopo era 2 arquivos, modelo limitou-se a isso |
| Loop | **SIM** — phase 1→2→3→2→1 repetido | NÃO — sequência linear discovery → execute |
| Correção do output | NÃO (rejeitado, scope-creep) | **SIM** (19 funds, PL multi-bilionario, CDI conhecido) |

## Análise

**A Sprint 39 Phase 3 reduziu 3 das 4 métricas problemáticas da Sprint 38**:
- ctx-saturação: melhor (44k< 65k cap individual turn) ✅
- loop: ausente ✅
- scope-creep: ausente ✅
- wall-clock: 13min vs 142min (11× mais rápido) ✅

**MAS o ganho NÃO vem de sub-agents** — vem de **escopo menor**. O planner usou Bash/PowerShell direto, ignorou `Task` apesar do tool estar exposto e da instrução explícita. Os 15 tool_uses são monolíticos, não dispatched.

**Interpretação correta**: a comparação isola **uma única variável crítica** que NÃO é a hipótese inicial — a **largura do escopo do prompt** é o que governa o comportamento de qwen3.6-64k, não a estrutura de dispatch.

## Implicações para o roadmap

| Sprint | Forma esperada original | Forma revisada pós-39 |
|---|---|---|
| **S47** Multi-sprint skill | "1 goal + auto-decomposição" (se sub-agents viáveis) | **Mantém pré-decomposição manual**; skill gera N sprints com cap 5 phases cada |
| **S48** Sprint doc auto-executável | "opcional se sub-agents viáveis" | **CRÍTICA** — scope-fence obrigatório, batch-gate per-phase |
| **S55-S58** Ferramentas | "podem assumir planner-dispatch" | **Assumem pré-decomposição**; Aider/OpenClaw como executores de phases individuais |

## Veredito (Phase 4)

Sub-agents **tecnicamente viáveis** (Phase 1 Test E proved), mas **comportamentalmente não-utilizáveis** em qwen3.6-64k sob constraint dispatch-only. Pré-decomposição manual continua sendo o pattern. ADR-018.
