from decimal import Decimal
from typing import TypeVar, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import ResultType
from app.domain.exceptions import (
    CatalogNotFoundError,
    DuplicateCatalogCodeError,
    InvalidCatalogOperationError,
)
from app.models.audit import AuditLog
from app.models.test_catalog import (
    LaboratoryDepartment,
    LabTest,
    LabTestDraft,
    QualitativeResultOption,
    ReferenceRange,
    SpecimenType,
    TestCategory,
    TestPriceHistory,
)
from app.repositories.audit import AuditRepository
from app.repositories.test_catalog import TestCatalogRepository
from app.schemas.test_catalog import (
    ActivationRequest,
    CatalogTestCreate,
    CatalogTestUpdate,
    ConfigurationCreate,
    ConfigurationUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    QualitativeOptionCreate,
    QualitativeOptionUpdate,
    ReferenceRangeCreate,
    ReferenceRangeUpdate,
)

CatalogEntity = (
    TestCategory
    | SpecimenType
    | LaboratoryDepartment
    | LabTest
    | LabTestDraft
    | ReferenceRange
    | QualitativeResultOption
)
CatalogChild = TypeVar("CatalogChild", ReferenceRange, QualitativeResultOption)


class TestCatalogService:
    def __init__(
        self,
        session: Session,
        repository: TestCatalogRepository | None = None,
        audit_repository: AuditRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or TestCatalogRepository(session)
        self.audit_repository = audit_repository or AuditRepository(session)

    def create_category(self, data: ConfigurationCreate, *, actor_reference: str) -> TestCategory:
        return cast(
            TestCategory,
            self._create_configuration(TestCategory, data, actor_reference=actor_reference),
        )

    def list_categories(self, *, include_inactive: bool = False) -> list[TestCategory]:
        return self.repository.list_categories(include_inactive)

    def update_category(
        self,
        category_id: int,
        data: ConfigurationUpdate,
        *,
        actor_reference: str,
    ) -> TestCategory:
        category = self.repository.get_category(category_id)
        if category is None:
            raise CatalogNotFoundError("test category not found")
        if (
            data.is_active is False
            and category.is_active
            and self.repository.active_test_uses_category(category.id)
        ):
            raise InvalidCatalogOperationError("cannot deactivate a category used by active tests")
        return cast(
            TestCategory,
            self._update_configuration(category, data, actor_reference=actor_reference),
        )

    def create_specimen_type(
        self, data: ConfigurationCreate, *, actor_reference: str
    ) -> SpecimenType:
        return cast(
            SpecimenType,
            self._create_configuration(SpecimenType, data, actor_reference=actor_reference),
        )

    def list_specimen_types(self, *, include_inactive: bool = False) -> list[SpecimenType]:
        return self.repository.list_specimen_types(include_inactive)

    def update_specimen_type(
        self,
        specimen_type_id: int,
        data: ConfigurationUpdate,
        *,
        actor_reference: str,
    ) -> SpecimenType:
        specimen_type = self.repository.get_specimen_type(specimen_type_id)
        if specimen_type is None:
            raise CatalogNotFoundError("specimen type not found")
        if (
            data.is_active is False
            and specimen_type.is_active
            and self.repository.active_test_uses_specimen_type(specimen_type.id)
        ):
            raise InvalidCatalogOperationError(
                "cannot deactivate a specimen type used by active tests"
            )
        return cast(
            SpecimenType,
            self._update_configuration(specimen_type, data, actor_reference=actor_reference),
        )

    def create_department(
        self, data: DepartmentCreate, *, actor_reference: str
    ) -> LaboratoryDepartment:
        if self.repository.department_code_exists(data.code):
            raise DuplicateCatalogCodeError("department code already exists")
        values = data.model_dump(exclude={"reason"})
        department = LaboratoryDepartment(**values)
        try:
            self.repository.add(department)
            self._audit(
                "LABORATORY_DEPARTMENT_CREATED",
                "laboratory_department",
                department,
                set(values),
                data.reason,
                actor_reference,
            )
            self.session.commit()
            self.session.refresh(department)
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateCatalogCodeError("department code already exists") from exc
        return department

    def get_department(self, department_id: int) -> LaboratoryDepartment:
        department = self.repository.get_department(department_id)
        if department is None:
            raise CatalogNotFoundError("laboratory department not found")
        return department

    def list_departments(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[LaboratoryDepartment, int]], int]:
        return self.repository.list_departments(
            search=search, is_active=is_active, offset=offset, limit=min(limit, 200)
        )

    def list_department_tests(self, department_id: int) -> list[LabTest]:
        self.get_department(department_id)
        return self.repository.list_department_tests(department_id)

    def update_department(
        self,
        department_id: int,
        data: DepartmentUpdate,
        *,
        actor_reference: str,
    ) -> LaboratoryDepartment:
        department = self.get_department(department_id)
        changes = data.model_dump(exclude_unset=True, exclude={"reason"})
        if "code" in changes and self.repository.department_code_exists(
            str(changes["code"]), exclude_department_id=department.id
        ):
            raise DuplicateCatalogCodeError("department code already exists")
        actual_changes = {
            field: value
            for field, value in changes.items()
            if getattr(department, field) != value
        }
        if not actual_changes:
            raise InvalidCatalogOperationError("no department data changed")
        for field, value in actual_changes.items():
            setattr(department, field, value)
        self._finish_mutation(
            "LABORATORY_DEPARTMENT_UPDATED",
            "laboratory_department",
            department,
            set(actual_changes),
            data.reason,
            actor_reference,
        )
        return department

    def set_department_activation(
        self,
        department_id: int,
        data: ActivationRequest,
        *,
        actor_reference: str,
    ) -> LaboratoryDepartment:
        department = self.get_department(department_id)
        if department.is_active == data.is_active:
            raise InvalidCatalogOperationError("department activation state did not change")
        department.is_active = data.is_active
        event = (
            "LABORATORY_DEPARTMENT_ACTIVATED"
            if data.is_active
            else "LABORATORY_DEPARTMENT_DEACTIVATED"
        )
        self._finish_mutation(
            event,
            "laboratory_department",
            department,
            {"is_active"},
            data.reason,
            actor_reference,
        )
        return department

    def create_test_draft(
        self, name: str, *, is_outlab: bool, actor_reference: str
    ) -> LabTestDraft:
        name = " ".join(name.split())
        if not name or len(name) > 200:
            raise InvalidCatalogOperationError("test name must contain 1–200 characters")
        draft = LabTestDraft(name=name, is_outlab=is_outlab)
        try:
            self.repository.add(draft)
            self._audit(
                "LAB_TEST_DRAFT_CREATED", "lab_test_draft", draft,
                {"name", "is_outlab"}, "Add name pending catalog configuration", actor_reference,
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateCatalogCodeError("draft test name already exists") from exc
        return draft

    def get_test_draft(self, draft_id: int) -> LabTestDraft:
        draft = self.repository.get_test_draft(draft_id)
        if draft is None:
            raise CatalogNotFoundError("draft test not found")
        return draft

    def list_test_drafts(self, search: str | None = None) -> list[LabTestDraft]:
        return self.repository.list_test_drafts(search)

    def create_test(
        self, data: CatalogTestCreate, *, actor_reference: str, draft_id: int | None = None
    ) -> LabTest:
        draft = self.get_test_draft(draft_id) if draft_id is not None else None
        if draft is not None and draft.completed_test_id is not None:
            raise InvalidCatalogOperationError("รายการนี้กรอกรายละเอียดเรียบร้อยแล้ว")
        self._require_active_configuration(
            data.category_id, data.department_id, data.specimen_type_id
        )
        if not data.is_outlab:
            self._validate_test_configuration(data.result_type, data.result_unit)
        if self.repository.test_code_exists(data.code):
            raise DuplicateCatalogCodeError("test code already exists")

        values = data.model_dump(exclude={"reason"})
        test = LabTest(**values)
        try:
            self.repository.add(test)
            self.repository.add(
                TestPriceHistory(
                    test_id=test.id,
                    old_price=None,
                    new_price=test.current_price,
                    reason=data.reason,
                    actor_reference=actor_reference,
                )
            )
            self._audit(
                "LAB_TEST_CREATED",
                "lab_test",
                test,
                {*values, "is_active"},
                data.reason,
                actor_reference,
            )
            if draft is not None:
                if not self.repository.complete_test_draft(draft.id, test.id):
                    raise InvalidCatalogOperationError("รายการนี้กรอกรายละเอียดเรียบร้อยแล้ว")
                self._audit(
                    "LAB_TEST_DRAFT_COMPLETED", "lab_test_draft", draft,
                    {"completed_test_id"}, data.reason, actor_reference,
                )
            self.session.commit()
            self.session.refresh(test)
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateCatalogCodeError("test code already exists") from exc
        except InvalidCatalogOperationError:
            self.session.rollback()
            raise
        return self.get_test(test.id)

    def get_test(self, test_id: int) -> LabTest:
        test = self.repository.get_test(test_id)
        if test is None:
            raise CatalogNotFoundError("lab test not found")
        return test

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
        return self.repository.list_tests(
            search=search,
            category_id=category_id,
            department_id=department_id,
            specimen_type_id=specimen_type_id,
            result_type=result_type,
            is_active=is_active,
            offset=offset,
            limit=limit,
        )

    def update_test(
        self,
        test_id: int,
        data: CatalogTestUpdate,
        *,
        actor_reference: str,
    ) -> LabTest:
        test = self.get_test(test_id)
        changes = data.model_dump(exclude_unset=True, exclude={"reason"})
        resulting_category_id = changes.get("category_id", test.category_id)
        is_outlab = changes.get("is_outlab", bool(test.is_outlab))
        if is_outlab is None or (
            is_outlab and not changes.get("outlab_lab_name", test.outlab_lab_name)
        ):
            raise InvalidCatalogOperationError("Outlab laboratory name is required")
        resulting_department_id = changes.get("department_id", test.department_id)
        resulting_specimen_type_id = changes.get("specimen_type_id", test.specimen_type_id)
        if not all(
            isinstance(value, int)
            for value in (
                resulting_category_id,
                resulting_department_id,
                resulting_specimen_type_id,
            )
        ):
            raise InvalidCatalogOperationError(
                "category, department, and specimen type are required"
            )
        self._require_editable_configuration(
            test,
            resulting_category_id,
            resulting_department_id,
            resulting_specimen_type_id,
        )
        if "code" in changes and self.repository.test_code_exists(
            changes["code"], exclude_test_id=test.id
        ):
            raise DuplicateCatalogCodeError("test code already exists")

        result_type = changes.get("result_type", test.result_type)
        result_unit = changes.get("result_unit", test.result_unit)
        if not is_outlab:
            self._validate_test_configuration(result_type, result_unit)
        if result_type != test.result_type:
            if result_type in {
                ResultType.QUALITATIVE,
                ResultType.CATEGORICAL,
            } and self.repository.list_reference_ranges(test.id):
                raise InvalidCatalogOperationError(
                    "a test with reference ranges cannot become qualitative"
                )
            if result_type == ResultType.NUMERIC and self.repository.list_qualitative_options(
                test.id
            ):
                raise InvalidCatalogOperationError(
                    "a test with qualitative options cannot become numeric"
                )

        required_text = ("name_th", "name_en")
        if any(changes.get(field, getattr(test, field)) is None for field in required_text):
            raise InvalidCatalogOperationError("test names are required")
        if changes.get("current_price", test.current_price) is None:
            raise InvalidCatalogOperationError("current price is required")
        if changes.get("tat_minutes", test.tat_minutes) is None:
            raise InvalidCatalogOperationError("turnaround time is required")

        actual_changes = {
            field: value for field, value in changes.items() if getattr(test, field) != value
        }
        if not actual_changes:
            raise InvalidCatalogOperationError("no test data changed")

        old_price = test.current_price
        for field, value in actual_changes.items():
            setattr(test, field, value)
        try:
            self.repository.flush()
            if "current_price" in actual_changes:
                self.repository.add(
                    TestPriceHistory(
                        test_id=test.id,
                        old_price=old_price,
                        new_price=test.current_price,
                        reason=data.reason,
                        actor_reference=actor_reference,
                    )
                )
            ordinary_changes = set(actual_changes) - {"department_id"}
            if ordinary_changes:
                self._audit(
                    "LAB_TEST_UPDATED",
                    "lab_test",
                    test,
                    ordinary_changes,
                    data.reason,
                    actor_reference,
                )
            if "department_id" in actual_changes:
                self._audit(
                    "LAB_TEST_DEPARTMENT_CHANGED",
                    "lab_test",
                    test,
                    {"department_id"},
                    data.reason,
                    actor_reference,
                )
            self.session.commit()
            self.session.refresh(test)
        except IntegrityError as exc:
            self.session.rollback()
            raise InvalidCatalogOperationError("test update violates catalog constraints") from exc
        return self.get_test(test.id)

    def set_test_activation(
        self,
        test_id: int,
        data: ActivationRequest,
        *,
        actor_reference: str,
    ) -> LabTest:
        test = self.get_test(test_id)
        if test.is_active == data.is_active:
            raise InvalidCatalogOperationError("test activation state did not change")
        if data.is_active:
            self._require_active_configuration(
                test.category_id, test.department_id, test.specimen_type_id
            )
        test.is_active = data.is_active
        event = "LAB_TEST_ACTIVATED" if data.is_active else "LAB_TEST_DEACTIVATED"
        self._finish_mutation(event, "lab_test", test, {"is_active"}, data.reason, actor_reference)
        return self.get_test(test.id)

    def list_reference_ranges(self, test_id: int) -> list[ReferenceRange]:
        self.get_test(test_id)
        return self.repository.list_reference_ranges(test_id)

    def update_panel_entry_options(
        self, test_id: int, code: str, options_text: str, reason: str, *, actor_reference: str
    ) -> None:
        test = self.get_test(test_id)
        parameter = next((p for p in test.parameters if p["code"] == code), None)
        if test.result_type != "UA" or parameter is None or parameter["kind"] == "NUMERIC":
            raise InvalidCatalogOperationError("This parameter does not support dropdown options")
        choices = [" ".join(line.split()) for line in options_text.splitlines() if line.strip()]
        if not choices or len(choices) > 100 or any(len(value) > 150 for value in choices):
            raise InvalidCatalogOperationError("Enter 1–100 options, at most 150 characters each")
        if len({value.casefold() for value in choices}) != len(choices):
            raise InvalidCatalogOperationError("Dropdown options must not contain duplicates")
        if not reason.strip() or len(reason.strip()) > 500:
            raise InvalidCatalogOperationError("Enter a change reason (at most 500 characters)")
        test.panel_entry_options = {**(test.panel_entry_options or {}), code: choices}
        self._finish_mutation(
            "PANEL_ENTRY_OPTIONS_UPDATED", "lab_test", test,
            {"panel_entry_options"}, reason.strip(), actor_reference,
        )

    def list_qualitative_options(self, test_id: int) -> list[QualitativeResultOption]:
        self.get_test(test_id)
        return self.repository.list_qualitative_options(test_id)

    def list_price_history(self, test_id: int) -> list[TestPriceHistory]:
        self.get_test(test_id)
        return self.repository.list_price_history(test_id)

    def list_test_audit_history(self, test_id: int) -> list[AuditLog]:
        self.get_test(test_id)
        entries = self.audit_repository.list_for_entity("lab_test", test_id)
        for reference_range in self.repository.list_reference_ranges(test_id):
            entries.extend(
                self.audit_repository.list_for_entity("reference_range", reference_range.id)
            )
        for option in self.repository.list_qualitative_options(test_id):
            entries.extend(
                self.audit_repository.list_for_entity("qualitative_result_option", option.id)
            )
        return sorted(entries, key=lambda entry: (entry.occurred_at, entry.id), reverse=True)

    def create_reference_range(
        self,
        test_id: int,
        data: ReferenceRangeCreate,
        *,
        actor_reference: str,
    ) -> ReferenceRange:
        test = self.get_test(test_id)
        if test.result_type != ResultType.NUMERIC:
            raise InvalidCatalogOperationError(
                "reference ranges are allowed only for numeric tests"
            )
        values = data.model_dump(exclude={"reason"})
        reference_range = ReferenceRange(test_id=test.id, **values)
        self._finish_new_mutation(
            "REFERENCE_RANGE_CREATED",
            "reference_range",
            reference_range,
            {*values, "test_id", "is_active"},
            data.reason,
            actor_reference,
        )
        return reference_range

    def update_reference_range(
        self,
        test_id: int,
        range_id: int,
        data: ReferenceRangeUpdate,
        *,
        actor_reference: str,
    ) -> ReferenceRange:
        test = self.get_test(test_id)
        reference_range = self.repository.get_reference_range(range_id)
        if reference_range is None or reference_range.test_id != test.id:
            raise CatalogNotFoundError("reference range not found")
        if test.result_type != ResultType.NUMERIC:
            raise InvalidCatalogOperationError(
                "reference ranges are allowed only for numeric tests"
            )
        changes = data.model_dump(exclude_unset=True, exclude={"reason"})
        merged = {
            field: changes.get(field, getattr(reference_range, field))
            for field in (
                "minimum_age",
                "maximum_age",
                "lower_value",
                "upper_value",
                "lower_critical",
                "upper_critical",
            )
        }
        self._validate_reference_bounds(**merged)
        return self._update_child(
            reference_range,
            changes,
            "REFERENCE_RANGE_UPDATED",
            "reference_range",
            data.reason,
            actor_reference,
        )

    def set_reference_range_activation(
        self,
        test_id: int,
        range_id: int,
        data: ActivationRequest,
        *,
        actor_reference: str,
    ) -> ReferenceRange:
        test = self.get_test(test_id)
        reference_range = self.repository.get_reference_range(range_id)
        if reference_range is None or reference_range.test_id != test.id:
            raise CatalogNotFoundError("reference range not found")
        if data.is_active and test.result_type != ResultType.NUMERIC:
            raise InvalidCatalogOperationError(
                "reference ranges are allowed only for numeric tests"
            )
        return self._set_child_activation(
            reference_range,
            data,
            "REFERENCE_RANGE_ACTIVATED",
            "REFERENCE_RANGE_DEACTIVATED",
            "reference_range",
            actor_reference,
        )

    def create_qualitative_option(
        self,
        test_id: int,
        data: QualitativeOptionCreate,
        *,
        actor_reference: str,
    ) -> QualitativeResultOption:
        test = self.get_test(test_id)
        if test.result_type not in {ResultType.QUALITATIVE, ResultType.CATEGORICAL}:
            raise InvalidCatalogOperationError(
                "qualitative options are allowed only for qualitative tests"
            )
        if self.repository.qualitative_option_code_exists(test.id, data.code):
            raise DuplicateCatalogCodeError("qualitative option code already exists")
        values = data.model_dump(exclude={"reason"})
        option = QualitativeResultOption(test_id=test.id, **values)
        try:
            self.repository.add(option)
            self._audit(
                "QUALITATIVE_OPTION_CREATED",
                "qualitative_result_option",
                option,
                {*values, "test_id", "is_active"},
                data.reason,
                actor_reference,
            )
            self.session.commit()
            self.session.refresh(option)
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateCatalogCodeError("qualitative option code already exists") from exc
        return option

    def update_qualitative_option(
        self,
        test_id: int,
        option_id: int,
        data: QualitativeOptionUpdate,
        *,
        actor_reference: str,
    ) -> QualitativeResultOption:
        test = self.get_test(test_id)
        option = self.repository.get_qualitative_option(option_id)
        if option is None or option.test_id != test.id:
            raise CatalogNotFoundError("qualitative option not found")
        if test.result_type not in {ResultType.QUALITATIVE, ResultType.CATEGORICAL}:
            raise InvalidCatalogOperationError(
                "qualitative options are allowed only for qualitative tests"
            )
        changes = data.model_dump(exclude_unset=True, exclude={"reason"})
        if any(
            changes.get(field, getattr(option, field)) is None
            for field in ("label_th", "label_en", "sort_order")
        ):
            raise InvalidCatalogOperationError("option labels and sort order are required")
        return self._update_child(
            option,
            changes,
            "QUALITATIVE_OPTION_UPDATED",
            "qualitative_result_option",
            data.reason,
            actor_reference,
        )

    def set_qualitative_option_activation(
        self,
        test_id: int,
        option_id: int,
        data: ActivationRequest,
        *,
        actor_reference: str,
    ) -> QualitativeResultOption:
        test = self.get_test(test_id)
        option = self.repository.get_qualitative_option(option_id)
        if option is None or option.test_id != test.id:
            raise CatalogNotFoundError("qualitative option not found")
        if data.is_active and test.result_type not in {
            ResultType.QUALITATIVE,
            ResultType.CATEGORICAL,
        }:
            raise InvalidCatalogOperationError(
                "qualitative options are allowed only for qualitative tests"
            )
        return self._set_child_activation(
            option,
            data,
            "QUALITATIVE_OPTION_ACTIVATED",
            "QUALITATIVE_OPTION_DEACTIVATED",
            "qualitative_result_option",
            actor_reference,
        )

    def _create_configuration(
        self,
        model: type[TestCategory] | type[SpecimenType],
        data: ConfigurationCreate,
        *,
        actor_reference: str,
    ) -> TestCategory | SpecimenType:
        if self.repository.configuration_code_exists(model, data.code):
            raise DuplicateCatalogCodeError("catalog code already exists")
        values = data.model_dump(exclude={"reason"})
        entity = model(**values)
        entity_type = "test_category" if model is TestCategory else "specimen_type"
        event = "TEST_CATEGORY_CREATED" if model is TestCategory else "SPECIMEN_TYPE_CREATED"
        try:
            self.repository.add(entity)
            self._audit(
                event,
                entity_type,
                entity,
                {*values, "is_active"},
                data.reason,
                actor_reference,
            )
            self.session.commit()
            self.session.refresh(entity)
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateCatalogCodeError("catalog code already exists") from exc
        return entity

    def _update_configuration(
        self,
        entity: TestCategory | SpecimenType,
        data: ConfigurationUpdate,
        *,
        actor_reference: str,
    ) -> TestCategory | SpecimenType:
        changes = data.model_dump(exclude_unset=True, exclude={"reason"})
        if any(
            changes.get(field, getattr(entity, field)) is None
            for field in ("name_th", "name_en", "is_active")
        ):
            raise InvalidCatalogOperationError("configuration fields must not be null")
        actual_changes = {
            field: value for field, value in changes.items() if getattr(entity, field) != value
        }
        if not actual_changes:
            raise InvalidCatalogOperationError("no configuration data changed")
        for field, value in actual_changes.items():
            setattr(entity, field, value)
        is_category = isinstance(entity, TestCategory)
        event = "TEST_CATEGORY_UPDATED" if is_category else "SPECIMEN_TYPE_UPDATED"
        entity_type = "test_category" if is_category else "specimen_type"
        self._finish_mutation(
            event,
            entity_type,
            entity,
            set(actual_changes),
            data.reason,
            actor_reference,
        )
        return entity

    def _require_active_configuration(
        self, category_id: int, department_id: int, specimen_type_id: int
    ) -> None:
        category = self.repository.get_category(category_id)
        if category is None or not category.is_active:
            raise CatalogNotFoundError("active test category not found")
        department = self.repository.get_department(department_id)
        if department is None or not department.is_active:
            raise InvalidCatalogOperationError("active laboratory department not found")
        specimen_type = self.repository.get_specimen_type(specimen_type_id)
        if specimen_type is None or not specimen_type.is_active:
            raise CatalogNotFoundError("active specimen type not found")

    def _require_editable_configuration(
        self, test: LabTest, category_id: int, department_id: int, specimen_type_id: int
    ) -> None:
        category = self.repository.get_category(category_id)
        if category is None or (category_id != test.category_id and not category.is_active):
            raise CatalogNotFoundError("active test category not found")
        department = self.repository.get_department(department_id)
        if department is None or (
            department_id != test.department_id and not department.is_active
        ):
            raise InvalidCatalogOperationError("active laboratory department not found")
        specimen_type = self.repository.get_specimen_type(specimen_type_id)
        if specimen_type is None or (
            specimen_type_id != test.specimen_type_id and not specimen_type.is_active
        ):
            raise CatalogNotFoundError("active specimen type not found")

    @staticmethod
    def _validate_test_configuration(result_type: object, result_unit: object) -> None:
        if result_type == ResultType.NUMERIC and not result_unit:
            raise InvalidCatalogOperationError("result unit is required for numeric tests")
        if result_type in {ResultType.QUALITATIVE, ResultType.CATEGORICAL} and result_unit:
            raise InvalidCatalogOperationError(
                "qualitative tests must not define a numeric result unit"
            )
        if result_type not in (
            ResultType.CBC,
            ResultType.UA,
            ResultType.INFLUENZA_AB,
            ResultType.NUMERIC,
            ResultType.TEXT,
            ResultType.CATEGORICAL,
            ResultType.QUALITATIVE,
        ):
            raise InvalidCatalogOperationError("valid result type is required")

    @staticmethod
    def _validate_reference_bounds(
        *,
        minimum_age: object,
        maximum_age: object,
        lower_value: object,
        upper_value: object,
        lower_critical: object,
        upper_critical: object,
    ) -> None:
        if not isinstance(minimum_age, int) or not isinstance(maximum_age, int):
            raise InvalidCatalogOperationError("minimum and maximum ages are required")
        if not isinstance(lower_value, Decimal) or not isinstance(upper_value, Decimal):
            raise InvalidCatalogOperationError("lower and upper reference values are required")
        if minimum_age > maximum_age:
            raise InvalidCatalogOperationError("minimum age must not exceed maximum age")
        if lower_value > upper_value:
            raise InvalidCatalogOperationError(
                "lower reference value must not exceed upper reference value"
            )
        if (
            isinstance(lower_critical, Decimal)
            and isinstance(upper_critical, Decimal)
            and lower_critical > upper_critical
        ):
            raise InvalidCatalogOperationError(
                "lower critical value must not exceed upper critical value"
            )

    def _update_child(
        self,
        entity: CatalogChild,
        changes: dict[str, object],
        event: str,
        entity_type: str,
        reason: str,
        actor_reference: str,
    ) -> CatalogChild:
        actual_changes = {
            field: value for field, value in changes.items() if getattr(entity, field) != value
        }
        if not actual_changes:
            raise InvalidCatalogOperationError("no catalog data changed")
        for field, value in actual_changes.items():
            setattr(entity, field, value)
        self._finish_mutation(
            event, entity_type, entity, set(actual_changes), reason, actor_reference
        )
        return entity

    def _set_child_activation(
        self,
        entity: CatalogChild,
        data: ActivationRequest,
        activated_event: str,
        deactivated_event: str,
        entity_type: str,
        actor_reference: str,
    ) -> CatalogChild:
        if entity.is_active == data.is_active:
            raise InvalidCatalogOperationError("activation state did not change")
        entity.is_active = data.is_active
        event = activated_event if data.is_active else deactivated_event
        self._finish_mutation(
            event, entity_type, entity, {"is_active"}, data.reason, actor_reference
        )
        return entity

    def _finish_new_mutation(
        self,
        event: str,
        entity_type: str,
        entity: CatalogEntity,
        changed_fields: set[str],
        reason: str,
        actor_reference: str,
    ) -> None:
        try:
            self.repository.add(entity)
            self._audit(
                event,
                entity_type,
                entity,
                changed_fields,
                reason,
                actor_reference,
            )
            self.session.commit()
            self.session.refresh(entity)
        except IntegrityError as exc:
            self.session.rollback()
            raise InvalidCatalogOperationError("catalog mutation violates constraints") from exc

    def _finish_mutation(
        self,
        event: str,
        entity_type: str,
        entity: CatalogEntity,
        changed_fields: set[str],
        reason: str,
        actor_reference: str,
    ) -> None:
        try:
            self.repository.flush()
            self._audit(
                event,
                entity_type,
                entity,
                changed_fields,
                reason,
                actor_reference,
            )
            self.session.commit()
            self.session.refresh(entity)
        except IntegrityError as exc:
            self.session.rollback()
            raise InvalidCatalogOperationError("catalog mutation violates constraints") from exc

    def _audit(
        self,
        event: str,
        entity_type: str,
        entity: CatalogEntity,
        changed_fields: set[str],
        reason: str,
        actor_reference: str,
    ) -> None:
        self.audit_repository.add(
            AuditLog(
                event_type=event,
                entity_type=entity_type,
                entity_id=entity.id,
                changed_fields=sorted(changed_fields),
                reason=reason,
                actor_reference=actor_reference,
            )
        )
