"""Shared grouping and presentation metadata for web and PDF reports."""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.services.report_identity import identity_label, order_creator_label, referrer_label


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
        reporter: dict[str, Any] = max(
            (r for r in section["results"] if r.get("entered_at")),
            key=lambda r: r["entered_at"],
            default={},
        )
        section["reported_by"] = reporter.get("entered_by") or context.get("reported_by")
        section["reported_at"] = reporter.get("entered_at") or context.get("reported_at")
        reporters: dict[str, datetime | None] = {}
        approvers: dict[str, datetime | None] = {}
        for result in section["results"]:
            label = identity_label(result.get("reporter_snapshot"), result.get("entered_by"))
            when = result.get("entered_at")
            if label not in reporters or (
                when and (not reporters[label] or when > reporters[label])
            ):
                reporters[label] = when
            label = identity_label(result.get("approver_snapshot"), result.get("released_by"))
            if result.get("released_by"):
                approvers[label] = result.get("released_at")
        if not reporters:
            reporters[identity_label(None, context.get("reported_by"))] = context.get("reported_at")
        if not approvers:
            order = context["order"]
            approvers[
                identity_label(getattr(order, "released_by_snapshot", None), order.released_by)
            ] = order.released_at
        section["reporters"] = [{"label": label, "at": when} for label, when in reporters.items()]
        section["approvers"] = [{"label": label, "at": when} for label, when in approvers.items()]
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
        "referrer_label": referrer_label(order),
        "order_creator_label": order_creator_label(order),
        "lab": {
            "name": settings.report_lab_name,
            "address": settings.report_lab_address,
            "phone": settings.report_lab_phone,
        },
    }
