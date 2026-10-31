"""Response shapes for the REST API. contracts/openapi.yaml is the source of truth; these mirror it and
`make contract-check` fails if they drift in a way that would break a client."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ledgerline_api.db import DeadLetter as DeadLetterRow
from ledgerline_api.db import Invoice as InvoiceRow
from ledgerline_api.db import PendingAction as PendingActionRow


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
    QUEUE_FULL = "queue_full"
    PRECONDITION_REQUIRED = "precondition_required"
    VERSION_CONFLICT = "version_conflict"
    ACTION_ALREADY_DECIDED = "action_already_decided"


class InvoiceStatus(enum.StrEnum):
    RECEIVED = "received"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    PARTIALLY_EXTRACTED = "partially_extracted"
    EXCEPTION = "exception"
    FAILED = "failed"
    MATCHED = "matched"


class PageStatus(enum.StrEnum):
    EXTRACTED = "extracted"
    BLANK = "blank"
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
    current_version: int | None = None


class ApiProblem(Exception):
    """Raised anywhere in request handling; rendered as application/problem+json."""

    def __init__(
        self, status: int, code: ProblemCode, title: str, detail: str | None = None,
        headers: dict[str, str] | None = None, **extra,
    ):
        super().__init__(f"{status} {code}: {detail or title}")
        self.headers = headers
        self.problem = Problem(
            type=f"https://github.com/Abuubkar/ledgerline/blob/main/docs/problems.md#{code}",
            title=title,
            status=status,
            detail=detail,
            code=code,
            **extra,
        )


Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


def _decimal_str(value: Decimal | None) -> str | None:
    # NUMERIC columns pad to their scale ("2.0000"); trailing zeros carry no meaning here.
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text


class Money(BaseModel):
    amount_minor: Annotated[int, Field(json_schema_extra={"format": "int64"})]
    currency: Currency


class PageResult(BaseModel):
    page_no: int
    status: PageStatus
    source: Literal["text", "image"]
    error_code: str | None
    llm_ms: int | None


class InvoiceLine(BaseModel):
    page_no: int
    line_no: int
    description: str | None
    # Decimals travel as strings so JSON floats can't round them.
    quantity: str | None
    unit_price: str | None
    amount: Money | None
    invalid_reason: str | None


class Vendor(BaseModel):
    id: uuid.UUID
    name: str
    tax_id: str | None


class MatchReason(BaseModel):
    code: str
    detail: str
    line: str | None


class MatchResult(BaseModel):
    status: Literal["matched", "exception"]
    purchase_order_id: uuid.UUID | None
    reasons: list[MatchReason]
    matched_at: datetime


class Invoice(BaseModel):
    id: uuid.UUID
    status: InvoiceStatus
    original_filename: str
    page_count: int | None
    vendor: Vendor | None
    # Kept for clients from before vendors existed; both now come from the vendor.
    vendor_name: str | None = Field(json_schema_extra={"deprecated": True})
    vendor_tax_id: str | None = Field(json_schema_extra={"deprecated": True})
    invoice_number: str | None
    po_number: str | None
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
    repair_attempted: bool
    pages: list[PageResult]
    lines: list[InvoiceLine]
    match: MatchResult | None
    created_at: datetime

    @classmethod
    def from_row(cls, invoice: InvoiceRow) -> "Invoice":
        def money(minor: int | None) -> Money | None:
            if minor is None or invoice.currency is None:
                return None
            return Money(amount_minor=minor, currency=invoice.currency)

        nested = ("vendor", "vendor_name", "vendor_tax_id", "subtotal", "tax", "total", "pages", "lines", "match")
        plain = {name: getattr(invoice, name) for name in cls.model_fields if name not in nested}
        vendor, match = invoice.vendor, invoice.match
        return cls(
            **plain,
            vendor=Vendor(id=vendor.id, name=vendor.name, tax_id=vendor.tax_id) if vendor else None,
            vendor_name=vendor.name if vendor else None, vendor_tax_id=vendor.tax_id if vendor else None,
            subtotal=money(invoice.subtotal_minor), tax=money(invoice.tax_minor), total=money(invoice.total_minor),
            pages=[
                PageResult(page_no=p.page_no, status=p.status, source=p.source, error_code=p.error_code, llm_ms=p.llm_ms)
                for p in invoice.pages
            ],
            lines=[
                InvoiceLine(
                    page_no=line.page_no, line_no=line.line_no, description=line.description,
                    quantity=_decimal_str(line.quantity), unit_price=_decimal_str(line.unit_price),
                    amount=money(line.amount_minor), invalid_reason=line.invalid_reason,
                )
                for line in invoice.lines
            ],
            match=MatchResult(status=match.status, purchase_order_id=match.purchase_order_id,
                              reasons=match.reasons, matched_at=match.matched_at) if match else None,
        )


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


class DeadLetter(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_name: str
    invoice_id: uuid.UUID
    error_code: str
    exception_chain: str
    attempts: int
    created_at: datetime
    replayed_at: datetime | None

    @classmethod
    def from_row(cls, row: DeadLetterRow) -> "DeadLetter":
        return cls.model_validate(row)


class DeadLetterPage(BaseModel):
    data: list[DeadLetter]
    next_cursor: str | None


class PendingAction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    agent_run_id: uuid.UUID
    action_type: Literal["credit_memo_request", "hold"]
    status: Literal["pending", "approved", "rejected"]
    details: dict
    version: int
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def from_row(cls, row: PendingActionRow) -> "PendingAction":
        return cls.model_validate(row)


class PendingActionList(BaseModel):
    data: list[PendingAction]


class Decision(BaseModel):
    note: str | None = Field(None, max_length=500)
