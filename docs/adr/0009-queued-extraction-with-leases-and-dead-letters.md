---
status: accepted
date: 2026-10-30
---

# Extraction runs on Celery + RabbitMQ quorum queues, with leases, an outbox, and dead letters

Uploads store the PDF, insert the invoice and an outbox row in one transaction, and return 202. An outbox
relay publishes the job to the `invoices.extract` quorum queue; Celery workers extract it. Failures are split
into transient (retried with exponential backoff and full jitter, max 5) and permanent (corrupt PDF, unusable
model output). When a job gives up, `on_failure` writes a `dead_letters` row and marks the invoice failed, and
Celery rejects the message without requeue so RabbitMQ moves it to `invoices.extract.dlq`. A Redis semaphore
with leased slots caps model calls across all workers, and uploads get 429 when too many jobs are waiting.

## Decisions inside this, and why

- **Leases instead of holding a row lock for the whole job.** The plan said `SELECT ... FOR UPDATE SKIP
  LOCKED` for the duration. A container killed with `docker kill` may never close its Postgres connection, so
  that lock can survive until TCP keepalive gives up (Postgres's default idle time is 2 hours) and the invoice
  is stuck. Instead an attempt claims the invoice briefly with `SKIP LOCKED`, inserts a `running` row in
  `extraction_runs` (a unique index allows one), and renews its lease every 20 s. A killed worker's lease lapses
  within 60 s; the redelivered message marks it `abandoned` and takes over. A second unique index allows only
  one `completed` run per invoice, so double extraction is impossible, not just unlikely.
- **Outbox relay instead of publishing from the request.** Publishing after commit can lose the job if the
  process dies in between; publishing before commit can queue a job for an upload that then rolls back. The
  relay is at-least-once, which the idempotent job tolerates.
- **Topology at broker boot, dead-lettering by policy.** `infra/rabbitmq/definitions.json` declares the queues
  and a policy with `dead-letter-exchange`, `delivery-limit: 6`, `dead-letter-strategy: at-least-once` and
  `overflow: reject-publish`. In RabbitMQ 4.x the delivery limit is set by policy (default 20); at-least-once
  dead-lettering requires reject-publish overflow. The limit catches messages that kill workers repeatedly.
- **The model stays out of the retry decision for bad output.** Temperature is 0, so the same input gives
  the same invalid output; retrying wastes model time. Unknown exceptions are treated as permanent so bugs show
  up in the dead-letter queue instead of looping.
- **Celery despite having no asyncio support.** Celery is what most Python teams run and supports quorum
  queues since 5.5. Each task runs the async job with `asyncio.run` and opens fresh DB and Redis connections,
  because asyncpg connections can't cross event loops. An async-native queue (taskiq, arq) would avoid that,
  at the cost of a less common stack.

## Gotchas found while building it (RabbitMQ 4.4, Celery 5.6.3)

- RabbitMQ 4.3+ refuses transient non-exclusive queues, which Celery's remote-control and event queues are by
  default; the worker crash-loops on start. `control_queue_exclusive=True` and `event_queue_exclusive=True` fix
  it (the matching Kombu default change is described for 5.7, not yet released).
- Importing definitions at boot skips creating the default user, so the user is declared in the file with a
  SHA-256 password hash.
- Quorum queues require `confirm_publish`; Celery turns off global QoS and schedules retry countdowns with
  native delayed delivery.
- Celery pickles exceptions. An exception class whose `args` can't rebuild it reaches `on_failure` as an
  `UnpickleableExceptionWrapper`, losing its error code; our error classes pass all fields to `Exception`.
- The model-call semaphore first used a fixed 240 s slot lease. Measured on 2026-10-30: after the chaos test
  killed a worker holding slots, the next real-model batch waited **~76 s** before its first call, because
  with one slot the dead worker's stale lease blocked all extraction until it expired. Slots now use a 30 s
  lease renewed every 10 s while the call runs, so a crash stalls extraction for at most one short lease. A
  renewal never revives a lease that already lapsed.
- The API stays on the host during development and the workers run in Docker, so they reach S3, Postgres and
  RabbitMQ by different hostnames; stored file references are `s3://` URIs for that reason.

## Assumptions

- `llm_max_concurrency` matches Ollama's parallelism (1 on the reference Mac). More concurrent calls only queue
  inside Ollama and make time limits fire.
- A job finishes well inside its 300 s hard time limit; a page-level split (slice 3b) keeps it that way for long
  invoices.
- A message dead-lettered by the delivery limit (a crash loop) skips `on_failure`, so it has no `dead_letters`
  row yet; it is visible only in the RabbitMQ DLQ. Acceptable for now; revisit if it happens.
