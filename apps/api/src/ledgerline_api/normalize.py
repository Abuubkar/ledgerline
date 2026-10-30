"""Turn what the model read off each page into typed invoice data, and check that the numbers add up.

The model returns strings exactly as asked (ISO dates, plain decimal amounts). Anything that doesn't fit is
recorded as an invalid field instead of being guessed at, so a person can see what went wrong. Totals are
checked here, in code; a number is never changed to make the arithmetic work.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from ledgerline_api.money import CURRENCY_EXPONENTS, MoneyError, format_minor, to_minor

HEADER_FIELDS = (
    "vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "due_date",
    "currency", "subtotal", "tax", "total",
)
# Allowed rounding slack between a total and the sum of its parts, in minor units.
TOLERANCE_MINOR = 1


class ExtractedHeader(BaseModel):
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


class ExtractedLine(BaseModel):
    description: str | None
    quantity: str | None
    unit_price: str | None
    amount: str | None


class ExtractedPage(ExtractedHeader):
    """What the model returns for one page. Its JSON schema is passed to Ollama's `format` parameter."""

    line_items: list[ExtractedLine]


class RepairedLine(ExtractedLine):
    page: int


class RepairedInvoice(ExtractedHeader):
    """What the repair call returns: the whole invoice, with each line's page."""

    line_items: list[RepairedLine]


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


@dataclass
class Line:
    page_no: int
    line_no: int
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount_minor: int | None
    invalid_reason: str | None = None


def normalize_tax_id(raw: str) -> str:
    # EU VAT IDs carry a country prefix (DE123456789), so letters are kept; only separators are dropped.
    return re.sub(r"[^0-9A-Z]", "", raw.upper())


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _currency(raw: str | None) -> tuple[str | None, str | None]:
    """(code, problem): an ISO code we support, or why the raw value isn't one."""
    if (raw := _blank_to_none(raw)) is None:
        return None, None
    code = raw.upper()
    return (code, None) if code in CURRENCY_EXPONENTS else (None, f"unsupported currency: {raw!r}")


def _decimal(raw: str | None) -> Decimal | None:
    if (raw := _blank_to_none(raw)) is None:
        return None
    cleaned = raw.replace(",", "").replace(" ", "").replace("'", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a number: {raw!r}") from None
    if not value.is_finite():
        raise ValueError(f"not a number: {raw!r}")
    return value


def normalize_header(extracted: ExtractedHeader, currency: str | None = None) -> InvoiceHeader:
    """Typed header fields from one extraction. `currency` is used when this extraction didn't print one (a
    continuation page often shows amounts but not the currency)."""
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

    code, problem = _currency(extracted.currency)
    if problem:
        header.invalid_fields["currency"] = problem
    header.currency = code
    money_currency = code or currency

    for name in ("subtotal", "tax", "total"):
        raw = _blank_to_none(getattr(extracted, name))
        if raw is None:
            continue
        if money_currency is None:
            header.invalid_fields[name] = "amount without a valid currency"
            continue
        try:
            setattr(header, f"{name}_minor", to_minor(raw, money_currency))
        except MoneyError as exc:
            header.invalid_fields[name] = str(exc)

    return header


def normalize_lines(page_no: int, items: list[ExtractedLine], currency: str | None) -> list[Line]:
    lines = []
    for line_no, item in enumerate(items, start=1):
        problems, quantity, unit_price, amount = [], None, None, None
        for name in ("quantity", "unit_price"):
            try:
                value = _decimal(getattr(item, name))
            except ValueError as exc:
                problems.append(f"{name}: {exc}")
            else:
                quantity, unit_price = (value, unit_price) if name == "quantity" else (quantity, value)
        if (raw := _blank_to_none(item.amount)) is None:
            problems.append("amount missing")
        elif currency is None:
            problems.append("amount without a valid currency")
        else:
            try:
                amount = to_minor(raw, currency)
            except MoneyError as exc:
                problems.append(f"amount: {exc}")
        lines.append(Line(page_no, line_no, _blank_to_none(item.description), quantity, unit_price, amount,
                          "; ".join(problems) or None))
    return lines


def _field_value(header: InvoiceHeader, name: str):
    return getattr(header, f"{name}_minor") if name in ("subtotal", "tax", "total") else getattr(header, name)


def merge_pages(pages: list[tuple[int, ExtractedPage]]) -> tuple[InvoiceHeader, list[Line]]:
    """One invoice from its pages. Each header field takes the value the pages agree on (keeping the highest
    confidence); pages that disagree make the field invalid rather than picking one."""
    # Amounts on a page that doesn't print the currency use the one the other pages agree on.
    currencies = {code for _, page in pages if (code := _currency(page.currency)[0])}
    currency = next(iter(currencies)) if len(currencies) == 1 else None

    per_page = [(page_no, page, normalize_header(page, currency)) for page_no, page in pages]
    merged = InvoiceHeader()
    for name in HEADER_FIELDS:
        seen: dict[object, list[int]] = {}
        best_confidence = None
        for page_no, page, header in per_page:
            value = _field_value(header, name)
            if value is None:
                if name in header.invalid_fields:
                    merged.invalid_fields.setdefault(name, f"page {page_no}: {header.invalid_fields[name]}")
                continue
            seen.setdefault(value, []).append(page_no)
            confidence = page.field_confidence.get(name)
            if confidence is not None:
                best_confidence = max(best_confidence or 0.0, confidence)
        if len(seen) > 1:
            merged.invalid_fields[name] = "pages disagree: " + "; ".join(
                f"page {', '.join(map(str, nums))} says {value}" for value, nums in seen.items()
            )
        elif seen:
            value = next(iter(seen))
            setattr(merged, f"{name}_minor" if name in ("subtotal", "tax", "total") else name, value)
            merged.invalid_fields.pop(name, None)  # another page had a usable value
            if best_confidence is not None:
                merged.field_confidence[name] = best_confidence

    lines = [line for page_no, page, _ in per_page for line in normalize_lines(page_no, page.line_items, currency)]
    return merged, lines


def from_repair(repaired: RepairedInvoice) -> tuple[InvoiceHeader, list[Line]]:
    header = normalize_header(repaired)
    by_page: dict[int, list[ExtractedLine]] = {}
    for item in repaired.line_items:
        by_page.setdefault(item.page, []).append(item)
    lines = [line for page_no in sorted(by_page) for line in normalize_lines(page_no, by_page[page_no], header.currency)]
    return header, lines


def check_totals(header: InvoiceHeader, lines: list[Line]) -> list[str]:
    """Problems with the arithmetic: sum(line amounts) + tax == total, and == subtotal when printed. A missing
    tax line counts as zero tax (tax-exempt invoices print none)."""
    if header.currency is None:
        return ["no valid currency, so amounts can't be checked"]
    fmt = lambda minor: format_minor(minor, header.currency)  # noqa: E731
    if header.total_minor is None:
        return ["no total extracted"]
    if not lines:
        return ["no line items extracted"]
    unusable = [f"page {line.page_no} line {line.line_no}" for line in lines if line.amount_minor is None]
    if unusable:
        return [f"lines without a usable amount: {', '.join(unusable)}"]

    problems = []
    lines_sum = sum(line.amount_minor for line in lines)
    tax = header.tax_minor or 0
    if abs(lines_sum + tax - header.total_minor) > TOLERANCE_MINOR:
        problems.append(
            f"line amounts sum to {fmt(lines_sum)}, plus tax {fmt(tax)} makes {fmt(lines_sum + tax)}, "
            f"but the total is {fmt(header.total_minor)}"
        )
    if header.subtotal_minor is not None and abs(lines_sum - header.subtotal_minor) > TOLERANCE_MINOR:
        problems.append(f"line amounts sum to {fmt(lines_sum)}, but the subtotal is {fmt(header.subtotal_minor)}")
    return problems


def needs_repair(page_statuses: list[str], problems: list[str], repair_attempted: bool) -> bool:
    """One repair call, and only when every page was read: with a page missing the sum is expected to be off."""
    return bool(problems) and not repair_attempted and "failed" not in page_statuses


def decide_status(page_statuses: list[str], problems: list[str]) -> str:
    """failed > partially_extracted > exception > extracted."""
    if "extracted" not in page_statuses:
        return "failed"
    if "failed" in page_statuses:
        return "partially_extracted"
    if problems:
        return "exception"
    return "extracted"
