from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.order import OrderPriority, OrderStatus


class LabOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: int = Field(ge=1)
    test_ids: list[int] = Field(default_factory=list, max_length=200)
    package_ids: list[int] = Field(default_factory=list, max_length=50)
    priority: OrderPriority = OrderPriority.ROUTINE
    clinical_note: str | None = Field(default=None, max_length=2000)

    @field_validator("test_ids", "package_ids")
    @classmethod
    def validate_test_ids(cls, value: list[int]) -> list[int]:
        if any(test_id < 1 for test_id in value):
            raise ValueError("test IDs must be positive")
        if len(value) != len(set(value)):
            raise ValueError("a Lab Test may only be selected once")
        return value

    @model_validator(mode='after')
    def require_selection(self):
        if not self.test_ids and not self.package_ids:
            raise ValueError('Select at least one test or package')
        return self

    @field_validator("clinical_note", mode="before")
    @classmethod
    def normalize_note(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = " ".join(str(value).split())
        return normalized or None


class LabOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lab_test_id: int
    included_in_package: bool = False
    is_outlab: bool = False
    test_code: str
    test_name_th: str
    test_name_en: str
    result_type: str
    result_unit: str | None
    price: Decimal
    created_at: datetime


class LabOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    patient_id: int
    status: OrderStatus
    priority: OrderPriority
    clinical_note: str | None
    ordered_at: datetime
    created_by: str
    verified_at: datetime | None
    verified_by: str | None
    released_at: datetime | None
    released_by: str | None
    created_at: datetime
    updated_at: datetime
    items: list[LabOrderItemResponse]
    total_price: Decimal
    package_snapshots: list[dict] | None = None


class LabOrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    patient_id: int
    status: OrderStatus
    priority: OrderPriority
    ordered_at: datetime
    created_by: str
