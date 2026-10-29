from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.exceptions import InvalidSpecimenOperationError
from app.models.audit import AuditLog
from app.models.order import LabOrder, OrderStatus
from app.models.specimen import Specimen
from app.models.test_catalog import SpecimenType
from app.schemas.specimen import SpecimenCollectRequest
from app.services.specimen import SpecimenService

HEADERS = {"X-Role": "LAB_TECH", "X-Actor": "collector-1"}
ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "catalog-admin"}


def _alembic_config(database_url: str) -> Config:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def create_collection_order(client: TestClient) -> tuple[int, int, int, int]:
    category = client.post(
        "/api/v1/test-categories",
        json={"code": "CHEM", "name_th": "Chem", "name_en": "Chemistry"},
        headers=ADMIN_HEADERS,
    )
    serum = client.post(
        "/api/v1/specimen-types",
        json={"code": "SERUM", "name_th": "Serum Thai", "name_en": "Serum"},
        headers=ADMIN_HEADERS,
    )
    urine = client.post(
        "/api/v1/specimen-types",
        json={"code": "URINE", "name_th": "Urine Thai", "name_en": "Urine"},
        headers=ADMIN_HEADERS,
    )
    plasma = client.post(
        "/api/v1/specimen-types",
        json={"code": "PLASMA", "name_th": "Plasma Thai", "name_en": "Plasma"},
        headers=ADMIN_HEADERS,
    )
    assert category.status_code == 201
    assert serum.status_code == 201
    assert urine.status_code == 201
    assert plasma.status_code == 201
    test_ids = []
    for code, name, specimen_id in (
        ("GLU", "Glucose", serum.json()["id"]),
        ("CREA", "Creatinine", serum.json()["id"]),
        ("UPRO", "Urine Protein", urine.json()["id"]),
    ):
        test = client.post(
            "/api/v1/tests",
            json={
                "code": code,
                "name_th": f"{name} Thai",
                "name_en": name,
                "category_id": category.json()["id"],
                "specimen_type_id": specimen_id,
                "current_price": "100.00",
                "result_type": "NUMERIC",
                "result_unit": "mg/dL",
                "tat_minutes": 30,
            },
            headers=ADMIN_HEADERS,
        )
        assert test.status_code == 201
        test_ids.append(test.json()["id"])
    patient = client.post(
        "/api/v1/patients",
        json={
            "first_name_en": "Specimen",
            "last_name_en": "Patient",
            "passport_number": "B1234567",
        },
        headers=ADMIN_HEADERS,
    )
    assert patient.status_code == 201
    order = client.post(
        "/api/v1/orders",
        json={"patient_id": patient.json()["id"], "test_ids": test_ids},
        headers=HEADERS,
    )
    assert order.status_code == 201
    return order.json()["id"], serum.json()["id"], urine.json()["id"], plasma.json()["id"]


@pytest.mark.integration
def test_collection_groups_items_and_records_audit(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, serum_id, urine_id, _ = create_collection_order(client)

    requirements = client.get(f"/api/v1/orders/{order_id}/specimen-requirements", headers=HEADERS)
    assert requirements.status_code == 200
    grouped = {item["specimen_type_id"]: item for item in requirements.json()}
    assert {item["test_code"] for item in grouped[serum_id]["items"]} == {"GLU", "CREA"}
    assert [item["test_code"] for item in grouped[urine_id]["items"]] == ["UPRO"]

    collected = client.post(
        "/api/v1/specimens",
        json={
            "order_id": order_id,
            "specimen_type_id": serum_id,
            "collection_note": "  Morning draw  ",
        },
        headers=HEADERS,
    )
    assert collected.status_code == 201
    specimen = collected.json()
    assert specimen["accession_number"].startswith("SPC")
    assert specimen["status"] == "COLLECTED"
    assert specimen["collection_note"] == "Morning draw"
    assert len(specimen["items"]) == 2

    with db_session_factory() as session:
        audit = session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "specimen", AuditLog.entity_id == specimen["id"]
            )
        ).one()
    assert audit.event_type == "SPECIMEN_COLLECTED"
    assert audit.reason == ""
    assert audit.changed_fields == sorted(audit.changed_fields)


@pytest.mark.integration
def test_specimen_rejection_and_duplicate_collection_rules(client: TestClient) -> None:
    order_id, serum_id, _, unrelated_type_id = create_collection_order(client)

    not_required = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": unrelated_type_id},
        headers=HEADERS,
    )
    assert not_required.status_code == 422

    collected = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    specimen_id = collected.json()["id"]
    assert collected.status_code == 201

    missing_reason = client.patch(
        f"/api/v1/specimens/{specimen_id}/rejection", json={}, headers=HEADERS
    )
    assert missing_reason.status_code == 422
    rejected = client.patch(
        f"/api/v1/specimens/{specimen_id}/rejection",
        json={"rejection_reason": "haemolysed sample"},
        headers=HEADERS,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["rejection_reason"] == "haemolysed sample"

    duplicate = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert duplicate.status_code == 422
    second_rejection = client.patch(
        f"/api/v1/specimens/{specimen_id}/rejection",
        json={"rejection_reason": "duplicate"},
        headers=HEADERS,
    )
    assert second_rejection.status_code == 422


@pytest.mark.integration
def test_web_collection_view_and_submit(client: TestClient) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)

    page = client.get(f"/orders/{order_id}/specimens", headers=HEADERS)
    assert page.status_code == 200
    assert "Glucose" in page.text
    collected = client.post(
        f"/orders/{order_id}/specimens/{serum_id}/collect",
        data={"collection_note": "web collection"},
        headers=HEADERS,
        follow_redirects=False,
    )
    assert collected.status_code == 303
    detail = client.get(collected.headers["location"], headers=HEADERS)
    assert detail.status_code == 200
    assert "SPC" in detail.text


@pytest.mark.integration
def test_collection_validates_input_and_preserves_order_snapshots(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)
    before = client.get(f"/api/v1/orders/{order_id}", headers=HEADERS).json()

    invalid_order = client.post(
        "/api/v1/specimens",
        json={"order_id": 99999, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert invalid_order.status_code == 404
    invalid_timestamp = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id, "collected_at": "nope"},
        headers=HEADERS,
    )
    assert invalid_timestamp.status_code == 422
    unknown_field = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id, "patient_id": 1},
        headers=HEADERS,
    )
    assert unknown_field.status_code == 422

    collected = client.post(
        "/api/v1/specimens",
        json={
            "order_id": order_id,
            "specimen_type_id": serum_id,
            "collected_at": "2026-10-19T09:30:00+07:00",
        },
        headers=HEADERS,
    )
    assert collected.status_code == 201
    assert collected.json()["collected_at"] == "2026-10-19T02:30:00Z"
    response = client.get(f"/api/v1/specimens/{collected.json()['id']}", headers=HEADERS)
    assert response.status_code == 200

    after = client.get(f"/api/v1/orders/{order_id}", headers=HEADERS).json()
    assert after["patient_id"] == before["patient_id"]
    assert after["items"] == before["items"]
    assert after["total_price"] == before["total_price"]
    with db_session_factory() as session:
        specimens = session.scalars(select(Specimen).where(Specimen.order_id == order_id)).all()
        assert len(specimens) == 1


@pytest.mark.integration
def test_collection_rejects_ineligible_orders_and_inactive_types_without_persistence(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        specimen_type = session.get(SpecimenType, serum_id)
        assert specimen_type is not None
        specimen_type.is_active = False
        session.commit()

    inactive = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert inactive.status_code == 422
    with db_session_factory() as session:
        assert session.scalars(select(Specimen).where(Specimen.order_id == order_id)).all() == []
        order = session.get(LabOrder, order_id)
        assert order is not None
        order.status = OrderStatus.CANCELLED
        session.commit()

    cancelled = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert cancelled.status_code == 422
    with db_session_factory() as session:
        assert session.scalars(select(Specimen).where(Specimen.order_id == order_id)).all() == []


@pytest.mark.integration
def test_order_detail_shows_collected_specimen_and_collection_requires_role(
    client: TestClient,
) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)
    forbidden = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers={"X-Role": "RECEPTION", "X-Actor": "reception-1"},
    )
    assert forbidden.status_code == 403
    collected = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    )
    assert collected.status_code == 201
    detail = client.get(f"/orders/{order_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert "Specimens" in detail.text
    assert collected.json()["accession_number"] in detail.text


@pytest.mark.integration
def test_specimen_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'specimens.sqlite3').as_posix()}"
    config = _alembic_config(database_url)
    command.upgrade(config, "head")

    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    assert {"specimens", "specimen_items"}.issubset(inspector.get_table_names())
    assert {"ix_specimens_order_id", "ix_specimens_order_status"}.issubset(
        index["name"] for index in inspector.get_indexes("specimens")
    )
    assert {"ix_specimen_items_specimen_id", "ix_specimen_items_order_item_id"}.issubset(
        index["name"] for index in inspector.get_indexes("specimen_items")
    )
    engine.dispose()

    command.downgrade(config, "20261007_0006")
    engine = sa.create_engine(database_url)
    assert {"specimens", "specimen_items"}.isdisjoint(sa.inspect(engine).get_table_names())
    engine.dispose()


@pytest.mark.integration
def test_collection_rolls_back_when_persistence_fails(
    client: TestClient, db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        service = SpecimenService(session)

        def fail_audit(_: AuditLog) -> AuditLog:
            raise IntegrityError("INSERT audit_logs", {}, Exception("forced failure"))

        monkeypatch.setattr(service.audit_repository, "add", fail_audit)
        with pytest.raises(InvalidSpecimenOperationError, match="could not be saved"):
            service.collect(
                SpecimenCollectRequest(order_id=order_id, specimen_type_id=serum_id),
                actor_reference="collector-1",
            )
        assert session.scalars(select(Specimen).where(Specimen.order_id == order_id)).all() == []


@pytest.mark.integration
def test_receiving_queue_receipt_and_final_order_status(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, serum_id, urine_id, _ = create_collection_order(client)
    serum = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": serum_id},
        headers=HEADERS,
    ).json()
    queue = client.get("/api/v1/specimens/receiving-queue", headers=HEADERS)
    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [serum["id"]]
    received = client.patch(
        f"/api/v1/specimens/{serum['id']}/receipt",
        json={"receiving_note": "  sealed  "},
        headers=HEADERS,
    )
    assert received.status_code == 200
    assert received.json()["status"] == "RECEIVED"
    assert received.json()["received_by"] == "collector-1"
    assert received.json()["receiving_note"] == "sealed"
    duplicate = client.patch(f"/api/v1/specimens/{serum['id']}/receipt", json={}, headers=HEADERS)
    assert duplicate.status_code == 422
    urine = client.post(
        "/api/v1/specimens",
        json={"order_id": order_id, "specimen_type_id": urine_id},
        headers=HEADERS,
    ).json()
    final_receipt = client.patch(
        f"/api/v1/specimens/{urine['id']}/receipt", json={}, headers=HEADERS
    )
    assert final_receipt.status_code == 200
    with db_session_factory() as session:
        order = session.get(LabOrder, order_id)
        assert order is not None
        assert order.status == OrderStatus.SPECIMENS_RECEIVED


@pytest.mark.integration
def test_web_datetime_local_uses_bangkok_but_api_remains_utc(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    order_id, serum_id, _, _ = create_collection_order(client)

    naive_api = client.post(
        "/api/v1/specimens",
        json={
            "order_id": order_id,
            "specimen_type_id": serum_id,
            "collected_at": "2026-10-28T14:30",
        },
        headers=HEADERS,
    )
    assert naive_api.status_code == 422
    assert "timezone offset is required" in naive_api.text

    collected = client.post(
        f"/orders/{order_id}/specimens/{serum_id}/collect",
        data={"collected_at": "2026-10-28T14:30"},
        headers=HEADERS,
        follow_redirects=False,
    )
    assert collected.status_code == 303
    with db_session_factory() as session:
        specimen = session.scalars(
            select(Specimen).where(
                Specimen.order_id == order_id,
                Specimen.specimen_type_id == serum_id,
            )
        ).one()
        specimen_id = specimen.id
        assert specimen.collected_at.isoformat() == "2026-10-28T07:30:00+00:00"

    collection_page = client.get(collected.headers["location"], headers=HEADERS)
    assert collection_page.status_code == 200
    assert "28/10/2026 14:30 (+07:00)" in collection_page.text
    assert "Timezone: Asia/Bangkok" in collection_page.text

    received = client.post(
        f"/specimens/receiving/{specimen_id}/receipt",
        data={"received_at": "2026-10-28T15:00"},
        headers=HEADERS,
        follow_redirects=False,
    )
    assert received.status_code == 303
    with db_session_factory() as session:
        specimen = session.get(Specimen, specimen_id)
        assert specimen is not None
        assert specimen.received_at is not None
        assert specimen.received_at.isoformat() == "2026-10-28T08:00:00+00:00"

    detail = client.get(f"/orders/{order_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert "28/10/2026 15:00 (+07:00)" in detail.text
