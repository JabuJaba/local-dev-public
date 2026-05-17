# VRAM Policy — Sprint 36b

## Hardware
- GPU: RTX 5070 Ti, 16GB VRAM
- qwen3.6-64k:latest: ~13.3GB VRAM
- gemma4:26b: ~16GB VRAM (estimated)

## Measurements (Sprint 36b Phase 4)

| Scenario | Load time | tok/s |
|---|---|---|
| qwen3.6-64k warm | 12.0s | 17.1 |
| gemma4:26b cold (swap from qwen3.6) | 6.2s | 31.5 |
| gemma4:26b warm | 0.2s | 30.8 |
| qwen3.6-64k cold (swap back) | 10.3s | 16.9 |

## Policy: `role_specialized`

Swap < 30s (6s): role-specialized routing is viable

## Consequence for Maestro

- Phase 3 winner: gemma4:26b for both planner and executor roles
- No per-role swap needed when using gemma4:26b as single model
- qwen3.6-64k reserved for: tasks requiring >32K context, or as fallback when gemma4 unavailable
- Concurrent two-model execution: NOT viable (VRAM contention)

## Swap threshold for delegation_rules.yaml

```yaml
local_model_swap_policy: role_specialized
swap_time_s: 6
```
