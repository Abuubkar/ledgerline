"""Linking an extracted invoice to its vendor, and flagging a second copy of an invoice we already have.

A vendor is recognized by its tax ID, or by its normalized name when the invoice prints no tax ID. A vendor
with a tax ID is never matched by name: two companies can share a name, and guessing would merge their bills.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ledgerline_api.db import Invoice, Vendor
from ledgerline_api.normalize import invoice_number_key, vendor_name_key


async def find_or_create(session: AsyncSession, tax_id: str | None, name: str | None) -> uuid.UUID | None:
    """The vendor's id, creating the vendor on first sight. None when there's nothing to recognize it by."""
    if tax_id is None and not (name and vendor_name_key(name)):
        return None
    if tax_id is not None:
        match, conflict = Vendor.tax_id == tax_id, dict(index_elements=["tax_id"], index_where=Vendor.tax_id.is_not(None))
    else:
        match = (Vendor.name_key == vendor_name_key(name)) & Vendor.tax_id.is_(None)
        conflict = dict(index_elements=["name_key"], index_where=Vendor.tax_id.is_(None))
    # Insert-or-ignore then read: safe when two workers see a new vendor at the same moment.
    vendor_id = (await session.execute(
        insert(Vendor)
        .values(tax_id=tax_id, name=name or tax_id, name_key=vendor_name_key(name or tax_id))
        .on_conflict_do_nothing(**conflict)
        .returning(Vendor.id)
    )).scalar_one_or_none()
    return vendor_id or (await session.execute(select(Vendor.id).where(match))).scalar_one()


async def link(session: AsyncSession, invoice: Invoice, tax_id: str | None, name: str | None) -> None:
    """Set the invoice's vendor and duplicate key from the extracted tax ID and name. A copy of an invoice we
    already hold keeps no key and goes to `exception`, pointing at the original."""
    invoice.vendor_id = await find_or_create(session, tax_id, name)
    key = invoice_number_key(invoice.invoice_number)
    invoice.invoice_number_key = None
    if invoice.vendor_id is None or key is None:
        return
    # Two copies extracted at the same moment would both see no original; this lock makes them take turns.
    # The unique index stays as the backstop.
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"{invoice.vendor_id}/{key}", 0))))
    original = (await session.execute(
        select(Invoice.id).where(
            Invoice.vendor_id == invoice.vendor_id, Invoice.invoice_number_key == key, Invoice.id != invoice.id
        )
    )).scalar_one_or_none()
    if original is None:
        invoice.invoice_number_key = key
        return
    invoice.invalid_fields = {**(invoice.invalid_fields or {}), "invoice_number": f"duplicate of invoice {original}"}
    if invoice.status == "extracted":
        invoice.status = "exception"
