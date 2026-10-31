"""The extraction job a worker runs for one invoice, and what happens when it gives up.

Safe to run twice for the same invoice. Each attempt claims the invoice by inserting a `running` row in
extraction_runs (a unique index allows only one), renews that lease while it works, and writes its results
only if the lease is still its own. A worker killed mid-job stops renewing; its lease lapses within
`extraction_lease_s` and the redelivered message takes over (ADR 0009).
"""

import asyncio
import enum
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ledgerline_api import prompts, storage, vendors
from ledgerline_api.db import DeadLetter, ExtractionRun, Invoice, InvoiceLine, InvoicePageResult
from ledgerline_api.errors import PermanentError, TransientError, classify
from ledgerline_api.extraction import ExtractionError, ModelCall, extract_page, read_pages, render_page, repair_invoice
from ledgerline_api.normalize import (
    ExtractedPage, check_totals, decide_status, from_repair, merge_pages, needs_repair,
)
from ledgerline_api.semaphore import llm_slot
from ledgerline_api.settings import settings

FINISHED = {"extracted", "partially_extracted", "exception"}
TERMINAL = FINISHED | {"failed"}


class Outcome(enum.Enum):
    COMPLETED = "completed"
    ALREADY_DONE = "already_done"  # a duplicate delivery of a job that already finished
    LEASE_LOST = "lease_lost"  # took too long; another attempt owns the invoice now


@asynccontextmanager
async def job_resources() -> AsyncIterator[tuple[async_sessionmaker, redis.Redis]]:
    """Fresh connections per job: each Celery task runs its own event loop (asyncio.run), and asyncpg and
    redis connections can't cross event loops."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    redis_client = redis.from_url(settings.redis_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False), redis_client
    finally:
        await redis_client.aclose()
        await engine.dispose()


def _now() -> datetime:
    return datetime.now(UTC)


async def _claim(sessions: async_sessionmaker, invoice_id: uuid.UUID, task_id: str, attempt: int) -> uuid.UUID | Outcome | float:
    """Returns the new run's id, ALREADY_DONE, or seconds to wait before trying again."""
    async with sessions() as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update(skip_locked=True))
        ).scalar_one_or_none()
        if invoice is None:
            exists = await session.get(Invoice, invoice_id)
            if exists is None:
                raise PermanentError("invoice_not_found", f"no invoice {invoice_id}")
            return 1.0  # another worker is claiming it this instant
        if invoice.status in TERMINAL:
            return Outcome.ALREADY_DONE

        # A previous attempt whose worker died stops renewing; once its lease lapses it's abandoned.
        await session.execute(
            update(ExtractionRun)
            .where(ExtractionRun.invoice_id == invoice_id, ExtractionRun.outcome == "running",
                   ExtractionRun.lease_until < _now())
            .values(outcome="abandoned", finished_at=_now())
        )
        run = ExtractionRun(
            invoice_id=invoice_id, task_id=task_id, attempt=attempt, outcome="running",
            lease_until=_now() + timedelta(seconds=settings.extraction_lease_s),
        )
        session.add(run)
        invoice.status = "extracting"
        try:
            await session.commit()
        except IntegrityError:
            # Another attempt holds a live lease (a duplicate delivery). Wait for it to finish or lapse.
            await session.rollback()
            holder = (
                await session.execute(
                    select(ExtractionRun).where(ExtractionRun.invoice_id == invoice_id, ExtractionRun.outcome == "running")
                )
            ).scalar_one_or_none()
            return max(1.0, (holder.lease_until - _now()).total_seconds()) if holder else 1.0
        return run.id


async def _heartbeat(sessions: async_sessionmaker, run_id: uuid.UUID, lost: asyncio.Event) -> None:
    while True:
        await asyncio.sleep(settings.extraction_heartbeat_s)
        async with sessions() as session:
            result = await session.execute(
                update(ExtractionRun)
                .where(ExtractionRun.id == run_id, ExtractionRun.outcome == "running")
                .values(lease_until=_now() + timedelta(seconds=settings.extraction_lease_s))
            )
            await session.commit()
        if result.rowcount == 0:
            lost.set()
            return


async def _finish_run(session: AsyncSession, run_id: uuid.UUID, outcome: str, error=None) -> ExtractionRun | None:
    """Close our run if we still own it. Returns None if the lease was taken over."""
    run = (await session.execute(select(ExtractionRun).where(ExtractionRun.id == run_id).with_for_update())).scalar_one()
    if run.outcome != "running":
        return None
    run.outcome, run.finished_at = outcome, _now()
    if error is not None:
        run.error_code, run.error_detail = error.code, error.detail
    return run


@dataclass
class DocumentResult:
    header: object
    lines: list
    pages: list[InvoicePageResult]
    status: str
    repair_attempted: bool
    calls: list[ModelCall]
    prompt_version: str


async def _extract_document(content: bytes, redis_client: redis.Redis) -> DocumentResult:
    """Every page on its own, then merge, check the totals, and give the model one chance to repair them.

    A model outage on any page raises TransientError and the whole job is retried. Bad output or an unreadable
    page fails only that page."""
    texts = await asyncio.to_thread(read_pages, content)
    pages: list[InvoicePageResult] = []
    extracted: list[tuple[int, ExtractedPage]] = []
    images: list[bytes] = []
    calls: list[ModelCall] = []
    for index, text in enumerate(texts):
        page_no = index + 1
        if text is None:
            pages.append(InvoicePageResult(page_no=page_no, status="failed", source="text", error_code="unreadable_page",
                                           error_detail="the page's content could not be parsed"))
            continue
        image = None
        if not text.strip():  # no text layer: read the page visually
            image = await asyncio.to_thread(render_page, content, index)
            if image is None:
                pages.append(InvoicePageResult(page_no=page_no, status="blank", source="image"))
                continue
            images.append(image)
        source = "image" if image else "text"
        try:
            async with llm_slot(redis_client):
                call = await extract_page(page_no, len(texts), text, image)
        except ExtractionError as exc:
            error = classify(exc)
            if isinstance(error, TransientError):
                raise error from exc
            pages.append(InvoicePageResult(page_no=page_no, status="failed", source=source,
                                           error_code=error.code, error_detail=error.detail))
            continue
        calls.append(call)
        extracted.append((page_no, call.parsed))
        pages.append(InvoicePageResult(page_no=page_no, status="extracted", source=source,
                                       prompt_tokens=call.prompt_tokens, output_tokens=call.output_tokens,
                                       llm_ms=call.llm_ms))

    statuses = [page.status for page in pages]
    if not extracted:
        if statuses and all(status == "blank" for status in statuses):
            raise PermanentError("empty_document", "every page is blank")
        failures = ", ".join(f"page {p.page_no}: {p.error_code}" for p in pages if p.status == "failed")
        raise PermanentError("no_page_extracted", failures or "the document has no pages")

    header, lines = merge_pages(extracted)
    problems = check_totals(header, lines)
    prompt_version = prompts.EXTRACT_PAGE_VERSION
    repair_attempted = needs_repair(statuses, problems, repair_attempted=False)
    if repair_attempted:
        prompt_version += f"+{prompts.REPAIR_VERSION}"
        previous = json.dumps([{"page": n, **p.model_dump()} for n, p in extracted])
        try:
            async with llm_slot(redis_client):
                call = await repair_invoice(texts, images, previous, problems)
        except ExtractionError as exc:
            if isinstance(classify(exc), TransientError):
                raise classify(exc) from exc
            call = None  # unusable repair: keep the page-by-page result and its problems
        if call is not None:
            calls.append(call)
            repaired_header, repaired_lines = from_repair(call.parsed)
            if not check_totals(repaired_header, repaired_lines):
                header, lines, problems = repaired_header, repaired_lines, []

    if problems:
        header.invalid_fields["total"] = "; ".join(problems)
    return DocumentResult(header, lines, pages, decide_status(statuses, problems), repair_attempted, calls, prompt_version)


async def extract(invoice_id: uuid.UUID, task_id: str, attempt: int) -> Outcome:
    """Run one extraction attempt. Raises TransientError (worth retrying) or PermanentError (dead-letter it)."""
    async with job_resources() as (sessions, redis_client):
        # Wait out a duplicate delivery's live lease, but not forever: at most two lease periods.
        deadline = _now() + timedelta(seconds=2 * settings.extraction_lease_s)
        while True:
            claimed = await _claim(sessions, invoice_id, task_id, attempt)
            if isinstance(claimed, uuid.UUID | Outcome):
                break
            if _now() > deadline:
                raise TransientError("invoice_busy", "another attempt kept a live lease on this invoice")
            await asyncio.sleep(min(claimed, 5.0))
        if claimed is Outcome.ALREADY_DONE:
            return claimed
        run_id = claimed

        lost = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat(sessions, run_id, lost))
        try:
            async with sessions() as session:
                file_uri = (await session.get(Invoice, invoice_id)).file_path
            content = await asyncio.to_thread(storage.get, file_uri)
            result = await _extract_document(content, redis_client)
        except BaseException as exc:
            error = classify(exc) if isinstance(exc, Exception) else TransientError("cancelled", repr(exc))
            async with sessions() as session:
                outcome = "transient_failure" if isinstance(error, TransientError) else "permanent_failure"
                if await _finish_run(session, run_id, outcome, error) is not None and isinstance(error, TransientError):
                    # Visible as queued again until the retry runs.
                    await session.execute(update(Invoice).where(Invoice.id == invoice_id).values(status="received"))
                await session.commit()
            raise error from exc
        finally:
            heartbeat.cancel()

        async with sessions() as session:
            if lost.is_set() or (run := await _finish_run(session, run_id, "completed")) is None:
                await session.rollback()
                return Outcome.LEASE_LOST
            header = asdict(result.header)
            run.extracted_header = json.loads(json.dumps(header, default=str))
            invoice = await session.get(Invoice, invoice_id)
            vendor_tax_id, vendor_name = header.pop("vendor_tax_id"), header.pop("vendor_name")
            for name, value in header.items():
                setattr(invoice, name, value)
            invoice.status = result.status
            await vendors.link(session, invoice, vendor_tax_id, vendor_name)
            invoice.page_count = len(result.pages)
            invoice.model = settings.llm_model
            invoice.prompt_version = result.prompt_version
            invoice.prompt_tokens = sum(c.prompt_tokens for c in result.calls)
            invoice.output_tokens = sum(c.output_tokens for c in result.calls)
            invoice.llm_ms = sum(c.llm_ms for c in result.calls)
            invoice.repair_attempted = result.repair_attempted
            invoice.error_code = invoice.error_detail = None
            # Replacing the collections deletes the rows from any earlier attempt (delete-orphan).
            invoice.pages = result.pages
            invoice.lines = [
                InvoiceLine(page_no=line.page_no, line_no=line.line_no, description=line.description,
                            quantity=line.quantity, unit_price=line.unit_price, amount_minor=line.amount_minor,
                            invalid_reason=line.invalid_reason)
                for line in result.lines
            ]
            await session.commit()
        return Outcome.COMPLETED


async def dead_letter(task_name: str, payload: dict, error: TransientError | PermanentError, chain: str, attempts: int) -> None:
    """The job gave up: mark the invoice failed and record why, so it can be inspected and replayed."""
    invoice_id = uuid.UUID(payload["invoice_id"])
    async with job_resources() as (sessions, _):
        async with sessions() as session:
            invoice = await session.get(Invoice, invoice_id, with_for_update=True)
            if invoice is None or invoice.status in FINISHED:
                return  # nothing to dead-letter: unknown invoice, or a duplicate delivery of a finished job
            invoice.status, invoice.error_code, invoice.error_detail = "failed", error.code, error.detail
            session.add(DeadLetter(
                task_name=task_name, invoice_id=invoice_id, payload=payload,
                error_code=error.code, exception_chain=chain, attempts=attempts,
            ))
            await session.commit()
