import pytest
from fastapi.testclient import TestClient

from tests.integration.test_specimens import ADMIN_HEADERS, HEADERS, create_collection_order

SUPERVISOR = {"X-Role": "LAB_SUPERVISOR", "X-Actor": "panel-reviewer"}


@pytest.mark.integration
@pytest.mark.parametrize("kind,count", [("CBC", 5), ("UA", 18)])
def test_panel_partial_completion_review_release_and_report(
    client: TestClient, kind: str, count: int
):
    original_id, serum, urine, _ = create_collection_order(client)
    original = client.get(f"/api/v1/orders/{original_id}", headers=HEADERS).json()
    specimen_type = serum if kind == "CBC" else urine
    test = client.post(
        "/api/v1/tests",
        headers=ADMIN_HEADERS,
        json={
            "code": kind,
            "name_th": kind,
            "name_en": kind,
            "category_id": 1,
            "department_id": 1,
            "specimen_type_id": specimen_type,
            "current_price": "100",
            "tat_minutes": 30,
            "result_type": kind,
        },
    )
    assert test.status_code == 201, test.text
    order = client.post(
        "/api/v1/orders",
        headers=HEADERS,
        json={
            "patient_id": original["patient_id"],
            "test_ids": [test.json()["id"]],
        },
    )
    assert order.status_code == 201
    order_id = order.json()["id"]
    collected = client.post(
        "/api/v1/specimens",
        headers=HEADERS,
        json={
            "order_id": order_id,
            "specimen_type_id": specimen_type,
        },
    )
    assert collected.status_code == 201
    assert (
        client.patch(
            f"/api/v1/specimens/{collected.json()['id']}/receipt", headers=HEADERS, json={}
        ).status_code
        == 200
    )
    context_url = f"/api/v1/results/orders/{order_id}"
    item = client.get(context_url, headers=HEADERS).json()["items"][0]
    assert len(item["parameters"]) == count
    item_id = item["order_item_id"]
    first = item["parameters"][0]
    first_value = "12" if kind == "CBC" else "Yellow"
    payload = {"order_item_id": item_id, "parameter_values": {first["code"]: first_value}}
    saved = client.post(context_url, headers=HEADERS, json={"items": [payload]})
    assert saved.status_code == 200, saved.text
    result_id = saved.json()[0]["id"]
    assert saved.json()[0]["status"] == "IN_PROGRESS"
    payload["complete"] = True
    assert client.post(context_url, headers=HEADERS, json={"items": [payload]}).status_code == 422
    assert (
        client.patch(f"/api/v1/results/{result_id}/verify", headers=SUPERVISOR, json={}).status_code
        == 422
    )
    entry = client.get(f"/worklist/orders/{order_id}", headers=HEADERS)
    assert f'name="parameter_{item_id}_{first["code"]}"' in entry.text
    values = {
        p["code"]: p["lower"] if p["kind"] == "NUMERIC" else p["reference"] or "None seen"
        for p in item["parameters"]
    }
    # Web form completes a panel only when every parameter has been entered.
    response = client.post(
        f"/worklist/orders/{order_id}",
        headers=HEADERS,
        data={f"parameter_{item_id}_{code}": value for code, value in values.items()},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    result = client.get(context_url, headers=HEADERS).json()["items"][0]["result"]
    assert result["status"] == "COMPLETED"
    assert len(result["parameter_results"]) == count
    review = client.get(f"/results/verification/orders/{order_id}", headers=SUPERVISOR)
    assert review.status_code == 200
    for p in item["parameters"]:
        assert p["name"] in review.text
    assert review.text.count(">Verify result</button>") == 1
    assert (
        client.patch(
            f"/api/v1/results/{result_id}/verification-rejection",
            headers=SUPERVISOR,
            json={"reason": "Check the panel"},
        ).status_code
        == 200
    )
    corrected_values = dict(values)
    corrected_values[first["code"]] = "12" if kind == "CBC" else "Straw"
    correction_form = {
        f"parameter_{item_id}_{code}": value for code, value in corrected_values.items()
    }
    correction_form[f"edit_{item_id}"] = "on"
    assert (
        client.post(
            f"/worklist/orders/{order_id}",
            headers=HEADERS,
            data=correction_form,
            follow_redirects=False,
        ).status_code
        == 422
    )
    correction_form[f"reason_{item_id}"] = "Panel rechecked"
    assert (
        client.post(
            f"/worklist/orders/{order_id}",
            headers=HEADERS,
            data=correction_form,
            follow_redirects=False,
        ).status_code
        == 303
    )
    revised = client.get(f"/results/verification/orders/{order_id}", headers=SUPERVISOR)
    revision = revised.context["context"]["results"][0]["revisions"][-1]
    assert revision["modification_reason"] == "Panel rechecked"
    assert revision["previous_value"]["parameter_values"] == values
    assert revision["new_value"]["parameter_values"] == corrected_values
    assert (
        client.patch(f"/api/v1/results/{result_id}/verify", headers=SUPERVISOR, json={}).status_code
        == 200
    )
    released = client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={})
    assert released.status_code == 200, released.text
    report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR)
    assert report.status_code == 200
    for p in item["parameters"]:
        assert p["name"] in report.text
    pdf = client.get(f"/results/reports/orders/{order_id}/pdf", headers=SUPERVISOR)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")
    assert (
        client.post(
            context_url,
            headers=HEADERS,
            json={
                "items": [
                    {
                        **payload,
                        "parameter_values": values,
                    }
                ]
            },
        ).status_code
        == 422
    )
