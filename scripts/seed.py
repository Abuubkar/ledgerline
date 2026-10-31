"""Load realistic volume into the dev database: vendors, invoices in every status with their line items, and
30 near-duplicate invoices (the same vendor and number, printed differently).

Deterministic: the same --seed gives the same rows. Loads with COPY and prints rows/sec.
Writes what the app writes at the database's current migration step (docs/migrations.md): before the vendors
table exists, the vendor's name and tax ID on each invoice; after step 4, only vendor_id; in between, both.
Seeded invoices point at PDFs that don't exist, so they can be listed and matched but not re-extracted.

Usage: uv run python scripts/seed.py [--profile small|large] [--seed 1] [--replace]
"""

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import asyncpg
from faker import Faker

from ledgerline_api.money import CURRENCY_EXPONENTS
from ledgerline_api.normalize import invoice_number_key, normalize_tax_id, vendor_name_key
from ledgerline_api.settings import settings

PROFILES = {
    # vendors, invoices, line items per invoice (min, max)
    "small": (200, 20_000, (1, 8)),
    "large": (200, 100_000, (5, 15)),  # ~1M invoice lines
}
NEAR_DUPLICATES = 30
VENDORS_WITHOUT_TAX_ID = 15
STATUSES = [("extracted", 80), ("exception", 7), ("partially_extracted", 4), ("received", 4), ("failed", 3),
            ("extracting", 2)]
COUNTRIES = [  # (Faker locale, tax ID format, currency)
    ("de_DE", "DE#########", "EUR"), ("en_US", "##-#######", "USD"), ("en_GB", "GB### #### ##", "GBP"),
    ("de_CH", "CHE-###.###.###", "CHF"), ("ja_JP", "T#############", "JPY"), ("fr_FR", "FR## #########", "EUR"),
]
TAX_RATE_PERCENT = {"EUR": 19, "USD": 0, "GBP": 20, "CHF": 8, "JPY": 10}
NOW = datetime(2026, 10, 31, tzinfo=UTC)  # fixed, so the same seed gives the same dates


@dataclass
class Vendor:
    id: uuid.UUID
    name: str
    tax_id: str | None
    currency: str
    number_prefix: str


def uuid7(at: datetime, rng: random.Random) -> uuid.UUID:
    """A time-ordered id like Postgres's uuidv7(), so seeded ids sort the way created_at does."""
    value = (int(at.timestamp() * 1000) << 80) | rng.getrandbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC 4122 variant
    return uuid.UUID(int=value)


def make_vendors(count: int, rng: random.Random, seed: str) -> list[Vendor]:
    vendors = []
    for i in range(count):
        locale, tax_format, currency = COUNTRIES[i % len(COUNTRIES)]
        fake = Faker(locale)
        fake.seed_instance(f"{seed}-vendor-{i}")
        name = fake.company()
        tax_id = None if i < VENDORS_WITHOUT_TAX_ID else normalize_tax_id(fake.numerify(tax_format))
        prefix = rng.choice(["INV", "RE", "F", "".join(w[0] for w in name.upper().split()[:2] if w[:1].isalpha()) or "X"])
        vendors.append(Vendor(uuid7(NOW - timedelta(days=400), rng), name, tax_id, currency, prefix))
    return vendors


def line_items(seed: str, index: int, sizes: tuple[int, int], descriptions: list[str], currency: str):
    """(line_no, description, quantity, unit_price, amount_minor) for one invoice. Its own RNG, so the lines
    can be regenerated for COPY without holding a million of them in memory."""
    rng = random.Random(f"{seed}-lines-{index}")
    exponent = CURRENCY_EXPONENTS[currency]
    for line_no in range(1, rng.randint(*sizes) + 1):
        quantity = rng.randint(1, 50)
        unit_minor = rng.randint(1, 500) * 10 ** exponent if exponent == 0 else rng.randint(100, 50_000)
        yield line_no, rng.choice(descriptions), Decimal(quantity), Decimal(unit_minor).scaleb(-exponent), quantity * unit_minor


def printed_variant(number: str, rng: random.Random) -> str:
    """The same invoice number as another clerk or scanner might print it: different case, separators,
    leading zeros or a prefix word, which invoice_number_key treats as the same number."""
    prefix, _, digits = number.partition("-")
    return rng.choice([f" {number.lower()} ", number.replace("-", " "), f"{prefix}-{int(digits)}",
                       f"Invoice No. {number}"])


async def columns(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'invoices'")
    return {r["column_name"] for r in rows}


async def copy(conn: asyncpg.Connection, table: str, cols: list[str], records) -> None:
    started = time.perf_counter()
    status = await conn.copy_records_to_table(table, columns=cols, records=records)
    rows = int(status.split()[-1])
    took = time.perf_counter() - started
    print(f"  {table:14} {rows:>9,} rows in {took:6.1f}s  ({rows / took:,.0f} rows/sec)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=PROFILES, default="small")
    parser.add_argument("--seed", default="1")
    parser.add_argument("--replace", action="store_true", help="delete earlier seed rows first")
    args = parser.parse_args()
    vendor_count, invoice_count, sizes = PROFILES[args.profile]
    rng = random.Random(args.seed)

    conn = await asyncpg.connect(settings.database_url.replace("postgresql+asyncpg", "postgresql"))
    existing = await columns(conn)
    legacy, linked = "vendor_name" in existing, "vendor_id" in existing
    if await conn.fetchval("SELECT count(*) FROM invoices WHERE original_filename LIKE 'seed-%'"):
        if not args.replace:
            sys.exit("seed rows already exist; rerun with --replace to delete and reload them")
        deleted = await conn.execute("DELETE FROM invoices WHERE original_filename LIKE 'seed-%'")
        if linked:
            await conn.execute("DELETE FROM vendors v WHERE NOT EXISTS (SELECT 1 FROM invoices i WHERE i.vendor_id = v.id)")
        print(f"deleted earlier seed rows ({deleted})")

    vendors = make_vendors(vendor_count, rng, args.seed)
    fake = Faker("en_US")
    fake.seed_instance(args.seed)
    descriptions = [fake.catch_phrase() for _ in range(500)]

    invoices, next_number = [], {v.id: 1000 for v in vendors}
    statuses, weights = zip(*STATUSES)
    for i in range(invoice_count):
        vendor = rng.choice(vendors)
        status = rng.choices(statuses, weights)[0]
        invoice_date = (NOW - timedelta(days=rng.randint(0, 365))).date()
        created_at = datetime.combine(invoice_date, datetime.min.time(), UTC) + timedelta(seconds=rng.randint(3600, 86_000))
        next_number[vendor.id] += rng.randint(1, 3)
        number = f"{vendor.number_prefix}-{next_number[vendor.id]:06d}"
        # 1 in 10 invoices spells the vendor's name differently; the tax ID still identifies it.
        name = vendor.name.upper() if rng.random() < 0.1 else vendor.name
        invoices.append(dict(id=uuid7(created_at, rng), index=i, lines_index=i, vendor=vendor, name=name, status=status,
                             number=number, invoice_date=invoice_date, created_at=created_at))
    originals = rng.sample([inv for inv in invoices if inv["status"] == "extracted"], NEAR_DUPLICATES)
    for n, original in enumerate(originals):
        created_at = original["created_at"] + timedelta(days=rng.randint(1, 20))
        invoices.append(dict(original, id=uuid7(created_at, rng), index=invoice_count + n, created_at=created_at,
                             number=printed_variant(original["number"], rng), duplicate_of=original["id"]))

    if linked:
        # Vendors the app already created (same tax ID) are reused, not duplicated.
        known = {r["tax_id"]: r["id"] for r in await conn.fetch("SELECT id, tax_id FROM vendors WHERE tax_id IS NOT NULL")}
        new_vendors = [v for v in vendors if v.tax_id not in known]
        for vendor in vendors:
            vendor.id = known.get(vendor.tax_id, vendor.id)

    def invoice_rows():
        """(invoice row, how to regenerate its line items) for every invoice."""
        for inv in invoices:
            vendor, status = inv["vendor"], inv["status"]
            read = status not in ("received", "extracting", "failed")
            lines = list(line_items(args.seed, inv["lines_index"], sizes, descriptions, vendor.currency)) if read else []
            subtotal = sum(line[4] for line in lines)
            tax = subtotal * TAX_RATE_PERCENT[vendor.currency] // 100
            invalid = {}
            key = invoice_number_key(inv["number"]) if read else None
            if linked and inv.get("duplicate_of"):  # what vendors.link does for a copy
                invalid["invoice_number"], key, status = f"duplicate of invoice {inv['duplicate_of']}", None, "exception"
            row = {
                "id": inv["id"], "status": status, "original_filename": f"seed-{inv['index']:06d}.pdf",
                "file_path": f"s3://{settings.s3_bucket}/seed/{inv['index']:06d}.pdf",
                "content_sha256": hashlib.sha256(f"seed-{args.seed}-{inv['index']}".encode()).hexdigest(),
                "page_count": 1 if read else None, "invoice_number": inv["number"] if read else None,
                "invoice_date": inv["invoice_date"] if read else None,
                "due_date": inv["invoice_date"] + timedelta(days=30) if read else None,
                "currency": vendor.currency if read else None,
                "subtotal_minor": subtotal if read else None, "tax_minor": tax if read else None,
                "total_minor": subtotal + tax if read else None,
                "invalid_fields": json.dumps(invalid) if read else None,
                "error_code": "no_page_extracted" if status == "failed" else None,
                "model": "seed" if read else None, "created_at": inv["created_at"],
            }
            if legacy:
                row |= {"vendor_name": inv["name"] if read else None, "vendor_tax_id": vendor.tax_id if read else None}
            if linked:
                row |= {"vendor_id": vendor.id if read else None, "invoice_number_key": key}
            yield row, (inv["lines_index"], vendor.currency) if lines else None

    rows = list(invoice_rows())
    print(f"seeding profile {args.profile!r}, seed {args.seed!r}, "
          f"schema: {'vendor columns' if legacy else ''}{' + ' if legacy and linked else ''}{'vendor_id' if linked else ''}")
    async with conn.transaction():
        if linked:
            await copy(conn, "vendors", ["id", "tax_id", "name", "name_key", "created_at"], [
                (v.id, v.tax_id, v.name, vendor_name_key(v.name), NOW - timedelta(days=400)) for v in new_vendors
            ])
        cols = list(rows[0][0])
        await copy(conn, "invoices", cols, [tuple(row[c] for c in cols) for row, _ in rows])
        line_cols = ["id", "invoice_id", "page_no", "line_no", "description", "quantity", "unit_price", "amount_minor"]
        line_rng = random.Random(f"{args.seed}-line-ids")
        await copy(conn, "invoice_lines", line_cols, (
            (uuid7(row["created_at"], line_rng), row["id"], 1, *line)
            for row, lines in rows if lines
            for line in line_items(args.seed, lines[0], sizes, descriptions, lines[1])
        ))
    counts = await conn.fetch(
        "SELECT status, count(*) FROM invoices WHERE original_filename LIKE 'seed-%' GROUP BY 1 ORDER BY 2 DESC")
    print("  statuses: " + ", ".join(f"{r['status']} {r['count']:,}" for r in counts))
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
