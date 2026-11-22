from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.models.order import LabOrder
    from app.models.patient import Patient


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (Index("ix_bookings_appointment_status", "appointment_at", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_number: Mapped[str] = mapped_column(String(30), unique=True)
    appointment_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="BOOKED", server_default="BOOKED")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    source: Mapped[str] = mapped_column(String(50), default="LINE OA", server_default="LINE OA")
    title: Mapped[str | None] = mapped_column(String(30))
    first_name_th: Mapped[str | None] = mapped_column(String(100))
    last_name_th: Mapped[str | None] = mapped_column(String(100))
    sex: Mapped[str | None] = mapped_column(String(20))
    phone_number: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(500))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_relationship: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(30))
    requested_services: Mapped[str | None] = mapped_column(Text)
    requested_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"))
    created_by: Mapped[str] = mapped_column(String(100))
    arrived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    registered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    registered_by: Mapped[str | None] = mapped_column(String(100))
    patient: Mapped["Patient | None"] = relationship()
    order_link: Mapped["BookingOrder | None"] = relationship(
        back_populates="booking", uselist=False
    )

    @property
    def display_name(self) -> str:
        return (
            " ".join(x for x in (self.title, self.first_name_th, self.last_name_th) if x)
            or "ยังไม่ระบุชื่อ"
        )

    @property
    def order_id(self) -> int | None:
        return self.order_link.order_id if self.order_link else None


class BookingOrder(Base):
    __tablename__ = "booking_orders"
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), primary_key=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("lab_orders.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    booking: Mapped[Booking] = relationship(back_populates="order_link")
    order: Mapped["LabOrder"] = relationship()
