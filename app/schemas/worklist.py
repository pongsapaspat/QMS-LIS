from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class WorklistTaskType(StrEnum):
    ORDER_PENDING_COLLECTION = "ORDER_PENDING_COLLECTION"
    SPECIMEN_PENDING_RECEIVING = "SPECIMEN_PENDING_RECEIVING"
    RESULT_PENDING_ENTRY = "RESULT_PENDING_ENTRY"
    RESULT_IN_PROGRESS = "RESULT_IN_PROGRESS"
    RESULT_CORRECTION_REQUIRED = "RESULT_CORRECTION_REQUIRED"


class WorklistTaskStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"


class WorklistItem(BaseModel):
    task_type: WorklistTaskType
    task_status: WorklistTaskStatus
    task_label: str
    priority: str
    order_id: int
    order_number: str
    patient_id: int
    patient_hn: str
    patient_display_name: str
    order_item_id: int | None = None
    accession_number: str | None = None
    specimen_id: int | None = None
    specimen_type: str | None = None
    test_code: str | None = None
    test_name: str | None = None
    department_id: int | None = None
    department_code: str | None = None
    current_order_status: str
    current_specimen_status: str | None = None
    current_result_status: str | None = None
    created_at: datetime
    tat_target: datetime | None = None
    source_actor: str | None = None
    next_action_label: str
    next_action_url: str
    detail_url: str


class WorklistDiagnostics(BaseModel):
    active_orders: int
    orders_pending_collection: int
    collected_specimens: int
    received_specimens: int
    pending_results: int


class WorklistResponse(BaseModel):
    items: list[WorklistItem]
    total: int
    page: int
    page_size: int
    counts_by_task_type: dict[str, int]
    diagnostics: WorklistDiagnostics
