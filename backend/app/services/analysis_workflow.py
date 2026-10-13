"""One in-process job at a time, with durable inputs/state and no blind restart."""

import asyncio
import json
import time
from collections.abc import Callable

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import Settings
from app.repositories import analyses, conversations
from app.services.coaching import CoachingError, PROMPT_VERSION, analyze_conversation
from app.services.coaching_models import CoachingInput, VerifiedTurn
from app.services.llm_provider import ProviderError
from app.services.evidence_validator import VALIDATOR_VERSION
from app.services.openai_provider import create_provider
from app.workflow_models import AnalysisRequest


def coaching_input(record: dict) -> CoachingInput:
    context, transcript = record["customer_context"], record["transcript"]
    if context is None:
        raise HTTPException(422, detail="Save fictional/test customer context before analysis.")
    if transcript is None:
        raise HTTPException(422, detail="This conversation has no saved transcript.")
    limit = CoachingInput.model_json_schema()["properties"]["transcript"]["maxLength"]
    if len(transcript["original_text"]) > limit:
        raise HTTPException(422, detail=(
            f"The complete transcript is saved ({len(transcript['original_text']):,} characters), "
            f"but coaching supports at most {limit:,} characters. No analysis was started or paid call made. "
            "View the full transcript in Transcript. Use a shorter meeting for coaching; "
            "this prototype does not split or truncate transcripts."))
    # Only the allowlisted labelled fixture supplies verified roles. Native text
    # segments cannot establish a speaker just because they alternate.
    turns = transcript["turns"] if record["provider"] == "offline_fixture" else []
    try:
        return CoachingInput(transcript=transcript["original_text"], objective=context["objective"],
            customer_context=json.dumps({key: value for key, value in context.items() if key != "objective"}),
            verified_turns=[VerifiedTurn.model_validate(turn) for turn in turns],
            sufficiently_complete=bool(turns) and transcript["source_metadata"].get("content_status") == "complete")
    except (ValidationError, KeyError):
        raise HTTPException(422, detail="Transcript or context is unusable: check its length, required fields and verified roles.") from None


class AnalysisRunner:
    def __init__(self, settings: Settings, provider_factory: Callable = create_provider):
        self.settings, self.provider_factory = settings, provider_factory
        self.task: asyncio.Task | None = None

    def submit(self, conversation_id: str, request: AnalysisRequest) -> dict:
        record = conversations.detail(self.settings.database_path, conversation_id)
        if record is None:
            raise HTTPException(404, detail="Conversation not found.")
        existing = analyses.by_request(self.settings.database_path, request.request_id)
        if existing:
            if not any(item["id"] == existing["id"] for item in record["analyses"]):
                raise HTTPException(409, detail="This request ID belongs to another conversation.")
            return existing
        if self.task is not None and not self.task.done():
            raise HTTPException(409, detail="An analysis is already running. Wait for it to finish before starting another.")
        source = coaching_input(record)
        if self.settings.llm_provider == "openai" and not request.allow_paid:
            raise HTTPException(409, detail="OpenAI requires explicit approval of this one paid request. No call was made.")
        model = self.settings.openai_model if self.settings.llm_provider == "openai" else self.settings.ollama_model
        analyses.create_analysis(self.settings.database_path, request.request_id, record["transcript"]["id"],
                                 record["customer_context"], self.settings.llm_provider, model)
        self.task = asyncio.create_task(self.run(request.request_id, source))
        return analyses.get_analysis(self.settings.database_path, request.request_id)

    async def run(self, identifier: str, source: CoachingInput) -> None:
        started = time.perf_counter()
        provider = None
        try:
            analyses.start(self.settings.database_path, identifier)
            async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(retries=0), follow_redirects=False) as client:
                provider = self.provider_factory(self.settings, client, call_id=identifier)
                result = await analyze_conversation(source, provider, diagnostics_path=(
                    self.settings.rejected_diagnostics_path if self.settings.retain_rejected_diagnostics else None),
                    retain_attribution_excerpt=self.settings.retain_rejected_attribution_excerpt)
            analyses.finish(self.settings.database_path, identifier, report=result.report.model_dump(), error=None,
                            metadata={**getattr(provider, "metadata", {}), "prompt_version": PROMPT_VERSION, "validator_version": VALIDATOR_VERSION}, latency=result.latency_seconds)
        except asyncio.CancelledError:
            analyses.finish(self.settings.database_path, identifier, report=None,
                error="Analysis interrupted; no automatic retry. An uncertain provider charge may remain reserved.",
                metadata={**getattr(provider, "metadata", {}), "prompt_version": PROMPT_VERSION, "validator_version": VALIDATOR_VERSION}, latency=time.perf_counter() - started)
            raise
        except Exception as error:
            # Known service errors contain safe messages; unknown exceptions do
            # not expose stack traces, provider payloads, or private transcript text.
            message = str(error) if isinstance(error, (CoachingError, ProviderError)) else "Analysis failed unexpectedly. Check local storage and configuration; no automatic retry was made."
            analyses.finish(self.settings.database_path, identifier, report=None, error=message,
                            metadata={**getattr(provider, "metadata", {}), "prompt_version": PROMPT_VERSION, "validator_version": VALIDATOR_VERSION}, latency=time.perf_counter() - started)

    async def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
