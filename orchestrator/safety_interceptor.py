"""Sprint 2 Phase 2 - Safety Interceptor (Claude Code PreToolUse hook).

Ativado quando CLAUDE_SAFETY_INTERCEPTOR=1 (setado pelos start_local_*.ps1).
Le JSON do hook em stdin, decide allow/ask/deny conforme regras destrutivas,
e emite JSON no stdout no contrato PreToolUse do Claude Code.

Contrato stdin:
  {"tool_name": "...", "tool_input": {...}, "cwd": "...", ...}

Contrato stdout (permissao):
  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                           "permissionDecision": "allow"|"ask"|"deny",
                           "permissionDecisionReason": "..."}}
Exit 0 sempre (o bloqueio vem via permissionDecision, nao exit code).
"""
from __future__ import annotations

import json
import os
import os
import re
import sys
from pathlib import Path
from datetime import datetime

# Sandbox roots (paths that destructive ops are allowed to touch).
# Configure via env var LOCAL_DEV_SANDBOX_ROOTS as os.pathsep-separated absolute paths.
# Default: empty list = nothing is whitelisted, every path is treated as outside-sandbox.
SANDBOX_ROOTS = [
    Path(p) for p in os.environ.get("LOCAL_DEV_SANDBOX_ROOTS", "").split(os.pathsep) if p
]

DESTRUCTIVE_BASH_PATTERNS = [
    # rm / del / rmdir / rd (com ou sem flags)
    (r"\brm\s+(-[rRfFvI]+\s+)*", "rm"),
    (r"(^|[\s;&|])del\s+", "del"),
    (r"(^|[\s;&|])rmdir\s+", "rmdir"),
    (r"(^|[\s;&|])rd\s+/s", "rd /s"),
    # git destrutivo
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\bgit\s+clean\b", "git clean"),
    (r"\bgit\s+push\s+.*--force\b", "git push --force"),
    (r"\bgit\s+branch\s+-D\b", "git branch -D"),
    # outros
    (r"\bshred\b", "shred"),
    (r"\bmkfs\b", "mkfs"),
    (r">\s*/dev/sd[a-z]", "disk overwrite"),
    # Remove-Item -Recurse -Force sem -WhatIf
    (r"Remove-Item\s+.*-Recurse.*-Force", "Remove-Item -Recurse -Force"),
]

OK = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                             "permissionDecision": "allow"}}


def emit(decision: str, reason: str | None = None) -> None:
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": decision}}
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def file_info(path: Path) -> str:
    try:
        size = path.stat().st_size
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        return f"size={size}B, modificado={mtime}"
    except OSError:
        return "nao acessivel"


def is_outside_sandbox(path_str: str) -> bool:
    try:
        p = Path(path_str).resolve()
    except (OSError, ValueError):
        return True
    for root in SANDBOX_ROOTS:
        try:
            p.relative_to(root.resolve())
            return False
        except ValueError:
            continue
    return True


def check_bash(tool_input: dict) -> tuple[str, str] | None:
    cmd = tool_input.get("command", "") or ""
    for pattern, label in DESTRUCTIVE_BASH_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return label, cmd
    return None


def check_write(tool_input: dict) -> tuple[str, str] | None:
    fp = tool_input.get("file_path", "")
    if not fp:
        return None
    p = Path(fp)
    reasons = []
    if p.exists():
        reasons.append(f"overwrite arquivo existente ({file_info(p)})")
    if is_outside_sandbox(fp):
        reasons.append("FORA do sandbox permitido")
    if reasons:
        return "; ".join(reasons), fp
    return None


def check_edit(tool_input: dict) -> tuple[str, str] | None:
    fp = tool_input.get("file_path", "")
    old = tool_input.get("old_string", "") or ""
    new = tool_input.get("new_string", "") or ""
    if not fp:
        return None
    p = Path(fp)
    reasons = []
    if is_outside_sandbox(fp):
        reasons.append("FORA do sandbox permitido")
    # edit que remove >50% do conteudo
    try:
        if p.exists():
            total = p.stat().st_size
            delta = len(old.encode("utf-8", errors="ignore")) - len(new.encode("utf-8", errors="ignore"))
            if total > 0 and delta > 0 and (delta / total) > 0.5:
                reasons.append(f"remove {delta}/{total} bytes (>50%) - destruicao encoberta")
    except OSError:
        pass
    if reasons:
        return "; ".join(reasons), fp
    return None


def main() -> int:
    if os.environ.get("CLAUDE_SAFETY_INTERCEPTOR") != "1":
        emit("allow")
        return 0

    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        emit("allow")
        return 0

    tool = payload.get("tool_name", "")
    inp  = payload.get("tool_input", {}) or {}
    model = os.environ.get("ANTHROPIC_CUSTOM_MODEL_OPTION", "unknown")

    hit: tuple[str, str] | None = None
    if tool == "Bash":
        hit = check_bash(inp)
    elif tool == "Write":
        hit = check_write(inp)
    elif tool == "Edit":
        hit = check_edit(inp)
    # Read/Glob/Grep sempre allow

    if hit is None:
        emit("allow")
        return 0

    label, target = hit
    msg = (
        f"OPERACAO DESTRUTIVA DETECTADA (modelo local ativo)\n"
        f"Tool: {tool} | Gatilho: {label}\n"
        f"Alvo: {target}\n"
        f"Modelo atual: {model} (sem guardrails)\n"
        f"Confirmar execucao?"
    )
    emit("ask", msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
