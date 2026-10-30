# Ledgerline

Accounts-payable automation that runs on a local LLM. Ledgerline reads vendor invoice PDFs, extracts the
header and line items, matches them against purchase orders and goods receipts from an ERP, and hands
mismatches to an agent that proposes a fix (credit memo request, PO amendment, or hold) for a person to
approve.

Finance data punishes mistakes: a double-paid invoice costs real money. So the interesting parts are the
unglamorous ones: idempotent ingestion, money that is never a float, failures that are recorded instead of
guessed around, and a human approving every write.

> **Status:** slice 2 of 8. Uploads are idempotent, duplicates are caught before the model runs, lists
> paginate with signed cursors, and the API is defined by a checked-in OpenAPI contract with a generated
> typed client and a GraphQL read API. See the [roadmap](#roadmap) for what's next.

## What works today

Upload up to 10 invoice PDFs with a text layer, and a local model (`gemma4:12b` via Ollama) extracts each
one's header fields: vendor, tax ID, invoice number, dates, currency, subtotal, tax and total. The results are
validated, normalized and stored in Postgres.

```bash
curl -H "Idempotency-Key: $(uuidgen)" -F "files=@samples/inv-002.pdf;type=application/pdf" \
  localhost:8000/v1/invoices
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

Around that:

- **Safe retries.** Every upload carries an `Idempotency-Key`; a retry returns the stored response in tens of
  milliseconds (`Idempotent-Replayed: true`), per the IETF idempotency-key draft.
- **Duplicates never reach the model.** The same invoice uploaded again is a 409 with a link to the original,
  answered in ~28 ms.
- **Partial failures are reported per file.** A multi-file upload returns 207 with one result per file.
- **Keyset pagination** with signed cursors (`GET /v1/invoices`), and the same list over GraphQL as a Relay
  connection (`POST /graphql`).
- **Errors** are RFC 9457 problem+json with stable codes, documented in [docs/problems.md](docs/problems.md).

**Measured so far** (Apple M1 Pro, 16 GB): 27 of 27 header fields correct across the 3 sample invoices
(EUR, USD, JPY), about 25 seconds of model time per invoice. That's a smoke test, not an accuracy claim; the
60-invoice golden set and eval gates arrive in slice 6. Before/after speed numbers live in
[docs/metrics.md](docs/metrics.md).

## Design choices worth knowing

- **Money is integer minor units plus an ISO currency.** The model copies amounts as printed strings and
  code converts them; anything that would need rounding is rejected, not rounded.
  ([ADR 0003](docs/adr/0003-money-as-integer-minor-units.md))
- **The model runs locally, for free.** `gemma4:12b` through Ollama, with a JSON schema constraining its
  output, thinking off and `temperature: 0`. ([ADR 0001](docs/adr/0001-local-llm-gemma4-via-ollama.md))
- **Failures are data.** If extraction fails (model down, truncated prompt, invalid output), the upload is
  still stored with an error code, and fields the model got in the wrong shape are listed in
  `invalid_fields` instead of being guessed.
- **The OpenAPI file is the contract.** [contracts/openapi.yaml](contracts/openapi.yaml) is written first;
  `make contract-check` fails if the code would break a client generated from it, and `make codegen`
  regenerates the typed client. ([ADR 0007](docs/adr/0007-spec-first-contracts-and-graphql.md))
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
make smoke                                # end to end with the generated client: idempotency, paging, GraphQL
make test                                 # unit tests, offline
make test-int                             # service tests against a throwaway Postgres (needs Docker)
make contract-check                       # code vs. contracts/openapi.yaml (needs Docker)
```

Configuration is read from environment variables or `.env`; every key is listed in
[.env.example](.env.example).

## Roadmap

Each slice is one end-to-end change. The destination layout and stack are in [docs/architecture.md](docs/architecture.md).

| Slice | Delivers | Status |
|---|---|---|
| 1 | Upload one PDF → local model extracts header fields → stored → fetched | Done |
| 2 | Spec-first REST API, idempotent bulk upload, keyset pagination, typed Python client, GraphQL reads | Done |
| 3 | Queued extraction (Celery + RabbitMQ): retries, dead letters, partial page failures, backpressure, scanned pages | Planned |
| 4 | ERP sync with cursor pagination, 3-way match, seed data, a live expand/contract migration | Planned |
| 5 | Exception agent with tool calling; reviewer UI to approve or reject its proposals | Planned |
| 6 | Golden set of 60 invoices, eval script with gates, model sweep | Planned |
| 7 | GitHub Actions: checks, offline eval, signed images to GHCR | Planned |
| 8 | OpenTelemetry: one invoice traced from upload to approval; dashboards and alerts | Planned |

## Layout

```text
apps/api/                 FastAPI app, SQLAlchemy models, Alembic migrations, tests
contracts/                openapi.yaml (source of truth), schema.graphql (exported from code)
packages/clients/python/  typed client generated from the contract; never edited by hand
scripts/                  sample invoice generator, end-to-end checks
samples/                  generated sample PDFs with their gold JSON
docs/                     ADRs, problem types, metrics
```
