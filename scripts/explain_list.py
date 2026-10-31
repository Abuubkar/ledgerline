"""EXPLAIN ANALYZE the invoice list query as the API runs it for a deep page (default: page 500 of 25).

Builds the same keyset query as service.keyset_page, positioned after the last row of the page before, so the
plan shows whether Postgres seeks into the (created_at, id) index or sorts. Needs a seeded database.
Usage: uv run python scripts/explain_list.py [--page 500] [--limit 25]
"""

import argparse
import asyncio

from sqlalchemy import select, text, tuple_
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

from ledgerline_api.db import Invoice
from ledgerline_api.settings import settings


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", type=int, default=500)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    engine = create_async_engine(settings.database_url)
    newest_first = (Invoice.created_at.desc(), Invoice.id.desc())
    async with engine.connect() as conn:
        position = (await conn.execute(
            select(Invoice.created_at, Invoice.id).order_by(*newest_first).offset((args.page - 1) * args.limit - 1).limit(1)
        )).one()
        # The query keyset_page sends for that cursor: the row-value comparison, then one extra row.
        query = (
            select(Invoice).where(tuple_(Invoice.created_at, Invoice.id) < tuple(position))
            .order_by(*newest_first).limit(args.limit + 1)
        )
        sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        total = (await conn.execute(text("SELECT count(*) FROM invoices"))).scalar_one()
        plan = (await conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) {sql}"))).scalars().all()
    await engine.dispose()
    print(f"invoices: {total:,}; page {args.page} of {args.limit}, after row {(args.page - 1) * args.limit:,}\n")
    print("\n".join(plan))


if __name__ == "__main__":
    asyncio.run(main())
