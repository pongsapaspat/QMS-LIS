from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime

if TYPE_CHECKING:
    from app.models.order import LabOrderItem


class OutlabCase(Base):
    __tablename__ = "outlab_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("lab_order_items.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="PENDING_SEND", nullable=False)
    lab_name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(150))
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sent_by: Mapped[str | None] = mapped_column(String(100))
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    received_by: Mapped[str | None] = mapped_column(String(100))
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    checked_by: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    order_item: Mapped["LabOrderItem"] = relationship(back_populates="outlab")
    documents: Mapped[list["OutlabDocument"]] = relationship(
        back_populates="case", order_by="OutlabDocument.id"
    )

    @property
    def ready(self) -> bool:
        return (
            self.status == "CHECKED"
            and self.checked_at is not None
            and bool(self.checked_by)
            and bool(self.documents)
        )


class OutlabDocument(Base):
    __tablename__ = "outlab_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("outlab_cases.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(100), nullable=False)
    case: Mapped[OutlabCase] = relationship(back_populates="documents")
