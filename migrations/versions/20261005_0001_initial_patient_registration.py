"""Initial branch and patient registration schema.

Revision ID: 20261005_0001
Revises:
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("next_hn_sequence", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branches")),
        sa.UniqueConstraint("code", name=op.f("uq_branches_code")),
    )
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("hn", sa.String(length=24), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("thai_national_id", sa.String(length=13), nullable=True),
        sa.Column("passport_number", sa.String(length=30), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name=op.f("fk_patients_branch_id_branches"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("branch_id", "hn", name="uq_patients_branch_hn"),
        sa.UniqueConstraint("passport_number", name="uq_patients_passport_number"),
        sa.UniqueConstraint("thai_national_id", name="uq_patients_thai_national_id"),
    )
    op.create_index("ix_patients_branch_id", "patients", ["branch_id"], unique=False)
    op.create_index(
        "ix_patients_branch_name",
        "patients",
        ["branch_id", "last_name", "first_name"],
        unique=False,
    )
    op.create_index("ix_patients_hn", "patients", ["hn"], unique=False)
    op.create_index("ix_patients_is_active", "patients", ["is_active"], unique=False)
    op.bulk_insert(
        sa.table(
            "branches",
            sa.column("id", sa.Integer()),
            sa.column("code", sa.String()),
            sa.column("name", sa.String()),
            sa.column("next_hn_sequence", sa.Integer()),
            sa.column("is_active", sa.Boolean()),
        ),
        [
            {
                "id": 1,
                "code": "MAIN",
                "name": "Main Branch",
                "next_hn_sequence": 0,
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_patients_is_active", table_name="patients")
    op.drop_index("ix_patients_hn", table_name="patients")
    op.drop_index("ix_patients_branch_name", table_name="patients")
    op.drop_index("ix_patients_branch_id", table_name="patients")
    op.drop_table("patients")
    op.drop_table("branches")
