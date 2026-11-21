"""Presentation of result numbers, without changing stored values or flags."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext


def format_reference_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"(?<![\w.])[+-]?\d+\.\d+(?![\w.])",
                  lambda match: format_result_number(match.group(), None), value)


def format_result_number(value: object, places: int | None = 2) -> str:
    if value is None:
        return ""
    original = str(value)
    try:
        number = Decimal(original)
    except InvalidOperation:
        return original
    if not number.is_finite():
        return original
    with localcontext() as context:
        context.rounding = ROUND_HALF_UP
        rendered = format(number, f".{places}f" if places is not None else "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered == "-0" else rendered


def display_panel_results(rows: list[dict] | None) -> list[dict]:
    return [
        {
            **row,
            "value": format_result_number(row["value"], 3 if row["code"] == "SG" else 2)
            if row.get("kind") == "NUMERIC" else row["value"],
        }
        for row in rows or []
    ]
