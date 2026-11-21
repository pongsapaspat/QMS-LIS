"""Retain rejected specimens and link each replacement to its predecessor."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0020"
down_revision = "20261121_0019"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("specimens") as batch:
        batch.add_column(
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("replaces_specimen_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rejected_by", sa.String(100), nullable=True))
        batch.create_foreign_key(
            "fk_specimens_replaces_specimen_id_specimens",
            "specimens",
            ["replaces_specimen_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_specimens_replaces_specimen_id", ["replaces_specimen_id"]
        )
        batch.drop_constraint("uq_specimens_order_type_group", type_="unique")
    op.create_index(
        "uq_specimens_current_group",
        "specimens",
        ["order_id", "specimen_type_id", "collection_group"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current"),
    )
    with op.batch_alter_table("specimen_items") as batch:
        batch.drop_constraint("uq_specimen_items_order_item", type_="unique")
    op.execute(
        sa.text(
            "UPDATE specimens SET rejected_by = (SELECT actor_reference FROM audit_logs "
            "WHERE entity_type = 'specimen' AND entity_id = specimens.id "
            "AND event_type = 'SPECIMEN_REJECTED' ORDER BY id DESC LIMIT 1) "
            "WHERE status = 'REJECTED'"
        )
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM specimens WHERE replaces_specimen_id IS NOT NULL")
    ):
        raise RuntimeError("Cannot downgrade while recollection history exists")
    with op.batch_alter_table("specimen_items") as batch:
        batch.create_unique_constraint("uq_specimen_items_order_item", ["order_item_id"])
    op.drop_index("uq_specimens_current_group", table_name="specimens")
    with op.batch_alter_table("specimens") as batch:
        batch.drop_constraint("fk_specimens_replaces_specimen_id_specimens", type_="foreignkey")
        batch.drop_constraint("uq_specimens_replaces_specimen_id", type_="unique")
        batch.drop_column("replaces_specimen_id")
        batch.drop_column("is_current")
        batch.drop_column("rejected_by")
        batch.create_unique_constraint(
            "uq_specimens_order_type_group", ["order_id", "specimen_type_id", "collection_group"]
        )
