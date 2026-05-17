"""
Phase 3 tests for rtk_trim.py hook.
Cases: (a) Bash short no-op, (b) Bash long trimmed, (c) Read always exempt, (d) malformed JSON fail-safe.

The hook itself lives in the user's global Claude Code config (~/.claude/hooks/rtk_trim.py),
not in this repo. These tests document its contract and run if the hook is installed locally;
they skip cleanly on a fresh clone where the hook isn't present.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = os.environ.get(
    "RTK_TRIM_HOOK",
    str(Path.home() / ".claude" / "hooks" / "rtk_trim.py"),
)

pytestmark = pytest.mark.skipif(
    not Path(HOOK).exists(),
    reason=f"rtk_trim.py hook not installed at {HOOK} — set RTK_TRIM_HOOK env var to point to it",
)


def run_hook(payload_str: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, HOOK],
        input=payload_str.encode("utf-8"),
        capture_output=True,
    )
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


def make_payload(tool_name: str, content: str) -> str:
    return json.dumps({"tool_name": tool_name, "tool_result": {"content": content}})


LONG_CONTENT = "\n".join(f"line{i}" for i in range(1, 301))  # 300 lines, well over threshold


def test_bash_short_noop():
    """Case (a): short Bash output -> no change, empty stdout."""
    code, out = run_hook(make_payload("Bash", "echo hello\nhello"))
    assert code == 0, f"Expected exit 0, got {code}"
    assert out == "", f"Expected empty stdout, got: {out[:100]}"


def test_bash_long_trimmed():
    """Case (b): long Bash output -> trim applied, count preserved."""
    code, out = run_hook(make_payload("Bash", LONG_CONTENT))
    assert code == 0, f"Expected exit 0, got {code}"
    assert out, "Expected non-empty stdout (trimmed payload)"
    data = json.loads(out)
    trimmed_content = data["tool_result"]["content"]
    assert "[rtk_trim" in trimmed_content, "Expected trim marker in output"
    assert "300" in trimmed_content or "trimmed" in trimmed_content.lower(), "Expected count info"
    # Verify first and last lines preserved
    assert "line1" in trimmed_content, "Expected first lines preserved"
    assert "line300" in trimmed_content, "Expected last lines preserved"


def test_read_always_exempt():
    """Case (c): Read tool_result is NEVER trimmed regardless of size."""
    code, out = run_hook(make_payload("Read", LONG_CONTENT))
    assert code == 0, f"Expected exit 0, got {code}"
    assert out == "", f"Read must not be trimmed. Got output: {out[:100]}"


def test_malformed_json_failsafe():
    """Case (d): malformed JSON -> fail-safe, no crash, exit 0, empty stdout."""
    code, out = run_hook("not valid json{{{")
    assert code == 0, f"Expected exit 0 on malformed JSON, got {code}"
    assert out == "", f"Expected empty stdout on malformed JSON, got: {out}"


def test_powershell_long_trimmed():
    """PowerShell outputs should be trimmed like Bash."""
    code, out = run_hook(make_payload("PowerShell", LONG_CONTENT))
    assert code == 0
    assert out, "Expected trimmed output for long PowerShell"
    data = json.loads(out)
    assert "[rtk_trim" in data["tool_result"]["content"]


def test_grep_trim_with_count():
    """Grep long output -> trimmed to max matches + count."""
    grep_lines = "\n".join(f"file{i}.py:10:match" for i in range(1, 200))
    code, out = run_hook(make_payload("Grep", grep_lines))
    assert code == 0
    assert out, "Expected trimmed Grep output"
    data = json.loads(out)
    content = data["tool_result"]["content"]
    assert "[rtk_trim" in content
    assert "199" in content or "150" in content or "matches" in content.lower()


if __name__ == "__main__":
    tests = [
        test_bash_short_noop,
        test_bash_long_trimmed,
        test_read_always_exempt,
        test_malformed_json_failsafe,
        test_powershell_long_trimmed,
        test_grep_trim_with_count,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed+failed} passed")
    sys.exit(0 if failed == 0 else 1)
