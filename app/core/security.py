from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class Actor:
    reference: str
    role: str


def get_current_actor(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Actor:
    if settings.app_env == "development":
        role = request.headers.get("X-Role") or request.cookies.get("qms_lis_dev_role")
        reference = request.headers.get("X-Actor") or request.cookies.get("qms_lis_dev_actor")
    else:
        role = None
        reference = None
    role = role or request.session.get("role")
    reference = reference or request.session.get("actor")

    if role is None and settings.app_env == "development" and settings.enable_dev_admin_fallback:
        return Actor(reference="development-admin", role="ADMIN")
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return Actor(reference=(reference or "unknown-actor")[:100], role=role.upper())


def require_admin(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "IT"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ADMIN or IT role required",
        )
    return actor


AdminActorDependency = Annotated[Actor, Depends(require_admin)]


def require_admin_only(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ADMIN role required",
        )
    return actor


AdminOnlyActorDependency = Annotated[Actor, Depends(require_admin_only)]


def require_audit_reader(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_SUPERVISOR"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LAB_SUPERVISOR or ADMIN role required",
        )
    return actor


AuditReaderDependency = Annotated[Actor, Depends(require_audit_reader)]


def require_specimen_collector(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_TECH", "IT"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LAB_TECH or ADMIN role required",
        )
    return actor


SpecimenCollectorDependency = Annotated[Actor, Depends(require_specimen_collector)]


def require_specimen_receiving_reader(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_TECH", "RECEPTION", "IT"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="RECEPTION, LAB_TECH or ADMIN role required",
        )
    return actor


SpecimenReceivingReaderDependency = Annotated[Actor, Depends(require_specimen_receiving_reader)]


def require_result_reader(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_TECH", "LAB_SUPERVISOR", "IT"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LAB_TECH, LAB_SUPERVISOR or ADMIN role required",
        )
    return actor


ResultReaderDependency = Annotated[Actor, Depends(require_result_reader)]


def require_result_mutator(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_TECH", "IT"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LAB_TECH or ADMIN role required",
        )
    return actor


ResultMutationDependency = Annotated[Actor, Depends(require_result_mutator)]
ActorDependency = Annotated[Actor, Depends(get_current_actor)]


def require_result_verifier(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_TECH", "LAB_SUPERVISOR", "IT"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="result verification permission required",
        )
    return actor


ResultVerifierDependency = Annotated[Actor, Depends(require_result_verifier)]


def require_result_releaser(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_SUPERVISOR", "IT"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LAB_SUPERVISOR or ADMIN role required",
        )
    return actor


ResultReleaserDependency = Annotated[Actor, Depends(require_result_releaser)]
