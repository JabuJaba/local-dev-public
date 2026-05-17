"""
router_deterministic.py — routing sem LLM para tasks com task_type claro.
Lê backlog.yaml de um projeto e aplica as regras de delegation_rules.yaml.
Tasks sem task_type ou com sinais conflitantes retornam needs_llm_eval:true.

Uso: python orchestrator/router_deterministic.py --project <path>
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

ALWAYS_LOCAL = {"read_only", "simple_edit", "bash_safe", "small_write"}
TRY_LOCAL = {"multi_file_edit", "bash_with_analysis", "read_then_write"}
ALWAYS_CLAUDE = {
    "long_text_generation", "generator_coroutine", "async_internals",
    "architectural_decision", "production_critical", "file_deletion",
    "schema_migration_dry", "bulk_rename", "gui_automation",
    "multi_file_cross_dependency",
}
LARGE_FILE_KB = 12


def route_task(task: dict) -> dict:
    task_id = task.get("id", "unknown")
    task_type = task.get("task_type") or task.get("type")
    preferred_agent = task.get("preferred_agent", "local")
    file_size_kb = task.get("file_size_kb", 0)

    if task.get("critical"):
        return {"task_id": task_id, "decision": "always_claude", "agent": "claude",
                "reason": "critical:true override", "needs_llm_eval": False}

    if task.get("destructive"):
        return {"task_id": task_id, "decision": "always_claude", "agent": "claude",
                "reason": "destructive:true (Sprint 9 migration)", "needs_llm_eval": False}

    if task_type in ALWAYS_CLAUDE:
        return {"task_id": task_id, "decision": "always_claude", "agent": "claude",
                "reason": f"task_type:{task_type} in always_claude", "needs_llm_eval": False}

    if file_size_kb > LARGE_FILE_KB and preferred_agent == "local":
        return {"task_id": task_id, "decision": "always_claude", "agent": "claude",
                "reason": f"large_file:{file_size_kb}KB>{LARGE_FILE_KB}KB (local timeout gate, Sprint 18)",
                "needs_llm_eval": False}

    if task_type in ALWAYS_LOCAL:
        return {"task_id": task_id, "decision": "always_local", "agent": "local",
                "reason": f"task_type:{task_type} in always_local", "needs_llm_eval": False}

    if task_type in TRY_LOCAL:
        return {"task_id": task_id, "decision": "try_local_first", "agent": "local",
                "reason": f"task_type:{task_type} in try_local_first", "needs_llm_eval": False}

    return {"task_id": task_id, "decision": "needs_llm_eval", "agent": None,
            "reason": f"no task_type or ambiguous: task_type={task_type!r}", "needs_llm_eval": True}


def run_on_backlog(project_path: str) -> list[dict]:
    backlog_path = Path(project_path) / "backlog.yaml"
    if not backlog_path.exists():
        print(f"ERROR: backlog.yaml not found at {backlog_path}", file=sys.stderr)
        sys.exit(1)
    with open(backlog_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    tasks = data if isinstance(data, list) else data.get("tasks", [])
    return [route_task(t) for t in tasks]


def print_table(results: list[dict]) -> None:
    header = f"{'task_id':<20} {'decision':<20} {'agent':<10} {'reason'}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['task_id']:<20} {r['decision']:<20} {str(r['agent']):<10} {r['reason']}")
    needs_llm = sum(1 for r in results if r["needs_llm_eval"])
    print(f"\nTotal: {len(results)} tasks | deterministic: {len(results)-needs_llm} | needs_llm_eval: {needs_llm}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="Path to project with backlog.yaml")
    args = parser.parse_args()
    results = run_on_backlog(args.project)
    print_table(results)
