"""Add departments and manual laboratory result entry.

Revision ID: 20261021_0009
Revises: 20261021_0008
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0009"
down_revision: str | None = "20261021_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    migration_time = datetime.now(UTC)
    op.create_table(
        "laboratory_departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name_th", sa.String(150), nullable=False),
        sa.Column("name_en", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_laboratory_departments_code_ci",
        "laboratory_departments",
        [sa.text("lower(code)")],
        unique=True,
    )
    op.bulk_insert(
        sa.table(
            "laboratory_departments",
            sa.column("id", sa.Integer),
            sa.column("code", sa.String),
            sa.column("name_th", sa.String),
            sa.column("name_en", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": 1,
                "code": "GENERAL",
                "name_th": "ทั่วไป",
                "name_en": "General",
                "is_active": True,
                "created_at": migration_time,
                "updated_at": migration_time,
            }
        ],
    )
    with op.batch_alter_table("lab_tests") as batch:
        batch.add_column(sa.Column("department_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_lab_tests_department_id_laboratory_departments",
            "laboratory_departments",
            ["department_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_lab_tests_department_id", ["department_id"])
    op.execute("UPDATE lab_tests SET department_id = 1 WHERE department_id IS NULL")
    with op.batch_alter_table("lab_tests") as batch:
        batch.alter_column("department_id", nullable=False)
    # SQLite batch table recreation drops expression indexes, while PostgreSQL
    # alters the table in place and preserves this index from revision 0005.
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "uq_lab_tests_code_ci",
            "lab_tests",
            [sa.text("lower(code)")],
            unique=True,
        )
    with op.batch_alter_table("test_reference_ranges") as batch:
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_item_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("specimen_id", sa.Integer(), nullable=False),
        sa.Column("result_type", sa.String(20), nullable=False),
        sa.Column("numeric_value", sa.Numeric(18, 6)),
        sa.Column("text_value", sa.Text()),
        sa.Column("categorical_value", sa.String(150)),
        sa.Column("result_unit_snapshot", sa.String(50)),
        sa.Column("reference_range_snapshot", sa.JSON()),
        sa.Column("abnormal_flag", sa.String(2)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True)),
        sa.Column("entered_by", sa.String(100)),
        sa.Column("last_modified_at", sa.DateTime(timezone=True)),
        sa.Column("last_modified_by", sa.String(100)),
        sa.Column("critical_acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("critical_acknowledged_by", sa.String(100)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["order_item_id"], ["lab_order_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["specimen_id"], ["specimens.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_results_status", "results", ["status"])
    op.create_index("ix_results_specimen", "results", ["specimen_id"])
    op.create_table(
        "result_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("previous_value", sa.JSON()),
        sa.Column("new_value", sa.JSON()),
        sa.Column("previous_flag", sa.String(2)),
        sa.Column("new_flag", sa.String(2)),
        sa.Column("modification_reason", sa.Text(), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified_by", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["results.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_result_revisions_result", "result_revisions", ["result_id", "modified_at"])


def downgrade() -> None:
    op.drop_index("ix_result_revisions_result", table_name="result_revisions")
    op.drop_table("result_revisions")
    op.drop_index("ix_results_specimen", table_name="results")
    op.drop_index("ix_results_status", table_name="results")
    op.drop_table("results")
    with op.batch_alter_table("test_reference_ranges") as batch:
        batch.drop_column("priority")
    with op.batch_alter_table("lab_tests") as batch:
        batch.drop_index("ix_lab_tests_department_id")
        batch.drop_constraint(
            "fk_lab_tests_department_id_laboratory_departments", type_="foreignkey"
        )
        batch.drop_column("department_id")
    if op.get_bind().dialect.name == "sqlite":
        op.create_index(
            "uq_lab_tests_code_ci",
            "lab_tests",
            [sa.text("lower(code)")],
            unique=True,
        )
    op.drop_index("uq_laboratory_departments_code_ci", table_name="laboratory_departments")
    op.drop_table("laboratory_departments")
