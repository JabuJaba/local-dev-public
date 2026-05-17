# -*- coding: utf-8 -*-
"""Compute Sprint 8 real economy from JSONL log.

Reports a ratio (% saved vs Claude-only baseline). Units are tool-calls — the
economy figure is a pure ratio and unit-independent, so the absolute rate per
tool-call doesn't affect the output percentage.
"""
import json
from pathlib import Path

# Tool calls estimates from sprint_4_routing_map.md
TOOL_CALLS = {
    "FG-01": 2, "FG-02": 2, "FG-03": 2, "FG-04": 2, "FG-05": 2,
    "FG-06": 3, "FG-07": 3, "FG-08": 3,
    "FG-09": 4, "FG-10": 3, "FG-11": 3, "FG-12": 2,
    "FG-13": 3, "FG-14": 5, "FG-15": 2, "FG-16": 5,
    "FG-17": 3, "FG-18": 3, "FG-19": 4, "FG-20": 3,
}
# Baseline rate per tool-call — relative units. Use 1.0 to report cost in
# tool-call equivalents. The economy ratio is independent of this constant.
BASELINE_RATE = 1.0

def main():
    log_path = Path(__file__).parent.parent / "logs" / "sprint8_run.jsonl"
    if not log_path.exists():
        print(f"JSONL nao encontrado: {log_path}")
        return

    # Parse JSONL for final outcomes
    final_outcomes = {}
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            outcome = d.get("outcome")
            if outcome in ("resolved", "handoff"):
                task = d["task"][:40]
                final_outcomes[task] = {
                    "outcome": outcome,
                    "elapsed_s": d.get("elapsed_s", 0),
                    "model": d.get("model", ""),
                    "retries": d.get("attempt", 1),
                    "routing": d.get("routing", ""),
                }

    # Map outcomes to task IDs based on order (FG-01..16..17..20)
    fg_tasks = sorted(TOOL_CALLS.keys(), key=lambda k: int(k.split("-")[1]))

    # Read backlog to get actual task statuses
    import yaml
    backlog_path = Path(__file__).parent.parent / "backlog" / "backlog.yaml"
    with open(backlog_path, encoding="utf-8") as f:
        backlog = yaml.safe_load(f)

    task_status = {t["id"]: t["status"] for t in backlog["tasks"] if str(t["id"]).startswith("FG-")}

    print("=" * 70)
    print("Sprint 8 — Economia Real Medida")
    print("=" * 70)
    print()
    print(f"{'ID':<8} {'Status':<14} {'tool_calls':<12} {'baseline':<10} {'real':<8} {'economy%'}")
    print("-" * 70)

    total_baseline = 0.0
    total_real = 0.0
    resolved_count = 0
    handoff_count = 0
    pending_count = 0

    for fg_id in fg_tasks:
        tc = TOOL_CALLS[fg_id]
        baseline = tc * BASELINE_RATE
        status = task_status.get(fg_id, "unknown")

        if status in ("done",):
            real = 0.0
            economy = 100.0
            resolved_count += 1
        elif status in ("waiting_handoff",):
            real = baseline  # handoff = Claude would do it at baseline cost
            economy = 0.0
            handoff_count += 1
        elif status in ("pending", "in_progress"):
            real = None
            economy = None
            pending_count += 1
        else:
            real = None
            economy = None
            pending_count += 1

        total_baseline += baseline
        if real is not None:
            total_real += real

        if economy is not None:
            print(f"{fg_id:<8} {status:<14} {tc:<12} {baseline:<10.2f} {real:<8.2f} {economy:.0f}%")
        else:
            print(f"{fg_id:<8} {status:<14} {tc:<12} {baseline:<10.2f} {'TBD':<8} TBD")

    print("-" * 70)
    print(f"{'TOTAL':<8} {'':<14} {sum(TOOL_CALLS.values()):<12} {total_baseline:<10.2f} {total_real:<8.2f}")
    print()

    if pending_count == 0:
        economy_bruta = (total_baseline - total_real) / total_baseline * 100
        print(f"Economia bruta:   {economy_bruta:.1f}%")
        print(f"Custo review:     ~0% (review humano, nao Claude tokens)")
        print(f"Economia liquida: {economy_bruta:.1f}%  (vs 64.2% projetado Sprint 7)")
        print()
        print(f"Resolucoes locais: {resolved_count}/{len(fg_tasks)} ({resolved_count/len(fg_tasks)*100:.0f}%)")
        print(f"Handoffs:          {handoff_count}/{len(fg_tasks)} ({handoff_count/len(fg_tasks)*100:.0f}%)")
        print()
        if economy_bruta >= 40:
            print("✓ DECISAO: ROLLOUT CONFIANTE (>= 40%)")
        elif economy_bruta >= 20:
            print("~ DECISAO: ROLLOUT CAUTELOSO (20-40%)")
        else:
            print("! DECISAO: REVISAR routing_rules (<20%)")
    else:
        print(f"ATENCAO: {pending_count} tasks ainda pendentes — run nao completo")

if __name__ == "__main__":
    main()
