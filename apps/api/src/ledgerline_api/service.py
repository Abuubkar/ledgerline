"""What the API does, independent of REST or GraphQL. Both call these functions, so the rules live once."""

import asyncio
import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ledgerline_api import cursor, idempotency, storage
from ledgerline_api.db import DeadLetter as DeadLetterRow
from ledgerline_api.db import Invoice as InvoiceRow
from ledgerline_api.db import OutboxMessage
from ledgerline_api.extraction import ExtractionError, read_pages
from ledgerline_api.schemas import ApiProblem, Invoice, MultiStatus, ProblemCode, UploadResult
from ledgerline_api.settings import settings

EXTRACT_TASK = "ledgerline.extract_invoice"
EXTRACT_QUEUE = "invoices.extract"
MATCH_TASK = "ledgerline.match_invoice"
MATCH_QUEUE = "invoices.match"
# Sent by Celery beat on a schedule, not through the outbox: it belongs to no transaction.
SYNC_TASK = "ledgerline.sync_erp"
SYNC_QUEUE = "erp.sync"
OUTBOX_QUEUES = {EXTRACT_TASK: EXTRACT_QUEUE, MATCH_TASK: MATCH_QUEUE}


@dataclass
class IncomingFile:
    filename: str
    content_type: str
    content: bytes


@dataclass
class UploadResponse:
    status: int
    body: dict
    replayed: bool


def content_fingerprint(pages: list[str] | None, content: bytes) -> str:
    """Same invoice, same fingerprint, even if the PDF was re-rendered: hash the text with whitespace collapsed.
    PDFs without a text layer (scans) all have empty text, so they fall back to the raw bytes."""
    text = re.sub(r"\s+", " ", " ".join(page or "" for page in pages or [])).strip()
    return hashlib.sha256(text.encode() if text else content).hexdigest()


def enqueue_extraction(session: AsyncSession, invoice_id: uuid.UUID) -> None:
    """Add the job to the caller's transaction; the outbox relay publishes it once that transaction commits."""
    session.add(OutboxMessage(task_name=EXTRACT_TASK, payload={"invoice_id": str(invoice_id)}))


def enqueue_match(session: AsyncSession, invoice_id: uuid.UUID) -> None:
    """Queue a 3-way match of the invoice, through the outbox like extraction."""
    session.add(OutboxMessage(task_name=MATCH_TASK, payload={"invoice_id": str(invoice_id)}))


# --- backpressure ---------------------------------------------------------------------------------------

_depth_cache: tuple[float, int] | None = None


async def queue_depth(session: AsyncSession) -> int | None:
    """Jobs waiting: ready messages in RabbitMQ plus jobs not yet published from the outbox. Cached for 2 s so
    a burst of uploads doesn't hammer the management API. None if RabbitMQ can't be asked."""
    global _depth_cache
    now = time.monotonic()
    if _depth_cache and now - _depth_cache[0] < 2:
        return _depth_cache[1]
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{settings.rabbitmq_management_url}/api/queues/%2F/{EXTRACT_QUEUE}")
            response.raise_for_status()
            ready = response.json().get("messages_ready", 0)
    except httpx.HTTPError:
        # Fail open: an unreachable management API shouldn't stop uploads; the broker's own max-length still
        # bounds the queue.
        return None
    # Only extraction jobs count: match jobs are cheap and don't wait for the model.
    unpublished = (
        await session.execute(
            select(func.count()).select_from(OutboxMessage)
            .where(OutboxMessage.published_at.is_(None), OutboxMessage.task_name == EXTRACT_TASK)
        )
    ).scalar_one()
    _depth_cache = (now, ready + unpublished)
    return _depth_cache[1]


# --- uploads --------------------------------------------------------------------------------------------


async def _find_duplicate(session: AsyncSession, sha: str) -> InvoiceRow | None:
    return (
        await session.execute(select(InvoiceRow).where(InvoiceRow.content_sha256 == sha, InvoiceRow.status != "failed"))
    ).scalar_one_or_none()


def _duplicate_result(filename: str, original_id: uuid.UUID) -> UploadResult:
    problem = ApiProblem(
        409,
        ProblemCode.DUPLICATE_INVOICE,
        "Duplicate invoice",
        f"{filename} has the same content as an invoice already stored",
        duplicate_of=original_id,
        duplicate_of_url=f"/v1/invoices/{original_id}",
    ).problem
    return UploadResult(filename=filename, status=409, invoice=None, problem=problem)


async def _store_one(session: AsyncSession, file: IncomingFile) -> UploadResult:
    if file.content_type != "application/pdf":
        problem = ApiProblem(415, ProblemCode.UNSUPPORTED_MEDIA_TYPE, "Unsupported media type",
                             f"{file.filename} is {file.content_type}; only application/pdf is accepted").problem
        return UploadResult(filename=file.filename, status=415, invoice=None, problem=problem)

    # Text is read here only to fingerprint the file. An unreadable PDF is still accepted: the worker records
    # why it can't be extracted, so the client sees the reason on the invoice rather than a bare 4xx.
    try:
        pages: list[str] | None = await asyncio.to_thread(read_pages, file.content)
    except ExtractionError:
        pages = None

    sha = content_fingerprint(pages, file.content)
    if (original := await _find_duplicate(session, sha)) is not None:
        return _duplicate_result(file.filename, original.id)

    invoice_id = uuid.uuid4()
    file_uri = await asyncio.to_thread(storage.put, f"{invoice_id}.pdf", file.content)
    invoice = InvoiceRow(
        id=invoice_id, status="received", original_filename=file.filename, file_path=file_uri,
        content_sha256=sha, page_count=len(pages) if pages is not None else None,
    )
    session.add(invoice)
    enqueue_extraction(session, invoice_id)
    try:
        await session.commit()
    except IntegrityError:
        # Another request stored the same content at the same moment; the unique index decided.
        await session.rollback()
        original = await _find_duplicate(session, sha)
        if original is None:
            raise
        return _duplicate_result(file.filename, original.id)
    await session.refresh(invoice)
    return UploadResult(filename=file.filename, status=202, invoice=Invoice.from_row(invoice), problem=None)


async def upload_invoices(session: AsyncSession, files: list[IncomingFile], key: uuid.UUID) -> UploadResponse:
    if not files:
        raise ApiProblem(400, ProblemCode.INVALID_REQUEST, "No files", "send at least one file in `files`")
    if len(files) > settings.max_files_per_request:
        raise ApiProblem(400, ProblemCode.TOO_MANY_FILES, "Too many files",
                         f"{len(files)} files sent; at most {settings.max_files_per_request} per request")

    now = datetime.now(UTC)
    request_hash = idempotency.request_fingerprint([(f.filename, f.content_type, f.content) for f in files])
    decision, row = await idempotency.claim(
        session, key, request_hash, now,
        ttl=timedelta(hours=settings.idempotency_ttl_hours),
        lock_timeout=timedelta(seconds=settings.idempotency_lock_timeout_s),
    )
    if decision is idempotency.Decision.REUSED:
        raise ApiProblem(422, ProblemCode.IDEMPOTENCY_KEY_REUSED, "Idempotency key reused",
                         "this Idempotency-Key was already used with different files")
    if decision is idempotency.Decision.IN_PROGRESS:
        raise ApiProblem(409, ProblemCode.REQUEST_IN_PROGRESS, "Request in progress",
                         "a request with this Idempotency-Key is still being processed; retry later")
    if decision is idempotency.Decision.REPLAY:
        return UploadResponse(status=row.response_status, body=row.response_body, replayed=True)

    # Checked after the idempotency claim so a retry of a request that already went through is still
    # answered from storage even when the queue is full.
    depth = await queue_depth(session)
    if depth is not None and depth >= settings.max_queue_depth:
        await idempotency.release(session, key)
        raise ApiProblem(429, ProblemCode.QUEUE_FULL, "Extraction queue full",
                         f"{depth} extraction jobs are waiting; retry later",
                         headers={"Retry-After": str(settings.upload_retry_after_s)})

    try:
        results = [await _store_one(session, file) for file in files]
    except BaseException:
        await idempotency.release(session, key)
        raise

    if len(results) == 1:
        only = results[0]
        status = only.status
        body = (only.invoice or only.problem).model_dump(mode="json")
    else:
        status, body = 207, MultiStatus(results=results).model_dump(mode="json")
    await idempotency.complete(session, key, status, body)
    return UploadResponse(status=status, body=body, replayed=False)


# --- reading --------------------------------------------------------------------------------------------


@dataclass
class Page:
    items: list
    next_cursor: str | None
    cursors: list[str]  # one per item, for GraphQL edges


async def keyset_page(session: AsyncSession, query, model, limit: int, after: str | None, filters: dict) -> Page:
    """Newest-first keyset pagination over (created_at, id) with signed cursors bound to `filters` (ADR 0006).
    The one implementation every list endpoint uses."""
    if after is not None:
        try:
            position = cursor.decode(after, filters, settings.cursor_secret)
        except cursor.InvalidCursor as exc:
            raise ApiProblem(400, ProblemCode.INVALID_CURSOR, "Invalid cursor", str(exc)) from None
        # Row-value comparison matches the (created_at DESC, id DESC) index exactly.
        query = query.where(tuple_(model.created_at, model.id) < (position.created_at, position.id))

    # One extra row tells us whether a next page exists without a COUNT.
    rows = list((await session.execute(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1))).scalars())
    items = rows[:limit]
    cursors = [cursor.encode(cursor.Position(row.created_at, row.id), filters, settings.cursor_secret) for row in items]
    return Page(items=items, next_cursor=cursors[-1] if len(rows) > limit else None, cursors=cursors)


async def list_invoices(
    session: AsyncSession,
    limit: int,
    after: str | None = None,
    status: str | None = None,
    created_after: datetime | None = None,
) -> Page:
    filters = {"status": status, "created_after": created_after.isoformat() if created_after else None}
    query = select(InvoiceRow)
    if status is not None:
        query = query.where(InvoiceRow.status == status)
    if created_after is not None:
        query = query.where(InvoiceRow.created_at > created_after)
    return await keyset_page(session, query, InvoiceRow, limit, after, filters)


async def get_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> InvoiceRow | None:
    return await session.get(InvoiceRow, invoice_id)


# --- dead letters ---------------------------------------------------------------------------------------


async def list_dead_letters(session: AsyncSession, limit: int, after: str | None = None) -> Page:
    return await keyset_page(session, select(DeadLetterRow), DeadLetterRow, limit, after, {"list": "dead_letters"})


async def replay_dead_letter(session: AsyncSession, dead_letter_id: uuid.UUID) -> tuple[DeadLetterRow, bool]:
    """Queue the invoice again with a fresh retry budget. Returns (row, replayed_now); a second replay of the
    same dead letter changes nothing."""
    row = (
        await session.execute(select(DeadLetterRow).where(DeadLetterRow.id == dead_letter_id).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        raise ApiProblem(404, ProblemCode.NOT_FOUND, "Dead letter not found", f"no dead letter with id {dead_letter_id}")
    if row.replayed_at is not None:
        await session.commit()
        return row, False

    invoice = await session.get(InvoiceRow, row.invoice_id, with_for_update=True)
    invoice.status, invoice.error_code, invoice.error_detail = "received", None, None
    row.replayed_at = datetime.now(UTC)
    enqueue_extraction(session, invoice.id)
    try:
        await session.commit()
    except IntegrityError:
        # The same content was uploaded again (and stored) while this one sat in the dead-letter queue.
        await session.rollback()
        original = await _find_duplicate(session, invoice.content_sha256)
        raise ApiProblem(409, ProblemCode.DUPLICATE_INVOICE, "Duplicate invoice",
                         "an invoice with the same content has been stored since; replay would duplicate it",
                         duplicate_of=original.id if original else None,
                         duplicate_of_url=f"/v1/invoices/{original.id}" if original else None) from None
    return row, True
