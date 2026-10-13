"""Minimal provider protocol and Ollama adapter; no model substitution."""

from typing import Any, Protocol

import httpx

from app.config import Settings


class ProviderError(RuntimeError):
    pass


class LLMProvider(Protocol):
    async def generate(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str: ...


class OllamaProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    async def generate(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        try:
            response = await self.client.post(
                self.settings.ollama_base_url.rstrip("/") + "/api/chat",
                json={"model": self.settings.ollama_model, "messages": messages,
                      "format": schema, "stream": False,
                      "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 3072}},
                timeout=self.settings.ollama_timeout,
            )
        except httpx.TimeoutException as error:
            raise ProviderError("Ollama timed out; no valid report was produced.") from error
        except httpx.RequestError as error:
            raise ProviderError("Cannot connect to Ollama. Check the configured local service.") from error
        if response.status_code != 200:
            raise ProviderError(f"Ollama returned HTTP {response.status_code}. Check the configured model and service; no substitute was used.")
        try:
            data = response.json()
            content = data["message"]["content"]
            if data.get("model") != self.settings.ollama_model:
                raise ValueError("Unexpected model")
            if data.get("done") is not True or data.get("done_reason") == "length" or not isinstance(content, str):
                raise ValueError("Incomplete response")
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderError("Ollama returned an invalid or incomplete response envelope.") from error
        return content
