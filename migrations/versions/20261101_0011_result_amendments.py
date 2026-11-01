"""Add result amendment metadata.

Revision ID: 20261101_0011
Revises: 20261029_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0011"
down_revision: str | None = "20261029_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.add_column(sa.Column("amendment_opened_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("amendment_opened_by", sa.String(100)))
        batch.add_column(sa.Column("amendment_reason", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.drop_column("amendment_reason")
        batch.drop_column("amendment_opened_by")
        batch.drop_column("amendment_opened_at")
