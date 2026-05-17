# Safety Protocol (Sandbox SQLite + Isolated Worktree)

## Objetivo
Implementar protocolo de seguranca para <pipeline-project> antes de qualquer escrita com modelo
local: sandbox SQLite via `$env:SANDBOX_DB_PATH` + worktree git isolado. Corrige as premissas
falsas identificadas em findings C2+C3 (2026-05-07): worktree git NAO isola SQLite que vive
fora do repo; escrita direta em prod e possivel sem env override.

## Phases

### Phase 1: Sandbox env override
**Entregavel**: variavel `$env:SANDBOX_DB_PATH` validada no extrator -- substituicao do DB prod
por sandbox descartavel confirmada antes de qualquer execucao

**Acceptance**:
- `$env:SANDBOX_DB_PATH = "$env:USERPROFILE\<pipeline-project>-sandbox-db\example_test.db"` definido e verificado
- `python extractor/src/ingest_from_<pipeline-project>-source.py --help` (ou trecho de boot do script) mostra
  `DB_PATH` resolvendo para o sandbox (nao `<workspace>/<pipeline-project>-extraction/<pipeline-project>.db`)
- Diretorio `$env:USERPROFILE\<pipeline-project>-sandbox-db\` criado se nao existir
- DB prod: 0 conexoes abertas durante a phase (verificar via `sqlite3 prod.db ".tables"` antes/depois)

**Nota**: findings C2 -- `ingest_from_<pipeline-project>-source.py:38` define fallback hardcoded para prod.
`$env:SANDBOX_DB_PATH` deve ser setado ANTES de qualquer invocacao do extrator nesta sprint.
Se o script nao honra a env var, corrigir o fallback antes de prosseguir para Phase 2.

---

### Phase 2: Worktree protocol
**Entregavel**: worktree `../<pipeline-project>-local-test` criado em branch isolada; checklist
de protocolo documentado em `analise/<pipeline-project>-worktree-protocol.md`

**Acceptance**:
- `git worktree list` (no repo <pipeline-project>) mostra a branch nova
- `analise/<pipeline-project>-worktree-protocol.md` existe e contem os 5 passos:
  1. `git worktree add ../<pipeline-project>-local-test <branch>` antes de qualquer sessao
  2. `$env:SANDBOX_DB_PATH` para sandbox obrigatorio (nao opcional)
  3. Aider/modelo em modo read-only primeiro (analisa, nao edita)
  4. Zero commits automaticos: diff review obrigatorio antes de apply
  5. Rollback: `git worktree remove ../<pipeline-project>-local-test` -- 1 comando, zero impacto prod
- Protocolo referencia findings C2+C3 explicitamente

**Nota**: findings C3 -- worktree isola apenas arquivos sob versionamento git. O SQLite em
`<workspace>/<pipeline-project>-extraction/<pipeline-project>.db` NAO esta no repo -- nunca e protegido pelo worktree.
Esse fato DEVE estar explicito no protocolo para que proximas sessoes nao repitam a premissa falsa.

---

### Phase 3: Probe read-only no worktree
**Entregavel**: execucao do extrator em modo analise (sem escrita) dentro do worktree com
`$env:SANDBOX_DB_PATH` apontando pro sandbox

**Acceptance**:
- Extrator completa sem erro
- Row count DB prod antes == row count DB prod depois (verificado via `sqlite3`)
- Sandbox pode ter 0 rows (read-only nao escreve) -- aceitavel
- Output do extrator (stdout/log) nao menciona o caminho do DB prod

---

### Phase 4: External acceptance (escrita controlada no sandbox)
**Entregavel**: 1 execucao completa com escrita no sandbox (task real: ex: TICKER_X, 1 periodo
curto fixo como 2025-01-01 a 2025-01-31); verificacao cruzada prod vs sandbox

**Acceptance**:
- rows no sandbox > 0 apos execucao
- rows no DB prod = mesmo numero de antes da phase (prod intocado)
- `git worktree remove ../<pipeline-project>-local-test` executa sem erro
- Resultado documentado em `analise/sprint37_acceptance_2026-05-07.md` com:
  - row count prod antes/depois, row count sandbox, fund testado, periodo, status (PASS/FAIL)

**Nota**: este e o external acceptance conforme `analise/sprint-acceptance-contract.md`
Tipo B (routing/seguranca). `phase_completed=4` NAO avanca sem o numero de rows documentado.

---

## Criterios de Aceite da Sprint
- [ ] `$env:SANDBOX_DB_PATH` redireciona para sandbox -- DB prod nunca tocado durante a sprint
- [ ] Worktree criado e protocolo documentado em `analise/<pipeline-project>-worktree-protocol.md` (5 passos)
- [ ] Probe read-only: row count prod identico antes e depois
- [ ] External acceptance: rows sandbox > 0, prod inalterado, worktree removivel, numeros documentados

## Dependencias
- Sprint 34 concluida -- acceptance contract disponivel como referencia (`analise/sprint-acceptance-contract.md`)
- findings C2+C3 (`findings-2026-05-07-011700.md`) como especificacao dos gaps a corrigir
- `git` disponivel no repo `<workspace>/<pipeline-project>/` (verificar antes de Phase 2)
- `sqlite3` CLI disponivel (ou Python sqlite3 como alternativa para contagem de rows)
- `$env:SANDBOX_DB_PATH` honrado por `extractor/src/ingest_from_<pipeline-project>-source.py` (verificar em Phase 1; corrigir fallback se necessario)

## Itens Pendentes do Sprint Anterior
- N/A (sprint independente -- desbloqueada pela Sprint 34)

## Notas
- **Encoding**: scripts Python UTF-8. `$env:PYTHONIOENCODING=utf-8` antes de qualquer execucao.
- **Nunca rodar extrator sem `$env:SANDBOX_DB_PATH`** nesta sprint -- mesmo em testes rapidos.
- **Backup antes de Phase 3**: se <pipeline-project> nao tem backup recente, criar antes de qualquer execucao.
- **Gate para Sprint 38 (aider em <pipeline-project> real)**: Sprint 37 PASS e prerequisito. Sem protocolo de seguranca validado, Sprint 38 nao roda.
- **Referencia acceptance**: `analise/sprint-acceptance-contract.md` Tipo B.

_Gerado por /sprint-generator em 2026-05-07_
