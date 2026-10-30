import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
        CheckConstraint("status IN ('extracted', 'failed')", name="invoices_status_check"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="invoices_currency_check"),
    )

    # uuidv7() is built into Postgres 18: time-ordered ids keep the primary-key index append-only.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    status: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str]
    file_path: Mapped[str]
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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
