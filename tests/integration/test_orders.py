import pytest
from fastapi.testclient import TestClient

ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "order-admin"}


def create_order_fixtures(client: TestClient) -> tuple[int, int, int]:
    category = client.post(
        "/api/v1/test-categories",
        json={"code": "CHEM", "name_th": "เคมี", "name_en": "Chemistry"},
        headers=ADMIN_HEADERS,
    )
    specimen = client.post(
        "/api/v1/specimen-types",
        json={"code": "SERUM", "name_th": "ซีรัม", "name_en": "Serum"},
        headers=ADMIN_HEADERS,
    )
    assert category.status_code == 201
    assert specimen.status_code == 201
    test = client.post(
        "/api/v1/tests",
        json={
            "code": "GLU",
            "name_th": "กลูโคส",
            "name_en": "Glucose",
            "category_id": category.json()["id"],
            "specimen_type_id": specimen.json()["id"],
            "current_price": "125.00",
            "result_type": "NUMERIC",
            "result_unit": "mg/dL",
            "tat_minutes": 30,
        },
        headers=ADMIN_HEADERS,
    )
    patient = client.post(
        "/api/v1/patients",
        json={
            "first_name_en": "Ada",
            "last_name_en": "Lovelace",
            "passport_number": "A1234567",
        },
        headers=ADMIN_HEADERS,
    )
    assert test.status_code == 201
    assert patient.status_code == 201
    return patient.json()["id"], test.json()["id"], category.json()["id"]


@pytest.mark.integration
def test_create_and_view_order_preserves_test_snapshots(client: TestClient) -> None:
    patient_id, test_id, _ = create_order_fixtures(client)

    created = client.post(
        "/api/v1/orders",
        json={"patient_id": patient_id, "test_ids": [test_id], "priority": "URGENT"},
        headers=ADMIN_HEADERS,
    )
    assert created.status_code == 201
    order = created.json()
    assert order["order_number"].startswith("ORD")
    assert order["priority"] == "URGENT"
    assert order["clinical_note"] is None
    assert order["total_price"] == "125.00"
    assert order["items"][0]["test_code"] == "GLU"
    assert order["items"][0]["test_name_th"] == "กลูโคส"
    assert order["items"][0]["test_name_en"] == "Glucose"
    assert order["items"][0]["result_type"] == "NUMERIC"
    assert order["items"][0]["result_unit"] == "mg/dL"
    assert order["items"][0]["price"] == "125.00"

    changed = client.patch(
        f"/api/v1/tests/{test_id}",
        json={"name_en": "Renamed Glucose", "current_price": "150.00"},
        headers=ADMIN_HEADERS,
    )
    assert changed.status_code == 200

    detail = client.get(f"/api/v1/orders/{order['id']}", headers=ADMIN_HEADERS)
    assert detail.status_code == 200
    assert detail.json()["items"][0]["test_name_en"] == "Glucose"
    assert detail.json()["items"][0]["price"] == "125.00"
    assert detail.json()["total_price"] == "125.00"


@pytest.mark.integration
def test_order_requires_active_patient_tests_and_unique_items(client: TestClient) -> None:
    patient_id, test_id, _ = create_order_fixtures(client)

    duplicate_items = client.post(
        "/api/v1/orders",
        json={
            "patient_id": patient_id,
            "test_ids": [test_id, test_id],
            "client_price": "0.01",
        },
        headers=ADMIN_HEADERS,
    )
    assert duplicate_items.status_code == 422

    inactive_patient = client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"is_active": False, "change_reason": "record closed"},
        headers=ADMIN_HEADERS,
    )
    assert inactive_patient.status_code == 200
    rejected_patient = client.post(
        "/api/v1/orders",
        json={"patient_id": patient_id, "test_ids": [test_id]},
        headers=ADMIN_HEADERS,
    )
    assert rejected_patient.status_code == 404
    reactivated_patient = client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"is_active": True, "change_reason": "record reopened"},
        headers=ADMIN_HEADERS,
    )
    assert reactivated_patient.status_code == 200

    inactive = client.patch(
        f"/api/v1/tests/{test_id}/activation",
        json={"is_active": False},
        headers=ADMIN_HEADERS,
    )
    assert inactive.status_code == 200
    rejected = client.post(
        "/api/v1/orders",
        json={"patient_id": patient_id, "test_ids": [test_id]},
        headers=ADMIN_HEADERS,
    )
    assert rejected.status_code == 404


@pytest.mark.integration
def test_web_order_form_creates_and_displays_order(client: TestClient) -> None:
    patient_id, test_id, _ = create_order_fixtures(client)

    form = client.get("/orders/new", headers=ADMIN_HEADERS)
    assert form.status_code == 200
    assert "Active Lab Tests" in form.text
    created = client.post(
        "/orders/new",
        data={
            "patient_id": str(patient_id),
            "test_ids": str(test_id),
            "priority": "ROUTINE",
            "clinical_note": "Annual review",
        },
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert created.status_code == 303
    detail = client.get(created.headers["location"], headers=ADMIN_HEADERS)
    assert detail.status_code == 200
    assert "Annual review" in detail.text
    assert "GLU" in detail.text
