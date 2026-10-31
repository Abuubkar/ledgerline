"""Service tests for the ERP sync and matching: the ERP mock in-process, a real Postgres in a container. These
are the cases that would lose, duplicate or overwrite data if they broke."""

import asyncio
import copy
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, text

from ledgerline_api import erp_sync, jobs
from ledgerline_api.db import ErpSyncState, Invoice, InvoiceLine, OutboxMessage, PoLine, PurchaseOrder, Vendor
from ledgerline_api.errors import TransientError
from ledgerline_api.service import MATCH_TASK
from ledgerline_erp_mock.main import Faults, create_app

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

START = datetime(2026, 1, 1, tzinfo=UTC)
VENDOR = {"tax_id": "DE812345678", "name": "ACME GmbH"}


def purchase_order(n: int, price: str = "10.00", updated: timedelta = timedelta(0)) -> dict:
    return {
        "erp_id": f"PO-{n:06d}", "po_number": str(4_500_000_000 + n), "vendor": VENDOR, "currency": "EUR",
        "status": "open", "updated_at": (START + timedelta(minutes=n) + updated).isoformat(),
        "lines": [{"line_no": 1, "description": "Widget", "quantity": "4", "unit_price": price},
                  {"line_no": 2, "description": "Gadget", "quantity": "2", "unit_price": "5.00"}],
    }


def receipt(n: int, widgets: str = "4") -> dict:
    return {
        "erp_id": f"GR-{n:06d}", "po_number": str(4_500_000_000 + n), "received_on": "2026-02-01",
        "updated_at": (START + timedelta(days=40, minutes=n)).isoformat(),
        "lines": [{"line_no": 1, "po_line_no": 1, "quantity": widgets}, {"line_no": 2, "po_line_no": 2, "quantity": "2"}],
    }


SEVEN_PAGES = {"purchase_orders": [purchase_order(n) for n in range(1, 651)], "receipts": [receipt(n) for n in range(1, 31)]}


class CrashOnPage(httpx.ASGITransport):
    """The ERP mock over ASGI; the `crash_on`-th purchase-order request fails like a dropped connection."""

    def __init__(self, app, crash_on: int | None = None):
        super().__init__(app=app)
        self.crash_on, self.po_requests = crash_on, 0

    async def handle_async_request(self, request):
        if request.url.path == "/erp/purchase-orders":
            self.po_requests += 1
            if self.po_requests == self.crash_on:
                raise httpx.ConnectError("injected crash", request=request)
        return await super().handle_async_request(request)


def erp(transport: httpx.ASGITransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, base_url="http://erp")


async def counts(client) -> tuple[int, int]:
    async with client.sessions() as session:
        orders = (await session.execute(select(func.count()).select_from(PurchaseOrder))).scalar_one()
        lines = (await session.execute(select(func.count()).select_from(PoLine))).scalar_one()
        return orders, lines


async def test_sync_resumes_from_the_saved_cursor_after_a_crash_on_page_3_of_7(client):
    mock = create_app(copy.deepcopy(SEVEN_PAGES), Faults(error_rate=0))

    with pytest.raises(TransientError):
        await erp_sync.run(erp(CrashOnPage(mock, crash_on=3)))
    assert await counts(client) == (200, 400)  # pages 1 and 2 committed, with their cursor
    async with client.sessions() as session:
        assert (await session.get(ErpSyncState, "purchase-orders")).cursor is not None

    transport = CrashOnPage(mock)
    result = await erp_sync.run(erp(transport))
    orders, receipts = result.reports
    assert orders.resumed and (orders.pages, orders.written) == (5, 450)  # pages 3–7 only
    assert transport.po_requests == 5
    assert await counts(client) == (650, 1300)
    assert receipts.written == 30
    first_request = next(query for path, query, _ in mock.state.requests[2:] if path == "/erp/purchase-orders")
    assert "cursor" in first_request  # the resumed walk continued, it didn't start over


async def test_expired_cursor_restarts_the_walk_from_how_far_it_got(client):
    mock = create_app(copy.deepcopy(SEVEN_PAGES), Faults(error_rate=0, cursor_ttl_s=1))
    with pytest.raises(TransientError):
        await erp_sync.run(erp(CrashOnPage(mock, crash_on=3)))
    async with client.sessions() as session:
        synced_through = (await session.get(ErpSyncState, "purchase-orders")).synced_through
    assert synced_through == datetime.fromisoformat(SEVEN_PAGES["purchase_orders"][199]["updated_at"])

    await asyncio.sleep(1.5)  # the saved cursor expires
    mock.state.requests.clear()
    result = await erp_sync.run(erp(CrashOnPage(mock)))

    assert result.reports[0].restarts == 1
    statuses = [status for path, _, status in mock.state.requests if path == "/erp/purchase-orders"]
    assert statuses[0] == 410
    restart = mock.state.requests[1][1]
    assert "cursor" not in restart and datetime.fromisoformat(restart["updated_since"]) == synced_through
    assert await counts(client) == (650, 1300)


async def test_only_a_newer_erp_version_overwrites_what_is_stored(client):
    dataset = {"purchase_orders": [purchase_order(1), purchase_order(2)], "receipts": []}
    await erp_sync.run(erp(CrashOnPage(create_app(copy.deepcopy(dataset)))))

    # PO 1 changed in the ERP (newer updated_at); PO 2 arrives again as the same version with another price,
    # like a stale replica answering. A full re-read must apply only the first.
    dataset["purchase_orders"] = [purchase_order(1, price="12.00", updated=timedelta(days=1)),
                                  purchase_order(2, price="99.00")]
    async with client.sessions() as session:
        await session.execute(text("DELETE FROM erp_sync_state"))
        await session.commit()
    result = await erp_sync.run(erp(CrashOnPage(create_app(copy.deepcopy(dataset)))))

    assert result.reports[0].written == 1
    async with client.sessions() as session:
        prices = dict((await session.execute(
            select(PurchaseOrder.erp_id, PoLine.unit_price).join(PoLine).where(PoLine.line_no == 1)
        )).all())
    assert prices == {"PO-000001": Decimal("12.00"), "PO-000002": Decimal("10.00")}


async def test_invoice_waiting_for_its_po_is_rematched_when_the_sync_brings_it(client):
    async with client.sessions() as session:
        vendor = Vendor(tax_id=VENDOR["tax_id"], name=VENDOR["name"], name_key="acme gmbh")
        session.add(vendor)
        await session.flush()
        invoice = Invoice(
            status="extracted", original_filename="a.pdf", file_path="s3://invoices/a.pdf", vendor_id=vendor.id,
            invoice_number="A-1", po_number="PO 4500000001", currency="EUR", invoice_date=date(2026, 2, 3),
            lines=[InvoiceLine(page_no=1, line_no=1, description="Widget", quantity=Decimal(4), unit_price=Decimal("10.00"),
                               amount_minor=4000),
                   InvoiceLine(page_no=1, line_no=2, description="gadget", quantity=Decimal(2), unit_price=Decimal("5.00"),
                               amount_minor=1000)],
        )
        session.add(invoice)
        await session.commit()
        invoice_id = invoice.id

    assert await jobs.match(invoice_id) == "exception"  # the PO hasn't been synced yet
    invoice = (await client.get(f"/v1/invoices/{invoice_id}")).json()
    assert [r["code"] for r in invoice["match"]["reasons"]] == ["po_not_found"]

    result = await erp_sync.run(erp(CrashOnPage(create_app({"purchase_orders": [purchase_order(1)], "receipts": [receipt(1)]}))))
    assert result.reports[0].rematch_queued == 1  # queued in the same transaction as the page that brought the PO
    async with client.sessions() as session:
        queued = (await session.execute(select(OutboxMessage).where(OutboxMessage.task_name == MATCH_TASK))).scalars().all()
    assert [m.payload["invoice_id"] for m in queued] == [str(invoice_id)]

    assert await jobs.match(invoice_id) == "matched"
    invoice = (await client.get(f"/v1/invoices/{invoice_id}")).json()
    assert invoice["status"] == "matched" and invoice["match"]["reasons"] == []
    assert invoice["match"]["purchase_order_id"] is not None
    assert await jobs.match(invoice_id) == "skipped"  # a duplicate delivery changes nothing


async def test_two_partial_receipts_add_up_and_a_short_one_is_an_exception(client):
    async with client.sessions() as session:
        vendor = Vendor(tax_id=VENDOR["tax_id"], name=VENDOR["name"], name_key="acme gmbh")
        session.add(vendor)
        await session.flush()
        ids = []
        for n in (1, 2):
            invoice = Invoice(
                status="extracted", original_filename=f"{n}.pdf", file_path=f"s3://invoices/{n}.pdf", vendor_id=vendor.id,
                invoice_number=f"A-{n}", po_number=str(4_500_000_000 + n), currency="EUR",
                lines=[InvoiceLine(page_no=1, line_no=1, description="Widget", quantity=Decimal(4),
                                   unit_price=Decimal("10.00"), amount_minor=4000),
                       InvoiceLine(page_no=1, line_no=2, description="Gadget", quantity=Decimal(2),
                                   unit_price=Decimal("5.00"), amount_minor=1000)],
            )
            session.add(invoice)
            await session.flush()
            ids.append(invoice.id)
        await session.commit()
    first_half, second_half = receipt(1, widgets="1"), receipt(1, widgets="3")
    second_half["erp_id"], second_half["lines"] = "GR-000099", second_half["lines"][:1]
    first_half["lines"][0]["quantity"] = "1"
    dataset = {"purchase_orders": [purchase_order(1), purchase_order(2)], "receipts": [first_half, second_half, receipt(2, widgets="3")]}
    await erp_sync.run(erp(CrashOnPage(create_app(dataset))))

    assert await jobs.match(ids[0]) == "matched"  # 1 + 3 widgets received over two receipts
    assert await jobs.match(ids[1]) == "exception"
    invoice = (await client.get(f"/v1/invoices/{ids[1]}")).json()
    assert invoice["match"]["reasons"] == [{"code": "short_shipment", "detail": "billed 4, received 3", "line": "page 1 line 1"}]
    assert uuid.UUID(invoice["match"]["purchase_order_id"])
