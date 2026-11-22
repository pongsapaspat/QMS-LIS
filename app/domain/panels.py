"""Panel definitions supplied by the laboratory; no inferred critical limits."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.exceptions import InvalidResultOperationError

# Entry choices are separate from stored panel definitions so existing orders
# receive the same controls without changing their reference ranges or results.
UA_ENTRY_OPTIONS = {
    "COLOR": (
        "Yellow", "Straw", "Pale yellow", "Dark yellow", "Amber", "Orange", "Red", "Brown",
        "Colorless",
    ),
    "TURBIDITY": ("Clear", "Slightly cloudy", "Cloudy", "Turbid"),
    "PROTEIN": ("Negative", "Trace", "1+", "2+", "3+", "4+"),
    "GLUCOSE": ("Negative", "Trace", "1+", "2+", "3+", "4+"),
    "KETONES": ("Negative", "Trace", "1+", "2+", "3+", "4+"),
    "BLOOD": ("Negative", "Trace", "1+", "2+", "3+", "4+"),
    "BILIRUBIN": ("Negative", "Trace", "1+", "2+", "3+", "4+"),
    "UROBILINOGEN": ("Negative", "Trace", "1+", "2+", "3+", "4+"),
    "NITRITE": ("Negative", "Positive"),
    "LEUKOCYTES": ("Negative", "Trace", "1+", "2+", "3+", "4+"),
}


def parameter(
    code: str, name: str, unit: str = "", reference: str = "",
    lower: str | None = None, upper: str | None = None, kind: str = "TEXT",
) -> dict[str, Any]:
    return dict(
        code=code, name=name, unit=unit, reference=reference, lower=lower, upper=upper, kind=kind
    )


PRESETS = {
    "INFLUENZA_AB": [
        {
            **parameter(code, name, kind="CATEGORICAL"),
            "choices": ["Negative", "Positive"],
        }
        for code, name in [("FLU_A", "Influenza A"), ("FLU_B", "Influenza B")]
    ],
    "CBC": [
        parameter("HB", "Hemoglobin (Hb)", "g/dL", "11.0–18.8", "11.0", "18.8", "NUMERIC"),
        parameter("HCT", "Hematocrit (Hct)", "%", "35.0–55.0", "35.0", "55.0", "NUMERIC"),
        parameter("WBC", "WBC", "×10³/µL", "4.00–10.00", "4", "10", "NUMERIC"),
        parameter("RBC", "RBC", "×10⁶/µL", "4.50–6.00", "4.5", "6", "NUMERIC"),
        parameter("PLT", "Platelet count", "×10³/µL", "150–400", "150", "400", "NUMERIC"),
    ],
    "UA": [
        parameter("COLOR", "Color", reference="Yellow"),
        parameter("TURBIDITY", "Turbidity", reference="Clear"),
        parameter(
            "SG",
            "Specific gravity",
            reference="1.003–1.030",
            lower="1.003",
            upper="1.030",
            kind="NUMERIC",
        ),
        parameter("PH", "pH", reference="4.6–8.0", lower="4.6", upper="8.0", kind="NUMERIC"),
        *[
            parameter(code, name, reference="Negative")
            for code, name in [
                ("PROTEIN", "Protein"),
                ("GLUCOSE", "Glucose"),
                ("KETONES", "Ketones"),
                ("BLOOD", "Blood"),
                ("BILIRUBIN", "Bilirubin"),
                ("UROBILINOGEN", "Urobilinogen"),
                ("NITRITE", "Nitrite"),
                ("LEUKOCYTES", "Leukocyte esterase"),
            ]
        ],
        parameter("RBC", "RBC", "cells/HPF", "0–2"),
        parameter("WBC", "WBC", "cells/HPF", "0–5"),
        parameter("EPITHELIAL", "Epithelial cells", "cells/HPF", "0–5"),
        parameter("BACTERIA", "Bacteria"),
        parameter("CASTS", "Casts", "/LPF"),
        parameter("CRYSTALS", "Crystals"),
    ],
}


def panel_definitions(result_type: str) -> list[dict[str, Any]]:
    return deepcopy(PRESETS.get(result_type, []))


def interpret_panel(
    definitions: list[dict[str, Any]], values: dict[str, str], complete: bool
) -> list[dict[str, Any]]:
    if not definitions:
        raise InvalidResultOperationError("Panel parameter definitions are missing")
    if set(values) - {p["code"] for p in definitions}:
        raise InvalidResultOperationError("Unknown panel parameter")
    rows = []
    for p in definitions:
        value = " ".join(values.get(p["code"], "").split())
        if not value:
            if complete:
                raise InvalidResultOperationError(f"กรุณากรอก {p['name']} ให้ครบก่อนส่ง Verify")
            continue
        if p.get("choices") and value not in p["choices"]:
            raise InvalidResultOperationError(f"กรุณาเลือกผล {p['name']} จากตัวเลือกที่กำหนด")
        flag = None
        if p["kind"] == "NUMERIC":
            try:
                number = Decimal(value)
                if not number.is_finite() or len(value) > 40:
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise InvalidResultOperationError(f"{p['name']} requires a finite number") from exc
            flag = (
                "L"
                if number < Decimal(p["lower"])
                else "H"
                if number > Decimal(p["upper"])
                else "N"
            )
        elif p["reference"] in {"Yellow", "Clear", "Negative"}:
            flag = "N" if value.casefold() == p["reference"].casefold() else "A"
        rows.append({**p, "value": value, "flag": flag})
    if not rows:
        raise InvalidResultOperationError("Enter at least one parameter")
    return rows


def same_panel_values(
    definitions: list[dict[str, Any]], left: dict[str, str], right: dict[str, str]
) -> bool:
    if set(left) - {p["code"] for p in definitions}:
        return False
    for p in definitions:
        a, b = (" ".join(data.get(p["code"], "").split()) for data in (left, right))
        if a == b:
            continue
        if p["kind"] == "NUMERIC":
            try:
                if Decimal(a).is_finite() and Decimal(a) == Decimal(b):
                    continue
            except InvalidOperation:
                pass
        return False
    return True
