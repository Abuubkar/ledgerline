"""Outbox relay: publishes jobs that committed transactions wrote to the outbox table. Run with:

    python -m ledgerline_api.relay

Delivery is at-least-once: if the relay dies after publishing but before marking a row, the job is published
again, which the jobs tolerate (extraction and matching are idempotent). A publish the broker refuses (queue full under
`overflow: reject-publish`, or the broker down) leaves the row unpublished for the next pass.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ledgerline_api.db import OutboxMessage
from ledgerline_api.service import OUTBOX_QUEUES
from ledgerline_api.settings import settings

log = logging.getLogger("ledgerline.relay")
BATCH = 100


async def publish_pending(sessions: async_sessionmaker, send: Callable[[OutboxMessage], None]) -> int:
    """Publish one batch. SKIP LOCKED lets several relays run side by side without publishing a row twice."""
    async with sessions() as session:
        rows = list(
            (
                await session.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.published_at.is_(None))
                    .order_by(OutboxMessage.id)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        published = 0
        for row in rows:
            try:
                # Celery's publish is blocking; with confirm_publish it returns only once the broker has the message.
                await asyncio.to_thread(send, row)
            except Exception:
                log.exception("publish failed for outbox %s; will retry", row.id)
                break
            row.published_at = datetime.now(UTC)
            published += 1
        await session.commit()
        return published


def celery_send(row: OutboxMessage) -> None:
    from ledgerline_api.worker import app

    # The outbox id doubles as the task id, so a republished job is recognisable in logs.
    app.send_task(row.task_name, kwargs=row.payload, task_id=str(row.id), queue=OUTBOX_QUEUES[row.task_name])


async def run_forever() -> None:
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    log.info("outbox relay started")
    idle_wait = 0.5
    while True:
        try:
            published = await publish_pending(sessions, celery_send)
        except Exception:
            log.exception("relay pass failed")
            published = 0
        if published:
            log.info("published %d job(s)", published)
            idle_wait = 0.5
        else:
            await asyncio.sleep(idle_wait)
            idle_wait = min(idle_wait * 2, 5.0)  # back off while idle or while the broker refuses


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run_forever())
