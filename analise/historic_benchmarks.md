# Histórico de Benchmarks — local-dev

Movido de `CLAUDE.md` em Sprint 24 (baseline-cleanup, 2026-05-06).
Conteúdo histórico mantido para referência; não consultar em runtime.

## Sprint 1.5 + 2 — Limites empíricos dos modelos locais

Tarefas que **sempre escalam para handoff** (modelos locais falham consistentemente):
- **Geração de texto longo (>600 palavras)**: Sprint 1.5 3/3 modelos falharam; Sprint 2 qwen3.6 entregou 40 palavras quando pedido 800. Adicionar `map_tokens: 1024` e aceitar handoff.
- **Generators com `send()` / `throw()`**: protocolo de coroutine raro em treino (Sprint 1.5). Curiosamente Sprint 2 task 10 passou no qwen3.6 (1/3 atual) — não determinístico, melhor escalar.
- **Async event loops customizados** (asyncio interno, não uso comum).

### Task types recomendados para routing local (Sprint 2 — 18/20 PASS no primário)
Local-first OK (outcome high, tokens ~5-10k por task):
- Read/grep/glob de arquivos conhecidos (tasks 1, 3, 11, 13, 18, 20)
- Edit pontual em arquivo existente (tasks 5, 15)
- Bash para introspecção rápida (tasks 4, 8, 12, 16)
- Write de arquivos novos com conteúdo curto (tasks 14, 19)

Direto pra Claude Code cloud (sem tentativa local):
- Output > 600 palavras (resumos, documentação longa)
- Refactors multi-arquivo com dependências cruzadas
- Depuração de stack traces longos

### Tool match (dados Sprint 2 qwen3.6)
- qwen3.6 usa Bash como canivete suíço — 9/20 tool match formal, mas 18/20 outcome PASS
- Não penalizar tool_match baixo se outcome PASS: modelo decide por Bash e funciona
- Write é a ferramenta menos confiável: task 6 (`scripts/hello_local.py`) falhou porque modelo tentou `echo > file` via Bash em vez de Write

## Resultados de benchmark (coding, 40 tasks, abril 2026)

| Modelo | Passou | % | TPS médio | Arquivo |
|--------|--------|---|-----------|---------|
| Gemma 4 26B (Ollama) | 31/40 | **77.5%** | ~18.7 | benchmark_20260412_134012.json |
| Qwen3-Coder-Next Q3_K_M (llama.cpp 80B MoE) | 30/40 | **75%** | ~18.6 | benchmark_20260412_132727.json |
| qwen3coder-local A3B MoE (Ollama) | 29/40 | **72.5%** | ~20.8 | benchmark_20260412_133311.json |

Pontos fracos comuns (todos os modelos): `ec_01` Unicode NFC+casefold, `int_03` Observer weak refs, `adv_02` generator send()/throw().
Gemma4 falha em respostas longas (>600 tokens no-think): `ec_02`, `lctx_01` com SyntaxError por truncamento.
CNext supera Gemma4 em: context manager no Windows (redteam_03), confidence trap (redteam_05).
