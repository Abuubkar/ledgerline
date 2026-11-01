---
status: accepted
date: 2026-11-01
---

# Two more eval sets: generated scans and real invoices, measured but not gated

The 60-invoice golden set (ADR 0015) measures reading clean, generated, text PDFs; it has one scan. Two sets now sit
beside it, run with `evals/run.py --set scans` and `--set real`. Both are reported, not gated, so they measure
without blocking a merge.

## Decisions inside this

- **`evals/golden/scans`: 12 generated scans.** Same six layouts and same gold-by-construction as the golden set,
  each degraded one way or several: straight, tilted ±1.5–3°, 100–150 dpi, faded, blurred, heavy JPEG, specks,
  fax-like greyscale, and 2- and 3-page scans (`scripts/make_invoice.py --scans`, `ScanStyle`). It's a separate set,
  with its own fixed split (4 held out), so the golden set's cases, splits, recordings and archived results stay
  exactly comparable. Regenerating the golden set after the refactor gives byte-identical files.
- **`evals/golden/real`: 25 real FCC ad-buy documents.** Real invoices are what the generated sets can't stand in for.
  - **Source:** no public dataset has real supplier invoices with header and line labels and a license to publish
    them (research, 2026-11-01). DocILE fits our fields but is research-only and can't be redistributed. These come
    from Google's VRDU benchmark and are FCC public filings (README in the folder).
  - **Choosing them:** 25 distinct stations, at most 5 of one shared template. 5 are scans (all the dataset has
    among its invoices with a total). Two aren't invoices (a payment report, an order worksheet): kept on purpose
    (the user's call) to see what Ledgerline does with them.
  - **Gold labels:** ours, transcribed twice independently from the documents. On 22 of 23 invoices the lines add up
    to the printed gross; the 23rd differs by a line printed as "Credit" that its own total leaves out.
    Compared field by field with VRDU's labels:
    - every disagreement is a convention (station vs remit-to address), a date format, a truncation or a definition
      (a payment report labelled with a gross);
    - VRDU's line labels are incomplete in places (14 of 28 spots on one invoice).

    VRDU's labels have no license and aren't included.
  - **Scoring for what these invoices print:** invoice number, invoice date and total, where the gross or the net
    after agency commission both count. Lines are checked only on the values a line prints: some layouts print an
    amount per aired spot, others a spot count and a rate. A description matches when its words are all in the
    extracted one (models fold air dates and spot codes into it), and lines whose numbers agree are paired first
    (per-spot invoices repeat one description). The strict rules for generated invoices are unchanged; unit tests
    pin both.

## What they found (gemma4:12b, extract-page/4)

| Set | Header | Lines F1 | Notes |
|---|---|---|---|
| Golden, dev (text PDFs) | 100% | 99.3% | for comparison |
| Scans, dev (8) | 91.2% avg, 50% lowest (VAT ID) | 81.0% | single-digit misreads; tilted rows swapped; calibration error 8.9% |
| Scans, test (4) | 97.5% avg, 75% lowest | 100% | |
| Real (23 invoices) | number 91.3%, date 91.3%, total 34.8% | 37.0% | 23 of 25 ended in `exception`; one timeout |

**Findings, with what they mean:**
- **Scans:** the model misreads single digits (VAT IDs, a due date, amounts). The arithmetic check catches the
  amounts (the invoice goes to `exception`). Nothing checks a VAT ID, so a misread one links the invoice to the wrong
  vendor or a new one. Backlog: check digits.
- **Real: dollar-sign invoices.** US invoices print `$`, never "USD", so the model (told to give an ISO code and
  never infer) answers no currency. Amounts can't then be turned into minor units, so totals and per-spot line
  amounts are dropped and the invoice goes to `exception`. Nothing was guessed, which is the safe failure. Where a
  currency was read, every extracted total was right (the net), and 70 of 94 lines were. Backlog: take the
  currency from the PO or the vendor master when only a symbol is printed.
- **Real: which rows are lines.** Some layouts print contract lines and every aired spot under them; on 3 invoices
  the model billed the spots.
- **Real: speed.** Dense real pages take 80 s (p50) to 147 s (p95) of model time per page, against 34 s for
  generated ones. A two-page sideways scan timed out at 180 s.
- **Real: a non-invoice.** The order worksheet's "REP HEADLINE 6282550" came back as an invoice number. The payment
  report got none.

## Alternatives considered

- **Add the scans to the golden set.** Simpler to run, but some existing cases would move between dev and test and
  the baseline would shift (the user chose a separate set).
- **DocILE for the real set.** Better field fit, but research-only: the files couldn't be published, and every
  contributor would need their own access.
- **Copy RealKIE's labels** (CC BY-NC) instead of writing our own: faster, but the labels folder would become
  non-commercial, and the comparison showed published labels aren't complete.
- **Gate on them.** There's no baseline yet, and the real set measures a document type Ledgerline wasn't built for.
  Gating would block merges for the wrong reasons.

## Assumptions

- The FCC documents are public records included for non-commercial evaluation (README); if a takedown is ever asked
  for, the set is removed and the report kept.
- Nothing is tuned against the real set; it has no held-out split because it's for measuring only.
