from fastapi import APIRouter

from app.api.v1.routes import health, orders, patients, results, specimens, test_catalog

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(patients.router)
api_router.include_router(test_catalog.category_router)
api_router.include_router(test_catalog.specimen_router)
api_router.include_router(test_catalog.test_router)
api_router.include_router(orders.router)
api_router.include_router(specimens.order_router)
api_router.include_router(specimens.router)
api_router.include_router(results.router)
