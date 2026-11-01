import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
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


class Vendor(Base):
    """A company that bills us. Recognized by its tax ID; one without a tax ID by its normalized name."""

    __tablename__ = "vendors"
    __table_args__ = (
        Index("vendors_tax_id_key", "tax_id", unique=True, postgresql_where=text("tax_id IS NOT NULL")),
        Index("vendors_name_key_key", "name_key", unique=True, postgresql_where=text("tax_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    tax_id: Mapped[str | None]
    # The name as first seen; later invoices may spell it differently.
    name: Mapped[str]
    name_key: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # received → extracting → extracted | partially_extracted | exception, or failed (dead-lettered);
        # extracted → matched | exception once checked against its purchase order and goods receipts.
        CheckConstraint(
            "status IN ('received', 'extracting', 'extracted', 'partially_extracted', 'exception', 'failed', 'matched')",
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
        # One invoice per vendor and number. A later copy keeps a null key and is flagged (vendors.link).
        Index(
            "invoices_vendor_number_key",
            "vendor_id",
            "invoice_number_key",
            unique=True,
            postgresql_where=text("invoice_number_key IS NOT NULL"),
        ),
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

    # The vendor's name and tax ID as read are kept on the completed extraction run (extracted_header).
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    invoice_number: Mapped[str | None]
    invoice_number_key: Mapped[str | None]
    # The buyer's purchase order number as printed; matching finds the PO by po_number_key.
    po_number: Mapped[str | None]
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

    # Loaded with the invoice: async sessions can't lazy-load, and the API always returns these.
    vendor: Mapped["Vendor | None"] = relationship(lazy="selectin")
    pages: Mapped[list["InvoicePageResult"]] = relationship(
        lazy="selectin", order_by="InvoicePageResult.page_no", cascade="all, delete-orphan"
    )
    lines: Mapped[list["InvoiceLine"]] = relationship(
        lazy="selectin", order_by="(InvoiceLine.page_no, InvoiceLine.line_no)", cascade="all, delete-orphan"
    )
    match: Mapped["MatchResult | None"] = relationship(lazy="selectin", passive_deletes=True)


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
    # What the model read, before vendors were linked or duplicates flagged. Set on the completed run.
    extracted_header: Mapped[dict | None] = mapped_column(JSONB)
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


class PurchaseOrder(Base):
    """A purchase order as the ERP last sent it (sync_erp). Updated only by a newer ERP version."""

    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    erp_id: Mapped[str] = mapped_column(unique=True)
    po_number: Mapped[str]
    po_number_key: Mapped[str] = mapped_column(unique=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str]
    erp_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["PoLine"]] = relationship(lazy="selectin", order_by="PoLine.line_no", passive_deletes=True)


class PoLine(Base):
    __tablename__ = "po_lines"
    __table_args__ = (UniqueConstraint("purchase_order_id", "line_no"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    line_no: Mapped[int]
    description: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))


class GoodsReceipt(Base):
    """Goods received against a purchase order. Linked by PO number, not a foreign key: the ERP can send a
    receipt before we have synced its PO."""

    __tablename__ = "goods_receipts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    erp_id: Mapped[str] = mapped_column(unique=True)
    po_number_key: Mapped[str] = mapped_column(index=True)
    received_on: Mapped[date]
    erp_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["ReceiptLine"]] = relationship(lazy="selectin", order_by="ReceiptLine.line_no", passive_deletes=True)


class ReceiptLine(Base):
    __tablename__ = "receipt_lines"
    __table_args__ = (UniqueConstraint("goods_receipt_id", "line_no"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goods_receipts.id", ondelete="CASCADE"))
    line_no: Mapped[int]
    po_line_no: Mapped[int]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class MatchResult(Base):
    """The latest 3-way match of an invoice against its PO and receipts; a re-match replaces it."""

    __tablename__ = "match_results"
    __table_args__ = (
        CheckConstraint("status IN ('matched', 'exception')", name="match_results_status_check"),
        # A sync that brings a missing PO or receipt re-matches the invoices that were waiting for it.
        Index("match_results_waiting_idx", "po_number_key", postgresql_where=text("status = 'exception'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    po_number_key: Mapped[str | None]
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id"))
    # [{"code": ..., "line": "page 1 line 2" | None, "detail": ...}]; empty when matched.
    reasons: Mapped[list] = mapped_column(JSONB)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ErpSyncState(Base):
    """Where sync_erp is in each ERP list. The cursor is saved with every page, so a crash resumes mid-walk."""

    __tablename__ = "erp_sync_state"

    resource: Mapped[str] = mapped_column(primary_key=True)  # purchase-orders | receipts
    # The ERP's opaque cursor for the next page of the walk in progress; null between walks.
    cursor: Mapped[str | None]
    # Every ERP change older than this is stored: the newest updated_at committed so far. The next walk, or a
    # restart after an expired cursor, asks for updated_since this.
    synced_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRun(Base):
    """One run of the exception agent on one invoice: it gathers evidence with tools and ends with exactly one
    proposal (a pending action), or fails. The full trace is in agent_steps."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'proposed', 'failed')", name="agent_runs_status_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    model: Mapped[str]
    prompt_version: Mapped[str]
    # Model responses that asked for tools; capped at agent_max_turns.
    tool_turns: Mapped[int] = mapped_column(server_default=text("0"))
    # Write tools refused by the code guard (e.g. a credit memo before the receipts were checked).
    guard_fires: Mapped[int] = mapped_column(server_default=text("0"))
    stop_reason: Mapped[str | None]  # proposed | no_proposal | agent_budget_exceeded | error code
    prompt_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    llm_ms: Mapped[int] = mapped_column(server_default=text("0"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list["AgentStep"]] = relationship(lazy="selectin", order_by="AgentStep.step_no", passive_deletes=True)


class AgentStep(Base):
    """One step of a run: a model response (its text and the tool calls it asked for) or one tool call with
    its validated arguments and result."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_no"),
        CheckConstraint("kind IN ('model', 'tool')", name="agent_steps_kind_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    step_no: Mapped[int]
    kind: Mapped[str] = mapped_column(String(10))
    content: Mapped[str | None]  # the model's text, if any
    tool_name: Mapped[str | None]
    arguments: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None]  # invalid arguments, a guard refusal or a tool failure, as sent back to the model
    llm_ms: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAction(Base):
    """What the agent proposes for an invoice, waiting for a person. Nothing is done until it's approved;
    `version` is the ETag that makes two reviewers deciding at once safe."""

    __tablename__ = "pending_actions"
    __table_args__ = (
        CheckConstraint("action_type IN ('credit_memo_request', 'hold')", name="pending_actions_type_check"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="pending_actions_status_check"),
        # At most one proposal waiting per invoice.
        Index("pending_actions_one_pending", "invoice_id", unique=True, postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    action_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending'"))
    # credit_memo_request: amount_minor, currency, reason, lines (computed in code, never by the model).
    # hold: reason_code, explanation.
    details: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(server_default=text("1"))
    decision_note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
