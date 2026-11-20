import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.order import LabOrder, OrderStatus
from tests.integration.test_specimens import (
    ADMIN_HEADERS,
    HEADERS,
    create_collection_order,
)

RECEPTION_HEADERS = {"X-Role": "RECEPTION", "X-Actor": "reception-1"}


@pytest.mark.integration
def test_result_queue_filters_stay_in_result_entry(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)
    specimen = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert specimen.status_code == 201
    assert (
        client.patch(
            f"/api/v1/specimens/{specimen.json()['id']}/receipt",
            json={},
            headers=HEADERS,
        ).status_code
        == 200
    )
    for query in (
        "task_type=RESULT_PENDING_ENTRY",
        "queue=results&task_type=&department_id=&search=",
        "queue=results",
    ):
        page = client.get(f"/worklist?{query}", headers=HEADERS)
        assert page.status_code == 200
        assert page.context["result_queue"] is True
        assert page.context["worklist"].total == 1
        assert len(page.context["worklist"].items) == 1
        row = page.context["worklist"].items[0]
        assert {test.test_code for test in row.result_tests} == {"GLU", "CREA"}
        assert row.result_status_counts == {"RESULT_PENDING_ENTRY": 2}
        assert page.text.count(f'href="/worklist/orders/{order_id}"') == 1
        assert all(
            item.task_type.value.startswith("RESULT_") for item in page.context["worklist"].items
        )
        assert 'name="queue" value="results"' in page.text
        assert 'href="/worklist?queue=results"' in page.text
        assert 'name="priority"' not in page.text
        assert 'name="status"' not in page.text
        assert 'aria-label="Task counts"' not in page.text
        assert '<option value="ORDER_PENDING_COLLECTION"' not in page.text
    progress = client.get(
        "/worklist?queue=results&task_type=RESULT_IN_PROGRESS",
        headers=HEADERS,
    )
    assert progress.context["worklist"].total == 0
    from app.services.worklist import WorklistService

    with db_session_factory() as session:
        service = WorklistService(session)
        for page_number in (1, 2):
            queue = service.list_tasks(
                task_type=None,
                department_id=None,
                priority=None,
                status=None,
                search=None,
                page=page_number,
                page_size=1,
                result_tasks_only=True,
            )
            assert queue.total == 1
            assert len(queue.items) == (1 if page_number == 1 else 0)
            if queue.items:
                assert len(queue.items[0].result_tests) == 2

    context = client.get(f"/api/v1/results/orders/{order_id}", headers=HEADERS).json()
    glu = next(item for item in context["items"] if item["test_code"] == "GLU")
    saved = client.post(
        f"/api/v1/results/orders/{order_id}",
        headers=HEADERS,
        json={
            "items": [
                {"order_item_id": glu["order_item_id"], "numeric_value": "96", "complete": False}
            ]
        },
    )
    assert saved.status_code == 200
    mixed = client.get("/worklist?queue=results", headers=HEADERS).context["worklist"]
    assert mixed.total == 1
    assert mixed.items[0].result_status_counts == {
        "RESULT_PENDING_ENTRY": 1,
        "RESULT_IN_PROGRESS": 1,
    }
    filtered = client.get(
        "/worklist?task_type=RESULT_IN_PROGRESS",
        headers=HEADERS,
    ).context["worklist"]
    assert filtered.total == 1
    assert [test.test_code for test in filtered.items[0].result_tests] == ["GLU"]


@pytest.mark.integration
def test_collection_page_groups_orders_and_keeps_only_pending_specimens(client: TestClient) -> None:
    order_id, serum_id, urine_id, _ = create_collection_order(client)
    page = client.get("/worklist?task_type=ORDER_PENDING_COLLECTION", headers=HEADERS)
    queue = page.context["worklist"]
    assert queue.total == 1
    assert len(queue.items) == 1
    assert set(queue.items[0].pending_specimens) == {"Serum", "Urine"}
    assert page.text.count(">Collect specimens</a>") == 1
    assert "Apply filters" not in page.text
    assert 'aria-label="Task counts"' not in page.text
    assert queue.items[0].next_action_url == f"/orders/{order_id}/specimens"

    assert (
        client.post(
            "/api/v1/specimens",
            json={
                "order_id": order_id,
                "specimen_type_id": serum_id,
            },
            headers=HEADERS,
        ).status_code
        == 201
    )
    partial = client.get("/worklist?task_type=ORDER_PENDING_COLLECTION", headers=HEADERS)
    assert partial.context["worklist"].total == 1
    assert partial.context["worklist"].items[0].pending_specimens == ["Urine"]
    assert (
        client.post(
            "/api/v1/specimens",
            json={
                "order_id": order_id,
                "specimen_type_id": urine_id,
            },
            headers=HEADERS,
        ).status_code
        == 201
    )
    complete = client.get("/worklist?task_type=ORDER_PENDING_COLLECTION", headers=HEADERS)
    assert complete.context["worklist"].total == 0


@pytest.mark.integration
def test_collection_orders_are_grouped_before_pagination(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    from app.schemas.worklist import WorklistTaskType
    from app.services.worklist import WorklistService

    order_id, _, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        service = WorklistService(session)
        for page in (1, 2):
            queue = service.list_tasks(
                task_type=WorklistTaskType.ORDER_PENDING_COLLECTION,
                department_id=None,
                priority=None,
                status=None,
                search=None,
                page=page,
                page_size=1,
                group_collection_orders=True,
            )
            assert queue.total == 1
            if page == 1:
                assert queue.items[0].order_id == order_id
                assert set(queue.items[0].pending_specimens) == {"Serum", "Urine"}
            else:
                assert queue.items == []


def _worklist(client: TestClient, **params: object) -> dict[str, object]:
    response = client.get("/api/v1/worklist", params=params, headers=HEADERS)
    assert response.status_code == 200
    return response.json()


@pytest.mark.integration
def test_unified_worklist_tracks_the_complete_laboratory_workflow(
    client: TestClient,
) -> None:
    order_id, serum_id, urine_id, _ = create_collection_order(client)

    initial = _worklist(client)
    initial_items = initial["items"]
    assert isinstance(initial_items, list)
    assert [item["task_type"] for item in initial_items] == [
        "ORDER_PENDING_COLLECTION",
        "ORDER_PENDING_COLLECTION",
    ]
    assert {item["specimen_type"] for item in initial_items} == {"Serum", "Urine"}
    assert initial["counts_by_task_type"]["ORDER_PENDING_COLLECTION"] == 2
    assert all(item["next_action_url"] == f"/orders/{order_id}/specimens" for item in initial_items)
    assert all(
        {
            "task_status",
            "priority",
            "order_number",
            "patient_hn",
            "patient_display_name",
            "current_order_status",
            "created_at",
            "next_action_label",
        }
        <= item.keys()
        for item in initial_items
    )

    dashboard = client.get("/", headers=HEADERS)
    assert dashboard.status_code == 200
    assert "/worklist?task_type=ORDER_PENDING_COLLECTION" in dashboard.text
    assert "เก็บสิ่งส่งตรวจ" in dashboard.text

    serum = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert serum.status_code == 201
    serum_data = serum.json()

    after_collection = _worklist(client)
    collection_items = after_collection["items"]
    assert {item["task_type"] for item in collection_items} == {
        "ORDER_PENDING_COLLECTION",
        "SPECIMEN_PENDING_RECEIVING",
    }
    remaining_collection = next(
        item for item in collection_items if item["task_type"] == "ORDER_PENDING_COLLECTION"
    )
    assert remaining_collection["specimen_type"] == "Urine"
    receiving = next(
        item for item in collection_items if item["task_type"] == "SPECIMEN_PENDING_RECEIVING"
    )
    assert receiving["accession_number"] == serum_data["accession_number"]
    assert receiving["next_action_url"] == f"/specimens/receiving/{serum_data['id']}"
    assert _worklist(client, search=serum_data["accession_number"])["total"] == 1

    received = client.patch(
        f"/api/v1/specimens/{serum_data['id']}/receipt", json={}, headers=HEADERS
    )
    assert received.status_code == 200
    after_receipt = _worklist(client)
    result_tasks = [
        item for item in after_receipt["items"] if item["task_type"] == "RESULT_PENDING_ENTRY"
    ]
    assert {item["test_code"] for item in result_tasks} == {"GLU", "CREA"}
    assert all(item["next_action_label"] == "Enter result" for item in result_tasks)
    assert all(item["next_action_url"] == f"/worklist/orders/{order_id}" for item in result_tasks)

    context = client.get(f"/api/v1/results/orders/{order_id}", headers=HEADERS)
    assert context.status_code == 200
    context_items = {item["test_code"]: item for item in context.json()["items"]}
    partial = client.post(
        f"/api/v1/results/orders/{order_id}",
        json={
            "items": [
                {
                    "order_item_id": context_items["GLU"]["order_item_id"],
                    "numeric_value": "95",
                    "complete": False,
                }
            ]
        },
        headers=HEADERS,
    )
    assert partial.status_code == 200
    after_partial = _worklist(client)
    in_progress = [
        item for item in after_partial["items"] if item["task_type"] == "RESULT_IN_PROGRESS"
    ]
    assert [item["test_code"] for item in in_progress] == ["GLU"]
    assert in_progress[0]["next_action_label"] == "Continue result entry"
    assert _worklist(client, status="IN_PROGRESS")["total"] == 1

    completed_serum = client.post(
        f"/api/v1/results/orders/{order_id}",
        json={
            "items": [
                {
                    "order_item_id": context_items["GLU"]["order_item_id"],
                    "numeric_value": "96",
                    "complete": True,
                },
                {
                    "order_item_id": context_items["CREA"]["order_item_id"],
                    "numeric_value": "1.1",
                    "complete": True,
                },
            ]
        },
        headers=HEADERS,
    )
    assert completed_serum.status_code == 200
    assert {item["task_type"] for item in _worklist(client)["items"]} == {
        "ORDER_PENDING_COLLECTION"
    }

    urine = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": urine_id},
        headers=HEADERS,
    )
    assert urine.status_code == 201
    assert (
        client.patch(
            f"/api/v1/specimens/{urine.json()['id']}/receipt", json={}, headers=HEADERS
        ).status_code
        == 200
    )
    context = client.get(f"/api/v1/results/orders/{order_id}", headers=HEADERS).json()
    urine_item = next(item for item in context["items"] if item["test_code"] == "UPRO")
    completed_urine = client.post(
        f"/api/v1/results/orders/{order_id}",
        json={
            "items": [
                {
                    "order_item_id": urine_item["order_item_id"],
                    "numeric_value": "12",
                    "complete": True,
                }
            ]
        },
        headers=HEADERS,
    )
    assert completed_urine.status_code == 200
    finished = _worklist(client)
    assert finished["total"] == 0
    assert finished["items"] == []

    empty_page = client.get("/worklist", headers=HEADERS)
    assert empty_page.status_code == 200
    assert "No actionable laboratory tasks found." in empty_page.text


@pytest.mark.integration
def test_worklist_filters_ordering_exclusions_and_permissions(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    routine_order_id, serum_id, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        routine_order = session.get(LabOrder, routine_order_id)
        assert routine_order is not None
        patient_id = routine_order.patient_id
        test_ids = [item.lab_test_id for item in routine_order.items]
        department_id = routine_order.items[0].lab_test.department_id
        routine_number = routine_order.order_number
        patient_hn = routine_order.patient.hn

    urgent = client.post(
        "/api/v1/orders",
        json={"patient_id": patient_id, "test_ids": test_ids, "priority": "URGENT"},
        headers=ADMIN_HEADERS,
    )
    assert urgent.status_code == 201
    urgent_order_id = urgent.json()["id"]

    all_tasks = _worklist(client)
    assert all_tasks["total"] == 4
    assert [item["priority"] for item in all_tasks["items"][:2]] == ["URGENT", "URGENT"]
    assert _worklist(client, task_type="ORDER_PENDING_COLLECTION")["total"] == 4
    assert _worklist(client, department_id=department_id)["total"] == 4
    assert _worklist(client, priority="URGENT")["total"] == 2
    assert _worklist(client, status="PENDING")["total"] == 4
    assert _worklist(client, status="IN_PROGRESS")["total"] == 0
    assert _worklist(client, search=routine_number)["total"] == 2
    assert _worklist(client, search=patient_hn)["total"] == 4
    assert _worklist(client, search="Specimen Patient")["total"] == 4
    assert _worklist(client, search="GLU")["total"] == 2
    paged = _worklist(client, page=2, page_size=1)
    assert paged["total"] == 4
    assert len(paged["items"]) == 1

    with db_session_factory() as session:
        urgent_order = session.get(LabOrder, urgent_order_id)
        assert urgent_order is not None
        urgent_order.status = OrderStatus.CANCELLED
        session.commit()
    assert _worklist(client, priority="URGENT")["total"] == 0

    collected = client.post(
        "/api/v1/specimens",
        json={"order_id": routine_order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert collected.status_code == 201
    rejected = client.patch(
        f"/api/v1/specimens/{collected.json()['id']}/rejection",
        json={"rejection_reason": "haemolysed sample"},
        headers=HEADERS,
    )
    assert rejected.status_code == 200
    remaining = _worklist(client)
    assert remaining["total"] == 1
    assert remaining["items"][0]["task_type"] == "ORDER_PENDING_COLLECTION"
    assert remaining["items"][0]["specimen_type"] == "Urine"

    unauthorized = client.get("/api/v1/worklist", headers=RECEPTION_HEADERS)
    assert unauthorized.status_code == 403
    forbidden_result = client.post(
        "/api/v1/results/orders/999",
        json={"items": [{"order_item_id": 1, "numeric_value": "1"}]},
        headers=RECEPTION_HEADERS,
    )
    assert forbidden_result.status_code == 403

    assert client.get("/orders/999/specimens", headers=HEADERS).status_code == 404
    assert client.get("/specimens/receiving/999", headers=HEADERS).status_code == 404
    assert client.get("/worklist/orders/999", headers=HEADERS).status_code == 404
