"""Application factory and local health endpoint."""

import sqlite3
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi.responses import JSONResponse
from app.routes import conversations, analyses, fixtures
from app.repositories.analyses import interrupt_stale
from app.services.analysis_workflow import AnalysisRunner
from app.services.openai_provider import create_provider

from fastapi import Depends, FastAPI, HTTPException, Request

from app.config import Settings
from app.database import check_database, initialize_database
from app.models import HealthResponse
from app.services.notion_client import NotionClient, NotionImportError
from app.services.notion_import import NotionImportRequest, NotionImportResponse, import_native_transcript, parse_page_id


async def get_notion_client(request: Request) -> AsyncIterator[NotionClient]:
    settings = request.app.state.settings
    token = settings.notion_api_token
    if token is None or not token.get_secret_value().strip():
        raise HTTPException(503, detail={"code": "notion_not_configured", "message": "Set NOTION_API_TOKEN in your local .env and restart the server."})
    if settings.notion_version != "2026-03-11":
        raise HTTPException(422, detail={"code": "unsupported_api_version", "message": "This native importer requires NOTION_VERSION=2026-03-11."})
    async with httpx.AsyncClient(
        base_url="https://api.notion.com/v1/",
        headers={"Authorization": f"Bearer {token.get_secret_value()}", "Notion-Version": settings.notion_version},
        timeout=15,
    ) as client:
        yield NotionClient(client)


def create_app(settings: Settings | None = None, provider_factory=create_provider) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        initialize_database(configuration.database_path)
        application.state.settings = configuration
        interrupt_stale(configuration.database_path)
        application.state.analysis_runner = AnalysisRunner(configuration, provider_factory)
        try:
            yield
        finally:
            await application.state.analysis_runner.close()

    application = FastAPI(title="Intellegam Sales Coaching", lifespan=lifespan)

    application.include_router(conversations.router)
    application.include_router(analyses.router)
    application.include_router(fixtures.router)

    @application.exception_handler(sqlite3.Error)
    async def database_error(request: Request, error: sqlite3.Error):
        return JSONResponse(status_code=503, content={"detail": "Local storage is unavailable. Check the database and restart if necessary."})

    from app.services.coaching import PROMPT_VERSION
    from app.services.evidence_validator import VALIDATOR_VERSION
    import os

    @application.get("/runtime")
    def runtime():
        return {"provider": configuration.llm_provider,
                "model": configuration.openai_model if configuration.llm_provider == "openai" else configuration.ollama_model,
                "paid_approval_required": configuration.llm_provider == "openai",
                "prompt_version": PROMPT_VERSION, "validator_version": VALIDATOR_VERSION,
                "backend_pid": os.getpid(), "rejected_diagnostics_enabled": configuration.retain_rejected_diagnostics}

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        try:
            check_database(configuration.database_path)
        except sqlite3.Error as error:
            raise HTTPException(
                status_code=503, detail="Database unavailable. Check local storage."
            ) from error
        return HealthResponse()

    @application.post("/imports/notion", response_model=NotionImportResponse)
    async def import_notion(body: NotionImportRequest, notion: NotionClient = Depends(get_notion_client)) -> NotionImportResponse:
        try:
            page_id = parse_page_id(body.page)
            return await import_native_transcript(notion, configuration.database_path, page_id, configuration.notion_version)
        except NotionImportError as error:
            raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
        except sqlite3.Error as error:
            raise HTTPException(503, detail={"code": "database_unavailable", "message": "Could not save the import. Check local storage and retry."}) from error

    return application
