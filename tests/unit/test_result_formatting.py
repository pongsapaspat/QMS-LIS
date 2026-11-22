from decimal import Decimal

import pytest

from app.core.result_formatting import (
    display_panel_results,
    format_reference_text,
    format_result_number,
)


def test_reference_ranges_trim_zeros_without_rounding():
    assert format_reference_text("70.000000 – 110.000000") == "70 – 110"
    assert format_reference_text("1.003000 – 1.030000") == "1.003 – 1.03"
    assert format_reference_text("< 5.100000 mg/dL") == "< 5.1 mg/dL"


@pytest.mark.parametrize("value", [70, {"lower": 70}, [70, 110]])
def test_malformed_reference_snapshot_can_fall_back_to_numeric_bounds(value):
    assert format_reference_text(value) is None


@pytest.mark.parametrize("value,expected", [
    ("89.000000", "89"), ("5.100000", "5.1"), ("5.126000", "5.13"),
    ("5.125", "5.13"), ("199.000000", "199"), ("0.000000", "0"),
    ("-0.001", "0"), ("-5.125", "-5.13"), ("1E+2", "100"),
    ("Negative", "Negative"), (None, ""),
])
def test_result_number_display(value, expected):
    assert format_result_number(value) == expected


def test_input_formatting_preserves_precision_and_panel_formatting_preserves_source():
    assert format_result_number(Decimal("5.126000"), None) == "5.126"
    rows = [
        {"code": "SG", "kind": "NUMERIC", "value": "1.025000"},
        {"code": "PH", "kind": "NUMERIC", "value": "6.500000"},
        {"code": "HB", "kind": "NUMERIC", "value": "12.345"},
        {"code": "PROTEIN", "kind": "TEXT", "value": "1+"},
        {"code": "RBC", "kind": "TEXT", "value": "0-2"},
    ]
    display = display_panel_results(rows)
    assert [p["value"] for p in display] == ["1.025", "6.5", "12.35", "1+", "0-2"]
    assert rows[0]["value"] == "1.025000"
    assert rows[2]["value"] == "12.345"
