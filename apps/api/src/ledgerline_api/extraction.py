"""Read an invoice PDF and ask the local model for its header fields."""

import asyncio
import io
import time
from dataclasses import dataclass

import ollama
import pdfplumber
from pydantic import ValidationError

from ledgerline_api import prompts
from ledgerline_api.normalize import ExtractedHeader, InvoiceHeader, normalize_header
from ledgerline_api.settings import settings


class ExtractionError(Exception):
    def __init__(self, code: str, detail: str):
        # Both values go to Exception so the error survives pickling (Celery pickles exceptions).
        super().__init__(code, detail)
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass
class Extraction:
    header: InvoiceHeader
    page_count: int
    model: str
    prompt_version: str
    prompt_tokens: int
    output_tokens: int
    llm_ms: int


def read_pages(content: bytes) -> list[str]:
    """Text per page. Raises ExtractionError for files pdfplumber can't parse."""
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:  # pdfminer raises a zoo of parser errors for corrupt files
        raise ExtractionError("unreadable_pdf", f"{type(exc).__name__}: {exc}") from exc


async def extract_header(pages: list[str]) -> Extraction:
    if not any(text.strip() for text in pages):
        # Scanned pages (no text layer) are handled from slice 3 on.
        raise ExtractionError("no_text_layer", "the PDF has no extractable text")

    client = ollama.AsyncClient(host=settings.ollama_host)
    started = time.perf_counter()
    try:
        async with asyncio.timeout(settings.llm_timeout_s):
            response = await client.chat(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": prompts.EXTRACT_HEADER_SYSTEM},
                    {"role": "user", "content": prompts.extract_header_user(pages)},
                ],
                format=ExtractedHeader.model_json_schema(),
                # gemma4 thinks by default; copying fields needs no reasoning trace, and it costs seconds.
                think=False,
                options={"temperature": settings.llm_temperature, "num_ctx": settings.llm_num_ctx},
                keep_alive=settings.llm_keep_alive,
            )
    except TimeoutError:
        raise ExtractionError("model_timeout", f"no reply within {settings.llm_timeout_s}s") from None
    except (ConnectionError, ollama.ResponseError) as exc:
        raise ExtractionError("model_unavailable", str(exc)) from exc
    llm_ms = int((time.perf_counter() - started) * 1000)

    prompt_tokens = response.prompt_eval_count or 0
    if response.done_reason == "length":
        raise ExtractionError("output_truncated", "the model hit its output limit")
    if prompt_tokens >= settings.llm_num_ctx:
        # Ollama drops the start of an over-long prompt instead of failing, so check it ourselves.
        raise ExtractionError("prompt_truncated", f"{prompt_tokens} prompt tokens >= num_ctx {settings.llm_num_ctx}")

    try:
        extracted = ExtractedHeader.model_validate_json(response.message.content or "")
    except ValidationError as exc:
        raise ExtractionError("invalid_model_output", str(exc)) from exc

    return Extraction(
        header=normalize_header(extracted),
        page_count=len(pages),
        model=settings.llm_model,
        prompt_version=prompts.EXTRACT_HEADER_VERSION,
        prompt_tokens=prompt_tokens,
        output_tokens=response.eval_count or 0,
        llm_ms=llm_ms,
    )
