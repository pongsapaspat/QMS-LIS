from collections import Counter
from dataclasses import dataclass, field

from app.models.order import LabOrder, OrderStatus
from app.models.result import ResultStatus
from app.models.specimen import Specimen, SpecimenStatus

ORDER_STATUS_LABELS = {
    OrderStatus.ORDERED: "สั่งตรวจแล้ว",
    OrderStatus.SPECIMENS_RECEIVED: "รับสิ่งส่งตรวจครบ",
    OrderStatus.RESULTS_IN_PROGRESS: "กำลังลงผล",
    OrderStatus.RESULTS_COMPLETED: "ลงผลครบ รอตรวจสอบ",
    OrderStatus.RESULTS_VERIFIED: "ตรวจสอบครบ รอเผยแพร่",
    OrderStatus.RELEASED: "เผยแพร่แล้ว",
    OrderStatus.CANCELLED: "ยกเลิก",
}


@dataclass
class OrderProgress:
    required: int = 0
    collected: int = 0
    received: int = 0
    recollection: int = 0
    internal: int = 0
    verified: int = 0
    awaiting_verification: int = 0
    outlab: int = 0
    outlab_ready: int = 0
    outlab_statuses: Counter[str] = field(default_factory=Counter)
    pending_rooms: Counter[str | None] = field(default_factory=Counter)
    can_enter_results: bool = False


def summarize_order(order: LabOrder, specimens: list[Specimen]) -> OrderProgress:
    current = {
        link.order_item_id: specimen
        for specimen in specimens if specimen.is_current
        for link in specimen.items
    }
    groups: dict[tuple[int, str], tuple[Specimen | None, str | None]] = {}
    progress = OrderProgress()
    for item in order.items:
        specimen = current.get(item.id)
        specimen_type = specimen.specimen_type if specimen else item.lab_test.specimen_type
        group = f"OUTLAB-{item.id}" if item.is_outlab else "INTERNAL"
        groups[(specimen_type.id, group)] = (specimen, specimen_type.collection_room)
        if item.is_outlab:
            progress.outlab += 1
            if item.outlab:
                progress.outlab_ready += item.outlab.ready
                progress.outlab_statuses[item.outlab.status] += 1
            continue
        progress.internal += 1
        status = item.result.status if item.result else None
        progress.verified += status in {ResultStatus.VERIFIED, ResultStatus.RELEASED}
        progress.awaiting_verification += status == ResultStatus.COMPLETED
        if specimen and specimen.status == SpecimenStatus.RECEIVED:
            progress.can_enter_results |= status in {
                None, ResultStatus.PENDING, ResultStatus.IN_PROGRESS,
                ResultStatus.VERIFICATION_REJECTED, ResultStatus.AMENDMENT_REQUESTED,
            }

    progress.required = len(groups)
    for specimen, room in groups.values():
        status = specimen.status if specimen else None
        progress.collected += status in {SpecimenStatus.COLLECTED, SpecimenStatus.RECEIVED}
        progress.received += status == SpecimenStatus.RECEIVED
        progress.recollection += status == SpecimenStatus.REJECTED
        if status not in {SpecimenStatus.COLLECTED, SpecimenStatus.RECEIVED}:
            progress.pending_rooms[room] += 1
    return progress
