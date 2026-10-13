"""Manual Stage 4B evaluation. Persistent call ID prevents an accidental second call."""

import asyncio
import json
import time

import httpx

from app.config import PROJECT_ROOT, Settings
from app.services.coaching import CoachingError, analyze_conversation
from app.services.coaching_models import CoachingInput, VerifiedTurn
from app.services.llm_provider import ProviderError
from app.services.openai_provider import OpenAIProvider

FIXTURE = PROJECT_ROOT / "backend/tests/fixtures/external/kapibala_record.json"
CALL_ID = "stage4b-kapibala-mstate-S46_standard-once"


def external_input() -> CoachingInput:
    record = json.loads(FIXTURE.read_text())
    chunks, turns, offset = [], [], 0
    for message in record["messages"]:
        # Dataset documentation explicitly defines a=salesperson, b=customer.
        role = {"a": "salesperson", "b": "customer"}[message["role"]]
        prefix, content = role.title() + ": ", message["content"]
        start = offset + len(prefix)
        turns.append(VerifiedTurn(start=start, end=start + len(content), role=role))
        chunk = prefix + content + "\n"
        chunks.append(chunk)
        offset += len(chunk)
    return CoachingInput(transcript="".join(chunks), verified_turns=turns,
        objective="Qualify enterprise helpdesk fit before peak season, address integration and security requirements, and agree appropriate next steps.",
        customer_context="Customer uses Shopify and Zendesk; repetitive order-tracking and returns tickets need automation before holiday rush. Budget and 14-day timeline fit; security approval is a prerequisite. Synthetic dataset scenario, not real product verification.")


async def main():
    settings = Settings(llm_provider="openai")
    source = external_input()
    destination = PROJECT_ROOT / "data" / "stage4b-openai-evaluation.json"
    destination.parent.mkdir(exist_ok=True)
    started = time.perf_counter()
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(retries=0), follow_redirects=False) as client:
        provider = OpenAIProvider(settings, client, call_id=CALL_ID)
        try:
            result = await analyze_conversation(source, provider)
        except (CoachingError, ProviderError) as error:
            output = {"status": "failed", "error": str(error), "metadata": provider.metadata,
                      "raw_content": provider.raw_content, "budget": provider.ledger.summary(),
                      "latency_seconds": time.perf_counter() - started}
            # Keep the original successful report if someone accidentally reruns.
            (destination.parent / "stage4b-openai-failure.json").write_text(json.dumps(output, indent=2))
            print(json.dumps({k: v for k, v in output.items() if k != "raw_content"}))
            raise SystemExit(1) from None
    output = {"status": "validated", "record_id": json.loads(FIXTURE.read_text())["id"],
              "metadata": provider.metadata, "budget": provider.ledger.summary(), "result": result.model_dump()}
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({"report_file": str(destination), "metadata": provider.metadata,
                      "latency_seconds": result.latency_seconds, "budget": provider.ledger.summary()}))


if __name__ == "__main__":
    asyncio.run(main())
