"""Add specimen collection and accessioning.

Revision ID: 20261016_0007
Revises: 20261007_0006
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0007"
down_revision: str | None = "20261007_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "specimens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("accession_number", sa.String(length=24), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("specimen_type_id", sa.Integer(), nullable=False),
        sa.Column("specimen_type_code", sa.String(length=30), nullable=False),
        sa.Column("specimen_type_name_th", sa.String(length=150), nullable=False),
        sa.Column("specimen_type_name_en", sa.String(length=150), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="COLLECTED", nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("collected_by", sa.String(length=100), nullable=False),
        sa.Column("collection_note", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["lab_orders.id"],
            name=op.f("fk_specimens_order_id_lab_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["specimen_type_id"],
            ["specimen_types.id"],
            name=op.f("fk_specimens_specimen_type_id_specimen_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specimens")),
        sa.UniqueConstraint("accession_number", name=op.f("uq_specimens_accession_number")),
        sa.UniqueConstraint("order_id", "specimen_type_id", name="uq_specimens_order_type"),
    )
    op.create_index("ix_specimens_order_id", "specimens", ["order_id"], unique=False)
    op.create_index(
        "ix_specimens_specimen_type_id", "specimens", ["specimen_type_id"], unique=False
    )
    op.create_index("ix_specimens_order_status", "specimens", ["order_id", "status"], unique=False)

    op.create_table(
        "specimen_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("specimen_id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["specimen_id"],
            ["specimens.id"],
            name=op.f("fk_specimen_items_specimen_id_specimens"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["lab_order_items.id"],
            name=op.f("fk_specimen_items_order_item_id_lab_order_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specimen_items")),
        sa.UniqueConstraint(
            "specimen_id",
            "order_item_id",
            name="uq_specimen_items_specimen_order_item",
        ),
        sa.UniqueConstraint("order_item_id", name="uq_specimen_items_order_item"),
    )
    op.create_index(
        "ix_specimen_items_specimen_id", "specimen_items", ["specimen_id"], unique=False
    )
    op.create_index(
        "ix_specimen_items_order_item_id", "specimen_items", ["order_item_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_specimen_items_order_item_id", table_name="specimen_items")
    op.drop_index("ix_specimen_items_specimen_id", table_name="specimen_items")
    op.drop_table("specimen_items")
    op.drop_index("ix_specimens_order_status", table_name="specimens")
    op.drop_index("ix_specimens_specimen_type_id", table_name="specimens")
    op.drop_index("ix_specimens_order_id", table_name="specimens")
    op.drop_table("specimens")
