from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.order import LabOrder
from tests.integration.test_specimens import ADMIN_HEADERS, HEADERS, create_collection_order

RECEPTION = {"X-Role": "RECEPTION", "X-Actor": "package-reception"}


def setup_tests(client):
    original_id, serum, urine, _ = create_collection_order(client)
    order = client.get(f"/api/v1/orders/{original_id}", headers=HEADERS).json()
    tests = {item["test_code"]: item["lab_test_id"] for item in order["items"]}
    return order["patient_id"], tests, serum, urine


def package(client, code, ids, price):
    data = dict(code=code, name=code, test_ids=ids, price=price)
    response = client.post("/api/v1/packages", headers=ADMIN_HEADERS, json=data)
    assert response.status_code == 201, response.text
    return response.json(), data


@pytest.mark.integration
def test_package_fixed_price_deduplicates_tests_and_preserves_history(client, db_session_factory):
    patient, tests, serum, _ = setup_tests(client)
    first, first_data = package(client, "BASIC", [tests["GLU"], tests["CREA"]], "150.50")
    second, _ = package(client, "FIT", [tests["GLU"]], "80.25")
    response = client.post(
        "/api/v1/orders",
        headers=RECEPTION,
        json={
            "patient_id": patient,
            "package_ids": [first["id"], second["id"]],
            "test_ids": [tests["GLU"], tests["UPRO"]],
        },
    )
    assert response.status_code == 201, response.text
    order = response.json()
    order_id = order["id"]
    assert len(order["items"]) == 3
    assert Decimal(order["total_price"]) == Decimal("330.75")
    assert {i["test_code"] for i in order["items"] if i["included_in_package"]} == {"GLU", "CREA"}
    detail = client.get(f"/orders/{order_id}", headers=RECEPTION)
    assert detail.status_code == 200
    assert "330.75" in detail.text and "BASIC" in detail.text
    changed = client.put(
        f"/api/v1/packages/{first['id']}",
        headers=ADMIN_HEADERS,
        json={
            **first_data,
            "name": "Changed package",
            "price": "999",
            "test_ids": [tests["UPRO"]],
            "is_active": False,
        },
    )
    assert changed.status_code == 200
    historical = client.get(f"/api/v1/orders/{order_id}", headers=RECEPTION).json()
    assert historical["package_snapshots"] == order["package_snapshots"]
    assert historical["total_price"] == order["total_price"]
    with db_session_factory() as session:
        saved = session.get(LabOrder, order_id)
        assert saved.total_price == Decimal("330.75")
        assert {
            event.event_type
            for event in session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type == "test_package", AuditLog.entity_id == first["id"]
                )
            )
        } == {"PACKAGE_CREATED", "PACKAGE_UPDATED"}
    # Package contents use the normal collection workflow, grouped by specimen type.
    requirements = client.get(f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS)
    assert requirements.status_code == 200
    assert sum(len(group["items"]) for group in requirements.json()) == 3
    collected = client.post(
        "/api/v1/specimens", headers=HEADERS, json={"order_id": order_id, "specimen_type_id": serum}
    )
    assert collected.status_code == 201
    assert len(collected.json()["items"]) == 2


@pytest.mark.integration
def test_package_only_orders_permissions_and_unavailable_packages(client, db_session_factory):
    patient, tests, _, _ = setup_tests(client)
    p, data = package(client, "BASIC", [tests["GLU"]], "75")
    for headers in (RECEPTION, HEADERS):
        assert client.post("/api/v1/packages", headers=headers, json=data).status_code == 403
        assert (
            client.put(f"/api/v1/packages/{p['id']}", headers=headers, json=data).status_code == 403
        )
        assert client.get("/packages", headers=headers).status_code == 403
    package_only = client.post(
        "/orders/new",
        headers=RECEPTION,
        data={
            "patient_id": str(patient),
            "package_ids": str(p["id"]),
        },
        follow_redirects=False,
    )
    assert package_only.status_code == 303
    assert (
        client.post("/api/v1/orders", headers=RECEPTION, json={"patient_id": patient}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/orders",
            headers=RECEPTION,
            json={
                "patient_id": patient,
                "package_ids": [p["id"], p["id"]],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/packages", headers=ADMIN_HEADERS, json={**data, "price": "-1"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/packages", headers=ADMIN_HEADERS, json={**data, "code": "basic"}
        ).status_code
        == 409
    )
    # Deactivated tests make packages unavailable and block ordering atomically.
    with db_session_factory() as session:
        from app.models.test_catalog import LabTest

        session.get(LabTest, tests["GLU"]).is_active = False
        session.commit()
    assert client.get("/api/v1/packages?available_only=true", headers=RECEPTION).json() == []
    assert (
        client.post(
            "/api/v1/orders",
            headers=RECEPTION,
            json={
                "patient_id": patient,
                "package_ids": [p["id"]],
            },
        ).status_code
        == 404
    )


@pytest.mark.integration
def test_package_admin_forms_validate_and_preserve_order_selection(client):
    patient, tests, _, _ = setup_tests(client)
    form = client.get("/packages/new", headers=ADMIN_HEADERS)
    assert form.status_code == 200
    saved = client.post(
        "/packages/new",
        headers=ADMIN_HEADERS,
        data={
            "code": "BASIC",
            "name": "Basic checkup",
            "price": "150",
            "test_ids": [str(tests["GLU"]), str(tests["CREA"])],
            "is_active": "on",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    p = client.get("/api/v1/packages", headers=ADMIN_HEADERS).json()[0]
    edit = client.get(f"/packages/{p['id']}/edit", headers=ADMIN_HEADERS)
    assert edit.status_code == 200
    assert 'value="150.00"' in edit.text
    invalid_order = client.post(
        "/orders/new",
        headers=RECEPTION,
        data={
            "patient_id": str(patient),
            "package_ids": [str(p["id"]), "999999"],
        },
    )
    assert invalid_order.status_code == 422
    assert f'value="{p["id"]}"' in invalid_order.text
    assert "package-choice" in invalid_order.text
    invalid_package = client.post(
        "/packages/new",
        headers=ADMIN_HEADERS,
        data={
            "code": "EMPTY",
            "name": "Empty",
            "price": "50",
            "is_active": "on",
        },
    )
    assert invalid_package.status_code == 422
    assert client.get("/packages", headers=ADMIN_HEADERS).status_code == 200
