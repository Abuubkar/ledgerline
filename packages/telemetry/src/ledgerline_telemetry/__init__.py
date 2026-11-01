"""One telemetry setup for every Ledgerline service (api, worker, relay, erp-mock): traces, metrics and logs over OTLP
to the OpenTelemetry Collector (ADR 0020, ADR 0021), with the libraries we use instrumented automatically, and log
lines as JSON carrying the current trace and span ids.

Telemetry is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set: tracing calls then cost next to nothing, and nothing
tries to reach a collector that isn't running. Every span passes through `RedactingSpanProcessor` before export,
so invoice content, prompt text and bank details never leave the process.
"""

import logging
import os
import socket
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

log = logging.getLogger("ledgerline.telemetry")

# Attributes that may carry invoice content, prompt or answer text, or bank details. Matched as whole keys or, for
# DENIED_PARTS, as part of a key. Error messages go too: a validation error repeats the model's answer, and the error
# code we record (ledgerline.error_code) says what failed without it.
DENIED_KEYS = frozenset({
    "gen_ai.input.messages", "gen_ai.output.messages", "gen_ai.system_instructions", "gen_ai.tool.definitions",
    "gen_ai.tool.call.arguments", "gen_ai.tool.call.result", "exception.message", "exception.stacktrace",
})
DENIED_PARTS = ("content", "body", "text", "iban", "bank", "account_number", "swift", "bic", "password", "secret")
# SQL is kept: every query binds its values as parameters ($1, $2), so the statement text holds none of them.
ALLOWED_KEYS = frozenset({"gen_ai.prompt.version", "gen_ai.prompt.name", "db.statement", "db.query.text"})


def allowed(key: str) -> bool:
    if key in ALLOWED_KEYS:
        return True
    lowered = key.lower()
    return key not in DENIED_KEYS and not any(part in lowered for part in DENIED_PARTS)


def _clean(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (attributes or {}).items() if allowed(k)}


class RedactingSpanProcessor(SpanProcessor):
    """Drops denylisted attributes (on the span and its events) before the span reaches the exporter.

    A finished span is read-only, so the processor hands the exporter a cleaned copy instead."""

    def __init__(self, inner: SpanProcessor):
        self.inner = inner

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self.inner.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        events = [Event(e.name, _clean(e.attributes), e.timestamp) for e in span.events]
        self.inner.on_end(ReadableSpan(
            name=span.name, context=span.context, parent=span.parent, resource=span.resource,
            attributes=_clean(span.attributes), events=events, links=span.links, kind=span.kind, status=span.status,
            start_time=span.start_time, end_time=span.end_time, instrumentation_scope=span.instrumentation_scope,
        ))

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def _trace_ids(_logger: Any, _method: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor: the current trace and span ids on every log line, so Loki links a line to its trace."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event["trace_id"], event["span_id"] = format(context.trace_id, "032x"), format(context.span_id, "016x")
    return event


def setup_logging(level: int = logging.INFO) -> None:
    """Every stdlib log record (ours and the libraries') as one JSON line on stderr, with trace ids when in a span."""
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.stdlib.add_log_level, structlog.stdlib.add_logger_name,
                           structlog.processors.TimeStamper(fmt="iso", utc=True), _trace_ids],
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer()],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, logging.StreamHandler)] + [handler]
    root.setLevel(level)
    # httpx logs every request at INFO, URL included: noise every 15 s from the metric gauges, and a URL can carry
    # credentials (the RabbitMQ management URL does). Its warnings and errors still come through.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def setup_telemetry(service_name: str, *, fastapi_app: Any = None, sqlalchemy_engines: Iterable[Any] = (),
                    celery: bool = False) -> bool:
    """Start tracing for this process. Returns False (and does nothing) when no OTLP endpoint is configured.

    Call it once per process, before work starts: at app startup for the API and the ERP mock, in Celery's
    worker_process_init for each worker process (spans can't cross a fork), at start for the relay. Engines
    created before this call are passed in; later ones are instrumented as they're created."""
    setup_logging()
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    resource = Resource.create({
        "service.name": service_name,
        # One per process (Prometheus's `instance` label): host and pid, readable where the SDK's default is a uuid.
        "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
        "service.version": os.environ.get("LEDGERLINE_VERSION", "dev"),
        "deployment.environment.name": os.environ.get("DEPLOYMENT_ENVIRONMENT", "development"),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(RedactingSpanProcessor(BatchSpanProcessor(OTLPSpanExporter())))
    trace.set_tracer_provider(provider)
    # Metrics every 15 s. Histograms keep exemplars (a trace id per bucket) from sampled spans, the SDK's default.
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[
        PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15_000)]))
    # Log records too, through the collector to Loki; they carry the trace context of the span they're written in.
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))

    engines = [e.sync_engine if hasattr(e, "sync_engine") else e for e in sqlalchemy_engines]
    # 0.66b0 declares sqlalchemy < 2.1 and would silently do nothing on our 2.1; the engine events it hooks are
    # unchanged in 2.1, and the span tree in docs/metrics.md (slice 8a) shows its SELECT/INSERT spans.
    SQLAlchemyInstrumentor().instrument(engines=engines, skip_dep_check=True)
    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()
    BotocoreInstrumentor().instrument()
    if celery:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        CeleryInstrumentor().instrument()
    if fastapi_app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        # No spans for each ASGI receive/send chunk: noise next to the request span.
        FastAPIInstrumentor.instrument_app(fastapi_app, exclude_spans=["receive", "send"])
    log.info("telemetry on: %s -> %s", service_name, os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"])
    return True


def flush_telemetry() -> None:
    """Send whatever is buffered now. For processes that exit without running atexit hooks (Celery's pool children),
    so their last spans, metrics and log records aren't lost."""
    from opentelemetry._logs import get_logger_provider
    for provider in (trace.get_tracer_provider(), metrics.get_meter_provider(), get_logger_provider()):
        if hasattr(provider, "force_flush"):
            provider.force_flush()

