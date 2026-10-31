"""ERP data and matching: purchase orders, goods receipts, match results, sync state; invoices.po_number

Additive only: new tables, and a nullable column on invoices. See docs/migrations.md.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("erp_id", sa.String(), nullable=False),
        sa.Column("po_number", sa.String(), nullable=False),
        sa.Column("po_number_key", sa.String(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("erp_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("erp_id"),
        sa.UniqueConstraint("po_number_key"),
    )
    op.create_table(
        "po_lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 6), nullable=False),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_order_id", "line_no"),
    )
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("erp_id", sa.String(), nullable=False),
        sa.Column("po_number_key", sa.String(), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("erp_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("erp_id"),
    )
    op.create_index("ix_goods_receipts_po_number_key", "goods_receipts", ["po_number_key"])
    op.create_table(
        "receipt_lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("po_line_no", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goods_receipt_id", "line_no"),
    )
    op.create_table(
        "match_results",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("po_number_key", sa.String(), nullable=True),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=True),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('matched', 'exception')", name="match_results_status_check"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id"),
    )
    op.create_index("match_results_waiting_idx", "match_results", ["po_number_key"],
                    postgresql_where=sa.text("status = 'exception'"))
    op.create_table(
        "erp_sync_state",
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("cursor", sa.String(), nullable=True),
        sa.Column("synced_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("resource"),
    )
    # Nullable with no default: a catalog change, no table rewrite.
    op.add_column("invoices", sa.Column("po_number", sa.String(), nullable=True))


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.drop_column("invoices", "po_number")
    op.drop_table("erp_sync_state")
    op.drop_index("match_results_waiting_idx", table_name="match_results")
    op.drop_table("match_results")
    op.drop_table("receipt_lines")
    op.drop_index("ix_goods_receipts_po_number_key", table_name="goods_receipts")
    op.drop_table("goods_receipts")
    op.drop_table("po_lines")
    op.drop_table("purchase_orders")
