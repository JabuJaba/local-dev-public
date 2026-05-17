# Structural Contracts (Hooks + Acceptance)

## Objetivo
Documentar dois contratos que travam o padrão "deploy-antes-de-validar-end-to-end" identificado no diagnóstico 2026-05-07. Sprint 34 não muda código de produção — só cria a folha de referência que próximas sprints leem antes de propor hook ou marcar `phase_completed`.

## Phases

### Phase 1: `claude-code-hooks-contract.md`
**Entregável**: `analise/claude-code-hooks-contract.md` mapeando o que cada evento de hook PODE / NÃO PODE fazer.

Conteúdo mínimo:
- Tabela com 1 linha por evento (PreToolUse, PostToolUse, SessionStart, PreCompact, Stop, PostToolUseFailure)
- Coluna "Pode mutar": o que o hook consegue alterar (input do tool, contexto adicional, decisão de bloqueio)
- Coluna "NÃO pode mutar": expressamente o que o evento não permite (ex: PostToolUse não muta tool_result)
- Coluna "Output JSON honrado": campos do envelope que Claude Code processa (`hookSpecificOutput.additionalContext`, `decision`, `continue`, etc.)
- Coluna "Anti-pattern": o erro típico (ex: emitir payload bruto via PostToolUse esperando trim — o caso rtk_trim)
- Link no header: `https://code.claude.com/docs/en/hooks` como fonte

**Acceptance**:
- [ ] Arquivo existe em `analise/claude-code-hooks-contract.md`
- [ ] 6 linhas (1 por evento) com 4 colunas preenchidas
- [ ] Caso `rtk_trim` Sprint 30 listado como exemplo de anti-pattern (PostToolUse linha)
- [ ] Header com data + URL fonte oficial
- [ ] `wc -l` ≤ 80 linhas (folha de referência, não tutorial)

**Anti-pattern**: copiar prosa dos docs em vez de tabela compacta. O objetivo é checagem rápida antes de propor hook, não estudo.

---

### Phase 2: `sprint-acceptance-contract.md`
**Entregável**: `analise/sprint-acceptance-contract.md` documentando a regra "internal + external acceptance" pra toda sprint que muda routing/hook/economia.

Conteúdo mínimo:
- Definição: sprint que muda routing/hook/custo precisa de **2 níveis de acceptance**:
  - **Internal**: unit tests / smoke / lint passam (estado anterior, mantido)
  - **External**: 1 medição empírica nominal com número antes/depois OU comparação com ground truth
- Regra explícita: sem external acceptance, `phase_completed` não avança. `lever_X_deployed=true` no checkpoint exige a medição.
- 3 exemplos com template:
  - "Hook novo": smoke 99/99 PASS + 1 sessão real comparando métrica afetada antes/depois
  - "Routing change": testes determinísticos PASS + 1 task real do projeto-alvo medindo custo/tempo
  - "Skill nova": testes (se houver) + 1 invocação real com output verificável contra critério escrito
- Lista de termos proibidos em acceptance: "funciona corretamente", "deployed", "operational" sem número anexado
- Cross-ref: ADR-015 lever 3 (rtk_trim) como o caso que motivou esse contrato

**Acceptance**:
- [ ] Arquivo em `analise/sprint-acceptance-contract.md`
- [ ] 3 exemplos com template (input, hipótese, métrica, gate)
- [ ] Lista de ≥4 termos proibidos
- [ ] Referência a ADR-015 + Sprint 30 como motivação documental
- [ ] `wc -l` ≤ 100 linhas

**Anti-pattern**: contrato genérico tipo "meça tudo". O contrato precisa ser **mecânico** o bastante pra que próxima sprint saiba se passou ou não — sem ambiguidade.

---

## Critérios de Aceite da Sprint
- [ ] 2 documentos em `analise/`
- [ ] Caso rtk_trim citado em ambos (hook contract: anti-pattern; acceptance contract: motivação)
- [ ] CLAUDE.md global (ou local-dev) ganha 2 linhas referenciando os contratos
- [ ] `.checkpoint.json` atualizado: sprint=34, phase_completed=2

## Dependências
- Diagnóstico `findings-2026-05-07-011700.md` lido (já existe)
- Phase 0 do plano executado (Sprint 32) — não obrigatório, mas Sprint 32 Phase 3 já incorpora o lever 3 morto que esse contrato formaliza

## Itens Pendentes do Sprint Anterior
- N/A

## Notas
- **Tempo estimado**: Phase 1 ~30min, Phase 2 ~30min. Total 1h.
- **Por que essa sprint vem antes do refactor de skills (Sprint 36+)**: sem o contrato escrito, refazer 31a-d como Sprint 36+ reproduz o mesmo padrão. Contrato é input pra `/sprint-generator` (notas em CLAUDE.md ajudam o gerador a propor acceptance external por padrão).
- **Por que sprint separada e não inline em outra**: o conteúdo é uma folha de referência permanente, lida por sessões futuras. Misturar com sprint de implementação polui o checkpoint e dilui a regra.
- **Encoding**: arquivos UTF-8 sem BOM. Tabelas markdown ASCII puro (gotcha em-dash do CLAUDE.md global aplica).

_Gerado por /sprint-generator em 2026-05-07_
