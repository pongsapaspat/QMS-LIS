from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import Sex
from app.schemas.patient import (
    normalize_optional_text,
    normalize_patient_phone,
    normalize_phone_number,
)


class BookingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appointment_at: datetime
    source: str = Field(default="LINE OA", min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=30)
    first_name_th: str | None = Field(default=None, max_length=100)
    last_name_th: str | None = Field(default=None, max_length=100)
    sex: Sex | None = None
    phone_number: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=500)
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_relationship: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)
    requested_services: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    test_ids: list[int] = Field(default_factory=list, max_length=200)
    package_ids: list[int] = Field(default_factory=list, max_length=50)

    @field_validator(
        "source",
        "title",
        "first_name_th",
        "last_name_th",
        "address",
        "emergency_contact_name",
        "emergency_contact_relationship",
        "requested_services",
        "note",
        mode="before",
    )
    @classmethod
    def text(cls, value: object) -> str | None:
        return normalize_optional_text(value)

    @field_validator("phone_number", mode="before")
    @classmethod
    def phone(cls, value: object) -> str | None:
        return normalize_patient_phone(value)

    @field_validator("emergency_contact_phone", mode="before")
    @classmethod
    def emergency_phone(cls, value: object) -> str | None:
        return normalize_phone_number(value)

    @field_validator("test_ids", "package_ids")
    @classmethod
    def ids(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value) or len(value) != len(set(value)):
            raise ValueError("รายการตรวจหรือแพ็กเกจไม่ถูกต้องหรือซ้ำกัน")
        return value

    @model_validator(mode="after")
    def identifiable(self) -> "BookingInput":
        if not self.first_name_th and not self.last_name_th and not self.phone_number:
            raise ValueError("กรุณาระบุชื่อหรือเบอร์โทรอย่างน้อยหนึ่งอย่าง")
        if self.appointment_at.tzinfo is None or self.appointment_at.utcoffset() is None:
            raise ValueError("กรุณาระบุวันเวลานัดหมายให้ถูกต้อง")
        return self
