# -*- coding: utf-8 -*-
"""
Sprint 36b Phase 4: VRAM / swap policy measurement.
Measures cold-load time and tok/s for model swap scenario.
"""
import os
import sys
import time
import json
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434"

def ollama_generate(model: str, prompt: str, max_tokens: int = 50) -> dict:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "num_ctx": 4096}
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def ollama_loaded_models() -> list:
    req = urllib.request.Request(f"{OLLAMA_URL}/api/ps", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return [m["name"] for m in data.get("models", [])]


def measure_model(model: str, prompt: str = "Say hello in one word.") -> dict:
    print(f"\n  Measuring {model}...")
    loaded_before = ollama_loaded_models()
    print(f"  Models loaded before: {loaded_before}")
    is_cold = model not in loaded_before

    t0 = time.time()
    result = ollama_generate(model, prompt, max_tokens=20)
    elapsed = time.time() - t0

    tok_s = result.get("eval_count", 0) / max(result.get("eval_duration", 1), 1) * 1e9
    load_duration_s = result.get("load_duration", 0) / 1e9
    prompt_eval_count = result.get("prompt_eval_count", 0)
    eval_count = result.get("eval_count", 0)

    print(f"  cold_load={is_cold} | total={elapsed:.1f}s | load_duration={load_duration_s:.1f}s | tok/s={tok_s:.1f} | tokens_in={prompt_eval_count} | tokens_out={eval_count}")
    return {
        "model": model,
        "cold_load": is_cold,
        "total_elapsed_s": elapsed,
        "load_duration_s": load_duration_s,
        "tok_s": tok_s,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
    }


print("=" * 60)
print("PHASE 4: VRAM / SWAP POLICY MEASUREMENT")
print("=" * 60)

# Step 1: warm up qwen3.6-64k (the "primary" model, 13.3GB)
print("\n[Step 1] Warm up qwen3.6-64k:latest")
r_warm = measure_model("qwen3.6-64k:latest")

# Step 2: load gemma4:26b (the executor/winner model) — forces swap if needed
print("\n[Step 2] Load gemma4:26b (cold load from qwen3.6-64k state)")
r_gemma_cold = measure_model("gemma4:26b")

# Step 3: load gemma4:26b again (warm, already in VRAM)
print("\n[Step 3] Load gemma4:26b (warm)")
r_gemma_warm = measure_model("gemma4:26b")

# Step 4: reload qwen3.6-64k (swap back)
print("\n[Step 4] Reload qwen3.6-64k:latest (swap back)")
r_qwen_cold = measure_model("qwen3.6-64k:latest")

# Analysis
print("\n" + "=" * 60)
print("ANALYSIS")
print("=" * 60)

swap_time = r_gemma_cold["load_duration_s"]
print(f"\nSwap time (qwen3.6->gemma4): {swap_time:.1f}s")
print(f"Warm load time: {r_gemma_warm['load_duration_s']:.1f}s")
print(f"gemma4 tok/s cold: {r_gemma_cold['tok_s']:.1f}")
print(f"gemma4 tok/s warm: {r_gemma_warm['tok_s']:.1f}")
print(f"qwen3.6 swap-back time: {r_qwen_cold['load_duration_s']:.1f}s")

# Policy decision
if swap_time < 30:
    policy = "role_specialized"
    policy_desc = f"Swap < 30s ({swap_time:.0f}s): role-specialized routing is viable"
elif swap_time < 90:
    policy = "single_model_per_run"
    policy_desc = f"Swap 30-90s ({swap_time:.0f}s): prefer single-model-per-run to avoid mid-pipeline swaps"
else:
    policy = "batch_mode_only"
    policy_desc = f"Swap > 90s ({swap_time:.0f}s): batch mode only — pre-schedule model per pipeline"

print(f"\nPolicy decision: {policy}")
print(f"Rationale: {policy_desc}")

# Write policy document
vram_doc = Path("orchestrator/VRAM_policy.md")
vram_doc.parent.mkdir(exist_ok=True)
vram_doc.write_text(f"""# VRAM Policy — Sprint 36b

## Hardware
- GPU: RTX 5070 Ti, 16GB VRAM
- qwen3.6-64k:latest: ~13.3GB VRAM
- gemma4:26b: ~16GB VRAM (estimated)

## Measurements (Sprint 36b Phase 4)

| Scenario | Load time | tok/s |
|---|---|---|
| qwen3.6-64k warm | {r_warm['load_duration_s']:.1f}s | {r_warm['tok_s']:.1f} |
| gemma4:26b cold (swap from qwen3.6) | {r_gemma_cold['load_duration_s']:.1f}s | {r_gemma_cold['tok_s']:.1f} |
| gemma4:26b warm | {r_gemma_warm['load_duration_s']:.1f}s | {r_gemma_warm['tok_s']:.1f} |
| qwen3.6-64k cold (swap back) | {r_qwen_cold['load_duration_s']:.1f}s | {r_qwen_cold['tok_s']:.1f} |

## Policy: `{policy}`

{policy_desc}

## Consequence for Maestro

- Phase 3 winner: gemma4:26b for both planner and executor roles
- No per-role swap needed when using gemma4:26b as single model
- qwen3.6-64k reserved for: tasks requiring >32K context, or as fallback when gemma4 unavailable
- Concurrent two-model execution: NOT viable (VRAM contention)

## Swap threshold for delegation_rules.yaml

```yaml
local_model_swap_policy: {policy}
swap_time_s: {swap_time:.0f}
```
""", encoding="utf-8")
print(f"\nVRAM policy written: {vram_doc}")

# Save raw results for reference
results_raw = {
    "warm_qwen": r_warm,
    "cold_gemma": r_gemma_cold,
    "warm_gemma": r_gemma_warm,
    "cold_qwen_back": r_qwen_cold,
    "policy": policy,
    "swap_time_s": swap_time,
}
import json as _json
Path("benchmark/results/phase4_vram.json").write_text(
    _json.dumps(results_raw, indent=2), encoding="utf-8"
)
print("Raw results: benchmark/results/phase4_vram.json")
