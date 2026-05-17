# -*- coding: utf-8 -*-
"""
Orquestrador de desenvolvimento autonomo local.

Pipeline:
  Warmup           -> ping Ollama para forcar carga do modelo na VRAM
  Tentativas 1-2   -> qwen3coder-local (Ollama A3B, rapido ~21 tok/s)
  Tentativa 3      -> gemma4:26b (Ollama, melhor qualidade geral 78%)
                      ou qwen3-coder-next via llama.cpp (use_llama_as_final=true)
  Falha/duvida     -> gera handoff.md para colar no Claude Code

Uso:
  python orchestrator.py --task "descricao" --project /caminho/do/projeto
  python orchestrator.py --loop --project /caminho/do/projeto
  python orchestrator.py --status
  python orchestrator.py --retry-handoffs   # re-fila tarefas waiting_handoff -> pending
"""

import argparse
import contextlib
import json
import logging
import os
import py_compile
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.yaml"
ROUTING_RULES_PATH = Path(__file__).parent / "routing_rules.yaml"

# Keywords that identify a refactoring task — triggers API-preservation prefix
_REFACTOR_KEYWORDS = ("refactor", "refactoring", "reorganize", "reorganizar", "reestruturar",
                      "extrair funcao", "extract function", "deduplicar", "deduplicate")

_REFACTOR_PREFIX = (
    "IMPORTANT: preserve ALL existing public function, method, and class names exactly. "
    "Callers must not need to change. You may restructure internals freely.\n\n"
)

# Indicators that a task modifies existing list/dict literals (two-category check)
_PRESERVE_LIST_VERBS = ("add", "adicionar", "update", "atualizar", "include", "inserir", "insert")
_PRESERVE_LIST_NOUNS = ("field", "campo", "key", "chave", "attribute", "atributo",
                         "flag", "property", "propriedade", "entry", "entrada",
                         "each source", "cada fonte", "each item", "cada item",
                         "each entry", "cada entrada", "sources list", "lista de")

_PRESERVE_LIST_PREFIX = (
    "IMPORTANT: when modifying list or dict literals, your SEARCH/REPLACE blocks MUST include "
    "ALL existing entries — do NOT omit or drop any. Only add or modify fields within entries.\n\n"
)


def _task_touches_list(task_lower: str) -> bool:
    """Return True if the task looks like it modifies entries in an existing list/dict literal."""
    has_verb = any(v in task_lower for v in _PRESERVE_LIST_VERBS)
    has_noun = any(n in task_lower for n in _PRESERVE_LIST_NOUNS)
    return has_verb and has_noun


# ---------------------------------------------------------------------------
# Project constraints — inject architectural rules before sending to aider
# ---------------------------------------------------------------------------

# Directory containing per-project constraint snippets (one .md per project folder).
# Configure via env var LOCAL_DEV_PROJECT_CONTEXT; defaults to ../_project_context relative to repo root.
import os as _os
_PROJECT_CONTEXT_DIR = Path(_os.environ.get(
    "LOCAL_DEV_PROJECT_CONTEXT",
    str(Path(__file__).resolve().parent.parent.parent / "_project_context"),
))

# Bullet fragments that signal an architectural constraint (must follow)
_CONSTRAINT_KEYWORDS = (
    "obrigatório", "obrigatorio",
    "não negociável", "nao negociavel",
    "nunca ",
    "proibido",
    "async-only",
    "nao deve", "não deve",
    "nao pode", "não pode",
    "nao usar", "não usar",
    "exclusivamente",          # "usa aiohttp exclusivamente"
    "nao negociavel",
    "nao editar sem",          # "não editar sem validar test_X.py"
)

# Bullet fragments that mark a pending task / not-yet-done feature — exclude these
_PENDING_EXCLUSIONS = (
    "pendente", "pending",
    "aguardando",
    "nao implementad", "não implementad",
    "nao testado", "não testado",
    "falta ",
    "fase ",
    "compilacao", "compilação",
    "download ",
    "aprovacao", "aprovação",
    "concluida", "concluído", "concluido",
    "ainda nao",
)

# Lazy-loaded cache: {folder_name: context_file_path}
_CONTEXT_INDEX: dict[str, Path] = {}


def _load_context_index() -> dict[str, Path]:
    """Parse _project_context/README.md table into {folder: Path}."""
    index_path = _PROJECT_CONTEXT_DIR / "README.md"
    if not index_path.exists():
        return {}
    result = {}
    for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\|\s*(\S+\.md)\s*\|\s*.+?\s*\|\s*(\S+?)\s*\|", line)
        if m:
            fname, folder = m.group(1), m.group(2)
            result[folder] = _PROJECT_CONTEXT_DIR / fname
    return result


def _extract_constraints(context_file: Path) -> list[str]:
    """
    Extract architectural constraint bullets from a _project_context/*.md file.
    Returns only bullets that are rules the model must respect, not pending tasks.
    """
    text = context_file.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"##\s+Limita[çc][aã]?[oe].*?\n(.*?)(?=\n##|\Z)", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    bullets = re.findall(r"^[-*]\s+(.+)", m.group(1), re.MULTILINE)
    constraints = []
    for b in bullets:
        b = b.strip()
        lower = b.lower()
        if any(kw in lower for kw in _PENDING_EXCLUSIONS):
            continue
        if any(kw in lower for kw in _CONSTRAINT_KEYWORDS):
            constraints.append(b)
    return constraints


_MAX_CANONICAL_LINES = 100   # max lines injected per canonical source file
_PROMPT_SIZE_WARN = 24_000   # chars (~6k tokens) — warn if exceeded


def resolve_canonical_context(
    canonical_sources: list[str],
    project_path: str,
) -> str:
    """
    Read each file listed in canonical_sources and return a context block to
    prepend to the task. Paths can be absolute or relative to project_path.
    Missing or unreadable files are skipped with a warning (never crash).
    Files exceeding _MAX_CANONICAL_LINES are truncated.
    """
    if not canonical_sources:
        return ""
    blocks = []
    for src in canonical_sources:
        p = Path(src)
        if not p.is_absolute():
            p = Path(project_path) / src
        if not p.exists():
            logging.warning("canonical_sources: arquivo nao encontrado — %s", p)
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            truncated = len(lines) > _MAX_CANONICAL_LINES
            if truncated:
                lines = lines[:_MAX_CANONICAL_LINES]
            content = "\n".join(lines)
            note = f" (truncado em {_MAX_CANONICAL_LINES} linhas)" if truncated else ""
            blocks.append(f"### {src}{note}\n```\n{content}\n```")
        except Exception as e:
            logging.warning("canonical_sources: erro ao ler %s — %s", p, e)
    if not blocks:
        return ""
    return (
        "## FONTES CANONICAS — leia antes de agir\n"
        "Estes arquivos sao a fonte autoritativa para esta tarefa. "
        "Nao use dados de outros arquivos ou memoria de sessoes anteriores.\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
    )


def load_project_constraints(project_path: str) -> str:
    """
    Return a constraints block to prepend to the task, or "" if none found.

    Priority:
      1. AGENTS.md in project root  — user-maintained, injected verbatim
      2. _project_context/*.md      — constraint bullets derived automatically
    """
    global _CONTEXT_INDEX

    # 1. AGENTS.md: user-maintained, full control
    agents_md = Path(project_path) / "AGENTS.md"
    if agents_md.exists():
        content = agents_md.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            return f"PROJECT CONSTRAINTS (AGENTS.md):\n{content}\n\n"

    # 2. Derive from _project_context/*.md
    if not _CONTEXT_INDEX:
        _CONTEXT_INDEX = _load_context_index()
    folder = Path(project_path).name
    ctx_file = _CONTEXT_INDEX.get(folder)
    if not ctx_file or not ctx_file.exists():
        return ""
    constraints = _extract_constraints(ctx_file)
    if not constraints:
        return ""
    lines = "\n".join(f"- {c}" for c in constraints)
    return f"PROJECT CONSTRAINTS:\n{lines}\n\n"


class OrchestratorConfig:
    def __init__(self, config_path: Path = CONFIG_PATH):
        if not config_path.exists():
            raise FileNotFoundError(f"config.yaml nao encontrado: {config_path}")
        with open(config_path, encoding="utf-8") as f:
            self._cfg = yaml.safe_load(f)

    @property
    def ollama_url(self) -> str:
        return self._cfg["endpoints"]["ollama"]["base_url"]

    @property
    def ollama_key(self) -> str:
        return self._cfg["endpoints"]["ollama"]["api_key"]

    @property
    def ollama_model(self) -> str:
        return self._cfg["endpoints"]["ollama"]["model"]

    @property
    def gemma4_url(self) -> str:
        return self._cfg["endpoints"]["gemma4"]["base_url"]

    @property
    def gemma4_key(self) -> str:
        return self._cfg["endpoints"]["gemma4"]["api_key"]

    @property
    def gemma4_model(self) -> str:
        return self._cfg["endpoints"]["gemma4"]["model"]

    @property
    def gemma4_task_prefix(self) -> str:
        return self._cfg["endpoints"]["gemma4"].get("task_prefix", "")

    @property
    def llama_url(self) -> str:
        return self._cfg["endpoints"]["llama_cpp"]["base_url"]

    @property
    def llama_key(self) -> str:
        return self._cfg["endpoints"]["llama_cpp"]["api_key"]

    @property
    def llama_model(self) -> str:
        return self._cfg["endpoints"]["llama_cpp"]["model"]

    @property
    def max_attempts(self) -> int:
        return self._cfg["escalation"]["max_attempts"]

    @property
    def ollama_attempts(self) -> int:
        """Number of attempts using the fast ollama slot before switching to gemma4/llama."""
        return self._cfg["escalation"].get("ollama_attempts", 2)

    @property
    def use_llama_as_final(self) -> bool:
        """If True, use llama_cpp on final attempt instead of gemma4."""
        return self._cfg["escalation"].get("use_llama_as_final", False)

    @property
    def test_timeout(self) -> int:
        return self._cfg["escalation"]["test_timeout_seconds"]

    @property
    def aider_timeout(self) -> int:
        return self._cfg["escalation"]["aider_timeout_seconds"]

    @property
    def uncertainty_phrases(self) -> list[str]:
        # Accepts in either escalation: or aider: section for backwards compat
        return (
            self._cfg["escalation"].get("uncertainty_phrases")
            or self._cfg.get("aider", {}).get("uncertainty_phrases", [])
        )

    @property
    def logs_dir(self) -> Path:
        return Path(self._cfg["paths"]["logs"])

    @property
    def handoffs_dir(self) -> Path:
        return Path(self._cfg["paths"]["handoffs"])

    @property
    def backlog_path(self) -> Path:
        return Path(self._cfg["paths"]["backlog"])

    @property
    def projects_root(self) -> Path:
        return Path(self._cfg["paths"]["projects_root"])

    @property
    def aider_map_tokens(self) -> int:
        return self._cfg.get("aider", {}).get("map_tokens", 512)

    @property
    def warmup_enabled(self) -> bool:
        return self._cfg.get("aider", {}).get("warmup", True)

    @property
    def auto_commit(self) -> bool:
        return self._cfg.get("aider", {}).get("auto_commit", False)

    def test_cmd_for(self, project_name: str) -> Optional[str]:
        projects = self._cfg.get("projects", {})
        return projects.get(project_name, {}).get("test_cmd")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AttemptResult:
    attempt_number: int
    model_used: str           # "ollama" | "llama_cpp"
    aider_output: str
    test_output: str
    exit_code: int
    escalation_triggered: bool
    escalation_reason: Optional[str]
    modified_files: list[str] = field(default_factory=list)
    git_diff: str = ""
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Escalation detector
# ---------------------------------------------------------------------------

class EscalationDetector:
    def __init__(self, config: OrchestratorConfig):
        self.cfg = config

    def check_uncertainty(self, output: str) -> tuple[bool, str]:
        lower = output.lower()
        for phrase in self.cfg.uncertainty_phrases:
            if phrase in lower:
                return True, f"uncertainty phrase: '{phrase}'"
        return False, ""

    def check_same_error(self, attempts: list[AttemptResult]) -> bool:
        if len(attempts) < 2:
            return False
        last_two = [a.test_output for a in attempts[-2:]]
        return (
            last_two[0]
            and last_two[1]
            and last_two[0].strip() == last_two[1].strip()
            and last_two[0].strip() != ""
        )

    def check_loop(self, attempts: list[AttemptResult]) -> bool:
        if len(attempts) < 3:
            return False
        diffs = [a.git_diff for a in attempts[-3:]]
        return diffs[0] and all(d == diffs[0] for d in diffs)

    def should_escalate(
        self, attempt: AttemptResult, all_attempts: list[AttemptResult]
    ) -> tuple[bool, str]:
        unc, reason = self.check_uncertainty(attempt.aider_output)
        if unc:
            return True, reason
        if self.check_same_error(all_attempts):
            return True, "same_error_twice"
        if self.check_loop(all_attempts):
            return True, "loop_detected"
        return False, ""


# ---------------------------------------------------------------------------
# Model warmup
# ---------------------------------------------------------------------------

def warmup_model(base_url: str, model: str, api_key: str, timeout: int = 30) -> bool:
    """
    Send a 1-token request via /api/generate (native Ollama) to force VRAM load
    before the first real task. Returns True if successful.
    """
    # Try native Ollama endpoint first (faster model load signal)
    generate_url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": "hi",
        "stream": False,
        "options": {"num_predict": 1},
    }
    req = urllib.request.Request(
        generate_url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        t0 = time.time()
        urllib.request.urlopen(req, timeout=timeout).read()
        print(f"  Warmup OK ({time.time()-t0:.1f}s) — modelo carregado na VRAM")
        return True
    except Exception as e:
        print(f"  Warmup falhou ({e}) — continuando sem warmup")
        return False


# ---------------------------------------------------------------------------
# Generated-file validator
# ---------------------------------------------------------------------------

def validate_generated_files(project_path: str, modified_files: list[str]) -> tuple[bool, str]:
    """
    Run py_compile on every .py file that aider modified.
    Returns (True, "") on success, (False, error_message) on syntax error.
    """
    for rel_path in modified_files:
        if not rel_path.endswith(".py"):
            continue
        abs_path = os.path.join(project_path, rel_path)
        if not os.path.exists(abs_path):
            continue
        try:
            py_compile.compile(abs_path, doraise=True)
        except py_compile.PyCompileError as e:
            return False, f"SyntaxError in {rel_path}: {e}"
    return True, ""


# ---------------------------------------------------------------------------
# Aider runner
# ---------------------------------------------------------------------------

def run_aider(
    model: str,
    api_base: str,
    api_key: str,
    task: str,
    project_path: str,
    timeout: int = 300,
    map_tokens: int = 512,
    dry_run: bool = False,
    read_files: Optional[list[str]] = None,
) -> tuple[str, int]:
    """Run aider as subprocess and return (output, exit_code)."""
    env = os.environ.copy()
    env["OPENAI_API_BASE"] = api_base
    env["OPENAI_API_KEY"] = api_key

    cmd = [
        "aider",
        "--model", f"openai/{model}",
        "--yes-always",
        "--no-auto-commits",
        "--message", task,
        "--no-stream",
        "--no-pretty",              # disable prompt_toolkit (avoids xterm crash)
        "--no-fancy-input",         # no interactive input
        "--no-check-update",        # skip update check
        "--no-show-model-warnings", # prevents browser opening for unknown models
        "--no-detect-urls",         # prevents aider from scraping URLs in task message
        "--map-tokens", str(map_tokens),
    ]

    # Reference files aider can read but won't modify (e.g. AGENTS.md)
    for rf in (read_files or []):
        cmd.extend(["--read", rf])

    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_path,
            env=env,
            timeout=timeout,
        )
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s", 124
    except FileNotFoundError:
        return "ERROR: aider not found in PATH", 127


def run_integrity_check(
    integrity_cmd: str,
    project_path: str,
    timeout: int = 60,
) -> tuple[bool, str]:
    """
    Run a project-specific integrity validation command after tests pass.
    Returns (passed, output). Empty integrity_cmd always returns (True, "").
    """
    if not integrity_cmd:
        return True, ""
    try:
        result = subprocess.run(
            integrity_cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=project_path,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, f"INTEGRITY TIMEOUT after {timeout}s"
    except Exception as e:
        return False, f"integrity check error: {e}"


def run_tests(test_cmd: str, project_path: str, timeout: int = 90) -> tuple[str, int]:
    """Run test command and return (output, exit_code)."""
    if not test_cmd:
        return "(no test_cmd configured)", 0

    try:
        result = subprocess.run(
            test_cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=project_path,
            timeout=timeout,
        )
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return f"TEST TIMEOUT after {timeout}s", 124


def get_git_diff(project_path: str) -> tuple[str, list[str]]:
    """Return (diff_text, modified_files_list). Returns empty results for non-git dirs."""
    try:
        # Check if this is actually a git repo first
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=project_path
        )
        if check.returncode != 0:
            logging.warning("get_git_diff: %s is not a git repo — skipping diff", project_path)
            return "(not a git repo)", []

        full_diff = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, cwd=project_path
        ).stdout

        stat = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, cwd=project_path
        ).stdout

        files = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=project_path
        ).stdout.strip().splitlines()

        return (full_diff or stat) or "(no changes)", files
    except Exception as e:
        return f"(git diff error: {e})", []


def auto_commit_changes(
    project_path: str, task_id: str, task_text: str, model_used: str
) -> tuple[bool, str]:
    """
    Stage all modified tracked files and create a git commit.
    Returns (success, message).
    Skips if there is nothing staged after `git add -u`.
    """
    try:
        # Stage only already-tracked files (never adds untracked secrets)
        subprocess.run(["git", "add", "-u"], cwd=project_path, capture_output=True)
        # Check if there is anything to commit
        status = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=project_path
        )
        if not status.stdout.strip():
            return True, "nothing to commit (no tracked files changed)"
        short_task = task_text[:72].replace("\n", " ")
        msg = f"auto: [{task_id}] {short_task}\n\nModel: {model_used} via orchestrator"
        result = subprocess.run(
            ["git", "commit", "-m", msg],
            capture_output=True, text=True, cwd=project_path
        )
        if result.returncode == 0:
            sha = result.stdout.strip().splitlines()[0] if result.stdout else ""
            return True, f"committed: {sha}"
        return False, result.stderr.strip()[:200]
    except Exception as e:
        return False, f"commit error: {e}"


def create_pre_task_snapshot(project_path: str, task_id: str) -> tuple[bool, str]:
    """
    Create a lightweight git tag before a destructive task for easy rollback.
    Tag name includes timestamp to avoid conflicts on retries.
    Returns (success, tag_name_or_error). Safe to call on non-git dirs.
    """
    try:
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=project_path,
        )
        if check.returncode != 0:
            return False, "not a git repo"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        raw_tag = f"pre-task-{task_id}-{ts}"
        tag = re.sub(r"[^a-zA-Z0-9._-]", "-", raw_tag)
        result = subprocess.run(
            ["git", "tag", tag],
            capture_output=True, text=True, cwd=project_path,
        )
        if result.returncode == 0:
            return True, tag
        return False, result.stderr.strip()[:100]
    except Exception as e:
        return False, f"snapshot error: {e}"


def notify_handoff(project: str, task_id: str, handoff_path: str):
    """
    Send a Windows toast notification when a handoff is generated.
    Falls back to a system beep if the PowerShell toast fails.
    The notification stays in the Action Center until dismissed.
    """
    title = f"Handoff gerado — {project}"
    body = f"Tarefa {task_id} escalou. Cole o handoff no Claude Code.\n{Path(handoff_path).name}"
    ps_cmd = (
        f'$t="{title}"; $b="{body}"; '
        r'Add-Type -AssemblyName System.Windows.Forms; '
        r'$n=New-Object System.Windows.Forms.NotifyIcon; '
        r'$n.Icon=[System.Drawing.SystemIcons]::Information; '
        r'$n.Visible=$true; '
        r'$n.ShowBalloonTip(8000,$t,$b,[System.Windows.Forms.ToolTipIcon]::Warning); '
        r'Start-Sleep -Milliseconds 8500; $n.Dispose()'
    )
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception:
        # Fallback: console bell
        print("\a", end="", flush=True)


# ---------------------------------------------------------------------------
# Handoff packager
# ---------------------------------------------------------------------------

class HandoffPackager:
    TEMPLATE = """\
# HANDOFF -- {project} -- {timestamp}

## Tarefa original
{task}

## Por que escalou
Razao: {escalation_reason}
Tentativas: {n}
Tempo total: {elapsed}s

## O que foi tentado
{attempts_log}

## Estado atual
### Git diff:
```diff
{git_diff}
```

### Testes falhando:
```
{test_output}
```

## Hipotese do modelo local
{model_last_output}

---
Cole este arquivo em uma nova sessao do Claude Code.
Os arquivos ja estao modificados conforme o diff acima.
Nao repita as abordagens listadas.
"""

    def package(
        self,
        task: str,
        project: str,
        attempts: list[AttemptResult],
        escalation_reason: str,
        elapsed: float,
    ) -> str:
        attempts_log_lines = []
        for a in attempts:
            attempts_log_lines.append(
                f"### Tentativa {a.attempt_number} ({a.model_used})\n"
                f"- Exit code: {a.exit_code}\n"
                f"- Escalou: {a.escalation_triggered} ({a.escalation_reason or '-'})\n"
                f"- Arquivos modificados: {', '.join(a.modified_files) or 'nenhum'}\n"
                f"- Output (ultimos 500 chars):\n```\n{a.aider_output[-500:]}\n```"
            )

        last = attempts[-1] if attempts else None
        return self.TEMPLATE.format(
            project=project,
            timestamp=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
            task=task,
            escalation_reason=escalation_reason,
            n=len(attempts),
            elapsed=f"{elapsed:.1f}",
            attempts_log="\n\n".join(attempts_log_lines),
            git_diff=last.git_diff if last else "(none)",
            test_output=last.test_output if last else "(none)",
            model_last_output=last.aider_output[-1000:] if last else "(none)",
        )

    def save(self, md: str, output_dir: Path, project: str) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = output_dir / f"{project}_{ts}.md"
        fname.write_text(md, encoding="utf-8")
        return str(fname)


# ---------------------------------------------------------------------------
# Backlog manager
# ---------------------------------------------------------------------------

class BacklogManager:
    # Statuses that should NOT be picked up by next_task()
    _SKIP_STATUSES = {"in_progress", "done", "blocked", "waiting_handoff"}

    def __init__(self, backlog_path: Path):
        self.path = backlog_path

    @contextlib.contextmanager
    def _locked(self):
        """
        Atomic file lock using O_CREAT|O_EXCL (works on Windows and Linux).
        Stale locks (>30s old) are auto-cleared.
        Raises RuntimeError if lock cannot be acquired within ~2s.
        """
        lock_path = self.path.with_suffix(".lock")
        acquired = False
        for _ in range(20):  # 20 x 0.1s = 2s max wait
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                acquired = True
                break
            except FileExistsError:
                try:
                    if time.time() - lock_path.stat().st_mtime > 30:
                        lock_path.unlink(missing_ok=True)
                except OSError:
                    pass
                time.sleep(0.1)

        if not acquired:
            raise RuntimeError(f"Nao foi possivel adquirir lock do backlog: {lock_path}")

        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"tasks": []}
        with open(self.path, encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise RuntimeError(f"backlog.yaml malformado — corrija antes de continuar: {e}") from e
        return data or {"tasks": []}

    def _save(self, data: dict):
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def next_task(self) -> Optional[dict]:
        with self._locked():
            data = self._load()
            tasks = sorted(
                [t for t in data["tasks"] if t["status"] == "pending"],
                key=lambda t: t.get("priority", 99),
            )
            if not tasks:
                return None
            task = tasks[0]
            task["status"] = "in_progress"
            self._save(data)
            return task

    def mark_done(self, task_id: str):
        with self._locked():
            data = self._load()
            for t in data["tasks"]:
                if t["id"] == task_id:
                    t["status"] = "done"
            self._save(data)

    def mark_blocked(self, task_id: str, reason: str):
        with self._locked():
            data = self._load()
            for t in data["tasks"]:
                if t["id"] == task_id:
                    t["status"] = "blocked"
                    t["blocked_reason"] = reason
            self._save(data)

    def mark_handoff(self, task_id: str, handoff_path: str):
        """
        Mark task as waiting_handoff — paused until manually resolved via Claude Code.
        Change status back to 'pending' to retry, or 'done' to close.
        """
        with self._locked():
            data = self._load()
            for t in data["tasks"]:
                if t["id"] == task_id:
                    t["status"] = "waiting_handoff"
                    t["handoff_file"] = handoff_path
                    t["blocked_since"] = datetime.now().isoformat()
            self._save(data)

    def retry_handoffs(self) -> int:
        """Re-queue all waiting_handoff tasks back to pending. Returns count re-queued."""
        with self._locked():
            data = self._load()
            count = 0
            for t in data["tasks"]:
                if t["status"] == "waiting_handoff":
                    t["status"] = "pending"
                    t.pop("handoff_file", None)
                    t.pop("blocked_since", None)
                    count += 1
            if count:
                self._save(data)
        return count


# ---------------------------------------------------------------------------
# Task router (Sprint 3 Phase 2)
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    category: str            # always_local | try_local_first | always_claude
    isolation_mode: str      # host | docker
    review_type: str         # none | light | full
    max_attempts: Optional[int]   # None → use cfg.max_attempts
    handoff_tag: Optional[str]    # None | escalate_claude | send_claude
    reason: str              # why this decision was reached (audit/log)


class TaskRouter:
    """
    Loads orchestrator/routing_rules.yaml and decides per-task routing.

    Inputs (from backlog.yaml):
      - task_type: string mapped to one of the categories' `types` lists
      - destructive: bool — if True, forces always_claude (override; Sprint 9: was destructive_local)
      - critical: bool   — if True (or project marked critical), forces always_claude

    Default category if task_type is missing or unknown: try_local_first.
    """

    def __init__(self, rules_path: Path = ROUTING_RULES_PATH):
        if not rules_path.exists():
            raise FileNotFoundError(f"routing_rules.yaml nao encontrado: {rules_path}")
        with open(rules_path, encoding="utf-8") as f:
            self._rules = yaml.safe_load(f) or {}
        self._categories = self._rules.get("routing_rules", {})
        self._default_category = self._rules.get("default_category", "try_local_first")
        self._destructive_override = self._rules.get("destructive_override", True)
        self._critical_override = self._rules.get("critical_override", True)
        # Build {task_type: category_name}
        self._type_index: dict[str, str] = {}
        for cat_name, cat_def in self._categories.items():
            for t in cat_def.get("types", []) or []:
                self._type_index[t] = cat_name

    def categories(self) -> dict:
        return self._categories

    def classify(self, task_data: dict) -> RoutingDecision:
        task_type = task_data.get("task_type")
        destructive = bool(task_data.get("destructive", False))
        critical = bool(task_data.get("critical", False))

        # Overrides take precedence
        if self._critical_override and critical:
            cat_name = "always_claude"
            reason = "critical_override (project/task critical=true)"
        elif self._destructive_override and destructive:
            cat_name = "always_claude"
            reason = "destructive_override (task destructive=true → always_claude; Sprint 9)"
        elif task_type and task_type in self._type_index:
            cat_name = self._type_index[task_type]
            reason = f"task_type='{task_type}' → {cat_name}"
        else:
            cat_name = self._default_category
            reason = (
                f"default ({cat_name}) — task_type "
                f"{'missing' if not task_type else f'unknown ({task_type})'}"
            )

        cat = self._categories.get(cat_name, {}) or {}
        isolation = cat.get("isolation_mode", "host")
        review = cat.get("review_type", "none")
        max_local = cat.get("max_local_attempts")
        if cat_name == "always_claude":
            tag = "send_claude"
        elif cat_name == "try_local_first":
            tag = "escalate_claude"   # only applied if local attempts exhaust
        else:
            tag = None
        return RoutingDecision(
            category=cat_name,
            isolation_mode=isolation,
            review_type=review,
            max_attempts=max_local,
            handoff_tag=tag,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# JSONL logger
# ---------------------------------------------------------------------------

class SessionLogger:
    def __init__(self, logs_dir: Path, project: str):
        logs_dir.mkdir(parents=True, exist_ok=True)
        date = datetime.now().strftime("%Y-%m-%d")
        self.path = logs_dir / f"{project}_{date}.jsonl"

    def log(self, entry: dict):
        entry.setdefault("timestamp", datetime.now().isoformat())
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    def __init__(self, config: OrchestratorConfig):
        self.cfg = config
        self.detector = EscalationDetector(config)
        self.packager = HandoffPackager()
        self.backlog = BacklogManager(config.backlog_path)
        self._last_warmed_model: Optional[str] = None
        try:
            self.router: Optional[TaskRouter] = TaskRouter()
        except FileNotFoundError as e:
            logging.warning("TaskRouter desabilitado: %s", e)
            self.router = None

    def _resolve_preferred(self, preferred: str) -> tuple[str, str, str, str]:
        """
        Resolve a preferred_model name (e.g. 'gemma4', 'ollama') to
        (slot_name, model_name, api_base, api_key).
        Falls back to ollama slot if unknown.
        """
        if preferred == "gemma4":
            return "gemma4", self.cfg.gemma4_model, self.cfg.gemma4_url, self.cfg.gemma4_key
        if preferred in ("llama", "llama_cpp"):
            return "llama_cpp", self.cfg.llama_model, self.cfg.llama_url, self.cfg.llama_key
        # default / "ollama"
        return "ollama", self.cfg.ollama_model, self.cfg.ollama_url, self.cfg.ollama_key

    def _model_for_attempt(self, n: int) -> tuple[str, str, str, str]:
        """
        Returns (slot_name, model_name, api_base, api_key).

        Slot routing (config-driven):
          attempts 1..ollama_attempts  -> ollama  (qwen3coder-local, fast)
          remaining attempts           -> gemma4  (best overall quality, 78%)
                                      OR llama_cpp if use_llama_as_final=true
        """
        if n <= self.cfg.ollama_attempts:
            return "ollama", self.cfg.ollama_model, self.cfg.ollama_url, self.cfg.ollama_key
        if self.cfg.use_llama_as_final:
            return "llama_cpp", self.cfg.llama_model, self.cfg.llama_url, self.cfg.llama_key
        return "gemma4", self.cfg.gemma4_model, self.cfg.gemma4_url, self.cfg.gemma4_key

    def _ensure_warmup(self, model: str):
        """
        Warmup if enabled and model has changed since last warmup.
        Handles Ollama model-switch latency (unloads A3B, loads gemma4).
        """
        if not self.cfg.warmup_enabled:
            return
        if self._last_warmed_model == model:
            return
        print(f"  Aquecendo modelo '{model}' (warmup)...")
        warmup_model(self.cfg.ollama_url, model, self.cfg.ollama_key)
        self._last_warmed_model = model

    def _inject_task_prefix(self, task: str, slot: str) -> str:
        """
        Inject slot-specific and task-type prefixes before sending to aider.
        Order: slot prefix → refactor prefix → task
        """
        result = task
        lower = task.lower()
        # List-preservation prefix: prevent models from dropping list entries
        if _task_touches_list(lower):
            result = _PRESERVE_LIST_PREFIX + result
        # Refactor prefix: ensure public API is preserved
        if any(kw in lower for kw in _REFACTOR_KEYWORDS):
            result = _REFACTOR_PREFIX + result
        # Slot-specific prefix (e.g. suppress Gemma4 thinking tokens via /v1)
        if slot == "gemma4" and self.cfg.gemma4_task_prefix:
            result = self.cfg.gemma4_task_prefix + result
        return result

    def _build_retry_context(self, task: str, prev: Optional["AttemptResult"]) -> str:
        """
        Build a task message that includes the previous attempt's failure output.
        Makes the next attempt aware of *what* failed so it doesn't repeat the same mistake.
        Returns the original task unchanged if prev is None or prev succeeded.
        """
        if prev is None or prev.exit_code == 0:
            return task
        failure_summary = (prev.test_output or prev.aider_output or "").strip()
        if not failure_summary:
            return task
        # Keep only the most informative part (last ~400 chars of test output)
        if len(failure_summary) > 400:
            failure_summary = "...\n" + failure_summary[-400:]
        return (
            f"PREVIOUS ATTEMPT FAILED. Do NOT repeat the same approach.\n"
            f"Error from previous attempt:\n"
            f"```\n{failure_summary}\n```\n\n"
            f"Fix the specific error above. Original task:\n\n{task}"
        )

    def run_attempt(
        self,
        n: int,
        task: str,
        project_path: str,
        test_cmd: Optional[str],
        map_tokens: int = 512,
        dry_run: bool = False,
        preferred_model: Optional[str] = None,
        previous_attempt: Optional["AttemptResult"] = None,
        canonical_context: Optional[str] = None,
    ) -> AttemptResult:
        # preferred_model overrides slot 1 only (subsequent attempts escalate normally)
        if n == 1 and preferred_model:
            slot, model, api_base, api_key = self._resolve_preferred(preferred_model)
        else:
            slot, model, api_base, api_key = self._model_for_attempt(n)
        print(f"\n[Tentativa {n}/{self.cfg.max_attempts}] modelo={slot} ({model})")
        self._ensure_warmup(model)

        # Smart retry: inject previous failure context so the model knows what to fix
        base_task = self._build_retry_context(task, previous_attempt)
        if base_task != task:
            print(f"  Smart retry: injetando contexto da falha anterior")

        # Project constraints: architectural rules the model must respect
        constraints_block = load_project_constraints(project_path)
        if constraints_block:
            n_rules = constraints_block.count("\n- ")
            print(f"  Constraints: {n_rules} regra(s) arquitetural(is) injetada(s)")
            base_task = constraints_block + base_task

        # Canonical sources: inject authoritative file contents before the task
        if canonical_context:
            base_task = canonical_context + base_task
            print(f"  Canonical sources: {len(canonical_context)} chars injetados")

        # Inject slot-specific and task-type prefixes
        effective_task = self._inject_task_prefix(base_task, slot)

        # Warn if prompt is very large (risk of exceeding effective context window)
        if len(effective_task) > _PROMPT_SIZE_WARN:
            print(f"  AVISO: prompt ~{len(effective_task)//4} tokens — considere reduzir canonical_sources")

        # Pass AGENTS.md as a read-only reference file if present
        read_files: list[str] = []
        if (Path(project_path) / "AGENTS.md").exists():
            read_files = ["AGENTS.md"]

        start = time.time()
        aider_out, aider_code = run_aider(
            model=model,
            api_base=api_base,
            api_key=api_key,
            task=effective_task,
            project_path=project_path,
            timeout=self.cfg.aider_timeout,
            map_tokens=map_tokens,
            dry_run=dry_run,
            read_files=read_files,
        )
        elapsed = time.time() - start

        # Aider itself failed (timeout / not found)
        if aider_code in (124, 127):
            return AttemptResult(
                attempt_number=n,
                model_used=slot,
                aider_output=aider_out,
                test_output="",
                exit_code=aider_code,
                escalation_triggered=True,
                escalation_reason=f"aider_error(exit={aider_code})",
                modified_files=[],
                git_diff="",
                elapsed_seconds=elapsed,
            )

        diff, files = get_git_diff(project_path)

        # Validate generated Python files before running tests
        if aider_code == 0 and not dry_run:
            valid, val_err = validate_generated_files(project_path, files)
            if not valid:
                print(f"  Validacao falhou: {val_err}")
                return AttemptResult(
                    attempt_number=n,
                    model_used=slot,
                    aider_output=aider_out,
                    test_output=val_err,
                    exit_code=1,
                    escalation_triggered=False,
                    escalation_reason=None,
                    modified_files=files,
                    git_diff=diff,
                    elapsed_seconds=elapsed,
                )

        test_out, test_code = run_tests(test_cmd or "", project_path, self.cfg.test_timeout)

        # No test_cmd: use aider exit code as result
        if not test_cmd:
            test_code = aider_code

        return AttemptResult(
            attempt_number=n,
            model_used=slot,
            aider_output=aider_out,
            test_output=test_out,
            exit_code=test_code,
            escalation_triggered=False,
            escalation_reason=None,
            modified_files=files,
            git_diff=diff,
            elapsed_seconds=elapsed,
        )

    def run_task(
        self,
        task: str,
        project_path: str,
        test_cmd: Optional[str] = None,
        map_tokens: Optional[int] = None,
        dry_run: bool = False,
        task_id: Optional[str] = None,
        preferred_model: Optional[str] = None,
        canonical_sources: Optional[list[str]] = None,
        integrity_cmd: Optional[str] = None,
        integrity_warn_only: bool = False,
        destructive: bool = False,
        isolated: bool = False,
        routing: Optional[RoutingDecision] = None,
    ) -> str:

        effective_map_tokens = map_tokens if map_tokens is not None else self.cfg.aider_map_tokens
        project_name = Path(project_path).name
        logger = SessionLogger(self.cfg.logs_dir, project_name)
        if not isolated and os.environ.get("ORCHESTRATOR_ISOLATED") == "1":
            isolated = True
        # docker isolation_mode triggers isolated flag (Sprint 3 Phase 2; destructive_local removed Sprint 9)
        if routing and routing.isolation_mode == "docker":
            isolated = True
        attempts: list[AttemptResult] = []
        start_total = time.time()
        # Routing fields included in every JSONL entry of this task
        route_meta = {
            "routing": routing.category if routing else None,
            "isolation_mode": routing.isolation_mode if routing else ("docker" if isolated else "host"),
            "review_type": routing.review_type if routing else None,
        }
        # Effective per-task max_attempts (try_local_first can cap at 2)
        effective_max = (
            routing.max_attempts if (routing and routing.max_attempts) else self.cfg.max_attempts
        )

        # always_claude: skip local entirely → synthetic handoff with tag send_claude
        if routing and routing.category == "always_claude":
            md = self.packager.package(
                task=task,
                project=project_name,
                attempts=[],
                escalation_reason=f"always_claude_route ({routing.reason})",
                elapsed=0.0,
            )
            handoff_path = self.packager.save(md, self.cfg.handoffs_dir, project_name)
            print(f"  -> Routing always_claude → handoff direto: {handoff_path}")
            notify_handoff(project_name, task_id or "task", handoff_path)
            logger.log({
                "task": task[:120],
                "attempt": 0,
                "model": "none",
                "outcome": "handoff",
                "elapsed_s": 0.0,
                "escalation_reason": "always_claude_route",
                "handoff_file": handoff_path,
                "handoff_tag": routing.handoff_tag,
                "isolated": isolated,
                **route_meta,
            })
            return "handoff"

        # Destructive snapshot: create git tag before any changes
        if destructive:
            snap_ok, snap_ref = create_pre_task_snapshot(project_path, task_id or "task")
            if snap_ok:
                print(f"  Snapshot criado: {snap_ref}")
            else:
                print(f"  AVISO: snapshot nao criado — {snap_ref}")

        # Resolve canonical sources once (same context injected in every attempt)
        canonical_context = resolve_canonical_context(canonical_sources or [], project_path)
        if canonical_context:
            print(f"  Canonical sources: {len(canonical_sources or [])} arquivo(s) resolvido(s)")

        for n in range(1, effective_max + 1):
            prev = attempts[-1] if attempts else None
            attempt = self.run_attempt(
                n, task, project_path, test_cmd, effective_map_tokens, dry_run,
                preferred_model=preferred_model,
                previous_attempt=prev,
                canonical_context=canonical_context or None,
            )
            attempts.append(attempt)

            # Check escalation signals
            escalate, reason = self.detector.should_escalate(attempt, attempts)
            if escalate:
                attempt.escalation_triggered = True
                attempt.escalation_reason = reason
                print(f"  -> Escalacao detectada: {reason}")

            logger.log({
                "task": task[:120],
                "attempt": n,
                "model": attempt.model_used,
                "outcome": "escalated" if escalate else ("ok" if attempt.exit_code == 0 else "failed"),
                "elapsed_s": round(attempt.elapsed_seconds, 1),
                "escalation_reason": reason or None,
                "exit_code": attempt.exit_code,
                "isolated": isolated,
                **route_meta,
            })

            if attempt.exit_code == 0 and not escalate:
                print(f"  OK Tentativa {n} - testes passaram")

                # Integrity check: project-specific validation after tests pass
                if integrity_cmd:
                    int_ok, int_out = run_integrity_check(integrity_cmd, project_path)
                    int_status = "pass" if int_ok else "fail"
                    print(f"  Integrity check: {int_status}")
                    if not int_ok:
                        print(f"  {int_out[:300]}")
                        logger.log({
                            "task": task[:120],
                            "attempt": n,
                            "model": attempt.model_used,
                            "outcome": "integrity_fail",
                            "elapsed_s": round(attempt.elapsed_seconds, 1),
                            "integrity_output": int_out[:500],
                            "isolated": isolated,
                            **route_meta,
                        })
                        if not integrity_warn_only:
                            # Treat as test failure — continue to next attempt / handoff
                            attempt.exit_code = 1
                            attempt.test_output = f"[integrity_cmd falhou]\n{int_out[:400]}"
                            continue
                        print(f"  integrity_warn_only=true — continuando apesar da falha")

                if self.cfg.auto_commit and attempt.modified_files:
                    tid = task_id or "task"
                    ok, msg = auto_commit_changes(project_path, tid, task, attempt.model_used)
                    print(f"  git commit: {msg}")
                logger.log({
                    "task": task[:120],
                    "attempt": n,
                    "model": attempt.model_used,
                    "outcome": "resolved",
                    "elapsed_s": round(time.time() - start_total, 1),
                    "escalation_reason": None,
                    "isolated": isolated,
                    **route_meta,
                })
                return "resolved"

            if escalate or n == effective_max:
                total_elapsed = time.time() - start_total
                final_reason = reason if escalate else f"max_attempts({effective_max})_reached"
                md = self.packager.package(
                    task=task,
                    project=project_name,
                    attempts=attempts,
                    escalation_reason=final_reason,
                    elapsed=total_elapsed,
                )
                handoff_path = self.packager.save(md, self.cfg.handoffs_dir, project_name)
                print(f"\n  -> Handoff gerado: {handoff_path}")
                notify_handoff(project_name, task_id or "task", handoff_path)
                logger.log({
                    "task": task[:120],
                    "attempt": n,
                    "model": attempt.model_used,
                    "outcome": "handoff",
                    "elapsed_s": round(total_elapsed, 1),
                    "escalation_reason": final_reason,
                    "handoff_file": handoff_path,
                    "handoff_tag": (routing.handoff_tag if routing else None),
                    "isolated": isolated,
                    **route_meta,
                })
                return "handoff"

        return "handoff"

    def run_loop(self, project_path: Optional[str] = None, dry_run: bool = False):
        """Consume backlog continuously."""
        print("Iniciando loop de backlog...")

        while True:
            task_data = self.backlog.next_task()
            if not task_data:
                print("Backlog vazio. Aguardando 60s...")
                time.sleep(60)
                continue

            task_id = task_data["id"]
            task_text = task_data["task"]
            task_project = task_data.get("project", "")
            task_test = task_data.get("test_cmd")
            task_map_tokens = task_data.get("map_tokens", None)              # per-task override
            task_preferred = task_data.get("preferred_model", None)        # skip A3B warmup slot
            task_canonical = task_data.get("canonical_sources", None)      # authoritative files
            task_integrity = task_data.get("integrity_cmd", None)          # post-test validator
            task_integrity_warn = task_data.get("integrity_warn_only", False)
            task_destructive = task_data.get("destructive", False)         # snapshot before changes

            # Sprint 3: classify task with TaskRouter (no-op if router unavailable)
            decision: Optional[RoutingDecision] = None
            if self.router is not None:
                decision = self.router.classify(task_data)
                print(f"Routing: {decision.category} | isolation={decision.isolation_mode} "
                      f"| review={decision.review_type} | {decision.reason}")

            if project_path:
                proj_path = project_path
            else:
                proj_path = str(self.cfg.projects_root / task_project)

            print(f"\n{'='*60}")
            print(f"Tarefa {task_id}: {task_text[:80]}")
            print(f"Projeto: {proj_path}")
            if task_map_tokens:
                print(f"map_tokens: {task_map_tokens} (override)")
            print(f"{'='*60}")

            outcome = self.run_task(
                task=task_text,
                project_path=proj_path,
                test_cmd=task_test,
                map_tokens=task_map_tokens,
                dry_run=dry_run,
                task_id=task_id,
                preferred_model=task_preferred,
                canonical_sources=task_canonical,
                integrity_cmd=task_integrity,
                integrity_warn_only=task_integrity_warn,
                destructive=task_destructive,
                routing=decision,
            )

            if outcome == "resolved":
                self.backlog.mark_done(task_id)
                print(f"Tarefa {task_id}: DONE")
            else:
                handoffs = sorted(
                    self.cfg.handoffs_dir.glob("*.md"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                hp = str(handoffs[0]) if handoffs else "unknown"
                self.backlog.mark_handoff(task_id, hp)
                print(f"Tarefa {task_id}: HANDOFF -> {hp}")
                print("  Edite o backlog: status 'pending' para re-tentar, 'done' para encerrar.")

    def check_status(self):
        """Check servers, loaded models, and backlog state."""
        def check_url(name: str, url: str) -> bool:
            try:
                urllib.request.urlopen(url, timeout=2)
                print(f"  {name}: OK")
                return True
            except Exception as e:
                print(f"  {name}: OFFLINE ({e})")
                return False

        print("=== Servidores ===")
        ollama_ok = check_url("Ollama   :11434", "http://localhost:11434/api/tags")
        llama_base = self.cfg.llama_url.removesuffix("/v1").removesuffix("/")
        check_url(f"llama.cpp:8081 ", f"{llama_base}/health")

        if ollama_ok:
            try:
                raw = urllib.request.urlopen("http://localhost:11434/api/ps", timeout=2).read()
                loaded = json.loads(raw).get("models", [])
                if loaded:
                    for m in loaded:
                        vram_mb = m.get("size_vram", 0) // 1024 // 1024
                        print(f"  -> Loaded: {m['name']} ({vram_mb} MB VRAM)")
                else:
                    print("  -> No model loaded in VRAM")
            except Exception:
                pass

        print("\n=== Backlog ===")
        try:
            data = self.backlog._load()
            tasks = data.get("tasks", [])
            from collections import Counter
            counts = Counter(t["status"] for t in tasks)
            for status, n in sorted(counts.items()):
                print(f"  {status:<20} {n}")
            # Sprint 3: show routing decision for pending tasks
            if self.router is not None:
                pendings = [t for t in tasks if t["status"] == "pending"]
                if pendings:
                    print(f"\n  Routing das pending:")
                    for t in pendings[:20]:
                        d = self.router.classify(t)
                        print(f"    [{t['id']}] {d.category:<18} iso={d.isolation_mode:<6} "
                              f"review={d.review_type}")
            pending_handoffs = [t for t in tasks if t["status"] == "waiting_handoff"]
            if pending_handoffs:
                print(f"\n  Handoffs pendentes:")
                for t in pending_handoffs:
                    since = t.get("blocked_since", "?")[:19]
                    print(f"    [{t['id']}] desde {since}")
        except Exception as e:
            print(f"  (erro ao ler backlog: {e})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Orquestrador de desenvolvimento autonomo local"
    )
    parser.add_argument("--task", help="Descricao da tarefa")
    parser.add_argument("--project", help="Caminho do projeto", default=".")
    parser.add_argument("--test-cmd", help="Comando de testes")
    parser.add_argument("--map-tokens", type=int, help="Tamanho do repo-map (default: config)")
    parser.add_argument("--preferred-model", choices=["ollama", "gemma4", "llama"],
                        help="Forcar modelo no slot 1 (ollama|gemma4|llama)")
    parser.add_argument("--dry-run", action="store_true", help="Nao modifica arquivos")
    parser.add_argument("--loop", action="store_true", help="Loop continuo no backlog")
    parser.add_argument("--status", action="store_true", help="Verificar status dos servidores e backlog")
    parser.add_argument("--watch", action="store_true",
                        help="Modo watch: atualiza --status a cada 30s (Ctrl+C para sair)")
    parser.add_argument("--retry-handoffs", action="store_true",
                        help="Re-fila todas as tarefas waiting_handoff -> pending")

    args = parser.parse_args()

    try:
        cfg = OrchestratorConfig()
    except FileNotFoundError as e:
        print(f"Erro: {e}")
        sys.exit(1)

    orch = Orchestrator(cfg)

    if args.watch:
        import os as _os
        print("Watch mode — Ctrl+C para sair. Atualiza a cada 30s.")
        try:
            while True:
                _os.system("cls" if sys.platform == "win32" else "clear")
                print(f"[{datetime.now().strftime('%H:%M:%S')}]")
                orch.check_status()
                time.sleep(30)
        except KeyboardInterrupt:
            print("\nWatch encerrado.")
        return

    if args.status:
        orch.check_status()
        return

    if args.retry_handoffs:
        n = orch.backlog.retry_handoffs()
        print(f"{n} tarefa(s) re-filadas para pending.")
        return

    if args.loop:
        orch.run_loop(
            project_path=args.project if args.project != "." else None,
            dry_run=args.dry_run,
        )
        return

    if not args.task:
        parser.error("--task e obrigatorio (ou use --loop ou --status)")

    outcome = orch.run_task(
        task=args.task,
        project_path=args.project,
        test_cmd=args.test_cmd,
        map_tokens=args.map_tokens,
        dry_run=args.dry_run,
        preferred_model=args.preferred_model,
    )

    print(f"\nResultado: {outcome}")
    if outcome == "handoff":
        handoffs = sorted(cfg.handoffs_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if handoffs:
            print(f"Handoff: {handoffs[0]}")
            print("\nPrimeiras 30 linhas do handoff:")
            lines = handoffs[0].read_text(encoding="utf-8").splitlines()
            print("\n".join(lines[:30]))


if __name__ == "__main__":
    main()
