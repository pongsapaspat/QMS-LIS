
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, TimestampMixin, utc_now

if TYPE_CHECKING:
    from app.models.patient import Patient


class OrderStatus(StrEnum):
    ORDERED = "ORDERED"
    CANCELLED = "CANCELLED"


class OrderPriority(StrEnum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class LabOrder(TimestampMixin, Base):
    __tablename__ = "lab_orders"
    __table_args__ = (Index("ix_lab_orders_patient_ordered_at", "patient_id", "ordered_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=OrderStatus.ORDERED,
        server_default=OrderStatus.ORDERED,
        nullable=False,
    )
    priority: Mapped[str] = mapped_column(
        String(20),
        default=OrderPriority.ROUTINE,
        server_default=OrderPriority.ROUTINE,
        nullable=False,
    )
    clinical_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)

    patient: Mapped["Patient"] = relationship()
    items: Mapped[list["LabOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="LabOrderItem.id"
    )

    @property
    def total_price(self) -> Decimal:
        return sum((item.price for item in self.items), Decimal("0.00"))


class LabOrderItem(Base):
    __tablename__ = "lab_order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "lab_test_id", name="uq_lab_order_items_order_test"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("lab_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lab_test_id: Mapped[int] = mapped_column(
        ForeignKey("lab_tests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    test_code: Mapped[str] = mapped_column(String(40), nullable=False)
    test_name_th: Mapped[str] = mapped_column(String(200), nullable=False)
    test_name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    result_type: Mapped[str] = mapped_column(String(20), nullable=False)
    result_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False
    )

    order: Mapped[LabOrder] = relationship(back_populates="items")
