# Concept Brief — pipeline-token-economy

## Problema

O pipeline de skills atual queima volume alto semanal em Claude (<pipeline-project> = 63% sozinho). Bash é o vilão isolado mais caro: stdout cru entra no contexto sem filtro. O pipeline atual também não é funcional — não converge — então a meta é **reestruturar, não otimizar incrementalmente**.

## Hipótese de solução

Pipeline reestruturado em 3 camadas empilhadas, com agents atomizados o suficiente pra modelos locais (Qwen3.6 / Gemma4) carregarem o grosso da execução, e Claude reservado pra decisões arquiteturais e tarefas que comprovadamente travam local.

### Camada 1 — Input compression (corta tokens que ENTRAM)

| Ferramenta | Camada que ataca | Economia | Onde aplica no pipeline |
|---|---|---|---|
| **rtk** (PreToolUse hook) | Bash output | 60–90% | **executor** (full Bash), **project-organizer** (tem Bash). Não ajuda task-planner/logger (sem Bash). |
| **code-review-graph** (MCP) | Code understanding | 8.2× médio, 49× pico | **task-planner** (substitui Glob/Grep recursivo), **project-organizer**, **specialists** (blast radius por task) |
| **repomix --compress** | Snapshot upfront | ~70% | maestro lê `.repomix/repomix-output.xml` na FASE 0 (já no design) |

### Camada 2 — Execução com agents existentes + 6 specialists novos

Mapeamento de modelo por agent (proposta), baseado em risco de qualidade × surface de tool × custo atual:

| Agent | Modelo atual | Modelo proposto | Justificativa |
|---|---|---|---|
| **maestro** | Haiku 4.5 | Haiku 4.5 (manter) | Orquestração precisa julgamento; Haiku já é barato; migrar local é o último passo, não o primeiro. |
| **task-planner** | Sonnet 4.6 | Sonnet → Qwen3.6 (Phase 3) | Quebra de escopo precisa julgamento. Migrar só após specialists locais validados. |
| **project-organizer** | Sonnet 4.6 | Sonnet (manter) | ADRs e roadmap são output longo (>600 palavras) — limite estrutural local conhecido. |
| **executor** | Haiku 4.5 | **Qwen3.6 local (Phase 2)** | Mecânico, confirma cada ação, contexto cirúrgico vindo do plano. Sweet spot do local. |
| **logger** | Haiku 4.5 | **Qwen3.6 local (Phase 1)** | Formatação pura, zero julgamento. Ideal pra começar — risco zero. |
| **6 specialists** (a criar) | — | Mix: ver abaixo | Atomização extrema + contexto cirúrgico (graph) → mecânico → local viável. |

**Specialists a criar e proposta de placement:**
- `security-specialist` → Sonnet (objeção 🔴 trava pipeline; falso negativo é caro)
- `data-engineer` → Qwen3.6 local (piloto natural pra <pipeline-project>)
- `backend-engineer` → Qwen3.6 local (após data-engineer validar)
- `frontend-engineer` → Qwen3.6 local
- `devops-engineer` → Qwen3.6 local
- `network-specialist` → Sonnet inicialmente (low volume, alta especificidade)

### Camada 3 — Output compression (corta tokens que SAEM)

**caveman** comprime resposta do Claude quando ainda for usado (65–75%). Aplicação:
- maestro (orquestração ainda Haiku Claude) — sim
- specialists em Sonnet (security, network) — sim
- agents migrados pra local — não aplica (output local não custa)

Ortogonal às camadas 1 e 2 — multiplicativo.

## Quem sente o problema

O mantenedor — gasto direto. <pipeline-project> puxa 63% do consumo, então é o piloto natural **de impacto**, mas local-dev (volume baixo semanal) é o piloto natural **de risco** (cobaia barata).

## Sinal de sucesso

**Piso 40% economia líquida** rodando pipeline completo de uma sprint do <pipeline-project> com resultado tecnicamente equivalente ao baseline atual. Medição por `/token-report` antes/depois sobre janela controlada (mesmas tasks). Velocidade pode degradar — 40% de piso já compensa.

**Métricas secundárias a medir já no piloto:**
- Tokens economizados por camada (rtk vs graph vs caveman) — atribuição limpa
- Tasks que escalaram local→Claude (taxa de fallback)
- Overhead de orquestração (handoffs entre N agents) em ms e tokens

## O que poderia matar isso

- **Risco A (principal, declarado pelo usuário)**: atomização extrema faz modelo local perder contexto agregado e qualidade despencar. Mitigação: code-review-graph dá blast radius por task; maestro injeta `get_impact_radius` antes de chamar specialist.
- **Risco B (já observado)**: overhead de handoff entre N agents come a economia. Pipeline atual é sintoma. Mitigação: medir overhead real antes de escalar; talvez 4 specialists bastem.
- **Risco C**: rtk + graph + repomix podem ter overlap conflitante (3 ferramentas filtrando os mesmos reads). Precisa ordem clara de precedência (graph > repomix snapshot > rtk para Bash residual).
- **Risco D**: caveman comprime output, mas se aplicado a Sonnet pode degradar precisão de specialist técnico (ex: security). Aplicar caveman seletivamente — só em agents de baixa criticidade.
- **Risco E**: especialistas escritos por nós (sem o colega que mandou os 5 atuais) podem ter qualidade desigual. Mitigação: usar os 5 existentes como template, replicar estrutura (frontmatter + tools restritos + protocolo educacional).
- **Risco F (descoberto na leitura)**: maestro.md tem inconsistência — afirma specialists herdam Sonnet, mas maestro frontmatter é Haiku. Resolver no Phase 1.
- **Risco G**: Qwen3.6 ainda tem bugs conhecidos (CLAUDE.md: "tool match baixo, output >600 palavras escala"). Logger e executor são os menos afetados — começar por eles.

## Incógnitas-chave

1. **Qual ordem/precedência entre rtk × graph × repomix** quando os 3 estão ativos? Existe receita publicada de stack ou é território virgem?
2. **Modelos locais aguentam specialists técnicos** (security, backend) com qualidade aceitável quando atomizados? Sprint 2 mostrou 18/20 PASS em tasks simples — mas specialists exigem julgamento. Alguém já documentou specialist técnico em modelo 30B local?
3. **<pipeline-project> é piloto certo ou risco alto?** É o maior consumidor → maior ganho potencial, mas também mais sensível a degradação. **Decisão: piloto duplo** — local-dev pra validar tecnicamente (risco baixo), <pipeline-project> pra medir economia (alto reward).
4. **Inconsistência maestro/specialists model: inherit** — qual era a intenção real? maestro Haiku + specialists Haiku? ou maestro Sonnet ocasionalmente?

## Nível de maturidade

**Hipótese** — direção clara, cada lever validada na fonte primária, agents existentes já alinhados com atomização e tool-surface restrito (não precisa reescrever do zero). Mas o stack inteiro é território novo. Cabe um sprint de validação antes de comprometer.

---

## Próximo passo sugerido — REESCRITO após sanity-check (2026-05-06)

Sanity-check (`sanity-cache/pipeline-stack-token-economy_2026-05-06.md`) **inverteu a prioridade** do plano original. Cache anterior do mesmo projeto (`pipeline-routing-overhead.md`, 5 dias atrás) já mediu empiricamente que **o pipeline atual gasta 6,5× mais em overhead que executar direto no Claude** (4.226k vs 651k tokens). External research confirma com 2026 industry consensus (Anthropic position oficial, multi-agent ⇒ 15× tokens sem circuit breakers, token usage explica 80% da variância).

**Novas peças identificadas pelo sanity-check:**
- **LiteLLM** como gateway unificado local+cloud (peça nova, gap real do design)
- **wshobson-agents** confirma como template para os 6 specialists faltantes
- **caveman seletivo** (`caveman-compress` em arquivos de memória, não modo grunt)
- **rtk standby na wiki está desatualizado** — confirmar instalação Windows nativa
- **Reavaliação Qwen3.6 vs Gemma 4** para specialists técnicos (sinal externo: Gemma mais robusto a Q4)
- **Circuit breakers + token budget enforcement** como requisito explícito (não como cuidado opcional)

→ **`/project-plan`** com a seguinte trilha (Sprint 11+):

**Phase 0 — Matar overhead determinístico (4–6h, ganho a ser remedido)**
- ⚠️ **Caveat de honestidade**: o "-86%" do `pipeline-routing-overhead.md` foi extrapolado de N=2 tasks `read_only` triviais com Bug 2 inflando merge-review. Sprint 18 já corrigiu os bugs mas **não há remedição**. Direção sustentada por 3 sinais convergentes (Sprint 17 + Anthropic position + arxiv Tran/Kiela), mas a **magnitude precisa ser validada pós-Sprint 18 com tasks representativas** (multi-arquivo, output longo, write/edit) antes de virar premissa.
- Implementar os 3 fixes do `pipeline-routing-overhead.md`: threshold de complexidade, fit-evaluator determinístico, oracle programático no merge-review
- **Adicionar separação `.ai()` vs `.harness()` (princípio agentfield)**: chamadas constrained de routing (fit-evaluator) viram `.ai()` puro sem tools; chamadas autônomas (executor + specialists) viram `.harness()` com tools + verification loop
- Resolver inconsistência maestro.md (Haiku vs Sonnet specialists herdam)
- Não adicionar nada novo nesta fase

**Phase 1 — Gateway + medição + estrutura de controle (1–2 dias)**
- Adotar **LiteLLM** como gateway unificado
- Migrar 1 chamada (executor) como prova de conceito
- Implementar **3 nested loops (padrão agentfield)**: (a) per-task com até 5 retries com QA feedback; (b) advisor com 5 typed recovery actions (retry-modified, split, escalate, abandon, manual); (c) replanner que restructura o DAG quando issues cascateiam
- Implementar **circuit breakers + token budget enforcement por agent** (não global) — multi-agent ⇒ 15× tokens vs chat sem isto (sinal externo + arxiv Tran/Kiela)
- Implementar **debt como first-class typed structure** — cada scope reduction, escalation, ou retry vira data record severity-rated; downstream agents consomem
- Definir métricas de medição limpa por camada
- **Justificar cada multi-agent step contra arxiv 2604.02460**: single-agent ≥ MAS sob budget igual em reasoning sequencial. Cada step paralelo precisa ou paralelização REAL ou skill especializada não atingível extendendo single-agent.

**Phase 2 — Camada de input isolada (1 sprint)**
- Instalar rtk + code-review-graph + repomix em local-dev
- Medir economia ISOLADA por ferramenta (não empilhar ainda)
- Confirmar instalação rtk no Windows nativo (atualizar wiki)

**Phase 3 — 6 specialists novos (1 sprint, paralelizável)**
- Usar **wshobson-agents** como template (não copiar cego)
- Criar backend, frontend, data, devops, network, security
- Manter modelo cloud (Sonnet) inicialmente — não migrar pra local nesta fase
- Mapeamento de tools restrito por role (3–5 ferramentas, padrão validado)

**Phase 4 — Logger local + spike Qwen vs Gemma (1 sprint)**
- Migrar **logger** pra modelo local (zero risco, formatação pura)
- Spike empírico: Qwen3.6 vs Gemma 4 em tasks de specialist técnico
- Decidir primário com dado, não com hipótese

**Phase 5 — Migração progressiva por agent (2 sprints)**
- Migrar executor pra local (médio risco)
- Migrar data-engineer pra local (piloto de specialist)
- Aplicar **caveman-compress** em arquivos de memória dos agents que ficam em Claude
- Rollout 1 specialist por vez, gate de qualidade entre cada um

**Phase 6 — Rollout <pipeline-project> + medição final**
- Canary em <pipeline-project>
- Medir economia líquida total contra piso 40%
- ADR consolidando placement final por agent
- Decisão sobre claude-mem (após pilot em <game-bot> ter resultado)

---

## Watchlist (avaliar em ciclo futuro, não agora)

- **Conductor (arxiv 2512.04388, ICLR 2026)** — RL-trained 7B router recursivo. Validação acadêmica do princípio "router pequeno dedicado". Não adotar (precisa treino RL); evolução natural do maestro se ele virar gargalo.
- **Zed parallel agents** — editor com multi-agent nativo (Apr 2026). Reasoning effort selection, 1M context BYOK Opus/Sonnet. Re-avaliar se Claude Code virar gargalo de custo unitário para specialists técnicos.
- **Qwen Code (terminal agent oficial Qwen)** — alternativa ao Claude Code para parte local. Avaliar se Sprint 4–5 mostrar atrito com Claude Code para chamadas Qwen3.6.
- **claude-mem** — após pilot <game-bot> (1–2 sem). Se ROI positivo, pode reduzir reads via PreToolUse gate determinístico.
- **PDFs locais lidos** (PyMuPDF, 2026-05-06):
  - **Lambda MFU** — descartado: datacenter training (HGX B200/GB300 NVL72) 100% off-topic para RTX 5070 Ti single-node
  - **Chain of Thought (IBM Research, Abstract-CoT)** — watchlist long-term: redução até 11,6× em tokens de reasoning treinando vocabulário abstrato reservado. Não acionável (precisa training); relevante se Sprint 12+ considerar fine-tune Qwen3.6. Reforça que **a próxima fronteira de economia não é compressão pós-hoc (caveman) mas treinar o modelo a raciocinar com menos tokens desde o início**.
  - Conductor.pdf já coberto via arxiv 2512.04388

---

## Maturidade — pronto para `/project-plan`

**Conceito Claro.** Após 4 rodadas de aprofundamento (brainstorm inicial → leitura dos 5 .md de ideias/ → sanity-check Tier 1 → verificação direta do Sprint 17 + 4 fontes externas + 2 PDFs locais):

- Direção sustentada por convergência de 4 sinais independentes: Sprint 17 (com caveats explícitos), Anthropic position 2026, arxiv Tran/Kiela, agentfield Beyond Vibe Coding
- Magnitude (-86%) marcada como **incerta a remedir**, não premissa
- 6 fases com dependência clara, risco crescente, métrica em cada gate
- Cada multi-agent step do plano tem justificativa contra arxiv 2604.02460 (paralelização real ou skill especializada)
- Padrões arquiteturais externos (`.ai()`/`.harness()`, 3 nested loops, debt como typed structure) integrados explicitamente
- Watchlist clara separa "agora" de "ciclo futuro"

Maturidade chegou ao teto que faz sentido sem implementar Phase 0. Próximo passo natural: `/project-plan` traduzindo as 6 fases em sprints concretos com Sprint 11+ no calendário.
