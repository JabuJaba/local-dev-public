# Plano: Pipeline Local — Estado Real e Proximos Passos
*2026-05-07 — pos revisao das 22 sprints*

---

## 1. Inventario honesto — o que existe hoje

### 1.1 Camada de memoria (dois sistemas separados, nao integrados)

**Sistema A — learnings.db (nosso custom, global)**

| Hook | Evento | Acao |
|------|--------|------|
| `auto_learn_from_claude_md.py` | PostToolUse Edit/Write em CLAUDE.md | Categoriza linhas → `pending_learnings.jsonl` |
| `session_learnings.py` | Stop | Drena `pending_learnings.jsonl` → `learnings.db` |
| `session_start_inject.py` | SessionStart | Injeta ate 25 learnings do projeto em contexto |

**Gaps identificados**:
- Aprende SOMENTE quando CLAUDE.md e editado — gotchas descobertos em sessao que nao chegam ao CLAUDE.md nunca entram no DB
- Recall e passivo: injecao apenas no session-start (max 25 items), sem busca mid-sessao antes de bloqueios
- Sem busca semantica — match e por projeto, nao por relevancia da query atual

**Sistema B — claude-mem plugin (instalado em <game-bot>, NAO no <pipeline-project>)**

- PreToolUse:Read injeta observacoes relevantes (50 hits na sessao <game-bot> relada)
- SQLite proprio, separado de `learnings.db` — integracao entre A e B: ZERO
- babysit = plugin GitHub PR review (errado para memoria — descartado)
- Gap real (per relato <game-bot>): `mem-search` nao e chamado proativamente antes de bloqueios; so session-start e automatico

### 1.2 Benchmarks realizados — o que foi e o que nao foi testado

**Sprint 1.5 (2026-04-21) — o que foi feito**:
- Sandbox: Subtitle-Forge (51k arquivos), 10 tasks genericas
- Interface: Claude Code via Ollama (`--bare --allowedTools`)
- Modelos: qwen3coder-local, gemma4:26b, qwen3.6:35b

**Resultados Sprint 1.5**:
- qwen3coder: XML bleed (formato OpenAI legado → alucinacao silenciosa). DESCARTADO rota interativa via Claude Code.
- gemma4: 90% outcome, bias Bash, trunca outputs longos (>600 tokens)
- qwen3.6: PRIMARIO — 90% outcome, melhor tool match (6/10)

**O que NUNCA foi testado**:
- Task <pipeline-project> real (extrator PDF com gotchas de layout complexo, num_ctx, encoding)
- CLAUDE.md com regras reais ativas durante execucao
- aider como interface (parser proprio — bypassa XML bleed do qwen3coder; nunca validado)
- Multiplos turnos com context acumulado (mega-sessao simulada)
- Gemma4 em task real vs qwen3.6 na mesma task (comparacao controlada)

### 1.3 Aider — status real

- Benchmarkeado: throughput (15-17 tok/s com qwen3coder via `/v1/chat/completions`)
- Testado em task real: NUNCA
- Gap: aider tem parser proprio → pode funcionar com qwen3coder sem XML bleed. Hipotese nunca validada.

### 1.4 <pipeline-project> — estrutura atual

- Renomeado de <pipeline-project>_Extractor → `<workspace>/<pipeline-project>/`
- Componentes: extractor (PDF→SQLite), scraper (disclosure-system), dashboard
- Sprint 8 routing (37.3% economy) foi em `<pipeline-project>_rollback_test`, NAO no live pipeline
- Nenhum protocolo de segurança definido para execucao com modelo local

---

## 2. Revisao das 22 sprints — veredito por fase

### Fase A — Overhead Reduction (6 sprints planejadas)

| Item | Status | Evidencia |
|------|--------|-----------|
| Hook cleanup | MORTO | Teto empirico -4.8% (Sprint 25) vs 20% alvo |
| Prompt engineering | MORTO | ≤2% ROI (Sprint 27) |
| megasess_advisor | ENTREGUE | Lever 1 (Sprint 29) |
| CLAUDE.md fix megasessions | ENTREGUE | Lever 2 (Sprint 29) |
| rtk_trim | ENTREGUE | Lever 3 (Sprint 30) |
| graph/repomix compressao | MORTO | Overhead nao era o driver |

**Saldo Fase A**: 3 entregues, 3 mortos.

### Fase B — Specialists em Sonnet (4 sprints planejadas): MORTO

Premissa: custo vinha de multiplicacao de tokens por specialist.
Evidencia real: custo vem de mega-sessoes power-law (top 3 = 65% do spend semanal). Specialists nao sao o driver.
**4 sprints mortas.**

### Fase C — Bench Local (4 sprints): EM ABERTO — nunca executado corretamente

| Item | Status | Gap |
|------|--------|-----|
| Benchmark qwen3.6 + gemma4 em task real <pipeline-project> | PENDENTE | So sandbox feito (Subtitle-Forge) |
| aider em task real | PENDENTE | So throughput medido, nunca task completa |
| Memoria procedural (gotchas sobrevivem entre sessoes) | PARCIAL | <game-bot> reativo; sem busca mid-sessao |
| Protocolo seguranca <pipeline-project> | PENDENTE | Sem audit, sem worktree protocol |

**Saldo Fase C**: 0 entregues. Este e o gargalo real.

### Fase D — Migrar specialists para local (3 sprints): BLOQUEADA

Gate hard: Fase C completa. fit-evaluator/sprint-generator/merge-review nao migram antes disso.

### Fase E — Nested loops + circuit breakers (3 sprints): MORTO

Over-engineering para problema que nao existe no escopo atual.

### Fase F — Validacao (2 sprints): ABSORVIDA

Cada Track abaixo carrega seu proprio acceptance criterio. Sem fase separada.

**Resumo 22 sprints**: 3 entregues (A), 7 mortos (B+E+A-parcial), 4 em aberto (C), 3 bloqueados (D), 2 absorvidos (F) = 3 entregues reais de 22 planejadas.

---

## 3. Plano de ataque — 4 tracks (esta e proxima semana)

### Track 1: Memoria proativa — fechar o gap mid-sessao
**Custo**: zero Claude tokens — Python puro sobre SQLite local
**Prazo**: esta semana

**Estado atual**: aprendizado so acontece via CLAUDE.md (auto_learn hook). Recall so no session-start (25 items, por projeto).

**Passos**:
1. Criar hook `PreToolUse` em `Grep|Bash` que faz query em `learnings.db` com keywords do argumento antes da busca. Se hit relevante → injeta como system-reminder.
2. Criar mecanismo de "learn explícito mid-sessao": comando ou trigger que grava gotcha descoberto em sessao para `pending_learnings.jsonl` sem precisar editar CLAUDE.md
3. Testar em 1 sessao <game-bot> ou local-dev: ≥1 bloqueio evitado por recall proativo = PASS

**Rollback**: remover entry PreToolUse do settings.json. 30 segundos.

**Sobre claude-mem em <game-bot>**: sistema separado. Nao integrar agora. Avaliar apos Track 1 provar ROI.

---

### Track 2: Benchmark real — aider em task <pipeline-project> autentica
**Custo**: zero Claude tokens — modelos locais
**Prazo**: esta semana, paralelo ao Track 1

**Diferencial vs Sprint 1.5**:
- Task: extrator <pipeline-project> real (ex: TICKER_X + BCFF11B, periodo fixo) — nao sandbox
- Interface: aider (nao Claude Code) → testa se XML bleed do qwen3coder desaparece com parser proprio
- CLAUDE.md real ativo: num_ctx, encoding, layout de PDF gotchas reais
- Medicao: output funcional (dados corretos no SQLite) + wall-clock + numero de turnos

**Protocolo**:
1. Escolher task da inventario Sprint 27 (sessao cara conhecida)
2. Aider + qwen3.6 (primario per Sprint 1.5)
3. Aider + gemma4 (mesma task, sequencial)
4. Comparar: output correto? onde falhou? qual modo de falha?

**Gate**: extrator roda sem erro, dados validos no SQLite = PASS
**Se falhar**: documentar modo de falha (alucinacao? loop? truncamento? encoding?) → esse dado decide se Fase D e viavel

---

### Track 3: Seguranca <pipeline-project> — protocolo antes de qualquer escrita
**Custo**: zero Claude tokens
**Prazo**: proxima semana, gated em Track 2 PASS

**Protocolo obrigatorio**:
1. `git worktree add ../<pipeline-project>-local-test` — branch isolada antes de qualquer escrita
2. Aider em modo read-only primeiro (analisa, nao edita)
3. Zero commits automaticos: diff review obrigatorio antes de apply
4. Task inicial: nao-destrutiva (analise de cobertura, nao extracao nova)
5. Gate: modelo completa task sem corromper dados existentes no worktree

**Rollback**: `git worktree remove` descarta tudo. Zero impacto no pipeline prod.

---

### Track 4: Hooks proativos globais — expansao
**Prazo**: gated em Track 1 + Track 2 validarem

Se Track 1 prova recall proativo evita erros reais → expandir para <pipeline-project>.
Se nao → aceitar que pipeline 100% local requer disciplina humana no loop, nao automacao.

---

## 4. O que NAO fazer agora

| Item | Motivo |
|------|--------|
| RAG (Sprint 25.6 M1/M2) | Nao empilhar sobre memoria nao validada |
| Migrar skills (fit-evaluator, sprint-generator, merge-review) | Bloqueado ate Tracks 1+2 validarem |
| Sprint 31 doc | Gated em re-medicao 2026-06-03 |
| claude-mem em <pipeline-project> | Esperar <game-bot> provar ROI real com recall proativo |
| babysit | Plugin errado (GitHub PRs), descartado |

---

## 5. Gates e decisao por data

| Gate | Criterio | Prazo | Decisao se FAIL |
|------|----------|-------|-----------------|
| Track 1 | ≥1 bloqueio evitado por recall proativo em sessao real | 2026-05-14 | Aceitar memoria passiva como limitacao estrutural |
| Track 2 | aider completa task <pipeline-project> sem erro, dados corretos | 2026-05-14 | Diagnosticar modo de falha; reavaliar Fase D |
| Track 3 | Sem corrupcao de dados em worktree isolado | 2026-05-21 | Nao usar modelo local em <pipeline-project> prod |
| Re-medicao levers | Queda ≥30% vs baseline semanal | 2026-06-03 | Gate Sprint 31 |

---

## 6. Proxima acao concreta

**Track 1 (hoje)**: Escrever o hook PreToolUse de busca mid-sessao.
- Input: argumento do Grep/Bash como query
- Output: system-reminder com learnings relevantes (se score > threshold)
- Arquivo: `~/.claude/hooks/mid_session_recall.py`

**Track 2 (hoje, paralelo)**: Definir a task <pipeline-project> alvo e preparar o ambiente aider.
- Confirmar que aider esta instalado: `aider --version`
- Selecionar fund pair da inventario Sprint 27
- Rodar aider + qwen3.6 na task

Ambos podem comecar em terminais separados agora — custo zero.

---

## 7. Track 5: Maestro — o pipeline completo (gated em Track 2)

**Status**: 5 agentes desenhados em `<workspace>/insights/ideias\` (maestro, project-organizer, task-planner, executor, logger). Nenhum implementado.

**Por que importa**: O Maestro com `model: inherit` nos specialists E a sessao Claude Code apontada para Ollama = pipeline inteiro rodando local — substitui fit-evaluator, sprint-generator-unified, universal-review-merge sem custo Claude API.

**Hipotese nao testada**: subagentes spawneados pelo Claude Code respeitam `model: inherit` quando o parent usa Ollama? Se sim, toda a orquestracao roda local. Se nao, specialists voltam para Sonnet/Haiku = custo permanece.

**Gate de entrada**: Track 2 PASS (modelo local completa task <pipeline-project> real). Se falhar la, falha aqui tambem.

**Quando atacar**: apos Track 2 + Track 3 validarem (estimativa: proxima semana).

**Experimento de validacao**:
1. Sessao Claude Code apontada para `qwen3.6` via Ollama
2. Invocar Maestro com task simples (ex: planeja 1 task de adicao de campo no extrator)
3. Observar: specialists sao spawneados com qwen3.6 ou retornam para Claude API?
4. Medir: custo = 0 tokens Claude se inherit funcionar corretamente
