"""Small typed records for the foundation, not the final coaching schema."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Conversation(BaseModel):
    id: str
    provider: Literal["notion", "offline_fixture"] = "notion"
    source_id: str
    title: str
    source_url: str | None = None
    created_at: datetime


class TranscriptVersion(BaseModel):
    id: str
    conversation_id: str
    content_hash: str
    original_text: str
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    turns: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    imported_at: datetime


class Analysis(BaseModel):
    id: str
    transcript_version_id: str
    customer_context: dict[str, Any]
    objective: str
    salesperson: str | None = None
    status: Literal["pending", "analyzing", "completed", "failed"] = "pending"
    model: str
    report: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    database: Literal["ok"] = "ok"
