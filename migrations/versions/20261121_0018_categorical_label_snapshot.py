"""Snapshot qualitative labels and resolve existing result codes."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0018"
down_revision = "20261121_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("results", sa.Column("categorical_label_snapshot", sa.JSON(), nullable=True))
    results = sa.table(
        "results",
        sa.column("id", sa.Integer),
        sa.column("order_item_id", sa.Integer),
        sa.column("categorical_value", sa.String),
        sa.column("categorical_label_snapshot", sa.JSON),
    )
    items = sa.table("lab_order_items", sa.column("id"), sa.column("lab_test_id"))
    options = sa.table(
        "qualitative_result_options",
        sa.column("test_id"),
        sa.column("code"),
        sa.column("label_th"),
        sa.column("label_en"),
    )
    connection = op.get_bind()
    # Older results have no historic labels; freeze the currently configured wording.
    rows = (
        connection.execute(
            sa.select(
                results.c.id, options.c.code, options.c.label_th, options.c.label_en
            ).select_from(
                results.join(items, results.c.order_item_id == items.c.id).join(
                    options,
                    sa.and_(
                        options.c.test_id == items.c.lab_test_id,
                        options.c.code == results.c.categorical_value,
                    ),
                )
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        connection.execute(
            results.update()
            .where(results.c.id == row["id"])
            .values(
                categorical_label_snapshot={
                    "code": row["code"],
                    "label_th": row["label_th"],
                    "label_en": row["label_en"],
                }
            )
        )


def downgrade():
    op.drop_column("results", "categorical_label_snapshot")
