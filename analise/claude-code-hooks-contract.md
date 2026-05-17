# Claude Code Hooks Contract
# Source: https://code.claude.com/docs/en/hooks
# Generated: 2026-05-07 | Sprint 34 | local-dev

## Referencia rapida: o que cada evento pode e nao pode fazer

| Evento | Pode mutar | NAO pode mutar | Output JSON honrado | Anti-pattern tipico |
|---|---|---|---|---|
| PreToolUse | `input` fields do tool; decisao de bloquear ou aprovar | tool_result; resposta do assistente | `decision` (block/approve/modify), `reason`, `hookSpecificOutput.additionalContext` | Rejeitar tools genericos sem criterio preciso -- falso-negativo silencioso bloqueia fluxo valido |
| PostToolUse | Contexto adicional para o assistente na proxima chamada | `tool_result` visto pelo assistente no transcript (descartado silenciosamente se emitido) | `hookSpecificOutput.additionalContext`, `suppressOutput` | **rtk_trim Sprint 30**: emitir payload bruto `{tool_name, tool_result}` esperando trim do resultado -- envelope nao reconhecido pelo Claude Code, descartado; hook NO-OP estrutural |
| SessionStart | Contexto de sessao (learnings, gotchas, env state) | Historico de conversa ja existente; mensagens anteriores | `hookSpecificOutput.additionalContext`, `continue`, `suppressOutput` | Injetar contexto volumoso sem filtro de relevancia -- overhead fixo por sessao independente de necessidade |
| PreCompact | Instrucoes para guiar a compactacao | Trigger da compactacao (nao pode adiar ou cancelar) | `hookSpecificOutput.additionalContext` | Assumir que hook PreCompact preserva contexto especifico -- so orienta, sem garantia de retencao |
| Stop | Decisao de continuar respondendo (evitar parada prematura) | Ultima mensagem do assistente ja emitida | `continue` (false = nao parar), `hookSpecificOutput.additionalContext` | Rodar operacao I/O pesada ou bloqueante no Stop -- aumenta latencia de CADA resposta |
| PostToolUseFailure | Contexto adicional pos-erro para o assistente | Causa do erro; retry automatico | `hookSpecificOutput.additionalContext` | Silenciar o erro no hook e retornar codigo 0 -- mascara falha real, assistente nao sabe |

## Campos de envelope processados pelo Claude Code

```
hookSpecificOutput.additionalContext   -- string injetada como contexto antes do proximo turno
decision                               -- "block" | "approve" | "modify" (PreToolUse apenas)
reason                                 -- string exibida ao usuario quando decision=block
continue                               -- bool; false em Stop faz Claude continuar respondendo
suppressOutput                         -- bool; omite o output do hook do transcript
```

## Regra de ouro

Se o objetivo e **alterar o que o assistente ve como resultado de uma ferramenta**, use PreToolUse
para interceptar antes -- PostToolUse nao alcanca o transcript ja escrito.

## Caso motivador (Sprint 30 / ADR-015 Lever 3)

`rtk_trim.py` operava em PostToolUse emitindo um payload JSON com `tool_result` trimado.
O Claude Code processar apenas `hookSpecificOutput.additionalContext` -- o payload bruto foi
descartado. Os testes unitarios (`tests/test_rtk_trim.py`, 6/6 PASS) validavam apenas a
transformacao Python interna, nao o efeito no transcript. Lever 3 foi removido no Sprint 32.
Cross-ref: `analise/sprint32_phase3_rtktrim-removal_2026-05-07.md`, ADR-015 atualizacao 2026-05-07.
