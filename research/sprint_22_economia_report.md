# Relatório de Economia — Sprint 22

Data: 2026-05-01
Baseline: Sprint 17 (handoff_sprint17.md)

## Baseline Sprint 17

| Componente | Tokens Claude | Observação |
|---|---|---|
| fit-evaluator (2/5 tasks avaliadas) | 596k | overhead fixo por task |
| sprint-generator (2 sprints geradas) | 1.295k | overhead fixo por sprint |
| merge-review (2 tasks revisadas) | 2.335k | maior componente |
| **Total pipeline** | **4.226k** | para 2 tasks read_only triviais |
| Execução direta (2 tasks) | 651k | sem pipeline |
| **Overhead ratio** | **6,5x** | pipeline mais caro que direto |

## Projeção com Fixes Sprints 19-21

| Componente | Tokens antes | Tokens depois | Economia |
|---|---|---|---|
| fit-evaluator (tasks determinísticas) | 596k | 0 tokens | -596k |
| fit-evaluator (tasks needs_llm_eval) | 0 (não havia) | custo real da avaliação LLM | overhead fixo |
| merge-review (tasks programáticas) | 2.335k | 0 tokens | -2.335k |
| merge-review (tasks NEEDS_LLM_REVIEW) | 0 | custo real | overhead fixo |
| sprint-generator | 1.295k | 1.295k (sem mudança nesta série) | 0 |
| **Total projetado** | **4.226k** | **~1.295k** | **-2.931k (-69%)** |

## Resultado da Phase 2 (router_deterministic)

Tasks roteadas deterministicamente: 5 de 5
Tasks needs_llm_eval: 0 de 5
Execução sem erro: SIM

### Tabela de roteamento (<pipeline-project>-sandbox, 2026-05-01)

| task_id | decision | agent | reason |
|---|---|---|---|
| FP-T01 | always_local | local | task_type:read_only in always_local |
| FP-T02 | always_local | local | task_type:read_only in always_local |
| FP-T03 | try_local_first | local | task_type:multi_file_edit in try_local_first |
| FP-T04 | try_local_first | local | task_type:multi_file_edit in try_local_first |
| FP-T05 | always_claude | claude | task_type:long_text_generation in always_claude |

**FP-T04 nota**: anteriormente roteava `always_claude` por large_file gate bug (Sprint 18). Fix confirmado nesta sprint — agora roteia `try_local_first` corretamente.

## Observações

- Sprint-generator não foi modificado nesta série — redução adicional possível em sprint futura
- Economia real depende da proporção de tasks com task_type definido no backlog
- Threshold min_pipeline_tokens: 4000 não foi testado E2E nesta série (requer integração com orchestrator.py)
- 5/5 tasks roteadas deterministicamente neste backlog — 0 tokens de LLM evaluation necessários para routing
