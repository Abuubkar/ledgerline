---
status: accepted
date: 2026-10-31
---

# Purchase orders come from a resumable ERP sync; invoices are 3-way matched against them

An invoice should be paid only for what was ordered at the agreed price and actually delivered. That's the
3-way match: invoice ↔ purchase order (PO) ↔ goods receipts. POs and receipts live in the company's ERP, so
Ledgerline copies them in (`sync_erp`) and checks each extracted invoice against them (`match_invoice`).
`apps/erp_mock` stands in for the ERP, with the faults real ones have: rate limits, slow answers, cursors
that expire.

## Decisions inside this

- **The invoice's PO number is read by the model** (`po_number`, prompt `extract-page/2`), and the PO is found
  by a normalized key (`po_number_key`: prefix words like "PO" or "P.O. No.", separators and leading zeros
  don't count). Guessing the PO from the vendor's open orders was the alternative: no extraction change, but
  it can pick the wrong PO, and a wrong match pays a wrong bill.
- **An invoice without a PO number isn't matched**: it stays `extracted`. There's no non-PO approval flow
  yet, and `extracted` is not "approved for payment". Flagging every one as an exception would bury the real
  mismatches.
- **New status `matched`**: `extracted → matched | exception`. A failed match uses the existing `exception`
  ("a person needs to look"), with the reasons in `match_results`. Adding `matched` to the public enum is a
  breaking change for clients generated before 0.6.0 (their enum rejects the new value; oasdiff reports
  `response-property-enum-value-added`). Accepted: the status is what the reviewer UI filters on, and a
  separate field would leave `extracted` meaning two things.
- **Match rules, per invoice line** (`matching.py`, plain functions): the PO line with the same description
  (case, punctuation and spacing ignored), unit price within 1% of the PO price (`match_price_tolerance_pct`),
  billed quantity exactly equal to the quantity received over all receipts, and not more than ordered. Also
  per invoice: PO found, same vendor, same currency, at least one receipt. Every failed rule is stored as a
  reason with the line it concerns; prices are compared as decimals, never floats.
- **Sync: walk each ERP list page by page, one transaction per page.** The page's upserts, the ERP's cursor
  for the next page and `synced_through` (the newest `updated_at` committed) are saved together, so a crash
  resumes on the next page. On 410 (cursor expired) a new walk starts with `updated_since = synced_through`;
  the next scheduled run does the same, which makes every run after the first incremental. Restarting from
  `synced_through` rather than from the last full success re-reads less and is just as safe: the ERP lists
  oldest change first, so everything older than it is stored.
- **Upsert only when newer**: `ON CONFLICT (erp_id) DO UPDATE ... WHERE stored.erp_updated_at <
  excluded.erp_updated_at`. Postgres returns no row for a skipped conflict, which gives the written count and
  says which POs need their lines replaced.
- **Receipts are linked by PO number, not a foreign key.** The ERP can send a receipt before its PO.
- **A sync that changes a PO or receipt re-queues invoices whose match failed for that PO**, through the
  outbox in the page's transaction (an invoice already waiting isn't queued twice).
- **Celery beat** sends `sync_erp` every 5 minutes (`expires` = the interval, so missed runs don't pile up).
  A session-level Postgres advisory lock lets only one sync run at a time; Postgres releases it if the worker
  dies. Matching and syncing get their own quorum queues (`invoices.match` with a dead-letter queue,
  `erp.sync`), so a backlog of one doesn't delay the others' messages.

## Alternatives considered

- **Sync with `updated_since` only, no cursors.** Simpler, but a crash mid-walk re-reads from the start, and
  the ERP's API is cursor-based anyway.
- **Match inside the extraction job.** No extra queue, but re-matching after a sync would need a second code
  path. One job serves both.
- **A `match_status` on invoices instead of a new status value.** Avoids the enum change; rejected above.
- **Fuzzy description matching** (similarity score). Would catch more re-worded lines, but decides money on a
  threshold. Exact-after-normalizing first; a fuzzy suggestion can come with the agent (slice 5).

## Assumptions

- One invoice bills one PO in full or in part, and no PO is billed by several invoices; split billing would
  need receipt quantities allocated across invoices.
- Invoice line descriptions copy the PO's descriptions closely enough that normalizing case, punctuation and
  spacing finds the line. A vendor that renames items will show up as `line_not_on_po`.
- PO numbers are unique in the ERP after normalizing (`purchase_orders.po_number_key` is unique; a clash
  stops the sync with an error rather than overwriting).
- The ERP's `updated_at` never goes backwards for a record.
