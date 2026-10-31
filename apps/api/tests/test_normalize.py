from datetime import date

from ledgerline_api.normalize import ExtractedHeader, normalize_header, normalize_tax_id


def extracted(**overrides) -> ExtractedHeader:
    fields = dict(
        vendor_name="ACME Tools GmbH",
        vendor_tax_id="DE 123.456.789",
        invoice_number="INV-2026-0042",
        po_number="PO 4500012345",
        invoice_date="2026-09-03",
        due_date="2026-10-03",
        currency="eur",
        subtotal="39.00",
        tax="7.41",
        total="46.41",
        field_confidence={"total": 0.98},
    )
    return ExtractedHeader(**(fields | overrides))


def test_clean_header_is_typed_and_in_minor_units():
    header = normalize_header(extracted())
    assert header.vendor_tax_id == "DE123456789"
    assert header.invoice_date == date(2026, 9, 3)
    assert header.currency == "EUR"
    assert (header.subtotal_minor, header.tax_minor, header.total_minor) == (3900, 741, 4641)
    assert header.invalid_fields == {}


def test_tax_ids_keep_country_prefix_and_drop_separators():
    assert normalize_tax_id("gb 123 4567 89") == "GB123456789"
    assert normalize_tax_id("12-3456789") == "123456789"


def test_non_iso_date_is_flagged_not_guessed():
    header = normalize_header(extracted(invoice_date="03/09/2026"))
    assert header.invoice_date is None
    assert "invoice_date" in header.invalid_fields


def test_amounts_need_a_valid_currency():
    header = normalize_header(extracted(currency="dollars"))
    assert header.currency is None
    assert header.total_minor is None
    assert set(header.invalid_fields) == {"currency", "subtotal", "tax", "total"}


def test_blank_strings_count_as_missing():
    header = normalize_header(extracted(vendor_tax_id="  ", due_date=""))
    assert header.vendor_tax_id is None
    assert header.due_date is None
    assert header.invalid_fields == {}
