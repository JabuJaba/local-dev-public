# ADR — local-dev Orchestrator

Registro de decisões arquiteturais do pipeline autônomo local.

---

## Table of Contents

- [ADR-001 — Context enrichment enforced at orchestrator, not model instruction level](#adr-001--context-enrichment-enforced-at-orchestrator-not-model-instruction-level)
- [ADR-002 — canonical_sources injection order: after constraints, before retry context](#adr-002--canonical_sources-injection-order-after-constraints-before-retry-context)
- [ADR-003 — Qwen3.6 35B A3B não substitui qwen3coder-local no slot 1-2](#adr-003--qwen36-35b-a3b-não-substitui-qwen3coder-local-no-slot-1-2)
- [ADR-004 — Gemma4 como modelo recomendado para OCR local](#adr-004--gemma4-como-modelo-recomendado-para-ocr-local)
- [ADR-005 — Local-first routing: Docker workspace isolation sobre safety interceptor](#adr-005--local-first-routing-docker-workspace-isolation-sobre-safety-interceptor)
- [ADR-006 — ANTHROPIC_BASE_URL para Claude Code usar modelos locais (não-oficial)](#adr-006--anthropic_base_url-para-claude-code-usar-modelos-locais-não-oficial)
- [ADR-007 — Safety interceptor project-local via hook PreToolUse](#adr-007--safety-interceptor-project-local-via-hook-pretooluse)
- [ADR-008 — Schema v0.2 migration: one-way adapter, corte limpo](#adr-008--schema-v02-migration-one-way-adapter-corte-limpo)
- [ADR-010 — Sprint 9: routing hardening pós-medição empírica (max_file_kb + remoção destructive_local)](#adr-010--sprint-9-routing-hardening-pós-medição-empírica-max_file_kb-remoção-destructive_local)
- [ADR-009 — Sprint 7: rollout local-first routing para Subtitle-Forge autorizado](#adr-009--sprint-7-rollout-local-first-routing-para-subtitle-forge-autorizado)
- [ADR-011 — Sprint 10: manter qwen3.6:35b-a3b como primário até Ollama suportar Qwen3.6-27B denso](#adr-011--sprint-10-manter-qwen3635b-a3b-como-primário-até-ollama-suportar-qwen36-27b-denso)
- [ADR-011b — gui_automation movido para always_claude (2026-04-30)](#adr-011b--gui_automation-movido-para-always_claude-2026-04-30)
- [ADR-012 — Pipeline de delegação tem ROI negativo para tasks simples; large_file gate deve ser agent-scoped](#adr-012--pipeline-de-delegação-tem-roi-negativo-para-tasks-simples-large_file-gate-deve-ser-agent-scoped)
- [ADR-013 — Ollama num_ctx deve ser explicitamente configurado para tasks com arquivos >3KB](#adr-013--ollama-num_ctx-deve-ser-explicitamente-configurado-para-tasks-com-arquivos-3kb)
- [ADR-014 — Leak <pipeline-project> é power-law em mega-sessões, não baseline distribuído (2026-05-06)](#adr-014--leak-pipeline-project-é-power-law-em-mega-sessões-não-baseline-distribuído-2026-05-06)
- [ADR-015 — Encerramento da fase audit (Sprints 23-27): Trilha 3 redirecionada para 3 levers fora-do-source (2026-05-06)](#adr-015--encerramento-da-fase-audit-sprints-23-27-trilha-3-redirecionada-para-3-levers-fora-do-source-2026-05-06)
- [ADR-015 Apêndice — Plano executável priorizado](#adr-015-apêndice-plano-executável-priorizado)
- [ADR-016 — Ramo A escolhido: Maestro local (3 agents, cautela) como próxima trilha de implementação (2026-05-07)](#adr-016--ramo-a-escolhido-maestro-local-3-agents-cautela-como-próxima-trilha-de-implementação-2026-05-07)
- [ADR-017 — Executor inter-step context: Option C (independent steps) para Sprint 36b (2026-05-07)](#adr-017--executor-inter-step-context-option-c-independent-steps-para-sprint-36b-2026-05-07)
- [ADR-018 — Sub-agents via Task tool: tecnicamente viaveis, comportamentalmente nao-utilizaveis em qwen3.6-64k (2026-05-17)](#adr-018--sub-agents-via-task-tool-tecnicamente-viaveis-comportamentalmente-nao-utilizaveis-em-qwen36-64k-2026-05-17)

---


## ADR-001 — Context enrichment enforced at orchestrator, not model instruction level

**Data:** 2026-04-17

**Decisão:**
As melhorias de contexto (source-of-truth, integrity checks, snapshots destrutivos) são implementadas
como lógica no orchestrator — não como instruções de prompt enviadas ao modelo.

**Motivação:**
Análise do relatório Claude Code Insights (2026-03-20 a 2026-04-17) identificou 3 padrões recorrentes
de fricção: (1) modelo operando com arquivo errado/stale, (2) sem validação de integridade pós-execução,
(3) sem snapshot antes de ops destrutivas.

As sugestões do report foram originalmente formuladas para Claude Code (frontier model) como instruções
CLAUDE.md. Para Qwen3-Coder 30B e Gemma4 26B, modelos locais menores, instruções de auto-regulação
são menos confiáveis. A decisão foi enforçar no orchestrator, independente do modelo.

**Alternativas rejeitadas:**
- Adicionar ao system prompt / AGENTS.md: dependeria da confiabilidade do modelo em seguir múltiplas
  constraints — inconsistente em 26-30B range.
- Resolver via post-processing do output: mais frágil que um gate explícito com exit code.

**Implementação:**
- `canonical_sources`: campo opcional no backlog task; `resolve_canonical_context()` injeta conteúdo antes do despacho
- `integrity_cmd`: campo opcional; `run_integrity_check()` roda após `test_cmd` passar
- `destructive`: flag booleana; `create_pre_task_snapshot()` cria git tag antes da 1ª tentativa

---

## ADR-002 — canonical_sources injection order: after constraints, before retry context

**Data:** 2026-04-17

**Decisão:**
Canonical sources são injetadas **depois** de constraints (AGENTS.md / _project_context) e **antes**
do retry context + task original. Ordem final no prompt:

```
[slot_prefix] [refactor/list_prefix] [constraints] [canonical_sources] [retry_context] [task]
```

**Motivação:**
- Constraints (regras arquiteturais) devem aparecer primeiro — são invariantes do projeto.
- Canonical sources (dados autoritativos) vêm antes do task — o modelo precisa ter o dado
  antes de ver a instrução que o referencia.
- Retry context fica próximo ao task — proximidade semântica ajuda modelos com attention bias para tokens recentes.

**Alternativas rejeitadas:**
- Sources antes de constraints: inverteria a hierarquia regra→dado.
- Sources no final (após task): risco maior de ser ignorado por modelos com viés para tokens iniciais.

---

## ADR-003 — Qwen3.6 35B A3B não substitui qwen3coder-local no slot 1-2

**Data:** 2026-04-18

**Decisão:**
Qwen3.6 35B A3B (`qwen3.6:35b-a3b-q4_k_m`) permanece apenas como alias de compatibilidade. O slot 1-2 do orquestrador mantém `qwen3coder-local` (Qwen3-Coder 30B A3B). O slot 3 mantém `gemma4:26b`.

**Motivação:**
Benchmark 2026-04-18 (40 tasks coding): Qwen3.6 atingiu 29/40 (72%) — mesmo score do qwen3coder-local — porém com 10.7 tok/s vs ~20.8 tok/s do modelo coding especializado. Velocidade ~2x menor com qualidade idêntica não justifica a troca no slot de alta frequência (1-2 tentativas por task).

Única vantagem concreta: `lctx_03` (paginate off-by-one) passou no Qwen3.6 mas falha no A3B. Regressão compensatória: `ec_01` (Unicode NFC+casefold) falhou no Qwen3.6 mas passava no A3B.

**Alternativas rejeitadas:**
- Usar qwen3.6 no slot 1-2: 2x mais lento sem ganho de qualidade — throughput do pipeline cai.
- Usar qwen3.6 no slot 3 (substituindo Gemma4): Gemma4 tem score 85% vs 72% do Qwen3.6 — downgrade claro.

---

## ADR-004 — Gemma4 como modelo recomendado para OCR local

**Data:** 2026-04-18

**Decisão:**
Para tarefas de OCR/visão no pipeline, usar `gemma4:26b` com system prompt `"Return ONLY the extracted text, no explanations, no preamble."`.

**Motivação:**
Benchmark OCR 2026-04-18 (10 tasks, 4 categorias): Gemma4 e Qwen3.6 empatam em acurácia (8/10, 80%), mas Gemma4 é 47% mais rápido (9.9 vs 6.7 tok/s). As 2 falhas são idênticas nos dois modelos e causadas por verbosidade (preamble conversacional), não por incapacidade visual — resolvível com system prompt. Gemma4 já era o modelo de slot 3 (qualidade), evitando troca de modelo para tasks OCR.

**Alternativas rejeitadas:**
- Claude API (claude-sonnet-4-6) para OCR local: custo extra, latência de rede, não necessário para tasks simples de extração.
- Qwen3.6 para OCR: mesma acurácia, menor velocidade, requer troca de modelo se Gemma4 já estiver em VRAM.

---

## ADR-005 — Local-first routing: Docker workspace isolation sobre safety interceptor

**Data:** 2026-04-19

**Decisão:**
Para isolar execução autônoma dos modelos locais, adotar Docker workspace isolation como mecanismo primário (sujeito a gate no Sprint 2.5), com safety interceptor como fallback. O modelo (Ollama) permanece no host; apenas os arquivos do projeto ficam dentro do container.

**Motivação:**
Safety interceptor requer parsing de tool calls para detectar padrões destrutivos — frágil e sujeito a falsos negativos. Docker workspace isolation é confinamento real: modelo pode fazer qualquer coisa dentro do container, projeto original no host fica intocado por design. GPU passthrough não é necessário porque o modelo não roda no container.

**Alternativas rejeitadas:**
- Safety interceptor como mecanismo único: detecta padrões conhecidos, mas não cobre edge cases.
- GPU-in-container (Ollama dentro do Docker): requer NVIDIA Container Toolkit for WSL2, adiado para sprint futura opcional.

**Gate:** Sprint 2.5 decide go/partial/no-go com dados reais de latência e compatibilidade de tool use.

---

## ADR-006 — ANTHROPIC_BASE_URL para Claude Code usar modelos locais (não-oficial)

**Data:** 2026-04-19

**Decisão:**
Usar `ANTHROPIC_BASE_URL=http://localhost:11434` (endpoint Anthropic-compat do Ollama, sem `/v1`) + `ANTHROPIC_AUTH_TOKEN=dummy` + `ANTHROPIC_CUSTOM_MODEL_OPTION=<modelo>` para redirecionar Claude Code para modelos locais. Manter endpoint `/v1` (OpenAI-compat) separado para o orchestrator.

**Motivação:**
Claude Code exige formato Anthropic (`/v1/messages`), não OpenAI. O orchestrator usa `/v1` (OpenAI-compat). São endpoints distintos no Ollama — não conflitam. A integração não é oficialmente suportada pela Anthropic mas documentada por Ollama, LM Studio e vLLM.

**Alternativas rejeitadas:**
- Proxy LiteLLM: camada extra de manutenção sem benefício claro se Ollama já expõe endpoint Anthropic-compat nativo.
- Claude Code só com modelos Claude: mantém custo total de tokens — objetivo é reduzir ≥20%.

**Risco aceito:** ANTHROPIC_BASE_URL pode quebrar sem aviso em updates do Claude Code. Mitigação: scripts start_local_mode.ps1 / start_claude_mode.ps1 permitem alternância rápida.

---

## ADR-007 — Safety interceptor project-local via hook PreToolUse

**Data:** 2026-04-21

**Decisão:**
Interceptar operações destrutivas (`rm`/`del`/`git reset --hard`/`git clean`/`Remove-Item -Recurse -Force`/Write overwrite/Write fora do sandbox/Edit removendo >50%) via hook PreToolUse em `.claude/settings.json` **project-local** (não global). Ativação gated por `CLAUDE_SAFETY_INTERCEPTOR=1` setado pelos scripts `start_local_*.ps1`. Mensagem enriquecida com modelo atual, alvo, tamanho e mtime.

**Motivação:**
Modelos locais não têm guardrails de raciocínio; um modelo 30B pode decidir `rm -rf` sem a hesitação que um frontier teria. Claude Code pede aprovação, mas sem contexto. Interceptor adiciona contexto explícito (qual modelo está rodando, tamanho do alvo) para o usuário decidir com mais informação.

**Alternativas rejeitadas:**
- Hook global em `~/.claude/settings.json`: firing em todos os repos, incluindo sessões normais com Claude cloud — falso-positivos operacionais.
- Docker workspace isolation (ADR-005): caminho planejado de longo prazo, mas requer overhead de container. Interceptor é complementar, não substituto.
- Exit code não-zero para bloquear: Claude Code exige `permissionDecision` em JSON no stdout; exit != 0 quebra o hook.

**Risco aceito:** `--dangerously-skip-permissions` em runs batch converte `"ask"` em allow silencioso. Para bloqueio duro em execução autônoma, adicionar `"deny"` gated por `CLAUDE_SAFETY_BLOCK=1` (não implementado em Sprint 2 por não ser necessário).

**Validação:** `tests/test_safety_interceptor.py` 10/10 passing; Sprint 2 Phase 3 20 tasks com interceptor ativo, 0 corrupções, 18/20 PASS.

---

## ADR-008 — Schema v0.2 migration: one-way adapter, corte limpo

**Data:** 2026-04-22

**Decisão:**
O adapter local-dev (Sprint 6) será one-way (v0.1 → v0.2). Não haverá período onde codex-fit-evaluator escreve v0.1 e v0.2 simultaneamente — o corte é limpo: antes de Sprint 6 codex-integration = v0.1, depois = v0.2.

Lógica do adapter: `if "schema_version" not in verdict: migrate_v01_to_v02(verdict)` — trivial e idempotente.

**Motivação:**
codex-integration confirmou (round 3, 2026-04-22) que Sprint 6 deles executa em dois passos sequenciais: (1) atualiza verdict_schema.md para v0.2, (2) roda `migrate_v01_to_v02.py` nos 3 vereditos existentes, (3) skills passam a escrever v0.2 direto — sem retrocompat com v0.1. Os arquivos v0.1 legados são migrados pelo script deles, não pelo adapter local.

**Alternativas rejeitadas:**
- Adapter bidirecional (0.1 ↔ 0.2): trabalho extra sem necessidade — nunca haverá escrita de volta em v0.1.
- Esperar migração completa antes de implementar adapter: Sprint 6 local pode rodar em paralelo; detecção por ausência de `schema_version` é estável.

---

## ADR-010 — Sprint 9: routing hardening pós-medição empírica (max_file_kb + remoção destructive_local)

**Data:** 2026-04-25

**Decisão:**
Duas mudanças de routing aplicadas como resultado direto dos dados empíricos do Sprint 8:

1. **`max_file_kb: 12`** adicionado à categoria `try_local_first` em `routing_rules.yaml`. Tasks cujos arquivos alvo excedem 12KB vão para `always_claude` sem tentativa local.

2. **`destructive_local` removido** como categoria de routing. Types `file_deletion`, `schema_migration_dry`, `bulk_rename` e o override `destructive: true` migrados para `always_claude`. Removido de `routing_rules.yaml`, `delegation_rules.yaml` e `orchestrator.py`.

**Motivação:**
Sprint 8 (20 tasks reais, <pipeline-project>_Extractor, Ollama online):
- 6 handoffs causados por timeout 300s em `cleaner.py` (18KB), `validate.py` (20KB), `pipeline_cpu.py` (18KB) → filtro `max_file_kb: 12` elimina esses handoffs previsíveis
- FG-17,18,20: modelo qwen3coder-local recusou tasks destrutivas em <130s mesmo com `isolated: true` no Docker (emissão de uncertainty phrases). FG-19: timeout 600s tentando mas sem sucesso. 0/4 resolved. Não é falha de infra — é comportamento de segurança do modelo.

**Sobre Gemma4 slot 3 (investigado Sprint 9 Phase 3):**
Slot 3 (attempt=3 → Gemma4) nunca foi acionado em Sprint 8 porque: (a) `try_local_first` tem `max_local_attempts=2` → `effective_max=2`, attempt 3 nunca roda; (b) `always_local` permite attempt 3 mas `should_escalate()` intercepta antes via uncertainty phrases ou `same_error_twice`. Comportamento documentado em `config.yaml` — intencional, não bug.

**Alternativas rejeitadas:**
- Manter `destructive_local` com Docker: ineficaz — o modelo recusa antes de tentar a ação, independente do isolamento. 0/4 resolved confirma o padrão.
- Filtro de arquivo por nome em vez de tamanho: lista de nomes é frágil; tamanho (12KB) é proxy estável e generaliza para novos arquivos grandes.
- Aumentar `aider_timeout_seconds` para arquivos grandes: timeout era 300s (já 5 min); aumentar para cobrir arquivos 18KB não garante sucesso e bloqueia o pipeline.

**Impacto:**
- `test_orchestrator_smoke.py` atualizado: 3 categorias (era 4), `destructive override → always_claude`
- Smoke tests: TODOS OS CHECKS PASSARAM
- pytest 5/5 passing

---

## ADR-009 — Sprint 7: rollout local-first routing para Subtitle-Forge autorizado

**Data:** 2026-04-23  
**Atualizado:** 2026-04-23 (Sprint 8 — medição direta concluída)

**Decisão:**
Pipeline unificado com `delegation_rules.yaml v0.2` ativado para produção. Rollout para Subtitle-Forge autorizado. Economia líquida real medida diretamente em Sprint 8: **37.3%** (faixa 54–74% projetada Sprint 7 não confirmada — ver análise abaixo).

**Dados que sustentam a decisão:**
- Sprint 3 sandbox: 55.6% economia medida diretamente (36 tasks, mix projetos)
- Sprint 5 Codex: 3/3 pilots ACEITAR (validação Codex side do pipeline)
- Sprint 6: 5/5 fit-evaluator regression PASS vs baseline Sprint 4
- Sprint 7 <pipeline-project>: 16/20 tasks PASS (4 bloqueadas por Docker engine offline — não falha do modelo)
- Sprint 7 fit-evaluator Subtitle-Forge: 4/5 decisões locais (SF-01, SF-02, SF-03, SF-05); SF-04 always_claude correto (long text)
- **Sprint 8 medição direta:** 9/20 resolved localmente, 11/20 handoff → 37.3% economia real

**Escopo do rollout:**
- <pipeline-project>_rollback_test: ativo (Sprint 8: 37.3% economia real medida)
- Subtitle-Forge: ativo (backup `Subtitle-Forge_backup_20260423_sprint7` criado, 51.981 arquivos)
- Demais projetos: aguardam próximo sprint para acompanhar métricas reais em produção

**Análise Sprint 8 — por que 37.3% vs 64.2% projetado:**
- Tarefas com arquivos >15KB (cleaner.py 18KB, validate.py 20KB, pipeline_cpu.py 18KB) causam timeout consistente (300s × 2 = handoff). Afeta FG-06,08,09,12,14,16.
- Tarefas destrutivas Docker (FG-17..20): modelo escala/recusa mesmo em isolamento. Padrão de segurança — não é falha de routing.
- Tarefas read-only em arquivos pequenos (<10KB): 9/9 resolvidas (100%). Routing correto.
- **Decisão: ROLLOUT CAUTELOSO (37.3% ≥ 20%)** — manter routing ativo; adicionar `max_file_kb: 12` como filtro adicional em try_local_first para evitar handoffs previsíveis em arquivos grandes.

**Alternativas rejeitadas:**
- Aguardar medição direta antes do rollout: atrasaria rollout por pelo menos 1 sprint; Sprint 3 já fornece base empírica sólida.
- Rollout para todos os projetos simultaneamente: risco maior sem confirmação por projeto.

---

## ADR-011 — Sprint 10: manter qwen3.6:35b-a3b como primário até Ollama suportar Qwen3.6-27B denso

**Data:** 2026-04-29

**Contexto:**
Pesquisa de Abril 2026 (`research/llm-optimization-handoff.md`) identificou que Qwen3.6-27B denso seria superior ao 35B-A3B MoE para coding sprints em 16GB VRAM: offload negligenciável (~800MB vs ~7GB), speculative decoding elegível, SWE-bench 77.2%. Porém, Qwen3.6-27B não é suportado pelo Ollama devido a mmproj files de visão separados.

Baseline numérico medido em Sprint 10 Phase 1 (`research/baseline_20260429.md`):

| Modelo | Prefill t/s | TG t/s | VRAM MB |
|--------|-------------|--------|---------|
| qwen3.6:35b-a3b-q4_k_m | 284.3 | 17.4 | 14441 |
| gemma4:26b | 842.4 | 31.5 | 14234 |
| qwen3coder-local (A3B MoE) | 457.6 | 37.3 | 14115 |

**Decisão:**
Manter `qwen3.6:35b-a3b-q4_k_m` como modelo primário da Rota Claude Code (Slot 1).

**Motivação:**
1. Qwen3.6-27B não disponível via Ollama — requer llama.cpp direto (infra separada não testada para uso interativo)
2. O 35B-A3B funciona com a infra atual (Ollama shim Anthropic) sem mudança operacional
3. TG t/s de 17.4 suficiente para coding sprints atuais
4. Migrar para llama.cpp direto como primário requer validação completa do shim e tool-use — risco sem benefício imediato mensurável

**Alternativas rejeitadas:**
- Migrar primário para llama.cpp + Qwen3.6-27B agora: infra não testada para uso interativo
- Usar qwen3coder-local como primário: melhor TG (37.3 t/s) mas proibido via Claude Code (emite XML legado `<function=Read>` — CLAUDE.md gotcha)

**Gatilho de reavaliação:**
Quando Ollama suportar Qwen3.6-27B via `ollama pull` (PR no repo Ollama resolvendo mmproj). Ao ocorrer:
1. Medir t/s com baseline_measure.py; comparar com qwen3.6:35b-a3b (17.4 TG t/s → esperado ~25 t/s)
2. Se ganho ≥ 30%: migrar primário, atualizar config.yaml + CLAUDE.md endpoints
3. Validar tool-use via Claude Code antes de ativar em produção

**Referência cruzada:** `research/baseline_20260429.md`; watchlist item 2 em `CLAUDE.md` seção "Watchlist Inferência"

---

## ADR-011b — gui_automation movido para always_claude (2026-04-30)

**Decisão:**
`gui_automation` (pyautogui, win32gui, click sequences) adicionado a `routing_rules.always_claude.types[]` em `delegation_rules.yaml`.

**Motivação:**
Sprint 24 <game-bot>-s24-p1: gemma4:26b stall de 15 minutos sem executar nenhum tool call. Causa: sprint doc Modo B continha coordenadas de clique, sequências de navegação no Script Manager e internos de GUI automation que o modelo não consegue executar via `--bare --allowedTools=Read,Edit,Write,Bash,Glob,Grep`. Modelo tentou reconciliar instruções com ferramentas disponíveis indefinidamente.

**Evidência empírica:**
- Sprint 24 Phase 1 (2026-04-30): 15min stall, zero tool calls, interrompido manualmente
- Task type misclassificado como `bash_safe` — na prática é `human_execute` (requer DreamBot aberto, cold_start, cliques em coordenadas)

**Alternativas rejeitadas:**
- Manter bash_safe com sprint doc stripped: strip remove os internos mas não resolve que a task em si requer GUI — o modelo ainda ficaria sem caminho de execução
- human_execute como tipo separado: desnecessário — always_claude cobre o mesmo resultado (Claude confirma ao usuário que a task requer execução manual)

**Impacto:**
- Qualquer task com pyautogui, win32gui, click, janela visível, coordenadas de tela → sempre_claude
- fit-evaluator deve classificar como `gui_automation` ao detectar esses padrões no contexto ou no código
- delegation_rules.yaml linha 119: entrada com comentário de evidência

---

## ADR-012 — Pipeline de delegação tem ROI negativo para tasks simples; large_file gate deve ser agent-scoped

**Data:** 2026-05-01

**Contexto:**
Sprint 17 mediu custo real do pipeline (fit-evaluator → sprint-generator → execução local → merge-review) vs execução direta via sprint-execute para 2 tasks `read_only` triviais no <pipeline-project>-sandbox.

**Decisão:**
1. Gate `large_file >12KB` no fit-evaluator deve ser condicional a `agent == local` apenas. Codex e Claude não têm o timeout de 300s que motivou o gate (Sprint 8 empírico com qwen). Gate global bloqueia Codex routing indevidamente.
2. merge-review deve distinguir verificação passiva (grep/diff no output do agente) de re-execução (skill refaz a tarefa para verificar). Re-execução → veredicto DEVOLVER/FALHA_AGENTE, nunca ACEITAR.
3. Pipeline tem ROI positivo apenas quando execução direta Claude custaria >>4k tokens (tasks longas, multi-arquivo, output >600 palavras) E o modelo local resolve corretamente.

**Evidência empírica:**
- Pipeline (2 tasks read_only): ~4.226k tokens Claude
- Execução direta (2 tasks read_only): 651k tokens Claude
- Overhead ratio: 6,5x
- qwen FP-T01: entregou resposta errada (4 IDs numéricos vs 18 tickers <pipeline-project>); merge-review mascarou com ACEITAR após re-execução
- FP-T04 (expected_routing: codex): bloqueado pelo gate large_file global — nunca chegou às heurísticas H1-H12

**Alternativas rejeitadas:**
- Manter pipeline para todas as tasks: custo de overhead supera economia para tasks simples
- Eliminar pipeline completamente: ROI existe para tasks complexas onde local resolve corretamente

**Impacto:**
- fit-evaluator corrigido Sprint 18: gate large_file com condição `agent == local`
- merge-review corrigido Sprint 18: distinção passivo vs re-execução, veredicto correto
- Threshold mínimo de complexidade para uso do pipeline: decisão pendente (sanity-check em andamento)

---

## ADR-013 — Ollama num_ctx deve ser explicitamente configurado para tasks com arquivos >3KB

**Data:** 2026-05-02

**Decisão:**
Toda chamada à API Ollama que inclua conteúdo de arquivo no prompt deve passar `"num_ctx": 16384` (ou maior) nas options. O orquestrador deve detectar tamanho estimado de prompt e expandir num_ctx dinamicamente quando necessário.

**Motivação:**
Teste E2E manual (2026-05-02) executou FP-T01 ao vivo: qwen3.6 retornou 7/18 tickers. A API reportou `tokens in: 4096` — confirmando que o modelo foi truncado no limite padrão do Ollama. O arquivo `column_mappings.json` tem 11KB (~4k+ tokens de prompt). O modelo processou apenas os primeiros tickers do JSON e produziu resposta plausível mas incompleta, sem qualquer aviso de truncamento.

Sprint 17 havia registrado "4 IDs numéricos em vez de 18 tickers" para a mesma task — a causa raiz era a mesma mas não tinha sido identificada. O padrão agora está confirmado empiricamente: **truncamento silencioso = resposta incorreta plausível**.

**Alternativas rejeitadas:**
- Confiar no num_ctx padrão do Ollama: descartado — trunca silenciosamente sem erro
- Usar num_ctx fixo alto para todos: aceitável como interim fix; solução melhor é dinâmico por tamanho de prompt
- Dividir arquivo grande em chunks: adiciona complexidade de reassembly desnecessária para tasks de leitura simples

**Impacto:**
- orchestrator.py deve adicionar lógica: `if estimated_prompt_tokens > 3000: options["num_ctx"] = 16384`
- scripts de teste devem usar `num_ctx: 16384` para arquivos >3KB
- FP-T01 re-executado com fix deve retornar 18 tickers (próxima sessão)

---

## ADR-014 — Leak <pipeline-project>  é power-law em mega-sessões, não baseline distribuído (2026-05-06)

**Data:** 2026-05-06 (Sprint 27)

**Decisão:**
Hipótese da Sprint 27 ("≥50% do custo <pipeline-project> otimizável via prompt engineering + caching no source") **refutada empiricamente**. Otimização real disponível via <pipeline-project>-source = ≤2%. O leak está concentrado em mega-sessões longas (top 3 = 65% / top 10 = 87% / bucket tool_calls 100+ = 84% do total semanal), não em baseline distribuído.

**Rationale:**
1. **Caching já está ativo** automaticamente via harness Claude Code: turn-1 de toda sessão <pipeline-project> mostra `cache_write` populado mesmo com 0 ocorrências de `cache_control` no source. Adicionar cache_control no source é estruturalmente impossível (skills são markdown; system prompt é proprietário do harness).
2. **Distribuição super-linear de custo** vs `tool_calls`: bucket 1-9 = baixo custo; bucket 100+ = muito superior (~100x). Cache_read cumulativo cresce ~quadrático com turns.
3. **Análise das 3 sessões mais recentes** (109/188/160 turns; 8M/17M/17M cache_read cumulativo) confirma que o multiplicador é n_turns × growing_context, não baseline cachado.
4. CLAUDE.md <pipeline-project> (35.7K chars ≈ 9k tokens) contribui marginalmente (contribuicao marginal via cache_read repetido; <2% do leak).

**Alternativas rejeitadas:**
- **Adicionar `cache_control` em system prompt <pipeline-project>:** estruturalmente impossível (não há ponto canônico no source; harness já faz).
- **Trim agressivo de CLAUDE.md <pipeline-project>:** ganho real ≤2%, custo de retrabalho alto e risco de perder gotchas críticos (35.7K chars curados em 27+ sprints).
- **Spike de 2 sessões idênticas com/sem cache_control:** abandonado (substituído por verificação inspecional de 3 sessões reais que prova caching já ativo).

**Implicação:**
1. **Sprint 27 fecha com binary=NÃO**, sem implementação. Resultado é diagnóstico, não fix.
2. **Sprint 28 herda** decisão estratégica: cruzamento com verdict da Sprint 25 (Trilha 3 morta por baseline-bound). Sprint 27 reabre framing parcial: o leak <pipeline-project> NÃO é baseline (que Sprint 25 atacou) — é mega-sessões com trabalho mecânico (Read/Edit/Bash dominante). Sprint 8 já validou 37.3% economia via routing <pipeline-project>. Sprint 28 deve decidir se reativa Trilha 3 com nova framing ou aceita levers fora-de-source (model choice Opus→Sonnet, session-close discipline, rtk hook global).
3. **Lição metodológica:** medir distribuição empírica do gasto antes de hipotetizar onde está o leak. A premissa de "30% redução via prompt source" foi formada sem dados; bastou olhar token_log para refutá-la em 2h.

**Cross-reference:**
- `analise/sprint27-<pipeline-project>-inventory_2026-05-06.md`
- `analise/sprint27-leak-analysis_2026-05-06.md`
- `analise/sprint27-caching-spike_2026-05-06.md`
- `analise/sprint27-verdict_2026-05-06.md`
- ADR-016 do projeto insights (cross-ref mencionada no sprint doc original — lição "medir source antes de otimizar routing" se confirma com nuance: nem source nem routing são o leak; é workflow de mega-sessões)

---

## ADR-015 — Encerramento da fase audit (Sprints 23-27): Trilha 3 redirecionada para 3 levers fora-do-source (2026-05-06)

**Status:** accepted

**Decisão:**
Encerrar a fase audit do local-dev como **Trilha 3 redirecionada**. Local-dev passa de "trilha de construção de specialists locais (rtk + graph + repomix + LiteLLM + 6 specialists)" para "trilha de manutenção + 3 levers fora-do-source priorizados por ROI". A construção da stack original de Trilha 3 é descontinuada por falta de evidência empírica de ROI — não é refutada como ideia, mas é refutada como prioridade.

**Rationale:**

5 sprints de medição empírica (23-27) produziram 5 verdicts negativos em sequência. Cada hipótese foi refutada pela sprint que a testou:

| Sprint | Hipótese | Resultado |
|---|---|---|
| 23 | Vetor (a) routing ou (b) baseline domina o gasto? | (b) domina turn-0 (32,337 tk = 16.2% ctx) — mas turn-0 é a métrica errada (ver S27) |
| 24 | Atacar baseline reduz gasto ≥15% | -11% projetado, -4.8% empírico acumulado; teto estrutural ~22-25k tk overhead Anthropic |
| 25 | Hooks/MCPs trim destrava redução adicional | -270 tk projetado, irrelevante; recomendou encerrar Trilha 3 |
| 26 | Specialists locais ≥2 viáveis ≥70%; orquestração ≥90% determinística | Arquivada sem execução (descendente de Branch A já refutado) |
| 27 | ≥50% do leak <pipeline-project> é otimizável no source via prompt-engineering+caching | NÃO — ≤2%. Caching já ativo automaticamente. **Driver real: mega-sessões Opus power-law (top 1 = 32% do gasto, top 3 = 65%, bucket 100+ tools = 84%, custo super-linear vs tool_calls).** |

A Sprint 27 reformulou a pergunta: o leak não é distribuído sobre N sessões (que justificaria atacar baseline), é concentrado em mega-sessões longas com cache_read cumulativo super-linear. Sob essa framing:

1. Trilha 3 como construção (rtk/graph/repomix/LiteLLM + 6 specialists) **não tem ROI**: a alavanca certa não é "cada sessão fica X% mais barata", é "as 3 mega-sessões da semana passam a custar 37% menos via routing seletivo Codex" (Sprint 8 já provou empiricamente).
2. Os levers reais identificados pela audit estão **fora-do-source e fora-do-stack-de-Trilha-3**: model choice global (Opus→Sonnet), session-close discipline, rtk hook global. Atacam o mesmo leak por caminhos drasticamente mais baratos.
3. Trilha 3 não é abandonada como ideia — replicar Sprint 8 (routing mecânico nas mega-sessões <pipeline-project>) entra como lever #4 da nova trilha de manutenção, com 3-5 sprints de custo, não 6+ sprints de construção de stack nova.

Cross-reference numérica completa em `analise/sprint28-cross-table_2026-05-06.md` e `analise/sprint28-decision-tree_2026-05-06.md` (nó novo criado conforme nota operacional da sprint doc).

**Alternativas rejeitadas:**

1. **Continuar Trilha 3 com escopo ajustado (rtk+graph+repomix+LiteLLM+specialists).** Rejeitada: 6+ sprints de construção sem evidência empírica de ROI, mesmo padrão de Sprints 17-22 que ADR-016 (insights) advertiu.
2. **Pivot pra <pipeline-project> source primeiro.** Rejeitada: Sprint 27 mediu source e refutou (≤2% otimizável). Não há alavanca lá.
3. **Pivot pra cleanup baseline + manutenção (encerrar local-dev nova).** Rejeitada parcialmente: o cleanup *já aconteceu* (Sprints 24-25) e atingiu teto estrutural. Encerrar como manutenção é parte da decisão, mas só isso ignora os levers reais fora-de-source identificados pela Sprint 27.
4. **Encerrar local-dev como manutenção pura, sem nova trilha.** Rejeitada: deixaria fracao substancial do gasto semanal de gasto não-atacado (mega-sess + tool_result bloat + Opus default) sem dono. Os 3 levers têm ROI demonstrável e baixo custo.

**Implicação cross-projeto:**

- **<pipeline-project>**: receberá os 3 levers em ordem de ROI/custo (lever 1 + 2 imediato; lever 3 e 4 como sprints dedicados). CLAUDE.md <pipeline-project> precisa update (gotcha #1 Sprint 27: layer2_claude unreachable mas force_api_parsers.json declara 4 <pipeline-project>s para layer2).
- **<game-bot>, insights, investments**: ADR-015 fica disponível em `insights/ADR.md` cross-ref. Qualquer projeto que considerasse replicar a Trilha 3 stack original passa a ter aviso explícito de ROI negativo no padrão "construir specialists locais antes de medir distribuição de custo".
- **local-dev**: spec.md recebe seção de encerramento da fase audit (Trilha 3 não-construída como originalmente proposta, redirecionada para manutenção + 3 levers).

**Cross-reference:**
- **insights ADR-014** (modelo de memória) — não-conflita; segue válida.
- **insights ADR-016** (medir baseline antes de prometer) — confirmada com nuance: medir baseline turn-0 não basta; medir distribuição gasto-por-sessao ao longo da janela operacional (semanal). Sprint 23 mediu o eixo certo para a pergunta errada.
- **local-dev ADR-014** (leak <pipeline-project> = power-law em mega-sessões) — ADR-015 é a consequência prática direta: como atacar o que ADR-014 mediu.

**Métrica de sucesso para superseder este ADR:**
Se aplicarmos os 3 levers nas próximas 4 semanas e o gasto semanal <pipeline-project> NÃO cair de em proporcao significativa (-37%, meta calibrada por Sprint 8), este ADR é re-aberto e revisitamos. Se cair, o ADR é confirmado e a fase audit fecha em definitivo.

---

## ADR-015 Apêndice — Plano executável priorizado

Esta seção é o "contrato" mencionado nos handoffs Sprint 27/28: cada finding mapeia para uma ação concreta com impacto estimado, custo de implementação, e reversibilidade. Sem ela, a próxima sessão repete o ciclo de propor sem priorizar.

### Levers em ordem de execução recomendada

| # | Lever | Origem | Onde executa | impacto estimado | Custo de implementar | Reversibilidade | Sprint candidata |
|---|---|---|---|---:|---|---|---|
| 1 | Disciplina session-close + flag Opus→Sonnet em mega-sess (gating ≥80 tool_calls ou ≥4h wall) | S27 distribuição power-law | workflow + 1 hook PreToolUse novo | medio | ~zero (regra + hook ~50 linhas) | total (`.bak` do hook) | sprint 29 (curta, 2-3h) |
| 2 | Update CLAUDE.md <pipeline-project> (layer2 stale; force_api_parsers.json não documentado) | S27 gotcha #1 | edit local em `<workspace>/<pipeline-project>/CLAUDE.md` | marginal (consistência, não gasto semanal direto) | 30min | total | inline na sprint 29 |
| 3 | rtk hook global (tool_result trim em PostToolUse para Bash output) | S27 cache_read super-linear | `~/.claude/hooks/` novo PostToolUse | medio | 1 sprint (~4-6h) | total (`.bak`) | sprint 30 |
| 4 | Replicar Sprint 8 routing seletivo nas top-3 mega-sess <pipeline-project> | S27 + Sprint 8 histórico (37.3% empírico) | sprint dedicado + `orchestrator/router_deterministic.py` existente | medio-alto | 3-5 sprints | sprint-by-sprint | sprint 31+ |
| 5 | (Opcional, validação retroativa) confirmar projeção Sprint 24 | S24 pendência herdada | `python analise/_measure_turn0.py 3` em fresh session | nenhum (sanity check) | 5min | n/a | inline qualquer sessão fresh |

### Princípios da priorização

- **ROI/custo decrescente, não $ absoluto**: lever 1 não é o maior em $, mas tem custo quase-zero de implementação. Lever 4 paga mais mas custa 3-5 sprints — só faz sentido depois de lever 1 + 3.
- **Reversibilidade obrigatória**: todos os levers têm `.bak` ou são reversíveis sprint-by-sprint. Padrão local-dev preservado.
- **Sequência respeita herança de aprendizado**: lever 1 mede empiricamente o impacto da disciplina antes de comprometer 3-5 sprints com lever 4.

### Critério de re-validação

Após aplicar levers 1+2+3 (estimativa 4-6 semanas calendar), re-medir:

```powershell
python analise/_sprint27_aggregate.py
python analise/_sprint27_distribution.py
```

**Espera-se:**
- Distribuição power-law atenua (top 3 cai de 65% → ~50%)
- gasto semanal <pipeline-project> cai de reducao ~30% (sem lever 4)
- Se não atenuar → este ADR é re-aberto, hipóteses revisitadas

Lever 4 só é executado se a re-medição mostrar que levers 1-3 deixaram residuo significativo em mega-sessões mecânicas (Read/Edit/Bash dominantes). Caso contrário, encerrar local-dev como manutenção pura.

### Atualização 2026-05-07 — Lever 3 encerrado (Sprint 32)

**Lever 3 (rtk_trim.py) — tentado Sprint 30, falhou estruturalmente. Removido Sprint 32. Não conta para a meta de queda 30-37%.**

Evidência primária: docs oficiais Claude Code (PostToolUse não pode mutar `tool_result` que o assistente vê no transcript; único campo honrado para injeção é `hookSpecificOutput.additionalContext`). O hook emitia o payload bruto — envelope não-reconhecido, descartado silenciosamente. 6/6 unit tests validavam o transform Python, não o efeito sistêmico. A/B real (Phase 4 Sprint 30) ficou PENDING indefinidamente — padrão "deploy-antes-de-validar-end-to-end". Entry `PostToolUse Bash|PowerShell|Grep|Glob` removida de `~/.claude/settings.json` em Sprint 32 Phase 3. Arquivo `rtk_trim.py` mantido em disco como referência para Sprint 34 (contracts). Reclassificado: "tentado, falhou estruturalmente" — não é ROI negativo, é lever que nunca existiu.

---

### O que esta tabela explicitamente NÃO faz

- Não constrói rtk/graph/repomix/LiteLLM stack (refutado por falta de ROI; pode ser revisitado se levers 1-3 falharem)
- Não toca em hooks de segurança (`injection_guard.py`, `py_check.py`, `handoff_vocab_check.py`) — fora de escopo
- Não modifica memory files (já mínimo)
- Não toca em modelos/Ollama/llama.cpp infra (Trilha 1/2 mantidas como estão; watchlist do CLAUDE.md continua válida)

---

## ADR-016 — Ramo A escolhido: Maestro local (3 agents, cautela) como próxima trilha de implementação (2026-05-07)

**Status:** accepted
**Data:** 2026-05-07

### Contexto

Sprint 32 (2026-05-07) mediu os três gates que decidiam a forma do refator:
- **Gate 1 (model:inherit → Ollama):** PASS — subagent `test-inherit` (model: inherit) executou via Ollama confirmado empiricamente (retornou conteúdo correto de arquivo local; API key=ollama invalida para api.anthropic.com descarta rota cloud).
- **Gate 2 (num_ctx no caminho Anthropic-compat):** FAIL — tokens_in == 4096 confirma truncamento silencioso ativo. Fix identificado: Modelfile com `num_ctx 65536`.
- **Gate 3 (rtk_trim lever 3):** DEAD — PostToolUse não pode mutar `tool_result`; lever estruturalmente inoperante (removido Sprint 32).

Sprint 33 (2026-05-07) rodou `/sanity-check` na tese central e tomou a decisão de ramo.

### Decisão

**Ramo A** — Maestro local via subagents Claude Code + Ollama Anthropic-compat.

Sprint 36-A implementará o Maestro com exatamente 3 agents (não 6+). Medição de economia real antes de qualquer expansão.

**Pré-requisitos de Sprint 36-A (derivados do sanity-check Sprint 33):**
1. Criar Modelfile `qwen3.6-64k` com `num_ctx 65536` — validar tokens_in > 4096 em sessão com arquivo >10KB antes de proceder.
2. Verificar que `/v1/messages/count_tokens` não causa timeout no Ollama local (issue ollama/ollama #13949) — se causar, investigar workaround.
3. Escopo hard-cap: 3 agents Sprint 36-A. Não expandir antes de medir economia real.

### Alternativas rejeitadas

**Ramo B (deterministic router sem LLM):** Sprint 32 Phase 1 = PASS refuta a premissa de Ramo B. Ramo B só seria executado se model:inherit não propagasse ANTHROPIC_BASE_URL — o que não ocorreu. Descartado formalmente.

**LiteLLM como gateway:** Sanity-check confirmou desnecessário para single-provider (tudo-Ollama). LiteLLM relevante apenas para per-agent routing multi-provider (cenário da issue anthropics/claude-code #38698 — ainda open/unresolved). Adicionaria overhead sem benefício.

**Maestro com 6+ agents imediatamente:** Padrão "deploy-antes-de-validar" identificado em Sprint 30 como causa de 22 sprints → 3 entregáveis reais. Escopo mínimo (3 agents) com medição real antes de expansão é o contrato estrutural derivado de Sprint 34.

### Cross-referências

- `analise/sprint32_phase1_inherit-test_2026-05-07.md` — evidência primária Gate 1
- `analise/sprint32_phase2_numctx-anthropic_2026-05-07.md` — evidência primária Gate 2
- `analise/sprint33_branch-decision_2026-05-07.md` — consolidação de inputs + justificativa
- `sanity-cache/maestro-local-ollama-stack_2026-05-07.md` — sanity-check completo (fontes, gotchas novos)
- ADR-015 — contexto do encerramento da fase audit; levers fora-de-source
- GitHub anthropics/claude-code #38698 — feature request per-agent routing (open; single-provider não precisa)
- GitHub ollama/ollama #13949 — count_tokens endpoint unsupported (monitorar)


## ADR-017 — Executor inter-step context: Option C (independent steps) para Sprint 36b (2026-05-07)

### Contexto

Sprint 36b Phase 1c precisa definir se o executor recebe output de steps anteriores.
Tres opcoes avaliadas:
- A: Accumulate — passa lista de prior_results para cada step (contexto completo, risco de overflow)
- B: Summary — comprime outputs anteriores para 2 frases antes de passar
- C: Independent — steps sao atomicos, sem dependencia permitida (restricao no prompt do planner)

### Decisao

**Option C (independent steps)** como default para Sprint 36b.

Rationale: (1) nao requer mudanca de arquitetura; (2) elimina risco de overflow de contexto; (3) qualquer task que precise de dependencia inter-steps e candidata a Claude ou a re-design do task para steps verdadeiramente atomicos; (4) se dependencia for necessaria, Sprint 36c revisita com Option A ou B — com evidencia real do caso de uso.

### Restricao implicita no planner

Prompt do planner deve incluir: "Each step must be independently executable — steps cannot reference outputs of prior steps."

### Alternativas rejeitadas

Option A: viavel mas risco de overflow nos 65K tokens com pipelines longos (>5 steps em arquivos grandes).
Option B: requer modelo para resumo — adiciona latencia e um novo ponto de falha.

### Cross-referencias

- `sprints/sprint_36b.md` Phase 1c — detalhe da decisao
- `orchestrator/maestro.py:run_executor()` — implementacao target

---

## ADR-018 — Sub-agents via Task tool: tecnicamente viaveis, comportamentalmente nao-utilizaveis em qwen3.6-64k (2026-05-17)

### Contexto

Sprint 38 V1 monolitico (1 prompt = 4 phases inteiras) saturou contexto, fez scope-creep (4 phases viraram 7), entrou em loop, 142 min wall-clock. Sprint 39 testou hipotese: planner local pode dispachar sub-agents via Task tool, tornando pre-decomposicao manual desnecessaria. Se sim, S47 (multi-sprint skill) e S48 (sprint doc executavel) mudam de forma.

### Findings empiricos

**Phase 1** (.eval/sprint39.jsonl):
- Task tool e exposto a qwen3.6-64k via shim Anthropic-Ollama APENAS quando --bare e removido (Test E, system prompt 69k tokens)
- Sob --bare, base tool set e fixo em [Bash,Edit,PowerShell,Read]; --allowedTools=Task nao adiciona Task
- --disable-slash-commands NAO strip skills (skills_count=38 igual); piora o prompt (177k tokens em Test F)
- Sem lever para expor Task mantendo budget <65k

**Phase 1 Test E**: sub-agent dispatch funciona end-to-end (Agent tool_use -> sub-agent retorna OK -> planner reporta).

**Phase 3**: planner em task real (regenerar data.js + Panorama HTML) IGNOROU instrucao "so dispatch via Task". 16 turns, 15 tool_uses, ZERO Task/Agent. Foi direto via Bash/PowerShell. Files regenerados corretamente (19 funds, PL 11.6bi) mas via arquitetura monolitica.

### Decisao

**Manter pre-decomposicao manual** (sprint doc com phases explicitas) como pattern padrao do roadmap local-dev. Nao adotar planner-dispatch architecture com qwen3.6-64k.

### Consequencias para o roadmap

| Sprint | Forma revisada |
|---|---|
| S47 (Multi-sprint skill) | Gera N sprints pre-decompostas com cap 5 phases cada. NAO assume dispatch automatico. |
| S48 (Sprint doc auto-executavel) | CRITICA, nao opcional. Scope-fence obrigatorio + batch-gate per-phase + checksum gate pra gitignored. |
| S55-S58 (Ferramentas: Aider, OpenClaw, Hermes, prompt-via-file) | Assumem pre-decomposicao. Cada tool roda phases individuais, nao goals abertos. |

### Mitigacoes ortogonais

1. **Wrapper de intercept** (futura sprint, nao escopo S39): hook que captura tool_use de Edit/Write/Bash do planner e redireciona para sub-agent. Anti-pattern: hack sobre o protocolo do CC, alto risco de breakage entre versoes.
2. **Modelo com instruction-following mais forte**: sonnet/opus seguem dispatch-only triviavelmente. NAO eh opcao para local-dev (custo + privacidade).
3. **Prompt engineering radical** (ex: ocultar Edit/Write/Bash do allowedTools do planner): quebra sub-agents que herdam allowedTools. Caminho sem saida.

### Alternativas rejeitadas

- "Sub-agents viaveis, S47 com auto-decomposicao": refutada empiricamente em Phase 3.
- "Forkar S45 (context ceiling 128k/262k) antes de S39 Phase 3": adiaria decisao arquitetural por dias; problema real (model nao obedece dispatch-only) e ortogonal a ctx ceiling.

### Cross-referencias

- `sprints/sprint_39.md` -- sprint completo
- `.eval/sprint39.jsonl` -- 3 entradas (phase 1+2 consolidado, phase 3)
- `analise/sprint39_subagents_vs_monolithic.md` -- Phase 4 comparison
- `.eval/sprint39_phase1_test{C,D,E,F}.jsonl` -- raw streams Phase 1
- `.eval/sprint39_phase3.jsonl` -- raw stream Phase 3
- ADR-017 (Maestro): com este achado, Maestro mantem option-C (independent steps) como design correto -- planner local nao reorganiza protocolo, executa phases pre-decompostas

