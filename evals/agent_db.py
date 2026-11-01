"""A throwaway Postgres for the agent eval, and seeding one scenario into it.

Each scenario's rows get fixed ids (derived from the scenario id), so the agent sees byte-identical tool results in
every run: that's what lets a recorded live run replay offline.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ledgerline_api.db import (
    GoodsReceipt,
    Invoice,
    InvoiceLine,
    MatchResult,
    PoLine,
    PurchaseOrder,
    ReceiptLine,
    Vendor,
)
from ledgerline_api.normalize import invoice_number_key, po_number_key, vendor_name_key
from ledgerline_api.settings import settings

REPO = Path(__file__).resolve().parents[1]
NAMESPACE = uuid.UUID("6f1d3c2a-6b8e-4c4f-9f0e-2a7d5b1e9c30")


def fixed_id(scenario_id: str, role: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{scenario_id}/{role}")


def start_database():
    """Start Postgres 18 in a container, migrate it, and point the app's settings at it. Returns the container."""
    from alembic import command
    from alembic.config import Config
    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer("postgres:18.6", driver="asyncpg").start()
    settings.database_url = container.get_connection_url()
    command.upgrade(Config(str(REPO / "alembic.ini")), "head")
    return container


async def seed(scenario: dict) -> uuid.UUID:
    """Empty the tables and write the scenario's vendor, PO, receipts, history and invoice. Returns the invoice id."""
    sid = scenario["id"]
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    inv = scenario["invoice"]
    created = datetime(2026, 10, 20, tzinfo=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE invoices, vendors, purchase_orders, goods_receipts, agent_runs, pending_actions, outbox CASCADE"))
    async with sessions() as session:
        def vendor_row(v: dict, role: str) -> Vendor:
            return Vendor(id=fixed_id(sid, role), tax_id=v["tax_id"], name=v["name"], name_key=vendor_name_key(v["name"]), created_at=created)

        vendor = vendor_row(inv["vendor"], "vendor")
        session.add(vendor)
        await session.flush()
        po = scenario.get("purchase_order")
        po_id = None
        if po:
            po_vendor = vendor if po["vendor"]["tax_id"] == inv["vendor"]["tax_id"] else vendor_row(po["vendor"], "po-vendor")
            if po_vendor is not vendor:
                session.add(po_vendor)
            await session.flush()  # vendors first: purchase_orders references them without an ORM relationship
            po_id = fixed_id(sid, "po")
            session.add(PurchaseOrder(id=po_id, erp_id=f"PO-{sid}", po_number=po["po_number"], po_number_key=po_number_key(po["po_number"]),
                                      vendor_id=po_vendor.id, currency=po["currency"], status="open", erp_updated_at=created, synced_at=created))
            await session.flush()
            for line in po["lines"]:
                session.add(PoLine(id=fixed_id(sid, f"po-line-{line['line_no']}"), purchase_order_id=po_id, line_no=line["line_no"],
                                   description=line["description"], quantity=Decimal(line["quantity"]), unit_price=Decimal(line["unit_price"])))
        for n, receipt in enumerate(scenario.get("receipts") or [], start=1):
            receipt_id = fixed_id(sid, f"receipt-{n}")
            session.add(GoodsReceipt(id=receipt_id, erp_id=f"GR-{sid}-{n}", po_number_key=po_number_key(inv["po_number"]),
                                     received_on=date.fromisoformat(receipt["received_on"]), erp_updated_at=created, synced_at=created))
            await session.flush()
            for k, line in enumerate(receipt["lines"], start=1):
                session.add(ReceiptLine(id=fixed_id(sid, f"receipt-{n}-line-{k}"), goods_receipt_id=receipt_id, line_no=k,
                                        po_line_no=line["po_line_no"], quantity=Decimal(line["quantity"])))
        for n, past in enumerate(scenario.get("history") or []):
            session.add(Invoice(id=uuid.UUID(past["id"]) if past.get("id") else fixed_id(sid, f"history-{n}"), status=past["status"],
                                original_filename=f"{past['invoice_number']}.pdf", file_path="s3://invoices/eval.pdf", vendor_id=vendor.id,
                                invoice_number=past["invoice_number"], invoice_number_key=invoice_number_key(past["invoice_number"]),
                                currency=inv["currency"], total_minor=past["total_minor"], invoice_date=date(2026, 9, 1),
                                created_at=datetime(2026, 9, 2, tzinfo=UTC)))
        invoice_id = fixed_id(sid, "invoice")
        session.add(Invoice(
            id=invoice_id, status=inv["status"], original_filename=f"{sid}.pdf", file_path="s3://invoices/eval.pdf", page_count=1,
            vendor_id=vendor.id, invoice_number=inv["invoice_number"], po_number=inv["po_number"], currency=inv["currency"],
            invoice_date=date.fromisoformat(inv["invoice_date"]), due_date=date.fromisoformat(inv["due_date"]),
            subtotal_minor=inv["subtotal_minor"], tax_minor=inv["tax_minor"], total_minor=inv["total_minor"],
            invalid_fields=inv["invalid_fields"], created_at=created,
            lines=[InvoiceLine(id=fixed_id(sid, f"line-{n}"), page_no=1, line_no=n, description=l["description"], quantity=Decimal(l["quantity"]),
                               unit_price=Decimal(l["unit_price"]), amount_minor=l["amount_minor"]) for n, l in enumerate(inv["lines"], start=1)],
        ))
        await session.flush()
        if inv["match_reasons"]:
            session.add(MatchResult(id=fixed_id(sid, "match"), invoice_id=invoice_id, status="exception",
                                    po_number_key=po_number_key(inv["po_number"]), purchase_order_id=po_id,
                                    reasons=inv["match_reasons"], matched_at=created))
        await session.commit()
    await engine.dispose()
    return invoice_id
