"""Expand patient registration and add immutable audit records.

Revision ID: 20261006_0002
Revises: 20261005_0001
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_0002"
down_revision: str | None = "20261005_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_index("ix_patients_branch_name")
        batch_op.drop_constraint("uq_patients_branch_hn", type_="unique")
        batch_op.drop_constraint("uq_patients_thai_national_id", type_="unique")

    with op.batch_alter_table("patients") as batch_op:
        batch_op.alter_column(
            "first_name",
            new_column_name="first_name_th",
            existing_type=sa.String(length=100),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.alter_column(
            "last_name",
            new_column_name="last_name_th",
            existing_type=sa.String(length=100),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.alter_column(
            "thai_national_id",
            new_column_name="national_id",
            existing_type=sa.String(length=13),
            existing_nullable=True,
        )
        batch_op.add_column(sa.Column("title", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("first_name_en", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("last_name_en", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("sex", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("phone_number", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("address", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
        batch_op.add_column(sa.Column("blood_group", sa.String(length=10), nullable=True))
        batch_op.add_column(
            sa.Column("emergency_contact_name", sa.String(length=200), nullable=True)
        )
        batch_op.add_column(
            sa.Column("emergency_contact_relationship", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("emergency_contact_phone", sa.String(length=30), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "identity_document_missing",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )

    with op.batch_alter_table("patients") as batch_op:
        batch_op.create_unique_constraint("uq_patients_hn", ["hn"])
        batch_op.create_unique_constraint("uq_patients_national_id", ["national_id"])
        batch_op.create_index(
            "ix_patients_branch_name_th",
            ["branch_id", "last_name_th", "first_name_th"],
            unique=False,
        )
        batch_op.create_index(
            "ix_patients_branch_name_en",
            ["branch_id", "last_name_en", "first_name_en"],
            unique=False,
        )
        batch_op.create_index(
            "ix_patients_identity_document_missing",
            ["identity_document_missing"],
            unique=False,
        )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_reference", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["patients.id"],
            name=op.f("fk_audit_logs_entity_id_patients"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"], unique=False)
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"], unique=False)
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_occurred_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_index("ix_patients_identity_document_missing")
        batch_op.drop_index("ix_patients_branch_name_en")
        batch_op.drop_index("ix_patients_branch_name_th")
        batch_op.drop_constraint("uq_patients_national_id", type_="unique")
        batch_op.drop_constraint("uq_patients_hn", type_="unique")

    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_column("identity_document_missing")
        batch_op.drop_column("emergency_contact_phone")
        batch_op.drop_column("emergency_contact_relationship")
        batch_op.drop_column("emergency_contact_name")
        batch_op.drop_column("blood_group")
        batch_op.drop_column("email")
        batch_op.drop_column("address")
        batch_op.drop_column("phone_number")
        batch_op.drop_column("sex")
        batch_op.drop_column("last_name_en")
        batch_op.drop_column("first_name_en")
        batch_op.drop_column("title")
        batch_op.alter_column(
            "national_id",
            new_column_name="thai_national_id",
            existing_type=sa.String(length=13),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "last_name_th",
            new_column_name="last_name",
            existing_type=sa.String(length=100),
            existing_nullable=True,
            nullable=False,
        )
        batch_op.alter_column(
            "first_name_th",
            new_column_name="first_name",
            existing_type=sa.String(length=100),
            existing_nullable=True,
            nullable=False,
        )

    with op.batch_alter_table("patients") as batch_op:
        batch_op.create_unique_constraint(
            "uq_patients_thai_national_id", ["thai_national_id"]
        )
        batch_op.create_unique_constraint("uq_patients_branch_hn", ["branch_id", "hn"])
        batch_op.create_index(
            "ix_patients_branch_name",
            ["branch_id", "last_name", "first_name"],
            unique=False,
        )
