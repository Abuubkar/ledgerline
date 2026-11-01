# Challenges and how we handled them

What went wrong or got in the way while building Ledgerline, slice by slice: what happened, what we did, why, and
what else we could have done. ADRs record the choices; this file records the bumps that led to some of them, and
the ones too small for an ADR. Add an entry whenever a slice hits something a future reader would trip on too.

## Slice 1: first extraction

**JPY amounts rejected.** The model wrote a yen total as `"125000.00"`, and `to_minor` refused it for having more
decimals than JPY allows (zero).
- *Did:* trailing zeros are accepted; only digits that would need rounding are rejected (`"10.005"` EUR still fails).
- *Why:* `125000.00` is exactly ¥125,000. Refusing it was strictness without a reason, and ADR 0003's real rule is
  "never round".
- *Alternatives:* tell the model not to write decimals for JPY (fragile, per-currency prompt rules); round
  (forbidden by ADR 0003).

## Slice 2: idempotent uploads

**Regenerated sample PDFs showed up as changed.** fpdf2 embeds the creation time, so every run of the generator
rewrote all samples with identical text.
- *Did:* the generator pins the creation date, so its output is byte-identical every time.
- *Alternatives:* `.gitignore` the samples (but then the gold files and PDFs drift apart); restore them after each
  run (easy to forget).

**MinIO stopped being a free option.** Its community edition stopped publishing images in October 2025.
- *Did:* SeaweedFS for S3-compatible storage (ADR 0008).
- *Alternatives:* MinIO AIStor Free (licence agreement, poor fit for a public repo), Garage, a shared Docker volume.

## Slice 3: queue and per-page extraction

**The truncation guard never fired.** Slice 1 assumed Ollama reports a full context window when it truncates.
A ~9.7k-token prompt came back as 4,099 prompt tokens, with no error.
- *Did:* budget the prompt before sending (2 characters per token, measured at 2.8) and check `prompt_eval_count`
  afterwards; a page that doesn't fit fails alone with `prompt_too_long` (ADR 0010).
- *Alternatives:* a bigger `num_ctx` per call (more memory and a reload), a tokenizer (Ollama has no endpoint),
  reading the page as an image instead.

**A 76-second stall after the chaos test.** A killed worker held the one model slot with a fixed 240 s lease, so
every job waited for it to expire.
- *Did:* 30 s slot leases renewed while the call runs; the test also caught a late renewal reviving an expired slot
  (ADR 0009).
- *Alternatives:* a long Postgres row lock (a `docker kill` can leave it held for up to 2 hours).

**"Garbled page fails alone" couldn't be built.** pdfminer reads every corruption tried as an empty page, which is
then skipped as blank.
- *Did:* tested page-level failure with dense fine print that doesn't fit the context instead.

**The stub model left 203 junk failed invoices** in the dev database. `make chaos` now deletes its own data
(`--keep` keeps it).

## Slice 4a: vendors table, live migration

**The backfill lost printed vendor names.** The contract step dropped the columns before the backfill had copied
the names as read onto the extraction record.
- *Did:* the backfill keeps them; the whole live migration was rerun from scratch. Invoices from slices 1–2 have no
  extraction record, so theirs couldn't be recovered (dev data only).
- *Why it matters:* expand/contract is only safe if every value the old columns held has a new home before the drop
  (docs/migrations.md).

**Japanese vendor names weren't normalized** by the first name-key rule. Fixed.

**The seed made "duplicates" our own rule says aren't, and future-dated invoices.** Fixed both.

**The test harness used the new client against the old server.** Switched to the old client during the migration,
which also proved backward compatibility.

## Slice 4b: ERP sync, 3-way match

**Commits that didn't run on their own.** The first grouping split code from the models it needed.
- *Did:* regrouped before merging, so every commit passes on its own.

**An invoice could be queued for re-matching twice** (once when its PO arrived, once when its receipt did).
Re-match jobs are now deduplicated.

## Slice 5a: exception agent

**Reseed failed.** Since 4b, vendors without a tax ID survive a reseed, and the seed tried to insert them again,
after already deleting its invoices.
- *Did:* the seed reuses existing vendors by tax ID, or by normalized name for those without one, the same way
  `vendors.find_or_create` recognizes them. Lesson: delete-then-insert seeds need to tolerate rows that outlive them.

**SQLAlchemy 2.1 deprecated a loader option** (`noload`). Replaced with `raiseload`, which also fails loudly if code
touches an unloaded relationship.

## Slice 5b: reviewer UI

**The first prototypes didn't look like a live product.** The user pointed to real design references and skills.
- *Did:* redesigned from those, built two full prototypes (A, C) against the real API data, iterated on C.
- *Alternatives:* skip prototypes and build directly (costlier to change in React).

**Prototypes opened from a file broke.** `crypto.randomUUID` isn't available there, and `#/` links didn't navigate.
Added a fallback id generator and in-page routing.

**MSW 3 with Jest.** MSW 3 is ESM-only and needed `jest-fixed-jsdom`, a transform for its packages, a `setImmediate`
polyfill and `onUnhandledFrame` handling (ADR 0014).
- *Alternatives:* Vitest (native ESM, but a second test runner convention), MSW 2 (older), hand-written fetch mocks.

**Hydration error on the upload page.** The idempotency key was generated on both server and browser.
- *Did:* random ids and the current time are computed in an effect (a CLAUDE.md rule now).

**Prototype folder committed by accident.** Removed before pushing.

**The UI didn't work on a phone** (found 2026-11-01, after 6d). The stylesheet had no breakpoints: the case file kept
a fixed 320 px side panel plus 112 px of spacing, so at 375 px the case text wrapped one word per line, the panel
overlapped it, and tables ran off the screen.
- *Did:* two breakpoints in `globals.css`. Under 960 px the side panel stacks under the case; under 640 px the rail
  becomes a bottom tab bar, the command bar shrinks to its icon, facts go two across, wide tables scroll inside their
  own box, and the decision bar spans the screen above the tabs. Keyboard hints are hidden on touch screens. Checked
  at 375, 768 and 1366 px: no page scrolls sideways.
- *Alternatives:* a separate mobile view (two layouts to keep in step); card rows instead of tables on a phone (more
  markup for a reviewer who mostly works at a desk).
- *Not checked:* the approve/reject bar with a pending proposal at phone size (none pending in the dev data); the
  layout follows the same rules as the decided bar that was checked.

## Slice 6a: evals

**Unrealistic yen prices** in generated invoices (¥1.6M per item). Fixed the generator before the first live run.

**Agent scenario seeding.** Purchase orders were inserted before their vendors (no ORM relationship to order them),
and Alembic couldn't run inside the script's event loop.
- *Did:* flush vendors first; start the database container and migrate before `asyncio.run`.

**The speed gate measured the wrong thing.** p95 ≤ 45 s per invoice failed because time grows with pages.
- *Did:* gates on quality only; speed reported per invoice and per page (the user's call: the eval compares models on
  a 16 GB laptop; it doesn't police the hardware). ADR 0015.

## Slice 6b: model sweep

**Memory limits on a 16 GB machine.**
- *Did:* skipped `llama3.1:8b` (9.6 GB) and `qwen2.5:14b` at the user's request; removed `qwen3.6` (23 GB);
  sequential runs with a 15-minute rest between models; stopped unrelated services (another project's dev server,
  the Ledgerline Docker stack) during runs.
- *Alternatives:* smaller quants of the big models (still heavy and slow), a cloud GPU (not free).

**Timeouts under memory pressure.** qwen2.5's live run hit the 180 s model timeout while qwen3.5 was downloading.
- *Did:* the eval retries a timed-out case once; a timeout is recorded, so a replay reproduces it exactly. Results are
  cached per case, so the run resumed where it stopped. Two invoices still timed out after the retry.
- *Alternatives:* a longer timeout (hides real slowness), no retry (one hiccup costs a case).

**The sweep replayed a half-recorded model.** A partial recordings folder looked "recorded", replay failed, and the
sweep crashed looking for results.
- *Did:* replay first; fall back to a live run when replay reports a missing recording.

**Qwen answered every amount with null.** The extraction schema allowed amounts only as strings. Ollama constrains
generation to the schema, and Qwen writes bare numbers, so its only legal answer was `null`. qwen2.5 scored 2.5% on
totals and 2.9% line F1. That was a schema result, not a model result.
- *Found by:* a one-page probe with bare numbers allowed, which read every number correctly.
- *Did:* amounts may be a string or a number; bare numbers are parsed as `Decimal`, never float; prompt versions
  bumped; every model rerun live (ADR 0016). qwen2.5 went to 98.8% header and 97.8% line F1.
- *Surprise:* gemma4 had quoted every amount, so we expected no change. Given the choice it wrote bare numbers,
  which changed some answers (totals up, a quantity misread on 4 invoices). Quoting under a grammar was the grammar.
- *Kept:* the old results in [evals/archive/2026-11-01-strings-only-schema/](../evals/archive/2026-11-01-strings-only-schema/README.md).
- *Alternatives:* prompt Qwen to quote numbers (the grammar decides first), numbers only (floats by default), no
  schema (loses first-try validity).

**Ollama's memory figure was wrong.** `/api/ps` reported 1.0 GB for gemma4:12b (a 7.6 GB download).
- *Did:* the sweep reads the resident size of Ollama's model server process instead (8.7 GB at an 8k context).
- *Alternatives:* `/api/ps` (right for the Qwen models, wrong for gemma4), the download size (leaves out the context).

**Prompt gaps the sweep exposed.** qwen3.5 adds up a page's lines and reports the sum as a subtotal the page doesn't
print; gemma4 took the "5" in "A4 copy paper, 5 reams" as the quantity.
- *Did:* recorded here and in the sweep; a prompt change aimed at both follows as `extract-page/4`, with every model
  rerun, instead of tuning mid-sweep (which would make the comparison unfair).

## Slice 6c: prompt `extract-page/4`

**A prompt fix that helped two models and cost the third.** The new rule "subtotal only where printed, never summed"
fixed qwen3.5's invented subtotals (72.5% → 100%), but qwen2.5 stopped reading "Net GBP …" as a subtotal (95% → 90%).
- *Did:* kept the rule (it raised the default model to 100% header and every model's lines to 99.3%), recorded the
  trade-off in ADR 0017.
- *Alternatives:* list subtotal labels in the prompt ("Net", "Zwischensumme", "小計"), which would fix it but tunes the
  prompt to six generated layouts; worth trying only against real invoices.

**Memory readings wandered between runs of the same model** (gemma4: 8.7 GB, then 7.1 GB), because the reading was
taken after a long run, when macOS had compressed part of the weights.
- *Did:* `sweep.py` measures each model on a fresh load (unload, one tiny call, read, unload); `--memory` remeasures
  without rerunning the eval.

## Slice 7a: CI on GitHub Actions

**Lint had never run, so the first run found 81 type errors, 110 ruff findings and 21 ESLint errors.**
- *Did:* fixed all of them in the slice, so CI starts green (the user's call). Ruff's fixes were mostly import order
  and `X | None`. The type fixes were annotations and narrowing, with `type: ignore[code]` and a reason only where a
  library's types can't say it (strawberry's JSON scalar and relay generics, FastAPI's `app.openapi` override). No
  real bug turned up. ESLint found one real React issue (a ref written during render in `Lists.tsx`, now removed).
- *Alternatives:* report-only lint, or a baseline file of accepted findings (both leave the debt in place).

**Migration 0010 never set `lock_timeout`,** though docs/migrations.md says every migration does; it adds foreign keys
to `invoices`, which briefly locks it. Found by running squawk over all migrations.
- *Did:* left it (already applied everywhere); squawk now fails any new migration without it.
- *Alternatives:* squawk on the whole chain (48 warnings on reviewed migrations), or editing 0010 (rewrites history).

## Slice 7b: release images

**New GHCR packages start private, even in a public repository,** and GitHub has no API to change a package's
visibility. Private packages would also have filled the free plan's ~500 MB Packages allowance within a couple of
releases (four images, two architectures each, every merge).
- *Did:* the user made the four packages public in the web UI. `cosign verify` then worked without logging in, and
  verifying against the wrong workflow identity (`ci.yml`) was rejected, showing the real signer
  (`release.yml@refs/heads/main`).
- *Alternatives:* keep them private and give the CLI `read:packages`, plus a retention rule for old versions.

**Next rewrites are fixed at build time,** so the web image can't read the API address from its environment when it
starts. `API_URL` is a build argument instead (default `http://api:8000`), recorded in ADR 0019.

## Slice 8a: tracing

**The SQLAlchemy instrumentation switched itself off without a word.** Release 0.66b0 declares `sqlalchemy < 2.1`;
on our 2.1.6 the instrumentor's dependency check skipped it, so the first traces had no database spans at all.
- *Did:* `skip_dep_check=True` with a comment (the engine events it uses are unchanged in 2.1), then checked that
  INSERT/SELECT spans appear in the demo trace.
- *Alternatives:* wait for an instrumentation release that declares 2.1; downgrade SQLAlchemy (no).

**Pinned OpenTelemetry versions didn't resolve.** SDK 1.45.1 requires semantic-conventions 0.66b1, while every
0.66b0 instrumentation pins 0.66b0. The SDK and the contrib instrumentations release in matched pairs.
- *Did:* SDK 1.45.0 with instrumentations 0.66b0 (released together).

**Trace context had to cross the outbox,** where a job is published later by another process. Celery's
instrumentation only propagates from the process that publishes.
- *Did:* the request's `traceparent` rides in the outbox row's JSON payload; the relay publishes inside it
  (ADR 0020). No migration.
- *Alternatives:* a column on the outbox table (schema change); separate traces with links (harder to follow).

**Engines created at import time aren't instrumented** (the instrumentation wraps `create_async_engine` when
telemetry starts, after modules imported it).
- *Did:* the global engine is passed in; per-job engines come from `db.new_engine()`, which looks the function up at
  call time.

**Jaeger 2.22 dropped the old `/api/traces` endpoints;** only the v3 API (OTLP JSON) answers.
`scripts/trace_tree.py` reads that.

**The GenAI conventions moved repositories mid-2026** (to `open-telemetry/semantic-conventions-genai`) and renamed
`gen_ai.system` to `gen_ai.provider.name`. The spans follow the new repo, at a recorded commit (ADR 0020).

## Slice 8b: metrics, logs, alerts

**Prometheus's OTLP receiver can't count a series' first measurement.** It ignores a counter's start time (its
zero-start features cover only scraped data), so a counter whose first export already read 3 showed `increase()` = 0.
The first dead-letter test showed nothing.
- *Did:* counters are reported at 0 when each process starts (so the dead-letter counter lost its error-code label);
  histograms can't be, so the speed panel uses running totals. Documented as a known limit (ADR 0021).
- *Alternatives:* scrape /metrics instead of OTLP (needs a multiprocess setup for Celery's pool); delta temporality
  (Prometheus's conversion is experimental and has the same first-sample gap).

**Stale gauges hid an outage.** OTLP leaves no staleness marker when a process stops, so a restarted relay's old
`ollama_up=1` kept `max()` at 1 for 5 minutes while the new relay reported 0.
- *Did:* gauge alerts and panels use `last_over_time(...[1m])`.

**Metrics lost when Celery pool children exit:** no atexit hooks run, so the last 15 s never left.
- *Did:* flush in `worker_process_shutdown`. A SIGKILLed worker (as in the chaos test) still loses up to 15 s.

**I misdiagnosed the first gap as processes overwriting each other's series.** The SDK already gives each process a
random `service.instance.id`. The real causes were the killed and scaled-down workers. The host-pid id I added stays
(more readable), with the comment corrected.

**A unit doubled a name:** `{token}/s` on `ledgerline.llm.tokens_per_second` became `…_per_second_per_second` in
Prometheus. Renamed to `ledgerline.llm.output_speed`.

**httpx logged every request at INFO, URL included**: noise every 15 s from the gauges, and the RabbitMQ management
URL carries its (development) credentials. httpx is set to WARNING.

**The collector 0.163.0 release has no published image** (Docker Hub and GHCR both lack it); 0.162.0 is used.

**The queue gauge first listed Celery's internal queues** (pidbox, delayed, events). It now reports only
`invoices.*` and `erp.*`.

**My runbooks first named the dead-letter endpoints wrongly** (`/v1/dead-letters/...`); checked against the contract,
they're `/v1/admin/dead-letters` and `.../{id}/replay`.

