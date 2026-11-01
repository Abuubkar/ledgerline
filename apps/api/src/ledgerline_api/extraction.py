"""Read invoice PDFs page by page and ask the local model about each page. Also home of call_model, the one
way any part of Ledgerline calls the model."""

import asyncio
import io
import json
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

import ollama
import pdfplumber
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

from ledgerline_api import prompts
from ledgerline_api.normalize import ExtractedPage, RepairedInvoice
from ledgerline_api.settings import settings

tracer = trace.get_tracer("ledgerline.extraction")

# PDFium (which renders pages for pdfplumber) is not thread-safe, even across documents.
_render_lock = threading.Lock()
RENDER_DPI = 150

# Token estimates without a tokenizer, measured on gemma4:12b (2026-10-30). A real page prompt counts ~2.8
# characters per token, because the chat template and JSON schema add tokens our character count doesn't
# see; plain prose runs ~6.5. Budgeting at 2 stays on the safe side. One rendered page measured ~520 tokens.
CHARS_PER_TOKEN_SAFE = 2.0
TOKENS_PER_IMAGE = 600
# A silently truncated prompt measured 15.5 characters per reported token; intact page prompts measure ~2.8.
# prompt_eval_count includes cached prefix tokens, so a reused system prompt doesn't skew the ratio.
TRUNCATED_CHARS_PER_TOKEN = 10.0


class ExtractionError(Exception):
    def __init__(self, code: str, detail: str):
        # Both values go to Exception so the error survives pickling (Celery pickles exceptions).
        super().__init__(code, detail)
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass
class ModelCall[T: BaseModel]:
    parsed: T
    prompt_tokens: int
    output_tokens: int
    llm_ms: int


def read_pages(content: bytes) -> list[str | None]:
    """Text per page; None for a page whose content can't be parsed. Raises ExtractionError only when the file
    as a whole can't be opened."""
    try:
        pdf = pdfplumber.open(io.BytesIO(content))
        pages = pdf.pages
    except Exception as exc:  # pdfminer raises a zoo of parser errors for corrupt files
        raise ExtractionError("unreadable_pdf", f"{type(exc).__name__}: {exc}") from exc
    with pdf:
        texts: list[str | None] = []
        for page in pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                texts.append(None)
        return texts


def render_page(content: bytes, page_index: int) -> bytes | None:
    """The page as a PNG, or None if it renders blank (e.g. the back of a scan)."""
    with _render_lock, pdfplumber.open(io.BytesIO(content)) as pdf:
        image = pdf.pages[page_index].to_image(resolution=RENDER_DPI)
        # getextrema gives (min, max); an all-near-white page has nothing to read.
        if image.original.convert("L").getextrema()[0] >= 250:  # type: ignore[operator]  # one band: (min, max) of ints
            return None
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def prompt_too_long(text_chars: int, image_count: int, num_ctx: int, reserve: int) -> bool:
    """Would this prompt crowd out room for the answer? Checked before sending, because Ollama truncates
    silently instead of failing."""
    estimated = text_chars / CHARS_PER_TOKEN_SAFE + image_count * TOKENS_PER_IMAGE
    return estimated > num_ctx - reserve


def looks_truncated(text_chars: int, image_count: int, prompt_tokens: int, num_ctx: int) -> bool:
    """Did Ollama drop part of the prompt anyway? Far fewer tokens than the text's length implies means yes."""
    if prompt_tokens >= num_ctx:
        return True
    if image_count or prompt_tokens == 0:
        return False  # image tokens make the ratio meaningless
    return text_chars / prompt_tokens > TRUNCATED_CHARS_PER_TOKEN


async def call_model(messages: list, *, schema: type[BaseModel] | None = None, tools: list[dict] | None = None,
                     timeout_s: float | None = None, prompt_version: str | None = None):
    """The one way Ledgerline calls the model: budget the prompt first (Ollama truncates silently), then check
    it wasn't truncated anyway. Returns (response, prompt_tokens, output_tokens, llm_ms). `schema` constrains
    the answer to JSON; `tools` offers tool calls (the agent).

    Each call is a `chat <model>` span with OpenTelemetry's GenAI attributes (ADR 0020): models, token counts,
    finish reason, prompt version and speed, never the prompt or the answer."""
    with tracer.start_as_current_span(f"chat {settings.llm_model}", kind=trace.SpanKind.CLIENT, attributes={
        "gen_ai.operation.name": "chat", "gen_ai.provider.name": "ollama", "gen_ai.request.model": settings.llm_model,
        "gen_ai.request.temperature": settings.llm_temperature, "gen_ai.output.type": "json" if schema else "text",
        **({"gen_ai.prompt.version": prompt_version} if prompt_version else {}),
    }) as span:
        try:
            response, prompt_tokens, output_tokens, llm_ms = await _call_model(messages, schema, tools, timeout_s)
        except ExtractionError as exc:
            span.set_status(trace.StatusCode.ERROR, exc.code)
            span.set_attribute("error.type", exc.code)
            raise
        span.set_attributes({
            "gen_ai.response.model": response.model or settings.llm_model,
            "gen_ai.usage.input_tokens": prompt_tokens, "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.response.finish_reasons": [response.done_reason or "stop"],
            "ledgerline.tokens_per_second": round(output_tokens / (response.eval_duration / 1e9), 1)
            if response.eval_duration else 0.0,
        })
        return response, prompt_tokens, output_tokens, llm_ms


async def _call_model(messages: list, schema: type[BaseModel] | None, tools: list[dict] | None, timeout_s: float | None):
    text_chars = sum(len(m.get("content") or "") if isinstance(m, dict) else len(m.content or "") for m in messages)
    text_chars += len(json.dumps(tools)) if tools else 0
    image_count = sum(len(m.get("images") or []) for m in messages if isinstance(m, dict))
    if prompt_too_long(text_chars, image_count, settings.llm_num_ctx, settings.llm_output_reserve_tokens):
        raise ExtractionError(
            "prompt_too_long",
            f"~{text_chars} characters and {image_count} image(s) won't fit num_ctx {settings.llm_num_ctx} "
            f"with {settings.llm_output_reserve_tokens} tokens left for the answer",
        )
    client = ollama.AsyncClient(host=settings.ollama_host)
    timeout_s = settings.llm_timeout_s if timeout_s is None else timeout_s
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_s):
            response = await client.chat(
                model=settings.llm_model,
                messages=messages,
                format=schema.model_json_schema() if schema else None,
                tools=tools,
                # gemma4 thinks by default; copying fields and picking a tool need no reasoning trace, and it
                # costs seconds per call.
                think=False,
                options={"temperature": settings.llm_temperature, "num_ctx": settings.llm_num_ctx},
                keep_alive=settings.llm_keep_alive,
            )
    except TimeoutError:
        raise ExtractionError("model_timeout", f"no reply within {timeout_s:.0f}s") from None
    except (ConnectionError, ollama.ResponseError) as exc:
        raise ExtractionError("model_unavailable", str(exc)) from exc
    llm_ms = int((time.perf_counter() - started) * 1000)

    prompt_tokens = response.prompt_eval_count or 0
    if response.done_reason == "length":
        raise ExtractionError("output_truncated", "the model hit its output limit")
    if looks_truncated(text_chars, image_count, prompt_tokens, settings.llm_num_ctx):
        raise ExtractionError(
            "prompt_truncated", f"{text_chars} characters came back as only {prompt_tokens} prompt tokens"
        )
    return response, prompt_tokens, response.eval_count or 0, llm_ms


async def _chat[T: BaseModel](system: str, user: str, schema: type[T], images: list[bytes] | None = None, *,
                               prompt_version: str) -> ModelCall[T]:
    message: dict = {"role": "user", "content": user}
    if images:
        message["images"] = images
    response, prompt_tokens, output_tokens, llm_ms = await call_model(
        [{"role": "system", "content": system}, message], schema=schema, prompt_version=prompt_version
    )
    return ModelCall(parse_answer(response.message.content or "", schema), prompt_tokens, output_tokens, llm_ms)


def parse_answer[T: BaseModel](content: str, schema: type[T]) -> T:
    """The model's JSON as `schema`. Bare numbers are read as Decimal, so 3572.00 arrives as "3572.00" and no amount
    ever passes through a float (ADR 0003, ADR 0016)."""
    try:
        return schema.model_validate(json.loads(content, parse_float=Decimal))
    except (ValueError, ValidationError) as exc:
        raise ExtractionError("invalid_model_output", str(exc)) from exc


async def extract_page(page_no: int, page_count: int, text: str | None, image: bytes | None) -> ModelCall[ExtractedPage]:
    """One page, from its text or, when it has none, from its rendered image."""
    user = prompts.extract_page_user(page_no, page_count, text if image is None else None)
    return await _chat(prompts.EXTRACT_PAGE_SYSTEM, user, ExtractedPage, [image] if image else None,
                       prompt_version=prompts.EXTRACT_PAGE_VERSION)


async def repair_invoice(
    texts: list[str | None], images: list[bytes], previous_json: str, problems: list[str]
) -> ModelCall[RepairedInvoice]:
    """The single second look when the totals don't add up."""
    return await _chat(
        prompts.REPAIR_SYSTEM, prompts.repair_user(texts, previous_json, problems), RepairedInvoice, images or None,
        prompt_version=prompts.REPAIR_VERSION,
    )
