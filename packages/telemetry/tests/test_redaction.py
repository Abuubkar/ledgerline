"""Invoice content, prompt text and bank details never reach the exporter (ADR 0020)."""

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ledgerline_telemetry import RedactingSpanProcessor, allowed


def exported_span(attributes: dict, event_attributes: dict | None = None):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(RedactingSpanProcessor(SimpleSpanProcessor(exporter)))
    with provider.get_tracer("test").start_as_current_span("chat gemma4:12b", attributes=attributes) as span:
        if event_attributes is not None:
            span.add_event("exception", event_attributes)
    [finished] = exporter.get_finished_spans()
    return finished


def test_content_and_bank_details_are_dropped_and_the_rest_is_kept():
    span = exported_span({
        "gen_ai.input.messages": '[{"role": "user", "content": "Invoice RE-1049 ..."}]',
        "gen_ai.output.messages": '{"total": 4286.4}',
        "gen_ai.system_instructions": "You read one page of a supplier invoice",
        "ledgerline.page_text": "Rechnungsnummer RE-2026-1049",
        "vendor.iban": "DE89 3704 0044 0532 0130 00",
        "vendor.bank_name": "Commerzbank",
        "http.request.body": "%PDF-1.7",
        "gen_ai.request.model": "gemma4:12b",
        "gen_ai.usage.input_tokens": 1830,
        "gen_ai.usage.output_tokens": 412,
        "gen_ai.prompt.version": "extract-page/4",
        "ledgerline.invoice_id": "019a3a42-2dd8-7d5a-bd47-1e4095f79246",
    })
    assert dict(span.attributes) == {
        "gen_ai.request.model": "gemma4:12b",
        "gen_ai.usage.input_tokens": 1830,
        "gen_ai.usage.output_tokens": 412,
        "gen_ai.prompt.version": "extract-page/4",
        "ledgerline.invoice_id": "019a3a42-2dd8-7d5a-bd47-1e4095f79246",
    }


def test_error_messages_on_events_are_dropped_but_the_type_stays():
    # A pydantic validation error repeats the model's answer, which holds invoice data.
    span = exported_span({}, {"exception.type": "ValidationError",
                              "exception.message": "total: input 4286.4 is not a string",
                              "exception.stacktrace": "Traceback ... 4286.4"})
    assert dict(span.events[0].attributes) == {"exception.type": "ValidationError"}


def test_denylist_matches_parts_of_keys_case_insensitively():
    assert not allowed("Vendor.IBAN")
    assert not allowed("ledgerline.page_text")
    assert allowed("gen_ai.prompt.version") and allowed("db.system.name") and allowed("http.response.status_code")
    assert allowed("db.query.text") and allowed("db.statement")  # parameterised SQL, no values
