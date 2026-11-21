from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.models.order import LabOrder, LabOrderItem
    from app.models.test_catalog import SpecimenType


class SpecimenStatus(StrEnum):
    PENDING_COLLECTION = "PENDING_COLLECTION"
    COLLECTED = "COLLECTED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"


class Specimen(TimestampMixin, Base):
    __tablename__ = "specimens"
    __table_args__ = (
        UniqueConstraint("order_id", "specimen_type_id", "collection_group",
                         name="uq_specimens_order_type_group"),
        Index("ix_specimens_order_status", "order_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("lab_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    specimen_type_id: Mapped[int] = mapped_column(
        ForeignKey("specimen_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    specimen_type_code: Mapped[str] = mapped_column(String(30), nullable=False)
    collection_group: Mapped[str] = mapped_column(
        String(40), default="INTERNAL", server_default="INTERNAL", nullable=False
    )
    specimen_type_name_th: Mapped[str] = mapped_column(String(150), nullable=False)
    specimen_type_name_en: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default=SpecimenStatus.COLLECTED,
        server_default=SpecimenStatus.COLLECTED,
        nullable=False,
    )
    collected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False
    )
    collected_by: Mapped[str] = mapped_column(String(100), nullable=False)
    collection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    received_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    receiving_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    order: Mapped["LabOrder"] = relationship()
    specimen_type: Mapped["SpecimenType"] = relationship()
    items: Mapped[list["SpecimenItem"]] = relationship(
        back_populates="specimen", cascade="all, delete-orphan", order_by="SpecimenItem.id"
    )


class SpecimenItem(Base):
    __tablename__ = "specimen_items"
    __table_args__ = (
        UniqueConstraint(
            "specimen_id", "order_item_id", name="uq_specimen_items_specimen_order_item"
        ),
        UniqueConstraint("order_item_id", name="uq_specimen_items_order_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    specimen_id: Mapped[int] = mapped_column(
        ForeignKey("specimens.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("lab_order_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False
    )

    specimen: Mapped[Specimen] = relationship(back_populates="items")
    order_item: Mapped["LabOrderItem"] = relationship()
