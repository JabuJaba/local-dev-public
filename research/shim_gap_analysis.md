# Shim Gap Analysis — Sprint 15
Data: 2026-05-02

## Pergunta
Por que qwen3.6 não invoca tools via Claude Code CLI (`claude --bare --model qwen3.6:35b-a3b-q4_k_m`), mesmo que o benchmark interno mostre 72.5% coding accuracy?

---

## O que foi testado

### Camada 1: Ollama nativo (`/api/chat`)

| Formato de tools | Resultado |
|---|---|
| `input_schema` (Anthropic) | FALHA — modelo hallucina `code_interpreter` (não reconhece o formato) |
| `parameters` (OpenAI nativo) | PASS — modelo emite `tool_calls[Read]` com argumento correto |

**Conclusão:** `/api/chat` requer formato OpenAI nativo. O shim Anthropic do Ollama não traduz `input_schema` para `/api/chat`.

### Camada 2: Shim Anthropic (`/v1/messages`)

| Teste | Resultado |
|---|---|
| Tool call com `input_schema` | PASS — retorna `[{type:thinking}, {type:tool_use, name:Read}]`, `stop_reason:tool_use` |
| Thinking desabilitado (`thinking:{type:disabled}`) | PARCIAL — bloco `thinking` ainda presente (len=453) |
| `/no_think` no prompt | PARCIAL — bloco `thinking` ainda presente (len=953) |
| `options:{think:false}` no `/api/chat` | PARCIAL — `thinking_len=719`, não elimina o bloco |

**Conclusão:** O endpoint `/v1/messages` funciona corretamente como Claude Code usa. O thinking mode NÃO pode ser desabilitado via parâmetros de API — está embutido no template do modelo.

---

## Onde a cadeia quebra

```
Claude Code CLI
  → ANTHROPIC_BASE_URL=http://localhost:11434
  → POST /v1/messages (com tools em input_schema, Anthropic format)
  → Ollama shim (converte OK)
  → qwen3.6 (emite tool_calls em OpenAI format)
  → Shim (converte tool_calls → tool_use block)
  → Claude Code recebe: {"content":[{"type":"thinking","thinking":"..."},{"type":"tool_use",...}],"stop_reason":"tool_use"}
  → ??? PONTO DE FALHA SUSPEITO: thinking block interfere no parser?
```

O shim funciona. A resposta chega com o formato correto (`stop_reason: tool_use`, `tool_use` content block). A hipótese mais provável é que o `thinking` content block (nunca desabilitável via API) interfere com o processamento do Claude Code CLI.

---

## Hipóteses rankeadas

### H1 (ALTA probabilidade): `thinking` block interfere no parser do Claude Code
O Claude Code é projetado para modelos Anthropic. Quando recebe um `thinking` block, pode não processar corretamente o `tool_use` subsequente. O behavior observado ("I see you typed Bash") sugere que o CLI exibe o conteúdo do thinking block como texto, ignorando o `tool_use`.

**Evidência a favor:** Ambos qwen3.6 e gemma4 emitem `thinking` blocks (confirma que é sistêmico, não específico do modelo). O thinking não pode ser desabilitado.

**Testabilidade:** Verificar no código fonte do Claude Code se ele processa `thinking` blocks de modelos não-Anthropic.

### H2 (MÉDIA probabilidade): Claude Code não envia tool definitions na request
O `--bare` flag pode strip mais do que Skills/MCPs — pode também não enviar tool definitions para modelos locais (detecção por model name).

**Evidência a favor:** Sprint 14 mostrou que sem `--bare` o modelo descreve o projeto de memória mas "não tem acesso ao D:/" — sugere que sem tools, o modelo responde do que sabe.

**Testabilidade:** Capturar o payload exato que Claude Code envia com um proxy interceptor.

### H3 (BAIXA probabilidade): Formato de tool_result na segunda turn
Após Claude Code executar uma tool, ele envia o resultado como `tool_result`. qwen3.6 pode não reconhecer o formato do `tool_result` e responder de forma incorreta.

**Evidência contra:** O problema ocorre antes da primeira tool execution ("I see you typed Bash" antes de qualquer execução).

---

## Limitação desta análise

Não foi possível capturar o payload exato que o Claude Code CLI envia para a Ollama (logs do Ollama não mostram request bodies). Para confirmar H2, um proxy interceptor é necessário:

```python
# proxy_logger.py — intercepta e loga requests do Claude Code
# Usar: ANTHROPIC_BASE_URL=http://localhost:11436 claude --bare ...
# Proxy encaminha para localhost:11434
```

---

## Conclusão operacional

O shim Ollama→Anthropic funciona corretamente para ambos os modelos. O problema está na integração com o Claude Code CLI, não na camada de API. As duas hipóteses mais prováveis (thinking block interference, ou tools não enviados) requerem:
1. Inspeção do código fonte do Claude Code
2. Proxy interceptor para capturar payloads reais

Enquanto isso, o caminho mais seguro é **Opção C** (wrapper direto via API), conforme fase 5.
