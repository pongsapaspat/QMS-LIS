from datetime import date
from decimal import Decimal

import pytest

from app.models.order import LabOrder
from app.models.result import Result
from app.models.specimen import Specimen
from app.models.test_catalog import ReferenceRange
from tests.integration.test_specimens import HEADERS, create_collection_order


@pytest.mark.integration
def test_async_save_keeps_unreceived_specimens_blocked_and_saves_after_receipt(
    client, db_session_factory,
):
    order_id, serum, _, _ = create_collection_order(client)
    page_url = f"/worklist/orders/{order_id}"
    page = client.get(page_url, headers=HEADERS)
    assert 'data-async-result-entry' in page.text
    assert 'role="alertdialog"' in page.text
    with db_session_factory() as session:
        item_id = next(item.id for item in session.get(LabOrder, order_id).items
                       if item.test_code == "GLU")
    headers = {**HEADERS, "X-Result-Entry": "true"}
    payload = {f"value_{item_id}": "95"}
    blocked = client.post(page_url, headers=headers, data=payload)
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "results may only be entered for received specimens"
    specimen = client.post("/api/v1/specimens", headers=HEADERS, json={
        "order_id": order_id, "specimen_type_id": serum,
    }).json()
    assert client.post(page_url, headers=headers, data=payload).status_code == 422
    with db_session_factory() as session:
        assert session.query(Result).count() == 0
    assert client.patch(f"/api/v1/specimens/{specimen['id']}/receipt",
                        headers=HEADERS, json={}).status_code == 200
    saved = client.post(page_url, headers=headers, data=payload)
    assert saved.status_code == 200
    assert saved.json() == {"redirect_url": "/worklist?queue=results&success=results-saved"}
    with db_session_factory() as session:
        result = session.query(Result).one()
        assert result.numeric_value == Decimal("95")
        assert result.status == "COMPLETED"
        session.get(Specimen, specimen['id']).status = "REJECTED"
        session.commit()
    correction = {f"value_{item_id}": "96", f"reason_{item_id}": "แก้ไขผล", f"edit_{item_id}": "on"}
    assert client.post(page_url, headers=headers, data=correction).status_code == 422
    with db_session_factory() as session:
        assert session.query(Result).one().numeric_value == Decimal("95")


@pytest.mark.integration
@pytest.mark.parametrize("case,expected", [
    ("unconfigured", "ยังไม่ได้กำหนดค่าอ้างอิงที่เปิดใช้งาน"),
    ("missing_birthdate", "ยังไม่มีวันเกิดผู้ป่วย"),
    ("unmatched", "ไม่มีช่วงอ้างอิงที่ตรงกับอายุและเพศ"),
    ("matched", "70 – 110"),
])
def test_reference_selection_explains_missing_values_and_snapshots_matching_range(
    client, db_session_factory, case, expected,
):
    order_id, serum, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        order.patient.date_of_birth = None if case == "missing_birthdate" else date(1990, 1, 1)
        item = next(item for item in order.items if item.test_code == "GLU")
        item_id = item.id
        if case != "unconfigured":
            session.add(ReferenceRange(
                test_id=item.lab_test_id, sex="ALL", minimum_age=0,
                maximum_age=1 if case == "unmatched" else 150,
                age_unit="YEARS", lower_value=Decimal("70"), upper_value=Decimal("110"),
            ))
        session.commit()
    collected = client.post("/api/v1/specimens", headers=HEADERS, json={
        "order_id": order_id, "specimen_type_id": serum,
    }).json()
    assert client.patch(
        f"/api/v1/specimens/{collected['id']}/receipt", headers=HEADERS, json={}
    ).status_code == 200
    page = client.get(f"/worklist/orders/{order_id}", headers=HEADERS)
    assert page.status_code == 200
    assert expected in page.context["entry_metadata"][item_id]["reference_text"]
    saved = client.post(f"/api/v1/results/orders/{order_id}", headers=HEADERS, json={
        "items": [{"order_item_id": item_id, "numeric_value": "95", "complete": True}],
    })
    assert saved.status_code == 200, saved.text
    snapshot = saved.json()[0]["reference_range_snapshot"]
    assert bool(snapshot) == (case == "matched")
    if snapshot:
        assert Decimal(snapshot["lower_value"]) == 70
        assert Decimal(snapshot["upper_value"]) == 110


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
