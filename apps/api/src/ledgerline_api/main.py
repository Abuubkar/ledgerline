import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ledgerline_api.db import Invoice, get_session
from ledgerline_api.extraction import ExtractionError, extract_invoice
from ledgerline_api.settings import settings

app = FastAPI(title="Ledgerline")


class Money(BaseModel):
    amount_minor: int
    currency: str


class InvoiceOut(BaseModel):
    id: uuid.UUID
    status: str
    original_filename: str
    page_count: int | None
    vendor_name: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: str | None
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    field_confidence: dict | None
    invalid_fields: dict | None
    error_code: str | None
    error_detail: str | None
    model: str | None
    prompt_version: str | None
    prompt_tokens: int | None
    output_tokens: int | None
    llm_ms: int | None
    created_at: datetime


def _money(minor: int | None, currency: str | None) -> Money | None:
    if minor is None or currency is None:
        return None
    return Money(amount_minor=minor, currency=currency)


def to_out(invoice: Invoice) -> InvoiceOut:
    return InvoiceOut(
        **{name: getattr(invoice, name) for name in InvoiceOut.model_fields if hasattr(invoice, name)},
        subtotal=_money(invoice.subtotal_minor, invoice.currency),
        tax=_money(invoice.tax_minor, invoice.currency),
        total=_money(invoice.total_minor, invoice.currency),
    )


Session = Annotated[AsyncSession, Depends(get_session)]


@app.post("/v1/invoices", status_code=201)
async def upload_invoice(file: UploadFile, session: Session) -> InvoiceOut:
    if file.content_type != "application/pdf":
        raise HTTPException(415, "only application/pdf is accepted")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{uuid.uuid4()}.pdf"
    path.write_bytes(await file.read())

    invoice = Invoice(original_filename=file.filename or path.name, file_path=str(path))
    try:
        extraction = await extract_invoice(path)
    except ExtractionError as exc:
        # The upload itself succeeded, so the record is kept with the reason extraction failed.
        invoice.status, invoice.error_code, invoice.error_detail = "failed", exc.code, exc.detail
    else:
        header = asdict(extraction.header)
        for name, value in header.items():
            setattr(invoice, name, value)
        invoice.status = "extracted"
        invoice.page_count = extraction.page_count
        invoice.model = extraction.model
        invoice.prompt_version = extraction.prompt_version
        invoice.prompt_tokens = extraction.prompt_tokens
        invoice.output_tokens = extraction.output_tokens
        invoice.llm_ms = extraction.llm_ms

    session.add(invoice)
    await session.commit()
    await session.refresh(invoice)
    return to_out(invoice)


@app.get("/v1/invoices/{invoice_id}")
async def get_invoice(invoice_id: uuid.UUID, session: Session) -> InvoiceOut:
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "invoice not found")
    return to_out(invoice)
