from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.models.order import LabOrderItem
    from app.models.specimen import Specimen


class ResultStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (
        Index("ix_results_status", "status"),
        Index("ix_results_specimen", "specimen_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("lab_order_items.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    specimen_id: Mapped[int] = mapped_column(
        ForeignKey("specimens.id", ondelete="RESTRICT"), nullable=False
    )
    result_type: Mapped[str] = mapped_column(String(20), nullable=False)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    categorical_value: Mapped[str | None] = mapped_column(String(150), nullable=True)
    result_unit_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_range_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    abnormal_flag: Mapped[str | None] = mapped_column(String(2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ResultStatus.PENDING, nullable=False)
    entered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    entered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_modified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_modified_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    critical_acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    critical_acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    order_item: Mapped["LabOrderItem"] = relationship(back_populates="result")
    specimen: Mapped["Specimen"] = relationship()
    revisions: Mapped[list["ResultRevision"]] = relationship(back_populates="result")


class ResultRevision(Base):
    __tablename__ = "result_revisions"
    __table_args__ = (Index("ix_result_revisions_result", "result_id", "modified_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("results.id", ondelete="RESTRICT"), nullable=False
    )
    previous_value: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    previous_flag: Mapped[str | None] = mapped_column(String(2), nullable=True)
    new_flag: Mapped[str | None] = mapped_column(String(2), nullable=True)
    modification_reason: Mapped[str] = mapped_column(Text, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    modified_by: Mapped[str] = mapped_column(String(100), nullable=False)
    result: Mapped[Result] = relationship(back_populates="revisions")


@event.listens_for(ResultRevision, "before_update")
@event.listens_for(ResultRevision, "before_delete")
def prevent_result_revision_mutation(
    mapper: object, connection: object, target: ResultRevision
) -> None:
    raise RuntimeError("result revisions are immutable")
