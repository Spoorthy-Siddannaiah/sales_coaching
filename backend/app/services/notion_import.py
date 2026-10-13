"""Native Meeting Notes only. Text segments are not inferred conversation turns."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.database import connect_database
from app.models import Conversation, TranscriptVersion
from app.services.notion_client import NotionClient, NotionImportError, block_id


class NotionImportRequest(BaseModel):
    page: str = Field(min_length=1, max_length=2048)


class TranscriptSegment(BaseModel):
    block_id: str
    text: str


class NotionImportResponse(BaseModel):
    conversation: Conversation
    transcript: TranscriptVersion
    reused: bool
    segments: list[TranscriptSegment]
    speaker_attribution: str = "unavailable"
    turn_timestamps: str = "unavailable"


def parse_page_id(value: str) -> str:
    candidate = value.strip()
    if "://" in candidate:
        try:
            parsed = urlparse(candidate)
            host = (parsed.hostname or "").lower()
        except ValueError as error:
            raise NotionImportError(422, "invalid_page_id", "Enter a valid Notion HTTPS page URL.") from error
        allowed_host = host == "app.notion.com" or any(
            host == domain or host.endswith("." + domain)
            for domain in ("notion.so", "notion.site")
        )
        if parsed.scheme != "https" or not allowed_host:
            raise NotionImportError(422, "invalid_page_id", "Enter a Notion HTTPS page URL or UUID.")
        candidate = unquote(parsed.path).rstrip("/").rsplit("/", 1)[-1]
        match = re.search(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$", candidate)
        if not match:
            raise NotionImportError(422, "invalid_page_id", "The Notion URL does not contain a page ID.")
        candidate = match.group(1)
    try:
        return str(UUID(candidate))
    except ValueError as error:
        raise NotionImportError(422, "invalid_page_id", "Enter a valid Notion page UUID or page URL.") from error


def plain_text(rich_text: Any) -> str:
    if not isinstance(rich_text, list) or not all(isinstance(item, dict) and isinstance(item.get("plain_text"), str) for item in rich_text):
        raise NotionImportError(422, "unsupported_structure", "Transcript rich text has an unsupported structure; no partial import was saved.")
    return "".join(item["plain_text"] for item in rich_text)


class NativeTranscriptReader:
    def __init__(self, notion: NotionClient) -> None:
        self.notion = notion
        self.snapshot: dict[str, Any] = {"child_lists": {}}
        self.visited: set[str] = set()

    def visit(self, identifier: str, depth: int) -> None:
        if identifier in self.visited or depth > 20 or len(self.visited) >= 2000:
            raise NotionImportError(422, "unsupported_structure", "Source nesting is cyclic or exceeds prototype limits; no partial import was saved.")
        self.visited.add(identifier)

    async def children(self, identifier: str) -> list[dict[str, Any]]:
        blocks = await self.notion.children(identifier)
        self.snapshot["child_lists"][identifier] = blocks
        return blocks

    async def discover(self, identifier: str, depth: int = 0) -> list[dict[str, Any]]:
        self.visit(identifier, depth)
        meetings = []
        for block in await self.children(identifier):
            kind = block.get("type")
            if kind == "meeting_notes":
                meetings.append(block)
            elif kind == "unsupported":
                raise NotionImportError(422, "unsupported_structure", "The page contains an unsupported block; native discovery may be incomplete.")
            elif block.get("has_children") is True and kind not in ("child_page", "child_database"):
                meetings.extend(await self.discover(block_id(block.get("id")), depth + 1))
        return meetings

    async def extract(self, block: dict[str, Any], depth: int = 0) -> list[TranscriptSegment]:
        identifier = block_id(block.get("id"))
        self.visit(identifier, depth)
        kind = block.get("type")
        text_types = {"paragraph", "quote", "bulleted_list_item", "numbered_list_item", "to_do", "toggle", "callout"}
        container_types = {"column", "column_list", "synced_block"}
        if kind not in text_types | container_types:
            raise NotionImportError(422, "unsupported_structure", "Transcript block type is unsupported; no partial import was saved.")
        body = block.get(kind)
        if not isinstance(body, dict):
            raise NotionImportError(422, "unsupported_structure", "Transcript block content is missing.")
        segments = []
        if kind in text_types:
            text = plain_text(body.get("rich_text"))
            if text:
                segments.append(TranscriptSegment(block_id=identifier, text=text))
        if block.get("has_children") is True:
            for child in await self.children(identifier):
                segments.extend(await self.extract(child, depth + 1))
        return segments


async def import_native_transcript(notion: NotionClient, path: Path, page_id: str, api_version: str) -> NotionImportResponse:
    reader = NativeTranscriptReader(notion)
    page = await notion.get(f"/pages/{page_id}")
    if page.get("object") != "page" or block_id(page.get("id")) != page_id:
        raise NotionImportError(502, "unsupported_structure", "Notion returned unexpected page metadata.")
    reader.snapshot["page"] = page
    meetings = await reader.discover(page_id)
    if not meetings:
        raise NotionImportError(422, "native_meeting_missing", "No native Meeting Notes block was found. Ordinary transcript pages are not supported.")
    if len(meetings) != 1:
        raise NotionImportError(422, "ambiguous_meeting", "This page contains multiple Meeting Notes blocks. Use a page containing one meeting.")
    meeting = meetings[0]
    metadata = meeting.get("meeting_notes")
    if not isinstance(metadata, dict):
        raise NotionImportError(422, "unsupported_structure", "Native Meeting Notes metadata is missing.")
    children = metadata.get("children")
    reference = children.get("transcript_block_id") if isinstance(children, dict) else None
    if not reference:
        raise NotionImportError(422, "transcript_reference_missing", "The native meeting has no transcript reference. Finish transcription and check the transcript in Notion.")
    if metadata.get("status") != "notes_ready":
        raise NotionImportError(409, "transcript_not_ready", "The native meeting is not marked notes_ready. Wait for processing to finish in Notion.")
    transcript_root = await notion.block(block_id(reference))
    reader.snapshot["transcript_root"] = transcript_root
    discovery_ids = set(reader.visited)
    segments = await reader.extract(transcript_root)
    original_text = "\n".join(segment.text for segment in segments)
    if not original_text.strip():
        raise NotionImportError(422, "empty_transcript", "The native transcript is empty; no import was saved.")
    warnings = [
        "Native retrieval has not been independently compared with the full Notion UI transcript.",
        "Speaker attribution and conversation turn boundaries are unavailable to this parser; text blocks are segments, not turns.",
        "Per-turn timestamps are unavailable to this parser. Raw source fields are preserved without interpretation.",
    ]
    source_metadata = {
        "source_kind": "native_meeting_notes", "api_version": api_version,
        "meeting_block_id": block_id(meeting.get("id")),
        "meeting_metadata": metadata, "snapshot": reader.snapshot,
        "segments": [segment.model_dump() for segment in segments],
    }
    # Hash content-bearing source blocks, excluding edit times and fetch time.
    # Unknown provider fields in the transcript payload remain part of the fingerprint.
    def content(block: dict[str, Any]) -> dict[str, Any]:
        audit_fields = {"created_time", "last_edited_time", "created_by", "last_edited_by", "request_id"}
        return {key: value for key, value in block.items() if key not in audit_fields}

    transcript_ids = reader.visited - discovery_ids
    source_content = {
        "meeting_block_id": source_metadata["meeting_block_id"],
        "root": content(transcript_root),
        "children": {key: [content(item) for item in value] for key, value in reader.snapshot["child_lists"].items()
                     if key in transcript_ids and key != page_id},
        "text": original_text,
    }
    digest = hashlib.sha256(json.dumps(source_content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    title = plain_text(metadata.get("title", [])) or "Untitled native meeting"
    now = datetime.now(timezone.utc).isoformat()
    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO conversations (id, provider, source_id, title, source_url, created_at) VALUES (?, 'notion', ?, ?, ?, ?) ON CONFLICT(provider, source_id) DO NOTHING",
            (str(uuid4()), page_id, title, f"https://www.notion.so/{page_id.replace('-', '')}", now),
        )
        conversation_row = connection.execute("SELECT * FROM conversations WHERE provider = 'notion' AND source_id = ?", (page_id,)).fetchone()
        conversation = Conversation(**dict(conversation_row))
        existing = connection.execute("SELECT * FROM transcript_versions WHERE conversation_id = ? AND content_hash = ?", (conversation.id, digest)).fetchone()
        reused = existing is not None
        if not reused:
            connection.execute(
                "INSERT INTO transcript_versions (id, conversation_id, content_hash, original_text, source_metadata, turns, warnings, imported_at) VALUES (?, ?, ?, ?, ?, '[]', ?, ?)",
                (str(uuid4()), conversation.id, digest, original_text, json.dumps(source_metadata, ensure_ascii=False), json.dumps(warnings), now),
            )
            existing = connection.execute("SELECT * FROM transcript_versions WHERE conversation_id = ? AND content_hash = ?", (conversation.id, digest)).fetchone()
        record = dict(existing)
        for name in ("source_metadata", "turns", "warnings"):
            record[name] = json.loads(record[name])
        transcript = TranscriptVersion(**record)
    return NotionImportResponse(conversation=conversation, transcript=transcript, reused=reused, segments=segments)
