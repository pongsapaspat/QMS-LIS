from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import ResultType
from app.domain.exceptions import InvalidCatalogOperationError
from app.models.test_catalog import (
    LabTest,
    ReferenceRange,
    SpecimenType,
)
from app.models.test_catalog import TestCategory as CatalogCategory
from app.repositories.audit import AuditRepository
from app.repositories.test_catalog import TestCatalogRepository as CatalogRepository
from app.schemas.test_catalog import CatalogTestUpdate, ReferenceRangeUpdate
from app.services.test_catalog import TestCatalogService as CatalogService


def build_service() -> tuple[
    CatalogService,
    MagicMock,
    MagicMock,
    MagicMock,
    LabTest,
]:
    session = MagicMock(spec=Session)
    repository = MagicMock(spec=CatalogRepository)
    audit_repository = MagicMock(spec=AuditRepository)
    category = CatalogCategory(id=1, code="CHEM", name_th="Chem", name_en="Chem", is_active=True)
    specimen = SpecimenType(id=1, code="SERUM", name_th="Serum", name_en="Serum", is_active=True)
    test = LabTest(
        id=1,
        code="GLU",
        name_th="Glucose Thai",
        name_en="Glucose",
        category_id=1,
        specimen_type_id=1,
        current_price=Decimal("100.00"),
        result_type=ResultType.NUMERIC,
        result_unit="mg/dL",
        tat_minutes=60,
    )
    repository.get_test.return_value = test
    repository.get_category.return_value = category
    repository.get_specimen_type.return_value = specimen
    return (
        CatalogService(session, repository, audit_repository),
        session,
        repository,
        audit_repository,
        test,
    )


@pytest.mark.unit
def test_partial_reference_range_update_validates_merged_state() -> None:
    service, session, repository, _, test = build_service()
    reference_range = ReferenceRange(
        id=3,
        test_id=test.id,
        sex="ALL",
        minimum_age=18,
        maximum_age=65,
        age_unit="YEARS",
        lower_value=Decimal("70"),
        upper_value=Decimal("110"),
    )
    repository.get_reference_range.return_value = reference_range

    with pytest.raises(InvalidCatalogOperationError, match="lower reference"):
        service.update_reference_range(
            test.id,
            reference_range.id,
            ReferenceRangeUpdate(lower_value=Decimal("120"), reason="invalid partial update"),
            actor_reference="admin-1",
        )

    session.commit.assert_not_called()


@pytest.mark.unit
def test_unchanged_price_does_not_add_price_history() -> None:
    service, session, repository, audit_repository, test = build_service()

    updated = service.update_test(
        test.id,
        CatalogTestUpdate(
            name_en="Blood Glucose",
            current_price=Decimal("100.00"),
            reason="clarify display name",
        ),
        actor_reference="admin-1",
    )

    assert updated.name_en == "Blood Glucose"
    repository.add.assert_not_called()
    audit = audit_repository.add.call_args.args[0]
    assert audit.changed_fields == ["name_en"]
    assert "Blood Glucose" not in str(audit.changed_fields)
    session.commit.assert_called_once_with()


@pytest.mark.unit
def test_changed_price_adds_history_and_audits_only_field_name() -> None:
    service, session, repository, audit_repository, test = build_service()

    service.update_test(
        test.id,
        CatalogTestUpdate(current_price=Decimal("125.50"), reason="annual price review"),
        actor_reference="admin-1",
    )

    history = repository.add.call_args.args[0]
    assert history.old_price == Decimal("100.00")
    assert history.new_price == Decimal("125.50")
    assert history.actor_reference == "admin-1"
    audit = audit_repository.add.call_args.args[0]
    assert audit.event_type == "LAB_TEST_UPDATED"
    assert audit.changed_fields == ["current_price"]
    assert "125.50" not in str(audit.changed_fields)
    session.commit.assert_called_once_with()
