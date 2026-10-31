from decimal import Decimal

from ledgerline_api.matching import Billed, BilledLine, Order, OrderLine, match
from ledgerline_api.normalize import po_number_key

TOLERANCE = Decimal("1")
VENDOR = "vendor-1"


def order(**changes) -> Order:
    lines = [OrderLine(1, "Torque wrench 40-200 Nm", Decimal(4), Decimal("89.50")),
             OrderLine(2, "Socket set 1/2 inch", Decimal(2), Decimal("124.00"))]
    return Order(**({"po_number": "4500012345", "vendor_id": VENDOR, "currency": "EUR", "lines": lines} | changes))


def invoice(*lines: BilledLine, **changes) -> Billed:
    lines = lines or (BilledLine("page 1 line 1", "Torque wrench 40-200 Nm", Decimal(4), Decimal("89.50")),
                      BilledLine("page 1 line 2", "Socket set 1/2 inch", Decimal(2), Decimal("124.00")))
    return Billed(**({"po_number": "PO 4500012345", "vendor_id": VENDOR, "currency": "EUR", "lines": list(lines)} | changes))


FULLY_RECEIVED = {1: Decimal(4), 2: Decimal(2)}


def codes(reasons) -> list[str]:
    return [r.code for r in reasons]


def test_invoice_matching_po_and_receipts_has_no_reasons():
    assert match(invoice(), order(), FULLY_RECEIVED, TOLERANCE) == []


def test_descriptions_match_ignoring_case_punctuation_and_spacing():
    billed = invoice(BilledLine("p1 l1", "TORQUE WRENCH 40–200 Nm.", Decimal(4), Decimal("89.50")))
    assert match(billed, order(), {1: Decimal(4)}, TOLERANCE) == []


def test_price_within_one_percent_matches_and_just_over_does_not():
    within = invoice(BilledLine("p1 l1", "Torque wrench 40-200 Nm", Decimal(4), Decimal("90.395")))  # +1.00%
    over = invoice(BilledLine("p1 l1", "Torque wrench 40-200 Nm", Decimal(4), Decimal("90.40")))  # +1.006%
    assert match(within, order(), FULLY_RECEIVED, TOLERANCE) == []
    reasons = match(over, order(), FULLY_RECEIVED, TOLERANCE)
    assert codes(reasons) == ["price_variance"]
    assert reasons[0].line == "p1 l1" and "+1.01%" in reasons[0].detail


def test_price_below_the_po_counts_too():
    cheaper = invoice(BilledLine("p1 l1", "Torque wrench 40-200 Nm", Decimal(4), Decimal("85.00")))
    assert codes(match(cheaper, order(), FULLY_RECEIVED, TOLERANCE)) == ["price_variance"]


def test_short_shipment_when_less_was_received_than_billed():
    reasons = match(invoice(), order(), {1: Decimal(3), 2: Decimal(2)}, TOLERANCE)
    assert codes(reasons) == ["short_shipment"]
    assert reasons[0].detail == "billed 4, received 3" and reasons[0].line == "page 1 line 1"


def test_quantity_must_equal_received_exactly():
    reasons = match(invoice(), order(), {1: Decimal(4), 2: Decimal(3)}, TOLERANCE)
    assert codes(reasons) == ["quantity_mismatch"]


def test_receipts_add_up_over_po_lines_never_received():
    # Line 2 has no receipt line at all: received 0.
    assert codes(match(invoice(), order(), {1: Decimal(4)}, TOLERANCE)) == ["short_shipment"]


def test_po_without_any_receipt_is_not_received():
    assert codes(match(invoice(), order(), None, TOLERANCE)) == ["not_received"]


def test_missing_po_number_and_unknown_po():
    assert codes(match(invoice(po_number=None), None, None, TOLERANCE)) == ["po_missing"]
    assert codes(match(invoice(), None, None, TOLERANCE)) == ["po_not_found"]


def test_line_not_on_po_and_billing_more_than_ordered():
    extra = BilledLine("page 1 line 3", "Gift basket", Decimal(1), Decimal("20.00"))
    over = BilledLine("page 1 line 1", "Torque wrench 40-200 Nm", Decimal(5), Decimal("89.50"))
    reasons = match(invoice(over, extra), order(), {1: Decimal(5)}, TOLERANCE)
    assert codes(reasons) == ["quantity_over_po", "line_not_on_po"]


def test_each_po_line_is_billed_once():
    same = BilledLine("page 1 line 1", "Torque wrench 40-200 Nm", Decimal(4), Decimal("89.50"))
    again = BilledLine("page 2 line 1", "Torque wrench 40-200 Nm", Decimal(4), Decimal("89.50"))
    assert codes(match(invoice(same, again), order(), FULLY_RECEIVED, TOLERANCE)) == ["line_not_on_po"]


def test_other_vendor_or_currency():
    assert codes(match(invoice(vendor_id="vendor-2"), order(), FULLY_RECEIVED, TOLERANCE)) == ["vendor_mismatch"]
    # Prices in different currencies aren't compared at all.
    assert codes(match(invoice(currency="USD"), order(), FULLY_RECEIVED, TOLERANCE)) == ["currency_mismatch"]


def test_unreadable_line_is_a_reason_not_a_guess():
    broken = BilledLine("page 1 line 1", "Torque wrench 40-200 Nm", None, Decimal("89.50"), "quantity: not a number")
    assert codes(match(invoice(broken), order(), FULLY_RECEIVED, TOLERANCE)) == ["line_unreadable"]


def test_po_number_key_ignores_prefix_words_separators_and_leading_zeros():
    assert {po_number_key(raw) for raw in ["4500012345", "PO 4500012345", "P.O. No. 4500012345", "po-04500012345",
                                           "Purchase Order: 4500012345", "Bestellung Nr. 4500012345"]} == {"4500012345"}
    assert po_number_key("PO-2026-17") != po_number_key("PO-2026-71")
    assert po_number_key(None) is None and po_number_key("P.O.") is None
