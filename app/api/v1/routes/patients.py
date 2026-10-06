from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import PatientServiceDependency
from app.core.security import ActorDependency, AdminActorDependency
from app.schemas.patient import (
    DuplicateCandidateResponse,
    DuplicateCheckQuery,
    DuplicateCheckResponse,
    PatientCreate,
    PatientDetailResponse,
    PatientListItem,
    PatientPage,
    PatientUpdate,
)

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientDetailResponse, status_code=status.HTTP_201_CREATED)
def create_patient(
    data: PatientCreate,
    service: PatientServiceDependency,
    actor: AdminActorDependency,
) -> PatientDetailResponse:
    return PatientDetailResponse.model_validate(
        service.create(data, actor_reference=actor.reference)
    )


@router.get("", response_model=PatientPage)
def list_patients(
    service: PatientServiceDependency,
    actor: ActorDependency,
    search: str | None = None,
    branch_id: Annotated[int | None, Query(ge=1)] = None,
    include_inactive: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PatientPage:
    patients, total = service.list_patients(
        search=search,
        branch_id=branch_id,
        include_inactive=include_inactive,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return PatientPage(
        items=[PatientListItem.model_validate(patient) for patient in patients],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/duplicate-check", response_model=DuplicateCheckResponse)
def duplicate_check(
    service: PatientServiceDependency,
    actor: ActorDependency,
    query: Annotated[DuplicateCheckQuery, Depends()],
) -> DuplicateCheckResponse:
    candidates = service.check_duplicates(**query.model_dump())
    return DuplicateCheckResponse(
        candidates=[
            DuplicateCandidateResponse.model_validate(candidate) for candidate in candidates
        ]
    )


@router.get("/{patient_id}", response_model=PatientDetailResponse)
def get_patient(
    patient_id: int,
    service: PatientServiceDependency,
    actor: ActorDependency,
) -> PatientDetailResponse:
    return PatientDetailResponse.model_validate(service.get(patient_id))


@router.patch("/{patient_id}", response_model=PatientDetailResponse)
def update_patient(
    patient_id: int,
    data: PatientUpdate,
    service: PatientServiceDependency,
    actor: AdminActorDependency,
) -> PatientDetailResponse:
    return PatientDetailResponse.model_validate(
        service.update(patient_id, data, actor_reference=actor.reference)
    )
