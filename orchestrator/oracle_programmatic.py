"""
oracle_programmatic.py — verificação de acceptance sem LLM para tasks simples.
Retorna PASS, FAIL, ou NEEDS_LLM_REVIEW.

Uso: python orchestrator/oracle_programmatic.py --task-type <type> --delivery <path>
     python orchestrator/oracle_programmatic.py --task-type read_only --delivery orchestrator/
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


PROGRAMMATIC_TYPES = {"read_only", "write_new_file", "simple_edit"}


def run_oracle(task_type: str, delivery_path: str, criteria: str = "") -> dict:
    path = Path(delivery_path)

    if task_type not in PROGRAMMATIC_TYPES:
        return {"result": "NEEDS_LLM_REVIEW",
                "reason": f"task_type '{task_type}' requires LLM evaluation",
                "lines_changed": None}

    if task_type == "read_only":
        if not path.exists():
            return {"result": "FAIL", "reason": f"delivery path not found: {path}", "lines_changed": None}
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else path.stat().st_size
        if size == 0:
            return {"result": "FAIL", "reason": "delivery path exists but is empty (0 bytes)", "lines_changed": None}
        return {"result": "PASS", "reason": f"delivery exists, {size} bytes", "lines_changed": None}

    if task_type == "write_new_file":
        if not path.exists():
            return {"result": "FAIL", "reason": f"expected new file/dir not found: {path}", "lines_changed": None}
        files = list(path.rglob("*")) if path.is_dir() else [path]
        new_files = [f for f in files if f.is_file()]
        if not new_files:
            return {"result": "FAIL", "reason": "directory exists but contains no files", "lines_changed": None}
        return {"result": "PASS", "reason": f"{len(new_files)} file(s) created", "lines_changed": len(new_files)}

    if task_type == "simple_edit":
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "HEAD"],
                capture_output=True, text=True, cwd=str(path) if path.is_dir() else str(path.parent),
                timeout=10,
            )
            stat_output = result.stdout.strip()
            if not stat_output:
                return {"result": "FAIL", "reason": "git diff --stat HEAD shows no changes", "lines_changed": 0}
            lines = [l for l in stat_output.splitlines() if "changed" in l]
            return {"result": "PASS", "reason": f"git diff: {stat_output[:120]}", "lines_changed": len(lines)}
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return {"result": "NEEDS_LLM_REVIEW", "reason": f"git unavailable or timeout: {e}", "lines_changed": None}

    return {"result": "NEEDS_LLM_REVIEW", "reason": "unhandled branch", "lines_changed": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--delivery", required=True)
    parser.add_argument("--criteria", default="")
    args = parser.parse_args()
    outcome = run_oracle(args.task_type, args.delivery, args.criteria)
    print(json.dumps(outcome, indent=2))
