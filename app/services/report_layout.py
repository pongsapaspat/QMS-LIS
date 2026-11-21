"""Shared grouping and presentation metadata for web and PDF reports."""

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import Settings


def prepare_report(context: dict[str, Any], settings: Settings) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for result in context["results"]:
        category = result.get("category_name_en", "").strip().lower()
        department = result.get("department_code", "GENERAL").upper()
        if result.get("result_type") == "UA":
            key, name, english = "UA", "ผลการตรวจปัสสาวะ", "Urinalysis"
        elif department in {"CHEMISTRY", "CHEM", "BIOCHEMISTRY"} or (
            department == "GENERAL" and category in {"chemical", "chemistry", "clinical chemistry"}
        ):
            key, name, english = "CHEMISTRY", "ผลการตรวจเคมีคลินิก", "Clinical Chemistry"
        else:
            key = f"{department}:{result.get('category_name', '')}"
            name = result.get("category_name") or result.get("department_name") or "ผลการตรวจ"
            english = result.get("category_name_en", "")
        section = groups.setdefault(
            key,
            {
                "title": name,
                "subtitle": english,
                "results": [],
                "specimens": [],
            },
        )
        section["results"].append(result)
        specimen = result.get("specimen")
        if specimen and all(s.id != specimen.id for s in section["specimens"]):
            section["specimens"].append(specimen)
    for section in groups.values():
        reporter = max(
            (r for r in section["results"] if r.get("entered_at")),
            key=lambda r: r["entered_at"],
            default={},
        )
        section["reported_by"] = reporter.get("entered_by") or context.get("reported_by")
        section["reported_at"] = reporter.get("entered_at") or context.get("reported_at")
        if section["subtitle"] == "Clinical Chemistry":
            section["report_title"] = "ใบรายงานผลการตรวจวิเคราะห์เคมีคลินิก"
            section["report_subtitle"] = "Clinical Chemistry laboratory report"
        elif section["subtitle"] == "Urinalysis":
            section["report_title"] = "ใบรายงานผลการตรวจวิเคราะห์ปัสสาวะ"
            section["report_subtitle"] = "Urine analysis laboratory report"
        else:
            section["report_title"] = "ใบรายงานผลการตรวจ" + section["title"]
            section["report_subtitle"] = section["subtitle"] + " laboratory report"
    patient, order = context["patient"], context["order"]
    dob = patient.date_of_birth
    on: date = order.ordered_at.astimezone(ZoneInfo(settings.timezone)).date()
    age = None
    if dob and dob <= on:
        age = on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))
    return {
        **context,
        "sections": list(groups.values()),
        "patient_age": age,
        "lab": {
            "name": settings.report_lab_name,
            "address": settings.report_lab_address,
            "phone": settings.report_lab_phone,
        },
    }
