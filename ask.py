# -*- coding: utf-8 -*-
"""
Helper rapido para perguntas ao qwen3coder-local via endpoint nativo Ollama.
Usa /api/generate (32-38 tok/s) em vez de /v1/chat/completions (15-17 tok/s).

Uso:
  python ask.py "o que faz essa funcao?"
  echo "codigo aqui" | python ask.py "explique isso"
  python ask.py --model qwen3.5:9b "responda brevemente: ..."
  python ask.py --json "retorne JSON com campos nome e valor"
"""

import argparse
import json
import sys
import time
import urllib.request

OLLAMA_GENERATE = "http://localhost:11434/api/generate"
OLLAMA_CHAT     = "http://localhost:11434/api/chat"
DEFAULT_MODEL   = "qwen3coder-local"

DEFAULT_OPTIONS = {
    "temperature": 0.7,
    "top_p": 0.8,
    "top_k": 20,
    "repeat_penalty": 1.05,
}


def ask_generate(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 120) -> dict:
    """
    Call /api/generate (faster — no chat history overhead).
    Returns {"response": str, "elapsed": float, "tokens": int, "tps": float}.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": DEFAULT_OPTIONS,
    }
    req = urllib.request.Request(
        OLLAMA_GENERATE,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
        elapsed = time.time() - t0
        r = json.loads(raw)
        tokens = r.get("eval_count", 0)
        tps = tokens / elapsed if elapsed > 0 else 0
        return {
            "ok": True,
            "response": r.get("response", ""),
            "elapsed": elapsed,
            "tokens": tokens,
            "tps": tps,
        }
    except urllib.error.URLError as e:
        return {"ok": False, "response": f"ERRO: Ollama offline ou modelo nao carregado.\n{e}", "elapsed": 0, "tokens": 0, "tps": 0}
    except Exception as e:
        return {"ok": False, "response": f"ERRO: {e}", "elapsed": 0, "tokens": 0, "tps": 0}


def main():
    parser = argparse.ArgumentParser(
        description="Pergunta rapida para qwen3coder-local (Ollama /api/generate, 32-38 tok/s)"
    )
    parser.add_argument("question", nargs="*", help="Pergunta ou instrucao")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modelo Ollama (default: {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", dest="json_mode",
                        help="Adiciona instrucao para retornar JSON valido")
    parser.add_argument("--stats", action="store_true",
                        help="Mostrar estatisticas de velocidade ao final")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout em segundos (default: 120)")
    args = parser.parse_args()

    # Build prompt from args + stdin pipe
    question_parts = []

    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            question_parts.append(piped)

    if args.question:
        question_parts.append(" ".join(args.question))

    if not question_parts:
        parser.print_help()
        sys.exit(1)

    prompt = "\n\n".join(question_parts)

    if args.json_mode:
        prompt = prompt + "\n\nResponda APENAS com JSON valido, sem markdown, sem explicacao."

    result = ask_generate(prompt, model=args.model, timeout=args.timeout)

    print(result["response"])

    if args.stats and result["ok"]:
        print(f"\n[{result['elapsed']:.1f}s | {result['tokens']} tok | {result['tps']:.1f} tok/s]",
              file=sys.stderr)


if __name__ == "__main__":
    main()
