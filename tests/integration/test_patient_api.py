import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit import AuditLog
from app.models.patient import Patient

ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "admin-test"}
SYNTHETIC_VALID_NATIONAL_ID = "0123456789016"


def patient_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Ms",
        "first_name_th": "สุดา",
        "last_name_th": "ดี",
        "first_name_en": "Suda",
        "last_name_en": "Dee",
        "date_of_birth": "1990-06-15",
        "sex": "female",
        "passport_number": "aa123456",
        "phone_number": "0812345678",
        "address": "Bangkok",
        "email": "suda@example.com",
        "blood_group": "A+",
        "emergency_contact_name": "Somchai Dee",
        "emergency_contact_relationship": "Brother",
        "emergency_contact_phone": "0899999999",
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
def test_create_retrieve_search_and_update_patient(client: TestClient) -> None:
    create_response = client.post(
        "/api/v1/patients", json=patient_payload(), headers=ADMIN_HEADERS
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["hn"] == "HN000001"
    assert created["branch_id"] == 1
    assert created["passport_number"] == "AA123456"
    assert created["identity_document_missing"] is False
    assert created["created_at"].endswith("Z") or created["created_at"].endswith("+00:00")

    patient_id = created["id"]
    retrieved = client.get(f"/api/v1/patients/{patient_id}", headers=ADMIN_HEADERS)
    assert retrieved.status_code == 200
    assert retrieved.json()["address"] == "Bangkok"

    listed = client.get(
        "/api/v1/patients", params={"search": "Suda"}, headers=ADMIN_HEADERS
    )
    assert listed.status_code == 200
    page = listed.json()
    assert page["total"] == 1
    assert page["items"][0]["hn"] == "HN000001"
    assert "national_id" not in page["items"][0]
    assert "passport_number" not in page["items"][0]
    assert "phone_number" not in page["items"][0]

    updated = client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"phone_number": "0822222222", "change_reason": "patient correction"},
        headers=ADMIN_HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["phone_number"] == "0822222222"
    assert updated.json()["hn"] == "HN000001"


@pytest.mark.integration
def test_search_supports_national_id_without_exposing_it_in_list(client: TestClient) -> None:
    created = client.post(
        "/api/v1/patients",
        json=patient_payload(
            passport_number=None,
            national_id="0-1234-56789-01-6",
        ),
        headers=ADMIN_HEADERS,
    )
    assert created.status_code == 201

    response = client.get(
        "/api/v1/patients",
        params={"search": SYNTHETIC_VALID_NATIONAL_ID},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert "national_id" not in response.json()["items"][0]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("field", "value"),
    [("national_id", SYNTHETIC_VALID_NATIONAL_ID), ("passport_number", "AA123456")],
)
def test_duplicate_identity_is_rejected(
    client: TestClient, field: str, value: str
) -> None:
    first_payload = patient_payload(passport_number=None)
    first_payload[field] = value
    assert client.post(
        "/api/v1/patients", json=first_payload, headers=ADMIN_HEADERS
    ).status_code == 201

    duplicate_payload = patient_payload(
        first_name_en="Mana",
        last_name_en="New",
        date_of_birth="1988-01-01",
        passport_number=None,
    )
    duplicate_payload[field] = value
    response = client.post(
        "/api/v1/patients", json=duplicate_payload, headers=ADMIN_HEADERS
    )

    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


@pytest.mark.integration
def test_duplicate_identity_is_rejected_during_update(client: TestClient) -> None:
    first = client.post(
        "/api/v1/patients", json=patient_payload(), headers=ADMIN_HEADERS
    ).json()
    second = client.post(
        "/api/v1/patients",
        json=patient_payload(
            first_name_en="Mana",
            last_name_en="New",
            date_of_birth="1988-01-01",
            passport_number="BB987654",
        ),
        headers=ADMIN_HEADERS,
    ).json()

    response = client.patch(
        f"/api/v1/patients/{second['id']}",
        json={"passport_number": first["passport_number"], "change_reason": "document update"},
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 409


@pytest.mark.integration
def test_duplicate_check_returns_minimal_candidate(client: TestClient) -> None:
    client.post("/api/v1/patients", json=patient_payload(), headers=ADMIN_HEADERS)

    response = client.get(
        "/api/v1/patients/duplicate-check",
        params={
            "first_name_en": "Suda",
            "last_name_en": "Dee",
            "date_of_birth": "1990-06-15",
        },
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert set(candidate) == {"patient_id", "hn", "display_name", "match_reason"}


@pytest.mark.integration
def test_invalid_national_id_error_does_not_echo_value(client: TestClient) -> None:
    invalid_id = "0123456789017"
    response = client.post(
        "/api/v1/patients",
        json=patient_payload(passport_number=None, national_id=invalid_id),
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 422
    assert invalid_id not in response.text


@pytest.mark.integration
def test_missing_identity_is_derived(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patients",
        json=patient_payload(national_id=None, passport_number=None),
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 201
    assert response.json()["identity_document_missing"] is True


@pytest.mark.integration
def test_optional_placeholder_values_are_persisted_as_null(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/api/v1/patients",
        json=patient_payload(
            national_id="-",
            passport_number="N/A",
            email="ไม่ระบุ",
            emergency_contact_name="—",
            emergency_contact_relationship="ไม่มี",
            emergency_contact_phone="n/a",
        ),
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 201
    created = response.json()
    optional_fields = (
        "national_id",
        "passport_number",
        "email",
        "emergency_contact_name",
        "emergency_contact_relationship",
        "emergency_contact_phone",
    )
    assert all(created[field] is None for field in optional_fields)
    assert created["identity_document_missing"] is True

    with db_session_factory() as session:
        stored = session.get(Patient, created["id"])
        assert stored is not None
        assert all(getattr(stored, field) is None for field in optional_fields)


@pytest.mark.integration
def test_registration_form_accepts_optional_placeholders(client: TestClient) -> None:
    response = client.post(
        "/patients/new",
        data={
            "first_name_en": "Test",
            "last_name_en": "Patient",
            "national_id": "-",
            "passport_number": "–",
            "email": "N/A",
            "emergency_contact_name": "ไม่มี",
            "emergency_contact_relationship": "ไม่ระบุ",
            "emergency_contact_phone": "—",
        },
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )

    assert response.status_code == 303


@pytest.mark.integration
def test_update_converts_optional_placeholders_to_null(client: TestClient) -> None:
    patient = client.post(
        "/api/v1/patients",
        json=patient_payload(),
        headers=ADMIN_HEADERS,
    ).json()

    response = client.patch(
        f"/api/v1/patients/{patient['id']}",
        json={
            "passport_number": "-",
            "email": "n/a",
            "emergency_contact_name": "ไม่มี",
            "emergency_contact_relationship": "ไม่ระบุ",
            "emergency_contact_phone": "—",
            "change_reason": "information not supplied",
        },
        headers=ADMIN_HEADERS,
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["passport_number"] is None
    assert updated["email"] is None
    assert updated["emergency_contact_name"] is None
    assert updated["emergency_contact_relationship"] is None
    assert updated["emergency_contact_phone"] is None
    assert updated["identity_document_missing"] is True


@pytest.mark.integration
def test_hn_is_immutable_and_update_requires_reason(client: TestClient) -> None:
    patient = client.post(
        "/api/v1/patients", json=patient_payload(), headers=ADMIN_HEADERS
    ).json()

    no_reason = client.patch(
        f"/api/v1/patients/{patient['id']}",
        json={"phone_number": "0800000000"},
        headers=ADMIN_HEADERS,
    )
    hn_change = client.patch(
        f"/api/v1/patients/{patient['id']}",
        json={"hn": "HN999999", "change_reason": "attempted change"},
        headers=ADMIN_HEADERS,
    )

    assert no_reason.status_code == 422
    assert hn_change.status_code == 422
    unchanged = client.get(
        f"/api/v1/patients/{patient['id']}", headers=ADMIN_HEADERS
    ).json()
    assert unchanged["hn"] == "HN000001"


@pytest.mark.integration
def test_possible_duplicate_requires_explicit_confirmation(client: TestClient) -> None:
    assert client.post(
        "/api/v1/patients", json=patient_payload(), headers=ADMIN_HEADERS
    ).status_code == 201

    possible_duplicate = patient_payload(passport_number="BB987654")
    blocked = client.post(
        "/api/v1/patients", json=possible_duplicate, headers=ADMIN_HEADERS
    )
    assert blocked.status_code == 409
    assert blocked.json()["candidates"][0]["hn"] == "HN000001"

    possible_duplicate["confirm_possible_duplicate"] = True
    confirmed = client.post(
        "/api/v1/patients", json=possible_duplicate, headers=ADMIN_HEADERS
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["hn"] == "HN000002"


@pytest.mark.integration
def test_audit_log_contains_field_names_not_pii_values(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    created = client.post(
        "/api/v1/patients", json=patient_payload(), headers=ADMIN_HEADERS
    ).json()
    client.patch(
        f"/api/v1/patients/{created['id']}",
        json={"phone_number": "0800000000", "change_reason": "verified correction"},
        headers=ADMIN_HEADERS,
    )

    with db_session_factory() as session:
        entries = list(session.scalars(select(AuditLog).order_by(AuditLog.id)))

    assert [entry.event_type for entry in entries] == ["PATIENT_CREATED", "PATIENT_UPDATED"]
    assert entries[1].changed_fields == ["phone_number"]
    audit_text = " ".join(str(entry.changed_fields) for entry in entries)
    assert "Suda" not in audit_text
    assert "AA123456" not in audit_text
    assert "0800000000" not in audit_text
    assert entries[1].actor_reference == "admin-test"


@pytest.mark.integration
def test_patient_mutations_require_admin(client: TestClient) -> None:
    non_admin_headers = {"X-Role": "LAB_TECH", "X-Actor": "tech-1"}
    response = client.post(
        "/api/v1/patients", json=patient_payload(), headers=non_admin_headers
    )

    assert response.status_code == 403


@pytest.mark.integration
def test_ui_patient_list_and_registration_form(client: TestClient) -> None:
    list_response = client.get("/patients", headers=ADMIN_HEADERS)
    form_response = client.get("/patients/new", headers=ADMIN_HEADERS)

    assert list_response.status_code == 200
    assert "Patients" in list_response.text
    assert "ผู้ป่วย" in list_response.text
    assert form_response.status_code == 200
    assert "Thai National ID" in form_response.text
    assert "ลงทะเบียนผู้ป่วย" in form_response.text
