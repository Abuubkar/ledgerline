"""Every metric Ledgerline records, in one place (ADR 0021). Instruments are created at import from the global meter,
which does nothing until `ledgerline_telemetry.setup_telemetry` installs a real one, so recording is always safe.

Names follow OpenTelemetry; Prometheus sees them with dots as underscores, the unit as a suffix and `_total` on
counters (`ledgerline.invoice.duration` in seconds → `ledgerline_invoice_duration_seconds`). The model metrics are
the GenAI semantic conventions' own (`gen_ai.client.token.usage`, `gen_ai.client.operation.duration`).
"""

from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

from ledgerline_api.settings import settings

meter = metrics.get_meter("ledgerline")

# Upload → terminal status. 900 s is a bucket edge on purpose: the SLO is "99% within 15 minutes" (docs/slo.md).
invoice_duration = meter.create_histogram(
    "ledgerline.invoice.duration", unit="s", description="Upload until the invoice reached a terminal status",
    explicit_bucket_boundaries_advisory=[5, 15, 30, 60, 120, 180, 300, 600, 900, 1800, 3600])
extraction_duration = meter.create_histogram(
    "ledgerline.extraction.duration", unit="s", description="One extraction attempt, from claim to stored result",
    explicit_bucket_boundaries_advisory=[1, 5, 10, 20, 30, 45, 60, 90, 120, 180, 300])
token_usage = meter.create_histogram(
    "gen_ai.client.token.usage", unit="{token}", description="Tokens per model call, by type (input or output)",
    explicit_bucket_boundaries_advisory=[16, 64, 256, 512, 1024, 2048, 4096, 8192])
operation_duration = meter.create_histogram(
    "gen_ai.client.operation.duration", unit="s", description="One model call, as the client saw it",
    explicit_bucket_boundaries_advisory=[1, 2, 5, 10, 20, 30, 45, 60, 90, 120])
# Named for what it measures: with unit {token}/s, Prometheus adds `_per_second` itself.
output_speed = meter.create_histogram(
    "ledgerline.llm.output_speed", unit="{token}/s", description="Output tokens per second of generation",
    explicit_bucket_boundaries_advisory=[2, 5, 8, 10, 12, 15, 20, 25, 30, 40])
slot_wait = meter.create_histogram(
    "ledgerline.llm.slot.wait", unit="s", description="Time waiting for a model slot (the concurrency limit)",
    explicit_bucket_boundaries_advisory=[0.01, 0.5, 1, 5, 10, 30, 60, 120, 300])
dead_letters = meter.create_counter("ledgerline.dead_letters", description="Jobs that gave up and were dead-lettered")
backpressure_rejections = meter.create_counter(
    "ledgerline.backpressure.rejections", description="Uploads refused with 429 because the extraction queue was full")


def prime_counters(tasks: Iterable[str] = ()) -> None:
    """Report the counters at zero as soon as a process starts. Prometheus's OTLP receiver ignores a counter's start
    time, so a series whose first export already reads 3 would show an increase of 0; starting it at 0 makes the first
    increments count. That's also why the dead-letter counter has no error-code label (codes can't be listed ahead)."""
    for task in tasks:
        dead_letters.add(0, {"task": task})
    backpressure_rejections.add(0)


def record_terminal(created_at: datetime, status: str) -> None:
    """An invoice reached a status nothing in the pipeline moves on from (matched, exception, failed, partially
    extracted, or extracted without a PO to match)."""
    invoice_duration.record((datetime.now(UTC) - created_at).total_seconds(), {"status": status})


def record_model_call(model: str, operation: str, input_tokens: int, output_tokens: int, seconds: float,
                      eval_seconds: float) -> None:
    common = {"gen_ai.request.model": model, "gen_ai.operation.name": operation, "gen_ai.provider.name": "ollama"}
    token_usage.record(input_tokens, {**common, "gen_ai.token.type": "input"})
    token_usage.record(output_tokens, {**common, "gen_ai.token.type": "output"})
    operation_duration.record(seconds, common)
    if eval_seconds > 0:
        output_speed.record(output_tokens / eval_seconds, {"gen_ai.request.model": model})


def register_gauges() -> None:
    """Gauges read when metrics are exported, from one long-running process (the relay): queue depth per queue
    from RabbitMQ's management API, the queue limit uploads are refused at, and whether Ollama answers."""

    def queue_depth(_options: CallbackOptions) -> Iterable[Observation]:
        try:
            queues = httpx.get(f"{settings.rabbitmq_management_url}/api/queues/%2F", timeout=2).json()
        except (httpx.HTTPError, ValueError):
            return []
        # Our job queues only: not their dead-letter queues, nor Celery's internal ones (pidbox, delayed, events).
        return [Observation(q.get("messages_ready", 0), {"queue": q["name"]}) for q in queues
                if q["name"].startswith(("invoices.", "erp.")) and not q["name"].endswith(".dlq")]

    def ollama_up(_options: CallbackOptions) -> Iterable[Observation]:
        try:
            up = httpx.get(f"{settings.ollama_host}/api/version", timeout=2).status_code == 200
        except httpx.HTTPError:
            up = False
        return [Observation(1 if up else 0)]

    meter.create_observable_gauge("ledgerline.queue.depth", [queue_depth], description="Messages ready in a queue")
    meter.create_observable_gauge("ledgerline.queue.limit", [lambda _o: [Observation(settings.max_queue_depth)]],
                                  description="Extraction jobs waiting at which uploads get 429 (MAX_QUEUE_DEPTH)")
    meter.create_observable_gauge("ledgerline.ollama.up", [ollama_up], description="1 if Ollama answers, else 0")
