from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.time import to_app_timezone
from app.domain.exceptions import InvalidResultOperationError
from app.models.audit import AuditLog
from app.models.order import LabOrder, OrderStatus
from app.models.result import ResultStatus
from app.schemas.result import OrderRelease
from app.services.result import ResultService
from tests.integration.test_specimens import create_collection_order

ENTRY_HEADERS = {"X-Role": "LAB_TECH", "X-Actor": "entry-tech"}
SUPERVISOR_HEADERS = {"X-Role": "LAB_SUPERVISOR", "X-Actor": "supervisor-1"}
ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "admin-1"}
RECEPTION_HEADERS = {"X-Role": "RECEPTION", "X-Actor": "reception-1"}


def _completed_order(client: TestClient) -> tuple[int, list[dict[str, object]]]:
    order_id, serum_id, urine_id, _ = create_collection_order(client)
    for specimen_type_id in (serum_id, urine_id):
        collected = client.post(
            "/api/v1/specimens",
            json={"order_id": order_id, "specimen_type_id": specimen_type_id},
            headers=ENTRY_HEADERS,
        )
        assert collected.status_code == 201
        received = client.patch(
            f"/api/v1/specimens/{collected.json()['id']}/receipt",
            json={},
            headers=ENTRY_HEADERS,
        )
        assert received.status_code == 200

    context = client.get(
        f"/api/v1/results/orders/{order_id}", headers=ENTRY_HEADERS
    ).json()
    values = {"GLU": "95", "CREA": "1.1", "UPRO": "12"}
    response = client.post(
        f"/api/v1/results/orders/{order_id}",
        json={
            "items": [
                {
                    "order_item_id": item["order_item_id"],
                    "numeric_value": values[item["test_code"]],
                    "complete": True,
                }
                for item in context["items"]
            ]
        },
        headers=ENTRY_HEADERS,
    )
    assert response.status_code == 200
    return order_id, response.json()


@pytest.mark.integration
def test_verification_rejection_correction_and_atomic_release(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QMS_LIS_ENFORCE_FOUR_EYES_CHECK", "true")
    get_settings.cache_clear()
    try:
        order_id, results = _completed_order(client)
        result_ids = [int(result["id"]) for result in results]

        unavailable_report = client.get(
            f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS
        )
        assert unavailable_report.status_code == 409
        assert unavailable_report.headers["content-type"].startswith("text/html")
        assert "รายงานผลตรวจยังไม่พร้อม" in unavailable_report.text
        assert client.get(
            f"/results/reports/orders/{order_id}", headers=RECEPTION_HEADERS
        ).status_code == 403

        queue = client.get("/api/v1/results/verification-queue", headers=ENTRY_HEADERS)
        assert queue.status_code == 200
        assert queue.json()["total"] == 3
        assert {item["status"] for item in queue.json()["items"]} == {"COMPLETED"}
        verification_page = client.get("/results/verification", headers=ENTRY_HEADERS)
        assert verification_page.status_code == 200
        assert "Completed results awaiting independent review" in verification_page.text
        verification_detail = client.get(
            f"/results/verification/orders/{order_id}", headers=SUPERVISOR_HEADERS
        )
        assert verification_detail.status_code == 200
        assert "Verify result" in verification_detail.text
        assert client.get(
            "/api/v1/results/verification-queue", headers=RECEPTION_HEADERS
        ).status_code == 403
        stale = client.patch(
            f"/api/v1/results/{result_ids[0]}/verify",
            json={"version": 999999},
            headers=SUPERVISOR_HEADERS,
        )
        assert stale.status_code == 409
        assert client.patch(
            f"/api/v1/results/{result_ids[0]}/verify",
            json={"actor_reference": "spoofed"},
            headers=SUPERVISOR_HEADERS,
        ).status_code == 422

        self_verification = client.patch(
            f"/api/v1/results/{result_ids[0]}/verify",
            json={"comment": "looks good"},
            headers=ENTRY_HEADERS,
        )
        assert self_verification.status_code == 422
        assert "four-eyes" in self_verification.json()["detail"]

        monkeypatch.setenv("QMS_LIS_ALLOW_ADMIN_FOUR_EYES_BYPASS", "true")
        get_settings.cache_clear()
        admin_bypass = client.patch(
            f"/api/v1/results/{result_ids[0]}/verify",
            json={"bypass_four_eyes": True},
            headers={"X-Role": "ADMIN", "X-Actor": "entry-tech"},
        )
        assert admin_bypass.status_code == 200
        verified = client.patch(
            f"/api/v1/results/{result_ids[1]}/verify",
            json={},
            headers=SUPERVISOR_HEADERS,
        )
        assert verified.status_code == 200
        assert verified.json()["status"] == "VERIFIED"
        assert client.get(
            "/api/v1/results/release-queue", headers=SUPERVISOR_HEADERS
        ).json()["total"] == 0

        missing_reason = client.patch(
            f"/api/v1/results/{result_ids[2]}/verification-rejection",
            json={},
            headers=SUPERVISOR_HEADERS,
        )
        assert missing_reason.status_code == 422
        rejected = client.patch(
            f"/api/v1/results/{result_ids[2]}/verification-rejection",
            json={"reason": "instrument trace requires review"},
            headers=SUPERVISOR_HEADERS,
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "VERIFICATION_REJECTED"
        assert rejected.json()["numeric_value"] == "12.000000"
        correction_tasks = client.get("/api/v1/worklist", headers=ENTRY_HEADERS).json()
        assert any(
            item["task_type"] == "RESULT_CORRECTION_REQUIRED"
            for item in correction_tasks["items"]
        )
        correction_page = client.get(
            f"/worklist/orders/{order_id}", headers=ENTRY_HEADERS
        )
        assert correction_page.status_code == 200
        assert "เหตุผลการแก้ไขผล" in correction_page.text

        corrected = client.put(
            f"/api/v1/results/{result_ids[2]}",
            json={
                "order_item_id": rejected.json()["order_item_id"],
                "numeric_value": "13",
                "complete": True,
                "modification_reason": "repeat analysis confirmed corrected value",
            },
            headers=ENTRY_HEADERS,
        )
        assert corrected.status_code == 200
        assert corrected.json()["status"] == "COMPLETED"
        assert corrected.json()["verification_rejection_reason"] is None

        final_verification = client.patch(
            f"/api/v1/results/{result_ids[2]}/verify",
            json={},
            headers=SUPERVISOR_HEADERS,
        )
        assert final_verification.status_code == 200
        release_queue = client.get(
            "/api/v1/results/release-queue", headers=SUPERVISOR_HEADERS
        )
        assert release_queue.status_code == 200
        assert release_queue.json()["total"] == 1
        release_page = client.get("/results/release", headers=SUPERVISOR_HEADERS)
        assert release_page.status_code == 200
        assert "Fully verified orders ready for release" in release_page.text
        release_detail = client.get(
            f"/results/release/orders/{order_id}", headers=SUPERVISOR_HEADERS
        )
        assert release_detail.status_code == 200
        assert "Release entire order" in release_detail.text

        preview = client.get(
            f"/api/v1/orders/{order_id}/release-preview", headers=SUPERVISOR_HEADERS
        )
        assert preview.status_code == 200
        assert preview.json()["release_ready"] is True
        assert len(preview.json()["results"]) == 3
        assert client.patch(
            f"/api/v1/orders/{order_id}/release",
            json={},
            headers=ENTRY_HEADERS,
        ).status_code == 403

        released = client.patch(
            f"/api/v1/orders/{order_id}/release",
            json={"comment": "authorized final release"},
            headers=SUPERVISOR_HEADERS,
        )
        assert released.status_code == 200
        assert released.json()["status"] == "RELEASED"

        report = client.get(
            f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS
        )
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("text/html")
        assert "รายงานผลการตรวจทางห้องปฏิบัติการ" in report.text
        assert "QMS-LIS" in report.text
        assert "พิมพ์รายงาน" in report.text
        assert "Glucose Thai" in report.text

        report_list = client.get(
            "/results/reports",
            params={"search": released.json()["order_number"]},
            headers=SUPERVISOR_HEADERS,
        )
        assert report_list.status_code == 200
        assert "รายงานผลตรวจ" in report_list.text
        assert released.json()["order_number"] in report_list.text
        assert f'/results/reports/orders/{order_id}' in report_list.text

        release_date = to_app_timezone(
            datetime.fromisoformat(released.json()["released_at"])
        ).date()
        filtered_reports = client.get(
            "/results/reports",
            params={
                "date_from": release_date.isoformat(),
                "date_to": release_date.isoformat(),
            },
            headers=SUPERVISOR_HEADERS,
        )
        assert released.json()["order_number"] in filtered_reports.text
        excluded_reports = client.get(
            "/results/reports",
            params={"date_from": (release_date + timedelta(days=1)).isoformat()},
            headers=SUPERVISOR_HEADERS,
        )
        assert released.json()["order_number"] not in excluded_reports.text

        amendment = client.post(
            f"/results/{result_ids[0]}/amendments",
            data={"reason": "แก้ไขผลหลังตรวจสอบเครื่องมือซ้ำ"},
            headers=ENTRY_HEADERS,
            follow_redirects=False,
        )
        assert amendment.status_code == 303
        assert amendment.headers["location"].endswith(f"/worklist/orders/{order_id}")
        assert client.get(
            f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS
        ).status_code == 409
        amendment_worklist = client.get(
            "/api/v1/worklist",
            params={"task_type": "RESULT_CORRECTION_REQUIRED"},
            headers=ENTRY_HEADERS,
        ).json()
        assert any(
            item["order_item_id"] == results[0]["order_item_id"]
            for item in amendment_worklist["items"]
        )
        amended = client.put(
            f"/api/v1/results/{result_ids[0]}",
            json={
                "order_item_id": results[0]["order_item_id"],
                "numeric_value": "99",
                "complete": True,
                "modification_reason": "confirmed by repeat analysis",
            },
            headers=ENTRY_HEADERS,
        )
        assert amended.status_code == 200
        assert amended.json()["status"] == "COMPLETED"
        assert client.patch(
            f"/api/v1/results/{result_ids[0]}/verify",
            json={},
            headers=SUPERVISOR_HEADERS,
        ).status_code == 200
        amendment_release = client.post(
            f"/results/release/orders/{order_id}",
            data={"comment": "release amended result"},
            headers=SUPERVISOR_HEADERS,
            follow_redirects=False,
        )
        assert amendment_release.status_code == 303
        amended_report = client.get(
            amendment_release.headers["location"], headers=SUPERVISOR_HEADERS
        )
        assert amended_report.status_code == 200
        assert "99.000000" in amended_report.text
        assert "ฉบับแก้ไข" not in amended_report.text

        edit_released = client.put(
            f"/api/v1/results/{result_ids[0]}",
            json={
                "order_item_id": results[0]["order_item_id"],
                "numeric_value": "99",
                "complete": True,
                "modification_reason": "normal edit must be blocked",
            },
            headers=ENTRY_HEADERS,
        )
        assert edit_released.status_code == 422
        assert "amendment workflow" in edit_released.json()["detail"]

        with db_session_factory() as session:
            order = session.get(LabOrder, order_id)
            assert order is not None
            assert order.status == OrderStatus.RELEASED
            stored_results = [item.result for item in order.items]
            assert all(result is not None for result in stored_results)
            assert all(result.status == ResultStatus.RELEASED for result in stored_results)
            events = set(session.scalars(select(AuditLog.event_type)))
            assert {
                "RESULT_VERIFIED",
                "RESULT_VERIFICATION_REJECTED",
                "ORDER_VERIFIED",
                "ORDER_RELEASED",
                "RESULT_RELEASED",
                "ADMIN_FOUR_EYES_BYPASS",
                "LAB_REPORT_VIEWED",
                "RESULT_AMENDMENT_OPENED",
                "ORDER_AMENDMENT_OPENED",
                "RESULT_AMENDED",
                "RESULT_AMENDMENT_RELEASED",
            } <= events
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
def test_incomplete_cancelled_and_unknown_release_errors(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, results = _completed_order(client)
    first_id = int(results[0]["id"])
    assert client.get(
        "/api/v1/results/orders/999999/verification", headers=ADMIN_HEADERS
    ).status_code == 404
    assert client.patch(
        "/api/v1/orders/999999/release", json={}, headers=ADMIN_HEADERS
    ).status_code == 404

    assert client.patch(
        f"/api/v1/results/{first_id}/verify", json={}, headers=SUPERVISOR_HEADERS
    ).status_code == 200
    incomplete = client.patch(
        f"/api/v1/orders/{order_id}/release", json={}, headers=SUPERVISOR_HEADERS
    )
    assert incomplete.status_code == 422
    assert "not verified" in incomplete.json()["detail"]

    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        assert order is not None
        order.status = OrderStatus.CANCELLED
        session.commit()
    cancelled = client.patch(
        f"/api/v1/orders/{order_id}/release", json={}, headers=SUPERVISOR_HEADERS
    )
    assert cancelled.status_code == 422
    assert "cancelled" in cancelled.json()["detail"]


@pytest.mark.integration
def test_release_rolls_back_when_audit_persistence_fails(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, results = _completed_order(client)
    for result in results:
        response = client.patch(
            f"/api/v1/results/{result['id']}/verify",
            json={},
            headers=SUPERVISOR_HEADERS,
        )
        assert response.status_code == 200

    with db_session_factory() as session:
        service = ResultService(session)

        def fail_audit(_: AuditLog) -> AuditLog:
            raise IntegrityError("INSERT audit_logs", {}, Exception("forced failure"))

        monkeypatch.setattr(service.audit_repository, "add", fail_audit)
        with pytest.raises(InvalidResultOperationError, match="could not be completed"):
            service.release(
                order_id,
                OrderRelease(),
                actor_reference="supervisor-1",
            )
        session.expire_all()
        order = session.get(LabOrder, order_id)
        assert order is not None
        assert order.status == OrderStatus.RESULTS_VERIFIED
        assert all(
            item.result is not None and item.result.status == ResultStatus.VERIFIED
            for item in order.items
        )
