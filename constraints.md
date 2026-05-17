# Constraints — Local-First Routing com Claude Code

## Ambiente
- OS: Windows 11 Pro, shell bash via Claude Code
- GPU: RTX 5070 Ti, 16GB VRAM, **sm_120** (Blackwell — nunca sm_100)
- RAM: 64GB — permite offload MoE
- Python: instalado em  (venv local)
- Encoding: PYTHONIOENCODING=utf-8 obrigatório em scripts Windows

## Modelos Permitidos
| Modelo | Engine | Uso | Sprint 1.5 (rota Claude Code) |
|--------|--------|-----|-------------------------------|
| `qwen3.6:35b-a3b-q4_k_m` | Ollama | **Primário** rota interativa Claude Code + orchestrator | 9/10 outcome, 6/10 tool match |
| `gemma4:26b` | Ollama | **Secundário** rota interativa, melhor em Bash | 9/10 outcome, 4/10 tool match |
| `qwen3coder-local` (A3B MoE) | Ollama | **Apenas orchestrator autônomo** — descartado da rota Claude Code (XML-bleed) | 8/10 outcome, 4/10 tool match |
| `qwen3-coder-next` | llama.cpp GGUF | Slot 3 batch (via llama-server) — **não funciona via Ollama** (registry recusa tools) | NO-GO Ollama |

- **Proibido rodar dois modelos simultâneos** (VRAM contention: cai de 32 para ~5 tok/s) — `ollama stop` antes de carregar o próximo
- Novos modelos: consultar `<workspace>/cardapio-LLM\` antes de qualquer download

## Endpoints Locais
| Serviço | URL OpenAI-compat | URL Anthropic-compat | Uso |
|---------|-------------------|----------------------|-----|
| Ollama | http://localhost:11434/v1 | http://localhost:11434 | Claude Code usa Anthropic |
| llama.cpp | http://localhost:8081/v1 | (não suportado nativamente) | orchestrator |

## Projetos — Regra de Toque
| Projeto | Status | Ação permitida |
|---------|--------|---------------|
| <pipeline-project>_Extractor | Backup existe (_20260411) | Sandbox: duplicar; Prod: Sprint 4 apenas |
| Subtitle-Forge | Sem backup | Duplicar antes de qualquer teste |
| <game-bot> (<gaming-scraper>?) | Sem backup | Somente após Sprint 4 validado |
| local-dev (orchestrator) | Em andamento | Pode editar — é o projeto-alvo |

## Gotchas Conhecidos
- Token log: corrigido no Sprint 1 — hook `~/.claude/hooks/token_logger.py` agora parseia `~/.claude/projects/*/*.jsonl`. Pricing inclui cache + tier 1M (>200K ctx → 2x). Backup em `.bak.20260420`.
- Gemma4 trunca respostas longas (>600 tokens no-think) com SyntaxError — não usar para tasks que exijam edições grandes de arquivo
- **Output ~800 palavras falha em 3/3 modelos locais** (Sprint 1.5 task 9) — limite estrutural, routing rules da Sprint 3 devem barrar geração longa
- Endpoint Ollama para Claude Code: `http://localhost:11434` (sem `/v1`) — formato Anthropic
- ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN=dummy para redirecionar Claude Code localmente
- **`--bare` + `--allowedTools=Read,Edit,Write,Bash,Glob,Grep` obrigatório** para modelos 30B — sem isso o tool surface (MCP + Skills) afoga o modelo. Aplica-se a Sprint 2+ no modo local.
- **qwen3coder-local emite `<function=Read>...</function>` (formato OpenAI legado)** — shim Anthropic do Ollama não converte; tool_use vira texto. Reproduzível. Usar só no orchestrator autônomo (parser próprio).
- Tasks que sempre falham e vão para handoff: generators com send()/throw(), async event loops customizados
- `ANTHROPIC_CUSTOM_MODEL_OPTION` aceita apenas UM modelo customizado (limitação do Claude Code)

## Parâmetros de Qualidade dos Modelos Locais
- Qwen3-Coder: temperature=0.7, top_p=0.8, top_k=20, repeat_penalty=1.05
- Gemma4: defaults (não documentado no CLAUDE.md)

## Referências
- Benchmark coding (40 tasks, abr 2026): `benchmark/benchmark_20260412_*.json`
- Smoke test orchestrator: `python tests/test_orchestrator_smoke.py` (~100 inline `check(...)` assertions; exit 0 = all green)
- Orchestrator config: `orchestrator/config.yaml`

_Gerado por /project-plan em 2026-04-19_
