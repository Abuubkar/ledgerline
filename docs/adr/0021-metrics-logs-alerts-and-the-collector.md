---
status: accepted
date: 2026-11-01
---

# Metrics, logs and alerts through one OpenTelemetry Collector

Every service sends traces, metrics and logs over OTLP to an OpenTelemetry Collector. It tail-samples the traces into
Jaeger, writes metrics to Prometheus (its native OTLP receiver) and logs to Loki (its native OTLP endpoint). Grafana
shows the "Ledgerline / Pipeline" dashboard over all three. Prometheus evaluates the alert rules; each alert links a
runbook in `docs/runbooks/`. The SLO and its burn-rate alerts are in `docs/slo.md`. All of it runs only with
`docker compose --profile observability` (and `TRACING=1` for the services), about 650 MB more.

## Decisions inside this

- **One collector, three backends,** so the services know one endpoint and sampling lives in one place. Jaeger and
  Prometheus no longer receive from the services directly.
- **Tail sampling:** keep every trace with an error span, every trace with a dead letter
  (`ledgerline.dead_letter=true`), and 20% of the rest (`TRACE_SAMPLE_PERCENT`). `decision_wait` is 120 s, because an
  invoice's trace runs a minute or more (extraction, then the match job) and the error worth keeping can come late.
  Decision caches make spans that arrive after the decision follow it. In the chaos run every dead-letter trace was
  kept. Most other traces were kept too, because the stub model answers about 20% of calls with HTTP 503, which
  marks those calls as errors, and each chaos upload holds about 10 invoices.
- **The metrics** live in `ledgerline_api/metrics.py`:
  - invoice end-to-end seconds (upload → terminal status), extraction seconds, LLM slot wait;
  - the GenAI conventions' `gen_ai.client.token.usage` (by model and token type) and `gen_ai.client.operation.duration`;
  - output tokens per second;
  - queue depth per job queue and the upload limit, as gauges read from RabbitMQ's management API by the relay;
  - `ledgerline.ollama.up`, a probe the relay runs every 15 s;
  - dead letters (by job) and backpressure rejections.

  Histograms carry exemplars, so a bucket links to a trace.
- **Logs:** every stdlib log record is one JSON line (structlog's formatter) with `trace_id` and `span_id` when written
  inside a span. The same records go over OTLP to Loki, where `trace_id` is structured metadata that Grafana links to
  Jaeger. httpx's per-request INFO lines are silenced: they repeated every 15 s from the gauges, and a URL can carry
  credentials (the RabbitMQ management URL does).
- **Alerts** (infra/prometheus/alerts.yml), checked with `promtool`:

  | Alert | Fires when |
  |---|---|
  | ExtractionSlow | extraction p95 > 45 s for 10 min |
  | DeadLettersGrowing | more than 10 dead letters in 15 min |
  | OllamaUnreachable | Ollama down for 2 min |
  | QueueNearlyFull | queue depth > 80% of `MAX_QUEUE_DEPTH` for 5 min |
  | InvoiceSLOFastBurn, InvoiceSLOSlowBurn | the SLO's error budget is burning fast or steadily (multiwindow) |

  OllamaUnreachable was tested by pointing the relay at a host that doesn't exist: pending, then firing 2 minutes
  later with its runbook link, and resolved once the relay could reach Ollama again.
- **The dashboard is generated** by `scripts/make_dashboard.py` and provisioned from a file, so it's reviewed as code.
- **Versions:** collector-contrib 0.162.0 (0.163.0 was never published as an image), Prometheus 3.15.1, Loki 3.7.9,
  Grafana 13.2.4, structlog 26.1.0.

## What OTLP into Prometheus gets wrong, and what we did

- **No staleness marker when a process stops.** Its gauge series keeps the last value for 5 minutes, so a restarted
  relay's old `ollama_up=1` hid the new 0. Gauge alerts and panels use `last_over_time(...[1m])`, which only sees
  series that reported in the last minute.
- **A series' first measurement can't count as an increase.** The OTLP receiver ignores a counter's start time
  (Prometheus's zero-start features cover only scraped data). The counters (dead letters, rejections) are reported
  at 0 when each process starts, which is also why the dead-letter counter has no error-code label: codes can't be
  listed ahead. Histograms can't be pre-reported without a fake observation, so the first observation of each new
  process is missed by `rate()` and `increase()`. With long-lived, busy processes this doesn't matter. In a dev run
  with one model call per process it's very visible, so the token check used the cumulative totals.
- **A process killed with SIGKILL loses up to 15 s of metrics.** Celery's pool children exit without atexit hooks, so
  they flush in `worker_process_shutdown`; SIGKILL can't be helped. In the chaos run, the killed worker took 2 of 200
  invoices' measurements with it.
- **Each process is its own series:** `service.instance.id` is host-pid, and Prometheus makes it the `instance` label.
- **Name translation:** dots become underscores, the unit becomes a suffix, counters get `_total`. A unit of
  `{token}/s` on a metric already named `…tokens_per_second` produced `…_per_second_per_second`; it's
  `ledgerline.llm.output_speed` now.

## Alternatives considered

- **Prometheus scraping each service's /metrics.** It handles staleness and start times properly, but a Celery
  worker has several pool processes and no HTTP server. It would need the multiprocess client or a pushgateway, a
  second way of doing metrics next to OTLP.
- **Grafana's all-in-one otel-lgtm image.** One container, but Tempo instead of Jaeger; the user chose the lean,
  on-demand setup.
- **Alertmanager.** Routing and notifications need somewhere to send them; for a local stack the alert state in
  Prometheus and Grafana is enough. It's the next piece when there's an on-call channel.
- **Head sampling in the SDK.** Simpler, but it decides before anyone knows whether the trace will hold an error.

## Assumptions

- One relay process (it owns the gauges); several relays would report the same queue depth, and `max` handles that.
- The tail-sampling collector is a single instance, so it sees every span of a trace.
- Exemplars point at traces the collector may have sampled out (80% of error-free traces). Following one can land on
  "trace not found"; that's the cost of tail sampling.
