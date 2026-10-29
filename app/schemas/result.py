from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _text(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("value is required")
    return value


class ResultItemSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_item_id: int = Field(gt=0)
    version: int | None = Field(default=None, ge=1)
    numeric_value: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    text_value: str | None = Field(default=None, max_length=2000)
    categorical_value: str | None = Field(default=None, max_length=150)
    complete: bool = False
    acknowledge_critical: bool = False

    @field_validator("text_value", "categorical_value")
    @classmethod
    def normalize_value(cls, value: str | None) -> str | None:
        return _text(value) if value is not None else None

    @model_validator(mode="after")
    def only_one_value(self) -> "ResultItemSave":
        values = [
            self.numeric_value is not None,
            self.text_value is not None,
            self.categorical_value is not None,
        ]
        if sum(values) > 1:
            raise ValueError("only one result value may be supplied")
        return self


class MultiResultSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ResultItemSave] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_items(self) -> "MultiResultSave":
        if len({item.order_item_id for item in self.items}) != len(self.items):
            raise ValueError("each order item may appear only once")
        return self


class ResultEdit(ResultItemSave):
    modification_reason: str = Field(min_length=1, max_length=500)

    _reason = field_validator("modification_reason")(_text)


class ResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_item_id: int
    specimen_id: int
    result_type: str
    numeric_value: Decimal | None
    text_value: str | None
    categorical_value: str | None
    result_unit_snapshot: str | None
    reference_range_snapshot: dict[str, object] | None
    abnormal_flag: str | None
    status: str
    entered_at: datetime | None
    entered_by: str | None
    verified_at: datetime | None
    verified_by: str | None
    verification_comment: str | None
    verification_rejected_at: datetime | None
    verification_rejected_by: str | None
    verification_rejection_reason: str | None
    released_at: datetime | None
    released_by: str | None
    version: int


class VerificationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=1000)
    version: int | None = Field(default=None, ge=1)
    bypass_four_eyes: bool = False

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class VerificationRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)
    version: int | None = Field(default=None, ge=1)

    _reason = field_validator("reason")(_text)


class OrderRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class ResultRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    previous_value: dict[str, object] | None
    new_value: dict[str, object] | None
    previous_flag: str | None
    new_flag: str | None
    modification_reason: str
    modified_at: datetime
    modified_by: str


class WorklistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    order_item_id: int
    order_id: int
    order_number: str
    accession_number: str
    patient_hn: str
    patient_name: str
    department_id: int
    department_code: str
    test_code: str
    test_name: str
    specimen_type: str
    priority: str
    result_status: str
    received_at: str
    tat_target: str
    abnormal_flag: str | None
