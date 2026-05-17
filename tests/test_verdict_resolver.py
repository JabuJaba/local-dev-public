"""
Unit tests for orchestrator/verdict_resolver.py — 5 scenarios (Sprint 6 Phase 1).

Scenarios:
  1. codex_legacy_read  — resolve returns .codex/ path when legacy file exists
  2. new_delegation     — resolve returns .delegation/ path for new tasks
  3. migrate_lazy       — v0.1 verdict migrated in-memory; original unchanged
  4. v02_is_noop        — migrate_v01_to_v02 returns unchanged object for v0.2 verdicts
  5. codex_no_legacy    — codex agent, no legacy file → falls back to .delegation/
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))
from verdict_resolver import resolve_verdict_path, migrate_v01_to_v02

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

V01_VERDICT = {
    "task_id": "test-task-01",
    "project": "TestProject",
    "project_path": "/fake/path",
    "created_at": "2026-04-20T23:00:00-03:00",
    "updated_at": "2026-04-20T23:30:00-03:00",
    "current_stage": "review",
    "stages": [
        {
            "stage": "fit",
            "decision": "GO",
            "rationale": "test rationale",
            "evidence_paths": [],
            "heuristics_applied": ["H1"],
            "created_at": "2026-04-20T23:00:00-03:00",
            "next_stage": "sprint",
        },
        {
            "stage": "sprint",
            "decision": "GENERATED",
            "rationale": "sprint rationale",
            "evidence_paths": [
                ".codex/sprints/test-task-01-codex.md",
            ],
            "heuristics_applied": [],
            "created_at": "2026-04-20T23:15:00-03:00",
            "next_stage": "review",
        },
        {
            "stage": "review",
            "decision": "ACEITAR",
            "rationale": "review rationale",
            "evidence_paths": [
                ".codex/deliveries/test-task-01/diff.patch",
                ".codex/deliveries/test-task-01/test_output.log",
            ],
            "heuristics_applied": [],
            "created_at": "2026-04-20T23:30:00-03:00",
            "next_stage": "closed",
        },
    ],
}


# ---------------------------------------------------------------------------
# Scenario 1: codex legacy path returned when .codex/ file exists
# ---------------------------------------------------------------------------

def test_resolve_codex_legacy_path(tmp_path):
    verdict_dir = tmp_path / ".codex" / "verdicts"
    verdict_dir.mkdir(parents=True)
    legacy_file = verdict_dir / "test-task-01.json"
    legacy_file.write_text("{}")

    result = resolve_verdict_path("test-task-01", "codex", tmp_path)
    assert result == legacy_file
    assert ".codex" in str(result)


# ---------------------------------------------------------------------------
# Scenario 2: new task → .delegation/ path
# ---------------------------------------------------------------------------

def test_resolve_new_delegation_path(tmp_path):
    result = resolve_verdict_path("new-task-01", "local", tmp_path)
    expected = tmp_path / ".delegation" / "verdicts" / "new-task-01.json"
    assert result == expected


# ---------------------------------------------------------------------------
# Scenario 3: lazy migration of v0.1 → v0.2 (in-memory, original unchanged)
# ---------------------------------------------------------------------------

def test_migrate_v01_to_v02_lazy():
    original_stages_count = len(V01_VERDICT["stages"])
    migrated = migrate_v01_to_v02(V01_VERDICT)

    # Root-level additions
    assert migrated["schema_version"] == "0.2"
    assert migrated["agent"] == "codex"

    # Stage count preserved
    assert len(migrated["stages"]) == original_stages_count

    # fit stage enriched
    fit = next(s for s in migrated["stages"] if s["stage"] == "fit")
    assert "rules_applied" in fit
    assert isinstance(fit["rules_applied"], list)
    assert "limits_checked" in fit
    assert fit["limits_checked"]["long_text_generation"] is False
    assert "expected_economy_pct" in fit

    # sprint stage: decision normalized + delivery_artifacts added
    sprint = next(s for s in migrated["stages"] if s["stage"] == "sprint")
    assert sprint["decision"] == "GENERATED_INTERACTIVE"
    assert sprint["sandbox_mode_used"] == "sandbox-copy"
    assert sprint["isolation_confirmed"] is False
    assert "delivery_artifacts" in sprint

    # review stage: delivery_artifacts_verified added + patch detected
    review = next(s for s in migrated["stages"] if s["stage"] == "review")
    assert "delivery_artifacts_verified" in review
    assert review["delivery_artifacts_verified"]["patch_path"] == ".codex/deliveries/test-task-01/diff.patch"
    assert review["delivery_artifacts_verified"]["log_path"] == ".codex/deliveries/test-task-01/test_output.log"

    # Original dict must NOT be mutated
    assert "schema_version" not in V01_VERDICT
    assert "agent" not in V01_VERDICT


# ---------------------------------------------------------------------------
# Scenario 4: v0.2 verdict is a no-op (same object returned)
# ---------------------------------------------------------------------------

def test_migrate_v02_is_noop():
    v02 = {**V01_VERDICT, "schema_version": "0.2", "agent": "codex"}
    result = migrate_v01_to_v02(v02)
    assert result is v02  # identity — same object, not a copy


# ---------------------------------------------------------------------------
# Scenario 5: codex agent but no legacy .codex/ file → .delegation/ fallback
# ---------------------------------------------------------------------------

def test_resolve_codex_no_legacy_falls_back(tmp_path):
    # No .codex/verdicts/ directory created → legacy file does not exist
    result = resolve_verdict_path("nonexistent-task", "codex", tmp_path)
    expected = tmp_path / ".delegation" / "verdicts" / "nonexistent-task.json"
    assert result == expected
    assert ".delegation" in str(result)
