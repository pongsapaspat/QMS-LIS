from datetime import UTC, date, datetime
from types import SimpleNamespace as Obj

import pytest

from app.core.config import Settings
from app.domain.panels import panel_definitions
from app.services.report_layout import prepare_report
from app.services.report_pdf import build_lab_report_pdf


def sample_report():
    when = datetime(2026, 11, 20, 18, 2, 33, tzinfo=UTC)
    order = Obj(
        order_number="ORD-SAMPLE-001",
        ordered_at=when,
        clinical_note=None,
        released_by="supervisor",
        released_at=when,
        priority="ROUTINE",
        package_snapshots=None,
    )
    patient = Obj(
        display_name="ผู้ป่วยตัวอย่าง", hn="HN-SAMPLE", sex="female", date_of_birth=date(2000, 11, 21)
    )
    specimens = [
        Obj(
            id=i,
            accession_number=f"SPC-SAMPLE-{i}",
            specimen_type_name_en=name,
            collected_at=when,
            received_at=when,
        )
        for i, name in [(1, "Plasma"), (2, "Urine")]
    ]
    chemistry = dict(
        result_id=1,
        test_code="T-03",
        test_name="Glucose",
        result_type="NUMERIC",
        category_name="เคมี",
        category_name_en="Chemical",
        department_code="GENERAL",
        department_name="ทั่วไป",
        specimen=specimens[0],
        entered_by="medtech",
        entered_at=when,
        result_value="89",
        unit="mg/dL",
        reference_text="70–110",
        abnormal_flag="N",
        parameters=[],
    )
    parameters = [
        {**p, "value": p["reference"] or "-", "flag": "N"} for p in panel_definitions("UA")
    ]
    parameters[2]["value"] = "1.003"
    parameters[3]["value"] = "6"
    ua = {
        **chemistry,
        "result_id": 2,
        "test_code": "T-02",
        "test_name": "UA",
        "result_type": "UA",
        "category_name": "ปัสสาวะ",
        "category_name_en": "UA",
        "specimen": specimens[1],
        "parameters": parameters,
    }
    return prepare_report(
        dict(
            order=order,
            patient=patient,
            results=[chemistry, ua],
            reported_by="medtech",
            reported_at=when,
            outlab_cases=[],
        ),
        Settings(),
    )


def test_sections_match_specimens_and_age_at_local_order_date():
    context = sample_report()
    chemistry, ua = context["sections"]
    assert chemistry["subtitle"] == "Clinical Chemistry"
    assert ua["subtitle"] == "Urinalysis"
    assert [s.id for s in chemistry["specimens"]] == [1]
    assert [s.id for s in ua["specimens"]] == [2]
    assert len(ua["results"][0]["parameters"]) == 18
    assert context["patient_age"] == 26  # Birthday in Bangkok, previous day in UTC.


def test_report_pdf_has_separate_complete_pages_and_escapes_text():
    fitz = pytest.importorskip("pymupdf")
    context = sample_report()
    context["patient"].display_name = "ตัวอย่าง <test> & sample"
    pdf = fitz.open(stream=build_lab_report_pdf(context), filetype="pdf")
    embedded_fonts = {font[3].split("+")[-1] for font in pdf[0].get_fonts()}
    assert {"THSarabunPSK", "THSarabunPSK-Bold"} <= embedded_fonts
    assert len(pdf) == 2
    chemistry, ua = [page.get_text() for page in pdf]
    assert "Glucose" in chemistry and "SPC-SAMPLE-1" in chemistry
    assert "SPC-SAMPLE-2" not in chemistry
    assert "SPC-SAMPLE-2" in ua and "Crystals" in ua and "1.003" in ua
    assert "<test> & sample" in chemistry
    assert "01:02:33" in chemistry and "+07:00" not in chemistry
    assert "Final" in chemistry and "Final" in ua
    assert tuple(pdf[0].rect) == (0, 0, 612, 792)  # Letter, like the supplied form.
    assert "Flag" not in chemistry and "Flag" not in ua
    assert "Requested Date/Time:" in chemistry and "Received Date/Time:" in ua
    # The paper form has a black header grid and an unshaded four-column results table.
    drawings = pdf[1].get_drawings()
    assert any(d["type"] == "s" and d.get("color") == (0, 0, 0) for d in drawings)
    assert not any(d.get("fill") is not None for d in drawings)


def test_numeric_test_in_other_category_is_not_assumed_chemistry():
    context = sample_report()
    other = {**context["results"][0], "category_name": "ภูมิคุ้มกัน", "category_name_en": "Immunology"}
    context["results"] = [other]
    report = prepare_report(context, Settings())
    assert report["sections"][0]["subtitle"] == "Immunology"
