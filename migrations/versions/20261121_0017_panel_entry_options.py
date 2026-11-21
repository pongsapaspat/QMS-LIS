"""Store editable dropdown choices per test parameter."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0017"
down_revision = "20261120_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lab_tests", sa.Column("panel_entry_options", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("lab_tests", "panel_entry_options")
