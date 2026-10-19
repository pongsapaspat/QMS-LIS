
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.specimen import SpecimenStatus


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


class SpecimenCollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int = Field(ge=1)
    specimen_type_id: int = Field(ge=1)
    collection_note: str | None = Field(default=None, max_length=2000)

    @field_validator("collection_note", mode="before")
    @classmethod
    def normalize_collection_note(cls, value: object) -> str | None:
        return _normalize_optional_text(value)


class SpecimenRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejection_reason: str = Field(min_length=1, max_length=2000)

    @field_validator("rejection_reason", mode="before")
    @classmethod
    def normalize_rejection_reason(cls, value: object) -> str:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            raise ValueError("rejection reason is required")
        return normalized


class SpecimenOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_item_id: int
    created_at: datetime


class SpecimenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    accession_number: str
    order_id: int
    specimen_type_id: int
    specimen_type_code: str
    specimen_type_name_th: str
    specimen_type_name_en: str
    status: SpecimenStatus
    collected_at: datetime
    collected_by: str
    collection_note: str | None
    rejection_reason: str | None
    rejected_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[SpecimenOrderItemResponse]


class SpecimenRequirementItem(BaseModel):
    id: int
    lab_test_id: int
    test_code: str
    test_name_th: str
    test_name_en: str


class SpecimenRequirement(BaseModel):
    specimen_type_id: int
    specimen_type_code: str
    specimen_type_name_th: str
    specimen_type_name_en: str
    items: list[SpecimenRequirementItem]
    specimen: SpecimenResponse | None = None
