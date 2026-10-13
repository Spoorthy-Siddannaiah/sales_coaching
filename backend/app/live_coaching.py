"""Manual synthetic evaluation; no endpoint, Notion access or SQLite writes."""

import asyncio
import json
import re
import time
from pathlib import Path

import httpx

from app.config import PROJECT_ROOT, Settings
from app.services.coaching import CoachingError, analyze_conversation
from app.services.coaching_models import CoachingInput, VerifiedTurn
from app.services.llm_provider import ProviderError
from app.services.openai_provider import create_provider


def synthetic_input() -> CoachingInput:
    text = (PROJECT_ROOT / "backend/tests/fixtures/synthetic_sales.txt").read_text()
    turns = []
    # Explicit fixture labels are verified by its fictional author. This is NOT
    # a role-inference/parser path for native Notion transcripts.
    for match in re.finditer(r"^(Salesperson|Customer): (.+)$", text, re.MULTILINE):
        turns.append(VerifiedTurn(start=match.start(2), end=match.end(2), role=match.group(1).lower()))
    return CoachingInput(
        transcript=text, verified_turns=turns,
        objective="Understand onboarding needs and qualify whether a fictional-data pilot is appropriate.",
        customer_context="Fictional Northbridge Freight: forty operations staff, expanding depots, spreadsheet onboarding. Avoid duplicate entry and respect security review.",
    )


async def main() -> None:
    settings = Settings()
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient() as client:
            result = await analyze_conversation(synthetic_input(), create_provider(settings, client))
    except (CoachingError, ProviderError) as error:
        print(json.dumps({"status": "failed", "latency_seconds": round(time.perf_counter() - started, 2), "error": str(error)}))
        raise SystemExit(1) from None
    destination = PROJECT_ROOT / "data" / f"synthetic-{settings.llm_provider}-report.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(result.model_dump_json(indent=2))
    print(json.dumps({"model": settings.openai_model if settings.llm_provider == "openai" else settings.ollama_model, "attempts": result.attempts,
                      "latency_seconds": round(result.latency_seconds, 2),
                      "validation_failures": result.validation_failures, "report_file": str(destination)}))


if __name__ == "__main__":
    asyncio.run(main())
