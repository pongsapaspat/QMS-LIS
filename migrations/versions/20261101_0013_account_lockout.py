"""Add account lockout tracking.

Revision ID: 20261101_0013
Revises: 20261101_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0013"
down_revision: str | None = "20261101_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("failed_login_window_started_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_window_started_at")
    op.drop_column("users", "failed_login_count")
