import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.passwords import hash_password
from app.models.audit import AuditLog
from app.models.user import User


@pytest.mark.integration
def test_login_session_and_logout(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_session_factory() as session:
        session.add(
            User(
                username="supervisor",
                password_hash=hash_password("correct-password"),
                role="LAB_SUPERVISOR",
                display_name="Supervisor",
            )
        )
        session.commit()

    login = client.post(
        "/login",
        data={"username": "supervisor", "password": "correct-password"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"].endswith("/")
    protected = client.get("/results/release")
    assert protected.status_code == 200
    assert "Release Queue" in protected.text

    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    with db_session_factory() as session:
        events = [
            entry.event_type
            for entry in session.query(AuditLog)
            .filter(AuditLog.entity_type == "user")
            .order_by(AuditLog.id)
        ]
        assert events == ["USER_LOGGED_IN", "USER_LOGGED_OUT"]
    monkeypatch.setenv("QMS_LIS_APP_ENV", "production")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert client.get("/results/release").status_code == 401
    get_settings.cache_clear()


@pytest.mark.integration
def test_invalid_login_does_not_create_session(client: TestClient) -> None:
    response = client.post(
        "/login", data={"username": "missing", "password": "wrong"}
    )
    assert response.status_code == 401
    assert "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง" in response.text
