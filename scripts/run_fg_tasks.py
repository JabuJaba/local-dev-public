# -*- coding: utf-8 -*-
"""One-shot runner: processes all pending FG-* tasks via orchestrator and exits."""
import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))

from orchestrator import OrchestratorConfig, Orchestrator, SessionLogger

def main():
    cfg_path = Path(__file__).parent.parent / "orchestrator" / "config.yaml"
    cfg = OrchestratorConfig(cfg_path)
    orch = Orchestrator(cfg)

    processed = []
    max_tasks = 20  # safety cap

    for _ in range(max_tasks):
        task_data = orch.backlog.next_task()
        if not task_data:
            print("Backlog vazio — todos os tasks processados.")
            break

        task_id = task_data["id"]
        if not str(task_id).startswith("FG-"):
            # Skip non-FG tasks (put back as pending)
            orch.backlog.mark_handoff(task_id, "skipped-by-runner")
            print(f"Pulando task nao-FG: {task_id}")
            continue

        task_text = task_data["task"]
        project = task_data.get("project", "")
        test_cmd = task_data.get("test_cmd")
        proj_path = str(cfg.projects_root / project)

        print(f"\n{'='*60}")
        print(f"Iniciando {task_id}: {task_text[:80]}")
        print(f"Projeto: {proj_path}")
        print(f"{'='*60}")

        start = time.time()
        try:
            decision = None
            if orch.router is not None:
                decision = orch.router.classify(task_data)
                print(f"Routing: {decision.category} | {decision.reason}")

            outcome = orch.run_task(
                task=task_text,
                project_path=proj_path,
                test_cmd=test_cmd,
                task_id=task_id,
                routing=decision,
            )
        except Exception as e:
            outcome = f"error: {e}"
            print(f"ERRO em {task_id}: {e}")

        elapsed = round(time.time() - start, 1)

        if outcome == "resolved":
            orch.backlog.mark_done(task_id)
            status = "DONE"
        else:
            import glob as globmod
            handoffs = sorted(
                Path(cfg.handoffs_dir).glob("*.md"),
                key=lambda f: f.stat().st_mtime, reverse=True
            )
            hp = str(handoffs[0]) if handoffs else "unknown"
            orch.backlog.mark_handoff(task_id, hp)
            status = "HANDOFF"

        processed.append({
            "task_id": task_id,
            "outcome": status,
            "elapsed_s": elapsed,
            "task_text": task_text[:100],
        })
        print(f"{task_id}: {status} ({elapsed}s)")

    print(f"\n{'='*60}")
    print(f"Resumo: {len(processed)} tasks processadas")
    for p in processed:
        print(f"  {p['task_id']}: {p['outcome']} ({p['elapsed_s']}s)")

    out_path = Path(__file__).parent.parent / "logs" / "sprint8_fg_run_summary.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"tasks": processed, "run_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, ensure_ascii=False, indent=2)
    print(f"\nResumo salvo em: {out_path}")

if __name__ == "__main__":
    main()
