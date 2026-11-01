from datetime import date
from decimal import Decimal

import pytest

from ledgerline_api.extraction import looks_truncated, prompt_too_long
from ledgerline_api.normalize import (
    ExtractedLine,
    ExtractedPage,
    InvoiceHeader,
    Line,
    check_totals,
    decide_status,
    invoice_number_key,
    merge_pages,
    needs_repair,
    normalize_lines,
    vendor_name_key,
)


def page(**fields) -> ExtractedPage:
    base = dict(
        vendor_name=None, vendor_tax_id=None, invoice_number=None, po_number=None, invoice_date=None, due_date=None,
        currency=None, subtotal=None, tax=None, total=None, field_confidence={}, line_items=[],
    )
    return ExtractedPage(**(base | fields))


def item(description="Widget", quantity="2", unit_price="10.00", amount="20.00") -> ExtractedLine:
    return ExtractedLine(description=description, quantity=quantity, unit_price=unit_price, amount=amount)


# --- merging pages -------------------------------------------------------------------------------------


def test_header_fields_are_taken_from_whichever_page_prints_them():
    first = page(vendor_name="ACME GmbH", invoice_number="INV-7", currency="EUR", line_items=[item()],
                 field_confidence={"vendor_name": 0.9})
    last = page(total="26.00", tax="6.00", line_items=[item("Bolt", "1", "0.125", "0.13")])

    header, lines = merge_pages([(1, first), (3, last)])

    assert (header.vendor_name, header.invoice_number, header.currency) == ("ACME GmbH", "INV-7", "EUR")
    # Page 3 prints no currency; its amounts use the one page 1 printed.
    assert (header.total_minor, header.tax_minor) == (2600, 600)
    assert header.field_confidence == {"vendor_name": 0.9}
    assert [(l.page_no, l.line_no, l.amount_minor) for l in lines] == [(1, 1, 2000), (3, 1, 13)]
    assert lines[1].unit_price == Decimal("0.125")  # finer than a cent: kept as a decimal, not money
    assert header.invalid_fields == {}


def test_pages_that_disagree_make_the_field_invalid_instead_of_picking_one():
    header, _ = merge_pages([
        (1, page(invoice_number="INV-7", currency="EUR")),
        (2, page(invoice_number="INV-8", currency="EUR")),
    ])
    assert header.invoice_number is None
    assert "pages disagree" in header.invalid_fields["invoice_number"]


def test_the_same_value_written_differently_is_agreement():
    header, _ = merge_pages([
        (1, page(currency="eur", total="1,000.00", invoice_date="2026-10-01")),
        (2, page(currency="EUR", total="1000.00", invoice_date="2026-10-01")),
    ])
    assert (header.currency, header.total_minor, header.invoice_date) == ("EUR", 100000, date(2026, 10, 1))
    assert header.invalid_fields == {}


def test_a_usable_value_on_one_page_wins_over_an_unusable_one_on_another():
    header, _ = merge_pages([(1, page(invoice_date="03/09/2026")), (2, page(invoice_date="2026-09-03"))])
    assert header.invoice_date == date(2026, 9, 3)
    assert "invoice_date" not in header.invalid_fields


def test_bad_line_values_are_flagged_on_the_line_not_dropped():
    lines = normalize_lines(1, [item(quantity="two", amount="10.005"), item(amount=None)], currency="EUR")
    assert lines[0].quantity is None and lines[0].amount_minor is None
    assert "quantity" in lines[0].invalid_reason and "decimal places" in lines[0].invalid_reason
    assert lines[1].invalid_reason == "amount missing"


# --- totals ---------------------------------------------------------------------------------------------


def header(total=None, tax=None, subtotal=None, currency="EUR") -> InvoiceHeader:
    return InvoiceHeader(currency=currency, total_minor=total, tax_minor=tax, subtotal_minor=subtotal)


def lines_of(*amounts) -> list[Line]:
    return [Line(1, i, "x", Decimal(1), None, a) for i, a in enumerate(amounts, start=1)]


@pytest.mark.parametrize(
    ("hdr", "lines", "problem"),
    [
        (header(total=2600, tax=600, subtotal=2000), lines_of(1500, 500), None),
        (header(total=2601, tax=600), lines_of(2000), None),  # within one minor unit of rounding
        (header(total=2000), lines_of(2000), None),  # no tax line: tax-exempt
        (header(total=2700, tax=600), lines_of(2000), "but the total is 27.00"),
        (header(total=2600, tax=600, subtotal=2100), lines_of(2000), "but the subtotal is 21.00"),
        (header(total=None), lines_of(2000), "no total extracted"),
        (header(total=2000), [], "no line items extracted"),
        (header(total=2000), [Line(2, 1, "x", None, None, None)], "page 2 line 1"),
        (header(total=2000, currency=None), lines_of(2000), "no valid currency"),
    ],
)
def test_totals_check(hdr, lines, problem):
    problems = check_totals(hdr, lines)
    if problem is None:
        assert problems == []
    else:
        assert any(problem in p for p in problems), problems


# --- status and repair ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pages", "problems", "status"),
    [
        (["extracted", "extracted"], [], "extracted"),
        (["extracted", "blank", "extracted"], [], "extracted"),  # blank pages are skipped, not failures
        (["extracted", "extracted"], ["sum is off"], "exception"),
        (["extracted", "failed"], [], "partially_extracted"),
        (["extracted", "failed"], ["sum is off"], "partially_extracted"),  # partial outranks exception
        (["failed", "blank"], [], "failed"),
    ],
)
def test_status_precedence(pages, problems, status):
    assert decide_status(pages, problems) == status


def test_repair_only_once_and_only_when_every_page_was_read():
    assert needs_repair(["extracted", "extracted"], ["sum is off"], repair_attempted=False)
    assert not needs_repair(["extracted", "extracted"], ["sum is off"], repair_attempted=True)
    assert not needs_repair(["extracted", "failed"], ["sum is off"], repair_attempted=False)  # sum expected off
    assert not needs_repair(["extracted", "blank"], [], repair_attempted=False)


# --- prompt size ----------------------------------------------------------------------------------------


def test_prompt_budget_leaves_room_for_the_answer():
    assert not prompt_too_long(text_chars=3_000, image_count=0, num_ctx=8192, reserve=2048)  # a normal page
    assert not prompt_too_long(text_chars=1_000, image_count=1, num_ctx=8192, reserve=2048)  # a scanned page
    assert prompt_too_long(text_chars=40_000, image_count=0, num_ctx=8192, reserve=2048)  # dense fine print


def test_truncation_is_detected_from_measured_ratios():
    # Measured on gemma4:12b with num_ctx 8192: 28,299 chars -> 4,327 tokens (intact);
    # 63,690 chars -> 4,099 tokens (silently truncated).
    assert not looks_truncated(28_299, 0, 4_327, 8192)
    assert looks_truncated(63_690, 0, 4_099, 8192)
    assert looks_truncated(10, 0, 8192, 8192)
    assert not looks_truncated(500, 1, 30, 8192)  # images: ratio meaningless


# --- duplicate keys -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "key"),
    [
        ("INV-0042", "42"),
        (" 42 ", "42"),
        ("inv 042", "42"),
        ("Invoice No. 42", "42"),
        ("RE-2026-0915", "RE-2026-915"),
        ("2026/0915", "2026-915"),
        ("NW-48213", "NW-48213"),
        ("INV-", None),
        (None, None),
    ],
)
def test_invoice_number_key_ignores_formatting(printed, key):
    assert invoice_number_key(printed) == key


def test_letters_inside_the_number_still_count():
    assert invoice_number_key("RE-2026-0915") != invoice_number_key("2026-0915")
    assert invoice_number_key("A-100") != invoice_number_key("B-100")


def test_vendor_name_key_ignores_case_and_punctuation():
    assert vendor_name_key("Northwind Supplies, Inc.") == vendor_name_key("NORTHWIND  supplies inc") == "northwind supplies inc"
    assert vendor_name_key("ACME GmbH") != vendor_name_key("ACME AG")
    assert vendor_name_key("株式会社サクラ") == "株式会社サクラ"  # not every name is Latin
    assert vendor_name_key("Café Lumière") == vendor_name_key("CAFE LUMIERE")
    assert vendor_name_key("ザクラ") != vendor_name_key("サクラ")


# --- reading the model's JSON -------------------------------------------------------------------------


def test_bare_numbers_and_quoted_numbers_both_arrive_as_exact_text():
    from ledgerline_api.extraction import parse_answer

    answer = ('{"vendor_name": "ACME", "vendor_tax_id": null, "invoice_number": "1", "po_number": null, "invoice_date": null,'
              ' "due_date": null, "currency": "EUR", "subtotal": 3572.00, "tax": "678.68", "total": 12345678901234.56,'
              ' "field_confidence": {"total": 0.9}, "line_items": [{"description": "Bracket", "quantity": 16,'
              ' "unit_price": 0.125, "amount": "2.00"}]}')
    page = parse_answer(answer, ExtractedPage)
    assert (page.subtotal, page.tax, page.total) == ("3572.00", "678.68", "12345678901234.56")  # trailing zeros kept, nothing rounded
    line = page.line_items[0]
    assert (line.quantity, line.unit_price, line.amount) == ("16", "0.125", "2.00")
    assert page.field_confidence == {"total": 0.9}


def test_the_schema_sent_to_the_model_allows_both_forms():
    amount = ExtractedPage.model_json_schema()["properties"]["total"]
    assert {"type": "number"} in amount["anyOf"] and {"type": "string"} in amount["anyOf"]
