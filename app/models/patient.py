from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("branch_id", "hn", name="uq_patients_branch_hn"),
        UniqueConstraint("thai_national_id", name="uq_patients_thai_national_id"),
        UniqueConstraint("passport_number", name="uq_patients_passport_number"),
        Index("ix_patients_branch_name", "branch_id", "last_name", "first_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"),
        default=1,
        server_default=text("1"),
        nullable=False,
        index=True,
    )
    hn: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    thai_national_id: Mapped[str | None] = mapped_column(String(13), nullable=True)
    passport_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False, index=True
    )

    branch: Mapped["Branch"] = relationship(back_populates="patients")


from app.models.branch import Branch  # noqa: E402
