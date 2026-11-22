"""Configure specimen collection rooms without changing specimen history."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_0025"
down_revision = "20261121_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("specimen_types", sa.Column("collection_room", sa.String(30), nullable=True))
    types = sa.table(
        "specimen_types", sa.column("name_en"), sa.column("collection_room")
    )
    # Match known specimen names; unfamiliar types stay visible under All until configured.
    defaults = {
        "URINE_STOOL": ("urine", "stool"),
        "SWAB": ("swab",),
        "BLOOD": (
            "blood", "whole blood", "serum", "plasma", "edta blood", "edta plasma",
            "li-heparinized plasma", "lithium heparin plasma", "citrate plasma",
        ),
    }
    for room, names in defaults.items():
        op.execute(types.update().where(
            sa.func.lower(sa.func.trim(types.c.name_en)).in_(names)
        ).values(collection_room=room))


def downgrade():
    op.drop_column("specimen_types", "collection_room")
