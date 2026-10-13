"""Small read-only Notion client. Provider responses never become error messages."""

from typing import Any
from uuid import UUID
from asyncio import sleep
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import random

import httpx


class NotionImportError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def block_id(value: Any) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise NotionImportError(502, "unsupported_structure", "Notion returned an invalid block identifier.") from error


class NotionClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        # Shared across this import: repeated pages cannot each incur unlimited waits.
        self.retries_remaining = 5
        self.wait_remaining = 10.0

    async def retry(self, attempt: int, response: httpx.Response | None = None) -> bool:
        if attempt >= 2 or self.retries_remaining <= 0:
            return False
        delay = 0.5 * (2 ** attempt) + random.uniform(0, 0.1)
        header = response.headers.get("Retry-After") if response is not None else None
        if header is not None:
            try:
                delay = float(header)
            except ValueError:
                try:
                    date = parsedate_to_datetime(header)
                    delay = (date - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    pass  # Invalid header: retain bounded backoff.
            if not math.isfinite(delay) or delay < 0:
                delay = 0.5 * (2 ** attempt)
        # Never shorten a valid provider wait; stop instead if it exceeds our budget.
        if delay > self.wait_remaining:
            return False
        self.retries_remaining -= 1
        self.wait_remaining -= delay
        await sleep(delay)
        return True

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # Only GETs are retried. No database write occurs during retrieval.
        for attempt in range(3):
            try:
                response = await self.client.get(path, params=params)
            except httpx.RequestError as error:
                if await self.retry(attempt):
                    continue
                if isinstance(error, httpx.TimeoutException):
                    raise NotionImportError(504, "notion_timeout", "Notion timed out. Retry the import later.") from error
                raise NotionImportError(502, "notion_connection", "Could not connect to Notion. Check connectivity and retry.") from error
            if response.status_code in {429, 500, 502, 503, 504} and await self.retry(attempt, response):
                continue
            break

        errors = {
            401: (401, "notion_unauthorized", "Notion rejected the token. Check NOTION_API_TOKEN locally."),
            403: (403, "notion_forbidden", "Notion denied access. Enable Read content and share the page with the connection."),
            404: (404, "notion_not_found", "The page or transcript is missing or inaccessible. Check its ID and connection access."),
            429: (429, "notion_rate_limited", "Notion rate limited the request. Wait before retrying."),
        }
        if response.status_code in errors:
            raise NotionImportError(*errors[response.status_code])
        if response.status_code != 200:
            raise NotionImportError(502, "notion_api_error", "Notion could not complete the request. Check the API version and retry later.")
        try:
            data = response.json()
        except ValueError as error:
            raise NotionImportError(502, "invalid_notion_response", "Notion returned invalid JSON.") from error
        if not isinstance(data, dict):
            raise NotionImportError(502, "invalid_notion_response", "Notion returned an unexpected response.")
        return data

    async def children(self, parent_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(100):
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = await self.get(f"/blocks/{block_id(parent_id)}/children", params)
            blocks = data.get("results")
            if data.get("object") != "list" or not isinstance(blocks, list) or not all(isinstance(item, dict) for item in blocks):
                raise NotionImportError(502, "unsupported_structure", "Notion returned an invalid block list.")
            for item in blocks:
                if item.get("object") != "block" or not isinstance(item.get("has_children"), bool) or not isinstance(item.get("type"), str):
                    raise NotionImportError(422, "unsupported_structure", "Notion returned incomplete block metadata; no partial import was saved.")
                block_id(item.get("id"))
            results.extend(blocks)
            if data.get("has_more") is False:
                return results
            cursor = data.get("next_cursor")
            if data.get("has_more") is not True or not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise NotionImportError(502, "unsupported_structure", "Notion returned inconsistent pagination.")
            seen_cursors.add(cursor)
        raise NotionImportError(422, "source_too_large", "The source exceeds this prototype's pagination limit; no partial import was saved.")

    async def block(self, identifier: str) -> dict[str, Any]:
        data = await self.get(f"/blocks/{block_id(identifier)}")
        if data.get("object") != "block" or block_id(data.get("id")) != block_id(identifier):
            raise NotionImportError(502, "unsupported_structure", "Notion returned an unexpected transcript block.")
        if not isinstance(data.get("has_children"), bool):
            raise NotionImportError(422, "unsupported_structure", "Transcript child metadata is missing; no partial import was saved.")
        return data
