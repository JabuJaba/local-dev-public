# Claude Code Review Protocol — Sprint 3 Phase 3

## Premissa econômica
- Tokens locais (Qwen3.6 / Gemma4 / CNext) tem custo proprio zero apos GPU — sunk cost de GPU.
- O que conta para a meta de economia (≥20% no `spec.md`) são **tokens consumidos pela assinatura Claude**.
- Baseline Sprint 1 Phase 4: **custo nao-trivial / tool-call mediana** Claude.
- Review leve (~3 tool-calls) = ~custo modesto por task; review completo (~8 tool-calls) = medio.
- Para uma task que sem review viraria escalação , review leve **mantém** o ganho na maioria dos casos.

## Marcação `review_type`
Cada task recebe um `review_type` no momento do classify do `TaskRouter` (Sprint 3 Phase 2):

| review_type | Quando | Custo Claude alvo |
|-------------|--------|-------------------|
| `none`  | tasks `always_local` (read_only, simple_edit, bash_safe, small_write) e `always_claude` (Claude já fez tudo) | 0 tokens |
| `light` | tasks `try_local_first` que passaram em testes | ~3 tool-calls |
| `full`  | tasks `destructive_local` (Docker), `critical: true`, ou marcadas `review_full` no resultado | ~8 tool-calls |

A marcação aparece em todos os entries JSONL do `SessionLogger` (campo `review_type`), permitindo filtragem retroativa.

## Procedimentos por nível

### REVIEW NONE — zero tokens
- Tasks `read_only` não têm side effects; Claude não toca.
- Tasks `always_claude` foram executadas pelo próprio Claude — review redundante.

### REVIEW LIGHT — ~3 tool-calls Claude
1. Ler **apenas o diff** do `git diff` da task (não o arquivo inteiro).
2. Conferir que nenhum arquivo fora do escopo declarado (`canonical_sources` ou pasta do projeto) foi modificado.
3. Rodar lint/test_cmd existente uma única vez. Se passar → marcar `done`. Se falhar → re-fila como `pending` com nota.

### REVIEW FULL — ~8 tool-calls Claude
1. Ler `git diff` completo.
2. Para tasks `destructive_local`:
   - Verificar via `mtime` que o **diretório original** (fora do workspace Docker) não foi tocado.
   - Confirmar `isolated: true` no entry JSONL da task.
3. Validar que o snapshot pré-task (`pre-task-<id>-<ts>` git tag, criado quando `destructive: true`) existe — permite rollback.
4. Rodar test_cmd + integrity_cmd (se houver).
5. Para tasks `critical: true`: revisar contexto arquitetural (ler ADR se afetado).
6. Decisão final: `done`, `pending` (re-tentar), ou `blocked` (escalar humano).

## Check-in schedule
- A cada **2 horas** (cron ou manual): Claude Code lê `python orchestrator/orchestrator.py --status` e processa fila `waiting_handoff`.
- Se fila vazia → 0 tool-calls (zero tokens).
- Se fila tem tasks → revisar **no máximo 5 por check-in** (evita explosão de contexto).
- Tasks `handoff_tag: send_claude` (always_claude) têm prioridade — é a Claude que vai executar.
- Tasks `handoff_tag: escalate_claude` (try_local_first esgotou) entram depois.

## Filtros úteis para o check-in
```bash
# Quantas tasks por handoff_tag
grep -h "handoff" logs/*.jsonl | jq -r '.handoff_tag // "none"' | sort | uniq -c

# Custo estimado da fila pendente (light=1.14, full=3.04)
grep -h "outcome.:.handoff" logs/*.jsonl | jq -r '.review_type'
```

## Métricas a coletar (insumo Sprint 4)
- `% always_local` na semana — alvo: ≥40% (modo conservador `spec.md`).
- `% review_full` no total revisado — manter <30% (é o que mais consome Claude).
- `economia real` = (tokens Claude se 100% Claude) − (tokens Claude reais). Calculado por `scripts/report.py`.
- Routing incorreto (always_local que falhou + foi pra handoff): alvo <15% (gate Sprint 3).

## Override manual
- Para forçar review completo em uma task `try_local_first`: adicionar `review_type: full` no backlog.yaml — orchestrator respeita override (TODO Sprint 4: implementar override de leitura no `TaskRouter`).
- Para suprimir review em task `try_local_first` que já tem cobertura externa de teste: `review_type: none` (idem, TODO Sprint 4).

_Gerado por /sprint-execute em Sprint 3 Phase 3._
