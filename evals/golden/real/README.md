# Real invoices: 25 FCC ad-buy documents

Real documents, unlike the generated golden set: invoices US TV stations issued to political advertisers, from the
FCC's public inspection files. Five are scanned (r11, r12, r14, r17, r18; four of them printed sideways). They test
reading what Ledgerline didn't design: real layouts, real scans, one-line-per-spot billing.

**Measured, not gated** (`uv run python evals/run.py --set real`, report in `evals/real/REPORT.md`). There's no test
split: nothing is tuned against this set.

## Source and permission

- **Documents:** taken unchanged from Google Research's VRDU benchmark, "Ad-buy forms" (DeepForm),
  https://github.com/google-research-datasets/vrdu/tree/main/ad-buy-form/main/pdfs. VRDU states that these are
  public documents from FCC PublicFiles (https://publicfiles.fcc.gov/). Stations must file them for public
  inspection. They're included here for non-commercial evaluation. Each gold file names its original file and URL.
- **Gold labels:** written for this project (2026-11-01) from the documents themselves, by two independent
  transcriptions, and checked: on 22 of 23 invoices the lines add up exactly to the printed gross. VRDU's own labels
  were used only to compare (they have no license, and they aren't included). On header fields, our labels agree
  with VRDU's wherever both have a value; on lines, VRDU's are incomplete in places (one invoice: 14 of 28 spots).
- **Privacy:** these are public filings. They name stations, campaigns, agencies and their business addresses, and
  no private individuals beyond public officials and candidates.

## What the gold holds

`rNN.pdf` and `rNN.json`:
- `document_type`: 23 invoices, plus r10, a payment report, and r11, an order worksheet. These two are kept on
  purpose, to see what Ledgerline does with documents that aren't invoices; in particular, whether it invents an
  invoice number.
- `invoice_number`, `invoice_date`, `due_date` (none print one except r15).
- `total_minor_accepted`: the gross and the net after agency commission, in cents. Either counts as the total.
- `lines`: as printed. Some layouts print one row per aired spot with its amount (quantity and unit price `null`);
  others print one row per contract line with a spot count and a rate (amount `null`). Scoring checks only the values
  a line prints.
- `fcc`: the rest of what the invoice says (station, advertiser, agency, product, flight dates, commission), for
  reference; not scored.
- `notes`: anything the transcribers found unclear or unusual (misprints kept as printed, clipped text, a credit line
  the printed total leaves out on r15).

## What it can't test

No VAT or tax ID, no PO number, no tax line, and dollars only. These are US advertising invoices, not the
supplier invoices Ledgerline is built for. They measure reading under real-world conditions. The supplier-invoice
fields are covered by the generated sets.
