from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.order import LabOrder
from app.models.result import Result
from app.models.user import User
from app.services.result import ResultService
from tests.integration.test_result_verification_release import (
    ADMIN_HEADERS,
    ENTRY_HEADERS,
    SUPERVISOR_HEADERS,
    _completed_order,
)
from tests.integration.test_specimens import create_collection_order


def seed_profiles(factory):
    with factory() as session:
        for username, role, name, number in [
            ("entry-tech", "LAB_TECH", "นางสาวผู้ลงผล ตัวอย่าง", "TEST1001"),
            ("supervisor-1", "LAB_SUPERVISOR", "นายผู้อนุมัติ ตัวอย่าง", "TEST1002"),
        ]:
            session.add(
                User(
                    username=username,
                    role=role,
                    display_name=username,
                    password_hash="unused-for-development-header-tests",
                    full_name=name,
                    professional_license_number=number,
                )
            )
        session.commit()


@pytest.mark.integration
def test_credentials_are_frozen_and_reports_do_not_lookup_current_profile(
    client, db_session_factory
):
    seed_profiles(db_session_factory)
    order_id, results = _completed_order(client)
    for result in results:
        response = client.patch(
            f"/api/v1/results/{result['id']}/verify", headers=SUPERVISOR_HEADERS, json={}
        )
        assert response.status_code == 200, response.text
    response = client.patch(
        f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR_HEADERS, json={}
    )
    assert response.status_code == 200, response.text
    with db_session_factory() as session:
        ids = list(session.scalars(select(User.id)))
        before = ResultService(session).report_context(order_id, actor_reference="reviewer")
        assert "TEST1001" in before["sections"][0]["reporters"][0]["label"]
        assert "TEST1002" in before["sections"][0]["approvers"][0]["label"]
    for user_id in ids:
        response = client.post(
            f"/users/{user_id}/profile",
            headers=ADMIN_HEADERS,
            data={"full_name": "ชื่อใหม่ นามสกุลใหม่", "professional_license_number": "CHANGED999"},
            follow_redirects=False,
        )
        assert response.status_code == 303
    report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS)
    assert report.status_code == 200
    assert "นางสาวผู้ลงผล ตัวอย่าง" in report.text and "TEST1001" in report.text
    assert "นายผู้อนุมัติ ตัวอย่าง" in report.text and "TEST1002" in report.text
    assert "CHANGED999" not in report.text
    pdf = client.get(f"/results/reports/orders/{order_id}/pdf", headers=SUPERVISOR_HEADERS)
    assert pdf.status_code == 200
    with db_session_factory() as session:
        result = session.get(Result, results[0]["id"])
        assert result.entered_by_snapshot["license_number"] == "TEST1001"
        assert result.verified_by_snapshot["license_number"] == "TEST1002"
        assert result.released_by_snapshot["license_number"] == "TEST1002"
        # Legacy signatures must stay unknown even when the account now has a profile.
        for item in session.get(LabOrder, order_id).items:
            item.result.entered_by_snapshot = None
            item.result.last_modified_by_snapshot = None
            item.result.released_by_snapshot = None
        session.get(LabOrder, order_id).released_by_snapshot = None
        session.commit()
        legacy = ResultService(session).report_context(order_id, actor_reference="reviewer")
        assert "CHANGED999" not in str(legacy["sections"])
        assert "entry-tech" in legacy["sections"][0]["reporters"][0]["label"]


@pytest.mark.integration
def test_profile_management_permission_validation_and_audit(client, db_session_factory):
    seed_profiles(db_session_factory)
    with db_session_factory() as session:
        user_id = session.scalar(select(User.id).where(User.username == "entry-tech"))
    url = f"/users/{user_id}/profile"
    for headers in (ENTRY_HEADERS, SUPERVISOR_HEADERS, {"X-Role": "RECEPTION"}):
        assert client.post(url, headers=headers, data={}).status_code == 403
    for data in (
        {"full_name": "   ", "professional_license_number": "1"},
        {"full_name": "ก" * 201, "professional_license_number": "1"},
    ):
        assert client.post(url, headers=ADMIN_HEADERS, data=data).status_code == 422
    response = client.post(
        url,
        headers=ADMIN_HEADERS,
        data={"full_name": "  ชื่อจริง   นามสกุล  ", "professional_license_number": "  TEST2001  "},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with db_session_factory() as session:
        user = session.get(User, user_id)
        assert user.full_name == "ชื่อจริง นามสกุล"
        assert user.professional_license_number == "TEST2001"
        audit = session.scalar(
            select(AuditLog).where(AuditLog.event_type == "USER_PROFESSIONAL_PROFILE_UPDATED")
        )
        assert set(audit.changed_fields) == {"full_name", "professional_license_number"}


@pytest.mark.integration
def test_real_account_missing_credentials_cannot_approve(client, db_session_factory):
    order_id, results = _completed_order(client)
    with db_session_factory() as session:
        session.add(
            User(
                username="supervisor-1",
                role="LAB_SUPERVISOR",
                display_name="Supervisor",
                password_hash="unused",
            )
        )
        session.commit()
    response = client.patch(
        f"/api/v1/results/{results[0]['id']}/verify", headers=SUPERVISOR_HEADERS, json={}
    )
    assert response.status_code == 422
    assert "ชื่อ-นามสกุล" in response.json()["detail"]
    with db_session_factory() as session:
        assert session.get(Result, results[0]["id"]).status == "COMPLETED"


@pytest.mark.integration
def test_missing_profile_blocks_completion_and_release_atomically(client, db_session_factory):
    order_id, results = _completed_order(client)
    seed_profiles(db_session_factory)
    with db_session_factory() as session:
        tech = session.scalar(select(User).where(User.username == "entry-tech"))
        tech.professional_license_number = None
        session.commit()
    response = client.put(
        f"/api/v1/results/{results[0]['id']}",
        headers=ENTRY_HEADERS,
        json={
            "order_item_id": results[0]["order_item_id"],
            "numeric_value": "99",
            "complete": True,
            "modification_reason": "Correction",
        },
    )
    assert response.status_code == 422
    with db_session_factory() as session:
        result = session.get(Result, results[0]["id"])
        assert result.numeric_value == Decimal(str(results[0]["numeric_value"]))
        assert result.status == "COMPLETED"
    for result in results:
        assert (
            client.patch(
                f"/api/v1/results/{result['id']}/verify", headers=SUPERVISOR_HEADERS, json={}
            ).status_code
            == 200
        )
    with db_session_factory() as session:
        supervisor = session.scalar(select(User).where(User.username == "supervisor-1"))
        supervisor.full_name = None
        session.commit()
    assert (
        client.patch(
            f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR_HEADERS, json={}
        ).status_code
        == 422
    )
    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        assert order.released_by is None
        assert all(item.result.status == "VERIFIED" for item in order.items)


@pytest.mark.integration
def test_amendment_uses_current_writer_and_preserves_previous_revision(client, db_session_factory):
    seed_profiles(db_session_factory)
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
        user = session.scalar(select(User).where(User.username == "entry-tech"))
        user.full_name = "ผู้แก้ไขผล ตัวอย่าง"
        user.professional_license_number = "AMENDED1001"
        session.commit()
    result = results[0]
    assert (
        client.post(
            f"/results/{result['id']}/amendments",
            headers=SUPERVISOR_HEADERS,
            data={"reason": "Correct value"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    response = client.put(
        f"/api/v1/results/{result['id']}",
        headers=ENTRY_HEADERS,
        json={
            "order_item_id": result["order_item_id"],
            "numeric_value": "99",
            "complete": True,
            "modification_reason": "Corrected value",
        },
    )
    assert response.status_code == 200, response.text
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
        amended = session.get(Result, result["id"])
        assert amended.entered_by_snapshot["license_number"] == "TEST1001"
        assert amended.last_modified_by_snapshot["license_number"] == "AMENDED1001"
        assert (
            amended.revisions[-1].previous_value["released_by_snapshot"]["license_number"]
            == "TEST1002"
        )
        context = ResultService(session).report_context(order_id, actor_reference="reviewer")
        labels = str([section["reporters"] for section in context["sections"]])
        assert "AMENDED1001" in labels and "TEST1001" in labels


@pytest.mark.integration
def test_referrer_is_separate_from_creator_and_validated(client):
    existing_id, _, _, _ = create_collection_order(client)
    existing = client.get(f"/api/v1/orders/{existing_id}", headers=ENTRY_HEADERS).json()
    data = {
        "patient_id": existing["patient_id"],
        "test_ids": [existing["items"][0]["lab_test_id"]],
        "referrer_name": " นพ.ผู้ส่งตรวจ   ตัวอย่าง ",
        "referrer_organization": "คลินิกตัวอย่าง",
        "referrer_license_type": "ว.",
        "referrer_license_number": "TEST3001",
    }
    response = client.post(
        "/api/v1/orders", headers={"X-Role": "RECEPTION", "X-Actor": "desk"}, json=data
    )
    assert response.status_code == 201
    order = response.json()
    assert order["referrer_name"] == "นพ.ผู้ส่งตรวจ ตัวอย่าง"
    assert order["referrer_license_type"] == "ว."
    assert order["created_by"] == "desk"
    assert (
        client.post(
            "/api/v1/orders", headers=ENTRY_HEADERS, json={**data, "referrer_name": " "}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/orders", headers=ENTRY_HEADERS, json={**data, "referrer_license_type": " "}
        ).status_code
        == 422
    )
