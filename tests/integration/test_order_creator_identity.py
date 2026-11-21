import pytest
from sqlalchemy import select

from app.models.order import LabOrder
from app.models.user import User
from app.services.report_identity import order_creator_label
from tests.integration.test_result_verification_release import (
    ENTRY_HEADERS,
    SUPERVISOR_HEADERS,
    _completed_order,
)
from tests.integration.test_specimens import create_collection_order

RECEPTION = {"X-Role": "RECEPTION", "X-Actor": "desk"}


@pytest.mark.integration
def test_creator_is_automatic_frozen_and_requires_no_reception_license(client, db_session_factory):
    existing, _, _, _ = create_collection_order(client)
    source = client.get(f"/api/v1/orders/{existing}", headers=ENTRY_HEADERS).json()
    with db_session_factory() as session:
        user = User(
            username="desk",
            role="RECEPTION",
            display_name="Desk alias",
            full_name="Reception Original",
            password_hash="unused",
        )
        session.add(user)
        session.commit()
    page = client.get("/orders/new", headers=RECEPTION)
    assert page.status_code == 200
    assert "Reception Original" in page.text
    assert "ผู้บันทึกคำสั่งตรวจ" in page.text
    assert 'aria-readonly="true"' in page.text
    payload = {
        "patient_id": str(source["patient_id"]),
        "test_ids": [str(source["items"][0]["lab_test_id"])],
        "created_by": "another-user",
        "created_by_name": "Spoofed Name",
    }
    created = client.post("/orders/new", headers=RECEPTION, data=payload, follow_redirects=False)
    assert created.status_code == 303
    with db_session_factory() as session:
        order = session.scalar(select(LabOrder).order_by(LabOrder.id.desc()))
        order_id = order.id
        assert order.created_by == "desk"
        assert order.created_by_snapshot["full_name"] == "Reception Original"
        assert order.created_by_snapshot["license_number"] is None
        user = session.scalar(select(User).where(User.username == "desk"))
        user.full_name = "Reception Renamed"
        session.commit()
        assert order_creator_label(order) == "Reception Original"
    detail = client.get(f"/orders/{order_id}", headers=RECEPTION)
    assert detail.status_code == 200
    assert "Reception Original" in detail.text
    assert "Reception Renamed" not in detail.text
    api = client.get(f"/api/v1/orders/{order_id}", headers=RECEPTION).json()
    assert api["created_by_snapshot"]["full_name"] == "Reception Original"
    spoof = client.post(
        "/api/v1/orders",
        headers=RECEPTION,
        json={
            "patient_id": source["patient_id"],
            "test_ids": [source["items"][0]["lab_test_id"]],
            "created_by_snapshot": {"full_name": "Spoofed"},
        },
    )
    assert spoof.status_code == 422


@pytest.mark.integration
def test_external_referrer_is_optional_and_reopens_on_validation_error(client):
    response = client.get("/orders/new", headers=RECEPTION)
    assert "ผู้ส่งตรวจภายนอก" in response.text
    assert '<details class="col-12 mt-3" >' in response.text  # Closed until needed.
    error = client.post(
        "/orders/new",
        headers=RECEPTION,
        data={"patient_id": "1", "referrer_organization": "External Clinic"},
    )
    assert error.status_code == 422
    assert '<details class="col-12 mt-3" open>' in error.text
    assert 'value="External Clinic"' in error.text


@pytest.mark.integration
def test_report_uses_order_creator_snapshot_and_preserves_external_referrer(
    client, db_session_factory
):
    with db_session_factory() as session:
        session.add(
            User(
                username="collector-1",
                role="LAB_TECH",
                display_name="Alias",
                full_name="Order Recorder Original",
                password_hash="unused",
            )
        )
        session.commit()
    order_id, results = _completed_order(client)
    for result in results:
        assert (
            client.patch(
                f"/api/v1/results/{result['id']}/verify", headers=SUPERVISOR_HEADERS, json={}
            ).status_code
            == 200
        )
    assert (
        client.patch(
            f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR_HEADERS, json={}
        ).status_code
        == 200
    )
    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        order.referrer_name = "External Referrer"
        order.referrer_license_type, order.referrer_license_number = "ว.", "EXT1001"
        user = session.scalar(select(User).where(User.username == "collector-1"))
        user.full_name = "Recorder Renamed"
        session.commit()
    report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS)
    assert "Order Recorder Original" in report.text and "Recorder Renamed" not in report.text
    assert "ผู้บันทึกคำสั่งตรวจ" in report.text and "ผู้ส่งตรวจภายนอก" in report.text
    assert "External Referrer" in report.text and "EXT1001" in report.text
    response = client.get(f"/results/reports/orders/{order_id}/pdf", headers=SUPERVISOR_HEADERS)
    assert response.status_code == 200
    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        order.created_by_snapshot = None  # Legacy records never borrow today's name.
        session.commit()
        assert order_creator_label(order) == "collector-1"
