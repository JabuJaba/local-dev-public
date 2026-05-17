# Refactor Roadmap — Local-Dev Course-Correction
*Última atualização: 2026-05-07 — autoritativo até superseder explícito*

**Para quem chega frio nessa sprint:** lê este arquivo + `findings-2026-05-07-011700.md` + `plan_local-pipeline_2026-05-07.md`. Não precisa rodar `/diagnose` ou `/project-plan` — escopo já cravado.

---

## Status atual (2026-05-07 01:30)

- Diagnóstico ✅ — `.diagnose/findings-2026-05-07-011700.md`
- Plano estratégico ✅ — `analise/plan_local-pipeline_2026-05-07.md` (4 tracks) + este roadmap (sprint chain)
- Sprints 32-34 escritas ✅ — `sprints/sprint_3{2,3,4}_*.md`
- Sprints 31a-d planejadas mas **superseded** — arquivamento agendado em Sprint 33 Phase 3
- Sprint 30 lever 3 (rtk_trim) confirmado morto — desativação em Sprint 32 Phase 3
- Próxima ação imediata: `/sprint-execute sprints/sprint_32_kill-switch.md` (≤1h30, custo zero)

---

## Sprint chain — 32 a 42

| # | Sprint | Status | Phases | Custo | Gate de entrada | Decide |
|---|---|---|---|---|---|---|
| 32 | kill-switch (3 testes) | escrita | 3 | nenhum | Ollama on | direção do refator |
| 33 | sanity-check + ramo (A/B) | escrita | 3 | nenhum | Sprint 32 PASS/FAIL conhecidos | Maestro vs deterministic |
| 34 | contratos (hooks + acceptance) | escrita | 2 | nenhum | independente | trava deploy-antes-de-validar |
| 35 | git init via /git-prep | a escrever | 3 | nenhum | independente, paralelizável | rede de segurança |
| 36-A | Maestro mínimo (3 agents) | a escrever | 5 | nenhum | Sprint 33 ramo=A | viabilidade real Maestro |
| 36-B | Deterministic router (sem LLM) | a escrever | 4 | nenhum | Sprint 33 ramo=B | economia via rotinas Python |
| 37 | <pipeline-project> safety (env override + worktree) | a escrever | 4 | nenhum | Sprint 34 acceptance contract | proteção prod <pipeline-project> |
| 38 | Aider em <pipeline-project> real | a escrever | 4 | nenhum | Sprint 37 PASS | benchmark task <pipeline-project> autêntica |
| 39 | Memory recall hook refeito | a escrever | 4 | nenhum | Sprint 34 | recall mid-sessão funcional |
| 40 | Bridge learnings.db ↔ claude-mem | a escrever | 3 | nenhum | Sprint 39 | unificar memória |
| 41 | Cleanup operacional | a escrever | 4 | nenhum | independente | dívida estrutural |
| 42 | Re-medição agregada ADR-015 | a escrever | 2 | nenhum | 4 sem após 32+33+36 | gate da fase audit |

**Por que 36-A e 36-B existem como exclusivos:** Sprint 33 escolhe um ramo. O outro NÃO é executado (não vira dívida no backlog — sai do plano). Se ramo A falhar empiricamente em Sprint 36-A acceptance external, refletir em ADR e considerar pivot pra ramo B numa Sprint 36-B retroativa.

---

## Decision points (3 gates críticos)

### Gate 1 — Sprint 32 Phase 1 (`model: inherit` propaga pra Ollama?)

| Outcome | Próxima ação |
|---|---|
| **PASS** (log Ollama mostra subagent hit) | Sprint 33 sanity-check confirma stack → ramo A → Sprint 36-A escreve Maestro mínimo |
| **FAIL** (subagent volta pra api.anthropic.com) | Sprint 33 pivota sanity-check pra "deterministic router patterns" → ramo B → Sprint 36-B substitui LLM por Python no fit-evaluator |
| **AMBÍGUO** (não consegue tail Ollama logs) | Repetir Phase 1 com setup mais explícito antes de prosseguir |

### Gate 2 — Sprint 32 Phase 2 (`num_ctx` no path Anthropic-compat)

| Outcome | Implicação |
|---|---|
| **PASS** (modelo lista 18 fundos completos) | Sprint 8 economia 37,3% confiável; benchmarks Sprint 1.5 não-contaminados; segue plano |
| **FAIL** (modelo lista 7 ou outro número parcial) | Truncamento silencioso ativo desde Sprint 7. ADR-013 estende pro path Anthropic-compat. **Toda sprint que rodou sessão local antes desta tem dado contaminado.** Sprint 33 Phase 3 ADR-016 referencia. Antes de Sprint 36+ executar, fix obrigatório (Modelfile com `num_ctx 32768` ou parâmetro nas envvars Claude Code) |

### Gate 3 — Sprint 36-A ou 36-B Phase final (acceptance external)

| Outcome | Próxima ação |
|---|---|
| **External acceptance PASS** (custo Claude zero medido em 3 tasks reais OU rotina determinística cobre fit-evaluator) | Sprint 37+ segue conforme plano |
| **External acceptance FAIL** (Maestro não funciona OU rotina não cobre) | NÃO marcar `phase_completed`. Re-abrir Sprint 33 com novo input. Considerar pivot. Documentar em ADR como "ramo X tentado, falhou em Sprint Y" |

---

## Anti-pattern guards (não-negociáveis para próximas sprints)

1. **Não declarar sprint completa sem external acceptance** (1 medição empírica, número antes/depois ou ground-truth diff). Internal acceptance sozinho — testes unitários, smoke — não basta para sprints que mudam routing/hook/economia.
2. **Não propor hook sem checar `analise/claude-code-hooks-contract.md`** (criado em Sprint 34 Phase 1). PostToolUse não muta tool_result — esse contrato é mecânico, não opinativo.
3. **Não escrever em <pipeline-project> prod sem `$env:SANDBOX_DB_PATH` apontando pra sandbox.** Worktree git **não isola SQLite** que vive fora do repo (`<workspace>/<pipeline-project>-extraction/<pipeline-project>.db`).
4. **Não rodar `/project-plan` reset.** Spec.md e constraints.md existem; o que precisa é course-correction (este roadmap), não restart.
5. **Não tentar lever 3 (rtk_trim ou variantes PostToolUse trim) de novo.** Estruturalmente impossível pelo contrato de hooks. Re-leitura do contrato em Sprint 34 antes de qualquer proposta similar.

---

## Mapa de arquivos canônicos

**Não substituir / não duplicar — atualizar inline:**
- `spec.md` — escopo macro (Trilha 1, 2, 3 fechadas)
- `constraints.md` — ambiente, modelos, endpoints
- `ADR.md` — decisões arquiteturais (ADR-015 vivo, ADR-016 pendente Sprint 33)
- `CLAUDE.md` — regras operacionais; ganha 2 linhas em Sprint 34 Phase 1+2
- `analise/plan_local-pipeline_2026-05-07.md` — plano estratégico em tracks (visão high-level)
- `analise/refactor-roadmap_2026-05-07.md` — **este arquivo** (visão sprint-por-sprint)
- `.diagnose/findings-2026-05-07-011700.md` — findings do diagnose 2026-05-07
- `.checkpoint.json` — estado live (sprint atual, phase_completed)

**Vai morrer (arquivar conforme sprint indicado):**
- `sprints/sprint_31a-d_*.md` — superseder em Sprint 33 Phase 3
- `~/.claude/hooks/rtk_trim.py` settings.json entry — desativar em Sprint 32 Phase 3 (arquivo no disco fica como referência)
- `brainstorm_pipeline-token-economy.md` Phases 0-6 — adicionar header SUPERSEDED em Sprint 41

**A criar (em Sprint indicada):**
- `analise/claude-code-hooks-contract.md` — Sprint 34 Phase 1
- `analise/sprint-acceptance-contract.md` — Sprint 34 Phase 2
- `analise/sprint32_phase{1,2}_*_2026-05-XX.md` — Sprint 32 Phase 1+2
- `sanity-cache/maestro-local-ollama-stack_*` — Sprint 33 Phase 1
- `analise/sprint33_branch-decision_*` — Sprint 33 Phase 2

---

## Quando re-rodar `/sprint-generator`

- Após Sprint 33 fechar com ramo cravado → gerar Sprint 36-A **OU** 36-B (não ambos)
- Após Sprint 34 fechar → contratos disponíveis para Sprint 37+ herdar como input
- Após Sprint 36 acceptance external PASS → gerar Sprint 37 (<pipeline-project> safety) e Sprint 38 (aider)
- Após Sprint 39 PASS → gerar Sprint 40 (bridge memory)
- Sprint 41 (cleanup) e Sprint 35 (git init) podem ser geradas a qualquer momento (independentes)

---

## Re-validação ADR-015 (gate da fase audit)

Agendado para `2026-06-03` (4 sem pós-Sprint 30) — agora corrige-se para `2026-06-XX` baseado em quando Sprint 36 fechar com external acceptance. Sprint 42 roda:
- `python analise/_sprint27_aggregate.py`
- Comparar top-3 gasto semanal <pipeline-project> vs baseline semanal

| Queda total | Decisão |
|---|---|
| ≥30% | ADR-015 confirmado, fase audit fecha em definitivo |
| 15-30% | Analisar contribuição por lever; lever 3 = 0 confirmado; considerar lever 4 (routing seletivo) |
| <15% | Reabrir ADR-015; rever tese central |

---

## Custo total estimado (Claude API)

Sprint 32-42 inteiro: **custo Claude zero se ramo A funcionar** (Maestro local). Se ramo B, custo permanece de fit-evaluator/sprint-generator (já em uso) mas elimina Claude do **routing** (ganho marginal). Custo de execução das próprias sprints (esta sessão e futuras) é o overhead da própria orquestração — alvo é manter overhead minimo até Sprint 42.

---

_Este arquivo é o source-of-truth da execução do refator. Editar inline conforme sprints fecham. Não criar v2 — atualizar este._
