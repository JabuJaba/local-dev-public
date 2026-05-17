# Supervisor: Production Execution with Local Models

## Objetivo

Claude Code atua como supervisor passo a passo: gera prompts, revisa outputs, valida acceptance, registra atrito. O backlog real do <pipeline-project> (dividendos listados lotes 1 e 2) é executado usando modelos locais e ferramentas diferentes. Dados de qualidade e atrito emergem como byproduct natural de cada delegação.

## Protocolo de supervisão (válido para todas as phases de delegação)

Para cada tarefa delegada a modelo local:
1. Claude Code gera o prompt/contexto completo para a ferramenta escolhida
2. Usuário executa (Aider, gemma-cl, Maestro, etc.) e traz o output
3. Claude Code revisa: aceitar / rejeitar / ajustar com instrução específica
4. Usuário commita o que passar (`git add <files específicos>; git commit`)
5. Claude Code registra 1 linha em `.eval/sprint38.jsonl` — sem formulário, sem overhead

Formato de entrada no `.eval/sprint38.jsonl`:
```json
{"task": "<pipeline-project>-6.32", "tool": "aider", "model": "gemma4:26b", "type": "scraping", "result": "accept", "attempts": 1, "friction": "...", "ts": "2026-05-08T..."}
```

## Phases

### Phase 1: Pre-flight <pipeline-project> + save points

**Entregável**: <pipeline-project> com git limpo, `ingest_from_<pipeline-project>-source.py:38` fail-closed commitado, worktree criado, 2 hashes no `.checkpoint.json`

**Acceptance**:
- `git status` em `<workspace>/<pipeline-project>/` = clean (9 arquivos: commitar ou descartar, decisão documentada por arquivo)
- `git push` executado — 8 commits pendentes pushados para origin
- `ingest_from_<pipeline-project>-source.py:38` corrigido para fail-closed:
  ```python
  _db_path_raw = os.environ.get("SANDBOX_DB_PATH")
  if not _db_path_raw:
      raise SystemExit("SANDBOX_DB_PATH must be set -- nunca rodar extrator sem sandbox redirect")
  DB_PATH = Path(_db_path_raw)
  ```
- Commit do fix com hash registrado em `.checkpoint.json` como `save_point_0`
- `git worktree add ../<pipeline-project>-local-test -b sprint38-local-test` executado
- `git worktree list` mostra `sprint38-local-test`
- `$env:SANDBOX_DB_PATH` verificado: output mostra `SANDBOX OK`
- 22/22 pytest passando pós-fix

**Nota**: prod DB real = `<workspace>/<pipeline-project>/scraper/<pipeline-project>.db` (baseline: 779/28/23).
Chromium path hardcoded em `render_html.py` — ignorar nesta sprint, não é bloqueio.

---

### Phase 2: <pipeline-project> Sprint 6.32 delegado — dividendos lote 1

**Entregável**: dividendos coletados para ≥5/6 fundos (TICKER1, TICKER2, TICKER3, TICKER4, TICKER5, TICKER6) via disclosure-system cat=6 tipo=40 (Informe Mensal Estruturado)

**Fonte confirmada (Sprint 6.31)**: `https://public-disclosures.example.com/<pipeline-project>-source/publico/exibirDocumento?id={id}&cvm=true`
Campo alvo: `8.2` (dividend yield do mês = unidade monetaria/cota). Fallback: Status Invest → disclosure-system cat=3/4/14.

**Acceptance**:
- `check_dividendos_coverage.py` retorna ≥5/6 fundos com ≥10 meses no range Apr/2025–Mar/2026; 0 duplicatas
- 22/22 pytest
- Commit no worktree com hash registrado como `save_point_1`
- 1 entrada em `.eval/sprint38.jsonl` com: tool, model, result, attempts, friction

**Nota**: Layer 2 (Claude API) retorna `layer2_no_api_key` sem chave — não esperar resultados de TICKER3/TICKER1/TICKER15/TICKER4 por essa rota. disclosure-system cat=6 tipo=40 é a rota correta.

---

### Phase 3: <pipeline-project> Sprint 6.33 delegado — dividendos lote 2

**Entregável**: dividendos coletados para ≥4/5 fundos (TICKER7, TICKER8, TICKER9, TICKER10, TICKER11), preferencialmente com ferramenta/modelo diferente da Phase 2 se houve atrito

**Acceptance**:
- `check_dividendos_coverage.py` retorna ≥4/5 fundos com ≥10 meses; 0 duplicatas
- 22/22 pytest
- Commit no worktree com hash registrado como `save_point_2`
- 1 entrada em `.eval/sprint38.jsonl` com comparação implícita vs Phase 2 (mesmo tipo de task, ferramenta possivelmente diferente)

**Nota**: TICKER12 não está neste lote (já coletado em Sprint 6.31, 9 meses — aceito). TICKER10 tem dependência de decisão TICKER18 tranches — se bloqueado, documentar e avançar para os outros 4.

---

### Phase 4: Merge + eval record + cleanup

**Entregável**: changes em main, worktree removido, eval consolidado, push feito

**Acceptance**:
- `git diff main...sprint38-local-test` revisado e aprovado antes do merge
- `git merge sprint38-local-test --no-ff` executado; merge commit em main
- `git worktree remove ../<pipeline-project>-local-test` + `git branch -d sprint38-local-test`
- `git worktree list` mostra apenas main
- Baseline prod confirmado: relatorios=779, avisos_cotistas=28, comunicados_mercado=23 (idêntico pré-sprint)
- `.eval/sprint38.jsonl` com ≥2 entradas (phase 2 + phase 3)
- `git push` executado
- `.checkpoint.json` atualizado: `save_point_0`, `save_point_1`, `save_point_2`, `save_point_final` registrados

---

## Critérios de Aceite da Sprint

- [ ] `ingest_from_<pipeline-project>-source.py:38` fail-closed — sem `SANDBOX_DB_PATH` o script aborta com mensagem clara (não cria DB vazio)
- [ ] ≥10/11 fundos (lotes 1+2) com dividendos ≥10 meses Apr/2025–Mar/2026
- [ ] 22/22 pytest após cada phase de execução (2 verificações)
- [ ] ≥2 ferramentas ou modelos distintos testados; cada um com entrada em `.eval/sprint38.jsonl`
- [ ] 4 git hashes em `.checkpoint.json`: save_point_0 (fail-closed), save_point_1 (lote 1), save_point_2 (lote 2), save_point_final (merge)
- [ ] Baseline prod inalterado ao final (779/28/23)

## Dependências

- Sprint 37 PASS — protocolo worktree + SANDBOX_DB_PATH validado end-to-end
- `<workspace>/<pipeline-project>/` acessível e em estado conhecido
- Ollama rodando com ≥1 modelo disponível (gemma4:26b ou qwen3.6:35b-a3b)
- `check_dividendos_coverage.py` existente (criado em Sprint 6.31)

## Itens Pendentes do Sprint Anterior

- `ingest_from_<pipeline-project>-source.py:38` fail-closed (handoff Sprint 37, item 1 PRIORITÁRIO) → Phase 1
- `filter_total_rows` bug `parsers_cpu/_utils.py:254` → Backlog Sprint 39 (não bloqueia dividendos)

## Backlog Sprint 39

<!-- Gerado automaticamente por split — incorporar na próxima execução de /sprint-generator -->
- <pipeline-project> Sprint 6.34: dividendos lote 3 (TICKER13, TICKER14, TICKER15, TICKER16, TICKER17) + consolidação final 19 fundos
- <pipeline-project> Sprint 6.35: CDI spread no Panorama — substituir DY Fundamentus por dy_12m_composto; atualizar ChartYield
- Decisão TICKER18 tranches aggregation (afeta Chart 8 top5 devedores)
- `filter_total_rows` bug (`parsers_cpu/_utils.py:254`) — investigar e corrigir via modelo local
- Base de CRAs + Assembleias: gráfico situação papéis, emissores sem CETIP

_Gerado por /sprint-generator em 2026-05-08_
