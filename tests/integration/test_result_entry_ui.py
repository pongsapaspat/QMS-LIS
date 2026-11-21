from datetime import date
from decimal import Decimal

import pytest

from app.models.order import LabOrder
from app.models.result import Result
from app.models.test_catalog import ReferenceRange
from tests.integration.test_specimens import HEADERS, create_collection_order


@pytest.mark.integration
@pytest.mark.parametrize("value,critical", [("95", False), ("40", True), ("400", True)])
def test_entry_uses_matching_reference_and_keeps_critical_acknowledgement_enforced(
    client,
    db_session_factory,
    value,
    critical,
):
    order_id, serum, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        order.patient.date_of_birth = date(1990, 1, 1)
        item = next(item for item in order.items if item.test_code == "GLU")
        item_id = item.id
        session.add(
            ReferenceRange(
                test_id=item.lab_test_id,
                sex="ALL",
                minimum_age=0,
                maximum_age=150,
                age_unit="YEARS",
                lower_value=Decimal("70"),
                upper_value=Decimal("110"),
                lower_critical=Decimal("40"),
                upper_critical=Decimal("400"),
                display_text="70–110",
            )
        )
        session.commit()
    collected = client.post(
        "/api/v1/specimens", headers=HEADERS, json={"order_id": order_id, "specimen_type_id": serum}
    ).json()
    client.patch(f"/api/v1/specimens/{collected['id']}/receipt", headers=HEADERS, json={})
    page_url = f"/worklist/orders/{order_id}"
    page = client.get(page_url, headers=HEADERS)
    assert page.status_code == 200
    assert "Acknowledge critical value" not in page.text
    assert "รับทราบค่าวิกฤตแล้ว" in page.text
    assert "70–110" in page.text
    meta = page.context["entry_metadata"][item_id]
    assert Decimal(meta["lower_critical"]) == 40
    assert Decimal(meta["upper_critical"]) == 400
    assert not meta["critical"]
    payload = {"items": [{"order_item_id": item_id, "numeric_value": value, "complete": True}]}
    url = f"/api/v1/results/orders/{order_id}"
    if critical:
        refused = client.post(url, headers=HEADERS, json=payload)
        assert refused.status_code == 422
        assert "acknowledgement" in refused.text
    payload["items"][0]["acknowledge_critical"] = critical
    saved = client.post(url, headers=HEADERS, json=payload)
    assert saved.status_code == 200, saved.text
    page = client.get(page_url, headers=HEADERS)
    assert page.context["entry_metadata"][item_id]["critical"] == critical
    with db_session_factory() as session:
        result = session.get(Result, saved.json()[0]["id"])
        assert bool(result.critical_acknowledged_at) == critical
