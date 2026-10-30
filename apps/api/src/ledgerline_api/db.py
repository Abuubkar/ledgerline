import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime

from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ledgerline_api.settings import settings

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # received → extracting → extracted | partially_extracted | exception, or failed (dead-lettered).
        CheckConstraint(
            "status IN ('received', 'extracting', 'extracted', 'partially_extracted', 'exception', 'failed')",
            name="invoices_status_check",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="invoices_currency_check"),
        # Failed extractions don't block a re-upload of the same invoice (e.g. after a model outage).
        Index(
            "invoices_content_sha256_key",
            "content_sha256",
            unique=True,
            postgresql_where=text("status <> 'failed'"),
        ),
        # Keyset pagination reads newest first: (created_at, id) descending, id breaking ties.
        Index("invoices_created_at_id_idx", text("created_at DESC"), text("id DESC")),
    )

    # uuidv7() is built into Postgres 18: time-ordered ids keep the primary-key index append-only.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    status: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str]
    # Local path for rows from slices 1–2; an s3:// URI from slice 3 on.
    file_path: Mapped[str]
    # sha256 of the normalized text, or of the file bytes when there is no text layer. Null for rows
    # stored before slice 2.
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None]

    vendor_name: Mapped[str | None]
    vendor_tax_id: Mapped[str | None]
    invoice_number: Mapped[str | None]
    invoice_date: Mapped[date | None]
    due_date: Mapped[date | None]
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal_minor: Mapped[int | None] = mapped_column(BigInteger)
    tax_minor: Mapped[int | None] = mapped_column(BigInteger)
    total_minor: Mapped[int | None] = mapped_column(BigInteger)
    field_confidence: Mapped[dict | None] = mapped_column(JSONB)
    invalid_fields: Mapped[dict | None] = mapped_column(JSONB)

    error_code: Mapped[str | None]
    error_detail: Mapped[str | None]

    model: Mapped[str | None]
    prompt_version: Mapped[str | None]
    prompt_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    llm_ms: Mapped[int | None]
    repair_attempted: Mapped[bool] = mapped_column(server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Loaded with the invoice: async sessions can't lazy-load, and the API always returns both.
    pages: Mapped[list["InvoicePageResult"]] = relationship(
        lazy="selectin", order_by="InvoicePageResult.page_no", cascade="all, delete-orphan"
    )
    lines: Mapped[list["InvoiceLine"]] = relationship(
        lazy="selectin", order_by="(InvoiceLine.page_no, InvoiceLine.line_no)", cascade="all, delete-orphan"
    )


class InvoicePageResult(Base):
    __tablename__ = "invoice_pages"
    __table_args__ = (
        UniqueConstraint("invoice_id", "page_no"),
        CheckConstraint("status IN ('extracted', 'blank', 'failed')", name="invoice_pages_status_check"),
        CheckConstraint("source IN ('text', 'image')", name="invoice_pages_source_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    page_no: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None]
    error_detail: Mapped[str | None]
    prompt_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    llm_ms: Mapped[int | None]


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (UniqueConstraint("invoice_id", "page_no", "line_no"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    page_no: Mapped[int]
    line_no: Mapped[int]
    description: Mapped[str | None]
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    # Unit prices can be finer than the currency's minor unit (0.125 EUR per screw), so they stay decimal;
    # the line amount is money and is stored in minor units.
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    invalid_reason: Mapped[str | None]


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    # Null while the first request is still running.
    response_status: Mapped[int | None]
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxMessage(Base):
    """A job written in the same transaction as the data it refers to; the relay publishes it after commit,
    so a rolled-back upload never produces a job and a committed one never loses its job."""

    __tablename__ = "outbox"
    __table_args__ = (Index("outbox_unpublished_idx", "id", postgresql_where=text("published_at IS NULL")),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    task_name: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractionRun(Base):
    """One attempt at extracting an invoice. A `running` row is a lease the worker renews while it works."""

    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('running', 'completed', 'transient_failure', 'permanent_failure', 'abandoned')",
            name="extraction_runs_outcome_check",
        ),
        # At most one attempt in flight, and at most one successful extraction, per invoice.
        Index("extraction_runs_one_running", "invoice_id", unique=True, postgresql_where=text("outcome = 'running'")),
        Index(
            "extraction_runs_one_completed", "invoice_id", unique=True, postgresql_where=text("outcome = 'completed'")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    task_id: Mapped[str]
    attempt: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(20))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None]
    error_detail: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeadLetter(Base):
    """A job that gave up: retries exhausted or a permanent error. Replay re-enqueues it with a fresh budget."""

    __tablename__ = "dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    task_name: Mapped[str]
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    error_code: Mapped[str]
    exception_chain: Mapped[str]
    attempts: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
