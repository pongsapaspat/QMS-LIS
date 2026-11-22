import pytest
from sqlalchemy import select

from app.models import AuditLog, LabOrder, Specimen, SpecimenType
from tests.integration.test_specimens import ADMIN_HEADERS, HEADERS, create_collection_order

QUEUE = "/worklist?task_type=ORDER_PENDING_COLLECTION"


def room_order(client, db_session_factory):
    original_id, serum, urine, plasma = create_collection_order(client)
    original = client.get(f"/api/v1/orders/{original_id}", headers=HEADERS).json()
    for type_id, room in ((serum, "BLOOD"), (plasma, "BLOOD"), (urine, "URINE_STOOL")):
        changed = client.patch(
            f"/api/v1/specimen-types/{type_id}", headers=ADMIN_HEADERS,
            json={"collection_room": room, "reason": "Configure collection station"},
        )
        assert changed.status_code == 200, changed.text
    types = {"serum": serum, "urine": urine, "plasma": plasma}
    for code, name, room in (("STOOL", "Stool", "URINE_STOOL"), ("SWAB", "Swab", "SWAB")):
        created = client.post(
            "/api/v1/specimen-types", headers=ADMIN_HEADERS,
            json={"code": code, "name_th": name, "name_en": name, "collection_room": room},
        )
        assert created.status_code == 201, created.text
        types[code.lower()] = created.json()["id"]
    test_ids = [item["lab_test_id"] for item in original["items"]]
    for code, type_id, outlab in (
        ("PLASMA-T", plasma, False), ("SWAB-T", types["swab"], False),
        ("STOOL-T", types["stool"], False), ("OUT-STOOL", types["stool"], True),
    ):
        created = client.post(
            "/api/v1/tests", headers=ADMIN_HEADERS,
            json={
                "code": code, "name_th": code, "name_en": code, "category_id": 1,
                "department_id": 1, "specimen_type_id": type_id, "current_price": "100",
                "tat_minutes": 30, "result_type": "TEXT", "is_outlab": outlab,
                "outlab_lab_name": "Reference lab" if outlab else None,
            },
        )
        assert created.status_code == 201, created.text
        test_ids.append(created.json()["id"])
    order = client.post(
        "/api/v1/orders", headers=HEADERS,
        json={"patient_id": original["patient_id"], "test_ids": test_ids},
    )
    assert order.status_code == 201, order.text
    with db_session_factory() as session:
        session.get(LabOrder, original_id).status = "CANCELLED"
        session.commit()
    return order.json(), types


@pytest.mark.integration
def test_room_queue_preferences_and_collection_keep_other_rooms_pending(client, db_session_factory):
    order, types = room_order(client, db_session_factory)
    order_id = order["id"]
    for room, expected in (
        ("BLOOD", {"Serum", "Plasma"}), ("URINE_STOOL", {"Urine", "Stool"}),
        ("SWAB", {"Swab"}),
    ):
        page = client.get(f"{QUEUE}&collection_room={room}", headers=HEADERS)
        assert page.status_code == 200
        assert page.context["worklist"].total == 1
        task = page.context["worklist"].items[0]
        assert set(task.pending_specimens) == expected
        assert task.next_action_url.endswith(f"?collection_room={room}")
        remembered = client.get(QUEUE, headers=HEADERS)
        assert remembered.context["filters"]["collection_room"] == room
    assert client.cookies.get("qms_lis_collection_room") == "SWAB"
    # The workstation preference does not narrow the separate result-entry queue.
    results = client.get("/worklist?queue=results", headers=HEADERS)
    assert results.context["filters"]["collection_room"] == "all"
    detail = client.get(f"/orders/{order_id}/specimens?collection_room=BLOOD", headers=HEADERS)
    assert {r.specimen_type_id for r in detail.context["requirements"]} == {
        types["serum"], types["plasma"],
    }
    assert "UPRO" not in detail.text and "SWAB-T" not in detail.text
    wrong_room = client.post(
        f'/orders/{order_id}/specimens/{types["urine"]}/collect?collection_room=BLOOD',
        headers=HEADERS, data={"collection_group": "INTERNAL"}, follow_redirects=False,
    )
    assert wrong_room.status_code == 422
    assert wrong_room.context["collection_room"] == "BLOOD"
    with db_session_factory() as session:
        assert list(session.scalars(select(Specimen))) == []
    for type_id in (types["serum"], types["plasma"]):
        saved = client.post(
            f"/orders/{order_id}/specimens/{type_id}/collect?collection_room=BLOOD",
            headers=HEADERS, data={"collection_group": "INTERNAL"}, follow_redirects=False,
        )
        assert saved.status_code == 303, saved.text
        assert "collection_room=BLOOD" in saved.headers["location"]
    assert client.get(
        f"{QUEUE}&collection_room=BLOOD", headers=HEADERS
    ).context["worklist"].total == 0
    assert client.get(
        f"{QUEUE}&collection_room=URINE_STOOL", headers=HEADERS
    ).context["worklist"].total == 1
    assert client.get(
        f"{QUEUE}&collection_room=SWAB", headers=HEADERS
    ).context["worklist"].total == 1
    with db_session_factory() as session:
        assert session.get(LabOrder, order_id).status == "ORDERED"
        assert len(list(session.scalars(select(Specimen)))) == 2
    outlab_detail = client.get(
        f"/orders/{order_id}/specimens?collection_room=URINE_STOOL", headers=HEADERS
    )
    stool = [r for r in outlab_detail.context["requirements"]
             if r.specimen_type_id == types["stool"]]
    assert len(stool) == 2
    assert sum(r.collection_group == "INTERNAL" for r in stool) == 1
    assert any(r.collection_group.startswith("OUTLAB-") for r in stool)
    for requirement in outlab_detail.context["requirements"]:
        saved = client.post(
            "/api/v1/specimens?collection_room=URINE_STOOL", headers=HEADERS,
            json={"order_id": order_id, "specimen_type_id": requirement.specimen_type_id,
                  "collection_group": requirement.collection_group},
        )
        assert saved.status_code == 201, saved.text
    assert client.get(
        f"{QUEUE}&collection_room=URINE_STOOL", headers=HEADERS
    ).context["worklist"].total == 0
    assert client.get(
        f"{QUEUE}&collection_room=SWAB", headers=HEADERS
    ).context["worklist"].total == 1
    cleared = client.get(f"{QUEUE}&collection_room=all", headers=HEADERS)
    assert cleared.context["filters"]["collection_room"] == "all"
    assert client.get(QUEUE, headers=HEADERS).context["filters"]["collection_room"] == "all"


@pytest.mark.integration
def test_recollection_and_historic_specimen_type_stay_in_their_room(client, db_session_factory):
    order, types = room_order(client, db_session_factory)
    order_id = order["id"]
    specimen = client.post(
        "/api/v1/specimens", headers=HEADERS,
        json={"order_id": order_id, "specimen_type_id": types["serum"]},
    ).json()
    assert client.patch(
        f'/api/v1/specimens/{specimen["id"]}/rejection', headers=HEADERS,
        json={"rejection_reason_code": "HEMOLYZED"},
    ).status_code == 200
    blood = client.get(
        f"{QUEUE}&collection_room=BLOOD&collection_filter=recollection&page=1", headers=HEADERS
    )
    assert blood.context["worklist"].total == 1
    assert blood.context["worklist"].items[0].current_specimen_status == "REJECTED"
    urine_initial = client.get(
        f"{QUEUE}&collection_room=URINE_STOOL&collection_filter=initial", headers=HEADERS
    )
    assert urine_initial.context["worklist"].total == 1
    assert client.get(
        f"{QUEUE}&collection_room=URINE_STOOL&collection_filter=recollection", headers=HEADERS
    ).context["worklist"].total == 0
    # Catalog changes must not reroute an existing rejected tube to another room.
    with db_session_factory() as session:
        current_order = session.get(LabOrder, order_id)
        for item in current_order.items:
            if item.test_code in {"GLU", "CREA"}:
                item.lab_test.specimen_type_id = types["urine"]
        session.commit()
    blood = client.get(
        f"{QUEUE}&collection_room=BLOOD&collection_filter=recollection", headers=HEADERS
    )
    assert "Serum" in blood.context["worklist"].items[0].pending_specimens
    requirements = client.get(
        f"/orders/{order_id}/specimens?collection_room=BLOOD", headers=HEADERS
    ).context["requirements"]
    assert any(r.specimen and r.specimen.id == specimen["id"] for r in requirements)
    recollected = client.post(
        f'/orders/{order_id}/specimens/{types["serum"]}/collect?collection_room=BLOOD',
        headers=HEADERS,
        data={"collection_group": "INTERNAL", "replaces_specimen_id": specimen["id"]},
        follow_redirects=False,
    )
    assert recollected.status_code == 303, recollected.text


@pytest.mark.integration
def test_room_settings_are_validated_audited_and_unknown_types_remain_visible(
    client, db_session_factory
):
    order_id, serum, _, _ = create_collection_order(client)
    assert client.patch(
        f"/api/v1/specimen-types/{serum}", headers=ADMIN_HEADERS,
        json={"collection_room": "INVALID"},
    ).status_code == 422
    assert client.get(f"{QUEUE}&collection_room=INVALID", headers=HEADERS).status_code == 422
    client.cookies.set("qms_lis_collection_room", "INVALID")
    assert client.get(QUEUE, headers=HEADERS).context["worklist"].total == 1
    assert client.get(
        f"{QUEUE}&collection_room=BLOOD", headers=HEADERS
    ).context["worklist"].total == 0
    assert client.get(
        f"{QUEUE}&collection_room=all", headers=HEADERS
    ).context["worklist"].total == 1
    settings = f"/test-catalog/specimen-types/{serum}/edit"
    assert client.get(settings, headers=HEADERS).status_code == 403
    assert client.post(settings, headers=HEADERS, data={}).status_code == 403
    saved = client.post(
        settings, headers=ADMIN_HEADERS, follow_redirects=False,
        data={"name_th": "Serum Thai", "name_en": "Serum", "is_active": "on",
              "collection_room": "BLOOD", "reason": "Assign draw station"},
    )
    assert saved.status_code == 303, saved.text
    assert client.get(
        f"{QUEUE}&collection_room=BLOOD", headers=HEADERS
    ).context["worklist"].total == 1
    # Submitting an older form without the new field keeps the current assignment.
    assert client.post(
        settings, headers=ADMIN_HEADERS, follow_redirects=False,
        data={"name_th": "Serum Thai", "name_en": "Updated serum", "is_active": "on"},
    ).status_code == 303
    with db_session_factory() as session:
        assert session.get(SpecimenType, serum).collection_room == "BLOOD"
        events = list(session.scalars(select(AuditLog).where(
            AuditLog.entity_type == "specimen_type", AuditLog.entity_id == serum,
        )))
        assert any("collection_room" in event.changed_fields for event in events)
