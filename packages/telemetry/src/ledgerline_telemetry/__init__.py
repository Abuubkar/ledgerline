"""One telemetry setup for every Ledgerline service (api, worker, relay, erp-mock): traces over OTLP to a collector
(Jaeger in development, ADR 0020), with the libraries we use instrumented automatically.

Telemetry is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set: tracing calls then cost next to nothing, and nothing
tries to reach a collector that isn't running. Every span passes through `RedactingSpanProcessor` before export,
so invoice content, prompt text and bank details never leave the process.
"""

import logging
import os
from collections.abc import Iterable, Mapping
from typing import Any

from opentelemetry import trace
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


def setup_telemetry(service_name: str, *, fastapi_app: Any = None, sqlalchemy_engines: Iterable[Any] = (),
                    celery: bool = False) -> bool:
    """Start tracing for this process. Returns False (and does nothing) when no OTLP endpoint is configured.

    Call it once per process, before work starts: at app startup for the API and the ERP mock, in Celery's
    worker_process_init for each worker process (spans can't cross a fork), at start for the relay. Engines
    created before this call are passed in; later ones are instrumented as they're created."""
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.environ.get("LEDGERLINE_VERSION", "dev"),
        "deployment.environment.name": os.environ.get("DEPLOYMENT_ENVIRONMENT", "development"),
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(RedactingSpanProcessor(BatchSpanProcessor(OTLPSpanExporter())))
    trace.set_tracer_provider(provider)

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
