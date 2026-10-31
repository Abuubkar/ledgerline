"""vendors, step 1 of 4 (expand): vendors table, invoices.vendor_id and invoice_number_key, raw extracted header

Additive only, so code from before this migration keeps working against it. See docs/migrations.md.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ADD COLUMN takes an ACCESS EXCLUSIVE lock for an instant. If a long transaction holds the table, give up
    # quickly instead of queueing every request behind this migration; rerunning it is safe.
    op.execute("SET lock_timeout = '5s'")
    op.create_table(
        "vendors",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("tax_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("vendors_tax_id_key", "vendors", ["tax_id"], unique=True,
                    postgresql_where=sa.text("tax_id IS NOT NULL"))
    op.create_index("vendors_name_key_key", "vendors", ["name_key"], unique=True,
                    postgresql_where=sa.text("tax_id IS NULL"))
    # Nullable with no default: a catalog change, no table rewrite.
    op.add_column("invoices", sa.Column("vendor_id", sa.Uuid(), nullable=True))
    op.add_column("invoices", sa.Column("invoice_number_key", sa.String(), nullable=True))
    op.add_column("extraction_runs", sa.Column("extracted_header", postgresql.JSONB(), nullable=True))

    # A plain CREATE INDEX would block writes to invoices for the whole build.
    with op.get_context().autocommit_block():
        op.create_index(
            "invoices_vendor_number_key", "invoices", ["vendor_id", "invoice_number_key"], unique=True,
            postgresql_where=sa.text("invoice_number_key IS NOT NULL"), postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("invoices_vendor_number_key", table_name="invoices", postgresql_concurrently=True,
                      if_exists=True)
    op.execute("SET lock_timeout = '5s'")
    op.drop_column("extraction_runs", "extracted_header")
    op.drop_column("invoices", "invoice_number_key")
    op.drop_column("invoices", "vendor_id")
    op.drop_index("vendors_name_key_key", table_name="vendors")
    op.drop_index("vendors_tax_id_key", table_name="vendors")
    op.drop_table("vendors")
