"""Vendors migration, step 2 of 4: link every existing invoice to its vendor (docs/migrations.md).

Runs against a database at revision 0005 or 0006, while the app keeps running; it's plain SQL, so it doesn't
depend on the ORM models of whatever code is deployed.

- Batches of --batch invoices, oldest first, each committed on its own. A crash loses at most one batch:
  rerun it and it carries on, because it only picks invoices that aren't linked yet.
- A vendor is found or created by tax ID, or by normalized name when there's no tax ID (vendors.py's rules).
- When two invoices share a vendor and invoice number, the older keeps it; the newer is flagged as a
  duplicate, as the extraction job does for new uploads.
- The vendor name and tax ID as read are copied onto the invoice's completed extraction run, so dropping the
  columns in step 4 doesn't lose them.

Usage: uv run python scripts/migrations/backfill_vendors.py [--batch 10000] [--stop-after N]
"""

import argparse
import asyncio
import json
import time

import asyncpg

from ledgerline_api.normalize import invoice_number_key, vendor_name_key
from ledgerline_api.settings import settings

NEXT_BATCH = """
    SELECT id, vendor_name, vendor_tax_id, invoice_number, status, invalid_fields
    FROM invoices
    WHERE vendor_id IS NULL AND (vendor_tax_id IS NOT NULL OR vendor_name IS NOT NULL) AND id > $1
    ORDER BY id
    LIMIT $2
"""
# Insert-or-ignore, then read back: vendors the app creates at the same moment are reused, not duplicated.
ADD_TAX_VENDORS = """
    INSERT INTO vendors (tax_id, name, name_key)
    SELECT * FROM unnest($1::text[], $2::text[], $3::text[])
    ON CONFLICT (tax_id) WHERE tax_id IS NOT NULL DO NOTHING
"""
ADD_NAME_VENDORS = """
    INSERT INTO vendors (name, name_key)
    SELECT * FROM unnest($1::text[], $2::text[])
    ON CONFLICT (name_key) WHERE tax_id IS NULL DO NOTHING
"""
TAKEN_KEYS = """
    SELECT i.vendor_id, i.invoice_number_key, i.id
    FROM invoices i JOIN unnest($1::uuid[], $2::text[]) AS k(vendor_id, key)
      ON i.vendor_id = k.vendor_id AND i.invoice_number_key = k.key
"""
# The name and tax ID as read live only in the columns step 4 drops; copy them onto the completed extraction
# run, where the job now records the raw header. Invoices from before extraction runs existed have no run, so
# only their vendor link survives.
KEEP_AS_READ = """
    UPDATE extraction_runs r
    SET extracted_header = jsonb_build_object('vendor_name', i.vendor_name, 'vendor_tax_id', i.vendor_tax_id,
                                              'source', 'backfill')
    FROM invoices i
    WHERE i.id = any($1::uuid[]) AND r.invoice_id = i.id AND r.outcome = 'completed' AND r.extracted_header IS NULL
"""
APPLY = """
    UPDATE invoices i
    SET vendor_id = u.vendor_id, invoice_number_key = u.key, status = u.status, invalid_fields = u.invalid_fields::jsonb
    FROM unnest($1::uuid[], $2::uuid[], $3::text[], $4::text[], $5::text[]) AS u(id, vendor_id, key, status, invalid_fields)
    WHERE i.id = u.id AND i.vendor_id IS NULL
"""


async def backfill_batch(conn: asyncpg.Connection, after, size: int) -> tuple[object, int, int, int]:
    """Link one batch. Returns (last id, invoices linked, vendors created, duplicates flagged)."""
    async with conn.transaction():
        rows = await conn.fetch(NEXT_BATCH, after, size)
        if not rows:
            return None, 0, 0, 0
        # Oldest row wins the vendor's display name (ids are time-ordered).
        by_tax, by_name = {}, {}
        for r in rows:
            if r["vendor_tax_id"]:
                by_tax.setdefault(r["vendor_tax_id"], r["vendor_name"] or r["vendor_tax_id"])
            elif vendor_name_key(r["vendor_name"]):
                by_name.setdefault(vendor_name_key(r["vendor_name"]), r["vendor_name"])
        before = await conn.fetchval("SELECT count(*) FROM vendors")
        await conn.execute(ADD_TAX_VENDORS, list(by_tax), list(by_tax.values()), [vendor_name_key(n) for n in by_tax.values()])
        await conn.execute(ADD_NAME_VENDORS, list(by_name.values()), list(by_name))
        created = await conn.fetchval("SELECT count(*) FROM vendors") - before
        tax_ids = dict(await conn.fetch("SELECT tax_id, id FROM vendors WHERE tax_id = any($1::text[])", list(by_tax)))
        name_ids = dict(await conn.fetch(
            "SELECT name_key, id FROM vendors WHERE tax_id IS NULL AND name_key = any($1::text[])", list(by_name)))

        linked = []
        for r in rows:
            vendor_id = tax_ids.get(r["vendor_tax_id"]) if r["vendor_tax_id"] else name_ids.get(vendor_name_key(r["vendor_name"]))
            linked.append((r, vendor_id, invoice_number_key(r["invoice_number"])))
        pairs = [(v, k) for _, v, k in linked if v and k]
        taken = {(row["vendor_id"], row["invoice_number_key"]): row["id"]
                 for row in await conn.fetch(TAKEN_KEYS, [v for v, _ in pairs], [k for _, k in pairs])}

        updates, duplicates = [], 0
        for r, vendor_id, key in linked:
            status, invalid = r["status"], json.loads(r["invalid_fields"]) if r["invalid_fields"] else None
            if vendor_id and key and (vendor_id, key) in taken:
                invalid = {**(invalid or {}), "invoice_number": f"duplicate of invoice {taken[(vendor_id, key)]}"}
                status, key, duplicates = ("exception" if status == "extracted" else status), None, duplicates + 1
            elif vendor_id and key:
                taken[(vendor_id, key)] = r["id"]  # later rows in this batch see it
            updates.append((r["id"], vendor_id, key, status, json.dumps(invalid) if invalid is not None else None))
        await conn.execute(KEEP_AS_READ, [r["id"] for r in rows])
        await conn.execute(APPLY, *map(list, zip(*updates)))
        return rows[-1]["id"], sum(1 for u in updates if u[1]), created, duplicates


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", type=int, default=10_000)
    parser.add_argument("--stop-after", type=int, help="stop after this many batches (to try a resume)")
    args = parser.parse_args()
    conn = await asyncpg.connect(settings.database_url.replace("postgresql+asyncpg", "postgresql"))
    # Short lock waits: if the app holds a row this batch wants, fail fast and let a rerun pick it up.
    await conn.execute("SET lock_timeout = '5s'")
    started, after, batches = time.perf_counter(), "00000000-0000-0000-0000-000000000000", 0
    totals = [0, 0, 0]
    while args.stop_after is None or batches < args.stop_after:
        batch_started = time.perf_counter()
        last, linked, created, duplicates = await backfill_batch(conn, after, args.batch)
        if last is None:
            break
        after, batches = last, batches + 1
        totals = [totals[0] + linked, totals[1] + created, totals[2] + duplicates]
        print(f"batch {batches}: linked {linked:,}, new vendors {created}, duplicates flagged {duplicates} "
              f"({time.perf_counter() - batch_started:.2f}s)")
    left = await conn.fetchval(
        "SELECT count(*) FROM invoices WHERE vendor_id IS NULL AND (vendor_tax_id IS NOT NULL OR vendor_name IS NOT NULL)")
    took = time.perf_counter() - started
    print(f"done: {batches} batches, linked {totals[0]:,}, new vendors {totals[1]}, duplicates flagged {totals[2]} "
          f"in {took:.1f}s ({totals[0] / max(took, 1e-9):,.0f} invoices/sec); still unlinked: {left:,}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
