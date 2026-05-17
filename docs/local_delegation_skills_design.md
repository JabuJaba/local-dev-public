# Local Delegation Skills — Design Doc

**Status:** DESIGN (nenhum arquivo de skill criado nesta sessão)
**Data:** 2026-04-21 — Sprint 4 Phase 1.C
**Escopo:** 3 skills Claude-side análogas às `codex-*`, porém voltadas ao routing de modelos **locais** (Ollama + llama.cpp) já existente no `local-dev/orchestrator/`.

---

## 1. Motivação e não-duplicação

O `orchestrator/` **já decide rotas automaticamente** via `routing_rules.yaml` + `TaskRouter` (Sprint 3, 55.6% economy, 36/36 tasks). Por que ainda precisaríamos de skills Claude-side?

**Resposta:** o orchestrator é a **rota batch autônoma** (cron/demand, consome `backlog.yaml`). As skills cobrem a **rota interativa síncrona**:

| Situação | Quem decide | Onde |
|----------|-------------|------|
| Backlog automático (cron, watch) | `orchestrator.TaskRouter` | batch — `.jsonl` logs |
| Task ad-hoc dentro de uma sessão Claude Code | **skill local-fit-evaluator** | interativo — `<projeto>/.local-routing/verdicts/<task-id>.json` |
| Projeto sensível (ex.: <pipeline-project>) pedindo aprovação manual por task | **skill local-fit-evaluator** | idem |

Ambos leem o mesmo arquivo-fonte: `routing_rules.yaml`. A skill **não reimplementa** a lógica de routing — ela **consulta** a mesma fonte e produz um veredito persistente pro Claude (e para auditoria cruzada).

---

## 2. Pattern herdado das skills Codex

Da leitura de `codex-fit-evaluator`, `codex-sprint-generator`, `codex-delivery-review` + `verdict_schema.md`:

| Elemento | Preservado | Adaptado |
|----------|:----------:|:--------:|
| 3 estágios: `fit → sprint → review` | ✅ | — |
| Veredito JSON append-only | ✅ | — |
| `current_stage` + `stages[]` imutáveis | ✅ | — |
| **Handoff humano obrigatório** | ❌ | orchestrator executa automático; handoff humano só quando `waiting_handoff` dispara |
| Sandbox-only (`<original>-codex-sandbox`) | ✅ *parcial* | Só obrigatório em `destructive_local` (Docker). `always_local`/`try_local_first` rodam no host com safety interceptor |
| Heurísticas em `capabilities.md` | ❌ | Usa `routing_rules.yaml` (empírico Sprint 2/3) |
| Decisões `GO/NO-GO/PARTIAL` | ❌ | `always_local / try_local_first / destructive_local / always_claude` |

---

## 3. Três skills propostas

### 3.1. `local-fit-evaluator`

**Análoga a:** `codex-fit-evaluator`
**Responsabilidade:** mapear descrição livre → categoria de roteamento + modo isolamento + tipo de review.

**Entradas obrigatórias:**
- `task_id` (kebab-case)
- `project_path` (raiz do projeto alvo)
- Descrição da tarefa
- Escopo estimado (nº arquivos, destrutivo?, output esperado)

**Fonte de decisão:**
1. `orchestrator\routing_rules.yaml` — eixo primário
2. **Limites conhecidos** (já em `CLAUDE.md` do local-dev):
   - Output >600 palavras → `always_claude` (3/3 modelos locais falham)
   - Generators `send()/throw()` → `always_claude` (não-determinístico)
   - Async custom event loops → `always_claude`
   - Refactors multi-arquivo com dependências cruzadas → `always_claude`
3. **Overrides** de `routing_rules.yaml`:
   - `destructive: true` → `destructive_local` + Docker obrigatório
   - `critical: true` → `always_claude` (sem tentativa local)

**Decision table:**

| Condição | Decisão |
|----------|---------|
| Qualquer limite conhecido ativo | `always_claude` |
| `destructive: true` e não-crítico | `destructive_local` + Docker |
| Tipo ∈ {read_only, simple_edit, bash_safe, small_write} | `always_local` |
| Tipo ∈ {multi_file_edit ≤3, read_then_write, bash_with_analysis} | `try_local_first` |
| Descrição ambígua / não mapeia | `try_local_first` (default conservador de `routing_rules.yaml`) |

**Saída:** `<project_path>/.local-routing/verdicts/<task-id>.json` stage=`fit`, decision ∈ `{always_local, try_local_first, destructive_local, always_claude}` + `routing_rules_version` (sha do yaml no momento).

**Diferença crítica vs codex-fit-evaluator:** não há "GO/NO-GO binário". Até `always_claude` é uma decisão válida — apenas descarta a rota local.

---

### 3.2. `local-sprint-generator`

**Análoga a:** `codex-sprint-generator`
**Responsabilidade:** converter task fit-aprovada em **formato que o orchestrator consegue consumir** (entry `backlog.yaml`) **OU** em sprint manual para o modelo local via Claude Code interativo (`ANTHROPIC_BASE_URL=http://localhost:11434` + `--bare --allowedTools=…`).

**Pré-requisito:** `current_stage == "fit"`, decision ≠ `always_claude` (senão a task segue o caminho Claude normal — sem sprint local).

**Dois modos de saída:**

#### Modo A — `backlog_entry` (default quando orchestrator está online)
Produz fragmento YAML para anexar em `backlog\backlog.yaml`:

```yaml
- id: <task_id>
  project: <project>
  project_path: <project_path>
  task_type: <mapped do fit>     # read_only | multi_file_edit | ...
  destructive: <bool>
  critical: <bool>
  preferred_model: qwen3.6       # opcional override
  map_tokens: 1024               # quando aplicável
  input_files: [...]             # do dossier 1.B §1
  oracle:                        # do dossier 1.B §3
    kind: golden_parquet | pytest | validate_prod | invariant_script
    target: <path>
  expected_metrics:              # do dossier 1.B §2
    rows: 704
    cols: 52
  guardrails: [B1, B4, B6]       # guardrails específicos do §4 do dossier
```

#### Modo B — `interactive_sprint` (quando user quer executar manualmente)
Produz `<project_path>/.local-routing/sprints/<task-id>-local.md`:

```markdown
# Sprint Local — <task-id>

## Rota
Category: <always_local|try_local_first|destructive_local>
Model: qwen3.6:35b-a3b-q4_k_m (slot primário)
Fallback: gemma4:26b após 2 falhas
Invocation: ANTHROPIC_BASE_URL=http://localhost:11434 claude --bare --allowedTools=Read,Edit,Write,Bash,Glob,Grep --model qwen3.6:35b-a3b-q4_k_m
Isolation: host | docker (Sprint 2.5 workspace efêmero)

## Ação mecânica (1 por phase)
### Phase 1 — <verbo direto>
Arquivos: <lista>
Comando local: <exato, copiável>
Acceptance determinística: <oracle do dossier §3>

## Guardrails ativos
<lista dos Bn do dossier §4 que a task pode reintroduzir>

## Fora de escopo
- <explícito>
```

**Invariantes:**
- Phase ≤ 1 ação mecânica + 1 check (mesmo padrão Codex: local também perde em cadeias condicionais longas)
- Sempre citar oracle do Phase 1.B §3
- Sempre listar guardrails do Phase 1.B §4 que a task **poderia** reintroduzir
- Para `destructive_local`: `isolation: docker` **não é negociável** — hardcoded no sprint

**Saída no JSON:** append em `stages[]` com stage=`sprint`, decision ∈ `{GENERATED_BACKLOG, GENERATED_INTERACTIVE, ABORTED}`, `evidence_paths` = [yaml fragment ou md].

---

### 3.3. `local-delivery-review`

**Análoga a:** `codex-delivery-review`
**Responsabilidade:** auditar entrega do modelo local (host ou Docker) e decidir.

**Pré-requisito:** `current_stage == "sprint"`.

**Onde está o delivery:**
- Modo A (orchestrator): log em `logs\<project>_<data>.jsonl` — já contém `outcome`, `escalated`, `retries`, `duration_s`, `cost_usd_est`, `isolated`, arquivos modificados
- Modo B (interativo): `<project_path>/.local-routing/deliveries/<task-id>/` — diff + output + logs

**Checklist de regressão (gerado por task)**

Sempre inclui itens mínimos + **itens dinâmicos extraídos do dossier 1.B**:

```markdown
## Regressão — <task-id>

### Rota respeitada
- [ ] Categoria executada == categoria do fit
- [ ] Se destructive_local: log tem `isolated: true` (Docker workspace usado)
- [ ] Se try_local_first: retries ≤ 2 antes de handoff
- [ ] Nenhuma modificação fora de `project_path`

### Oracle (do dossier §3)
- [ ] <oracle.kind> retornou esperado: <tolerance + target>
- [ ] Se pytest: N/N passed conforme `expected_metrics`
- [ ] Se validate_prod: "16/0/1" baseline mantido (ou diff justificado)
- [ ] Se golden_parquet: schema + row_count + ticker set batem

### Guardrails B1..B11 (dossier §4)
- [ ] B1 (camada 3): `grep -rE "layer3|8081|llama-server" src/` = 0
- [ ] B4 (PROCESSED_DIR): hardcoded absent, env var respeitada
- [ ] B6 (dataReferencia): camelCase preservado
- [ ] <mais Bn ativos para a task>

### Custo e review_type
- [ ] review_type executado == fit (none/light/full)
- [ ] cost_usd_est ≤ projeção do baseline tool-call medio × n_tool_calls × (1 - economia_esperada)
- [ ] Se review=full: Claude rodou o checklist inteiro

### Secrets
- [ ] `.env`, `credentials.json`, `token_log.jsonl` não modificados
- [ ] Nenhum token/senha em logs ou diffs
```

**Decisões** (mesmo formato Codex):

| Resultado | Decisão | Próximo passo |
|-----------|---------|---------------|
| Todos checks passam | `ACEITAR` | Sugerir merge sandbox → host (manual) ou nada se já é host |
| Falha mecânica corrigível local | `DEVOLVER-LOCAL` | Re-enfileirar no orchestrator com `retries++` |
| Falha arquitetural / padrão repetido | `ASSUMIR-CLAUDE` | handoff humano, Claude conclui |
| Fim de ciclo | `SESSION-CLOSE` | invocar skill `session-close` |

Append stage=`review` no JSON, idêntico ao Codex.

---

## 4. Reuso de skills Claude já existentes

Skills globais que **não precisam ser re-escritas** — as 3 novas skills acima as **invocam** em momentos específicos:

| Skill existente | Quando é invocada pelas skills locais |
|-----------------|---------------------------------------|
| `backup` | Pré-`destructive_local` — chamada automática antes de abrir container Docker |
| `data-audit` | `local-delivery-review` quando oracle.kind=`invariant_script` e projeto tem pipeline de dados |
| `diagnose` | `local-delivery-review` quando review_type=`full` detectar regressão não-trivial |
| `session-close` | `local-delivery-review` ao decidir `SESSION-CLOSE` |
| `sprint-execute` | Rota normal Claude (não é invocada pela skill local — é o próprio "always_claude") |
| `git-prep` / `git-publish` | Se task envolve primeiro commit em `project_path` — invocável manualmente |

**Skills que provavelmente não cabem no modelo local** (ficam sempre em `always_claude`):
- `project-plan` — requer output longo + decisões arquiteturais (limite conhecido)
- `sprint-generator` Claude-side — idem (`local-sprint-generator` é a versão mínima, não substitui)
- `skill-creator` — requer síntese + writing longo
- `diagnose` — quando >1 arquivo impactado (multi-arquivo = limite conhecido)

**Skills do plugin Codex** (`codex-*`): independentes — os dois pipelines (Codex remoto e local) coexistem. Possível evolução: um meta-avaliador que decide Codex vs Local vs Claude, mas **não é escopo da Sprint 4**.

---

## 5. Pontos de integração com infra existente

| Componente | Como se conecta |
|------------|-----------------|
| `routing_rules.yaml` | Fonte única de heurísticas — skill lê, não edita |
| `TaskRouter` (`orchestrator.py`) | Modo A de `local-sprint-generator` produz entry compatível; orchestrator consome sem mudança |
| `token_log.jsonl` | `local-delivery-review` lê `cost_usd_est` para comparar com projeção do baseline tool-call medio |
| `logs/<project>_<data>.jsonl` (orchestrator) | Fonte primária de evidência para modo A do review |
| `safety_interceptor.py` | Invocado automaticamente em `isolation: host` — sem mudança |
| `docker/run_workspace.ps1` | Invocado em `isolation: docker` para `destructive_local` — sem mudança |
| Sprint 4 Phase 1.B dossier | Fonte canônica de oracles + guardrails + expected_metrics |

---

## 6. Schema de veredito (espelho do `verdict_schema.md` com diffs)

Arquivo: `<project_path>/.local-routing/verdicts/<task-id>.json`

```json
{
  "task_id": "kebab-case",
  "project": "<pipeline-project>_Extractor",
  "project_path": "<projects_root>/<pipeline-project>_Extractor_backup_20260421_sprint4_pre",
  "routing_rules_version": "<sha-256 do routing_rules.yaml>",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "current_stage": "fit | sprint | review | closed",
  "stages": [
    {
      "stage": "fit",
      "decision": "always_local | try_local_first | destructive_local | always_claude",
      "rationale": "≤3 parágrafos",
      "evidence_paths": [],
      "rules_applied": ["routing_rules.types.read_only", "critical_override"],
      "limits_checked": ["long_text_generation=false", "generator_coroutine=false"],
      "expected_economy_pct": 55.6,
      "created_at": "ISO-8601",
      "next_stage": "sprint | closed",
      "notes": ""
    },
    {
      "stage": "sprint",
      "decision": "GENERATED_BACKLOG | GENERATED_INTERACTIVE | ABORTED",
      "mode": "A | B",
      "evidence_paths": ["backlog_fragment.yaml" ou ".local-routing/sprints/<id>-local.md"],
      "oracle": {"kind": "...", "target": "...", "tolerance": "..."},
      "guardrails_active": ["B1","B4","B6"],
      "expected_metrics": {"rows": 704, "cols": 52, "pytest": "133 passed / 3 skipped"},
      "created_at": "ISO-8601",
      "next_stage": "review"
    },
    {
      "stage": "review",
      "decision": "ACEITAR | DEVOLVER-LOCAL | ASSUMIR-CLAUDE | SESSION-CLOSE",
      "checklist_pass_rate": "12/14",
      "guardrail_violations": [],
      "measured_metrics": {"rows": 704, "cols": 52, "cost_usd_est": 0.21},
      "economy_real_pct": 52.3,
      "evidence_paths": [".local-routing/deliveries/<id>/regression_checklist.md"],
      "created_at": "ISO-8601",
      "next_stage": "closed | sprint"
    }
  ]
}
```

**Diffs principais vs Codex:**

- Novos campos no `fit`: `rules_applied`, `limits_checked`, `expected_economy_pct`
- Novo campo no `sprint`: `mode` (A/B), `oracle`, `guardrails_active`, `expected_metrics`
- Novo campo no `review`: `guardrail_violations`, `measured_metrics`, `economy_real_pct`
- Enum de `decision` diferente em todos os 3 estágios
- `project_path` para `destructive_local` **deve** ser caminho que Docker monta; para outros, pode ser o host

---

## 7. Ordem de implementação sugerida (não-escopo desta sessão)

1. **Phase 2 da Sprint 4 (próxima sessão):** `local-fit-evaluator` — é a primeira porta de entrada; vale testar com 5 tasks do dossier antes de ir pra sprint/review
2. **Phase 2 + 1 (após validar fit):** `local-sprint-generator` Modo A — produzir entries de `backlog.yaml`, executar via orchestrator existente, medir
3. **Phase 2 + 2:** `local-delivery-review` — ler jsonl do orchestrator + rodar checklist
4. **Phase 2 + 3 (opcional):** `local-sprint-generator` Modo B — só se user preferir fluxo interativo

Cada skill deve ter **3 testes mentais** antes de ser aceita (padrão codex-fit-evaluator) — por ex.:
- Fit: task "ler parquet e contar rows" → `always_local`
- Fit: task "refatorar cleaner.py + consolidate.py + pipeline.py" → `always_claude` (multi-arquivo cross-dependency)
- Fit: task "dropar tabela e recriar no SQLite" → `destructive_local` + Docker

---

## 8. Riscos e decisões em aberto

| # | Risco / questão | Mitigação proposta |
|---|----------------|--------------------|
| R1 | Skill duplica lógica do TaskRouter | `local-fit-evaluator` **só consulta** `routing_rules.yaml` + limites conhecidos; nunca hardcoda thresholds |
| R2 | Veredito pode ficar stale se `routing_rules.yaml` mudar | Campo `routing_rules_version` (sha) no JSON; review bloqueia se sha divergir |
| R3 | `project_path` no host para `destructive_local` é perigoso | Skill **recusa** abrir sprint nesse modo sem `Dockerfile.workspace` presente e Docker ativo |
| R4 | Usuário pode querer "pular o fit" para tasks triviais | Não implementar bypass — overhead do fit é baixo; força consistência de auditoria |
| R5 | <pipeline-project>_Extractor está arquivado — skills operam sobre cópia, não sobre "projeto vivo" | `project_path` aponta para `backup_20260421_sprint4_pre`; mesma convenção do Codex (sandbox) |
| R6 | Fit pode classificar algo como local mas modelo local bloqueia por contexto | `try_local_first` com `max_local_attempts=2` + escalation automático; veredito append-only captura a escalação |

---

## 9. Acceptance checklist Phase 1.C

- [x] 3 skills Codex lidas e padrão extraído (3-stage, veredito JSON append-only, evidência explícita)
- [x] `verdict_schema.md` Codex lido e espelhado para `.local-routing/verdicts/`
- [x] `routing_rules.yaml` + orchestrator integrations mapeados — skills não duplicam lógica
- [x] 3 skills propostas (`local-fit-evaluator`, `local-sprint-generator`, `local-delivery-review`) com: pré-requisitos, decision tables, saídas, invariantes
- [x] Mapa de reuso de skills Claude existentes (`backup`, `data-audit`, `diagnose`, `session-close`, `sprint-execute`)
- [x] Schema JSON diffado contra Codex com campos adicionais justificados
- [x] 6 riscos/decisões em aberto listados com mitigação
- [x] Zero arquivos de skill criados nesta sessão (só design)

**Gate Phase 1.C: PASS — design pronto para revisão do usuário antes da implementação.**
