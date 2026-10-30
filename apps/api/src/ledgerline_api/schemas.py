"""Response shapes for the REST API. contracts/openapi.yaml is the source of truth; these mirror it and
`make contract-check` fails if they drift in a way that would break a client."""

import enum
import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ledgerline_api.db import Invoice as InvoiceRow


class ProblemCode(enum.StrEnum):
    INVALID_REQUEST = "invalid_request"
    IDEMPOTENCY_KEY_MISSING = "idempotency_key_missing"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    REQUEST_IN_PROGRESS = "request_in_progress"
    TOO_MANY_FILES = "too_many_files"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    DUPLICATE_INVOICE = "duplicate_invoice"
    INVALID_CURSOR = "invalid_cursor"
    NOT_FOUND = "not_found"


class InvoiceStatus(enum.StrEnum):
    EXTRACTED = "extracted"
    FAILED = "failed"


class Problem(BaseModel):
    """RFC 9457 problem details, plus our stable `code`."""

    model_config = ConfigDict(use_enum_values=True)

    type: str
    title: str
    status: int
    detail: str | None = None
    code: ProblemCode
    duplicate_of: uuid.UUID | None = None
    duplicate_of_url: str | None = None


class ApiProblem(Exception):
    """Raised anywhere in request handling; rendered as application/problem+json."""

    def __init__(self, status: int, code: ProblemCode, title: str, detail: str | None = None, **extra):
        super().__init__(f"{status} {code}: {detail or title}")
        self.problem = Problem(
            type=f"https://github.com/Abuubkar/ledgerline/blob/main/docs/problems.md#{code}",
            title=title,
            status=status,
            detail=detail,
            code=code,
            **extra,
        )


Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class Money(BaseModel):
    amount_minor: Annotated[int, Field(json_schema_extra={"format": "int64"})]
    currency: Currency


class Invoice(BaseModel):
    id: uuid.UUID
    status: InvoiceStatus
    original_filename: str
    page_count: int | None
    vendor_name: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: Currency | None
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    field_confidence: dict[str, float] | None
    invalid_fields: dict[str, str] | None
    error_code: str | None
    error_detail: str | None
    model: str | None
    prompt_version: str | None
    prompt_tokens: int | None
    output_tokens: int | None
    llm_ms: int | None
    created_at: datetime

    @classmethod
    def from_row(cls, invoice: InvoiceRow) -> "Invoice":
        def money(minor: int | None) -> Money | None:
            if minor is None or invoice.currency is None:
                return None
            return Money(amount_minor=minor, currency=invoice.currency)

        plain = {name: getattr(invoice, name) for name in cls.model_fields if name not in ("subtotal", "tax", "total")}
        return cls(**plain, subtotal=money(invoice.subtotal_minor), tax=money(invoice.tax_minor), total=money(invoice.total_minor))


class InvoicePage(BaseModel):
    data: list[Invoice]
    next_cursor: str | None


class UploadResult(BaseModel):
    filename: str
    status: int
    invoice: Invoice | None
    problem: Problem | None


class MultiStatus(BaseModel):
    results: list[UploadResult]
