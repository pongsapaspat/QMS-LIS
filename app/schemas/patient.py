import re
import unicodedata
from datetime import date, datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.domain.enums import BloodGroup, Sex

MISSING_VALUE_MARKERS = frozenset(
    marker.casefold() for marker in ("-", "–", "—", "N/A", "NA", "ไม่มี", "ไม่ระบุ")
)
PASSPORT_PATTERN = re.compile(r"^[A-Z0-9]{6,20}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9]{8,15}$")
PATIENT_PHONE_PATTERN = re.compile(r"^[0-9]{10}$")
NATIONAL_ID_SEPARATOR_PATTERN = re.compile(r"[\s\-\u2010-\u2015]+")
PHONE_SEPARATOR_PATTERN = re.compile(r"[\s().-]+")


def is_valid_thai_national_id(value: str) -> bool:
    # The LIS accepts synthetic/test identifiers, so format validation is
    # intentionally limited to exactly 13 numeric digits. Checksum validation
    # would prevent test and simulation data from being entered.
    return bool(re.fullmatch(r"[0-9]{13}", value))


def normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    if not normalized or normalized.casefold() in MISSING_VALUE_MARKERS:
        return None
    return normalized


def normalize_national_id(value: object) -> str | None:
    normalized = normalize_optional_text(value)
    if normalized is None:
        return None
    normalized = NATIONAL_ID_SEPARATOR_PATTERN.sub("", normalized)
    if not is_valid_thai_national_id(normalized):
        raise ValueError("invalid Thai National ID")
    return normalized


def normalize_passport_number(value: object) -> str | None:
    normalized = normalize_optional_text(value)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if not PASSPORT_PATTERN.fullmatch(normalized):
        raise ValueError("invalid passport number")
    return normalized


def normalize_phone_number(value: object) -> str | None:
    normalized = normalize_optional_text(value)
    if normalized is None:
        return None
    normalized = PHONE_SEPARATOR_PATTERN.sub("", normalized)
    if not PHONE_PATTERN.fullmatch(normalized):
        raise ValueError("invalid phone number")
    return normalized


def normalize_patient_phone(value: object) -> str | None:
    normalized = normalize_optional_text(value)
    if normalized is None:
        return None
    normalized = PHONE_SEPARATOR_PATTERN.sub("", normalized)
    if not PATIENT_PHONE_PATTERN.fullmatch(normalized):
        raise ValueError("phone number must contain exactly 10 digits")
    return normalized


def normalize_english_name(value: object) -> str | None:
    normalized = normalize_optional_text(value)
    if normalized is None:
        return None
    return normalized[0].upper() + normalized[1:]


def validate_identity_fields(
    national_id: object,
    passport_number: object,
) -> tuple[str | None, str | None]:
    return normalize_national_id(national_id), normalize_passport_number(passport_number)


class PatientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: int = Field(default=1, ge=1)
    title: str | None = Field(default=None, max_length=30)
    first_name_th: str | None = Field(default=None, max_length=100)
    last_name_th: str | None = Field(default=None, max_length=100)
    first_name_en: str | None = Field(default=None, max_length=100)
    last_name_en: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    sex: Sex | None = None
    national_id: str | None = None
    passport_number: str | None = Field(default=None, max_length=30)
    phone_number: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None
    blood_group: BloodGroup | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_relationship: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)
    confirm_possible_duplicate: bool = False

    @field_validator(
        "title",
        "first_name_th",
        "last_name_th",
        "address",
        "emergency_contact_name",
        "emergency_contact_relationship",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return normalize_optional_text(value)

    @field_validator("first_name_en", "last_name_en", mode="before")
    @classmethod
    def normalize_english_names(cls, value: object) -> str | None:
        return normalize_english_name(value)

    @field_validator("national_id", mode="before")
    @classmethod
    def validate_national_id(cls, value: object) -> str | None:
        return validate_identity_fields(value, None)[0]

    @field_validator("passport_number", mode="before")
    @classmethod
    def normalize_passport(cls, value: object) -> str | None:
        return validate_identity_fields(None, value)[1]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> str | None:
        return normalize_optional_text(value)

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_patient_phone_number(cls, value: object) -> str | None:
        return normalize_patient_phone(value)

    @field_validator("emergency_contact_phone", mode="before")
    @classmethod
    def normalize_emergency_phone(cls, value: object) -> str | None:
        return normalize_phone_number(value)

    @field_validator("date_of_birth")
    @classmethod
    def reject_future_birth_date(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("date of birth cannot be in the future")
        return value

    @model_validator(mode="after")
    def require_name(self) -> "PatientCreate":
        thai_complete = bool(self.first_name_th and self.last_name_th)
        english_complete = bool(self.first_name_en and self.last_name_en)
        if not thai_complete and not english_complete:
            raise ValueError("a complete Thai or English name is required")
        return self


class PatientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=30)
    first_name_th: str | None = Field(default=None, max_length=100)
    last_name_th: str | None = Field(default=None, max_length=100)
    first_name_en: str | None = Field(default=None, max_length=100)
    last_name_en: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    sex: Sex | None = None
    national_id: str | None = None
    passport_number: str | None = Field(default=None, max_length=30)
    phone_number: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None
    blood_group: BloodGroup | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_relationship: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None
    change_reason: str = Field(min_length=3, max_length=500)

    @field_validator(
        "title",
        "first_name_th",
        "last_name_th",
        "address",
        "emergency_contact_name",
        "emergency_contact_relationship",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return normalize_optional_text(value)

    @field_validator("first_name_en", "last_name_en", mode="before")
    @classmethod
    def normalize_english_names(cls, value: object) -> str | None:
        return normalize_english_name(value)

    @field_validator("national_id", mode="before")
    @classmethod
    def validate_national_id(cls, value: object) -> str | None:
        return validate_identity_fields(value, None)[0]

    @field_validator("passport_number", mode="before")
    @classmethod
    def normalize_passport(cls, value: object) -> str | None:
        return validate_identity_fields(None, value)[1]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> str | None:
        return normalize_optional_text(value)

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_patient_phone_number(cls, value: object) -> str | None:
        return normalize_patient_phone(value)

    @field_validator("emergency_contact_phone", mode="before")
    @classmethod
    def normalize_emergency_phone(cls, value: object) -> str | None:
        return normalize_phone_number(value)

    @field_validator("change_reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("change reason is required")
        return normalized

    @field_validator("date_of_birth")
    @classmethod
    def reject_future_birth_date(cls, value: date | None) -> date | None:
        return PatientCreate.reject_future_birth_date(value)

    @model_validator(mode="after")
    def require_change(self) -> "PatientUpdate":
        if self.model_fields_set == {"change_reason"}:
            raise ValueError("at least one patient field must change")
        return self


class PatientDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    branch_id: int | None
    hn: str
    title: str | None
    first_name_th: str | None
    last_name_th: str | None
    first_name_en: str | None
    last_name_en: str | None
    date_of_birth: date | None
    sex: str | None
    national_id: str | None
    passport_number: str | None
    phone_number: str | None
    address: str | None
    email: str | None
    blood_group: str | None
    emergency_contact_name: str | None
    emergency_contact_relationship: str | None
    emergency_contact_phone: str | None
    identity_document_missing: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PatientListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    branch_id: int | None
    hn: str
    display_name: str
    identity_document_missing: bool
    is_active: bool


class PatientPage(BaseModel):
    items: list[PatientListItem]
    total: int
    page: int
    page_size: int


class DuplicateCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: int
    hn: str
    display_name: str
    match_reason: str


class DuplicateCheckResponse(BaseModel):
    candidates: list[DuplicateCandidateResponse]


class DuplicateCheckQuery(BaseModel):
    national_id: str | None = None
    passport_number: str | None = None
    first_name_th: str | None = None
    last_name_th: str | None = None
    first_name_en: str | None = None
    last_name_en: str | None = None
    date_of_birth: date | None = None

    @field_validator("national_id", mode="before")
    @classmethod
    def validate_national_id(cls, value: object) -> str | None:
        return validate_identity_fields(value, None)[0]

    @field_validator("passport_number", mode="before")
    @classmethod
    def normalize_passport(cls, value: object) -> str | None:
        return validate_identity_fields(None, value)[1]
