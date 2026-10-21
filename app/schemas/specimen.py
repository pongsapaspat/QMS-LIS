
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    collected_at: datetime | None = None
    collection_note: str | None = Field(default=None, max_length=2000)

    @field_validator("collection_note", mode="before")
    @classmethod
    def normalize_collection_note(cls, value: object) -> str | None:
        return _normalize_optional_text(value)


class SpecimenRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejection_reason_code: "RejectionReasonCode | None" = None
    rejection_reason: str | None = Field(default=None, max_length=2000)

    @field_validator("rejection_reason", mode="before")
    @classmethod
    def normalize_rejection_reason(cls, value: object) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_rejection_reason(self) -> "SpecimenRejectRequest":
        if self.rejection_reason_code is None:
            if self.rejection_reason:
                self.rejection_reason_code = RejectionReasonCode.OTHER
            else:
                raise ValueError("rejection reason code is required")
        if self.rejection_reason_code == RejectionReasonCode.OTHER and not self.rejection_reason:
            raise ValueError("rejection reason is required when code is OTHER")
        return self


class RejectionReasonCode(StrEnum):
    WRONG_CONTAINER = "WRONG_CONTAINER"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
    LEAKING_OR_BROKEN = "LEAKING_OR_BROKEN"
    HEMOLYZED = "HEMOLYZED"
    LABEL_MISMATCH = "LABEL_MISMATCH"
    EXPIRED_TRANSPORT_TIME = "EXPIRED_TRANSPORT_TIME"
    CLOTTED = "CLOTTED"
    CONTAMINATED = "CONTAMINATED"
    OTHER = "OTHER"


REJECTION_REASON_LABELS: dict[RejectionReasonCode, str] = {
    RejectionReasonCode.WRONG_CONTAINER: "Wrong container",
    RejectionReasonCode.INSUFFICIENT_VOLUME: "Insufficient volume",
    RejectionReasonCode.LEAKING_OR_BROKEN: "Leaking or broken",
    RejectionReasonCode.HEMOLYZED: "Hemolyzed",
    RejectionReasonCode.LABEL_MISMATCH: "Label mismatch",
    RejectionReasonCode.EXPIRED_TRANSPORT_TIME: "Expired transport time",
    RejectionReasonCode.CLOTTED: "Clotted",
    RejectionReasonCode.CONTAMINATED: "Contaminated",
    RejectionReasonCode.OTHER: "Other",
}


class SpecimenReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_at: datetime | None = None
    receiving_note: str | None = Field(default=None, max_length=2000)

    @field_validator("receiving_note", mode="before")
    @classmethod
    def normalize_receiving_note(cls, value: object) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
    received_at: datetime | None
    received_by: str | None
    receiving_note: str | None
    rejection_reason_code: str | None
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
