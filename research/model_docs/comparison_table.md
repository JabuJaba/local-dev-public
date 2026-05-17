# Comparação: qwen3.6 vs gemma4 vs Codex — Tool Use & Prompting

Gerado em: 2026-05-01 (Sprint 14)
Objetivo: apoiar Sprint 15 — diagnóstico do problema de tool-call via Claude Code CLI

---

## Tabela comparativa

| Aspecto | qwen3.6 (35B-A3B) | gemma4 (26B) | Codex (OpenAI) |
|---------|-------------------|--------------|----------------|
| **Tool-call format (nativo)** | OpenAI-compat: `tool_calls` array com `function.name` + `function.arguments` (JSON string) | OpenAI-compat via Ollama; Gemma library: `{"tool_name": "...", "arg": "..."}` inline no texto | N/A — usa ações internas (command_execution, file_changes, mcp_tool_calls) |
| **Sistema de template** | Hermes-style embutido no tokenizer (`<\|im_start\|>` / `<\|im_end\|>`) | Chat template nativo com roles `system`/`user`/`assistant`; thinking via `<\|think\|>` | AGENTS.md (persistente) + Skills (sob demanda) |
| **System prompt obrigatório?** | Não — template tem default; sem system prompt o modelo opera mas com menor contexto | Não — mas tool use é mais robusto com system prompt; Gemma 4 adicionou suporte nativo ao role system | Não — AGENTS.md é opcional; sem ele o modelo opera com menos contexto do repo |
| **Parâmetros recomendados** | temp=0.7, top_p=0.8, top_k=20, repeat_penalty=1.05 (non-thinking); temp=0.6 (thinking) | temp=1.0, top_p=0.95, top_k=64 | Não exposto ao usuário (controlado pelo OpenAI) |
| **Comportamento sem system prompt** | Template aplica default "You are Qwen..."; tools passadas via API params, não via system | Funciona; sem system prompt não ativa thinking mode | Opera com contexto mínimo, sem AGENTS.md qualidade cai em repos com convenções não-óbvias |
| **Formato esperado pelo shim Anthropic (Ollama)** | Shim converte OpenAI `tool_calls` → Anthropic `tool_use` block; **falha inconsistente documentada** (emite JSON texto puro) | Shim converte OpenAI `tool_calls` → Anthropic `tool_use` block; sem falhas documentadas localmente | N/A (usa API OpenAI diretamente) |
| **Thinking mode** | Sim; default ON; `enable_thinking: false` para desativar; `reasoning_content` emitido antes do tool call | Sim; ativado com `<\|think\|>` no system prompt; tags vazias mesmo desativado (exceto E2B/E4B) | N/A (raciocínio interno, não exposto) |
| **Tool use oficial** | Sim (Hermes templates, suporte nativo) | Sim em Gemma 4 (nativo); Gemma 1-3 era proof-of-concept | Sim (ações internas do agente) |
| **Via Claude Code CLI (`--bare`)** | `--bare` remove Skills/MCPs mas não afeta tool-call mechanism; **problema documentado**: não invoca tools via CLI (Sprint 14) | A testar (Sprint 15) | N/A |
| **Compatibilidade API** | OpenAI + Anthropic (via Alibaba Cloud); local: shim Ollama→Anthropic com falhas | OpenAI via Ollama; shim Anthropic a validar | OpenAI API (Chat Completions / Responses API) |
| **Contexto máximo** | 262K tokens (35B-A3B) | 128K–256K tokens | Depende do modelo GPT-5.x usado internamente |

---

## Hipótese para o problema de Sprint 14

**Sintoma:** qwen3.6 não invoca tools via Claude Code CLI mesmo com `--system-prompt`

**Causa mais provável (baseada nas docs):**

1. **Thinking mode ativo (padrão):** No modo thinking, o modelo emite `reasoning_content` antes do tool call. O shim Ollama→Anthropic pode não converter corretamente o bloco `<think>...</think>` + tool call em um `tool_use` block do Anthropic.

2. **Template Hermes vs shim:** O shim espera OpenAI `tool_calls` array. Se o modelo emite no formato Qwen-Agent (`function_call` ao invés de `tool_calls`), o shim não reconhece e retorna texto puro.

3. **Workaround a testar (Sprint 15):**
   - Forçar `enable_thinking: false` (non-thinking mode)
   - Verificar se o shim recebe `tool_calls` ou `function_call` via logs
   - Testar com SGLang/vLLM `--tool-call-parser hermes` ao invés de Ollama

---

## Ação recomendada por modelo no pipeline

| Cenário | Modelo recomendado | Motivo |
|---------|-------------------|--------|
| Tool use confiável via Claude Code | **Codex** (handoff) | Único com tool use provado no pipeline |
| Task Bash / shell | **gemma4:26b** | Melhor benchmark Bash; sem falhas de shim documentadas |
| Task coding geral | **qwen3.6:35b-a3b** | Maior benchmark geral; mas tool use via shim instável |
| Task >600 tokens output | **Claude Code cloud** | Todos os locais falham consistentemente |

---

## Referências

- `research/model_docs/codex_summary.md`
- `research/model_docs/qwen36_summary.md`
- `research/model_docs/gemma4_summary.md`
