from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.branch import Branch


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("hn", name="uq_patients_hn"),
        UniqueConstraint("national_id", name="uq_patients_national_id"),
        UniqueConstraint("passport_number", name="uq_patients_passport_number"),
        Index("ix_patients_branch_name_th", "branch_id", "last_name_th", "first_name_th"),
        Index("ix_patients_branch_name_en", "branch_id", "last_name_en", "first_name_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"),
        default=1,
        server_default=text("1"),
        nullable=True,
        index=True,
    )
    hn: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(30), nullable=True)
    first_name_th: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name_th: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_name_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(13), nullable=True)
    passport_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    emergency_contact_relationship: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    identity_document_missing: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False, index=True
    )

    branch: Mapped["Branch | None"] = relationship(back_populates="patients")

    @property
    def display_name(self) -> str:
        thai_name = " ".join(part for part in (self.first_name_th, self.last_name_th) if part)
        english_name = " ".join(part for part in (self.first_name_en, self.last_name_en) if part)
        return thai_name or english_name or "Unnamed patient"
