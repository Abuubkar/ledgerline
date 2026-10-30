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

## Slice 3a: queued extraction (after)

Measured on 2026-10-30 with the real model: one worker container (`--concurrency=2`), `LLM_MAX_CONCURRENCY=1`,
10 freshly generated invoices uploaded in one request, polled until all were terminal. All 10 model calls warm.

| Metric | Slice 2 (before, synchronous) | Slice 3a (after, queued) | Based on |
|---|---|---|---|
| Upload response time, 10 files | ~4.0 min warm (projected) | **0.50 s** (207, all `received`) | 1 request |
| Time until all 10 are extracted | ~4.0 min warm (projected) | **246.7 s** (4.1 min) | 1 run, 10 invoices |
| Model time per invoice (warm) | 24.2 s avg (7 calls) | 24.0 s avg, 21.9–25.6 s (10 calls) | `llm_ms` |
| Queue overhead per invoice | n/a | ~0.6 s ((246.7 − 240.5 s of model time) / 10) | the same run |
| Concurrent model calls | 1 per request, unbounded across requests | capped at 1 across all workers (Redis semaphore) | config |
| Upload cap per request | 10 | **50** (raised once uploads no longer wait for the model) | config |

What changed and what didn't:

- **The client no longer waits for the model.** The same 10 invoices that held a request open for ~4 minutes
  now return in half a second, and the client polls `GET /v1/invoices/{id}`.
- **Throughput is unchanged, and is still bound by the model**: one call at a time on this machine, about 24 s
  each, so ~150 invoices per hour. A queue doesn't make a single local model faster; it makes waiting safe.
- **Per-invoice queue cost is small**: ~0.6 s for publish, claim, S3 read, and the result write.

### A stall the measurement caught

The first after-run, started right after the chaos test, waited **~76 s** before its first model call
(first invoice done at 112 s with only 35.6 s of model time). The chaos test had killed a worker holding model
slots with a fixed 240 s lease; with one slot, the stale lease blocked every job until it expired. Slots now use
a 30 s lease renewed while the call runs (ADR 0009), and the rerun above had no stall (first invoice done at
29.5 s with 24.9 s of model time).

## Slice 3a: chaos test (stub model)

`make chaos` on 2026-10-30: 200 generated invoices + 3 corrupt PDFs, a stub model answering 15% of calls with
HTTP 503, two workers with one killed after 110 uploads. Not a speed benchmark (the stub answers in ~0.2 s).

| Check | Result |
|---|---|
| Uploaded (202) / stored | 203 / 203; 0 lost |
| Terminal status | all 203: 200 extracted, 3 failed |
| Dead letters | exactly the 3 corrupt PDFs (`unreadable_pdf`) |
| Invoices with more than one completed run | 0 |
| Transient failures retried | 35 runs (stub answered 36 calls with 503; one went to the killed worker) |
| Runs taken over after the kill | 2 abandoned leases, both completed by the other worker |
| Uploading 203 files (21 requests) | 8.7 s |
| Whole run, including waiting out the killed worker's leases | 120.9 s |

## Slice 3b: per-page extraction (real model)

`scripts/check_scenarios.py` on 2026-10-31, gemma4:12b, one worker, one model call at a time. All 36 header fields
across the four invoices matched their gold files.

| Scenario | Outcome | Model calls | Wall-clock |
|---|---|---|---|
| 3 pages, dense fine print in the middle | `partially_extracted`; page 2 failed `prompt_too_long` (no model call) | 2 text pages: 30.7 s, 30.6 s | 66 s |
| 3 pages, blank page in the middle | `extracted`; page 2 `blank` (rendered, no model call) | 2 text pages: 31.6 s, 23.5 s | 62 s |
| 1 page, total misprinted by 10,000 yen | `exception` after one repair call | text page 34.0 s + repair 38.6 s | 74 s |
| 1 page, scanned and rotated 2° | `extracted` from the image | image page 34.2 s | 41 s |

| Per call (warm) | Calls | Range |
|---|---|---|
| Text page | 5 | 23.5–34.0 s |
| Image page (scan) | 1 | 34.2 s (a standalone warm probe measured 29.7 s, 21.4 s of it encoding the image) |
| Repair call (whole invoice) | 1 | 38.6 s |

What this shows:

- **Cost scales with pages, not invoices.** A 3-page invoice with two readable pages costs two model calls
  (~55–61 s); a blank or over-long page costs none.
- **A repair roughly doubles an invoice's model time**, which is why it's limited to one call and skipped when a
  page is already missing.
- **Scans cost about the same as text pages** on this machine.
- These are 7 calls in total, a smoke-test reading; the slice 6 golden set measures properly.

## What slice 3 was expected to change (kept for reference)

| Metric | Slice 2 (now) | Slice 3 target |
|---|---|---|
| Upload response time, 10 files | ~4.0 min warm (projected) | < 1 s (202 Accepted, extraction queued) |
| Time until all 10 are extracted | ~4.0 min warm (projected) | measure; bounded by model throughput, not HTTP |
| Concurrent model calls | 1 per request, unbounded across requests | capped at `OLLAMA_NUM_PARALLEL` |
| Upload cap per request | 10 | 50 |

When slice 3 measures these, it should report warm and cold calls separately and give call counts, the same
way as above.
