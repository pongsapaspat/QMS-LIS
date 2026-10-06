from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies import TestCatalogServiceDependency
from app.core.security import ActorDependency, AdminActorDependency
from app.domain.enums import ResultType
from app.schemas.test_catalog import (
    ActivationRequest,
    AuditHistoryResponse,
    CatalogTestCreate,
    CatalogTestDetail,
    CatalogTestDetailBundle,
    CatalogTestListItem,
    CatalogTestPage,
    CatalogTestUpdate,
    ConfigurationCreate,
    ConfigurationResponse,
    ConfigurationUpdate,
    PriceHistoryResponse,
    QualitativeOptionCreate,
    QualitativeOptionResponse,
    QualitativeOptionUpdate,
    ReferenceRangeCreate,
    ReferenceRangeResponse,
    ReferenceRangeUpdate,
)

category_router = APIRouter(prefix="/test-categories", tags=["test catalog"])
specimen_router = APIRouter(prefix="/specimen-types", tags=["test catalog"])
test_router = APIRouter(prefix="/tests", tags=["test catalog"])


@category_router.post(
    "", response_model=ConfigurationResponse, status_code=status.HTTP_201_CREATED
)
def create_category(
    data: ConfigurationCreate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> ConfigurationResponse:
    return ConfigurationResponse.model_validate(
        service.create_category(data, actor_reference=actor.reference)
    )


@category_router.get("", response_model=list[ConfigurationResponse])
def list_categories(
    service: TestCatalogServiceDependency,
    actor: ActorDependency,
    include_inactive: bool = False,
) -> list[ConfigurationResponse]:
    return [
        ConfigurationResponse.model_validate(item)
        for item in service.list_categories(include_inactive=include_inactive)
    ]


@category_router.patch("/{category_id}", response_model=ConfigurationResponse)
def update_category(
    category_id: int,
    data: ConfigurationUpdate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> ConfigurationResponse:
    return ConfigurationResponse.model_validate(
        service.update_category(category_id, data, actor_reference=actor.reference)
    )


@specimen_router.post(
    "", response_model=ConfigurationResponse, status_code=status.HTTP_201_CREATED
)
def create_specimen_type(
    data: ConfigurationCreate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> ConfigurationResponse:
    return ConfigurationResponse.model_validate(
        service.create_specimen_type(data, actor_reference=actor.reference)
    )


@specimen_router.get("", response_model=list[ConfigurationResponse])
def list_specimen_types(
    service: TestCatalogServiceDependency,
    actor: ActorDependency,
    include_inactive: bool = False,
) -> list[ConfigurationResponse]:
    return [
        ConfigurationResponse.model_validate(item)
        for item in service.list_specimen_types(include_inactive=include_inactive)
    ]


@specimen_router.patch("/{specimen_type_id}", response_model=ConfigurationResponse)
def update_specimen_type(
    specimen_type_id: int,
    data: ConfigurationUpdate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> ConfigurationResponse:
    return ConfigurationResponse.model_validate(
        service.update_specimen_type(
            specimen_type_id, data, actor_reference=actor.reference
        )
    )


@test_router.post("", response_model=CatalogTestDetail, status_code=status.HTTP_201_CREATED)
def create_test(
    data: CatalogTestCreate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> CatalogTestDetail:
    return CatalogTestDetail.model_validate(
        service.create_test(data, actor_reference=actor.reference)
    )


@test_router.get("", response_model=CatalogTestPage)
def list_tests(
    service: TestCatalogServiceDependency,
    actor: ActorDependency,
    search: str | None = None,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    specimen_type_id: Annotated[int | None, Query(ge=1)] = None,
    result_type: ResultType | None = None,
    is_active: bool | None = True,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CatalogTestPage:
    items, total = service.list_tests(
        search=search,
        category_id=category_id,
        specimen_type_id=specimen_type_id,
        result_type=result_type,
        is_active=is_active,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return CatalogTestPage(
        items=[CatalogTestListItem.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@test_router.get("/{test_id}", response_model=CatalogTestDetailBundle)
def get_test(
    test_id: int,
    service: TestCatalogServiceDependency,
    actor: ActorDependency,
) -> CatalogTestDetailBundle:
    test = service.get_test(test_id)
    return CatalogTestDetailBundle(
        test=CatalogTestDetail.model_validate(test),
        reference_ranges=[
            ReferenceRangeResponse.model_validate(item)
            for item in service.list_reference_ranges(test_id)
        ],
        qualitative_options=[
            QualitativeOptionResponse.model_validate(item)
            for item in service.list_qualitative_options(test_id)
        ],
        price_history=[
            PriceHistoryResponse.model_validate(item)
            for item in service.list_price_history(test_id)
        ],
        audit_history=[
            AuditHistoryResponse.model_validate(item)
            for item in service.list_test_audit_history(test_id)
        ],
    )


@test_router.patch("/{test_id}", response_model=CatalogTestDetail)
def update_test(
    test_id: int,
    data: CatalogTestUpdate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> CatalogTestDetail:
    return CatalogTestDetail.model_validate(
        service.update_test(test_id, data, actor_reference=actor.reference)
    )


@test_router.patch("/{test_id}/activation", response_model=CatalogTestDetail)
def set_test_activation(
    test_id: int,
    data: ActivationRequest,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> CatalogTestDetail:
    return CatalogTestDetail.model_validate(
        service.set_test_activation(test_id, data, actor_reference=actor.reference)
    )


@test_router.post(
    "/{test_id}/reference-ranges",
    response_model=ReferenceRangeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reference_range(
    test_id: int,
    data: ReferenceRangeCreate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> ReferenceRangeResponse:
    return ReferenceRangeResponse.model_validate(
        service.create_reference_range(test_id, data, actor_reference=actor.reference)
    )


@test_router.patch(
    "/{test_id}/reference-ranges/{range_id}", response_model=ReferenceRangeResponse
)
def update_reference_range(
    test_id: int,
    range_id: int,
    data: ReferenceRangeUpdate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> ReferenceRangeResponse:
    return ReferenceRangeResponse.model_validate(
        service.update_reference_range(
            test_id, range_id, data, actor_reference=actor.reference
        )
    )


@test_router.patch(
    "/{test_id}/reference-ranges/{range_id}/activation",
    response_model=ReferenceRangeResponse,
)
def set_reference_range_activation(
    test_id: int,
    range_id: int,
    data: ActivationRequest,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> ReferenceRangeResponse:
    return ReferenceRangeResponse.model_validate(
        service.set_reference_range_activation(
            test_id, range_id, data, actor_reference=actor.reference
        )
    )


@test_router.post(
    "/{test_id}/qualitative-options",
    response_model=QualitativeOptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_qualitative_option(
    test_id: int,
    data: QualitativeOptionCreate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> QualitativeOptionResponse:
    return QualitativeOptionResponse.model_validate(
        service.create_qualitative_option(test_id, data, actor_reference=actor.reference)
    )


@test_router.patch(
    "/{test_id}/qualitative-options/{option_id}",
    response_model=QualitativeOptionResponse,
)
def update_qualitative_option(
    test_id: int,
    option_id: int,
    data: QualitativeOptionUpdate,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> QualitativeOptionResponse:
    return QualitativeOptionResponse.model_validate(
        service.update_qualitative_option(
            test_id, option_id, data, actor_reference=actor.reference
        )
    )


@test_router.patch(
    "/{test_id}/qualitative-options/{option_id}/activation",
    response_model=QualitativeOptionResponse,
)
def set_qualitative_option_activation(
    test_id: int,
    option_id: int,
    data: ActivationRequest,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> QualitativeOptionResponse:
    return QualitativeOptionResponse.model_validate(
        service.set_qualitative_option_activation(
            test_id, option_id, data, actor_reference=actor.reference
        )
    )
