from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_camel(string: str) -> str:
  """Convert snake_case to camelCase so the API accepts frontend-style payloads."""
  parts = string.split("_")
  if not parts:
    return string
  return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


class BasicInfo(BaseModel):
  model_config = ConfigDict(populate_by_name=True, extra="ignore", alias_generator=_to_camel)
  age: int = Field(..., description="User's age")
  gender: str = Field(..., description="User's gender")
  gender_other: str | None = Field(None, description="Other gender description if applicable")
  city: str = Field(..., description="User's city")
  country: str = Field(..., description="User's country")

  @field_validator("age")
  @classmethod
  def validate_age(cls, v: int) -> int:
    if v < 13:
      raise ValueError("Age must be 13 or older")
    return v


class Personalization(BaseModel):
  model_config = ConfigDict(populate_by_name=True, extra="ignore", alias_generator=_to_camel)
  occupation: str = Field(..., description="User's occupation")
  topics_of_interest: list[str] = Field(..., description="List of topics user is interested in")
  intended_use: str = Field(..., description="Intended use of the platform")
  intended_use_other: str | None = Field(None, description="Other intended use if applicable")

  @field_validator("topics_of_interest")
  @classmethod
  def validate_topics(cls, v: list[str]) -> list[str]:
    if not v:
      raise ValueError("At least one topic of interest is required")
    return v


class LegalConsent(BaseModel):
  model_config = ConfigDict(populate_by_name=True, extra="ignore", alias_generator=_to_camel)
  accepted_terms: bool = Field(..., description="Whether terms of service are accepted")
  accepted_privacy: bool = Field(..., description="Whether privacy policy is accepted")
  terms_version: str = Field(..., description="Version of the terms accepted")
  privacy_version: str = Field(..., description="Version of the privacy policy accepted")

  @field_validator("accepted_terms", "accepted_privacy")
  @classmethod
  def validate_acceptance(cls, v: bool) -> bool:
    if not v:
      raise ValueError("Must accept legal agreements")
    return v


class OnboardingRequest(BaseModel):
  model_config = ConfigDict(populate_by_name=True, extra="ignore", alias_generator=_to_camel)
  basic: BasicInfo
  personalization: Personalization
  legal: LegalConsent
