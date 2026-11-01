# Speed and throughput, slice by slice

Numbers measured on the reference machine: Apple M1 Pro, 16 GB RAM, `gemma4:12b` via Ollama 0.40.6 running
natively, Postgres 18.6 in Docker. Every figure says how many calls it rests on; projections are labelled as
projections. The point is to compare **before and after** when slice 3 moves extraction onto a queue.

> **These are smoke-test readings, not a benchmark.** They come from 9 model calls on the same 3 sample
> invoices. Treat differences of a second or two as noise. The real measurement is the 60-invoice golden set
> in slice 6.

## Latest eval results per model

Kept current: each eval run that changes a model's numbers updates its row here, and the numbers it replaces stay
in that slice's section below and in [evals/archive/](../evals/archive/). Dev split (40 invoices, 15 agent
scenarios), reference Mac, one model call at a time. Full table and recommendation: [evals/SWEEP.md](../evals/SWEEP.md).

| Model | Prompts | Header avg / lowest field | Line F1 | Agent | Page p50 / p95 | Invoices/h | Memory | Measured |
|---|---|---|---|---|---|---|---|---|
| **gemma4:12b** (default) | extract-page/4, agent/1 | 100% / 100% | 99.3% | 15/15 | 34 / 42 s | 73 | 8.7 GB | 2026-11-01, slice 6c |
| qwen3.5:9b-q4_K_M | extract-page/4, agent/1 | 99.0% / 90.0% (tax ID) | 99.3% | 14/15 | 21 / 27 s | 115 | 6.6 GB | 2026-11-01, slice 6c |
| qwen2.5:7b-instruct | extract-page/4, agent/1 | 98.2% / 90.0% (subtotal) | 99.3% | 10/15 | 14 / 19 s | 172 | 5.1 GB | 2026-11-01, slice 6c |

Memory is the resident size of Ollama's model server on a fresh load at `num_ctx` 8192 (`evals/sweep.py --memory`).

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

## Slice 4a: seed, backfill, live migration, deep pages

Dev database on the reference Mac, Postgres 18.6 in Docker. Full detail in [migrations.md](migrations.md).

| Measure | Result |
|---|---|
| `make seed` (small): 200 vendors, 20,030 invoices, 81,935 lines via COPY | ~1.1 s total; invoices ~100k rows/sec, lines ~100k rows/sec |
| `--profile large`: 100,030 invoices, 909,511 lines | 14.9 s end to end; lines 103k rows/sec |
| Backfill, 18,767 legacy invoices in batches of 10,000 | 0.2–0.3 s per batch (~35k invoices/sec) |
| Migrations under load (0005 / 0006 / 0007) | 0.67 s / 0.69 s / 0.55 s |
| Upload loop across all 4 steps (0.4.0 client) | 339 uploads accepted, 339 extracted, 0 errors; 32 refused connections during API restarts, retried |
| Invoice list, page 500 of 25: keyset vs `OFFSET` | **0.08 ms** (26 rows read) vs **9.4 ms** (12,501 rows walked) |

## Slice 4b: ERP sync and 3-way match

Same machine, everything in Docker except the API and Ollama. ERP mock with 5,000 POs and 5,386 goods
receipts from `make seed`.

| Measure | Result |
|---|---|
| Full sync, no faults (104 pages of 100) | 8.1 s |
| Full sync, 20% 429s (`Retry-After: 1`) and up to 300 ms latency per request, worker killed after 23 PO pages | Resumed on page 24 from the saved cursor; finished with **5,000 / 17,432 / 5,386 / 18,630** POs / PO lines / receipts / receipt lines, the mock's exact counts. 126 requests, 20 answered 429, no page fetched twice |
| Incremental sync (nothing changed) | 0.1 s, 2 requests, 0 rows written |
| Matching 5,000 seeded invoices (2 worker processes) | 71 s (~70 invoices/s); 0 dead-lettered |
| Real model, an invoice billing a PO (gemma4:12b) | PO number read from the PDF; matched. Same with line 1 priced 3% higher: exception, `price_variance` (+3.00%) |

Match result distribution for the 5,000 seeded invoices that cite a PO:

| Result | Invoices | What the seed planted |
|---|---|---|
| matched | 3,853 | clean invoices, plus 5% with a price 0.5% above the PO (inside the 1% tolerance) |
| exception: `not_received` | 493 | 10% of POs have no goods receipt |
| exception: `short_shipment` | 450 | 10% of received POs are short on one line |
| exception: `price_variance` | 138 | 3% of invoices price one line 3% above the PO |
| exception: `po_not_found` | 56 | 1% cite a PO number the ERP doesn't have |
| exception: `line_not_on_po` | 45 | 1% bill an extra line |

1,147 exceptions in all; 35 of them have more than one reason, so the reason counts add up to more.

## Slice 5a: exception agent

gemma4:12b on the same machine, `think: false`, one run per scenario through the queue (`scripts/agent_scenarios.py`).

| Scenario | Tool calls | Proposed | Expected | Model time |
|---|---|---|---|---|
| Price variance | get_po → get_receipts → compute_variance → draft_credit_memo_request | credit memo ¥376 | credit memo | 39.7 s |
| Short shipment (1 unit not received) | get_po → get_receipts → compute_variance → draft_credit_memo_request | credit memo €385.89 | credit memo | 46.8 s |
| Duplicate | get_vendor_history → propose_hold | hold: duplicate | hold: duplicate | 38.2 s |
| Missing PO | get_po (not found) → propose_hold | hold: missing_po | hold: missing_po | 29.0 s |
| Tax mismatch | propose_hold | hold: tax_mismatch | hold: tax_mismatch | 10.2 s |

- **5 of 5** expected actions; 0 guard refusals, 0 invalid tool calls, no run hit a budget.
- The first model call of a run takes 22–30 s (system prompt, tool schemas and invoice: the prompt to
  evaluate); each later call 4–8 s, because Ollama reuses the cached prompt prefix.
- Wall time per run including the wait for the model slot was 41–92 s (two workers, one model slot).
- Five runs is a smoke test, not an accuracy number: slice 6 measures 25 scenarios.

## Slice 6a: first eval baseline (gemma4:12b, dev split)

40 golden invoices and 15 agent scenarios, live against Ollama on the reference Mac (45 minutes), then replayed
offline in 11 seconds with identical numbers. Full detail in [evals/REPORT.md](../evals/REPORT.md).

| Metric | Result | Original gate | Gate now |
|---|---|---|---|
| Header fields, macro / lowest field | 98.8% / 95.0% (vendor name) | ≥ 95% / ≥ 93% | ≥ 97% / ≥ 93% |
| Line items F1 | 97.8% (135 of 139 lines right) | ≥ 88% | ≥ 95% |
| First-try schema validity | 100% | ≥ 98% | ≥ 98% |
| Calibration error (fields ≥ 90% sure) | 0.3% of 385 | ≤ 3% | ≤ 2% |
| Agent action accuracy | 100% (15/15) | ≥ 75% | ≥ 85% |
| Model time per invoice, p50 / p95 | 41 s / 148 s | p95 ≤ 45 s (missed) | reported only |
| Model time per page, p50 / p95 | 36 s / 46 s | — | reported only |
| Output tokens per second | 14.2 | — | reported only |
| Invoices per hour (one model slot) | 62 | — | reported only |

Time grows with pages: one-page invoices took 29–62 s, two-page 52–148 s, three-page 104–174 s (a repair call adds
a whole-invoice pass). What the 6 failing invoices show: a stamp over the lines lost 2 of 8 lines; one layout's total
labels ("Net / VAT / Amount payable") weren't read; the compact layout's quantity column was missed twice; one
vendor name came back with an underscore and one not at all.

## Slice 6b: model sweep (dev split)

Three models through the same eval (`evals/sweep.py`), one after another with a 15-minute rest between them. Wall
time: qwen3.5 26 min, qwen2.5 15 min (its agent results were reused, see below), gemma4 33 min. Every run replays
offline with identical numbers.

**First pass, strings-only schema (`extract-page/2`), superseded.** The schema allowed amounts only as JSON
strings, and Ollama enforces it while generating, so a model that writes bare numbers could only answer `null`
(ADR 0016). Kept in [evals/archive/2026-11-01-strings-only-schema/](../evals/archive/2026-11-01-strings-only-schema/README.md):

| Model | Header avg / lowest field | Line F1 | Agent | Page p50 / p95 | Invoices/h |
|---|---|---|---|---|---|
| gemma4:12b (6a baseline) | 98.8% / 95.0% (vendor name) | 97.8% | 15/15 | 36 / 46 s | 62 |
| qwen2.5:7b-instruct | 66.5% / 2.5% (totals) | 2.9% | 10/15 | 14 / 19 s | 94 |
| qwen3.5:9b-q4_K_M | 2-invoice trial only: numbers empty, agent correct | | | | |

**After the fix (`extract-page/3`):**

| Model | Header avg / lowest field | Line F1 | Schema valid | Calibration error | Agent | Page p50 / p95 | Invoice p50 / p95 | Tokens/s | Invoices/h | Memory |
|---|---|---|---|---|---|---|---|---|---|---|
| gemma4:12b | 99.5% / 95.0% | 96.4% | 100% | 0.3% | 15/15 | 34 / 42 s | 39 / 99 s | 14.5 | 74 | 8.7 GB |
| qwen3.5:9b-q4_K_M | 96.2% / 72.5% | 99.3% | 100% | 0.0% | 14/15 | 22 / 29 s | 26 / 66 s | 20.1 | 110 | 7.1 GB |
| qwen2.5:7b-instruct | 98.8% / 92.5% | 97.8% | 100% | 0.0% | 10/15 | 14 / 18 s | 18 / 55 s | 25.3 | 159 | 5.2 GB |

What changed and why:

- **qwen2.5 went from 66.5% to 98.8% header and 2.9% to 97.8% line F1** with no change but the schema. Its agent
  results (10/15) come from its first-pass run: the agent never uses the extraction schema, and its prompt didn't
  change.
- **gemma4 changed too, though it never had the problem.** In 6a it quoted every amount only because the grammar
  left it a quote or `null`; given the choice it writes bare numbers (558 of 558). Subtotal, tax and total went to
  100%. On 4 invoices it now takes the "5" in "A4 copy paper, 5 reams" as the quantity (line F1 97.8% → 96.4%,
  within the 1.5-point baseline tolerance). The baseline is now this run (old one archived).
- **qwen3.5's subtotal (72.5%).** On 10 multi-page invoices it reported its own sum of a page's lines as that page's
  subtotal, where none was printed. The pages then disagree, and the merge correctly leaves the field invalid
  (ADR 0010). qwen2.5 did it once.
- **Memory** is the resident size of Ollama's model server with the model loaded at `num_ctx` 8192. Ollama's
  `/api/ps` reported 1.0 GB for gemma4:12b (it leaves out the weights), so the sweep now reads the process instead.
- gemma4's p95 per invoice fell from 148 s to 99 s: totals now add up more often, so it made 2 repair calls instead
  of 7 (each re-reads the whole invoice).

## Slice 6c: prompt `extract-page/4` (dev split)

Two rules added to the extraction prompt (ADR 0017): subtotal, tax and total only where printed, never summed from
lines; quantity from its own column, not a pack size in the description. All three models rerun, one after another
with a 15-minute rest between them. Wall time: qwen3.5 21 min, qwen2.5 14 min, gemma4 33 min. The `extract-page/3`
results are kept in [evals/archive/2026-11-01-extract-page-3/](../evals/archive/2026-11-01-extract-page-3/README.md).

| Model | Header avg / lowest field | Line F1 | Calibration error | Agent | Page p50 / p95 | Invoice p50 / p95 | Tokens/s | Invoices/h | Memory |
|---|---|---|---|---|---|---|---|---|---|
| gemma4:12b | 100% / 100% (was 99.5% / 95.0%) | 99.3% (was 96.4%) | 0.0% | 15/15 | 34 / 42 s | 39 / 98 s | 14.4 | 73 | 8.7 GB |
| qwen3.5:9b-q4_K_M | 99.0% / 90.0% (was 96.2% / 72.5%) | 99.3% (same) | 0.0% | 14/15 | 21 / 27 s | 25 / 63 s | 21.8 | 115 | 6.6 GB |
| qwen2.5:7b-instruct | 98.2% / 90.0% (was 98.8% / 92.5%) | 99.3% (was 97.8%) | 0.0% | 10/15 | 14 / 19 s | 18 / 40 s | 25.4 | 172 | 5.1 GB |

- **qwen3.5's invented subtotals are gone:** subtotal 72.5% → 100%, tax 97.5% → 100%. Its one weak field is the
  Japanese "Registration No.: T…" (tax ID 90%).
- **gemma4's pack-size errors are gone:** every header field right, 137 of 139 lines. The 2 missed lines sit under
  the rubber stamp on g27 and have in every run.
- **qwen2.5 over-corrected:** lines up to 99.3%, but it no longer reads "Net GBP …" as the subtotal (subtotal 95% →
  90%), on one of the six layouts.
- **All three models now read 137 of 139 lines.** What separates them is the agent (15, 14 and 10 of 15), speed and
  memory.
- **Memory corrected.** Read right after a run, the same model's resident size varied by up to 1.7 GB (gemma4 8.7 GB
  in one run, 7.1 GB in the next), because macOS compresses idle memory. The sweep now measures on a fresh load; the
  6b figures came from a one-off load by hand; qwen3.5 read 7.1 GB there and 6.6 GB with the sweep's method, so
  treat memory differences under ~0.5 GB as noise.

## Slice 6d: held-out test split (gemma4:12b, `extract-page/4`)

The 20 invoices and 10 agent scenarios never used for tuning, run once, live, after the prompt was settled
(`make eval-test LIVE=1`, 24 minutes). Report in [evals/test-split/REPORT.md](../evals/test-split/REPORT.md).

| Metric | Test split | Dev split (6c) |
|---|---|---|
| Header avg / lowest field | 99.5% / 95.0% (subtotal) | 100% / 100% |
| Line F1 | 97.1% (83 of 85 lines) | 99.3% (137 of 139) |
| Schema valid / calibration error | 100% / 0.5% | 100% / 0.0% |
| Agent | 10/10, hold reasons 100% | 15/15 |
| Page p50 / p95 | 33 / 47 s | 34 / 42 s |
| Invoice p50 / p95 | 48 / 109 s | 39 / 98 s |

- **Every gate passes on unseen data**, so `extract-page/4` isn't fitted to the dev invoices.
- **The one miss is the tilted scan (g13),** read from the image because it has no text layer. On the tilted rows gemma
  paired two descriptions with the wrong numbers, added an empty fourth line, and read the subtotal 248,97 as 249,97.
  The arithmetic check caught it, the repair call didn't fix it, and the invoice went to `exception`: the safe outcome.
  It's the only scanned invoice in the golden set, so the dev split never measured reading from images at all, and
  one scan is too few to say how well scans go (parked in docs/backlog.md).

## Slice 8a: one invoice, one trace

After a chaos run (203 uploads, a worker killed, 0 lost, exactly the 3 corrupt files dead-lettered, 118 s), one real
invoice billing PO 4500005000 with line 1 priced 3% high went through gemma4:12b with tracing on (ADR 0020). Jaeger's
v3 API returned its trace; `scripts/trace_tree.py --invoice <id>` printed it:

```text
79 spans; 70 database/Redis spans hidden below
api      POST /v1/invoices  (137 ms)
  api      S3.PutObject  (11 ms)
  relay    apply_async/ledgerline.extract_invoice  (9 ms)
    worker   run/ledgerline.extract_invoice  (55,156 ms)  {'ledgerline.invoice_id': '74c79f61-47c5-40c1-b7ca-ec0c0bb12c63'}
      worker   S3.GetObject  (5 ms)
      worker   chat gemma4:12b  (54,857 ms)  {'gen_ai.prompt.version': 'extract-page/4', 'gen_ai.usage.input_tokens': '677', 'gen_ai.usage.output_tokens': '465', 'ledgerline.tokens_per_second': 11.5}
        worker   POST  (54,805 ms)
      relay    apply_async/ledgerline.match_invoice  (43 ms)
        worker   run/ledgerline.match_invoice  (331 ms)  {'ledgerline.invoice_id': '74c79f61-47c5-40c1-b7ca-ec0c0bb12c63'}
```

- **One trace from upload to match:** the upload request is the parent of the relay's publish, then of the worker's
  extraction, the model call and the HTTP call to Ollama, then of the match job the extraction queued (through the
  outbox again). The match found the planted price variance and a short shipment.
- **The agent run and the approval are their own traces,** found by `ledgerline.invoice_id`. The agent:
  `invoke_agent exception-agent` (38.8 s), with 4 `chat` spans (1,360 → 2,114 input tokens as the conversation
  grows; 5–16 s each) and `execute_tool` get_po → get_receipts → compute_variance → draft_credit_memo_request.
  The approval: `POST /v1/pending-actions/{action_id}:approve` (138 ms), tagged `ledgerline.decision=approved`.
- **Where the time goes:** the model call is 99.5% of the extraction job (54.9 of 55.2 s). Everything else, the
  upload included, is milliseconds.
- **Privacy:** about 5 MB of stored spans held none of the invoice's number, vendor, tax ID, total or line
  descriptions. The attribute keys are metadata only (model, tokens, prompt version, routes, SQL with `$1`
  parameters).

## Slice 8b: metrics, logs, alerts, SLO

The full observability profile (collector, Jaeger, Prometheus, Loki, Grafana) on the reference Mac, after two chaos
runs and three real invoices through gemma4:12b (ADR 0021).

| Check | Result |
|---|---|
| Chaos run (203 uploads, a worker killed) | 0 lost; the invoice-duration histogram counted 198 extracted + 3 failed, and 3 dead letters. The 2 missing were in the SIGKILLed worker |
| LLM tokens, `sum by (gen_ai_request_model, gen_ai_token_type) (gen_ai_client_token_usage_sum)` | gemma4:12b: 1,279 input, 769 output for two invoices |
| Output speed (average) | 14.4 tokens/s, as in the model sweep |
| Exemplars | 23 on the invoice-duration histogram in 15 minutes, each with a trace id |
| Logs | worker lines in Loki with `trace_id` as structured metadata |
| Tail sampling | every dead-letter trace kept (2 of 2); most chaos traces kept because nearly every upload held a 503 from the stub model |
| Alert rules | 10 rules (4 recording, 6 alerts) pass `promtool`; all healthy |
| OllamaUnreachable | relay pointed at a host that doesn't exist: pending, firing 2 minutes later with its runbook link, resolved when Ollama was reachable again |
| Release images | `docker-compose.release.yml` ran the published `main` images: API 200, UI 200, the UI container's proxy reached the API container, GraphQL answered |

The dashboard is `infra/grafana/dashboards/pipeline.json` (19 panels; generated by `scripts/make_dashboard.py`):
- the SLO stat ("within 15 minutes", 100% over the run), Ollama up, dead letters and refused uploads;
- invoices finished per minute and upload → terminal p50/p95 with exemplar dots;
- extraction p50/p95, tokens per minute by model and type, output speed, model call duration, slot wait;
- queue depth against `MAX_QUEUE_DEPTH`, dead letters by job, and logs.

## Scans and real invoices (gemma4:12b, `extract-page/4`)

Two sets beside the golden set, measured and not gated (ADR 0022). Reports: [evals/scans/REPORT.md](../evals/scans/REPORT.md),
[evals/scans/test-split/REPORT.md](../evals/scans/test-split/REPORT.md), [evals/real/REPORT.md](../evals/real/REPORT.md).

| Set | Header | Lines F1 | Calibration error | Page p50 / p95 | Statuses |
|---|---|---|---|---|---|
| Golden dev (40 text PDFs) | 100% / 100% lowest | 99.3% | 0.0% | 34 / 42 s | as expected |
| Scans dev (8) | 91.2% / 50.0% lowest (VAT ID) | 81.0% | 8.9% | — / 45 s | 2 misread amounts caught as `exception` |
| Scans test (4) | 97.5% / 75.0% lowest | 100% | 2.6% | — / 47 s | |
| Real (23 invoices + 2 other) | number 91.3%, date 91.3%, total 34.8% | 37.0% (104 of 267) | 2.0% | 80 / 147 s | exception 23, extracted 1, failed 1 (timeout) |

- **Scans:** single-digit misreads in VAT IDs (4 of 8), a due date and two amounts. At 3° tilt two lines swapped
  their numbers. The arithmetic check caught both misread amounts; nothing catches a misread VAT ID.
- **Real, the dollar sign:** these invoices print `$` and no currency code, so no currency is read and no amount can
  be converted. That empties totals and per-spot line amounts. Where a currency was read (8 invoices), all 8 totals
  were right and 70 of 94 lines were.
- **Real, by layout:** per-spot invoices 59 of 174 lines (all with a currency right: r04, r08, r25 at 100%);
  contract-line invoices 45 of 93 (count × rate doesn't need a currency; r06 and r16 at 100%). On r01, r07 and r13
  the model billed the aired spots instead of the contract lines.
- **Real, non-invoices:** the payment report got no invoice number. The order worksheet's "REP HEADLINE 6282550"
  came back as one.

