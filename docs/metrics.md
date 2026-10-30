# Speed and throughput, slice by slice

Numbers measured on the reference machine: Apple M1 Pro, 16 GB RAM, `gemma4:12b` via Ollama 0.40.6 running
natively, Postgres 18.6 in Docker. Every figure says how many calls it rests on; projections are labelled as
projections. The point is to compare **before and after** when slice 3 moves extraction onto a queue.

> **These are smoke-test readings, not a benchmark.** They come from 9 model calls on the same 3 sample
> invoices. Treat differences of a second or two as noise. The real measurement is the 60-invoice golden set
> in slice 6.

## Model time per invoice

From `invoices.llm_ms` (wall-clock around the Ollama call, including any model load), `prompt_tokens` and
`output_tokens`. Every call used the same 3 samples (EUR, USD, JPY): ~498 prompt tokens and ~264 output
tokens each.

A call is **cold** when the model wasn't in memory: the first call of a run, more than 10 minutes
(`keep_alive`) after the previous one. All other calls are **warm**. Cold calls include loading the model,
so they're reported separately; mixing them into one average makes runs incomparable.

| | Calls | Avg | Min | Max | Output tok/s (incl. prompt eval) |
|---|---|---|---|---|---|
| **Warm**, all slices | 7 | **24.2 s** | 22.2 s | 26.0 s | 11.0 |
| Warm, slice 1 | 5 | 24.6 s | 23.6 s | 26.0 s | 10.8 |
| Warm, slice 2 | 2 | 23.1 s | 22.2 s | 24.1 s | 11.5 |
| **Cold**, all slices | 2 | **32.1 s** | 30.5 s | 33.8 s | 8.2 |

- **Slice 2 didn't change model time**, and couldn't have: it doesn't touch the model call. The 1.5 s gap
  between the warm rows rests on 5 and 2 calls and is noise.
- **A cold start adds roughly 8 s**, consistent with the 7.5 s model load measured directly in slice 1.
- **Why the call counts differ.** Slice 1 ran `scripts/check_samples.py` twice (the first run exposed the JPY
  money bug, the second ran after the fix), and slice 1 had no duplicate detection, so 6 calls. In slice 2
  each sample reaches the model once; every later upload of the same samples is a 409 duplicate answered in
  milliseconds, so only 3 calls.

### Every call

| Time (PKT) | Invoice | Model time | Run | Cold? |
|---|---|---|---|---|
| 13:05:12 | inv-001 | 33.8 s | Slice 1, run 1 | cold |
| 13:05:36 | inv-002 | 23.6 s | Slice 1, run 1 | |
| 13:06:00 | inv-003 | 23.9 s | Slice 1, run 1 | |
| 13:07:00 | inv-001 | 24.2 s | Slice 1, run 2 (after the JPY fix) | |
| 13:07:25 | inv-002 | 25.5 s | Slice 1, run 2 | |
| 13:07:51 | inv-003 | 26.0 s | Slice 1, run 2 | |
| 14:22:49 | inv-001 | 30.5 s | Slice 2 smoke run | cold |
| 14:23:19 | inv-002 | 22.2 s | Slice 2 smoke run | |
| 14:23:42 | inv-003 | 24.1 s | Slice 2 smoke run | |

All on 2026-10-30.

## Request latency (slice 2 baseline, synchronous extraction)

From `scripts/smoke.py` on 2026-10-30.

| Request | Result | Wall-clock | Based on |
|---|---|---|---|
| Upload 1 invoice | 201 | ~24 s warm, ~32 s cold | the model-time table above |
| Upload 3 invoices in one request | 207 | **77.3 s** (model 30.5 cold + 22.2 + 24.1 s, one after another) | 1 request |
| Same request retried with the same Idempotency-Key | 207, replayed | **38 ms** (7 ms on a later rerun) | 2 requests |
| Same content under a new key | 409 duplicate | **28 ms** (20 ms on a later rerun), no model call | 2 requests |
| Upload 10 invoices (the current cap) | 207 | **projected** ~4.0 min warm, ~4.2 min if the first call is cold | 10 × 24.2 s; not measured |

What this baseline shows:

- **Uploads hold the HTTP request open for the whole extraction.** Wall-clock grows linearly with file
  count, about 24 s per invoice when warm. That's why the cap is 10 files per request until slice 3 (decided
  2026-10-30; the plan's final cap is 50).
- **Retries and duplicates are already cheap**: both are answered from Postgres in tens of milliseconds and
  never reach the model.
- **Throughput is one invoice at a time per request**: about 150 invoices per hour for a single client with
  a warm model (projected from 24.2 s per call).

## What slice 3 should change (to be measured, not assumed)

| Metric | Slice 2 (now) | Slice 3 target |
|---|---|---|
| Upload response time, 10 files | ~4.0 min warm (projected) | < 1 s (202 Accepted, extraction queued) |
| Time until all 10 are extracted | ~4.0 min warm (projected) | measure; bounded by model throughput, not HTTP |
| Concurrent model calls | 1 per request, unbounded across requests | capped at `OLLAMA_NUM_PARALLEL` |
| Upload cap per request | 10 | 50 |

When slice 3 measures these, it should report warm and cold calls separately and give call counts, the same
way as above.
