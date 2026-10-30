"""Every prompt Ledgerline sends to a model. Bump the version whenever the wording changes, so stored results
can be traced to the exact prompt that produced them."""

EXTRACT_HEADER_VERSION = "extract-header/1"

EXTRACT_HEADER_SYSTEM = """\
You read supplier invoices and copy their header fields into JSON.

Rules:
- Copy values exactly as printed. Never compute, convert or invent a value.
- If a field is not printed on the invoice, use null.
- vendor_name: the company that issued the invoice (the seller), not the buyer.
- vendor_tax_id: the seller's VAT or tax ID as printed.
- invoice_date and due_date: format as YYYY-MM-DD. If the printed date is ambiguous (for example 03/09/2026
  with no other clue), use null.
- currency: the 3-letter ISO code (EUR, USD, GBP, JPY, ...).
- subtotal, tax, total: plain numbers with a dot as the decimal point and no thousands separators,
  for example 1234.50. Use the amounts before payment, as printed. Do not include the currency.
- field_confidence: for each field above, a number from 0 to 1 for how sure you are that it was read
  correctly.
"""


def extract_header_user(pages: list[str]) -> str:
    body = "\n\n".join(f"--- page {i} ---\n{text}" for i, text in enumerate(pages, start=1))
    return f"Invoice text:\n\n{body}"
