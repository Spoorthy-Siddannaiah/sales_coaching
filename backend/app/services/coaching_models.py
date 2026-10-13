"""Strict input and report contracts; no generated timestamp field exists."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["salesperson", "customer"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class VerifiedTurn(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    role: Role


class CoachingInput(StrictModel):
    transcript: str = Field(min_length=80, max_length=16000)
    objective: str = Field(min_length=1, max_length=2000)
    customer_context: str = Field(min_length=1, max_length=4000)
    verified_turns: list[VerifiedTurn] = Field(default_factory=list)
    sufficiently_complete: bool = False

    @model_validator(mode="after")
    def validate_input(self) -> "CoachingInput":
        if len(self.transcript.strip()) < 80 or not self.objective.strip() or not self.customer_context.strip():
            raise ValueError("Provide a substantive transcript, objective and customer context.")
        previous_end = 0
        for turn in self.verified_turns:
            if not previous_end <= turn.start < turn.end <= len(self.transcript):
                raise ValueError("Verified turns must be ordered, non-overlapping transcript character spans.")
            previous_end = turn.end
        if self.verified_turns and {turn.role for turn in self.verified_turns} != {"salesperson", "customer"}:
            raise ValueError("Full coaching requires verified salesperson and customer turns.")
        return self


class Evidence(StrictModel):
    quote: str = Field(min_length=1)
    role: Role | None


class Finding(StrictModel):
    text: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class Dimension(StrictModel):
    score: int | None = Field(ge=1, le=5)
    reason: str = Field(min_length=1)
    evidence: list[Evidence]


class Dimensions(StrictModel):
    understanding_customer_needs: Dimension
    discovery_questions: Dimension
    value_explanation: Dimension
    objection_handling: Dimension
    next_step_clarity: Dimension


class Improvement(StrictModel):
    suggestion: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    suggested_phrasing: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class CoachingReport(StrictModel):
    mode: Literal["full", "limited"]
    summary: Finding
    customer_needs_and_pain_points: list[Finding]
    outcome: Finding | None
    questions_asked: list[Finding]
    open_questions: list[Finding]
    next_steps: list[Finding]
    dimensions: Dimensions
    strengths: list[Finding]
    improvements: list[Improvement]
    fewer_improvements_reason: str | None
    evidence_limitations: list[str] = Field(min_length=1)


class CoachingResult(StrictModel):
    report: CoachingReport
    attempts: int
    latency_seconds: float
    validation_failures: list[str] = Field(default_factory=list)
