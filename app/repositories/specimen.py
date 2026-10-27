from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.order import LabOrder, LabOrderItem
from app.models.specimen import Specimen, SpecimenItem
from app.models.test_catalog import LabTest, SpecimenType


class SpecimenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: object) -> None:
        self.session.add(entity)
        self.session.flush()

    def get_order(self, order_id: int) -> LabOrder | None:
        statement = select(LabOrder).where(LabOrder.id == order_id)
        return self.session.scalars(statement).first()

    def list_order_items(self, order_id: int) -> list[LabOrderItem]:
        statement = (
            select(LabOrderItem)
            .options(selectinload(LabOrderItem.lab_test).selectinload(LabTest.specimen_type))
            .where(LabOrderItem.order_id == order_id)
            .order_by(LabOrderItem.id)
        )
        return list(self.session.scalars(statement))

    def get_specimen(self, specimen_id: int) -> Specimen | None:
        statement = (
            select(Specimen)
            .options(
                selectinload(Specimen.items).selectinload(SpecimenItem.order_item),
                selectinload(Specimen.order).selectinload(LabOrder.patient),
            )
            .where(Specimen.id == specimen_id)
        )
        return self.session.scalars(statement).first()

    def get_by_accession_number(self, accession_number: str) -> Specimen | None:
        statement = (
            select(Specimen)
            .options(
                selectinload(Specimen.items).selectinload(SpecimenItem.order_item),
                selectinload(Specimen.order).selectinload(LabOrder.patient),
            )
            .where(Specimen.accession_number == accession_number)
        )
        return self.session.scalars(statement).first()

    def list_receiving_queue(
        self, *, status: str | None, accession_number: str | None, limit: int
    ) -> list[Specimen]:
        statement = select(Specimen).options(
            selectinload(Specimen.order).selectinload(LabOrder.patient),
            selectinload(Specimen.items),
        )
        if status is not None:
            statement = statement.where(Specimen.status == status)
        if accession_number:
            statement = statement.where(Specimen.accession_number == accession_number)
        statement = statement.order_by(Specimen.collected_at, Specimen.id).limit(limit)
        return list(self.session.scalars(statement))

    def get_order_specimen(self, order_id: int, specimen_type_id: int) -> Specimen | None:
        statement = select(Specimen).where(
            Specimen.order_id == order_id,
            Specimen.specimen_type_id == specimen_type_id,
        )
        return self.session.scalars(statement).first()

    def list_order_specimens(self, order_id: int) -> list[Specimen]:
        statement = (
            select(Specimen)
            .options(selectinload(Specimen.items))
            .where(Specimen.order_id == order_id)
            .order_by(Specimen.specimen_type_code)
        )
        return list(self.session.scalars(statement))

    def all_required_specimens_received(self, order_id: int) -> bool:
        required_type_ids = {
            item.lab_test.specimen_type_id for item in self.list_order_items(order_id)
        }
        if not required_type_ids:
            return False
        specimens = self.list_order_specimens(order_id)
        received_type_ids = {
            specimen.specimen_type_id for specimen in specimens if specimen.status == "RECEIVED"
        }
        return required_type_ids == received_type_ids

    def get_specimen_type(self, specimen_type_id: int) -> SpecimenType | None:
        return self.session.get(SpecimenType, specimen_type_id)
