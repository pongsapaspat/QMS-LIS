from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import AgeUnit, ReferenceSex, ResultType


def normalize_required_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("value is required")
    return normalized


def normalize_optional_required_text(value: str | None) -> str | None:
    return None if value is None else normalize_required_text(value)


def normalize_code(value: str) -> str:
    normalized = "".join(value.split()).upper()
    if not normalized:
        raise ValueError("code is required")
    return normalized


def normalize_reason(value: str | None) -> str:
    if value is None:
        return ""
    normalized = " ".join(value.split())
    return normalized


def normalize_optional_code(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_code(value)


class ConfigurationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=30)
    name_th: str = Field(min_length=1, max_length=150)
    name_en: str = Field(min_length=1, max_length=150)
    reason: str = Field(default="", max_length=500)

    _code = field_validator("code")(normalize_code)
    _names = field_validator("name_th", "name_en")(normalize_required_text)
    _reason = field_validator("reason", mode="before")(normalize_reason)


class ConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_th: str | None = Field(default=None, min_length=1, max_length=150)
    name_en: str | None = Field(default=None, min_length=1, max_length=150)
    is_active: bool | None = None
    reason: str = Field(default="", max_length=500)

    _names = field_validator("name_th", "name_en")(normalize_optional_required_text)
    _reason = field_validator("reason", mode="before")(normalize_reason)

    @model_validator(mode="after")
    def require_change(self) -> "ConfigurationUpdate":
        if not (self.model_fields_set - {"reason"}):
            raise ValueError("at least one field must change")
        return self


class ConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name_th: str
    name_en: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z0-9_-]+$")
    name_th: str = Field(min_length=1, max_length=150)
    name_en: str = Field(min_length=1, max_length=150)
    is_active: bool = True
    reason: str = Field(default="", max_length=500)

    _code = field_validator("code", mode="before")(normalize_code)
    _names = field_validator("name_th", "name_en")(normalize_required_text)
    _reason = field_validator("reason", mode="before")(normalize_reason)


class DepartmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(
        default=None, min_length=2, max_length=30, pattern=r"^[A-Z0-9_-]+$"
    )
    name_th: str | None = Field(default=None, min_length=1, max_length=150)
    name_en: str | None = Field(default=None, min_length=1, max_length=150)
    reason: str = Field(default="", max_length=500)

    _code = field_validator("code", mode="before")(normalize_optional_code)
    _names = field_validator("name_th", "name_en")(normalize_optional_required_text)
    _reason = field_validator("reason", mode="before")(normalize_reason)

    @model_validator(mode="after")
    def require_change(self) -> "DepartmentUpdate":
        if not (self.model_fields_set - {"reason"}):
            raise ValueError("at least one field must change")
        return self


class DepartmentResponse(ConfigurationResponse):
    test_count: int = 0


class DepartmentPage(BaseModel):
    items: list[DepartmentResponse]
    total: int
    page: int
    page_size: int


class DepartmentDetail(DepartmentResponse):
    tests: list["CatalogTestListItem"] = Field(default_factory=list)


class CatalogTestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    name_th: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    category_id: int = Field(ge=1)
    department_id: int = Field(ge=1)
    specimen_type_id: int = Field(ge=1)
    current_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    result_type: ResultType
    result_unit: str | None = Field(default=None, max_length=50)
    tat_minutes: int = Field(gt=0, le=525600)
    reason: str = Field(default="", max_length=500)

    _code = field_validator("code")(normalize_code)
    _names = field_validator("name_th", "name_en")(normalize_required_text)
    _reason = field_validator("reason", mode="before")(normalize_reason)

    @field_validator("result_unit", mode="before")
    @classmethod
    def normalize_unit(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = " ".join(str(value).split())
        return normalized or None

    @model_validator(mode="after")
    def validate_result_configuration(self) -> "CatalogTestCreate":
        if self.result_type == ResultType.NUMERIC and not self.result_unit:
            raise ValueError("result unit is required for numeric tests")
        if self.result_type == ResultType.QUALITATIVE and self.result_unit:
            raise ValueError("qualitative tests must not define a numeric result unit")
        return self


class CatalogTestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=40)
    name_th: str | None = Field(default=None, min_length=1, max_length=200)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = Field(default=None, ge=1)
    department_id: int | None = Field(default=None, ge=1)
    specimen_type_id: int | None = Field(default=None, ge=1)
    current_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    result_type: ResultType | None = None
    result_unit: str | None = Field(default=None, max_length=50)
    tat_minutes: int | None = Field(default=None, gt=0, le=525600)
    reason: str = Field(default="", max_length=500)

    _code = field_validator("code", mode="before")(normalize_optional_code)
    _names = field_validator("name_th", "name_en")(normalize_optional_required_text)
    _reason = field_validator("reason", mode="before")(normalize_reason)

    @field_validator("result_unit", mode="before")
    @classmethod
    def normalize_unit(cls, value: object) -> str | None:
        return CatalogTestCreate.normalize_unit(value)

    @model_validator(mode="after")
    def require_change(self) -> "CatalogTestUpdate":
        if not (self.model_fields_set - {"reason"}):
            raise ValueError("at least one field must change")
        return self


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool
    reason: str = Field(default="", max_length=500)

    _reason = field_validator("reason", mode="before")(normalize_reason)


class CatalogTestListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name_th: str
    name_en: str
    current_price: Decimal
    result_type: str
    result_unit: str | None
    tat_minutes: int
    is_active: bool
    category: ConfigurationResponse
    department: ConfigurationResponse
    specimen_type: ConfigurationResponse


class CatalogTestDetail(CatalogTestListItem):
    parameters: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CatalogTestPage(BaseModel):
    items: list[CatalogTestListItem]
    total: int
    page: int
    page_size: int


class ReferenceRangeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sex: ReferenceSex = ReferenceSex.ALL
    minimum_age: int = Field(ge=0)
    maximum_age: int = Field(ge=0)
    age_unit: AgeUnit = AgeUnit.YEARS
    lower_value: Decimal
    upper_value: Decimal
    lower_critical: Decimal | None = None
    upper_critical: Decimal | None = None
    display_text: str | None = Field(default=None, max_length=500)
    context_metadata: dict[str, str] | None = None
    reason: str = Field(default="", max_length=500)

    _reason = field_validator("reason", mode="before")(normalize_reason)

    @model_validator(mode="after")
    def validate_bounds(self) -> "ReferenceRangeCreate":
        if self.minimum_age > self.maximum_age:
            raise ValueError("minimum age must not exceed maximum age")
        if self.lower_value > self.upper_value:
            raise ValueError("lower reference value must not exceed upper reference value")
        if (
            self.lower_critical is not None
            and self.upper_critical is not None
            and self.lower_critical > self.upper_critical
        ):
            raise ValueError("lower critical value must not exceed upper critical value")
        return self


class ReferenceRangeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sex: ReferenceSex | None = None
    minimum_age: int | None = Field(default=None, ge=0)
    maximum_age: int | None = Field(default=None, ge=0)
    age_unit: AgeUnit | None = None
    lower_value: Decimal | None = None
    upper_value: Decimal | None = None
    lower_critical: Decimal | None = None
    upper_critical: Decimal | None = None
    display_text: str | None = Field(default=None, max_length=500)
    context_metadata: dict[str, str] | None = None
    reason: str = Field(default="", max_length=500)

    _reason = field_validator("reason", mode="before")(normalize_reason)

    @model_validator(mode="after")
    def require_change(self) -> "ReferenceRangeUpdate":
        if not (self.model_fields_set - {"reason"}):
            raise ValueError("at least one field must change")
        return self


class ReferenceRangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_id: int
    sex: str
    minimum_age: int
    maximum_age: int
    age_unit: str
    lower_value: Decimal
    upper_value: Decimal
    lower_critical: Decimal | None
    upper_critical: Decimal | None
    display_text: str | None
    context_metadata: dict[str, str] | None
    is_active: bool


class QualitativeOptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    label_th: str = Field(min_length=1, max_length=150)
    label_en: str = Field(min_length=1, max_length=150)
    sort_order: int = Field(default=0, ge=0)
    is_abnormal: bool | None = None
    reason: str = Field(default="", max_length=500)

    _code = field_validator("code")(normalize_code)
    _labels = field_validator("label_th", "label_en")(normalize_required_text)
    _reason = field_validator("reason", mode="before")(normalize_reason)


class QualitativeOptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_th: str | None = Field(default=None, min_length=1, max_length=150)
    label_en: str | None = Field(default=None, min_length=1, max_length=150)
    sort_order: int | None = Field(default=None, ge=0)
    is_abnormal: bool | None = None
    reason: str = Field(default="", max_length=500)

    _labels = field_validator("label_th", "label_en")(normalize_optional_required_text)
    _reason = field_validator("reason")(normalize_reason)

    @model_validator(mode="after")
    def require_change(self) -> "QualitativeOptionUpdate":
        if not (self.model_fields_set - {"reason"}):
            raise ValueError("at least one field must change")
        return self


class QualitativeOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_id: int
    code: str
    label_th: str
    label_en: str
    sort_order: int
    is_abnormal: bool | None
    is_active: bool


class PriceHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    old_price: Decimal | None
    new_price: Decimal
    effective_at: datetime
    reason: str
    actor_reference: str


class AuditHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    changed_fields: list[str]
    reason: str
    actor_reference: str
    occurred_at: datetime


class CatalogTestDetailBundle(BaseModel):
    test: CatalogTestDetail
    reference_ranges: list[ReferenceRangeResponse]
    qualitative_options: list[QualitativeOptionResponse]
    price_history: list[PriceHistoryResponse]
    audit_history: list[AuditHistoryResponse]


class CatalogFilters(BaseModel):
    search: str | None = None
    category_id: int | None = None
    department_id: int | None = None
    specimen_type_id: int | None = None
    result_type: ResultType | None = None
    is_active: bool | None = True
