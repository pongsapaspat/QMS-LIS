"""Professional identities and historical report signatures."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0021"
down_revision = "20261121_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("full_name", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("professional_license_number", sa.String(100), nullable=True))
    for name, length in (
        ("referrer_name", 200),
        ("referrer_organization", 200),
        ("referrer_license_type", 50),
        ("referrer_license_number", 100),
    ):
        op.add_column("lab_orders", sa.Column(name, sa.String(length), nullable=True))
    op.add_column("lab_orders", sa.Column("released_by_snapshot", sa.JSON(), nullable=True))
    for name in (
        "entered_by_snapshot",
        "last_modified_by_snapshot",
        "verified_by_snapshot",
        "released_by_snapshot",
    ):
        op.add_column("results", sa.Column(name, sa.JSON(), nullable=True))
    # Existing usernames remain authoritative; today's profile cannot prove historic credentials.


def downgrade():
    for name in (
        "entered_by_snapshot",
        "last_modified_by_snapshot",
        "verified_by_snapshot",
        "released_by_snapshot",
    ):
        op.drop_column("results", name)
    for name in (
        "released_by_snapshot",
        "referrer_license_number",
        "referrer_license_type",
        "referrer_organization",
        "referrer_name",
    ):
        op.drop_column("lab_orders", name)
    op.drop_column("users", "professional_license_number")
    op.drop_column("users", "full_name")
