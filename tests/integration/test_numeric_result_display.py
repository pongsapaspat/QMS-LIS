from decimal import Decimal

import pytest

from app.models.result import Result
from tests.integration.test_result_verification_release import (
    ENTRY_HEADERS,
    SUPERVISOR_HEADERS,
    _completed_order,
)


@pytest.mark.integration
def test_numeric_display_rounds_without_changing_results_or_edit_fields(
    client, db_session_factory,
):
    order_id, results = _completed_order(client)
    target = results[0]
    edited = client.put(f'/api/v1/results/{target["id"]}', headers=ENTRY_HEADERS, json={
        "order_item_id": target["order_item_id"], "numeric_value": "89.125",
        "complete": True, "modification_reason": "Precision check",
    })
    assert edited.status_code == 200
    assert Decimal(edited.json()["numeric_value"]) == Decimal("89.125")
    entry = client.get(f"/worklist/orders/{order_id}", headers=ENTRY_HEADERS)
    assert 'value="89.125"' in entry.text
    assert 'value="89.125000"' not in entry.text
    review = client.get(f"/results/verification/orders/{order_id}", headers=SUPERVISOR_HEADERS)
    assert review.context["context"]["results"][0]["result_value"] == "89.13"
    for result in results:
        assert client.patch(f'/api/v1/results/{result["id"]}/verify',
                            headers=SUPERVISOR_HEADERS, json={}).status_code == 200
    preview = client.get(f"/results/release/orders/{order_id}", headers=SUPERVISOR_HEADERS)
    assert preview.context["context"]["results"][0]["result_value"] == "89.13"
    assert client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR_HEADERS,
                        json={}).status_code == 200
    report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR_HEADERS)
    assert report.context["context"]["results"][0]["result_value"] == "89.13"
    with db_session_factory() as session:
        stored = session.get(Result, target["id"])
        assert stored.numeric_value == Decimal("89.125")
        assert stored.revisions[-1].new_value["numeric_value"] == "89.125"
