# Local Dev — Regras Operacionais

## Hardware
- CPU: Ryzen 7950X3D (32 threads) — usar `-t 16` no llama.cpp
- GPU: RTX 5070 Ti, 16GB VRAM, **sm_120** (Blackwell consumer; NÃO sm_100)
- RAM: 64GB — permite offload MoE para modelos grandes

## Endpoints locais
| Serviço | URL | Modelo | Uso |
|---|---|---|---|
| Ollama (Anthropic) | http://localhost:11434 | qwen3.6:35b-a3b-q4_k_m | Rota Claude Code primária |
| Ollama (Anthropic) | http://localhost:11434 | gemma4:26b | Rota Claude Code secundária (melhor Bash) |
| Ollama (OpenAI) | http://localhost:11434/v1 | qwen3coder-local | Orchestrator autônomo (não usar em Claude Code: XML-bleed) |
| Ollama (OpenAI) | http://localhost:11434/v1 | gemma4:26b | Slot 3 orchestrator: qualidade |
| llama.cpp | http://localhost:8081/v1 | qwen3-coder-next | Slot 3 batch (Ollama recusa tools no registry) |

## Iniciar pipeline
```powershell
start.ps1          # ambos
start.ps1 -Status  # verificar
```

## Modelos
- **Cardápio:** consultar `<workspace>/cardapio-LLM/` antes de baixar.
- **Rápido (Ollama):** `qwen3-coder:30b-a3b-q4_K_M` (A3B MoE, 18GB, 36+ tok/s); alias `qwen3coder-local` (Modelfile.qwen3coder). Não baixar `qwen3-coder:30b` denso.
- **Batch (llama.cpp):** `models\Qwen3-Coder-Next-Q3_K_M.gguf`; binário `llama_cpp\llama-server.exe` (b8763, CUDA 13.1).
- **Parâmetros Qwen3-Coder:** temperature=0.7, top_p=0.8, top_k=20, repeat_penalty=1.05.
- **Upgrade Qwen3.5-Coder (mai-jun 2026):** `ollama pull qwen3.5-coder:30b` → atualizar `config.yaml` → recriar alias. Sem retrabalho de infra.

## Regras de escalação

### Rota Claude Code (interativa)
1. Tentativas 1-2: qwen3.6:35b-a3b-q4_k_m (primário)
2. Tentativa 3: gemma4:26b (melhor Bash)
3. Bloqueio → handoff em `handoffs/` → usuário cola no Claude Code original
4. **Sempre** invocar com `--bare --allowedTools=Read,Edit,Write,Bash,Glob,Grep`
5. Tasks com output esperado >600 palavras vão direto pro Claude (limite estrutural)

### Rota Orchestrator (autônoma, batch)
1. Tentativas 1-2: qwen3coder-local (~21 tok/s)
2. Tentativa 3: gemma4:26b (~10s troca via Ollama). Para CNext: `use_llama_as_final: true` em config.yaml (requer llama-server)
3. Dúvida → OpenClaw aguarda usuário
4. Bloqueio → handoff em `handoffs/`

## Pipeline unificado (Sprint 7+, ATIVO)

`orchestrator/delegation_rules.yaml` v0.2 — `status: active`. Dados empíricos: Sprint 3 (55.6%), Sprint 5 Codex (3/3 ACEITAR), Sprint 6 (5/5 regression). Economia real <pipeline-project> Sprint 8: **37.3%** (9/20 resolved).

**Projetos com routing ativo:** `<pipeline-project>_rollback_test`, `Subtitle-Forge`.

**Skills:** `/fit-evaluator` → veredito v0.2 em `.delegation/verdicts/`; `/sprint-generator-unified` → fragment por agente; `/universal-review-merge` → review unificado.

**Gotchas pipeline:**
- Modelo local recusa/escala tarefas destrutivas mesmo com Docker `isolated: true` — padrão de segurança, não bug. Destrutivas → `always_claude`.
- qwen3coder-local timeout 300s consistente em arquivos >15KB. Adicionar `max_file_kb: 12` em `try_local_first`.

## Gotchas críticos

### Ollama `num_ctx` (CRÍTICO)
- **Default `num_ctx = 4096`** trunca prompt silenciosamente (sem erro, sem aviso) se arquivo >3KB.
- Diagnóstico: se `tokens in == num_ctx` na resposta, houve truncamento.
- **Fix obrigatório arquivos >3KB:** `"num_ctx": 16384` nas options.
- Causa raiz padrão FP-T01 Sprints 17/20260502. Warm-up sem modelo em VRAM: +30-60s, timeout ≥300s.

### Rota Claude Code local — configuracao correta (Sprint 32)
- `--bare` obrigatório para 30B (sem isso, MCP+Skills afogam).
- `--allowedTools=Read,Edit,Write,Bash,Glob,Grep` limita surface.
- `qwen3coder-local` NÃO usar via Claude Code: emite XML legado (`<function=Read>`) que o shim Anthropic não converte. Só no orchestrator (parser próprio).
- CNext via Ollama é NO-GO — manter GGUF para batch via llama-server.
- **ANTHROPIC_AUTH_TOKEN ignorado pelo Claude Code v2.1.132** — usar `ANTHROPIC_API_KEY=ollama`.
- **ANTHROPIC_CUSTOM_MODEL_OPTION não existe** — modelo via `--model <nome>` flag ou campo `model` em settings.json.
- **`model: inherit` em subagents propaga ANTHROPIC_BASE_URL** — subagents herdam roteamento Ollama (Sprint 32 Phase 1 PASS).
- **num_ctx NAO propagado no caminho /v1/messages (Anthropic-compat)** — sessoes Claude Code via Ollama truncam em 4096 tokens por default, mesmo com modelo configurado para 262K. Fix: Modelfile com `num_ctx 16384` ou maior (Sprint 32 Phase 2 FAIL).
- **Fix aplicado (Sprint 36)**: `Modelfile.qwen3.6-64k` com `num_ctx 65536` criado; validado tokens_in=14911 em arquivo 58.9KB. Reservado para tarefas >50KB context (nao e o modelo padrao -- ver assignments abaixo).
- **count_tokens endpoint ausente em Ollama**: POST `/v1/messages/count_tokens` retorna 404. Workaround: usar campo `prompt_eval_count` da resposta `/api/generate`.
- **Maestro (Sprint 36b COMPLETO)**: `orchestrator/maestro.py` refatorado -- `parse_plan()`, `STEP_RE`, `PlanSchema`, rc checks, `escalation_warnings`. 10/10 testes passando. Planner hallucination corrigida via prompt fix (Phase 1a). `maestro.run()` retorna `plan_schema`, `steps`, `escalation_warnings`.
- **Role assignments (Sprint 36b benchmark empirico)**: planner=`gemma4:26b` (16/18 pts, 0 hallucinacoes), executor=`gemma4:26b` (3/3 Bash, 100%), fallback=`qwen3.6-64k` (>50KB context). Fonte: `benchmark/sprint36b_results.md`.
- **qwen3.6-64k executor: Bash hallucination**: modelo reporta sucesso mas NAO modifica arquivos em operacoes de append/escrita. Usar apenas como planner (contexto longo) ou fallback. NAO usar como executor.
- **qwen3-coder:30b executor**: falha em append -- omite newline, mescla linhas (`beforeafter` em vez de `before\nafter`). NAO usar como executor de Bash.
- **VRAM swap policy (Sprint 36b)**: swap qwen3.6->gemma4 = 6s (< threshold 30s). Policy: `role_specialized` -- dois modelos em pipeline sao viaveis. gemma4:26b: 31.5 tok/s; qwen3.6-64k: 17.1 tok/s. Dois modelos simultaneos: INVIAVEL (VRAM contention). Fonte: `orchestrator/VRAM_policy.md`.
- **PlanSchema**: dataclass em `maestro.py` -- `task`, `steps` (max 5), `context_summary` (max 500 chars), `work_dir`. Handoff estruturado entre planner e executor. Previne overflow de contexto (cada executor call recebe step + summary, nao transcript completo).
- **`claude --bare -p` executa loop multi-turn completo**: com `--allowedTools=...`, o modelo executa tool calls internamente ate producao da resposta final -- NAO e single-turn. Planner com Glob/Read no prompt e arquiteturalmente viavel. (verificado empiricamente 2026-05-07)
- **Aliases no PowerShell profile:** `qwen-cl`/`qwen-clm`, `gemma-cl`/`gemma-clm`, `qwenc-cl`/`qwenc-clm`, `qwenf-cl`/`qwenf-clm`.

### Encoding Windows
- `$env:PYTHONIOENCODING=utf-8` antes de qualquer Python que escreva stdout/arquivos. Task Scheduler default cp1252.
- `.ps1` files: PS5.1 lê UTF-8 sem BOM como Win-1252. **Nunca** usar não-ASCII em string literals .ps1 (em-dash U+2014 vira terminador de string).
- Não usar `sys.stdout.write` Unicode no Windows. Usar `sys.stdout.buffer.write(s.encode('ascii'))` ou `json.dump(..., ensure_ascii=False)` + `open(..., encoding='utf-8')`.

## Docker workspace isolation (Sprint 2.5 — PARTIAL)

- **Imagem:** `local-dev-workspace` (python:3.11-slim + node 20 + claude-code + `USER dev` uid 1000). Build: `docker build -t local-dev-workspace -f docker/Dockerfile.workspace docker/`
- **Scripts:** `docker/ensure_docker.ps1`, `docker/run_workspace.ps1 -ProjectPath <path> [-Detached] [-Rebuild]`
- **Gotchas:** Git Bash converte `/workspace` → `MSYS_NO_PATHCONV=1` antes de `docker run -v`. Claude Code recusa root → Dockerfile usa `USER dev`. Ollama host: `http://host.docker.internal:11434`. Sempre passar `--model qwen3.6:35b-a3b-q4_k_m`.
- **Decisão:** Docker para `destructive: true`; safety interceptor para `always_local` triviais. Veredito: `sprints/sprint_2_5_isolation_report.md`. Backlog: `isolated: true` → `ORCHESTRATOR_ISOLATED=1`.

## Contratos de referencia (Sprint 34)
- **Hooks**: `analise/claude-code-hooks-contract.md` -- o que cada evento pode/NAO pode mutar (anti-pattern rtk_trim documentado)
- **Acceptance**: `analise/sprint-acceptance-contract.md` -- regra dos 2 niveis; termos proibidos; templates Hook/Routing/Skill

## Nunca fazer
- Não usar GLM-4.7 Flash (incompatível com Ollama)
- Não baixar modelos sem consultar `cardapio-LLM/`
- Não sobrescrever `CLAUDE.md` de outros projetos
- Não compilar llama.cpp com sm_100 em RTX 5000 series (usar sm_120)
- Não rodar Ollama+llama.cpp simultâneos (VRAM contention: 32→~5 tok/s)

## Handoff para Claude Code
- Sempre manual — sem API, sem custo extra
- Formato: `handoffs/{projeto}_{timestamp}.md`
- Inclui diff, tentativas, hipótese — sem cold start

## Backlog opcional (`backlog.yaml`)
- `preferred_model: gemma4` — força Gemma4 slot 1 (multifile/longctx)
- `map_tokens: 1024` — projetos grandes
- `priority: 1` — menor = mais prioritário
- `isolated: true` — Docker

## Watchlist Inferência (Trilha 2 — Sprint 10+)

Baseline: `research/baseline_20260429.md`. Checar antes de cada sprint Trilha 2.

| # | Item | Trigger | Ganho | Ação |
|---|---|---|---|---|
| 1 | TurboQuant PR #21089 (llama.cpp) | mergeado | 8K→100K ctx; -7.5% t/s | Ativar `-ctk q8_0 -ctv turbo4` |
| 2 | Qwen3.6-27B no Ollama (mmproj) | `pull` funcionar | ~25 t/s; spec dec | ADR; substituir 35B-A3B |
| 3 | EAGLE-3 PR #18039 (llama.cpp) | mergeado | 4-6x t/s coding | Testar com 27B + draft 1.5B |
| 4 | NVFP4 nativo llama.cpp (#22042) | estável | até 25% prefill | Flag nativa |
| 5 | CUDA 13.2 fix Qwen3.6 (NVIDIA) | novo driver | desbloqueio sem gibberish | Re-rodar `baseline_measure.py` |

## Histórico

- Limites empíricos modelos locais (Sprint 1.5 + 2) e benchmarks abr 2026 → `analise/historic_benchmarks.md`
- Scripts utilitários e detalhes de campos backlog → `docs/scripts.md`

