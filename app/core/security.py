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
    role = request.headers.get("X-Role") or request.cookies.get("qms_lis_dev_role")
    reference = request.headers.get("X-Actor") or request.cookies.get("qms_lis_dev_actor")

    if role is None and settings.app_env == "development" and settings.enable_dev_admin_fallback:
        return Actor(reference="development-admin", role="ADMIN")
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return Actor(reference=(reference or "unknown-actor")[:100], role=role.upper())


def require_admin(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ADMIN role required",
        )
    return actor


AdminActorDependency = Annotated[Actor, Depends(require_admin)]


def require_specimen_collector(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
    if actor.role not in {"ADMIN", "LAB_TECH"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LAB_TECH or ADMIN role required",
        )
    return actor


SpecimenCollectorDependency = Annotated[Actor, Depends(require_specimen_collector)]
ActorDependency = Annotated[Actor, Depends(get_current_actor)]
