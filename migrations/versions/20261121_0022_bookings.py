"""Reception booking drafts and explicit patient/order linkage."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0022"
down_revision = "20261121_0021"
branch_labels = None
depends_on = None


def upgrade():
    columns = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_number", sa.String(30), nullable=False, unique=True),
        sa.Column("appointment_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="BOOKED"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(50), nullable=False, server_default="LINE OA"),
    ]
    for name, length in (
        ("title", 30),
        ("first_name_th", 100),
        ("last_name_th", 100),
        ("sex", 20),
        ("phone_number", 30),
        ("address", 500),
        ("emergency_contact_name", 200),
        ("emergency_contact_relationship", 100),
        ("emergency_contact_phone", 30),
    ):
        columns.append(sa.Column(name, sa.String(length), nullable=True))
    columns += [
        sa.Column("requested_services", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("requested_items", sa.JSON(), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="RESTRICT")),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("arrived_at", sa.DateTime(timezone=True)),
        sa.Column("registered_at", sa.DateTime(timezone=True)),
        sa.Column("registered_by", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]
    op.create_table("bookings", *columns)
    op.create_index("ix_bookings_appointment_status", "bookings", ["appointment_at", "status"])
    op.create_table(
        "booking_orders",
        sa.Column(
            "booking_id",
            sa.Integer(),
            sa.ForeignKey("bookings.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("lab_orders.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade():
    op.drop_table("booking_orders")
    op.drop_index("ix_bookings_appointment_status", table_name="bookings")
    op.drop_table("bookings")
