# LLM Local Inference — Handoff de Otimizações
**Setup:** RTX 5070 Ti 16GB GDDR7 | Ryzen 7950X3D | 64GB DDR5 | Windows 11
**Gerado em:** Abril 2026 | **Fonte:** Sessão de análise + varredura mensal Abril 2026

---

## Índice

1. [Diagnóstico de gargalos reais](#1-diagnóstico-de-gargalos-reais)
2. [TurboQuant — KV Cache Compression](#2-turboquant--kv-cache-compression)
3. [Speculative Checkpointing](#3-speculative-checkpointing)
4. [Speculative Decoding — mapa de elegibilidade](#4-speculative-decoding--mapa-de-elegibilidade)
5. [NVFP4 / MXFP4 — Blackwell nativo](#5-nvfp4--mxfp4--blackwell-nativo)
6. [Flash Attention](#6-flash-attention)
7. [RT Cores para roteamento MoE](#7-rt-cores-para-roteamento-moe)
8. [Tensor Parallelism](#8-tensor-parallelism)
9. [SpecExec — Speculative para offload pesado](#9-specexec--speculative-para-offload-pesado)
10. [Modelos — decisão de troca](#10-modelos--decisão-de-troca)
11. [Combinação recomendada para coding sprints](#11-combinação-recomendada-para-coding-sprints)
12. [Watchlist — ainda não acionável](#12-watchlist--ainda-não-acionável)
13. [Confirmações negativas — o que não funciona](#13-confirmações-negativas--o-que-não-funciona)

---

## 1. Diagnóstico de Gargalos Reais

Antes de qualquer otimização, dois villões físicos distintos que determinam o teto real:

### Vilão 1 — Bandwidth de RAM no offload
Quando modelo não cabe na VRAM e derrama para RAM:
- **DDR5 bandwidth:** ~96 GB/s
- **GDDR7 bandwidth (5070 Ti):** ~900 GB/s
- **Diferença:** 9.4x — intransponível por software
- **Manifestação:** Qwen Coder 80B a ~3 t/s — limitado pela física do barramento

### Vilão 2 — Teto de VRAM (16GB)
- Define qual modelo roda inteiramente no GPU
- Abaixo dessa linha: Flash Attention, RT Cores, NVFP4 não atingem as camadas na RAM
- Qualquer benchmark publicado em GPU com mais VRAM (3090 24GB, 5090 32GB) **não é transferível** sem ajuste

### Implicação estratégica
O ganho real vem de manter modelos **inteiramente dentro da VRAM**, não de otimizar o offload.
Modelos com offload pesado: SpecExec pode dobrar t/s, mas o teto físico permanece baixo.

---

## 2. TurboQuant — KV Cache Compression

**O que é:** Comprime o KV cache de 16-bit para 2–4 bits em runtime. Pesos do modelo não são alterados.

**Paper:** arXiv:2504.19874 (Zandieh et al., ICLR 2026, Google Research)

**Números validados em consumer GPU (fonte primária: ai-engineering-at/llama-cpp-turboquant-guide, 4 runs independentes):**
- Contexto de 8K → 100K tokens no mesmo GPU
- +12% de uso de VRAM (+1.8 GB no benchmark Mistral 24B / RTX 3090)
- -7.5% de tokens/s
- Compressão KV: 4.3x vs f16

**Variantes disponíveis:**

| Variante | Bits | Compressão vs f16 | Impacto qualidade |
|----------|------|-------------------|-------------------|
| turbo2 | 2.0 | 6.4x | +6.48% PPL — extremo |
| turbo3 / tbq3_0 | 3.06 | 4.9x | ~1% PPL — bom |
| turbo4 / tbq4_0 | 4.06 | 3.8x | ~0.3% PPL — excelente |

**Config recomendada para Qwen3.6-27B Q4_K_M:**
```bash
-ctk q8_0 -ctv turbo4 --flash-attn on
```
K em q8_0 (precisão de atenção é dominante), V em turbo4 (compressão sem custo significativo).

**Caveat de arquitetura para modelos híbridos (ex: Qwen3.6-27B):**
- 75% das camadas são GatedDeltaNet (atenção linear) — **sem KV cache convencional**
- TurboQuant comprime apenas as 25% de camadas com atenção quadrática
- Headroom real de VRAM é maior do que o tamanho do modelo sugere
- Symmetric turbo (`-ctk turbo3 -ctv turbo3`) válido para modelos Q8_0+; para Q4_K_M, preferir assimétrico

**Sparse V (TheTom/turboquant_plus, não-paper):**
- Pula posições V de baixo peso durante decoding
- +22.8% de decode speed a 32K context, zero impacto em PPL
- Funciona com q8_0, q4_0 e turbo3 KV

**Status de implementação (verificado 19 Abr 2026):**

| Implementação | Status | Uso |
|---|---|---|
| PR #21089 (main llama.cpp) | Em review, não mergeado | Aguardar |
| TheTom/turboquant_plus | Ativo, 18/18 testes passando | Usar hoje |
| AmesianX/TurboQuant | Fork estável com CUDA | Alternativa |

**Build correto (erro comum):**
```bash
# ERRADO — flag silenciosamente ignorada desde o refactor GGML:
cmake -DLLAMA_CUBLAS=ON .

# CORRETO:
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
```

---

## 3. Speculative Checkpointing

**O que é:** Elimina o custo de backup completo do KV cache a cada rollback durante speculative decoding. Antes, o overhead de sincronização de memória anulava os ganhos de spec decoding em consumer GPUs.

**Merge:** 18 de abril de 2026, Georgi Gerganov (main llama.cpp)
**Build mínimo:** llama.cpp b8500+

**Números reportados (fonte: startupfortune.com — verificar contra PR antes de citar):**
- Até 40% redução de VRAM em operações batched
- 15–20% melhora em t/s em hardware bandwidth-limited

**Impacto prático:** Habilita speculative decoding em consumer GPUs pela primeira vez com custo-benefício positivo. Pré-requisito para as combinações descritas na seção 4.

**Downstream:** Ollama, LM Studio e GPT4All já rastreando integração da master branch.

---

## 4. Speculative Decoding — Mapa de Elegibilidade

A lógica: modelo draft pequeno propõe N tokens → modelo target verifica todos em um único forward pass. Só funciona quando há compute ocioso suficiente para a verificação ser gratuita.

### Quando funciona (no teu setup):

| Cenário | Ganho esperado | Config |
|---|---|---|
| Modelo denso 8B–14B totalmente na VRAM | +40–150% em coding | Draft Qwen2.5-Coder-1.5B |
| Qwen3.6-27B denso (~fit total) | A testar pós-checkpointing | Draft Qwen3.5-1.5B ou Qwen2.5-Coder-1.5B |
| Qwen3.6-27B, tasks repetitivas de código | Potencial +100%+ | Draft 0.5B–1.5B família Qwen |

**Nota sobre n-gram self-speculation** (sem draft model):
- Casos extremos (edição repetitiva de código): até 665% de speedup
- Média em workloads diversos: 40–150%
- Tasks variadas / reasoning: zero melhora ou negativo

### Quando não funciona:

| Cenário | Motivo |
|---|---|
| Qwen 35B-A3B MoE (16GB, offload) | GPU saturado em bandwidth — overhead excede savings |
| Qualquer modelo com offload pesado | Vilão 1 domina, compute não está ocioso |
| MoE geral em consumer GPU | Ver Seção 13 |

---

## 5. NVFP4 / MXFP4 — Blackwell Nativo

**O que é:** Formato FP4 com suporte nativo nos Tensor Cores de 5ª geração do RTX 5070 Ti (Blackwell).

**Ganhos documentados:**
- ComfyUI / Flux.1: 3x speedup vs FP16, 60% menos VRAM — **já disponível e estável**
- Prompt processing (prefill) em LLMs: até 25% de ganho
- vLLM com NVFP4: 3–4x throughput vs llama.cpp em alta concorrência (benchmark Qwen3.6-27B em 2× RTX 5060 Ti)

**Modelos com release NVFP4 oficial (HuggingFace):**
- Llama 4 Scout 17B-16E
- Llama 3.3 70B / 3.1 8B / 3.1 405B
- DeepSeek-R1, DeepSeek-R1-0528, DeepSeek-V3.2
- Qwen3.6-27B-FP8 (não FP4, mas 128-block fine-grained)

**Status por stack:**

| Stack | Status NVFP4 |
|---|---|
| ComfyUI / Flux.1 | ✅ Estável — usar agora |
| vLLM (LLMs) | ✅ Estável com modelos oficiais |
| llama.cpp | ⚠️ Em discussão (issue #22042) — riscos de corretude, aguardar |
| Ollama | ❌ Não disponível |

---

## 6. Flash Attention

**O que é:** Computa atenção em blocos menores (tiling), reduzindo transferências entre VRAM e memória do sistema.

**Ganhos por caso de uso:**

| Caso | Ganho real |
|---|---|
| Prefill a 32K+ tokens | 2–3x mais rápido |
| Token generation (TG) | 10–20% |
| Modelos com offload | Negligenciável (gargalo é RAM, não atenção) |

**Pré-requisito obrigatório** para TurboQuant. Ativar sempre:
```bash
--flash-attn on   # ou -fa 1
```

---

## 7. RT Cores para Roteamento MoE

**O que é:** Repropósito dos RT Cores (normalmente para ray tracing) para processar roteamento de tokens para experts em modelos MoE.

**Speedup:** 218x na operação de roteamento isolada.

**Impacto no modelo completo:** O roteamento representa 1–3% do tempo total de inferência.
- Modelos MoE densos (poucos experts): ~2–5% de ganho em t/s no modelo completo
- Llama 4 Scout (16 experts ativos de 128): potencial 5–10%

**Status:** Técnica de pesquisa. Sem PR concreto no llama.cpp em abril 2026.

**Para o Qwen Coder 80B a 3 t/s:** irrelevante — gargalo é bandwidth de RAM, não roteamento.

---

## 8. Tensor Parallelism

**O que é:** Divide matrizes de pesos entre múltiplas GPUs computando em paralelo (vs. layer-split sequencial anterior).

**Merge:** llama.cpp, backend-agnostic (CUDA + ROCm + Metal).

**Números reais em PCIe (sem NVLink):**
- vs. GPU único: +40–60% de t/s — nunca 2x
- Overhead: all-reduce a cada token gerado via PCIe (~16–32 GB/s)
- Com NVLink (600 GB/s): ~1.8x, ainda não 2x por overhead de sincronização

**Conclusão para setup single-GPU:** Irrelevante hoje. Relevante apenas se adicionar segunda GPU para ampliar VRAM total para modelos maiores, não para ganho de velocidade.

---

## 9. SpecExec — Speculative para Offload Pesado

**O que é:** Speculative decoding projetado especificamente para o cenário de offload RAM. Constrói uma "cache tree" de continuações prováveis e verifica em batch durante o tempo em que a GPU já estaria esperando dados da RAM.

**Lógica:** Com offload, o bottleneck muda de *compute por token* para *tempo de transferência RAM→GPU por camada*. Se a camada leva 300ms para ser carregada de qualquer forma, verificar 20 tokens durante esse tempo é gratuito.

**Ganho documentado:** 4–6 t/s em modelos 50B+ com offload (vs. 2–3 t/s baseline).
Para o Qwen Coder 80B: 3 t/s → potencialmente 5–7 t/s.

**Requisitos:** PCIe 4.0+ e ≥32GB DDR5. Teu setup tem ambos.

**Limitação:** É o teto do software contra o Vilão 1. Não resolve o gargalo fundamental.

---

## 10. Modelos — Decisão de Troca

### Qwen3.6-27B denso vs Qwen3.6-35B-A3B MoE (contexto 16GB VRAM)

| Critério | 27B Denso | 35B-A3B MoE |
|---|---|---|
| Tamanho Q4_K_M | 16.8 GB | ~22 GB |
| Offload necessário (16GB VRAM) | ~800MB — negligenciável | ~6 GB — significativo |
| Velocidade efetiva (16GB) | ~25 t/s quase full VRAM | Bem abaixo do 101 t/s publicado |
| Benchmark 101 t/s publicado | N/A | Medido em RTX 3090 24GB — não transferível |
| Speculative decoding | ✅ Elegível | ❌ Negativo confirmado |
| TurboQuant | ✅ Comprime 25% quadráticas | ✅ Comprime camadas de atenção |
| SWE-bench Verified | 77.2% | (anterior: 76.2% no 397B-A17B) |
| Arquitetura atenção | 75% linear + 25% quadrática | MoE puro |
| Ollama | ❌ Não suportado (mmproj) | ✅ Suportado |

**Veredito para coding sprints em 16GB:** 27B denso ganha — offload negligenciável, spec decoding elegível, qualidade superior em coding.
**35B-A3B mantém vantagem:** Chat geral rápido, múltiplas apps simultâneas, Ollama.

### Arquitetura híbrida do Qwen3.6-27B
- 64 camadas em 16 blocos repetidos: 3× GatedDeltaNet (linear, O(n)) + 1× Gated Attention (quadrática)
- GatedDeltaNet: 48 value heads + 16 Q/K heads, sem KV cache convencional
- Atenção quadrática: 24 Q heads + 4 K/V heads (KV mínimo por design)
- Resultado: KV cache real ~4x menor do que modelo denso equivalente — mais headroom para contexto longo

### Modelos de referência por tier (Abril 2026)

| Tier / Uso | Modelo | Tamanho Q4 | t/s estimado 16GB |
|---|---|---|---|
| Coding sprint principal | Qwen3.6-27B UD-Q4_K_XL | 16.8 GB | ~25 t/s |
| Chat geral / offload aceitável | Qwen3.6-35B-A3B | ~22 GB | ~12–18 t/s |
| Autocomplete / FIM | Qwen2.5-Coder-14B | ~9 GB | ~45 t/s |
| Draft p/ spec decoding | Qwen3.5-1.5B ou Qwen2.5-Coder-1.5B | ~1 GB | — |
| Classificação (Radar LinkedIn) | Qwen3.5-8B ou Gemma 4 4B | ~5–6 GB | ~50–70 t/s |

### ⚠️ Avisos críticos (Qwen3.6)
- **CUDA 13.2 produz gibberish** com Qwen3.6. Fixar em CUDA 12.x ou 13.1. NVIDIA trabalhando no fix.
- **Ollama não suporta Qwen3.6** por causa dos mmproj files de visão separados. Usar llama.cpp direto ou LM Studio.

---

## 11. Combinação Recomendada para Coding Sprints

Stack completo acionável hoje para o caso de uso principal (sprint longa, contexto >32K):

```bash
# Build com TurboQuant (TheTom fork) + Flash Attention habilitado
git clone https://github.com/TheTom/turboquant_plus
cd turboquant_plus
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)

# Download do modelo
huggingface-cli download unsloth/Qwen3.6-27B-GGUF UD-Q4_K_XL.gguf

# Servidor com configuração otimizada
./build/bin/llama-server \
  -m Qwen3.6-27B-UD-Q4_K_XL.gguf \
  -ngl 99 \
  -c 65536 \
  --flash-attn on \
  -ctk q8_0 -ctv turbo4 \
  --temp 0.6 --top-p 0.95 --top-k 20 \
  --reasoning on \
  --chat-template-kwargs '{"preserve_thinking": true}' \
  --host 0.0.0.0 --port 8080
```

**O que cada flag faz:**
- `-ngl 99` — máximo de camadas no GPU (evitar offload)
- `--flash-attn on` — pré-requisito para TurboQuant + ganho em prefill
- `-ctk q8_0 -ctv turbo4` — K cache preciso (roteamento de atenção), V cache comprimido
- `--reasoning on` — habilita modo de raciocínio híbrido do Qwen3.6
- `preserve_thinking: true` — mantém traces de reasoning entre turns

**Próximo passo a testar:** Adicionar speculative decoding com draft Qwen3.5-1.5B:
```bash
# Adicionar ao comando acima:
-md ./Qwen3.5-1.5B-Q4_K_M.gguf \
--draft 8 \
--n-gpu-layers-draft 99
```

---

## 12. Watchlist — Ainda Não Acionável

| Item | Status (Abr 2026) | O que aguardar |
|---|---|---|
| TurboQuant PR #21089 | Em review, não mergeado | Merge → usar via Ollama/LM Studio sem compilar fork |
| NVFP4 nativo llama.cpp (issue #22042) | Em discussão, riscos de corretude | Estabilização antes de ativar |
| EAGLE-3 PR #18039 | Em draft | Merge → testar com Qwen3.6-27B denso; 4–6x projetado em coding |
| CUDA 13.2 fix Qwen3.6 | NVIDIA confirmou bug | Fix confirmado → atualizar driver |
| Qwen3.6-27B no Ollama | Bloqueado por mmproj | PR no repo Ollama |
| RT Cores para MoE | Técnica de pesquisa | PR concreto no llama.cpp |
| SpecExec upstream | Sem PR no main | Integração em llama.cpp ou vLLM |
| BitNet 1.58-bit consumer | Papers sem impl. madura | Modelo 70B em 1.58-bit com qualidade aceitável em coding |
| DGX Spark / NVLink C2C consumer | Hardware futuro (2–3 anos) | Unified memory consumer grade >300 GB/s |

---

## 13. Confirmações Negativas — O que Não Funciona

Dados negativos são tão valiosos quanto positivos. Evitam re-testar o que já foi invalidado.

**Speculative decoding em MoE com ≤3B ativos (16GB VRAM):**
- 19 configurações testadas (ngram-cache, ngram-mod, classic draft com Qwen3.5-0.8B)
- Resultado: queda de 3–12% em t/s em **todas** as variantes, mesmo com 100% de taxa de aceitação
- Causa: overhead de verificação num GPU saturado em bandwidth excede a economia de pular forward passes
- Fonte: benchmark comunitário r/LocalLLaMA, RTX 3090 equivalente, Abr 2026

**TurboQuant com head_dim=512 (ex: Gemma 4 31B):**
- QJL não converge corretamente — usar apenas MSE-only
- WHT + QJL: para modelos com head_dim=64, K cache cai para q8_0 automaticamente

**QJL no TurboQuant (resultado contra-intuitivo do paper):**
- QJL elimina bias mas explode variância
- Para atenção, variância é mais danosa que bias — MSE-only ganha em Top-1 token matching
- Impl. recomendada: MSE-only ou assimétrico (turbo para V, q8_0 para K)

**Tensor Parallelism para velocidade (PCIe, sem NVLink):**
- Ganho real: +40–60% vs GPU único — nunca 2x
- Cada token exige all-reduce inter-GPU via PCIe (~16–32 GB/s)
- Uso legítimo: ampliar VRAM total para modelos maiores, não para velocidade

**Dois GPUs consumer = pior que um (pre-tensor-parallelism):**
- Layer-split sequencial: GPU 2 espera GPU 1 terminar sua camada antes de iniciar
- Resultado: utilização de 50% em ambos, throughput inferior ao single GPU
- Tensor parallelism resolve a subutilização, mas não o overhead de PCIe

---

## Baseline Ativo — Abril 2026

```
Stack:      llama.cpp b8500+ (pós speculative checkpointing, 18 Abr 2026)
Fork:       TheTom/turboquant_plus (para TurboQuant antes do PR merge)
Modelo:     Qwen3.6-27B UD-Q4_K_XL (16.8GB) — coding sprints
KV cache:   -ctk q8_0 -ctv turbo4 (assimétrico para Q4_K_M pesos)
Spec dec:   A testar — primeira vez elegível (denso + checkpointing)
CUDA:       12.x ou 13.1 (13.2 produz gibberish em Qwen3.6)
Ollama:     Manter para modelos 8B–14B; Qwen3.6-27B requer llama.cpp direto
Flux.1:     NVFP4 ativo no ComfyUI — 3x speedup, -60% VRAM (já estável)
```

---

*Próxima varredura: Maio 2026 — trigger "varredura mensal" na conversa.*
*Skill de automação: llm-innovation-scan_SKILL.md*
