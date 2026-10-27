from fastapi import APIRouter, Query

from app.api.dependencies import ResultServiceDependency
from app.core.security import ResultMutationDependency, ResultReaderDependency
from app.models.result import Result
from app.schemas.result import MultiResultSave, ResultEdit, ResultResponse

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/worklist")
def worklist(
    service: ResultServiceDependency,
    actor: ResultReaderDependency,
    department_id: int | None = None,
    result_status: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    rows, total = service.worklist(
        department_id=department_id,
        status=result_status,
        search=search,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "items": [
            {
                "order_item_id": item.id,
                "order_id": item.order_id,
                "order_number": item.order.order_number,
                "accession_number": specimen.accession_number,
                "patient_hn": item.order.patient.hn,
                "department_id": item.lab_test.department_id,
                "department_code": item.lab_test.department.code,
                "test_code": item.test_code,
                "result_status": result.status if result else "PENDING",
                "abnormal_flag": result.abnormal_flag if result else None,
            }
            for item, specimen, result in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/orders/{order_id}")
def result_context(
    order_id: int, service: ResultServiceDependency, actor: ResultReaderDependency
) -> dict[str, object]:
    items = service.context(order_id)
    return {
        "order_id": order_id,
        "items": [
            {
                "order_item_id": item.id,
                "test_code": item.test_code,
                "test_name": item.test_name_en,
                "result_type": item.result_type,
                "unit": item.result_unit,
                "options": [
                    option.code for option in item.lab_test.qualitative_options if option.is_active
                ],
                "result": ResultResponse.model_validate(item.result).model_dump(mode="json")
                if item.result
                else None,
            }
            for item in items
        ],
    }


@router.post("/orders/{order_id}", response_model=list[ResultResponse])
def save_results(
    order_id: int,
    data: MultiResultSave,
    service: ResultServiceDependency,
    actor: ResultMutationDependency,
) -> list[Result]:
    return service.save_multiple(order_id, data, actor_reference=actor.reference)


@router.put("/{result_id}", response_model=ResultResponse)
def edit_result(
    result_id: int,
    data: ResultEdit,
    service: ResultServiceDependency,
    actor: ResultMutationDependency,
) -> Result:
    return service.edit(result_id, data, actor_reference=actor.reference)
