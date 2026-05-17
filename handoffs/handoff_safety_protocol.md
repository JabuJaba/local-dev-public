# Handoff — Safety Protocol for Local Model Sessions

Data: 2026-05-07/08
Status: **COMPLETO — PASS**
Gate liberado: Sprint 38 (aider + modelo local em <pipeline-project> real)

---

## O que foi feito

Sprint 37 implementou e validou o protocolo de seguranca para sessoes com modelo local no <pipeline-project>.
Todas as 4 fases PASS. Acceptance doc: `<workspace>/<pipeline-project>/analise/sprint37_acceptance_2026-05-07.md`.

### Phase 1 — Sandbox env override (PASS)
- `$env:SANDBOX_DB_PATH` redireciona o extrator para `C:/Users/user/<pipeline-project>-sandbox-db/example_test.db`
- Verificado que DB prod (`<workspace>/<pipeline-project>/scraper/<pipeline-project>.db`) nao foi tocado
- Descoberta critica: sprint doc referenciava `<workspace>/<pipeline-project>-extraction/<pipeline-project>.db` (diretorio inexistente)
  O DB prod real e `<workspace>/<pipeline-project>/scraper/<pipeline-project>.db`

### Phase 2 — Worktree protocol (PASS)
- Worktree `sprint37-local-test` criado e removido (rollback em 1 comando verificado)
- Protocolo de 5 passos criado em `<workspace>/<pipeline-project>/analise/<pipeline-project>-worktree-protocol.md`
- Protocolo referencia findings C2+C3 explicitamente e documenta que worktree NAO protege SQLite

### Phase 3 — Probe read-only (PASS)
- `--dry-run` no worktree com sandbox DB: `Pendentes encontrados: 0`
- Row count prod identico antes e depois: relatorios=779, avisos_cotistas=28, comunicados_mercado=23

### Phase 4 — External acceptance (PASS)
- Fundo: TICKER13, dataReferencia=31/01/2025, id_documento=844020
- Sandbox: 1 row escrita (status=ERRO — bug pre-existente `filter_total_rows`, nao relacionado a sprint)
- Prod: row 844020 permaneceu PENDENTE (intocado)
- Worktree removido com `git worktree remove` + `git branch -d sprint37-local-test`

---

## Artefatos gerados

| Artefato | Caminho |
|---|---|
| Protocolo 5 passos | `<workspace>/<pipeline-project>/analise/<pipeline-project>-worktree-protocol.md` |
| Acceptance doc | `<workspace>/<pipeline-project>/analise/sprint37_acceptance_2026-05-07.md` |
| Checkpoint | `.checkpoint.json` (phase_completed=4) |
| Sandbox DB | `C:/Users/user/<pipeline-project>-sandbox-db/example_test.db` (pode ser deletado) |

---

## Baseline prod (referencia para Sprint 38)

DB: `<workspace>/<pipeline-project>/scraper/<pipeline-project>.db`

| Tabela | Rows |
|---|---|
| relatorios | 779 |
| avisos_cotistas | 28 |
| comunicados_mercado | 23 |
| **Total** | **830** |

relatorios por status: PENDENTE=729, DONE=47, ERRO=2, KNOWN_GAP=1

---

## Itens abertos para Sprint 38

### Item 1 (PRIORITARIO) — Corrigir fallback hardcoded em `ingest_from_<pipeline-project>-source.py:38`

O fallback atual e um diretorio inexistente (protecao acidental, fragil):
```python
# atual — fragil:
DB_PATH = Path(os.environ.get("SANDBOX_DB_PATH", r"<workspace>/<pipeline-project>-extraction/<pipeline-project>.db"))

# fix correto — fail-closed:
_db_path_raw = os.environ.get("SANDBOX_DB_PATH")
if not _db_path_raw:
    raise SystemExit("SANDBOX_DB_PATH must be set -- nunca rodar extrator sem sandbox redirect")
DB_PATH = Path(_db_path_raw)
```

Arquivo: `<workspace>/<pipeline-project>/extractor/src/ingest_from_<pipeline-project>-source.py` linha 38.
Gotcha documentado em `<workspace>/<pipeline-project>/CLAUDE.md` gotcha #71.

### Item 2 (BACKLOG) — Investigar `filter_total_rows` bug

`parsers_cpu/_utils.py:254` levanta `'int' object has no attribute 'lower'` para alguns PDFs.
Descoberto em TICKER13 2025-01 (id_documento=844020). Nao e bloqueio para Sprint 38.
Gotcha documentado em `<workspace>/<pipeline-project>/CLAUDE.md` gotcha #72.

---

## Pre-requisitos para Sprint 38

Antes de qualquer sessao com modelo local (Aider/Claude Code via Ollama):

```powershell
# 1. Worktree isolado
cd <workspace>/<pipeline-project>
git worktree add ../<pipeline-project>-local-test -b sprint38-local-test
git worktree list  # verificar

# 2. Sandbox DB
$env:SANDBOX_DB_PATH = "$env:USERPROFILE\<pipeline-project>-sandbox-db\example_test.db"
New-Item -ItemType Directory -Path "$env:USERPROFILE\<pipeline-project>-sandbox-db" -Force | Out-Null

# 3. Verificar sandbox OK
$env:PYTHONIOENCODING = "utf-8"
& "<workspace>/<pipeline-project>/extractor/venv/Scripts/python.exe" -c "
import os; from pathlib import Path
p = Path(os.environ.get('SANDBOX_DB_PATH', 'FALLBACK-PROD'))
print('DB_PATH:', p)
print('SANDBOX OK' if '<pipeline-project>-sandbox-db' in str(p) else 'FAIL')
"

# 4. Baseline row count
& "<workspace>/<pipeline-project>/extractor/venv/Scripts/python.exe" -c "
import sqlite3
con = sqlite3.connect(r'<workspace>/<pipeline-project>/scraper/<pipeline-project>.db')
for t in ['relatorios', 'avisos_cotistas', 'comunicados_mercado']:
    print(t, con.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0])
con.close()
"
```

Protocolo completo: `<workspace>/<pipeline-project>/analise/<pipeline-project>-worktree-protocol.md`

---

_Sprint doc: `sprints\sprint_37.md`_
_Findings: `.diagnose/findings-2026-05-07-011700.md` (C2, C3 — resolved-by-sprint37)_
