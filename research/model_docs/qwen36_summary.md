# Qwen3.6 — Tool Use & Prompting Summary

Fontes:
- `github.com/QwenLM/Qwen3.6` README (org verificada: QwenLM/Alibaba, lido 2026-05-01)
- `qwen.readthedocs.io/en/latest/framework/function_call.html`
- `qwen.readthedocs.io/en/latest/run_locally/ollama.html`
- `github.com/QwenLM/Qwen3` README

---

## 1. Tool-call format

Qwen3.6 usa o formato **OpenAI-compatible** com templates **Hermes-style** embutidos no tokenizer.

### Definição de ferramenta (input)
```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Retorna clima de uma localização",
    "parameters": {
      "type": "object",
      "properties": {
        "location": {"type": "string", "description": "cidade"}
      },
      "required": ["location"]
    }
  }
}
```

### Resposta do modelo com tool call (vLLM / OpenAI API format)
```json
{
  "role": "assistant",
  "tool_calls": [{
    "id": "call_abc123",
    "type": "function",
    "function": {"name": "get_weather", "arguments": "{\"location\": \"São Paulo\"}"}
  }]
}
```

### Resposta do modelo (Qwen-Agent format)
```json
{
  "role": "assistant",
  "function_call": {
    "name": "get_weather",
    "arguments": "{\"location\": \"São Paulo\"}"
  }
}
```

### Tool result (role "tool" no formato OpenAI, "function" no Qwen-Agent)
```json
{"role": "tool", "tool_call_id": "call_abc123", "content": "22°C, nublado"}
```

---

## 2. System prompt behavior

- Chat template usa delimiters `<|im_start|>` / `<|im_end|>`:
  ```
  <|im_start|>system
  You are a helpful assistant.<|im_end|>
  <|im_start|>user
  ...
  ```
- O template **gerencia automaticamente** a formatação das tool definitions — não é necessário construir manualmente o bloco de tools no system prompt.
- Default system message (Ollama): `"You are Qwen, created by Alibaba Cloud. You are a helpful assistant."`

---

## 3. Parâmetros recomendados

| Modo | temperature | top_p | top_k | repeat_penalty |
|---|---|---|---|---|
| **Não-thinking (padrão Claude Code)** | 0.7 | 0.8 | 20 | 1.05 |
| **Thinking** | 0.6 | 0.95 | 20 | 1.05 |

Parâmetros de servidor (vLLM):
```
--enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser qwen3
```

Controle de thinking mode:
- Soft switches: `/think` ou `/no_think` no prompt do usuário
- Hard switch: `chat_template_kwargs: {"enable_thinking": false}`

---

## 4. Comportamento sem system prompt (`--bare`)

- O template ainda é aplicado pelo tokenizer — sem system prompt, o modelo opera com contexto mínimo
- Tool definitions são passadas via parâmetros da API, não via system prompt manual
- `--bare` remove Skills/MCPs que "afogam" modelos 30B — não afeta o mecanismo de tool-call em si

---

## 5. Thinking mode vs non-thinking mode para tool use

| Aspecto | Thinking (padrão) | Non-thinking |
|---|---|---|
| Campo extra | `reasoning_content` antes do tool call | Não existe |
| Qualidade | Melhor para queries complexas | Direto, menor overhead |
| Controle | `enable_thinking: true` (default) | `enable_thinking: false` |
| **CUIDADO** | SGLang/vLLM podem descartar `reasoning_content` — usar sem extrair thinking content | N/A |

**NÃO usar ReAct templates** (baseados em stopwords) com modelos de thinking — a seção `<think>` pode disparar stopwords incorretamente.

---

## 6. Comportamento via Ollama

- Tool use suportado: `<tool_call>` XML tags no template Ollama
- Modelo disponível: `qwen3:30b` (19GB), contexto 40K–256K dependendo da variante
- **Gotcha local-dev (CLAUDE.md):** via shim Ollama→Anthropic, `qwen3coder-local` emite tool-call como texto JSON puro em vez de bloco `tool_use` nativo Anthropic — inconsistente, não é bug de infra

---

## 7. Formato esperado pelo shim Anthropic (Ollama)

O shim converte:
- **OpenAI format** → **Anthropic format** (`tool_use` content block)
- Quando a conversão funciona, o Claude Code CLI recebe `{"type": "tool_use", "id": "...", "name": "...", "input": {...}}`
- **Quando falha** (inconsistência conhecida): o modelo emite JSON como texto puro, o shim não converte, Claude Code não invoca a ferramenta

Hipótese para o problema de Sprint 14 (qwen3.6 não invoca tools via Claude Code CLI):
O modelo em modo thinking emite tool calls dentro do bloco `<think>` ou com estrutura que o shim não reconhece como `tool_use`.

---

## 8. Compatibilidade API

Alibaba Cloud Model Studio é compatível com **OpenAI e Anthropic APIs** — o modelo oficial suporta ambos os formatos. A questão é se o shim local do Ollama implementa essa conversão corretamente.

---

## 9. Modelo no pipeline local-dev

| Tag | Parâmetros | VRAM | TPS |
|---|---|---|---|
| `qwen3.6:35b-a3b-q4_k_m` | 35B MoE (3.5B ativos) | ~18GB | ~36 tok/s |
| `qwen3.6:27b` (bloqueado, ver Watchlist#2) | 27B denso | full VRAM | ~25 tok/s (esperado) |
