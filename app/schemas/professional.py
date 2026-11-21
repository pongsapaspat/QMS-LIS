from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfessionalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, max_length=200)
    professional_license_number: str | None = Field(default=None, max_length=100)

    @field_validator("full_name", "professional_license_number", mode="before")
    @classmethod
    def normalize(cls, value: object) -> str | None:
        if value is None:
            return None
        return " ".join(str(value).split()) or None
