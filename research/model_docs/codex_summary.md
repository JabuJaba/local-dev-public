# Codex (OpenAI) — Tool Use & Prompting Summary

Fonte: `<workspace>/codex-docs/data/clean/codex` (docs oficiais locais, lidos 2026-05-01)

---

## 1. O que é Codex no contexto do pipeline

OpenAI Codex é um **agente de coding** (não um modelo LLM acessível via API direta como Qwen/Gemma). Ele opera em loop autônomo: recebe um prompt de tarefa, chama o modelo interno (GPT-5.x), executa ações (file reads, edits, shell commands) e itera até completar.

No pipeline local-dev, Codex é roteado para tarefas `always_claude` ou `agent=codex` pelo fit-evaluator — ele recebe handoff.md e executa de forma autônoma.

---

## 2. Tool-call format

Codex não expõe tool-calls no formato OpenAI/Anthropic para o usuário. Internamente usa os seguintes tipos de ação (visíveis em `--json` output):

| Tipo de item | Descrição |
|---|---|
| `command_execution` | Shell commands (`bash -lc ...`) |
| `file_changes` | Edições de arquivo |
| `mcp_tool_calls` | Chamadas a servidores MCP |
| `web_searches` | Buscas na web |
| `agent_message` | Resposta final do agente |

Output via `codex exec --json` (JSONL stream):
```json
{"type": "item.started", "item": {"type": "command_execution", "command": "bash -lc ls"}}
{"type": "item.completed", "item": {"type": "agent_message", "text": "..."}}
{"type": "turn.completed", "usage": {"input_tokens": 24763, "output_tokens": 122}}
```

---

## 3. System prompt / instruções persistentes

Codex não usa `system` role como parâmetro de API. A equivalência é:

| Mecanismo | Escopo | Equivalente a |
|---|---|---|
| `AGENTS.md` (repo root) | Por repositório | System prompt persistente para o time |
| `~/.codex/AGENTS.md` | Global (usuário) | System prompt pessoal |
| **Skills** (`SKILL.md`) | Por skill invocada | Instruções especializadas carregadas sob demanda |
| **Memories** | Por projeto | Contexto acumulado de sessões anteriores |
| `--system-prompt` (CLI) | Por sessão | Override pontual |

Hierarquia: arquivos mais próximos do diretório de trabalho têm precedência.

---

## 4. Parâmetros recomendados

Codex não expõe parâmetros de geração (temperature, top_p) para o usuário — são controlados internamente pelo OpenAI.

Parâmetros relevantes de invocação:
- `--model gpt-5.5` (default recomendado; ou `gpt-5.4` como fallback)
- `--sandbox workspace-write` (para edições; default é read-only)
- `--sandbox danger-full-access` (apenas em ambiente isolado/CI)
- `--ephemeral` (não persiste arquivos de sessão)
- `--json` (output JSONL para pipelines)

---

## 5. Comportamento sem system prompt

Sem AGENTS.md, Codex opera com contexto mínimo: lê o repositório e age com base apenas no prompt de task. Qualidade cai em repos com convenções não-óbvias.

---

## 6. Invocação não-interativa (pipeline)

```bash
codex exec --sandbox workspace-write "implementar feature X, rodar testes, criar PR"
codex exec --json "analisar repo" | jq '.item.text'
```

Auth via `CODEX_API_KEY` (env var). Para CI, não usar `codex login` — usar API key diretamente.

---

## 7. Formato esperado pelo shim Anthropic

N/A — Codex usa a API OpenAI (Chat Completions / Responses API), não o shim Anthropic do Ollama. Roteamento no pipeline via handoff.md, não via shim.

---

## 8. Modelos disponíveis (2026-05)

| Modelo | Uso |
|---|---|
| `gpt-5.5` | Flagship (coding complexo, computer use) — via ChatGPT auth |
| `gpt-5.4` | Fallback robusto (inclui raciocínio profundo) |
| `gpt-5.4-mini` | Rápido/barato para tasks leves ou subagents |
| `gpt-5.3-codex-spark` | Research preview — iteração em tempo real (Pro subscribers) |
