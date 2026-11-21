"""Allow catalog names to wait for specimen and other configuration."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0024"
down_revision = "20261121_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lab_test_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_outlab", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "completed_test_id", sa.Integer(),
            sa.ForeignKey("lab_tests.id", ondelete="RESTRICT"), nullable=True, unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_lab_test_drafts_name_ci", "lab_test_drafts", [sa.text("lower(name)")], unique=True
    )


def downgrade():
    op.drop_index("uq_lab_test_drafts_name_ci", table_name="lab_test_drafts")
    op.drop_table("lab_test_drafts")
