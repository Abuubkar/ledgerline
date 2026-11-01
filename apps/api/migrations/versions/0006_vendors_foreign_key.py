"""vendors, step 3 of 4: foreign key from invoices.vendor_id, added NOT VALID then validated

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31 13:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Two separate transactions. NOT VALID checks only new writes, so adding it is instant (a brief SHARE ROW
    # EXCLUSIVE lock). VALIDATE then scans existing rows under SHARE UPDATE EXCLUSIVE, which doesn't block
    # reads or writes. In one transaction the first lock would be held for the whole scan.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        op.execute(
            "ALTER TABLE invoices ADD CONSTRAINT invoices_vendor_id_fkey "
            "FOREIGN KEY (vendor_id) REFERENCES vendors (id) NOT VALID"
        )
        op.execute("ALTER TABLE invoices VALIDATE CONSTRAINT invoices_vendor_id_fkey")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.drop_constraint("invoices_vendor_id_fkey", "invoices", type_="foreignkey")
