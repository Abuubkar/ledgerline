"""Turn what the model read off the page into typed, comparable header fields.

The model returns strings exactly as asked (ISO dates, plain decimal amounts). Anything that doesn't fit is
recorded as an invalid field instead of being guessed at, so a person can see what went wrong.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from ledgerline_api.money import CURRENCY_EXPONENTS, MoneyError, to_minor


class ExtractedHeader(BaseModel):
    """What the model must return. Its JSON schema is passed to Ollama's `format` parameter."""

    vendor_name: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    currency: str | None
    subtotal: str | None
    tax: str | None
    total: str | None
    field_confidence: dict[str, float]


@dataclass
class InvoiceHeader:
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal_minor: int | None = None
    tax_minor: int | None = None
    total_minor: int | None = None
    field_confidence: dict[str, float] = field(default_factory=dict)
    invalid_fields: dict[str, str] = field(default_factory=dict)


def normalize_tax_id(raw: str) -> str:
    # EU VAT IDs carry a country prefix (DE123456789), so letters are kept; only separators are dropped.
    return re.sub(r"[^0-9A-Z]", "", raw.upper())


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def normalize_header(extracted: ExtractedHeader) -> InvoiceHeader:
    header = InvoiceHeader(field_confidence=extracted.field_confidence)

    header.vendor_name = _blank_to_none(extracted.vendor_name)
    header.invoice_number = _blank_to_none(extracted.invoice_number)

    if tax_id := _blank_to_none(extracted.vendor_tax_id):
        header.vendor_tax_id = normalize_tax_id(tax_id) or None

    for name in ("invoice_date", "due_date"):
        raw = _blank_to_none(getattr(extracted, name))
        if raw is None:
            continue
        try:
            # Only ISO is accepted: "03/09/2026" is ambiguous between March and September.
            setattr(header, name, date.fromisoformat(raw))
        except ValueError:
            header.invalid_fields[name] = f"not an ISO date: {raw!r}"

    if currency := _blank_to_none(extracted.currency):
        currency = currency.upper()
        if currency in CURRENCY_EXPONENTS:
            header.currency = currency
        else:
            header.invalid_fields["currency"] = f"unsupported currency: {currency!r}"

    for name in ("subtotal", "tax", "total"):
        raw = _blank_to_none(getattr(extracted, name))
        if raw is None:
            continue
        if header.currency is None:
            header.invalid_fields[name] = "amount without a valid currency"
            continue
        try:
            setattr(header, f"{name}_minor", to_minor(raw, header.currency))
        except MoneyError as exc:
            header.invalid_fields[name] = str(exc)

    return header
