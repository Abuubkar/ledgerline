"""Render sample invoice PDFs plus their gold JSON (the exact values printed), so extraction has real input.

The gold file is the template input, so it is correct by construction. Slice 6 grows this into the golden set.
Usage:
  uv run python scripts/make_invoice.py [out_dir]                      # the 3 fixed samples
  uv run python scripts/make_invoice.py --random 200 --seed 7 out_dir  # 200 varied, unique invoices
  uv run python scripts/make_invoice.py --scenarios out_dir            # slice 3b edge cases (see SCENARIOS)
  uv run python scripts/make_invoice.py --golden                       # the 60-invoice eval set in evals/golden/
  uv run python scripts/make_invoice.py --from-po 4500000042 out_dir   # bills a PO from data/erp/dataset.json
      [--price-change 3]                                               # ...with line 1 priced 3% above the PO
"""

import argparse
import json
import random
from dataclasses import asdict, dataclass
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
    scanned: bool = False  # image-only PDF of the rendered page, no text layer (how: scan_style)
    scan_style: "ScanStyle | None" = None  # None: the original golden scan (first page, 150 dpi, rotated 2 degrees)
    po_number: str | None = None  # printed as "PO number" when set
    style: str = "classic"  # how the vendor lays out its invoices: see STYLES
    pages: int = 1  # with layout "single": spread the lines over this many pages, totals on the last
    stamp: str | None = None  # text of a rubber stamp drawn across the lines (e.g. "PAID 2026-10-31")


# Six vendor layouts for the golden set. Labels, number format and arrangement differ; what's printed is always
# the same information, so the gold values don't depend on the style.
STYLES = {
    "classic": {"labels": ("Invoice number", "Invoice date", "Due date", "PO number"), "totals": ("Subtotal", "Tax", "Total due"),
                "table": ("Description", "Qty", "Unit price", "Amount"), "decimal_comma": False, "align": "L", "font": 10},
    "german": {"labels": ("Rechnungsnummer", "Rechnungsdatum", "Faellig am", "Bestellnummer"), "totals": ("Zwischensumme", "MwSt.", "Gesamtbetrag"),
               "table": ("Bezeichnung", "Menge", "Einzelpreis", "Betrag"), "decimal_comma": True, "align": "L", "font": 10},
    "right": {"labels": ("Invoice #", "Date", "Payment due", "Your order"), "totals": ("Net", "VAT", "Amount payable"),
              "table": ("Item", "Quantity", "Price each", "Line total"), "decimal_comma": False, "align": "R", "font": 10},
    "boxed": {"labels": ("Invoice No.", "Issued", "Due", "Purchase order"), "totals": ("Sub-total", "Sales tax", "TOTAL"),
              "table": ("Description", "Units", "Rate", "Amount"), "decimal_comma": False, "align": "L", "font": 10, "boxed": True},
    "compact": {"labels": ("Invoice", "Dated", "Pay by", "PO"), "totals": ("Subtotal", "Tax", "Balance due"),
                "table": ("Description", "Qty", "Unit", "Total"), "decimal_comma": False, "align": "L", "font": 8.5, "inline": True},
    "seikyu": {"labels": ("Seikyusho No. (Invoice)", "Hakko-bi (Date)", "Shiharai kigen (Due)", "Chumon No. (PO)"),
               "totals": ("Shokei (Subtotal)", "Shohizei (Tax)", "Gokei (Total)"), "table": ("Hinmei (Item)", "Suryo", "Tanka", "Kingaku"),
               "decimal_comma": False, "align": "L", "font": 10},
}


def fmt(minor: int, sample: Sample) -> str:
    # Core PDF fonts only cover Latin-1, so currency symbols like the euro and yen signs are avoided;
    # invoices print the ISO code instead (see docs/adr/0002).
    units, cents = divmod(minor, 10**sample.exponent) if sample.exponent else (minor, 0)
    text = f"{units:,}"
    text = f"{text}.{cents:0{sample.exponent}d}" if sample.exponent else text
    if STYLES[sample.style]["decimal_comma"]:  # German print: 1.234,50
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


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
    if sample.style != "classic":
        return _styled_header(pdf, sample)
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


def _styled_header(pdf: FPDF, sample: Sample) -> None:
    style = STYLES[sample.style]
    align, size = style["align"], style["font"]
    pdf.set_font("helvetica", style="B", size=size + 6)
    pdf.cell(0, 8, sample.vendor_name, align=align, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=size - 1)
    for line in [*sample.vendor_address, f"{sample.vendor_tax_label}: {sample.vendor_tax_id_printed}"]:
        pdf.cell(0, 5, line, align=align, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    labels = style["labels"]
    rows = [(labels[0], sample.invoice_number), (labels[1], sample.invoice_date_printed), (labels[2], sample.due_date_printed)]
    if sample.po_number:
        rows.append((labels[3], sample.po_number))
    pdf.set_font("helvetica", style="B", size=size + 2)
    pdf.cell(0, 7, "RECHNUNG" if sample.style == "german" else "INVOICE", align=align, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=size)
    if style.get("inline"):  # all on one line, as compact layouts do
        pdf.cell(0, 6, "   ".join(f"{label}: {value}" for label, value in rows), new_x="LMARGIN", new_y="NEXT")
    else:
        for label, value in rows:
            if align == "R":
                pdf.cell(0, 6, f"{label}: {value}", align="R", new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(48, 6, label)
                pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("helvetica", style="B", size=size)
    pdf.cell(0, 6, "Rechnungsempfaenger" if sample.style == "german" else "Bill to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=size)
    for line in sample.buyer:
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)


def _lines_table(pdf: FPDF, sample: Sample, lines: list[Line]) -> None:
    if sample.style != "classic":
        style = STYLES[sample.style]
        pdf.set_font("helvetica", size=style["font"])
        heads = style["table"]
        borders = "ALL" if style.get("boxed") else "HORIZONTAL_LINES"
        with pdf.table(col_widths=(90, 20, 40, 40), text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT"), borders_layout=borders) as table:
            table.row([heads[0], heads[1], f"{heads[2]} ({sample.currency})", f"{heads[3]} ({sample.currency})"])
            for line in lines:
                table.row([line.description, str(line.quantity), fmt(line.unit_price_minor, sample), fmt(line.quantity * line.unit_price_minor, sample)])
        return
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
    names = STYLES[sample.style]["totals"]
    for label, minor, bold in [
        (names[0], subtotal, False),
        (f"{names[1]} ({sample.tax_rate_pct}%)", tax, False),
        (names[2], total + sample.total_misprint_minor, True),
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


def _stamp(pdf: FPDF, text: str) -> None:
    """A red rubber stamp, tilted and see-through, drawn across the line items as a clerk would."""
    x, y = 70, pdf.get_y() - 22
    with pdf.local_context(fill_opacity=0.55, stroke_opacity=0.55):
        pdf.set_draw_color(200, 30, 30)
        pdf.set_text_color(200, 30, 30)
        pdf.set_line_width(1.2)
        with pdf.rotation(14, x=x + 35, y=y + 8):
            pdf.rect(x, y, 70, 16)
            pdf.set_font("helvetica", style="B", size=15)
            pdf.set_xy(x, y + 3)
            pdf.cell(70, 10, text, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)


def _new_pdf() -> FPDF:
    pdf = FPDF()
    # A fixed date keeps regenerated PDFs byte-identical, so rerunning the script never shows up as a git diff.
    pdf.set_creation_date(FIXED_CREATION_DATE)
    return pdf


def render_bytes(sample: Sample) -> bytes:
    pdf = _new_pdf()
    pdf.add_page()
    _header(pdf, sample)
    if sample.layout == "single" and sample.pages > 1:
        # Lines spread over the pages; each continuation page repeats who and which invoice, totals on the last.
        per_page = -(-len(sample.lines) // sample.pages)
        for page in range(sample.pages):
            if page:
                pdf.add_page()
                pdf.set_font("helvetica", size=9)
                pdf.cell(0, 6, f"{sample.vendor_name} - {STYLES[sample.style]['labels'][0]} {sample.invoice_number} - page {page + 1} of {sample.pages}",
                         new_x="LMARGIN", new_y="NEXT")
                pdf.ln(4)
            _lines_table(pdf, sample, sample.lines[page * per_page:(page + 1) * per_page])
            if page == 0 and sample.stamp:
                _stamp(pdf, sample.stamp)
        _totals(pdf, sample)
    elif sample.layout == "single":
        _lines_table(pdf, sample, sample.lines)
        if sample.stamp:
            _stamp(pdf, sample.stamp)
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


@dataclass(frozen=True)
class ScanStyle:
    """How a page looks after a scanner or a fax: what the scans set varies (evals/golden/scans)."""
    angle: float = 2.0  # degrees, counter-clockwise
    dpi: int = 150
    contrast: float = 1.0  # below 1: greyish paper and faded ink
    blur: float = 0.0  # Gaussian blur radius in pixels
    jpeg_quality: int | None = None  # compress the page as a JPEG at this quality
    noise: float = 0.0  # share of pixels turned into dark specks
    grey: bool = False  # greyscale, as a fax
    all_pages: bool = False  # scan every page, not just the first


def _as_scan(pdf_bytes: bytes, style: ScanStyle | None = None) -> bytes:
    """Rasterize the page(s) and put the pictures in a PDF with no text layer, degraded as `style` says. With no
    style: the first page at 150 dpi, rotated 2 degrees (the golden set's one scan, unchanged)."""
    import io

    import pdfplumber
    from PIL import Image, ImageEnhance, ImageFilter

    style = style or ScanStyle()
    scan = _new_pdf()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as source:
        pages = source.pages if style.all_pages else source.pages[:1]
        for page_no, page in enumerate(pages):
            image = page.to_image(resolution=style.dpi).original
            if style.grey:
                image = image.convert("L").convert("RGB")
            if style.contrast != 1.0:
                image = ImageEnhance.Contrast(image).enhance(style.contrast)
            if style.blur:
                image = image.filter(ImageFilter.GaussianBlur(style.blur))
            if style.noise:
                rng = random.Random(f"specks-{page_no}-{style}")
                pixels = image.load()
                for _ in range(int(image.width * image.height * style.noise)):
                    pixels[rng.randrange(image.width), rng.randrange(image.height)] = (40, 40, 40)
            image = image.rotate(style.angle, expand=True, fillcolor="white")
            if style.jpeg_quality:
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=style.jpeg_quality)
                image = Image.open(io.BytesIO(buffer.getvalue()))
            scan.add_page()
            scan.image(image, x=0, y=0, w=210)
    return bytes(scan.output())


def render(sample: Sample, path: Path) -> None:
    content = render_bytes(sample)
    path.write_bytes(_as_scan(content, sample.scan_style) if sample.scanned else content)


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


def golden_gold(sample: Sample) -> dict:
    """The gold file of a golden-set invoice: every header field and every line, exactly as printed."""
    exponent = sample.exponent
    unit = lambda minor: f"{minor / 10**exponent:.{exponent}f}" if exponent else str(minor)  # noqa: E731
    return gold(sample) | {
        "style": sample.style,
        "pages": sample.pages if not sample.scanned or (sample.scan_style and sample.scan_style.all_pages) else 1,
        "stamp": sample.stamp, **({"scan_style": asdict(sample.scan_style)} if sample.scan_style else {}),
        "lines": [{"description": line.description, "quantity": str(line.quantity), "unit_price": unit(line.unit_price_minor),
                   "amount_minor": line.quantity * line.unit_price_minor} for line in sample.lines],
    }


GOLDEN_STYLES = [  # (style, vendor index in VENDORS, currency override)
    ("classic", 0, None), ("german", 1, None), ("right", 2, None), ("seikyu", 3, None), ("boxed", 4, "EUR"), ("compact", 5, None),
]
GOLDEN_SCANNED, GOLDEN_STAMPED, GOLDEN_MISPRINTED = {13}, {27}, {5, 33, 50}


def _layout_sample(i: int, seed: str, slug: str, pages: int, **overrides) -> Sample:
    """One invoice in one of the six vendor layouts (i picks the layout), from its own seeded random source."""
    from dataclasses import replace

    rng = random.Random(seed)
    style, vendor_index, currency = GOLDEN_STYLES[i % 6]
    base = random_sample(rng, i, "gold")
    name, tax_label, tax_printed, vendor_currency, rate = VENDORS[vendor_index]
    currency = currency or vendor_currency
    exponent = 0 if currency == "JPY" else 2
    lines = [Line(rng.choice(ITEMS), rng.randint(1, 40), rng.randint(50, 9000) * rng.choice([1, 10]) if exponent == 0
                  else rng.randint(1, 900) * rng.choice([1, 10, 25]))
             for _ in range(rng.randint(pages, min(pages * 4, 12)))]
    day, month = rng.randint(1, 28), rng.randint(1, 9)
    printed = (lambda d: f"{d[8:]}.{d[5:7]}.{d[:4]}") if style == "german" else (lambda d: d)
    iso, due = f"2026-{month:02d}-{day:02d}", f"2026-{month + 1:02d}-{day:02d}"
    return replace(base,
        slug=slug, vendor_name=name, vendor_tax_label=tax_label, vendor_tax_id_printed=tax_printed,
        vendor_tax_id="".join(c for c in tax_printed.upper() if c.isalnum()), currency=currency, exponent=exponent,
        tax_rate_pct=rate, lines=lines, style=style, pages=pages,
        invoice_number=f"{['INV', 'RE', 'NW', 'SK', 'AB', 'PR'][i % 6]}-2026-{1000 + i * 7}",
        invoice_date=iso, invoice_date_printed=printed(iso), due_date=due, due_date_printed=printed(due),
        po_number=str(4_500_100_000 + i) if rng.random() < 0.7 else None, **overrides,
    )


def golden_samples() -> list[Sample]:
    """60 invoices: six vendor layouts, EUR/USD/JPY/GBP, 1–4 pages, one rotated scan, one stamped, three with
    a misprinted total. Deterministic, so the set never changes unless this function does."""
    out = []
    for i in range(60):
        pages = 4 if i in (19, 44) else 3 if i % 10 == 9 else 2 if i % 10 in (7, 8) else 1
        exponent_jpy = GOLDEN_STYLES[i % 6][2] is None and VENDORS[GOLDEN_STYLES[i % 6][1]][3] == "JPY"
        out.append(_layout_sample(
            i, f"golden-{i}", f"g{i:02d}", 1 if i in GOLDEN_SCANNED else pages,
            scanned=i in GOLDEN_SCANNED, stamp="PAID 2026-10-31" if i in GOLDEN_STAMPED else None,
            total_misprint_minor=(500 if exponent_jpy else 1000) if i in GOLDEN_MISPRINTED else 0,
        ))
    return out


# The scans set (evals/golden/scans): what a scanner, a phone or a fax does to a page, one degradation or a mix per
# invoice, across the six layouts. (pages, style) per invoice.
SCAN_VARIANTS = [
    (1, ScanStyle(angle=0)),                                   # straight, clean
    (1, ScanStyle(angle=-1.5)),                                # tilted the other way
    (1, ScanStyle(angle=3)),                                   # tilted more
    (1, ScanStyle(angle=1, dpi=120)),                          # lower resolution
    (1, ScanStyle(angle=0.5, dpi=100)),                        # low resolution
    (1, ScanStyle(angle=1, contrast=0.55)),                    # faded: grey paper, light ink
    (1, ScanStyle(angle=-1, blur=0.9)),                        # out of focus
    (1, ScanStyle(angle=2, jpeg_quality=30)),                  # heavy JPEG compression
    (1, ScanStyle(angle=1, noise=0.004)),                      # specks
    (2, ScanStyle(angle=1, all_pages=True)),                   # a two-page scan
    (1, ScanStyle(angle=2, dpi=110, contrast=0.7, blur=0.6, grey=True)),   # fax-like
    (3, ScanStyle(angle=-1, dpi=130, all_pages=True)),         # a three-page scan
]


def scan_samples() -> list[Sample]:
    """12 scanned invoices, one per SCAN_VARIANTS entry, in the golden set's layouts but with their own seeds."""
    return [_layout_sample(i, f"scan-{i}", f"s{i + 1:02d}", pages, scanned=True, scan_style=style)
            for i, (pages, style) in enumerate(SCAN_VARIANTS)]


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
    parser.add_argument("--golden", action="store_true", help="write the 60-invoice eval set to evals/golden/extraction")
    parser.add_argument("--scans", action="store_true", help="write the 12 scanned invoices to evals/golden/scans")
    parser.add_argument("--from-po", help="write one invoice billing this purchase order instead")
    parser.add_argument("--dataset", type=Path, default=Path("data/erp/dataset.json"))
    parser.add_argument("--price-change", type=int, default=0, help="percent added to line 1's unit price")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.golden:
        out = Path("evals/golden/extraction")
        out.mkdir(parents=True, exist_ok=True)
        for sample in golden_samples():
            render(sample, out / f"{sample.slug}.pdf")
            (out / f"{sample.slug}.json").write_text(json.dumps(golden_gold(sample), indent=2) + "\n")
        print(f"wrote 60 golden invoices to {out}/")
        return
    if args.scans:
        out = Path("evals/golden/scans")
        out.mkdir(parents=True, exist_ok=True)
        for sample in scan_samples():
            render(sample, out / f"{sample.slug}.pdf")
            (out / f"{sample.slug}.json").write_text(json.dumps(golden_gold(sample), indent=2) + "\n")
        print(f"wrote {len(SCAN_VARIANTS)} scanned invoices to {out}/")
        return
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
