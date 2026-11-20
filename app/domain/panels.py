"""Panel definitions supplied by the laboratory; no inferred critical limits."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation

from app.domain.exceptions import InvalidResultOperationError


def parameter(code, name, unit="", reference="", lower=None, upper=None, kind="TEXT"):
    return dict(
        code=code, name=name, unit=unit, reference=reference, lower=lower, upper=upper, kind=kind
    )


PRESETS = {
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


def panel_definitions(result_type: str) -> list[dict]:
    return deepcopy(PRESETS.get(result_type, []))


def interpret_panel(definitions: list[dict], values: dict[str, str], complete: bool):
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


def same_panel_values(definitions: list[dict], left: dict[str, str], right: dict[str, str]) -> bool:
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
