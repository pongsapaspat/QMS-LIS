import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.result import Result
from app.services.result import ResultService
from tests.integration.test_specimens import ADMIN_HEADERS, HEADERS, create_collection_order

SUPERVISOR = {"X-Role": "LAB_SUPERVISOR", "X-Actor": "label-reviewer"}


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["QUALITATIVE", "CATEGORICAL"])
def test_labels_survive_catalog_edits_and_flow_through_review_and_report(
    client,
    db_session_factory,
    kind,
):
    original_id, serum, _, _ = create_collection_order(client)
    patient_id = client.get(f"/api/v1/orders/{original_id}", headers=HEADERS).json()["patient_id"]
    test = client.post(
        "/api/v1/tests",
        headers=ADMIN_HEADERS,
        json={
            "code": "HIV",
            "name_th": "HIV",
            "name_en": "HIV Ag/Ab",
            "category_id": 1,
            "department_id": 1,
            "specimen_type_id": serum,
            "current_price": "100",
            "tat_minutes": 30,
            "result_type": kind,
        },
    )
    assert test.status_code == 201
    test_id = test.json()["id"]
    options_url = f"/api/v1/tests/{test_id}/qualitative-options"
    option = client.post(
        options_url,
        headers=ADMIN_HEADERS,
        json={
            "code": "T-151",
            "label_th": "ไม่พบปฏิกิริยา",
            "label_en": "Non-reactive",
            "reason": "Lab wording",
        },
    )
    assert option.status_code == 201
    order = client.post(
        "/api/v1/orders",
        headers=HEADERS,
        json={
            "patient_id": patient_id,
            "test_ids": [test_id],
        },
    ).json()
    order_id = order["id"]
    specimen = client.post(
        "/api/v1/specimens",
        headers=HEADERS,
        json={
            "order_id": order_id,
            "specimen_type_id": serum,
        },
    ).json()
    assert (
        client.patch(
            f"/api/v1/specimens/{specimen['id']}/receipt", headers=HEADERS, json={}
        ).status_code
        == 200
    )
    context_url = f"/api/v1/results/orders/{order_id}"
    item_id = client.get(context_url, headers=HEADERS).json()["items"][0]["order_item_id"]
    saved = client.post(
        context_url,
        headers=HEADERS,
        json={
            "items": [
                {
                    "order_item_id": item_id,
                    "categorical_value": "T-151",
                    "complete": True,
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    result_id = saved.json()[0]["id"]
    assert saved.json()[0]["categorical_value"] == "T-151"
    assert saved.json()[0]["categorical_label_snapshot"]["label_en"] == "Non-reactive"
    assert (
        client.patch(
            f"{options_url}/{option.json()['id']}",
            headers=ADMIN_HEADERS,
            json={"label_en": "Changed wording", "reason": "Catalog edit"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"{options_url}/{option.json()['id']}/activation",
            headers=ADMIN_HEADERS,
            json={"is_active": False, "reason": "Retired"},
        ).status_code
        == 200
    )
    page = client.get(f"/results/verification/orders/{order_id}", headers=SUPERVISOR)
    assert "Non-reactive" in page.text
    assert "Changed wording" not in page.text
    with db_session_factory() as session:
        result = session.get(Result, result_id)
        # A legacy row without a snapshot resolves even an inactive option.
        result.categorical_label_snapshot = None
        assert ResultService._result_value(result) == "Changed wording"
        result.categorical_value = "MISSING"
        assert ResultService._result_value(result) == "MISSING"
        session.rollback()
    assert (
        client.patch(f"/api/v1/results/{result_id}/verify", headers=SUPERVISOR, json={}).status_code
        == 200
    )
    preview = client.get(f"/results/release/orders/{order_id}", headers=SUPERVISOR)
    assert preview.status_code == 200
    assert "Non-reactive" in preview.text
    assert (
        client.patch(f"/api/v1/orders/{order_id}/release", headers=SUPERVISOR, json={}).status_code
        == 200
    )
    report = client.get(f"/results/reports/orders/{order_id}", headers=SUPERVISOR)
    assert report.status_code == 200
    assert "Non-reactive" in report.text
    with db_session_factory() as session:
        report_data = ResultService(session).report_context(order_id, actor_reference="reviewer")
        assert report_data["results"][0]["result_value"] == "Non-reactive"


@pytest.mark.integration
def test_label_migration_backfills_matching_test_only(monkeypatch):
    migration = importlib.import_module(
        "migrations.versions.20261121_0018_categorical_label_snapshot"
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE results (id INTEGER, order_item_id INTEGER, categorical_value TEXT)"
        )
        connection.exec_driver_sql("CREATE TABLE lab_order_items (id INTEGER, lab_test_id INTEGER)")
        connection.exec_driver_sql(
            "CREATE TABLE qualitative_result_options "
            "(test_id INTEGER, code TEXT, label_th TEXT, label_en TEXT)"
        )
        connection.exec_driver_sql("INSERT INTO lab_order_items VALUES (1, 10), (2, 20)")
        connection.exec_driver_sql(
            "INSERT INTO results VALUES (1, 1, 'X'), (2, 2, 'X'), (3, 1, 'UNKNOWN')"
        )
        connection.exec_driver_sql(
            "INSERT INTO qualitative_result_options VALUES "
            "(10, 'X', 'Label TH', 'First'), (20, 'X', 'Other TH', 'Second')"
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        table = sa.Table("results", sa.MetaData(), autoload_with=connection)
        rows = connection.execute(sa.select(table).order_by(table.c.id)).mappings().all()
        assert rows[0]["categorical_label_snapshot"]["label_en"] == "First"
        assert rows[1]["categorical_label_snapshot"]["label_en"] == "Second"
        assert rows[2]["categorical_label_snapshot"] is None
    engine.dispose()
