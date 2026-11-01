# Backlog: improvements found but not done

Problems we know about and how we'd fix them, parked on purpose. Each entry says what's wrong, how big it is, the
suggested fix and its cost, and why it waits. Picking one up means following HOW_WE_BUILD.md like any change: a
prompt wording change bumps its version and reruns every model (`evals/sweep.py --live`), with the old results
archived first.

## Extraction

### Currency from the purchase order when an invoice prints only a symbol

- **What:** US invoices print `$`, never "USD". Ledgerline reads no currency, can't convert any amount, and sends the
  invoice to `exception` with the total and line amounts empty. On the real set this emptied the total on 14 of 23 invoices (a 15th timed out).
- **Fix:** keep the model copying what's printed, but when the currency is missing and the invoice cites a PO (or
  the vendor master has one), take the currency from there before converting amounts. Never guess from the
  symbol alone (`$` is also CAD, AUD...).
- **Cost:** a small change in the extraction job plus tests; rerun the real set. **Found:** real-invoice eval,
  2026-11-01 (ADR 0022).

### Check VAT IDs before trusting them

- **What:** on scans the model misreads single digits in VAT IDs (4 of 8 dev scans). Nothing checks them, and an
  invoice's vendor is found by its tax ID, so a misread ID links the invoice to the wrong vendor or makes a new one.
- **Fix:** validate the country's check digits (DE, GB, EU VAT formats) and mark a failing ID invalid instead of
  linking it; optionally match by name when the ID fails.
- **Cost:** a validation function with tests; no model change. **Found:** scans eval, 2026-11-01.

### Real pages: sideways scans and time limits

- **What:** dense real pages take 80–147 s of model time; a two-page sideways scan timed out at 180 s. Four of the
  five real scans are printed sideways.
- **Fix:** detect page orientation before reading (e.g. compare text-line angles, or try both and keep the better
  answer); give image pages a longer budget.
- **Found:** real-invoice eval, 2026-11-01.

### Japan's registration number isn't read as the vendor's tax ID (qwen3.5 only)

- **What:** Japanese invoices print the seller's tax registration number as "Registration No.: T9876543210987"
  (T + 13 digits, required on qualified invoices since October 2023). qwen3.5:9b leaves `vendor_tax_id` empty on all
  4 such invoices in the dev split (tax ID 90%). gemma4 and qwen2.5 read it.
- **Why:** the prompt says "the seller's VAT or tax ID as printed", and "Registration No." doesn't say "tax".
- **Fix:** name the forms in the `vendor_tax_id` rule in `prompts._FIELD_RULES`, e.g. "the seller's VAT or tax ID as
  printed (a VAT number, USt-IdNr., or Japan's registration number, T followed by 13 digits)".
- **Cost:** a prompt version bump and a rerun of all three models (~70 min of model time plus rests).
- **Why it waits:** it only affects qwen3.5, which isn't the default. This is a real-world rule, not tuning to our
  layouts, so it's safe to add when qwen3.5 is considered seriously or with the next prompt change.
- **Found:** slice 6c (ADR 0017), 2026-11-01.

### "Net" isn't read as the subtotal (qwen2.5 only)

- **What:** one generated layout labels the subtotal "Net GBP 3,572.00". Since `extract-page/4`, qwen2.5:7b answers
  null there on 4 of 7 invoices (it read all 7 under `extract-page/3`). gemma4 and qwen3.5 read all 7. Tax and total
  stay right and the invoices still end `extracted`; only the subtotal is empty and the subtotal cross-check is
  skipped.
- **Why:** `extract-page/4` says "only the invoice's own figures, where printed… never add up line amounts". qwen2.5
  seems to distrust a figure labelled "Net" that equals the sum of the lines (our reading of the pattern).
- **Fix:** add common subtotal labels to the rule: "the subtotal may be labelled Net, Net amount, Zwischensumme, 小計
  (Shokei)…".
- **Cost:** as above, a version bump and a rerun of all three models.
- **Why it waits:** it tunes the prompt to the labels of our six generated layouts, and only affects qwen2.5, which
  isn't a candidate (agent 10/15). Worth trying against real invoices.
- **Found:** slice 6c (ADR 0017), 2026-11-01.

### A text stamp over line items scrambles the text layer (all models)

- **What:** on g27 a tilted "PAID 2026-10-31" stamp drawn as text sits over two line items. pdfplumber groups
  characters into lines by height, and the stamp's staircase of letters chains rows 2 and 3 into one "line", so their
  letters interleave (`U / Sa / S / f / B / e…`). Every model loses those 2 of 139 lines; the totals then don't add up
  and the invoice correctly goes to `exception`.
- **Fix (preferred):** detect scrambled page text (mostly one- or two-letter lines) and re-read that page with
  `extract_text(use_text_flow=True)` (draw order, which gives clean rows here) or as an image. Only broken pages
  change, so only their model calls rerun (minutes, not hours).
- **Alternatives:** always use draw order (breaks PDFs that draw columns separately); drop oversized or odd
  characters (guesswork).
- **Why it waits:** the user chose to leave it (2026-11-01). Real stamps are usually scanned images or annotations,
  which don't touch the text layer, so our generated stamp is harsher than most real PDFs.
- **Found:** slice 6b/6c, 2026-11-01.

## Observability

### Langfuse as a second destination for the model and agent spans

- **What:** Langfuse (open source, self-hostable) shows LLM calls and agent runs as conversations, with prompt
  versions, scores and feedback. LangSmith is the hosted equivalent.
- **Why it might help:** reading individual agent runs (which tool, which answer) in a UI built for it, alongside
  Jaeger's view of the whole pipeline.
- **Fix:** Langfuse accepts OTLP, and the spans already follow the GenAI conventions (ADR 0020), so it's mostly an
  extra exporter in `ledgerline_telemetry`. The catch is content: Langfuse is most useful with prompt and answer
  text, which Ledgerline's telemetry drops on purpose (invoice data). It would need either metadata only or a
  decision that text may be kept in a local, access-controlled Langfuse.
- **Cost:** self-hosted Langfuse v3 needs Postgres, ClickHouse, Redis and S3 (several GB of memory).
- **Why it waits:** prompts are versioned in code and quality is measured by the eval harness; the user asked about
  it as a question, not a requirement (2026-11-01).
- **Found:** slice 8a, 2026-11-01.

### Alertmanager, so alerts reach someone

- **What:** Prometheus evaluates the alerts and Grafana shows them, but nothing notifies anyone.
- **Fix:** add Alertmanager to the observability profile with a route per severity (`page`, `ticket`) to a channel
  (email, Slack, a webhook); Prometheus's `alerting:` block points at it.
- **Why it waits:** there's no on-call channel for a local portfolio stack. Found: slice 8b, 2026-11-01.

