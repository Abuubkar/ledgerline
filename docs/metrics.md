# Speed and throughput, slice by slice

Measured numbers only, on the reference machine: Apple M1 Pro, 16 GB RAM, `gemma4:12b` via Ollama 0.40.6
running natively, Postgres 18.6 in Docker. Each slice that changes the request path adds a row; nothing is
estimated. The point is to compare **before and after** when slice 3 moves extraction onto a queue.

## Model time per invoice (unchanged by slice 2)

From `invoices.llm_ms`, `prompt_tokens` and `output_tokens` for the 3 sample invoices (EUR, USD, JPY).

| Measured in | Invoices | Avg | Min | Max | Prompt tokens | Output tokens | Output tok/s (incl. prompt eval) |
|---|---|---|---|---|---|---|---|
| Slice 1 (2026-10-30) | 6 | 26.2 s | 23.6 s | 33.8 s | 498 | 264 | 10.3 |
| Slice 2 (2026-10-30) | 3 | 25.6 s | 22.2 s | 30.5 s | 498 | 264 | 10.5 |

The first call after a pause includes a cold model load (7.5 s measured in slice 1), which is why the max is
higher. `keep_alive` is 10 minutes.

## Request latency (slice 2 baseline, synchronous extraction)

From `scripts/smoke.py` on 2026-10-30.

| Request | Result | Wall-clock |
|---|---|---|
| Upload 1 invoice | 201 | ~25 s (slice 1 runs: 23.6–33.8 s) |
| Upload 3 invoices in one request | 207 | **77.3 s** (model 30.5 + 22.2 + 24.1 s, run one after another) |
| Same request retried with the same Idempotency-Key | 207, replayed | **38 ms** |
| Same content under a new key | 409 duplicate | **28 ms** (no model call) |
| Upload 10 invoices (the current cap) | 207 | not measured; projected ~4.3 min from the per-invoice average |

What this baseline shows:

- **Uploads hold the HTTP request open for the whole extraction.** Wall-clock grows linearly with file
  count: about 25 s per invoice. That's why the cap is 10 files per request until slice 3 (decided
  2026-10-30; the plan's final cap is 50).
- **Retries and duplicates are already cheap**: both are answered from Postgres in tens of milliseconds and
  never reach the model.
- **Throughput is one invoice at a time per request**, roughly 140 invoices per hour for a single client.

## What slice 3 should change (to be measured, not assumed)

| Metric | Slice 2 (now) | Slice 3 target |
|---|---|---|
| Upload response time, 10 files | ~4.3 min (projected) | < 1 s (202 Accepted, extraction queued) |
| Time until all 10 are extracted | ~4.3 min | measure; bounded by model throughput, not HTTP |
| Concurrent model calls | 1 per request, unbounded across requests | capped at `OLLAMA_NUM_PARALLEL` |
| Upload cap per request | 10 | 50 |
