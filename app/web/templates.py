from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.time import format_datetime_for_web, format_datetime_local

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["app_datetime"] = format_datetime_for_web
templates.env.filters["app_datetime_local"] = format_datetime_local
templates.env.globals["app_timezone"] = get_settings().timezone
