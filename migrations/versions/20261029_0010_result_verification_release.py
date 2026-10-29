"""Add result verification and order release metadata.

Revision ID: 20261029_0010
Revises: 20261021_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261029_0010"
down_revision: str | None = "20261021_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("results") as batch:
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("verified_by", sa.String(100)))
        batch.add_column(sa.Column("verification_comment", sa.Text()))
        batch.add_column(sa.Column("verification_rejected_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("verification_rejected_by", sa.String(100)))
        batch.add_column(sa.Column("verification_rejection_reason", sa.Text()))
        batch.add_column(sa.Column("released_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("released_by", sa.String(100)))
        batch.create_index("ix_results_verified_at", ["verified_at"])
        batch.create_index("ix_results_released_at", ["released_at"])

    with op.batch_alter_table("lab_orders") as batch:
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("verified_by", sa.String(100)))
        batch.add_column(sa.Column("released_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("released_by", sa.String(100)))
        batch.create_index("ix_lab_orders_verified_at", ["verified_at"])
        batch.create_index("ix_lab_orders_released_at", ["released_at"])
        batch.create_index("ix_lab_orders_status_priority", ["status", "priority"])


def downgrade() -> None:
    with op.batch_alter_table("lab_orders") as batch:
        batch.drop_index("ix_lab_orders_status_priority")
        batch.drop_index("ix_lab_orders_released_at")
        batch.drop_index("ix_lab_orders_verified_at")
        batch.drop_column("released_by")
        batch.drop_column("released_at")
        batch.drop_column("verified_by")
        batch.drop_column("verified_at")

    with op.batch_alter_table("results") as batch:
        batch.drop_index("ix_results_released_at")
        batch.drop_index("ix_results_verified_at")
        batch.drop_column("released_by")
        batch.drop_column("released_at")
        batch.drop_column("verification_rejection_reason")
        batch.drop_column("verification_rejected_by")
        batch.drop_column("verification_rejected_at")
        batch.drop_column("verification_comment")
        batch.drop_column("verified_by")
        batch.drop_column("verified_at")
