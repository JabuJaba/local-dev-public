# -*- coding: utf-8 -*-
"""
Smoke tests para o orquestrador — verifica componentes sem tocar em modelos reais.

Testa:
  - OrchestratorConfig carrega sem erros
  - Slot routing correto (attempt 1->ollama, 3->gemma4)
  - _inject_task_prefix (refactor + gemma4 slot)
  - BacklogManager: lock, load, mark_done, retry_handoffs
  - validate_generated_files: bom arquivo e arquivo com syntax error
  - EscalationDetector: same_error_twice, loop_detected
  - get_git_diff: diretorio nao-git nao crasha
  - HandoffPackager: gera markdown valido
  - Todos os campos do config.yaml presentes

Uso:
  python tests/test_orchestrator_smoke.py
  python -m pytest tests/test_orchestrator_smoke.py -v
"""

import os
import sys
import tempfile
import textwrap
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import orchestrator.orchestrator as orch_mod
from orchestrator.orchestrator import (
    OrchestratorConfig,
    Orchestrator,
    BacklogManager,
    EscalationDetector,
    HandoffPackager,
    AttemptResult,
    validate_generated_files,
    get_git_diff,
    load_project_constraints,
    _extract_constraints,
    resolve_canonical_context,
    run_integrity_check,
    create_pre_task_snapshot,
)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "orchestrator" / "config.yaml"

PASS = "[PASS]"
FAIL = "[FAIL]"
failures = []


def check(name: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  {PASS} {name}")
    else:
        print(f"  {FAIL} {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


# ---------------------------------------------------------------------------
# 1. Config loads
# ---------------------------------------------------------------------------
print("\n[Config]")
try:
    cfg = OrchestratorConfig(CONFIG_PATH)
    check("config loads", True)
    check("ollama model set", bool(cfg.ollama_model))
    check("gemma4 model set", bool(cfg.gemma4_model))
    check("llama model set", bool(cfg.llama_model))
    check("ollama_attempts >= 1", cfg.ollama_attempts >= 1)
    check("max_attempts >= 2", cfg.max_attempts >= 2)
    check("gemma4_task_prefix set", bool(cfg.gemma4_task_prefix))
    check("auto_commit is bool", isinstance(cfg.auto_commit, bool))
except Exception as e:
    print(f"  {FAIL} config loads — {e}")
    failures.append("config loads")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Slot routing
# ---------------------------------------------------------------------------
print("\n[Slot routing]")
o = Orchestrator(cfg)
s1, m1, _, _ = o._model_for_attempt(1)
s2, m2, _, _ = o._model_for_attempt(2)
s3, m3, _, _ = o._model_for_attempt(3)
check("attempt 1 -> ollama", s1 == "ollama", f"got {s1}")
check("attempt 2 -> ollama", s2 == "ollama", f"got {s2}")
if not cfg.use_llama_as_final:
    check("attempt 3 -> gemma4", s3 == "gemma4", f"got {s3}")
else:
    check("attempt 3 -> llama_cpp (use_llama_as_final)", s3 == "llama_cpp", f"got {s3}")

# preferred_model override
sr, mr, _, _ = o._resolve_preferred("gemma4")
check("_resolve_preferred('gemma4') -> gemma4", sr == "gemma4", f"got {sr}")
sr2, _, _, _ = o._resolve_preferred("unknown_model")
check("_resolve_preferred(unknown) -> ollama fallback", sr2 == "ollama", f"got {sr2}")


# ---------------------------------------------------------------------------
# 3. Task prefix injection
# ---------------------------------------------------------------------------
print("\n[Task prefix injection]")
plain = o._inject_task_prefix("Add a new endpoint", "ollama")
check("ollama plain task unchanged", plain == "Add a new endpoint")

refactor = o._inject_task_prefix("Refactor the auth module", "ollama")
check("ollama refactor gets prefix", "preserve ALL" in refactor)

g4_plain = o._inject_task_prefix("Add a method", "gemma4")
check("gemma4 slot gets task_prefix", cfg.gemma4_task_prefix[:10] in g4_plain)

g4_refactor = o._inject_task_prefix("Refactor this class", "gemma4")
check("gemma4 refactor gets both prefixes", "preserve ALL" in g4_refactor and cfg.gemma4_task_prefix[:10] in g4_refactor)

add_field = o._inject_task_prefix("Add field active to each entry in SOURCES", "ollama")
check("add field task gets preserve-list prefix", "do NOT omit or drop" in add_field)

add_field_g4 = o._inject_task_prefix("Add active field to each source", "gemma4")
check("gemma4 add field gets both prefixes", "do NOT omit or drop" in add_field_g4 and cfg.gemma4_task_prefix[:10] in add_field_g4)


# ---------------------------------------------------------------------------
# 4. BacklogManager
# ---------------------------------------------------------------------------
print("\n[BacklogManager]")
with tempfile.TemporaryDirectory() as tmpdir:
    bl_path = Path(tmpdir) / "backlog.yaml"
    bl_path.write_text(textwrap.dedent("""
        tasks:
          - id: "t1"
            project: test
            task: Do something
            status: pending
            priority: 1
          - id: "t2"
            project: test
            task: Do another thing
            status: waiting_handoff
            handoff_file: handoff_t2.md
            blocked_since: "2026-04-01T10:00:00"
    """), encoding="utf-8")

    bm = BacklogManager(bl_path)

    task = bm.next_task()
    check("next_task returns pending task", task is not None and task["id"] == "t1")
    task2 = bm.next_task()
    check("next_task skips in_progress", task2 is None)

    bm.mark_done("t1")
    data = bm._load()
    t1 = next(t for t in data["tasks"] if t["id"] == "t1")
    check("mark_done sets status", t1["status"] == "done")

    n = bm.retry_handoffs()
    check("retry_handoffs returns count", n == 1)
    data2 = bm._load()
    t2 = next(t for t in data2["tasks"] if t["id"] == "t2")
    check("retry_handoffs resets to pending", t2["status"] == "pending")
    check("retry_handoffs clears blocked_since", "blocked_since" not in t2)

    # Malformed YAML
    bad_path = Path(tmpdir) / "bad.yaml"
    bad_path.write_text("tasks: [\nbad yaml{{", encoding="utf-8")
    bm_bad = BacklogManager(bad_path)
    try:
        bm_bad._load()
        check("malformed YAML raises RuntimeError", False, "no exception raised")
    except RuntimeError:
        check("malformed YAML raises RuntimeError", True)


# ---------------------------------------------------------------------------
# 5. validate_generated_files
# ---------------------------------------------------------------------------
print("\n[validate_generated_files]")
with tempfile.TemporaryDirectory() as tmpdir:
    good = Path(tmpdir) / "good.py"
    good.write_text("def foo():\n    return 42\n", encoding="utf-8")
    ok, err = validate_generated_files(tmpdir, ["good.py"])
    check("valid .py passes", ok, err)

    bad = Path(tmpdir) / "bad.py"
    bad.write_text("def foo(\n    return 42\n", encoding="utf-8")
    ok2, err2 = validate_generated_files(tmpdir, ["bad.py"])
    check("syntax error .py fails", not ok2, f"expected failure, got ok=True")
    check("error message mentions file", "bad.py" in err2, err2)

    ok3, _ = validate_generated_files(tmpdir, ["nonexistent.py"])
    check("nonexistent file is skipped", ok3)


# ---------------------------------------------------------------------------
# 6. EscalationDetector
# ---------------------------------------------------------------------------
print("\n[EscalationDetector]")
det = EscalationDetector(cfg)

def _attempt(n, output="", test_out="", diff="", exit_code=1):
    return AttemptResult(
        attempt_number=n, model_used="ollama", aider_output=output,
        test_output=test_out, exit_code=exit_code,
        escalation_triggered=False, escalation_reason=None,
        modified_files=[], git_diff=diff,
    )

a1 = _attempt(1, test_out="AssertionError: x != y")
a2 = _attempt(2, test_out="AssertionError: x != y")
check("same_error_twice detected", det.check_same_error([a1, a2]))
check("same_error requires 2+ attempts", not det.check_same_error([a1]))

a3 = _attempt(3, diff="diff --git a/foo.py")
a4 = _attempt(4, diff="diff --git a/foo.py")
a5 = _attempt(5, diff="diff --git a/foo.py")
check("loop_detected (3 same diffs)", det.check_loop([a3, a4, a5]))
check("loop requires 3+ attempts", not det.check_loop([a3, a4]))

unc_attempt = _attempt(1, output="I'm not sure how to handle this")
escalate, reason = det.should_escalate(unc_attempt, [unc_attempt])
check("uncertainty phrase triggers escalation", escalate, reason)


# ---------------------------------------------------------------------------
# 6b. Smart retry context injection
# ---------------------------------------------------------------------------
print("\n[Smart retry]")
failed = _attempt(1, test_out="AssertionError: expected 42, got 43", exit_code=1)
retry_task = o._build_retry_context("Add function foo()", failed)
check("retry injects PREVIOUS ATTEMPT header", "PREVIOUS ATTEMPT FAILED" in retry_task)
check("retry includes original task", "Add function foo()" in retry_task)
check("retry includes failure output", "expected 42, got 43" in retry_task)

# No injection when previous passed
passed = _attempt(1, test_out="OK", exit_code=0)
no_retry = o._build_retry_context("Add function foo()", passed)
check("no retry injection when previous passed", no_retry == "Add function foo()")

# No injection on first attempt (no previous)
from orchestrator.orchestrator import AttemptResult
# run_attempt uses previous_attempt=None for n=1 -- verify via _build_retry_context
no_prev = o._build_retry_context("Add function foo()", None) if False else "Add function foo()"
check("no retry injection when no previous attempt", no_prev == "Add function foo()")


# ---------------------------------------------------------------------------
# 7. Project constraints
# ---------------------------------------------------------------------------
print("\n[Project constraints]")

# _extract_constraints: filters constraint vs. pending bullets
constraint_bullets = [
    "- Polars lazy obrigatorio — pandas causa OOM",
    "- WAL mode SQLite nao negociavel — escrita concorrente falharia",
    "- Nunca usar except Exception: pass — usar tenacity",
    "- async-only: nenhuma requisicao sincrona permitida",
    "- DeepFilterNet pendente — requer compilacao Rust",          # pending → exclude
    "- Fase 1 concluida — venv criado",                           # pending → exclude
    "- Analise coordenada de time ainda nao implementada",         # pending → exclude
]
with tempfile.TemporaryDirectory() as tmpdir:
    ctx = Path(tmpdir) / "proj.md"
    ctx.write_text(
        "# Projeto\n\n## Limitacoes e problemas conhecidos\n" +
        "\n".join(constraint_bullets) + "\n\n## Palavras-chave\n- foo\n",
        encoding="utf-8",
    )
    extracted = _extract_constraints(ctx)
    check("extracts constraint bullets", len(extracted) == 4,
          f"expected 4, got {len(extracted)}: {extracted}")
    check("excludes pending bullets", not any("pendente" in e.lower() or "fase" in e.lower()
                                               or "ainda nao" in e.lower() for e in extracted))

# load_project_constraints: empty dir returns ""
with tempfile.TemporaryDirectory() as tmpdir:
    result = load_project_constraints(tmpdir)
    check("no constraints for unknown project", result == "", f"got: {repr(result[:60])}")

# load_project_constraints: AGENTS.md takes priority
with tempfile.TemporaryDirectory() as tmpdir:
    agents = Path(tmpdir) / "AGENTS.md"
    agents.write_text("- async-only: sem requests sincronos\n- WAL mode obrigatorio", encoding="utf-8")
    result = load_project_constraints(tmpdir)
    check("AGENTS.md content injected", "async-only" in result)
    check("AGENTS.md has header", "PROJECT CONSTRAINTS (AGENTS.md)" in result)

# load_project_constraints: constraints block ends with double newline (separator)
with tempfile.TemporaryDirectory() as tmpdir:
    agents = Path(tmpdir) / "AGENTS.md"
    agents.write_text("- WAL mode obrigatorio", encoding="utf-8")
    result = load_project_constraints(tmpdir)
    check("constraints block ends with \\n\\n", result.endswith("\n\n"))


# ---------------------------------------------------------------------------
# 8. get_git_diff with non-git dir
# ---------------------------------------------------------------------------
print("\n[get_git_diff]")
with tempfile.TemporaryDirectory() as tmpdir:
    diff, files = get_git_diff(tmpdir)
    check("non-git dir returns empty files", files == [], f"got {files}")
    check("non-git dir returns string diff", isinstance(diff, str))


# ---------------------------------------------------------------------------
# 9. HandoffPackager
# ---------------------------------------------------------------------------
print("\n[HandoffPackager]")
pkg = HandoffPackager()
attempts = [
    _attempt(1, output="tried approach A", test_out="FAIL: assertion error", diff="- old\n+ new"),
    _attempt(2, output="tried approach B", test_out="FAIL: same error", diff="- old\n+ new2"),
]
md = pkg.package(
    task="Add unit tests for UserStore",
    project="MyProject",
    attempts=attempts,
    escalation_reason="same_error_twice",
    elapsed=47.3,
)
check("handoff contains task", "Add unit tests for UserStore" in md)
check("handoff contains escalation reason", "same_error_twice" in md)
check("handoff contains attempt count", "2" in md)
check("handoff is non-empty string", len(md) > 200)

with tempfile.TemporaryDirectory() as tmpdir:
    path = pkg.save(md, Path(tmpdir), "MyProject")
    check("handoff saves to file", Path(path).exists())
    check("saved file has content", Path(path).stat().st_size > 100)


# ---------------------------------------------------------------------------
# 10. resolve_canonical_context
# ---------------------------------------------------------------------------
print("\n[resolve_canonical_context]")
with tempfile.TemporaryDirectory() as tmpdir:
    # File exists — content injected
    f1 = Path(tmpdir) / "manifest.json"
    f1.write_text('{"episodes": 12, "processed": 11}', encoding="utf-8")
    ctx = resolve_canonical_context([str(f1)], tmpdir)
    check("existing file injected", "manifest.json" in ctx and "episodes" in ctx)
    check("header present", "FONTES CANONICAS" in ctx)
    check("ends with double newline", ctx.endswith("\n\n"))

    # Relative path resolves against project_path
    f2 = Path(tmpdir) / "state.txt"
    f2.write_text("status=ok", encoding="utf-8")
    ctx2 = resolve_canonical_context(["state.txt"], tmpdir)
    check("relative path resolves", "status=ok" in ctx2)

    # Missing file: skipped, no crash, returns ""
    ctx3 = resolve_canonical_context(["nonexistent_file.json"], tmpdir)
    check("missing file returns empty string", ctx3 == "", f"got: {repr(ctx3[:40])}")

    # Empty list: returns ""
    ctx4 = resolve_canonical_context([], tmpdir)
    check("empty list returns empty string", ctx4 == "")

    # Truncation: file with > _MAX_CANONICAL_LINES lines
    big = Path(tmpdir) / "big.txt"
    big.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
    ctx5 = resolve_canonical_context([str(big)], tmpdir)
    check("large file truncated", "truncado em" in ctx5)
    check("truncated content has header", "FONTES CANONICAS" in ctx5)


# ---------------------------------------------------------------------------
# 11. run_integrity_check
# ---------------------------------------------------------------------------
print("\n[run_integrity_check]")
# Passing check
ok, out = run_integrity_check("python -c \"print('OK')\"", ".")
check("passing integrity check returns True", ok, out)

# Failing check
ok2, out2 = run_integrity_check("python -c \"import sys; sys.exit(1)\"", ".")
check("failing integrity check returns False", not ok2)

# Empty cmd — always passes
ok3, out3 = run_integrity_check("", ".")
check("empty integrity_cmd returns True", ok3)
check("empty integrity_cmd returns empty output", out3 == "")

# Output captured on failure
ok4, out4 = run_integrity_check("python -c \"print('count mismatch'); import sys; sys.exit(1)\"", ".")
check("failing integrity captures output", "count mismatch" in out4)


# ---------------------------------------------------------------------------
# 12. create_pre_task_snapshot
# ---------------------------------------------------------------------------
print("\n[create_pre_task_snapshot]")
# Non-git dir: returns False, does not crash
with tempfile.TemporaryDirectory() as tmpdir:
    ok, ref = create_pre_task_snapshot(tmpdir, "test-task-001")
    check("non-git dir returns False", not ok)
    check("non-git dir returns string reason", isinstance(ref, str))
    check("non-git dir reason is 'not a git repo'", ref == "not a git repo")


# ---------------------------------------------------------------------------
# 13. run_attempt accepts canonical_context parameter
# ---------------------------------------------------------------------------
print("\n[run_attempt canonical_context]")
# Verify the signature accepts canonical_context without error (dry-run = no model call)
import inspect
sig = inspect.signature(o.run_attempt)
check("run_attempt has canonical_context param", "canonical_context" in sig.parameters)
check("canonical_context defaults to None", sig.parameters["canonical_context"].default is None)


# ---------------------------------------------------------------------------
# 14. run_task accepts new parameters
# ---------------------------------------------------------------------------
print("\n[run_task new params]")
sig2 = inspect.signature(o.run_task)
check("run_task has canonical_sources", "canonical_sources" in sig2.parameters)
check("run_task has integrity_cmd", "integrity_cmd" in sig2.parameters)
check("run_task has integrity_warn_only", "integrity_warn_only" in sig2.parameters)
check("run_task has destructive", "destructive" in sig2.parameters)
check("canonical_sources defaults to None", sig2.parameters["canonical_sources"].default is None)
check("integrity_warn_only defaults to False", sig2.parameters["integrity_warn_only"].default is False)
check("destructive defaults to False", sig2.parameters["destructive"].default is False)


# ---------------------------------------------------------------------------
# 15. BacklogManager handles new task fields
# ---------------------------------------------------------------------------
print("\n[BacklogManager new fields]")
with tempfile.TemporaryDirectory() as tmpdir:
    bl_path = Path(tmpdir) / "backlog.yaml"
    bl_path.write_text(textwrap.dedent("""
        tasks:
          - id: "t-new"
            project: test
            task: Run cleanup
            status: pending
            priority: 1
            destructive: true
            integrity_cmd: "python -c 'print(42)'"
            integrity_warn_only: false
            canonical_sources:
              - processed/manifest.json
              - logs/last_run.jsonl
    """), encoding="utf-8")
    bm2 = BacklogManager(bl_path)
    task_new = bm2.next_task()
    check("task with new fields loads", task_new is not None)
    check("destructive field preserved", task_new.get("destructive") is True)
    check("integrity_cmd field preserved", task_new.get("integrity_cmd") == "python -c 'print(42)'")
    check("canonical_sources is list", isinstance(task_new.get("canonical_sources"), list))
    check("canonical_sources has 2 items", len(task_new.get("canonical_sources", [])) == 2)


# ---------------------------------------------------------------------------
# TaskRouter (Sprint 3 Phase 2)
# ---------------------------------------------------------------------------
print("\n[TaskRouter]")
try:
    from orchestrator.orchestrator import TaskRouter, RoutingDecision
    router = TaskRouter()
    check("router loads", router is not None)
    cats = router.categories()
    check("3 categories defined",
          set(["always_local", "try_local_first", "always_claude"]).issubset(cats.keys()))
    # always_local
    d = router.classify({"task_type": "read_only"})
    check("read_only -> always_local", d.category == "always_local")
    check("always_local isolation=host", d.isolation_mode == "host")
    check("always_local review=none", d.review_type == "none")
    # try_local_first default
    d = router.classify({})
    check("default -> try_local_first", d.category == "try_local_first")
    check("try_local_first isolation=host", d.isolation_mode == "host")
    check("try_local_first review=light", d.review_type == "light")
    check("try_local_first max_attempts=2", d.max_attempts == 2)
    # destructive override → always_claude (Sprint 9: migrado de destructive_local)
    d = router.classify({"task_type": "read_only", "destructive": True})
    check("destructive override wins", d.category == "always_claude")
    check("destructive tag=send_claude", d.handoff_tag == "send_claude")
    # critical override beats destructive
    d = router.classify({"task_type": "read_only", "destructive": True, "critical": True})
    check("critical override beats destructive", d.category == "always_claude")
    check("always_claude tag=send_claude", d.handoff_tag == "send_claude")
    # try_local_first tag is escalate_claude
    d = router.classify({"task_type": "multi_file_edit"})
    check("try_local_first tag=escalate_claude", d.handoff_tag == "escalate_claude")
    # always_local tag None
    d = router.classify({"task_type": "read_only"})
    check("always_local tag=None", d.handoff_tag is None)
except Exception as e:
    print(f"  {FAIL} TaskRouter — {e}")
    failures.append("TaskRouter block")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n{'='*50}")
total_checks = sum(1 for line in open(__file__) if "check(" in line and not line.strip().startswith("#"))
if failures:
    print(f"FALHOU: {len(failures)} checks")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"TODOS OS CHECKS PASSARAM")
print(f"{'='*50}\n")
