# Schema migrations without downtime

Every migration must be safe to run while the previous release is serving traffic, and every release must
work against both the schema before and after its migration. The vendors move in slice 4a is the worked
example ([ADR 0011](adr/0011-vendors-table-and-expand-contract-migration.md)).

## Rules

- **Additive first.** New tables, nullable columns without defaults, new indexes. Old code ignores them.
- **Indexes on existing tables: `CREATE INDEX CONCURRENTLY`** inside `op.get_context().autocommit_block()`.
  A plain `CREATE INDEX` blocks writes for the whole build. A failed concurrent build leaves an `INVALID`
  index behind: find it with `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid`, drop it, rerun.
  (`IF NOT EXISTS` would silently keep the invalid one.)
- **Foreign keys: `NOT VALID`, then `VALIDATE CONSTRAINT`, in separate transactions.** Adding it `NOT VALID`
  takes a brief lock and checks only new writes; validating scans the table under a lock that doesn't block
  reads or writes.
- **`SET lock_timeout = '5s'`** before any `ALTER TABLE`. `ADD`/`DROP COLUMN` need an `ACCESS EXCLUSIVE` lock
  for an instant; queued behind a long transaction, they would block every request behind them. Better to
  fail and rerun.
- **Drop a column only after no deployed code reads or writes it** (the ORM selects every mapped column, so
  "doesn't use it" means "isn't in the model").
- **Data backfills are scripts, not migrations:** committed batches, resumable, oldest first, plain SQL.
- **One transaction per migration file** (`transaction_per_migration=True` in `migrations/env.py`), so an
  autocommit block never commits half of another file's work.

## Vendors move: deploy order

| Step | Migration | Code deployed | Order | Rollback |
|---|---|---|---|---|
| 1. Expand | `0005`: `vendors` table; `invoices.vendor_id`, `invoices.invoice_number_key`, `extraction_runs.extracted_header` (all nullable); unique `(vendor_id, invoice_number_key)` index built concurrently | Job writes the old columns **and** `vendor_id`, the duplicate key and the raw header | migrate, then deploy | Redeploy the old code, then `alembic downgrade 0004`. Vendor links made so far are lost; nothing else is, because the old columns kept being written |
| 2. Backfill | none | none | `uv run python scripts/migrations/backfill_vendors.py` (rerun after a crash) | Nothing to undo: old columns are untouched; `vendor_id` is ignored by step-1 code if you go back |
| 3. Switch reads | `0006`: FK `invoices.vendor_id → vendors.id`, `NOT VALID` then `VALIDATE` | REST/GraphQL read the vendor through `vendor_id`; still dual-write | migrate, then deploy | Redeploy step-1 code, then `alembic downgrade 0005` |
| 4. Contract | `0007`: drop `invoices.vendor_name`, `invoices.vendor_tax_id` | No reference to the old columns | **deploy, then migrate** | `alembic downgrade 0006` re-adds the columns and refills them from the extraction run's raw header, else from the vendor; then redeploy step-3 code. Not batched: a recovery, not a routine step |

The backfill (step 2) also copies each invoice's vendor name and tax ID as read onto its completed
extraction run before step 4 drops them. Invoices from before extraction runs existed (slices 1–2) have no
run, so only their vendor link survives.

## Live run, 2026-10-31

All four steps against the dev database (20,030 seeded invoices in the old shape plus earlier dev data),
while `scripts/upload_loop.py` uploaded an invoice every 0.5 s and listed the first page after each, using
the **0.4.0 client generated before this slice**. Workers on the stub model (15% of calls answer 503, which
the queue retries). Each deploy rebuilt nothing: images and worktrees for each step's commit were prepared
beforehand, then the worker and relay containers were recreated and the API (on the host) restarted.

```text
18:27:13 STEP 1 expand: migrate 0005 (old code live)        took 0.67s
18:27:29 deployed step1 code in 5s
18:27:59 STEP 2 backfill: one batch, stop, resume
  done: 1 batches, linked 10,000, new vendors 200, duplicates flagged 16 in 0.3s (34,318 invoices/sec)
  done: 1 batches, linked 8,767, new vendors 3, duplicates flagged 20 in 0.2s (37,560 invoices/sec); still unlinked: 0
18:28:20 STEP 3 switch reads: migrate 0006 (FK NOT VALID + VALIDATE)   took 0.69s
18:28:35 deployed step3 code in 5s
18:29:05 STEP 4 contract: deploy code first   (deployed in 4s)
18:29:29 STEP 4 contract: migrate 0007 (drop columns)       took 0.55s

uploads accepted: 339
final statuses: {'extracted': 339}; still not final: 0
errors: 0
refused connections (API restarts), retried: 32
```

After the run: all 339 live invoices linked to a vendor and carrying their raw header; the foreign key is
validated; the unique index is valid; 36 duplicates flagged (the seed's 30, plus the 3 sample PDFs uploaded
twice more in slice 1, before duplicate checks existed).

**Not zero-downtime for the API process itself:** the API runs as one uvicorn process on the host, so each
code deploy refuses connections for ~1–2 s (32 refusals over 4 deploys, retried by the client). The schema
changes caused no errors. Behind a load balancer with two instances, a rolling restart would remove the gap.

## Deep pages stay fast: EXPLAIN ANALYZE, invoice list page 500

`uv run python scripts/explain_list.py` (the query `service.keyset_page` sends, after row 12,475):

```text
invoices: 20,843; page 500 of 25, after row 12,475

Limit (actual time=0.018..0.049 rows=26.00 loops=1)
  Buffers: shared hit=5
  ->  Index Scan using invoices_created_at_id_idx on invoices (actual time=0.017..0.046 rows=26.00 loops=1)
        Index Cond: (ROW(created_at, id) < ROW('2026-04-01 13:31:32+00'::timestamp with time zone, '019d493d-fb20-729c-b2f2-3791e6181795'::uuid))
        Index Searches: 1
        Buffers: shared hit=5
Planning Time: 0.504 ms
Execution Time: 0.081 ms
```

An index scan reading only the 26 rows it returns, no sort. The same page by `OFFSET 12475` walks 12,501
index entries: **9.4 ms** against **0.08 ms**, and it grows with the page number. With the large profile
(100,030 invoices) the keyset plan is unchanged and reads 26 rows.
