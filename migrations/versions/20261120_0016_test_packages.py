"""Test packages with fixed prices and immutable order snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0016"
down_revision = "20261120_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "test_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "test_package_items",
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("test_packages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "test_id",
            sa.Integer(),
            sa.ForeignKey("lab_tests.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.add_column("lab_orders", sa.Column("package_snapshots", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("lab_orders", "package_snapshots")
    op.drop_table("test_package_items")
    op.drop_table("test_packages")
