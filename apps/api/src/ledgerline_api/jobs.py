"""The extraction job a worker runs for one invoice, and what happens when it gives up.

Safe to run twice for the same invoice. Each attempt claims the invoice by inserting a `running` row in
extraction_runs (a unique index allows only one), renews that lease while it works, and writes its results
only if the lease is still its own. A worker killed mid-job stops renewing; its lease lapses within
`extraction_lease_s` and the redelivered message takes over (ADR 0009).
"""

import asyncio
import enum
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ledgerline_api import storage
from ledgerline_api.db import DeadLetter, ExtractionRun, Invoice
from ledgerline_api.errors import PermanentError, TransientError, classify
from ledgerline_api.extraction import extract_header, read_pages
from ledgerline_api.semaphore import llm_slot
from ledgerline_api.settings import settings

TERMINAL = {"extracted", "failed"}


class Outcome(enum.Enum):
    COMPLETED = "completed"
    ALREADY_DONE = "already_done"  # a duplicate delivery of a job that already finished
    LEASE_LOST = "lease_lost"  # took too long; another attempt owns the invoice now


@asynccontextmanager
async def job_resources() -> AsyncIterator[tuple[async_sessionmaker, redis.Redis]]:
    """Fresh connections per job: each Celery task runs its own event loop (asyncio.run), and asyncpg and
    redis connections can't cross event loops."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    redis_client = redis.from_url(settings.redis_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False), redis_client
    finally:
        await redis_client.aclose()
        await engine.dispose()


def _now() -> datetime:
    return datetime.now(UTC)


async def _claim(sessions: async_sessionmaker, invoice_id: uuid.UUID, task_id: str, attempt: int) -> uuid.UUID | Outcome | float:
    """Returns the new run's id, ALREADY_DONE, or seconds to wait before trying again."""
    async with sessions() as session:
        invoice = (
            await session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update(skip_locked=True))
        ).scalar_one_or_none()
        if invoice is None:
            exists = await session.get(Invoice, invoice_id)
            if exists is None:
                raise PermanentError("invoice_not_found", f"no invoice {invoice_id}")
            return 1.0  # another worker is claiming it this instant
        if invoice.status in TERMINAL:
            return Outcome.ALREADY_DONE

        # A previous attempt whose worker died stops renewing; once its lease lapses it's abandoned.
        await session.execute(
            update(ExtractionRun)
            .where(ExtractionRun.invoice_id == invoice_id, ExtractionRun.outcome == "running",
                   ExtractionRun.lease_until < _now())
            .values(outcome="abandoned", finished_at=_now())
        )
        run = ExtractionRun(
            invoice_id=invoice_id, task_id=task_id, attempt=attempt, outcome="running",
            lease_until=_now() + timedelta(seconds=settings.extraction_lease_s),
        )
        session.add(run)
        invoice.status = "extracting"
        try:
            await session.commit()
        except IntegrityError:
            # Another attempt holds a live lease (a duplicate delivery). Wait for it to finish or lapse.
            await session.rollback()
            holder = (
                await session.execute(
                    select(ExtractionRun).where(ExtractionRun.invoice_id == invoice_id, ExtractionRun.outcome == "running")
                )
            ).scalar_one_or_none()
            return max(1.0, (holder.lease_until - _now()).total_seconds()) if holder else 1.0
        return run.id


async def _heartbeat(sessions: async_sessionmaker, run_id: uuid.UUID, lost: asyncio.Event) -> None:
    while True:
        await asyncio.sleep(settings.extraction_heartbeat_s)
        async with sessions() as session:
            result = await session.execute(
                update(ExtractionRun)
                .where(ExtractionRun.id == run_id, ExtractionRun.outcome == "running")
                .values(lease_until=_now() + timedelta(seconds=settings.extraction_lease_s))
            )
            await session.commit()
        if result.rowcount == 0:
            lost.set()
            return


async def _finish_run(session: AsyncSession, run_id: uuid.UUID, outcome: str, error=None) -> ExtractionRun | None:
    """Close our run if we still own it. Returns None if the lease was taken over."""
    run = (await session.execute(select(ExtractionRun).where(ExtractionRun.id == run_id).with_for_update())).scalar_one()
    if run.outcome != "running":
        return None
    run.outcome, run.finished_at = outcome, _now()
    if error is not None:
        run.error_code, run.error_detail = error.code, error.detail
    return run


async def extract(invoice_id: uuid.UUID, task_id: str, attempt: int) -> Outcome:
    """Run one extraction attempt. Raises TransientError (worth retrying) or PermanentError (dead-letter it)."""
    async with job_resources() as (sessions, redis_client):
        # Wait out a duplicate delivery's live lease, but not forever: at most two lease periods.
        deadline = _now() + timedelta(seconds=2 * settings.extraction_lease_s)
        while True:
            claimed = await _claim(sessions, invoice_id, task_id, attempt)
            if isinstance(claimed, uuid.UUID | Outcome):
                break
            if _now() > deadline:
                raise TransientError("invoice_busy", "another attempt kept a live lease on this invoice")
            await asyncio.sleep(min(claimed, 5.0))
        if claimed is Outcome.ALREADY_DONE:
            return claimed
        run_id = claimed

        lost = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat(sessions, run_id, lost))
        try:
            async with sessions() as session:
                file_uri = (await session.get(Invoice, invoice_id)).file_path
            content = await asyncio.to_thread(storage.get, file_uri)
            pages = await asyncio.to_thread(read_pages, content)
            async with llm_slot(redis_client):
                extraction = await extract_header(pages)
        except BaseException as exc:
            error = classify(exc) if isinstance(exc, Exception) else TransientError("cancelled", repr(exc))
            async with sessions() as session:
                outcome = "transient_failure" if isinstance(error, TransientError) else "permanent_failure"
                if await _finish_run(session, run_id, outcome, error) is not None and isinstance(error, TransientError):
                    # Visible as queued again until the retry runs.
                    await session.execute(update(Invoice).where(Invoice.id == invoice_id).values(status="received"))
                await session.commit()
            raise error from exc
        finally:
            heartbeat.cancel()

        async with sessions() as session:
            if lost.is_set() or await _finish_run(session, run_id, "completed") is None:
                await session.rollback()
                return Outcome.LEASE_LOST
            invoice = await session.get(Invoice, invoice_id)
            for name, value in asdict(extraction.header).items():
                setattr(invoice, name, value)
            invoice.status = "extracted"
            invoice.page_count = extraction.page_count
            invoice.model = extraction.model
            invoice.prompt_version = extraction.prompt_version
            invoice.prompt_tokens = extraction.prompt_tokens
            invoice.output_tokens = extraction.output_tokens
            invoice.llm_ms = extraction.llm_ms
            invoice.error_code = invoice.error_detail = None
            await session.commit()
        return Outcome.COMPLETED


async def dead_letter(task_name: str, payload: dict, error: TransientError | PermanentError, chain: str, attempts: int) -> None:
    """The job gave up: mark the invoice failed and record why, so it can be inspected and replayed."""
    invoice_id = uuid.UUID(payload["invoice_id"])
    async with job_resources() as (sessions, _):
        async with sessions() as session:
            invoice = await session.get(Invoice, invoice_id, with_for_update=True)
            if invoice is None or invoice.status == "extracted":
                return  # nothing to dead-letter: unknown invoice, or a duplicate delivery of a finished job
            invoice.status, invoice.error_code, invoice.error_detail = "failed", error.code, error.detail
            session.add(DeadLetter(
                task_name=task_name, invoice_id=invoice_id, payload=payload,
                error_code=error.code, exception_chain=chain, attempts=attempts,
            ))
            await session.commit()
