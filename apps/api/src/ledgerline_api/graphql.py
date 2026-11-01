"""GraphQL API for the reviewer UI: reads, plus approving or rejecting the agent's proposals. Resolvers call the
same service functions as REST (see ADR 0007). Related rows (vendors, lines, proposals, agent runs) are loaded
by per-request DataLoaders, one query per kind per request instead of one per invoice."""

import asyncio
import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, NewType, overload

import strawberry
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry import relay
from strawberry.dataloader import DataLoader
from strawberry.fastapi import BaseContext, GraphQLRouter
from strawberry.scalars import JSON
from strawberry.schema.config import StrawberryConfig

from ledgerline_api import service
from ledgerline_api.db import AgentRun as AgentRunRow
from ledgerline_api.db import GoodsReceipt as GoodsReceiptRow
from ledgerline_api.db import Invoice as InvoiceRow
from ledgerline_api.db import InvoiceLine as InvoiceLineRow
from ledgerline_api.db import PendingAction as PendingActionRow
from ledgerline_api.db import PurchaseOrder as PurchaseOrderRow
from ledgerline_api.db import Vendor as VendorRow
from ledgerline_api.db import get_session
from ledgerline_api.normalize import po_number_key
from ledgerline_api.schemas import ApiProblem, ProblemCode

# GraphQL Int is 32-bit: 2^31 cents is only $21.4M, too small for invoice totals. BigInt is serialized as a
# JSON number; JavaScript clients stay exact up to 2^53 minor units.
BigInt = NewType("BigInt", int)


def _parse_bigint(value: object) -> int:
    return int(str(value))


class Context(BaseContext):
    def __init__(self, session: AsyncSession):
        super().__init__()
        self.session = session
        # Resolvers run concurrently, but one AsyncSession runs one query at a time.
        self.lock = asyncio.Lock()
        self.vendors = DataLoader(load_fn=self._load_vendors)
        self.lines = DataLoader(load_fn=self._load_lines)
        self.pending_actions = DataLoader(load_fn=self._load_pending_actions)
        self.agent_runs = DataLoader(load_fn=self._load_agent_runs)
        self.purchase_orders = DataLoader(load_fn=self._load_purchase_orders)
        self.goods_receipts = DataLoader(load_fn=self._load_goods_receipts)

    async def _rows(self, query) -> list:
        async with self.lock:
            return list((await self.session.execute(query)).scalars())

    async def _load_vendors(self, ids: list[uuid.UUID]) -> list[VendorRow | None]:
        rows = {row.id: row for row in await self._rows(select(VendorRow).where(VendorRow.id.in_(ids)))}
        return [rows.get(i) for i in ids]

    async def _grouped(self, model, invoice_ids: list[uuid.UUID], *order) -> list[list]:
        groups = defaultdict(list)
        for row in await self._rows(select(model).where(model.invoice_id.in_(invoice_ids)).order_by(*order)):
            groups[row.invoice_id].append(row)
        return [groups[i] for i in invoice_ids]

    async def _load_lines(self, invoice_ids: list[uuid.UUID]) -> list[list[InvoiceLineRow]]:
        return await self._grouped(InvoiceLineRow, invoice_ids, InvoiceLineRow.page_no, InvoiceLineRow.line_no)

    async def _load_pending_actions(self, invoice_ids: list[uuid.UUID]) -> list[list[PendingActionRow]]:
        return await self._grouped(PendingActionRow, invoice_ids, PendingActionRow.id.desc())

    async def _load_agent_runs(self, invoice_ids: list[uuid.UUID]) -> list[list[AgentRunRow]]:
        return await self._grouped(AgentRunRow, invoice_ids, AgentRunRow.id.desc())

    # Purchase orders and receipts are found by the invoice's normalized PO number, as matching finds them.
    async def _load_purchase_orders(self, keys: list[str]) -> list[PurchaseOrderRow | None]:
        rows = {row.po_number_key: row for row in await self._rows(select(PurchaseOrderRow).where(PurchaseOrderRow.po_number_key.in_(keys)))}
        return [rows.get(k) for k in keys]

    async def _load_goods_receipts(self, keys: list[str]) -> list[list[GoodsReceiptRow]]:
        groups = defaultdict(list)
        query = select(GoodsReceiptRow).where(GoodsReceiptRow.po_number_key.in_(keys)).order_by(GoodsReceiptRow.received_on)
        for row in await self._rows(query):
            groups[row.po_number_key].append(row)
        return [groups[k] for k in keys]


async def get_context(session: AsyncSession = Depends(get_session)) -> Context:
    return Context(session)


@strawberry.type
class Money:
    amount_minor: BigInt
    currency: str


@strawberry.type
class Vendor:
    id: uuid.UUID
    name: str
    tax_id: str | None


@strawberry.type
class MatchReason:
    code: str
    detail: str
    line: str | None


@strawberry.type
class MatchResult:
    status: str
    purchase_order_id: uuid.UUID | None
    reasons: list[MatchReason]
    matched_at: datetime


@overload
def _decimal(value: Decimal) -> str: ...
@overload
def _decimal(value: Decimal | None) -> str | None: ...
def _decimal(value: Decimal | None) -> str | None:
    return format(value.normalize(), "f") if value is not None else None


@strawberry.type
class InvoiceLine:
    page_no: int
    line_no: int
    description: str | None
    quantity: str | None
    unit_price: str | None
    amount: Money | None
    invalid_reason: str | None


@strawberry.type
class PageResult:
    page_no: int
    status: str
    source: str = strawberry.field(description="text: read from the PDF's text layer; image: rendered and read visually (a scan).")
    error_code: str | None
    llm_ms: int | None


@strawberry.type
class PoLine:
    line_no: int
    description: str
    quantity: str
    unit_price: str


@strawberry.type(description="A purchase order as last synced from the ERP.")
class PurchaseOrder:
    id: uuid.UUID
    po_number: str
    status: str
    currency: str
    lines: list[PoLine]


@strawberry.type
class ReceiptLine:
    po_line_no: int
    quantity: str


@strawberry.type(description="Goods received against a purchase order.")
class GoodsReceipt:
    id: uuid.UUID
    received_on: date
    lines: list[ReceiptLine]


@strawberry.type
class AgentStep:
    step_no: int
    kind: str
    content: str | None
    tool_name: str | None
    arguments: JSON | None
    result: JSON | None
    error: str | None
    llm_ms: int | None


@strawberry.type
class AgentRun:
    id: uuid.UUID
    status: str
    stop_reason: str | None
    model: str
    prompt_version: str
    tool_turns: int
    guard_fires: int
    llm_ms: int
    started_at: datetime
    finished_at: datetime | None
    steps: list[AgentStep]

    @classmethod
    def from_row(cls, row: AgentRunRow) -> "AgentRun":
        return cls(
            id=row.id, status=row.status, stop_reason=row.stop_reason, model=row.model,
            prompt_version=row.prompt_version, tool_turns=row.tool_turns, guard_fires=row.guard_fires,
            llm_ms=row.llm_ms, started_at=row.started_at, finished_at=row.finished_at,
            steps=[AgentStep(step_no=s.step_no, kind=s.kind, content=s.content, tool_name=s.tool_name,
                             arguments=s.arguments, result=s.result, error=s.error, llm_ms=s.llm_ms) for s in row.steps],  # type: ignore[arg-type]  # strawberry's JSON scalar takes any JSON-able value
        )


@strawberry.type
class PendingAction:
    id: uuid.UUID
    invoice_id: uuid.UUID
    action_type: str
    status: str
    details: JSON
    version: int
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def from_row(cls, row: PendingActionRow) -> "PendingAction":
        return cls(id=row.id, invoice_id=row.invoice_id, action_type=row.action_type, status=row.status,
                   details=row.details, version=row.version, decision_note=row.decision_note,  # type: ignore[arg-type]  # strawberry's JSON scalar takes any JSON-able value
                   created_at=row.created_at, decided_at=row.decided_at)


@strawberry.type
class Invoice:
    id: uuid.UUID
    status: str
    original_filename: str
    page_count: int | None
    invoice_number: str | None
    po_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: str | None
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    invalid_fields: JSON | None
    field_confidence: JSON | None
    error_code: str | None
    error_detail: str | None
    model: str | None
    prompt_version: str | None
    llm_ms: int | None
    repair_attempted: bool
    pages: list[PageResult]
    match: MatchResult | None
    created_at: datetime
    vendor_id: strawberry.Private[uuid.UUID | None]

    async def _vendor(self, info: strawberry.Info[Context]) -> Vendor | None:
        row = await info.context.vendors.load(self.vendor_id) if self.vendor_id else None
        return Vendor(id=row.id, name=row.name, tax_id=row.tax_id) if row else None

    @strawberry.field
    async def vendor(self, info: strawberry.Info[Context]) -> Vendor | None:
        return await self._vendor(info)

    @strawberry.field(deprecation_reason="Use vendor.name.")
    async def vendor_name(self, info: strawberry.Info[Context]) -> str | None:
        vendor = await self._vendor(info)
        return vendor.name if vendor else None

    @strawberry.field(deprecation_reason="Use vendor.taxId.")
    async def vendor_tax_id(self, info: strawberry.Info[Context]) -> str | None:
        vendor = await self._vendor(info)
        return vendor.tax_id if vendor else None

    @strawberry.field
    async def lines(self, info: strawberry.Info[Context]) -> list[InvoiceLine]:
        def money(minor: int | None) -> Money | None:
            return Money(amount_minor=BigInt(minor), currency=self.currency) if minor is not None and self.currency else None

        return [
            InvoiceLine(page_no=line.page_no, line_no=line.line_no, description=line.description,
                        quantity=_decimal(line.quantity), unit_price=_decimal(line.unit_price),
                        amount=money(line.amount_minor), invalid_reason=line.invalid_reason)
            for line in await info.context.lines.load(self.id)
        ]

    @strawberry.field(description="The purchase order the invoice cites, if it has been synced from the ERP.")
    async def purchase_order(self, info: strawberry.Info[Context]) -> PurchaseOrder | None:
        key = po_number_key(self.po_number)
        row = await info.context.purchase_orders.load(key) if key else None
        if row is None:
            return None
        return PurchaseOrder(id=row.id, po_number=row.po_number, status=row.status, currency=row.currency, lines=[
            PoLine(line_no=l.line_no, description=l.description, quantity=_decimal(l.quantity), unit_price=_decimal(l.unit_price))
            for l in row.lines
        ])

    @strawberry.field(description="Goods receipts for the purchase order the invoice cites, oldest first.")
    async def goods_receipts(self, info: strawberry.Info[Context]) -> list[GoodsReceipt]:
        key = po_number_key(self.po_number)
        rows = await info.context.goods_receipts.load(key) if key else []
        return [GoodsReceipt(id=r.id, received_on=r.received_on,
                             lines=[ReceiptLine(po_line_no=l.po_line_no, quantity=_decimal(l.quantity)) for l in r.lines])
                for r in rows]

    @strawberry.field(description="The agent's latest proposal for this invoice, decided or not.")
    async def pending_action(self, info: strawberry.Info[Context]) -> PendingAction | None:
        rows = await info.context.pending_actions.load(self.id)
        return PendingAction.from_row(rows[0]) if rows else None

    @strawberry.field(description="Agent runs on this invoice, newest first, each with its full trace.")
    async def agent_runs(self, info: strawberry.Info[Context]) -> list[AgentRun]:
        return [AgentRun.from_row(row) for row in await info.context.agent_runs.load(self.id)]

    @classmethod
    def from_row(cls, row: InvoiceRow) -> "Invoice":
        def money(minor: int | None) -> Money | None:
            return Money(amount_minor=BigInt(minor), currency=row.currency) if minor is not None and row.currency else None

        match = MatchResult(
            status=row.match.status, purchase_order_id=row.match.purchase_order_id, matched_at=row.match.matched_at,
            reasons=[MatchReason(**reason) for reason in row.match.reasons],
        ) if row.match else None
        return cls(
            id=row.id, status=row.status, original_filename=row.original_filename, page_count=row.page_count,
            invoice_number=row.invoice_number, po_number=row.po_number,
            invoice_date=row.invoice_date, due_date=row.due_date, currency=row.currency,
            subtotal=money(row.subtotal_minor), tax=money(row.tax_minor), total=money(row.total_minor),
            invalid_fields=row.invalid_fields, field_confidence=row.field_confidence, error_code=row.error_code,  # type: ignore[arg-type]  # strawberry's JSON scalar takes any JSON-able value
            error_detail=row.error_detail, model=row.model, prompt_version=row.prompt_version, llm_ms=row.llm_ms,
            repair_attempted=row.repair_attempted,
            # Lean list queries don't load pages; the case file asks for one invoice, which does.
            pages=[PageResult(page_no=p.page_no, status=p.status, source=p.source, error_code=p.error_code, llm_ms=p.llm_ms)
                   for p in row.pages] if "pages" in row.__dict__ else [],
            match=match, created_at=row.created_at, vendor_id=row.vendor_id,
        )


@strawberry.type
class InvoiceConnection(relay.Connection[Invoice]):  # type: ignore[type-var]  # Invoice isn't a relay.Node: our cursors are signed keysets, not global ids
    """Relay-style connection backed by the same signed keyset cursors as REST, not by offsets."""


def _connection(page: service.Page, after: str | None) -> InvoiceConnection:
    edges = [relay.Edge(node=Invoice.from_row(row), cursor=c) for row, c in zip(page.items, page.cursors)]  # type: ignore[type-var]  # Invoice isn't a relay.Node: our cursors are signed keysets, not global ids
    return InvoiceConnection(
        edges=edges,
        page_info=relay.PageInfo(
            has_next_page=page.next_cursor is not None,
            has_previous_page=after is not None,
            start_cursor=edges[0].cursor if edges else None,
            end_cursor=edges[-1].cursor if edges else None,
        ),
    )


async def _page(info: strawberry.Info[Context], first: int, after: str | None, **filters) -> InvoiceConnection:
    if not 1 <= first <= 100:
        raise ValueError("first must be between 1 and 100")
    try:
        page = await service.list_invoices(info.context.session, first, after, lean=True, **filters)
    except ApiProblem as exc:
        raise ValueError(exc.problem.detail) from None
    return _connection(page, after)


@strawberry.type
class Query:
    @strawberry.field
    async def invoice(self, info: strawberry.Info[Context], id: uuid.UUID) -> Invoice | None:
        row = await service.get_invoice(info.context.session, id)
        return Invoice.from_row(row) if row else None

    @strawberry.field
    async def invoices(
        self, info: strawberry.Info[Context], first: int = 25, after: str | None = None, status: str | None = None
    ) -> InvoiceConnection:
        return await _page(info, first, after, status=status)

    @strawberry.field(description="Invoices in `exception`, newest first: what a reviewer works through.")
    async def exceptions_queue(
        self, info: strawberry.Info[Context], first: int = 25, after: str | None = None
    ) -> InvoiceConnection:
        return await _page(info, first, after, status="exception")


@strawberry.type
class DecisionSuccess:
    pending_action: PendingAction


@strawberry.type(description="Someone else decided first, or the version is stale: reload and decide again.")
class VersionConflict:
    current_version: int
    pending_action: PendingAction


@strawberry.type
class NotFound:
    id: uuid.UUID


DecisionResult = Annotated[DecisionSuccess | VersionConflict | NotFound, strawberry.union("DecisionResult")]


async def _decide(info: strawberry.Info[Context], id: uuid.UUID, decision: str, expected_version: int,
                  note: str | None) -> DecisionResult:
    session = info.context.session
    try:
        row = await service.decide_pending_action(session, id, decision, expected_version, note)
    except ApiProblem as exc:
        if exc.problem.code == ProblemCode.NOT_FOUND:
            return NotFound(id=id)
        current = await service.get_pending_action(session, id)
        return VersionConflict(current_version=current.version, pending_action=PendingAction.from_row(current))
    return DecisionSuccess(pending_action=PendingAction.from_row(row))


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Approve a pending action at the version the reviewer saw.")
    async def approve_pending_action(self, info: strawberry.Info[Context], id: uuid.UUID, expected_version: int,
                                     note: str | None = None) -> DecisionResult:
        return await _decide(info, id, "approved", expected_version, note)

    @strawberry.mutation(description="Reject a pending action at the version the reviewer saw.")
    async def reject_pending_action(self, info: strawberry.Info[Context], id: uuid.UUID, expected_version: int,
                                    note: str | None = None) -> DecisionResult:
        return await _decide(info, id, "rejected", expected_version, note)


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    config=StrawberryConfig(
        scalar_map={BigInt: strawberry.scalar(name="BigInt", serialize=int, parse_value=_parse_bigint)}
    ),
)
graphql_router = GraphQLRouter(schema, context_getter=get_context)
