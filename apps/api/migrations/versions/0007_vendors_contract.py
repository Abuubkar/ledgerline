"""vendors, step 4 of 4 (contract): drop invoices.vendor_name and invoices.vendor_tax_id

Deploy the code that no longer reads or writes them first (docs/migrations.md).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # DROP COLUMN only hides the column in the catalog: instant, but it needs ACCESS EXCLUSIVE for a moment.
    op.execute("SET lock_timeout = '5s'")
    op.drop_column("invoices", "vendor_tax_id")
    op.drop_column("invoices", "vendor_name")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.add_column("invoices", sa.Column("vendor_name", sa.String(), nullable=True))
    op.add_column("invoices", sa.Column("vendor_tax_id", sa.String(), nullable=True))
    # Refill from what the model read where we have it, else from the vendor. One statement, not batched:
    # rolling back this step is a recovery, not something done while under full load.
    op.execute("""
        UPDATE invoices i SET
            vendor_name = coalesce(r.extracted_header ->> 'vendor_name', v.name),
            vendor_tax_id = coalesce(r.extracted_header ->> 'vendor_tax_id', v.tax_id)
        FROM invoices j
        LEFT JOIN vendors v ON v.id = j.vendor_id
        LEFT JOIN extraction_runs r ON r.invoice_id = j.id AND r.outcome = 'completed'
        WHERE i.id = j.id AND (v.id IS NOT NULL OR r.id IS NOT NULL)
    """)
