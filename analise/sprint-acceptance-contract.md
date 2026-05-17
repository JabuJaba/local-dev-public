# Sprint Acceptance Contract
# Generated: 2026-05-07 | Sprint 34 | local-dev
# Motivacao: padrao "deploy-antes-de-validar-end-to-end" em 22 sprints (findings-2026-05-07-011700.md)
# Cross-ref: ADR-015 Lever 3 (rtk_trim) -- Sprint 30 motivou este contrato

## Regra

Qualquer sprint que mude routing, hook ou custo exige **dois niveis de acceptance** antes de
marcar `phase_completed` ou setar `lever_X_deployed: true` no checkpoint:

1. **Internal acceptance** -- testes unitarios / smoke / lint passam. Estado anterior mantido.
   Gate necessario mas nao suficiente.

2. **External acceptance** -- 1 medicao empirica nominal com numero antes/depois OU comparacao
   contra ground truth em sessao real. Sem esse numero, o `phase_completed` nao avanca.

A ausencia de External acceptance e o que permitiu rtk_trim ser declarado "operacional" no
Sprint 30 com 6/6 testes PASS -- e depois descoberto NO-OP estrutural.

## Templates por tipo

### Tipo A: Hook novo

```
Input:       sessao real com 5+ tool calls do tipo coberto pelo hook
Hipotese:    hook X vai reduzir tokens_cache_read em Y%
Metrica:     tokens_cache_read sessao com hook ON vs baseline OFF (mesma task)
Gate:        delta >= threshold declarado no sprint doc; se delta < threshold -> lever nao conta
```

Exemplo concreto: Sprint 30 deveria ter rodado 1 sessao <pipeline-project> com rtk_trim ON e medido
`cache_creation_input_tokens` + `cache_read_input_tokens` vs baseline Sprint 29.

### Tipo B: Routing change

```
Input:       1 task real do projeto-alvo (nao smoke test sintetico)
Hipotese:    rota X vai custar Y% menos / ser Z% mais rapida que rota anterior
Metrica:     custo USD ou tokens_in/out medido na task real; tempo de wall-clock se relevante
Gate:        custo/tempo dentro de 10% da hipotese, ou hipotese ajustada com evidencia
```

Exemplo concreto: Sprint 32 Phase 1 mediu model:inherit via Ollama -- retornou conteudo
correto, API key=ollama invalida descarta rota cloud. PASS binario com evidencia.

### Tipo C: Skill nova

```
Input:       1 invocacao real com projeto existente (nao hello-world isolado)
Hipotese:    skill X vai produzir output verificavel contra criterio Y
Metrica:     output observado vs criterio escrito (ex: "arquivo com N linhas", "N/N testes pass")
Gate:        criterio atendido quantitativamente; "parece funcionar" nao conta
```

## Termos proibidos em acceptance (sem numero ou evidencia anexada)

- "funciona corretamente" -- vago; qual funcao, medida como?
- "deployed" / "deployado" -- estado do artefato, nao validacao de efeito
- "operational" / "operacional" -- implica efeito sistemico sem prova-lo
- "PENDING_USER_SESSIONS" -- gate adiado infinitamente; se o gate nao pode rodar agora, a fase nao esta completa
- "testes passam" sozinho como external acceptance -- testes internos nao substituem medicao real

## Escopo de aplicacao

Esta regra se aplica quando o sprint doc contem qualquer um destes:
- `lever_N_deployed`, `hook_deployed`, `routing_change`
- Phase que muda `settings.json`, `ANTHROPIC_BASE_URL`, `model:`, ou Modelfile
- Phase que declara reducao de custo ou melhoria de latencia como entregavel

Sprints puramente de documentacao (como este Sprint 34) precisam apenas de Internal acceptance
(arquivo existe, linha count dentro do limite, criterios textuais atendidos).

## Cross-references

- ADR-015 (2026-05-06): encerramento fase audit; Lever 3 rtk_trim tentado + falhou
- ADR-015 atualizacao 2026-05-07: Lever 3 removido Sprint 32; gate real de ROI nunca rodou
- `analise/claude-code-hooks-contract.md`: o que PostToolUse pode/nao pode fazer
- `findings-2026-05-07-011700.md` C1: evidencia primaria do NO-OP estrutural
