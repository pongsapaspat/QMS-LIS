from datetime import UTC, datetime

from app.models import LabOrder, SpecimenType
from tests.integration.test_collection_rooms import room_order
from tests.integration.test_specimens import HEADERS, create_collection_order

RECEPTION = {"X-Role": "RECEPTION", "X-Actor": "tracking-reception"}
SUPERVISOR = {"X-Role": "LAB_SUPERVISOR", "X-Actor": "tracking-supervisor"}


def test_tracking_search_default_dates_and_pagination(client, db_session_factory, monkeypatch):
    order_id, *_ = create_collection_order(client)
    # Today begins at 17:00 UTC on the preceding day in the app's Bangkok timezone.
    monkeypatch.setattr(
        "app.web.routes.orders.utc_now", lambda: datetime(2026, 11, 22, 5, tzinfo=UTC)
    )
    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        order.ordered_at = datetime(2026, 11, 21, 12, tzinfo=UTC)
        patient_id = order.patient_id
        for i in range(27):
            session.add(LabOrder(
                order_number=f"TRACK-{i:02}", patient_id=patient_id, created_by="fixture",
                status="RELEASED", ordered_at=datetime(2026, 11, 21, 17, tzinfo=UTC)
                if i < 26 else datetime(2026, 11, 21, 16, 59, tzinfo=UTC),
            ))
        session.commit()
        hn, number = order.patient.hn, order.order_number

    first = client.get("/orders", headers=RECEPTION)
    assert first.status_code == 200
    assert first.context["total"] == 27
    assert len(first.context["rows"]) == 25
    page2 = client.get("/orders", headers=RECEPTION, params={"page": 2})
    assert len(page2.context["rows"]) == 2
    assert number in page2.text and "TRACK-00" in page2.text
    for search in (hn, "Specimen Patient"):
        result = client.get("/orders", headers=RECEPTION, params={"search": search})
        assert result.context["total"] == 27
    historical = client.get("/orders", headers=RECEPTION, params={
        "date_from": "2026-11-21", "date_to": "2026-11-21", "order_status": "RELEASED",
    })
    assert historical.context["total"] == 1
    assert "TRACK-26" in historical.text
    all_dates = client.get("/orders", headers=RECEPTION, params={
        "all_dates": "true", "search": "TRACK-26",
    })
    assert all_dates.context["total"] == 1
    invalid = client.get("/orders", headers=RECEPTION, params={
        "date_from": "2026-11-23", "date_to": "2026-11-22",
    })
    assert invalid.status_code == 422
    assert "กรุณาตรวจสอบช่วงวันที่" in invalid.text


def test_tracking_progress_and_links_respect_roles(client, db_session_factory):
    order, types = room_order(client, db_session_factory)
    order_id = order["id"]
    detail_url = f"/orders/{order_id}"
    for headers in (RECEPTION, HEADERS, SUPERVISOR):
        home = client.get("/", headers=headers)
        assert ">รายการ Order</a>" in home.text
        listing = client.get("/orders", headers=headers)
        assert listing.status_code == 200
        progress = listing.context["rows"][0]["progress"]
        assert (progress.required, progress.collected, progress.internal, progress.outlab) == (
            6, 0, 6, 1,
        )
    assert "Order Tracking" in client.get("/", headers=HEADERS).text
    created = client.post("/api/v1/specimens", headers=HEADERS, json={
        "order_id": order_id, "specimen_type_id": types["serum"],
    }).json()
    specimen_id = created["id"]
    tech = client.get(detail_url, headers=HEADERS)
    assert f"/specimens/receiving/{specimen_id}" in tech.text
    assert "collection_room=BLOOD" in tech.text
    assert "/outlab/" in tech.text
    assert client.patch(
        f"/api/v1/specimens/{specimen_id}/receipt", headers=HEADERS, json={}
    ).status_code == 200
    tech = client.get(detail_url, headers=HEADERS)
    assert f"/worklist/orders/{order_id}" in tech.text
    result_url = f"/api/v1/results/orders/{order_id}"
    item = client.get(result_url, headers=HEADERS).json()["items"][0]
    saved = client.post(result_url, headers=HEADERS, json={"items": [{
        "order_item_id": item["order_item_id"], "numeric_value": "91.234567", "complete": True,
    }]})
    assert saved.status_code == 200, saved.text
    supervisor = client.get(detail_url, headers=SUPERVISOR)
    assert f"/results/verification/orders/{order_id}" in supervisor.text
    assert "/outlab/" in supervisor.text
    assert supervisor.context["progress"].awaiting_verification == 1
    assert supervisor.context["progress"].received == 1
    reception = client.get(detail_url, headers=RECEPTION)
    assert reception.status_code == 200
    assert "Verify แล้ว 0/6" in reception.text
    for secret in (created["accession_number"], "91.234567", "Reference lab"):
        assert secret not in reception.text
    for path in (
        "/outlab/", f"{detail_url}/specimens", f"/worklist/orders/{order_id}",
        f"/results/verification/orders/{order_id}", f"/results/reports/orders/{order_id}",
    ):
        assert path not in reception.text
    assert client.get(f"/results/reports/orders/{order_id}", headers=RECEPTION).status_code == 403


def test_rejected_specimen_is_counted_in_its_collection_room(client, db_session_factory):
    order_id, serum, *_ = create_collection_order(client)
    with db_session_factory() as session:
        session.get(SpecimenType, serum).collection_room = "BLOOD"
        session.commit()
    specimen = client.post("/api/v1/specimens", headers=HEADERS, json={
        "order_id": order_id, "specimen_type_id": serum,
    }).json()
    rejected = client.patch(
        f"/api/v1/specimens/{specimen['id']}/rejection", headers=HEADERS,
        json={"rejection_reason_code": "CLOTTED"},
    )
    assert rejected.status_code == 200
    page = client.get(f"/orders/{order_id}", headers=HEADERS)
    progress = page.context["progress"]
    assert (progress.required, progress.collected, progress.recollection) == (2, 0, 1)
    assert "เจาะเลือด · 1" in page.text
    assert "CLOTTED" in page.text
