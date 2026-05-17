# Sub-Agents Architectural Probe (Linchpin)

## Objetivo

Responder uma pergunta arquitetural que define a forma de **todas as sprints subsequentes**: **um planner local (qwen3.6-64k) consegue despachar sub-agents (via Task tool no shim Anthropic-Ollama) para executar phases independentes — tornando a pré-decomposição manual de sprints desnecessária?**

Se sim → sprints viram "1 goal + N sub-agents auto-decompostos pelo planner". Contexto fresh por sub-agent, scope-fence implícito no boundary, batch-gate de graça.
Se não → mantemos pré-decomposição manual e investimos na Sprint 48 (sprint doc auto-executável + batch-gate explícito).

**Resultado desta sprint condiciona a forma de Sprints 47, 48, 55-58 do roadmap.** Não escrever esses arquivos até esta sprint fechar.

## Phases

### Phase 1: Setup do probe e baseline de exposição do Task tool

**Entregável**: Confirmar empiricamente se o flag `--allowedTools=Task` é aceito pelo Claude Code apontando para `qwen3.6-64k` via shim Ollama. Ver se o modelo recebe a Task tool no system prompt.

**Acceptance**:
- Comando `qwen-cl --allowedTools=Read,Edit,Write,Bash,Glob,Grep,Task --version` executa sem erro
- Prompt minimal `"List your available tools"` retorna lista que **inclui** `Task`. Capturar resposta literal em `.eval/sprint39_phase1.txt`
- Se `Task` não aparecer → documentar e ir direto pra Phase 5 (decisão "sub-agents inviável via shim")
- 1 entrada em `.eval/sprint39.jsonl` registrando exposure result

### Phase 2: Dispatch unitário — sub-agent simples

**Entregável**: Planner despacha **um** sub-agent com escopo trivial (Read+Grep apenas), recebe resultado estruturado de volta.

**Acceptance**:
- Prompt: `"Use Task tool, subagent_type=general-purpose, prompt='Read <workspace>/<pipeline-project>/sprints/sprint_6.36.md and report Phase 1 deliverable in <=50 words'"`
- Sub-agent dispatch acontece (tool call visível no log)
- Sub-agent retorna resposta coerente (não consultive menu, não loop)
- Planner usa o resultado do sub-agent na sua resposta final
- Tempo wall-clock < 5 min total
- Capturar transcript em `.eval/sprint39_phase2.txt`

### Phase 3: Dispatch multi-phase — sub-agents executam phases REAIS sem pré-decomposição manual

**Entregável**: Validar a hipótese central. Dar ao planner **só o goal** (não as phases), deixar ele decompor e despachar sub-agents.

**Acceptance**:
- Cenário: replicar Phase 3 da 6.36 (regenerar `data.js` + Panorama HTML). Prompt ao planner: `"Goal: regenerar front-end/data.js e front-end/'Panorama <pipeline-project>s standalone.html' a partir do market_data.parquet atualizado. Decomponha em sub-tasks, despache sub-agents via Task para cada uma, valide o resultado, reporte. Você NÃO faz Edit/Write/Bash diretamente — só dispatch via Task."`
- Planner decompõe em ≥2 sub-tasks reais (não meramente conversacionais)
- Sub-agents executam (cada um com seu contexto)
- Resultado final: `data.js` e `standalone.html` realmente regenerados (verificar via `Get-Item ... | Select Length`)
- Tempo wall-clock < 30 min; planner ctx observado < 32k
- Capturar tudo em `.eval/sprint39_phase3.txt`
- **Critério qualitativo (o ponto desta sprint)**: o planner conseguiu decompor sozinho? Quantas sub-tasks? Houve scope-creep dele? Houve loop? Reportar análise em 200 palavras

### Phase 4: Comparação quantitativa vs Sprint 38 monolítico

**Entregável**: Tabela comparativa entre execução Sprint 38 Phase 1+monolithic-V1 (já registradas no `.eval/sprint38.jsonl`) e Phase 3 desta sprint (sub-agents).

**Acceptance**:
- Métricas comparadas: wall-clock total, tokens-in cumulative, max ctx observado, tools usados, files-touched, scope-creep (sim/não), loop (sim/não), correção do output (sim/não)
- Tabela em `analise/sprint39_subagents_vs_monolithic.md`
- Decisão registrada: sub-agents reduz ≥2 das 4 métricas problemáticas da Sprint 38 (ctx-saturação, loop, scope-creep, time)?

### Phase 5: ADR e propagação às sprints subsequentes

**Entregável**: ADR-016 declarando a arquitetura de sprint vencedora + atualização do roadmap nesta seção da Sprint 39.

**Acceptance**:
- `ADR.md` ganha entrada ADR-016 com: contexto (findings Sprint 38 + 39), decisão (planner-dispatch vs pré-decomposição), consequências, sprints afetadas
- Roadmap abaixo (Sprints 40+) revisado: marcar quais mudam de forma dependendo do veredito
- Se sub-agents viável → S47 (multi-sprint skill) muda design; S48 (sprint doc executável) pode virar opcional; sprint doc template muda
- Se sub-agents inviável → S48 vira crítica; S47 fica baseada em pré-decomposição manual
- `.checkpoint.json` atualizado com `sprint:"39", phase_completed:"5"` + decisão

## Critérios de Aceite da Sprint

- [ ] Task tool exposure verificado empiricamente (não inferido) — Phase 1
- [ ] Sub-agent unitário despachado e respondido — Phase 2
- [ ] Sub-agents executaram phases reais sem pré-decomposição manual ou falharam comprovadamente — Phase 3
- [ ] Comparação numérica vs Sprint 38 monolítico documentada — Phase 4
- [ ] ADR-016 escrito + roadmap atualizado conforme veredito — Phase 5
- [ ] ≥4 entradas em `.eval/sprint39.jsonl` (uma por phase)
- [ ] **Nenhuma decisão arquitetural sobre sub-agents tomada por inferência — só por evidência empírica desta sprint**

## Dependências

- Sprint 38 concluída (qwen-cl reconfigurado pra qwen3.6-64k default, 7 entradas eval, finding A confirmado)
- `<workspace>/<pipeline-project>/` com Phase 2 da 6.36 commitada (`044055a`) — usado como base estável da Phase 3
- Ollama com qwen3.6-64k:latest carregável
- Backup `extractor/data/output/market_data.pre-sprint636.parquet` preservado (para reset de Phase 3 se necessário)

## Itens Pendentes do Sprint Anterior

- Sprint 38 fechamento formal — após Sprint 39 Phase 5, escrever `handoffs/handoff_sprint38.md` com 7 entradas eval e finding A; pode ir junto com Phase 5 ou virar Phase 6 desta sprint se escopo permitir
- Parquet `market_data.parquet` revertido ao baseline pré-experimento — não bloqueia nada

## Princípios operativos desta sprint (anti-erros Sprint 38)

- **Usuário define probes/tarefas reais**. Eu (Claude supervisor) não invento "treat TICKER7 as cetipado". Quando aparecer decisão fora do sprint doc, parar e perguntar
- **Logs registrados pelo usuário ficam em `.eval/sprint39.jsonl`**. Eu reviso, ele commita
- **Cap 30min wall-clock por phase delegada a modelo local**. Acima disso = abort + entrada de eval com "exceeded budget"
- **Nenhum sprint doc subsequente é escrito antes de Phase 5 desta sprint**

---

# Veredito Sprint 39 (2026-05-17, fechada)

**Decisão: sub-agents via Task tool são TECNICAMENTE VIÁVEIS mas COMPORTAMENTALMENTE NÃO-UTILIZÁVEIS em qwen3.6-64k.**

- Phase 1: Task tool exposto apenas sem `--bare` (system prompt 69k+ tokens; --disable-slash-commands piora pra 177k)
- Phase 1 Test E: dispatch unitário funcionou end-to-end (Agent tool_use → sub-agent → response)
- Phase 3: planner em task real (regen data.js + HTML) executou direto via Bash/PowerShell, **ZERO Task dispatches**, ignorou instrução textual "só dispatch via Task". Output correto (19 funds, PL multi-bilionario) mas arquitetura monolítica.
- Phase 4: ganho de Sprint 39 vs Sprint 38 V1 veio de **escopo menor** (2 arquivos vs 4 phases), não de sub-agents.

**Pré-decomposição manual permanece como pattern arquitetural do local-dev.** Detalhes em **ADR-018**.

---

# Roadmap Sprints 40+ (revisado pós-veredito S39)

Lista organizada por dependência. Cada sprint = 3-5 phases focadas, escopo único, **não escrita ainda**.
Após Sprint 39 Phase 5, geramos próxima sprint via `/sprint-generator` consumindo este roadmap.

**Detalhamento completo (phases, acceptance quantitativo, dependências, notas) em `sprints/roadmap_sprints_41_62.md`** — companion file (renumerado pós-S39: S40 standalone, demais shift). Stubs abaixo são overview histórico; consulte o companion atualizado antes de gerar qualquer sprint via /sprint-generator.

## Tier 1 — Research/sanity (sem dependências; podem rodar em paralelo)

- **S40 [sanity] Coder rankings refresh mai/2026** — qwen3-coder family, deepseek-coder, codestral, glm-coder, GLM Air, novos releases. Phases: 1 família por phase + síntese matriz. Substrato pra S50-S54.
- **S41 [sanity] AGENTS.md convention status** — padrão emergente Aider/agentic-tools? formato? adoção? exemplos reais? Phases: pesquisa Aider docs, comunidade, repos referência, decisão de formato pra nós. Substrato pra S55.
- **S42 [sanity] Tool-use models no Ollama** — Hermes (Nous Research), outros tool-use-tuned (Mistral Small 3.1, Llama 4 quando disponível). Quem realmente funciona via shim Anthropic? Substrato pra S57.
- **S43 [sanity] OpenClaw status atual** — está vivo? que problema resolveria pro pipeline? overlap com Aider? Substrato pra S56.
- **S44 [sanity] TurboQuant PR#21089 status + outras KV cache opts** — mergeou? alternativas (HipCache, FlashKV, etc.)? Substrato pra S59.
- **S45 [probe] Context ceiling qwen3.6** — Modelfile com num_ctx 128k e 262k. Probe truncamento via prompt-eval-count. Achar ceiling útil vs degradação de qualidade.
- **S46 [infra] Skill cost analysis quando local** — quais skills Claude Code somem? quanto contexto Claude Code injeta default vs `--bare`? alternativas (CLAUDE.md inline, snippets reutilizáveis, AGENTS.md)?

## Tier 2 — Infra/protocolo (depende S39) — **FORMA FIXADA pós-veredito S39**

- **S47 [skill] Multi-sprint skill** — **forma: skill gera N sprints pré-decompostas com cap 5 phases cada**. NÃO assume planner-dispatch (ADR-018).
- **S48 [protocolo] Sprint doc auto-executável** — **CRÍTICA** (era opcional). Scope-fence obrigatório + batch-gate per-phase + checksum gate pra gitignored. É o substituto arquitetural pro caminho sub-agent que foi descartado.
- **S49 [protocolo] Skills inline alternativas** — depende S46. Se skills do CC somem, mover essenciais (project-plan, sprint-generator, etc.) pra formato consumível por modelo local (CLAUDE.md? sub-files?).

## Tier 3 — Modelos (depende S40 + S45)

- **S50 [modelo] Variantes gemma** — gemma4:26b atual (estável), explorar gemma4 distill/instruction-tuned, gemma 2/3 se ainda viável. Phases por variante.
- **S51 [modelo] Top-3 MoEs novos do S40** — você (Tony) escolhe 3 do ranking; eu monto Modelfile + alias + probe surgical-edit + Bash-heavy + handoff-quality.
- **S52 [modelo] 1 modelo denso com offload (avaliar perda de tempo ou não)** — você decide qual; provavelmente classe 70B com offload CPU+GPU. Métrica: tok/s real vs uso prático.
- **S53 [modelo] Slot "100% VRAM, velocidade máxima"** — qual modelo cabe inteiramente em 16GB com latência mínima? qwen3.5:9b é candidato base; comparar com alternativas do S40.
- **S54 [modelo] qwen3-coder-64k** — Modelfile analog ao qwen3.6-64k; probe vs qwen3.6-64k em surgical-edit + Bash. Se ganhar, vira default p/ tasks codifying.

## Tier 4 — Ferramentas (depende S39 + S41 + S42 + S43 + S47) — **assumem pré-decomposição (ADR-018)**

- **S55 [tool] Aider + qwen3-coder + AGENTS.md** — depende S41 ter spec de AGENTS.md. Aider executa phases individuais pré-decompostas, não goals abertos.
- **S56 [tool] OpenClaw integração** — depende S43 ter veredito de viabilidade. Idem: execução de phases.
- **S57 [tool] Hermes/Nous tool-use** — depende S42 ter modelo confirmado. Probe: modelo tool-use-tuned segue dispatch-only melhor que qwen3.6? Se sim, reabre questão S47.
- **S58 [tool] Prompt-via-file pattern** — `qwen-cl -p $(Get-Content prompt.md)`. Mecânica de delivery, ortogonal aos modelos.

## Tier 5 — Otimização/avaliação (depende tiers anteriores)

- **S59 [opt] TurboQuant KV cache** — só se S44 retornar "mergeado/disponível".
- **S60 [external] APIs free-tier (GLM 4.6/Flash, Minimax M2, DeepSeek V3.2 atual)** — inventário rate-limits, probe long-context, probe rate-limit empírico, decisão de fallback.
- **S61 [capability] PDF chart probe** — VOCÊ define qual PDF, qual gráfico, qual lib. Eu monto a sprint sob seu input.
- **S62+ [capability] Outras probes específicas que você definir** — não invento; aguardo input.

## Critérios meta do roadmap

- Cada sprint = uma dimensão única, sem cross-contamination
- Cap 5 phases. Se exceder = split em N+1
- Sanity-checks (Tier 1) bundle research por tema (família de modelos, convenção, etc.) — não 1 sprint por item solto
- Usuário define probes em sprints de capability; Claude não inventa
- Cada sprint produz entrada estruturada em `.eval/sprint<N>.jsonl` + handoff
- ADR pra qualquer decisão arquitetural

## O que NÃO está no roadmap (propositadamente, aguardando sua decisão)

- Backlog <pipeline-project> (sprint 6.37+) — <pipeline-project> tem seu próprio backlog; local-dev coordena, não absorve
- Re-validação Phase 1 da 6.36 (Fundamentus stale) — depende de fonte upstream, não é problema técnico
- Distilled candidates (memory `project_distilled_model_candidates.md`) — entram em S51 se tier-de-confiança ok
- Watchlist Trilha 2 — itens bloqueados upstream, revisão mensal continua à parte

---

_Gerado por /sprint-generator (com input do advisor) em 2026-05-16_
