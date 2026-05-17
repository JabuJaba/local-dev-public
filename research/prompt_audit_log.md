# Prompt Audit Log — Sprint 16

Data: 2026-05-01
Objetivo: Auditar aderência dos prompts das skills ao comportamento real de qwen3.6, gemma4 e Codex.

---

## Skill: local-sprint-optimizer

### Mudança 1 — Corrigir claim de latência do qwen3.6 thinking mode

**Antes:** `custo de latência é marginal e aceitável`
**Depois:** `custo real: ~12-13 tok/s efetivos com thinking ativo (benchmark 36 tok/s era non-thinking; ~2/3 dos tokens gerados são thinking content — Sprint 15)`
**Motivo:** Sprint 15 confirmou empiricamente que thinking mode em uso real com tool use produz 12-13 tok/s, não 36. O benchmark de 36 tok/s foi medido em non-thinking mode via API Ollama direta — contexto ausente na skill original.
**Doc que fundamenta:** `handoffs/handoff_sprint15.md` §Tok/s observado vs. esperado

### Mudança 2 — Atualizar forma explícita de invocação batch (pós-sprint-15)

**Antes:** Forma explícita mostrava `claude --bare --model qwen3.6:35b-a3b-q4_k_m ... --print "..."`
**Depois:** Separar claramente invocação interativa (qwen sem --print → Claude Code CLI) de batch (qwen --print → qwen_api.py). Forma explícita batch agora é `python scripts/qwen_api.py --print "..."`. Adicionada nota sobre known issue de tool use via CLI (thinking block) e quando usar cada forma.
**Motivo:** Sprint 15 atualizou o `.bashrc` para rotear `qwen --print` para `qwen_api.py` (API Ollama direta com tool-use loop próprio), não para Claude Code CLI. A forma explícita antiga levava o usuário a invocar `claude --bare --model ... --print`, que tem o thinking-block bug.
**Doc que fundamenta:** `handoffs/handoff_sprint15.md` §Correção implementada + .bashrc atualizado

---

## Skill: sprint-generator-unified

### Mudança 3 — Clarificar `--print` como "batch only" com nota pós-sprint-15

**Antes:** `--print` documentado como "opcional" para Modo B, com implicação de ser intercambiável com modo interativo.
**Depois:** `--print` marcado explicitamente como **batch only** no Modo A; Modo B documentado como "não usar --print" em sessão interativa. Adicionada nota que pós-sprint-15 `qwen --print` / `gemma --print` roteiam para `qwen_api.py`.
**Motivo:** Clareza necessária pois pós-sprint-15 o comportamento do alias mudou: `--print` agora bypassa Claude Code CLI. Usuário que usasse `--print` em Modo B (manual) receberia output via qwen_api.py (sem sessão interativa), não o comportamento esperado.
**Doc que fundamenta:** `handoffs/handoff_sprint15.md` §Correção implementada; `research/shim_gap_analysis.md` §Hipóteses

### Mudança 4 — Codex sprint template: adicionar lint/pre-commit em Entrega

**Antes:** Entrega listava diff.patch, test_output.log, notes.md — sem menção a lint.
**Depois:** Adicionada instrução para rodar lint/pre-commit antes de salvar (flake8/ruff/pre-commit) e reportar em notes.md, sem bloquear entrega por falhas em arquivos não-modificados.
**Motivo:** Codex best practices docs recomendam explicitamente "Include steps to reproduce an issue, validate a feature, and run linting and pre-commit checks" como padrão. O template anterior omitia esse passo.
**Doc que fundamenta:** `<workspace>/codex-docs/data/clean/codex/learn/learn-best-practices-9b101352b13cd35a.md` §Improve reliability with testing and review

---

## Skill: fit-evaluator

### Mudança 5 — Adicionar `large_file` como gate em limites conhecidos

**Antes:** Limites conhecidos listavam: long_text_generation, generator_coroutine, async_internals, multi_file_cross_dependency. Sem gate para tamanho de arquivo.
**Depois:** Adicionado `large_file: arquivo-alvo principal >12KB → always_claude`. Gate inclui exceção para tasks read-only. Campo adicionado ao schema `limits_checked` do veredito.
**Motivo:** CLAUDE.md documenta timeout consistente em 300s para qwen3.6 em arquivos >12KB (Sprint 8: cleaner.py 18KB, validate.py 20KB, pipeline_cpu.py 18KB). CLAUDE.md recomenda explicitamente "Adicionar max_file_kb: 12 como filtro em try_local_first". A skill não aplicava esse filtro no momento da avaliação de fit, causando handoffs previsíveis.
**Doc que fundamenta:** `CLAUDE.md` §Gotcha arquivos grandes (>15KB); Sprint 8 dados empíricos

### Seção 0b — Confirmação de validade

A seção 0b (auto-detecção sem args) foi avaliada e está **válida**. O fluxo (cwd → backlog.yaml → batch mode; sem backlog → sprint discovery) é internamente consistente. Nenhuma edição necessária.

---

## Resumo por skill

| Skill | Mudanças | Status |
|-------|----------|--------|
| local-sprint-optimizer | 2 (latência thinking, forma explícita batch) | ✓ Aplicado |
| sprint-generator-unified | 2 (--print batch only, lint Codex) | ✓ Aplicado |
| fit-evaluator | 1 (large_file gate + schema) | ✓ Aplicado |

Total: 5 edições fundamentadas em docs. 0 edições por tentativa e erro.

---

## Sprint 18 — Correções de roteamento e veredicto

Data: 2026-05-01

### Mudança 6 — fit-evaluator: gate large_file global → condicional agent==local

| Sprint | Skill | Mudança | Causa raiz |
|--------|-------|---------|------------|
| Sprint 18 | fit-evaluator | large_file gate global → condicional agent==local | Sprint 17 FP-T04 roteado errado: task `expected_routing: codex` foi bloqueada pelo gate >12KB que existe apenas para timeout do qwen, não para Codex/Claude |

**Antes:** gate `large_file >12KB` aplicado universalmente → bloqueava Codex mesmo sem limite de timeout.
**Depois:** gate só se aplica quando `agent == local`; quando `agent == codex` ou `agent == claude`, gate não é avaliado.
**Motivo:** gate foi criado em Sprint 8 para timeout consistente do qwen3.6 em arquivos grandes (cleaner.py 18KB etc.). Não existe razão para bloquear Codex ou Claude nessa condição.
**Doc que fundamenta:** Sprint 17 FP-T04 roteamento incorreto; CLAUDE.md §Gotcha arquivos grandes

### Mudança 7 — universal-review-merge: re-execução mascarava falha do agente como ACEITAR

| Sprint | Skill | Mudança | Causa raiz |
|--------|-------|---------|------------|
| Sprint 18 | universal-review-merge | re-execução mascarava falha do agente como ACEITAR | Sprint 17 FP-T01: qwen entregou 4 IDs numéricos; merge-review re-executou oracle, encontrou 18 tickers corretos e marcou ACEITAR — mascarando a falha real |

**Antes:** nenhuma distinção entre verificação passiva (inspecionar output do agente) e re-execução (skill refaz a tarefa). Resultado: oracle passava mesmo quando o agente havia falhado.
**Depois:** distinção explícita na seção 3B + regra inviolável: se oracle precisou ser re-executado pela skill, agente falhou → veredicto deve ser DEVOLVER ou ASSUMIR-CLAUDE, nunca ACEITAR.
**Motivo:** re-execução pela skill não prova que o agente entregou o resultado correto — prova o oposto. Mascarar isso como ACEITAR dá falsa confiança e polui métricas de qualidade.
**Doc que fundamenta:** Sprint 17 FP-T01 análise post-mortem; advisor confirmation Sprint 18

---

## Resumo consolidado (Sprints 16–18)

| Sprint | Skill | Mudanças |
|--------|-------|----------|
| 16 | local-sprint-optimizer | 2 |
| 16 | sprint-generator-unified | 2 |
| 16 | fit-evaluator | 1 |
| 18 | fit-evaluator | 1 (large_file condicional) |
| 18 | universal-review-merge | 1 (passiva/re-execução) |
| Sprint 19-21 | fit-evaluator | Section 0c: router_deterministic pré-passo — tasks com task_type claro bypass LLM call | Sprint 17 empirical: 596k tokens fit-evaluator para 2 tasks read_only triviais |
| Sprint 19-21 | universal-review-merge | Section 3B: oracle_programmatic pré-passo — tasks simples bypass LLM review | Sprint 17 empirical: 2.335k tokens merge-review para tasks read_only/simple_edit |

Total acumulado: 9 edições. 0 por tentativa e erro.
