"""Enforce append-only audit logs at the database boundary.

Revision ID: 20261006_0003
Revises: 20261006_0002
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261006_0003"
down_revision: str | None = "20261006_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_update")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
