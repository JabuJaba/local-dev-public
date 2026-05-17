# Gemma 4 — Tool Use & Prompting Summary

Fontes:
- `github.com/google-deepmind/gemma` colabs/tool_use.ipynb (org verificada: google-deepmind, lido 2026-05-01)
- `ollama.com/library/gemma4` — página oficial Ollama
- Benchmark Ollama (local-dev, abril 2026)

---

## 1. Tool-call format

### Via Gemma Python Library (google-deepmind/gemma)

Gemma usa um formato **proprietário e simplificado** via `gm.text.ToolSampler`. O modelo emite tool calls como JSON inline no stream de texto:

```json
{"tool_name": "calculator", "expression": "cos(3) * 2"}
```

O modelo inclui uma linha `Thought:` antes de cada tool call (ReAct-style):
```
Thought: I need to compute S1 = cos(S0) * 2 = cos(3) * 2
{"tool_name": "calculator", "expression": "cos(3) * 2"}
```

Tool result injetado pelo framework:
```
[Tool result: -1.9799849932008908]
```

### Via Ollama (pipeline local-dev)

Via Ollama, Gemma4 expõe **OpenAI-compatible function calling**:
```json
{
  "role": "assistant",
  "tool_calls": [{
    "id": "call_abc",
    "type": "function",
    "function": {"name": "get_weather", "arguments": "{\"location\": \"SP\"}"}
  }]
}
```

---

## 2. System prompt behavior

- Gemma 4 adicionou **suporte nativo ao role `system`** — mudança significativa em relação ao Gemma 3
- Gemma 1, 2, 3: tool use é "proof-of-concept, not officially supported feature"
- Gemma 4: "native function-calling support"

### Ativação de thinking mode
```
<|think|>
```
Incluir `<|think|>` no início do system prompt ativa raciocínio interno. Output:
```
<think>
... raciocínio interno ...
</think>
Resposta final
```
**Nota:** Desativar thinking ainda gera tags `<think></think>` vazias, exceto nas variantes E2B e E4B.

---

## 3. Parâmetros recomendados

| Parâmetro | Valor |
|---|---|
| `temperature` | 1.0 |
| `top_p` | 0.95 |
| `top_k` | 64 |

Diferente do Qwen3.6 (temperature 0.7) — Gemma4 opera melhor com temperatura mais alta.

---

## 4. Comportamento sem system prompt

- Gemma 4 funciona sem system prompt, mas qualidade em tool use pode cair
- Tool descriptions devem ser passadas via parâmetros da API (não via system prompt manual)
- Sem system prompt, o modelo não ativa thinking mode

---

## 5. Diferenças Gemma4 vs Gemma3 em function calling

| Aspecto | Gemma 3 | Gemma 4 |
|---|---|---|
| Tool use oficial | Não (proof-of-concept) | Sim (nativo) |
| System role | Não suportado nativamente | Suportado nativamente |
| Context window | Menor | 128K–256K tokens |
| Thinking mode | Não | Sim (via `<\|think\|>`) |
| Multimodal | Limitado | Expandido |
| Benchmark coding | Inferior | Superior |

---

## 6. Variantes disponíveis (Ollama, 2026-05)

| Tag | Parâmetros | Arquitetura |
|---|---|---|
| `gemma4:e2b` | 2.3B efetivos | Edge |
| `gemma4:e4b` | 4.5B efetivos | Edge |
| `gemma4:26b` | 3.8B ativos (MoE) | MoE |
| `gemma4:31b` | 30.7B | Dense |

**Pipeline local-dev usa:** `gemma4:26b` (slot secundário, ~18.7 tok/s)

---

## 7. Formato esperado pelo shim Anthropic (Ollama)

Via Ollama→Anthropic shim, Gemma4 deve emitir `tool_use` content blocks quando o shim converte corretamente. Sem dados empíricos documentados de falha no shim para Gemma4 (ao contrário do qwen3coder-local).

**Recomendação:** Testar na Sprint 15 se Gemma4:26b via shim invoca tools corretamente no Claude Code CLI.

---

## 8. Resultado benchmark local (abril 2026)

- 31/40 tasks: **77.5%** (melhor dos 3 modelos locais)
- TPS médio: ~18.7 tok/s
- Fraqueza: respostas longas (>600 tokens no-think) — `ec_02`, `lctx_01` com SyntaxError por truncamento
- Força: melhor em tasks Bash que o qwen3.6 (secundário preferido para Bash no CLAUDE.md)
