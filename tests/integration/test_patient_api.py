import pytest
from fastapi.testclient import TestClient


def patient_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "first_name": "Suda",
        "last_name": "Dee",
        "date_of_birth": "1990-06-15",
        "passport_number": "aa123456",
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
def test_patient_crud_search_and_soft_deactivation(client: TestClient) -> None:
    create_response = client.post("/api/v1/patients", json=patient_payload())

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["hn"] == "HN00100000001"
    assert created["branch_id"] == 1
    assert created["passport_number"] == "AA123456"
    assert created["is_active"] is True
    assert created["created_at"]
    assert created["updated_at"]
    assert created["created_at"].endswith("Z") or created["created_at"].endswith("+00:00")

    patient_id = created["id"]
    retrieve_response = client.get(f"/api/v1/patients/{patient_id}")
    assert retrieve_response.status_code == 200
    assert retrieve_response.json()["hn"] == created["hn"]

    search_response = client.get("/api/v1/patients", params={"search": "sud"})
    assert search_response.status_code == 200
    assert [patient["id"] for patient in search_response.json()] == [patient_id]

    update_response = client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"first_name": "Sudaporn", "is_active": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["first_name"] == "Sudaporn"
    assert update_response.json()["is_active"] is False

    assert client.get("/api/v1/patients").json() == []
    inactive_response = client.get(
        "/api/v1/patients", params={"include_inactive": "true"}
    )
    assert [patient["id"] for patient in inactive_response.json()] == [patient_id]


@pytest.mark.integration
def test_hn_is_unique_and_uses_branch_sequence(client: TestClient) -> None:
    first = client.post("/api/v1/patients", json=patient_payload()).json()
    second = client.post(
        "/api/v1/patients",
        json=patient_payload(first_name="Mana", passport_number="BB987654"),
    ).json()

    assert first["hn"] == "HN00100000001"
    assert second["hn"] == "HN00100000002"


@pytest.mark.integration
def test_invalid_thai_national_id_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/patients",
        json=patient_payload(passport_number=None, thai_national_id="1101700207031"),
    )

    assert response.status_code == 422
    assert "invalid Thai National ID" in response.text


@pytest.mark.integration
def test_duplicate_identifier_returns_conflict(client: TestClient) -> None:
    first_response = client.post("/api/v1/patients", json=patient_payload())
    duplicate_response = client.post(
        "/api/v1/patients",
        json=patient_payload(first_name="Different"),
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409


@pytest.mark.integration
def test_missing_patient_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/patients/999")

    assert response.status_code == 404
