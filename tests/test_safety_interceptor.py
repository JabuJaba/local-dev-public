"""Sprint 2 Phase 2 - smoke test do safety_interceptor.

Creates a fresh temp directory at runtime and registers it as a sandbox root
via LOCAL_DEV_SANDBOX_ROOTS, so the test is self-contained and works on any
machine. Also defines a parent-of-sandbox path to test "outside sandbox" cases.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

INTERCEPTOR = Path(__file__).resolve().parent.parent / "orchestrator" / "safety_interceptor.py"


def run(payload: dict, env_extra: dict, interceptor_on: bool = True) -> dict:
    env = os.environ.copy()
    env.update(env_extra)
    env["CLAUDE_SAFETY_INTERCEPTOR"] = "1" if interceptor_on else "0"
    env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = "qwen3.6:35b-a3b-q4_k_m"
    proc = subprocess.run(
        [sys.executable, str(INTERCEPTOR)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr.decode()}"
    return json.loads(proc.stdout.decode())


def decision(resp: dict) -> str:
    return resp["hookSpecificOutput"]["permissionDecision"]


def main() -> int:
    failures: list[str] = []

    # Create real sandbox + outside-sandbox dirs in tempdir.
    parent = Path(tempfile.mkdtemp(prefix="safety_test_"))
    sandbox = parent / "sandbox"
    outside = parent / "outside"
    sandbox.mkdir()
    outside.mkdir()
    env_extra = {"LOCAL_DEV_SANDBOX_ROOTS": str(sandbox)}

    def call(payload, interceptor_on=True):
        return run(payload, env_extra, interceptor_on)

    # 1. rm bloqueia
    r = call({"tool_name": "Bash", "tool_input": {"command": "rm -rf ./output/"}})
    if decision(r) != "ask":
        failures.append(f"rm deveria pedir confirmacao, veio {decision(r)}")

    # 2. git reset --hard bloqueia
    r = call({"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD~1"}})
    if decision(r) != "ask":
        failures.append(f"git reset --hard deveria pedir, veio {decision(r)}")

    # 3. ls passa
    r = call({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    if decision(r) != "allow":
        failures.append(f"ls deveria allow, veio {decision(r)}")

    # 4. Write em arquivo existente bloqueia
    tmp = sandbox / "existing.tmp"
    tmp.write_bytes(b"existing")
    r = call({"tool_name": "Write", "tool_input": {"file_path": str(tmp), "content": "new"}})
    if decision(r) != "ask":
        failures.append(f"Write overwrite deveria pedir, veio {decision(r)}")

    # 5. Write em arquivo novo DENTRO do sandbox passa
    new_path = sandbox / "_safety_test_new.tmp"
    new_path.unlink(missing_ok=True)
    r = call({"tool_name": "Write", "tool_input": {"file_path": str(new_path), "content": "hi"}})
    if decision(r) != "allow":
        failures.append(f"Write novo no sandbox deveria allow, veio {decision(r)}")

    # 6. Write em arquivo FORA do sandbox bloqueia
    r = call({"tool_name": "Write",
              "tool_input": {"file_path": str(outside / "README.md"),
                             "content": "boom"}})
    if decision(r) != "ask":
        failures.append(f"Write fora do sandbox deveria pedir, veio {decision(r)}")

    # 7. Edit destrutivo (remove >50%)
    big = sandbox / "big.py"
    big.write_bytes(b"A" * 1000)
    r = call({"tool_name": "Edit",
              "tool_input": {"file_path": str(big),
                             "old_string": "A" * 800,
                             "new_string": ""}})
    if decision(r) != "ask":
        failures.append(f"Edit destrutivo deveria pedir, veio {decision(r)}")

    # 8. Edit pequeno passa
    small_edit = sandbox / "small.py"
    small_edit.write_bytes(b"A" * 1000)
    r = call({"tool_name": "Edit",
              "tool_input": {"file_path": str(small_edit),
                             "old_string": "A" * 10,
                             "new_string": "BBB"}})
    if decision(r) != "allow":
        failures.append(f"Edit pequeno deveria allow, veio {decision(r)}")

    # 9. Read sempre allow
    r = call({"tool_name": "Read", "tool_input": {"file_path": "anywhere"}})
    if decision(r) != "allow":
        failures.append(f"Read deveria allow, veio {decision(r)}")

    # 10. Interceptor desligado -> tudo passa
    r = call({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
             interceptor_on=False)
    if decision(r) != "allow":
        failures.append(f"interceptor off deveria allow, veio {decision(r)}")

    # Cleanup
    import shutil
    shutil.rmtree(parent, ignore_errors=True)

    if failures:
        print("FALHAS:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK: 10/10 checks passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
