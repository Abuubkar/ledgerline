"""Service test for the vendors backfill (step 2 of docs/migrations.md), on a database held at revision 0005:
the schema it was written for, which later migrations remove."""

import importlib.util
import json

import asyncpg
import pytest

from ledgerline_api.settings import settings

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def _load_backfill():
    from conftest import REPO

    spec = importlib.util.spec_from_file_location("backfill_vendors", REPO / "scripts/migrations/backfill_vendors.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def expanded_db(postgres_url):
    """A second database in the test container, migrated only as far as step 1 (expand)."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    from conftest import REPO

    dsn = postgres_url.replace("postgresql+asyncpg", "postgresql")

    async def recreate():
        admin = await asyncpg.connect(dsn)
        await admin.execute("DROP DATABASE IF EXISTS at_0005")
        await admin.execute("CREATE DATABASE at_0005")
        await admin.close()

    asyncio.run(recreate())
    url = postgres_url.rsplit("/", 1)[0] + "/at_0005"
    previous, settings.database_url = settings.database_url, url
    try:
        command.upgrade(Config(str(REPO / "alembic.ini")), "0005")
    finally:
        settings.database_url = previous
    return url.replace("postgresql+asyncpg", "postgresql")


async def test_backfill_links_vendors_flags_the_newer_copy_and_resumes_after_a_crash(expanded_db):
    backfill = _load_backfill()
    conn = await asyncpg.connect(expanded_db)
    # Invoices written before step 1: the vendor only as extracted text. Ids are time-ordered, oldest first.
    legacy = [
        ("0190a000-0000-7000-8000-000000000001", "ACME GmbH", "DE812345678", "INV-0001", "extracted"),
        ("0190a000-0000-7000-8000-000000000002", "Café Lumière", None, "77", "extracted"),
        ("0190a000-0000-7000-8000-000000000003", "ACME GMBH", "DE812345678", "inv 1", "extracted"),  # a copy of 1
        ("0190a000-0000-7000-8000-000000000004", "CAFE LUMIERE", None, "78", "exception"),
        ("0190a000-0000-7000-8000-000000000005", "Café Lumière.", None, "079", "extracted"),
        ("0190a000-0000-7000-8000-000000000006", "Other AG", "CHE123456789", "INV-0001", "extracted"),  # other vendor
        ("0190a000-0000-7000-8000-000000000007", None, None, None, "received"),  # nothing extracted yet
    ]
    await conn.executemany(
        "INSERT INTO invoices (id, vendor_name, vendor_tax_id, invoice_number, status, original_filename, file_path)"
        " VALUES ($1, $2, $3, $4, $5, 'legacy.pdf', 's3://invoices/legacy.pdf')",
        legacy,
    )

    # Invoice 3 was extracted by a worker before step 1: a completed run with no raw header yet.
    await conn.execute(
        "INSERT INTO extraction_runs (invoice_id, task_id, attempt, outcome, lease_until)"
        " VALUES ($1, 't', 1, 'completed', now())", legacy[2][0])

    # One batch of 2, then the "crash": the first two invoices are linked and committed, the rest aren't.
    last, linked, _, _ = await backfill.backfill_batch(conn, "00000000-0000-0000-0000-000000000000", 2)
    assert linked == 2
    assert await conn.fetchval("SELECT count(*) FROM invoices WHERE vendor_id IS NOT NULL") == 2

    # The rerun starts from the beginning and only picks up what isn't linked yet.
    after = "00000000-0000-0000-0000-000000000000"
    while (result := await backfill.backfill_batch(conn, after, 2))[0] is not None:
        after = result[0]

    rows = {str(r["id"])[-1]: r for r in await conn.fetch(
        "SELECT i.id, i.vendor_id, i.invoice_number_key, i.status, i.invalid_fields, v.name, v.tax_id"
        " FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id")}
    assert await conn.fetchval("SELECT count(*) FROM vendors") == 3
    # The two ACME spellings are one vendor (same tax ID), named as first seen.
    assert rows["1"]["vendor_id"] == rows["3"]["vendor_id"] and rows["1"]["name"] == "ACME GmbH"
    # Three spellings of a vendor without a tax ID: one vendor, recognized by its normalized name.
    assert rows["2"]["vendor_id"] == rows["4"]["vendor_id"] == rows["5"]["vendor_id"]
    assert rows["2"]["tax_id"] is None
    # The newer copy of INV-0001 is flagged and loses its key; the other vendor's INV-0001 is not a copy.
    assert rows["1"]["invoice_number_key"] == "1" and rows["6"]["invoice_number_key"] == "1"
    assert rows["3"]["status"] == "exception" and rows["3"]["invoice_number_key"] is None
    assert json.loads(rows["3"]["invalid_fields"])["invoice_number"] == f"duplicate of invoice {rows['1']['id']}"
    assert rows["4"]["status"] == "exception" and rows["5"]["invoice_number_key"] == "79"
    assert rows["7"]["vendor_id"] is None  # nothing to link it by until it's extracted
    # The spelling as read survives on the run, though the vendor is named "ACME GmbH".
    raw = json.loads(await conn.fetchval("SELECT extracted_header FROM extraction_runs WHERE invoice_id = $1", legacy[2][0]))
    assert raw == {"vendor_name": "ACME GMBH", "vendor_tax_id": "DE812345678", "source": "backfill"}
    await conn.close()
