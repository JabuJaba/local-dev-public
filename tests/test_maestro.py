# -*- coding: utf-8 -*-
"""
Sprint 36b Phase 0: test fixtures for orchestrator/maestro.py
6 cases: parse, executor, full pipeline, error path, inter-step context, escalation.
All subprocess calls are mocked -- no live model invocations.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import orchestrator.maestro as maestro


# ---------------------------------------------------------------------------
# Case 1 — planner-only: parse_plan extracts steps in 3 formats
# ---------------------------------------------------------------------------

def test_parse_plan_numbered():
    text = "1. Read the file\n2. Check the content\n3. Write the result"
    steps = maestro.parse_plan(text)
    assert steps == ["Read the file", "Check the content", "Write the result"]


def test_parse_plan_bulleted():
    text = "- Read the file\n- Check the content\n* Write the result"
    steps = maestro.parse_plan(text)
    assert len(steps) == 3
    assert steps[0] == "Read the file"


def test_parse_plan_mixed():
    text = "1. Read the file\n- Check the content\n* Write the result"
    steps = maestro.parse_plan(text)
    assert len(steps) == 3


def test_parse_plan_caps_at_five():
    text = "\n".join(f"{i}. Step {i}" for i in range(1, 9))
    steps = maestro.parse_plan(text)
    assert len(steps) == 5


def test_parse_plan_skips_commentary():
    text = "Here is the plan:\n1. Read the file\nNote: be careful\n2. Write result"
    steps = maestro.parse_plan(text)
    assert len(steps) == 2
    assert "Here is the plan" not in steps


# ---------------------------------------------------------------------------
# Case 2 — executor-only: success path returns output
# ---------------------------------------------------------------------------

def test_executor_returns_output():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "sprint_36.md sprint_36b.md\n"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        output = maestro.run_executor("List files in sprints/", ".")

    assert len(output) > 0
    assert "sprint_36" in output


# ---------------------------------------------------------------------------
# Case 3 — full pipeline: run() orchestrates planner -> executor
# ---------------------------------------------------------------------------

def test_full_pipeline():
    planner_proc = MagicMock()
    planner_proc.returncode = 0
    planner_proc.stdout = "1. List files in sprints/\n2. Report the count\n"
    planner_proc.stderr = ""

    executor_proc = MagicMock()
    executor_proc.returncode = 0
    executor_proc.stdout = "sprint_36.md sprint_36b.md"
    executor_proc.stderr = ""

    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        return planner_proc if call_count[0] == 1 else executor_proc

    with patch("subprocess.run", side_effect=fake_run):
        result = maestro.run("list 3 files in sprints/", ".")

    assert result["task"] == "list 3 files in sprints/"
    assert result["agent_count"] == 3
    assert "results" in result
    assert len(result["results"]) >= 1
    assert any("sprint" in r["output"].lower() for r in result["results"])


# ---------------------------------------------------------------------------
# Case 4 — error path: rc != 0 is surfaced in result, not swallowed
# ---------------------------------------------------------------------------

def test_error_path_surfaced():
    planner_proc = MagicMock()
    planner_proc.returncode = 0
    planner_proc.stdout = "1. Run invalid command\n"
    planner_proc.stderr = ""

    fail_proc = MagicMock()
    fail_proc.returncode = 1
    fail_proc.stdout = ""
    fail_proc.stderr = "command not found: invalid-tool"

    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        return planner_proc if call_count[0] == 1 else fail_proc

    with patch("subprocess.run", side_effect=fake_run):
        result = maestro.run("run invalid command", ".")

    assert any("ERROR" in r["output"] for r in result["results"])


# ---------------------------------------------------------------------------
# Case 5 — multi-step Option C: steps are independent (no context bleed)
# ---------------------------------------------------------------------------

def test_executor_steps_are_independent():
    planner_proc = MagicMock()
    planner_proc.returncode = 0
    planner_proc.stdout = "1. Read file A\n2. Read file B\n"
    planner_proc.stderr = ""

    exec1 = MagicMock()
    exec1.returncode = 0
    exec1.stdout = "UNIQUE_CONTENT_OF_FILE_A"
    exec1.stderr = ""

    exec2 = MagicMock()
    exec2.returncode = 0
    exec2.stdout = "content of file B"
    exec2.stderr = ""

    prompts_captured = []
    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return planner_proc
        # capture the -p prompt (executor calls only)
        for i, arg in enumerate(cmd):
            if arg == "-p" and i + 1 < len(cmd):
                prompts_captured.append(cmd[i + 1])
        return exec1 if call_count[0] == 2 else exec2

    with patch("subprocess.run", side_effect=fake_run):
        result = maestro.run("read files A and B", ".")

    assert len(result["results"]) == 2
    # Option C: step 2 prompt must NOT contain step 1 output
    if len(prompts_captured) >= 2:
        assert "UNIQUE_CONTENT_OF_FILE_A" not in prompts_captured[1]


# ---------------------------------------------------------------------------
# Case 6 — long-output escalation: >600 words triggers escalation_warning
# ---------------------------------------------------------------------------

def test_long_output_escalation_flag():
    planner_proc = MagicMock()
    planner_proc.returncode = 0
    planner_proc.stdout = "1. Generate a long report\n"
    planner_proc.stderr = ""

    long_output = " ".join(f"word{i}" for i in range(650))  # 650 words
    exec_long = MagicMock()
    exec_long.returncode = 0
    exec_long.stdout = long_output
    exec_long.stderr = ""

    call_count = [0]

    def fake_run(cmd, **kwargs):
        call_count[0] += 1
        return planner_proc if call_count[0] == 1 else exec_long

    with patch("subprocess.run", side_effect=fake_run):
        result = maestro.run("generate a long report", ".")

    assert "escalation_warnings" in result
    assert len(result["escalation_warnings"]) > 0
    assert "600" in result["escalation_warnings"][0] or "words" in result["escalation_warnings"][0].lower()
