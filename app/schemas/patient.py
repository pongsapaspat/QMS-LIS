from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def is_valid_thai_national_id(value: str) -> bool:
    if len(value) != 13 or not value.isdigit() or value[0] == "0":
        return False
    weighted_sum = sum(
        int(digit) * weight
        for digit, weight in zip(value[:12], range(13, 1, -1), strict=True)
    )
    check_digit = (11 - (weighted_sum % 11)) % 10
    return check_digit == int(value[-1])


class PatientFields(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date | None = None
    thai_national_id: str | None = None
    passport_number: str | None = Field(default=None, max_length=30)

    @field_validator("first_name", "last_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @field_validator("thai_national_id", mode="before")
    @classmethod
    def validate_thai_national_id(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).replace("-", "").replace(" ", "")
        if not is_valid_thai_national_id(normalized):
            raise ValueError("invalid Thai National ID")
        return normalized

    @field_validator("passport_number", mode="before")
    @classmethod
    def normalize_passport(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None


class PatientCreate(PatientFields):
    branch_id: int = Field(default=1, ge=1)


class PatientUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    date_of_birth: date | None = None
    thai_national_id: str | None = None
    passport_number: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None

    _normalize_name = field_validator("first_name", "last_name")(
        PatientFields.normalize_name.__func__
    )
    _validate_thai_id = field_validator("thai_national_id", mode="before")(
        PatientFields.validate_thai_national_id.__func__
    )
    _normalize_passport = field_validator("passport_number", mode="before")(
        PatientFields.normalize_passport.__func__
    )

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "PatientUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    branch_id: int
    hn: str
    first_name: str
    last_name: str
    date_of_birth: date | None
    thai_national_id: str | None
    passport_number: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
