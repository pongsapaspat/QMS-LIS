import re
from html import unescape

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
    assert 'href="/worklist?queue=results"' in response.text
    assert 'class="nav-link active"' in response.text
    assert 'aria-current="page"' in response.text


def test_collection_filter_form_submits_to_html_page_not_api(client: TestClient) -> None:
    headers = {"X-Role": "LAB_TECH", "X-Actor": "collection-filter-test"}
    page = client.get("/worklist?task_type=ORDER_PENDING_COLLECTION", headers=headers)
    action = re.search(r'<form[^>]*action="([^"]+)"', page.text).group(1)
    assert action == "http://testserver/worklist"
    clear_url = re.search(r'href="([^"]+)">ล้าง</a>', page.text).group(1)
    assert unescape(clear_url) == (
        "http://testserver/worklist?task_type=ORDER_PENDING_COLLECTION&collection_room=all"
    )
    for value in ("all", "initial", "recollection"):
        submitted = client.get(action, headers=headers, params={
            "task_type": "ORDER_PENDING_COLLECTION", "collection_filter": value,
        })
        assert submitted.status_code == 200
        assert submitted.headers["content-type"].startswith("text/html")
        assert f'<option value="{value}" selected>' in submitted.text
        assert 'name="collection_filter"' in submitted.text
    client.get(action, headers=headers, params={
        "task_type": "ORDER_PENDING_COLLECTION", "collection_room": "BLOOD",
        "collection_filter": "recollection",
    })
    cleared = client.get(unescape(clear_url), headers=headers)
    assert cleared.context["filters"]["collection_room"] == "all"
    assert cleared.context["filters"]["collection_filter"] == "all"
