# -*- coding: utf-8 -*-
"""
Benchmark de OCR/visão para modelos locais com capacidade multimodal.
Compara qwen3.6:35b-a3b-q4_k_m vs gemma4:26b na extração de texto de imagens.

Uso:
  python bench_ocr.py                  # ambos os modelos
  python bench_ocr.py --model qwen36   # só Qwen3.6
  python bench_ocr.py --model gemma4   # só Gemma4
  python bench_ocr.py --category text  # só categoria específica
"""

import argparse
import base64
import io
import json
import re
import textwrap
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Configuração dos modelos (multimodal via Ollama native API)
# ---------------------------------------------------------------------------

MODELS = {
    "qwen36": {
        "url": "http://localhost:11434/api/chat",
        "model": "qwen3.6:35b-a3b-q4_k_m",
        "label": "Qwen3.6 35B A3B MoE [vision, no-think]",
        "think": False,
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
    },
    "gemma4": {
        "url": "http://localhost:11434/api/chat",
        "model": "gemma4:26b",
        "label": "Gemma 4 26B (Google) [vision, no-think]",
        "think": False,
        "temperature": 0.2,
        "top_p": 0.95,
        "top_k": 64,
    },
}

# ---------------------------------------------------------------------------
# Geração de imagens de teste
# ---------------------------------------------------------------------------

def _make_font(size: int = 18) -> ImageFont.ImageFont:
    """Carrega fonte monoespaçada ou fallback do sistema."""
    candidates = [
        "cour.ttf", "Courier New.ttf", "DejaVuSansMono.ttf",
        "LiberationMono-Regular.ttf", "consola.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            pass
    return ImageFont.load_default()


def make_image(lines: list[str], font_size: int = 20, bg: str = "white",
               fg: str = "black", padding: int = 20, noise: bool = False) -> str:
    """Cria imagem PNG a partir de linhas de texto. Retorna base64 PNG."""
    font = _make_font(font_size)
    dummy = Image.new("RGB", (1, 1))
    draw_dummy = ImageDraw.Draw(dummy)

    line_heights = [draw_dummy.textbbox((0, 0), ln or " ", font=font)[3] for ln in lines]
    max_width = max(draw_dummy.textbbox((0, 0), ln or " ", font=font)[2] for ln in lines)
    total_height = sum(line_heights) + (len(lines) - 1) * 4

    w = max_width + padding * 2
    h = total_height + padding * 2

    img = Image.new("RGB", (w, h), color=bg)
    draw = ImageDraw.Draw(img)

    y = padding
    for ln, lh in zip(lines, line_heights):
        draw.text((padding, y), ln, font=font, fill=fg)
        y += lh + 4

    if noise:
        import random
        rng = random.Random(42)
        pixels = img.load()
        for _ in range(w * h // 50):
            x_n = rng.randint(0, w - 1)
            y_n = rng.randint(0, h - 1)
            v = rng.randint(180, 255)
            pixels[x_n, y_n] = (v, v, v)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Definição das tasks de OCR
# ---------------------------------------------------------------------------

@dataclass
class OcrTask:
    id: str
    category: str
    difficulty: str
    description: str
    lines: list[str]          # texto real na imagem
    prompt: str               # instrução para o modelo
    expected: str             # saída esperada (texto normalizado)
    font_size: int = 20
    bg: str = "white"
    fg: str = "black"
    noise: bool = False


def _norm(text: str) -> str:
    """Normaliza para comparação: lowercase, espaços colapsados, sem pontuação extra."""
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def score_ocr(predicted: str, expected: str) -> float:
    """
    Retorna score 0.0-1.0 baseado em word-level accuracy.
    Partial credit: palavras certas / total palavras esperadas.
    """
    pred_words = _norm(predicted).split()
    exp_words = _norm(expected).split()
    if not exp_words:
        return 1.0
    matches = sum(1 for w in exp_words if w in pred_words)
    return matches / len(exp_words)


PASS_THRESHOLD = 0.85  # >=85% das palavras corretas = PASS


TASKS: list[OcrTask] = [
    # --- plain_text ---
    OcrTask(
        id="ocr_01",
        category="plain_text",
        difficulty="easy",
        description="Linha única, texto simples",
        lines=["Hello, World! This is a test."],
        prompt="Extraia todo o texto desta imagem. Responda apenas com o texto extraído, sem explicações.",
        expected="Hello, World! This is a test.",
    ),
    OcrTask(
        id="ocr_02",
        category="plain_text",
        difficulty="easy",
        description="Múltiplas linhas, parágrafo curto",
        lines=[
            "The quick brown fox jumps",
            "over the lazy dog.",
            "Pack my box with five",
            "dozen liquor jugs.",
        ],
        prompt="Extraia todo o texto desta imagem linha por linha. Responda apenas com o texto.",
        expected="The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.",
    ),
    OcrTask(
        id="ocr_03",
        category="plain_text",
        difficulty="medium",
        description="Texto com números e pontuação",
        lines=[
            "Invoice #2024-0042",
            "Date: 18/04/2026",
            "Total: <amount>",
            "Due in 30 days.",
        ],
        prompt="Extraia todo o texto desta imagem. Inclua todos os números e símbolos exatamente como aparecem.",
        expected="Invoice #2024-0042 Date: 18/04/2026 Total: <amount> Due in 30 days.",
    ),
    # --- structured ---
    OcrTask(
        id="ocr_04",
        category="structured",
        difficulty="medium",
        description="Lista com marcadores",
        lines=[
            "Ingredientes:",
            "  - 2 xícaras de farinha",
            "  - 1 colher de sal",
            "  - 3 ovos",
            "  - 200ml de leite",
        ],
        prompt="Extraia o texto desta imagem. Preserve a estrutura de lista.",
        expected="Ingredientes: 2 xícaras de farinha 1 colher de sal 3 ovos 200ml de leite",
    ),
    OcrTask(
        id="ocr_05",
        category="structured",
        difficulty="medium",
        description="Tabela simples ASCII",
        lines=[
            "Nome        | Idade | Cidade",
            "------------|-------|--------",
            "Ana Silva   |  28   | SP",
            "Bruno Costa |  35   | RJ",
            "Carla Dias  |  42   | BH",
        ],
        prompt="Extraia os dados desta tabela. Liste cada linha como: Nome, Idade, Cidade.",
        expected="Ana Silva 28 SP Bruno Costa 35 RJ Carla Dias 42 BH",
    ),
    OcrTask(
        id="ocr_06",
        category="structured",
        difficulty="hard",
        description="Código fonte Python curto",
        lines=[
            "def fibonacci(n):",
            "    if n <= 1:",
            "        return n",
            "    return fibonacci(n-1) + fibonacci(n-2)",
        ],
        font_size=18,
        bg="#1e1e1e",
        fg="#d4d4d4",
        prompt="Extraia o código Python desta imagem exatamente como está escrito.",
        expected="def fibonacci(n): if n <= 1: return n return fibonacci(n-1) + fibonacci(n-2)",
    ),
    # --- noisy ---
    OcrTask(
        id="ocr_07",
        category="noisy",
        difficulty="medium",
        description="Texto com ruído de fundo",
        lines=[
            "ATENÇÃO: Leia com cuidado.",
            "Este documento é confidencial.",
            "Não compartilhe.",
        ],
        noise=True,
        prompt="Extraia todo o texto desta imagem apesar do ruído de fundo.",
        expected="ATENÇÃO: Leia com cuidado. Este documento é confidencial. Não compartilhe.",
    ),
    OcrTask(
        id="ocr_08",
        category="noisy",
        difficulty="hard",
        description="Texto em fundo cinza com ruído",
        lines=[
            "Serial: XK-9921-BQ",
            "Lote: 2026-A",
            "Validade: 12/2028",
        ],
        bg="#d0d0d0",
        fg="#111111",
        noise=True,
        font_size=22,
        prompt="Extraia os campos Serial, Lote e Validade desta imagem.",
        expected="Serial: XK-9921-BQ Lote: 2026-A Validade: 12/2028",
    ),
    # --- multilingual ---
    OcrTask(
        id="ocr_09",
        category="multilingual",
        difficulty="medium",
        description="Texto em português com acentos",
        lines=[
            "Comunicação Organizacional",
            "Ação imediata requerida.",
            "Avaliação de desempenho: ótimo.",
            "Próxima reunião: terça-feira.",
        ],
        prompt="Extraia todo o texto desta imagem incluindo acentos e caracteres especiais.",
        expected="Comunicação Organizacional Ação imediata requerida. Avaliação de desempenho: ótimo. Próxima reunião: terça-feira.",
    ),
    OcrTask(
        id="ocr_10",
        category="multilingual",
        difficulty="hard",
        description="Texto misto PT/EN com símbolos técnicos",
        lines=[
            "API Rate Limit: 100 req/s",
            "Latência média: 42ms ± 5ms",
            "Uptime: 99.9% (SLA garantido)",
            "Endpoint: /api/v2/dados",
        ],
        prompt="Extraia todo o texto desta imagem, incluindo todos os símbolos técnicos.",
        expected="API Rate Limit: 100 req/s Latência média: 42ms ± 5ms Uptime: 99.9% (SLA garantido) Endpoint: /api/v2/dados",
    ),
]

# ---------------------------------------------------------------------------
# Chamada ao modelo (multimodal)
# ---------------------------------------------------------------------------

def call_model_vision(model_key: str, prompt: str, image_b64: str,
                      timeout: int = 120) -> dict:
    cfg = MODELS[model_key]
    payload = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
        "think": cfg.get("think", False),
        "options": {
            "temperature": cfg.get("temperature", 0.2),
            "top_p": cfg.get("top_p", 0.8),
            "top_k": cfg.get("top_k", 20),
            "num_predict": 512,
        },
    }
    t0 = time.time()
    try:
        req = urllib.request.Request(
            cfg["url"],
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        elapsed = time.time() - t0
        content = r["message"]["content"]
        eval_count = r.get("eval_count", 0)
        return {
            "ok": True,
            "content": content,
            "elapsed": elapsed,
            "tps": eval_count / elapsed if elapsed > 0 else 0,
            "completion_tokens": eval_count,
        }
    except Exception as e:
        return {"ok": False, "content": "", "elapsed": time.time() - t0, "error": str(e), "tps": 0}


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

@dataclass
class OcrResult:
    task_id: str
    category: str
    difficulty: str
    model_key: str
    model_label: str
    passed: bool
    score: float
    predicted: str
    expected: str
    elapsed: float
    tps: float
    error: str = ""


def run_ocr_task(task: OcrTask, model_key: str) -> OcrResult:
    image_b64 = make_image(
        task.lines,
        font_size=task.font_size,
        bg=task.bg,
        fg=task.fg,
        noise=task.noise,
    )
    result = call_model_vision(model_key, task.prompt, image_b64)

    if not result["ok"]:
        return OcrResult(
            task_id=task.id, category=task.category, difficulty=task.difficulty,
            model_key=model_key, model_label=MODELS[model_key]["label"],
            passed=False, score=0.0, predicted="", expected=task.expected,
            elapsed=result["elapsed"], tps=0.0, error=result.get("error", ""),
        )

    predicted = result["content"]
    score = score_ocr(predicted, task.expected)
    passed = score >= PASS_THRESHOLD

    return OcrResult(
        task_id=task.id, category=task.category, difficulty=task.difficulty,
        model_key=model_key, model_label=MODELS[model_key]["label"],
        passed=passed, score=score, predicted=predicted.strip(), expected=task.expected,
        elapsed=result["elapsed"], tps=result["tps"],
    )


def run_ocr_benchmark(model_keys: list[str], categories: list[str] | None = None) -> list[OcrResult]:
    results = []
    tasks = [t for t in TASKS if not categories or t.category in categories]

    for mk in model_keys:
        label = MODELS[mk]["label"]
        print(f"\n{'='*70}")
        print(f"MODELO: {label}")
        print(f"{'='*70}")
        print(f"  {'Task':<12}  {'Cat':<14}  {'Dif':<8}  {'Score':>6}  {'Pass':>5}  {'TPS':>6}  Predicted[:50]")
        print(f"  {'-'*12}  {'-'*14}  {'-'*8}  {'-'*6}  {'-'*5}  {'-'*6}  {'-'*50}")

        for task in tasks:
            r = run_ocr_task(task, mk)
            results.append(r)
            mark = "PASS" if r.passed else "FAIL"
            preview = r.predicted[:50].replace("\n", " ")
            tps_str = f"{r.tps:.1f}" if r.tps > 0 else "err"
            print(f"  {task.id:<12}  {task.category:<14}  {task.difficulty:<8}  {r.score:>5.0%}  {mark:>5}  {tps_str:>6}  {preview}")

        passed = sum(1 for r in results if r.model_key == mk and r.passed)
        total = sum(1 for r in results if r.model_key == mk)
        avg_tps = sum(r.tps for r in results if r.model_key == mk and r.tps > 0)
        cnt = sum(1 for r in results if r.model_key == mk and r.tps > 0)
        print(f"\n  Score: {passed}/{total} ({passed/total*100:.0f}%)   Avg TPS: {avg_tps/cnt:.1f}" if cnt else "")

    return results


def save_results(results: list[OcrResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = output_dir / f"ocr_benchmark_{ts}.json"
    data = {
        "timestamp": datetime.now().isoformat(),
        "results": [asdict(r) for r in results],
        "summary": {},
    }
    for mk in {r.model_key for r in results}:
        mrs = [r for r in results if r.model_key == mk]
        passed = sum(1 for r in mrs if r.passed)
        avg_score = sum(r.score for r in mrs) / len(mrs) if mrs else 0
        avg_tps = sum(r.tps for r in mrs if r.tps > 0)
        cnt = sum(1 for r in mrs if r.tps > 0)
        data["summary"][mk] = {
            "label": MODELS[mk]["label"],
            "passed": passed,
            "total": len(mrs),
            "pct": passed / len(mrs) * 100 if mrs else 0,
            "avg_score": avg_score,
            "avg_tps": avg_tps / cnt if cnt else 0,
        }
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResultados salvos: {out}")


# ---------------------------------------------------------------------------
# Comparação final
# ---------------------------------------------------------------------------

def print_comparison(results: list[OcrResult]) -> None:
    model_keys = list({r.model_key for r in results})
    if len(model_keys) < 2:
        return

    print(f"\n{'='*70}")
    print("COMPARAÇÃO QWEN3.6 vs GEMMA4 — OCR")
    print(f"{'='*70}")
    print(f"  {'Task':<12}  {'Cat':<14}  {'Dif':<8}", end="")
    for mk in model_keys:
        print(f"  {MODELS[mk]['label'].split('(')[0].strip()[:16]:<16}", end="")
    print()

    for task in TASKS:
        row = f"  {task.id:<12}  {task.category:<14}  {task.difficulty:<8}"
        for mk in model_keys:
            r = next((x for x in results if x.task_id == task.id and x.model_key == mk), None)
            if r:
                row += f"  {'PASS' if r.passed else 'FAIL'} ({r.score:.0%})   "
            else:
                row += f"  {'N/A':<16}"
        print(row)

    print(f"\n  {'TOTAL':<12}  {'':14}  {'':8}", end="")
    for mk in model_keys:
        mrs = [r for r in results if r.model_key == mk]
        p = sum(1 for r in mrs if r.passed)
        pct = p / len(mrs) * 100 if mrs else 0
        avg = sum(r.score for r in mrs) / len(mrs) * 100 if mrs else 0
        print(f"  {p}/{len(mrs)} ({pct:.0f}%) avg={avg:.0f}%", end="")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark OCR — qwen3.6 vs gemma4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Exemplos:
              python bench_ocr.py                    # ambos os modelos (10 tasks)
              python bench_ocr.py --model qwen36     # só Qwen3.6
              python bench_ocr.py --model gemma4     # só Gemma4
              python bench_ocr.py --category noisy   # só tasks ruidosas
        """),
    )
    parser.add_argument("--model", choices=["qwen36", "gemma4", "both"], default="both",
                        help="Modelo(s) a usar (default: both)")
    parser.add_argument("--category", nargs="*",
                        help="Filtra categorias: plain_text structured noisy multilingual")
    args = parser.parse_args()

    model_keys = ["qwen36", "gemma4"] if args.model == "both" else [args.model]

    results = run_ocr_benchmark(model_keys, args.category)
    save_results(results, Path(__file__).parent / "results")

    if len(model_keys) > 1:
        print_comparison(results)


if __name__ == "__main__":
    main()
