---
status: accepted
date: 2026-10-30
---

# Local LLM: gemma4:12b through Ollama, run natively on the host

> **Update, 2026-11-04:** The exception agent (ADR 0013) and scanned pages both run on gemma4:12b. The slice 6 eval
> since measured it: every gate passed (100% header fields, 99.3% line items, 15/15 agent actions on dev; 99.5%,
> 97.1% and 10/10 held out). The newer small model was tested too: qwen3.5:9b-q4_K_M in the model sweep (ADR 0017,
> evals/SWEEP.md). gemma4:12b stays the default.

Invoice extraction (and later the exception agent and scanned pages) uses `gemma4:12b` served by Ollama on
the developer's Mac, called through the official `ollama` Python client with a JSON schema in `format`,
`think: false`, `temperature: 0` and an explicit `num_ctx`. It's free, already installed, current
generation, and a single model covers text, images (scanned pages) and tool calls.

## Considered options

- **qwen2.5:7b-instruct** (the original plan's default): ~4.7 GB download, likely 1.5–2× faster, but an
  older generation and text-only, so scans would need a second model (qwen2.5vl).
- **A newer small model** (7–9B with vision): would need a search, a download and a test before committing.
- **Claude API**: best quality, but costs money per call; ruled out for now by the "free" constraint.
- **qwen3.6 (already installed)**: 36B MoE, 23 GB. Doesn't fit in 16 GB RAM without heavy swapping.

## Assumptions

- Hardware is an Apple M1 Pro with 16 GB RAM. Measured 2026-10-30: 11.6 output tokens/s on a small
  structured-output prompt, 7.5 s cold load. A full invoice is expected to take roughly 20–30 s.
- Ollama runs natively, not in Docker: Docker on macOS has no GPU (Metal) access.
- `think: false` is safe for extraction because copying fields needs no reasoning trace; this is checked in
  the slice 6 eval, and revisited if accuracy suffers.
- Quality is unproven until the slice 6 eval. If gemma4:12b misses the gates, rerun the model sweep and
  supersede this ADR.

## Consequences

- Model name and options live in settings (`LLM_MODEL`, `LLM_NUM_CTX`, ...), so switching models is a
  config change plus an eval run.
- CI can't call the model (no GPU on runners); it replays recorded responses from slice 6 on.
