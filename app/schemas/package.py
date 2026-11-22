from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class PackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    test_ids: list[int] = Field(min_length=1, max_length=200)
    is_active: bool = True
    reason: str = Field(default="", max_length=500)

    @field_validator("code", "name")
    @classmethod
    def text(cls, value: str, info: ValidationInfo) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Code and name are required")
        return value.upper() if info.field_name == "code" else value

    @field_validator("test_ids")
    @classmethod
    def ids(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value) or len(value) != len(set(value)):
            raise ValueError("Select unique positive test IDs")
        return value


class PackageTestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_en: str
    result_type: str


class PackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    price: Decimal
    is_active: bool
    available: bool
    tests: list[PackageTestResponse]
