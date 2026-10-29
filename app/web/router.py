from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import WorklistServiceDependency
from app.core.security import ActorDependency
from app.web.routes import orders, patients, results, specimens, test_catalog

templates = Jinja2Templates(directory="app/templates")
web_router = APIRouter(include_in_schema=False)
web_router.include_router(patients.router)
web_router.include_router(test_catalog.router)
web_router.include_router(orders.router)
web_router.include_router(specimens.router)
web_router.include_router(specimens.receiving_router)
web_router.include_router(results.router)


@web_router.get("/", response_class=HTMLResponse)
def home(
    request: Request, service: WorklistServiceDependency, actor: ActorDependency
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "page_title": "QMS-LIS",
            "worklist_counts": service.summary_counts(),
        },
    )
