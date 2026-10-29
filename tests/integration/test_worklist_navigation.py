from fastapi.testclient import TestClient


def test_home_contains_worklist_card_and_navigation(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Laboratory Worklist" in response.text
    assert "รายการงานห้องปฏิบัติการ" in response.text
    assert "Worklist | รายการงานตรวจ" in response.text
    assert response.text.count('href="/worklist"') == 2


def test_authorized_laboratory_user_can_open_worklist(client: TestClient) -> None:
    response = client.get(
        "/worklist",
        headers={"X-Role": "LAB_TECH", "X-Actor": "navigation-test-tech"},
    )

    assert response.status_code == 200
    assert 'href="/worklist"' in response.text
    assert 'class="nav-link active"' in response.text
    assert 'aria-current="page"' in response.text
