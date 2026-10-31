"""Every prompt Ledgerline sends to a model. Bump a version whenever its wording changes, so stored results
can be traced to the exact prompt that produced them."""

EXTRACT_PAGE_VERSION = "extract-page/2"

_FIELD_RULES = """\
- Copy values exactly as printed. Never compute, convert or invent a value.
- vendor_name: the company that issued the invoice (the seller), not the buyer.
- vendor_tax_id: the seller's VAT or tax ID as printed.
- po_number: the buyer's purchase order number (PO) the invoice refers to, as printed; null if none is printed.
- invoice_date and due_date: format as YYYY-MM-DD. If the printed date is ambiguous (for example 03/09/2026
  with no other clue), use null.
- currency: the 3-letter ISO code (EUR, USD, GBP, JPY, ...).
- subtotal, tax, total, and each line's quantity, unit_price and amount: plain numbers with a dot as the
  decimal point and no thousands separators, for example 1234.50. Never include a currency code or symbol.
- field_confidence: for each header field, a number from 0 to 1 for how sure you are it was read correctly.
"""

EXTRACT_PAGE_SYSTEM = f"""\
You read one page of a supplier invoice and copy what is printed on that page into JSON.

Rules:
- Only report what is on this page. A header field that is not printed on this page is null; it may be on
  another page.
- line_items: every billed line printed on this page, top to bottom. Not subtotals, tax or totals.
{_FIELD_RULES}"""


def extract_page_user(page_no: int, page_count: int, text: str | None) -> str:
    where = f"This is page {page_no} of {page_count}."
    if text is None:
        return f"{where} The page is attached as an image."
    return f"{where} Its text:\n\n{text}"


REPAIR_VERSION = "repair-totals/2"

REPAIR_SYSTEM = f"""\
You re-read a supplier invoice whose extracted numbers don't add up, and return a corrected extraction of the
whole invoice as JSON.

Rules:
- A check found an inconsistency, described below. Look again at the printed numbers involved.
- If the invoice really prints numbers that don't add up, copy them as printed anyway. Never change a number
  just to make the arithmetic work.
- line_items: every billed line on every page, with the page number it appears on.
{_FIELD_RULES}"""


def repair_user(pages: list[str | None], previous_json: str, violations: list[str]) -> str:
    texts = "\n\n".join(
        f"--- page {i} ---\n{text if text is not None else '(attached as an image)'}"
        for i, text in enumerate(pages, start=1)
    )
    problems = "\n".join(f"- {v}" for v in violations)
    return f"Problems found:\n{problems}\n\nPrevious extraction:\n{previous_json}\n\nThe invoice:\n\n{texts}"
