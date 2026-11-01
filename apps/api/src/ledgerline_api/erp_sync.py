"""sync_erp: copy purchase orders and goods receipts from the ERP into Postgres (ADR 0012).

Each list is walked page by page. Every page is one transaction: upsert its records, save the ERP's cursor for
the next page and how far the data is synced, then commit. A run that crashes resumes from the saved cursor;
a run that finds its cursor expired (410) starts a new walk with `updated_since` = how far it got.

A record is written only when the ERP's updated_at is newer than the stored one, so replaying a page, or an
old version arriving late, never overwrites newer data. Purchase orders are walked before receipts; a
receipt is linked by PO number, so one arriving before its PO is still stored.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
from sqlalchemy import String, cast, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from ledgerline_api import service, vendors
from ledgerline_api.db import ErpSyncState, GoodsReceipt, MatchResult, OutboxMessage, PoLine, PurchaseOrder, ReceiptLine
from ledgerline_api.errors import PermanentError, TransientError
from ledgerline_api.normalize import normalize_tax_id, po_number_key
from ledgerline_api.settings import settings

log = logging.getLogger("ledgerline.erp_sync")
RESOURCES = ("purchase-orders", "receipts")


class CursorExpired(Exception):
    pass


@dataclass
class Report:
    resource: str
    pages: int = 0
    seen: int = 0
    written: int = 0  # new, or newer than what we had
    rate_limited: int = 0
    restarts: int = 0  # new walks after an expired cursor
    rematch_queued: int = 0
    resumed: bool = False  # started from a cursor a previous run saved

    def __str__(self) -> str:
        return (f"{self.resource}: {self.pages} pages, {self.seen} records, {self.written} written, "
                f"{self.rate_limited} rate-limited, {self.restarts} restarts, {self.rematch_queued} re-matches queued"
                + (", resumed from saved cursor" if self.resumed else ""))


@dataclass
class RunResult:
    skipped: bool = False
    reports: list[Report] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


async def fetch_page(client: httpx.AsyncClient, resource: str, cursor: str | None, since: datetime | None,
                     report: Report) -> dict:
    """One page, waiting out 429s as Retry-After says. Raises CursorExpired on 410."""
    params: dict[str, str | int] = {"limit": settings.erp_page_size}
    if cursor is not None:
        params["cursor"] = cursor
    elif since is not None:
        params["updated_since"] = since.isoformat()
    rate_limited = 0
    while True:
        try:
            response = await client.get(f"/erp/{resource}", params=params)
        except httpx.TransportError as exc:
            raise TransientError("erp_unavailable", f"{type(exc).__name__}: {exc}") from exc
        if response.status_code == 429:
            rate_limited += 1
            report.rate_limited += 1
            if rate_limited > settings.erp_max_rate_limited:
                raise TransientError("erp_rate_limited", f"{rate_limited} rate-limited answers in a row")
            # Retry-After may also be an HTTP date (RFC 9110); the ERP sends seconds, anything else waits 1 s.
            wait = response.headers.get("Retry-After", "1")
            await asyncio.sleep(min(int(wait) if wait.isdigit() else 1, settings.erp_retry_after_cap_s))
            continue
        if response.status_code == 410:
            raise CursorExpired
        if response.status_code >= 500:
            raise TransientError("erp_unavailable", f"HTTP {response.status_code}")
        if response.status_code != 200:
            raise PermanentError("erp_rejected_request", f"HTTP {response.status_code}: {response.text[:200]}")
        return response.json()


def _updated_at(record: dict) -> datetime:
    return datetime.fromisoformat(record["updated_at"])


async def _upsert(session: AsyncSession, model, values: list[dict]) -> dict[str, object]:
    """Insert the records, or update the stored ones the ERP has changed since. Returns {erp_id: id} for the
    rows written: Postgres returns no row for a conflict whose WHERE is false (an older or same version)."""
    statement = insert(model).values(values)
    upsert = statement.on_conflict_do_update(
        index_elements=["erp_id"],
        set_={name: statement.excluded[name] for name in values[0] if name != "erp_id"},
        where=model.erp_updated_at < statement.excluded.erp_updated_at,
    ).returning(model.erp_id, model.id)
    return dict((await session.execute(upsert)).all())


async def _store_purchase_orders(session: AsyncSession, records: list[dict]) -> tuple[int, set[str]]:
    """Returns how many records were written and the PO numbers (keys) they touched."""
    vendor_ids: dict[tuple, object] = {}
    rows = []
    for record in records:
        tax_id = normalize_tax_id(record["vendor"]["tax_id"]) if record["vendor"].get("tax_id") else None
        who = (tax_id, record["vendor"]["name"])
        if who not in vendor_ids:
            vendor_ids[who] = await vendors.find_or_create(session, *who)
        rows.append(dict(
            erp_id=record["erp_id"], po_number=record["po_number"], po_number_key=po_number_key(record["po_number"]),
            vendor_id=vendor_ids[who], currency=record["currency"], status=record["status"],
            erp_updated_at=_updated_at(record), synced_at=_now(),
        ))
    written = await _upsert(session, PurchaseOrder, rows)
    if written:
        # A newer PO version replaces its lines wholesale.
        await session.execute(delete(PoLine).where(PoLine.purchase_order_id.in_(written.values())))
        await session.execute(insert(PoLine).values([
            dict(purchase_order_id=written[record["erp_id"]], line_no=line["line_no"], description=line["description"],
                 quantity=Decimal(line["quantity"]), unit_price=Decimal(line["unit_price"]))
            for record in records if record["erp_id"] in written for line in record["lines"]
        ]))
    return len(written), {row["po_number_key"] for row in rows if row["erp_id"] in written}


async def _store_receipts(session: AsyncSession, records: list[dict]) -> tuple[int, set[str]]:
    rows = [dict(
        erp_id=record["erp_id"], po_number_key=po_number_key(record["po_number"]),
        received_on=date.fromisoformat(record["received_on"]), erp_updated_at=_updated_at(record), synced_at=_now(),
    ) for record in records]
    written = await _upsert(session, GoodsReceipt, rows)
    if written:
        await session.execute(delete(ReceiptLine).where(ReceiptLine.goods_receipt_id.in_(written.values())))
        await session.execute(insert(ReceiptLine).values([
            dict(goods_receipt_id=written[record["erp_id"]], line_no=line["line_no"], po_line_no=line["po_line_no"],
                 quantity=Decimal(line["quantity"]))
            for record in records if record["erp_id"] in written for line in record["lines"]
        ]))
    return len(written), {row["po_number_key"] for row in rows if row["erp_id"] in written}


STORE = {"purchase-orders": _store_purchase_orders, "receipts": _store_receipts}


async def _queue_rematches(session: AsyncSession, po_keys: set[str]) -> int:
    """Invoices whose match failed may match now that their PO or receipt changed: queue them again, in the
    same transaction as the page, so a crash can't lose the re-match. One already waiting isn't queued twice."""
    if not po_keys:
        return 0
    already_queued = select(OutboxMessage.id).where(
        OutboxMessage.published_at.is_(None), OutboxMessage.task_name == service.MATCH_TASK,
        OutboxMessage.payload["invoice_id"].astext == cast(MatchResult.invoice_id, String),
    )
    waiting = (await session.execute(
        select(MatchResult.invoice_id).where(
            MatchResult.status == "exception", MatchResult.po_number_key.in_(po_keys), ~already_queued.exists(),
        )
    )).scalars().all()
    for invoice_id in waiting:
        service.enqueue_match(session, invoice_id)
    return len(waiting)


async def sync_resource(session: AsyncSession, client: httpx.AsyncClient, resource: str) -> Report:
    report = Report(resource)
    await session.execute(insert(ErpSyncState).values(resource=resource).on_conflict_do_nothing())
    state = await session.get(ErpSyncState, resource)
    assert state is not None  # inserted just above if it wasn't there
    report.resumed = state.cursor is not None
    await session.commit()
    while True:
        try:
            page = await fetch_page(client, resource, state.cursor, state.synced_through, report)
        except CursorExpired:
            # Everything up to synced_through is stored, so a new walk from there loses nothing.
            log.warning("%s: cursor expired; new walk with updated_since=%s", resource, state.synced_through)
            report.restarts += 1
            state.cursor = None
            await session.commit()
            continue
        records = page["data"]
        report.pages += 1
        report.seen += len(records)
        if records:
            written, po_keys = await STORE[resource](session, records)
            report.written += written
            newest = max(_updated_at(record) for record in records)
            state.synced_through = max(state.synced_through or newest, newest)
            report.rematch_queued += await _queue_rematches(session, po_keys)
        state.cursor = page["next_cursor"]
        state.updated_at = _now()
        if state.cursor is None:
            state.last_success_at = state.updated_at
        await session.commit()
        if state.cursor is None:
            return report


async def run(client: httpx.AsyncClient | None = None) -> RunResult:
    """One sync of every ERP list. Skips if another run holds the lock (beat fired while a slow run was
    still going, or a crashed run's message was redelivered next to a new one)."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    own_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.erp_base_url, timeout=settings.erp_timeout_s)
    try:
        # A session-level advisory lock lives as long as this one connection, across the per-page commits,
        # and is released by Postgres if the worker dies.
        async with engine.connect() as conn:
            got_lock = (await conn.execute(select(func.pg_try_advisory_lock(func.hashtext("ledgerline.sync_erp"))))).scalar_one()
            await conn.commit()
            if not got_lock:
                return RunResult(skipped=True)
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                reports = [await sync_resource(session, client, resource) for resource in RESOURCES]
            await conn.execute(text("SELECT pg_advisory_unlock(hashtext('ledgerline.sync_erp'))"))
            await conn.commit()
            return RunResult(reports=reports)
    finally:
        if own_client:
            await client.aclose()
        await engine.dispose()
