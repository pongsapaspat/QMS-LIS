from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, utc_now


class TestCategory(TimestampMixin, Base):
    __tablename__ = "test_categories"
    __table_args__ = (Index("uq_test_categories_code_ci", text("lower(code)"), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name_th: Mapped[str] = mapped_column(String(150), nullable=False)
    name_en: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )

    tests: Mapped[list["LabTest"]] = relationship(back_populates="category")


class LaboratoryDepartment(TimestampMixin, Base):
    __tablename__ = "laboratory_departments"
    __table_args__ = (Index("uq_laboratory_departments_code_ci", text("lower(code)"), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name_th: Mapped[str] = mapped_column(String(150), nullable=False)
    name_en: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    tests: Mapped[list["LabTest"]] = relationship(back_populates="department")


class SpecimenType(TimestampMixin, Base):
    __tablename__ = "specimen_types"
    __table_args__ = (Index("uq_specimen_types_code_ci", text("lower(code)"), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name_th: Mapped[str] = mapped_column(String(150), nullable=False)
    name_en: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )

    tests: Mapped[list["LabTest"]] = relationship(back_populates="specimen_type")


class LabTestDraft(TimestampMixin, Base):
    """A catalog name awaiting configuration; never available for ordering."""

    __tablename__ = "lab_test_drafts"
    __table_args__ = (
        Index("uq_lab_test_drafts_name_ci", text("lower(name)"), unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_outlab: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    completed_test_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_tests.id", ondelete="RESTRICT"), nullable=True, unique=True
    )


class LabTest(TimestampMixin, Base):
    __tablename__ = "lab_tests"
    __table_args__ = (
        Index("uq_lab_tests_code_ci", text("lower(code)"), unique=True),
        Index("ix_lab_tests_names", "name_th", "name_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name_th: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("test_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("laboratory_departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    specimen_type_id: Mapped[int] = mapped_column(
        ForeignKey("specimen_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    result_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    result_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tat_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    panel_entry_options: Mapped[dict[str, list[str]] | None] = mapped_column(JSON, nullable=True)
    is_outlab: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    outlab_lab_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )

    category: Mapped[TestCategory] = relationship(back_populates="tests")
    department: Mapped[LaboratoryDepartment] = relationship(back_populates="tests")
    specimen_type: Mapped[SpecimenType] = relationship(back_populates="tests")
    reference_ranges: Mapped[list["ReferenceRange"]] = relationship(back_populates="test")
    qualitative_options: Mapped[list["QualitativeResultOption"]] = relationship(
        back_populates="test"
    )
    price_history: Mapped[list["TestPriceHistory"]] = relationship(back_populates="test")

    @property
    def entry_options(self) -> dict[str, list[str]]:
        from app.domain.panels import UA_ENTRY_OPTIONS

        defaults = {code: list(values) for code, values in UA_ENTRY_OPTIONS.items()}
        return {**defaults, **(self.panel_entry_options or {})} if self.result_type == "UA" else {}

    @property
    def parameters(self) -> list[dict]:
        from app.domain.panels import panel_definitions

        return panel_definitions(self.result_type)


class ReferenceRange(TimestampMixin, Base):
    __tablename__ = "test_reference_ranges"
    __table_args__ = (Index("ix_reference_ranges_test_active", "test_id", "is_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(
        ForeignKey("lab_tests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sex: Mapped[str] = mapped_column(String(20), nullable=False)
    minimum_age: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_age: Mapped[int] = mapped_column(Integer, nullable=False)
    age_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    lower_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    upper_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    lower_critical: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    upper_critical: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    display_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_metadata: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    test: Mapped[LabTest] = relationship(back_populates="reference_ranges")


class QualitativeResultOption(TimestampMixin, Base):
    __tablename__ = "qualitative_result_options"
    __table_args__ = (
        Index(
            "uq_qualitative_options_test_code_ci",
            "test_id",
            text("lower(code)"),
            unique=True,
        ),
        Index("ix_qualitative_options_test_sort", "test_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(
        ForeignKey("lab_tests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    label_th: Mapped[str] = mapped_column(String(150), nullable=False)
    label_en: Mapped[str] = mapped_column(String(150), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    is_abnormal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False, index=True
    )

    test: Mapped[LabTest] = relationship(back_populates="qualitative_options")


class TestPriceHistory(Base):
    __tablename__ = "test_price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(
        ForeignKey("lab_tests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_reference: Mapped[str] = mapped_column(String(100), nullable=False)

    test: Mapped[LabTest] = relationship(back_populates="price_history")
