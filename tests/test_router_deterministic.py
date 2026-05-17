import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.router_deterministic import route_task


def test_read_only_routes_always_local():
    r = route_task({"id": "RD-T01", "task_type": "read_only"})
    assert r["decision"] == "always_local", r
    assert r["agent"] == "local", r
    assert not r["needs_llm_eval"], r


def test_long_text_routes_always_claude():
    r = route_task({"id": "RD-T02", "task_type": "long_text_generation"})
    assert r["decision"] == "always_claude", r
    assert r["agent"] == "claude", r


def test_critical_override_routes_always_claude():
    r = route_task({"id": "RD-T03", "task_type": "simple_edit", "critical": True})
    assert r["decision"] == "always_claude", r
    assert "critical" in r["reason"], r


def test_large_file_local_routes_always_claude():
    r = route_task({"id": "RD-T04", "task_type": "simple_edit",
                    "file_size_kb": 20, "preferred_agent": "local"})
    assert r["decision"] == "always_claude", r
    assert "large_file" in r["reason"], r


def test_no_task_type_needs_llm_eval():
    r = route_task({"id": "RD-T05"})
    assert r["decision"] == "needs_llm_eval", r
    assert r["needs_llm_eval"] is True, r
    assert r["agent"] is None, r
