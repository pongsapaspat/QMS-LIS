from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.exceptions import (
    BranchNotFoundError,
    DuplicatePatientIdentifierError,
    InvalidPatientChangeError,
    PatientNotFoundError,
    PossibleDuplicatePatientError,
)
from app.domain.policies import (
    DuplicateCandidate,
    names_are_similar,
    normalize_person_name,
)
from app.models.audit import AuditLog
from app.models.patient import Patient
from app.repositories.audit import AuditRepository
from app.repositories.patient import PatientRepository
from app.schemas.patient import PatientCreate, PatientUpdate

HN_COUNTER_BRANCH_ID = 1


class PatientService:
    def __init__(
        self,
        session: Session,
        repository: PatientRepository | None = None,
        audit_repository: AuditRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or PatientRepository(session)
        self.audit_repository = audit_repository or AuditRepository(session)

    def create(self, data: PatientCreate, *, actor_reference: str) -> Patient:
        if not self.repository.branch_is_active(data.branch_id):
            raise BranchNotFoundError("active branch not found")

        identity_match = self.repository.find_identifier_match(
            national_id=data.national_id,
            passport_number=data.passport_number,
        )
        if identity_match is not None:
            raise DuplicatePatientIdentifierError("National ID or passport is already registered")

        candidates = self.check_duplicates(
            national_id=None,
            passport_number=None,
            first_name_th=data.first_name_th,
            last_name_th=data.last_name_th,
            first_name_en=data.first_name_en,
            last_name_en=data.last_name_en,
            date_of_birth=data.date_of_birth,
        )
        if candidates and not data.confirm_possible_duplicate:
            raise PossibleDuplicatePatientError(candidates)

        hn = self.repository.allocate_hn(HN_COUNTER_BRANCH_ID)
        if hn is None:
            self.session.rollback()
            raise BranchNotFoundError("HN counter branch not found")

        patient_data = data.model_dump(exclude={"confirm_possible_duplicate"})
        patient_data["identity_document_missing"] = not bool(
            data.national_id or data.passport_number
        )
        patient = Patient(hn=hn, **patient_data)
        try:
            self.repository.add(patient)
            changed_fields = sorted(
                field for field, value in patient_data.items() if value is not None
            )
            changed_fields.extend(["hn", "is_active"])
            self.audit_repository.add(
                AuditLog(
                    event_type="PATIENT_CREATED",
                    entity_type="patient",
                    entity_id=patient.id,
                    changed_fields=sorted(set(changed_fields)),
                    reason="patient registration",
                    actor_reference=actor_reference,
                )
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicatePatientIdentifierError(
                "National ID, passport, or HN is already registered"
            ) from exc
        return patient

    def get(self, patient_id: int) -> Patient:
        patient = self.repository.get(patient_id)
        if patient is None:
            raise PatientNotFoundError("patient not found")
        return patient

    def list_patients(
        self,
        *,
        search: str | None,
        branch_id: int | None,
        include_inactive: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[Patient], int]:
        return self.repository.list_patients(
            search=search,
            branch_id=branch_id,
            include_inactive=include_inactive,
            offset=offset,
            limit=limit,
        )

    def check_duplicates(
        self,
        *,
        national_id: str | None,
        passport_number: str | None,
        first_name_th: str | None,
        last_name_th: str | None,
        first_name_en: str | None,
        last_name_en: str | None,
        date_of_birth: date | None,
    ) -> list[DuplicateCandidate]:
        candidates: dict[int, DuplicateCandidate] = {}
        identity_match = self.repository.find_identifier_match(
            national_id=national_id,
            passport_number=passport_number,
        )
        if identity_match is not None:
            candidates[identity_match.id] = self._candidate(identity_match, "exact_identity")

        requested_thai = normalize_person_name(first_name_th, last_name_th)
        requested_english = normalize_person_name(first_name_en, last_name_en)
        for patient in self.repository.find_by_date_of_birth(date_of_birth):
            existing_thai = normalize_person_name(patient.first_name_th, patient.last_name_th)
            existing_english = normalize_person_name(patient.first_name_en, patient.last_name_en)
            if names_are_similar(requested_thai, existing_thai) or names_are_similar(
                requested_english, existing_english
            ):
                candidates.setdefault(
                    patient.id,
                    self._candidate(patient, "similar_name_same_date_of_birth"),
                )
        return list(candidates.values())

    def update(
        self,
        patient_id: int,
        data: PatientUpdate,
        *,
        actor_reference: str,
    ) -> Patient:
        patient = self.get(patient_id)
        changes = data.model_dump(exclude_unset=True)
        reason = changes.pop("change_reason")

        national_id = changes.get("national_id", patient.national_id)
        passport_number = changes.get("passport_number", patient.passport_number)
        identity_match = self.repository.find_identifier_match(
            national_id=national_id,
            passport_number=passport_number,
            exclude_patient_id=patient.id,
        )
        if identity_match is not None:
            raise DuplicatePatientIdentifierError("National ID or passport is already registered")

        resulting_names = {
            "first_name_th": changes.get("first_name_th", patient.first_name_th),
            "last_name_th": changes.get("last_name_th", patient.last_name_th),
            "first_name_en": changes.get("first_name_en", patient.first_name_en),
            "last_name_en": changes.get("last_name_en", patient.last_name_en),
        }
        if not self._has_complete_name(**resulting_names):
            raise InvalidPatientChangeError("a complete Thai or English name is required")

        actual_changes = {
            field: value for field, value in changes.items() if getattr(patient, field) != value
        }
        identity_missing = not bool(national_id or passport_number)
        if patient.identity_document_missing != identity_missing:
            actual_changes["identity_document_missing"] = identity_missing
        if not actual_changes:
            raise InvalidPatientChangeError("no patient data changed")

        for field, value in actual_changes.items():
            setattr(patient, field, value)
        try:
            self.repository.flush()
            self.audit_repository.add(
                AuditLog(
                    event_type="PATIENT_UPDATED",
                    entity_type="patient",
                    entity_id=patient.id,
                    changed_fields=sorted(actual_changes),
                    reason=reason,
                    actor_reference=actor_reference,
                )
            )
            self.session.commit()
            self.session.refresh(patient)
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicatePatientIdentifierError(
                "National ID or passport is already registered"
            ) from exc
        return patient

    @staticmethod
    def _candidate(patient: Patient, reason: str) -> DuplicateCandidate:
        return DuplicateCandidate(
            patient_id=patient.id,
            hn=patient.hn,
            display_name=patient.display_name,
            match_reason=reason,
        )

    @staticmethod
    def _has_complete_name(
        *,
        first_name_th: str | None,
        last_name_th: str | None,
        first_name_en: str | None,
        last_name_en: str | None,
    ) -> bool:
        return bool(
            (first_name_th and last_name_th) or (first_name_en and last_name_en)
        )
