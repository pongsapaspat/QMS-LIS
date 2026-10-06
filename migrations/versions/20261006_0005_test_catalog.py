"""Add the test catalog and make audit entities generic.

Revision ID: 20261006_0005
Revises: 20261006_0004
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_0005"
down_revision: str | None = "20261006_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_audit_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs")


def _create_audit_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit log entries are immutable');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit log entries are immutable');
            END
            """
        )
    elif dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit log entries are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_logs_immutable
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation()
            """
        )


def upgrade() -> None:
    _drop_audit_triggers()
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_constraint("fk_audit_logs_entity_id_patients", type_="foreignkey")
        batch_op.create_index(
            "ix_audit_logs_entity", ["entity_type", "entity_id"], unique=False
        )
    _create_audit_triggers()

    op.create_table(
        "test_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name_th", sa.String(length=150), nullable=False),
        sa.Column("name_en", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_categories")),
    )
    op.create_index(
        "uq_test_categories_code_ci",
        "test_categories",
        [sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ix_test_categories_is_active", "test_categories", ["is_active"], unique=False
    )

    op.create_table(
        "specimen_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name_th", sa.String(length=150), nullable=False),
        sa.Column("name_en", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_specimen_types")),
    )
    op.create_index(
        "uq_specimen_types_code_ci",
        "specimen_types",
        [sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ix_specimen_types_is_active", "specimen_types", ["is_active"], unique=False
    )

    op.create_table(
        "lab_tests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_th", sa.String(length=200), nullable=False),
        sa.Column("name_en", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("specimen_type_id", sa.Integer(), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("result_type", sa.String(length=20), nullable=False),
        sa.Column("result_unit", sa.String(length=50), nullable=True),
        sa.Column("tat_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["test_categories.id"],
            name=op.f("fk_lab_tests_category_id_test_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["specimen_type_id"],
            ["specimen_types.id"],
            name=op.f("fk_lab_tests_specimen_type_id_specimen_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_tests")),
    )
    op.create_index("uq_lab_tests_code_ci", "lab_tests", [sa.text("lower(code)")], unique=True)
    op.create_index("ix_lab_tests_names", "lab_tests", ["name_th", "name_en"], unique=False)
    op.create_index("ix_lab_tests_category_id", "lab_tests", ["category_id"], unique=False)
    op.create_index(
        "ix_lab_tests_specimen_type_id", "lab_tests", ["specimen_type_id"], unique=False
    )
    op.create_index("ix_lab_tests_result_type", "lab_tests", ["result_type"], unique=False)
    op.create_index("ix_lab_tests_is_active", "lab_tests", ["is_active"], unique=False)

    op.create_table(
        "test_reference_ranges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("sex", sa.String(length=20), nullable=False),
        sa.Column("minimum_age", sa.Integer(), nullable=False),
        sa.Column("maximum_age", sa.Integer(), nullable=False),
        sa.Column("age_unit", sa.String(length=20), nullable=False),
        sa.Column("lower_value", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("upper_value", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("lower_critical", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("upper_critical", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("display_text", sa.Text(), nullable=True),
        sa.Column("context_metadata", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["lab_tests.id"],
            name=op.f("fk_test_reference_ranges_test_id_lab_tests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_reference_ranges")),
    )
    op.create_index(
        "ix_reference_ranges_test_active",
        "test_reference_ranges",
        ["test_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_test_reference_ranges_test_id",
        "test_reference_ranges",
        ["test_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_reference_ranges_is_active",
        "test_reference_ranges",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "qualitative_result_options",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label_th", sa.String(length=150), nullable=False),
        sa.Column("label_en", sa.String(length=150), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_abnormal", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["lab_tests.id"],
            name=op.f("fk_qualitative_result_options_test_id_lab_tests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qualitative_result_options")),
    )
    op.create_index(
        "uq_qualitative_options_test_code_ci",
        "qualitative_result_options",
        ["test_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ix_qualitative_options_test_sort",
        "qualitative_result_options",
        ["test_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "ix_qualitative_result_options_test_id",
        "qualitative_result_options",
        ["test_id"],
        unique=False,
    )
    op.create_index(
        "ix_qualitative_result_options_is_active",
        "qualitative_result_options",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "test_price_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("old_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("new_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_reference", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["lab_tests.id"],
            name=op.f("fk_test_price_history_test_id_lab_tests"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_price_history")),
    )
    op.create_index(
        "ix_test_price_history_test_id", "test_price_history", ["test_id"], unique=False
    )
    op.create_index(
        "ix_test_price_history_effective_at",
        "test_price_history",
        ["effective_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_test_price_history_effective_at", table_name="test_price_history")
    op.drop_index("ix_test_price_history_test_id", table_name="test_price_history")
    op.drop_table("test_price_history")

    op.drop_index(
        "ix_qualitative_result_options_is_active",
        table_name="qualitative_result_options",
    )
    op.drop_index(
        "ix_qualitative_result_options_test_id",
        table_name="qualitative_result_options",
    )
    op.drop_index(
        "ix_qualitative_options_test_sort", table_name="qualitative_result_options"
    )
    op.drop_index(
        "uq_qualitative_options_test_code_ci", table_name="qualitative_result_options"
    )
    op.drop_table("qualitative_result_options")

    op.drop_index("ix_test_reference_ranges_is_active", table_name="test_reference_ranges")
    op.drop_index("ix_test_reference_ranges_test_id", table_name="test_reference_ranges")
    op.drop_index("ix_reference_ranges_test_active", table_name="test_reference_ranges")
    op.drop_table("test_reference_ranges")

    op.drop_index("ix_lab_tests_is_active", table_name="lab_tests")
    op.drop_index("ix_lab_tests_result_type", table_name="lab_tests")
    op.drop_index("ix_lab_tests_specimen_type_id", table_name="lab_tests")
    op.drop_index("ix_lab_tests_category_id", table_name="lab_tests")
    op.drop_index("ix_lab_tests_names", table_name="lab_tests")
    op.drop_index("uq_lab_tests_code_ci", table_name="lab_tests")
    op.drop_table("lab_tests")

    op.drop_index("ix_specimen_types_is_active", table_name="specimen_types")
    op.drop_index("uq_specimen_types_code_ci", table_name="specimen_types")
    op.drop_table("specimen_types")

    op.drop_index("ix_test_categories_is_active", table_name="test_categories")
    op.drop_index("uq_test_categories_code_ci", table_name="test_categories")
    op.drop_table("test_categories")

    _drop_audit_triggers()
    op.execute(sa.text("DELETE FROM audit_logs WHERE entity_type <> 'patient'"))
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_index("ix_audit_logs_entity")
        batch_op.create_foreign_key(
            "fk_audit_logs_entity_id_patients",
            "patients",
            ["entity_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    _create_audit_triggers()
