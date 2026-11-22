from datetime import date
from typing import Any, cast

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, selectinload

from app.core.time import app_date_range_utc
from app.domain.exceptions import (
    BookingNotFoundError,
    InvalidBookingOperationError,
    PossibleDuplicatePatientError,
)
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.booking import Booking
from app.models.patient import Patient
from app.models.test_catalog import LabTest
from app.schemas.booking import BookingInput
from app.schemas.patient import PatientCreate, normalize_national_id, normalize_passport_number
from app.services.package import PackageService
from app.services.patient import PatientService

STATUS_LABELS = {
    "BOOKED": "นัดหมายแล้ว",
    "ARRIVED": "มาถึงแล้ว",
    "REGISTERED": "ลงทะเบียนครบแล้ว",
    "CANCELLED": "ยกเลิก",
    "NO_SHOW": "ไม่มาตามนัด",
}


class BookingService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, booking_id: int) -> Booking:
        booking = self.session.scalar(
            select(Booking)
            .options(selectinload(Booking.patient), selectinload(Booking.order_link))
            .where(Booking.id == booking_id)
        )
        if booking is None:
            raise BookingNotFoundError("ไม่พบรายการจอง")
        return booking

    def list_bookings(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
        search: str | None,
        page: int = 1,
    ) -> tuple[list[Booking], int]:
        if status and status not in STATUS_LABELS:
            raise InvalidBookingOperationError("สถานะที่เลือกไม่ถูกต้อง")
        if date_from and date_to and date_from > date_to:
            raise InvalidBookingOperationError("วันเริ่มต้นต้องไม่อยู่หลังวันสิ้นสุด")
        start, end = app_date_range_utc(date_from, date_to)
        query = select(Booking)
        if start:
            query = query.where(Booking.appointment_at >= start)
        if end:
            query = query.where(Booking.appointment_at < end)
        if status:
            query = query.where(Booking.status == status)
        if search and search.strip():
            term = search.strip()
            name = (
                func.coalesce(Booking.first_name_th, "")
                + " "
                + func.coalesce(Booking.last_name_th, "")
            )
            query = query.where(
                or_(
                    name.contains(term, autoescape=True),
                    Booking.phone_number.contains(term, autoescape=True),
                    Booking.booking_number.contains(term, autoescape=True),
                )
            )
        count = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = list(
            self.session.scalars(
                query.options(selectinload(Booking.patient), selectinload(Booking.order_link))
                .order_by(Booking.appointment_at, Booking.id)
                .offset((page - 1) * 20)
                .limit(20)
            )
        )
        return rows, count or 0

    def _items(self, data: BookingInput) -> list[dict[str, Any]]:
        tests = list(self.session.scalars(select(LabTest).where(LabTest.id.in_(data.test_ids))))
        if len(tests) != len(data.test_ids) or any(
            not (
                test.is_active
                and test.department.is_active
                and test.category.is_active
                and test.specimen_type.is_active
            )
            for test in tests
        ):
            raise InvalidBookingOperationError("มีรายการตรวจที่ไม่พร้อมใช้งาน กรุณาเลือกใหม่")
        packages = {p.id: p for p in PackageService(self.session).list(available_only=True)}
        if any(package_id not in packages for package_id in data.package_ids):
            raise InvalidBookingOperationError("มีแพ็กเกจที่ไม่พร้อมใช้งาน กรุณาเลือกใหม่")
        return [{"kind": "TEST", "id": t.id, "code": t.code, "name": t.name_en} for t in tests] + [
            {"kind": "PACKAGE", "id": p, "code": packages[p].code, "name": packages[p].name}
            for p in data.package_ids
        ]

    def _audit(self, event: str, booking: Booking, actor: str, fields: list[str]) -> None:
        self.session.add(
            AuditLog(
                event_type=event,
                entity_type="booking",
                entity_id=booking.id,
                changed_fields=fields,
                reason="Reception booking workflow",
                actor_reference=actor,
            )
        )

    def _reserve(self, booking: Booking, version: int, allowed: set[str]) -> None:
        if booking.status not in allowed:
            raise InvalidBookingOperationError(
                "สถานะรายการจองเปลี่ยนแล้ว กรุณาเปิดรายการอีกครั้ง", conflict=True
            )
        result = cast(CursorResult[Any], self.session.execute(
            update(Booking)
            .where(
                Booking.id == booking.id, Booking.version == version, Booking.status.in_(allowed)
            )
            .values(version=Booking.version + 1, updated_at=utc_now())
            .execution_options(synchronize_session=False)
        ))
        if result.rowcount != 1:
            raise InvalidBookingOperationError("มีผู้แก้ไขรายการนี้แล้ว กรุณาโหลดข้อมูลล่าสุด", conflict=True)
        self.session.refresh(booking)

    def save(
        self,
        data: BookingInput,
        actor: str,
        *,
        booking_id: int | None = None,
        version: int | None = None,
    ) -> Booking:
        try:
            values = data.model_dump(exclude={"test_ids", "package_ids"})
            values["requested_items"] = self._items(data)
            if booking_id is None:
                booking = Booking(booking_number="PENDING", created_by=actor, **values)
                self.session.add(booking)
                self.session.flush()
                booking.booking_number = f"BKG{utc_now():%Y%m%d}-{booking.id:06d}"
            else:
                booking = self.get(booking_id)
                self._reserve(booking, version or 0, {"BOOKED", "ARRIVED"})
                for field, value in values.items():
                    setattr(booking, field, value)
            self._audit(
                "BOOKING_CREATED" if booking_id is None else "BOOKING_UPDATED",
                booking,
                actor,
                list(values),
            )
            self.session.commit()
            return booking
        except Exception:
            self.session.rollback()
            raise

    def transition(self, booking_id: int, version: int, target: str, actor: str) -> Booking:
        allowed = {
            "ARRIVED": {"BOOKED"},
            "CANCELLED": {"BOOKED", "ARRIVED"},
            "NO_SHOW": {"BOOKED"},
            "BOOKED": {"CANCELLED", "NO_SHOW", "ARRIVED"},
        }
        if target not in allowed:
            raise InvalidBookingOperationError("ไม่สามารถเปลี่ยนเป็นสถานะนี้ได้")
        try:
            booking = self.get(booking_id)
            self._reserve(booking, version, allowed[target])
            booking.status = target
            if target == "ARRIVED":
                booking.arrived_at = utc_now()
            elif target == "BOOKED":
                booking.arrived_at = None
            self._audit("BOOKING_STATUS_CHANGED", booking, actor, ["status", "arrived_at"])
            self.session.commit()
            return booking
        except Exception:
            self.session.rollback()
            raise

    def candidates(self, booking: Booking, search: str | None = None) -> list[Patient]:
        criteria = []
        if booking.phone_number:
            criteria.append(Patient.phone_number == booking.phone_number)
        if booking.first_name_th and booking.last_name_th:
            criteria.append(
                and_(
                    Patient.first_name_th == booking.first_name_th,
                    Patient.last_name_th == booking.last_name_th,
                )
            )
        if search and search.strip():
            name = (
                func.coalesce(Patient.first_name_th, "")
                + " "
                + func.coalesce(Patient.last_name_th, "")
            )
            term = search.strip()
            criteria = [
                or_(
                    name.contains(term, autoescape=True),
                    Patient.hn == term,
                    Patient.phone_number == term,
                )
            ]
        if not criteria:
            return []
        return list(
            self.session.scalars(
                select(Patient)
                .where(Patient.is_active.is_(True), or_(*criteria))
                .order_by(Patient.id.desc())
                .limit(20)
            )
        )

    def _finish(self, booking: Booking, patient: Patient, actor: str) -> None:
        booking.patient_id = patient.id
        booking.status = "REGISTERED"
        booking.registered_at, booking.registered_by = utc_now(), actor
        self._audit("BOOKING_REGISTERED", booking, actor, ["patient_id", "status", "registered_at"])
        self.session.commit()

    def register_new(
        self, booking_id: int, version: int, data: PatientCreate, actor: str
    ) -> Patient:
        try:
            booking = self.get(booking_id)
            self._reserve(booking, version, {"ARRIVED"})
            if not data.national_id:
                raise InvalidBookingOperationError("กรุณากรอกเลขบัตรประชาชน 13 หลักก่อนยืนยันลงทะเบียน")
            candidates = self.candidates(booking)
            if candidates and not data.confirm_possible_duplicate:
                raise PossibleDuplicatePatientError(
                    [PatientService._candidate(p, "booking_name_or_phone") for p in candidates]
                )
            patient = PatientService(self.session).create(data, actor_reference=actor, commit=False)
            self._finish(booking, patient, actor)
            return patient
        except Exception:
            self.session.rollback()
            raise

    def link_existing(
        self,
        booking_id: int,
        version: int,
        patient_id: int,
        actor: str,
        *,
        national_id: str | None,
        passport_number: str | None,
        confirmed: bool,
    ) -> Patient:
        try:
            booking = self.get(booking_id)
            self._reserve(booking, version, {"ARRIVED"})
            patient = PatientService(self.session).get(patient_id)
            nid, passport = (
                normalize_national_id(national_id),
                normalize_passport_number(passport_number),
            )
            if not patient.is_active or not confirmed or not (nid or passport):
                raise InvalidBookingOperationError(
                    "กรุณายืนยันผู้ป่วยและเลขบัตรประชาชนหรือ Passport ก่อนใช้ HN เดิม"
                )
            if (nid and nid != patient.national_id) or (
                passport and passport != patient.passport_number
            ):
                raise InvalidBookingOperationError(
                    "ข้อมูลยืนยันตัวตนไม่ตรงกับ HN ที่เลือก กรุณาตรวจสอบข้อมูลผู้ป่วย"
                )
            self._finish(booking, patient, actor)
            return patient
        except Exception:
            self.session.rollback()
            raise
