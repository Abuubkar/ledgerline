"""What the API does, independent of REST or GraphQL. Both call these functions, so the rules live once."""

import asyncio
import hashlib
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ledgerline_api import cursor, idempotency
from ledgerline_api.db import Invoice as InvoiceRow
from ledgerline_api.extraction import ExtractionError, extract_header, read_pages
from ledgerline_api.schemas import ApiProblem, Invoice, MultiStatus, ProblemCode, UploadResult
from ledgerline_api.settings import settings


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
    text = re.sub(r"\s+", " ", " ".join(pages or [])).strip()
    return hashlib.sha256(text.encode() if text else content).hexdigest()


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

    try:
        pages: list[str] | None = await asyncio.to_thread(read_pages, file.content)
        read_error = None
    except ExtractionError as exc:
        pages, read_error = None, exc

    sha = content_fingerprint(pages, file.content)
    # Checked before the model call: a duplicate costs a query, not 25 seconds of model time.
    if (original := await _find_duplicate(session, sha)) is not None:
        return _duplicate_result(file.filename, original.id)

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{uuid.uuid4()}.pdf"
    await asyncio.to_thread(path.write_bytes, file.content)
    invoice = InvoiceRow(original_filename=file.filename, file_path=str(path), content_sha256=sha)

    try:
        if read_error:
            raise read_error
        extraction = await extract_header(pages or [])
    except ExtractionError as exc:
        # The upload itself succeeded, so it is kept with the reason extraction failed.
        invoice.status, invoice.error_code, invoice.error_detail = "failed", exc.code, exc.detail
        invoice.page_count = len(pages) if pages is not None else None
    else:
        for name, value in asdict(extraction.header).items():
            setattr(invoice, name, value)
        invoice.status = "extracted"
        invoice.page_count = extraction.page_count
        invoice.model = extraction.model
        invoice.prompt_version = extraction.prompt_version
        invoice.prompt_tokens = extraction.prompt_tokens
        invoice.output_tokens = extraction.output_tokens
        invoice.llm_ms = extraction.llm_ms

    session.add(invoice)
    try:
        await session.commit()
    except IntegrityError:
        # Another request stored the same content while this one was extracting; the unique index decided.
        await session.rollback()
        original = await _find_duplicate(session, sha)
        if original is None:
            raise
        return _duplicate_result(file.filename, original.id)
    await session.refresh(invoice)
    return UploadResult(filename=file.filename, status=201, invoice=Invoice.from_row(invoice), problem=None)


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


@dataclass
class Page:
    items: list[InvoiceRow]
    next_cursor: str | None
    cursors: list[str]  # one per item, for GraphQL edges


def _filters(status: str | None, created_after: datetime | None) -> dict[str, str | None]:
    return {"status": status, "created_after": created_after.isoformat() if created_after else None}


async def list_invoices(
    session: AsyncSession,
    limit: int,
    after: str | None = None,
    status: str | None = None,
    created_after: datetime | None = None,
) -> Page:
    filters = _filters(status, created_after)
    query = select(InvoiceRow)
    if status is not None:
        query = query.where(InvoiceRow.status == status)
    if created_after is not None:
        query = query.where(InvoiceRow.created_at > created_after)
    if after is not None:
        try:
            position = cursor.decode(after, filters, settings.cursor_secret)
        except cursor.InvalidCursor as exc:
            raise ApiProblem(400, ProblemCode.INVALID_CURSOR, "Invalid cursor", str(exc)) from None
        # Row-value comparison matches the (created_at DESC, id DESC) index exactly.
        query = query.where(tuple_(InvoiceRow.created_at, InvoiceRow.id) < (position.created_at, position.id))

    # One extra row tells us whether a next page exists without a COUNT.
    rows = list(
        (await session.execute(query.order_by(InvoiceRow.created_at.desc(), InvoiceRow.id.desc()).limit(limit + 1))).scalars()
    )
    items = rows[:limit]
    cursors = [
        cursor.encode(cursor.Position(row.created_at, row.id), filters, settings.cursor_secret) for row in items
    ]
    next_cursor = cursors[-1] if len(rows) > limit else None
    return Page(items=items, next_cursor=next_cursor, cursors=cursors)


async def get_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> InvoiceRow | None:
    return await session.get(InvoiceRow, invoice_id)
