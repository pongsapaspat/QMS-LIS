from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.core.time import (
    ensure_utc,
    format_datetime_for_web,
    format_datetime_local,
    parse_local_datetime,
    to_app_timezone,
    utc_now,
)


def test_utc_now_and_ensure_utc_are_timezone_aware() -> None:
    now = utc_now()
    assert now.tzinfo is UTC
    assert ensure_utc(datetime(2026, 10, 28, 7, 30)) == datetime(
        2026, 10, 28, 7, 30, tzinfo=UTC
    )
    assert ensure_utc(
        datetime(2026, 10, 28, 14, 30, tzinfo=timezone(timedelta(hours=7)))
    ) == datetime(2026, 10, 28, 7, 30, tzinfo=UTC)


def test_bangkok_conversion_and_web_formats_preserve_the_instant() -> None:
    stored = datetime(2026, 10, 28, 7, 30, tzinfo=UTC)
    displayed = to_app_timezone(stored, "Asia/Bangkok")

    assert displayed.isoformat() == "2026-10-28T14:30:00+07:00"
    assert format_datetime_for_web(stored, "Asia/Bangkok") == (
        "28/10/2026 14:30 (+07:00)"
    )
    assert format_datetime_local(stored, "Asia/Bangkok") == "2026-10-28T14:30"
    assert format_datetime_for_web(date(2026, 10, 28), "Asia/Bangkok") == "2026-10-28"


def test_datetime_local_is_interpreted_in_bangkok_and_converted_to_utc() -> None:
    parsed = parse_local_datetime("2026-10-28T14:30", "Asia/Bangkok")

    assert parsed == datetime(2026, 10, 28, 7, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="must not include"):
        parse_local_datetime("2026-10-28T14:30+07:00", "Asia/Bangkok")
    with pytest.raises(ValueError, match="invalid local datetime"):
        parse_local_datetime("not-a-time", "Asia/Bangkok")


def test_datetime_local_rejects_ambiguous_and_nonexistent_wall_times() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        parse_local_datetime("2026-03-08T02:30", "America/New_York")
    with pytest.raises(ValueError, match="ambiguous"):
        parse_local_datetime("2026-11-01T01:30", "America/New_York")
