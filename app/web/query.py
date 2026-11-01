from typing import Any


def empty_string_to_none(value: Any) -> Any:
    """Treat an unselected HTML GET control as an omitted query parameter."""
    return None if value == "" else value


def positive_int_or_none(value: int | None) -> int | None:
    if value is not None and value < 1:
        raise ValueError("value must be greater than or equal to 1")
    return value
