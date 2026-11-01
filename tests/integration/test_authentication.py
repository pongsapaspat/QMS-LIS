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
    set_cookie = login.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=28800" in set_cookie
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


@pytest.mark.integration
def test_navigation_matches_logged_in_user_role(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    with db_session_factory() as session:
        for username, role in (
            ("admin", "ADMIN"),
            ("tech", "LAB_TECH"),
            ("supervisor", "LAB_SUPERVISOR"),
            ("reception", "RECEPTION"),
        ):
            session.add(
                User(
                    username=username,
                    password_hash=hash_password("password"),
                    role=role,
                    display_name=username,
                )
            )
        session.commit()

    expected_links = {
        "admin": [
            'href="/patients"',
            'href="/test-catalog"',
            'href="/users"',
            'href="/audit-logs"',
            'href="/results/release"',
        ],
        "tech": [
            'href="/orders/new"',
            'href="/worklist"',
            'href="/results/verification"',
            "/results/reports",
        ],
        "supervisor": [
            'href="/orders/new"',
            'href="/worklist"',
            'href="/results/release"',
            'href="/audit-logs"',
        ],
        "reception": ['href="/orders/new"'],
    }
    hidden_links = {
        "tech": [
            'href="/patients"',
            'href="/test-catalog"',
            'href="/users"',
            'href="/audit-logs"',
            'href="/results/release"',
        ],
        "supervisor": ['href="/patients"', 'href="/test-catalog"', 'href="/users"'],
        "reception": [
            'href="/patients"',
            'href="/test-catalog"',
            'href="/worklist"',
            'href="/results/verification"',
        ],
    }
    for username in expected_links:
        assert client.post(
            "/login",
            data={"username": username, "password": "password"},
            follow_redirects=False,
        ).status_code == 303
        page = client.get("/")
        assert page.status_code == 200
        for link in expected_links[username]:
            assert link in page.text
        for link in hidden_links.get(username, []):
            assert link not in page.text
        assert client.post("/logout", follow_redirects=False).status_code == 303

    client.post("/login", data={"username": "tech", "password": "password"})
    forbidden = client.get("/test-catalog", headers={"Accept": "text/html"})
    assert forbidden.status_code == 403
    assert "ไม่มีสิทธิ์เข้าถึงหน้านี้" in forbidden.text


@pytest.mark.integration
def test_user_can_change_own_password_and_audit_it(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    with db_session_factory() as session:
        session.add(
            User(
                username="tech",
                password_hash=hash_password("old-password"),
                role="LAB_TECH",
                display_name="Tech",
            )
        )
        session.commit()

    assert (
        client.post(
            "/login",
            data={"username": "tech", "password": "old-password"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    changed = client.post(
        "/change-password",
        data={
            "current_password": "old-password",
            "new_password": "new-password",
            "confirm_password": "new-password",
        },
    )
    assert changed.status_code == 200
    assert "เปลี่ยนรหัสผ่านเรียบร้อยแล้ว" in changed.text
    client.post("/logout")
    assert (
        client.post(
            "/login", data={"username": "tech", "password": "old-password"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/login",
            data={"username": "tech", "password": "new-password"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    with db_session_factory() as session:
        assert session.query(AuditLog).filter_by(event_type="USER_PASSWORD_CHANGED").count() == 1
