from typing import cast

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.test_catalog import (
    LaboratoryDepartment,
    LabTest,
    QualitativeResultOption,
    ReferenceRange,
    SpecimenType,
    TestCategory,
    TestPriceHistory,
)


class TestCatalogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: object) -> None:
        self.session.add(entity)
        self.session.flush()

    def flush(self) -> None:
        self.session.flush()

    def get_category(self, category_id: int) -> TestCategory | None:
        return self.session.get(TestCategory, category_id)

    def get_or_create_general_department(self) -> LaboratoryDepartment:
        department = self.session.scalars(
            select(LaboratoryDepartment).where(LaboratoryDepartment.code == "GENERAL")
        ).first()
        if department is None:
            department = LaboratoryDepartment(code="GENERAL", name_th="ทั่วไป", name_en="General")
            self.session.add(department)
            self.session.flush()
        return department

    def get_department(self, department_id: int) -> LaboratoryDepartment | None:
        return self.session.get(LaboratoryDepartment, department_id)

    def department_code_exists(
        self, code: str, *, exclude_department_id: int | None = None
    ) -> bool:
        statement = select(LaboratoryDepartment.id).where(
            func.lower(LaboratoryDepartment.code) == code.casefold()
        )
        if exclude_department_id is not None:
            statement = statement.where(LaboratoryDepartment.id != exclude_department_id)
        return self.session.execute(statement.limit(1)).scalar_one_or_none() is not None

    def list_departments(
        self,
        *,
        search: str | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[LaboratoryDepartment, int]], int]:
        test_counts = (
            select(LabTest.department_id, func.count(LabTest.id).label("test_count"))
            .group_by(LabTest.department_id)
            .subquery()
        )
        statement = select(
            LaboratoryDepartment,
            func.coalesce(test_counts.c.test_count, 0),
        ).outerjoin(test_counts, test_counts.c.department_id == LaboratoryDepartment.id)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    LaboratoryDepartment.code.ilike(term),
                    LaboratoryDepartment.name_th.ilike(term),
                    LaboratoryDepartment.name_en.ilike(term),
                )
            )
        if is_active is not None:
            statement = statement.where(LaboratoryDepartment.is_active.is_(is_active))
        total = self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        rows = self.session.execute(
            statement.order_by(
                LaboratoryDepartment.is_active.desc(), LaboratoryDepartment.code
            )
            .offset(offset)
            .limit(limit)
        )
        results: list[tuple[LaboratoryDepartment, int]] = []
        for department, count in rows:
            results.append(
                (cast(LaboratoryDepartment, department), cast(int, count))
            )
        return results, total

    def count_department_tests(self, department_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(LabTest.id)).where(LabTest.department_id == department_id)
            )
            or 0
        )

    def list_department_tests(self, department_id: int) -> list[LabTest]:
        statement = (
            select(LabTest)
            .options(
                selectinload(LabTest.category),
                selectinload(LabTest.department),
                selectinload(LabTest.specimen_type),
            )
            .where(LabTest.department_id == department_id)
            .order_by(LabTest.code)
        )
        return list(self.session.scalars(statement))

    def get_specimen_type(self, specimen_type_id: int) -> SpecimenType | None:
        return self.session.get(SpecimenType, specimen_type_id)

    def list_categories(self, include_inactive: bool = False) -> list[TestCategory]:
        statement = select(TestCategory)
        if not include_inactive:
            statement = statement.where(TestCategory.is_active.is_(True))
        return list(self.session.scalars(statement.order_by(TestCategory.code)))

    def list_specimen_types(self, include_inactive: bool = False) -> list[SpecimenType]:
        statement = select(SpecimenType)
        if not include_inactive:
            statement = statement.where(SpecimenType.is_active.is_(True))
        return list(self.session.scalars(statement.order_by(SpecimenType.code)))

    def configuration_code_exists(
        self, model: type[TestCategory] | type[SpecimenType], code: str
    ) -> bool:
        statement = select(model.id).where(func.lower(model.code) == code.casefold()).limit(1)
        return self.session.execute(statement).scalar_one_or_none() is not None

    def test_code_exists(self, code: str, exclude_test_id: int | None = None) -> bool:
        statement = select(LabTest.id).where(func.lower(LabTest.code) == code.casefold())
        if exclude_test_id is not None:
            statement = statement.where(LabTest.id != exclude_test_id)
        statement = statement.limit(1)
        return self.session.execute(statement).scalar_one_or_none() is not None

    def active_test_uses_category(self, category_id: int) -> bool:
        statement = (
            select(LabTest.id)
            .where(LabTest.category_id == category_id, LabTest.is_active.is_(True))
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none() is not None

    def active_test_uses_specimen_type(self, specimen_type_id: int) -> bool:
        statement = (
            select(LabTest.id)
            .where(
                LabTest.specimen_type_id == specimen_type_id,
                LabTest.is_active.is_(True),
            )
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none() is not None

    def get_test(self, test_id: int) -> LabTest | None:
        statement = (
            select(LabTest)
            .options(
                selectinload(LabTest.category),
                selectinload(LabTest.department),
                selectinload(LabTest.specimen_type),
            )
            .where(LabTest.id == test_id)
        )
        return self.session.scalars(statement).first()

    def list_tests(
        self,
        *,
        search: str | None,
        category_id: int | None,
        department_id: int | None,
        specimen_type_id: int | None,
        result_type: str | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[LabTest], int]:
        statement = select(LabTest).options(
            selectinload(LabTest.category),
            selectinload(LabTest.department),
            selectinload(LabTest.specimen_type),
        )
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    LabTest.code.ilike(term),
                    LabTest.name_th.ilike(term),
                    LabTest.name_en.ilike(term),
                )
            )
        if category_id is not None:
            statement = statement.where(LabTest.category_id == category_id)
        if department_id is not None:
            statement = statement.where(LabTest.department_id == department_id)
        if specimen_type_id is not None:
            statement = statement.where(LabTest.specimen_type_id == specimen_type_id)
        if result_type is not None:
            statement = statement.where(LabTest.result_type == result_type)
        if is_active is not None:
            statement = statement.where(LabTest.is_active.is_(is_active))
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        total = self.session.execute(count_statement).scalar_one()
        statement = statement.order_by(LabTest.code).offset(offset).limit(limit)
        return list(self.session.scalars(statement)), total

    def get_reference_range(self, range_id: int) -> ReferenceRange | None:
        return self.session.get(ReferenceRange, range_id)

    def list_reference_ranges(self, test_id: int) -> list[ReferenceRange]:
        statement = (
            select(ReferenceRange)
            .where(ReferenceRange.test_id == test_id)
            .order_by(ReferenceRange.sex, ReferenceRange.minimum_age)
        )
        return list(self.session.scalars(statement))

    def get_qualitative_option(self, option_id: int) -> QualitativeResultOption | None:
        return self.session.get(QualitativeResultOption, option_id)

    def qualitative_option_code_exists(self, test_id: int, code: str) -> bool:
        statement = (
            select(QualitativeResultOption.id)
            .where(
                QualitativeResultOption.test_id == test_id,
                func.lower(QualitativeResultOption.code) == code.casefold(),
            )
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none() is not None

    def list_qualitative_options(self, test_id: int) -> list[QualitativeResultOption]:
        statement = (
            select(QualitativeResultOption)
            .where(QualitativeResultOption.test_id == test_id)
            .order_by(QualitativeResultOption.sort_order, QualitativeResultOption.id)
        )
        return list(self.session.scalars(statement))

    def list_price_history(self, test_id: int) -> list[TestPriceHistory]:
        statement = (
            select(TestPriceHistory)
            .where(TestPriceHistory.test_id == test_id)
            .order_by(TestPriceHistory.effective_at.desc(), TestPriceHistory.id.desc())
        )
        return list(self.session.scalars(statement))
