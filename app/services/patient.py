from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.exceptions import (
    BranchNotFoundError,
    DuplicatePatientIdentifierError,
    PatientNotFoundError,
)
from app.models.patient import Patient
from app.repositories.patient import PatientRepository
from app.schemas.patient import PatientCreate, PatientUpdate


class PatientService:
    def __init__(
        self, session: Session, repository: PatientRepository | None = None
    ) -> None:
        self.session = session
        self.repository = repository or PatientRepository(session)

    def create(self, data: PatientCreate) -> Patient:
        if self.repository.identifiers_exist(
            thai_national_id=data.thai_national_id,
            passport_number=data.passport_number,
        ):
            raise DuplicatePatientIdentifierError("patient identifier already exists")

        hn = self.repository.allocate_hn(data.branch_id)
        if hn is None:
            self.session.rollback()
            raise BranchNotFoundError("active branch not found")

        patient = Patient(hn=hn, **data.model_dump())
        try:
            self.repository.add(patient)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicatePatientIdentifierError("patient identifier already exists") from exc
        return patient

    def get(self, patient_id: int) -> Patient:
        patient = self.repository.get(patient_id)
        if patient is None:
            raise PatientNotFoundError("patient not found")
        return patient

    def list(
        self,
        *,
        search: str | None,
        branch_id: int | None,
        include_inactive: bool,
        offset: int,
        limit: int,
    ) -> list[Patient]:
        return self.repository.list(
            search=search,
            branch_id=branch_id,
            include_inactive=include_inactive,
            offset=offset,
            limit=limit,
        )

    def update(self, patient_id: int, data: PatientUpdate) -> Patient:
        patient = self.get(patient_id)
        changes = data.model_dump(exclude_unset=True)
        thai_national_id = changes.get("thai_national_id", patient.thai_national_id)
        passport_number = changes.get("passport_number", patient.passport_number)
        if self.repository.identifiers_exist(
            thai_national_id=thai_national_id,
            passport_number=passport_number,
            exclude_patient_id=patient.id,
        ):
            raise DuplicatePatientIdentifierError("patient identifier already exists")

        for field, value in changes.items():
            setattr(patient, field, value)
        try:
            self.session.commit()
            self.session.refresh(patient)
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicatePatientIdentifierError("patient identifier already exists") from exc
        return patient
