# Spec — Local-First Routing com Claude Code como Coordenador

## Objetivo
Reduzir o consumo real de tokens da assinatura Claude roteando tarefas de código para modelos locais (Qwen3-Coder A3B, Gemma4 26B, CNext) e usando Claude Code apenas para coordenação, review e escalação. O orchestrator existente serve como camada de execução local; Claude Code formaliza o protocolo de review e as regras de roteamento.

## Critério de Sucesso
- ≥20% de redução de tokens vs baseline medido (tokens reais do token_log.jsonl)
- 0 arquivos corrompidos em projetos originais durante qualquer sprint
- Smoke test do orchestrator (`tests/test_orchestrator_smoke.py`, ~100 inline assertions) passa após cada sprint
- Matriz de compatibilidade de tool use documentada (modelo × tipo de tool)

## Escopo

### IN
- Correção do token_log (atualmente registra zeros)
- Teste de compatibilidade de tool use: formato Anthropic com Qwen/Gemma
- Configuração de ANTHROPIC_BASE_URL para Claude Code apontar para Ollama
- Safety interceptor para operações destrutivas (rm, overwrite)
- Regras de roteamento: quais tipos de task vão local vs Claude
- Integração do protocolo de routing no orchestrator existente
- Protocolo de review do Claude Code (o que verifica, quando, custo em tokens)
- Validação em produção: <pipeline-project>_Extractor (tem backup _20260411)
- Reescrita parcial ou total do orchestrator se necessário

### OUT
- Projetos originais <game-bot>, <pipeline-project>, Subtitle antes do Sprint 4 ter dados validados
- Novos modelos além dos já instalados (consultar cardapio-LLM/ primeiro)
- Modificação do Claude Code source
- Infraestrutura de nuvem ou APIs externas pagas

## Sprints
| Sprint | Nome | Objetivo |
|--------|------|----------|
| 1 | Baseline + Tool Use POC | Medir consumo real, testar tool use Anthropic format em sandbox |
| 2 | Integração + Safety Layer | Claude Code via ANTHROPIC_BASE_URL, interceptor destrutivo |
| 2.5 | Docker Workspace Isolation | Confinamento real via container — substitui interceptor se go |
| 3 | Routing Protocol + Orchestrator | Regras de roteamento, integração orchestrator, protocolo review |
| 4 | Validação em Produção | Rollout <pipeline-project>, 20+ tasks monitoradas, economia confirmada |

## Estimativa de Economia
| Cenário | Economia Esperada |
|---------|------------------|
| Conservador (routing cauteloso, 40% local) | ~20-25% |
| Moderado (60% local, review leve) | ~30-35% |
| Teórico máximo (sem overhead de escalação) | ~45-48% |

Meta comprometida: **≥20%** confirmada com dados reais no Sprint 4.

_Gerado por /project-plan em 2026-04-19_

---

## Fechamento — CONCLUÍDO (2026-04-23)

**Status: ENCERRADO — meta atingida**

### Resultado Real
| Métrica | Valor |
|---------|-------|
| Economia líquida real | **37.3%** (9/20 tasks resolvidas localmente, Sprint 8) |
| Critério de sucesso (≥20%) | ✅ ATINGIDO |
| Decisão de rollout | CAUTELOSO (abaixo de 40% = threshold CONFIANTE) |
| Data de medição | 2026-04-23 (Ollama online, 20 tasks <pipeline-project>_Extractor) |

### Economia por categoria (Sprint 8 dados reais)
| Categoria | Resolved | Total | Economia |
|-----------|----------|-------|---------|
| always_local | 4 | 8 | 57.9% |
| try_local_first | 4 | 8 | 40.7% |
| destructive_local | 0 | 4 | 0% |

### Hardening Sprint 9 (2026-04-23)
- `max_file_kb: 12` adicionado em `try_local_first` → evita timeouts 300s em arquivos >12KB
- `destructive_local` migrado para `always_claude` → 0 handoffs previsíveis em tasks destrutivas
- Gemma4 slot 3 investigado: intencionalmente não acionado (should_escalate() e max_local_attempts=2 bloqueiam antes de atingir tentativa 3)
- Smoke tests: TODOS OS CHECKS PASSARAM após hardening

---

## Trilha 2 — Otimização de Inferência Local (aberta 2026-04-29)

### Objetivo
Otimizar o stack de inferência local (llama.cpp + Ollama + drivers) com base no handoff de pesquisa `research/llm-optimization-handoff.md` (abr 2026). Caminho conservador: quick wins de baixo risco + watchlist persistente para itens dependentes de upstream merge.

### Critério de Sucesso
- Baseline numérico documentado (CUDA, flash-attn, t/s, VRAM) para os 3 modelos primários
- CUDA fixada em ≤13.1 (Qwen3.6 gibberish bug com 13.2)
- Flash-attn ativo no Slot 3 (llama-server) com ganho de prefill ≥1.5x
- Watchlist persistente com 5 itens revisáveis em revisões mensais
- Zero regressão nos smoke tests do orchestrator (53/53 PASS)

### Escopo
**IN**
- Baseline numérico do stack atual (medição em produção)
- Verificação/correção de CUDA
- Flash-attn no llama-server
- NVFP4 no ComfyUI/Flux.1 (condicional ao uso)
- Watchlist de itens upstream (TurboQuant, Qwen3.6-27B@Ollama, EAGLE-3, NVFP4 llama.cpp, CUDA 13.2)
- ADR sobre manter Qwen3.6-35B-A3B como primário até Ollama suportar 27B denso

**OUT (esta trilha)**
- Troca de modelo primário (aguarda Ollama suportar Qwen3.6-27B)
- Build de fork TheTom/turboquant_plus (aguarda PR #21089 mergear no main)
- Speculative decoding em MoE (negativo confirmado)
- Tensor parallelism (single GPU)

### Sprints
| Sprint | Nome | Objetivo |
|--------|------|----------|
| 10 | Baseline + Quick Wins | Medir, corrigir CUDA, ativar flash-attn, instalar watchlist |

---

## Trilha 3 — Audit (encerrada 2026-05-06)

A fase audit (Sprints 23-27) encerrou-se com Sprint 28 e ADR-015 (ver `ADR.md`). 5 sprints de medição empírica refutaram em sequência: (1) baseline turn-0 como driver de gasto não-atacável, (2) hooks/MCPs trim com teto -4.8%, (3) source <pipeline-project> como leak otimizável (≤2%), (4) caching ausente (já ativo automaticamente). Driver real do gasto semanal <pipeline-project>: **mega-sessões Opus power-law** (top 3 = 65% do gasto, custo ~quadrático em tool_calls).

**Decisão durável:** Trilha 3 stack original (rtk + graph + repomix + LiteLLM + 6 specialists) **não construída**. Local-dev redirecionado para manutenção + 3 levers fora-do-source priorizados por ROI: (1) session-close discipline + Opus→Sonnet em mega-sess, (2) rtk hook global, (3) replicar Sprint 8 routing nas top-3 mega-sess <pipeline-project> (condicional). Detalhes e priorização em ADR-015 e seu apêndice executável.

Sprints 29+ são novas, geradas via `/sprint-generator` em sessão fresh, com escopo definido pelos levers do ADR-015.
