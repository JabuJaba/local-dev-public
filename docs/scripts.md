# Scripts utilitários local-dev

Movido de `CLAUDE.md` em Sprint 24 (baseline-cleanup).

| Script | Uso |
|---|---|
| `python scripts/report.py` | Relatório semanal (logs JSONL) |
| `python scripts/report.py --diagnose` | Relatório + diagnóstico de todos os projetos |
| `python scripts/diagnose.py` | Diagnóstico de saúde de todos os projetos |
| `python scripts/diagnose.py --add-to-backlog` | Aprovar sugestões e adicionar ao backlog |
| `python scripts/diagnose.py --github-only` | Apenas verificações de prontidão para GitHub |
| `python orchestrator/orchestrator.py --status` | Servidores + modelo em VRAM + backlog |
| `python orchestrator/orchestrator.py --watch` | Status em loop (atualiza a cada 30s) |
| `python orchestrator/orchestrator.py --retry-handoffs` | Re-fila tasks `waiting_handoff` → `pending` |
| `python tests/test_orchestrator_smoke.py` | Smoke test do orquestrador (~100 inline `check(...)` assertions) |
| `python benchmark/bench.py --model qwen36` | Benchmark coding do Qwen3.6 35B A3B |
| `python benchmark/bench_ocr.py` | Benchmark OCR: qwen3.6 vs gemma4 (10 tasks, vision) |

## Campos opcionais no backlog.yaml

- `preferred_model: gemma4` — força Gemma4 no slot 1 (tasks multifile/longctx)
- `map_tokens: 1024` — aumentar para projetos grandes
- `priority: 1` — menor = mais prioritário
- `isolated: true` — roda task em container Docker (`ORCHESTRATOR_ISOLATED=1`)
