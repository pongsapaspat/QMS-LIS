
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings

WEB_DATETIME_FORMAT = "%d/%m/%Y %H:%M"
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


def utc_now() -> datetime:
    """Return the current instant as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC.

    Naive values are treated as UTC because SQLite removes timezone metadata
    from values that were already normalized by ``UTCDateTime`` on write.
    User and API inputs must be validated before reaching this boundary.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def app_timezone(timezone_name: str | None = None) -> ZoneInfo:
    name = timezone_name or get_settings().timezone
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown application timezone: {name}") from exc


def to_app_timezone(value: datetime, timezone_name: str | None = None) -> datetime:
    """Convert a UTC instant to the configured application timezone."""
    return ensure_utc(value).astimezone(app_timezone(timezone_name))


def format_datetime_for_web(
    value: datetime | date | None, timezone_name: str | None = None
) -> str:
    """Format a datetime for web display without shifting date-only values."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        localized = to_app_timezone(value, timezone_name)
        offset = localized.strftime("%z")
        readable_offset = f"{offset[:3]}:{offset[3:]}"
        return f"{localized.strftime(WEB_DATETIME_FORMAT)} ({readable_offset})"
    return value.isoformat()


def format_datetime_local(
    value: datetime | str | None, timezone_name: str | None = None
) -> str:
    """Format a UTC instant for an HTML ``datetime-local`` control."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return to_app_timezone(value, timezone_name).strftime(DATETIME_LOCAL_FORMAT)


def parse_local_datetime(value: str, timezone_name: str | None = None) -> datetime:
    """Interpret an HTML ``datetime-local`` value in the application timezone.

    Offset-bearing values are rejected because this function is specifically
    for wall-clock form input. Ambiguous and nonexistent local times are also
    rejected for timezone configurations that observe clock changes.
    """
    normalized = value.strip()
    if not normalized:
        raise ValueError("local datetime is required")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("invalid local datetime") from exc
    if parsed.tzinfo is not None or parsed.utcoffset() is not None:
        raise ValueError("local datetime must not include a timezone offset")

    timezone = app_timezone(timezone_name)
    candidates = [parsed.replace(tzinfo=timezone, fold=fold) for fold in (0, 1)]
    valid = [
        candidate
        for candidate in candidates
        if candidate.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) == parsed
    ]
    if not valid:
        raise ValueError("local datetime does not exist in the application timezone")
    if len(valid) == 2 and valid[0].utcoffset() != valid[1].utcoffset():
        raise ValueError("local datetime is ambiguous in the application timezone")
    return valid[0].astimezone(UTC)


def app_date_range_utc(
    date_from: date | None,
    date_to: date | None,
    timezone_name: str | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Convert inclusive application-local dates to half-open UTC boundaries."""
    timezone = app_timezone(timezone_name)
    start = (
        datetime.combine(date_from, time.min, tzinfo=timezone).astimezone(UTC)
        if date_from is not None
        else None
    )
    end = (
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone).astimezone(UTC)
        if date_to is not None
        else None
    )
    return start, end
