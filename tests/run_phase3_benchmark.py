# -*- coding: utf-8 -*-
"""
Sprint 36b Phase 3: model x role benchmark.
Runs 6-task suites for planner candidates and executor candidates.
Results saved to benchmark/sprint36b_results.md
"""
import os
import sys
import time
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:11434")
os.environ.setdefault("ANTHROPIC_API_KEY", "ollama")

import orchestrator.maestro as maestro

WORK_DIR = str(Path(__file__).resolve().parent.parent)

ACTION_VERBS = re.compile(
    r"^(Read|List|Check|Create|Write|Find|Count|Verify|Glob|Grep|Run|Delete|"
    r"Open|Search|Get|Show|Inspect|Load|Scan|Look)", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Planner tasks (non-destructive; tests step decomposition, not task answering)
# ---------------------------------------------------------------------------
PLANNER_TASKS = [
    "List all Python files in the orchestrator/ directory",
    "Find the AGENT_CAP constant value in orchestrator/maestro.py",
    "Check if delegation_rules.yaml has a status field set to active",
    "Count the number of test functions in tests/test_maestro.py",
    "List all YAML files in the project root",
    "Find what sprint is currently active in .checkpoint.json",
]

# ---------------------------------------------------------------------------
# Executor tasks (file-manipulation suite, same as Phase 2)
# ---------------------------------------------------------------------------
EXECUTOR_TASKS = [
    ("create", "Create the file scratch/bench_exec.txt with the single line: bench verified"),
    ("append", "Append the text 'bench_line2' as a new line to scratch/bench_exec.txt using Bash"),
    ("delete", "Delete the file scratch/bench_exec.txt"),
]


def score_planner_output(steps: list, task: str) -> dict:
    """Score step quality: 0-3 points per task."""
    if not steps:
        return {"points": 0, "reason": "no steps (hallucination or empty)"}
    if len(steps) > 5:
        return {"points": 1, "reason": f"plan explosion: {len(steps)} steps"}
    action_count = sum(1 for s in steps if ACTION_VERBS.match(s))
    action_rate = action_count / len(steps)
    if action_rate >= 0.8:
        return {"points": 3, "reason": f"{len(steps)} steps, {action_count}/{len(steps)} action verbs"}
    elif action_rate >= 0.5:
        return {"points": 2, "reason": f"{len(steps)} steps, {action_count}/{len(steps)} action verbs"}
    else:
        return {"points": 1, "reason": f"{len(steps)} steps but weak verbs: {steps[:2]}"}


def run_planner_benchmark(model: str) -> dict:
    print(f"\n{'='*60}")
    print(f"PLANNER BENCHMARK: {model}")
    print(f"{'='*60}")
    os.environ["MAESTRO_MODEL"] = model
    results = []
    total_elapsed = 0
    for i, task in enumerate(PLANNER_TASKS, 1):
        print(f"\n  Task {i}: {task[:60]}")
        t0 = time.time()
        try:
            plan_text = maestro.run_planner(task, WORK_DIR)
            steps = maestro.parse_plan(plan_text)
        except Exception as e:
            steps = []
            plan_text = f"ERROR: {e}"
        elapsed = time.time() - t0
        total_elapsed += elapsed
        score = score_planner_output(steps, task)
        timed_out = elapsed > 60
        results.append({
            "task": task,
            "steps": steps,
            "score": score["points"],
            "reason": score["reason"],
            "elapsed": elapsed,
            "timed_out": timed_out,
            "plan_text": plan_text[:200],
        })
        flag = "TIMEOUT" if timed_out else ("PASS" if score["points"] == 3 else "PARTIAL" if score["points"] > 0 else "FAIL")
        print(f"  [{flag}] {score['reason']} | {elapsed:.1f}s")
        if steps:
            for s in steps[:3]:
                print(f"    - {s[:80]}")

    total_score = sum(r["score"] for r in results)
    max_score = len(PLANNER_TASKS) * 3
    pass_rate = sum(1 for r in results if r["score"] == 3) / len(results)
    halluc_count = sum(1 for r in results if r["score"] == 0)

    print(f"\n  SUMMARY: {total_score}/{max_score} pts | pass_rate={pass_rate:.0%} | hallucinations={halluc_count} | total_time={total_elapsed:.0f}s")
    return {
        "model": model,
        "role": "planner",
        "tasks": len(PLANNER_TASKS),
        "total_score": total_score,
        "max_score": max_score,
        "pass_rate": pass_rate,
        "hallucination_count": halluc_count,
        "median_elapsed": sorted(r["elapsed"] for r in results)[len(results)//2],
        "total_elapsed": total_elapsed,
        "details": results,
    }


def run_executor_benchmark(model: str) -> dict:
    print(f"\n{'='*60}")
    print(f"EXECUTOR BENCHMARK: {model}")
    print(f"{'='*60}")
    os.environ["MAESTRO_MODEL"] = model
    scratch = Path(WORK_DIR) / "scratch"
    bench_file = scratch / "bench_exec.txt"
    results = []
    total_elapsed = 0

    # Task 1: create
    print("\n  Task 1: create bench_exec.txt")
    bench_file.unlink(missing_ok=True)
    t0 = time.time()
    try:
        out = maestro.run_executor(EXECUTOR_TASKS[0][1], WORK_DIR)
    except Exception as e:
        out = f"ERROR: {e}"
    elapsed = time.time() - t0
    total_elapsed += elapsed
    passed = bench_file.exists() and "bench verified" in bench_file.read_text(encoding="utf-8", errors="replace")
    results.append({"task": "create", "passed": passed, "elapsed": elapsed, "output": out[:100]})
    print(f"  [{'PASS' if passed else 'FAIL'}] file_exists={bench_file.exists()} | {elapsed:.1f}s")

    # Task 2: append (only if create passed)
    print("\n  Task 2: append bench_line2")
    if bench_file.exists():
        t0 = time.time()
        try:
            out = maestro.run_executor(EXECUTOR_TASKS[1][1], WORK_DIR)
        except Exception as e:
            out = f"ERROR: {e}"
        elapsed = time.time() - t0
        total_elapsed += elapsed
        lines = bench_file.read_text(encoding="utf-8", errors="replace").splitlines() if bench_file.exists() else []
        passed = len(lines) == 2 and any("bench_line2" in ln for ln in lines)
        results.append({"task": "append", "passed": passed, "elapsed": elapsed, "output": out[:100], "lines": lines})
        print(f"  [{'PASS' if passed else 'FAIL'}] lines={lines} | {elapsed:.1f}s")
    else:
        results.append({"task": "append", "passed": False, "elapsed": 0, "output": "skipped: create failed"})
        print("  [SKIP] create failed, skipping append")

    # Task 3: delete
    print("\n  Task 3: delete bench_exec.txt")
    t0 = time.time()
    try:
        out = maestro.run_executor(EXECUTOR_TASKS[2][1], WORK_DIR)
    except Exception as e:
        out = f"ERROR: {e}"
    elapsed = time.time() - t0
    total_elapsed += elapsed
    passed = not bench_file.exists()
    results.append({"task": "delete", "passed": passed, "elapsed": elapsed, "output": out[:100]})
    print(f"  [{'PASS' if passed else 'FAIL'}] file_deleted={not bench_file.exists()} | {elapsed:.1f}s")

    pass_count = sum(1 for r in results if r["passed"])
    pass_rate = pass_count / len(results)
    print(f"\n  SUMMARY: {pass_count}/{len(results)} PASS | pass_rate={pass_rate:.0%} | total_time={total_elapsed:.0f}s")
    return {
        "model": model,
        "role": "executor",
        "tasks": len(results),
        "pass_count": pass_count,
        "pass_rate": pass_rate,
        "median_elapsed": sorted(r["elapsed"] for r in results)[len(results)//2],
        "total_elapsed": total_elapsed,
        "details": results,
    }


# ---------------------------------------------------------------------------
# Run all benchmarks
# ---------------------------------------------------------------------------
all_results = {}

# Planner candidates
for m in ["qwen3.5:9b", "qwen3.6-64k:latest"]:
    all_results[f"planner_{m}"] = run_planner_benchmark(m)

# Executor candidates
for m in ["gemma4:26b", "qwen3-coder:30b-a3b-q4_K_M"]:
    all_results[f"executor_{m}"] = run_executor_benchmark(m)

# Multi-role: gemma4 does both roles
print(f"\n{'='*60}")
print("MULTI-ROLE: gemma4:26b (planner + executor)")
print(f"{'='*60}")
all_results["multirole_gemma4"] = run_planner_benchmark("gemma4:26b")


# ---------------------------------------------------------------------------
# Determine winners
# ---------------------------------------------------------------------------
planner_scores = {k: v for k, v in all_results.items() if "planner_" in k}
planner_winner = max(planner_scores, key=lambda k: (planner_scores[k]["pass_rate"], -planner_scores[k].get("hallucination_count", 99)))
planner_winner_model = planner_scores[planner_winner]["model"]

executor_scores = {k: v for k, v in all_results.items() if "executor_" in k}
executor_winner = max(executor_scores, key=lambda k: executor_scores[k]["pass_rate"])
executor_winner_model = executor_scores[executor_winner]["model"]

print(f"\n{'='*60}")
print(f"WINNERS:")
print(f"  planner:  {planner_winner_model}")
print(f"  executor: {executor_winner_model}")
print(f"{'='*60}")

# ---------------------------------------------------------------------------
# Save results markdown
# ---------------------------------------------------------------------------
md = []
md.append("# Sprint 36b Model x Role Benchmark Results\n")
md.append(f"**Date**: 2026-05-08  \n**Work dir**: {WORK_DIR}\n\n")

md.append("## Planner Candidates\n\n")
md.append("| Model | Pass Rate | Hallucinations | Score | Median Time |\n")
md.append("|---|---|---|---|---|\n")
for k, r in planner_scores.items():
    md.append(f"| {r['model']} | {r['pass_rate']:.0%} | {r['hallucination_count']} | {r['total_score']}/{r['max_score']} | {r['median_elapsed']:.0f}s |\n")

md.append("\n## Executor Candidates\n\n")
md.append("| Model | Pass Rate | Pass Count | Median Time |\n")
md.append("|---|---|---|---|\n")
for k, r in executor_scores.items():
    md.append(f"| {r['model']} | {r['pass_rate']:.0%} | {r['pass_count']}/{r['tasks']} | {r['median_elapsed']:.0f}s |\n")

md.append("\n## Multi-Role: gemma4:26b\n\n")
mr = all_results["multirole_gemma4"]
md.append(f"- Planner pass rate: {mr['pass_rate']:.0%}\n")
md.append(f"- Hallucinations: {mr['hallucination_count']}\n")
md.append(f"- Swap penalty vs specialized: see Phase 4\n\n")

md.append("## Winners\n\n")
md.append(f"- **Planner**: `{planner_winner_model}` — highest pass rate, lowest hallucination count\n")
md.append(f"- **Executor**: `{executor_winner_model}` — highest Bash correctness\n\n")

md.append("## Phase 2 Finding (pre-benchmark)\n\n")
md.append("- `qwen3.6-64k:latest` executor: reported success but did NOT modify files (Bash hallucination)\n")
md.append("- `gemma4:26b` executor: correctly used Bash append, 3/3 Phase 2 tasks passed\n\n")

result_path = Path(WORK_DIR) / "benchmark" / "sprint36b_results.md"
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text("".join(md), encoding="utf-8")
print(f"\nResults saved: {result_path}")

# Export winners for Phase 6
winners_path = Path(WORK_DIR) / "benchmark" / ".benchmark_winners.txt"
winners_path.write_text(f"planner={planner_winner_model}\nexecutor={executor_winner_model}\n", encoding="utf-8")
print(f"Winners saved: {winners_path}")
