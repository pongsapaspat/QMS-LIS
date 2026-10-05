from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
web_router = APIRouter(include_in_schema=False)


@web_router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"page_title": "QMS-LIS"},
    )
