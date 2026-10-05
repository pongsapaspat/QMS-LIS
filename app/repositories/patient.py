from sqlalchemy import Select, or_, select, update
from sqlalchemy.orm import Session

from app.models.branch import Branch
from app.models.patient import Patient


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def allocate_hn(self, branch_id: int) -> str | None:
        statement = (
            update(Branch)
            .where(Branch.id == branch_id, Branch.is_active.is_(True))
            .values(next_hn_sequence=Branch.next_hn_sequence + 1)
            .returning(Branch.next_hn_sequence)
        )
        sequence = self.session.execute(statement).scalar_one_or_none()
        return None if sequence is None else f"HN{branch_id:03d}{sequence:08d}"

    def add(self, patient: Patient) -> Patient:
        self.session.add(patient)
        self.session.flush()
        return patient

    def get(self, patient_id: int) -> Patient | None:
        return self.session.get(Patient, patient_id)

    def list(
        self,
        *,
        search: str | None,
        branch_id: int | None,
        include_inactive: bool,
        offset: int,
        limit: int,
    ) -> list[Patient]:
        statement: Select[tuple[Patient]] = select(Patient)
        if branch_id is not None:
            statement = statement.where(Patient.branch_id == branch_id)
        if not include_inactive:
            statement = statement.where(Patient.is_active.is_(True))
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Patient.hn.ilike(term),
                    Patient.first_name.ilike(term),
                    Patient.last_name.ilike(term),
                    Patient.thai_national_id.ilike(term),
                    Patient.passport_number.ilike(term),
                )
            )
        statement = statement.order_by(Patient.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def identifiers_exist(
        self,
        *,
        thai_national_id: str | None,
        passport_number: str | None,
        exclude_patient_id: int | None = None,
    ) -> bool:
        criteria = []
        if thai_national_id:
            criteria.append(Patient.thai_national_id == thai_national_id)
        if passport_number:
            criteria.append(Patient.passport_number == passport_number)
        if not criteria:
            return False
        statement = select(Patient.id).where(or_(*criteria))
        if exclude_patient_id is not None:
            statement = statement.where(Patient.id != exclude_patient_id)
        return self.session.execute(statement.limit(1)).scalar_one_or_none() is not None
