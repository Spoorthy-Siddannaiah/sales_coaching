"""Small API contracts for saved conversations and analysis requests."""

from uuid import UUID

from pydantic import Field, field_validator

from app.services.coaching_models import StrictModel


class CustomerContext(StrictModel):
    company: str = Field(min_length=1, max_length=200)
    relevant_needs: str = Field(min_length=1, max_length=1500)
    previous_interactions: str = Field(min_length=1, max_length=1000)
    objective: str = Field(min_length=1, max_length=2000)

    @field_validator("company", "relevant_needs", "previous_interactions", "objective")
    @classmethod
    def substantive(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Provide nonblank fictional/test customer context; use 'None known' where appropriate.")
        return value


class AnalysisRequest(StrictModel):
    request_id: str
    allow_paid: bool = False

    @field_validator("request_id")
    @classmethod
    def uuid_request(cls, value: str) -> str:
        return str(UUID(value))


class FixtureRequest(StrictModel):
    fixture: str = "kapibala"
