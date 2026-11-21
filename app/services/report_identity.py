"""Capture credentials at an action, never reconstruct them from a later profile."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.exceptions import InvalidResultOperationError
from app.models.user import User


def capture_identity(
    session: Session, username: str, settings: Settings, *, require_complete: bool = False
) -> dict:
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        # Development role headers may use synthetic actors without login accounts.
        if settings.app_env != "development":
            raise InvalidResultOperationError("ไม่พบบัญชีผู้ปฏิบัติงาน")
        return {
            "username": username,
            "full_name": None,
            "license_number": None,
            "license_type": "ทน.",
        }
    if require_complete and (not user.full_name or not user.professional_license_number):
        raise InvalidResultOperationError(
            "กรุณาให้ผู้ดูแลระบบกรอกชื่อ-นามสกุลและเลข ทน. ของบัญชีผู้ปฏิบัติงานก่อนส่งผลหรืออนุมัติผล"
        )
    return {
        "username": user.username,
        "full_name": user.full_name,
        "license_number": user.professional_license_number,
        "license_type": "ทน.",
    }


def identity_label(snapshot: dict | None, username: str | None = None) -> str:
    identity = snapshot or {}
    name = identity.get("full_name") or identity.get("username") or username or "-"
    number = identity.get("license_number")
    return f"{name} (เลข {identity.get('license_type') or 'ทน.'}: {number or '-'})"


def referrer_label(order: object) -> str:
    name = getattr(order, "referrer_name", None)
    if not name:
        return "-"
    parts = [name]
    number = getattr(order, "referrer_license_number", None)
    if number:
        parts.append(f"{getattr(order, 'referrer_license_type', None) or ''} {number}".strip())
    organization = getattr(order, "referrer_organization", None)
    if organization:
        parts.append(organization)
    return " / ".join(parts)


def order_creator_label(order: object) -> str:
    snapshot = getattr(order, "created_by_snapshot", None) or {}
    name = (
        snapshot.get("full_name")
        or snapshot.get("username")
        or getattr(order, "created_by", None)
        or "-"
    )
    if snapshot.get("license_number"):
        return f"{name} ({snapshot.get('license_type') or 'ทน.'} {snapshot['license_number']})"
    return name
