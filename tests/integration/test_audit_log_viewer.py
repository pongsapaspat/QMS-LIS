from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit import AuditLog

ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "admin-test"}
SUPERVISOR_HEADERS = {"X-Role": "LAB_SUPERVISOR", "X-Actor": "supervisor-test"}
TECH_HEADERS = {"X-Role": "LAB_TECH", "X-Actor": "tech-test"}


@pytest.mark.integration
def test_audit_viewer_permissions_filters_and_detail(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    with db_session_factory() as session:
        session.add_all(
            [
                AuditLog(
                    event_type="RESULT_VERIFIED",
                    entity_type="result",
                    entity_id=42,
                    changed_fields=["status", "verified_at"],
                    reason="verified",
                    actor_reference="supervisor-test",
                    occurred_at=datetime(2026, 11, 1, 3, 0, tzinfo=UTC),
                ),
                AuditLog(
                    event_type="PATIENT_UPDATED",
                    entity_type="patient",
                    entity_id=7,
                    changed_fields=["phone"],
                    reason="corrected phone",
                    actor_reference="admin-test",
                    occurred_at=datetime(2026, 10, 31, 3, 0, tzinfo=UTC),
                ),
            ]
        )
        session.commit()
        audit_id = session.query(AuditLog.id).filter_by(entity_id=42).scalar()

    assert client.get("/audit-logs", headers=ADMIN_HEADERS).status_code == 200
    supervisor = client.get(
        "/audit-logs",
        params={"actor": "supervisor-test", "entity_type": "result", "entity_id": 42},
        headers=SUPERVISOR_HEADERS,
    )
    assert supervisor.status_code == 200
    assert "RESULT_VERIFIED" in supervisor.text
    assert "patient #7" not in supervisor.text
    assert "แก้ไขหรือลบไม่ได้" in supervisor.text

    export = client.get("/audit-logs/export.csv", headers=SUPERVISOR_HEADERS)
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert "RESULT_VERIFIED" in export.content.decode("utf-8-sig")
    assert "+07:00" in export.content.decode("utf-8-sig")

    detail = client.get(f"/audit-logs/{audit_id}", headers=SUPERVISOR_HEADERS)
    assert detail.status_code == 200
    assert "verified_at" in detail.text
    assert "อ่านอย่างเดียว" in detail.text
    assert client.get("/audit-logs", headers=TECH_HEADERS).status_code == 403
