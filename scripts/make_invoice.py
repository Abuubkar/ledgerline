"""Render sample invoice PDFs plus their gold JSON (the exact values printed), so extraction has real input.

The gold file is the template input, so it is correct by construction. Slice 6 grows this into the golden set.
Usage:
  uv run python scripts/make_invoice.py [out_dir]                      # the 3 fixed samples
  uv run python scripts/make_invoice.py --random 200 --seed 7 out_dir  # 200 varied, unique invoices
  uv run python scripts/make_invoice.py --scenarios out_dir            # slice 3b edge cases (see SCENARIOS)
  uv run python scripts/make_invoice.py --from-po 4500000042 out_dir   # bills a PO from data/erp/dataset.json
      [--price-change 3]                                               # ...with line 1 priced 3% above the PO
"""

import argparse
import json
import random
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
    # "single": one page. "dense-middle" / "blank-middle": three pages, lines split over pages 1 and 3, with a
    # page of dense fine print or a blank page in between.
    layout: str = "single"
    total_misprint_minor: int = 0  # printed total = true total + this, to test the arithmetic check
    scanned: bool = False  # image-only PDF of the rendered page, rotated 2 degrees, no text layer
    po_number: str | None = None  # printed as "PO number" when set


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


def _header(pdf: FPDF, sample: Sample) -> None:
    pdf.set_font("helvetica", style="B", size=16)
    pdf.cell(0, 8, sample.vendor_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    for line in [*sample.vendor_address, f"{sample.vendor_tax_label}: {sample.vendor_tax_id_printed}"]:
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("helvetica", style="B", size=12)
    pdf.cell(0, 7, "INVOICE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    rows = [
        ("Invoice number", sample.invoice_number),
        ("Invoice date", sample.invoice_date_printed),
        ("Due date", sample.due_date_printed),
    ]
    if sample.po_number:
        rows.append(("PO number", sample.po_number))
    for label, value in rows:
        pdf.cell(40, 6, label)
        pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("helvetica", style="B", size=10)
    pdf.cell(0, 6, "Bill to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    for line in sample.buyer:
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)


def _lines_table(pdf: FPDF, sample: Sample, lines: list[Line]) -> None:
    pdf.set_font("helvetica", size=10)
    with pdf.table(col_widths=(90, 20, 40, 40), text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT")) as table:
        table.row(["Description", "Qty", f"Unit price ({sample.currency})", f"Amount ({sample.currency})"])
        for line in lines:
            table.row([
                line.description,
                str(line.quantity),
                fmt(line.unit_price_minor, sample),
                fmt(line.quantity * line.unit_price_minor, sample),
            ])


def _totals(pdf: FPDF, sample: Sample) -> None:
    subtotal, tax, total = totals(sample)
    pdf.ln(4)
    for label, minor, bold in [
        ("Subtotal", subtotal, False),
        (f"Tax ({sample.tax_rate_pct}%)", tax, False),
        ("Total due", total + sample.total_misprint_minor, True),
    ]:
        pdf.set_font("helvetica", style="B" if bold else "", size=10)
        pdf.cell(150, 6, label, align="R")
        pdf.cell(40, 6, f"{sample.currency} {fmt(minor, sample)}", align="R", new_x="LMARGIN", new_y="NEXT")


def _fine_print(pdf: FPDF) -> None:
    # A page of dense terms: more text than fits the model's context window, a realistic page-level failure.
    clause = ("The supplier warrants that all goods delivered under this invoice conform to the agreed "
              "specifications, are free from defects in material and workmanship, and comply with applicable law. ")
    pdf.set_auto_page_break(False)
    pdf.set_font("helvetica", size=3.5)
    pdf.set_xy(8, 8)
    pdf.multi_cell(194, 1.25, clause * 260)
    pdf.set_auto_page_break(True)


def _new_pdf() -> FPDF:
    pdf = FPDF()
    # A fixed date keeps regenerated PDFs byte-identical, so rerunning the script never shows up as a git diff.
    pdf.set_creation_date(FIXED_CREATION_DATE)
    return pdf


def render_bytes(sample: Sample) -> bytes:
    pdf = _new_pdf()
    pdf.add_page()
    _header(pdf, sample)
    if sample.layout == "single":
        _lines_table(pdf, sample, sample.lines)
        _totals(pdf, sample)
    else:
        half = max(1, len(sample.lines) // 2)
        _lines_table(pdf, sample, sample.lines[:half])
        pdf.add_page()
        if sample.layout == "dense-middle":
            _fine_print(pdf)
        pdf.add_page()
        pdf.set_font("helvetica", size=9)
        pdf.cell(0, 6, f"{sample.vendor_name} - invoice {sample.invoice_number} (continued)", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        _lines_table(pdf, sample, sample.lines[half:])
        _totals(pdf, sample)
    return bytes(pdf.output())


def _as_scan(pdf_bytes: bytes) -> bytes:
    """Rasterize the first page and put the picture, slightly rotated, in a PDF with no text layer."""
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as source:
        image = source.pages[0].to_image(resolution=150).original.rotate(2, expand=True, fillcolor="white")
    scan = _new_pdf()
    scan.add_page()
    scan.image(image, x=0, y=0, w=210)
    return bytes(scan.output())


def render(sample: Sample, path: Path) -> None:
    content = render_bytes(sample)
    path.write_bytes(_as_scan(content) if sample.scanned else content)


def gold(sample: Sample) -> dict:
    subtotal, tax, total = totals(sample)
    return {
        "vendor_name": sample.vendor_name,
        "vendor_tax_id": sample.vendor_tax_id,
        "invoice_number": sample.invoice_number,
        "po_number": sample.po_number,
        "invoice_date": sample.invoice_date,
        "due_date": sample.due_date,
        "currency": sample.currency,
        "subtotal_minor": subtotal,
        "tax_minor": tax,
        "total_minor": total + sample.total_misprint_minor,
        "arithmetic_error": sample.total_misprint_minor != 0,
        "layout": sample.layout,
        "scanned": sample.scanned,
    }


VENDORS = [
    ("Brightline Office Supply LLC", "EIN", "84-1937465", "USD", 8),
    ("Nordwerk Industrietechnik GmbH", "USt-IdNr.", "DE 274 918 365", "EUR", 19),
    ("Harbourside Catering Ltd", "VAT No.", "GB 482 1937 56", "GBP", 20),
    ("Kawasemi Electronics K.K.", "Registration No.", "T9876543210987", "JPY", 10),
    ("Alpenblick Logistik AG", "MWST-Nr.", "CHE-123.456.789", "CHF", 8),
    ("Pacific Rim Packaging Inc.", "EIN", "91-2846573", "USD", 8),
]
ITEMS = [
    "Laser printer toner, black", "A4 copy paper, 5 reams", "Ergonomic office chair", "USB-C docking station",
    "Pallet wrap film, 500 m", "Industrial shelving bracket", "Safety goggles, anti-fog", "Cable ties, pack of 1000",
    "Thermal labels 100x150", "Hand truck, folding", "LED panel light 60x60", "Server rack screws, M6",
]


def random_sample(rng: random.Random, index: int, tag: str) -> Sample:
    """A varied invoice whose text is unique to (tag, index), so duplicate detection never fires by accident."""
    name, tax_label, tax_printed, currency, rate = rng.choice(VENDORS)
    exponent = 0 if currency == "JPY" else 2
    day = rng.randint(1, 28)
    month = rng.randint(1, 9)
    lines = [
        Line(rng.choice(ITEMS), rng.randint(1, 20), rng.randint(1, 500) * (100 if exponent == 0 else 1) * rng.choice([99, 100, 150]))
        for _ in range(rng.randint(1, 4))
    ]
    return Sample(
        slug=f"{tag}-{index:04d}",
        vendor_name=name,
        vendor_address=["Generated test vendor", f"Unit {rng.randint(1, 999)}"],
        vendor_tax_label=tax_label,
        vendor_tax_id_printed=tax_printed,
        vendor_tax_id="".join(c for c in tax_printed.upper() if c.isalnum()),
        buyer=["Ledgerline Demo Corp", "88 Market Street", "San Francisco, CA 94105"],
        invoice_number=f"{tag.upper()}-{index:05d}",
        invoice_date=f"2026-{month:02d}-{day:02d}",
        invoice_date_printed=f"2026-{month:02d}-{day:02d}",
        due_date=f"2026-{month + 1:02d}-{day:02d}",
        due_date_printed=f"2026-{month + 1:02d}-{day:02d}",
        currency=currency,
        exponent=exponent,
        tax_rate_pct=rate,
        lines=lines,
    )


def scenarios() -> list[Sample]:
    """The slice 3b edge cases, built from the fixed samples so their content is known."""
    from dataclasses import replace

    acme, northwind, sakura = SAMPLES
    more = [Line("Spare blades, pack of 10", 3, 1250), Line("Carry case", 1, 3400)]
    return [
        replace(northwind, slug="scenario-dense-middle", invoice_number="NW-48300",
                layout="dense-middle", lines=northwind.lines + more),
        replace(acme, slug="scenario-blank-middle", invoice_number="RE-2026-0930",
                layout="blank-middle", lines=acme.lines + more),
        replace(sakura, slug="scenario-misprinted-total", invoice_number="SK-2026-1101-01",
                total_misprint_minor=10000),  # printed total is 10,000 yen too high
        replace(northwind, slug="scenario-scanned", invoice_number="NW-48301", scanned=True),
    ]


def from_purchase_order(po_number: str, dataset: Path, tag: str, price_change_pct: int) -> Sample:
    """An invoice billing the whole purchase order as the ERP mock serves it, at the PO's prices."""
    from decimal import Decimal

    order = next(o for o in json.loads(dataset.read_text())["purchase_orders"] if o["po_number"] == po_number)
    exponent = 0 if order["currency"] == "JPY" else 2
    lines = [Line(line["description"], int(line["quantity"]), int(Decimal(line["unit_price"]).scaleb(exponent)))
             for line in order["lines"]]
    lines[0].unit_price_minor = lines[0].unit_price_minor * (100 + price_change_pct) // 100
    tax_id = order["vendor"]["tax_id"]
    return Sample(
        slug=f"{tag}-{po_number}", vendor_name=order["vendor"]["name"], vendor_address=["Generated from an ERP purchase order"],
        vendor_tax_label="VAT No." if tax_id else "Ref.", vendor_tax_id_printed=tax_id or "-", vendor_tax_id=tax_id or "",
        buyer=["Ledgerline Demo Corp", "88 Market Street", "San Francisco, CA 94105"],
        invoice_number=f"{tag.upper()}-{po_number}", invoice_date="2026-10-28", invoice_date_printed="2026-10-28",
        due_date="2026-11-27", due_date_printed="2026-11-27", currency=order["currency"], exponent=exponent,
        tax_rate_pct=10, lines=lines, po_number=f"PO {po_number}",
    )


def write(sample: Sample, out: Path) -> None:
    render(sample, out / f"{sample.slug}.pdf")
    (out / f"{sample.slug}.json").write_text(json.dumps(gold(sample), indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", nargs="?", default="samples")
    parser.add_argument("--random", type=int, default=0, help="generate this many random invoices instead")
    parser.add_argument("--seed", default="1", help="any string; the same seed gives the same invoices")
    parser.add_argument("--tag", default="gen", help="prefix for file names and invoice numbers")
    parser.add_argument("--scenarios", action="store_true", help="write the slice 3b edge cases instead")
    parser.add_argument("--from-po", help="write one invoice billing this purchase order instead")
    parser.add_argument("--dataset", type=Path, default=Path("data/erp/dataset.json"))
    parser.add_argument("--price-change", type=int, default=0, help="percent added to line 1's unit price")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.from_po:
        samples = [from_purchase_order(args.from_po, args.dataset, args.tag, args.price_change)]
    elif args.scenarios:
        samples = scenarios()
    elif args.random:
        samples = [random_sample(random.Random(f"{args.seed}-{i}"), i, args.tag) for i in range(args.random)]
    else:
        samples = SAMPLES
    for sample in samples:
        write(sample, out)
    print(f"wrote {len(samples)} invoice(s) to {out}/")


if __name__ == "__main__":
    main()
