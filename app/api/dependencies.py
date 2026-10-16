from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.order import OrderService
from app.services.patient import PatientService
from app.services.test_catalog import TestCatalogService

SessionDependency = Annotated[Session, Depends(get_db)]


def get_patient_service(session: SessionDependency) -> PatientService:
    return PatientService(session)


PatientServiceDependency = Annotated[PatientService, Depends(get_patient_service)]


def get_test_catalog_service(session: SessionDependency) -> TestCatalogService:
    return TestCatalogService(session)


TestCatalogServiceDependency = Annotated[
    TestCatalogService, Depends(get_test_catalog_service)
]


def get_order_service(session: SessionDependency) -> OrderService:
    return OrderService(session)


OrderServiceDependency = Annotated[OrderService, Depends(get_order_service)]
