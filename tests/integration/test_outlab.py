from io import BytesIO
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.order import LabOrder
from app.models.outlab import OutlabCase, OutlabDocument
from app.models.result import Result
from tests.integration.test_packages import package, setup_tests
from tests.integration.test_specimens import ADMIN_HEADERS, HEADERS

SUPERVISOR = {"X-Role": "LAB_SUPERVISOR", "X-Actor": "outlab-reviewer"}
RECEPTION = {"X-Role": "RECEPTION", "X-Actor": "outlab-reception"}
SOURCE = b"%PDF-1.4\nOriginal verified external laboratory report\n%%EOF"


def setup_outlab(client, factory, external_only=False):
    patient, tests, serum, _ = setup_tests(client)
    outlab = client.post(
        "/api/v1/tests",
        headers=ADMIN_HEADERS,
        json={
            "code": "OUT-VITD",
            "name_th": "Vitamin D Outlab",
            "name_en": "Vitamin D Outlab",
            "category_id": 1,
            "department_id": 1,
            "specimen_type_id": serum,
            "current_price": "900",
            "tat_minutes": 2880,
            "result_type": "TEXT",
            "is_outlab": True,
            "outlab_lab_name": "External Reference Lab",
        },
    )
    assert outlab.status_code == 201, outlab.text
    p, _ = package(client, "INTERNAL", [tests["GLU"], tests["CREA"]], "150")
    response = client.post(
        "/api/v1/orders",
        headers=RECEPTION,
        json={
            "patient_id": patient,
            "package_ids": [] if external_only else [p["id"]],
            "test_ids": [outlab.json()["id"]],
        },
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    with factory() as session:
        case = session.scalar(
            select(OutlabCase)
            .join(OutlabCase.order_item)
            .where(OutlabCase.order_item.has(order_id=order_id))
        )
        return order_id, case.id, outlab.json()["id"]


def collect(client, order_id, requirement):
    response = client.post(
        "/api/v1/specimens",
        headers=HEADERS,
        json={
            "order_id": order_id,
            "specimen_type_id": requirement["specimen_type_id"],
            "collection_group": requirement["collection_group"],
        },
    )
    assert response.status_code == 201, response.text
    received = client.patch(
        f"/api/v1/specimens/{response.json()['id']}/receipt", headers=HEADERS, json={}
    )
    assert received.status_code == 200, received.text
    return response.json()


def send(client, case_id):
    response = client.post(
        f"/outlab/{case_id}/send",
        headers=HEADERS,
        data={
            "lab_name": "Actual External Lab",
            "external_reference": "EXT-123",
            "notes": "Separate tube sent",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def upload(client, case_id, content=SOURCE):
    return client.post(
        f"/outlab/{case_id}/receive",
        headers=SUPERVISOR,
        files={"document": ("original.pdf", content, "application/pdf")},
        follow_redirects=False,
    )


@pytest.mark.integration
@pytest.mark.parametrize("documents_first", [False, True])
def test_package_plus_outlab_separate_specimens_and_wait_for_both(
    client,
    db_session_factory,
    documents_first,
):
    order_id, case_id, test_id = setup_outlab(client, db_session_factory)
    requirements = client.get(
        f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS
    ).json()
    assert len(requirements) == 2
    assert len({r["specimen_type_id"] for r in requirements}) == 1
    internal = next(r for r in requirements if r["collection_group"] == "INTERNAL")
    external = next(r for r in requirements if r["collection_group"] != "INTERNAL")
    assert len(internal["items"]) == 2 and len(external["items"]) == 1
    # New catalog settings do not rewrite an existing order's route or destination.
    assert (
        client.patch(
            f"/api/v1/tests/{test_id}",
            headers=ADMIN_HEADERS,
            json={
                "is_outlab": False,
                "outlab_lab_name": "Changed lab",
                "reason": "future orders only",
            },
        ).status_code
        == 200
    )
    own_specimen = collect(client, order_id, internal)
    pending = client.get("/worklist?task_type=ORDER_PENDING_COLLECTION", headers=HEADERS)
    assert any(row.order_id == order_id for row in pending.context["worklist"].items)
    original = collect(client, order_id, external)
    assert original["id"] != own_specimen["id"]
    external_page = client.get(
        f"/specimens/receiving/{original['id']}", headers=HEADERS
    )
    internal_page = client.get(
        f"/specimens/receiving/{own_specimen['id']}", headers=HEADERS
    )
    badge = '<span class="badge text-bg-warning ms-2">Outlab</span>'
    assert badge in external_page.text
    assert badge not in internal_page.text
    assert original["accession_number"] != own_specimen["accession_number"]
    assert {i["order_item_id"] for i in original["items"]}.isdisjoint(
        {i["order_item_id"] for i in own_specimen["items"]}
    )
    # No third tube may silently duplicate the same collection group.
    assert (
        client.post(
            "/api/v1/specimens",
            headers=HEADERS,
            json={
                "order_id": order_id,
                "specimen_type_id": external["specimen_type_id"],
                "collection_group": external["collection_group"],
            },
        ).status_code
        == 422
    )
    context_url = f"/api/v1/results/orders/{order_id}"
    items = client.get(context_url, headers=HEADERS).json()["items"]
    foreign_item = next(item for item in items if item["is_outlab"])
    assert (
        client.post(
            context_url,
            headers=HEADERS,
            json={
                "items": [
                    {
                        "order_item_id": foreign_item["order_item_id"],
                        "text_value": "forbidden transcription",
                        "complete": True,
                    }
                ]
            },
        ).status_code
        == 422
    )
    entry = client.get(f"/worklist/orders/{order_id}", headers=HEADERS)
    assert f'name="value_{foreign_item["order_item_id"]}"' not in entry.text
    queue = client.get("/worklist?queue=results", headers=HEADERS).context["worklist"]
    row = next(row for row in queue.items if row.order_id == order_id)
    assert {test.test_code for test in row.result_tests} == {"GLU", "CREA"}
    send(client, case_id)

    def complete_documents():
        assert upload(client, case_id).status_code == 303
        assert (
            client.post(
                f"/outlab/{case_id}/document/check",
                headers=SUPERVISOR,
                data={"confirmed": "on"},
                follow_redirects=False,
            ).status_code
            == 303
        )

    if documents_first:
        complete_documents()
        assert (
            client.patch(
                f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={}
            ).status_code
            == 422
        )
    saved = client.post(
        context_url,
        headers=HEADERS,
        json={
            "items": [
                {"order_item_id": item["order_item_id"], "numeric_value": "95", "complete": True}
                for item in items
                if not item["is_outlab"]
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    for result in saved.json():
        assert (
            client.patch(
                f"/api/v1/results/{result['id']}/verify", headers=SUPERVISOR, json={}
            ).status_code
            == 200
        )
    if not documents_first:
        blocked = client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={})
        assert blocked.status_code == 422 and "Outlab" in blocked.text
        complete_documents()
    released = client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={})
    assert released.status_code == 200, released.text
    report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR)
    assert report.status_code == 200
    assert {r["test_code"] for r in report.context["context"]["results"]} == {"GLU", "CREA"}
    assert len(report.context["context"]["outlab_cases"]) == 1
    with db_session_factory() as session:
        case = session.get(OutlabCase, case_id)
        assert case.lab_name == "Actual External Lab"
        doc_id = case.documents[-1].id
        assert (
            session.scalar(select(Result).where(Result.order_item_id == case.order_item_id)) is None
        )
        events = {
            e.event_type
            for e in session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type == "outlab_case", AuditLog.entity_id == case_id
                )
            )
        }
        assert {"OUTLAB_SENT", "OUTLAB_DOCUMENT_RECEIVED", "OUTLAB_DOCUMENT_CHECKED"} <= events
    download = client.get(f"/outlab/documents/{doc_id}", headers=SUPERVISOR)
    assert download.status_code == 200 and download.content == SOURCE
    bundle = client.get(f"/results/reports/orders/{order_id}/bundle", headers=SUPERVISOR)
    assert bundle.status_code == 200
    with ZipFile(BytesIO(bundle.content)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert archive.read(next(n for n in names if n.startswith("Outlab/"))) == SOURCE
        assert archive.read(next(n for n in names if n.startswith("QMS-LIS-"))).startswith(b"%PDF-")
    assert upload(client, case_id).status_code == 422
    for path in (
        "/outlab",
        f"/outlab/{case_id}",
        f"/outlab/documents/{doc_id}",
        f"/results/reports/orders/{order_id}/bundle",
    ):
        assert client.get(path, headers=RECEPTION).status_code == 403


@pytest.mark.integration
def test_document_check_validation_replacement_and_external_only_order(client, db_session_factory):
    order_id, case_id, _ = setup_outlab(client, db_session_factory, external_only=True)
    assert (
        client.post(
            f"/outlab/{case_id}/send", headers=HEADERS, data={"lab_name": "Lab"}
        ).status_code
        == 422
    )
    requirement = client.get(
        f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS
    ).json()[0]
    collect(client, order_id, requirement)
    send(client, case_id)
    assert upload(client, case_id, b"<html>not a pdf</html>").status_code == 422
    assert upload(client, case_id).status_code == 303
    assert upload(client, case_id).status_code == 422
    assert (
        client.post(f"/outlab/{case_id}/document/check", headers=SUPERVISOR, data={}).status_code
        == 422
    )
    assert (
        client.post(
            f"/outlab/{case_id}/document/check",
            headers=SUPERVISOR,
            data={"decision": "reject", "reason": "Wrong patient"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    replacement = SOURCE + b"\nReplacement"
    assert upload(client, case_id, replacement).status_code == 303
    assert (
        client.post(
            f"/outlab/{case_id}/document/check",
            headers=SUPERVISOR,
            data={"confirmed": "on"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            f"/outlab/{case_id}/document/check", headers=SUPERVISOR, data={"confirmed": "on"}
        ).status_code
        == 422
    )
    assert (
        client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={}).status_code
        == 200
    )
    bundle = client.get(f"/results/reports/orders/{order_id}/bundle", headers=SUPERVISOR)
    with ZipFile(BytesIO(bundle.content)) as archive:
        assert len(archive.namelist()) == 1
        assert archive.read(archive.namelist()[0]) == replacement
    with db_session_factory() as session:
        assert len(list(session.scalars(select(OutlabDocument)))) == 2


@pytest.mark.integration
@pytest.mark.parametrize("manager", [SUPERVISOR, ADMIN_HEADERS])
def test_outlab_responsibilities_enforced_for_each_stage(client, db_session_factory, manager):
    order_id, case_id, _ = setup_outlab(client, db_session_factory, external_only=True)
    pending_supervisor = client.get(f"/outlab/{case_id}", headers=SUPERVISOR)
    assert pending_supervisor.status_code == 200
    assert f'/orders/{order_id}/specimens"' not in pending_supervisor.text
    requirement = client.get(
        f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS
    ).json()[0]
    collect(client, order_id, requirement)
    assert (
        client.post(
            f"/outlab/{case_id}/send", headers=SUPERVISOR, data={"lab_name": "Not permitted"}
        ).status_code
        == 403
    )
    send(client, case_id)
    tech_page = client.get(f"/outlab/{case_id}", headers=HEADERS)
    supervisor_page = client.get(f"/outlab/{case_id}", headers=SUPERVISOR)
    assert 'name="document"' not in tech_page.text
    assert 'name="document"' in supervisor_page.text
    for denied in (HEADERS, RECEPTION, {"X-Role": "IT", "X-Actor": "it-user"}):
        assert (
            client.post(
                f"/outlab/{case_id}/receive",
                headers=denied,
                files={"document": ("original.pdf", SOURCE, "application/pdf")},
            ).status_code
            == 403
        )
        for decision in ({"confirmed": "on"}, {"decision": "reject", "reason": "Denied"}):
            assert (
                client.post(
                    f"/outlab/{case_id}/document/check", headers=denied, data=decision
                ).status_code
                == 403
            )
    with db_session_factory() as session:
        case = session.get(OutlabCase, case_id)
        assert case.status == "SENT" and not case.documents
    assert (
        client.post(
            f"/outlab/{case_id}/receive",
            headers=manager,
            files={"document": ("original.pdf", SOURCE, "application/pdf")},
            follow_redirects=False,
        ).status_code
        == 303
    )
    tech_page = client.get(f"/outlab/{case_id}", headers=HEADERS)
    supervisor_page = client.get(f"/outlab/{case_id}", headers=SUPERVISOR)
    assert 'name="confirmed"' not in tech_page.text
    assert 'name="confirmed"' in supervisor_page.text
    assert (
        client.post(
            f"/outlab/{case_id}/document/check", headers=HEADERS, data={"confirmed": "on"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/outlab/{case_id}/document/check",
            headers=HEADERS,
            data={"decision": "reject", "reason": "Denied"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/outlab/{case_id}/document/check",
            headers=manager,
            data={"confirmed": "on"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    with db_session_factory() as session:
        case = session.get(OutlabCase, case_id)
        assert case.ready
        assert case.sent_by == HEADERS["X-Actor"]
        assert case.received_by == case.checked_by == manager["X-Actor"]
        assert case.documents[-1].uploaded_by == manager["X-Actor"]


@pytest.mark.integration
def test_cancelled_order_cannot_send_outlab(client, db_session_factory):
    order_id, case_id, _ = setup_outlab(client, db_session_factory)
    requirements = client.get(
        f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS
    ).json()
    collect(client, order_id, next(r for r in requirements if r["outlab_lab_name"]))
    with db_session_factory() as session:
        session.get(LabOrder, order_id).status = "CANCELLED"
        session.commit()
    assert (
        client.post(
            f"/outlab/{case_id}/send", headers=HEADERS, data={"lab_name": "Lab"}
        ).status_code
        == 422
    )
