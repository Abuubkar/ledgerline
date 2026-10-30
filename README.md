# Ledgerline

Accounts-payable automation that runs on a local LLM. Ledgerline reads vendor invoice PDFs, extracts the
header and line items, matches them against purchase orders and goods receipts from an ERP, and hands
mismatches to an agent that proposes a fix (credit memo request, PO amendment, or hold) for a person to
approve.

Finance data punishes mistakes: a double-paid invoice costs real money. So the interesting parts are the
unglamorous ones: idempotent ingestion, money that is never a float, failures that are recorded instead of
guessed around, and a human approving every write.

> **Status:** slice 1 of 8. Today it uploads one PDF and extracts its header fields. See the
> [roadmap](#roadmap) for what's next.

## What works today

Upload an invoice PDF with a text layer, and a local model (`gemma4:12b` via Ollama) extracts its header
fields: vendor, tax ID, invoice number, dates, currency, subtotal, tax and total. The result is validated,
normalized and stored in Postgres.

```bash
curl -F file=@samples/inv-002.pdf localhost:8000/v1/invoices
```

```json
{
  "status": "extracted",
  "vendor_name": "Northwind Supplies Inc.",
  "invoice_number": "NW-48213",
  "invoice_date": "2026-10-02",
  "currency": "USD",
  "total": { "amount_minor": 208865, "currency": "USD" },
  "model": "gemma4:12b",
  "llm_ms": 25503
}
```

*(Response trimmed.)*

**Measured so far** (Apple M1 Pro, 16 GB): 27 of 27 header fields correct across the 3 sample invoices
(EUR, USD, JPY), about 25 seconds per invoice. That's a smoke test, not an accuracy claim; the 60-invoice
golden set and eval gates arrive in slice 6.

## Design choices worth knowing

- **Money is integer minor units plus an ISO currency.** The model copies amounts as printed strings and
  code converts them; anything that would need rounding is rejected, not rounded.
  ([ADR 0003](docs/adr/0003-money-as-integer-minor-units.md))
- **The model runs locally, for free.** `gemma4:12b` through Ollama, with a JSON schema constraining its
  output, thinking off and `temperature: 0`. ([ADR 0001](docs/adr/0001-local-llm-gemma4-via-ollama.md))
- **Failures are data.** If extraction fails (model down, truncated prompt, invalid output), the upload is
  still stored with an error code, and fields the model got in the wrong shape are listed in
  `invalid_fields` instead of being guessed.
- **Built in thin vertical slices**, each running end to end on real input, with every real choice recorded
  as an [ADR](docs/adr/). The working rules are in [HOW_WE_BUILD.md](HOW_WE_BUILD.md).

## Run it

Needs Docker, [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com) running natively (Docker on
macOS has no GPU access, so the model runs outside it).

```bash
ollama pull gemma4:12b
docker compose up -d --wait               # Postgres 18 on localhost:5434
uv run alembic upgrade head
uv run uvicorn ledgerline_api.main:app --port 8000
```

In another terminal:

```bash
uv run python scripts/make_invoice.py     # renders samples/*.pdf with gold JSON
uv run python scripts/check_samples.py    # uploads them and compares with gold
uv run pytest
```

Configuration is read from environment variables or `.env`; every key is listed in
[.env.example](.env.example).

## Roadmap

Each slice is one end-to-end change. The destination layout and stack are in [docs/architecture.md](docs/architecture.md).

| Slice | Delivers | Status |
|---|---|---|
| 1 | Upload one PDF → local model extracts header fields → stored → fetched | Done |
| 2 | Spec-first REST API, idempotent bulk upload, keyset pagination, typed Python client, GraphQL reads | In progress |
| 3 | Queued extraction (Celery + RabbitMQ): retries, dead letters, partial page failures, backpressure, scanned pages | Planned |
| 4 | ERP sync with cursor pagination, 3-way match, seed data, a live expand/contract migration | Planned |
| 5 | Exception agent with tool calling; reviewer UI to approve or reject its proposals | Planned |
| 6 | Golden set of 60 invoices, eval script with gates, model sweep | Planned |
| 7 | GitHub Actions: checks, offline eval, signed images to GHCR | Planned |
| 8 | OpenTelemetry: one invoice traced from upload to approval; dashboards and alerts | Planned |

## Layout

```text
apps/api/        FastAPI app, SQLAlchemy models, Alembic migrations, tests
scripts/         sample invoice generator and end-to-end check
samples/         generated sample PDFs with their gold JSON
docs/adr/        architecture decision records
```
