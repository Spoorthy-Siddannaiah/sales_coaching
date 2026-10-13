"""One paid structured-output request; no retries, repair or model fallback."""

import json
import uuid

import httpx

from app.config import Settings
from app.services.llm_provider import OllamaProvider, ProviderError
from app.services.spending import SpendingLedger


class OpenAIProvider:
    max_attempts = 1

    def __init__(self, settings: Settings, client: httpx.AsyncClient, *, call_id: str | None = None):
        self.settings, self.client = settings, client
        self.call_id = call_id or str(uuid.uuid4())
        self.ledger = SpendingLedger(settings)
        self.metadata: dict = {}
        self.raw_content: str | None = None

    async def generate(self, messages, schema) -> str:
        key = self.settings.openai_api_key
        if key is None or not key.get_secret_value().strip():
            raise ProviderError("Configure OPENAI_API_KEY in the root .env file.")
        payload = {"model": self.settings.openai_model, "messages": messages, "temperature": 0,
                   "max_completion_tokens": self.settings.openai_max_output_tokens,
                   "response_format": {"type": "json_schema", "json_schema": {"name": "coaching_report", "strict": True, "schema": schema}}}
        # UTF-8 bytes bound byte-level BPE text tokens. Include the schema and
        # generous framing allowance; reject rather than truncate input.
        estimate = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 2048
        if estimate > self.settings.openai_max_input_tokens:
            raise ProviderError("Input exceeds the conservative token limit; no request was sent.")
        reserved = self.ledger.reserve(self.call_id, estimate, self.settings.openai_max_output_tokens)
        self.metadata = {"call_id": self.call_id, "requested_model": self.settings.openai_model,
                         "estimated_input_tokens_upper_bound": estimate, "reserved_cost_usd": reserved / 1000000}
        try:
            response = await self.client.post("https://api.openai.com/v1/chat/completions", json=payload,
                headers={"Authorization": "Bearer " + key.get_secret_value()}, timeout=self.settings.openai_timeout)
        except httpx.RequestError as error:
            raise ProviderError("OpenAI request failed or timed out. No retry; full budget reservation retained.") from error
        if response.status_code != 200:
            raise ProviderError(f"OpenAI returned HTTP {response.status_code}. No retry; reservation retained. Check provider dashboard.")
        try:
            data = response.json()
            usage = data["usage"]
            input_tokens, output_tokens = usage["prompt_tokens"], usage["completion_tokens"]
            if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
                raise ValueError("Invalid usage")
            amount = self.ledger.settle(self.call_id, input_tokens, output_tokens)
            self.metadata.update({"model": data["model"], "input_tokens": input_tokens, "output_tokens": output_tokens,
                                  "estimated_cost_usd": amount / 1000000, "usage": usage, "http_status": response.status_code})
            choice = data["choices"][0]
            content = choice["message"].get("content")
            if isinstance(content, str):
                self.raw_content = content
            if not data["model"].startswith(self.settings.openai_model) or choice["finish_reason"] != "stop" or choice["message"].get("refusal") or not isinstance(content, str):
                raise ValueError("Incomplete, refused or unexpected-model response")
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise ProviderError("OpenAI returned an invalid, refused or incomplete response; no retry.") from error
        return content


def create_provider(settings: Settings, client: httpx.AsyncClient, *, call_id: str | None = None):
    return OpenAIProvider(settings, client, call_id=call_id) if settings.llm_provider == "openai" else OllamaProvider(settings, client)
