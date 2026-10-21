"""Add specimen receiving fields.

Revision ID: 20261021_0008
Revises: 20261016_0007
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0008"
down_revision: str | None = "20261016_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("specimens") as batch_op:
        batch_op.add_column(sa.Column("received_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("received_by", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("receiving_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("rejection_reason_code", sa.String(length=50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("specimens") as batch_op:
        batch_op.drop_column("rejection_reason_code")
        batch_op.drop_column("receiving_note")
        batch_op.drop_column("received_by")
        batch_op.drop_column("received_at")
