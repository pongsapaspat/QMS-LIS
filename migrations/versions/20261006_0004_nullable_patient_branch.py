"""Make patient branch nullable-ready while retaining the V1 default.

Revision ID: 20261006_0004
Revises: 20261006_0003
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_0004"
down_revision: str | None = "20261006_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("patients") as batch_op:
        batch_op.alter_column(
            "branch_id",
            existing_type=sa.Integer(),
            existing_nullable=False,
            nullable=True,
            existing_server_default=sa.text("1"),
        )


def downgrade() -> None:
    with op.batch_alter_table("patients") as batch_op:
        batch_op.alter_column(
            "branch_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
            nullable=False,
            existing_server_default=sa.text("1"),
        )
