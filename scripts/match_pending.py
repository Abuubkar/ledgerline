"""Queue a 3-way match for every extracted invoice that cites a PO but was never matched: invoices loaded by
scripts/seed.py, or extracted before matching existed. New extractions queue their own match.

Writes the jobs to the outbox in one statement; the relay publishes them and the workers match.
Usage: uv run python scripts/match_pending.py
"""

import asyncio

import asyncpg

from ledgerline_api.service import MATCH_TASK
from ledgerline_api.settings import settings


async def main() -> None:
    conn = await asyncpg.connect(settings.database_url.replace("postgresql+asyncpg", "postgresql"))
    status = await conn.execute(
        """
        INSERT INTO outbox (task_name, payload)
        SELECT $1, jsonb_build_object('invoice_id', i.id::text)
        FROM invoices i
        WHERE i.status = 'extracted' AND i.po_number IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM match_results m WHERE m.invoice_id = i.id)
        ORDER BY i.id
        """,
        MATCH_TASK,
    )
    print(f"queued {int(status.split()[-1]):,} match jobs")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
