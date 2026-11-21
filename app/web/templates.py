from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from app.core.config import get_settings
from app.core.result_formatting import format_result_number
from app.core.time import format_datetime_for_web, format_datetime_local

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["app_datetime"] = format_datetime_for_web
templates.env.filters["app_datetime_local"] = format_datetime_local
templates.env.filters["result_number"] = format_result_number


def report_unit(value: str | None) -> Markup:
    # Use ordinary digits at a controlled superscript size, avoiding font fallback.
    unit = escape(value or "-")
    for superscript, digit in zip("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789", strict=True):
        unit = unit.replace(
            superscript, Markup('<sup class="unit-exponent">{}</sup>').format(digit)
        )
    return unit


templates.env.filters["report_unit"] = report_unit
settings = get_settings()
templates.env.globals["app_timezone"] = settings.timezone
templates.env.globals["allow_dev_role_headers"] = settings.app_env == "development"
templates.env.globals["template_default_role"] = (
    "ADMIN" if settings.app_env == "development" and settings.enable_dev_admin_fallback else None
)
