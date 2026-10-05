from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.domain.exceptions import BranchNotFoundError
from app.repositories.patient import PatientRepository
from app.schemas.patient import PatientCreate, is_valid_thai_national_id
from app.services.patient import PatientService


@pytest.mark.unit
def test_thai_national_id_checksum() -> None:
    assert is_valid_thai_national_id("1101700207030")
    assert not is_valid_thai_national_id("1101700207031")
    assert not is_valid_thai_national_id("0000000000000")


@pytest.mark.unit
def test_service_creates_patient_with_repository_allocated_hn() -> None:
    session = MagicMock(spec=Session)
    repository = MagicMock(spec=PatientRepository)
    repository.identifiers_exist.return_value = False
    repository.allocate_hn.return_value = "HN00100000001"
    repository.add.side_effect = lambda patient: patient
    service = PatientService(session, repository)

    patient = service.create(PatientCreate(first_name="Suda", last_name="Dee"))

    assert patient.hn == "HN00100000001"
    assert patient.branch_id == 1
    repository.add.assert_called_once_with(patient)
    session.commit.assert_called_once_with()


@pytest.mark.unit
def test_service_rolls_back_when_branch_does_not_exist() -> None:
    session = MagicMock(spec=Session)
    repository = MagicMock(spec=PatientRepository)
    repository.identifiers_exist.return_value = False
    repository.allocate_hn.return_value = None
    service = PatientService(session, repository)

    with pytest.raises(BranchNotFoundError):
        service.create(PatientCreate(first_name="Suda", last_name="Dee", branch_id=99))

    session.rollback.assert_called_once_with()
    repository.add.assert_not_called()
