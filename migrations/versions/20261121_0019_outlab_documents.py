"""Separate referral specimens and retain external reports as original documents."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0019"
down_revision = "20261121_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "lab_tests", sa.Column("is_outlab", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("lab_tests", sa.Column("outlab_lab_name", sa.String(200)))
    op.add_column(
        "lab_order_items",
        sa.Column("is_outlab", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table("specimens") as batch:
        batch.add_column(
            sa.Column("collection_group", sa.String(40), nullable=False, server_default="INTERNAL")
        )
        batch.drop_constraint("uq_specimens_order_type", type_="unique")
        batch.create_unique_constraint(
            "uq_specimens_order_type_group", ["order_id", "specimen_type_id", "collection_group"]
        )
    op.create_table(
        "outlab_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_item_id",
            sa.Integer(),
            sa.ForeignKey("lab_order_items.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lab_name", sa.String(200), nullable=False),
        sa.Column("external_reference", sa.String(150)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("sent_by", sa.String(100)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("received_by", sa.String(100)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("checked_by", sa.String(100)),
        sa.Column("notes", sa.Text()),
    )
    op.create_table(
        "outlab_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("outlab_cases.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by", sa.String(100), nullable=False),
    )
    op.create_index("ix_outlab_documents_case_id", "outlab_documents", ["case_id"])


def downgrade():
    # Splitting specimens cannot be reversed without destroying tracking history.
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT COUNT(*) FROM specimens WHERE collection_group != 'INTERNAL'")
    ):
        raise RuntimeError("Cannot downgrade while Outlab specimens exist; retain their history")
    op.drop_table("outlab_documents")
    op.drop_table("outlab_cases")
    with op.batch_alter_table("specimens") as batch:
        batch.drop_constraint("uq_specimens_order_type_group", type_="unique")
        batch.drop_column("collection_group")
        batch.create_unique_constraint("uq_specimens_order_type", ["order_id", "specimen_type_id"])
    op.drop_column("lab_order_items", "is_outlab")
    op.drop_column("lab_tests", "outlab_lab_name")
    op.drop_column("lab_tests", "is_outlab")
