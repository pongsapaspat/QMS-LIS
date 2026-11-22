from collections import Counter
from datetime import timedelta

from sqlalchemy.orm import Session

from app.domain.collection import CollectionRoom
from app.models.order import OrderPriority
from app.models.test_catalog import LaboratoryDepartment
from app.repositories.worklist import WorklistRecord, WorklistRepository
from app.schemas.worklist import (
    WorklistItem,
    WorklistResponse,
    WorklistResultTest,
    WorklistTaskStatus,
    WorklistTaskType,
)

ALL_TASK_TYPES = set(WorklistTaskType)
PENDING_TASK_TYPES = {
    WorklistTaskType.ORDER_PENDING_COLLECTION,
    WorklistTaskType.SPECIMEN_PENDING_RECEIVING,
    WorklistTaskType.RESULT_PENDING_ENTRY,
}


class WorklistService:
    def __init__(self, session: Session, repository: WorklistRepository | None = None) -> None:
        self.repository = repository or WorklistRepository(session)

    def list_tasks(
        self,
        *,
        task_type: WorklistTaskType | None,
        department_id: int | None,
        priority: OrderPriority | None,
        status: WorklistTaskStatus | None,
        search: str | None,
        page: int,
        page_size: int,
        group_collection_orders: bool = False,
        result_tasks_only: bool = False,
        collection_filter: str = "all",
        collection_room: CollectionRoom | None = None,
    ) -> WorklistResponse:
        task_types = {task_type} if task_type is not None else set(ALL_TASK_TYPES)
        if result_tasks_only:
            task_types &= {
                WorklistTaskType.RESULT_PENDING_ENTRY,
                WorklistTaskType.RESULT_IN_PROGRESS,
                WorklistTaskType.RESULT_CORRECTION_REQUIRED,
            }
        if status == WorklistTaskStatus.PENDING:
            task_types &= PENDING_TASK_TYPES
        elif status == WorklistTaskStatus.IN_PROGRESS:
            task_types &= {WorklistTaskType.RESULT_IN_PROGRESS}
        elif status == WorklistTaskStatus.CORRECTION_REQUIRED:
            task_types &= {WorklistTaskType.RESULT_CORRECTION_REQUIRED}
        records = self.repository.list_records(
            task_types={item.value for item in task_types},
            department_id=department_id,
            priority=priority.value if priority is not None else None,
            search=search.strip() if search and search.strip() else None,
            collection_room=collection_room.value if collection_room else None,
        )
        items = sorted((self._to_item(record) for record in records), key=self._sort_key)
        if collection_room is not None:
            for item in items:
                if item.task_type == WorklistTaskType.ORDER_PENDING_COLLECTION:
                    item.next_action_url += f"?collection_room={collection_room.value}"
        if group_collection_orders:
            items = self._group_collection_orders(items)
            if collection_filter == "recollection":
                items = [item for item in items if item.current_specimen_status == "REJECTED"]
            elif collection_filter == "initial":
                items = [item for item in items if item.current_specimen_status != "REJECTED"]
        counts = Counter(item.task_type.value for item in items)
        if result_tasks_only:
            items = self._group_result_orders(items)
        all_counts = {item.value: counts.get(item.value, 0) for item in WorklistTaskType}
        offset = (page - 1) * page_size
        return WorklistResponse(
            items=items[offset : offset + page_size],
            total=len(items),
            page=page,
            page_size=page_size,
            counts_by_task_type=all_counts,
            diagnostics=self.repository.diagnostics(),
        )

    @staticmethod
    def _group_result_orders(items: list[WorklistItem]) -> list[WorklistItem]:
        orders: dict[int, WorklistItem] = {}
        for item in items:
            if item.order_id not in orders:
                order = item.model_copy(deep=True)
                order.task_label = "ลงผลตรวจของ Order"
                order.next_action_label = "ลงผลตรวจ"
                order.department_id = None
                order.department_code = None
                order.department_name = None
                orders[item.order_id] = order
            order = orders[item.order_id]
            order.result_tests.append(
                WorklistResultTest.model_validate(
                    {field: getattr(item, field) for field in WorklistResultTest.model_fields}
                )
            )
            key = item.task_type.value
            order.result_status_counts[key] = order.result_status_counts.get(key, 0) + 1
        return list(orders.values())

    @staticmethod
    def _group_collection_orders(items: list[WorklistItem]) -> list[WorklistItem]:
        grouped: list[WorklistItem] = []
        orders: dict[int, WorklistItem] = {}
        for item in items:
            if item.task_type != WorklistTaskType.ORDER_PENDING_COLLECTION:
                grouped.append(item)
                continue
            if item.order_id not in orders:
                item = item.model_copy(deep=True)
                item.next_action_label = "Collect specimens"
                orders[item.order_id] = item
                grouped.append(item)
            order = orders[item.order_id]
            if item.current_specimen_status == "REJECTED":
                order.current_specimen_status = "REJECTED"
                order.task_label = "รอเก็บสิ่งส่งตรวจใหม่"
                order.next_action_label = "เก็บสิ่งส่งตรวจใหม่"
            if item.specimen_type and item.specimen_type not in order.pending_specimens:
                order.pending_specimens.append(item.specimen_type)
            if order.department_id != item.department_id:
                order.department_id = None
                order.department_code = None
                order.department_name = None
        return grouped

    def summary_counts(self) -> dict[str, int]:
        response = self.list_tasks(
            task_type=None,
            department_id=None,
            priority=None,
            status=None,
            search=None,
            page=1,
            page_size=1,
        )
        return response.counts_by_task_type

    def departments(self) -> list[LaboratoryDepartment]:
        return self.repository.list_departments()

    @staticmethod
    def _to_item(record: WorklistRecord) -> WorklistItem:
        task_type = WorklistTaskType(record.task_type)
        labels = {
            WorklistTaskType.ORDER_PENDING_COLLECTION: (
                "Specimen collection required",
                "Collect specimen",
                f"/orders/{record.order_id}/specimens",
            ),
            WorklistTaskType.SPECIMEN_PENDING_RECEIVING: (
                "Specimen awaiting receipt",
                "Receive specimen",
                f"/specimens/receiving/{record.specimen_id}",
            ),
            WorklistTaskType.RESULT_PENDING_ENTRY: (
                "Laboratory result required",
                "Enter result",
                f"/worklist/orders/{record.order_id}",
            ),
            WorklistTaskType.RESULT_IN_PROGRESS: (
                "Laboratory result in progress",
                "Continue result entry",
                f"/worklist/orders/{record.order_id}",
            ),
            WorklistTaskType.RESULT_CORRECTION_REQUIRED: (
                "Result correction required",
                "Correct result",
                f"/worklist/orders/{record.order_id}",
            ),
        }
        task_label, action_label, action_url = labels[task_type]
        if (task_type == WorklistTaskType.ORDER_PENDING_COLLECTION
                and record.current_specimen_status == "REJECTED"):
            task_label, action_label = "รอเก็บสิ่งส่งตรวจใหม่", "เก็บสิ่งส่งตรวจใหม่"
        tat_target = (
            record.created_at + timedelta(minutes=record.tat_minutes)
            if record.tat_minutes is not None
            else None
        )
        return WorklistItem(
            task_type=task_type,
            task_status=WorklistTaskStatus(record.task_status),
            task_label=task_label,
            priority=record.priority,
            order_id=record.order_id,
            order_number=record.order_number,
            patient_id=record.patient_id,
            patient_hn=record.patient_hn,
            patient_display_name=record.patient_display_name,
            order_item_id=record.order_item_id,
            accession_number=record.accession_number,
            specimen_id=record.specimen_id,
            specimen_type=record.specimen_type,
            test_code=record.test_code,
            test_name=record.test_name,
            department_id=record.department_id,
            department_code=record.department_code,
            department_name=record.department_name,
            current_order_status=record.current_order_status,
            current_specimen_status=record.current_specimen_status,
            current_result_status=record.current_result_status,
            created_at=record.created_at,
            tat_target=tat_target,
            source_actor=record.source_actor,
            next_action_label=action_label,
            next_action_url=action_url,
            detail_url=f"/orders/{record.order_id}",
        )

    @staticmethod
    def _sort_key(item: WorklistItem) -> tuple[object, ...]:
        return (
            0 if item.priority == OrderPriority.URGENT else 1,
            item.tat_target.timestamp() if item.tat_target is not None else float("inf"),
            item.created_at.timestamp(),
            item.task_type.value,
            item.order_id,
            item.specimen_id or 0,
            item.order_item_id or 0,
        )
