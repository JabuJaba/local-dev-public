"""
Adapter for unified delegation verdict schema (v0.2).

Public API:
  resolve_verdict_path(task_id, agent, project_path) -> Path
  migrate_v01_to_v02(verdict_dict) -> dict

One-way migration: Codex schema v0.1 → v0.2.
Detection: v0.1 lacks `schema_version` field.
Round 3 decision (2026-04-22): no bidirectional adapter needed; clean cut.
"""
import re
from pathlib import Path
from typing import Union


def resolve_verdict_path(
    task_id: str,
    agent: str,
    project_path: Union[str, Path],
) -> Path:
    """
    Return the canonical verdict file path for a task.

    For codex verdicts that already exist in the legacy `.codex/` path, returns
    that path to preserve immutability of written verdicts. All new verdicts
    (and all non-codex agents) go to `.delegation/verdicts/`.
    """
    if not task_id:
        raise ValueError("task_id must be a non-empty string")
    if not project_path:
        raise ValueError("project_path must be a non-empty string or Path")

    project = Path(project_path)

    if agent == "codex":
        legacy = project / ".codex" / "verdicts" / f"{task_id}.json"
        if legacy.exists():
            return legacy

    return project / ".delegation" / "verdicts" / f"{task_id}.json"


def migrate_v01_to_v02(verdict: dict) -> dict:
    """
    One-way migration: Codex schema v0.1 → unified v0.2.

    Detects v0.1 by the absence of `schema_version`.
    Does NOT write to disk — caller decides whether to persist.
    Does NOT mutate the input dict.
    Returns the same object unchanged if already v0.2+.
    """
    if "schema_version" in verdict:
        return verdict  # already v0.2+, no-op

    result = {**verdict}
    result["agent"] = "codex"
    result["schema_version"] = "0.2"

    result["stages"] = [_migrate_stage(s) for s in verdict.get("stages", [])]
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _migrate_stage(stage: dict) -> dict:
    s = dict(stage)
    name = s.get("stage")

    if name == "fit":
        s.setdefault("rules_applied", [])
        s.setdefault("limits_checked", {
            "long_text_generation": False,
            "generator_coroutine": False,
            "async_internals": False,
            "multi_file_cross_dependency": False,
        })
        s.setdefault("expected_economy_pct", None)

    elif name == "sprint":
        s.setdefault("isolation_confirmed", False)
        s.setdefault("sandbox_mode_used", "sandbox-copy")
        s.setdefault("delivery_artifacts", _classify_evidence_paths(s.get("evidence_paths", [])))
        if s.get("decision") == "GENERATED":
            s["decision"] = "GENERATED_INTERACTIVE"

    elif name == "review":
        s.setdefault("delivery_artifacts_verified", _classify_evidence_paths(s.get("evidence_paths", [])))

    return s


_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _classify_evidence_paths(paths: list) -> dict:
    """Classify a list of evidence paths into the typed delivery_artifacts dict."""
    artifacts: dict = {"patch_path": None, "commit_sha": None, "log_path": None}
    for p in paths:
        p_lower = p.lower()
        if p_lower.endswith(".patch"):
            artifacts["patch_path"] = p
        elif p_lower.endswith(".jsonl") or "log" in p_lower:
            artifacts["log_path"] = p
        elif _SHA_RE.match(p):
            artifacts["commit_sha"] = p
    return artifacts
