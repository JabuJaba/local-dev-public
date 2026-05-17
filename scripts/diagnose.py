# -*- coding: utf-8 -*-
"""
Diagnostico de saude dos projetos sob `projects_root` (config.yaml).

Para cada projeto listado em _project_context/:
  - Verifica se o diretorio existe
  - Le "Limitacoes e problemas conhecidos" como lista de pendencias
  - Verifica prontidao para GitHub (README, .gitignore, requirements, credenciais)
  - Verifica saude do repo git (ultimo commit, arquivos grandes, arquivos sujos)
  - Classifica arquivos grandes por tipo (modelo/temporario/dados/binario)
  - Grep de padroes frageis no codigo (BRL/USD hardcoded, localhost ports, dirs temp)
  - Gera sugestoes de tarefas de manutencao

Saidas:
  - Relatorio no terminal (--report)
  - Arquivo YAML de tarefas sugeridas para aprovacao (--suggest)
  - Adicao direta ao backlog.yaml (--add-to-backlog, requer confirmacao)

Uso:
  python scripts/diagnose.py --report
  python scripts/diagnose.py --suggest > suggested_tasks.yaml
  python scripts/diagnose.py --add-to-backlog   # interativo, pede confirmacao
  python scripts/diagnose.py --project <scraper-project>
  python scripts/diagnose.py --github-only       # so verificacoes de GitHub readiness
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# Root directory containing all the project folders this script scans.
# Override via env var LOCAL_DEV_PROJECTS_ROOT; defaults to one level above the repo.
import os as _os
PROJECTS_ROOT = Path(_os.environ.get(
    "LOCAL_DEV_PROJECTS_ROOT",
    str(Path(__file__).resolve().parent.parent.parent),
))
PROJECT_CONTEXT_DIR = PROJECTS_ROOT / "_project_context"
BACKLOG_PATH = Path(__file__).resolve().parent.parent / "backlog" / "backlog.yaml"
README_INDEX = PROJECT_CONTEXT_DIR / "README.md"

# Directories to skip when scanning (venvs, build artifacts, etc.)
SKIP_DIRS = {"venv", ".venv", "env", ".env", "node_modules", "__pycache__",
             ".git", "build", "dist", ".tox", "site-packages"}

CREDENTIAL_PATTERNS = [
    r'["\']?(api_key|apikey|secret|password|token|APIFY_TOKEN|OPENAI_API_KEY)\s*[=:]\s*["\'][A-Za-z0-9_\-]{10,}',
    r'sk-[A-Za-z0-9]{32,}',
]

GITHUB_REQUIRED = [
    ("README.md", "README ausente"),
    (".gitignore", ".gitignore ausente"),
]

# ---------------------------------------------------------------------------
# Large file classification
# ---------------------------------------------------------------------------

# Path fragments that indicate intentional model storage
_MODEL_PATH_HINTS = {"models", "model", "weights", "checkpoints", "gguf", "onnx"}
# Extensions that are almost always model weights/binaries
_MODEL_EXTENSIONS = {".gguf", ".safetensors", ".pt", ".pth", ".h5"}
# Extensions that are typically data artifacts
_DATA_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".parquet", ".pkl", ".csv"}
# Binary distributions / archives
_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".7z", ".rar"}

# Path/name fragments that strongly suggest a temporary or probe file
_TEMP_HINTS = {"tmp", "temp", "probe", "manual_probe", "scratch", "debug",
               "_tmp", "_temp", "_check", "socios_tmp", "tmp_check"}


def classify_large_file(rel_path: str) -> str:
    """
    Classify a large file into one of four categories:
      modelo     — intentional model weights/binaries (just needs .gitignore)
      temporario — likely a throwaway file (candidate for deletion)
      dados      — runtime database or data artifact (needs .gitignore)
      binario    — archive / compiled binary (needs .gitignore)
    """
    p = Path(rel_path)
    parts_lower = {part.lower() for part in p.parts}
    name_lower = p.name.lower()
    suffix = p.suffix.lower()

    # Temp heuristic: any path fragment matches temp hints
    if any(hint in name_lower for hint in _TEMP_HINTS) or \
       any(hint in part for part in parts_lower for hint in _TEMP_HINTS):
        return "temporario"

    # Model heuristic: extension is model-specific OR path contains model dir hints
    if suffix in _MODEL_EXTENSIONS:
        return "modelo"
    if suffix == ".bin" and parts_lower & _MODEL_PATH_HINTS:
        return "modelo"

    # Data artifacts
    if suffix in _DATA_EXTENSIONS:
        return "dados"

    # Archives/binaries
    if suffix in _ARCHIVE_EXTENSIONS:
        # Archives inside a model/bin-like dir are intentional binaries
        if parts_lower & {"bin", "llama_cpp", "cuda"} | _MODEL_PATH_HINTS:
            return "binario-intencional"
        return "binario"

    return "grande"


# ---------------------------------------------------------------------------
# Parsing do README de contexto
# ---------------------------------------------------------------------------

def parse_context_file(path: Path) -> dict:
    """Parse a _project_context/*.md file into structured data."""
    text = path.read_text(encoding="utf-8", errors="replace")
    result = {"title": "", "limitations": []}

    m = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if m:
        result["title"] = m.group(1).strip()

    m = re.search(r"##\s+Limita[çc][aã]?[oe].*?\n(.*?)(?=\n##|\Z)", text, re.DOTALL | re.IGNORECASE)
    if m:
        raw = m.group(1)
        bullets = re.findall(r"^[-*]\s+(.+)", raw, re.MULTILINE)
        result["limitations"] = [b.strip() for b in bullets if b.strip()]

    return result


def load_project_index() -> dict[str, dict]:
    """Parse README.md table: filename -> {projeto, pasta, status}."""
    if not README_INDEX.exists():
        return {}
    text = README_INDEX.read_text(encoding="utf-8", errors="replace")
    projects = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*(\S+\.md)\s*\|\s*(.+?)\s*\|\s*(\S+?)\s*\|\s*(.+?)\s*\|", line)
        if m:
            fname, nome, pasta, status = m.groups()
            projects[fname] = {
                "nome": nome.strip(),
                "pasta": pasta.strip(),
                "status": status.strip(),
                "context_file": PROJECT_CONTEXT_DIR / fname,
            }
    return projects


# ---------------------------------------------------------------------------
# Verificacoes de projeto
# ---------------------------------------------------------------------------

@dataclass
class ProjectHealth:
    name: str
    folder: str
    status: str
    exists: bool
    is_git: bool
    last_commit_days: Optional[int]
    dirty_files: int
    large_files: list[str]          # formatted as "path (NMB) [categoria]"
    credential_hits: list[str]
    missing_github_required: list[str]
    missing_github_recommended: list[str]
    known_issues: list[str]         # ALL bullets from "Limitacoes" section
    code_issues: list[str]          # grep-detected fragile patterns in source code
    suggested_tasks: list[str] = field(default_factory=list)


def check_git(project_path: Path) -> tuple[bool, Optional[int], int]:
    """Returns (is_git, last_commit_days_ago, dirty_file_count)."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=project_path
        )
        if r.returncode != 0:
            return False, None, 0
        log = subprocess.run(
            ["git", "log", "-1", "--format=%ci"],
            capture_output=True, text=True, cwd=project_path
        ).stdout.strip()
        days = None
        if log:
            try:
                dt = datetime.fromisoformat(log[:19])
                days = (datetime.now() - dt).days
            except ValueError:
                pass
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=project_path
        ).stdout.strip().splitlines()
        return True, days, len([l for l in dirty if l.strip()])
    except Exception:
        return False, None, 0


def _is_skippable(path: Path, project_path: Path) -> bool:
    rel_parts = path.relative_to(project_path).parts
    return any(part in SKIP_DIRS for part in rel_parts)


def check_large_files(project_path: Path, max_size_mb: float = 5.0) -> list[str]:
    """Find large/sensitive files, classified by type."""
    large_extensions = {".db", ".sqlite3", ".gguf", ".bin", ".pt", ".pkl", ".h5",
                        ".safetensors", ".parquet", ".zip", ".tar", ".gz", ".sqlite", ".pth"}
    hits = []
    try:
        for f in project_path.rglob("*"):
            if _is_skippable(f, project_path):
                continue
            if f.is_file() and f.suffix.lower() in large_extensions:
                size_mb = f.stat().st_size / 1024 / 1024
                if size_mb > max_size_mb:
                    rel = str(f.relative_to(project_path))
                    category = classify_large_file(rel)
                    hits.append((rel, size_mb, category))
    except PermissionError:
        pass
    # Sort: temporario first (most actionable), then by size desc
    hits.sort(key=lambda x: (x[2] != "temporario", -x[1]))
    return [f"{rel} ({size:.0f}MB) [{cat}]" for rel, size, cat in hits[:8]]


def check_credentials(project_path: Path) -> list[str]:
    """Scan source files for possible hardcoded credentials."""
    hits = []
    patterns = [re.compile(p, re.IGNORECASE) for p in CREDENTIAL_PATTERNS]
    try:
        for ext in ["*.py", "*.env", "*.json", "*.yaml", "*.yml", "*.cfg", "*.ini"]:
            for f in project_path.rglob(ext):
                if _is_skippable(f, project_path):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    for pat in patterns:
                        if pat.search(text):
                            hits.append(str(f.relative_to(project_path)))
                            break
                except (PermissionError, OSError):
                    pass
    except Exception:
        pass
    return list(set(hits))[:5]


def check_github_readiness(project_path: Path) -> tuple[list[str], list[str]]:
    """Returns (missing_required, missing_recommended)."""
    missing_req = []
    missing_rec = []
    for fname, msg in GITHUB_REQUIRED:
        if not (project_path / fname).exists():
            missing_req.append(msg)
    has_req = (project_path / "requirements.txt").exists()
    has_pyp = (project_path / "pyproject.toml").exists()
    if not has_req and not has_pyp:
        missing_rec.append("requirements.txt ausente (ou pyproject.toml)")
    return missing_req, missing_rec


# ---------------------------------------------------------------------------
# Grep de padroes frageis no codigo
# ---------------------------------------------------------------------------

# Each entry: (pattern, message_template)
# {file} and {match} are substituted at match time
_CODE_CHECKS = [
    # Hardcoded exchange rates
    (r"BRL[_\s]*TO[_\s]*USD\s*=\s*[\d.]+",
     "taxa BRL/USD hardcoded em {file} — requer atualizacao manual periodica"),
    (r"USD[_\s]*TO[_\s]*BRL\s*=\s*[\d.]+",
     "taxa USD/BRL hardcoded em {file} — requer atualizacao manual periodica"),
    # Ollama port hardcoded (might be wrong if project uses llama-server)
    (r"localhost:11434",
     "porta Ollama hardcoded (11434) em {file} — confirmar se deveria ser llama-server"),
    # llama-server port hardcoded
    (r"localhost:8081|localhost:8082",
     "porta llama-server hardcoded em {file} — confirmar se endpoint ainda e valido"),
    # Hardcoded API keys that look like env var names but are set directly
    (r'APIFY_TOKEN\s*=\s*["\'][A-Za-z0-9_\-]{10,}',
     "token APIFY hardcoded em {file} — mover para variavel de ambiente"),
    # Temp directories with content (checked separately, not via grep)
]

_TEMP_DIR_PATTERNS = re.compile(
    r"^(tmp_|_tmp|temp_|_temp|_socios_tmp|_tmp_check|scratch_|debug_)", re.IGNORECASE
)


def check_code_patterns(project_path: Path) -> list[str]:
    """
    Grep Python source files for known fragile patterns.
    Returns human-readable issue strings.
    """
    issues = []
    seen = set()
    compiled = [(re.compile(pat, re.IGNORECASE), msg) for pat, msg in _CODE_CHECKS]

    try:
        for f in project_path.rglob("*.py"):
            if _is_skippable(f, project_path):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                rel = str(f.relative_to(project_path))
                for pat, msg_template in compiled:
                    m = pat.search(text)
                    if m:
                        issue = msg_template.format(file=rel, match=m.group(0)[:60])
                        if issue not in seen:
                            seen.add(issue)
                            issues.append(issue)
            except (PermissionError, OSError):
                pass
    except Exception:
        pass

    # Check for non-empty temp directories
    try:
        for d in project_path.iterdir():
            if d.is_dir() and _TEMP_DIR_PATTERNS.match(d.name):
                contents = list(d.iterdir())
                if contents:
                    total_mb = sum(
                        f.stat().st_size for f in d.rglob("*") if f.is_file()
                    ) / 1024 / 1024
                    issue = (f"diretorio temporario nao-vazio: {d.name}/ "
                             f"({len(contents)} itens, ~{total_mb:.0f}MB) — candidato a limpeza")
                    if issue not in seen:
                        seen.add(issue)
                        issues.append(issue)
    except Exception:
        pass

    return issues[:10]


# ---------------------------------------------------------------------------
# Analise completa por projeto
# ---------------------------------------------------------------------------

def analyze_project(name: str, folder: str, status: str, context_file: Path) -> ProjectHealth:
    project_path = PROJECTS_ROOT / folder
    exists = project_path.exists() and project_path.is_dir()

    is_git, last_commit_days, dirty = check_git(project_path) if exists else (False, None, 0)
    large = check_large_files(project_path) if exists else []
    creds = check_credentials(project_path) if exists else []
    miss_req, miss_rec = check_github_readiness(project_path) if exists else (["diretorio nao existe"], [])
    code_issues = check_code_patterns(project_path) if exists else []

    known_issues = []
    if context_file.exists():
        ctx = parse_context_file(context_file)
        known_issues = ctx["limitations"]  # ALL bullets, unfiltered

    h = ProjectHealth(
        name=name, folder=folder, status=status,
        exists=exists, is_git=is_git,
        last_commit_days=last_commit_days,
        dirty_files=dirty,
        large_files=large,
        credential_hits=creds,
        missing_github_required=miss_req,
        missing_github_recommended=miss_rec,
        known_issues=known_issues,
        code_issues=code_issues,
    )
    h.suggested_tasks = generate_suggestions(h)
    return h


# ---------------------------------------------------------------------------
# Geracao de sugestoes
# ---------------------------------------------------------------------------

def generate_suggestions(h: ProjectHealth) -> list[str]:
    suggestions = []

    if not h.exists:
        return [f"Criar diretorio do projeto em <workspace>/{h.folder}"]

    if not h.is_git:
        suggestions.append("Inicializar repositorio git (git init + commit inicial)")

    if h.last_commit_days is not None and h.last_commit_days > 30:
        suggestions.append(
            f"Revisar projeto: ultimo commit ha {h.last_commit_days} dias — "
            "pode precisar de atualizacao de dependencias"
        )

    if h.dirty_files > 3:
        suggestions.append(
            f"Commitar ou descartar {h.dirty_files} arquivos modificados nao commitados"
        )

    if h.credential_hits:
        files = ", ".join(h.credential_hits[:3])
        suggestions.append(f"Revisar possiveis credenciais hardcoded em: {files}")

    # Large files: split by category for more targeted suggestions
    temp_files = [f for f in h.large_files if "[temporario]" in f]
    model_files = [f for f in h.large_files if "[modelo]" in f]
    other_large = [f for f in h.large_files
                   if "[temporario]" not in f and "[modelo]" not in f
                   and "[binario-intencional]" not in f]

    if temp_files:
        files = ", ".join(f.split(" [")[0] for f in temp_files[:3])
        suggestions.append(f"[limpeza] Deletar arquivos temporarios: {files}")

    if model_files:
        files = ", ".join(f.split(" [")[0] for f in model_files[:2])
        suggestions.append(f"[gitignore] Adicionar ao .gitignore modelos grandes: {files}")

    if other_large:
        files = ", ".join(f.split(" [")[0] for f in other_large[:3])
        suggestions.append(f"Adicionar ao .gitignore arquivos grandes antes do GitHub: {files}")

    if ".gitignore ausente" in h.missing_github_required:
        suggestions.append("Criar .gitignore adequado para Python/dados antes de subir ao GitHub")

    if "README ausente" in h.missing_github_required:
        suggestions.append("Criar README.md com descricao do projeto, stack e instrucoes de uso")

    if "requirements.txt ausente (ou pyproject.toml)" in h.missing_github_recommended:
        suggestions.append("Gerar requirements.txt (pip freeze > requirements.txt) para reproducibilidade")

    # Grep-detected code issues — all of them
    for issue in h.code_issues:
        suggestions.append(f"[codigo] {issue}")

    # Known issues from context file — ALL bullets, no keyword filter, no cap
    for issue in h.known_issues:
        suggestions.append(f"[contexto] {issue}")

    return suggestions


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(projects: list[ProjectHealth], github_only: bool = False):
    print(f"\n{'='*70}")
    print(f" DIAGNOSTICO DE PROJETOS  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    total = len(projects)
    healthy = sum(1 for p in projects if not p.suggested_tasks)
    print(f"\n  {total} projetos analisados  {healthy} sem pendencias, {total-healthy} com sugestoes\n")

    for p in sorted(projects, key=lambda x: (not x.exists, len(x.suggested_tasks)), reverse=True):
        icon = "OK" if not p.suggested_tasks else "!!"
        print(f"\n  [{icon}] {p.name} ({p.folder})  {p.status}")

        if not p.exists:
            print(f"       DIRETORIO NAO ENCONTRADO: <workspace>/{p.folder}")
            continue

        git_str = (f"git: ultimo commit {p.last_commit_days}d atras"
                   if p.last_commit_days is not None else "git: sem commits")
        if not p.is_git:
            git_str = "nao e um repositorio git"
        print(f"       {git_str}" + (f", {p.dirty_files} arquivos sujos" if p.dirty_files else ""))

        if not github_only and p.credential_hits:
            print(f"       ATENCAO credenciais possiveis: {', '.join(p.credential_hits[:3])}")

        if p.large_files and not github_only:
            print(f"       Arquivos grandes:")
            for lf in p.large_files[:5]:
                print(f"         {lf}")

        if p.missing_github_required:
            print(f"       GitHub required: {'; '.join(p.missing_github_required)}")

        if p.code_issues and not github_only:
            print(f"       Padroes frageis no codigo:")
            for ci in p.code_issues[:3]:
                print(f"         - {ci}")

        if p.known_issues and not github_only:
            print(f"       Limitacoes conhecidas ({len(p.known_issues)}):")
            for ki in p.known_issues:
                print(f"         - {ki}")

        if p.suggested_tasks:
            # Group by prefix for readability
            fs_tasks = [t for t in p.suggested_tasks
                        if not t.startswith("[contexto]") and not t.startswith("[codigo]")]
            ctx_tasks = [t for t in p.suggested_tasks if t.startswith("[contexto]")]
            code_tasks = [t for t in p.suggested_tasks if t.startswith("[codigo]")]

            print(f"       Sugestoes filesystem/git:")
            for t in fs_tasks[:5]:
                print(f"         - {t}")
            if code_tasks:
                print(f"       Sugestoes codigo:")
                for t in code_tasks[:3]:
                    print(f"         - {t}")
            if ctx_tasks:
                print(f"       Sugestoes contexto (todas as limitacoes conhecidas):")
                for t in ctx_tasks:
                    print(f"         - {t[len('[contexto] '):]}")

    print(f"\n{'='*70}\n")


def build_yaml_suggestions(projects: list[ProjectHealth]) -> list[dict]:
    """Build list of backlog-ready task dicts from suggestions."""
    tasks = []
    try:
        data = yaml.safe_load(BACKLOG_PATH.read_text(encoding="utf-8")) or {"tasks": []}
        existing_ids = [int(t["id"]) for t in data["tasks"] if str(t["id"]).isdigit()]
        next_id = max(existing_ids, default=0) + 1
    except Exception:
        next_id = 100

    for p in projects:
        for suggestion in p.suggested_tasks:
            if "Criar diretorio" in suggestion:
                continue
            # Tag source type for backlog metadata
            if suggestion.startswith("[contexto]"):
                source = "contexto"
                task_text = suggestion[len("[contexto] "):]
            elif suggestion.startswith("[codigo]"):
                source = "codigo"
                task_text = suggestion[len("[codigo] "):]
            elif suggestion.startswith("[limpeza]"):
                source = "limpeza"
                task_text = suggestion[len("[limpeza] "):]
            elif suggestion.startswith("[gitignore]"):
                source = "gitignore"
                task_text = suggestion[len("[gitignore] "):]
            else:
                source = "filesystem"
                task_text = suggestion

            tasks.append({
                "id": str(next_id).zfill(3),
                "project": p.folder,
                "task": task_text,
                "test_cmd": None,
                "status": "pending",
                "priority": 3 if source == "contexto" else 5,
                "_source": source,
                "_generated": datetime.now().strftime("%Y-%m-%d"),
            })
            next_id += 1
    return tasks


def interactive_add_to_backlog(projects: list[ProjectHealth]):
    """Interactive: show each suggestion and ask user to approve."""
    suggestions = build_yaml_suggestions(projects)
    if not suggestions:
        print("Nenhuma sugestao gerada.")
        return

    approved = []
    print(f"\n{len(suggestions)} sugestoes geradas. Revisar cada uma (s/n/q):\n")
    for task in suggestions:
        src = task.get("_source", "")
        print(f"  [{src}] Projeto: {task['project']}")
        print(f"          Tarefa:  {task['task']}")
        ans = input("  Adicionar ao backlog? [s/n/q] ").strip().lower()
        if ans == "q":
            break
        if ans == "s":
            approved.append(task)
        print()

    if not approved:
        print("Nenhuma tarefa adicionada.")
        return

    data = yaml.safe_load(BACKLOG_PATH.read_text(encoding="utf-8")) or {"tasks": []}
    for t in approved:
        t.pop("_source", None)
        t.pop("_generated", None)
        data["tasks"].append(t)
    BACKLOG_PATH.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8"
    )
    print(f"\n{len(approved)} tarefa(s) adicionada(s) ao backlog.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Diagnostico de saude dos projetos")
    parser.add_argument("--report", action="store_true", default=True,
                        help="Imprimir relatorio (default)")
    parser.add_argument("--suggest", action="store_true",
                        help="Imprimir tarefas sugeridas em YAML")
    parser.add_argument("--add-to-backlog", action="store_true", dest="add_to_backlog",
                        help="Interativo: aprovar tarefas e adicionar ao backlog.yaml")
    parser.add_argument("--github-only", action="store_true", dest="github_only",
                        help="Mostrar apenas verificacoes de prontidao para GitHub")
    parser.add_argument("--project", help="Analisar apenas um projeto (nome da pasta)")
    args = parser.parse_args()

    project_index = load_project_index()
    if not project_index:
        print(f"Nao foi possivel carregar o indice de projetos de {README_INDEX}")
        sys.exit(1)

    results = []
    for fname, info in project_index.items():
        if args.project and info["pasta"] != args.project:
            continue
        h = analyze_project(
            name=info["nome"],
            folder=info["pasta"],
            status=info["status"],
            context_file=info["context_file"],
        )
        results.append(h)

    if not results:
        print(f"Projeto '{args.project}' nao encontrado no indice.")
        sys.exit(1)

    if args.suggest:
        tasks = build_yaml_suggestions(results)
        print(yaml.dump({"suggested_tasks": tasks}, allow_unicode=True, default_flow_style=False))
        return

    if args.add_to_backlog:
        interactive_add_to_backlog(results)
        return

    print_report(results, github_only=args.github_only)


if __name__ == "__main__":
    main()
