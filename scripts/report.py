# -*- coding: utf-8 -*-
"""
Relatorio semanal do orquestrador.

Le todos os arquivos JSONL em logs/ e imprime:
  - Total de tarefas resolvidas / escaladas / com handoff
  - Taxa de resolucao por modelo
  - Tipos de escalacao mais comuns
  - Projetos com mais handoffs (candidatos a melhoria de test_cmd)
  - Tarefas mais lentas

Uso:
  python scripts/report.py
  python scripts/report.py --days 14        # ultimas 2 semanas
  python scripts/report.py --json           # saida JSON bruta
  python scripts/report.py --pipeline       # breakdown de tokens Claude por skill
  python scripts/report.py --pipeline --project <game-bot>  # filtrar por projeto
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
CLAUDE_TOKEN_LOG = Path.home() / ".claude" / "token_log.jsonl"

PIPELINE_SKILLS = {
    "fit-evaluator", "local-fit-evaluator", "codex-fit-evaluator",
    "sprint-generator-unified", "sprint-generator",
    "sprint-execute",
    "universal-review-merge", "codex-delivery-review",
    "session-close", "catchup", "diagnose", "fix-triage", "fix-verify",
}

_CMD_RE = re.compile(r"<command-name>/?([^<]+)</command-name>")


def load_entries(days: int) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    for f in sorted(LOGS_DIR.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                ts = e.get("timestamp", "")
                if ts and datetime.fromisoformat(ts) >= cutoff:
                    entries.append(e)
            except (json.JSONDecodeError, ValueError):
                continue
    return entries


def report(entries: list[dict]) -> dict:
    outcomes = Counter(e.get("outcome") for e in entries)
    by_model = defaultdict(Counter)
    for e in entries:
        by_model[e.get("model", "?")][e.get("outcome")] += 1

    escalation_reasons = Counter(
        e.get("escalation_reason") for e in entries if e.get("escalation_reason")
    )

    # Handoffs per project (project inferred from JSONL filename)
    handoff_entries = [e for e in entries if e.get("outcome") == "handoff"]
    # Group by task prefix (first word of task text)
    slow_tasks = sorted(
        [e for e in entries if e.get("elapsed_s", 0) > 120],
        key=lambda e: e.get("elapsed_s", 0),
        reverse=True,
    )[:5]

    total = len(entries)
    resolved = outcomes.get("resolved", 0)
    handoffs = outcomes.get("handoff", 0)
    escalated = outcomes.get("escalated", 0)

    return {
        "total_entries": total,
        "resolved": resolved,
        "handoffs": handoffs,
        "escalated_early": escalated,
        "resolution_rate_pct": round(resolved / total * 100, 1) if total else 0,
        "by_model": {m: dict(c) for m, c in by_model.items()},
        "top_escalation_reasons": escalation_reasons.most_common(8),
        "slow_tasks": [
            {"task": e.get("task", "")[:60], "elapsed_s": e.get("elapsed_s"), "model": e.get("model")}
            for e in slow_tasks
        ],
        "handoff_count": len(handoff_entries),
    }


def print_report(data: dict, days: int):
    print(f"\n{'='*60}")
    print(f" RELATORIO ORQUESTRADOR — ultimos {days} dias")
    print(f" Gerado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    total = data["total_entries"]
    print(f"\n  Entradas totais:    {total}")
    print(f"  Resolvidas:         {data['resolved']}  ({data['resolution_rate_pct']}%)")
    print(f"  Handoffs gerados:   {data['handoffs']}")
    print(f"  Escalacoes precoces:{data['escalated_early']}")

    print(f"\n  {'Modelo':<25} {'resolved':>9} {'handoff':>9} {'escalated':>10}")
    print(f"  {'-'*25} {'-'*9} {'-'*9} {'-'*10}")
    for model, counts in sorted(data["by_model"].items()):
        print(f"  {model:<25} {counts.get('resolved',0):>9} {counts.get('handoff',0):>9} {counts.get('escalated',0):>10}")

    if data["top_escalation_reasons"]:
        print(f"\n  Top razoes de escalacao:")
        for reason, count in data["top_escalation_reasons"]:
            print(f"    {reason:<40} {count:>4}x")

    if data["slow_tasks"]:
        print(f"\n  Tarefas mais lentas:")
        for t in data["slow_tasks"]:
            print(f"    [{t['elapsed_s']:.0f}s] {t['task']}")

    print(f"\n{'='*60}\n")


def _extract_skill(first_prompt: str) -> str:
    m = _CMD_RE.search(first_prompt or "")
    return m.group(1).strip() if m else "(direct)"


def load_claude_token_entries(days: int, project_filter: str | None = None) -> list[dict]:
    if not CLAUDE_TOKEN_LOG.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    for line in CLAUDE_TOKEN_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts = e.get("logged_at", "")
            if ts and datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None) >= cutoff:
                if project_filter and project_filter.lower() not in (e.get("project") or "").lower():
                    continue
                entries.append(e)
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


def pipeline_token_report(entries: list[dict]) -> dict:
    by_skill: dict[str, dict] = defaultdict(lambda: {
        "sessions": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cost_usd": 0.0,
    })

    for e in entries:
        skill = _extract_skill(e.get("first_prompt", ""))
        s = by_skill[skill]
        s["sessions"] += 1
        s["input_tokens"] += e.get("input_tokens", 0)
        s["output_tokens"] += e.get("output_tokens", 0)
        s["cache_read_tokens"] += e.get("cache_read_tokens", 0)
        s["cost_usd"] += e.get("cost_usd_est", 0.0)

    pipeline_cost = sum(
        v["cost_usd"] for k, v in by_skill.items() if k in PIPELINE_SKILLS
    )
    total_cost = sum(v["cost_usd"] for v in by_skill.values())

    return {
        "by_skill": dict(by_skill),
        "pipeline_cost_usd": round(pipeline_cost, 6),
        "total_cost_usd": round(total_cost, 6),
        "pipeline_pct": round(pipeline_cost / total_cost * 100, 1) if total_cost else 0,
        "sessions_total": len(entries),
    }


def print_pipeline_report(data: dict, days: int, project_filter: str | None):
    label = f" [{project_filter}]" if project_filter else " [todos os projetos]"
    print(f"\n{'='*65}")
    print(f" PIPELINE TOKEN BREAKDOWN — ultimos {days} dias{label}")
    print(f" Gerado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")

    by_skill = data["by_skill"]
    if not by_skill:
        print("\n  Nenhuma sessao Claude encontrada no periodo.\n")
        return

    # Sort: pipeline skills first (by cost desc), then others
    def sort_key(item):
        k, v = item
        return (0 if k in PIPELINE_SKILLS else 1, -v["cost_usd"])

    print(f"\n  {'Skill':<35} {'Sess':>5} {'Input':>8} {'Output':>8} {'Cache':>9} {'USD':>8}")
    print(f"  {'-'*35} {'-'*5} {'-'*8} {'-'*8} {'-'*9} {'-'*8}")

    pipeline_sep_printed = False
    for skill, v in sorted(by_skill.items(), key=sort_key):
        if skill not in PIPELINE_SKILLS and not pipeline_sep_printed:
            print(f"  {'--- outros ---':<35}")
            pipeline_sep_printed = True
        tag = " *" if skill in PIPELINE_SKILLS else "  "
        print(
            f"  {skill:<35}{tag}"
            f"{v['sessions']:>4} "
            f"{v['input_tokens']:>8,} "
            f"{v['output_tokens']:>8,} "
            f"{v['cache_read_tokens']:>9,} "
            f"{v['cost_usd']:>8.4f}"
        )

    print(f"\n  {'*'} = skill do pipeline")
    print(f"\n  Pipeline total: {data['pipeline_cost_usd']:.4f}  ({data['pipeline_pct']}% do total Claude)")
    print(f"  Total Claude:   {data['total_cost_usd']:.4f}  ({data['sessions_total']} sessoes)")
    print(f"\n  Local execution (orchestrator): custo Claude zero por definicao")
    print(f"{'='*65}\n")


def main():
    parser = argparse.ArgumentParser(description="Relatorio semanal do orquestrador")
    parser.add_argument("--days", type=int, default=7, help="Janela em dias (default: 7)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Saida JSON bruta")
    parser.add_argument("--diagnose", action="store_true",
                        help="Incluir diagnostico de saude de todos os projetos")
    parser.add_argument("--pipeline", action="store_true",
                        help="Breakdown de tokens Claude por skill do pipeline")
    parser.add_argument("--project", type=str, default=None,
                        help="Filtrar pipeline report por nome de projeto (ex: <game-bot>)")
    args = parser.parse_args()

    if args.pipeline:
        claude_entries = load_claude_token_entries(args.days, args.project)
        pipeline_data = pipeline_token_report(claude_entries)
        if args.as_json:
            print(json.dumps(pipeline_data, indent=2, ensure_ascii=False))
        else:
            print_pipeline_report(pipeline_data, args.days, args.project)
        return

    if not LOGS_DIR.exists():
        print(f"Diretorio de logs nao encontrado: {LOGS_DIR}")
        sys.exit(0)

    entries = load_entries(args.days)
    if not entries:
        print(f"Nenhuma entrada de log nos ultimos {args.days} dias.")
        sys.exit(0)

    data = report(entries)

    if args.diagnose:
        run_with_diagnostics(args.days)
        return

    if args.as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print_report(data, args.days)


if __name__ == "__main__":
    main()


# ---- convenience: called from diagnose.py --report-with-diagnostics ----
def run_with_diagnostics(days: int = 7):
    """Combined: print orchestrator report + project diagnostics."""
    entries = load_entries(days)
    if entries:
        data = report(entries)
        print_report(data, days)
    else:
        print(f"\n(Sem entradas de log nos ultimos {days} dias)\n")

    # Import diagnose lazily to avoid circular deps
    try:
        import importlib, sys
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        diag = importlib.import_module("diagnose")
        index = diag.load_project_index()
        results = [diag.analyze_project(v["nome"], v["pasta"], v["status"], v["context_file"])
                   for v in index.values()]
        diag.print_report(results)
    except Exception as e:
        print(f"(Diagnostico indisponivel: {e})")
