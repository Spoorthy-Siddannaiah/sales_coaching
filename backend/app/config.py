"""Server-side settings; paths are independent of the launch directory."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_path: Path = PROJECT_ROOT / "data" / "coaching.sqlite3"
    notion_api_token: SecretStr | None = None
    notion_version: str = "2026-03-11"
    llm_api_key: SecretStr | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_timeout: float = Field(default=180, gt=0)
    llm_provider: Literal["ollama", "openai"] = "ollama"
    openai_api_key: SecretStr | None = None
    openai_model: Literal["gpt-4.1-mini"] = "gpt-4.1-mini"
    openai_timeout: float = Field(default=90, gt=0)
    openai_max_input_tokens: int = Field(default=24000, gt=0, le=32000)
    openai_max_output_tokens: int = Field(default=4096, gt=0, le=4096)
    spending_ledger_path: Path = PROJECT_ROOT / "data" / "spending.sqlite3"
    retain_rejected_attribution_excerpt: bool = False
    retain_rejected_diagnostics: bool = False
    rejected_diagnostics_path: Path = PROJECT_ROOT / "data" / "rejected-diagnostics"
    budget_usd: float = Field(default=5, gt=0, le=5)
    budget_reserve_usd: float = Field(default=1, ge=1)

    @field_validator("database_path", "spending_ledger_path", "rejected_diagnostics_path", mode="after")
    @classmethod
    def resolve_database_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value
