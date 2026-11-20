from fastapi import APIRouter

from app.api.dependencies import SessionDependency
from app.core.security import ActorDependency, AdminActorDependency
from app.schemas.package import PackageCreate, PackageResponse
from app.services.package import PackageService

router = APIRouter(prefix="/packages", tags=["packages"])


@router.get("", response_model=list[PackageResponse])
def list_packages(session: SessionDependency, actor: ActorDependency, available_only: bool = False):
    return PackageService(session).list(available_only)


@router.post("", response_model=PackageResponse, status_code=201)
def create_package(data: PackageCreate, session: SessionDependency, actor: AdminActorDependency):
    return PackageService(session).save(data, actor.reference)


@router.get("/{package_id}", response_model=PackageResponse)
def get_package(package_id: int, session: SessionDependency, actor: ActorDependency):
    return PackageService(session).get(package_id)


@router.put("/{package_id}", response_model=PackageResponse)
def update_package(
    package_id: int, data: PackageCreate, session: SessionDependency, actor: AdminActorDependency
):
    return PackageService(session).save(data, actor.reference, package_id)
