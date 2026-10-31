"""invoices.status gains 'matched': the check constraint is replaced NOT VALID, then validated

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "'received', 'extracting', 'extracted', 'partially_extracted', 'exception', 'failed'"
NEW = OLD + ", 'matched'"


def _replace_check(statuses: str) -> None:
    # Swapping the constraint takes an ACCESS EXCLUSIVE lock for an instant; NOT VALID skips the scan of
    # existing rows. VALIDATE then scans them in its own transaction under a lock that blocks neither reads
    # nor writes (same pattern as 0006).
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        op.execute(
            "ALTER TABLE invoices DROP CONSTRAINT invoices_status_check, "
            f"ADD CONSTRAINT invoices_status_check CHECK (status IN ({statuses})) NOT VALID"
        )
        op.execute("ALTER TABLE invoices VALIDATE CONSTRAINT invoices_status_check")


def upgrade() -> None:
    _replace_check(NEW)


def downgrade() -> None:
    # Matched invoices go back to what they were before matching existed. Not batched: a recovery step.
    op.execute("UPDATE invoices SET status = 'extracted' WHERE status = 'matched'")
    _replace_check(OLD)
