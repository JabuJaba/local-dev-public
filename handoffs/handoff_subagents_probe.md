# Handoff — Sub-Agents Architectural Probe

## Veredito

Sub-agents via Task tool são **tecnicamente viáveis** em qwen3.6-64k via shim Anthropic-Ollama, mas **comportamentalmente não-utilizáveis** sob constraint dispatch-only em task real. **Pré-decomposição manual permanece como pattern arquitetural do local-dev.** Detalhes: `ADR.md` ADR-018.

## O que foi feito (built/verified)

- 4 probes empíricos de exposição da Task tool (Phase 1 testes C/D/E/F) — built, verified
- 1 dispatch unitário end-to-end (Phase 1 Test E satisfaz Phase 2 inteira) — verified
- 1 execução de task real (Phase 3 <pipeline-project> regen) com 30-min cap — verified, exit=0
- Tabela comparativa Sprint 38 V1 monolítico vs Sprint 39 sub-agents-instructed — built
- ADR-018 — built, appended to `ADR.md`
- Roadmap `sprint_39.md` revisado: S47 mantém pré-decomposição, S48 promovida a CRÍTICA, S55-S58 marcadas como assumindo phases pré-decompostas
- `.checkpoint.json` updated: `phase_completed:5`, decision recorded

## Métricas chave

| Phase | wall-clock | tokens_in | turns | tools | Task dispatches | Output |
|---|---|---|---|---|---|---|
| 1 (4 testes) | ~10 min total | 1.3k–177k por test | — | — | 1 (Test E only) | Task exposable only without --bare |
| 2 | — | — | — | — | — | satisfied by Test E |
| 3 (regen real) | 13 min | 444k cumulative | 16 | 15 | **0** | data.js + HTML regenerated correctly |

Comparação Phase 3 vs Sprint 38 V1: 11× mais rápido, 10× menos tokens, sem scope-creep, sem loop, **mas o ganho veio de escopo menor, não de sub-agents** (zero dispatches).

## Artefatos

- `.eval/sprint39.jsonl` — 3 entradas (phase 1+2 consolidado, phase 3)
- `.eval/sprint39_phase1_test{C,D,E,F}.{txt,jsonl}` — raw streams das 4 probes
- `.eval/sprint39_phase3.{txt,jsonl}` — raw stream + summary com pré/pós-state e análise qualitativa
- `analise/sprint39_subagents_vs_monolithic.md` — Phase 4 comparison table
- `ADR.md` (ADR-018 appended)
- `sprints/sprint_39.md` — sprint doc com veredito propagado ao roadmap
- `.checkpoint.json` — phase_completed=5
- `<pipeline-project>/front-end/data.js` regenerated (6962B, mtime 2026-05-17 11:46)
- `<pipeline-project>/front-end/Panorama <pipeline-project>s standalone.html` regenerated (965170B, mtime 2026-05-17 11:47)

## Findings técnicos (gotchas para CLAUDE.md futuras)

1. **`--allowedTools` é subtrativo, não aditivo** no Claude Code v2.1.143. Sob `--bare`, base tool set é fixo em `[Bash,Edit,PowerShell,Read]`; adicionar `Task` em `--allowedTools` não força exposição.
2. **`--disable-slash-commands` é anti-feature** pra contexto: não strip skills do system prompt (`skills_count=38` permanece) e ainda adiciona tools extras (`ShareOnboardingGuide`). Test F produziu 177k input_tokens vs 69k do Test E.
3. **`qwen3.6-64k` ignora instrução textual de "dispatch-only"** quando ferramentas alternativas (Bash/PowerShell) estão expostas e o task tem caminho direto. Verificado empiricamente.
4. **Bash shim do Claude Code no Windows não aceita sintaxe PowerShell** (`$env:VAR=`, `& "path"`). Modelo precisou de 4 retentativas até encontrar sintaxe Bash válida.

## Pendências (não bloqueiam fechamento da Sprint 39)

- **Sprint 38 handoff formal**: `handoffs/handoff_sprint38.md` ainda não escrito (era item backlog declarado no próprio doc da S39). 7 entradas em `.eval/sprint38.jsonl` + finding A (num_ctx=4096 era gargalo) precisam ser registrados. Opcional: virar `Phase 6` da S39 ou pular pra próxima sessão.
- **Parquet revert**: `extractor/data/output/market_data.parquet` permanece em estado pré-experimento (mtime 2026-05-16). Sem impacto no veredito S39.
- **Janelas PowerShell órfãs** (`Start-Process -NoExit` dos Testes C/D/E/F) podem estar abertas na área de trabalho do usuário; fechar manualmente.

## Próxima sprint

Per roadmap atualizado, próximas sprints candidatas (Tier 1, sem dependências cruzadas, podem rodar em paralelo):
- **S40** Coder rankings refresh mai/2026
- **S41** AGENTS.md convention status
- **S42** Tool-use models no Ollama (Hermes etc.)
- **S43** OpenClaw status atual
- **S44** TurboQuant PR#21089 + KV cache opts
- **S45** Context ceiling qwen3.6 (128k / 262k)
- **S46** Skill cost analysis quando local

Tier 2 (S47/S48) tem dependência só sobre S39 e podem ir em seguida — S48 agora é CRÍTICA per ADR-018.

Gerar via `/sprint-generator <N>` consumindo `sprints/sprint_39.md` (roadmap revisado) + companion `sprints/roadmap_sprints_40_62.md`.
