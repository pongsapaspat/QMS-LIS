from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_home_page_is_available() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "QMS-LIS" in response.text


def test_root_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(response.headers["x-request-id"]) == 36


def test_versioned_health_check() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_is_generated() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "QMS-LIS"
    assert "/api/v1/health" in schema["paths"]
