from datetime import date

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.branch import Branch
from app.models.patient import Patient


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def branch_is_active(self, branch_id: int) -> bool:
        statement = select(Branch.id).where(Branch.id == branch_id, Branch.is_active.is_(True))
        return self.session.execute(statement).scalar_one_or_none() is not None

    def allocate_hn(self, counter_branch_id: int = 1) -> str | None:
        statement = (
            update(Branch)
            .where(Branch.id == counter_branch_id)
            .values(next_hn_sequence=Branch.next_hn_sequence + 1)
            .returning(Branch.next_hn_sequence)
        )
        sequence = self.session.execute(statement).scalar_one_or_none()
        return None if sequence is None else f"HN{sequence:06d}"

    def add(self, patient: Patient) -> Patient:
        self.session.add(patient)
        self.session.flush()
        return patient

    def flush(self) -> None:
        self.session.flush()

    def get(self, patient_id: int) -> Patient | None:
        return self.session.get(Patient, patient_id)

    def list_patients(
        self,
        *,
        search: str | None,
        branch_id: int | None,
        include_inactive: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[Patient], int]:
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
                    Patient.first_name_th.ilike(term),
                    Patient.last_name_th.ilike(term),
                    Patient.first_name_en.ilike(term),
                    Patient.last_name_en.ilike(term),
                    Patient.national_id.ilike(term),
                )
            )
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        total = self.session.execute(count_statement).scalar_one()
        statement = statement.order_by(Patient.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement)), total

    def find_identifier_match(
        self,
        *,
        national_id: str | None,
        passport_number: str | None,
        exclude_patient_id: int | None = None,
    ) -> Patient | None:
        criteria = []
        if national_id:
            criteria.append(Patient.national_id == national_id)
        if passport_number:
            criteria.append(Patient.passport_number == passport_number)
        if not criteria:
            return None
        statement = select(Patient).where(or_(*criteria))
        if exclude_patient_id is not None:
            statement = statement.where(Patient.id != exclude_patient_id)
        return self.session.scalars(statement.limit(1)).first()

    def find_by_date_of_birth(self, date_of_birth: date | None) -> list[Patient]:
        if date_of_birth is None:
            return []
        statement = select(Patient).where(Patient.date_of_birth == date_of_birth)
        return list(self.session.scalars(statement))
