"""Run one ERP sync in the foreground and print what it did (beat runs the same job every 5 minutes).

--full forgets the saved cursors and watermarks first, so the next walk reads everything again (after the
ERP's data was replaced by an older seed, say). Rows already stored are rewritten only if the ERP's copy is
newer, so a full sync is safe.
Usage: uv run python scripts/sync_erp.py [--full] [--erp http://localhost:8100]
"""

import argparse
import asyncio
import time

import asyncpg

from ledgerline_api import erp_sync
from ledgerline_api.settings import settings


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--erp", default=settings.erp_base_url)
    args = parser.parse_args()
    settings.erp_base_url = args.erp
    if args.full:
        conn = await asyncpg.connect(settings.database_url.replace("postgresql+asyncpg", "postgresql"))
        await conn.execute("DELETE FROM erp_sync_state")
        await conn.close()
    started = time.perf_counter()
    result = await erp_sync.run()
    if result.skipped:
        print("another sync is running; skipped")
        return
    for report in result.reports:
        print(report)
    print(f"took {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
