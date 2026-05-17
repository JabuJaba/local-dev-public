# Handoff — Local Model Viability under Production Workload

Fechamento formal escrito retroativamente em 2026-05-17 (item de backlog da Sprint 39 Phase 6).

## Veredito

**Finding A confirmado: `num_ctx=4096` default era o gargalo silencioso da rota Claude Code via shim Ollama.** O alias `qwen-cl` original sofria de truncamento silencioso no path `/v1/messages` (Anthropic-compat) — modelo via apenas os últimos 4k tokens do prompt, sem erro nem aviso. Mudança para Modelfile com `num_ctx 65536` baked-in (`qwen3.6-64k:latest`) resolveu. Comportamento qualitativamente diferente comprovado em 3 runs (entradas 5/6/7 do eval).

Comportamentos secundários documentados: modo consultivo, hallucination, scope-creep + loop em prompts monolíticos.

## 7 entradas eval (`.eval/sprint38.jsonl`)

| # | Tool/Model | Task | Result | Wall | Tokens cumul. | Files OK | Friction principal |
|---|---|---|---|---|---|---|---|
| 1 | gemma-cl / gemma4:26b | <pipeline-project>-6.36 full-sprint (4 phases monolítico) | reject-null-delivery | 10 min | n/a | 0/0 | menu genérico ou crunched sem output; tool calls invisíveis |
| 2 | gemma-cl / gemma4:26b | phase2 surgical-edit isolated | abort-too-slow | 10 min | 854 out | 0/1 | 2 tok/s observado vs 31.5 benchmark — ordem de magnitude pior por thinking-heavy mode |
| 3 | qwen-cl (4k) / qwen3.6:35b-a3b | phase2 surgical-edit | reject-consultative-mode | 3.83 min | 23k in / 2k out | 0/1 | modo consultivo: leu 3 arquivos, gerou tabela de domínios + menu pedindo confirmação. ctx=4k confirmado (num_ctx default) |
| 4 | qwen-cl (4k) / qwen3.6:35b-a3b | phase2 surgical-edit imperative prompt | reject-broken-delivery+hallucination | 5.58 min | — | 0/1 (1 broken, 1 hallucinated) | Edit deixou `elif` órfão → SyntaxError; para o 2º arquivo, hallucinou rewrite no chat com tickers fictícios (<pipeline-project>01, ALRO4, KOPA11_DEVIATION_ALLOWED) |
| 5 | qwen64-cl / qwen3.6-64k | phase2 surgical-edit imperative | **ACCEPT** | 12.33 min | 508k cumul / 4k out | **3/3** | entrega limpa: gates rodados pelo próprio modelo, pycache stale identificado, PS vs Bash auto-corrigido, instrução "não commitar" respeitada. ctx_observed=20k. **Finding A confirmado.** |
| 6 | qwen-cl (renomeado p/ qwen3.6-64k) | phase1 multi-source orchestration | ACCEPT-WITH-EXTERNAL-BLOCK | TBD | 132k cumul | 1/1 | zero friction do modelo; bloqueio era Fundamentus upstream (desdobramento TICKER7 10:1 ainda não refletido) |
| 7 | qwen-cl / qwen3.6-64k | V1 minimal invocation (todas as 4 phases) | REJECT-scope-creep+loop+ctx-saturation | 142 min | 4.53M cumul / 58k out | scope misaligned | re-interpretou 4 phases como 7 unilateralmente, fez Option B/C fora-de-escopo, saturou 64k ctx, loop 1→2→3→2→1 |

## Findings

**Finding A (PRIMARY):** num_ctx=4096 default no path /v1/messages do shim Anthropic-Ollama truncava prompt silenciosamente. Workaround: Modelfile com num_ctx baked-in (`Modelfile.qwen3.6-64k` → `qwen3.6-64k:latest`). Validado por 3 runs com ctx_observed >4k em entries 5/6/7.

**Finding B (gemma2 tok/s):** gemma4:26b operou a 2 tok/s vs benchmark Sprint 36b de 31.5 tok/s. Causa provável: thinking-heavy mode adicionando overhead invisível. Conclusão: gemma4 viável para Bash mas não para surgical edits supervisionados em tempo real.

**Finding C (consultative mode under 4k ctx):** qwen3.6 sob num_ctx=4096 default + prompt curto entra em modo consultivo (tabela de domínios + menu pedindo confirmação) ao invés de executar. Padrão observado em gemma também em entry 1. Não é bug do modelo — é resposta à instrução ambígua que cabe inteira no ctx truncado.

**Finding D (hallucination under imperative prompt + 4k ctx):** quando forçado a executar via prompt imperativo, qwen3.6@4k aplica Edits incompletos (deixa órfãos sintáticos) e/ou alucina rewrites no chat com identificadores fictícios. Comportamento ausente em qwen3.6-64k.

**Finding E (V1 minimal invocation não é autônomo):** prompt "Execute <full-path-da-sprint>" ainda precisa de confirmação humana ("Executar todas as fases"). Após confirmação, modelo capaz mas sem disciplina de escopo: reinterpreta phases, satura contexto, entra em loop. Conclusão: sprint doc precisa scope-fence explícito + batch-gate per-phase. → Substrato direto da Sprint 39 Phase 3 (que confirmou empiricamente que mesmo com Task tool disponível, modelo não muda esse padrão).

## O que ficou built/verified vs pivot

- **Phase 1 built/verified (commit ecf43f4)**: `ingest_from_<pipeline-project>-source` fail-closed em SANDBOX_DB_PATH ausente. Pytest 23 passed / 4 pre-existing FAIL / 128 skipped. Prod baseline ref: 779 relatórios, 28 avisos, 23 comunicados.
- **Phase 2 not delivered**: tentativa supervisor-chosen (`filter_total_rows` fix) abortada por decisão do usuário — não alinhada com prioridade de backlog. Worktree `<workspace>/<pipeline-project>-local-test` deletado, branch `sprint38-local-test` removido.
- **Pivot**: trabalho real migrou pra `<pipeline-project>` branch `sprint-6.36` (re-coleta market_data pós-desdobramento TICKER7), executado pelo usuário em main checkout. Claude usado em modo supervisionado per-phase, não autônomo full-sprint.

## Artefatos

- `.eval/sprint38.jsonl` — 7 entradas registradas pelo usuário
- `.checkpoint.json` — `prior_sprint_38_archive` carrega save_point_0 e pivot
- Código: `ingest_from_<pipeline-project>-source` fail-closed em `extractor/...` (<pipeline-project> commit `ecf43f4`)
- Aliases PowerShell: `qwen-cl` → `qwen3.6-64k:latest` (renomeação ocorrida durante a sprint); `qwen4k-cl` como legacy reproducer do gotcha; `qwen64-cl` como alias compatível

## Próxima sprint (foi Sprint 39 — fechada 2026-05-17)

Sprint 39 explorou a pergunta arquitetural levantada por Finding E: planner local pode despachar sub-agents para evitar prompts monolíticos? Resposta: tecnicamente sim, comportamentalmente não. Ver `handoff_sprint39.md` + ADR-018.
