from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.exceptions import PossibleDuplicatePatientError
from app.models.patient import Patient
from app.repositories.audit import AuditRepository
from app.repositories.patient import PatientRepository
from app.schemas.patient import PatientCreate, PatientUpdate, is_valid_thai_national_id
from app.services.patient import PatientService

SYNTHETIC_VALID_NATIONAL_ID = "0123456789016"


@pytest.mark.unit
def test_thai_national_id_checksum() -> None:
    assert is_valid_thai_national_id(SYNTHETIC_VALID_NATIONAL_ID)
    assert not is_valid_thai_national_id("0123456789017")
    assert not is_valid_thai_national_id("0000000000000")


@pytest.mark.unit
@pytest.mark.parametrize(
    "formatted_value",
    [
        SYNTHETIC_VALID_NATIONAL_ID,
        "0-1234-56789-01-6",
        "0 1234 56789 01 6",
    ],
)
def test_thai_national_id_formats_are_normalized(formatted_value: str) -> None:
    patient = PatientCreate(
        first_name_en="Test",
        last_name_en="Patient",
        national_id=formatted_value,
    )

    assert patient.national_id == SYNTHETIC_VALID_NATIONAL_ID


@pytest.mark.unit
@pytest.mark.parametrize(
    "marker",
    ["", "   ", "-", "–", "—", "N/A", "n/a", "NA", "ไม่มี", "ไม่ระบุ"],
)
@pytest.mark.parametrize(
    "field",
    [
        "national_id",
        "passport_number",
        "email",
        "emergency_contact_name",
        "emergency_contact_relationship",
        "emergency_contact_phone",
    ],
)
def test_optional_markers_are_normalized_to_none(field: str, marker: str) -> None:
    patient = PatientCreate(
        first_name_en="Test",
        last_name_en="Patient",
        **{field: marker},
    )

    assert getattr(patient, field) is None


@pytest.mark.unit
def test_optional_real_values_are_normalized_before_validation() -> None:
    patient = PatientCreate(
        first_name_en="Test",
        last_name_en="Patient",
        passport_number="  aa123456  ",
        email="  test.patient@example.com  ",
        emergency_contact_name="  Example   Contact  ",
        emergency_contact_phone=" 081-234-5678 ",
    )

    assert patient.passport_number == "AA123456"
    assert patient.email == "test.patient@example.com"
    assert patient.emergency_contact_name == "Example Contact"
    assert patient.emergency_contact_phone == "0812345678"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("national_id", "0123456789017"),
        ("passport_number", "A!"),
        ("email", "not-an-email"),
        ("emergency_contact_phone", "12x"),
    ],
)
def test_actual_optional_values_keep_strict_validation(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        PatientCreate(
            first_name_en="Test",
            last_name_en="Patient",
            **{field: value},
        )


@pytest.mark.unit
def test_update_normalizes_optional_markers_and_formatted_national_id() -> None:
    update = PatientUpdate(
        national_id="0 1234 56789 01 6",
        passport_number="-",
        email="ไม่ระบุ",
        emergency_contact_name="N/A",
        emergency_contact_relationship="—",
        emergency_contact_phone="ไม่มี",
        change_reason="verified correction",
    )

    assert update.national_id == SYNTHETIC_VALID_NATIONAL_ID
    assert update.passport_number is None
    assert update.email is None
    assert update.emergency_contact_name is None
    assert update.emergency_contact_relationship is None
    assert update.emergency_contact_phone is None


@pytest.mark.unit
def test_hn_allocation_is_sequential_and_rolls_back_with_transaction(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        repository = PatientRepository(session)
        assert repository.allocate_hn() == "HN000001"
        assert repository.allocate_hn() == "HN000002"
        session.rollback()

    with db_session_factory() as session:
        repository = PatientRepository(session)
        assert repository.allocate_hn() == "HN000001"


@pytest.mark.unit
def test_service_creates_incomplete_identity_patient_and_audit() -> None:
    session = MagicMock(spec=Session)
    repository = MagicMock(spec=PatientRepository)
    audit_repository = MagicMock(spec=AuditRepository)
    repository.branch_is_active.return_value = True
    repository.find_identifier_match.return_value = None
    repository.find_by_date_of_birth.return_value = []
    repository.allocate_hn.return_value = "HN000001"
    repository.add.side_effect = lambda patient: patient
    service = PatientService(session, repository, audit_repository)

    patient = service.create(
        PatientCreate(first_name_en="Suda", last_name_en="Dee"),
        actor_reference="admin-1",
    )

    assert patient.hn == "HN000001"
    assert patient.identity_document_missing is True
    session.commit.assert_called_once_with()
    audit_entry = audit_repository.add.call_args.args[0]
    assert audit_entry.event_type == "PATIENT_CREATED"
    assert "first_name_en" in audit_entry.changed_fields
    assert "Suda" not in str(audit_entry.changed_fields)


@pytest.mark.unit
def test_similar_name_and_birth_date_requires_confirmation() -> None:
    session = MagicMock(spec=Session)
    repository = MagicMock(spec=PatientRepository)
    repository.branch_is_active.return_value = True
    repository.find_identifier_match.return_value = None
    repository.find_by_date_of_birth.return_value = [
        Patient(
            id=9,
            hn="HN000009",
            branch_id=1,
            first_name_en="Suda",
            last_name_en="Dee",
        )
    ]
    service = PatientService(session, repository, MagicMock(spec=AuditRepository))

    with pytest.raises(PossibleDuplicatePatientError):
        service.create(
            PatientCreate(
                first_name_en="Suda",
                last_name_en="Dee",
                date_of_birth="1990-06-15",
            ),
            actor_reference="admin-1",
        )


@pytest.mark.unit
def test_update_schema_requires_reason_and_forbids_hn() -> None:
    with pytest.raises(ValueError):
        PatientUpdate(first_name_en="New")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        PatientUpdate(first_name_en="New", change_reason="correction", hn="HN999999")
