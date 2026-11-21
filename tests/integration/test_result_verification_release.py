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
from app.models.result import ResultRevision, ResultStatus
from app.schemas.result import OrderRelease
from app.services.result import ResultService
from tests.integration.test_specimens import create_collection_order

ENTRY_HEADERS = {"X-Role": "LAB_TECH", "X-Actor": "entry-tech"}
SUPERVISOR_HEADERS = {"X-Role": "LAB_SUPERVISOR", "X-Actor": "supervisor-1"}
ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "admin-1"}
RECEPTION_HEADERS = {"X-Role": "RECEPTION", "X-Actor": "reception-1"}


@pytest.mark.integration
def test_web_can_continue_partial_results_without_revising_saved_value(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)
    specimen = client.post(
        "/api/v1/specimens",
        headers=ENTRY_HEADERS,
        json={"order_id": order_id, "specimen_type_id": serum_id},
    )
    assert specimen.status_code == 201
    assert (
        client.patch(
            f"/api/v1/specimens/{specimen.json()['id']}/receipt", headers=ENTRY_HEADERS, json={}
        ).status_code
        == 200
    )
    path = f"/worklist/orders/{order_id}"
    context_path = f"/api/v1/results/orders/{order_id}"
    context = client.get(context_path, headers=ENTRY_HEADERS).json()
    entries = {item["test_code"]: item for item in context["items"]}
    glu_id = entries["GLU"]["order_item_id"]
    crea_id = entries["CREA"]["order_item_id"]
    assert (
        client.post(
            path, headers=ENTRY_HEADERS, data={f"value_{glu_id}": "95"}, follow_redirects=False
        ).status_code
        == 303
    )
    original = next(
        item
        for item in client.get(context_path, headers=ENTRY_HEADERS).json()["items"]
        if item["test_code"] == "GLU"
    )["result"]
    page = client.get(path, headers=ENTRY_HEADERS)
    assert f'data-edit-result="{glu_id}"' in page.text
    assert f'id="result-fields-{glu_id}" class="border-0 p-0 m-0" disabled' in page.text
    # Older forms also resubmit saved values; equivalent decimal formatting is unchanged.
    assert (
        client.post(
            path,
            headers=ENTRY_HEADERS,
            data={f"value_{glu_id}": "95.000000", f"value_{crea_id}": "1.1"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    entries = {
        item["test_code"]: item
        for item in client.get(context_path, headers=ENTRY_HEADERS).json()["items"]
    }
    assert entries["GLU"]["result"]["version"] == original["version"]
    with db_session_factory() as session:
        assert (
            list(
                session.scalars(
                    select(ResultRevision).where(ResultRevision.result_id == original["id"])
                )
            )
            == []
        )
    assert entries["CREA"]["result"]["status"] == "COMPLETED"
    changed = client.post(
        path, headers=ENTRY_HEADERS, data={f"value_{glu_id}": "97"}, follow_redirects=False
    )
    assert changed.status_code == 422
    corrected = client.post(
        path,
        headers=ENTRY_HEADERS,
        data={f"value_{glu_id}": "97", f"reason_{glu_id}": "Corrected entry"},
        follow_redirects=False,
    )
    assert corrected.status_code == 303
    result = next(
        item
        for item in client.get(context_path, headers=ENTRY_HEADERS).json()["items"]
        if item["test_code"] == "GLU"
    )["result"]
    with db_session_factory() as session:
        revisions = list(
            session.scalars(select(ResultRevision).where(ResultRevision.result_id == result["id"]))
        )
        assert len(revisions) == 1
        assert revisions[0].modification_reason == "Corrected entry"


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

    context = client.get(f"/api/v1/results/orders/{order_id}", headers=ENTRY_HEADERS).json()
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
def test_verification_web_groups_orders_before_pagination(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, results = _completed_order(client)
    page = client.get('/results/verification', headers=SUPERVISOR_HEADERS)
    assert page.status_code == 200
    queue = page.context['queue']
    assert queue['total'] == 1
    assert len(queue['items']) == 1
    assert queue['items'][0]['pending_count'] == 3
    assert {test['test_code'] for test in queue['items'][0]['results']} == {'GLU', 'CREA', 'UPRO'}
    assert page.text.count(f'href="/results/verification/orders/{order_id}"') == 1
    filtered = client.get('/results/verification?search=GLU', headers=SUPERVISOR_HEADERS)
    assert filtered.context['queue']['total'] == 1
    assert filtered.context['queue']['items'][0]['pending_count'] == 1
    with db_session_factory() as session:
        service = ResultService(session)
        first = service.verification_queue(department_id=None, priority=None, search=None,
                                          page=1, page_size=1, group_orders=True)
        second = service.verification_queue(department_id=None, priority=None, search=None,
                                           page=2, page_size=1, group_orders=True)
        assert first['total'] == second['total'] == 1
        assert first['items'][0]['pending_count'] == 3
        assert second['items'] == []
    assert client.patch(f"/api/v1/results/{results[0]['id']}/verify",
                       headers=SUPERVISOR_HEADERS, json={}).status_code == 200
    remaining = client.get('/results/verification', headers=SUPERVISOR_HEADERS)
    assert remaining.context['queue']['total'] == 1
    assert remaining.context['queue']['items'][0]['pending_count'] == 2


@pytest.mark.integration
def test_admin_bypass_visibility_matches_role_and_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, results = _completed_order(client)
    path = f'/results/verification/orders/{order_id}'
    try:
        monkeypatch.setenv('QMS_LIS_ENFORCE_FOUR_EYES_CHECK', 'true')
        for enabled in ('false', 'true'):
            monkeypatch.setenv('QMS_LIS_ALLOW_ADMIN_FOUR_EYES_BYPASS', enabled)
            get_settings.cache_clear()
            for role in ('ADMIN', 'LAB_SUPERVISOR', 'LAB_TECH'):
                page = client.get(path, headers={'X-Role': role, 'X-Actor': 'reviewer'})
                assert page.status_code == 200
                assert ('name="bypass_four_eyes"' in page.text) == (
                    role == 'ADMIN' and enabled == 'true'
                )
                assert 'Verify result' in page.text
        # A forged bypass cannot let a supervisor verify their own entry.
        denied = client.post(
            f"/results/verification/{results[0]['id']}/verify",
            headers={'X-Role': 'LAB_SUPERVISOR', 'X-Actor': 'entry-tech'},
            data={'order_id': str(order_id), 'bypass_four_eyes': 'on'},
        )
        assert denied.status_code == 422
        assert 'name="bypass_four_eyes"' not in denied.text
        monkeypatch.setenv('QMS_LIS_ENFORCE_FOUR_EYES_CHECK', 'false')
        get_settings.cache_clear()
        assert 'name="bypass_four_eyes"' not in client.get(path, headers=ADMIN_HEADERS).text
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
@pytest.mark.parametrize('action', ['verify', 'reject'])
def test_inline_review_updates_in_place_even_after_last_result(
    client: TestClient, action: str,
) -> None:
    order_id, results = _completed_order(client)
    headers = {**SUPERVISOR_HEADERS, 'X-Verification-Inline': 'true'}
    for index, result in enumerate(results):
        response = client.post(
            f"/results/verification/{result['id']}/{action}", headers=headers,
            data={'order_id': str(order_id), 'reason': 'Please recheck'},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert 'location' not in response.headers
        assert f'id="verification-result-{result["id"]}"' in response.text
        assert response.text.count('data-inline-verification>') == 2 * (len(results) - index - 1)
        statuses = {item['result_id']: item['status']
                    for item in response.context['context']['results']}
        assert statuses[result['id']] == (
            'VERIFIED' if action == 'verify' else 'VERIFICATION_REJECTED'
        )
    # Double submission still goes through the original server-side status checks.
    duplicate = client.post(
        f"/results/verification/{results[0]['id']}/{action}", headers=headers,
        data={'order_id': str(order_id), 'reason': 'Please recheck'},
    )
    assert duplicate.status_code == 422
    assert 'data-verification-error' in duplicate.text


@pytest.mark.integration
def test_inline_verification_preserves_four_eyes_error_and_comment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id, results = _completed_order(client)
    monkeypatch.setenv('QMS_LIS_ENFORCE_FOUR_EYES_CHECK', 'true')
    get_settings.cache_clear()
    try:
        response = client.post(
            f"/results/verification/{results[0]['id']}/verify",
            headers={'X-Role': 'LAB_SUPERVISOR', 'X-Actor': 'entry-tech',
                     'X-Verification-Inline': 'true'},
            data={'order_id': str(order_id), 'comment': 'Keep this comment'},
        )
        assert response.status_code == 422
        assert 'data-verification-error' in response.text
        assert 'Keep this comment' in response.text
        assert all(item['status'] == 'COMPLETED'
                   for item in response.context['context']['results'])
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
@pytest.mark.parametrize('actions', [
    ('verify', 'verify', 'verify'),
    ('reject', 'verify', 'verify'),
    ('verify', 'verify', 'reject'),
])
def test_web_review_stays_on_order_until_all_results_are_reviewed(
    client: TestClient, actions: tuple[str, str, str],
) -> None:
    order_id, results = _completed_order(client)
    for index, (result, action) in enumerate(zip(results, actions, strict=True)):
        response = client.post(
            f"/results/verification/{result['id']}/{action}",
            data={'order_id': str(order_id), 'reason': 'Please check result'},
            headers=SUPERVISOR_HEADERS, follow_redirects=False,
        )
        assert response.status_code == 303
        destination = (f'/results/verification/orders/{order_id}'
                       if index < len(results) - 1 else '/results/verification')
        success = 'result-verified' if action == 'verify' else 'result-rejected'
        assert response.headers['location'].endswith(f'{destination}?success={success}')
        page = client.get(response.headers['location'], headers=SUPERVISOR_HEADERS)
        assert page.status_code == 200
        if index < len(results) - 1:
            statuses = {entry['result_id']: entry['status']
                        for entry in page.context['context']['results']}
            assert statuses[result['id']] == (
                'VERIFIED' if action == 'verify' else 'VERIFICATION_REJECTED'
            )


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
        assert (
            client.get(f"/results/reports/orders/{order_id}", headers=RECEPTION_HEADERS).status_code
            == 409
        )

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
        assert (
            client.get("/api/v1/results/verification-queue", headers=RECEPTION_HEADERS).status_code
            == 403
        )
        stale = client.patch(
            f"/api/v1/results/{result_ids[0]}/verify",
            json={"version": 999999},
            headers=SUPERVISOR_HEADERS,
        )
        assert stale.status_code == 409
        assert (
            client.patch(
                f"/api/v1/results/{result_ids[0]}/verify",
                json={"actor_reference": "spoofed"},
                headers=SUPERVISOR_HEADERS,
            ).status_code
            == 422
        )

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
        assert (
            client.get("/api/v1/results/release-queue", headers=SUPERVISOR_HEADERS).json()["total"]
            == 0
        )

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
            item["task_type"] == "RESULT_CORRECTION_REQUIRED" for item in correction_tasks["items"]
        )
        correction_page = client.get(f"/worklist/orders/{order_id}", headers=ENTRY_HEADERS)
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
        release_queue = client.get("/api/v1/results/release-queue", headers=SUPERVISOR_HEADERS)
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
        assert (
            client.patch(
                f"/api/v1/orders/{order_id}/release",
                json={},
                headers=ENTRY_HEADERS,
            ).status_code
            == 403
        )

        released = client.patch(
            f"/api/v1/orders/{order_id}/release",
            json={"comment": "authorized final release"},
            headers=SUPERVISOR_HEADERS,
        )
        assert released.status_code == 200
        assert released.json()["status"] == "RELEASED"

        report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS)
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("text/html")
        assert "รายงานผลการตรวจทางห้องปฏิบัติการ" in report.text
        assert "QMS-LIS" in report.text
        assert "พิมพ์รายงาน" in report.text
        assert report.context['context']['reported_by'] == ENTRY_HEADERS['X-Actor']
        assert report.context['context']['order'].released_by == SUPERVISOR_HEADERS['X-Actor']
        assert 'รายงานผลโดย:</strong> entry-tech' in report.text
        assert 'อนุมัติผลโดย:</strong> supervisor-1' in report.text
        assert 'ตรวจสอบผลโดย:' not in report.text
        assert "Glucose Thai" in report.text

        reception_report = client.get(
            f"/results/reports/orders/{order_id}", headers=RECEPTION_HEADERS
        )
        assert reception_report.status_code == 200
        assert "QMS-LIS" in reception_report.text

        pdf_report = client.get(
            f"/results/reports/orders/{order_id}/pdf", headers=SUPERVISOR_HEADERS
        )
        assert pdf_report.status_code == 200
        assert pdf_report.headers["content-type"] == "application/pdf"
        assert pdf_report.headers["content-disposition"].endswith('.pdf"')
        assert pdf_report.content.startswith(b"%PDF-")

        reception_pdf = client.get(
            f"/results/reports/orders/{order_id}/pdf", headers=RECEPTION_HEADERS
        )
        assert reception_pdf.status_code == 200
        assert reception_pdf.content.startswith(b"%PDF-")

        report_list = client.get(
            "/results/reports",
            params={"search": released.json()["order_number"]},
            headers=SUPERVISOR_HEADERS,
        )
        assert report_list.status_code == 200
        assert "รายงานผลตรวจ" in report_list.text
        assert released.json()["order_number"] in report_list.text
        assert f"/results/reports/orders/{order_id}" in report_list.text

        reception_report_list = client.get("/results/reports", headers=RECEPTION_HEADERS)
        assert reception_report_list.status_code == 200
        assert released.json()["order_number"] in reception_report_list.text

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

        reception_amendment = client.post(
            f"/results/{result_ids[0]}/amendments",
            data={"reason": "reception must not amend results"},
            headers=RECEPTION_HEADERS,
            follow_redirects=False,
        )
        assert reception_amendment.status_code == 403

        amendment = client.post(
            f"/results/{result_ids[0]}/amendments",
            data={"reason": "แก้ไขผลหลังตรวจสอบเครื่องมือซ้ำ"},
            headers=ENTRY_HEADERS,
            follow_redirects=False,
        )
        assert amendment.status_code == 303
        assert amendment.headers["location"].endswith(f"/worklist/orders/{order_id}")
        assert (
            client.get(
                f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS
            ).status_code
            == 409
        )
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
        assert (
            client.patch(
                f"/api/v1/results/{result_ids[0]}/verify",
                json={},
                headers=SUPERVISOR_HEADERS,
            ).status_code
            == 200
        )
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
                "LAB_REPORT_PDF_DOWNLOADED",
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
    assert (
        client.get("/api/v1/results/orders/999999/verification", headers=ADMIN_HEADERS).status_code
        == 404
    )
    assert (
        client.patch("/api/v1/orders/999999/release", json={}, headers=ADMIN_HEADERS).status_code
        == 404
    )

    assert (
        client.patch(
            f"/api/v1/results/{first_id}/verify", json={}, headers=SUPERVISOR_HEADERS
        ).status_code
        == 200
    )
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
