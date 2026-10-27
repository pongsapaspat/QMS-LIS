"""Add initial laboratory order workflow.

Revision ID: 20261007_0006
Revises: 20261006_0005
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261007_0006"
down_revision: str | None = "20261006_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lab_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_number", sa.String(length=24), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="ORDERED", nullable=False),
        sa.Column("priority", sa.String(length=20), server_default="ROUTINE", nullable=False),
        sa.Column("clinical_note", sa.Text(), nullable=True),
        sa.Column(
            "ordered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_lab_orders_patient_id_patients"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_orders")),
        sa.UniqueConstraint("order_number", name=op.f("uq_lab_orders_order_number")),
    )
    op.create_index("ix_lab_orders_patient_id", "lab_orders", ["patient_id"], unique=False)
    op.create_index("ix_lab_orders_ordered_at", "lab_orders", ["ordered_at"], unique=False)
    op.create_index(
        "ix_lab_orders_patient_ordered_at",
        "lab_orders",
        ["patient_id", "ordered_at"],
        unique=False,
    )

    op.create_table(
        "lab_order_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("lab_test_id", sa.Integer(), nullable=False),
        sa.Column("test_code", sa.String(length=40), nullable=False),
        sa.Column("test_name_th", sa.String(length=200), nullable=False),
        sa.Column("test_name_en", sa.String(length=200), nullable=False),
        sa.Column("result_type", sa.String(length=20), nullable=False),
        sa.Column("result_unit", sa.String(length=50), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["lab_orders.id"],
            name=op.f("fk_lab_order_items_order_id_lab_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lab_test_id"],
            ["lab_tests.id"],
            name=op.f("fk_lab_order_items_lab_test_id_lab_tests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_order_items")),
        sa.UniqueConstraint("order_id", "lab_test_id", name="uq_lab_order_items_order_test"),
    )
    op.create_index("ix_lab_order_items_order_id", "lab_order_items", ["order_id"], unique=False)
    op.create_index(
        "ix_lab_order_items_lab_test_id", "lab_order_items", ["lab_test_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_lab_order_items_lab_test_id", table_name="lab_order_items")
    op.drop_index("ix_lab_order_items_order_id", table_name="lab_order_items")
    op.drop_table("lab_order_items")
    op.drop_index("ix_lab_orders_patient_ordered_at", table_name="lab_orders")
    op.drop_index("ix_lab_orders_ordered_at", table_name="lab_orders")
    op.drop_index("ix_lab_orders_patient_id", table_name="lab_orders")
    op.drop_table("lab_orders")
