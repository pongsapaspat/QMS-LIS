from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.models.outlab import OutlabCase
    from app.models.patient import Patient
    from app.models.result import Result
    from app.models.test_catalog import LabTest


class OrderStatus(StrEnum):
    ORDERED = "ORDERED"
    SPECIMENS_RECEIVED = "SPECIMENS_RECEIVED"
    RESULTS_IN_PROGRESS = "RESULTS_IN_PROGRESS"
    RESULTS_COMPLETED = "RESULTS_COMPLETED"
    RESULTS_VERIFIED = "RESULTS_VERIFIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class OrderPriority(StrEnum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class LabOrder(TimestampMixin, Base):
    __tablename__ = "lab_orders"
    __table_args__ = (
        Index("ix_lab_orders_patient_ordered_at", "patient_id", "ordered_at"),
        Index("ix_lab_orders_status_priority", "status", "priority"),
    )

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
    referrer_name: Mapped[str | None] = mapped_column(String(200))
    referrer_organization: Mapped[str | None] = mapped_column(String(200))
    referrer_license_type: Mapped[str | None] = mapped_column(String(50))
    referrer_license_number: Mapped[str | None] = mapped_column(String(100))
    released_by_snapshot: Mapped[dict[str, str | None] | None] = mapped_column(JSON)
    package_snapshots: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    ordered_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by_snapshot: Mapped[dict[str, str | None] | None] = mapped_column(JSON)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    verified_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    released_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    patient: Mapped["Patient"] = relationship()
    items: Mapped[list["LabOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="LabOrderItem.id"
    )

    @property
    def total_price(self) -> Decimal:
        package_price = sum((Decimal(p['price']) for p in self.package_snapshots or []),
                            Decimal('0.00'))
        return package_price + sum((item.price for item in self.items
                                    if item.lab_test_id not in self.package_test_ids),
                                   Decimal('0.00'))

    @property
    def package_test_ids(self) -> set[int]:
        return {test_id for p in self.package_snapshots or [] for test_id in p['test_ids']}


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
    parameter_definitions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    is_outlab: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False
    )

    order: Mapped[LabOrder] = relationship(back_populates="items")
    lab_test: Mapped["LabTest"] = relationship()
    result: Mapped["Result | None"] = relationship(back_populates="order_item", uselist=False)
    outlab: Mapped["OutlabCase | None"] = relationship(back_populates="order_item", uselist=False)

    @property
    def included_in_package(self) -> bool:
        return self.lab_test_id in self.order.package_test_ids
