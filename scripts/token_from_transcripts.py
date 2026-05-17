"""Reconstroi token_log.jsonl a partir dos transcripts em ~/.claude/projects/.

Fonte da verdade: ~/.claude/projects/{encoded_cwd}/{session_id}.jsonl
Cada mensagem 'assistant' carrega message.usage com input/output/cache tokens.

Substitui temporariamente (em escopo local) o hook token_logger.py que le
do diretorio session-meta/ — esse diretorio esta stale desde 2026-04-19.

Uso:
  python scripts/token_from_transcripts.py              # todos sessions novos
  python scripts/token_from_transcripts.py --session SID   # so uma sessao
  python scripts/token_from_transcripts.py --since 7d      # ultimos 7 dias
  python scripts/token_from_transcripts.py --dry-run       # sem escrever
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
TOKEN_LOG = CLAUDE_DIR / "token_log.jsonl"

# Pricing USD per 1M tokens. Cache: 5m=1.25x, 1h=2x, read=0.1x do input base.
# Long-context tier (>200K de input somado) multiplica input e output por 2.
PRICING = {
    "claude-opus-4-7":     {"input": 15.0, "output": 75.0, "cache_read":  1.50, "cache_5m": 18.75, "cache_1h": 30.00},
    "claude-opus-4-5":     {"input": 15.0, "output": 75.0, "cache_read":  1.50, "cache_5m": 18.75, "cache_1h": 30.00},
    "claude-sonnet-4-6":   {"input":  3.0, "output": 15.0, "cache_read":  0.30, "cache_5m":  3.75, "cache_1h":  6.00},
    "claude-sonnet-4-5":   {"input":  3.0, "output": 15.0, "cache_read":  0.30, "cache_5m":  3.75, "cache_1h":  6.00},
    "claude-haiku-4-5":    {"input":  1.0, "output":  5.0, "cache_read":  0.10, "cache_5m":  1.25, "cache_1h":  2.00},
}
FALLBACK_PRICING_KEY = "claude-sonnet-4-6"
LONG_CTX_THRESHOLD = 200_000
LONG_CTX_MULTIPLIER = 2.0


def project_name(project_path: str) -> str:
    if not project_path:
        return "unknown"
    parts = Path(project_path.replace("\\", "/")).parts
    for i, part in enumerate(parts):
        if part.lower() in ("ai_lab", "ai lab") and i + 1 < len(parts):
            return parts[i + 1]
    return parts[-1] if parts else "unknown"


def already_logged_ids() -> set:
    ids = set()
    if not TOKEN_LOG.exists():
        return ids
    with open(TOKEN_LOG, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
                # Considera "ja logado" apenas se tiver tokens reais (nao zero)
                if rec.get("total_tokens", 0) > 0:
                    ids.add(rec["session_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def message_cost(usage: dict, model: str) -> float:
    input_tok = usage.get("input_tokens", 0) or 0
    output_tok = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_create = usage.get("cache_creation", {}) or {}
    cache_5m = cache_create.get("ephemeral_5m_input_tokens", 0) or 0
    cache_1h = cache_create.get("ephemeral_1h_input_tokens", 0) or 0

    rates = PRICING.get(model, PRICING[FALLBACK_PRICING_KEY])

    total_input_ctx = input_tok + cache_read + cache_5m + cache_1h
    mult = LONG_CTX_MULTIPLIER if total_input_ctx > LONG_CTX_THRESHOLD else 1.0

    cost = (
        input_tok     * rates["input"]
        + cache_read  * rates["cache_read"]
        + cache_5m    * rates["cache_5m"]
        + cache_1h    * rates["cache_1h"]
        + output_tok  * rates["output"]
    ) * mult / 1_000_000
    return cost


def aggregate_session(jsonl_path: Path) -> dict | None:
    """Le um transcript e agrega tokens + metadata da sessao."""
    input_total = 0
    output_total = 0
    cache_read_total = 0
    cache_5m_total = 0
    cache_1h_total = 0
    cost_total = 0.0
    tool_counts: dict[str, int] = {}
    models_used: set[str] = set()
    timestamps: list[str] = []
    user_msgs = 0
    cwd = ""
    session_id = jsonl_path.stem
    first_prompt = ""
    long_ctx_hits = 0

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if d.get("cwd") and not cwd:
                    cwd = d["cwd"]
                ts = d.get("timestamp")
                if ts:
                    timestamps.append(ts)

                t = d.get("type")

                if t == "user" and not d.get("isMeta"):
                    msg = d.get("message", {})
                    content = msg.get("content", "")
                    # User messages podem ter content = string ou lista
                    if isinstance(content, str) and content.strip():
                        user_msgs += 1
                        if not first_prompt:
                            first_prompt = content[:120]
                    elif isinstance(content, list):
                        # Pula tool_result — conta so text real do usuario
                        has_text = any(
                            isinstance(c, dict) and c.get("type") == "text"
                            for c in content
                        )
                        if has_text:
                            user_msgs += 1
                            if not first_prompt:
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        first_prompt = c.get("text", "")[:120]
                                        break

                elif t == "assistant":
                    msg = d.get("message", {})
                    model = msg.get("model") or ""
                    if model:
                        models_used.add(model)
                    usage = msg.get("usage") or {}
                    if usage:
                        i = usage.get("input_tokens", 0) or 0
                        o = usage.get("output_tokens", 0) or 0
                        cr = usage.get("cache_read_input_tokens", 0) or 0
                        cc = usage.get("cache_creation") or {}
                        c5 = cc.get("ephemeral_5m_input_tokens", 0) or 0
                        c1 = cc.get("ephemeral_1h_input_tokens", 0) or 0

                        input_total     += i
                        output_total    += o
                        cache_read_total += cr
                        cache_5m_total  += c5
                        cache_1h_total  += c1

                        if (i + cr + c5 + c1) > LONG_CTX_THRESHOLD:
                            long_ctx_hits += 1

                        cost_total += message_cost(usage, model)

                    # Contagem de ferramentas (tool_use nos content blocks)
                    for c in msg.get("content") or []:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            name = c.get("name", "unknown")
                            tool_counts[name] = tool_counts.get(name, 0) + 1
    except OSError:
        return None

    if input_total == 0 and output_total == 0:
        return None  # transcript vazio / sessao nao iniciada

    start_time = min(timestamps) if timestamps else ""
    end_time = max(timestamps) if timestamps else ""
    duration_min = 0
    if start_time and end_time:
        try:
            s = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            duration_min = int((e - s).total_seconds() // 60)
        except ValueError:
            pass

    proj = project_name(cwd)
    total_tok = input_total + output_total + cache_read_total + cache_5m_total + cache_1h_total

    return {
        "session_id": session_id,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "date": start_time[:10],
        "project": proj,
        "project_path": cwd,
        "input_tokens": input_total,
        "output_tokens": output_total,
        "cache_read_tokens": cache_read_total,
        "cache_5m_tokens": cache_5m_total,
        "cache_1h_tokens": cache_1h_total,
        "total_tokens": total_tok,
        "cost_usd_est": round(cost_total, 6),
        "duration_minutes": duration_min,
        "user_messages": user_msgs,
        "tool_calls": sum(tool_counts.values()),
        "tool_counts": tool_counts,
        "models_used": sorted(models_used),
        "long_ctx_requests": long_ctx_hits,
        "first_prompt": first_prompt,
    }


def parse_since(s: str) -> datetime | None:
    if not s:
        return None
    if s.endswith("d"):
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return datetime.now(timezone.utc) - timedelta(hours=int(s[:-1]))
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="Processar so uma sessao por session_id")
    ap.add_argument("--since", help="Apenas transcripts modificados desde N (ex: 7d, 24h, 2026-04-01)")
    ap.add_argument("--dry-run", action="store_true", help="Nao escreve no token_log.jsonl")
    ap.add_argument("--limit", type=int, help="Maximo de sessions a processar")
    args = ap.parse_args()

    if not PROJECTS_DIR.exists():
        print(f"[erro] {PROJECTS_DIR} nao existe", file=sys.stderr)
        return 1

    logged = already_logged_ids()
    since = parse_since(args.since) if args.since else None

    transcripts = sorted(PROJECTS_DIR.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if args.session:
        transcripts = [p for p in transcripts if p.stem == args.session]
    if since:
        transcripts = [p for p in transcripts if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) >= since]
    if args.limit:
        transcripts = transcripts[:args.limit]

    new_records = []
    skipped_logged = 0
    skipped_empty = 0

    for p in transcripts:
        sid = p.stem
        if sid in logged:
            skipped_logged += 1
            continue
        rec = aggregate_session(p)
        if rec is None:
            skipped_empty += 1
            continue
        new_records.append(rec)

    print(f"transcripts escaneados: {len(transcripts)}")
    print(f"  ja logados (pulados): {skipped_logged}")
    print(f"  vazios   (pulados):   {skipped_empty}")
    print(f"  novos:                {len(new_records)}")

    if args.dry_run:
        for r in new_records[:5]:
            print(f"  - {r['session_id'][:8]} {r['project']:20s} "
                  f"in={r['input_tokens']} out={r['output_tokens']} "
                  f"cache_r={r['cache_read_tokens']} cache_w={r['cache_5m_tokens']+r['cache_1h_tokens']} "
                  f"cost={r['cost_usd_est']:.4f}")
        if len(new_records) > 5:
            print(f"  ... ({len(new_records)-5} outros)")
        return 0

    with open(TOKEN_LOG, "a", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"gravado em {TOKEN_LOG}")

    total_cost = sum(r["cost_usd_est"] for r in new_records)
    total_tok = sum(r["total_tokens"] for r in new_records)
    print(f"total novo: {total_tok:,} tokens, cost_est={total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
