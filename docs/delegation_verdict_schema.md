# Delegation Verdict Schema — v0.2

**Status:** placeholder — não consumido até Sprint 6
**Criado:** 2026-04-22 (Sprint 4 Phase 2.A)
**Convergência:** local-dev + codex-integration round 2 (handoffs/to_codex_integration_20260421_round2_close.md)
**Inclui:** D1–D5 (round 1) + F1–F5 + worktree (round 2)

---

## Caminho canônico

```
<project_path>/.delegation/verdicts/<task-id>.json
```

> **Nota de migração:** Skills `local-fit-evaluator` (Sprint 4) usam `.local-routing/verdicts/` como caminho temporário.
> Migração lazy para `.delegation/` na Sprint 6, quando o schema v0.2 se tornar operativo.

---

## Regra de imutabilidade (F3)

`stages[]` é **append-only**. Um stage gravado NUNCA é sobrescrito.
Se uma entrega falha e a task é re-enfileirada, o novo ciclo gera um **novo veredito** com `task_id` incremental (ex.: `<pipeline-project>-read-01-r2`).
Erros transitórios são registrados em `notes` do stage seguinte, nunca editando o stage anterior.

---

## Schema completo

```json
{
  "task_id": "kebab-case estável (ex: <pipeline-project>-read-01)",
  "project": "nome do projeto (ex: <pipeline-project>_Extractor)",
  "project_path": "caminho do sandbox ou projeto ativo",

  // F1 — adicionado round 2
  "project_path_original": "caminho do projeto original (host) — referência somente-leitura",
  "sandbox_mode": "none | sandbox-copy | docker | worktree",

  "agent": "local | codex | claude",
  "schema_version": "0.2-local-only",  // local: 0.2-local-only; codex: 0.1 (até Sprint 6)
  "routing_rules_version": "<sha-256 do routing_rules.yaml ou delegation_rules.yaml>",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "current_stage": "fit | sprint | review | closed",

  "stages": [

    // -----------------------------------------------------------------------
    // STAGE: fit
    // -----------------------------------------------------------------------
    {
      "stage": "fit",
      "decision": "always_local | try_local_first | destructive_local | always_claude",
      "rationale": "≤3 parágrafos — justificativa referenciando routing_rules.yaml ou limite conhecido",

      "rules_applied": [
        "routing_rules.types.read_only",
        "critical_override",
        "known_limits.long_text_threshold_words"
      ],

      // F2 — opcional, só quando agent=codex
      "heuristics_applied": ["H1", "H3", "H7"],  // null ou ausente se agent ≠ codex

      "limits_checked": {
        "long_text_generation": false,
        "generator_coroutine": false,
        "async_internals": false,
        "multi_file_cross_dependency": false
      },

      "expected_economy_pct": 55.6,   // estimativa baseada em Sprint 3 baseline

      "evidence_paths": [],           // arquivos lidos para embasar a decisão
      "created_at": "ISO-8601",
      "next_stage": "sprint | closed",
      "notes": ""
    },

    // -----------------------------------------------------------------------
    // STAGE: sprint
    // -----------------------------------------------------------------------
    {
      "stage": "sprint",
      "decision": "GENERATED_BACKLOG | GENERATED_INTERACTIVE | ABORTED",
      "mode": "A | B",
      // A = entry para backlog.yaml (orchestrator batch)
      // B = sprint markdown para execução interativa (Claude Code local)

      "isolation_confirmed": true,    // docker/worktree presente se destructive_local
      "sandbox_mode_used": "none | sandbox-copy | docker | worktree",

      // F4 — delivery_artifacts tipado
      "delivery_artifacts": {
        "patch_path": null,           // Codex: caminho do .patch gerado
        "commit_sha": null,           // local/claude: SHA do commit no worktree
        "log_path": null              // orchestrator: caminho do .jsonl de run
      },

      "oracle": {
        "kind": "golden_parquet | pytest | validate_prod | invariant_script | hash_match",
        "target": "ex: tests/fixtures/golden/TICKER13.parquet",
        "tolerance": "exact | schema_only | row_count | percentile"
      },

      "guardrails_active": ["B1", "B4", "B6"],   // bugs históricos que esta task pode reintroduzir
      "expected_metrics": {
        "rows": 704,
        "cols": 52,
        "pytest": "133 passed / 3 skipped",
        "validate_prod": "16/0/1"
      },

      "evidence_paths": [
        "backlog_fragment.yaml",
        ".local-routing/sprints/<id>-local.md"
      ],
      "created_at": "ISO-8601",
      "next_stage": "review"
    },

    // -----------------------------------------------------------------------
    // STAGE: review
    // -----------------------------------------------------------------------
    {
      "stage": "review",

      // F5 — SESSION-CLOSE adicionado ao enum
      "decision": "ACEITAR | DEVOLVER-LOCAL | ASSUMIR-CLAUDE | SESSION-CLOSE",
      // ACEITAR         → delivery OK; sugerir merge sandbox→host (manual)
      // DEVOLVER-LOCAL  → falha corrigível; re-enfileirar no orchestrator (retries++)
      // ASSUMIR-CLAUDE  → falha arquitetural / padrão repetido; handoff humano
      // SESSION-CLOSE   → fim de ciclo; invocar skill session-close

      "checklist_pass_rate": "12/14",
      "guardrail_violations": [],     // ex: ["B4 — PROCESSED_DIR hardcoded encontrado"]

      "measured_metrics": {
        "rows": 704,
        "cols": 52,
        "cost_usd_est": 0.21,
        "isolated": true
      },

      "economy_real_pct": 52.3,       // ((baseline - real) / baseline) × 100

      // F4 — evidência da entrega auditada
      "delivery_artifacts_verified": {
        "patch_path": null,
        "commit_sha": null,
        "log_path": "logs/<pipeline-project>_extractor_20260422.jsonl"
      },

      "evidence_paths": [
        ".local-routing/deliveries/<id>/regression_checklist.md"
      ],
      "created_at": "ISO-8601",
      "next_stage": "closed | sprint"   // sprint = re-enfileirar (DEVOLVER-LOCAL)
    }
  ]
}
```

---

## Enum reference rápido

| Stage | Campo `decision` — valores |
|-------|---------------------------|
| fit   | `always_local` \| `try_local_first` \| `destructive_local` \| `always_claude` |
| sprint | `GENERATED_BACKLOG` \| `GENERATED_INTERACTIVE` \| `ABORTED` |
| review | `ACEITAR` \| `DEVOLVER-LOCAL` \| `ASSUMIR-CLAUDE` \| `SESSION-CLOSE` |

## sandbox_mode por agente (matriz D4 + worktree F1)

| Agente | Não-destructive (git project) | Não-destructive (non-git) | Destructive |
|--------|-------------------------------|--------------------------|-------------|
| local  | `worktree`                    | `none`                   | `docker`    |
| claude | `worktree`                    | `none`                   | `docker`    |
| codex  | `sandbox-copy`                | `sandbox-copy`           | `sandbox-copy` |
| read-only (qualquer) | `none`           | `none`                   | n/a         |

`worktree` requer: projeto git limpo (sem uncommitted changes) + `git worktree add` disponível.
Rollback: `git worktree remove <path>` + `git branch -d <branch>`.

---

## Diferenças locais vs Codex (schema_version)

| Campo | local (0.2-local-only) | codex (0.1 atual) |
|-------|------------------------|-------------------|
| `agent` | `"local"` | `"codex"` |
| `fit.decision` | `always_local\|try_local_first\|destructive_local\|always_claude` | `GO\|NO-GO\|PARTIAL` |
| `fit.heuristics_applied` | ausente | `[H1..H12]` |
| `fit.rules_applied` | presente (routing_rules.yaml) | ausente |
| `sprint.delivery_artifacts` | presente (commit_sha, log_path) | presente (patch_path) |
| `review.decision` | inclui SESSION-CLOSE | inclui SESSION-CLOSE (F5) |

---

## Adapter de schema (Sprint 6 — implementado)

Módulo: `orchestrator\verdict_resolver.py`

### `resolve_verdict_path(task_id, agent, project_path) -> Path`

Retorna o path canônico para o arquivo de veredito:
- Se `agent == "codex"` **e** `.codex/verdicts/<task_id>.json` existe → retorna path legado (preserva imutabilidade)
- Caso contrário → retorna `.delegation/verdicts/<task_id>.json`

### `migrate_v01_to_v02(verdict_dict) -> dict`

Migração one-way em memória. Detecta v0.1 pela **ausência de `schema_version`**.
Não escreve no disco. Não muta o dict de entrada. Retorna o mesmo objeto se já for v0.2+.

Transformações aplicadas:
| Campo | v0.1 (ausente/valor) | v0.2 (adicionado) |
|-------|---------------------|-------------------|
| `schema_version` | ausente | `"0.2"` |
| `agent` | ausente | `"codex"` |
| `fit.rules_applied` | ausente | `[]` |
| `fit.limits_checked` | ausente | `{long_text: false, ...}` |
| `fit.expected_economy_pct` | ausente | `null` |
| `sprint.decision` | `GENERATED` | `GENERATED_INTERACTIVE` |
| `sprint.delivery_artifacts` | ausente | classificado de `evidence_paths` |
| `sprint.sandbox_mode_used` | ausente | `"sandbox-copy"` |
| `sprint.isolation_confirmed` | ausente | `false` |
| `review.delivery_artifacts_verified` | ausente | classificado de `evidence_paths` |

Classificação de `evidence_paths` → `delivery_artifacts`:
- `.patch` → `patch_path`
- `.jsonl` ou contém `log` → `log_path`
- hash hex 7-40 chars → `commit_sha`
