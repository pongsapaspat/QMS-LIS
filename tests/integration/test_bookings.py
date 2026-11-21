from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Branch, LabOrder, LabTest, Patient
from app.models import TestPackage as LabPackage
from app.models.booking import Booking, BookingOrder
from app.services.booking import BookingService
from tests.integration.test_specimens import create_collection_order

RECEPTION = {"X-Role": "RECEPTION", "X-Actor": "booking-desk"}
BASE = {
    "appointment_at": "2026-11-22T09:30",
    "source": "LINE OA",
    "first_name_th": "สมใจ",
    "last_name_th": "ตัวอย่าง",
    "phone_number": "0891234567",
    "address": "ที่อยู่จาก OA",
    "emergency_contact_name": "ญาติ ตัวอย่าง",
    "emergency_contact_phone": "0812345678",
    "requested_services": "ตรวจสุขภาพจาก OA",
}
PATIENT = {
    "title_option": "นางสาว",
    "first_name_th": "สมใจ",
    "last_name_th": "ตัวอย่าง",
    "phone_number": "0891234567",
    "national_id": "1234567890123",
    "date_of_birth": "1990-01-02",
    "sex": "female",
    "address": "ที่อยู่ที่ยืนยันแล้ว",
}


def new_booking(client, **changes):
    response = client.post(
        "/bookings/new", headers=RECEPTION, data={**BASE, **changes}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rstrip("/").split("/")[-1])


def arrive(client, booking_id):
    response = client.post(
        f"/bookings/{booking_id}/status",
        headers=RECEPTION,
        data={"version": "1", "status": "ARRIVED"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def counts(factory):
    with factory() as session:
        return (
            session.scalar(select(func.count()).select_from(Patient)),
            session.scalar(select(func.count()).select_from(LabOrder)),
            session.get(Branch, 1).next_hn_sequence,
        )


@pytest.mark.integration
def test_booking_registration_and_reviewed_order_are_separate_and_idempotent(
    client, db_session_factory
):
    create_collection_order(client)
    with db_session_factory() as session:
        tests = list(session.scalars(select(LabTest).order_by(LabTest.id)))
        test_id = tests[0].id
        package = LabPackage(
            code="BOOK-PKG", name="แพ็กเกจจอง", price=Decimal("300"), tests=tests[:2]
        )
        session.add(package)
        session.commit()
        package_id = package.id
    before = counts(db_session_factory)
    booking_id = new_booking(client, test_ids=[str(test_id)], package_ids=[str(package_id)])
    assert counts(db_session_factory) == before
    with db_session_factory() as session:
        booking = session.get(Booking, booking_id)
        assert booking.patient_id is None and booking.status == "BOOKED"
        assert len(booking.requested_items) == 2
    assert client.get(f"/bookings/{booking_id}/register", headers=RECEPTION).status_code == 409
    arrive(client, booking_id)
    page = client.get(f"/bookings/{booking_id}/register", headers=RECEPTION)
    assert page.status_code == 200
    assert 'value="0891234567"' in page.text and "ที่อยู่จาก OA" in page.text
    assert 'name="national_id"' in page.text and 'required aria-required="true"' in page.text
    invalid = client.post(
        f"/bookings/{booking_id}/register",
        headers=RECEPTION,
        data={**PATIENT, "national_id": "", "booking_version": "2"},
    )
    assert invalid.status_code == 422
    assert counts(db_session_factory) == before
    registered = client.post(
        f"/bookings/{booking_id}/register",
        headers=RECEPTION,
        data={**PATIENT, "booking_version": "2"},
        follow_redirects=False,
    )
    assert registered.status_code == 303
    assert registered.headers["location"] == f"/orders/new?booking_id={booking_id}"
    after = counts(db_session_factory)
    assert after == (before[0] + 1, before[1], before[2] + 1)
    with db_session_factory() as session:
        booking = session.get(Booking, booking_id)
        assert booking.status == "REGISTERED"
        patient_id = booking.patient_id
        assert session.get(Patient, patient_id).address == "ที่อยู่ที่ยืนยันแล้ว"
        assert booking.address == "ที่อยู่จาก OA"
        session.get(LabPackage, package_id).price = Decimal("350")
        session.commit()
    page = client.get(registered.headers["location"], headers=RECEPTION)
    assert page.status_code == 200
    assert "ตรวจสุขภาพจาก OA" in page.text and "แพ็กเกจจอง" in page.text
    assert page.context["values"]["test_ids"] == [str(test_id)]
    assert page.context["values"]["package_ids"] == [str(package_id)]
    order_data = {
        "patient_id": str(patient_id),
        "booking_id": str(booking_id),
        "test_ids": [str(test_id)],
        "package_ids": [str(package_id)],
    }
    ordered = client.post("/orders/new", headers=RECEPTION, data=order_data, follow_redirects=False)
    assert ordered.status_code == 303, ordered.text
    with db_session_factory() as session:
        link = session.get(BookingOrder, booking_id)
        assert len(link.order.items) == 2  # Duplicate test inside package is ordered once.
        assert link.order.total_price == Decimal("350")
    duplicate = client.post(
        "/orders/new", headers=RECEPTION, data=order_data, follow_redirects=False
    )
    assert duplicate.status_code in (409, 422)
    assert "สร้าง Order แล้ว" in duplicate.text
    duplicate_registration = client.post(
        f"/bookings/{booking_id}/register",
        headers=RECEPTION,
        data={**PATIENT, "booking_version": "2"},
        follow_redirects=False,
    )
    assert duplicate_registration.status_code == 409
    assert counts(db_session_factory) == (after[0], after[1] + 1, after[2])


@pytest.mark.integration
def test_existing_patient_requires_identity_confirmation_without_overwriting_master(
    client, db_session_factory
):
    old_order, _, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        patient = session.get(LabOrder, old_order).patient
        patient.phone_number, patient.address = BASE["phone_number"], "ข้อมูลเดิมที่ยืนยันแล้ว"
        patient_id, hn = patient.id, patient.hn
        session.commit()
    before = counts(db_session_factory)
    booking_id = new_booking(client)
    arrive(client, booking_id)
    page = client.get(f"/bookings/{booking_id}", headers=RECEPTION)
    assert hn in page.text
    payload = {"version": "2", "patient_id": str(patient_id), "passport_number": "B1234567"}
    assert (
        client.post(f"/bookings/{booking_id}/link", headers=RECEPTION, data=payload).status_code
        == 422
    )
    wrong = client.post(
        f"/bookings/{booking_id}/link",
        headers=RECEPTION,
        data={**payload, "confirmed": "on", "passport_number": "Z1234567"},
    )
    assert wrong.status_code == 422
    assert "ไม่ตรง" in wrong.text
    linked = client.post(
        f"/bookings/{booking_id}/link",
        headers=RECEPTION,
        data={**payload, "confirmed": "on"},
        follow_redirects=False,
    )
    assert linked.status_code == 303
    assert counts(db_session_factory) == before
    with db_session_factory() as session:
        assert session.get(Booking, booking_id).patient_id == patient_id
        assert session.get(Patient, patient_id).address == "ข้อมูลเดิมที่ยืนยันแล้ว"


@pytest.mark.integration
def test_duplicates_and_failed_registration_roll_back_hn_and_booking_version(
    client, db_session_factory, monkeypatch
):
    old_order, _, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        patient = session.get(LabOrder, old_order).patient
        patient.national_id = PATIENT["national_id"]
        hn = patient.hn
        session.commit()
    booking_id = new_booking(client)
    arrive(client, booking_id)
    before = counts(db_session_factory)
    duplicate = client.post(
        f"/bookings/{booking_id}/register",
        headers=RECEPTION,
        data={**PATIENT, "booking_version": "2"},
    )
    assert duplicate.status_code == 409 and hn in duplicate.text
    assert "เลือกใช้ HN นี้" in duplicate.text
    assert counts(db_session_factory) == before

    def fail_finish(*args, **kwargs):
        raise RuntimeError("Simulated booking commit failure")

    monkeypatch.setattr(BookingService, "_finish", fail_finish)
    with pytest.raises(RuntimeError, match="Simulated booking"):
        client.post(
            f"/bookings/{booking_id}/register",
            headers=RECEPTION,
            data={**PATIENT, "national_id": "2234567890123", "booking_version": "2"},
        )
    assert counts(db_session_factory) == before
    with db_session_factory() as session:
        booking = session.get(Booking, booking_id)
        assert booking.status == "ARRIVED" and booking.version == 2 and booking.patient_id is None


@pytest.mark.integration
def test_stale_updates_and_closed_states_cannot_register_or_create_orders(
    client, db_session_factory
):
    booking_id = new_booking(client)
    updated = client.post(
        f"/bookings/{booking_id}/edit",
        headers=RECEPTION,
        data={**BASE, "note": "Updated", "version": "1"},
        follow_redirects=False,
    )
    assert updated.status_code == 303
    stale = client.post(
        f"/bookings/{booking_id}/edit",
        headers=RECEPTION,
        data={**BASE, "note": "Stale", "version": "1"},
    )
    assert stale.status_code == 409
    assert "โหลดข้อมูลล่าสุด" in stale.text
    cancelled = client.post(
        f"/bookings/{booking_id}/status",
        headers=RECEPTION,
        data={"version": "2", "status": "CANCELLED"},
        follow_redirects=False,
    )
    assert cancelled.status_code == 303
    assert (
        client.post(
            f"/bookings/{booking_id}/register",
            headers=RECEPTION,
            data={**PATIENT, "booking_version": "3"},
        ).status_code
        == 409
    )
    assert counts(db_session_factory) == (0, 0, 0)
    assert client.get(f"/bookings/{booking_id}/edit", headers=RECEPTION).status_code == 409
    assert (
        client.post(
            f"/bookings/{booking_id}/status",
            headers=RECEPTION,
            data={"version": "3", "status": "REGISTERED"},
        ).status_code
        == 422
    )


@pytest.mark.integration
def test_filters_use_thai_dates_and_return_html_for_bad_filters(client):
    first = new_booking(client, appointment_at="2026-11-21T00:30", first_name_th="คนแรก")
    new_booking(client, appointment_at="2026-11-22T00:01", first_name_th="คนถัดไป")
    page = client.get("/bookings?date_from=2026-11-21&date_to=2026-11-21", headers=RECEPTION)
    assert page.status_code == 200
    assert f"/bookings/{first}" in page.text
    assert "คนแรก" in page.text and "คนถัดไป" not in page.text
    for query in ("status=WRONG", "date_from=oops", "date_from=2026-12-01&date_to=2026-11-21"):
        invalid = client.get("/bookings?" + query, headers=RECEPTION)
        assert invalid.status_code == 422
        assert invalid.headers["content-type"].startswith("text/html")
    assert client.get("/bookings?all_dates=true", headers=RECEPTION).context["total"] == 2
    assert (
        client.get("/bookings?all_dates=true&search=คนแรก", headers=RECEPTION).context["total"] == 1
    )


@pytest.mark.integration
@pytest.mark.parametrize("role", ["LAB_TECH", "LAB_SUPERVISOR"])
def test_booking_routes_are_restricted_to_reception_permissions(client, role):
    booking_id = new_booking(client)
    headers = {"X-Role": role, "X-Actor": "unauthorized"}
    for path in (
        "/bookings",
        "/bookings/new",
        f"/bookings/{booking_id}",
        f"/bookings/{booking_id}/edit",
        f"/bookings/{booking_id}/register",
        f"/orders/new?booking_id={booking_id}",
    ):
        assert client.get(path, headers=headers).status_code == 403
    for path in (
        "/bookings/new",
        f"/bookings/{booking_id}/edit",
        f"/bookings/{booking_id}/status",
        f"/bookings/{booking_id}/register",
        f"/bookings/{booking_id}/link",
    ):
        assert client.post(path, headers=headers, data={}).status_code == 403


@pytest.mark.integration
def test_stale_registration_preserves_version_and_allocates_no_hn(client, db_session_factory):
    booking_id = new_booking(client)
    arrive(client, booking_id)
    response = client.post(
        f"/bookings/{booking_id}/edit",
        headers=RECEPTION,
        data={**BASE, "phone_number": "0890000000", "version": "2"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    stale = client.post(
        f"/bookings/{booking_id}/register",
        headers=RECEPTION,
        data={**PATIENT, "booking_version": "2"},
    )
    assert stale.status_code == 409
    assert 'name="booking_version" value="2"' in stale.text
    assert counts(db_session_factory) == (0, 0, 0)
    fresh = client.get(f"/bookings/{booking_id}/register", headers=RECEPTION)
    assert 'value="0890000000"' in fresh.text
    assert 'name="booking_version" value="3"' in fresh.text


@pytest.mark.integration
def test_unavailable_services_require_review_and_patient_cannot_be_changed(
    client, db_session_factory
):
    old_order, _, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        order = session.get(LabOrder, old_order)
        old_patient_id = order.patient_id
        retired_id, active_id = [item.lab_test_id for item in order.items[:2]]
    booking_id = new_booking(client, test_ids=[str(retired_id)])
    arrive(client, booking_id)
    assert (
        client.post(
            f"/bookings/{booking_id}/register",
            headers=RECEPTION,
            data={**PATIENT, "booking_version": "2"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    with db_session_factory() as session:
        patient_id = session.get(Booking, booking_id).patient_id
        session.get(LabTest, retired_id).is_active = False
        session.commit()
    page = client.get(f"/orders/new?booking_id={booking_id}", headers=RECEPTION)
    assert page.status_code == 200 and "ไม่พร้อมใช้งาน" in page.text
    before = counts(db_session_factory)
    for patient, selected in ((patient_id, retired_id), (old_patient_id, active_id)):
        response = client.post(
            "/api/v1/orders",
            headers=RECEPTION,
            json={"patient_id": patient, "booking_id": booking_id, "test_ids": [selected]},
        )
        assert response.status_code in (404, 422)
    assert counts(db_session_factory) == before
    valid = client.post(
        "/api/v1/orders",
        headers=RECEPTION,
        json={"patient_id": patient_id, "booking_id": booking_id, "test_ids": [active_id]},
    )
    assert valid.status_code == 201


@pytest.mark.integration
def test_shared_phone_requires_explicit_distinct_patient_confirmation(client, db_session_factory):
    old_order, _, _, _ = create_collection_order(client)
    with db_session_factory() as session:
        patient = session.get(LabOrder, old_order).patient
        patient.phone_number = BASE["phone_number"]
        session.commit()
    booking_id = new_booking(client)
    arrive(client, booking_id)
    before = counts(db_session_factory)
    payload = {**PATIENT, "booking_version": "2"}
    possible_duplicate = client.post(
        f"/bookings/{booking_id}/register", headers=RECEPTION, data=payload
    )
    assert possible_duplicate.status_code == 409
    assert 'name="confirm_possible_duplicate"' in possible_duplicate.text
    assert counts(db_session_factory) == before
    confirmed = client.post(
        f"/bookings/{booking_id}/register",
        headers=RECEPTION,
        data={**payload, "confirm_possible_duplicate": "true"},
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    assert counts(db_session_factory) == (before[0] + 1, before[1], before[2] + 1)
