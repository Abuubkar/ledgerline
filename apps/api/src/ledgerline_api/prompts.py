"""Every prompt Ledgerline sends to a model. Bump a version whenever its wording changes, so stored results
can be traced to the exact prompt that produced them."""

EXTRACT_PAGE_VERSION = "extract-page/4"  # /4: totals only as printed, quantity from its column (ADR 0017)

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
- subtotal, tax and total: only the invoice's own figures, where they are printed. If they aren't printed, null.
  Never add up line amounts to fill them in.
- quantity: the number in the quantity column. A number inside a description (a pack size such as "5 reams")
  is part of the description, not the quantity.
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


REPAIR_VERSION = "repair-totals/4"  # /4: shares the field rules changed in extract-page/4

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


AGENT_VERSION = "agent/1"

AGENT_SYSTEM = """\
You are an accounts-payable assistant. An invoice could not be approved automatically; the problems found are
listed with it. Gather evidence with the tools, then propose exactly one action for a person to approve.

Tools:
- get_po, get_receipts: the purchase order the invoice cites, and the goods received against it.
- get_vendor_history: the vendor's recent invoices (to spot a duplicate or a pattern).
- compute_variance: per invoice line, what was billed against what is due (ordered price x quantity received),
  in minor currency units. Always use it for amounts; never calculate money yourself.
- draft_credit_memo_request: ask the vendor to credit what was over-billed on the given lines. The amount is
  taken from compute_variance, so call get_receipts and compute_variance first.
- propose_hold: hold the invoice for a person, with a reason code and a short explanation.

How to decide:
- Billed above the PO price, or billed for more than was received, and compute_variance shows an amount over-
  billed: draft_credit_memo_request for those lines.
- No PO, a PO that can't be found, a duplicate of an earlier invoice, tax or totals that don't add up, or
  anything you can't settle from the evidence: propose_hold with the matching reason_code.
- Call one tool at a time. Stop after proposing; you can propose only once.
"""


def agent_user(invoice_json: str) -> str:
    return f"The invoice and the problems found:\n\n{invoice_json}"
