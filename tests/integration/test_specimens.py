import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit import AuditLog

HEADERS = {"X-Role": "LAB_TECH", "X-Actor": "collector-1"}
ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "catalog-admin"}


def create_collection_order(client: TestClient) -> tuple[int, int, int, int]:
    category = client.post(
        "/api/v1/test-categories",
        json={"code": "CHEM", "name_th": "Chem", "name_en": "Chemistry"},
        headers=ADMIN_HEADERS,
    )
    serum = client.post(
        "/api/v1/specimen-types",
        json={"code": "SERUM", "name_th": "Serum Thai", "name_en": "Serum"},
        headers=ADMIN_HEADERS,
    )
    urine = client.post(
        "/api/v1/specimen-types",
        json={"code": "URINE", "name_th": "Urine Thai", "name_en": "Urine"},
        headers=ADMIN_HEADERS,
    )
    plasma = client.post(
        "/api/v1/specimen-types",
        json={"code": "PLASMA", "name_th": "Plasma Thai", "name_en": "Plasma"},
        headers=ADMIN_HEADERS,
    )
    assert category.status_code == 201
    assert serum.status_code == 201
    assert urine.status_code == 201
    assert plasma.status_code == 201
    test_ids = []
    for code, name, specimen_id in (
        ("GLU", "Glucose", serum.json()["id"]),
        ("CREA", "Creatinine", serum.json()["id"]),
        ("UPRO", "Urine Protein", urine.json()["id"]),
    ):
        test = client.post(
            "/api/v1/tests",
            json={
                "code": code,
                "name_th": f"{name} Thai",
                "name_en": name,
                "category_id": category.json()["id"],
                "specimen_type_id": specimen_id,
                "current_price": "100.00",
                "result_type": "NUMERIC",
                "result_unit": "mg/dL",
                "tat_minutes": 30,
            },
            headers=ADMIN_HEADERS,
        )
        assert test.status_code == 201
        test_ids.append(test.json()["id"])
    patient = client.post(
        "/api/v1/patients",
        json={
            "first_name_en": "Specimen",
            "last_name_en": "Patient",
            "passport_number": "B1234567",
        },
        headers=ADMIN_HEADERS,
    )
    assert patient.status_code == 201
    order = client.post(
        "/api/v1/orders",
        json={"patient_id": patient.json()["id"], "test_ids": test_ids},
        headers=HEADERS,
    )
    assert order.status_code == 201
    return order.json()["id"], serum.json()["id"], urine.json()["id"], plasma.json()["id"]


@pytest.mark.integration
def test_collection_groups_items_and_records_audit(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, serum_id, urine_id, _ = create_collection_order(client)

    requirements = client.get(
        f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS
    )
    assert requirements.status_code == 200
    grouped = {item["specimen_type_id"]: item for item in requirements.json()}
    assert {item["test_code"] for item in grouped[serum_id]["items"]} == {"GLU", "CREA"}
    assert [item["test_code"] for item in grouped[urine_id]["items"]] == ["UPRO"]

    collected = client.post(
        "/api/v1/specimens",
        json={
            "order_id": order_id,
            "specimen_type_id": serum_id,
            "collection_note": "  Morning draw  ",
        },
        headers=HEADERS,
    )
    assert collected.status_code == 201
    specimen = collected.json()
    assert specimen["accession_number"].startswith("SPC")
    assert specimen["status"] == "COLLECTED"
    assert specimen["collection_note"] == "Morning draw"
    assert len(specimen["items"]) == 2

    with db_session_factory() as session:
        audit = session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "specimen", AuditLog.entity_id == specimen["id"]
            )
        ).one()
    assert audit.event_type == "SPECIMEN_COLLECTED"
    assert audit.reason == ""
    assert audit.changed_fields == sorted(audit.changed_fields)


@pytest.mark.integration
def test_specimen_rejection_and_duplicate_collection_rules(client: TestClient) -> None:
    order_id, serum_id, _, unrelated_type_id = create_collection_order(client)

    not_required = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": unrelated_type_id},
        headers=HEADERS,
    )
    assert not_required.status_code == 422

    collected = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    specimen_id = collected.json()["id"]
    assert collected.status_code == 201

    missing_reason = client.patch(
        f"/api/v1/specimens/{specimen_id}/rejection", json={}, headers=HEADERS
    )
    assert missing_reason.status_code == 422
    rejected = client.patch(
        f"/api/v1/specimens/{specimen_id}/rejection",
        json={"rejection_reason": "haemolysed sample"},
        headers=HEADERS,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["rejection_reason"] == "haemolysed sample"

    duplicate = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert duplicate.status_code == 422
    second_rejection = client.patch(
        f"/api/v1/specimens/{specimen_id}/rejection",
        json={"rejection_reason": "duplicate"},
        headers=HEADERS,
    )
    assert second_rejection.status_code == 422


@pytest.mark.integration
def test_web_collection_view_and_submit(client: TestClient) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)

    page = client.get(f"/orders/{order_id}/specimens", headers=HEADERS)
    assert page.status_code == 200
    assert "Glucose" in page.text
    collected = client.post(
        f"/orders/{order_id}/specimens/{serum_id}/collect",
        data={"collection_note": "web collection"},
        headers=HEADERS,
        follow_redirects=False,
    )
    assert collected.status_code == 303
    detail = client.get(collected.headers["location"], headers=HEADERS)
    assert detail.status_code == 200
    assert "SPC" in detail.text
