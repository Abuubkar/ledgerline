---
status: accepted
date: 2026-10-31
---

# Vendors get their own table, moved there with an expand/contract migration

Until slice 4a each invoice carried the vendor's name and tax ID as extracted text, so nothing knew that two
invoices came from the same company (the dev database had 9 tax IDs under 10 spellings). Matching invoices to
purchase orders (slice 4b) needs a vendor identity. Invoices now point at a `vendors` row through
`invoices.vendor_id`, and the move was done in four deployable steps while uploads kept running
(docs/migrations.md).

## Decisions inside this

- **Recognize a vendor by tax ID, else by normalized name.** A tax ID is the only identifier printed on almost
  every invoice and unique per company. Without one, the name with case, punctuation, spacing and Latin
  accents ignored. A vendor with a tax ID is never matched by name: two companies can share a name, and a
  wrong merge would mix their bills. The vendor keeps the name as first seen.
- **Duplicates: same vendor and same normalized invoice number.** Case, separators, leading zeros and prefix
  words (INV, No., Rechnung…) don't count; other letters do ("RE-2026-0915" ≠ "2026-0915"), because a vendor's
  own prefix can tell two series apart. The later copy goes to `exception` with
  `invalid_fields.invoice_number = "duplicate of invoice <id>"` and keeps no key. An advisory lock per
  vendor and number orders two copies extracted at once; a partial unique index on
  `(vendor_id, invoice_number_key)` is the backstop.
- **No new status for duplicates.** `exception` already means "a person needs to look"; the reason says why.
  A `duplicate` status would change the public enum for no new behaviour.
- **The raw extracted header lives on the completed extraction run** (`extraction_runs.extracted_header`).
  It records what the model read, separate from what we concluded (vendor link, duplicate flag).
- **The API keeps `vendor_name` and `vendor_tax_id`**, now taken from the vendor and marked deprecated, next
  to a new `vendor` object. Clients generated before 0.5.0 keep working (shown live: the upload loop used the
  0.4.0 client throughout).
- **Backfill is a plain-SQL script, not an Alembic data migration.** It runs for as long as the data needs,
  in committed batches, resumable, while the app serves traffic; a migration would hold one transaction.
  Plain SQL keeps it independent of whichever ORM models are deployed.

## Alternatives considered

- **One migration that adds the table, fills it and drops the columns.** Simple, but it locks `invoices`
  for the length of the backfill and can't be rolled out with running code. Rejected: the point is no
  downtime.
- **Keep the text columns and add `vendor_id` beside them.** No migration risk, but two sources for the
  vendor's name that drift apart. Rejected.
- **Match vendors by fuzzy name similarity.** Catches more spellings, but merges different companies
  silently. Can come later as a suggestion for a person to confirm, not as an automatic link.

## Assumptions

- Tax IDs are extracted correctly often enough to be the identity; a misread tax ID creates a new vendor rather
  than attaching to the wrong one, which is the safer failure.
- Invoices from before extraction runs existed (slices 1–2) have no run to keep the raw spelling on; for those
  only the vendor link survives. Acceptable for dev data; there is no production data.
