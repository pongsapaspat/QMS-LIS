import re

import pytest

from tests.integration.test_panel_results import SUPERVISOR
from tests.integration.test_specimens import ADMIN_HEADERS, HEADERS, create_collection_order


@pytest.mark.integration
def test_influenza_dropdowns_require_both_results_and_keep_them_separate(client):
    original_id, serum_id, _, _ = create_collection_order(client)
    original = client.get(f"/api/v1/orders/{original_id}", headers=HEADERS).json()
    created = client.post(
        "/api/v1/tests", headers=ADMIN_HEADERS,
        json={
            "code": "FLU-AB", "name_th": "Influenza A/B", "name_en": "Influenza A/B",
            "category_id": 1, "department_id": 1, "specimen_type_id": serum_id,
            "current_price": "100", "tat_minutes": 30, "result_type": "INFLUENZA_AB",
        },
    )
    assert created.status_code == 201, created.text
    assert [p["name"] for p in created.json()["parameters"]] == ["Influenza A", "Influenza B"]
    catalog = client.get(f'/test-catalog/{created.json()["id"]}', headers=ADMIN_HEADERS)
    assert catalog.text.count("DROPDOWN") == 2
    assert "INFLUENZA_AB" in client.get("/test-catalog/new", headers=ADMIN_HEADERS).text
    order = client.post(
        "/api/v1/orders", headers=HEADERS,
        json={"patient_id": original["patient_id"], "test_ids": [created.json()["id"]]},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    collected = client.post(
        "/api/v1/specimens", headers=HEADERS,
        json={"order_id": order_id, "specimen_type_id": serum_id},
    )
    assert collected.status_code == 201, collected.text
    assert client.patch(
        f'/api/v1/specimens/{collected.json()["id"]}/receipt', headers=HEADERS, json={},
    ).status_code == 200
    context_url = f"/api/v1/results/orders/{order_id}"
    item = client.get(context_url, headers=HEADERS).json()["items"][0]
    item_id = item["order_item_id"]
    assert [p["code"] for p in item["parameters"]] == ["FLU_A", "FLU_B"]
    entry_url = f"/worklist/orders/{order_id}"
    entry = client.get(entry_url, headers=HEADERS)
    for code in ("FLU_A", "FLU_B"):
        dropdown = re.search(
            rf'<select[^>]*name="parameter_{item_id}_{code}"[^>]*>(.*?)</select>',
            entry.text, re.S,
        )
        assert dropdown is not None
        assert '<option value="" selected>' in dropdown.group(1)
        assert '<option value="Negative">' in dropdown.group(1)
        assert '<option value="Positive">' in dropdown.group(1)

    for values, complete in (
        ({"FLU_A": "Other", "FLU_B": "Negative"}, False),
        ({"FLU_A": "Positive", "UNKNOWN": "Negative"}, False),
        ({"FLU_A": "Positive"}, True),
    ):
        refused = client.post(
            context_url, headers=HEADERS,
            json={"items": [{
                "order_item_id": item_id, "parameter_values": values, "complete": complete,
            }]},
        )
        assert refused.status_code == 422, refused.text
    assert client.get(context_url, headers=HEADERS).json()["items"][0]["result"] is None

    partial = client.post(
        entry_url, headers=HEADERS, data={f"parameter_{item_id}_FLU_A": "Positive"},
        follow_redirects=False,
    )
    assert partial.status_code == 303, partial.text
    saved = client.get(context_url, headers=HEADERS).json()["items"][0]["result"]
    assert saved["status"] == "IN_PROGRESS"
    assert saved["parameter_values"].get("FLU_B", "") == ""
    result_id = saved["id"]
    assert client.patch(
        f"/api/v1/results/{result_id}/verify", headers=SUPERVISOR, json={},
    ).status_code == 422

    values = {"FLU_A": "Positive", "FLU_B": "Negative"}
    complete = client.post(
        entry_url, headers=HEADERS,
        data={f"parameter_{item_id}_{code}": value for code, value in values.items()},
        follow_redirects=False,
    )
    assert complete.status_code == 303, complete.text
    saved = client.get(context_url, headers=HEADERS).json()["items"][0]["result"]
    assert saved["status"] == "COMPLETED"
    assert saved["parameter_values"] == values
    review = client.get(f"/results/verification/orders/{order_id}", headers=SUPERVISOR)
    assert review.text.count(">Verify result</button>") == 1
    for row in review.context["context"]["results"][0]["parameters"]:
        assert row["value"] == values[row["code"]]
    assert client.patch(
        f"/api/v1/results/{result_id}/verify", headers=SUPERVISOR, json={},
    ).status_code == 200
    released = client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={})
    assert released.status_code == 200, released.text
    report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR)
    assert report.status_code == 200
    rows = report.context["context"]["results"][0]["parameters"]
    assert [(p["name"], p["value"]) for p in rows] == [
        ("Influenza A", "Positive"), ("Influenza B", "Negative"),
    ]
    for name, value in (("Influenza A", "Positive"), ("Influenza B", "Negative")):
        assert re.search(rf"<tr><td>{name}</td><td>{value}", report.text)
