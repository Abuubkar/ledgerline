---
status: accepted
date: 2026-11-01
---

# Tracing: OpenTelemetry in every service, one trace per upload, Jaeger in development

> Since slice 8b (ADR 0021) the services send to an OpenTelemetry Collector, which tail-samples traces into Jaeger
> and also carries metrics and logs. Everything below about the spans themselves still holds.

Every Python service (api, worker, relay, erp-mock) calls `ledgerline_telemetry.setup_telemetry` once. It sends
traces over OTLP/HTTP, and instruments FastAPI, SQLAlchemy, httpx (the Ollama and ERP clients), Redis, botocore
(S3) and Celery. One invoice's upload, extraction, model call and match form **one trace**. The agent run and the
approval are their own traces, tied to the invoice by `ledgerline.invoice_id`. In development the traces go to
Jaeger v2, which runs only with `docker compose --profile observability` and `TRACING=1`. Telemetry is off whenever
`OTEL_EXPORTER_OTLP_ENDPOINT` is unset, so tests, evals and a plain `docker compose up` don't change.

## Decisions inside this

- **Trace context crosses the outbox.** A job is published by the relay, after the request's transaction commits,
  in another process. So `service.job_payload` stores the W3C `traceparent` in the outbox row's payload (under
  `_trace`, never passed to the task), and the relay publishes inside that context. Celery's instrumentation then
  carries it through RabbitMQ in the message headers. No schema change: the payload is already JSON.
- **Model calls follow the GenAI semantic conventions:** span `chat <model>`, `gen_ai.operation.name=chat`,
  `gen_ai.provider.name=ollama`, request and response model, `gen_ai.usage.input_tokens` / `output_tokens`,
  `gen_ai.response.finish_reasons` (Ollama's done_reason), `gen_ai.prompt.version`, plus
  `ledgerline.tokens_per_second`. The agent gets `invoke_agent exception-agent` per run and `execute_tool <name>`
  per tool call. The conventions are still "Development" status and moved in 2026 from the main semantic-conventions
  repo to `open-telemetry/semantic-conventions-genai`. This follows that repo's `main` at commit 244465e (31 Oct 2026),
  where `gen_ai.provider.name` replaces the older `gen_ai.system` and `gen_ai.prompt.version` is standard.
- **No invoice content leaves the process.** `RedactingSpanProcessor` sits in front of the exporter and drops
  denylisted attributes on spans and their events:
  - the conventions' message and instruction keys, tool arguments and results;
  - any key containing content, body, text, iban, bank, account_number, swift, bic, password or secret;
  - exception messages and stack traces, because a validation error repeats the model's answer. `error.type`
    keeps the code.

  SQL statements are kept, because every query binds its values as parameters. A unit test pins the denylist down.
  After the demo run, the stored traces held none of the invoice's number, vendor, tax ID, total or line
  descriptions.
- **Jaeger v2, one container.** It's an OpenTelemetry Collector distribution, so it is both the OTLP receiver
  and the trace store and UI (about 200 MB, in memory). A separate collector arrives in 8b, with tail sampling and
  metrics. Jaeger 2.22 serves only its v3 API (`/api/v3/traces`, OTLP JSON); `scripts/trace_tree.py` prints a span
  tree from it.
- **OTLP over HTTP, not gRPC:** no grpcio native wheel in every image.
- **Engines and the SQLAlchemy instrumentation.** It wraps `create_async_engine` when telemetry starts, so the
  global engine is passed in explicitly and the per-job engines come from `db.new_engine()`, which looks the
  function up at call time. Release 0.66b0 declares `sqlalchemy < 2.1` and would silently do nothing on our 2.1.6.
  Its version check is skipped (the engine events it hooks are unchanged), and the demo trace shows its spans.
- **Per Celery worker process:** tracing starts in `worker_process_init`, after the fork, as the instrumentation's
  docs require.
- **service.version** is the image's git commit (`LEDGERLINE_VERSION` build argument from the release workflow),
  `dev` locally.

## Alternatives considered

- **Langfuse or LangSmith.** They focus on the LLM's inputs and outputs (prompt text, answers, evals, feedback).
  Ledgerline must not store invoice text in telemetry, and it already has prompt versions and its own eval
  harness. The GenAI spans here can be sent to Langfuse later as an extra OTLP destination (docs/backlog.md).
- **A traceparent column on the outbox.** It would be a schema change for what fits in the existing JSON payload.
- **Zero-code `opentelemetry-instrument`.** It needs no setup code, but hides which libraries are traced. It also
  can't stamp the redaction processor in front of the exporter without a custom distro.
- **Tempo or Grafana's all-in-one image instead of Jaeger.** The user chose the lean, on-demand setup; Jaeger's API
  is the plan's check.

## Assumptions

- The agent and the approval happen later and are started by something else (a script, a person), so they're
  separate traces. Searching Jaeger for `ledgerline.invoice_id` finds all of one invoice's traces.
- Development traces are in memory and sampled at 100%; sampling and retention are 8b's concern.
