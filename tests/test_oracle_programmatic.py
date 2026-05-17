import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.oracle_programmatic import run_oracle


def test_read_only_existing_path_returns_pass():
    result = run_oracle("read_only", str(Path(__file__).parent))
    assert result["result"] == "PASS", result
    assert result["lines_changed"] is None


def test_write_new_file_missing_path_returns_fail():
    result = run_oracle("write_new_file", "/nonexistent/path/that/does/not/exist/xyz123")
    assert result["result"] == "FAIL", result
    assert "not found" in result["reason"].lower(), result


def test_unknown_task_type_returns_needs_llm_review():
    result = run_oracle("architectural_decision", ".")
    assert result["result"] == "NEEDS_LLM_REVIEW", result
