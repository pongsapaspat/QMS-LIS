from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies import PatientServiceDependency
from app.schemas.patient import PatientCreate, PatientResponse, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
def create_patient(data: PatientCreate, service: PatientServiceDependency) -> PatientResponse:
    return PatientResponse.model_validate(service.create(data))


@router.get("", response_model=list[PatientResponse])
def list_patients(
    service: PatientServiceDependency,
    search: str | None = None,
    branch_id: Annotated[int | None, Query(ge=1)] = None,
    include_inactive: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PatientResponse]:
    patients = service.list(
        search=search,
        branch_id=branch_id,
        include_inactive=include_inactive,
        offset=offset,
        limit=limit,
    )
    return [PatientResponse.model_validate(patient) for patient in patients]


@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(patient_id: int, service: PatientServiceDependency) -> PatientResponse:
    return PatientResponse.model_validate(service.get(patient_id))


@router.patch("/{patient_id}", response_model=PatientResponse)
def update_patient(
    patient_id: int, data: PatientUpdate, service: PatientServiceDependency
) -> PatientResponse:
    return PatientResponse.model_validate(service.update(patient_id, data))
