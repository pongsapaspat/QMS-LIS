"""Allow the full verification rejection status on PostgreSQL."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_0026"
down_revision = "20261122_0025"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("results") as batch:
        batch.alter_column(
            "status", existing_type=sa.String(20), type_=sa.String(32), existing_nullable=False
        )


def downgrade():
    # Never truncate or rename recorded workflow states to fit the old column.
    oversized = op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM results WHERE length(status) > 20"
    ))
    if oversized:
        raise RuntimeError("Cannot shorten results.status while values exceed 20 characters")
    with op.batch_alter_table("results") as batch:
        batch.alter_column(
            "status", existing_type=sa.String(32), type_=sa.String(20), existing_nullable=False
        )
