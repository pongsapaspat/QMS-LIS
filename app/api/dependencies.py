from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.patient import PatientService

SessionDependency = Annotated[Session, Depends(get_db)]


def get_patient_service(session: SessionDependency) -> PatientService:
    return PatientService(session)


PatientServiceDependency = Annotated[PatientService, Depends(get_patient_service)]
