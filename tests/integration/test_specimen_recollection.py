import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain.exceptions import InvalidSpecimenOperationError
from app.models.audit import AuditLog
from app.models.order import LabOrder
from app.models.result import Result
from app.models.specimen import Specimen, SpecimenItem
from app.schemas.specimen import SpecimenCollectRequest
from app.services.specimen import SpecimenService
from tests.integration.test_outlab import SUPERVISOR, setup_outlab
from tests.integration.test_specimens import HEADERS, create_collection_order


def collect(client, order_id, type_id, previous=None, group="INTERNAL", **extras):
    return client.post(
        "/api/v1/specimens",
        headers=HEADERS,
        json={
            "order_id": order_id,
            "specimen_type_id": type_id,
            "collection_group": group,
            "replaces_specimen_id": previous,
            **extras,
        },
    )


def reject(client, specimen):
    response = client.patch(
        f"/api/v1/specimens/{specimen['id']}/rejection",
        headers=HEADERS,
        json={
            "rejection_reason_code": "INSUFFICIENT_VOLUME",
            "rejection_reason": "Need a new specimen",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def receive(client, specimen):
    response = client.patch(f"/api/v1/specimens/{specimen['id']}/receipt", headers=HEADERS, json={})
    assert response.status_code == 200, response.text


@pytest.mark.integration
def test_repeated_recollection_retains_history_and_results_use_latest(client, db_session_factory):
    order_id, serum, urine, _ = create_collection_order(client)
    urine_specimen = collect(client, order_id, urine).json()
    receive(client, urine_specimen)
    context_url = f"/api/v1/results/orders/{order_id}"
    context = client.get(context_url, headers=HEADERS).json()["items"]
    urine_item = next(i for i in context if i["test_code"] == "UPRO")
    saved_urine = client.post(
        context_url,
        headers=HEADERS,
        json={
            "items": [
                {
                    "order_item_id": urine_item["order_item_id"],
                    "numeric_value": "12",
                    "complete": True,
                }
            ]
        },
    ).json()[0]
    assert (
        client.patch(
            f"/api/v1/results/{saved_urine['id']}/verify", headers=SUPERVISOR, json={}
        ).status_code
        == 200
    )
    old = collect(client, order_id, serum).json()
    rejected = reject(client, old)
    assert rejected["rejected_by"] == HEADERS["X-Actor"]
    queue = client.get("/worklist?task_type=ORDER_PENDING_COLLECTION", headers=HEADERS)
    row = next(i for i in queue.context["worklist"].items if i.order_id == order_id)
    assert row.task_label == "รอเก็บสิ่งส่งตรวจใหม่"
    assert row.next_action_label == "เก็บสิ่งส่งตรวจใหม่"
    assert (
        client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={}).status_code
        == 422
    )
    replacement = collect(client, order_id, serum, previous=old["id"])
    assert replacement.status_code == 201, replacement.text
    second = replacement.json()
    assert second["id"] != old["id"] and second["accession_number"] != old["accession_number"]
    assert second["replaces_specimen_id"] == old["id"] and second["is_current"]
    assert collect(client, order_id, serum, previous=old["id"]).status_code == 422
    assert (
        client.patch(f"/api/v1/specimens/{old['id']}/receipt", headers=HEADERS, json={}).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/specimens/{old['id']}/rejection",
            headers=HEADERS,
            json={"rejection_reason": "Cannot change old"},
        ).status_code
        == 422
    )
    old_detail = client.get(f"/specimens/receiving/{old['id']}", headers=HEADERS)
    assert second["accession_number"] in old_detail.text
    assert "Need a new specimen" in old_detail.text
    reject(client, second)
    third = collect(client, order_id, serum, previous=second["id"]).json()
    receive(client, third)
    requirements = client.get(
        f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS
    ).json()
    current = next(r for r in requirements if r["specimen_type_id"] == serum)
    assert current["specimen"]["id"] == third["id"]
    assert [s["id"] for s in current["history"]] == [old["id"], second["id"]]
    page = client.get(f"/orders/{order_id}/specimens", headers=HEADERS)
    assert all(s["accession_number"] in page.text for s in [old, second, third])
    result_queue = client.get("/worklist?queue=results", headers=HEADERS).context["worklist"]
    row = next(i for i in result_queue.items if i.order_id == order_id)
    assert len(row.result_tests) == 2
    assert {t.accession_number for t in row.result_tests} == {third["accession_number"]}
    saved = client.post(
        context_url,
        headers=HEADERS,
        json={
            "items": [
                {"order_item_id": i["order_item_id"], "numeric_value": "95", "complete": True}
                for i in context
                if i["test_code"] != "UPRO"
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert {r["specimen_id"] for r in saved.json()} == {third["id"]}
    for result in saved.json():
        assert (
            client.patch(
                f"/api/v1/results/{result['id']}/verify", headers=SUPERVISOR, json={}
            ).status_code
            == 200
        )
    assert (
        client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={}).status_code
        == 200
    )
    with db_session_factory() as session:
        for prior in (old, second):
            row = session.get(Specimen, prior["id"])
            assert row.status == "REJECTED" and not row.is_current
            assert row.rejected_by == HEADERS["X-Actor"]
            assert len(row.items) == 2
        assert session.get(Result, saved_urine["id"]).status == "RELEASED"
        events = {
            e.event_type
            for e in session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type == "specimen", AuditLog.entity_id == third["id"]
                )
            )
        }
        assert {"SPECIMEN_RECOLLECTED", "SPECIMEN_RECEIVED"} <= events


@pytest.mark.integration
def test_recollection_requires_matching_rejected_specimen_and_permissions(
    client, db_session_factory
):
    order_id, serum, urine, _ = create_collection_order(client)
    old = collect(client, order_id, serum).json()
    assert collect(client, order_id, serum, previous=old["id"]).status_code == 422
    rejected = reject(client, old)
    assert collect(client, order_id, serum).status_code == 422
    assert collect(client, order_id, urine, previous=old["id"]).status_code == 422
    assert (
        collect(client, order_id, serum, previous=old["id"], group="OUTLAB-999").status_code == 422
    )
    before = rejected["collected_at"]
    assert (
        collect(client, order_id, serum, previous=old["id"], collected_at=before).status_code == 422
    )
    for role in ("RECEPTION", "LAB_SUPERVISOR"):
        assert (
            client.post(
                "/api/v1/specimens",
                headers={"X-Role": role, "X-Actor": "denied"},
                json={
                    "order_id": order_id,
                    "specimen_type_id": serum,
                    "replaces_specimen_id": old["id"],
                },
            ).status_code
            == 403
        )
    other = client.post(
        "/api/v1/orders",
        headers=HEADERS,
        json={
            "patient_id": client.get(f"/api/v1/orders/{order_id}", headers=HEADERS).json()[
                "patient_id"
            ],
            "test_ids": [
                client.get(f"/api/v1/orders/{order_id}", headers=HEADERS).json()["items"][0][
                    "lab_test_id"
                ]
            ],
        },
    ).json()
    assert collect(client, other["id"], serum, previous=old["id"]).status_code == 422
    with db_session_factory() as session:
        session.get(LabOrder, order_id).status = "CANCELLED"
        session.commit()
    assert collect(client, order_id, serum, previous=old["id"]).status_code == 422


@pytest.mark.integration
def test_recollection_rollback_keeps_rejected_specimen_current(
    client, db_session_factory, monkeypatch
):
    order_id, serum, _, _ = create_collection_order(client)
    old = reject(client, collect(client, order_id, serum).json())
    with db_session_factory() as session:
        service = SpecimenService(session)

        def fail_audit(_):
            raise IntegrityError("INSERT audit_logs", {}, Exception("forced failure"))

        monkeypatch.setattr(service.audit_repository, "add", fail_audit)
        with pytest.raises(InvalidSpecimenOperationError):
            service.collect(
                SpecimenCollectRequest(
                    order_id=order_id, specimen_type_id=serum, replaces_specimen_id=old["id"]
                ),
                actor_reference="recollector",
            )
        assert session.get(Specimen, old["id"]).is_current
        assert len(list(session.scalars(select(Specimen)))) == 1
        assert len(list(session.scalars(select(SpecimenItem)))) == 2


@pytest.mark.integration
def test_database_prevents_two_current_specimens_or_branched_replacements(
    client, db_session_factory
):
    order_id, serum, _, _ = create_collection_order(client)
    old = reject(client, collect(client, order_id, serum).json())
    replacement = collect(client, order_id, serum, previous=old["id"])
    assert replacement.status_code == 201
    for is_current, replaces_id in ((True, None), (False, old["id"])):
        with db_session_factory() as session:
            row = session.get(Specimen, old["id"])
            conflicting = Specimen(
                accession_number=f"DUP-{is_current}",
                order_id=order_id,
                specimen_type_id=serum,
                specimen_type_code=row.specimen_type_code,
                specimen_type_name_th=row.specimen_type_name_th,
                specimen_type_name_en=row.specimen_type_name_en,
                collection_group=row.collection_group,
                collected_by="constraint-test",
                is_current=is_current,
                replaces_specimen_id=replaces_id,
            )
            session.add(conflicting)
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()


@pytest.mark.integration
def test_collection_filter_classifies_mixed_orders_before_pagination(client, db_session_factory):
    order_id, serum, _, _ = create_collection_order(client)
    original = client.get(f"/api/v1/orders/{order_id}", headers=HEADERS).json()
    other = client.post(
        "/api/v1/orders",
        headers=HEADERS,
        json={
            "patient_id": original["patient_id"],
            "test_ids": [item["lab_test_id"] for item in original["items"]],
        },
    ).json()
    old = reject(client, collect(client, order_id, serum).json())
    # This order also has an uncollected urine specimen, but appears in the recollection group.
    base_url = "/worklist?task_type=ORDER_PENDING_COLLECTION"
    for value, expected in (
        ("all", {order_id, other["id"]}),
        ("initial", {other["id"]}),
        ("recollection", {order_id}),
    ):
        response = client.get(f"{base_url}&collection_filter={value}", headers=HEADERS)
        assert response.status_code == 200
        queue = response.context["worklist"]
        assert queue.total == len(expected)
        assert {item.order_id for item in queue.items} == expected
        assert f'<option value="{value}" selected>' in response.text
        assert 'name="task_type" value="ORDER_PENDING_COLLECTION"' in response.text
        assert 'name="collection_filter"' in response.text
    empty = client.get(
        f"{base_url}&collection_filter=recollection&search={other['order_number']}", headers=HEADERS
    )
    assert empty.context["worklist"].total == 0
    assert "ไม่พบรายการรอเก็บสิ่งส่งตรวจตามเงื่อนไขที่เลือก" in empty.text
    assert client.get(f"{base_url}&collection_filter=invalid", headers=HEADERS).status_code == 422
    from app.schemas.worklist import WorklistTaskType
    from app.services.worklist import WorklistService

    with db_session_factory() as session:
        service = WorklistService(session)
        for value in ("initial", "recollection"):
            queue = service.list_tasks(
                task_type=WorklistTaskType.ORDER_PENDING_COLLECTION,
                department_id=None,
                priority=None,
                status=None,
                search=None,
                page=2,
                page_size=1,
                group_collection_orders=True,
                collection_filter=value,
            )
            assert queue.total == 1 and queue.items == []
    assert collect(client, order_id, serum, previous=old["id"]).status_code == 201
    remaining = client.get(f"{base_url}&collection_filter=recollection", headers=HEADERS)
    assert remaining.context["worklist"].total == 0
    initial = client.get(f"{base_url}&collection_filter=initial", headers=HEADERS)
    assert initial.context["worklist"].total == 2


@pytest.mark.integration
def test_outlab_uses_new_separate_specimen_after_rejection(client, db_session_factory):
    order_id, case_id, _ = setup_outlab(client, db_session_factory, external_only=True)
    req = client.get(f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS).json()[0]
    old = collect(client, order_id, req["specimen_type_id"], group=req["collection_group"]).json()
    reject(client, old)
    assert (
        client.post(
            f"/outlab/{case_id}/send", headers=HEADERS, data={"lab_name": "External Lab"}
        ).status_code
        == 422
    )
    replacement = client.post(
        f"/orders/{order_id}/specimens/{req['specimen_type_id']}/collect",
        headers=HEADERS,
        data={"replaces_specimen_id": old["id"], "collection_group": req["collection_group"]},
        follow_redirects=False,
    )
    assert replacement.status_code == 303, replacement.text
    with db_session_factory() as session:
        current = session.scalar(select(Specimen).where(Specimen.is_current.is_(True)))
        new_id = current.id
    before_receive = client.get(f"/outlab/{case_id}", headers=HEADERS)
    assert "ตรวจรับ Specimen ก่อนส่ง" in before_receive.text
    assert (
        client.post(
            f"/outlab/{case_id}/send", headers=HEADERS, data={"lab_name": "External Lab"}
        ).status_code
        == 422
    )
    receive(client, {"id": new_id})
    assert (
        client.post(
            f"/outlab/{case_id}/send",
            headers=HEADERS,
            data={"lab_name": "External Lab"},
            follow_redirects=False,
        ).status_code
        == 303
    )
