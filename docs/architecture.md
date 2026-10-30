# Ledgerline architecture (destination)

**Pitch:** Ledgerline ingests vendor invoices (PDF/email), extracts structured line items, runs a 3-way match against purchase orders and goods receipts pulled from an ERP, and hands mismatches to a tool-using agent. The agent proposes a resolution (credit memo request, PO amendment, or a hold with a reason) that a human approves in a review UI.

**Why it isn't a toy:** Finance data punishes mistakes. A double-paid invoice costs real money, so idempotency, auditability and human-in-the-loop are product requirements, not polish.

This file is the destination after all 8 slices. Nothing here is built ahead of need: folders, services and
dependencies appear only when a slice uses them (see HOW_WE_BUILD.md). The current state is whatever the
code says.

## Target layout

This is where the project ends up after slice 8. It is a destination, not a to-do list: each folder, service and dependency appears only when a slice needs it (see HOW_WE_BUILD.md).

Decisions that changed the original plan are recorded in `docs/adr/`.

**Stack:** Python 3.13, uv workspaces, FastAPI, Pydantic v2, SQLAlchemy 2.1 async + asyncpg, Alembic, Strawberry GraphQL, Celery 5 on RabbitMQ 3.13 (quorum queues), Redis 7, Postgres 18, MinIO (S3-compatible) for documents, Next.js 15 + TypeScript for a reviewer UI, pnpm for JS.

```text
  apps/api/            FastAPI app (REST under /v1, GraphQL at /graphql), uvicorn entrypoint
  apps/worker/         Celery app + task modules
  apps/erp_mock/       separate FastAPI service imitating an ERP: cursor pagination, 429s, latency injection
  apps/web/            Next.js reviewer UI
  packages/core/       domain models, money type (int minor units + ISO currency), errors
  packages/db/         SQLAlchemy models, session factory, Alembic env + versions/
  packages/ai/         Ollama client, prompts, schemas, token/latency accounting
  packages/clients/    generated typed clients (python/, ts/), never hand-edited
  packages/telemetry/  OTel setup shared by all Python apps
  contracts/           openapi.yaml, schema.graphql (source of truth)
  evals/               golden data, harness, reports
  infra/               docker-compose.yml, otel-collector.yaml, rabbitmq definitions.json, grafana dashboards
  scripts/             seed, codegen, load-test
  .github/workflows/
```
