import pytest
from fastapi.testclient import TestClient

ADMIN_HEADERS = {"X-Role": "ADMIN", "X-Actor": "web-admin"}
TECH_HEADERS = {"X-Role": "LAB_TECH", "X-Actor": "web-tech"}


def web_configuration_payload(code: str) -> dict[str, str]:
    return {
        "code": code,
        "name_th": f"Thai {code}",
        "name_en": f"English {code}",
        "reason": "web administration setup",
    }


def create_web_masters(client: TestClient) -> tuple[int, int]:
    category = client.post(
        "/test-catalog/categories/new",
        data=web_configuration_payload("CHEM"),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    specimen = client.post(
        "/test-catalog/specimen-types/new",
        data=web_configuration_payload("SERUM"),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert category.status_code == 303
    assert specimen.status_code == 303

    category_id = client.get("/api/v1/test-categories", headers=ADMIN_HEADERS).json()[0]["id"]
    specimen_id = client.get("/api/v1/specimen-types", headers=ADMIN_HEADERS).json()[0]["id"]
    return category_id, specimen_id


def web_test_payload(category_id: int, specimen_id: int, **overrides: object) -> dict[str, str]:
    payload = {
        "code": "GLU",
        "name_th": "Glucose Thai",
        "name_en": "Glucose",
        "category_id": str(category_id),
        "department_id": "1",
        "specimen_type_id": str(specimen_id),
        "current_price": "0",
        "result_type": "NUMERIC",
        "result_unit": "mg/dL",
        "tat_minutes": "30",
        "reason": "web test setup",
    }
    payload.update({key: str(value) for key, value in overrides.items()})
    return payload


@pytest.mark.integration
def test_department_web_navigation_crud_search_and_detail(client: TestClient) -> None:
    listing = client.get("/test-catalog", headers=ADMIN_HEADERS)
    assert "Departments" in listing.text
    assert "แผนกห้องปฏิบัติการ" in listing.text
    created = client.post(
        "/test-catalog/departments/new",
        data={
            "code": " chemistry ",
            "name_th": " เคมีคลินิก ",
            "name_en": " Clinical Chemistry ",
            "is_active": "on",
            "reason": "create section",
        },
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert created.status_code == 303
    detail = client.get(created.headers["location"], headers=ADMIN_HEADERS)
    assert detail.status_code == 200
    assert "CHEMISTRY" in detail.text
    assert "Timezone: Asia/Bangkok" not in detail.text
    searched = client.get(
        "/test-catalog/departments",
        params={"search": "clinical"},
        headers=ADMIN_HEADERS,
    )
    assert "CHEMISTRY" in searched.text
    invalid = client.post(
        "/test-catalog/departments/new",
        data={"code": "!", "name_th": "", "name_en": "Clinical Chemistry"},
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert invalid.status_code == 422
    assert 'value="!"' in invalid.text


@pytest.mark.integration
def test_catalog_navigation_list_form_and_non_admin_rejection(client: TestClient) -> None:
    home = client.get("/", headers=ADMIN_HEADERS)
    listing = client.get("/test-catalog", headers=ADMIN_HEADERS)
    new_form = client.get("/test-catalog/new", headers=ADMIN_HEADERS)

    assert home.status_code == 200
    assert "/test-catalog" in home.text
    assert listing.status_code == 200
    assert "Test Catalog" in listing.text
    assert new_form.status_code == 200
    assert 'name="current_price"' in new_form.text
    assert client.get("/test-catalog", headers=TECH_HEADERS).status_code == 403


@pytest.mark.integration
def test_web_create_edit_detail_and_validation_redisplay(client: TestClient) -> None:
    category_id, specimen_id = create_web_masters(client)
    invalid = client.post(
        "/test-catalog/new",
        data=web_test_payload(category_id, specimen_id, result_unit=""),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert invalid.status_code == 422
    assert "result unit is required" in invalid.text
    assert 'value="0"' in invalid.text

    created = client.post(
        "/test-catalog/new",
        data=web_test_payload(category_id, specimen_id),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert created.status_code == 303
    detail_url = created.headers["location"]
    detail = client.get(detail_url, headers=ADMIN_HEADERS)
    assert detail.status_code == 200
    assert "Glucose" in detail.text
    assert "Price history" in detail.text
    test_id = int(detail_url.rsplit("/", 1)[1])

    edited = client.post(
        f"/test-catalog/{test_id}/edit",
        data=web_test_payload(
            category_id,
            specimen_id,
            name_en="Blood Glucose",
            current_price="125.50",
            reason="web price review",
        ),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert edited.status_code == 303
    assert "Blood Glucose" in client.get(detail_url, headers=ADMIN_HEADERS).text


@pytest.mark.integration
def test_web_configuration_activation_and_numeric_range_management(
    client: TestClient,
) -> None:
    category_id, specimen_id = create_web_masters(client)
    category_edit = client.post(
        f"/test-catalog/categories/{category_id}/edit",
        data={
            "name_th": "Thai CHEM",
            "name_en": "Clinical Chemistry",
            "is_active": "on",
            "reason": "rename category",
        },
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert category_edit.status_code == 303

    created = client.post(
        "/test-catalog/new",
        data=web_test_payload(category_id, specimen_id),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    test_id = int(created.headers["location"].rsplit("/", 1)[1])
    range_form = client.get(f"/test-catalog/{test_id}/reference-ranges/new", headers=ADMIN_HEADERS)
    assert range_form.status_code == 200
    range_response = client.post(
        f"/test-catalog/{test_id}/reference-ranges/new",
        data={
            "sex": "ALL",
            "minimum_age": "0",
            "maximum_age": "120",
            "age_unit": "YEARS",
            "lower_value": "70",
            "upper_value": "110",
            "lower_critical": "40",
            "upper_critical": "500",
            "display_text": "Adult interval",
            "context_metadata": '{"source":"web"}',
            "reason": "add web reference range",
        },
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert range_response.status_code == 303
    detail = client.get(f"/test-catalog/{test_id}", headers=ADMIN_HEADERS)
    assert "Adult interval" in detail.text
    assert "Reference ranges" in detail.text

    deactivated = client.post(
        f"/test-catalog/{test_id}/activation",
        data={"is_active": "false", "reason": "retire web test"},
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert deactivated.status_code == 303


@pytest.mark.integration
def test_web_qualitative_option_management(client: TestClient) -> None:
    category_id, specimen_id = create_web_masters(client)
    created = client.post(
        "/test-catalog/new",
        data=web_test_payload(
            category_id,
            specimen_id,
            code="HCG",
            name_en="Pregnancy",
            result_type="QUALITATIVE",
            result_unit="",
        ),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert created.status_code == 303
    test_id = int(created.headers["location"].rsplit("/", 1)[1])
    option = client.post(
        f"/test-catalog/{test_id}/qualitative-options/new",
        data={
            "code": "POS",
            "label_th": "Positive",
            "label_en": "Positive",
            "sort_order": "0",
            "reason": "add web option",
        },
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert option.status_code == 303
    detail = client.get(f"/test-catalog/{test_id}", headers=ADMIN_HEADERS)
    assert "Qualitative options" in detail.text
    assert "Positive" in detail.text
