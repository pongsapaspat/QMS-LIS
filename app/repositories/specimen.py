
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.order import LabOrder, LabOrderItem
from app.models.specimen import Specimen
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
            .options(selectinload(Specimen.items))
            .where(Specimen.id == specimen_id)
        )
        return self.session.scalars(statement).first()

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

    def get_specimen_type(self, specimen_type_id: int) -> SpecimenType | None:
        return self.session.get(SpecimenType, specimen_type_id)
