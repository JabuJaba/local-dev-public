#!/usr/bin/env python3
# Baseline measurement script for Sprint 10 Phase 1
# Uses Ollama /api/generate native timing fields

import json
import subprocess
import time
import urllib.request
import os
import sys

OLLAMA_URL = "http://localhost:11434"
MODELS = [
    "qwen3.6:35b-a3b-q4_k_m",
    "gemma4:26b",
    "qwen3coder-local",
]

# Fixed prompt for repeatability (~200 tokens prefill)
PREFILL_PROMPT = (
    "You are a coding assistant. Analyze the following Python function and explain "
    "what it does, identify any bugs, and suggest improvements. Focus on correctness "
    "and performance. Here is the function:\n\n"
    "def process_records(records, threshold=0.5, max_retries=3):\n"
    "    results = []\n"
    "    errors = []\n"
    "    for i, record in enumerate(records):\n"
    "        retry_count = 0\n"
    "        while retry_count < max_retries:\n"
    "            try:\n"
    "                score = compute_score(record)\n"
    "                if score >= threshold:\n"
    "                    results.append({'id': record['id'], 'score': score})\n"
    "                break\n"
    "            except Exception as e:\n"
    "                retry_count += 1\n"
    "                errors.append({'record': i, 'error': str(e), 'attempt': retry_count})\n"
    "    return results, errors\n\n"
    "Please provide your analysis:"
)

def ollama_stop():
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": "nomic-embed-text", "prompt": "", "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception:
        pass
    # Use ollama CLI to stop all loaded models
    try:
        subprocess.run(["ollama", "stop", "--all"], capture_output=True, timeout=10)
    except Exception:
        pass
    time.sleep(3)

def get_vram_mb():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            timeout=5
        ).decode().strip()
        return int(out)
    except Exception:
        return -1

def measure_model(model_name):
    print(f"\n{'='*60}", flush=True)
    print(f"Measuring: {model_name}", flush=True)

    # Stop all models first (VRAM contention)
    print("  Stopping loaded models...", flush=True)
    ollama_stop()

    vram_before = get_vram_mb()
    print(f"  VRAM before load: {vram_before} MB", flush=True)

    payload = {
        "model": model_name,
        "prompt": PREFILL_PROMPT,
        "stream": False,
        "options": {
            "num_predict": 200,
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "repeat_penalty": 1.05,
        }
    }

    print("  Running inference (200 prefill + 200 TG)...", flush=True)
    t_start = time.time()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read()
            result = json.loads(raw)
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        return None

    t_elapsed = time.time() - t_start

    # Parse timing fields (nanoseconds)
    prompt_tokens = result.get("prompt_eval_count", 0)
    prompt_ns = result.get("prompt_eval_duration", 0)
    gen_tokens = result.get("eval_count", 0)
    gen_ns = result.get("eval_duration", 0)

    prefill_tps = prompt_tokens / (prompt_ns / 1e9) if prompt_ns > 0 else 0
    tg_tps = gen_tokens / (gen_ns / 1e9) if gen_ns > 0 else 0

    # Measure VRAM during loaded state (model is cached after first inference)
    vram_after = get_vram_mb()
    vram_model_mb = max(0, vram_after - vram_before)

    metrics = {
        "model": model_name,
        "prompt_tokens": prompt_tokens,
        "gen_tokens": gen_tokens,
        "prefill_tps": round(prefill_tps, 1),
        "tg_tps": round(tg_tps, 1),
        "vram_before_mb": vram_before,
        "vram_after_mb": vram_after,
        "vram_model_mb": vram_model_mb,
        "total_elapsed_s": round(t_elapsed, 1),
    }

    print(f"  Prompt tokens:   {prompt_tokens}", flush=True)
    print(f"  Generated tokens:{gen_tokens}", flush=True)
    print(f"  Prefill t/s:     {prefill_tps:.1f}", flush=True)
    print(f"  TG t/s:          {tg_tps:.1f}", flush=True)
    print(f"  VRAM before:     {vram_before} MB", flush=True)
    print(f"  VRAM after:      {vram_after} MB", flush=True)
    print(f"  VRAM model:      {vram_model_mb} MB (delta)", flush=True)

    return metrics


def main():
    cuda_version = "unknown"
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            timeout=5
        ).decode().strip()
        driver_ver = out
        # Get CUDA version from nvcc or nvidia-smi header
        smi_out = subprocess.check_output(["nvidia-smi"], timeout=5).decode()
        for line in smi_out.splitlines():
            if "CUDA Version" in line:
                parts = line.split("CUDA Version:")
                if len(parts) > 1:
                    cuda_version = parts[1].strip().split()[0]
                break
    except Exception:
        driver_ver = "unknown"

    print(f"CUDA Version: {cuda_version}", flush=True)
    print(f"Driver: {driver_ver}", flush=True)

    all_metrics = []
    for model in MODELS:
        m = measure_model(model)
        if m:
            all_metrics.append(m)
        # Small pause between models
        time.sleep(2)

    # Final ollama stop
    ollama_stop()

    # Output JSON for processing
    print("\n\nJSON_RESULTS_START")
    print(json.dumps({"cuda_version": cuda_version, "driver": driver_ver, "models": all_metrics}, indent=2, ensure_ascii=False))
    print("JSON_RESULTS_END")


if __name__ == "__main__":
    main()
