"""Freeze the order recorder's identity independently of external referrers."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0023"
down_revision = "20261121_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lab_orders", sa.Column("created_by_snapshot", sa.JSON(), nullable=True))
    # Historic usernames are kept; current profiles are not evidence of historic names.


def downgrade():
    op.drop_column("lab_orders", "created_by_snapshot")
