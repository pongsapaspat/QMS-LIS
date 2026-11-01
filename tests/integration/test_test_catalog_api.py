import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit import AuditLog

ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "catalog-admin"}
READER_HEADERS = {"X-Role": "LAB_TECH", "X-Actor": "tech-1"}


def create_configuration(client: TestClient, path: str, code: str) -> dict[str, object]:
    response = client.post(
        path,
        json={
            "code": code,
            "name_th": f"Thai {code}",
            "name_en": f"English {code}",
            "reason": "initial catalog setup",
        },
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_masters(client: TestClient) -> tuple[int, int]:
    category = create_configuration(client, "/api/v1/test-categories", "CHEM")
    specimen = create_configuration(client, "/api/v1/specimen-types", "SERUM")
    return int(category["id"]), int(specimen["id"])


def catalog_test_payload(
    category_id: int, specimen_type_id: int, **overrides: object
) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": "GLU",
        "name_th": "Glucose Thai",
        "name_en": "Glucose",
        "category_id": category_id,
        "department_id": 1,
        "specimen_type_id": specimen_type_id,
        "current_price": "100.00",
        "result_type": "NUMERIC",
        "result_unit": "mg/dL",
        "tat_minutes": 60,
        "reason": "initial test setup",
    }
    payload.update(overrides)
    return payload


def create_department(client: TestClient, code: str = "CHEMISTRY") -> dict[str, object]:
    response = client.post(
        "/api/v1/departments",
        json={
            "code": code,
            "name_th": "เคมีคลินิก",
            "name_en": "Clinical Chemistry",
            "reason": "laboratory organization",
        },
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
def test_department_api_crud_search_activation_and_validation(client: TestClient) -> None:
    department = create_department(client)
    assert department["code"] == "CHEMISTRY"
    assert department["test_count"] == 0

    duplicate = client.post(
        "/api/v1/departments",
        json={"code": "chemistry", "name_th": "ซ้ำ", "name_en": "Duplicate"},
        headers=ADMIN_HEADERS,
    )
    assert duplicate.status_code == 409
    invalid = client.post(
        "/api/v1/departments",
        json={"code": "bad code!", "name_th": "ผิด", "name_en": "Invalid"},
        headers=ADMIN_HEADERS,
    )
    assert invalid.status_code == 422
    unknown = client.post(
        "/api/v1/departments",
        json={
            "code": "HEMATOLOGY",
            "name_th": "โลหิตวิทยา",
            "name_en": "Hematology",
            "unexpected": True,
        },
        headers=ADMIN_HEADERS,
    )
    assert unknown.status_code == 422

    searched = client.get(
        "/api/v1/departments", params={"search": "clinical"}, headers=READER_HEADERS
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1

    updated = client.patch(
        f"/api/v1/departments/{department['id']}",
        json={"name_en": "Chemistry", "reason": "shorten display name"},
        headers=ADMIN_HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["name_en"] == "Chemistry"

    deactivated = client.patch(
        f"/api/v1/departments/{department['id']}/activation",
        json={"is_active": False, "reason": "temporary closure"},
        headers=ADMIN_HEADERS,
    )
    assert deactivated.status_code == 200
    inactive = client.get(
        "/api/v1/departments", params={"is_active": False}, headers=READER_HEADERS
    )
    assert inactive.json()["total"] == 1
    assert client.patch(
        f"/api/v1/departments/{department['id']}/activation",
        json={"is_active": True, "reason": "reopen"},
        headers=READER_HEADERS,
    ).status_code == 403
    assert client.get("/api/v1/departments/9999", headers=READER_HEADERS).status_code == 404


@pytest.mark.integration
def test_department_assignment_filter_inactive_history_and_audit(client: TestClient) -> None:
    category_id, specimen_id = create_masters(client)
    department = create_department(client)
    department_id = int(department["id"])
    created = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(
            category_id, specimen_id, department_id=department_id
        ),
        headers=ADMIN_HEADERS,
    )
    assert created.status_code == 201, created.text
    test_id = created.json()["id"]
    assert created.json()["department"]["code"] == "CHEMISTRY"
    filtered = client.get(
        "/api/v1/tests", params={"department_id": department_id}, headers=READER_HEADERS
    )
    assert filtered.json()["total"] == 1

    assert client.patch(
        f"/api/v1/departments/{department_id}/activation",
        json={"is_active": False, "reason": "temporary closure"},
        headers=ADMIN_HEADERS,
    ).status_code == 200
    detail = client.get(f"/api/v1/tests/{test_id}", headers=READER_HEADERS)
    assert detail.json()["test"]["department"]["is_active"] is False
    blocked = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(
            category_id, specimen_id, code="ALT", department_id=department_id
        ),
        headers=ADMIN_HEADERS,
    )
    assert blocked.status_code == 422

    replacement = create_department(client, "HEMATOLOGY")
    changed = client.patch(
        f"/api/v1/tests/{test_id}",
        json={
            "department_id": replacement["id"],
            "reason": "move test to responsible section",
        },
        headers=ADMIN_HEADERS,
    )
    assert changed.status_code == 200
    audit = client.get(f"/api/v1/tests/{test_id}", headers=READER_HEADERS).json()[
        "audit_history"
    ]
    assert audit[0]["event_type"] == "LAB_TEST_DEPARTMENT_CHANGED"


@pytest.mark.integration
def test_master_data_crud_duplicate_codes_and_inactive_filtering(client: TestClient) -> None:
    category = create_configuration(client, "/api/v1/test-categories", "CHEM")

    duplicate = client.post(
        "/api/v1/test-categories",
        json={
            "code": "chem",
            "name_th": "Duplicate",
            "name_en": "Duplicate",
            "reason": "duplicate check",
        },
        headers=ADMIN_HEADERS,
    )
    assert duplicate.status_code == 409

    updated = client.patch(
        f"/api/v1/test-categories/{category['id']}",
        json={"name_en": "Clinical Chemistry", "reason": "clarify display name"},
        headers=ADMIN_HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["name_en"] == "Clinical Chemistry"

    deactivated = client.patch(
        f"/api/v1/test-categories/{category['id']}",
        json={"is_active": False, "reason": "retire unused category"},
        headers=ADMIN_HEADERS,
    )
    assert deactivated.status_code == 200
    assert client.get("/api/v1/test-categories", headers=READER_HEADERS).json() == []
    all_categories = client.get(
        "/api/v1/test-categories",
        params={"include_inactive": True},
        headers=READER_HEADERS,
    )
    assert all_categories.status_code == 200
    assert all_categories.json()[0]["is_active"] is False


@pytest.mark.integration
def test_inactive_master_data_cannot_be_used(client: TestClient) -> None:
    category_id, specimen_id = create_masters(client)
    response = client.patch(
        f"/api/v1/specimen-types/{specimen_id}",
        json={"is_active": False, "reason": "temporarily unavailable"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200

    blocked = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(category_id, specimen_id),
        headers=ADMIN_HEADERS,
    )
    assert blocked.status_code == 404
    assert "active specimen type" in blocked.json()["detail"]


@pytest.mark.integration
def test_numeric_and_qualitative_constraints(client: TestClient) -> None:
    category_id, specimen_id = create_masters(client)
    missing_unit = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(category_id, specimen_id, result_unit=None),
        headers=ADMIN_HEADERS,
    )
    assert missing_unit.status_code == 422

    qualitative_with_unit = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(
            category_id,
            specimen_id,
            code="HCG",
            result_type="QUALITATIVE",
            result_unit="positive",
        ),
        headers=ADMIN_HEADERS,
    )
    assert qualitative_with_unit.status_code == 422

    numeric = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(category_id, specimen_id),
        headers=ADMIN_HEADERS,
    ).json()
    duplicate_test = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(category_id, specimen_id, code="glu"),
        headers=ADMIN_HEADERS,
    )
    assert duplicate_test.status_code == 409

    option_on_numeric = client.post(
        f"/api/v1/tests/{numeric['id']}/qualitative-options",
        json={
            "code": "POS",
            "label_th": "Positive Thai",
            "label_en": "Positive",
            "reason": "add result choice",
        },
        headers=ADMIN_HEADERS,
    )
    assert option_on_numeric.status_code == 422

    qualitative = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(
            category_id,
            specimen_id,
            code="HCG",
            result_type="QUALITATIVE",
            result_unit=None,
        ),
        headers=ADMIN_HEADERS,
    ).json()
    range_on_qualitative = client.post(
        f"/api/v1/tests/{qualitative['id']}/reference-ranges",
        json={
            "minimum_age": 0,
            "maximum_age": 120,
            "lower_value": "0",
            "upper_value": "1",
            "reason": "invalid range attempt",
        },
        headers=ADMIN_HEADERS,
    )
    assert range_on_qualitative.status_code == 422

    first_option = client.post(
        f"/api/v1/tests/{qualitative['id']}/qualitative-options",
        json={
            "code": "POS",
            "label_th": "Positive Thai",
            "label_en": "Positive",
            "reason": "add result choice",
        },
        headers=ADMIN_HEADERS,
    )
    assert first_option.status_code == 201
    duplicate_option = client.post(
        f"/api/v1/tests/{qualitative['id']}/qualitative-options",
        json={
            "code": "pos",
            "label_th": "Other",
            "label_en": "Other",
            "reason": "duplicate result choice",
        },
        headers=ADMIN_HEADERS,
    )
    assert duplicate_option.status_code == 409


@pytest.mark.integration
def test_reference_range_creation_and_merged_update_validation(client: TestClient) -> None:
    category_id, specimen_id = create_masters(client)
    test = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(category_id, specimen_id),
        headers=ADMIN_HEADERS,
    ).json()

    invalid_create = client.post(
        f"/api/v1/tests/{test['id']}/reference-ranges",
        json={
            "minimum_age": 20,
            "maximum_age": 10,
            "lower_value": "70",
            "upper_value": "110",
            "reason": "invalid bounds test",
        },
        headers=ADMIN_HEADERS,
    )
    assert invalid_create.status_code == 422

    created = client.post(
        f"/api/v1/tests/{test['id']}/reference-ranges",
        json={
            "sex": "ALL",
            "minimum_age": 18,
            "maximum_age": 65,
            "age_unit": "YEARS",
            "lower_value": "70",
            "upper_value": "110",
            "lower_critical": "40",
            "upper_critical": "500",
            "reason": "adult reference interval",
        },
        headers=ADMIN_HEADERS,
    )
    assert created.status_code == 201
    range_id = created.json()["id"]

    invalid_partial = client.patch(
        f"/api/v1/tests/{test['id']}/reference-ranges/{range_id}",
        json={"lower_value": "120", "reason": "invalid partial update"},
        headers=ADMIN_HEADERS,
    )
    assert invalid_partial.status_code == 422
    assert "lower reference" in invalid_partial.json()["detail"]

    deactivated = client.patch(
        f"/api/v1/tests/{test['id']}/reference-ranges/{range_id}/activation",
        json={"is_active": False, "reason": "temporarily retire interval"},
        headers=ADMIN_HEADERS,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    reactivated = client.patch(
        f"/api/v1/tests/{test['id']}/reference-ranges/{range_id}/activation",
        json={"is_active": True, "reason": "restore validated interval"},
        headers=ADMIN_HEADERS,
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


@pytest.mark.integration
def test_price_history_audit_privacy_noop_and_detail(client: TestClient) -> None:
    category_id, specimen_id = create_masters(client)
    created = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(category_id, specimen_id),
        headers=ADMIN_HEADERS,
    ).json()
    test_id = created["id"]

    same_price = client.patch(
        f"/api/v1/tests/{test_id}",
        json={
            "name_en": "Blood Glucose",
            "current_price": "100.00",
            "reason": "improve display name",
        },
        headers=ADMIN_HEADERS,
    )
    assert same_price.status_code == 200

    price_change = client.patch(
        f"/api/v1/tests/{test_id}",
        json={"current_price": "125.50", "reason": "annual price review"},
        headers=ADMIN_HEADERS,
    )
    assert price_change.status_code == 200

    noop = client.patch(
        f"/api/v1/tests/{test_id}",
        json={"current_price": "125.50", "reason": "attempted duplicate update"},
        headers=ADMIN_HEADERS,
    )
    assert noop.status_code == 422

    detail_response = client.get(f"/api/v1/tests/{test_id}", headers=READER_HEADERS)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["test"]["current_price"] == "125.50"
    assert len(detail["price_history"]) == 2
    assert detail["price_history"][0]["old_price"] == "100.00"
    assert detail["price_history"][0]["new_price"] == "125.50"
    assert [entry["event_type"] for entry in detail["audit_history"]] == [
        "LAB_TEST_UPDATED",
        "LAB_TEST_UPDATED",
        "LAB_TEST_CREATED",
    ]
    assert detail["audit_history"][0]["changed_fields"] == ["current_price"]
    assert detail["audit_history"][0]["reason"] == "annual price review"
    assert detail["audit_history"][0]["actor_reference"] == "catalog-admin"

    audit_text = str(detail["audit_history"])
    assert "125.50" not in audit_text
    assert "Blood Glucose" not in audit_text


@pytest.mark.integration
def test_listing_filtering_pagination_not_found_and_authorization(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    category_id, specimen_id = create_masters(client)
    for code, name, result_type, unit in (
        ("GLU", "Glucose", "NUMERIC", "mg/dL"),
        ("HCG", "Pregnancy", "QUALITATIVE", None),
        ("ALT", "Alanine", "NUMERIC", "U/L"),
    ):
        response = client.post(
            "/api/v1/tests",
            json=catalog_test_payload(
                category_id,
                specimen_id,
                code=code,
                name_en=name,
                result_type=result_type,
                result_unit=unit,
            ),
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 201

    page = client.get(
        "/api/v1/tests",
        params={"result_type": "NUMERIC", "page": 1, "page_size": 1},
        headers=READER_HEADERS,
    )
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1

    searched = client.get("/api/v1/tests", params={"search": "preg"}, headers=READER_HEADERS)
    assert searched.status_code == 200
    assert searched.json()["items"][0]["code"] == "HCG"

    assert client.get("/api/v1/tests/9999", headers=READER_HEADERS).status_code == 404
    forbidden = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(category_id, specimen_id, code="AST"),
        headers=READER_HEADERS,
    )
    assert forbidden.status_code == 403

    with db_session_factory() as session:
        audits = list(session.scalars(select(AuditLog)))
    assert audits
    assert all(isinstance(entry.changed_fields, list) for entry in audits)


@pytest.mark.integration
def test_catalog_activation_and_qualitative_option_update(client: TestClient) -> None:
    category_id, specimen_id = create_masters(client)
    qualitative = client.post(
        "/api/v1/tests",
        json=catalog_test_payload(
            category_id,
            specimen_id,
            code="HCG",
            result_type="QUALITATIVE",
            result_unit=None,
        ),
        headers=ADMIN_HEADERS,
    ).json()
    test_id = qualitative["id"]
    option = client.post(
        f"/api/v1/tests/{test_id}/qualitative-options",
        json={
            "code": "POS",
            "label_th": "Positive Thai",
            "label_en": "Positive",
            "reason": "add result choice",
        },
        headers=ADMIN_HEADERS,
    ).json()

    updated = client.patch(
        f"/api/v1/tests/{test_id}/qualitative-options/{option['id']}",
        json={"label_en": "Detected", "reason": "align result wording"},
        headers=ADMIN_HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["label_en"] == "Detected"

    option_deactivated = client.patch(
        f"/api/v1/tests/{test_id}/qualitative-options/{option['id']}/activation",
        json={"is_active": False, "reason": "temporarily retire choice"},
        headers=ADMIN_HEADERS,
    )
    assert option_deactivated.status_code == 200
    assert option_deactivated.json()["is_active"] is False

    test_deactivated = client.patch(
        f"/api/v1/tests/{test_id}/activation",
        json={"is_active": False, "reason": "temporarily retire test"},
        headers=ADMIN_HEADERS,
    )
    assert test_deactivated.status_code == 200
    assert test_deactivated.json()["is_active"] is False
    no_op = client.patch(
        f"/api/v1/tests/{test_id}/activation",
        json={"is_active": False, "reason": "duplicate state request"},
        headers=ADMIN_HEADERS,
    )
    assert no_op.status_code == 422

    reactivated = client.patch(
        f"/api/v1/tests/{test_id}/activation",
        json={"is_active": True, "reason": "return test to service"},
        headers=ADMIN_HEADERS,
    )
    assert reactivated.status_code == 200
    detail = client.get(f"/api/v1/tests/{test_id}", headers=READER_HEADERS).json()
    event_types = {entry["event_type"] for entry in detail["audit_history"]}
    assert {
        "QUALITATIVE_OPTION_CREATED",
        "QUALITATIVE_OPTION_UPDATED",
        "QUALITATIVE_OPTION_DEACTIVATED",
        "LAB_TEST_DEACTIVATED",
        "LAB_TEST_ACTIVATED",
    }.issubset(event_types)
