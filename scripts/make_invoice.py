"""Render sample invoice PDFs plus their gold JSON (the exact values printed), so extraction has real input.

The gold file is the template input, so it is correct by construction. Slice 6 grows this into the golden set.
Usage: uv run python scripts/make_invoice.py [out_dir]
"""

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF


@dataclass
class Line:
    description: str
    quantity: int
    unit_price_minor: int


@dataclass
class Sample:
    slug: str
    vendor_name: str
    vendor_address: list[str]
    vendor_tax_label: str
    vendor_tax_id_printed: str
    vendor_tax_id: str  # normalized form, as stored
    buyer: list[str]
    invoice_number: str
    invoice_date: str  # ISO, for the gold file
    invoice_date_printed: str
    due_date: str
    due_date_printed: str
    currency: str
    exponent: int
    tax_rate_pct: int
    lines: list[Line]


def fmt(minor: int, sample: Sample) -> str:
    # Core PDF fonts only cover Latin-1, so currency symbols like the euro and yen signs are avoided;
    # invoices print the ISO code instead (see docs/adr/0002).
    units, cents = divmod(minor, 10**sample.exponent) if sample.exponent else (minor, 0)
    text = f"{units:,}"
    return f"{text}.{cents:0{sample.exponent}d}" if sample.exponent else text


FIXED_CREATION_DATE = datetime(2026, 10, 30, tzinfo=UTC)

SAMPLES = [
    Sample(
        slug="inv-001",
        vendor_name="ACME Werkzeuge GmbH",
        vendor_address=["Industriestrasse 12", "70565 Stuttgart", "Germany"],
        vendor_tax_label="USt-IdNr.",
        vendor_tax_id_printed="DE 812 345 678",
        vendor_tax_id="DE812345678",
        buyer=["Northbridge Retail Ltd", "4 Canal Street", "Manchester M1 3HE"],
        invoice_number="RE-2026-0915",
        invoice_date="2026-09-15",
        invoice_date_printed="15.09.2026",
        due_date="2026-10-15",
        due_date_printed="15.10.2026",
        currency="EUR",
        exponent=2,
        tax_rate_pct=19,
        lines=[Line("Torque wrench 40-200 Nm", 4, 8950), Line("Socket set 1/2 inch, 24 pcs", 2, 12400)],
    ),
    Sample(
        slug="inv-002",
        vendor_name="Northwind Supplies Inc.",
        vendor_address=["1200 Harbor Blvd, Suite 300", "Oakland, CA 94607", "USA"],
        vendor_tax_label="EIN",
        vendor_tax_id_printed="94-3216549",
        vendor_tax_id="943216549",
        buyer=["Ledgerline Demo Corp", "88 Market Street", "San Francisco, CA 94105"],
        invoice_number="NW-48213",
        invoice_date="2026-10-02",
        invoice_date_printed="October 2, 2026",
        due_date="2026-11-01",
        due_date_printed="November 1, 2026 (Net 30)",
        currency="USD",
        exponent=2,
        tax_rate_pct=8,
        lines=[
            Line("Warehouse shelving unit, steel", 6, 18999),
            Line("Pallet jack, 5500 lb", 1, 64900),
            Line("Safety gloves (box of 100)", 10, 1450),
        ],
    ),
    Sample(
        slug="inv-003",
        vendor_name="Sakura Components K.K.",
        vendor_address=["2-14-5 Shibaura, Minato-ku", "Tokyo 108-0023", "Japan"],
        vendor_tax_label="Registration No.",
        vendor_tax_id_printed="T1234567890123",
        vendor_tax_id="T1234567890123",
        buyer=["Ledgerline Demo Corp", "88 Market Street", "San Francisco, CA 94105"],
        invoice_number="SK-2026-1020-07",
        invoice_date="2026-10-20",
        invoice_date_printed="2026-10-20",
        due_date="2026-11-30",
        due_date_printed="2026-11-30",
        currency="JPY",
        exponent=0,
        tax_rate_pct=10,
        lines=[Line("Stepper motor NEMA 17", 20, 3800), Line("Motor driver board", 20, 2450)],
    ),
]


def totals(sample: Sample) -> tuple[int, int, int]:
    subtotal = sum(line.quantity * line.unit_price_minor for line in sample.lines)
    tax = subtotal * sample.tax_rate_pct // 100
    return subtotal, tax, subtotal + tax


def render(sample: Sample, path: Path) -> None:
    subtotal, tax, total = totals(sample)
    pdf = FPDF()
    # A fixed date keeps regenerated PDFs byte-identical, so rerunning the script never shows up as a git diff.
    pdf.set_creation_date(FIXED_CREATION_DATE)
    pdf.add_page()

    pdf.set_font("helvetica", style="B", size=16)
    pdf.cell(0, 8, sample.vendor_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    for line in [*sample.vendor_address, f"{sample.vendor_tax_label}: {sample.vendor_tax_id_printed}"]:
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("helvetica", style="B", size=12)
    pdf.cell(0, 7, "INVOICE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    for label, value in [
        ("Invoice number", sample.invoice_number),
        ("Invoice date", sample.invoice_date_printed),
        ("Due date", sample.due_date_printed),
    ]:
        pdf.cell(40, 6, label)
        pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("helvetica", style="B", size=10)
    pdf.cell(0, 6, "Bill to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    for line in sample.buyer:
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    with pdf.table(col_widths=(90, 20, 40, 40), text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT")) as table:
        table.row(["Description", "Qty", f"Unit price ({sample.currency})", f"Amount ({sample.currency})"])
        for line in sample.lines:
            table.row([
                line.description,
                str(line.quantity),
                fmt(line.unit_price_minor, sample),
                fmt(line.quantity * line.unit_price_minor, sample),
            ])

    pdf.ln(4)
    for label, minor, bold in [
        ("Subtotal", subtotal, False),
        (f"Tax ({sample.tax_rate_pct}%)", tax, False),
        ("Total due", total, True),
    ]:
        pdf.set_font("helvetica", style="B" if bold else "", size=10)
        pdf.cell(150, 6, label, align="R")
        pdf.cell(40, 6, f"{sample.currency} {fmt(minor, sample)}", align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(path))


def gold(sample: Sample) -> dict:
    subtotal, tax, total = totals(sample)
    return {
        "vendor_name": sample.vendor_name,
        "vendor_tax_id": sample.vendor_tax_id,
        "invoice_number": sample.invoice_number,
        "invoice_date": sample.invoice_date,
        "due_date": sample.due_date,
        "currency": sample.currency,
        "subtotal_minor": subtotal,
        "tax_minor": tax,
        "total_minor": total,
    }


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    out.mkdir(parents=True, exist_ok=True)
    for sample in SAMPLES:
        render(sample, out / f"{sample.slug}.pdf")
        (out / f"{sample.slug}.json").write_text(json.dumps(gold(sample), indent=2) + "\n")
        print(f"wrote {out / sample.slug}.pdf and .json")


if __name__ == "__main__":
    main()
