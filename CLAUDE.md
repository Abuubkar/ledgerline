# Ledgerline

Accounts-payable automation: invoice PDFs in, structured and matched invoices out, built in thin slices.

- **How we work:** [HOW_WE_BUILD.md](HOW_WE_BUILD.md). It wins over everything else, including slice prompts.
- **Where it's heading:** [docs/architecture.md](docs/architecture.md). A destination, not a to-do list.
- **Why things are the way they are:** [docs/adr/](docs/adr/). Add one for every real choice.

## Run it

```bash
docker compose up -d --wait          # Postgres :5434, RabbitMQ :5672/:15672, Redis :6379, SeaweedFS :8333,
                                     # plus the worker and outbox relay containers
uv run alembic upgrade head
ollama pull gemma4:12b               # once; Ollama runs natively on the Mac, not in Docker
uv run uvicorn ledgerline_api.main:app --port 8000
uv run python scripts/make_invoice.py    # writes samples/*.pdf + gold *.json
uv run python scripts/check_samples.py   # uploads them and compares with gold
make smoke            # end to end via the generated client
make test             # unit tests, offline
make test-int         # service tests (testcontainers Postgres)
make codegen          # regenerate client + schema.graphql after changing contracts or GraphQL types
make contract-check   # oasdiff: code vs contracts/openapi.yaml
make chaos            # 200 invoices, stub model failing 15%, one worker killed; checks nothing lost
docker compose build worker && docker compose up -d worker relay   # after changing worker code
```

## Rules that are easy to break

- Money is always integer minor units + ISO currency. Never floats, never rounding (ADR 0003).
- Model name and options come from settings; prompts live only in `prompts.py`, and any wording change bumps
  its version.
- Always pass `num_ctx` to Ollama: its default silently truncates long prompts.
- `contracts/openapi.yaml` is the source of truth: change it first, then the code, then `make codegen`.
  `packages/clients/python` is generated; never edit it by hand.
- REST and GraphQL both call `service.py`; business rules never live in a route or resolver.
- Jobs are enqueued only through the outbox (`service.enqueue_extraction`) inside the same transaction as the
  data; never publish to RabbitMQ from a request.
- New failure types go through `errors.classify`: transient is retried, permanent is dead-lettered. Error
  classes must stay picklable (Celery pickles exceptions).
- The worker image doesn't reload code: rebuild it after changing anything under `apps/api/src`.
- All model calls go through `extraction._chat`, which budgets the prompt first: Ollama truncates over-long
  prompts silently and `prompt_eval_count` is the only way to notice afterwards (ADR 0010).
- Rendering pages uses PDFium via pdfplumber, which isn't thread-safe: keep it behind `_render_lock`.
