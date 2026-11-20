from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.test_catalog import LabTest


class TestPackage(TimestampMixin, Base):
    __tablename__ = "test_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    tests: Mapped[list[LabTest]] = relationship(
        secondary="test_package_items",
        lazy="selectin",
        order_by="LabTest.code",
    )

    @property
    def available(self) -> bool:
        return (
            self.is_active
            and bool(self.tests)
            and all(
                t.is_active
                and t.department.is_active
                and t.category.is_active
                and t.specimen_type.is_active
                for t in self.tests
            )
        )


class TestPackageItem(Base):
    __tablename__ = "test_package_items"

    package_id: Mapped[int] = mapped_column(
        ForeignKey("test_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    test_id: Mapped[int] = mapped_column(
        ForeignKey("lab_tests.id", ondelete="RESTRICT"),
        primary_key=True,
    )
