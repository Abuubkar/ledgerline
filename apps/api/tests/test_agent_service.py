"""Service tests for the agent and the approval flow against a real Postgres: the cases where a wrong answer
writes, double-decides or loses a proposal. The model is scripted."""

import asyncio
import contextlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from ledgerline_api import agent
from ledgerline_api.db import (
    AgentRun,
    AgentStep,
    GoodsReceipt,
    Invoice,
    InvoiceLine,
    MatchResult,
    PendingAction,
    PoLine,
    PurchaseOrder,
    ReceiptLine,
    Vendor,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def exception_invoice(client, unit_price="10.30", amount=4120) -> uuid.UUID:
    """An invoice billing 4 widgets at `unit_price` against a PO at 10.00, all 4 received: in exception."""
    async with client.sessions() as session:
        vendor = Vendor(tax_id="DE812345678", name="ACME GmbH", name_key="acme gmbh")
        session.add(vendor)
        await session.flush()
        order = PurchaseOrder(erp_id="PO-1", po_number="4500000001", po_number_key="4500000001", vendor_id=vendor.id,
                              currency="EUR", status="open", erp_updated_at=datetime(2026, 1, 1, tzinfo=UTC))
        session.add(order)
        await session.flush()
        session.add(PoLine(purchase_order_id=order.id, line_no=1, description="Widget", quantity=Decimal(4),
                           unit_price=Decimal("10.00")))
        receipt = GoodsReceipt(erp_id="GR-1", po_number_key="4500000001", received_on=date(2026, 1, 9),
                               erp_updated_at=datetime(2026, 1, 9, tzinfo=UTC))
        session.add(receipt)
        await session.flush()
        session.add(ReceiptLine(goods_receipt_id=receipt.id, line_no=1, po_line_no=1, quantity=Decimal(4)))
        invoice = Invoice(
            status="exception", original_filename="a.pdf", file_path="s3://invoices/a.pdf", vendor_id=vendor.id,
            invoice_number="A-1", po_number="PO 4500000001", currency="EUR", total_minor=amount,
            lines=[InvoiceLine(page_no=1, line_no=1, description="Widget", quantity=Decimal(4),
                               unit_price=Decimal(unit_price), amount_minor=amount)],
        )
        session.add(invoice)
        await session.flush()
        session.add(MatchResult(invoice_id=invoice.id, status="exception", po_number_key="4500000001",
                                purchase_order_id=order.id, reasons=[{"code": "price_variance", "line": "page 1 line 1",
                                                                      "detail": "unit price 10.30 vs PO 10.00"}]))
        await session.commit()
        return invoice.id


def call(name, **arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def scripted(*responses):
    replies = iter(responses)

    async def chat(messages, timeout_s):
        reply = next(replies)
        return SimpleNamespace(content=None, tool_calls=reply), 100, 10, 5

    return chat


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    @contextlib.asynccontextmanager
    async def free_slot(_redis):
        yield

    monkeypatch.setattr(agent, "llm_slot", free_slot)


async def test_agent_proposes_a_credit_memo_for_exactly_what_was_over_billed(client):
    invoice_id = await exception_invoice(client)
    chat = scripted(
        [call("get_po", po_number="4500000001")],
        [call("get_receipts", po_number="4500000001")],
        [call("compute_variance")],
        # The model names the lines; it has no way to name the amount.
        [call("draft_credit_memo_request", lines=["page 1 line 1"], reason="billed 10.30 against PO price 10.00")],
    )
    assert await agent.run(invoice_id, chat=chat) == "proposed"

    actions = (await client.get(f"/v1/invoices/{invoice_id}/pending-actions")).json()["data"]
    assert len(actions) == 1
    assert actions[0]["action_type"] == "credit_memo_request" and actions[0]["status"] == "pending"
    assert actions[0]["details"]["amount_minor"] == 120 and actions[0]["details"]["currency"] == "EUR"
    async with client.sessions() as session:
        run = (await session.execute(select(AgentRun).where(AgentRun.invoice_id == invoice_id))).scalar_one()
        steps = (await session.execute(select(AgentStep).where(AgentStep.run_id == run.id))).scalars().all()
    assert (run.status, run.stop_reason, run.tool_turns, run.guard_fires) == ("proposed", "proposed", 4, 0)
    assert [s.tool_name for s in steps if s.kind == "tool"] == [
        "get_po", "get_receipts", "compute_variance", "draft_credit_memo_request"]
    assert steps[1].result["same_vendor_as_invoice"] is True

    # One proposal waiting is enough: a second run (a duplicate delivery) does nothing.
    assert await agent.run(invoice_id, chat=scripted()) == "skipped"


async def test_agent_never_writes_anything_but_a_pending_action(client):
    invoice_id = await exception_invoice(client)
    chat = scripted([call("propose_hold", reason_code="price_variance", explanation="price above PO")])
    await agent.run(invoice_id, chat=chat)
    invoice = (await client.get(f"/v1/invoices/{invoice_id}")).json()
    assert invoice["status"] == "exception"  # unchanged until a person decides, and even then (for now)


async def test_two_concurrent_approvals_with_the_same_version_exactly_one_wins(client):
    invoice_id = await exception_invoice(client)
    await agent.run(invoice_id, chat=scripted([call("propose_hold", reason_code="other", explanation="check")]))
    action = (await client.get(f"/v1/invoices/{invoice_id}/pending-actions")).json()["data"][0]
    got = await client.get(f"/v1/pending-actions/{action['id']}")
    assert got.headers["ETag"] == '"1"'

    approve = lambda: client.post(f"/v1/pending-actions/{action['id']}:approve", headers={"If-Match": '"1"'},  # noqa: E731
                                  json={"note": "ok"})
    first, second = await asyncio.gather(approve(), approve())
    assert sorted([first.status_code, second.status_code]) == [200, 412]
    loser = second if second.status_code == 412 else first
    assert loser.json()["code"] == "version_conflict" and loser.json()["current_version"] == 2
    winner = first if first.status_code == 200 else second
    assert winner.headers["ETag"] == '"2"' and winner.json()["status"] == "approved"

    # Deciding again at the current version: it's no longer pending.
    again = await client.post(f"/v1/pending-actions/{action['id']}:reject", headers={"If-Match": '"2"'})
    assert again.status_code == 409 and again.json()["code"] == "action_already_decided"
    missing = await client.post(f"/v1/pending-actions/{action['id']}:reject")
    assert missing.status_code == 428
    async with client.sessions() as session:
        row = await session.get(PendingAction, uuid.UUID(action["id"]))
    assert (row.status, row.version, row.decision_note) == ("approved", 2, "ok")


QUEUE = """
query Queue($after: String) {
  exceptionsQueue(first: 10, after: $after) {
    edges { node { id invoiceNumber vendor { name } lines { description unitPrice amount { amountMinor } }
                   match { reasons { code } }
                   pendingAction { id version actionType details }
                   agentRuns { stopReason steps { toolName } } } }
    pageInfo { hasNextPage endCursor }
  }
}"""

APPROVE = """
mutation Approve($id: UUID!, $version: Int!) {
  approvePendingAction(id: $id, expectedVersion: $version) {
    __typename
    ... on DecisionSuccess { pendingAction { status version } }
    ... on VersionConflict { currentVersion pendingAction { status } }
    ... on NotFound { id }
  }
}"""


async def test_graphql_queue_shows_the_evidence_and_a_stale_approval_is_a_version_conflict(client):
    invoice_id = await exception_invoice(client)
    await agent.run(invoice_id, chat=scripted([call("propose_hold", reason_code="price_variance", explanation="price above PO")]))

    data = (await client.post("/graphql", json={"query": QUEUE})).json()["data"]["exceptionsQueue"]
    node = data["edges"][0]["node"]
    assert node["vendor"]["name"] == "ACME GmbH" and node["lines"][0]["unitPrice"] == "10.3"
    assert node["match"]["reasons"][0]["code"] == "price_variance"
    assert node["pendingAction"]["actionType"] == "hold" and node["agentRuns"][0]["steps"][1]["toolName"] == "propose_hold"

    action_id = node["pendingAction"]["id"]
    ok = (await client.post("/graphql", json={"query": APPROVE, "variables": {"id": action_id, "version": 1}})).json()
    assert ok["data"]["approvePendingAction"] == {"__typename": "DecisionSuccess",
                                                  "pendingAction": {"status": "approved", "version": 2}}
    stale = (await client.post("/graphql", json={"query": APPROVE, "variables": {"id": action_id, "version": 1}})).json()
    assert stale["data"]["approvePendingAction"] == {"__typename": "VersionConflict", "currentVersion": 2,
                                                     "pendingAction": {"status": "approved"}}
    missing = (await client.post("/graphql", json={"query": APPROVE,
                                                  "variables": {"id": str(uuid.uuid4()), "version": 1}})).json()
    assert missing["data"]["approvePendingAction"]["__typename"] == "NotFound"
