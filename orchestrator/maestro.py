"""
Maestro minimo -- 3-agent orchestrator via Ollama (Sprint 36).
All agents use model:inherit; routing via ANTHROPIC_BASE_URL=http://localhost:11434.
Sprint 36b: parse_plan(), PlanSchema, rc checks, escalation_warnings added.
"""
import re
import subprocess
import os
from dataclasses import dataclass
from pathlib import Path

AGENT_CAP = 3  # hard cap: never spawn more than this many agents per pipeline run

AGENTS = {
    "maestro": {
        "model": "inherit",
        "description": "Orchestrator: receives task, delegates to planner then executor",
        "tools": ["Read", "Glob", "Grep"],
    },
    "planner": {
        "model": "inherit",
        "description": "Breaks task into ordered steps with acceptance criteria",
        "tools": ["Read", "Glob", "Grep"],
    },
    "executor": {
        "model": "inherit",
        "description": "Executes one atomic step at a time, reports result",
        "tools": ["Read", "Edit", "Write", "Bash", "Glob", "Grep"],
    },
}

assert len(AGENTS) <= AGENT_CAP, f"Agent count {len(AGENTS)} exceeds AGENT_CAP={AGENT_CAP}"

LONG_OUTPUT_WORD_LIMIT = 600

# Accepts: "1. step", "1) step", "- step", "* step"
STEP_RE = re.compile(r"^(?:\d+[.)]\s*|[-*]\s+)(.*)")


@dataclass
class PlanSchema:
    task: str
    steps: list  # max 5
    context_summary: str  # max 500 chars, from planner
    work_dir: str


def parse_plan(plan_text: str) -> list:
    """Extract steps from planner output. Accepts numbered, bulleted, and mixed formats."""
    steps = []
    for line in plan_text.splitlines():
        m = STEP_RE.match(line.strip())
        if m:
            steps.append(m.group(1).strip())
    return steps[:5]


def _build_claude_cmd(agent_name: str, prompt: str, allowed_tools: list) -> list:
    """
    Build a claude --bare invocation for a named agent.
    Model is inherited via MAESTRO_MODEL env var (set by caller for Ollama routing).
    No Claude API model names are hardcoded here.
    """
    tools_str = ",".join(allowed_tools)
    model = os.environ.get("MAESTRO_MODEL", "")
    if model:
        return ["claude", "--bare", f"--model={model}", f"--allowedTools={tools_str}", "-p", prompt]
    return ["claude", "--bare", f"--allowedTools={tools_str}", "-p", prompt]


def run_planner(task: str, work_dir: str) -> str:
    """Invoke the planner agent to break task into steps."""
    prompt = (
        f"You are a planner. Use your tools to gather information if needed, "
        f"then break this task into 2-5 concrete execution steps.\n"
        f"Each step must be an ACTION (start with a verb: Read, List, Create, Write, Check).\n"
        f"Do NOT answer the task -- output only the step list.\n"
        f"Working directory: {work_dir}\n"
        f"Task: {task}\n"
        f"Output format: numbered list, one step per line, no commentary."
    )
    cmd = _build_claude_cmd("planner", prompt, AGENTS["planner"]["tools"])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=120)
    return result.stdout.strip()


def run_executor(step: str, work_dir: str, context_summary: str = "") -> str:
    """Invoke the executor agent for a single step. Returns ERROR string on failure."""
    ctx = f"Context: {context_summary[:500]}\n" if context_summary else ""
    prompt = (
        f"You are an executor. Perform exactly this step and report the result:\n"
        f"Working directory: {work_dir}\n"
        f"{ctx}"
        f"Step: {step}"
    )
    cmd = _build_claude_cmd("executor", prompt, AGENTS["executor"]["tools"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=300)
    except subprocess.TimeoutExpired:
        return "ERROR (timeout): executor exceeded 300s limit"
    if result.returncode != 0:
        return f"ERROR (rc={result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
    return result.stdout.strip()


def run(task: str, work_dir: str | None = None) -> dict:
    """
    Entry point. Orchestrates: maestro -> planner -> executor.
    Returns dict with plan, steps, results, escalation_warnings, and agent count.
    """
    if work_dir is None:
        work_dir = str(Path.cwd())

    agents_used: list = []

    agents_used.append("maestro")
    print(f"[maestro] task received: {task!r}")

    agents_used.append("planner")
    print("[planner] generating plan...")
    plan_text = run_planner(task, work_dir)
    print(f"[planner] plan:\n{plan_text}")

    steps = parse_plan(plan_text)

    # Build PlanSchema: structured handoff between planner and executor.
    # context_summary is first 500 chars of non-step planner output (narrative context).
    non_step_lines = [ln for ln in plan_text.splitlines() if not STEP_RE.match(ln.strip())]
    context_summary = " ".join(non_step_lines)[:500]
    schema = PlanSchema(task=task, steps=steps, context_summary=context_summary, work_dir=work_dir)

    agents_used.append("executor")
    results = []
    escalation_warnings = []

    for step in schema.steps:
        print(f"[executor] running: {step}")
        output = run_executor(step, work_dir, schema.context_summary)
        results.append({"step": step, "output": output})
        word_count = len(output.split())
        if word_count > LONG_OUTPUT_WORD_LIMIT:
            escalation_warnings.append(
                f"Step '{step[:60]}' produced {word_count} words (>{LONG_OUTPUT_WORD_LIMIT}); consider always_claude"
            )

    assert len(agents_used) <= AGENT_CAP, (
        f"BUG: spawned {len(agents_used)} agents, exceeds AGENT_CAP={AGENT_CAP}"
    )

    return {
        "task": task,
        "plan": plan_text,
        "steps": schema.steps,
        "plan_schema": schema,
        "agents_used": agents_used,
        "agent_count": len(agents_used),
        "results": results,
        "escalation_warnings": escalation_warnings,
    }
