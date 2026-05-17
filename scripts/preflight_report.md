# Preflight Anthropic-compat Ollama - Sprint 1.5 Phase 1

Executado: 2026-04-20 22:14:14 -03:00
BaseUrl: http://localhost:11434

| Modelo | Tags OK | HTTP | content | stop_reason | 1a resp (ms) | Erro |
|--------|---------|------|---------|-------------|--------------|------|
| qwen3coder-local | True | 200 | True | True | 15834 |  |
| gemma4:26b | True | 200 | True | True | 17563 |  |

## Raw snippets (primeiros 500 chars)

### qwen3coder-local

``````json
{"id":"msg_d58f15cb8860666a4ed6d81b","type":"message","role":"assistant","model":"qwen3coder-local","content":[{"type":"tool_use","id":"call_wmxxws8s","name":"get_weather","input":{"city":"Paris"}}],"stop_reason":"tool_use","usage":{"input_tokens":299,"output_tokens":22}}

``````

### gemma4:26b

``````json
{"id":"msg_309f90a9c37f0f60b249ce2e","type":"message","role":"assistant","model":"gemma4:26b","content":[{"type":"thinking","thinking":"The user is asking for the weather in Paris and explicitly requests to \"Use the tool.\"\nLooking at the available tools, `get_weather` is the correct tool to use.\nThe `get_weather` tool takes one argument: `city`.\nThe user provided the city name \"Paris\".\n\nTherefore, I should call `get_weather(city='Paris')`."},{"type":"tool_use","id":"call_etdf5skw","name
``````
