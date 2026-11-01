import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
@pytest.mark.parametrize(
    ("path", "headers", "expected_text"),
    [
        (
            "/worklist?task_type=&department_id=&priority=&status=&search=",
            {"X-Role": "LAB_TECH", "X-Actor": "filter-tech"},
            "Laboratory Worklist",
        ),
        (
            "/test-catalog?search=&category_id=&department_id=&specimen_type_id="
            "&result_type=&is_active=true",
            {"X-Role": "ADMIN", "X-Actor": "filter-admin"},
            "Test Catalog",
        ),
        (
            "/results/verification?department_id=&priority=&search=",
            {"X-Role": "LAB_TECH", "X-Actor": "filter-tech"},
            "Verification Queue",
        ),
        (
            "/results/release?priority=&search=",
            {"X-Role": "LAB_SUPERVISOR", "X-Actor": "filter-supervisor"},
            "Release Queue",
        ),
    ],
)
def test_web_filter_forms_accept_unselected_controls(
    client: TestClient,
    path: str,
    headers: dict[str, str],
    expected_text: str,
) -> None:
    response = client.get(path, headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert expected_text in response.text
