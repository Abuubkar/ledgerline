"""The 3-way match: what the invoice bills, against what the purchase order ordered and what goods receipts say
arrived. Deterministic rules on plain data; match_invoice (jobs.py) loads the rows and stores the result.

Per invoice line: the PO line with the same description, a unit price within the tolerance of the PO price,
and a billed quantity exactly equal to the quantity received. Any failed rule is a reason, and any reason
sends the invoice to `exception` for a person (later the agent) to resolve.
"""

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class OrderLine:
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal


@dataclass
class Order:
    po_number: str
    vendor_id: object
    currency: str
    lines: list[OrderLine]


@dataclass
class BilledLine:
    label: str  # "page 1 line 2", how a person finds it on the invoice
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    invalid_reason: str | None = None


@dataclass
class Billed:
    po_number: str | None
    vendor_id: object
    currency: str | None
    lines: list[BilledLine]


@dataclass
class Reason:
    code: str
    detail: str
    line: str | None = None


def description_key(text: str) -> str:
    """Descriptions match when they differ only in case, punctuation or spacing."""
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def _num(value: Decimal) -> str:
    return format(value.normalize(), "f")


def match(invoice: Billed, order: Order | None, received: dict[int, Decimal] | None,
          price_tolerance_pct: Decimal) -> list[Reason]:
    """Why the invoice doesn't match; an empty list means it matches. `received` is the quantity received per
    PO line number over all goods receipts, or None when the PO has no receipt at all."""
    if invoice.po_number is None:
        return [Reason("po_missing", "the invoice cites no purchase order number")]
    if order is None:
        return [Reason("po_not_found", f"no purchase order {invoice.po_number} in the ERP data")]

    reasons = []
    if invoice.vendor_id != order.vendor_id:
        reasons.append(Reason("vendor_mismatch", f"PO {order.po_number} was issued to a different vendor"))
    if invoice.currency != order.currency:
        reasons.append(Reason("currency_mismatch", f"invoice is in {invoice.currency}, PO in {order.currency}"))
        return reasons  # prices in different currencies can't be compared
    if received is None:
        reasons.append(Reason("not_received", f"no goods receipt for PO {order.po_number}"))
    if not invoice.lines:
        reasons.append(Reason("no_lines", "the invoice has no line items to match"))

    unused = list(order.lines)
    for line in invoice.lines:
        if line.invalid_reason or line.description is None or line.quantity is None or line.unit_price is None:
            reasons.append(Reason("line_unreadable", line.invalid_reason or "description, quantity or unit price missing",
                                  line.label))
            continue
        key = description_key(line.description)
        po_line = next((candidate for candidate in unused if description_key(candidate.description) == key), None)
        if po_line is None:
            reasons.append(Reason("line_not_on_po", f"{line.description!r} is not on PO {order.po_number}", line.label))
            continue
        unused.remove(po_line)

        if abs(line.unit_price - po_line.unit_price) * 100 > po_line.unit_price * price_tolerance_pct:
            change = (line.unit_price - po_line.unit_price) / po_line.unit_price * 100
            reasons.append(Reason(
                "price_variance",
                f"unit price {_num(line.unit_price)} vs PO {_num(po_line.unit_price)} ({change:+.2f}%, "
                f"tolerance {_num(price_tolerance_pct)}%)", line.label,
            ))
        if line.quantity > po_line.quantity:
            reasons.append(Reason("quantity_over_po", f"billed {_num(line.quantity)}, ordered {_num(po_line.quantity)}",
                                  line.label))
        if received is not None:
            got = received.get(po_line.line_no, Decimal(0))
            if got < line.quantity:
                reasons.append(Reason("short_shipment", f"billed {_num(line.quantity)}, received {_num(got)}", line.label))
            elif got > line.quantity:
                reasons.append(Reason("quantity_mismatch", f"billed {_num(line.quantity)}, received {_num(got)}",
                                      line.label))
    return reasons
