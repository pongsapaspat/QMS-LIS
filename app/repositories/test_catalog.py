from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.test_catalog import (
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

    def test_code_exists(self, code: str) -> bool:
        statement = select(LabTest.id).where(func.lower(LabTest.code) == code.casefold()).limit(1)
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
            .options(selectinload(LabTest.category), selectinload(LabTest.specimen_type))
            .where(LabTest.id == test_id)
        )
        return self.session.scalars(statement).first()

    def list_tests(
        self,
        *,
        search: str | None,
        category_id: int | None,
        specimen_type_id: int | None,
        result_type: str | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[LabTest], int]:
        statement = select(LabTest).options(
            selectinload(LabTest.category), selectinload(LabTest.specimen_type)
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
