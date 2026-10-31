"""GraphQL read API for the reviewer UI. Resolvers call the same service functions as REST (see ADR 0007)."""

import uuid
from datetime import date, datetime
from typing import NewType

import strawberry
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry import relay
from strawberry.fastapi import BaseContext, GraphQLRouter
from strawberry.schema.config import StrawberryConfig

from ledgerline_api import service
from ledgerline_api.db import Invoice as InvoiceRow
from ledgerline_api.db import get_session
from ledgerline_api.schemas import ApiProblem

# GraphQL Int is 32-bit: 2^31 cents is only $21.4M, too small for invoice totals. BigInt is serialized as a
# JSON number; JavaScript clients stay exact up to 2^53 minor units.
BigInt = NewType("BigInt", int)


def _parse_bigint(value: object) -> int:
    return int(str(value))


class Context(BaseContext):
    def __init__(self, session: AsyncSession):
        super().__init__()
        self.session = session


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
class Invoice:
    id: uuid.UUID
    status: str
    original_filename: str
    page_count: int | None
    vendor: Vendor | None
    vendor_name: str | None = strawberry.field(deprecation_reason="Use vendor.name.")
    vendor_tax_id: str | None = strawberry.field(deprecation_reason="Use vendor.taxId.")
    invoice_number: str | None
    invoice_date: date | None
    due_date: date | None
    currency: str | None
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    error_code: str | None
    model: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: InvoiceRow) -> "Invoice":
        def money(minor: int | None) -> Money | None:
            return Money(amount_minor=BigInt(minor), currency=row.currency) if minor is not None and row.currency else None

        vendor = Vendor(id=row.vendor.id, name=row.vendor.name, tax_id=row.vendor.tax_id) if row.vendor else None
        return cls(
            id=row.id, status=row.status, original_filename=row.original_filename, page_count=row.page_count,
            vendor=vendor, vendor_name=vendor and vendor.name, vendor_tax_id=vendor and vendor.tax_id,
            invoice_number=row.invoice_number,
            invoice_date=row.invoice_date, due_date=row.due_date, currency=row.currency,
            subtotal=money(row.subtotal_minor), tax=money(row.tax_minor), total=money(row.total_minor),
            error_code=row.error_code, model=row.model, created_at=row.created_at,
        )


@strawberry.type
class InvoiceConnection(relay.Connection[Invoice]):
    """Relay-style connection backed by the same signed keyset cursors as REST, not by offsets."""


@strawberry.type
class Query:
    @strawberry.field
    async def invoice(self, info: strawberry.Info[Context], id: uuid.UUID) -> Invoice | None:
        row = await service.get_invoice(info.context.session, id)
        return Invoice.from_row(row) if row else None

    @strawberry.field
    async def invoices(
        self, info: strawberry.Info[Context], first: int = 25, after: str | None = None
    ) -> InvoiceConnection:
        if not 1 <= first <= 100:
            raise ValueError("first must be between 1 and 100")
        try:
            page = await service.list_invoices(info.context.session, first, after)
        except ApiProblem as exc:
            raise ValueError(exc.problem.detail) from None
        edges = [relay.Edge(node=Invoice.from_row(row), cursor=c) for row, c in zip(page.items, page.cursors)]
        return InvoiceConnection(
            edges=edges,
            page_info=relay.PageInfo(
                has_next_page=page.next_cursor is not None,
                has_previous_page=after is not None,
                start_cursor=edges[0].cursor if edges else None,
                end_cursor=edges[-1].cursor if edges else None,
            ),
        )


schema = strawberry.Schema(
    query=Query,
    config=StrawberryConfig(
        scalar_map={BigInt: strawberry.scalar(name="BigInt", serialize=int, parse_value=_parse_bigint)}
    ),
)
graphql_router = GraphQLRouter(schema, context_getter=get_context)
