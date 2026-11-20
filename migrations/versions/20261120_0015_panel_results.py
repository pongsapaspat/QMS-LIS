"""Snapshot multi-parameter definitions and results for CBC and UA."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0015"
down_revision = "20261119_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lab_order_items", sa.Column("parameter_definitions", sa.JSON(), nullable=True))
    op.add_column("results", sa.Column("parameter_values", sa.JSON(), nullable=True))
    op.add_column("results", sa.Column("parameter_results", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("results", "parameter_results")
    op.drop_column("results", "parameter_values")
    op.drop_column("lab_order_items", "parameter_definitions")
