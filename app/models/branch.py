from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.patient import Patient


class Branch(TimestampMixin, Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    next_hn_sequence: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False
    )

    patients: Mapped[list["Patient"]] = relationship(back_populates="branch")
