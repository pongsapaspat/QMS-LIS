import pytest
from sqlalchemy import func, select

from app.models import AuditLog, LabTest, LabTestDraft, SpecimenType
from app.models import TestPriceHistory as PriceHistory
from app.repositories.test_catalog import TestCatalogRepository as CatalogRepository
from app.services.test_catalog import TestCatalogService as CatalogService
from tests.integration.test_test_catalog_web import (
    ADMIN_HEADERS,
    TECH_HEADERS,
    create_web_masters,
    web_test_payload,
)

PANEL_NAME = "Stool Viral Panel (Rota/Adeno/Noro)"


@pytest.mark.integration
def test_name_only_outlab_draft_can_be_completed_once(client, db_session_factory):
    with db_session_factory() as session:
        draft = CatalogService(session).create_test_draft(
            PANEL_NAME, is_outlab=True, actor_reference="catalog-admin"
        )
        draft_id = draft.id
        assert session.scalar(select(func.count(LabTest.id))) == 0
        assert session.scalar(select(func.count(SpecimenType.id))) == 0

    url = f"/test-catalog/new?draft_id={draft_id}"
    listing = client.get("/test-catalog", headers=ADMIN_HEADERS)
    assert PANEL_NAME in listing.text
    assert "เพิ่มรายละเอียด" in listing.text
    assert PANEL_NAME not in client.get("/orders/new", headers=ADMIN_HEADERS).text
    assert client.get(url, headers=TECH_HEADERS).status_code == 403
    assert client.post(url, headers=TECH_HEADERS).status_code == 403
    form = client.get(url, headers=ADMIN_HEADERS)
    assert form.status_code == 200
    assert f'value="{PANEL_NAME}"' in form.text
    assert 'name="is_outlab" value="on" checked' in form.text
    for field in ("code", "current_price", "tat_minutes", "outlab_lab_name"):
        assert f'name="{field}"' in form.text
    invalid = client.post(url, data={"name_en": PANEL_NAME}, headers=ADMIN_HEADERS)
    assert invalid.status_code == 422
    assert "รอกรอกรายละเอียด" in invalid.text

    category_id, specimen_id = create_web_masters(client)
    payload = web_test_payload(
        category_id, specimen_id, code="STOOL-VIRAL", name_th=PANEL_NAME,
        name_en=PANEL_NAME, result_type="TEXT", result_unit="", is_outlab="on",
        outlab_lab_name="Example reference lab", current_price="650", tat_minutes="1440",
    )
    created = client.post(url, data=payload, headers=ADMIN_HEADERS, follow_redirects=False)
    assert created.status_code == 303
    detail_url = created.headers["location"]
    assert PANEL_NAME in client.get(detail_url, headers=ADMIN_HEADERS).text
    assert "รายการรอกรอกรายละเอียด" not in client.get(
        "/test-catalog", headers=ADMIN_HEADERS
    ).text
    old_link = client.get(url, headers=ADMIN_HEADERS, follow_redirects=False)
    assert old_link.status_code == 303
    assert old_link.headers["location"] == detail_url
    stale = client.post(
        url, data={**payload, "code": "OTHER-CODE"}, headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert stale.status_code == 422
    with db_session_factory() as session:
        test = session.scalar(select(LabTest))
        assert test.is_outlab and test.is_active
        assert test.specimen_type_id == specimen_id
        assert session.get(LabTestDraft, draft_id).completed_test_id == test.id
        assert session.scalar(select(func.count(LabTest.id))) == 1
        assert session.scalar(select(func.count(PriceHistory.id))) == 1
        assert session.scalar(select(AuditLog.id).where(
            AuditLog.event_type == "LAB_TEST_DRAFT_COMPLETED"
        )) is not None


@pytest.mark.integration
def test_draft_completion_conflict_rolls_back_new_test(
    client, db_session_factory, monkeypatch
):
    category_id, specimen_id = create_web_masters(client)
    with db_session_factory() as session:
        draft_id = CatalogService(session).create_test_draft(
            PANEL_NAME, is_outlab=True, actor_reference="catalog-admin"
        ).id
    # Another administrator completes the draft while this form is open.
    monkeypatch.setattr(CatalogRepository, "complete_test_draft", lambda *args: False)
    response = client.post(
        f"/test-catalog/new?draft_id={draft_id}",
        data=web_test_payload(
            category_id, specimen_id, result_type="TEXT", result_unit="",
            is_outlab="on", outlab_lab_name="Example reference lab",
        ),
        headers=ADMIN_HEADERS,
        follow_redirects=False,
    )
    assert response.status_code == 422
    with db_session_factory() as session:
        assert session.scalar(select(func.count(LabTest.id))) == 0
        assert session.scalar(select(func.count(PriceHistory.id))) == 0
        assert session.get(LabTestDraft, draft_id).completed_test_id is None
        assert session.scalar(select(AuditLog.id).where(
            AuditLog.event_type == "LAB_TEST_CREATED"
        )) is None
