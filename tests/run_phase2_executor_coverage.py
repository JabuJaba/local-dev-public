"""
Sprint 36b Phase 2: executor role coverage via live maestro.run().
Tests file-manipulation tools (Write/Edit/Bash) against local Ollama model.
Run from project root with Ollama UP and MAESTRO_MODEL set.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:11434")
os.environ.setdefault("ANTHROPIC_API_KEY", "ollama")
os.environ.setdefault("MAESTRO_MODEL", "qwen3.6-64k:latest")

import orchestrator.maestro as maestro

WORK_DIR = str(Path(__file__).resolve().parent.parent)
SCRATCH = Path(WORK_DIR) / "scratch"
TARGET = SCRATCH / "test_exec.txt"

PASS = "[PASS]"
FAIL = "[FAIL]"
failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  {PASS} {name}")
    else:
        print(f"  {FAIL} {name}" + (f" -- {detail}" if detail else ""))
        failures.append(name)


# -----------------------------------------------------------------------
# Task 1: create file
# -----------------------------------------------------------------------
print("\n[Task 1] create scratch/test_exec.txt")
t0 = time.time()
TARGET.unlink(missing_ok=True)
result1 = maestro.run(
    "Create the file scratch/test_exec.txt with the single line: maestro executor verified",
    WORK_DIR,
)
elapsed1 = time.time() - t0
print(f"  wall-clock: {elapsed1:.1f}s")
print(f"  escalation_warnings: {result1['escalation_warnings']}")
check("file created", TARGET.exists(), f"path={TARGET}")
if TARGET.exists():
    content = TARGET.read_text(encoding="utf-8").strip()
    check("content correct", "maestro executor verified" in content, f"got: {content!r}")


# -----------------------------------------------------------------------
# Task 2: append line
# -----------------------------------------------------------------------
print("\n[Task 2] append 'line2' to scratch/test_exec.txt")
t0 = time.time()
result2 = maestro.run(
    "Append the line 'line2' to the file scratch/test_exec.txt",
    WORK_DIR,
)
elapsed2 = time.time() - t0
print(f"  wall-clock: {elapsed2:.1f}s")
check("file still exists after append", TARGET.exists())
if TARGET.exists():
    lines = TARGET.read_text(encoding="utf-8").splitlines()
    check("file has 2 lines after append", len(lines) == 2, f"lines={lines}")
    check("line2 present", any("line2" in ln for ln in lines), f"lines={lines}")


# -----------------------------------------------------------------------
# Task 3: delete file
# -----------------------------------------------------------------------
print("\n[Task 3] delete scratch/test_exec.txt")
t0 = time.time()
result3 = maestro.run(
    "Delete the file scratch/test_exec.txt",
    WORK_DIR,
)
elapsed3 = time.time() - t0
print(f"  wall-clock: {elapsed3:.1f}s")
check("file deleted", not TARGET.exists(), f"still exists: {TARGET}")


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
total = elapsed1 + elapsed2 + elapsed3
print(f"\n{'='*50}")
print(f"Total wall-clock: {total:.1f}s")
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL PHASE 2 CHECKS PASSED")
print(f"{'='*50}\n")
