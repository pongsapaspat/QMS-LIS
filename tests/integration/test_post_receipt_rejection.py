import pytest

from tests.integration.test_specimens import HEADERS, create_collection_order


@pytest.mark.integration
@pytest.mark.parametrize("has_result", [False, True])
def test_reject_received_only_before_result_entry(client, has_result):
    order_id, serum_id, _, _ = create_collection_order(client)
    specimen = client.post(
        "/api/v1/specimens",
        headers=HEADERS,
        json={"order_id": order_id, "specimen_type_id": serum_id},
    ).json()
    specimen_id = specimen["id"]
    receipt = client.patch(
        f"/api/v1/specimens/{specimen_id}/receipt", headers=HEADERS, json={}
    )
    assert receipt.status_code == 200
    if has_result:
        item = client.get(f"/api/v1/results/orders/{order_id}", headers=HEADERS).json()["items"][0]
        assert (
            client.post(
                f"/api/v1/results/orders/{order_id}",
                headers=HEADERS,
                json={
                    "items": [
                        {
                            "order_item_id": item["order_item_id"],
                            "numeric_value": "1",
                            "complete": False,
                        }
                    ]
                },
            ).status_code
            == 200
        )
    page = client.get(f"/specimens/receiving/{specimen_id}", headers=HEADERS)
    assert page.status_code == 200
    assert ("Reject / ขอเก็บใหม่" in page.text) == (not has_result)
    rejected = client.patch(
        f"/api/v1/specimens/{specimen_id}/rejection",
        headers=HEADERS,
        json={"rejection_reason_code": "HEMOLYZED"},
    )
    assert rejected.status_code == (422 if has_result else 200)
    if not has_result:
        assert rejected.json()["received_at"] == receipt.json()["received_at"]
        assert rejected.json()["received_by"] == receipt.json()["received_by"]
        assert rejected.json()["status"] == "REJECTED"
        assert (
            client.patch(
                f"/api/v1/specimens/{specimen_id}/rejection",
                headers=HEADERS,
                json={"rejection_reason_code": "HEMOLYZED"},
            ).status_code
            == 422
        )
        replacement = client.post(
            "/api/v1/specimens",
            headers=HEADERS,
            json={
                "order_id": order_id,
                "specimen_type_id": serum_id,
                "replaces_specimen_id": specimen_id,
            },
        )
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["accession_number"] != specimen["accession_number"]
