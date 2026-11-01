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
make seed             # 200 vendors, 20k invoices, 30 near-duplicates into the dev DB, plus data/erp/dataset.json
                      # for the ERP mock (PROFILE=large: ~1M lines); restarts erp_mock
uv run python scripts/sync_erp.py [--full]   # one ERP sync now; beat runs it every 5 min
uv run python scripts/match_pending.py       # queue matches for extracted invoices with a PO and no match yet
uv run python scripts/agent_scenarios.py     # real model: agent on 5 seeded exception scenarios, prints traces
make chaos            # 200 invoices, stub model failing 15%, one worker killed; checks nothing lost, then deletes its data (--keep to keep)
docker compose build worker && docker compose up -d worker relay   # after changing worker code
pnpm --dir apps/web install && make web   # reviewer UI on :3000, proxying /graphql and /v1 to the API on :8000
make test-web                             # Jest + MSW for the UI
make eval                                 # evals on the dev split, replaying recorded model answers (no Ollama)
make eval LIVE=1                          # the same against Ollama, recording answers (~1 h); commit evals/recordings
make eval-test                            # the held-out test split: only to check a finished change
```

## Rules that are easy to break

- Money is always integer minor units + ISO currency. Never floats, never rounding (ADR 0003).
- Model name and options come from settings; prompts live only in `prompts.py`, and any wording change bumps
  its version.
- Always pass `num_ctx` to Ollama: its default silently truncates long prompts.
- `contracts/openapi.yaml` is the source of truth: change it first, then the code, then `make codegen`.
  `packages/clients/python` is generated; never edit it by hand.
- REST and GraphQL both call `service.py`; business rules never live in a route or resolver.
- Jobs are enqueued only through the outbox (`service.enqueue_extraction` / `enqueue_match`) inside the same
  transaction as the data; never publish to RabbitMQ from a request. The one exception is `sync_erp`, which
  Celery beat sends on a schedule. Run exactly one beat.
- A new task needs its queue in `service.OUTBOX_QUEUES` (if sent through the outbox), `worker.task_queues`, and
  `infra/rabbitmq/definitions.json` (RabbitMQ only reads it at boot: restart it after a change).
- New failure types go through `errors.classify`: transient is retried, permanent is dead-lettered. Error
  classes must stay picklable (Celery pickles exceptions).
- The worker image doesn't reload code: rebuild it after changing anything under `apps/api/src`.
- All model calls go through `extraction.call_model`, which budgets the prompt first: Ollama truncates over-long
  prompts silently and `prompt_eval_count` is the only way to notice afterwards (ADR 0010). Extraction wraps it
  in `_chat` (JSON schema); the agent calls it with `tools=`.
- Rendering pages uses PDFium via pdfplumber, which isn't thread-safe: keep it behind `_render_lock`.
- Schema changes on big tables follow docs/migrations.md: additive first, `CREATE INDEX CONCURRENTLY` inside
  `autocommit_block()`, foreign keys `NOT VALID` then `VALIDATE`, `lock_timeout` set, and columns dropped only
  after the code that used them is gone. Migrations run one transaction per file.
- An invoice's vendor comes from `vendors.link` (tax ID, else normalized name). What the model read is on the
  completed `extraction_runs.extracted_header`, not on the invoice.
- `sync_erp` commits once per page, together with the ERP cursor and `synced_through`; never batch pages into
  one transaction, or a crash re-reads (and an expired cursor loses) everything since the last commit.
- Match rules live in `matching.py` as plain functions; `jobs.match` only loads rows and stores the result.
  Only `extracted` invoices with a PO number are matched (plus re-matches of failed matches).
- The agent only proposes: its write tools create `pending_actions` rows and nothing else. Money in a proposal
  comes from `agent.compute_variance`, never from the model's arguments; tool argument models forbid extra
  fields. Guards and budgets live in `agent.run_loop`, not in the prompt (ADR 0013).
- Approve/reject goes through `service.decide_pending_action` (one conditional UPDATE on `version`), from REST
  and GraphQL alike.
- The UI reads through GraphQL (`apps/web/src/lib/queries.ts`, typed by `make codegen`; never edit `src/gql`). REST
  only for uploads and dead letters (`src/lib/rest.ts`). Wording for reviewers lives in `src/lib/present.ts`;
  decision rules never move into the UI.
- Money in the UI goes through `formatMinor` / `formatMoney` (`src/lib/money.ts`), which must agree with Python's
  `format_minor` on `packages/clients/fixtures/money.json`. Never divide minor units by 100 in TypeScript.
- Anything that can differ between server and browser (random ids, the current time) is computed in an effect,
  or the page fails to hydrate.
- Changing a prompt (and bumping its version) or anything that changes what's sent to the model invalidates the
  recordings: run `make eval LIVE=1`, then commit `evals/recordings/`, `evals/REPORT.md` and `evals/results.json`.
  Never tune against the test split.
- Golden gold files come from the generator (`make golden`); don't edit them by hand. Agent scenarios
  (`evals/golden/agent/*.yaml`) are hand-maintained.
